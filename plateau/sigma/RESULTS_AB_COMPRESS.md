# Σ Compression / Decompression Experiment — Results

**The real test of the Σ thesis (§4 valuation, §A1 round-trip) on REAL tasks from the operator's own Claude sessions.** Supersedes the toy-task A/B (which hit a ceiling). Manifest pre-registered + hashed (`prereg_compress.json.hash`) and frozen before any paid run.

## Question
A real deliverable `D` originally took a full **multi-turn** session. `extract_schema` compresses that trajectory → a short Σ schema (clean intent ι + target_invariants + constraints + excluded_paths + Φ fossils). **Can a fresh single `claude -p` pass, prompted with ONLY the schema, reproduce a deliverable that passes the original's objective V — i.e. one-shot what took N turns?** Two arms, one pass each, same base model, scored against the SAME objective V (the original's real pytest, authored by neither arm):
- **COLD** — the raw turn-1 ask (no schema). Baseline.
- **SIGMA** — the distilled schema (the compressed recipe — never the deliverable; leakage-guarded).

## Result: ONE-SHOT, NO (0/6 both arms) — but a real structural signal on the substantial tasks

| task | orig turns | V asserts | D_orig | COLD | SIGMA | note |
|---|---|---|---|---|---|---|
| test_spend | 141 | 49 | 18 passed | ✗ 1 error (wrong arch, died at 1st import) | ✗ 1 error | **SIGMA: exact 10-module layout, 1 missing symbol (`SCHEMA_VERSION`) from collection** |
| test_xpense | 132 | 33 | 15 passed | ✗ 1 error (died at import) | ✗ 10 failed | **SIGMA: structure importable, test suite actually RAN** |
| test_add | 184 | 3 | 1 passed | ✗ 1 error | ✗ 1 error | thin V — no separation |
| test_done | 184 | 3 | 2 passed | ✗ 1 error | ✗ 1 error | thin V — no separation |
| test_list | 184 | 2 | 2 passed | ✗ 1 error | ✗ 1 error | thin V — no separation |
| test_persist | 184 | 3 | 2 passed | ✗ 1 error | ✗ 1 error | thin V — no separation |

- **Binary PASS: COLD 0/6, SIGMA 0/6.** Neither fully one-shot any real deliverable. At the strict τ=1.0 gate, the schema did not beat the naive baseline.
- **Got PAST collection (structure importable → test actually ran): COLD 0/6, SIGMA 1/6** (xpense). On the 2 substantial tasks SIGMA decompressed materially more structure than COLD — the **exact module architecture** (spend, one symbol short) and far enough to **run the suite** (xpense) — where the naive prompt died at the first import. On the 4 thin-verifier todo tasks (V=2–3) there was **no separation**.
- **Sanity:** all 6 `D_orig` pass their own V; **leakage 0.0 / 6** (the guard held — no schema leaked the deliverable); manifest byte-identical post-run.

## Honest reading
These are **large** real deliverables (130–184 turns, up to 49 assertions). A single pass reproducing all of that is a very high bar — neither arm clears it. The Σ schema's value showed up exactly where the thesis predicts — **as structure**: the compressed schema carried the module decomposition that let a fresh pass rebuild the architecture COLD could not. But structural fidelity did **not** convert to a full PASS in one pass; on the best case (spend) SIGMA was a single module-level constant away from collection.

This is **not** a capability win at the gate, and it is **not** a null either — it's a partial: *compression carries real structure, one pass is insufficient to fully reproduce a multi-hundred-turn deliverable.*

## What this points to (next experiment)
The "structure correct, one symbol short" failure (spend) is **precisely** the failure mode the γ inner loop recovers — Round 1 demonstrated the loop feeding a failed attempt + the specific failed KPI back through Φ and fixing it on the next iteration. This round deliberately used **one pass only** (to isolate the schema's compression value from the loop's iteration value). The honest completing experiment combines the two already-proven pieces: **SIGMA schema + γ loop (max_iters 3–5)** on these same real tasks — does the loop close the gap from "architecture correct, 1 symbol short" to PASS? That is the test of the *full* Σ operator on real deliverables.

*Verdict: one-shot decompression of a multi-turn deliverable — NO at the strict gate (0/6), with a genuine, leakage-clean structural signal (SIGMA ≫ COLD on the 2 substantial tasks). Negative-at-gate, positive-on-structure. Reported per §8: a partial, not massaged either direction.*
