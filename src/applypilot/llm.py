"""
Unified LLM client for ApplyPilot.

Auto-detects provider from environment:
  LLM_PROVIDER=claude-code -> the logged-in `claude` CLI, billed to your Claude
                    subscription instead of an API key (default model: haiku)
  ANTHROPIC_API_KEY -> Anthropic Claude (default: claude-opus-5-5; needs `pip install anthropic`)
  GEMINI_API_KEY  -> Google Gemini (default: gemini-2.0-flash)
  OPENAI_API_KEY  -> OpenAI (default: gpt-4o-mini)
  LLM_PROVIDER=ollama -> Ollama (default: http://127.0.0.1:11434/v1)
  LLM_URL         -> Local llama.cpp / Ollama compatible endpoint

LLM_MODEL env var overrides the model name for any provider.
LLM_TIMEOUT env var overrides the request timeout in seconds (default 120).
"""

import logging
import os
import time

import httpx

from applypilot import telemetry

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Provider detection
# ---------------------------------------------------------------------------

def _detect_provider() -> tuple[str, str, str]:
    """Return (base_url, model, api_key) based on environment variables.

    Reads env at call time (not module import time) so that load_env() called
    in _bootstrap() is always visible here.
    """
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "")
    gemini_key = os.environ.get("GEMINI_API_KEY", "")
    openai_key = os.environ.get("OPENAI_API_KEY", "")
    local_url = os.environ.get("LLM_URL", "")
    model_override = os.environ.get("LLM_MODEL", "")
    provider = os.environ.get("LLM_PROVIDER", "").lower()

    # Explicit choice wins over any key or URL that is also set.
    if os.environ.get("LLM_PROVIDER", "").lower() == _CLAUDE_CODE_PROVIDER:
        # Same default as `applypilot apply --model`.
        return (_CLAUDE_CODE_PROVIDER, model_override or "haiku", "")

    if provider == "ollama":
        return (
            local_url.rstrip("/") if local_url else "http://127.0.0.1:11434/v1",
            model_override or os.environ.get("OLLAMA_MODEL", "llama3.1"),
            os.environ.get("LLM_API_KEY", ""),
        )

    if anthropic_key and not local_url:
        return (
            _ANTHROPIC_PROVIDER,
            model_override or "claude-opus-5-5",
            anthropic_key,
        )

    if gemini_key and not local_url:
        return (
            "https://generativelanguage.googleapis.com/v1beta/openai",
            model_override or "gemini-2.0-flash",
            gemini_key,
        )

    if openai_key and not local_url:
        return (
            "https://api.openai.com/v1",
            model_override or "gpt-4o-mini",
            openai_key,
        )

    if local_url:
        return (
            local_url.rstrip("/"),
            model_override or "local-model",
            os.environ.get("LLM_API_KEY", ""),
        )

    raise RuntimeError(
        "No LLM provider configured. "
        "Set ANTHROPIC_API_KEY, GEMINI_API_KEY, OPENAI_API_KEY, or LLM_URL in your environment."
    )


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

_MAX_RETRIES = 5
_TIMEOUT = 120  # seconds

# Base wait on first 429/503 (doubles each retry, caps at 60s).
# Gemini free tier is 15 RPM = 4s minimum between requests; 10s gives headroom.
_RATE_LIMIT_BASE_WAIT = 10


_GEMINI_COMPAT_BASE = "https://generativelanguage.googleapis.com/v1beta/openai"
_GEMINI_NATIVE_BASE = "https://generativelanguage.googleapis.com/v1beta"

# Claude goes through the official SDK, not an HTTP base URL.
_ANTHROPIC_PROVIDER = "anthropic"

# Claude via the `claude` CLI (Claude Code) using the user's subscription login.
_CLAUDE_CODE_PROVIDER = "claude-code"
_CLAUDE_CODE_TIMEOUT = 600  # seconds; overridden by LLM_TIMEOUT
# Windows caps a command line at ~32K chars; longer system prompts go via stdin.
_CLAUDE_CODE_MAX_ARG = 20000

# Claude thinks before answering, and thinking tokens count toward max_tokens.
# Callers size max_tokens for the visible answer only (as low as 512), so
# raise the floor to leave room for both.
_ANTHROPIC_MIN_MAX_TOKENS = 16000

# Models that support the server-side refusal fallback (array form).
_ANTHROPIC_FALLBACK_MODELS = {"claude-opus-5-5", "claude-opus-5", "claude-fable-5-1"}


def _provider_label(base_url: str) -> str:
    """Short provider name for log records."""
    if base_url == _CLAUDE_CODE_PROVIDER:
        return "claude-code"
    if base_url == _ANTHROPIC_PROVIDER:
        return "anthropic"
    if base_url.startswith(_GEMINI_COMPAT_BASE):
        return "gemini"
    if "api.openai.com" in base_url:
        return "openai"
    if "11434" in base_url:
        return "ollama"
    return "local"


class LLMClient:
    """Thin LLM client supporting OpenAI-compatible and native Gemini endpoints.

    For Gemini keys, starts on the OpenAI-compat layer. On a 403 (which
    happens with preview/experimental models not exposed via compat), it
    automatically switches to the native generateContent API and stays there
    for the lifetime of the process.
    """

    def __init__(self, base_url: str, model: str, api_key: str) -> None:
        self.base_url = base_url
        self.model = model
        self.api_key = api_key
        # LLM_TIMEOUT overrides the default; slow local models need longer.
        self._client = httpx.Client(timeout=float(os.environ.get("LLM_TIMEOUT") or _TIMEOUT))
        # True once we've confirmed the native Gemini API works for this model
        self._use_native_gemini: bool = False
        self._is_gemini: bool = base_url.startswith(_GEMINI_COMPAT_BASE)
        self._is_anthropic: bool = base_url == _ANTHROPIC_PROVIDER
        self._anthropic = None  # created lazily so the SDK stays optional
        self._is_claude_code: bool = base_url == _CLAUDE_CODE_PROVIDER
        self.provider: str = _provider_label(base_url)

    # -- Claude Code CLI ----------------------------------------------------

    def _chat_claude_code(self, messages: list[dict]) -> tuple[str, dict]:
        """Run one prompt through `claude -p` with all tools disabled.

        Uses whatever account the CLI is logged into, so it works with a
        Claude Pro/Max/Team/Enterprise plan and no API key. Usage counts
        against that plan's limits.
        """
        import json
        import shutil
        import subprocess

        claude = shutil.which("claude")
        if not claude:
            raise RuntimeError(
                "LLM_PROVIDER=claude-code but the `claude` CLI was not found on PATH."
            )

        system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
        convo = [m for m in messages if m["role"] in ("user", "assistant")]
        if len(convo) == 1:
            prompt = convo[0]["content"]
        else:
            prompt = "\n\n".join(f"[{m['role'].upper()}]\n{m['content']}" for m in convo)

        cmd = [
            claude, "-p",
            "--model", self.model,
            "--tools", "",
            "--output-format", "json",
            "--no-session-persistence",
            "--disable-slash-commands",
            "--strict-mcp-config",
        ]
        if system and len(system) <= _CLAUDE_CODE_MAX_ARG:
            cmd += ["--system-prompt", system]
        elif system:
            prompt = f"<instructions>\n{system}\n</instructions>\n\n{prompt}"

        # Allow running from inside a Claude Code terminal (nested sessions).
        env = os.environ.copy()
        env.pop("CLAUDECODE", None)
        env.pop("CLAUDE_CODE_ENTRYPOINT", None)
        # The CLI enables extended thinking by default, which made a resume
        # rewrite take ~14k tokens and ~2 min instead of ~800 tokens and ~9s.
        # Set MAX_THINKING_TOKENS yourself to turn it back on.
        env.setdefault("MAX_THINKING_TOKENS", "0")

        timeout = float(os.environ.get("LLM_TIMEOUT") or _CLAUDE_CODE_TIMEOUT)
        t0 = time.time()
        proc = subprocess.run(
            cmd, input=prompt, capture_output=True, text=True,
            encoding="utf-8", errors="replace", env=env, timeout=timeout,
        )
        log.info("claude CLI (%s): exit %d in %.1fs", self.model, proc.returncode, time.time() - t0)
        try:
            data = json.loads(proc.stdout)
        except json.JSONDecodeError:
            raise RuntimeError(
                f"claude CLI failed (exit {proc.returncode}): "
                f"{(proc.stderr or proc.stdout).strip()[:300]}"
            )
        if data.get("is_error"):
            raise RuntimeError(f"claude CLI error: {str(data.get('result'))[:300]}")
        u = data.get("usage") or {}
        usage = {
            "input_tokens": u.get("input_tokens"),
            "output_tokens": u.get("output_tokens"),
            "cache_read_tokens": u.get("cache_read_input_tokens"),
            "cache_write_tokens": u.get("cache_creation_input_tokens"),
            # Reported by the CLI itself, so this is a measured number.
            "cost_usd": data.get("total_cost_usd"),
            "provider_duration_ms": data.get("duration_api_ms"),
        }
        return data.get("result", ""), usage

    # -- Anthropic Claude API -----------------------------------------------

    def _chat_anthropic(self, messages: list[dict], max_tokens: int) -> tuple[str, dict]:
        """Call Claude via the official Anthropic SDK.

        System messages are moved to the top-level `system` field. Temperature
        is not sent: current Claude models reject sampling parameters. The SDK
        retries 429/5xx and connection errors itself.
        """
        if self._anthropic is None:
            try:
                import anthropic
            except ImportError as e:
                raise RuntimeError(
                    "ANTHROPIC_API_KEY is set but the Anthropic SDK is not installed. "
                    "Run: pip install anthropic"
                ) from e
            timeout = os.environ.get("LLM_TIMEOUT")
            self._anthropic = anthropic.Anthropic(
                api_key=self.api_key,
                max_retries=_MAX_RETRIES,
                **({"timeout": float(timeout)} if timeout else {}),
            )

        system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
        convo = [
            {"role": m["role"], "content": m["content"]}
            for m in messages if m["role"] in ("user", "assistant")
        ]
        kwargs: dict = {
            "model": self.model,
            "max_tokens": max(max_tokens, _ANTHROPIC_MIN_MAX_TOKENS),
            "messages": convo,
        }
        if system:
            kwargs["system"] = system

        if self.model in _ANTHROPIC_FALLBACK_MODELS:
            # If a safety classifier declines, re-run on another model in the same call.
            response = self._anthropic.beta.messages.create(
                betas=["server-side-fallback-2026-06-01"],
                fallbacks=[{"model": "claude-opus-4-8"}],
                **kwargs,
            )
        else:
            response = self._anthropic.messages.create(**kwargs)

        if response.stop_reason == "refusal":
            raise RuntimeError(f"Claude declined the request (model {self.model})")
        ru = response.usage
        usage = {
            "input_tokens": getattr(ru, "input_tokens", None),
            "output_tokens": getattr(ru, "output_tokens", None),
            "cache_read_tokens": getattr(ru, "cache_read_input_tokens", None),
            "cache_write_tokens": getattr(ru, "cache_creation_input_tokens", None),
        }
        return "".join(b.text for b in response.content if b.type == "text"), usage

    # -- Native Gemini API --------------------------------------------------

    def _chat_native_gemini(
        self,
        messages: list[dict],
        temperature: float,
        max_tokens: int,
    ) -> tuple[str, dict]:
        """Call the native Gemini generateContent API.

        Used automatically when the OpenAI-compat endpoint returns 403,
        which happens for preview/experimental models not exposed via compat.

        Converts OpenAI-style messages to Gemini's contents/systemInstruction
        format transparently.
        """
        contents: list[dict] = []
        system_parts: list[dict] = []

        for msg in messages:
            role = msg["role"]
            text = msg.get("content", "")
            if role == "system":
                system_parts.append({"text": text})
            elif role == "user":
                contents.append({"role": "user", "parts": [{"text": text}]})
            elif role == "assistant":
                # Gemini uses "model" instead of "assistant"
                contents.append({"role": "model", "parts": [{"text": text}]})

        payload: dict = {
            "contents": contents,
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_tokens,
            },
        }
        if system_parts:
            payload["systemInstruction"] = {"parts": system_parts}

        url = f"{_GEMINI_NATIVE_BASE}/models/{self.model}:generateContent"
        resp = self._client.post(
            url,
            json=payload,
            headers={"Content-Type": "application/json"},
            params={"key": self.api_key},
        )
        resp.raise_for_status()
        data = resp.json()
        meta = data.get("usageMetadata") or {}
        usage = {
            "input_tokens": meta.get("promptTokenCount"),
            "output_tokens": meta.get("candidatesTokenCount"),
        }
        return data["candidates"][0]["content"]["parts"][0]["text"], usage

    # -- OpenAI-compat API --------------------------------------------------

    def _chat_compat(
        self,
        messages: list[dict],
        temperature: float,
        max_tokens: int,
    ) -> tuple[str, dict]:
        """Call the OpenAI-compatible endpoint."""
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        resp = self._client.post(
            f"{self.base_url}/chat/completions",
            json=payload,
            headers=headers,
        )

        # 403 on Gemini compat = model not available on compat layer.
        # Raise a specific sentinel so chat() can switch to native API.
        if resp.status_code == 403 and self._is_gemini:
            raise _GeminiCompatForbidden(resp)

        return self._handle_compat_response(resp)

    @staticmethod
    def _handle_compat_response(resp: httpx.Response) -> tuple[str, dict]:
        resp.raise_for_status()
        data = resp.json()
        u = data.get("usage") or {}
        usage = {
            "input_tokens": u.get("prompt_tokens"),
            "output_tokens": u.get("completion_tokens"),
        }
        return data["choices"][0]["message"]["content"], usage

    # -- public API ---------------------------------------------------------

    def chat(
        self,
        messages: list[dict],
        temperature: float = 0.0,
        max_tokens: int = 4096,
    ) -> str:
        """Send a chat completion request and return the assistant message text.

        Every call, successful or not, appends one ``llm_call`` record to the
        structured run log (see :mod:`applypilot.telemetry`) with the model,
        wall-clock duration, token counts and, where the provider reports it,
        the dollar cost.
        """
        t0 = time.perf_counter()
        input_chars = sum(len(m.get("content") or "") for m in messages)
        try:
            text, usage = self._chat_raw(messages, temperature, max_tokens)
        except Exception as e:
            telemetry.record(
                "llm_call",
                status="error",
                provider=self.provider,
                model=self.model,
                input_chars=input_chars,
                output_chars=0,
                duration_ms=round((time.perf_counter() - t0) * 1000),
                error=f"{type(e).__name__}: {str(e)[:300]}",
            )
            raise
        telemetry.record(
            "llm_call",
            status="ok",
            provider=self.provider,
            model=self.model,
            input_chars=input_chars,
            output_chars=len(text or ""),
            duration_ms=round((time.perf_counter() - t0) * 1000),
            **{k: v for k, v in (usage or {}).items() if v is not None},
        )
        return text

    def _chat_raw(
        self,
        messages: list[dict],
        temperature: float,
        max_tokens: int,
    ) -> tuple[str, dict]:
        """Provider dispatch. Returns (assistant text, usage dict)."""
        # Qwen3 optimization: prepend /no_think to skip chain-of-thought
        # reasoning, saving tokens on structured extraction tasks.
        if "qwen" in self.model.lower() and messages:
            first = messages[0]
            if first.get("role") == "user" and not first["content"].startswith("/no_think"):
                messages = [{"role": first["role"], "content": f"/no_think\n{first['content']}"}] + messages[1:]

        if self._is_claude_code:
            return self._chat_claude_code(messages)
        if self._is_anthropic:
            return self._chat_anthropic(messages, max_tokens)

        for attempt in range(_MAX_RETRIES):
            try:
                # Route to native Gemini if we've already confirmed it's needed
                if self._use_native_gemini:
                    return self._chat_native_gemini(messages, temperature, max_tokens)

                return self._chat_compat(messages, temperature, max_tokens)

            except _GeminiCompatForbidden as exc:
                # Model not available on OpenAI-compat layer — switch to native.
                log.warning(
                    "Gemini compat endpoint returned 403 for model '%s'. "
                    "Switching to native generateContent API. "
                    "(Preview/experimental models are often compat-only on native.)",
                    self.model,
                )
                self._use_native_gemini = True
                # Retry immediately with native — don't count as a rate-limit wait
                try:
                    return self._chat_native_gemini(messages, temperature, max_tokens)
                except httpx.HTTPStatusError as native_exc:
                    raise RuntimeError(
                        f"Both Gemini endpoints failed. Compat: 403 Forbidden. "
                        f"Native: {native_exc.response.status_code} — "
                        f"{native_exc.response.text[:200]}"
                    ) from native_exc

            except httpx.HTTPStatusError as exc:
                resp = exc.response
                if resp.status_code in (429, 503) and attempt < _MAX_RETRIES - 1:
                    # Respect Retry-After header if provided (Gemini sends this).
                    retry_after = (
                        resp.headers.get("Retry-After")
                        or resp.headers.get("X-RateLimit-Reset-Requests")
                    )
                    if retry_after:
                        try:
                            wait = float(retry_after)
                        except (ValueError, TypeError):
                            wait = _RATE_LIMIT_BASE_WAIT * (2 ** attempt)
                    else:
                        wait = min(_RATE_LIMIT_BASE_WAIT * (2 ** attempt), 60)

                    log.warning(
                        "LLM rate limited (HTTP %s). Waiting %ds before retry %d/%d. "
                        "Tip: Gemini free tier = 15 RPM. Consider a paid account "
                        "or switching to a local model.",
                        resp.status_code, wait, attempt + 1, _MAX_RETRIES,
                    )
                    time.sleep(wait)
                    continue
                raise

            except httpx.TimeoutException:
                if attempt < _MAX_RETRIES - 1:
                    wait = min(_RATE_LIMIT_BASE_WAIT * (2 ** attempt), 60)
                    log.warning(
                        "LLM request timed out, retrying in %ds (attempt %d/%d)",
                        wait, attempt + 1, _MAX_RETRIES,
                    )
                    time.sleep(wait)
                    continue
                raise

        raise RuntimeError("LLM request failed after all retries")

    def ask(self, prompt: str, **kwargs) -> str:
        """Convenience: single user prompt -> assistant response."""
        return self.chat([{"role": "user", "content": prompt}], **kwargs)

    def close(self) -> None:
        self._client.close()


class _GeminiCompatForbidden(Exception):
    """Sentinel: Gemini OpenAI-compat returned 403. Switch to native API."""
    def __init__(self, response: httpx.Response) -> None:
        self.response = response
        super().__init__(f"Gemini compat 403: {response.text[:200]}")


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_instance: LLMClient | None = None


def get_client() -> LLMClient:
    """Return (or create) the module-level LLMClient singleton."""
    global _instance
    if _instance is None:
        base_url, model, api_key = _detect_provider()
        log.info("LLM provider: %s  model: %s", base_url, model)
        _instance = LLMClient(base_url, model, api_key)
    return _instance
