# BENCHMARKS — every number, sourced

Plateau's proof is not a synthetic benchmark suite; it is a **real multi-hour autonomous run** plus
sealed, recompute-verifiable demos. This file collects the numbers and **sources each one to the
artifact it came from**. Where a figure was a round estimate in a run brief and the live API/meter
disagreed, the **measured** value is authoritative and the estimate is shown struck-through in prose.

Two roots:
- The **live `wavex-os` run** metrics come from on-disk meters + live API, written up in
  `/Users/geniex/wavex-os/.plateau-agency/reports/AGENCY_RUN_REPORT.md` (parent run) and
  `FLEET_REPORT.md` (the fleet beneath it). These are **LOCAL, unpublished** artifacts.
- The **sealed demos** ship *in this repo* (`demo/`) and re-verify from the repo root; the
  **continuum cycles** live in the parent research tree (`bmacp-trunk`). See [`RESULTS.md`](RESULTS.md)
  for the full sealed-verdict table and per-row re-verify commands.

> Quick local readout of the run table: `python -m plateau.agency.bench_summary`.

---

## 1. The bounded-parent run

**Source:** `wavex-os/.plateau-agency/reports/AGENCY_RUN_REPORT.md` §1, §3, §4
(meters `.plateau-agency/meters/{onboarding,connectors,fleet-launch,fleet-observe}.jsonl` + `.status`,
live `gh pr view`). Run window 2026-06-03, 11:28:28 → 14:43:18 local (≈3h15m envelope); repo
`aimerdoux/wavex-os` @ `e872882`.

The headline: a bounded parent orchestrator drove **four independent missions** and **never once
compacted its own context.**

| Metric | Value | Source |
|---|--:|---|
| Bounded orchestrators (missions) | **4** | §1 — `connectors`, `fleet-observe`, `fleet-launch`, `onboarding` |
| Parent compactions over the run | **0** | §1, §5 — per-step signal stayed flat start to finish |
| Orchestrator-signal grand total (all steps, all missions) | **76,030 tok** | §3 aggregate table |
| Per-step signal band | **300 → 1,700 tok** | §3 — never trends upward |
| Σ worker cache_read | **40,230,750 tok** | §3 aggregate table |
| Σ worker input | **154,917 tok** | §3 aggregate table |
| Σ worker output | **238,753 tok** | §3 aggregate table |
| Grand worker total (in+out+cache_read) | **40,624,420 tok** | §3 aggregate table |
| Worker context that **bypassed** the parent (cache_read + input) | **40,385,667 tok** | §4 ratio table |
| **Bypass : signal ratio** | **≈ 531 : 1** | §4 — 40,385,667 ÷ 76,030 (**observed for this run**) |
| Peak single-step cache_read (discarded with its worker) | **7,294,973 tok** | §3 — fleet-launch step 13, resume-API worker |
| 2nd-largest single-step cache_read | **5,261,868 tok** | §3 — onboarding auth-coverage worker |
| Total findings | **115** | §3 aggregate table |
| Total work steps (excl. 50 poll waits) | **51** | §3 aggregate table |
| Sequential-equivalent work | **8,650 s ≈ 2.40 h** | §3 aggregate table |
| PRs emitted | **3** (all `OPEN`, **never merged**) | §1, §6.A |

### Per-mission loop shape (§2, §3)

| Mission | Work steps | Σ cache_read | Peak step cache_read | PRs |
|---|--:|--:|--:|--:|
| onboarding | 13 | 20,966,484 | 5,261,868 | 1 |
| connectors | 13 | 6,510,224 | 1,500,966 | 1 |
| fleet-launch | 17 | 12,754,042 | 7,294,973 | 1 |
| fleet-observe | 8* | 0 (per-agent workers tracked out-of-band) | 0 | 0 |

\*fleet-observe logged 58 lines (50 `poll-fleet.ready` waits + 8 real steps); it spawned 19 read-only
workers whose cost is tracked out-of-band (≈ $18.44, §3).

### The footprint-law claim, stated exactly

`PARENT_TURNS = O(agents + resumes)`, independent of `N` (internal step count), is a **design
property** of the parent→orchestrator→worker contract — **not** a swept-`N` live experiment. This run
**corroborates** it: 76,030 signal tokens total and **0 compactions** while 40.39M worker tokens
flowed underneath. The bound on the token *slope* is proven separately and under control (§4 below).

### The 3 PRs — emitted, never merged (§6.A)

**The agency is code-enforced to never merge, never force-push, never push to `main`** (see
`plateau/agency/README.md` → Safety model). All three were `OPEN` at report time:

| PR | Title | +add | −del | files |
|---|---|--:|--:|--:|
| [#44](https://github.com/aimerdoux/wavex-os/pull/44) | force devDeps in dev install (paperclip boots under `NODE_ENV=production`) | 2 | 2 | 1 |
| [#45](https://github.com/aimerdoux/wavex-os/pull/45) | gate unauthenticated `/api/connectors/*` routes + harden env write | 41 | 10 | 4 |
| [#46](https://github.com/aimerdoux/wavex-os/pull/46) | gate 4 unauthenticated control-plane + inference-allocation endpoints | 49 | 5 | 2 |

### What an inline single agent would have hit (§5 — labelled estimate)

Forcing the same 40,385,667 bypassed tokens through one ~200,000-token window ≈ **~202 forced
compactions** (`40,385,667 ÷ 200,000 ≈ 201.9`). The bounded run suffered **0**. This compaction count
is an **explicitly modelled estimate**, as is the run's **$16–35** USD cost (§3) — both flagged as
estimates in the source report; every other number above is a real meter/API read.

---

## 2. The 19-agent fleet beneath it

**Source:** `wavex-os/.plateau-agency/reports/FLEET_REPORT.md` (live Paperclip control plane
`http://127.0.0.1:3100` — `/agents`, `/issues`, `/heartbeat-runs`). Company `tony-apple-qa`
(`c293df60-…`). `fleet-launch` ignited this fleet; `fleet-observe` read it back, non-interfering.

| Metric | Value (live API) | Source |
|---|--:|---|
| Agents (all `claude-sonnet-4-6`) | **19** | §1 roster |
| Issues total | **500** | §2 |
| Issues done | **439 (88%)** | §2 |
| Heartbeat runs total | **2,499** | §3 |
| Run success rate | **83.1%** (2,076 succeeded) | §3 |
| Failures that were upstream rate-limit/quota | **207 of 296 (70%)** | §3 — infra ceiling, not agent logic |

> **Integrity note on the fleet numbers.** The run brief carried round estimates (~441 done, ~2,482
> runs). The **live API is authoritative** and reports **439 done / 2,499 runs**; `FLEET_REPORT.md` §2
> records the discrepancy explicitly ("Brief estimated ~441 done … Live API: 439"). We publish the
> measured counts, not the estimate — that is the same discipline as the sealed demos.

---

## 3. Bounded context at no recall penalty (sealed demos)

The bound costs nothing: completion parity holds in every efficiency win. Numbers copied from sealed
verdict files; re-verify commands in [`RESULTS.md`](RESULTS.md).

### demo6b — real code (the headline sealed result)

**Source:** `demo/verdict6b.json` (slopes) + `demo/raw6b/*_completion.json` (endpoints, test counts);
readout `demo/demo6b_readout.md`. Re-verify: `DEMO6_RAW=demo/raw6b DEMO6_VERDICT=demo/verdict6b.json
python demo/recompute_demo6.py` → **PASS, 38 sealed files**.

| arm | s1 | s6 | slope | tests | PASS |
|---|--:|--:|--:|--:|:--:|
| full-history | 365 | 37,405 | **6,859.7** | 32/32 | ✓ |
| Plateau | 508 | 1,075 | **103.0** (≈1.5%) | 36/36 | ✓ |

→ **66.6× lower context-growth slope at completion parity, zero rework.** n=1 per arm; the bound
(100×+ slope gap) and direction are decisive, the absolute scale (~37k peak) is modest.

### driver A/B — live `claude -p` workers (the real adapter)

**Source:** `demo/driver_ab_readout.md`; sealed in the parent tree at
`reports/continuum/driver_ab/{raw,verdict.json,integrity_manifest.jsonl}`. recompute PASS.

| arm | per-step context | slope | completion |
|---|---|--:|:--:|
| control (full history) | 152 → 476 → 1,210 → 2,671 → 5,607 → **11,482** | **2,100** | 6/6 |
| signal (bounded) | 172 → 234 → 290 → 347 → 403 → **460** | **57** (~2.7%, ~37×) | 6/6 |

→ **~37× gap at 6/6 parity**, and the signal-arm worker built the correct *dependent* layer
(`l6` imports `l5`) from the compact signal alone — no amnesia. n=1, 6 steps.

### gatebench — the cost axis (time + disk)

**Source:** `reports/continuum/gatebench/raw/{results,disk}.json` (parent tree, sealed;
`python -m experiments.continuum.gatebench recompute` → PASS).

- Re-grounding a carried fact via `file_hash` costs **~13 µs/fact** (per-fact median 0.0133 ms;
  marginal slope **0.0114 ms/fact**, linear). A 50-fact signal re-grounds in **0.59 ms/step**.
  Classification **GATE-CHEAP** — cheaper on time, not just tokens.
- A modeled subprocess `command_output` grounding would cost **1.93 ms/fact** (~145× file_hash,
  GATE-COSTLY) — but the core ships **only** `file_hash`; other kinds fail closed without spawning.
- Disk: carried signal **~220 B/fact, O(facts)** (bounded); sealed integrity trail **1.03 MB / 339
  files** and grows per cycle (the audit cost); avoided full-history transcript **~149 KB** for one
  short real-code demo (the disk you didn't keep).

---

## 3b. Standard QA suites — accuracy preserved under collapse (PAID `claude -p`)

The accuracy-preserved-under-compression table, measured on Plateau's real collapse path
(`emit → inflate → _render`). Both arms hit the same `claude -p` backend / same scorer; only the
conditioning payload differs (full few-shot exemplars vs the bounded Plateau signal). Per-item logs
sealed under `reports/qa_suite/<suite>/`.

| suite | metric | baseline → Plateau | Δ | compression | N | cost (this resume) |
|---|---|--:|--:|--:|--:|--:|
| **GSM8K** | exact-match (final integer) | **0.96 → 0.96** (48/50→48/50) | 0.000 | **63.3%** (472→173 tok) | 50 | 66 calls / 600,647 billed-new tok / ~$10.96 |
| **TruthfulQA MC1** | single-correct option pick | **0.667 → 0.697** (22/33→23/33) | +0.030 | **59.8%** (338→136 tok) | 33\* | 67 calls / 883,184 billed-new tok / ~$11.38 |

\*TruthfulQA stopped at **N=33** when the resume's ~1.5 M billed-new-token budget guard fired; 33 items
scored on both arms (the half-finished item dropped). Real partial, labelled — not padded.
**SQuAD v2 / BFCL are not run by design** (their conditioning context is the answer substrate — see
`QUALITY_BENCHMARKS.md` §5b); the runner refuses them with a logged reason rather than inventing a score.

- Source: `reports/qa_suite/{gsm8k,truthfulqa}/verdict.json` + `items.jsonl` + `raw/`.
- Reproduce: `PYTHONPATH=<repo>/plateau python -m experiments.qa_suite.run --suite gsm8k --n 50 --go`
  (swap `--suite truthfulqa`). Harness: `experiments/qa_suite/`; tests: `tests/test_qa_suite.py`.

---

## 4. Sealed continuum cycles (mechanism probes)

Full table, sealed paths, and per-row re-verify commands are in [`RESULTS.md`](RESULTS.md). Summary:

| cycle | verdict | one-line result |
|---|---|---|
| **C3** (n=10) | **WIN** | control slope 22.903 vs signal 0.285; CI [21.941, 23.128] excludes 0; completion 1.0 both |
| **C4** (×2 runs) | **WIN** | carried-signal trajectory PR ~2.3–2.65 vs cold ~4.7–4.8; replicated; necessary-not-sufficient |
| **C9** (c9b, clean) | **CORRESPONDENCE-DOMINATES** | high mean corr 0.975 vs broken 0.048; gap_axis_effect 0.0; perf_gap 1.0 |
| **C7** | **NULL** (ceiling-tie) | both arms 0/48 non-existent edges (perfect faithful traversal); scramble control 1.0 confirms genuine deref — a tie at the faithful ceiling, **not** confabulation |

**Four published nulls/ties** — C7 plus demo2 (NULL near-miss), demo3 (UNSCORABLE), demo4 (AUTONOMY
NULL) — are the integrity signal. We don't cherry-pick; the bound is bounded context at no recall
penalty, **and nothing stronger**.

---

## How to re-verify

```bash
# the live-run numbers, printed from the sourced report values:
python -m plateau.agency.bench_summary

# the sealed real-code headline (fresh process → PASS):
DEMO6_RAW=demo/raw6b DEMO6_VERDICT=demo/verdict6b.json python demo/recompute_demo6.py

# the 3-arm NULL (fresh process):
python demo/recompute_demo4.py
```

The continuum cycles (C3/C4/C9/C7/gatebench/driver_ab) re-verify from the parent research tree
`bmacp-trunk`; see [`RESULTS.md`](RESULTS.md) for the exact commands.

---
— [D-014] · every figure sourced (live run = on-disk meters/API; demos = sealed verdicts) · results **LOCAL**, unpublished · /halt
