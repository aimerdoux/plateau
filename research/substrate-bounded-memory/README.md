# D-036 — Substrate as bounded memory (research side-track)

> A **pre-registered, staged falsification** of a speculative idea: can a dissipative
> physical field — a frozen 2D Complex Ginzburg–Landau **vortex glass** — serve as a
> *bounded* memory store for a long-running agent, the way Plateau's capped signal does?

This is a **research prereg, not a claim.** In keeping with the repo's ethos
(*cheaper, not smarter; recompute-verifiable; null results published; mechanism, silent on
phenomenality*), nothing here asserts that any physics "remembers." A stored item is a
vortex — a coordinate with a charge sign — and the whole exercise is to find out whether the
field's dynamics add anything a plain 2D index does not already give for free.

## Why it is built cheapest-killer-first

The design runs the **no-LLM stages first** so the branch can die for a day's cost instead of
a quarter's, and so Stages 0–2 carry **zero prompt-injection surface**:

| stage | what it decides | LLM? |
|---|---|---|
| **Calibration gate** | are we in the frozen regime, not turbulence? (else all numbers are noise) | no |
| **H1 — capacity** | does the field hold ≥ 50 distinguishable items, and does it beat its *own* projection stored in a plain dict? | no |
| **H2 — semantic interference** | when items merge, are they more related than chance (vs. arbitrary, LRU-for-free)? | no |
| **H3 — task performance** | fixed byte budget, blind runner, task success not recall@k | yes (gated twice) |

**H1 is the cheap killer.** Its mandatory **B1 control** — the identical 2D projection in a
dict with no dynamics, read at the same resolution — isolates the D-035-class trap
(measuring *projection loss* and calling it substrate behaviour). If the field's capacity is
just geometric packing, or merely loses to its own dict, that is a **REFUTED**, and it ships
as a first-class null.

**The operator's pre-registered prior: H1 fails, ~75%.** Scored against the sealed rule.

## Relation to the paper

The idea is a physical analogue of the paper's compression projection **Π** and its
compression noise **QΠ** (README §"The paper"): the random 768→2 projection *is* a lossy Π,
and every downstream question is whether the field reduces or merely inherits that
distortion. It touches no core code and imports no phenomenal claim — the **bright line**
holds by construction.

## Files

- [`PREREG.md`](PREREG.md) — the binding pre-registration: sealed constants `(b, c, T, L,
  N_crit, r_pb, α, seeds, stopping rule, B1)`, calibration gate, H1/H2/H3 methods, decision
  rules, guards, integrity. **Written before any harness or field run.**
- [`SEAL.txt`](SEAL.txt) — sha256 + git blob hash of `PREREG.md` at the sealing commit; the
  run must echo it before writing datum one.
- `raw/` — created on first run; sealed write-once per the integrity convention. Not
  committed without operator go.
