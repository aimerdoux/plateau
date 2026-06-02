# demo6b readout — real-workload 2-arm efficiency re-test (isolation-clean)

LOCAL ARTIFACT — NOT committed/pushed/published. Awaiting operator go.
Prereg: `demo/demo6_prereg.md` (committed 386b6b7, precedes data). Locked rule
`demo/harness4.py` reused byte-for-byte (sha256 `e4484988…d3f1bb1`, asserted at score time).
Sealed raw in `demo/raw6b/` (38 files, manifest verified); verdict reproduces in a fresh
process. This run SUPERSEDES the banked `raw6` (see "Relationship to raw6").

## Result

- **EFFICIENCY (arm2 vs arm1): WIN — and isolation-clean.**
  Both arms PASS the objective check in **6 steps, 0 rework steps**. arm1 (full-history)
  context climbs 365→37405 tok (slope **6859.7**); arm2 (plateau-efficiency) stays bounded
  508→1075 tok (slope **103.0** ≈ **1.5%** of arm1, far under the 25% WIN bar). Completion
  parity held (both reach PASS; arm2 never FAILs while arm1 PASSes).
- **AUTONOMY: not tested.** demo6 is 2-arm by design; demo4's pre-committed NULL stands.

## Per-step context (sealed, deterministic `tok()`)

| arm | s1 | s2 | s3 | s4 | s5 | s6 | slope | steps→PASS | errors | PASS |
|---|---|---|---|---|---|---|---|---|---|---|
| arm1 full-history     | 365 | 1494 | 3753 | 8568 | 18186 | 37405 | 6859.7 | 6 | 0 | ✓ (32 tests) |
| arm2 plateau-efficiency | 508 | 707  | 788  | 856  | 941   | 1075  | 103.0  | 6 | 0 | ✓ (36 tests) |

Chart: `demo/context_per_step6b.png` (rendered from sealed data).

## Method integrity

- Baseline attested on a pristine arm repo BEFORE the run: 26 tests, probe fails closed
  ("no ground_report API (L4 missing)"). Success bar = `pytest ≥ 32` AND the
  `probe_verification_chain.py` full-pipeline probe (live-admit → mutate → stale-propagation
  through L1–L5 → fail-closed). Binary, no grading.
- Mock-plumb (free, deterministic) PASS before any paid dispatch: all four efficiency
  branches fire; check returns PASS on a reference L1–L5 impl (≥32) and FAIL on baseline (26);
  seal→score round-trips.
- 2 pristine repo copies (`git archive HEAD`, baseline 26), identical task/seed/check/cap(12).
- Sealed write-once into `raw6b/` BEFORE scoring; recompute (fresh process) PASS: chain+files
  verify, `context_tokens` re-derive from sealed prompt bytes, harness4 pin intact, verdict
  reproduces (38 sealed files).
- **Bounded orchestrator:** each step's coding subagent was spawned fresh and read ONLY its
  arm's prompt FILE (+ its own repo copy) — no session history, no other-arm awareness, no
  experiment framing. The orchestrator only ever handled token counts, paths, and bounded
  check JSON; it never ingested the growing transcript (arm1's 37k-tok step-6 prompt was read
  by the subagent, not the orchestrator).
- **Isolation attestation (on sealed bytes):** at every step the arm1 vs arm2 prompts share a
  1545-byte byte-identical head with NO arm token; the sole differing bytes are the context
  payload (arm1 transcript vs arm2 bounded signal). The arms differ ONLY in the context block.

## Relationship to raw6 (why this re-run exists)

The earlier banked run `raw6`/`verdict6.json` also scored EFFICIENCY=WIN and is length-valid
(arm1 climbed 6 steps) and recompute-clean — BUT its prompts were produced by an assembler
that put an arm-identity token in the prompt head (`[demo6 arm=arm1_fullhistory …]` vs
`arm=arm2_efficiency`), so its arms differed in more than the context block: a breach of the
pre-registered byte-identical-head invariant (a mild behavioral-prime confound, not a content/
session leak). raw6b re-runs the SAME feature at the SAME length with the corrected
byte-identical-head assembler; the WIN reproduces isolation-clean. **`raw6` was left
immutable** (write-once); raw6b is the governing result.

## Provenance note

The demo6 wrapper scripts were corrected after raw6 (assembler head-identity fix + env-based
output-dir parametrization so raw6b would not touch sealed raw6). raw6b was produced by the
current corrected wrappers. raw6's code-of-record is its own sealed prompt bytes.

## Honest caveats

- n=1 per arm. Absolute magnitudes are modest (arm1 peaks ~37k tok), consistent with the
  project's prior "toy magnitudes" caveat; the bound (100×+ slope gap) and direction are
  decisive, the scale is small.
- Agent agency under identical task/check: arm2's subagents added tests incrementally (suite
  29 by L3, 36 at L6); arm1 added its tests at L6 (suite 32). Both reached PASS at step 6 with
  0 errors — parity unaffected.

## Guard / finality

- arm1 PASS at **step 6 ≥ 4** → clears the prereg's `<4-step → UNSCORABLE` guard; this is a
  scorable run, not a second UNSCORABLE.
- Per the prereg EXIT and the operator's instruction, this verdict is **FINAL** — no third
  attempt. Results not committed/published without operator go.
