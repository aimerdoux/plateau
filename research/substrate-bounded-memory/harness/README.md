# D-036 harness — no-LLM Stages 0–2

Pure-numpy implementation of the sealed [`../PREREG.md`](../PREREG.md) run. **No LLM
touches any of this** — Stages 0–2 carry zero prompt-injection surface. Every scored
run echoes the sealed `PREREG.md` sha256 and seals its raw output write-once under
`../raw/` via `plateau.integrity` (results stay local/unpublished until operator go).

## Files
| file | what |
|---|---|
| `cgle.py` | 2D CGLE pseudo-spectral **ETD2** integrator + periodic vortex seeder (image-sum, no boundary seams) + phase-winding defect detector |
| `items.py` | synthetic 768-dim vectors → fixed sealed random projection → `(x, y)` + net-neutral charge (median split). H1 is semantics-agnostic, so no embedding model is needed |
| `sealutil.py` | prereg-hash echo + seal-before-score wrapper |
| `mock_verify.py` | **free** correctness self-tests (PREREG guard) — detector on known configs, periodic seeder, ETD2 2nd-order convergence, seal round-trip + tamper detection |
| `run_calibration.py` | **Stage 1** calibration gate: one pair, 10·T steps, PASS iff it persists with zero nucleation |
| `stage0_tau.py` | **Stage 0** annihilation law τ(r)=α·r² → `r_min`, `N_pack` (the REFUTED-by-geometry check) |
| `h1_sweep.py` | **H1** capacity sweep: field vs **B1** (lossless dict at same ρ) vs **B2** (FIFO); `N_crit` per arm. `--smoke` for a tiny unsealed pipeline check |

## Run order (each gates the next)
```bash
cd research/substrate-bounded-memory/harness
PYTHONPATH=../../.. python mock_verify.py        # free; must pass first
PYTHONPATH=../../.. python run_calibration.py     # ~11 min; PASS admits (b,c)
PYTHONPATH=../../.. python stage0_tau.py          # τ(r) → N_pack
PYTHONPATH=../../.. python h1_sweep.py --smoke     # ~6 min pipeline check (unsealed)
PYTHONPATH=../../.. python h1_sweep.py             # ~3 h sealed sweep (8 k × 20 seeds)
```

Requires `numpy` (research-only; the Plateau core stays stdlib-only).

## Re-verify a sealed run
```python
from plateau.integrity import Manifest
m = Manifest("research/substrate-bounded-memory/raw/manifest.jsonl")
print(m.verify_chain()); print(m.verify_files("research/substrate-bounded-memory/raw"))
```
