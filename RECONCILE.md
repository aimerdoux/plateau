# RECONCILE — paper ↔ sealed artifacts (flag-only; do NOT silently edit the paper)

Diffs the paper draft (`paper/the-integrator-2026-06-02.pdf`) against the **sealed verdict files**
and lists every mismatch as **[paper says X / sealed says Y]** for the operator to fix in the paper
source. **No paper number is edited here** — the paper PDF is not modified and its source is not in
this repo.

This file **extends** [`PAPER_RECONCILIATION.md`](PAPER_RECONCILIATION.md) (which resolved the §8
`[value]` placeholders for C3/C4/C6). Those resolutions are **re-verified against the current sealed
verdicts** below and carried forward; the **new** material is the **C9 labeling mismatch** and the
**§9 citation audit**.

The paper deliberately writes its empirical figures as `[value]` placeholders "where any figure still
needs reconciliation against the sealed verdict" (§8.1) — so most of §8 is *flagged by the paper
itself*; this file resolves each flag to a sealed number.

## C3 — compression at completion parity (synthetic)
Sealed: `reports/continuum/c3_10/verdict.json` (WIN).

| paper (§8.1) | sealed | status |
|---|---|---|
| `[10]`-step chain | 10 dependent steps | ✓ resolves |
| slope ratio `∼[80]×` | 22.903 / 0.285 = **80.4×** | ✓ resolves |
| control slope `≈[22.9]` | 22.903 | ✓ resolves |
| signal slope `≈[0.285]` | 0.285 | ✓ resolves |
| carried-token reduction `∼[18]×` | **MIS-ATTRIBUTED** | **[paper: 18× is C3 / sealed: C3's carried blob is flat 139→143 tok vs control prompt 113→317 ≈ 2.2×; the 18× is the *recall demo3* (≈2,138 vs ≈120 tok), not C3]** |

→ **Correction C3-1 (carried over):** state slope-ratio (80×) and token-ratio separately; the 18× is
demo3, not C3.

## C4 — low-dimensional state trajectory
Sealed: `reports/continuum/c4/run2/verdict.json` (WIN) + `c4/verdict.json` (prior run).

| paper (§8.1) | sealed | status |
|---|---|---|
| continuum PR `∼[2.3--2.65]` | run2 **2.6502**, prior **2.3325** | ✓ resolves |
| cold-start PR `∼[4.7--4.8]` | run2 **4.7163**, prior **4.8236** | ✓ resolves |
| "replicated across two independent runs" | run2 (self-produced) + prior | ✓ resolves |

→ No numeric correction. **Integrity note:** the *prior* `c4/raw/emissions.json` carried a `#tamper`
drill marker that recompute flags; the C4 claim rests on the intact, independently-produced **run2**.
(Per STATUS, the drill was operator-re-baselined to the genuine original and global recompute now PASSes.)

## C6 — bounded context on real code (efficiency WIN)
Sealed: `plateau/demo/verdict6.json` (demo6) and `plateau/demo/verdict6b.json` (demo6b, isolation-clean).
**The paper's §8.1 C6 numbers are demo6; demo6b supersedes demo6.**

| paper (§8.1, = demo6) | sealed demo6 | status |
|---|---|---|
| full-history `[368]→[37,321]`, slope `≈[6839]` | slope **6839.2** (endpoints in `raw6`) | ✓ resolves |
| Plateau `[514]→[1,555]`, slope `≈[203]` | slope **203.34** | ✓ resolves |
| "≈3% … a `∼24×` gap" | 203.34 / 6839.2 = 2.97% ⇒ **~34×**, not 24× | **[paper: ≈3% AND ~24× / sealed: 3% ⇒ ~34× — internally inconsistent]** |
| `[33]` / `[34]` tests, `[38]` sealed files | demo6 arm1 33 / arm2 34; 38 files | ✓ resolves |
| Fig 3 caption "∼100× over six steps" | absolute growth 37,405/365 = **102×** (≠ slope gap) | ✓ resolves — this is *absolute context growth*, a distinct quantity from the slope gap; OK as written |

→ **Correction C6-1 (carried over):** "≈3%" ⇒ ~34× gap (not 24×) for demo6.
→ **Correction C6-2 (carried over, recommended — supersede with demo6b):**
   from `verdict6b.json` + `raw6b/*_completion.json` (sealed):
   full-history **365 → 37,405** (slope **6859.7**), Plateau **508 → 1,075** (slope **103.0 ≈ 1.5%**,
   a **66.6×** slope gap), tests **arm1 32/32, arm2 36/36**, both PASS zero rework, parity.
   *(Note: paper §8.1's "[33]/[34] tests" are demo6; demo6b's are 32/36 — update if superseding.)*

## C9 — **labeling mismatch (NEW; the substantive one)**

The repo ran and sealed a cycle it calls **C9** (`cycle9_prereg.md` / `c9b`): the **reload-correspondence**
experiment — sweep gap × correspondence, locate the boundary. Sealed verdict
`reports/continuum/c9b/raw/verdict.json`: **CORRESPONDENCE-DOMINATES**, vertical boundary,
high_mean_corr **0.975** ≥ 0.55 > broken **0.048**, corr_axis_effect **1.0**, gap_axis_effect **0.0**,
perf_gap **1.0**.

But in the **paper's §8.2 forward program**, the labels are different:

| paper §8.2 label | paper description | repo reality |
|---|---|---|
| paper **C9** = "the rate–distortion knee" | sweep the signal **rate** (β/IB multiplier), trace next-action distortion: knee or smooth slope? | **NOT run in the repo.** No sealed rate-sweep cycle exists. |
| paper **C11** = "reload-correspondence (proposed)" | sweep gap × correspondence: vertical (correspondence) or horizontal (cadence) boundary? "Null: correspondence dominates." | **This is what the repo ran as "C9" (c9b)** → CORRESPONDENCE-DOMINATES (vertical). |

→ **FLAG C9-1 (operator decision required):** **[paper: the reload-correspondence / vertical-boundary
experiment is C11, listed as not-yet-run; the paper's C9 is a different experiment (rate–distortion
knee), also not-yet-run / sealed: the repo executed the reload-correspondence experiment under the
label "C9" (c9b) and it returned CORRESPONDENCE-DOMINATES].** The repo's sealed result maps to the
**paper's C11**, and confirms the paper's stated C11 weighted-null direction ("correspondence
dominates, pure cadence barely matters"). The paper's own **C9 (rate–distortion knee) remains unrun.**
The operator must decide whether to (a) relabel the repo cycle to C11 in the paper's terms, (b) promote
the result from "forward program / not-run" to a completed result, and (c) keep the paper's C9 (knee)
in the forward program. **Do not silently renumber either side.**

## §8.2 forward-program status (paper says "none run" — mostly correct)

| paper §8.2 cycle | paper status | repo status (sealed/source) | match? |
|---|---|---|---|
| C5 frequency vs structured | not run | PREPARED, HALTED (`c5_freq.py`) | ✓ |
| C7/C8 symbolic-index faithfulness | not run | PREPARED, HALTED (`c7_symbolic.py`, `c8_teach.py`) | ✓ |
| C9 rate–distortion knee | not run | **not run** | ✓ |
| C10 attracting slow manifold | not run | not run | ✓ |
| C11 reload-correspondence | not run | **RUN as repo-C9 (c9b) → CORRESPONDENCE-DOMINATES** | ✗ — see FLAG C9-1 |

## §9 Related work — citation audit

The paper's **References** list keys only two sources, both real and resolvable:
- **[1]** R. K. Mehra, *On the identification of variances and adaptive Kalman filtering*, IEEE TAC
  15(2):175–184, **1970** — real, resolvable.
- **[2]** P. R. Bélanger, *Estimation of noise covariance matrices for a linear time-varying stochastic
  process*, Automatica 10(3):267–275, **1974** — real, resolvable.

The §9 prose **names** eight further bodies of work that are **not yet keyed to references** — the
paper's own "Citation note" states this ("They are named, not yet keyed"). Each names a real research
line, but **none has a formal reference entry**, so none currently "resolves" as a citation:

| named in §9 | real research line? | reference entry present? |
|---|---|---|
| gist tokens | yes (Mu et al., learning to compress prompts) | **MISSING — must be added** |
| AutoCompressors | yes (Chevalier et al.) | **MISSING** |
| ICAE (in-context autoencoder) | yes (Ge et al.) | **MISSING** |
| information bottleneck | yes (Tishby et al.) | **MISSING** |
| β-VAE | yes (Higgins et al.) | **MISSING** |
| Gallego / Vyas population manifolds | yes (low-D neural population dynamics) | **MISSING** |
| Turpin / Lanham CoT (un)faithfulness | yes | **MISSING** |
| graph-constrained decoding | yes | **MISSING** |
| Moschella relative representations | yes | **MISSING** |

→ **FLAG REF-1:** every §9 named result needs a full, verified reference added before submission. I did
**not** invent arXiv IDs or bibliographic entries — the operator/author must supply and verify them.
(All nine are recognizable real lines of work; the gap is keying, not existence.)

## Figures (repo ↔ paper)

| paper figure | kind | repo asset | status |
|---|---|---|---|
| Fig 1 (the integrator diagram) | conceptual | — | PDF-only; not a sealed-data plot, nothing to reconcile |
| Fig 2 (projection / QΠ) | conceptual | — | PDF-only; nothing to reconcile |
| Fig 3 (C6 bounded context) | empirical | `demo/context_per_step6b.png` | regenerated from sealed `raw6b`; agrees with `verdict6b.json` |
| Fig 4 (C4 low-dim trajectory) | empirical | **none** | **[repo ships no C4 trajectory chart]** — operator may want one generated from sealed `c4/run2/emissions.json` for repo↔paper parity |

## Status / what the operator does

- This file **flags**; it does not edit the paper. Paste corrections C3-1, C6-1, C6-2 and resolve
  FLAG C9-1 / FLAG REF-1 into the paper **source** (not in this repo — only the PDF is here).
- All non-placeholder, non-flagged claims are verified against the cited sealed artifacts and are
  recompute-verifiable (`make recompute`).

---
— [D-014] · paper-vs-sealed diff, flag-only (data **GROUNDED**, paper **UNCHANGED**) · **LOCAL** · /halt
