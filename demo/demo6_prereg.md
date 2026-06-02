# Plateau real-workload efficiency re-test (demo6) — PRE-REGISTRATION

Written and committed BEFORE building or running, so it provably precedes the data.
Engineering only — context efficiency vs task completion; no phenomenality.

## Why this exists (what demo4 left open)

demo4 came back **EFFICIENCY = UNSCORABLE**: the full-history arm reached the success
check in only **2 steps**, so its context was a single increment, not a multi-step
climb — the task was too short to score the efficiency axis. (demo4 AUTONOMY = NULL,
clean and pre-committed; **demo6 does NOT re-test autonomy** and will not re-read that
banked NULL.) demo6 changes **ONLY task length**: a genuinely larger, strictly serial
real-code feature so the full-history arm accumulates a real ≥5-step climbing transcript.

## What is reused BYTE-FOR-BYTE (the binding rule)

`demo/harness4.py` — the locked scorer (`score`), token counter (`tok`), slope
(`_slope`), per-arm summary (`_arm_summary`), and `make_arm_repo`. The efficiency
decision rule, the **25% / 4× WIN bar**, and the **anti-rig "arm1 must climb" guard**
are exactly demo4's and are NOT modified. Pin for proof:
`harness4.py sha256:e4484988a77d52b76e37ef4a7fc73f6ff2d69cb504cb570ef8a27da65d3f1bb1`
(re-checked unchanged at scoring time). Only the **task spec + its probe + the test
threshold** differ (because the task differs) — never the rule.

## Two arms only (autonomy is answered; not re-tested)

1. **arm1 FULL-HISTORY** — each step's prompt carries the entire prior transcript
   (instructions + the agent's prior diffs/notes). Context climbs every step.
2. **arm2 PLATEAU-EFFICIENCY** — carry only the bounded signal (goals/stance/lessons/
   pointers/gated-facts), re-ground each step; do NOT spend freed context.

No autonomy arm. (The demo4 scorer is 3-arm; demo6 calls it with a dummy arm3 := arm2
and reads ONLY the efficiency field. The autonomy field is discarded and not reported.)

## The real task — a STRICTLY SERIAL ≥5-layer feature ("verification chain")

A pristine copy of the real `plateau` repo per arm (same commit d7857bd, 26 passing
tests). The feature is a composite-Measurement pipeline whose layers have REAL ordered
dependencies; the success check cannot pass until ALL layers are in place (no shortcut
path — this is the fix for demo4's "2 of 4 sub-tasks was enough" problem):

- **L1 `signal.py` — `command_output` kind**: whitelisted command, value =
  `"sha256:"+sha256(raw stdout)`, fail closed on nonzero-exit/non-whitelisted/missing.
  (The mutable child used to test staleness.)
- **L2 `signal.py` — `all_of` composite kind**: `source` = JSON list of child measurement
  specs `{kind,source,value}`; `reverify()` True iff EVERY child reverifies; fail closed
  on empty/malformed/unknown-child. (Depends on L1: the testable mutable child.)
- **L3 `continuum.py` — lossless carry of `all_of`**: emit/inflate/ground serialize and
  restore nested children intact; an `all_of` whose source won't parse is treated stale
  (guard, fail closed). (Depends on L2's shape.)
- **L4 `signal.py` — `ground_report(state) -> dict`**: walk verified_facts; per fact
  report {claim, kind, live, stale_children}; descend `all_of` and name failing children;
  aggregate {n_live, n_stale}. (Depends on L2+L3.)
- **L5 `plateau/report.py` (new) + `python -m plateau.report <blob_file>`**: inflate a
  signal blob, run ground_report, print JSON, exit 0 iff all live else 1. (Depends on L4+L3.)
- **L6 `tests/test_verification_chain.py` (new, ≥6 tests)** covering each layer + the
  cross-cut (gate admits an `all_of` only while every child is live); plus `README.md` +
  `adapters/claude_code/SKILL.md` one-paragraph docs (docs not required by the check).

Dependent ordering is real and unavoidable: L2 needs L1; L3 needs L2; L4 needs L2+L3;
L5 needs L4+L3; L6 (green) needs L1–L5. A late step's full-history prompt must carry the
earlier layers' signatures.

## Objective success check (identical for both arms; harness-run, not judged)

PASS = BOTH of:
1. `pytest -q` exits 0 with **≥ 32 tests** (26 original + ≥6 new), AND
2. the full-pipeline probe `demo/probe_verification_chain.py`: set whitelist; build a
   `command_output` child; wrap it in an `all_of` composite (with a stable `file_hash`
   child); assert composite re-verifies, gate admits it, emit→inflate round-trips it live,
   `ground_report` n_stale=0, CLI exit 0; then MUTATE the command output and assert the
   composite re-verify False, gate drops it, inflate flags it stale, `ground_report` names
   the stale child, CLI exit 1. This probe can only pass if L1–L5 all work.

Binary, reproducible, no grading. FAIL otherwise.

## Metric & decision rule (reused from harness4.score, applied WITHOUT override)

- `context_tokens[step][arm]` = deterministic `tok()` of the sealed per-step prompt.
- **Efficiency (arm2 vs arm1):**
  * **UNSCORABLE** if arm1 does not climb materially (slope not positive / single
    increment → task STILL too short) OR check not objective OR arms differ.
  * **WIN** if arm1 climbs AND arm2 slope ≤ 25% of arm1 slope AND completion parity
    (both reach PASS; arm2 not FAIL while arm1 PASS).
  * **PARTIAL_FORGETS** if arm2 bounded but FAILs while arm1 PASSes (amnesia, not a win).
  * **NULL** if arm2 slope not materially below arm1 (no bound achieved).

## Pre-registered prediction (honest)

| claim | prediction | conf |
|---|---|---|
| Efficiency WIN: arm1 climbs ≥5 steps, arm2 bounded at completion parity | LIKELY WIN | 0.70 |

NULL/UNSCORABLE are live. I do NOT force a win.

## Guards (pre-committed; second-attempt discipline)

- Do NOT modify harness4 or the 25%/4× thresholds after seeing data (the demo4 scorer is
  the binding rule; reused byte-for-byte, hash-pinned above).
- **One re-attempt only.** If arm1 AGAIN reaches PASS in **< 4 steps**, the task is still
  too short → report **UNSCORABLE and HALT**. Do NOT lengthen further this run. A second
  UNSCORABLE is itself the honest finding: "real-code efficiency is hard to demonstrate at
  runnable task sizes." Iterating until arm1 climbs is goalpost-chasing and is forbidden.
- The per-step dispatch instruction is demo4's verbatim ("advance ONE coherent sub-task
  this step, then STOP; do not attempt the whole feature at once") — NOT strengthened to
  manufacture steps. The feature's serial depth, not coaching, must produce the climb.
- Mock-plumb the harness free (all branches + check PASS/FAIL + seal round-trip) BEFORE
  any paid dispatch.

## Integrity

Per-step prompts/replies/checks + per-arm completion records sealed write-once to
`demo/raw6/` (sealed with `root=demo/raw6`, matching raw4's convention) BEFORE scoring.
Score reads only sealed records; recompute (fresh process) must verify chain+files,
re-derive `context_tokens` from sealed prompt bytes, and reproduce the verdict. Chart
(context-per-step, both arms) rendered from sealed data. Results NOT committed/pushed/
published without operator go.

## EXIT

Real ≥5-step serial task on both arms, sealed, recompute-verified, scored by the reused
locked rule. Report per-step context (both arms), completion parity, the efficiency
verdict, chart path, recompute result. /halt at the verdict.
