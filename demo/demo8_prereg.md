# Control-loop A/B at completion parity (demo8) — PRE-REGISTRATION

Written and committed **BEFORE** the driver is built and **BEFORE** any worker is
dispatched, so it provably precedes the data. The verdict is computed from sealed records by
the locked rule below; **this document is the rule.** Engineering only — context efficiency
vs task completion; no phenomenality.

## Why this exists (what demo7 left open)

demo7 came back **UNSCORABLE** and shipped that way: its pre-registered guard (≥5 completed
dispatch records) fired at n=3. Two flaws caused it, and demo8 fixes exactly those two:

1. **The scorer ran inside the run it was scoring.** demo7's T5 sealed while T2/T3/T7/T8
   were still in flight, so it could only ever see a partial series. **demo8 scores strictly
   AFTER the run reaches DONE**, in a separate process.
2. **The full-history arm was a COUNTERFACTUAL** — modelled from cumulative worker bytes,
   never actually run. demo8 **measures it**: a real second arm whose workers really do
   carry the whole accumulated transcript.

Everything else about the mechanism is unchanged.

## Two arms (identical task spec, identical gates, identical order, isolated worktrees)

Each arm gets its **own git worktree** off the same commit (per the Parent Agent Manual's
isolation law — no two writing agents share a checkout), and implements the **same** 5-layer
feature independently. Both arms' workers are real `claude -p` dispatches.

1. **arm_plateau (BOUNDED)** — each worker's prompt is the **inflated signal + one task**.
   Never the transcript.
2. **arm_fullhistory (CONTROL)** — each worker's prompt is the **entire accumulated
   transcript** (every prior task's prompt + that worker's full reply) + one task. This is
   the standard loop, and it is genuinely dispatched, not simulated.

## The task spec — 5 STRICTLY SERIAL layers (`control resume`)

Real code in this repo, dependent in order so the control arm's context must actually climb:

- **T1** `next_task(text)` → the first unchecked `Task`, or `None`.
- **T2** `resume_plan(control_dir, root)` → `{next, gate, expect, blocked, unchecked_count}`
  (depends on T1).
- **T3** CLI `resume` subcommand printing that dict (depends on T2).
- **T4** `tests/test_resume.py`, ≥4 tests covering T1–T3 (depends on T1+T2+T3).
- **T5** document `resume` in `CONTROL_LOOP.md` (depends on T3's final CLI shape).

Gates are authored here, before any work, and are run by the **parent** in each arm's
worktree — never by the worker (the trust boundary; a worker's word never checks a box).

## Metrics (from sealed records only; never typed by hand)

- `prompt_tokens[arm][step]` — deterministic `tok()` over the exact prompt bytes sent to
  that worker. The efficiency axis.
- `completion[arm]` — did the task's parent-run GATE pass. The hard gate.
- `slope[arm]` — least-squares slope of `prompt_tokens` vs step index.

## Decision rule (reused from demo4/demo6 `harness4.score`, applied WITHOUT override)

- **UNSCORABLE** if `arm_fullhistory` does not climb materially (slope not positive → the
  task chain is too short to test the axis), or the arms differ in spec/gates/order.
- **WIN** if fullhistory climbs **AND** `slope[plateau] ≤ 0.25 × slope[fullhistory]`
  **AND** completion parity (plateau passes every gate fullhistory passes).
- **PARTIAL_FORGETS** if plateau is bounded but FAILS a gate fullhistory passes (amnesia,
  not a win).
- **NULL** if `slope[plateau]` is not materially below fullhistory (no bound achieved).

## Pre-registered predictions (honest)

| # | claim | prediction | conf |
|---|---|---|---|
| P1 | fullhistory prompt tokens climb materially across 5 serial tasks | LIKELY | 0.85 |
| P2 | plateau slope ≤ 25% of fullhistory slope | LIKELY | 0.80 |
| P3 | completion parity (both arms pass all 5 gates) | GENUINELY OPEN | 0.55 |
| P4 | **WIN** = P1 ∧ P2 ∧ P3 | OPEN | 0.50 |

**NULL, PARTIAL_FORGETS and UNSCORABLE are all live and will ship.** The most likely honest
failure is **P3**: the bounded arm may forget something the transcript arm still has and
fail a late gate — that is `PARTIAL_FORGETS`, and it is a real finding about the condensation
limit, not a bug to paper over.

## Guards (pre-committed)

- **Score only after DONE.** No scoring process may run while any worker is in flight. This
  is demo7's flaw #1 and it is now a rule.
- **No re-runs to improve a number.** One dispatch per (arm, task). If a worker fails its
  gate, that is recorded as a completion failure — it is not silently retried to make the
  arms look equal. (A retry, if any, is logged and the *first* result stands for scoring.)
- **Identical spec across arms**: same 5 tasks, same gates, same order, same model, same
  worker timeout. Only the PROMPT CONTENT differs (signal vs transcript) — that is the
  single manipulated variable.
- **Thresholds are frozen above** (25% slope bar, materiality of the climb) and are not
  retuned after seeing data.
- **Workers may not edit the judge**: `tests/test_control_loop.py` and the gate semantics in
  `control.py` are off-limits; edits there invalidate the arm.
- If fewer than 5 tasks complete **in the control arm**, report **UNSCORABLE** — same guard
  that fired in demo7, kept deliberately.

## Integrity

Per-(arm, step) records — the exact prompt bytes, the reply, `prompt_tokens`, the gate
result — are written write-once to `demo/raw8/` and sealed under a hash-chained manifest
(`plateau.integrity`) **BEFORE** scoring. The scorer reads only sealed records; a fresh
process must re-derive `prompt_tokens` from the sealed prompt bytes and reproduce the
verdict. Results are **LOCAL** and are not published into README/RESULTS/BENCHMARKS unless
the verdict is WIN **and** the operator says go.

## EXIT

Both arms run to DONE-or-failure on the identical 5-task spec, sealed, recompute-verified,
scored by the locked rule above. Report per-step prompt tokens for both arms, completion
parity, the verdict, and the recompute result. **/halt at the verdict.**
