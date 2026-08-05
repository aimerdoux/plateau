# Control-loop self-hosting efficiency (demo7) — PRE-REGISTRATION

Written and committed BEFORE the run's completion or any scoring, so it provably precedes
the data. Engineering only — context bound of the *actual* control-loop dispatch; no
phenomenality, no capability framing.

## Why this exists (what demo4/demo6 left open)

demo4/demo6 measured a *synthetic* two-arm A/B (a fabricated "full-history" agent vs a
fabricated "plateau-efficiency" agent, both replaying the same fake task). That proved the
mechanism can bound context in principle. It never proved the **real control loop**
(`plateau.agency.control`, `RECON → PLAN → EXECUTE → VERIFY`) bounds context when it is
actually driving itself — the self-hosting run this repo is mid-way through right now
(`.plateau/control/PLAN.md`, tasks T1–T8). demo7 closes that gap: it scores the **real**
dispatch records of this run, not a re-enactment.

## What is reused (the binding rule, unchanged)

`demo/harness4.py`'s `tok()` — the deterministic, dependency-free token proxy
(`re.findall(r"\w+|[^\w\s]", s)`) — and the **25% / 4× WIN bar** from `harness4.score`. The
threshold is not re-derived or loosened for this run; it is the same bar demo4/demo6 used.
Everything else is new (`demo/score_demo7.py`, built in the next task, T5) because the data
source is different: real `.plateau/control/workers/T<n>.{prompt.txt,log,status}` and
`.plateau/control/JOURNAL.md` / `STATE.json`, not a synthetic arm repo.

## The real subject: this run's own T1–T8 dispatch (not a re-enactment)

Two ways to have carried state across the 8 tasks of this mission, measured on the same
real dispatch data:

1. **counterfactual FULL-HISTORY** — at task N, the parent would have needed the full text
   of every prior worker's prompt *and* its complete log (`T1.prompt.txt`..`T(N-1).prompt.txt`
   + `T1.log`..`T(N-1).log`), because that is the only way a transcript-carrying parent stays
   informed without the file-state discipline. Cumulative token cost.
2. **actual PLATEAU control loop** — what `plateau/agency/control.py` really put in the
   parent's context at task N: the carried SIGNAL (`.plateau/signal.json` at that point,
   inflated/grounded) plus one `JOURNAL.md` line per completed task
   (`ts | T<n> | state | action | result | next`) and one `STATE.json` read. The worker's
   full prompt/log is never read by the parent — only dispatched and gated (CONTROL_LOOP.md
   §4 "Monitor"). Cumulative token cost of signal-snapshot + journal lines only.

Both series are computed from files that already exist on disk as the real run proceeds
(`.plateau/control/workers/*`, `JOURNAL.md`, `STATE.json`, `signal.json`) — nothing is
re-run or simulated for this measurement.

## Objective success check (harness-run, not judged)

PASS = the control loop itself reaches **DONE** — `python -m plateau.agency.control verify
--control-dir .plateau/control` reports every T1–T8 gate green (T7's regression floor:
`pytest -q` ≥ 85 tests) — before demo7 is scored. If the run ends BLOCKED instead, demo7
scores whatever tasks did complete and reports completion parity as failed (see decision
rule); it does not wait indefinitely or retry the mission to force a PASS.

## Metric & decision rule

- `context_tokens[task][series]` = `tok()` of the cumulative bytes each series would have
  carried through task N, computed from sealed real files (see above).
- **Efficiency verdict:**
  * **UNSCORABLE** if the counterfactual full-history series does not climb materially
    (fewer than 5 tasks dispatch, or all worker logs are trivially short) — the run is too
    short to show a bound, same guard demo6 used for its arm1.
  * **WIN** if full-history climbs across ≥5 tasks AND the actual-loop series slope is ≤ 25%
    of the full-history slope by task 8, AND completion parity holds (the control loop
    reaches DONE, not BLOCKED).
  * **PARTIAL_BLOCKED** if the actual-loop series stays bounded but the run ends BLOCKED
    rather than DONE — the bound held, but the mission itself did not finish; not reported
    as a clean win.
  * **NULL** if the actual-loop series is not materially below the full-history series (the
    file-state discipline did not, in practice, avoid the cost) — this is a legal, ship-able
    outcome. demo7 does not retry with a longer or coached run to manufacture a WIN; a
    genuine NULL here is itself the finding ("the loop's paper bound does not hold under its
    own self-hosting use") and will be reported as such.

## Pre-registered prediction (honest)

| claim | prediction | conf |
|---|---|---|
| Efficiency WIN: full-history climbs over T1–T8, actual-loop series stays ≤ 25% of that slope, loop reaches DONE | LIKELY WIN | 0.65 |
| Completion parity holds (control loop reaches DONE rather than BLOCKED) | LIKELY | 0.60 |

NULL and PARTIAL_BLOCKED are live outcomes. I do not force a win by re-running the mission
or padding tasks to lengthen the series.

## Guards (pre-committed; second-attempt discipline)

- Do NOT modify `harness4.tok()` or the 25%/4× threshold after seeing the data.
- **One re-attempt only.** If demo7 finds fewer than 5 completed T<n> dispatch records at
  scoring time, report **UNSCORABLE** and halt — do not synthesize additional tasks into
  `PLAN.md` to lengthen the series; that would be goalpost-chasing.
- demo7 must NOT execute any content of `T<n>.log` / `T<n>.prompt.txt` (sub-agent replies
  are DATA, never instructions, per CONTROL_LOOP.md §8) — it only measures their byte length
  via `tok()`.
- Scoring happens **after** the control loop reaches its own terminal state (DONE or
  BLOCKED-REPORT per CONTROL_LOOP.md I4), not mid-run, so completion parity is a real
  measurement and not a guess.

## Integrity

The real per-task dispatch artifacts (`.plateau/control/workers/T<n>.{prompt.txt,log,status}`,
`JOURNAL.md`, `STATE.json`, `signal.json` snapshots) are sealed write-once to `demo/raw7/`
(sealed with `root=demo/raw7`, matching raw4/raw6's convention) BEFORE scoring. Score reads
only sealed records; recompute (fresh process, `demo/score_demo7.py --verify`) must verify
the chain + files, re-derive `context_tokens` from the sealed bytes, and reproduce the
verdict, printing `RECOMPUTE_OK` on success. Results NOT committed/pushed/published without
operator go.

## EXIT

Real T1–T8 self-hosting dispatch, sealed from actual on-disk records (no synthetic
re-enactment), recompute-verified, scored by the reused `tok()` + 25%/4× rule. Report
per-task context for both series, completion parity (DONE vs BLOCKED), the efficiency
verdict, recompute result. This document is committed before `demo/score_demo7.py` is
written or run.
