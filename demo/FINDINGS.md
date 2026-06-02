# Plateau demos — findings, one by one

Every demo is pre-registered, sealed write-once before scoring, and recompute-verifiable
from its own `raw*/manifest.jsonl`. Verdicts below are what the **locked rules computed** —
including the ones that deny a win. Bright line: these measure **context efficiency and
recall** (and, for C4, trajectory structure) — nothing about understanding or phenomenality.

| demo | what it tested | sealed finding | status | recompute | paper |
|---|---|---|---|---|---|
| **demo1** (`demo_*`, `verdict.json`) | context-growth slope on a dependent **arithmetic** chain | slope win holds (Plateau flat vs control climbing) and Plateau **beat** control on completion, but neither arm cleared the 90% parity floor — an **instrument confound** (noisy subagent arithmetic + GOLD-vs-error-propagation) swamped the completion axis. NOT "Plateau forgets." | **NOT-A-CLEAN-WIN** | sealed `raw/` | motivates C3; why recall-only demos exist |
| **demo2** (`verdict2.json`) | recall accuracy vs fact-distance (sequential values, sorted file) | Plateau far-recall **0.667** missed its pre-registered 0.70 floor by one query (2 misses were a layout artifact). Directionally favored Plateau (flatter+higher: drop 0.083 vs control 0.50; far 0.667 > control 0.5). n small (far bin=6). | **NULL (near-miss)** | sealed `raw2/` | recall receipt |
| **demo3** (`verdict3.json`) | same, confounds removed (random values, shuffled layout, bigger far bin) | Control recall did **not** degrade (near 1.0, far 0.8 — only 0.20, under the 0.25 anti-rig margin); facts didn't sink deep enough to score a degradation. Plateau answered **18/18** at every distance on ~120 tok vs full-history ~2,138 tok (~18×). | **UNSCORABLE** | sealed `raw3/` | recall receipt; source of the README ~18× token figure |
| **demo4** (`demo4_arms`, `verdict4.json`) | first **real-workload** 3-arm test (command_output end-to-end) | Full-history (arm1) reached the success check in **2 steps**, so its context never materially climbed → the efficiency comparison had no range. Autonomy: pre-committed NULL. | **UNSCORABLE** (efficiency) | sealed `raw4/` | **C6 predecessor** |
| **demo6** (`demo6_arms`, `verdict6.json`) | 2-arm real-code efficiency, re-registered at ≥5-layer serial depth (verification chain) | **EFFICIENCY WIN** — arm1 full-history 368→37,321 tok (slope **6839.2**); arm2 Plateau 514→1,555 (slope **203.34** = 3.0% of arm1, ~34× margin); both reach PASS (32/36 tests), 0 rework — **completion parity**. | **WIN** | recompute PASS, 38 sealed files (`raw6/`) | **C6** |
| **demo6b** (`demo6b_arms`, `verdict6b.json`) | demo6 re-run, **isolation-clean** (SUPERSEDES raw6) | **EFFICIENCY WIN** — arm1 365→37,405 (slope **6859.7**); arm2 508→1,075 (slope **103.0** ≈1.5% of arm1); both PASS (32→36 tests), 0 rework — parity. | **WIN** | recompute PASS, 38 sealed files (`raw6b/`) | **C6 (primary)** |
| **C4** (`c4_readout.md`, in `reports/continuum/c4/`) | state-trajectory geometry (effective dimensionality), multi-dim RelationalState | continuum participation ratio **2.65** vs cold-start **4.72** (run2, primary); 2.33 vs 4.82 (prior). Replicated across two runs; drift confound tested (survives). | **WIN** | run2 recompute-verified, intact | **C4** (see pointer) |

## What the series shows (honest synthesis)

1. **The decisive, unambiguous claim is bounded context.** In every demo the full-history
   arm climbs toward the ceiling while Plateau stays flat. demo6/demo6b move this from a toy
   to **real multi-module code**: ~6840 tok/step vs ~103–203 tok/step (≈1.5–3%) at completion
   parity — the C6 result.
2. **No recall *penalty* (demo3): 18/18 at every distance** on ~18× less context. But we did
   **not** prove a recall *advantage*: demo2 = NULL, demo3 = UNSCORABLE (the baseline recalled
   too well to score a degradation). We publish the NULL/UNSCORABLE rather than lengthen the
   chain until the baseline breaks.
3. **The discipline killed its own headline and caught its own fabrication.** demo1's
   arithmetic confound forced the recall-only redesign; and the integrity apparatus caught a
   fabricated "PASS" (the C4 fork-#11 episode) and, separately, a live tamper on a sealed C4
   file. See `examples/continuum_story.md` and `INTEGRITY.md`.

## Verifying any row
```bash
cd plateau
uv run --with numpy python demo/recompute_demo6.py     # demo6  → RECOMPUTE PASS, EFFICIENCY=WIN
DEMO6_RAW=$PWD/demo/raw6b DEMO6_VERDICT=$PWD/demo/verdict6b.json \
  uv run --with numpy python demo/recompute_demo6.py   # demo6b → RECOMPUTE PASS
```
Each `verdict*.json` is reproduced from the sealed `raw*/` bytes in a fresh process; the
locked scorer's hash is pinned and re-checked at score time.
