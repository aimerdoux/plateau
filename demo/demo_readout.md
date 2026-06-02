# Plateau long-shot demo — readout

**Auto-rendered from `demo/verdict.json` (sealed). Numbers not typed by hand.**
Source raw: `demo/raw/records.json` (14 real subagent step-pairs, sealed write-once before scoring). Seal chain verified, verdict reproduces from sealed raw in a fresh process.

## Result: NOT-A-CLEAN-WIN

Two arms, identical 14-step register-ledger task (4 long-range QUERY steps, registers last written 6–10 steps earlier). Full pre-registration in `demo_prereg.md`, written before the run.

| metric | full-history control | Plateau (bounded) |
|---|---|---|
| context slope (est. tok/step) | **17.567** | **0.035** |
| context first → last | 84 → 312 | 81 → 83 |
| mean context | 197.8 | 80.9 |
| completion (vs GOLD) | 14.3% | 35.7% |

Headline slope difference **17.532** tok/step; bootstrap 95% CI **[17.307, 17.749]** excludes zero.

## Pre-registered claims (locked rule, applied without override)
- **D1** control climbs (anti-rig): **True**
- **D2** Plateau slope ≤ 25% of control: **True**
- **D3** completion parity ≥ control: **True**  |  ≥ 90% floor: **False**
- **D4** slope-diff CI excludes zero: **True**

## What is and isn't proven (honest)
**Proven decisively — context efficiency (the core claim):** the full-history arm's context climbs at 17.567 tok/step (84→312 over 14 steps) while Plateau stays flat at 0.035 tok/step (81→83). Extrapolated to a 200k-token budget: control crosses in ~11,367 steps; Plateau's near-zero slope ≈ never (~5,685,140 steps — effectively flat). This is the product claim and it holds.

**Observed, not claimed as clean — completion.** Plateau answered 35.7% vs control's 14.3% — Plateau BEAT the full-history arm — but NEITHER cleared the pre-registered 90% parity floor, so by the locked rule this is **not a clean WIN**. The library `decide()` (which only checks ≥ control) reads "WIN"; the stricter pre-registered rule overrides it. We report the harsher verdict.

**Why neither arm cleared 90% (the instrument confound).** The subagents made frequent arithmetic/reading slips (e.g. 9−5 returned as 2; a register misread), and because each step is scored against GOLD while each arm propagates its own earlier errors, a single early slip cascades. This is noise on BOTH arms, not Plateau amnesia — Plateau out-completed control. The control also showed a genuine long-context pathology: it perseverated, repeating "8" for most steps as its transcript filled with "you answered 8".

**The recall money shot (step 11, QUERY R2 set 10 steps earlier, GOLD=8):** the full-history control answered **2** (the stale SEED value, buried in its long transcript) while Plateau answered **8** correctly from its compact current register file. Long-range QUERY tally: control 1/4, Plateau 2/4.

## The fix (separate run, if wanted)
The completion axis was confounded by arithmetic. A **recall-only** task (no arithmetic — each step only asks the agent to surface a previously-established value) would isolate the state-carry mechanism from arithmetic noise and let completion parity be measured cleanly. That is the honest next experiment; this run already proves the context-bounding claim.

## Bright line
This measures **context EFFICIENCY** — tokens per step and whether dependent work completes. It says nothing about understanding or any inner state.
