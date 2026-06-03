# Driver A/B — the real adapter, measured on live `claude -p` workers

**Verdict: WIN** — by the locked `plateau.metrics.decide` rule, applied without override.
This is the result the failed in-session plugin A/B could not be: the **driver owns the
message loop**, so it actually bounds context — a passive `UserPromptSubmit` hook cannot
(append-only).

## What ran
A strictly serial 6-layer verification feature (`vchain/l1..l6.py`, each depends on the
prior), built by **fresh headless `claude -p` workers — one per step** (scoped to
Read/Write/Edit). Two arms, identical task head; only the carried payload differs:
- **control** — each step's prompt carries the full prior transcript.
- **signal** — each step's prompt carries only `inflate(signal)` (the bounded
  goals/stance/lessons/pointers/gated-facts); facts gated between steps by file-hash.

## Result (reproduces from sealed raw)

| arm | per-step context tokens | slope | completion |
|---|---|---|---|
| control (full history) | 152 → 476 → 1210 → 2671 → 5607 → **11,482** | **2100** | **6/6** |
| signal (bounded) | 172 → 234 → 290 → 347 → 403 → **460** | **57** (~2.7%, **~37× gap**) | **6/6** |

- context flattened ≤25% of control ✓ · completion parity ✓ · anti-rig control-climbs ✓ → **WIN**.
- **Not hollow parity:** the signal-arm `l6.py` does `from vchain import l5` and folds the
  upstream seal — a worker that **never saw the transcript** built the correct *dependent*
  layer from the compact signal alone. That is the "no amnesia" claim, demonstrated.

## Integrity
- Sealed write-once **before** scoring; verdict reproduces in a fresh process.
- `recompute` PASS. One disclosed fix: the run's first manifest was mis-rooted (paths relative
  to `driver_ab/` instead of the repo root — a runner bug, now fixed); the **same bytes** were
  re-sealed with repo-root paths (file hashes identical before/after — content untouched).
- Sealed source of truth (bmacp research tree, not duplicated here):
  `reports/continuum/driver_ab/{raw,verdict.json,integrity_manifest.jsonl}`;
  prereg `reports/continuum/plateau_driver_ab_prereg.md`; runner
  `experiments/continuum/run_driver_ab.py` (lock-gated, seal-before-score).

## Honest caveats
- **n=1, 6 steps.** A repeat run / longer chain would strengthen it; the pre-registered null
  (~0.40 it's a clean WIN) was live and the data returned WIN.
- Completion = the layer file is present **and** imports its predecessor (`l6`→`l5`), not a
  full functional test of every layer's logic.
- The bound is real because the driver controls each worker's input; it is an **orchestration**
  property (what the demos always measured), now delivered by an autonomous adapter.

## Bright line
Measures context **efficiency at completion parity**. Silent on understanding or any inner state.
