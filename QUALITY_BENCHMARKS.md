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

## 5. The literal QA suites (GSM8K / TruthfulQA) — now BUILT and RUN, accuracy preserved under collapse

**This is now measured, not deferred.** The harness exists (`experiments/qa_suite/`), the runs are PAID
`claude -p`, and every item is logged. Earlier revisions of this file said the QA suites were an un-built
~1–2-day task; that is **superseded** — they are built and the real numbers are below.

### 5a. The measured table (PAID, `claude -p`, per-item logs sealed)

Both arms hit the **same** `claude -p` backend, same question, same suite-standard scorer. The ONLY
difference is the conditioning payload: full few-shot exemplars (baseline) vs those exemplars run through
Plateau's **real** collapse path (`emit → inflate → _render`, the production driver's) into a bounded
signal blob (plateau). Compression % is per-arm payload token size, measured once (constant per arm).

| suite | metric | baseline acc | Plateau acc | Δ | compression | N scored | verdict |
|---|---|--:|--:|--:|--:|--:|---|
| **GSM8K** | exact-match (final integer) | **0.96** (48/50) | **0.96** (48/50) | **0.000** | **63.3%** (472→173 tok) | 50 | accuracy **held** under 63% cut |
| **TruthfulQA MC1** | single-correct option pick | **0.667** (22/33) | **0.697** (23/33) | **+0.030** | **59.8%** (338→136 tok) | 33\* | accuracy **held (↑ within noise)** under 60% cut |

\*TruthfulQA scored **N=33**, not 50: the resumed paid run hit its **token budget guard** (this resume
was hard-capped at ~1.5 M billed-new tokens; GSM8K consumed ~0.60 M, TruthfulQA ~0.88 M) and stopped
**cleanly** with 33 items fully scored on *both* arms. The single half-finished item (one arm only) was
**dropped from the log and the score** — the two arms are compared on the identical 33-item set. This is
a real partial, explicitly labelled; it is **not** padded to 50 or extrapolated.

- **GSM8K reproduce:** `PYTHONPATH=<repo>/plateau python -m experiments.qa_suite.run --suite gsm8k --n 50 --go`
  · log [`reports/qa_suite/gsm8k/items.jsonl`](../reports/qa_suite/gsm8k/items.jsonl)
  · verdict [`reports/qa_suite/gsm8k/verdict.json`](../reports/qa_suite/gsm8k/verdict.json)
  · raw prompts+replies under `reports/qa_suite/gsm8k/raw/` (sealed per item).
- **TruthfulQA reproduce:** `PYTHONPATH=<repo>/plateau python -m experiments.qa_suite.run --suite truthfulqa --n 50 --go`
  · log [`reports/qa_suite/truthfulqa/items.jsonl`](../reports/qa_suite/truthfulqa/items.jsonl)
  · verdict [`reports/qa_suite/truthfulqa/verdict.json`](../reports/qa_suite/truthfulqa/verdict.json).
- **Real cost (this resume, from `claude -p` response JSON):** GSM8K 66 calls / **600,647** billed-new
  tok / ~$10.96; TruthfulQA 67 calls / **883,184** billed-new tok / ~$11.38 (cache_read dominates the
  raw total but is the same cached bytes re-read, not newly-billed context — both verdicts record the
  full breakdown). The 11 GSM8K items recovered from the interrupted prior run were **reused, not
  re-paid**.

### 5b. The two suites deliberately NOT run — and exactly why (no invented scores)

| suite | why it is NOT a fair Plateau mapping | status |
|---|---|---|
| **SQuAD v2** | the conditioning context *is the passage that contains the answer span*; collapsing it deletes the bytes the answer is read from — that is compressing the **answer**, not a redundant few-shot prior. Forcing it would manufacture a misleading F1 drop. | **documented, not run** |
| **BFCL** | the conditioning context *is the tool/function schema* the call must match argument-for-argument; collapsing it removes the names the answer needs — again compressing the answer substrate, not a prior. | **documented, not run** |

The runner refuses these with a logged reason (`experiments/qa_suite/run.py::SKIPPED`) rather than
emitting a fabricated number. This is the same discipline as the published nulls (§nulls below): the
mapping is run **only where it is honest**.

### 5c. What this adds to the native evidence

The QA table is the **single-prompt** analogue of accuracy-preserved-under-compression; the collapse-A/B
(§1), demo6b pytest parity (§2), and C3 (§3) remain Plateau's **multi-step** quality-retention evidence
(completion/test parity under bounded *working* context). Together: Plateau preserves task quality both
when it collapses a **conditioning context** for one answer (§5) and when it collapses a **growing
transcript** across a long build (§1–3).

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
| Quality held flat under reduction — **literal QA suites** | GSM8K **0.870 → 0.870**; TruthfulQA **0.530 → 0.560** | **GSM8K 0.96 → 0.96** (Δ 0.0, N=50); **TruthfulQA MC1 0.667 → 0.697** (Δ +0.030, N=33) — measured on Plateau's own collapse path (§5a) |
| Quality held flat under reduction — **multi-step builds** | (n/a — headroom is single-prompt) | collapse A/B **completion 1.0 → 1.0** (§1b); demo6b **32/32 & 36/36 tests** (§2); C3 **1.0/1.0** (§3) |
| Reduction achieved at that quality | SQuAD v2 **@ 19 %** compression; BFCL **@ 32 %** compression | **QA conditioning context cut 63.3 % (GSM8K) / 59.8 % (TruthfulQA)** at held accuracy (§5a); **~99.7 % working-context cut** at the wall (694 vs 218,094 tok, §1b); slope cut to **1.5 %** (demo6b) / **1.2 %** (C3) |
| Real-workload savings | **92 / 92 / 73 / 47 %** | live bounded-parent run: **0 compactions**, bypass:signal **≈531:1** (BENCHMARKS.md §1) |

### Where Plateau is stronger, and where the comparison does **not** map

**Plateau is stronger on the magnitude and the layer of the reduction.** headroom's reductions are
**19–32 %** payload compression at flat accuracy; Plateau's collapse A/B holds **completion parity while
cutting context ~99.7 %** at the step where the full-history arm goes *over-window and collapses*. That is
a qualitatively different regime: headroom keeps accuracy while *shrinking a request*; Plateau keeps
task-completion while *preventing the session from collapsing at all*. The slope result (§3, CI-bounded)
is something headroom does not report — Plateau shows the bounded arm's context **does not grow** with
task length, which is the property that matters for long-horizon agents.

**Where the comparison does — and does NOT — map, stated honestly:**
- **Now there IS a literal-suite comparison.** Plateau has run **GSM8K (N=50) and TruthfulQA MC1
  (N=33)** through its real collapse path (§5a): **0.96 → 0.96** and **0.667 → 0.697** at **63 % / 60 %**
  conditioning-context compression. These sit on headroom's *own* axis (standard-suite accuracy under
  payload reduction) and are directly comparable to headroom's GSM8K 0.870→0.870 / TruthfulQA
  0.530→0.560 rows — same kind of number, both "accuracy held under compression." **SQuAD v2 and BFCL
  remain un-run on purpose** (§5b): their conditioning context *is* the answer substrate, so a Plateau
  collapse there would compress the answer, not a prior — no fair mapping, no invented score.
- **Still a different quality instrument for the multi-step claim.** Plateau's *native* evidence (§1–3)
  is **completion/test parity** on multi-step builds, not graded QA accuracy. The QA table (§5) is the
  single-prompt bridge to headroom's instrument; the collapse-A/B / demo6b / C3 results are a
  **different, complementary** measurement (collapse avoidance across a session) and should not be
  quoted as if they were QA accuracy.
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
**real and strong at two layers now**. (1) On headroom's *own* instrument: **GSM8K 0.96 → 0.96** and
**TruthfulQA MC1 0.667 → 0.697** with the conditioning context cut **~60–63 %** (§5a), measured PAID
through Plateau's real collapse path — accuracy held (or nudged up within noise) under compression, the
literal headroom-style claim, earned not asserted. (2) At its native session layer: bounded
working-context at **completion/test parity** with a **~99.7 % context cut** at the collapse wall (§1b),
a **66.6× / 80.4× flatter growth slope** at full test parity (§2/§3, CI-excludes-zero), and a
**GATE-CHEAP** (~13 µs/fact) cost of preserving it (§4). Against headroom's published table, Plateau now
shows **comparable accuracy-held-under-compression on the literal suites** *and* a **far larger reduction
at the session layer headroom does not touch**. The honest caveats remain: TruthfulQA is **N=33 not 50**
(budget-capped, labelled), SQuAD/BFCL are **un-run by design** (§5b), and the multi-step "1.0 → 1.0"
parity is a **coarser instrument** than graded QA accuracy and must not be quoted *as if* it were
headroom's "0.870 → 0.870". The two systems are **best read as complementary layers of the same idea**;
this file shows where they meet (§5) and where they do not (§1–3), and invents nothing.

---

— all numbers sealed-sourced or freshly logged this session · results **LOCAL**, unpublished · reproduce
commands verified (spot-check in commit message) · /halt
