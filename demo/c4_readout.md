# C4 — low-dimensional state trajectory (geometry) · pointer

C4 is the paper's third prior result. Unlike the efficiency/recall demos here, C4's
sealed artifacts live in the **continuum research tree**, not in `plateau/demo/`. This file
is a pointer so Plateau's evidence set matches the paper without duplicating (and risking
drift on) sealed bytes.

**Finding (grounded):** the carried-signal state trajectory occupies materially **fewer
effective dimensions** than cold-start scatter, replicated across two independent paid runs.

| run | continuum PR | cold-start PR | verdict | status |
|---|---|---|---|---|
| run2 (self-produced, primary) | **2.65** | **4.72** | WIN | sealed + recompute-verified, intact |
| prior run (corroborating) | 2.33 | 4.82 | WIN | sealed; raw currently flagged — see note |

Both: cold eff_rank 5 (scorable multi-dim space), continuum trajectory moves (path ≈11.9,
not a static dot), C4.1∧C4.2∧C4.3 hold. The off-task drift confound was tested, not
asserted: with the 2 drifted cold states removed, on-task-only cold PR 2.82 vs continuum
2.02 — the gap survives.

**Sealed source of truth (do not duplicate):**
- `reports/continuum/c4/run2/{emissions,verdict,cycle4_readout}.json/md` (+ `integrity_manifest.jsonl`)
- `reports/continuum/c4/{raw/emissions.json,verdict.json,cycle4_readout.md}` (prior run)
- prereg `reports/continuum/cycle4_prereg.md`

**Integrity note (honest):** the *prior* run's `raw/emissions.json` was modified after
sealing (a trailing `#tamper` marker appended; emission data unchanged) and is currently
flagged by `experiments.recompute` — an operator-domain restore is pending. The C4 finding
does **not** depend on it: `run2` is independently produced, intact, and recompute-verified,
and replicates the result.

**Bright line:** this measures trajectory **structure** (effective dimensionality) only — it
is silent on phenomenality, exactly as the efficiency/recall demos are silent on understanding.
