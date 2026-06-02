# Paper ↔ sealed-artifact reconciliation — "The Integrator" (plateau020626.pdf)

Resolves every `[value]` placeholder in the paper's §8 against the sealed source of truth,
and flags three real corrections. The **paper source is not in this repo** (only the PDF in
`~/Downloads/`); this file is the drop-in reconciliation + corrected sentences to paste into
the source. Every value below is recompute-verifiable from the cited sealed artifact.

## C3 — compression at completion parity (synthetic)
Source: `reports/continuum/c3_readout_n10.md` (sealed; recompute PASS, 95 files/3 manifests).

| paper bracket | resolved | check |
|---|---|---|
| `[10]`-step dependent chain | 10 | ✓ (V1..V10 = 6,11,33,29,58,69,62,248,257,244) |
| control slope `≈[22.9]` | 22.9 tok/step | ✓ |
| signal slope `≈[0.285]` | 0.285 tok/step | ✓ |
| slope ratio `∼[80]×` | 22.9 / 0.285 = **80.4×** | ✓ |
| carried-token reduction `∼[18]×` | **✗ MIS-ATTRIBUTED** | see correction |

**Correction C3-1.** C3's *carried-token* figure is **not** 18×. C3's signal blob is flat
(`139→143` tok) while control prompt tokens climb `113→317` → ~**2.2×** at the last step
(the win is in the *slope*, 80×, not the absolute token ratio at this toy scale). The **18×**
belongs to the **recall demo (demo3 / README)**: full-history ~2,138 tok vs Plateau ~120 tok.
*Drop-in:* "…a slope ratio of ∼80× (control ≈22.9 vs signal ≈0.285); the carried signal stays
flat (~140 tok) against a control prompt that climbs to 317 (~2.2× at step 10). (The ∼18×
carried-token reduction is the separate recall demo, not C3.)"

## C4 — low-dimensional state trajectory
Source: `reports/continuum/c4/run2/verdict.json` (intact, recompute-verified) + `c4/verdict.json` (prior).

| paper bracket | resolved | check |
|---|---|---|
| continuum PR `∼[2.3--2.65]` | run2 **2.65**, prior **2.33** | ✓ |
| cold-start PR `∼[4.7--4.8]` | run2 **4.72**, prior **4.82** | ✓ |
| "replicated across two independent runs" | run2 (self-produced) + prior | ✓ |

No correction. (Drift confound tested: on-task-only cold PR 2.82 vs continuum 2.02 — gap survives.)
**Integrity note:** the *prior* run's `c4/raw/emissions.json` currently carries an appended
`#tamper` marker (data intact) and is flagged by recompute — operator-domain restore pending.
The C4 claim rests on the intact, independently-produced run2.

## C6 — bounded context on real code (efficiency WIN)
Source: `plateau/demo/verdict6.json` (now populated; recompute_demo6 PASS, 38 files) + readouts.
**The paper's C6 numbers are demo6.** demo6b (isolation-clean) **supersedes** demo6.

| paper bracket | resolved (demo6) | check |
|---|---|---|
| full-history `[368]→[37,321]` | 368 → 37,321 | ✓ |
| full-history slope `≈[6839]` | 6839.2 | ✓ |
| Plateau `[514]→[1,555]` | 514 → 1,555 | ✓ |
| Plateau slope `≈[203]` | 203.34 (≈**2.97%** of full-history) | ✓ |
| `[33]` and `[34]` tests | arm1 33, arm2 34 | ✓ |
| `[38]` sealed files | 38 | ✓ |
| "≈3% … a `∼24×` gap" | **✗ INCONSISTENT** | see correction |

**Correction C6-1 (internal inconsistency).** "≈3%" and "~24× gap" can't both hold: 203.34 /
6839.2 = 2.97% ⇒ a **~34× gap**, not 24×. Use ~34× (demo6).

**Correction C6-2 (supersession — recommended).** Cite **demo6b** as primary (latest,
isolation-clean; `verdict6b.json`, recompute PASS, 38 files): full-history 365→37,405 (slope
**6859.7**), Plateau 508→1,075 (slope **103.0** ≈**1.5%**, a **~67× gap**), tests 32/36, parity.
Keep demo6 as the corroborating predecessor. *Drop-in:* "…the full-history arm climbed
365→37,405 tokens over six dependent steps (slope ≈6,860), while Plateau stayed bounded
508→1,075 (slope ≈103, ≈1.5%, a ~67× gap), both reaching PASS (32 and 36 tests, zero
rework) — completion parity (demo6b, isolation-clean; supersedes the demo6 predecessor)."

## §7 — the integrity apparatus episode
The paper's §7 (manifest filename the recompute glob didn't scan → false "recompute PASS" →
resuming run declined to adopt it → reproduced the finding → closed the coverage gap → operator
verified in a real shell incl. a tamper returning FAIL naming the file) **matches the fork-#11
episode exactly.** Receipts: `reports/continuum/fork_log.md` (#11 injected; #12 the grounding),
`reports/continuum/c4/{run2,}` manifests.
**New corroboration (this session):** a *second* live episode — a `#tamper` marker appended to
the sealed `c4/raw/emissions.json` was caught by recompute (named the file) and **not
self-healed** by the agent (restore is operator-domain). The apparatus bit twice.

## Status
- Paper source: **not in repo** — paste the drop-in sentences above into the source (likely the
  `plateau paper with images.zip` / your LaTeX), or hand this file to the author.
- All non-placeholder claims verified against sealed artifacts; the three corrections (C3-1,
  C6-1, C6-2) are the only substantive edits the data requires.
