"""Opt-in local Ollama agent runner for the auto-apply workflow.

The runner deliberately has no dependency on the rest of the apply pipeline.  It
starts the MCP servers described by ``launcher._make_mcp_config``, exposes their
tools to Ollama's OpenAI-compatible API, and forwards tool calls back over MCP
stdio.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from typing import Any

import httpx


DEFAULT_OLLAMA_BASE_URL = "http://127.0.0.1:11434"
DEFAULT_OLLAMA_MODEL = "llama3.1"
MCP_PROTOCOL_VERSION = "2024-11-05"
DEFAULT_BROWSER_TOOLS = {
    "browser_click",
    "browser_file_upload",
    "browser_fill_form",
    "browser_handle_dialog",
    "browser_navigate",
    "browser_navigate_back",
    "browser_press_key",
    "browser_select_option",
    "browser_snapshot",
    "browser_tabs",
    "browser_type",
    "browser_wait_for",
}


class OllamaAgentError(RuntimeError):
    """Raised when an Ollama request or MCP operation fails."""


@dataclass
class _MCPServer:
    name: str
    process: subprocess.Popen[str]


class OllamaAgentRunner:
    """Run a tool-using chat loop against a local Ollama instance.

    Args:
        mcp_config: An ``mcpServers`` configuration, normally obtained from
            :func:`applypilot.apply.launcher._make_mcp_config`.
        model: Ollama model name.  Defaults to ``OLLAMA_MODEL``.
        base_url: Ollama OpenAI-compatible base URL.  Defaults to
            ``OLLAMA_BASE_URL`` or localhost.
    """

    def __init__(
        self,
        mcp_config: dict[str, Any],
        *,
        model: str | None = None,
        base_url: str | None = None,
        timeout: float = 120.0,
        api_key: str | None = None,
    ) -> None:
        self._config = mcp_config.get("mcpServers", mcp_config)
        if not isinstance(self._config, dict):
            raise ValueError("mcp_config must contain an mcpServers object")
        self.model = model or os.environ.get("OLLAMA_MODEL", DEFAULT_OLLAMA_MODEL)
        self.base_url = (base_url or os.environ.get("OLLAMA_BASE_URL", DEFAULT_OLLAMA_BASE_URL)).rstrip("/")
        if self.base_url.endswith("/v1"):
            self.base_url = self.base_url[:-3].rstrip("/")
        configured_timeout = (
            os.environ.get("OLLAMA_TIMEOUT")
            or os.environ.get("LLM_TIMEOUT")
        )
        self.timeout = float(configured_timeout) if configured_timeout else timeout
        self.think = os.environ.get("OLLAMA_THINK", "false").lower() in {"1", "true", "yes"}
        configured_max_tokens = os.environ.get("OLLAMA_MAX_TOKENS")
        self.max_tokens = int(configured_max_tokens) if configured_max_tokens else 2048
        configured_context = os.environ.get("OLLAMA_CONTEXT_LENGTH")
        self.context_length = int(configured_context) if configured_context else 16384
        self.all_tools = os.environ.get("OLLAMA_ALL_TOOLS", "false").lower() in {"1", "true", "yes"}
        self.api_key = api_key or os.environ.get("OLLAMA_API_KEY")
        self._servers: dict[str, _MCPServer] = {}
        self._next_id = 0

    @classmethod
    def for_cdp_port(cls, cdp_port: int, **kwargs: Any) -> "OllamaAgentRunner":
        """Build a runner from the existing auto-apply MCP configuration."""
        from .launcher import _make_mcp_config

        mcp_config = _make_mcp_config(cdp_port)
        # Gmail is not needed to fill browser applications. It also requires
        # a separate OAuth setup and can block local agents during startup.
        mcp_config["mcpServers"].pop("gmail", None)
        return cls(mcp_config, **kwargs)

    def __enter__(self) -> "OllamaAgentRunner":
        self.start()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def start(self) -> None:
        """Start and initialize every configured MCP server."""
        if self._servers:
            return
        try:
            for name, raw in self._config.items():
                if not isinstance(raw, dict) or not raw.get("command"):
                    raise OllamaAgentError(f"Invalid MCP configuration for server {name!r}")
                command = str(raw["command"])
                if os.name == "nt" and command == "npx":
                    command = shutil.which("npx") or shutil.which("npx.cmd") or command
                argv = [command, *[str(arg) for arg in raw.get("args", [])]]
                process = subprocess.Popen(
                    argv,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    encoding="utf-8",
                    bufsize=1,
                )
                self._servers[name] = _MCPServer(name, process)
                self._request(name, "initialize", {
                    "protocolVersion": MCP_PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {"name": "applypilot-ollama-agent", "version": "1.0"},
                })
                self._notify(name, "notifications/initialized", {})
        except Exception:
            self.close()
            raise

    def close(self) -> None:
        """Terminate all MCP children, including children that outlive SIGTERM."""
        servers = list(self._servers.values())
        self._servers.clear()
        for server in servers:
            process = server.process
            if process.stdin:
                process.stdin.close()
            if process.poll() is None:
                process.terminate()
        for server in servers:
            process = server.process
            if process.poll() is None:
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()

    def _request(self, server_name: str, method: str, params: dict[str, Any]) -> dict[str, Any]:
        server = self._servers[server_name]
        if server.process.stdin is None or server.process.stdout is None:
            raise OllamaAgentError(f"MCP server {server_name!r} has no stdio pipes")
        self._next_id += 1
        request_id = self._next_id
        message = {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}
        server.process.stdin.write(json.dumps(message) + "\n")
        server.process.stdin.flush()
        while True:
            line = server.process.stdout.readline()
            if not line:
                raise OllamaAgentError(f"MCP server {server_name!r} exited while handling {method}")
            try:
                response = json.loads(line)
            except json.JSONDecodeError:
                continue
            if "id" not in response:
                continue
            if response["id"] != request_id:
                continue
            if "error" in response:
                raise OllamaAgentError(f"MCP {method} failed on {server_name}: {response['error']}")
            return response.get("result", {})

    def _notify(self, server_name: str, method: str, params: dict[str, Any]) -> None:
        server = self._servers[server_name]
        if server.process.stdin is None:
            raise OllamaAgentError(f"MCP server {server_name!r} has no stdin")
        server.process.stdin.write(
            json.dumps({"jsonrpc": "2.0", "method": method, "params": params}) + "\n"
        )
        server.process.stdin.flush()

    def _list_tools(self) -> tuple[list[dict[str, Any]], dict[str, tuple[str, str]]]:
        tools: list[dict[str, Any]] = []
        mapping: dict[str, tuple[str, str]] = {}
        for server_name in self._servers:
            result = self._request(server_name, "tools/list", {})
            for tool in result.get("tools", []):
                original_name = str(tool["name"])
                if (
                    server_name == "playwright"
                    and not self.all_tools
                    and original_name not in DEFAULT_BROWSER_TOOLS
                ):
                    continue
                ollama_name = f"{server_name}__{original_name}"
                mapping[ollama_name] = (server_name, original_name)
                tools.append({
                    "type": "function",
                    "function": {
                        "name": ollama_name,
                        "description": tool.get("description", ""),
                        "parameters": tool.get("inputSchema", {"type": "object", "properties": {}}),
                    },
                })
        return tools, mapping

    def _call_tool(self, server_name: str, tool_name: str, arguments: Any) -> str:
        if isinstance(arguments, dict):
            parsed_arguments = arguments
        else:
            try:
                parsed_arguments = json.loads(arguments) if arguments else {}
            except (TypeError, json.JSONDecodeError) as exc:
                return json.dumps({"error": f"Invalid tool arguments: {exc}"})
        result = self._request(server_name, "tools/call", {"name": tool_name, "arguments": parsed_arguments})
        return json.dumps(result, ensure_ascii=False)

    def run(
        self,
        prompt: str,
        *,
        system_prompt: str | None = None,
        max_turns: int = 40,
        temperature: float = 0.0,
        max_tokens: int | None = None,
        initial_url: str | None = None,
    ) -> str:
        """Run until Ollama emits a final assistant message without tool calls."""
        self.start()
        try:
            tools, mapping = self._list_tools()
            if initial_url:
                navigate_name = next(
                    (name for name, pair in mapping.items() if pair == ("playwright", "browser_navigate")),
                    None,
                )
                if not navigate_name:
                    raise OllamaAgentError("Playwright browser_navigate tool is unavailable")
                self._call_tool("playwright", "browser_navigate", {"url": initial_url})
            messages: list[dict[str, Any]] = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": prompt})
            headers = {"Content-Type": "application/json"}
            if self.api_key:
                headers["Authorization"] = "Bearer " + self.api_key
            with httpx.Client(timeout=self.timeout) as client:
                for _ in range(max_turns):
                    try:
                        response = client.post(
                            f"{self.base_url}/api/chat",
                            headers=headers,
                            json={
                                "model": self.model,
                                "messages": messages,
                                "tools": tools,
                                "tool_choice": "auto",
                                "temperature": temperature,
                                "options": {
                                    "num_ctx": self.context_length,
                                    "num_predict": max_tokens or self.max_tokens,
                                },
                                "think": self.think,
                                "stream": False,
                            },
                        )
                    except httpx.TimeoutException as exc:
                        raise OllamaAgentError(
                            f"Ollama timed out after {self.timeout:g}s while "
                            f"generating with model {self.model!r}; "
                            "try a smaller model such as qwen3:8b or increase "
                            "OLLAMA_TIMEOUT"
                        ) from exc
                    response.raise_for_status()
                    assistant = response.json().get("message", {})
                    if not assistant:
                        raise OllamaAgentError("Ollama returned no message")
                    tool_calls = assistant.get("tool_calls") or []
                    messages.append(assistant)
                    if not tool_calls:
                        return assistant.get("content") or ""
                    for tool_call in tool_calls:
                        function = tool_call.get("function", {})
                        ollama_name = function.get("name", "")
                        if ollama_name not in mapping:
                            content = json.dumps({"error": f"Unknown tool {ollama_name!r}"})
                        else:
                            server_name, tool_name = mapping[ollama_name]
                            content = self._call_tool(server_name, tool_name, function.get("arguments", "{}"))
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tool_call.get("id", ""),
                            "content": content,
                        })
            raise OllamaAgentError(f"Ollama exceeded max_turns={max_turns}")
        finally:
            self.close()


def run_ollama_agent(
    prompt: str,
    cdp_port: int,
    *,
    initial_url: str | None = None,
    **kwargs: Any,
) -> str:
    """Convenience wrapper for one auto-apply run with deterministic cleanup."""
    with OllamaAgentRunner.for_cdp_port(cdp_port, **kwargs) as runner:
        return runner.run(prompt, initial_url=initial_url)


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="Run an ApplyPilot Ollama MCP agent")
    parser.add_argument("--cdp-port", type=int, required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--url", required=True)
    args = parser.parse_args()
    try:
        result = run_ollama_agent(
            sys.stdin.read(),
            args.cdp_port,
            model=args.model,
            initial_url=args.url,
        )
        print(json.dumps({"type": "result", "result": result, "usage": {}}), flush=True)
    except Exception as exc:
        print(json.dumps({"type": "result", "is_error": True, "result": str(exc)}), flush=True)
        raise
