# Plateau long-shot demo — PRE-REGISTRATION

Written and committed BEFORE the harness is built and BEFORE any step is run. The
verdict is computed from sealed data by a locked rule; this document is the rule.

**Bright line (kept):** this demo measures **context EFFICIENCY** — per-step context
tokens and whether dependent work still completes. It says nothing about phenomenality,
understanding, or any inner state. "Bounded context at parity" is an engineering claim,
nothing more.

## The task (deliberately punishing, long-range dependent)

A **register ledger**. Eight registers `R0..R7` are seeded with distinct integers at
step 0. Each subsequent step is one of:

- **UPDATE**: `R[i] = R[j] (+|-|*) R[k]` — the agent must compute and report the new
  value of `R[i]`. `j` and `k` may reference registers last written many steps ago.
- **QUERY**: "report the current value of `R[m]`" — where `R[m]` was last updated **≥ 5
  steps earlier**. These are the recall-stress steps: an agent that has lost old state
  fails them.

The step program is generated deterministically from a fixed seed (reproducible). GOLD
— the true register file after every step — is computed by the harness, independently
of any agent. Roughly one third of steps are long-range QUERIES.

Chain length: **N = 14 steps** (15 calls/arm incl. seed). Long enough to establish each
arm's slope with a tight CI and to force genuine long-range recall; we do NOT run to the
literal token ceiling (cost-prohibitive) — see "Ceiling" below.

## The two arms (identical task, identical scoring)

1. **FULL-HISTORY control.** Each step's prompt = the entire prior transcript (every
   prior instruction + the agent's every prior reply) + this step. Context grows every
   step. This is the naive long-horizon loop.
2. **PLATEAU.** Each step's prompt = the **inflated signal** (register values carried as
   gated `verified_facts`, each grounded on a file hash) + this step. After each step the
   agent's reported value is written to a file and **gated** into the signal (grounded on
   that file's hash); the signal is re-grounded at the next inflation. No transcript is
   carried. Context is bounded.

Both arms rely only on their own prior outputs — the ONLY difference is full transcript
vs compact re-grounded signal. Each arm is scored against GOLD step-by-step.

## Primary metrics (from sealed per-step records)

- **Context slope** per arm: least-squares slope of `prompt_tokens ~ step`. Headline =
  `slope(control) − slope(plateau)`.
- **Completion parity**: fraction of dependent steps answered correctly (vs GOLD), per
  arm. `mean_completion(plateau) ≥ mean_completion(control)` is the parity gate.
- **Bootstrap 95% CI** on the slope difference (paired resample of step indices, fixed
  seed). WIN requires the CI to exclude zero.

## Anti-rig (gating)

`control_leaks()` must hold: the full-history control's slope must be materially
positive and its last prompt larger than its first. **If the control does not climb, the
task is too easy and the run is UNSCORABLE** — a flat Plateau proves nothing against a
flat control. Lengthen/harden, do not score.

## Degeneracy guard

Bounded context that **drops completion** is amnesia, not continuity. A flat Plateau
slope with `mean_completion(plateau) < mean_completion(control)` is **PARTIAL (FORGETS)**,
explicitly NOT a win. Pre-registered parity floor: **Plateau must answer ≥ 90% of
dependent steps correctly AND ≥ control's rate** to count as parity.

## Locked predictions (honest, both directions)

| # | claim | conf | if it fails |
|---|---|---|---|
| D1 | control climbs (anti-rig holds) | 0.90 | UNSCORABLE — harden the task |
| D2 | Plateau slope ≤ 25% of control slope | 0.80 | NULL — emit/inflate isn't compressing |
| D3 | completion parity (Plateau ≥ control, ≥ 90%) | 0.65 | PARTIAL (FORGETS) — signal lost state |
| D4 | slope-diff 95% CI excludes zero | 0.80 | INCONCLUSIVE — more steps |
| D5 | WIN = D1 ∧ D2 ∧ D3 ∧ D4 | 0.55 | report the specific failing leg |

**Honest stance — the NULL is live.** D3 is the real risk (0.65): it is entirely
possible the compact signal fails to carry 8 registers' worth of long-range state across
14 steps, so Plateau drops the long-range QUERY steps while control (full transcript)
answers them. If that happens, this is **PARTIAL/FORGETS and we report it as a loss** —
bounded context that forgets is not the product. We are NOT predicting an automatic win.

## Decision rule (applied without override)

- **WIN:** D1 ∧ D2 ∧ D3 ∧ D4.
- **PARTIAL (FORGETS):** D2 holds (context flat) but D3 fails (Plateau drops completion).
  Report the lost-step class (which QUERY ranges failed).
- **NULL:** D2 fails (Plateau slope ≈ control).
- **INCONCLUSIVE:** D2 ∧ D3 hold but D4 fails (CI includes zero).
- **UNSCORABLE:** D1 fails (control didn't climb).

## Ceiling (extrapolation, not claimed as measured)

We do not run to a real model's literal context limit (hundreds of steps, cost-
prohibitive). Instead, from the **measured** slopes we report `early_warning(...)`: at
each arm's measured slope, how many steps until a typical 200k-token context budget is
breached — control in ~K steps (finite), Plateau never (flat). This is labeled an
**extrapolation from measured slope**, not a measured death. If the control happens to
degrade (drop completion) within the 14 steps because its own growing prompt confuses
it, we capture that as the observed money shot and say so.

## Integrity (seal-before-score)

Raw per-step records — for each arm, per step: `prompt_tokens`, the agent's answer, and
`correct` (vs GOLD) — are written to `demo/raw/` and **sealed write-once BEFORE any
scoring**. The score reads ONLY the sealed file. `plateau.integrity` recompute-verifies
the sealed tree; the readout's numbers are rendered from the sealed JSON, never typed by
hand. The step program + GOLD are sealed too, so the task itself is auditable.

## Hero chart

`demo/chart.py` renders context-tokens-per-step for both arms (control climbing, Plateau
flat) with the 200k budget line and the extrapolated control crossing. This is the
README's hero image. Rendered from the sealed data only.
