# demo6 readout — 2-arm real-code efficiency re-test (verification chain)

LOCAL ARTIFACT — NOT committed/pushed/published. Awaiting operator go.
Prereg: `demo/demo6_prereg.md` (committed 386b6b7, precedes this run). Locked rule
(`harness4.score`, 25%/4× bar, climbs guard) reused BYTE-FOR-BYTE, hash-pinned and
re-verified intact at scoring. Sealed raw in `demo/raw6/` (38 files); verdict reproduces
in a fresh process.

## Result — efficiency axis (the one demo4 left UNSCORABLE)

**EFFICIENCY (arm2 vs arm1): WIN.**
arm1 climbed materially across **6 dependent steps** (368 → 37,321 tok, ~101×, slope
6839); arm2 stayed **bounded** (514 → 1,555, ~3×, slope **203 = 3.0% of arm1**, far under
the 25% bar — a ~34× margin); **both reached PASS** (completion parity held). Computed by
the reused locked rule, not declared. This is the clean, scorable efficiency win demo4
could not produce — here the task was long enough (a strictly serial 5-layer feature) that
the full-history arm actually accumulated a multi-step climbing transcript.

**Autonomy: NOT re-tested.** demo4's pre-committed NULL stands; demo6 is 2-arm by design
(the scorer's autonomy field was fed a dummy arm3:=arm2 and discarded).

## Per-step context (sealed, deterministic token count)

| arm | s1 | s2 | s3 | s4 | s5 | s6 | slope | steps→PASS | errors | PASS |
|---|---|---|---|---|---|---|---|---|---|---|
| arm1 full-history    | 368 | 1541 | 3806 | 8592 | 18148 | 37321 | 6839.2 | 6 | 0 | ✓ (33) |
| arm2 plateau-efficiency | 514 | 926 | 1188 | 1468 | 1470 | 1555 | 203.3 | 6 | 0 | ✓ (34) |

arm1 grows ~exponentially (each step carries all prior prompts+replies); arm2 plateaus
(~1.5k) — the bounded signal. arm1's 37k-token step-6 prompt lived on disk + in the
dispatched subagent; the orchestrator only ever held token counts + bounded check records.

## The task (forced ≥5 serial steps — demo4's fix)

A strictly serial "verification chain": L1 `command_output` kind → L2 `all_of` composite
→ L3 continuum lossless carry+guard → L4 `ground_report` → L5 `python -m plateau.report`
CLI → L6 ≥6 tests + docs. The success check (pytest ≥32 AND a full-pipeline probe) cannot
pass until ALL layers exist — no shortcut path. Both arms traversed the identical layer
sequence (this also removes demo4's path-divergence confound). arm1 reached PASS in 6 steps
(not <4 → the "task too short" UNSCORABLE guard did not fire).

## Method integrity

- Pre-flight: all four Plateau trees (raw/raw2/raw3/raw4) verify on their own chains;
  baseline 26 → threshold 32. (raw4 first tripped a FALSE alarm — my one-liner used the
  wrong root; raw4 was sealed with root=demo/raw4 and verifies clean there.)
- Mock-plumb BEFORE any paid dispatch: all efficiency branches fire via the reused scorer;
  the check PASSes a reference 6-layer impl and FAILs baseline; seal round-trips.
- 2 pristine arm repos (git archive HEAD), identical task/seed/check/step-cap(12).
- Sealed write-once BEFORE scoring (root=demo/raw6). Recompute (fresh process) PASS:
  chain+files verify, context_tokens re-derive from sealed prompt bytes, harness4 pin
  intact, verdict reproduces (38 sealed files).

## FORK LOG (full disclosure)

- **fork demo6-F1 (probe L5 calling-convention bug — material, disclosed):** at step 5 the
  probe's *in-process* `report.main(["report", path])` check failed for arm2. Diagnosis
  showed arm2's code was CORRECT: its actual `python -m plateau.report <file>` CLI works
  (the prereg's real L5 spec); the probe had imposed an UNSPECIFIED explicit-`main(argv)`
  convention (program-name-first) that arm1 happened to match and arm2 (bare-args) did not.
  Leaving it would have scored arm2 FAIL→PARTIAL_FORGETS and FALSELY blamed "bounded-context
  amnesia" for a probe bug. Fix (made before sealing, applied identically to both arms):
  test L5 via the real `-m` CLI on a file_hash composite (whitelist-independent, unambiguous;
  a fresh CLI process cannot carry the process-local command_output whitelist), with
  command_output staleness still proven in-process (gate/inflate/ground_report). Re-validated:
  reference impl still PASSES, baseline still FAILS. Re-recorded step 5 for BOTH arms under
  the corrected probe. NOTE: the WIN's core (the slope gap) is independent of this fix — it
  only affected arm2's completion (parity), and arm2 genuinely completed the spec (34 tests,
  full probe pass). The locked scorer + 25%/4× thresholds were NOT touched.
- **fork demo6-F2 (probe assertion bug, during mock-plumb):** the stale-child check used a
  `json.dumps` substring match that broke on quote-escaping; fixed to inspect `stale_children`
  structurally. Pre-data.
- **fork demo6-F3 (seal-root convention):** raw4/raw6 sealed with root=seal-dir (bare-filename
  rel_paths); raw/raw2/raw3 with root=repo. Each verifies on its own chain; recompute uses the
  matching root. Noted, not a defect.

## Honest caveats

- The efficiency WIN is strong on the slope axis (arm2 = 3% of arm1) and on parity (both
  PASS). The one judgment call is demo6-F1, disclosed above; without it the run would have
  produced a FALSE PARTIAL_FORGETS, so the fix produces the honest result rather than rescuing
  a win — but the operator should weigh that it was made after seeing arm2's step-5 failure.
- arm1's climb is now genuinely large (37k by step 6), unlike demo4's compact 2-step jump —
  the longer serial task achieved exactly what the re-test set out to test.
- This is one paired run (no replication / CI). It demonstrates the bounded-context efficiency
  win holds on a real ≥5-step coding task; it does not estimate variance.
