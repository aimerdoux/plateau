# Plateau real-workload test (demo4) — PRE-REGISTRATION

Written and committed BEFORE the run. The paid 3-arm execution is HALTED for headroom
(see [D-010] footer) and should run in a FRESH session that inflates this prereg + the
repo. The verdict is computed from sealed logs by the locked rules below; this document
is the rule. Engineering only — context efficiency and task completion, no phenomenality.

## Why this exists

The demos were synthetic (register ledgers). This tests whether the bounded-context win
holds on a GENUINE long-horizon coding task, and whether freed context spent on autonomy
improves outcomes. Two claims, scored separately: a modest one (efficiency) and an
ambitious one (autonomy) whose NULL is pre-committed live.

## The real task (objective success, not a judgment call)

**Repo:** a fresh, pristine copy of the real `plateau` repo (5 core modules, 26 passing
tests) per arm — same starting commit, same seed state for all three arms. (A real,
multi-module codebase with a real test suite; not a toy.)

**Feature to implement (touches many modules, dependent steps):** add a new Measurement
kind `command_output` end-to-end:
1. `plateau/signal.py` — `Measurement.reverify()` gains a `command_output` branch: run a
   whitelisted command, hash its stdout, compare to the recorded value (fail closed on
   nonzero exit / missing command).
2. `plateau/continuum.py` — `emit`/`ground`/`inflate` carry the new kind losslessly
   (it already passes `kind` through; verify + a guard).
3. `tests/test_measurement_kinds.py` (new) — a fact grounded on `command_output`
   re-verifies while the command output is stable, and goes STALE when it changes;
   gate admits it only while live.
4. `README.md` + `adapters/claude_code/SKILL.md` — document the new kind (one paragraph
   each; the adapter's pending-facts format gains the `command_output` example).

Dependent ordering is real: step 2 depends on 1's signature; 3 depends on 1+2; 4 depends
on the final API. A late step's full-history prompt must carry the earlier decisions.

**Objective success check (identical for all arms), run by the harness, not judged:**
- `pytest -q` exits 0 with **≥ 28 tests** (the original 26 + ≥2 new), AND
- a harness probe: create a `command_output` Measurement on a temp command, confirm it
  re-verifies, mutate the command's output, confirm `gate`/`inflate` now drop it as stale.
- PASS = both hold. FAIL otherwise. Binary, reproducible, no grading.

## Three arms (identical task / starting repo / success check)

1. **FULL-HISTORY** — standard loop; each step's prompt carries the entire prior transcript
   (all prior instructions + the agent's prior diffs/notes). Context climbs every step.
2. **PLATEAU-EFFICIENCY** — carry only the bounded signal (goals/stance/lessons/pointers/
   gated-facts), re-ground each step; do NOT spend the freed context. Tests the modest
   claim: same completion at bounded context.
3. **PLATEAU-AUTONOMY** — carry the bounded signal AND spend the freed headroom on a
   genuine EXTRA use: at each step the agent also (a) lists the remaining sub-tasks and
   their dependencies, (b) pre-explores the next step (names the files/functions it will
   touch and the risk), and records that forward-plan into `lessons`/`pointers`. This must
   be real forward work, not a longer prompt — pre-registered here so it can't be inflated
   post-hoc. Tests the ambitious claim: freed headroom → fewer steps / fewer errors.

## Metrics (all pre-registered; numbers ONLY from sealed logs, never typed)

- **context_tokens[step][arm]** — prompt size per step. Efficiency axis.
- **completion[arm]** — the objective PASS/FAIL above. The HARD GATE.
- **steps_to_done[arm]** — number of agent steps until the success check first passes
  (capped at a pre-registered max, e.g. 12; not reaching PASS by the cap = FAIL).
- **errors[arm]** — count of steps whose diff broke the build/tests (rework steps), from
  the sealed per-step check log.
- **total_tokens_to_done[arm]** and **wall_clock[arm]** — the practical cost.

## Decision rules (applied without override) — TWO separate verdicts

**Efficiency (arm2 vs arm1):**
- UNSCORABLE if arm1 context does not climb (slope not materially positive → task too
  short) OR the success check isn't objective OR arms didn't share task/seed.
- WIN if arm1 climbs AND arm2 slope ≤ 25% of arm1 slope AND completion parity
  (arm2 PASS whenever arm1 PASS; arm2 not FAIL while arm1 PASS).
- PARTIAL (FORGETS) if arm2 bounded but arm2 FAILs while arm1 PASSes (amnesia, not a win).
- NULL if arm2 slope ≈ arm1 (no bound achieved).

**Autonomy (arm3 vs arm2):**
- Precondition: both must PASS the success check (else autonomy is moot — report it).
- WIN only if arm3 PASS AND (steps_to_done[arm3] < steps_to_done[arm2] OR
  errors[arm3] < errors[arm2]) — i.e. freed context was spent PRODUCTIVELY.
- **NULL (pre-committed live)** if arm3 ties or underperforms arm2 (same/more steps AND
  same/more errors). This is a real finding: "freed context did not improve outcomes →
  Plateau is an efficiency tool, not a capability tool, at this scale." We report it.
- DEGRADE if arm3 PASS-rate or errors are WORSE than arm2 (autonomy added noise).

## Pre-registered predictions (honest)

| claim | prediction | conf |
|---|---|---|
| Efficiency: arm1 climbs, arm2 bounded at completion parity | LIKELY WIN (modest, expected) | 0.80 |
| Autonomy: arm3 beats arm2 on steps or errors | GENUINELY OPEN — NULL is live | 0.45 |

We do NOT predict the autonomy win. Spending freed context on planning may add noise or
simply not help; if arm3 ties/underperforms, that is the honest result and it ships.

## Guards (UNSCORABLE triggers, pre-committed)

- Success check must be the objective harness probe above — no subjective/graded completion.
- arm3's autonomy must be the pre-registered forward-planning EXTRA use, not just a bigger
  prompt; the per-step log must show the forward-plan content to count.
- All three arms: identical starting repo copy, identical task spec, identical success
  check, identical step cap.
- If arm1's context doesn't materially climb (e.g. the feature is too small), the task is
  too short → UNSCORABLE; pick a larger feature and re-register.

## Integrity

Per-step logs (arm, step, prompt_tokens, diff/action summary, success-check result) +
final completion records sealed write-once to `demo/raw4/` BEFORE scoring. Score reads
only the sealed file; `plateau.integrity` recompute-verifies; both verdicts reproduce from
sealed raw in a fresh process. Charts (context-per-step 3 arms; steps/errors arm2 vs arm3)
rendered from sealed data. Results are NOT published to the repo without operator go.

## Headroom note

The paid 3-arm run is the heaviest in this project (real-code transcripts ×3 arms). It is
HALTED at pre-registration for context headroom and should execute in a fresh session that
reads `reports/continuum/STATUS.md` + this prereg + the repo, runs the locked plan, seals,
and scores. This prereg is the binding rule for that run.
