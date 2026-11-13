# Running ApplyPilot's instrumented score stage (Capstone, Path B: local with logs)

This is the run path for the capstone extension: the `score` stage with the
structured run log around it. It runs on your machine from one command and leaves
a record of every run in `logs/runs.jsonl` under the data directory.

## What the environment needs

| Thing | Version used | Notes |
|---|---|---|
| Python | 3.12.4 (3.11+ works) | Windows 11; nothing OS-specific in this stage |
| Claude Code CLI | 2.1.70, logged in | `LLM_PROVIDER=claude-code` sends each scoring prompt through `claude -p` on the user's subscription. No API key needed. |
| Model files | none | The provider is remote. Ollama is optional and not used by this run path. |
| Chrome, Node.js, python-jobspy | not needed | Only the auto-apply and discovery stages use them |

Pinned Python dependencies are in `requirements-capstone.txt`. They are the versions a
fresh virtual environment resolved to during the clean-checkout test, and the versions the
trial numbers were produced with:

```
typer==0.29.1
rich==15.0.0
httpx==0.28.1
python-dotenv==1.2.4
PyYAML==6.0.3
beautifulsoup4==4.15.0
pandas==3.1.1
playwright==1.65.1
```

`pandas` and `playwright` are declared dependencies of the package but are not
imported by the score stage; they install anyway so `pip install -e .` succeeds.

## Setup from a clean checkout

```bash
git clone https://github.com/<your-fork>/ApplyPilot.git
cd ApplyPilot
python -m venv .venv
# Windows: .venv\Scripts\activate      macOS/Linux: source .venv/bin/activate
pip install -r requirements-capstone.txt -e .
```

The package needs a data directory with four files. Either run `python -m applypilot init`
(interactive) or point `APPLYPILOT_DIR` at a folder that already has them:

```
<data dir>/
  .env            LLM_PROVIDER=claude-code and LLM_MODEL=haiku (or any provider llm.py supports)
  profile.json    your profile (applypilot init writes it)
  resume.txt      plain-text resume
  applypilot.db   the jobs database; needs jobs with a full_description to score
```

`APPLYPILOT_DIR` defaults to `~/.applypilot`. For the capstone trials I used a copy of
my real data directory so the trials never touch my live database.

On this Windows machine `pip` could not create the `applypilot.exe` entry point
(an `applypilot.exe.deleteme` rename error in `C:\Python312\Scripts`), so every command
below uses `python -m applypilot`, which is equivalent.

## The command

```bash
python -m applypilot run score --limit 10 --rescore
```

Scores ten jobs (the first ten in the database that have a description), writes the
scores to the database, and appends two records per job to the run log:
one `llm_call` (model, duration, tokens, cost) and one `job_scored` (score, parse result).
Drop `--rescore` to score only jobs that have no score yet; drop `--limit` to score all of them.

Read the log back without opening the file:

```bash
python -m applypilot runlog --last 10            # summary table + last 10 llm_call records
python -m applypilot runlog --event job_scored   # same for the per-job records
python -m applypilot runlog --json               # summary as JSON
```

The log file is `<data dir>/logs/runs.jsonl`. Set `APPLYPILOT_RUN_LOG=<path>` to write
somewhere else (the trial runner does this so each trial gets its own file).

## Running the capstone trials

```bash
python scripts/capstone_trial.py --home <data dir> --trials 3 --jobs 10 --label before
python scripts/capstone_trial.py --home <data dir> --trials 3 --jobs 10 --label before --fail-mode timeout
```

Each trial restores `<data dir>/applypilot.snapshot.db` over `applypilot.db` if that
snapshot exists (so every trial scores the same ten jobs), runs the command above with its
own run-log file, and prints the counts the acceptance criteria in `criteria.md` are
judged on. `--fail-mode timeout` sets `LLM_TIMEOUT=0.2` so every call fails; this is how the
error-path criterion is exercised. Output and logs land in `<data dir>/logs/trial-*`.

## Record of it running

The README's **Instrumentation** section under `## Capstone` has the pasted log entries
from real sessions, including a failed run, and **What It Costs** has the measured cost.

## What the clean-checkout test found

I cloned the repository into an empty folder, made a fresh virtual environment, ran
`pip install -e .` and then the command above against a copy of my data directory. It
scored two jobs on the first try, so nothing in the instructions was missing. What was
wrong was the pin list: I had written the versions from my working machine, and the fresh
environment resolved to newer ones (rich 15.0.0 instead of 14.3.3, typer 0.29.1 instead
of 0.24.1, pandas 3.1.1 instead of 2.2.3). The stage ran identically on both sets, but
"pinned" has to mean the versions that actually ran, so `requirements-capstone.txt` now
holds the fresh-environment set and the install line uses it.
