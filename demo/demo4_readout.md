# demo4 readout — real-workload 3-arm test (command_output end-to-end)

LOCAL ARTIFACT — NOT committed/pushed/published. Awaiting operator go.
Prereg: `demo/demo4_prereg.md` (committed d7857bd, precedes this run). Rules applied
without override; sealed raw in `demo/raw4/` (27 files, manifest verified); verdict
reproduces in a fresh process.

## Result (TWO separate verdicts)

- **EFFICIENCY (arm2 vs arm1): UNSCORABLE — task too short.**
  arm1 (full-history) reached the success check in **2 steps**, so its context
  trajectory is a single increment (243→1172 tok), not a multi-step climb. This is the
  prereg's pre-registered guard verbatim ("If arm1's context doesn't materially climb,
  e.g. the feature is too small, the task is too short → UNSCORABLE") and the operator's
  stated UNSCORABLE condition ("arm1 doesn't actually climb (task too short)"). It is
  also power-limited by the project's own precedent (C3 n=3 was INCONCLUSIVE; arm1 here
  has a single climbing interval).
  - Mechanical locked-scorer output (sealed, reproducible) = **NULL** ("arm2 slope 310.5
    not ≤ 25% of arm1 929.0"). Disclosed for transparency. Note even this NULL is not a
    clean refutation: arm2's slope is ~1/3 of arm1's and would flatten further (lessons
    cap); it missed the 4× WIN bar partly *because* arm1 produced only one interval.
  - Governing verdict = **UNSCORABLE**. Not a Plateau win and not a refutation — the run
    simply could not test the efficiency axis at this feature size.

- **AUTONOMY (arm3 vs arm2): NULL — pre-committed live NULL.**
  Both PASS. arm3 = 3 steps / 0 errors; arm2 = 3 steps / 0 errors → exact tie → not a
  win by the locked rule (WIN requires fewer steps OR fewer errors). The freed headroom
  arm3 spent on forward-planning grew its own context to slope **778** (≈ full-history's
  929 — it spent most of the budget) and bought **zero** improvement in steps or errors.
  **"Plateau is an efficiency tool, not a capability tool, at this scale."** Reported plainly.
  This is clean and scorable (both arms PASS, identical sub-task path).

## Per-step context (sealed, deterministic token count)

| arm | step1 | step2 | step3 | slope/step | steps→PASS | errors | PASS |
|---|---|---|---|---|---|---|---|
| arm1 full-history    | 243 | 1172 | —    | 929.0 | 2 | 0 | ✓ (33 tests) |
| arm2 plateau-efficiency | 413 | 826  | 1034 | 310.5 | 3 | 0 | ✓ (30 tests) |
| arm3 plateau-autonomy   | 435 | 1372 | 1991 | 778.0 | 3 | 0 | ✓ (30 tests) |

## Method integrity

- Pre-flight: Plateau's own integrity trees (raw/raw2/raw3) verified clean before the run,
  independent of the (tamper-drilled, unrelated) bmacp parent. Baseline = 26 tests.
- Objective binary check (no judgment): `pytest -q` exit 0 with ≥28 tests AND the
  command_output stale-detection probe (live-admit → mutate → stale-drop → fail-closed).
- Mock-plumb BEFORE any paid dispatch proved all 8 verdict branches fire, the check
  returns PASS on a reference impl and FAIL on baseline, and seal→score round-trips.
- 3 pristine repo copies (git archive HEAD), identical task/seed/check/step-cap(12).
- Sealed write-once BEFORE scoring; recompute (fresh process) PASS: chain+files verify,
  context_tokens re-derive from sealed prompts, verdict reproduces (27 sealed files).
- Bounded-orchestrator architecture: arm1's transcript lived on disk + in the dispatched
  subagent; the orchestrator only ever held token counts + bounded check records.

## FORK LOG

- **fork demo4-F1 (efficiency scorability):** mechanical locked scorer returned NULL;
  governing verdict set to **UNSCORABLE (task too short)** per the binding prereg guard +
  operator UNSCORABLE condition (arm1 completed in 2 steps → single climb interval). Both
  the mechanical NULL and the governing UNSCORABLE are disclosed; the call does NOT favor
  Plateau (neither is a win). The locked harness was NOT modified post-data.
- **fork demo4-F2 (autonomy precedence, pre-committed in harness before data):** DEGRADE >
  WIN > NULL precedence fixed in `harness4.score` before the run. Outcome landed in NULL
  (tie) — precedence did not bind this run.

## Honest caveats

- arm1 transcripts are compact (terse subagent replies), so the climb is modest in
  absolute terms (243→1172), not the "tens of thousands per late step" the prereg
  imagined. Direction (climb) faithful; magnitude small — consistent with the project's
  prior "toy magnitudes" caveat.
- Arms chose different sub-task paths (arm1: signal→tests; arm2/arm3: signal→continuum→
  tests), so arm1 reached PASS via a shorter path. This is agent agency under identical
  task/check, but it contributes to arm1's short run.
- To actually score the efficiency axis, re-register with a larger feature so the
  full-history arm runs ≥4–5 dependent steps before PASS.
