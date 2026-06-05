# Research roadmap — Levin's bioelectric morphogenesis → Plateau

> **Source video:** *Bioelectricity, Morphogenesis, and Two-Headed Worms | Michael Levin*
> — <https://youtu.be/t6EFV2gSSmg> (id `t6EFV2gSSmg`).
> **How to get the transcript:** see [`TRANSCRIPTION.md`](TRANSCRIPTION.md) (yt-dlp).

This is a **research roadmap**, not a claim. In keeping with the repo's ethos
(*cheaper, not smarter; recompute-verifiable; null results published*), nothing here
asserts that biology proves anything about the code. Levin's developmental-bioelectricity
program is used as a **design lens**: it is the most rigorous existing account of how a
*collective of memory-limited agents* holds a goal stable by carrying a small,
continuously re-verified signal instead of replaying its whole history — which is
precisely Plateau's mechanism, one substrate up. The roadmap's job is to turn that
analogy into **falsifiable experiments against the existing core**.

---

## 1. The theory in one screen

Michael Levin (Tufts; Levin Lab) studies **morphogenesis as collective intelligence**.
The load-bearing ideas:

- **Bioelectricity is the coordination medium.** All cells carry voltage gradients;
  gap-junction-coupled networks form bioelectric circuits that steer individual cell
  behavior toward a shared anatomical outcome. It is a *low-bandwidth shared channel*,
  not a blueprint any single cell holds.
- **Target morphology = a setpoint.** Morphogenesis is **homeostatic error reduction**:
  the collective stores a *target shape* and keeps acting until the measured anatomy
  matches it, then stops. Regenerate a salamander limb and growth halts exactly at the
  correct shape — the setpoint, not the path, is what's carried.
- **Pattern memory is re-writable — and that's the danger.** Modulating the bioelectric
  state can **incept a "false memory"**: flip the right gradient and a flatworm
  regenerates **two heads** from an unchanged genome. The wrong setpoint, once written,
  is faithfully pursued. *Memory that isn't re-grounded against reality is a liability.*
- **Multiscale competency architecture.** Cells → tissues → organs → body: nested agents,
  each pursuing goals in its **own** problem space, each reporting upward. Robustness
  comes from every level solving locally, not from one global controller.
- **Cognitive light cone.** An agent's scale is the size of the goals it can represent
  and pursue — the spatiotemporal reach of what it can "care about."
- **TAME / basal cognition.** The same goal-directed, error-reducing machinery runs at
  every scale; intelligence is a continuum, not a brain-only property.

Primary sources to mine: [Levin Lab overview](https://drmichaellevin.org/research/),
[TAME (arXiv 2201.10346)](https://arxiv.org/abs/2201.10346),
[*Bioelectric networks: the cognitive glue…*](https://link.springer.com/article/10.1007/s10071-023-01780-3),
[*The scaling of goals from cellular to anatomical homeostasis*](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC10102734/).

---

## 2. The mapping (theory → existing Plateau mechanism)

Plateau already implements a homeostatic, re-grounded, multiscale loop. The biology
names the design and exposes its sharp edge.

| Levin concept | Plateau mechanism (file) | What the lens adds |
|---|---|---|
| **Target morphology / setpoint** — carry the goal, not the path | `RelationalState.open_goals` + `stance` (`plateau/signal.py`) | Frames the signal as a *setpoint*: the loop should drive measured state toward it and **stop at match** |
| **Homeostatic error reduction** — act until anatomy = target | `serve_forever` / `should_continue` (`plateau/orchestrator.py`) | Suggests an explicit *error metric* (carried-goal vs measured-state distance) as a stop/continue signal |
| **Bioelectric re-sensing every moment** — never trust last state | `ground()` / `inflate()` re-verify every fact each step (`plateau/continuum.py`) | This **is** the homeostatic sense loop; the analogy validates "re-ground, don't replay" |
| **False-memory two-headed worm** — a wrong setpoint, faithfully pursued | The **GATE**: a model's assertion is never a `Measurement`; ungrounded claims dropped (`plateau/signal.py`) | The biology's failure mode is *exactly* what the gate exists to prevent — the strongest evidence the gate is load-bearing, and a ready-made **adversarial test** |
| **Multiscale competency** — cells→tissues→organs, each an agent | worker → orchestrator → parent (`plateau/agency/`) | Predicts the footprint law should hold *recursively*; motivates a deeper-than-3-level stress test |
| **Cognitive light cone** — scale = reach of representable goals | the footprint law `O(agents+resumes)` / capped signal | Reframes the cap as a **deliberately bounded light cone**; a knob to study, not just a limit |
| **Low-bandwidth shared channel** — bioelectricity, not a blueprint | the small capped SIGNAL blob (`emit`) | Predicts a *minimum viable bandwidth*: below some signal size, coordination should fail measurably |

**Honest non-mappings (where the analogy breaks):** cells share a *continuous,
bidirectional* bioelectric field; Plateau agents pass a *discrete, one-shot* JSON blob
upward. Biology has no cryptographic gate — it has redundancy and physics; Plateau's
`reverify()` is a hash check. Do not import biological vocabulary into the codebase as if
it were mechanism. The value is **hypotheses and tests**, not renaming functions.

---

## 3. The roadmap — phases

Each phase is gated: it produces an artifact and a go/no-go before the next. Every
experiment must be **recompute-verifiable** and is allowed to produce a **null result**
(which we publish, per repo norm).

### Phase 0 — Transcript & grounding *(half day)*
- Run [`scripts/get_transcript.py`](scripts/get_transcript.py); commit
  `transcript/t6EFV2gSSmg.txt`.
- Annotate the transcript: pull the exact quotes/timestamps for setpoint, false-memory,
  multiscale, light-cone. These become the cited claims this roadmap rests on.
- **Exit:** transcript committed; ≥4 timestamped claims extracted.

### Phase 1 — Concept ledger *(half day)*
- For each mapped concept, write one row: *biological claim → Plateau analogue →
  testable prediction → which existing test/bench touches it*. Land it as
  `CONCEPT_LEDGER.md` here.
- **Exit:** every Phase-2 experiment traces to a ledger row (no orphan ideas).

### Phase 2 — Falsification experiments against the **core** *(1–2 days each, pick ≥2)*
Reuse the existing harness (`experiments/qa_suite/`, `demo/`) — **no new core deps.**

- **E1 · Setpoint error-metric (homeostasis).** Add a *read-only* metric: distance
  between carried `open_goals`/`verified_facts` and the live measured state at each step.
  Hypothesis: on a converging task the curve is monotone-decreasing; on a diverging task
  it isn't. *Prediction it could kill:* if error doesn't track task progress, the
  "setpoint" framing is decorative — say so.
- **E2 · False-memory adversarial (the two-headed-worm test).** Inject a plausible-but-
  false `Thought` with fabricated/looks-right grounding into the signal and confirm the
  **gate drops it** and `inflate()` re-grounding flags it **stale**. Hypothesis: zero
  false facts survive a re-ground. This turns Levin's failure mode into a regression
  test guarding `plateau/signal.py`.
- **E3 · Minimum-bandwidth sweep.** Cap the signal blob at decreasing byte budgets;
  measure recall (the existing recall-vs-distance metric in `demo/`). Hypothesis: a
  **knee** exists — a smallest signal that still coordinates. Locating it operationalizes
  the "low-bandwidth channel" claim.
- **E4 · Recursive footprint (deeper multiscale).** Extend the agency stack beyond
  parent→orchestrator→worker (add one more nesting level in a sandbox) and check the
  footprint law `O(agents+resumes)` still holds. *Null result is fine and publishable.*

### Phase 3 — Integration (only what an experiment earned) *(scoped per result)*
- Promote a **green** experiment into the core *minimally*: e.g. E1's error metric joins
  `plateau/metrics.py` as an optional read-only meter; E2 becomes a permanent test in
  `tests/`. **No biological naming in code.** Audit-mode / read-only first
  (`plateau-agency --mode audit`), matching the repo's zero-remote-risk default.
- **Exit:** `pip install -e . && python -m pytest` green; `examples/bare_loop.py` and
  `python -m plateau.agency.bench_summary` still run; new numbers sourced.

### Phase 4 — Write-up *(half day)*
- One readout per experiment in `demo/`-style prereg→readout format (hypothesis stated
  *before* the run). Update `BENCHMARKS.md`/`RESULTS.md` only with sourced numbers.
- Reconcile against the paper lens in `PAPER_RECONCILIATION.md` if a result is paper-worthy.

---

## 4. The workflow (repeatable loop)

This mirrors Plateau's own emit→inflate→ground discipline applied to *research*:

```
 ┌─ INGEST ──────────────────────────────────────────────────────┐
 │ yt-dlp transcript  →  annotate timestamped claims              │
 └───────────────┬───────────────────────────────────────────────┘
                 │  (each claim is a "thought")
 ┌─ GATE ────────▼───────────────────────────────────────────────┐
 │ a claim earns a roadmap row ONLY if it maps to a real mechanism │
 │ AND yields a falsifiable prediction. Vibes get dropped, logged. │
 └───────────────┬───────────────────────────────────────────────┘
                 │  (gated claims → CONCEPT_LEDGER.md rows)
 ┌─ EXPERIMENT ──▼───────────────────────────────────────────────┐
 │ prereg hypothesis → run against existing harness → readout      │
 │ null results are first-class and published                      │
 └───────────────┬───────────────────────────────────────────────┘
                 │  (only GREEN, sourced results cross)
 ┌─ INTEGRATE ───▼───────────────────────────────────────────────┐
 │ minimal core change + permanent test; audit-mode first;         │
 │ no biological vocabulary leaks into code                         │
 └───────────────┬───────────────────────────────────────────────┘
                 │
 ┌─ RE-GROUND ───▼───────────────────────────────────────────────┐
 │ pytest green · benches re-run · numbers re-sourced · then loop  │
 └────────────────────────────────────────────────────────────────┘
```

The discipline is deliberately the same one the project already enforces on agent
context: **a claim may persist only if a measurement re-verifies it now.** Here the
"measurement" is a passing, prereg'd experiment — not the elegance of the analogy.

---

## 5. Guardrails (so this stays Plateau, not poetry)

1. **No overclaiming.** Biology *inspires* hypotheses; it never *evidences* code behavior.
   Every kept claim has a number or a test behind it.
2. **No new core dependencies.** `yt-dlp`/`whisper` live in this research folder only;
   the core stays zero-dep.
3. **No biological renaming of code.** `gate`, `Measurement`, `RelationalState` keep
   their names. The lens lives in docs/tests, not identifiers.
4. **Null results ship.** An experiment that kills a mapping is a success and goes in the
   readouts.
5. **Recompute or it didn't happen.** Transcript, prereg, and readouts are committed so
   anyone can re-derive the conclusions.

---

## 6. Files in this folder

- [`TRANSCRIPTION.md`](TRANSCRIPTION.md) — how to pull the transcript with yt-dlp (+ the
  bot-gate workaround observed in CI).
- [`scripts/get_transcript.py`](scripts/get_transcript.py) — zero-dep yt-dlp wrapper:
  VTT → clean, de-duplicated, timestamped text.
- `transcript/` — created on first run; commit the `.txt` so claims stay checkable.
- `CONCEPT_LEDGER.md` — produced in Phase 1.
