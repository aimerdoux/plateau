# QUALITY_BENCHMARKS — Plateau's real, reproduced quality-retention scores, and the honest head-to-head vs headroom

Every number in this file comes from a run that was **actually executed and logged to disk** in this
repo's research tree (`bmacp-trunk`). No number is estimated, rounded-from-memory, or carried over from
a brief. Each row carries (a) the exact command that re-derives it in a fresh process and (b) the path to
the run log or sealed verdict it came from. Where a reproduction did not exactly match the seal, **both
numbers are shown** and the delta is explained — never papered over.

> **Read this first — what "quality" means here.** Plateau is a *context-binding* mechanism: a bounded
> signal blob replaces a growing full-history transcript. Its quality metric is therefore **task-quality
> retention under bounded context** — does the bounded arm still *finish the same multi-step task
> correctly* (file built, contract held, tests green) when it is denied the full transcript? That is
> measured by **completion parity** (and, on the real-code demo, by **pytest pass counts**), not by
> question-answering accuracy. This is the honest shared axis with headroom (see the head-to-head at the
> bottom): both measure **quality preserved under context reduction** — headroom at the payload-
> compression layer, Plateau at the working-context layer.

---

## 1. The headline: collapse A/B (Plateau's analogue to "accuracy preserved under compression")

The collapse A/B is the direct quality-retention experiment. Two arms run the **same** strictly-serial
≥10-layer dependent build through fresh `claude -p` workers:

- **control** carries the **full transcript** each step → context climbs toward the window wall and
  **collapses** (the headless analogue of an interactive session's auto-summarize compaction);
- **signal** carries **only the bounded Plateau blob** → context stays flat.

The quality question: *does the bounded arm still complete every step the control arm does?* If yes at a
near-flat slope, that is **bounded context at no quality loss** — Plateau's analogue to headroom's
"GSM8K 0.870 → 0.870 with the payload compressed."

### 1a. Fresh reproduction this session (PAID, `claude -p` / Claude Max OAuth)

| arm | context first → last (tok) | slope (tok/step) | completion | collapse |
|---|---|---|---|---|
| control (full history) | `168` → `195,685` | `16,650.1` | `1.0` | `step 9 (over budget)` |
| **signal (Plateau bounded)** | `192` → `699` | `55.8` | `1.0` | — |

- **Context cut at the wall:** `99.6%` fewer tokens carried at the final step (signal vs control).
- **Quality retention:** signal completion `1.0` vs control `1.0` → **parity holds**
  (`true`). Verdict: **`WIN`**.
- Reproduce: `PYTHONPATH=<repo>/plateau python -m experiments.continuum.run_collapse_ab --steps 10 --budget 180000 --go`
  (this session ran it via a thin wrapper that monkeypatches `OUT` to `collapse_ab_repro/` so the prior
  sealed run is never clobbered — same harness code path).
- Run log: [`reports/continuum/collapse_ab_repro/verdict.json`](../reports/continuum/collapse_ab_repro/verdict.json)
  · raw prompts+replies under `reports/continuum/collapse_ab_repro/raw/` (sealed before scoring).
- **Cost (this paid run):** ~**398 k** carried-context input tok (389 k control + 4.5 k signal) + ~4 k
  reply output + ~100 k Claude Code system-prompt overhead across the 20 fresh `claude -p` calls ≈
  **~0.5 M tok total**, on Claude Max OAuth (quota-metered, not per-token billed). The signal arm is the
  cheap one (4.5 k carried across all 10 steps); the control arm spent **~87×** more carried context to
  reach the same completion.

> **Fresh-vs-sealed reconciliation (honest delta).** The fresh run reproduces the sealed §1b verdict on
> every load-bearing claim — **collapse at step 9, both arms completion 1.0, signal slope ~55–56,
> verdict WIN** — but the control arm's *exact* final token count differs (**195,685** fresh vs
> **218,094** sealed; slopes 16,650 vs 18,561). That is expected and not a discrepancy: the control
> prompt is built from **real `claude -p` replies**, whose length varies run-to-run, so the cumulative
> transcript lands at a slightly different size each time. The signal arm, carrying only the bounded
> blob, reproduces almost exactly (**192→699** fresh vs **192→694** sealed). The qualitative result —
> *bounded context holds completion parity while full history climbs over-window and collapses* — is
> **stable across both runs**.

### 1b. The prior sealed run it reproduces (`--steps 10 --budget 180000`)

Source: [`reports/continuum/collapse_ab/verdict.json`](../reports/continuum/collapse_ab/verdict.json)
(sealed; raw replies under `reports/continuum/collapse_ab/raw/`).

| arm | context first → last (tok) | slope (tok/step) | completion | collapse |
|---|---|---|---|---|
| control (full history) | 168 → **218,094** | 18,560.7 | 1.0 | **step 9 (over budget)** |
| **signal (Plateau bounded)** | 192 → **694** | 55.5 | 1.0 | — |

- **Context cut at the wall:** signal carried **694 tok** where control carried **218,094 tok** — a
  **99.7 % reduction** at the final step, and the control arm was **already over its 180 k window budget**.
- **Quality retention:** both arms reached **completion 1.0** — the bounded arm finished L10 correctly
  (it even derived a *tighter* closed form, `lN = 2^(N-1)·x + (2^N−1)`, verified `compute(0)=1023`),
  while carrying 0.3 % of the context. Verdict (sealed): **WIN — bounded context, no amnesia.**
- This is the row that maps most directly onto headroom's accuracy-preserved claim: **quality held flat
  (1.0 → 1.0) while context was cut ~99.7 %.**

---

## 2. Real-code efficiency win (demo6b) — completion parity on a 5-layer feature with pytest

The collapse A/B uses a synthetic dependent chain; **demo6b** runs the same bounded-vs-full-history A/B
on a **real ≥5-layer feature built on this repo**, scored by **pytest pass counts** (a harder quality bar
than file-existence).

Source: [`demo/verdict6b.json`](demo/verdict6b.json) + `demo/raw6b/*_completion.json` (sealed).

| arm | context first → last (tok) | slope (tok/step) | final tests | completion |
|---|---|---|---|---|
| arm1 (full history) | 365 → **37,405** | 6,859.7 | **32 / 32 pass** | True |
| **arm2 (Plateau bounded)** | 508 → **1,075** | **103.0** | **36 / 36 pass** | True |

- Bounded slope **103.0** is **1.5 %** of full-history **6,859.7** (a **66.6×** lower growth slope);
  **both arms reach green with zero rework.** Quality (tests passing) is **fully retained** under
  bounded context. Verdict (sealed): **EFFICIENCY WIN.**
- Reproduce (repo root):
  `DEMO6_RAW=demo/raw6b DEMO6_VERDICT=demo/verdict6b.json python demo/recompute_demo6.py`
- Reproduced **this session**: **PASS — 38 sealed files, verdict reproduces** (log:
  [`reports/continuum/qualbench_logs/`](../reports/continuum/qualbench_logs/)).

---

## 3. Context-growth-slope cycle (C3, n=10) — quality parity at a flattened slope, with CI

C3 is the synthetic mechanism probe behind the collapse result: it isolates **context-growth slope at
completion parity** with a bootstrap CI, so the "no quality loss" claim is statistically bounded.

Source: [`reports/continuum/c3_10/verdict.json`](../reports/continuum/c3_10/verdict.json) (sealed).

| arm | slope | mean completion |
|---|---|---|
| control | 22.903 | 1.0 |
| **signal (Plateau)** | **0.285** | **1.0** |

- Slope-diff **22.618**, **CI95 [21.941, 23.128] excludes zero**; **completion parity 1.0 both arms**.
  Signal slope is **1.2 %** of control. Verdict (sealed): **WIN — flattens context AND keeps completion.**
- Re-verify (parent root): `python -m experiments.recompute` (integrity hash-check over sealed files).

---

## 4. Gatebench — the *cost* of preserving quality (wall-clock + disk, the second axis)

Every result above measures **tokens**. Gatebench measures the **wall-clock and disk cost** of Plateau's
quality-preservation mechanism: re-grounding each carried fact through the gate every step. If that gate
were expensive, "bounded context" would just move the cost; gatebench shows it does not.

Source: `reports/continuum/gatebench/raw/results.json` (sealed) + the recompute path.

| grounding kind | per-fact median | classification | in shipped core? |
|---|---|---|---|
| **file_hash** (the shipped gate) | **~0.0133 ms/fact** (13 µs), linear | **GATE-CHEAP** | yes |
| command_output (modeled subprocess) | ~1.93 ms/fact (~145× file_hash) | GATE-COSTLY | no — fails closed |

- The shipped re-grounding gate is **GATE-CHEAP**: a 50-fact signal re-grounds in **0.59 ms/step**,
  **linear** in fact count. Preserving quality under bounded context is cheap on **time** as well as
  tokens. Carried signal is **~220 B/fact, O(facts)** on disk.
- Re-verify (parent root): `python -m experiments.continuum.gatebench recompute`
- Reproduced **this session**: **PASS** — `file_hash → GATE-CHEAP`, `command_output → GATE-COSTLY`
  (matches seal). **Honest caveat:** this benchmark times microsecond-scale ops, so it is **sensitive to
  machine load** — on a loaded run it transiently misclassified `file_hash` as `GATE-COSTLY+SUPER-LINEAR`
  (load jitter inflating 13 µs ops), then reproduced **PASS twice** when the machine was quiet. The
  *classification* is correct under normal load; the absolute µs figure is not a stable single-shot
  number. Logs: [`reports/continuum/qualbench_logs/`](../reports/continuum/qualbench_logs/).

---

## 5. Can the literal QA suites (GSM8K / TruthfulQA / SQuAD / BFCL) run through Plateau today?

**No — not with the existing harness, and this file does not fabricate scores for them.**

I checked: there is **no GSM8K / TruthfulQA / SQuAD / BFCL / MMLU wiring anywhere** in `experiments/`,
`plateau/plateau/`, or `harness/` (grep returned nothing). Plateau's harness scores **task completion**
(`expect_file` existence + pytest pass), not question-answering accuracy. Driving a literal QA suite
through Plateau's collapse mechanism would require **building a new eval harness**:

1. a QA adapter that turns each benchmark item into a Plateau `Task`/`Step` whose `expect_file` is the
   model's answer, scored against the gold label (not file-existence);
2. a dataset loader + the suite's official scorer (exact-match / F1 / MC1 / AST-match for BFCL);
3. a control-vs-signal split so the *retention-under-bounded-context* delta is what's measured — i.e.
   accuracy with full QA context vs accuracy with only the Plateau blob.

That is a **separate harness-build task** (honest estimate: **~1–2 focused engineering days** for one
suite end-to-end with sealing — most of it the per-suite scorer + a payload-compression analogue so the
comparison to headroom is apples-to-apples; each additional suite ~half a day). Per the run contract I
did **not** build or fake it. **Plateau's native quality benchmark is the collapse-A/B (§1) + demo6b
pytest parity (§2) + C3 (§3)** — quality-retention measured by completion/test parity under bounded
context.

---

## 6. HEAD-TO-HEAD vs headroom — same axis, different layer

[headroom](https://github.com/chopratejas/headroom) publishes an **"Accuracy preserved on standard
benchmarks"** table and a **"Savings on real agent workloads"** table. Plateau publishes
**quality-retention under bounded working-context**. They sit on the **same axis — quality preserved
under context reduction — at two different layers of the stack.**

### The axis, stated precisely

| | **headroom** | **Plateau** |
|---|---|---|
| What is reduced | the **payload** sent to the model (prompt/RAG compression) | the **working context** the agent carries across steps (transcript → bounded blob) |
| Quality metric | benchmark **accuracy** (GSM8K, TruthfulQA, SQuAD, BFCL) | **task-completion / test parity** across a multi-step build |
| Reduction metric | **% compression** of the payload | **% context cut** + **growth-slope** flattening |
| Failure mode it guards | accuracy drop when you compress the prompt | **amnesia / collapse** when the transcript fills the window |
| Layer | request-time payload | session-lifetime context loop |

### The numbers, side by side

| claim | headroom (published) | Plateau (reproduced here) |
|---|---|---|
| Quality held flat under reduction | GSM8K **0.870 → 0.870**; TruthfulQA **0.530 → 0.560** | collapse A/B **completion 1.0 → 1.0** (§1b); demo6b **32/32 & 36/36 tests** (§2); C3 **1.0/1.0** (§3) |
| Reduction achieved at that quality | SQuAD v2 **@ 19 %** compression; BFCL **@ 32 %** compression | **~99.7 % context cut** at the wall (694 vs 218,094 tok, §1b); slope cut to **1.5 %** (demo6b) / **1.2 %** (C3) of full-history |
| Real-workload savings | **92 / 92 / 73 / 47 %** | live bounded-parent run: **0 compactions**, bypass:signal **≈531:1** (BENCHMARKS.md §1) |

### Where Plateau is stronger, and where the comparison does **not** map

**Plateau is stronger on the magnitude and the layer of the reduction.** headroom's reductions are
**19–32 %** payload compression at flat accuracy; Plateau's collapse A/B holds **completion parity while
cutting context ~99.7 %** at the step where the full-history arm goes *over-window and collapses*. That is
a qualitatively different regime: headroom keeps accuracy while *shrinking a request*; Plateau keeps
task-completion while *preventing the session from collapsing at all*. The slope result (§3, CI-bounded)
is something headroom does not report — Plateau shows the bounded arm's context **does not grow** with
task length, which is the property that matters for long-horizon agents.

**Where the comparison does NOT map — stated honestly:**
- **Different quality instrument.** headroom reports **standard QA accuracy** on named public suites;
  Plateau reports **completion/test parity** on multi-step builds. They both mean "quality preserved,"
  but they are **not the same number** and should not be quoted as if interchangeable. Plateau has **not**
  run GSM8K/TruthfulQA/SQuAD/BFCL (§5) — so on headroom's *literal* benchmark rows Plateau has **no
  comparable score yet**, only its native completion-parity evidence.
- **Different baseline.** headroom's "0.870 → 0.870" is *the same model* with a compressed prompt.
  Plateau's "1.0 → 1.0" is *full-transcript vs bounded-blob* — a harder reduction but a **coarser quality
  metric** (binary completion / test pass, not graded accuracy). A 1.0 → 1.0 on a task the model finds
  *easy enough to always complete* would be uninformative; the anti-rig guard (`control must climb and
  collapse`) is what makes Plateau's parity load-bearing, and it fired (control hit the wall at step 9).
- **headroom measures accuracy retention; Plateau measures collapse avoidance.** The honest framing is
  **complementary, not competitive**: headroom compresses *what you send*, Plateau bounds *what you
  carry*. They could compose (a headroom-compressed payload inside a Plateau-bounded loop).

### BOTTOM LINE

On the shared axis — **quality preserved under context reduction** — Plateau's reproduced evidence is
**real and strong at its own layer**: bounded working-context at **completion/test parity** with a
**~99.7 % context cut** at the collapse wall (§1b), a **66.6× / 80.4× flatter growth slope** at full test
parity (§2/§3, CI-excludes-zero), and a **GATE-CHEAP** (~13 µs/fact) cost of preserving it (§4). Against
headroom's published table, **Plateau's reduction magnitude is far larger and operates at the session
layer headroom does not touch**, but Plateau **cannot yet quote a GSM8K/TruthfulQA-style accuracy number**
— its quality instrument is completion/test parity, and the literal QA suites are an un-built, ~1–2-day
harness task (§5). The two are **best read as complementary layers of the same idea**, not as a
single-number horse race; quoting Plateau's "1.0 → 1.0" *as if* it were headroom's "0.870 → 0.870" would
be the one dishonest move, and this file refuses it.

---

— all numbers sealed-sourced or freshly logged this session · results **LOCAL**, unpublished · reproduce
commands verified (spot-check in commit message) · /halt
