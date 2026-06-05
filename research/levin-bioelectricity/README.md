# Research roadmap — Levin's bioelectric morphogenesis → Plateau (via *The Integrator*)

> **Source video:** *Bioelectricity, Morphogenesis, and Two-Headed Worms | Michael Levin*
> — <https://youtu.be/t6EFV2gSSmg> (id `t6EFV2gSSmg`).
> **Transcript how-to:** [`TRANSCRIPTION.md`](TRANSCRIPTION.md) (yt-dlp).
> **The repo's formal theory:** [`paper/the-integrator-2026-06-02.pdf`](../../paper/the-integrator-2026-06-02.pdf)
> — *The Integrator: A Free-Energy Filtering Account of Compressed-State Continuity in
> Long-Running Agents* (Project Plateau, draft 2026-06-02). **This roadmap is anchored to
> that paper's formal objects and its pre-registered cycles C5–C11.**

This is a **research roadmap**, not a claim. In keeping with the repo's ethos
(*cheaper, not smarter; recompute-verifiable; null results published; mechanism, silent
on phenomenality*), nothing here asserts that biology proves anything about the code.
Levin's developmental-bioelectricity program is used as a **design lens** on the
formalism the paper already commits to: a collective of memory-limited agents holds a
goal stable by carrying a small, continuously **re-verified** signal instead of
replaying its history. The roadmap's job is to turn that lens into **sharper versions of
the paper's already-pre-registered experiments**, not a competing track.

---

## 1. The paper this lands in — *The Integrator*, in one screen

The paper formalizes Plateau's mechanism as a **recursive Bayesian filter on a
compressed belief**, plus a second filter on top. The load-bearing objects (use these
names — they are the integration's anchor):

- **Belief `bₜ(s)`** over task-relevant state `s` (goals, scope, constraints, working
  facts) — the variables the next action depends on.
- **Predict (reasoning)** advances the belief and *generically raises* uncertainty `P⁻`.
- **Update (the gate) is the gain.** A grounded measurement reweights the prior by its
  precision `R⁻¹`. A claim that re-verifies cleanly → `R→0`, gain `K→1`, it enters the
  signal. An ungrounded assertion → `R→∞`, `K→0`, it is **dropped**. *"The gate admits
  only measurement-backed facts" and "the update weights by measurement precision" are
  the same statement* (§2.3).
- **Projection `Π` and compression noise `QΠ`.** The agent does **not** carry the full
  belief; it carries a fixed-dimension lossy projection and re-inflates it. `Π` injects
  `QΠ` — the compress→inflate reconstruction error — which is **what a rate–distortion
  sweep measures** and is *indistinguishable from reasoning noise in the error stream*.
- **Metacognition = a filter on the filter.** A second filter watches the base filter's
  **innovation stream** `eₜ = mₜ − m̂⁻ₜ` (with predicted variance `Sₜ = P⁻ + QΠ + R`) to
  estimate the base filter's own reliability.
- **Proposition 1 / Claim 1 (identifiability bound).** In steady state the three terms
  enter the innovations only through their **sum `S = P⁻ + QΠ + R`**; the meta-filter can
  recover `S` but **provably cannot decompose** it into reasoning error vs. gate error vs.
  compression error. *The self-model calibrates an aggregate it cannot attribute.*
  Separation requires an **external intervention** — e.g. sweeping the projection rate to
  move `QΠ` alone (that is cycle **C9**).
- **Readouts, not objectives** (each with a degeneracy guard): **correspondence** =
  `−KL(π(a|full context) ‖ π(a|inflate(signal)))` (does the signal induce the same next
  action?), and **calibration** (Brier/ECE, scored by the *resolution* component vs.
  base-rate, to block the regress-to-base-rate cheat).
- **Completed, sealed results:** **C3** (compression at completion parity, synthetic
  chain), **C6** (same on real multi-module code — full-history blew up ~100×, Plateau
  stayed bounded, both PASS), **C4** (low-dimensional state trajectory). **Forward
  program (pre-registered, not run):** **C5, C7/C8, C9, C10, C11.**
- **Bright line.** The account is of a **mechanism**; it is *silent on phenomenality by
  construction*. The metacognition layer is "a model of the modeling, not comprehension
  from within." This boundary is load-bearing — and it governs how we may use Levin.

---

## 2. The theory in one screen — Levin (the lens)

- **Bioelectricity is the coordination medium** — a *low-bandwidth shared channel*, not a
  blueprint any single cell holds.
- **Target morphology = a setpoint.** Morphogenesis is **homeostatic error reduction**:
  store a target shape, act until measured anatomy matches it, then stop.
- **Pattern memory is re-writable — and that's the danger.** The right bioelectric
  perturbation **incepts a "false memory"**: a flatworm regenerates **two heads** from an
  unchanged genome. *Memory not re-grounded against reality is faithfully-pursued error.*
- **Multiscale competency architecture** — cells→tissues→organs→body, nested agents each
  pursuing goals in their own problem space, each reporting upward.
- **Cognitive light cone** — an agent's scale is the reach of the goals it can represent.
- **TAME / basal cognition** — goal-directed error-reduction at every scale.

Sources: [Levin Lab](https://drmichaellevin.org/research/),
[TAME (arXiv 2201.10346)](https://arxiv.org/abs/2201.10346),
[*Bioelectric networks: the cognitive glue…*](https://link.springer.com/article/10.1007/s10071-023-01780-3),
[*Scaling of goals from cellular to anatomical homeostasis*](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC10102734/).

---

## 3. The three-column bridge (Levin → Integrator formalism → Plateau code)

The middle column is the point of this revision: the biology is mapped to the paper's
**named formal objects**, and only through them to code. That keeps the analogy honest
and gives every row a measurable handle the paper already defined.

| Levin (lens) | *Integrator* formal object | Plateau code |
|---|---|---|
| Target morphology = **setpoint**; carry the goal, not the path | belief `bₜ(s)` over task-relevant state; **predict→update** loop minimizing one-step free energy | `RelationalState.open_goals`/`stance` (`plateau/signal.py`) |
| **Homeostatic error reduction**; act until anatomy = target, then stop | update step *lowers uncertainty* in expectation; innovation `eₜ` / `Sₜ` shrink toward the setpoint | `serve_forever`/`should_continue` (`plateau/orchestrator.py`) |
| Cells **re-sense every moment**; never trust last state | **the gate is the gain**: precision `R⁻¹`; `R→0 ⇒ K→1` admit, `R→∞ ⇒ K→0` drop (§2.3) | `ground()`/`inflate()` re-verify each fact each step (`plateau/continuum.py`); `Measurement.reverify()` |
| **Two-headed worm** = a false setpoint faithfully pursued | the gate dropping ungrounded claims; the **integrity apparatus** catching a *fabricated pass* (§7) | the **GATE** + `reverify()` failing closed (`plateau/signal.py`); sealed-manifest integrity (`plateau/integrity/`) |
| **Low-bandwidth shared channel**; a minimum viable bandwidth | projection **`Π`** + compression noise **`QΠ`**; the **rate–distortion knee** (cycle **C9**) | the capped SIGNAL blob (`emit` in `plateau/continuum.py`) |
| Collective navigating **morphospace**; trajectories on a low-dim set | belief lives near a **low-dimensional set** (**C4**); **slow-manifold** attractor (**C10**) | the carried `verified_facts`/signal trajectory across steps |
| **Multiscale competency**; agents reporting upward | the **metacognition filter on the filter**; but *"recursion stops at two"* (§5.6) | worker → orchestrator → parent (`plateau/agency/`) |
| **Cognitive light cone** = reach of representable goals | the footprint law; **Claim 1**: self-model is *aggregate-only*, can't attribute its own error | the capped footprint `O(agents+resumes)` |

**Honest non-mappings (where the lens breaks — state them, don't paper over them):**

1. Cells share a *continuous, bidirectional* bioelectric field; Plateau passes a
   *discrete, one-shot* JSON blob upward (`emit`). Different channel physics.
2. Levin's multiscale competency implies **arbitrarily deep** nesting; the paper proves
   the opposite for self-modeling — **two filters, not a tower** (§5.6), because each
   level estimates a slower, lower-dimensional quantity on shrinking data. *The biology
   suggests depth; the math caps it. We follow the math.*
3. TAME/basal-cognition routinely makes **phenomenal/cognition** claims. The paper's
   bright line forbids importing them. We take Levin's **structure and function only**
   and discard the "what it's like" leap — exactly as the paper's §9 treats predictive
   processing ("controlled hallucination").

---

## 4. The roadmap — phases (anchored to the paper's cycles)

Each phase produces an artifact and a go/no-go. Every experiment is
**recompute-verifiable**, **pre-registered** (decision rule before data, per §7), and may
produce a **null** (published, per repo norm). The Levin lens does not add new cycles —
it **sharpens the paper's existing C5–C11** and supplies adversarial cases.

### Phase 0 — Transcript & grounding *(half day)*
- Run [`scripts/get_transcript.py`](scripts/get_transcript.py); commit
  `transcript/t6EFV2gSSmg.txt`. Extract ≥4 timestamped quotes (setpoint, false-memory,
  multiscale, light-cone). These become the cited claims this roadmap rests on.
- **Exit:** transcript committed; quotes pinned.

### Phase 1 — Concept ledger *(half day)*
- Land `CONCEPT_LEDGER.md`: one row per mapped concept — *biological claim → Integrator
  object → Plateau code → which cycle (C3–C11) it touches → testable prediction*. No
  orphan ideas; every Phase-2 item traces to a row **and** to a paper cycle.

### Phase 2 — Lens-sharpened experiments *(pick ≥2; reuse `experiments/qa_suite/`, `demo/`)*

- **L1 · The two-headed-worm gate test → sharpens C7/C8 + §7 integrity.**
  Inject a plausible-but-false `Thought` with fabricated/looks-right grounding and confirm
  the **gate drops it** and `inflate()` re-grounding flags it **stale**. This is Levin's
  false-memory failure mode rendered as a regression test guarding `plateau/signal.py`,
  and it operationalizes the paper's **gate rejection-rate** faithfulness measure (C7/C8)
  with an adversarial corpus. *Prediction it could kill:* if any fabricated fact survives
  a re-ground, the gate's `H` does not observe that state direction (Remark 2) — report it.

- **L2 · Minimum-bandwidth knee → is C9 directly.**
  Sweep the signal byte/rate budget; trace next-action **distortion** (the existing
  recall-vs-distance metric in `demo/` is the seed). Levin's "low-bandwidth channel"
  predicts a **knee** (an irreducible `QΠ` floor); the paper's C9 null says the curve may
  be a smooth slope. Run it and locate (or fail to locate) the knee. *This is the single
  highest-value experiment — it moves `QΠ` alone, the one external intervention Claim 1
  says is needed to separate compression error from reasoning error.*

- **L3 · Setpoint error-metric → feeds C4/C10.**
  Add a **read-only** meter: distance between carried `open_goals`/`verified_facts` and the
  live measured state per step (a symbolic proxy for the innovation `eₜ`). Levin's
  homeostasis predicts monotone decrease on a converging task. Pair it with C4's
  participation-ratio probe to test whether the trajectory relaxes onto C10's **slow
  manifold** (restoring force + spectral gap). *Null (paper's prior): a static
  low-dimensional cloud, not an attractor.*

- **L4 · Recursion-depth honesty check → tests §5.6 against Levin.**
  Levin says competency nests arbitrarily deep; the paper says **two filters is all the
  data support.** In a sandbox, add a third nesting level to the agency stack and a
  meta-meta reliability estimate; measure whether the third level beats base-rate
  **resolution** (Remark 3 guard) or just regresses to base rate. *Honestly weighted null
  (high prior, per the paper): the third level carries zero discriminative self-knowledge
  — the tower collapses, and we publish that as confirmation of §5.6.*

### Phase 3 — Integration (only what an experiment earned) *(scoped per result)*
- Promote a **green** result minimally: L3's meter joins `plateau/metrics.py` as an
  optional read-only readout (a **correspondence/innovation** proxy, named in the paper's
  vocabulary — *not* biology); L1 becomes a permanent test in `tests/`. Audit-mode first
  (`plateau-agency --mode audit`, zero remote risk).
- Any sealed numeric goes through the paper's integrity apparatus (pre-register → seal →
  independent recompute) and reconciles in [`PAPER_RECONCILIATION.md`](../../PAPER_RECONCILIATION.md).
- **Exit:** `pip install -e . && python -m pytest` green; `examples/bare_loop.py` and
  `python -m plateau.agency.bench_summary` still run; new numbers sourced from a sealed verdict.

### Phase 4 — Write-up *(half day)*
- One prereg→readout per experiment in `demo/` format (hypothesis *before* the run). Fold
  results back into the paper's bracketed `[value]` placeholders **only** where a sealed
  verdict supports it; update `BENCHMARKS.md`/`RESULTS.md` with sourced numbers only.

---

## 5. The workflow (repeatable loop — itself an emit/inflate/ground discipline)

```
 ┌─ INGEST ──────────────────────────────────────────────────────┐
 │ yt-dlp transcript → annotate timestamped claims (the "thoughts")│
 └───────────────┬───────────────────────────────────────────────┘
                 │
 ┌─ GATE ────────▼───────────────────────────────────────────────┐
 │ a claim earns a roadmap row ONLY if it maps to an Integrator    │
 │ object AND a paper cycle AND yields a falsifiable prediction.    │
 │ vibes are dropped and logged — the gate is the gain.            │
 └───────────────┬───────────────────────────────────────────────┘
                 │  (gated claims → CONCEPT_LEDGER.md rows)
 ┌─ EXPERIMENT ──▼───────────────────────────────────────────────┐
 │ prereg hypothesis → run against existing harness → readout.     │
 │ null results are first-class and published.                     │
 └───────────────┬───────────────────────────────────────────────┘
                 │  (only GREEN, sealed, recompute-verifiable results cross)
 ┌─ INTEGRATE ───▼───────────────────────────────────────────────┐
 │ minimal core change + permanent test; paper-vocabulary naming;  │
 │ reconcile sealed numerics into the paper's [value] slots.       │
 └───────────────┬───────────────────────────────────────────────┘
                 │
 ┌─ RE-GROUND ───▼───────────────────────────────────────────────┐
 │ pytest green · benches re-run · numbers re-sourced · then loop  │
 └────────────────────────────────────────────────────────────────┘
```

The discipline is deliberately the project's own: **a claim persists only if a
measurement re-verifies it now.** Here the measurement is a passing, pre-registered,
sealed experiment — never the elegance of the analogy.

---

## 6. Guardrails (so this stays Plateau, not poetry)

1. **Respect the bright line.** Use Levin/TAME for **structure and function only**;
   discard every phenomenal/consciousness/"basal cognition is real cognition" claim, as
   the paper's §9 does for predictive processing. The mechanism is silent on
   phenomenality by construction.
2. **No overclaiming.** Biology *inspires* hypotheses; it never *evidences* code behavior.
   Every kept claim has a sealed number or a test behind it.
3. **No new core dependencies.** `yt-dlp`/`whisper` live in this research folder only; the
   core stays zero-dep.
4. **Paper vocabulary in code, biology in docs.** Code keeps `gate`, `Measurement`,
   `RelationalState`; new readouts are named for the paper's objects (correspondence,
   calibration, `QΠ`), never for cells or worms.
5. **Follow the math over the metaphor.** Where Levin implies unbounded recursion and the
   paper proves a two-level cap (§5.6), the paper wins.
6. **Null results ship; recompute or it didn't happen.** Transcript, prereg, and readouts
   are committed and sealed so anyone can re-derive the conclusions.

---

## 7. Files in this folder

- [`TRANSCRIPTION.md`](TRANSCRIPTION.md) — pull the transcript with yt-dlp (+ the
  datacenter bot-gate workaround observed in CI).
- [`scripts/get_transcript.py`](scripts/get_transcript.py) — zero-dep yt-dlp wrapper:
  VTT → clean, de-duplicated, timestamped text.
- `transcript/` — created on first run; commit the `.txt` so claims stay checkable.
- `CONCEPT_LEDGER.md` — produced in Phase 1.
- **Anchored to** [`paper/the-integrator-2026-06-02.pdf`](../../paper/the-integrator-2026-06-02.pdf)
  — the formal theory; every experiment above traces to one of its cycles C3–C11.
