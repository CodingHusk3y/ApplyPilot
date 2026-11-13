# Capstone acceptance criteria

Written before any trial was run. The only numbers I had when writing these were the
Milestone 3 measurement (one ten-job session: mean 3.6 s and $0.0026 per job, no
errors) and a one-job smoke test of the timeout path. Each criterion is judged on three
trials; the target has to hold in every trial to count as MET.

Trials are produced by `scripts/capstone_trial.py` against an isolated copy of my data
directory (`APPLYPILOT_DIR`), so the same ten jobs are scored each time:

- normal trials: `--trials 3 --jobs 10 --label before` (criteria 1, 2, 5)
- failure trials: `--trials 3 --jobs 5 --fail-mode timeout --pending --label before`
  (criteria 2, 3, 4)

---

## 1. Every scored job leaves exactly two records in the run log

**Target:** in a ten-job run, the run log holds exactly 10 `llm_call` records and 10
`job_scored` records carrying that run's `run_id`, with no malformed lines. 10 of 10
in each of three trials.

**Why this target:** the whole point of the extension is that nothing the scorer does is
invisible afterwards. A log that is 90% complete is worse than none, because the missing
10% is where the interesting failure would be and I would read the log and conclude it
never happened. "Exactly" matters in both directions: a duplicate record would double a
cost total. Nothing looser is defensible for a log; nothing stricter is possible.

## 2. Every record has the fields the other criteria depend on

**Target:** every `llm_call` and `job_scored` record has non-null `ts`, `run_id`,
`event`, `status`, `duration_ms`, `stage`, `job_url` and `model`. Every successful
`llm_call` record additionally has non-null `input_tokens`, `output_tokens` and
`cost_usd`. Every record with `status = error` has a non-empty `error`. 20 of 20 records
complete in each normal trial, and 10 of 10 in each failure trial.

**Why this target:** criterion 5 and the cost number are computed from `duration_ms` and
`cost_usd`; if the provider stopped reporting usage, the cost in "What It Costs" would
silently become an estimate. A null `cost_usd` on a successful call is exactly the
failure I want the trials to catch. The error branch is stricter than "status is set"
because an error record without a message tells me *that* something failed and nothing
about *what*.

## 3. When the provider fails, the stage finishes and records every failure

**Target:** with `LLM_TIMEOUT=0.2` (every `claude` call is killed before it answers), a
five-job run exits with code 0, prints `Stage 'score' completed`, prints no traceback,
and the run log holds 5 `llm_call` records and 5 `job_scored` records with
`status = error` and an `error` field that starts with the exception type
(`TimeoutExpired: ...`). 5 of 5 in each of three trials.

**Why this target:** this is the "failure that shows up only as an absence" case. The
score stage already catches exceptions per job so one bad call does not abort the
batch; what was missing before this unit is any trace of it. Timeouts are the real
failure on this provider: a 600 s `LLM_TIMEOUT` is set in my `.env` because the CLI
sometimes stalls, and until now a stalled job looked identical to a scored one with a
low score. The target is all five, not four of five, because a dropped error record is
the same as no error logging at all.

## 4. A job whose scoring call failed is still pending afterwards

**Target:** after each failure trial in criterion 3, the five jobs it touched still have
`fit_score IS NULL` in the database, so the next `applypilot run score` picks them up
again. 5 of 5 in each of three trials.

**Why this target:** this is the bad-path criterion about the system as it was, and I
expect it to be the one most likely to miss. The one-job smoke test suggested the scorer
writes `fit_score = 0` when the LLM errors, and `0` is not `NULL`, so the job silently
drops out of every future run. One timed-out job is a lost application. If the trials
confirm it, the diagnosis is clear enough that it is the improvement I would make.
The run log is what makes this measurable: before this unit there was no record of
which jobs had errored, so there was nothing to check against the database.

## 5. Scoring one job takes under six seconds, almost always

**Target:** in a ten-job run, at least 9 of the 10 `llm_call` records have
`duration_ms < 6000` (wall clock, including starting the `claude` process). 9 of 10 in
each of three trials.

**Why this target:** six seconds is ten jobs a minute, which turns the 82 unscored
jobs in my database into about eight minutes and a thousand-job discovery run into
under two hours overnight. The Milestone 3 session averaged 3.6 s with a 4.1 s maximum,
but the first call of the two-job smoke test took 6.3 s, so I expect a cold first call
to be slower than the rest. "9 of 10" allows for that one cold call; "10 of 10" would be
measuring process startup, which is not what I care about, and "under 10 s" would never
fail and teach me nothing.
