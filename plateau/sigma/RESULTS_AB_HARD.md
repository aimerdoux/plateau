# Σ / Plateau — LIVE A/B Capability Experiment — HARD (DISCRIMINATING) ROUND — RESULTS

**Manifest hash (pre-registered, frozen + committed BEFORE any WITH run):**
`sha256:4e248246873f0d6b9388a196d675526d9fad7b99c039ff753dad2fa32dc92d18`

This is the **discriminating round** the FLAT N=7 result (`RESULTS_AB.md`) could not deliver. That
round was a ceiling effect: the base model one-shot all 7 tasks, so the Σ loop had no headroom to
help. Here we built a **harder task set**, used an **objective headroom filter** to find tasks the
base model CANNOT one-shot, and measured whether the Σ loop **recovers** them.

**Model:** live `claude -p` (Claude Code CLI, v2.1.170). Every number below is from a real paid run.
**NO fabrication.** Both arms = the SAME base model; the only delta is the Σ scaffolding.
**Objective V only** — fixed programmatic gates in `ab_tasks_hard.py`, pre-verified SOUND
(good-passes / bad-fails) in a fresh subprocess by neither arm before any paid call (A6 holds).

## Protocol (exactly as pre-registered)

1. **Harder sample (N=12):** multi-constraint / deep / edge-case-heavy deliverables (roman round-trip
   with strict rejection, shunting-yard calc with precedence + right-assoc `^` + unary minus, interval
   merge+complement, LRU cache, SemVer 2.0.0 precedence, base62, JSON-path getter, RFC-4180 CSV,
   bracket validator with string-literal awareness, cross-field-consistent sealed-verdict JSON,
   topological sort with cycle detection, banker's-rounding money). Each scored by ONE objective
   programmatic gate asserting many independent properties simultaneously (threshold τ=1.0; one miss
   ⇒ FAIL). Grounded in corpus deliverable SHAPES (committed_file / sealed_verdict). Meaningfully
   harder than t1–t7.
2. **Headroom filter (objective):** run ARM_WITHOUT (a SINGLE `claude -p` pass) on ALL 12; record
   baseline pass/fail. Tasks where WITHOUT FAILS = the **measured-headroom core set**; tasks where
   WITHOUT PASSES = controls.
3. **Recovery:** run ARM_WITH (`run_schema`'s Φ-hydrated Σ loop, **max_iters=6**, depth compounds) on
   every baseline-FAILING task. **Metric = recovery-rate = (#WITH passes) / (#WITHOUT fails).** Also
   run ARM_WITH on 3 baseline-PASSING tasks as CONTROLS (regression check).
4. Pre-registration hashed + committed before the WITH runs; `negative_result_is_valid=true`.

## Headroom (Phase A — objective filter)

**baseline_fail = 2 / 12.** The base model one-shot 10 of 12 hard tasks. The 2 with measured headroom:

- `h3_intervals` (depth 4) — interval merge + complement
- `h8_csv` (depth 5) — RFC-4180 CSV parser (quoted fields, escaped `""`, embedded commas/newlines)

## Verdict

- **Recovery rate (gate-level, mechanical): 1 / 2.**
- **Recovery rate (mechanism-honest): 0 / 2.** See the per-task breakdown — the one gate-level pass
  (`h8_csv`) was a **first-draw re-roll**, not a Φ-hydrated loop recovery, and the one task where the
  loop actually iterated (`h3_intervals`) **failed all 6 Φ-hydrated iterations**.
- **Controls: 0 / 3 regressed** — WITH did not break any baseline-passing task.
- **Capability enhanced?  → NO** (mechanism-honest), on a **thin (2/12) headroom base that itself
  borders on a ceiling.** The Σ loop's depth-compounding feed-forward recovered **none** of the tasks
  where it was actually exercised.

## Per-task results

| Task | Depth | Baseline (WITHOUT) | WITH result | WITH iters | WITH trace | Role | Honest reading |
|---|---|---|---|---|---|---|---|
| h1_roman | 4 | PASS | PASS | 1 | [1.0] | control | no regression |
| h2_calc | 5 | PASS | PASS | 1 | [1.0] | control | no regression |
| h3_intervals | 4 | **FAIL** | **fail** | 6 | [0.0, 0.0, 0.0, 0.0, 0.0, 0.0] | RECOVERY | **loop ran all 6, never recovered** |
| h4_lru | 5 | PASS | PASS | 1 | [1.0] | control | no regression |
| h5_semver | 5 | PASS | — | — | — | baseline-pass | no headroom |
| h6_base62 | 4 | PASS | — | — | — | baseline-pass | no headroom |
| h7_jsonpath | 4 | PASS | — | — | — | baseline-pass | no headroom |
| h8_csv | 5 | **FAIL** | **PASS** | 1 | [1.0] | RECOVERY | **passed on iter 1 = re-draw variance, NOT loop recovery** |
| h9_brackets | 4 | PASS | — | — | — | baseline-pass | no headroom |
| h10_verdict_json | 5 | PASS | — | — | — | baseline-pass | no headroom |
| h11_toposort | 5 | PASS | — | — | — | baseline-pass | no headroom |
| h12_money | 5 | PASS | — | — | — | baseline-pass | no headroom |

**Approx cost (claude -p invocations):** Phase A = 12 (one WITHOUT pass each). Phase B = 6 (h3) + 1
(h8) + 1+1+1 (controls) = 10. **Total ≈ 22 paid calls.**

## Why this is NOT a pattern win (mechanism analysis)

The metric "recovery-rate on baseline failures" is only meaningful if a gate-level pass on a WITH run
was actually *produced by the loop's depth-compounding mechanism* (Φ hydrates the failed attempt +
failed-KPI back into the next prompt). Reading the two headroom tasks:

- **`h3_intervals` — the clean test of the mechanism — FAILED.** The loop got the full 6 Φ-hydrated
  iterations (trace `[0,0,0,0,0,0]`, `stop_reason=budget_exhausted`). Every iteration re-produced the
  same class of bug: it merges intervals whose gap is 1 (`if s <= merged[-1][1] + 1`), so it wrongly
  merges `[1,2]` and `[3,4]` and fails the gate's "NOT touching" case. Feeding the failure forward 5
  times did **not** fix it. This is the depth-compounding loop being given exactly the room the FLAT
  round lacked — and it did not climb.
- **`h8_csv` — passed on iteration 1** (`trace=[1.0]`, the loop never reached iteration 2). The WITH
  arm's *first fresh draw* of the same base model happened to pass where the WITHOUT arm's single draw
  failed. The Σ scaffolding contributed nothing here: no failure was ever hydrated forward, because
  the first pass already passed. This is **sample-to-sample variance** at k=1, not a loop recovery.
  Counting it as a "recovery" would overstate the pattern.

So the mechanism that the Σ pattern claims as its value — externalize the failure through Φ, feed it
forward, recover on a later iteration — fired on exactly one task (`h3`) and **failed**. The other
"recovery" was a coin-flip re-draw. Net mechanism-attributable recovery: **0/2**.

## Honest caveats

- **Thin headroom (2/12) — borderline ceiling.** Even this harder set was mostly within the base
  model's single-pass reach (10/12). Two headroom tasks is a small base to measure a rate on; the
  result is directional, not powered. A genuinely discriminating set would need many MORE
  baseline-failing tasks. By the pre-registered rule this is not `INCONCLUSIVE_CEILING`
  (baseline_fail > 0), but it is close to it, and that caveat is load-bearing.
- **k=1 per arm.** Both arms draw the base model once per attempt; `h8`'s WITH=PASS / WITHOUT=FAIL
  split is exactly the noise this exposes. With k=1 a single task can flip on resample. The honest
  read controls for this by looking at the *trace* (did the loop iterate?) not just the final bit.
- **The mechanical analyzer reports verdict=YES (1/2 > 0).** That is the literal gate-level count and
  is recorded faithfully in `ab_runs_hard/*.json`. This writeup overrides it to **NO** on
  mechanism-honest grounds (the 1 was re-draw variance; the loop-exercised task failed). Both numbers
  are stated so a reader can see the gap and judge.
- **Objective-V only; A6 held.** Gates are fixed code in `ab_tasks_hard.py`, pre-verified
  good-passes/bad-fails in a fresh subprocess (`_selftest_hard_gates.py`), authored by neither arm.
  A WITHOUT win, a tie, or a NEGATIVE is a first-class, valid result and is reported as-is.
- **Controls clean.** 0/3 baseline-passing tasks regressed under WITH — the scaffolding does not
  *break* things; it simply did not *add* capability on the tasks with headroom.
- **Monitor-vs-disk note (process hygiene):** during the run a line-buffered log tail intermittently
  emitted stale reads (e.g. briefly showing `h3`/`h8` as WITH-PASS `[0.0,1.0]`). All numbers in this
  report are read from the fsync'd on-disk checkpoints (`ab_runs_hard/*.json`) and the final flushed
  `_driver.log`, which are authoritative; the transient tail flickers were discarded.

## Bottom line

Given real headroom, the Σ depth-compounding loop **did not recover the one task where its mechanism
was actually exercised** (`h3_intervals`, 0/6 iterations), and the only gate-level pass was a
first-draw re-roll (`h8_csv`). **Capability enhanced = NO** on a thin headroom base. This is a real,
mechanism-honest negative for the pattern on these tasks — consistent with, and sharper than, the
FLAT N=7 round: the loop mechanically runs and externalizes state correctly, but on the tasks the
base model cannot one-shot it did not buy additional capability.
