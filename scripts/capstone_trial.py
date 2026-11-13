"""Capstone trial runner: run the instrumented score stage N times and measure it.

Each trial:
  1. restores the database copy in --home from applypilot.snapshot.db (if present),
     so every trial scores the same jobs;
  2. runs ``python -m applypilot run score --limit JOBS --rescore`` with
     APPLYPILOT_DIR=--home and a fresh run log file for the trial;
  3. reads that run log back and reports the numbers the acceptance criteria in
     criteria.md are judged on.

Usage:
  python scripts/capstone_trial.py --home PATH [--trials 3] [--jobs 10]
                                   [--label before] [--fail-mode timeout|badmodel]
                                   [--latency-ms 6000] [--pending]

--pending scores jobs that have no fit_score yet (no --rescore), and afterwards
checks how many of them are still pending in the database, i.e. retryable.

--fail-mode breaks the LLM provider on purpose so the error path can be tested:
  timeout   LLM_TIMEOUT=0.2  (every call is killed before it can answer)
  badmodel  LLM_MODEL=no-such-model  (the provider rejects every call)
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import statistics
import subprocess
import sys
import time
from pathlib import Path

REQUIRED_FIELDS = ("ts", "run_id", "event", "status", "duration_ms", "stage", "job_url", "model")
REQUIRED_OK_FIELDS = ("cost_usd", "input_tokens", "output_tokens")


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            out.append({"_malformed": line[:80]})
    return out


def run_trial(home: Path, k: int, jobs: int, label: str, fail_mode: str | None,
              latency_ms: int, pending: bool = False) -> dict:
    snapshot = home / "applypilot.snapshot.db"
    if snapshot.exists():
        shutil.copyfile(snapshot, home / "applypilot.db")

    log_dir = home / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    run_log = log_dir / f"trial-{label}-{k}.jsonl"
    out_file = log_dir / f"trial-{label}-{k}.out.txt"
    if run_log.exists():
        run_log.unlink()

    env = os.environ.copy()
    env["APPLYPILOT_DIR"] = str(home)
    env["APPLYPILOT_RUN_LOG"] = str(run_log)
    env["PYTHONIOENCODING"] = "utf-8"
    if fail_mode == "timeout":
        env["LLM_TIMEOUT"] = "0.2"
    elif fail_mode == "badmodel":
        env["LLM_MODEL"] = "no-such-model"

    cmd = [sys.executable, "-m", "applypilot", "run", "score", "--limit", str(jobs)]
    if not pending:
        cmd.append("--rescore")
    t0 = time.perf_counter()
    proc = subprocess.run(cmd, env=env, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    wall_s = time.perf_counter() - t0
    out_file.write_text(f"$ {' '.join(cmd)}\nexit={proc.returncode}\n--- stdout ---\n"
                        f"{proc.stdout}\n--- stderr ---\n{proc.stderr}", encoding="utf-8")

    recs = read_jsonl(run_log)
    malformed = [r for r in recs if "_malformed" in r]
    calls = [r for r in recs if r.get("event") == "llm_call"]
    scored = [r for r in recs if r.get("event") == "job_scored"]
    ok_calls = [r for r in calls if r.get("status") == "ok"]
    err_calls = [r for r in calls if r.get("status") != "ok"]

    def complete(r: dict) -> bool:
        if any(r.get(f) in (None, "") for f in REQUIRED_FIELDS):
            return False
        if r.get("status") == "ok" and r.get("event") == "llm_call":
            return all(r.get(f) is not None for f in REQUIRED_OK_FIELDS)
        if r.get("status") != "ok":
            return bool(r.get("error"))
        return True

    durations = [r["duration_ms"] for r in calls if r.get("duration_ms") is not None]
    costs = [r["cost_usd"] for r in ok_calls if r.get("cost_usd") is not None]
    crashed = "Traceback" in proc.stderr or "STAGE FAILED" in proc.stdout
    stage_completed = "Stage 'score' completed" in proc.stdout

    # Criterion 4: are the jobs this run touched still retryable (fit_score NULL)?
    still_pending = None
    if scored:
        conn = sqlite3.connect(home / "applypilot.db")
        urls = [r.get("job_url") for r in scored if r.get("job_url")]
        still_pending = sum(
            1 for u in urls
            if conn.execute("SELECT fit_score IS NULL FROM jobs WHERE url = ?", (u,)).fetchone()[0]
        )
        conn.close()

    return {
        "trial": k,
        "label": label,
        "fail_mode": fail_mode,
        "exit_code": proc.returncode,
        "wall_s": round(wall_s, 1),
        "jobs_requested": jobs,
        "llm_call_records": len(calls),
        "job_scored_records": len(scored),
        "malformed_lines": len(malformed),
        "records_complete": sum(complete(r) for r in calls + scored),
        "records_total": len(calls) + len(scored),
        "ok_calls": len(ok_calls),
        "error_calls": len(err_calls),
        "errors_with_message": sum(1 for r in err_calls if r.get("error")),
        "jobs_error_with_message": sum(1 for r in scored if r.get("status") != "ok" and r.get("error")),
        "stage_crashed": crashed,
        "stage_completed": stage_completed,
        "jobs_still_pending_after_run": still_pending,
        f"calls_under_{latency_ms}ms": sum(1 for d in durations if d < latency_ms),
        "duration_ms_mean": round(statistics.mean(durations)) if durations else None,
        "duration_ms_max": max(durations) if durations else None,
        "cost_usd_mean": round(statistics.mean(costs), 5) if costs else None,
        "cost_usd_total": round(sum(costs), 4) if costs else None,
        "scores": [r.get("score") for r in scored],
        "run_log": str(run_log),
        "output": str(out_file),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--home", required=True, type=Path, help="APPLYPILOT_DIR to run against (an isolated copy).")
    ap.add_argument("--trials", type=int, default=3)
    ap.add_argument("--jobs", type=int, default=10)
    ap.add_argument("--label", default="before")
    ap.add_argument("--fail-mode", choices=("timeout", "badmodel"), default=None)
    ap.add_argument("--latency-ms", type=int, default=6000)
    ap.add_argument("--pending", action="store_true",
                    help="Score unscored jobs (omit --rescore) and report how many stay pending afterwards.")
    args = ap.parse_args()

    results = []
    for k in range(1, args.trials + 1):
        print(f"--- trial {k}/{args.trials} ({args.label}{', ' + args.fail_mode if args.fail_mode else ''}) ---",
              flush=True)
        r = run_trial(args.home.resolve(), k, args.jobs, args.label, args.fail_mode,
                      args.latency_ms, pending=args.pending)
        results.append(r)
        print(json.dumps(r, indent=2), flush=True)

    summary_path = args.home / "logs" / f"trial-{args.label}{'-' + args.fail_mode if args.fail_mode else ''}-summary.json"
    summary_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"\nsummary written to {summary_path}")


if __name__ == "__main__":
    main()
