<!-- logo here -->

> **⚠️ ApplyPilot** is the original open-source project, created by [Pickle-Pixel](https://github.com/Pickle-Pixel) and first published on GitHub on **February 17, 2026**. We are **not affiliated** with applypilot.app, useapplypilot.com, or any other product using the "ApplyPilot" name. These sites are **not associated with this project** and may misrepresent what they offer. If you're looking for the autonomous, open-source job application agent — you're in the right place.

# ApplyPilot

**Applied to 1,000 jobs in 2 days. Fully autonomous. Open source.**

[![PyPI version](https://img.shields.io/pypi/v/applypilot?color=blue)](https://pypi.org/project/applypilot/)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
[![License: AGPL-3.0](https://img.shields.io/badge/license-AGPL--3.0-green.svg)](LICENSE)
[![GitHub stars](https://img.shields.io/github/stars/Pickle-Pixel/ApplyPilot?style=social)](https://github.com/Pickle-Pixel/ApplyPilot)
[![ko-fi](https://ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/S6S01UL5IO)




https://github.com/user-attachments/assets/7ee3417f-43d4-4245-9952-35df1e77f2df


---

## What It Does

ApplyPilot is a 6-stage autonomous job application pipeline. It discovers jobs across 5+ boards, scores them against your resume with AI, tailors your resume per job, writes cover letters, and **submits applications for you**. It navigates forms, uploads documents, answers screening questions, all hands-free.

Three commands. That's it.

```bash
pip install applypilot
pip install --no-deps python-jobspy
pip install pydantic tls-client requests markdownify regex
applypilot init          # one-time setup: resume, profile, preferences, API keys
applypilot doctor        # verify your setup — shows what's installed and what's missing
python -m applypilot run           # discover > enrich > score > tailor > cover letters
applypilot run -w 4      # same but parallel (4 threads for discovery/enrichment)
python -m applypilot run score tailor
python -m applypilot apply         # autonomous browser-driven submission
applypilot apply -w 3    # parallel apply (3 Chrome instances)
applypilot apply --dry-run  # fill forms without submitting
```

> **Why two install commands?** `python-jobspy` pins an exact numpy version in its metadata that conflicts with pip's resolver, but works fine at runtime with any modern numpy. The `--no-deps` flag bypasses the resolver; the second command installs jobspy's actual runtime dependencies. Everything except `python-jobspy` installs normally.

---

## Two Paths

### Full Pipeline (recommended)
**Requires:** Python 3.11+, Node.js (for npx), Gemini API key (free), Claude Code CLI, Chrome

Runs all 6 stages, from job discovery to autonomous application submission. This is the full power of ApplyPilot.

### Discovery + Tailoring Only
**Requires:** Python 3.11+, Gemini API key (free)

Runs stages 1-5: discovers jobs, scores them, tailors your resume, generates cover letters. You submit applications manually with the AI-prepared materials.

---

## The Pipeline

| Stage | What Happens |
|-------|-------------|
| **1. Discover** | Scrapes 5 job boards (Indeed, LinkedIn, Glassdoor, ZipRecruiter, Google Jobs) + 48 Workday employer portals + 30 direct career sites |
| **2. Enrich** | Fetches full job descriptions via JSON-LD, CSS selectors, or AI-powered extraction |
| **3. Score** | AI rates every job 1-10 based on your resume and preferences. Only high-fit jobs proceed |
| **4. Tailor** | AI rewrites your resume per job: reorganizes, emphasizes relevant experience, adds keywords. Never fabricates |
| **5. Cover Letter** | AI generates a targeted cover letter per job |
| **6. Auto-Apply** | Claude Code navigates application forms, fills fields, uploads documents, answers questions, and submits |

Each stage is independent. Run them all or pick what you need.

---

## ApplyPilot vs The Alternatives

| Feature | ApplyPilot | AIHawk | Manual |
|---------|-----------|--------|--------|
| Job discovery | 5 boards + Workday + direct sites | LinkedIn only | One board at a time |
| AI scoring | 1-10 fit score per job | Basic filtering | Your gut feeling |
| Resume tailoring | Per-job AI rewrite | Template-based | Hours per application |
| Auto-apply | Full form navigation + submission | LinkedIn Easy Apply only | Click, type, repeat |
| Supported sites | Indeed, LinkedIn, Glassdoor, ZipRecruiter, Google Jobs, 46 Workday portals, 28 direct sites | LinkedIn | Whatever you open |
| License | AGPL-3.0 | MIT | N/A |

---

## Requirements

| Component | Required For | Details |
|-----------|-------------|---------|
| Python 3.11+ | Everything | Core runtime |
| Node.js 18+ | Auto-apply | Needed for `npx` to run Playwright MCP server |
| Gemini API key | Scoring, tailoring, cover letters | Free tier (15 RPM / 1M tokens/day) is enough |
| Chrome/Chromium | Auto-apply | Auto-detected on most systems |
| Claude Code CLI or Ollama | Auto-apply | Claude Code is the default; Ollama is supported experimentally for local tool calling |

**Gemini API key is free.** Get one at [aistudio.google.com](https://aistudio.google.com). OpenAI and local models (Ollama/llama.cpp) are also supported.

### Local Ollama auto-apply (experimental)

Ollama can replace Claude Code for the browser agent. It must support OpenAI-compatible
tool calls; `qwen3:14b` is a good starting point for machines with about 10 GB of
available VRAM/RAM. Larger models are more reliable on long Workday forms.

```bash
ollama pull qwen3:14b
```

Add these settings to `~/.applypilot/.env`:

```dotenv
LLM_PROVIDER=ollama
LLM_MODEL=qwen3:14b
APPLY_PROVIDER=ollama
APPLY_MODEL=qwen3:14b
LLM_TIMEOUT=600
```

Run `applypilot doctor`, then use `applypilot apply --dry-run` first. Local browser
agents are slower and may make more tool-call mistakes than Claude Code, so review
dry-run behavior before enabling real submissions.

### Optional

| Component | What It Does |
|-----------|-------------|
| CapSolver API key | Solves CAPTCHAs during auto-apply (hCaptcha, reCAPTCHA, Turnstile, FunCaptcha). Without it, CAPTCHA-blocked applications just fail gracefully |

> **Note:** python-jobspy is installed separately with `--no-deps` because it pins an exact numpy version in its metadata that conflicts with pip's resolver. It works fine with modern numpy at runtime.

---

## Configuration

All generated by `applypilot init`:

### `profile.json`
Your personal data in one structured file: contact info, work authorization, compensation, experience, skills, resume facts (preserved during tailoring), and EEO defaults. Powers scoring, tailoring, and form auto-fill.

### `searches.yaml`
Job search queries, target titles, locations, boards. Run multiple searches with different parameters.

### `.env`
API keys and runtime config: `GEMINI_API_KEY`, `LLM_MODEL`, `CAPSOLVER_API_KEY` (optional).

### Package configs (shipped with ApplyPilot)
- `config/employers.yaml` - Workday employer registry (48 preconfigured)
- `config/sites.yaml` - Direct career sites (30+), blocked sites, base URLs, manual ATS domains
- `config/searches.example.yaml` - Example search configuration

---

## How Stages Work

### Discover
Queries Indeed, LinkedIn, Glassdoor, ZipRecruiter, Google Jobs via JobSpy. Scrapes 48 Workday employer portals (configurable in `employers.yaml`). Hits 30 direct career sites with custom extractors. Deduplicates by URL.

### Enrich
Visits each job URL and extracts the full description. 3-tier cascade: JSON-LD structured data, then CSS selector patterns, then AI-powered extraction for unknown layouts.

### Score
AI scores every job 1-10 against your profile. 9-10 = strong match, 7-8 = good, 5-6 = moderate, 1-4 = skip. Only jobs above your threshold proceed to tailoring.

### Tailor
Generates a custom resume per job: reorders experience, emphasizes relevant skills, incorporates keywords from the job description. Your `resume_facts` (companies, projects, metrics) are preserved exactly. The AI reorganizes but never fabricates.

### Cover Letter
Writes a targeted cover letter per job referencing the specific company, role, and how your experience maps to their requirements.

### Auto-Apply
Claude Code (or the experimental Ollama runner) launches a Chrome instance, navigates
to each application page, detects the form type, fills personal information and work
history, uploads the tailored resume and cover letter, answers screening questions
with AI, and submits. A live dashboard shows progress in real-time.

The Playwright MCP server is configured automatically at runtime per worker. No manual MCP setup needed.

```bash
# Utility modes (no Chrome/Claude needed)
applypilot apply --mark-applied URL    # manually mark a job as applied
applypilot apply --mark-failed URL     # manually mark a job as failed
applypilot apply --reset-failed        # reset all failed jobs for retry
applypilot apply --gen --url URL       # generate prompt file for manual debugging
```

---

## CLI Reference

```
applypilot init                         # First-time setup wizard
applypilot doctor                       # Verify setup, diagnose missing requirements
applypilot run [stages...]              # Run pipeline stages (or 'all')
applypilot run --workers 4              # Parallel discovery/enrichment
applypilot run --stream                 # Concurrent stages (streaming mode)
applypilot run --min-score 8            # Override score threshold
applypilot run --dry-run                # Preview without executing
applypilot run --validation lenient     # Relax validation (recommended for Gemini free tier)
applypilot run --validation strict      # Strictest validation (retries on any banned word)
applypilot apply                        # Launch auto-apply
applypilot apply --workers 3            # Parallel browser workers
applypilot apply --dry-run              # Fill forms without submitting
applypilot apply --continuous           # Run forever, polling for new jobs
applypilot apply --headless             # Headless browser mode
applypilot apply --url URL              # Apply to a specific job
applypilot status                       # Pipeline statistics
applypilot dashboard                    # Open HTML results dashboard
```

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup, coding standards, and PR guidelines.

---

## License

ApplyPilot is licensed under the [GNU Affero General Public License v3.0](LICENSE).

You are free to use, modify, and distribute this software. If you deploy a modified version as a service, you must release your source code under the same license.

---

## Capstone

**What This Extends**

This capstone extends ApplyPilot, the job-application pipeline in this repository
(my fork of Pickle-Pixel/ApplyPilot). The system as it stood before this unit is the
commit `ec306e7` ("Baseline before capstone"): a six-stage pipeline (discover, enrich,
score, tailor, cover letter, auto-apply) that scores every discovered job against my
resume with an LLM and tailors a resume for the good fits. My earlier work on it added
the `LLM_PROVIDER=claude-code` path (scoring and tailoring through the logged-in
`claude` CLI), an Ollama provider, and `applypilot add` for hand-picked job links.

What is new in this unit is the operational layer around the **score** stage:

- `src/applypilot/telemetry.py`: a structured JSONL run log. Every LLM call and every
  scored job appends one record with a timestamp, run id, stage, job URL, model,
  duration, token counts, dollar cost (when the provider reports it), and the error
  text when something fails.
- `LLMClient.chat()` now records every call, successful or not, through that module.
  No stage had to change its call sites.
- `applypilot run score --limit N --rescore`: a bounded, repeatable run so one
  invocation does a fixed amount of work and can be timed and costed.
- `applypilot runlog`: reads the run log back and answers "how many calls, how many
  errors, how long, how much" without opening the file.

**The Shape**

Shape A, deploy and instrument. Before this unit the score stage only ever ran from my
terminal with `print`-style progress lines and nothing kept afterwards: I could not say
how long a job took to score, what it cost, or which jobs failed and why. The extension
is the run path (RUNNING.md, Path B: local with a committed log), the instrumentation,
and the measured numbers that come out of it.

Out of scope, decided before building:

- Not instrumenting the auto-apply stage. The browser agent runs through MCP in a
  separate process and its failures are mostly site-specific; it would take the
  whole unit on its own.
- Not touching discovery or enrichment (the scrapers). They hit live job boards, so a
  trial would not be repeatable from one hour to the next.
- Not hosting it. The pipeline needs my resume, my profile and a logged-in `claude`
  CLI on the machine that runs it, and the hosted free tier could not hold that.
- Not changing how scoring works. Same prompt, same model, same parser. Anything the
  log reveals about scoring quality goes in "What's Still Broken", not into a fix this
  unit, unless the diagnosis in Milestone 6 points there.

**Running It**

Path B, local with logs. The exact command, what the environment needs, and how the
trials are run are in [RUNNING.md](RUNNING.md). In one line:

```bash
python -m applypilot run score --limit 10 --rescore     # then: python -m applypilot runlog
```

I tested the instructions from a clean clone into a fresh virtual environment. It ran
first time; what it caught was that my dependency pins were not the versions a fresh
environment installs. The note at the end of RUNNING.md has the details.

**Instrumentation**

Every run appends to `<data dir>/logs/runs.jsonl` (override with `APPLYPILOT_RUN_LOG`).
Two record types, one JSON object per line, written by `src/applypilot/telemetry.py`:

- `llm_call`, written by `LLMClient.chat()` in `src/applypilot/llm.py` for every call,
  successful or not: `ts`, `run_id` (one per process), `event`, `stage`, `job_url`,
  `job_title`, `status` (`ok`/`error`), `provider`, `model`, `input_chars`, `output_chars`,
  `duration_ms` (wall clock, includes starting the `claude` process), `input_tokens`,
  `output_tokens`, `cache_read_tokens`, `cache_write_tokens`, `cost_usd` (as reported by
  the CLI's `total_cost_usd`), `provider_duration_ms` (the CLI's own `duration_api_ms`),
  and `error` (exception type and message) on failure.
- `job_scored`, written by `score_job()` in `src/applypilot/scoring/scorer.py` once per
  job: the same context fields plus `score`, `parse_ok`, `keywords_chars`,
  `reasoning_chars`, `duration_ms` for the whole job, and `error` when the call failed
  or the reply could not be parsed.

Ten `llm_call` entries from one real session (`run_id` 5ad0e06a, the ten-job cost
measurement below), pasted as written:

```
{"ts": "2026-11-13T20:44:15.657+00:00", "run_id": "5ad0e06a", "event": "llm_call", "stage": "score", "job_url": "https://www.linkedin.com/jobs/view/4378952516", "job_title": "Data Analyst", "status": "ok", "provider": "claude-code", "model": "haiku", "input_chars": 6098, "output_chars": 745, "duration_ms": 3558, "input_tokens": 1507, "output_tokens": 165, "cache_read_tokens": 0, "cache_write_tokens": 0, "cost_usd": 0.002332, "provider_duration_ms": 2095}
{"ts": "2026-11-13T20:44:18.950+00:00", "run_id": "5ad0e06a", "event": "llm_call", "stage": "score", "job_url": "https://www.linkedin.com/jobs/view/4381028541", "job_title": "Technical Data Analyst", "status": "ok", "provider": "claude-code", "model": "haiku", "input_chars": 6320, "output_chars": 708, "duration_ms": 3287, "input_tokens": 1566, "output_tokens": 135, "cache_read_tokens": 0, "cache_write_tokens": 0, "cost_usd": 0.002241, "provider_duration_ms": 1965}
{"ts": "2026-11-13T20:44:22.285+00:00", "run_id": "5ad0e06a", "event": "llm_call", "stage": "score", "job_url": "https://www.linkedin.com/jobs/view/4473687078", "job_title": "Senior Associate & Manager", "status": "ok", "provider": "claude-code", "model": "haiku", "input_chars": 6617, "output_chars": 655, "duration_ms": 3330, "input_tokens": 1645, "output_tokens": 145, "cache_read_tokens": 0, "cache_write_tokens": 0, "cost_usd": 0.0023699999999999997, "provider_duration_ms": 2062}
{"ts": "2026-11-13T20:44:25.594+00:00", "run_id": "5ad0e06a", "event": "llm_call", "stage": "score", "job_url": "https://www.linkedin.com/jobs/view/4473677293", "job_title": "Manager, Strategy", "status": "ok", "provider": "claude-code", "model": "haiku", "input_chars": 9508, "output_chars": 705, "duration_ms": 3305, "input_tokens": 2214, "output_tokens": 134, "cache_read_tokens": 0, "cache_write_tokens": 0, "cost_usd": 0.002884, "provider_duration_ms": 2039}
{"ts": "2026-11-13T20:44:29.679+00:00", "run_id": "5ad0e06a", "event": "llm_call", "stage": "score", "job_url": "https://www.linkedin.com/jobs/view/4475422891", "job_title": "Tax Manager", "status": "ok", "provider": "claude-code", "model": "haiku", "input_chars": 8235, "output_chars": 900, "duration_ms": 4088, "input_tokens": 1958, "output_tokens": 186, "cache_read_tokens": 0, "cache_write_tokens": 0, "cost_usd": 0.002888, "provider_duration_ms": 2682}
{"ts": "2026-11-13T20:44:33.471+00:00", "run_id": "5ad0e06a", "event": "llm_call", "stage": "score", "job_url": "https://www.linkedin.com/jobs/view/4476757057", "job_title": "Pricing Specialist", "status": "ok", "provider": "claude-code", "model": "haiku", "input_chars": 9850, "output_chars": 826, "duration_ms": 3780, "input_tokens": 2175, "output_tokens": 163, "cache_read_tokens": 0, "cache_write_tokens": 0, "cost_usd": 0.0029899999999999996, "provider_duration_ms": 2485}
{"ts": "2026-11-13T20:44:36.993+00:00", "run_id": "5ad0e06a", "event": "llm_call", "stage": "score", "job_url": "https://www.linkedin.com/jobs/view/4473594738", "job_title": "Category Sales Analyst", "status": "ok", "provider": "claude-code", "model": "haiku", "input_chars": 9204, "output_chars": 647, "duration_ms": 3516, "input_tokens": 2153, "output_tokens": 134, "cache_read_tokens": 0, "cache_write_tokens": 0, "cost_usd": 0.002823, "provider_duration_ms": 2153}
{"ts": "2026-11-13T20:44:40.720+00:00", "run_id": "5ad0e06a", "event": "llm_call", "stage": "score", "job_url": "https://www.linkedin.com/jobs/view/4464118805", "job_title": "Senior Development Analyst (Commercial Real Estate)", "status": "ok", "provider": "claude-code", "model": "haiku", "input_chars": 6885, "output_chars": 903, "duration_ms": 3723, "input_tokens": 1611, "output_tokens": 174, "cache_read_tokens": 0, "cache_write_tokens": 0, "cost_usd": 0.002481, "provider_duration_ms": 2342}
{"ts": "2026-11-13T20:44:44.073+00:00", "run_id": "5ad0e06a", "event": "llm_call", "stage": "score", "job_url": "https://www.linkedin.com/jobs/view/4476365520", "job_title": "Acquisition Associate", "status": "ok", "provider": "claude-code", "model": "haiku", "input_chars": 6412, "output_chars": 670, "duration_ms": 3348, "input_tokens": 1551, "output_tokens": 135, "cache_read_tokens": 0, "cache_write_tokens": 0, "cost_usd": 0.002226, "provider_duration_ms": 1996}
{"ts": "2026-11-13T20:44:48.027+00:00", "run_id": "5ad0e06a", "event": "llm_call", "stage": "score", "job_url": "https://www.linkedin.com/jobs/view/4467274198", "job_title": "Data Solution Consultant", "status": "ok", "provider": "claude-code", "model": "haiku", "input_chars": 10255, "output_chars": 906, "duration_ms": 3946, "input_tokens": 2343, "output_tokens": 178, "cache_read_tokens": 0, "cache_write_tokens": 0, "cost_usd": 0.0032329999999999998, "provider_duration_ms": 2662}
```

One failed run, triggered on purpose with `LLM_TIMEOUT=0.2` so the `claude` subprocess is
killed before it answers. Both records are written and the stage finishes instead of
crashing (the `error` field is the exception text, cut at 300 characters):

```
{"ts": "2026-11-13T20:44:50.885+00:00", "run_id": "66f2c9c6", "event": "llm_call", "stage": "score", "job_url": "https://www.linkedin.com/jobs/view/4378952516", "job_title": "Data Analyst", "status": "error", "provider": "claude-code", "model": "haiku", "input_chars": 6098, "output_chars": 0, "duration_ms": 573, "error": "TimeoutExpired: Command '['C:\\\\Users\\\\caomi\\\\.local\\\\bin\\\\claude.EXE', '-p', '--model', 'haiku', '--tools', '', '--output-format', 'json', '--no-session-persistence', '--disable-slash-commands', '--strict-mcp-config', '--system-prompt', \"You are a job fit evaluator. Given a candidate's resume and a job description,"}
{"ts": "2026-11-13T20:44:50.887+00:00", "run_id": "66f2c9c6", "event": "job_scored", "stage": "score", "job_url": "https://www.linkedin.com/jobs/view/4378952516", "job_title": "Data Analyst", "status": "error", "score": 0, "parse_ok": false, "duration_ms": 1267, "error": "TimeoutExpired: Command '['C:\\\\Users\\\\caomi\\\\.local\\\\bin\\\\claude.EXE', '-p', '--model', 'haiku', '--tools', '', '--output-format', 'json', '--no-session-persistence', '--disable-slash-commands', '--strict-mcp-config', '--system-prompt', \"You are a job fit evaluator. Given a candidate's resume and a job description,"}
```

**What It Costs**

One run here means scoring one job: one prompt (system instructions + resume + job
description) through `claude -p --model haiku`, one reply. The cost comes from the
`total_cost_usd` field the Claude Code CLI returns with each JSON result, which the
run log stores as `cost_usd`. I ran the stage on ten jobs
(`python -m applypilot run score --limit 10 --rescore`) and averaged the ten records
with `python -m applypilot runlog --json`:

| Measure (10 jobs, one session) | Value |
|---|---|
| Mean cost per scored job | $0.00265 |
| Total for the ten | $0.0265 |
| Min / max per job | $0.00223 / $0.00323 |
| Mean input / output tokens | 1872 / 155 |
| Mean wall time per job | 3.6 s (CLI-reported API time 2.2 s) |

This is API-equivalent spend as priced by the CLI; on a subscription plan it is drawn
from the plan's usage allowance rather than billed per call. The hundred-a-day
arithmetic is finished in Milestone 7 below, once the trials give a number from more
than one session.
