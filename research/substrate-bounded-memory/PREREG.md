# D-036 — Substrate as bounded memory — PRE-REGISTRATION

Written and committed **before** any harness is built and **before** any field is evolved,
so this document provably precedes the data. The verdict is computed from sealed logs by
the locked rules below; **this document is the rule.** Staged so the cheapest killer runs
first: Stages 0–1 use **no LLM at all** (zero injection surface); H3 is gated twice behind
them.

**Bright line (kept).** This asks a purely *mechanistic* question — can a dissipative field
hold N distinguishable items and give them back — and is **silent on phenomenality by
construction**, exactly as the paper's account is (README §"The paper"). No claim here is
about experience, understanding, or "the field remembering." A vortex is a coordinate with
a sign; nothing more is imported.

**My prior, on the record: H1 fails, ~75%.** The analytic packing check (below) is expected
to kill the branch *before* the sweep runs. If the field's measured capacity is just
geometric packing, it is replaceable by a 2D grid index and this is a **REFUTED** — a
first-class, publishable outcome per repo norm (null results ship).

---

## 0. What is sealed (the binding constants)

Nothing downstream may be changed after data is seen. If the calibration gate (§1) forces a
re-tune of `(b, c)`, that is the **only** permitted post-hoc edit, it is logged as a `NOTE`,
and it happens **before** any H1 datum is collected — never after.

### 0.1 Model
2D complex Ginzburg–Landau equation, periodic boundaries:

```
∂ₜ A = A + (1 + i·b) ∇²A − (1 + i·c) |A|² A
```

- **b = +0.50, c = −0.60** → **1 + bc = 0.70 > 0** (Benjamin–Feir–Newell **stable**),
  opposite-sign dispersion of modest magnitude → the frozen / vortex-glass side of the 2D
  CGLE phase diagram. *Binding only if the calibration gate passes*; if it fails, re-tune
  within the BFN-stable frozen region, re-run the gate, log the new pair as a `NOTE`, and
  proceed. The downstream rules never move.
- **Box:** L = 256 grid points, physical side 128.0 (dx = 0.5), area `A_box = 128² = 16384`.
- **Integrator:** pseudo-spectral, ETD2 (exponential time-differencing, 2nd order),
  **dt = 0.05**. Seeded, deterministic per seed.
- **Readout resolution `ρ`:** defects localized to sub-grid precision by phase-winding on
  the 4 plaquette neighbours; a survivor "matches" a stored item if it is the item's nearest
  survivor **and** within `ρ = 2·dx = 1.0` of it. **The same `ρ` is used for every arm,
  including the dict control** — no arm is given infinite precision.

### 0.2 Run lengths
- **H1 evolve time:** **T = 20000 steps** (= 1000 time units), fixed for every k and seed.
- **Calibration gate:** evolve a single seeded pair for **10·T = 200000 steps**.

### 0.3 H1 capacity
- **Sweep:** k ∈ {1, 2, 5, 10, 20, 50, 100, 200} vortex pairs. **20 seeds per k.**
- **Metric:** Accuracy@1 = fraction of stored items whose nearest surviving defect (within
  `ρ`) is its own item.
- **Collapse threshold (SEALED):** Accuracy@1 **< 0.90**. N_crit = the largest k at which
  mean Accuracy@1 ≥ 0.90 across seeds.
- **N_crit seal (SEALED before running): N_crit ≥ 50.** Below 50 it is not a context store
  for any real agent horizon — that is a REFUTED regardless of the packing check.

### 0.4 H2 semantic interference *(only if H1 passes)*
- **Statistic:** point-biserial correlation `r_pb` between (a) cosine similarity of an item
  pair in the **original 768-dim embedding space** and (b) a binary merged/annihilated
  indicator for that pair, logged per event.
- **Null:** shuffle **item→coordinate assignment** (NOT positions — positions carry the
  projection confound), **1000 permutations**.
- **Seal (SEALED before running):** effect **|r_pb| ≥ 0.20** AND permutation **p < 0.01**.

### 0.5 H3 task performance *(only if H2 passes)*
- 500-turn agent runs; memory budget held **constant in bytes** across arms.
- Metric: **task success**, not recall@k.
- Safety: `--disallowedTools "*"`, the instruction lives in the user prompt, retrieved
  content is cited as **DATA**, and **the runner is blind to the hypothesis and thresholds**
  — no `CLAUDE.md`, no memory injection.

### 0.6 Seeds / stopping rule
- Seeds `0..19` per k (H1). All PRNG draws seeded from the loop index; no wall-clock, no
  `Math.random`-equivalent, so a fresh process reproduces every field byte-for-byte.
- **Stopping rule:** H1 runs the full 8×20 grid, then **HALT at the verdict**. No
  "one more k," no threshold nudge, no seed top-up to cross a bar. A REFUTED halts the whole
  branch — H2 and H3 do **not** run.

The seal hash of this file is recorded in [`SEAL.txt`](SEAL.txt) at the committing commit;
the run must echo it before writing any datum.

---

## 1. Calibration gate — run before anything (no LLM)

> You are not allowed to measure memory until you have proven you are not measuring
> turbulence.

- With sealed `(b, c)` inside the BFN-stable frozen regime, write **one** vortex–antivortex
  pair and evolve **10·T = 200000 steps**.
- **PASS** = the pair persists **and** zero spontaneous defect nucleation anywhere in the
  domain over the whole run (defect count time-series is flat at 2).
- **FAIL** → you are in defect / phase turbulence; every downstream number is noise.
  Re-tune `(b, c)` within the stable frozen region, log the new pair as a `NOTE`, and
  re-run the gate. Do **not** proceed on a failed gate.

Sealed artifact: `raw/calibration.json` — the defect-count time-series + a PASS/FAIL flag,
written before Stage 0.

---

## 2. H1 — Capacity (the cheap killer, no LLM)

**Hypothesis.** The field retains **≥ N_crit = 50** distinguishable items before retrieval
collapses (Accuracy@1 < 0.90).

**Method**
1. Embed M text chunks → 768-dim vectors → fixed **random projection** to (x, y) + charge
   sign. The projection matrix is seeded and sealed (`raw/projection.npy`).
2. Write k vortex pairs at those coordinates, k over the sealed grid.
3. Evolve **T = 20000** steps (sealed, fixed).
4. Retrieve: read out surviving defect positions; nearest-neighbour match (within `ρ`) back
   to items.
5. Accuracy@1 vs k, 20 seeds per k.

### 2.1 Analytic pre-check — on paper first (Stage 0, no field sweep)
Vortex-pair annihilation time scales `τ ∼ r²` (diffusive approach of opposite charges).
Stage 0 measures the constant directly: evolve isolated pairs at separations
`r ∈ {2,4,6,…}`, fit `τ(r) = α·r²`, invert to the `r_min` for which `τ(r_min) = T`. Then

```
N_pack = floor( A_box / (r_min² / η) ) ,  η = 0.9069 (hexagonal packing efficiency)
```

is the pure-geometry prediction: how many pairs fit at minimum stable separation, nothing
to do with the field beyond τ(r).

- **REFUTED-by-packing (SEALED):** if measured **N_crit ∈ [0.5, 2.0] × N_pack** **and** the
  field's N_crit does not exceed the B1 control beyond its 95% CI, then **the field
  contributes nothing beyond geometric packing** — it is replaceable by a 2D grid index.
  **REFUTED.** *(This is the outcome I am betting on.)*

### 2.2 Mandatory control — the D-035-class trap
768 dims were compressed to 2 **before** any physics ran. Without isolating that, we would
measure **projection loss** and mislabel it substrate behaviour.

- **B1 (critical).** The **identical** 2D projections stored in a plain dict, **no field
  dynamics**, retrieved at the **same readout resolution `ρ`** as the field (not infinite
  precision — that would rig B1 to win). Any capacity difference between B1 and the field
  **is** the physics. **If field ≤ B1, the substrate is pure loss.**
- **B2.** FIFO buffer at the same item capacity — the "arbitrary forgetting" baseline.
- **BLOCKED as degenerate:** any comparison against an unbounded vector store, or across
  unequal memory budgets. Not run; not reported as a win if smuggled in.

### 2.3 Decision rule (applied without override)
- **H1 WIN** = field N_crit **≥ 50** **AND** field N_crit **> B1** N_crit beyond the 95% CI
  (the dynamics *added* distinguishable capacity a lossless dict of the same coords did not
  have — e.g. like-charge repulsion increasing survivors' min-separation faster than
  annihilation destroys items). Only then is there physics to chase.
- **H1 REFUTED** = field N_crit **< 50** **OR** field **≤ B1** (pure projection loss) **OR**
  REFUTED-by-packing (§2.1).
- **Gate:** H1 REFUTED → **branch DEAD. Do not run H2.** This costs a day, not a quarter.

Sealed artifacts: `raw/h1_<k>_<seed>.json` (surviving defects + matches + Accuracy@1),
`raw/tau_fit.json` (Stage-0 τ(r) fit + N_pack), `raw/controls_b1_b2.json`.

---

## 3. H2 — Interference is semantic, not arbitrary *(only if H1 passes)*

This is the **only** hypothesis where a win is available — REFUTED here means forgetting is
arbitrary, which LRU already gives for free.

**Hypothesis.** When two stored items merge or annihilate, they are **more semantically
related than chance.**

**Method.** Log every annihilation event and the item pair involved. Compute point-biserial
`r_pb` between original-embedding-space cosine similarity and the merge indicator. **Null:
shuffle item→coordinate assignment, 1000 permutations.**

**Confound, pre-stated.** Nearby projections are both more likely to merge *and* more likely
to be similar, purely from the projection. **The null must shuffle assignments, not
positions** — shuffling positions would leave the confound intact and manufacture a false
positive. Sealed.

- **H2 WIN** = |r_pb| ≥ 0.20 **and** permutation p < 0.01 (§0.4).
- **H2 REFUTED** = either bar missed → forgetting is arbitrary; branch stops at "an
  efficiency curiosity, not a semantic memory."

Sealed artifact: `raw/h2_events.json` (every event + pair cosine + the 1000-perm null).

---

## 4. H3 — Task performance at fixed budget *(only if H2 passes)*

Expensive; gated twice. Per §0.5: 500-turn runs, byte-constant budget, task-success metric,
**blind runner**, safety per convention. Pre-registered only — not built until H1 and H2
have both passed and been sealed. A separate readout will seal its own decision rule before
it runs; nothing here pre-authorizes spend.

---

## 5. Locked predictions (honest, both directions)

| # | claim | prediction | conf |
|---|---|---|---|
| P0 | Calibration gate PASSes at sealed (b,c) (or after ≤2 re-tunes) | LIKELY | 0.80 |
| P1 | Measured N_crit ≈ N_pack (field = geometric packing) | LIKELY | 0.70 |
| P2 | field N_crit ≤ B1 (pure projection loss, no dynamical gain) | LIKELY | 0.70 |
| P3 | **H1 WIN** (N_crit ≥ 50 AND field > B1 beyond CI) | UNLIKELY | 0.25 |
| P4 | H2 WIN, conditional on H1 passing | GENUINELY OPEN | 0.45 |

**H1 REFUTED is the pre-committed live outcome (~0.75).** I do not force a win. If the field
merely packs, or merely loses to its own dict, the readout says so plainly and the branch
dies at H1 — a cheap, honest negative.

---

## 6. Guards (pre-committed)

- **No moving bars.** N_crit ≥ 50, the 0.90 collapse line, |r_pb| ≥ 0.20, p < 0.01, the
  [0.5, 2.0]×N_pack packing band, k-grid, and 20 seeds are frozen above and are **not**
  retuned after seeing data.
- **The only permitted re-tune** is `(b, c)` on a **failed calibration gate**, before any H1
  datum, logged as a `NOTE`.
- **B1 uses the same readout resolution `ρ`** as the field — no rigging the control to lose
  by giving the dict exact coordinates.
- **Null shuffles assignments, not positions** (H2) — the confound is not laundered.
- **No unbounded-store / unequal-budget comparisons** are reported as wins.
- Mock-verify the whole harness free (calibration flag, τ-fit, match logic, seal round-trip)
  **before** any run.
- **No LLM touches Stages 0–2.** Zero injection surface until H3, which is separately gated.

---

## 7. Integrity (seal-before-score)

Per-stage raw records — calibration series, projection matrix, τ(r) fit, per-(k, seed)
survivor/match logs, control runs, and (if reached) H2 events — are written write-once to
`research/substrate-bounded-memory/raw/` and their SHA-256 hashes recorded in an
append-only, self-hash-chained manifest **before** any scoring, using the repo's
`plateau.integrity` layer (same convention as `demo/raw*/`). The score reads only the sealed
records; a fresh process must (1) recompute the manifest chain, (2) re-hash every sealed
file, and (3) reproduce the verdict from sealed raw. Charts (Accuracy@1 vs k for field / B1 /
B2; τ(r) fit) are rendered from sealed data only. **Results are not committed, pushed, or
published without operator go.**

The seal of this pre-registration itself is the committing commit plus [`SEAL.txt`](SEAL.txt)
(sha256 + git blob hash of this file). The run must echo that hash before writing datum one.

---

## 8. EXIT

Calibration gate PASS, Stage-0 τ(r) fit + N_pack on paper, then the full H1 sweep (field +
B1 + B2, 8×20, sealed, recompute-verified) scored by the locked rule. Report N_crit per arm,
the packing comparison, the H1 verdict, chart paths, and the recompute result. **/halt at
the verdict** — H2 runs only on an H1 WIN; H3 only on an H2 WIN.

---
— [D-036] · pre-registered before data · Stages 0–2 **no-LLM** (zero injection surface) ·
mechanism only, **silent on phenomenality** · results **LOCAL**, unpublished until operator go · /halt
