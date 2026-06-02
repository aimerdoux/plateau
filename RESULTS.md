# RESULTS — every sealed cycle, its verdict, and how to re-verify it

Every number here is copied from a **sealed verdict file** (write-once, hash-recorded in an
integrity manifest), never from memory. Each row gives a one-line command that re-derives the
result from the sealed raw in a fresh process. If a command prints `PASS` / reproduces the verdict,
the row is trustworthy; if it prints `FAIL`, something was tampered and the row should be distrusted.

**Two roots.** The **plateau demos** ship *in this repo* (`demo/`) and are self-contained — run their
commands from the **repo root**. The **continuum cycles (C3/C4/C9)** live in the parent research tree
`bmacp-trunk` (under `reports/continuum/`), are **not part of this package**, and are recompute-verifiable
from the **parent root**. Both kinds of path are shown below as written.

## The headline, stated narrow and true

**Bounded context at no recall penalty, on real multi-step code.** On a strictly serial ≥5-layer
feature built on this repo (demo6b, isolation-clean), the full-history arm's context climbed
**365 → 37,405 tokens** over six dependent steps (slope **6859.7 tok/step**) while the Plateau arm
stayed bounded **508 → 1,075** (slope **103.0 tok/step ≈ 1.5%** of full-history — a **66.6×** lower
growth slope), and **both arms reached PASS with zero rework** (full-history 32/32 tests, Plateau
36/36). Completion parity held. Source: [`demo/verdict6b.json`](demo/verdict6b.json) (slopes) +
[`demo/raw6b/*_completion.json`](demo/raw6b/) (endpoints, test counts). It is an **efficiency**
result — cheaper, not smarter. See "What this is NOT" in the [README](README.md).

## Plateau demos (in this repo — run from the repo root)

| demo | what it tests | verdict | key sealed numbers | re-verify (repo root) |
|---|---|---|---|---|
| **demo6b** (raw6b) | bounded context on **real code** | **EFFICIENCY WIN** | arm1 slope 6859.7 vs arm2 103.0 (≤25% bar; 1.5%); arm1 365→37,405 / 32 tests, arm2 508→1,075 / 36 tests; parity | `DEMO6_RAW=demo/raw6b DEMO6_VERDICT=demo/verdict6b.json python demo/recompute_demo6.py` |
| demo6 (raw6) | same, predecessor | EFFICIENCY WIN | arm1 slope 6839.2 vs arm2 203.34 (≤25%); parity | `python demo/recompute_demo6.py` |
| **demo4** | 3-arm real workload | **EFFICIENCY NULL / AUTONOMY NULL** | arm1 929.0, arm2 310.5 (not ≤25%); arm3 778.0 ties arm2 (steps 3=3, errors 0=0) | `python demo/recompute_demo4.py` |
| **demo1** | context-slope at parity (arithmetic) | **NOT-A-CLEAN-WIN** | control slope 17.567 vs plateau 0.035; CI [17.307, 17.749] excludes 0; completion 0.3571 > 0.1429 but neither cleared the 0.90 floor | `python demo/score_demo.py` (re-scores from sealed `demo/raw/records.json`) |
| **demo2** | recall vs fact-distance | **NULL (near-miss)** | far-recall plateau 0.6667 vs control 0.5 (overall 0.7857 vs 0.7143); missed own 0.70 far floor by one query | `python demo/score_demo2.py` (re-scores from sealed `demo/raw2/records.json`) |
| **demo3** | recall, confounds removed | **UNSCORABLE** | plateau recall 1.0 every bin; control near 1.0 / far 0.8 — degraded only 0.20 < the 0.25 anti-rig margin; control prompt 98→2,138 vs plateau 71→120 | re-score from sealed `demo/raw3/records.json` (`run_demo3.py` scorer) |

These demos carry their own write-once manifests (`demo/raw*/manifest.jsonl`); the recompute scripts
re-derive each `context_tokens` from the sealed prompt bytes, re-hash every file, and reproduce the
verdict. demo6b verified this session: **PASS, 38 sealed files**. demo4: **PASS, 27 sealed files**.

## Continuum cycles (parent research tree `bmacp-trunk` — run from the parent root)

| cycle | what it tests | verdict | key sealed numbers | sealed path | re-verify (parent root) |
|---|---|---|---|---|---|
| **C3** (n=10) | context-growth slope at parity (synthetic) | **WIN** | control 22.903 vs signal 0.285; slope-diff 22.618, CI [21.941, 23.128] excludes 0; completion 1.0 both | `reports/continuum/c3_10/verdict.json` | `python -m experiments.recompute` (integrity) |
| C3 (n=3) | same, fewer steps | INCONCLUSIVE | control 79.5 vs signal 10.0; CI [0.0, 81.0] **includes 0** | `reports/continuum/c3/verdict.json` | `python -m experiments.recompute` (integrity) |
| **C4** (run1) | state-trajectory effective dimensionality | **WIN** | continuum PR 2.3325 vs cold 4.8236 (diff 2.4911); path 11.0805 | `reports/continuum/c4/verdict.json` | `python -m experiments.recompute` (integrity) |
| **C4** (run2) | independent replication | **WIN** | continuum PR 2.6502 vs cold 4.7163 (diff 2.0661); path 11.9477 | `reports/continuum/c4/run2/verdict.json` | `python -m experiments.recompute` (integrity) |
| **C9** (c9b, clean) | correspondence vs cadence (gap × correspondence) | **CORRESPONDENCE-DOMINATES** (vertical) | high_mean_corr 0.975 ≥ 0.55 > broken 0.048; corr_axis_effect 1.0, gap_axis_effect 0.0; perf_gap 1.0 | `reports/continuum/c9b/raw/verdict.json` | `python -m experiments.continuum.c9b_run recompute` (verdict) |
| C9 (c9, leaky) | same, **superseded** | CORRESPONDENCE-DOMINATES | high 0.936 > broken 0.092 | `reports/continuum/c9/raw/verdict.json` | `python -m experiments.continuum.c9_run recompute` (verdict) |
| **C7** | symbolic-index faithfulness (relational traversal) | **NULL** (ceiling-tie — see below) | incumbent rejection **0.0** = challenger **0.0** (both **0/48** edges faithful); scrambled **1.0** (genuine deref, not surface-form); MI **0.0** (opaque); depth 4 | `reports/continuum/c7/raw/verdict.json` | `python -m experiments.continuum.c7_run recompute` (verdict) |

**Re-verify legend.** "verdict" = re-derives the verdict from sealed raw in a fresh process (demo4/6/6b,
C9b/C9/C7). "integrity" = the global recompute hash-verifies the sealed C3/C4 files are unaltered (it does
not re-run the C3/C4 scorer). Global recompute currently: **PASS over 121 sealed files across 9
manifests** (continuum cycles + gatebench + task-bank manifests under `reports/`); bank hash
`sha256:9e10c7a6…` unchanged.

## C9 specifically (the latest sealed cycle)

C9 sweeps the gap × correspondence plane and asks whether reload continuity is governed by
**correspondence** (state-match across the gap) or **cadence** (gap duration). The clean run of record
is **c9b** (`reports/continuum/c9b/raw/verdict.json`):

> **CORRESPONDENCE-DOMINATES** — vertical boundary. Continuity holds wherever correspondence is HIGH
> (mean corr **0.975** across all three gaps) and fails wherever it is BROKEN (mean **0.048**),
> *independent of gap size* (`gap_axis_effect 0.0`). The load-bearing guard cleared on the data
> (`perf_gap 1.0`): breaking correspondence cost task performance, so the carried signal was doing real
> work — not decorative.

`c9b` superseded the earlier `c9` (fork #26), whose subagent prompt **filenames** encoded the condition
(`gN_BROKEN_inflate_…`) and let ≥3 inflate subagents infer "BROKEN" and hedge. `c9b` re-ran the
identical experiment with **opaque random-token filenames** and a private cell→condition map the
subagent never sees; the verdict reproduced **more cleanly** (BROKEN corr 0.092 → 0.048, no hedging).
`c9/` is **retained immutable** as the leaky predecessor — not deleted, so the supersession is auditable.

> Naming note: the theory preprint labels this reload-correspondence experiment **C11** and reserves
> **C9** for a different (unrun) rate–distortion-knee sweep. The repo ran it under the label "C9". See
> [`RECONCILE.md`](RECONCILE.md) (FLAG C9-1) — the operator decides the final labeling.

## C7 — symbolic-index faithfulness (state it correctly: a ceiling-tie, NOT confabulation)

C7 asks whether an agent can faithfully traverse an **opaque** symbolic index — measured by an
**external gate's rejection rate** on proposed multi-hop traversals — or whether it confabulates
edges faster than the gate can ground them. Two arms over the same graph: a readable-label
incumbent and an opaque-symbol challenger; a permuted-binding **scramble control**.

> **NULL** — but read the numbers, not the scorer's stock prose. Both arms proposed **0/48
> non-existent edges** (rejection **0.0** each): *perfect faithful traversal*, including the
> opaque-symbol arm. The scramble control collapsed the challenger to **1.0** rejection, which
> **confirms it genuinely dereferenced the real symbols** (not surface-form tracking → not
> FALSIFIED). Symbols were opaque (MI **0.0** bits ≤ 0.20) and traversals were depth 4 (≥ 3).

The verdict is NULL **by the locked rule, without override** — but because the challenger could not
score *below* a **perfect incumbent**, i.e. a **tie at the faithful ceiling**, *not* the
pre-registered "confabulation outruns grounding" mechanism (which **did not occur**). The honest
bounding finding: **faithful traversal of an opaque symbolic index IS achievable** at depth 4 with
the adjacency visible; the comparative design simply had **no headroom** against a perfect
incumbent. The relational-structure direction is **alive but unproven** — the real test needs a
regime where text itself confabulates (deeper graphs, no visible adjacency, or memory pressure).
*(The locked scorer attaches a templated NULL reason that says "confabulates…"; that prose does not
fit this run — see [`RECONCILE.md`](RECONCILE.md), flagged for the next scorer version, not edited.)*

## Gate cost & disk footprint (gatebench — the second axis, sealed)

Every other result measured **tokens**; gatebench measures **wall-clock** and **disk**, so "efficient"
is shown on both axes. Source: `reports/continuum/gatebench/raw/{results,disk}.json` (sealed;
`python -m experiments.continuum.gatebench recompute` → PASS).

- **The shipped gate is cheap.** Re-grounding a carried fact via `file_hash` (the only live
  re-grounding the core implements) costs **~13 µs/fact** (per-fact median 0.0133 ms; marginal slope
  **0.0114 ms/fact**), **linear** in fact count — re-grounding a 50-fact signal takes **0.59 ms/step**.
  Classification **GATE-CHEAP**. So bounded context is cheaper on **time** as well as tokens.
- **Subprocess-backed grounding would be costly — but is NOT in the core.** A modeled `command_output`
  grounding (cheapest possible subprocess) costs **1.93 ms/fact** (~**145×** file_hash), **GATE-COSTLY**.
  The shipped core implements **only** `file_hash`; other kinds **fail closed without spawning** (see
  [`RECONCILE.md`](RECONCILE.md), the command_output gap).
- **Disk: three opposite-direction numbers.** Carried signal **~220 B/fact, O(facts)** (bounded);
  sealed integrity trail **1.03 MB / 339 files** and **grows** with every cycle (the audit cost);
  avoided full-history transcript **~149 KB** for one short real-code demo (the disk you didn't keep).

## Figures (generated from sealed data)

- `demo/context_per_step6b.png` — C6/demo6b bounded context (the headline figure; agrees with `verdict6b.json`).
- `demo/recall_vs_distance3.png` — demo3 recall vs distance (the no-recall-penalty figure).
- `demo/context_per_step4.png` — demo4 three-arm context.

The paper's empirical figures (Fig 3 = C6, Fig 4 = C4) should agree with these sealed numbers; see
[`RECONCILE.md`](RECONCILE.md) for the figure-by-figure mapping and the one C4 chart the repo does not
yet ship.

---
— [D-014] · all numbers sealed-sourced (data **GROUNDED**) · results **LOCAL**, unpublished · /halt
