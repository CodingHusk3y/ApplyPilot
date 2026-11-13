"""Structured run log for ApplyPilot.

Every LLM call and every scored job appends one JSON record (one line) to
``~/.applypilot/logs/runs.jsonl``. Override the path with ``APPLYPILOT_RUN_LOG``.

A record always carries:

    ts           ISO-8601 UTC timestamp of when the event finished
    run_id       8-char id shared by every record from one process
    event        "llm_call" or "job_scored"
    status       "ok" or "error"
    duration_ms  wall-clock time for the event

plus whatever context the caller set (stage, job_url, job_title) and the
event's own fields (model, tokens, cost_usd, error, ...).

Writing the log must never break the pipeline: every failure inside this
module is swallowed and reported through ``logging`` instead.
"""

from __future__ import annotations

import contextlib
import contextvars
import json
import logging
import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, median

from applypilot import config

log = logging.getLogger(__name__)

# One id per process so records from one `applypilot run` can be grouped.
RUN_ID = uuid.uuid4().hex[:8]

_context: contextvars.ContextVar[dict] = contextvars.ContextVar("telemetry_context", default={})
_lock = threading.Lock()


def log_path() -> Path:
    """Where records are appended."""
    override = os.environ.get("APPLYPILOT_RUN_LOG")
    return Path(override) if override else config.LOG_DIR / "runs.jsonl"


@contextlib.contextmanager
def context(**fields):
    """Attach fields (stage, job_url, ...) to every record written inside the block."""
    merged = {**_context.get(), **{k: v for k, v in fields.items() if v is not None}}
    token = _context.set(merged)
    try:
        yield
    finally:
        _context.reset(token)


def record(event: str, **fields) -> dict:
    """Append one record and return it. Never raises."""
    rec = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        "run_id": RUN_ID,
        "event": event,
        **_context.get(),
        **fields,
    }
    try:
        path = log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(rec, ensure_ascii=False, default=str)
        with _lock:
            with path.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
    except Exception as e:  # noqa: BLE001 - logging must not break the pipeline
        log.warning("telemetry: could not write run log: %s", e)
    return rec


def read_records(path: Path | None = None) -> list[dict]:
    """Read every well-formed record. Malformed lines are skipped, not fatal."""
    path = path or log_path()
    if not path.exists():
        return []
    out: list[dict] = []
    with path.open("r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                log.warning("telemetry: skipping malformed line: %s", line[:80])
    return out


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = max(0, min(len(ordered) - 1, round(pct / 100 * (len(ordered) - 1))))
    return ordered[idx]


def summarize(records: list[dict], event: str = "llm_call") -> dict:
    """Aggregate one event type: counts, error rate, latency, tokens, cost."""
    rows = [r for r in records if r.get("event") == event]
    ok = [r for r in rows if r.get("status") == "ok"]
    durations = [float(r["duration_ms"]) for r in rows if r.get("duration_ms") is not None]
    costs = [float(r["cost_usd"]) for r in ok if r.get("cost_usd") is not None]
    tokens_in = [int(r["input_tokens"]) for r in ok if r.get("input_tokens") is not None]
    tokens_out = [int(r["output_tokens"]) for r in ok if r.get("output_tokens") is not None]
    return {
        "event": event,
        "count": len(rows),
        "ok": len(ok),
        "errors": len(rows) - len(ok),
        "duration_ms_mean": mean(durations) if durations else 0.0,
        "duration_ms_p50": median(durations) if durations else 0.0,
        "duration_ms_p95": _percentile(durations, 95),
        "duration_ms_max": max(durations) if durations else 0.0,
        "cost_usd_total": sum(costs),
        "cost_usd_mean": mean(costs) if costs else None,
        "cost_known": len(costs),
        "input_tokens_mean": mean(tokens_in) if tokens_in else None,
        "output_tokens_mean": mean(tokens_out) if tokens_out else None,
    }
