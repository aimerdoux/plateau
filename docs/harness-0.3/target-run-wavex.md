# Target run: Plateau 0.3 adapter on a real private repo (aggregates only)

A supervised, measured target run of the 0.3 adapter (branch `feat/harness-0.3`, HEAD `a3194e5`)
against a real private repository, outside `experiments/`. No target-repo paths, symbols, decision
text, or code appear below — counts, kinds, line shapes, costs, session ids and PASS/FAIL only.
Full detail (with target-repo specifics) is in the private companion report the orchestrator holds
outside this repo.

## Setup

- `plateau` was already `pip install -e`'d and importable from any directory; no install step was
  required. The `plateau` console script was already on `PATH`, so `plateau init` wrote `plateau
  hook <mode>` commands.
- A git worktree of the target repo was created (a workaround was needed because the target's main
  checkout already had the target branch checked out; a differently-named local branch was used
  for the worktree and the required remote branch was updated via an explicit push refspec at the
  end — no other branch was touched).
- `plateau init` (project scope) installed **9 distinct hook modes**: `parent`, `pre`, `post`,
  `receipt`, `snapshot`, `inject`, `handoff`, `lift`, `ledger` — across `SessionStart` (×2 matchers),
  `UserPromptSubmit`, `PostToolUse`, `PreCompact`, `Stop` (×3), `SessionEnd` (×2), `SubagentStop`.
- `.plateau/config.toml`: `[bridge] enabled = true`, `[lab] shadow_probes = true`,
  `[private_ring] remote = "" key = ""`.
- `plateau doctor` before the run: **7/7 PASS**.

## Task session

One continuing `claude -p` session (session id `98e6f070-0b45-4a7c-9e35-fd4ccebdc09f`), 5 task
turns via `--resume`, `--autocompact 200000`, `CLAUDE_AUTOCOMPACT_PCT_OVERRIDE=40`,
`--permission-mode acceptEdits`, the D-038 `ALLOWED` Bash-subcommand allowlist,
`--disallowedTools "WebSearch,WebFetch"`, `--output-format json`.

| turn | rc | seconds | cost (USD) | num_turns |
|---|---|---|---|---|
| T1 | 0 | 89.2 | 0.2562758 | 14 |
| T2 | 0 | 82.8 | 0.2310578 | 7 |
| T3 | 0 | 330.0 | 0.8146112 | 10 |
| T4 | 0 | 139.3 | 0.3755342 | 12 |
| T5 | 0 | 28.5 | 0.0980080 | 3 |

**Task-turn cost: $1.775487.** **Shadow-probe cost: $0.00** (0 probes ran — see below).
**Grand total vs. the $5.00 cap: $1.775487 (35.5%).** All 5 turns: rc=0, success, same session id.

## Store counts (`.plateau/index.sqlite`)

- **receipts**: 36 total, all `agent=main`. By tool: Bash 20, Write 9, Read 7. 100% of receipt and
  injection rows carry `bridge_version`/`bridge_sha` identical to `config.load`'s resolved sha.
  Measured against the transcript's own tool-call log, receipt coverage was **36/38 (94.7%)** of
  real tool_use calls by the main agent — 2 calls (1 Bash, 1 Read) produced no receipt and no
  logged error.
- **nodes** by kind: `decided` 30, `command` 19, `file` 13. `symbol`, `error`, `test`, `search`,
  `tool`, `read` = 0 each. Of these, `read`, `symbol`, and `test` being permanently absent is a
  confirmed adapter bug in each case (not merely "none occurred") — see PASS/FAIL notes.
- **edges**: 36.
- **compactions**: 3 rows (k=0,1,2), each with a matching on-disk snapshot file.
- **injections**: 4 rows (1 startup + 3 compact), all `holdout=0`, all under budget (218/6000
  startup; 1662, 1797, 3293 all < 12000 compact), all carrying matching provenance.
- **decisions**: 30 rows, all with non-empty provenance. All 30 came from 3 of the 5 turns; the
  other 2 turns' decision/fact lines were dropped by the lifter because of a markdown-formatting
  mismatch against the marker regex (a model behaviour, not a store bug, but one the adapter's
  regex should tolerate).
- **turns**: **0 rows** — the store's turn-marking entry point is never called anywhere in the
  shipped hook pipeline, so this table is always empty regardless of session length. This
  cascades into `receipts_per_turn` always using its hardcoded fallback and `plateau report`'s
  "per turn" metrics being computed against a turn count that is never real.

## Ledger (`.plateau/ledger.sqlite`)

- **sessions**: 1 row, correctly mirroring receipts=36/compactions=3/injections_n=4 from the
  store. `cost_usd=0.0` — wrong (real cost was $1.775); the ledger reads cost from a transcript
  field that Claude Code never actually writes into the transcript file, only into the CLI's own
  final JSON result.
- **probes**: **0 rows.** No shadow probe ran at any point across 5 turns / 3 compactions, despite
  `[lab] shadow_probes = true`. Root cause is two-fold and confirmed by reading the code: the
  probe-scheduling function is never invoked from any installed hook mode (dead code, referenced
  only in comments/docstrings elsewhere), and — independently — it also gates on the same
  turn-count table that is always empty. No forked session was created anywhere (confirmed: the
  local Claude Code project directory for this worktree contains exactly one transcript file, the
  main session's).

## Transcript

3 `compact_boundary` events, matching exactly (3-for-3, no orphans) with 3 snapshot files and 3
compact-event injection rows.

## Handoff

`.plateau/handoff/` held 4 files: 1 correct main-agent handoff (renders correctly via `plateau
handoff --last`, matching the documented block format field-for-field) and 3 files carrying a
`subagent:<id>` label that do **not** correspond to any real delegated subagent task — their
timestamps align with the 3 auto-compaction events instead, to within a fraction of a second, and
independent transcript evidence (no sub-session markers, no real subagent tool invocation) rules
out a genuine subagent having run. This looks like an internal Claude Code hook-event side effect
being misclassified as a subagent by the adapter's agent-identification fallback. No receipt data
was misattributed as a result — only 3 extra, harmless files were written.

## CLI checks

- `plateau report` / `plateau report --json`: ran and returned a well-formed table/JSON for the
  session's one bridge version, but two of its fields (`compact/turn`, `tokens/turn`) inherit the
  turns-table bug above and are not meaningful as "per turn" figures for this run.
- `plateau lookup <words>`: returned correctly ranked, lexically-starred `decided` lines with no
  errors.
- `plateau doctor` (final): **7/7 PASS**, identical to the pre-run result (doctor's synthetic
  fixtures are insensitive to the gaps found in the real run above).

## T5 (blind re-derivation) check

T5 asked the model to document two files' exported functions' *exact signatures* without
re-reading either — a direct exercise of the bridge's carried-context use case. Verified
independently against the real files: **4/4 function signatures matched character-for-character**
(including default-parameter expressions and destructured parameters), across 2 intervening
compactions. Final test run confirmed independently: all modules' syntax checks clean; full test
suite passed (54/54).

## Acceptance PASS/FAIL

| # | expectation | verdict |
|---|---|---|
| 1 | nine hooks installed | **PASS** — 9 distinct modes across the correct events |
| 2 | receipts for every tool call | **PARTIAL** — 36/38 (94.7%) of real tool_use calls got a receipt; 2 silently missing, no logged error |
| 3 | nodes of kinds `read` and `decided` present | **FAIL** — `decided` present (30); `read` never appears (confirmed bug in the Read-response text extractor) |
| 4 | ≥1 compaction with snapshot+inject pair | **PASS** — 3/3, fully paired |
| 5 | injections under budget with provenance | **PASS** — 4/4 under budget, 100% carry bridge_version/bridge_sha |
| 6 | handoff files for the main agent | **PASS** — correct file present and renders correctly (3 extra spurious subagent-labeled files also exist, see above) |
| 7 | ledger row | **PASS** (row present, correct counts) with a noted defect — `cost_usd` always 0.0 |
| 8 | ≥1 shadow probe on a fork | **FAIL** — 0 probes ran; probe scheduling is not wired into any installed hook, and would be blocked by the empty turns table even if it were |
| 9 | doctor PASS | **PASS** — 7/7 both before and after the run |

**Net: 6 PASS, 1 PASS-with-defect, 1 PARTIAL, 2 FAIL** (of 9). The two clean FAILs (`read` nodes,
shadow probes) and the turns-table root cause behind several of the other defects are the
highest-value findings from this run — they are reproducible from code inspection alone (not
run-specific flukes) and would recur on any project using this exact bridge version.

## Hook errors

None. No `.plateau/hooks.log` line anywhere in the run matches an error/exception/traceback
pattern — every gap above is a *silent* one (a row or classification the plan calls for simply
never gets produced), not a logged failure.

---

## Run 2 (after fixes)

A second, smaller supervised run (2 task turns, same worktree, `plateau init` re-applied
idempotently to pick up one new hook wiring) verifying the 9 defects this run's findings drove.
New session id: `58031f63-2e1c-456a-8843-f6a7c753db41`. `plateau doctor` before the run: 7/7 PASS.

**Cost**: 2 task turns, $0.1994296 total, well under the $1.50 verification cap. Both turns
succeeded (rc 0, success).

**Store counts (new session)**: 6 receipts (100% of the new session's own tool_use calls — no
receipt gap this run), nodes by kind now include `read` (8), `symbol` (2), and `test` (1) — all
three were permanently 0 in run 1 — alongside `file` (4), `decided` (1), `command` (1). 1
injection under budget. 1 decision recorded with provenance, lifted from a markdown-bold-wrapped
marker line. `turns` table: 2 rows (previously always 0 regardless of session length).

**Ledger**: 1 sessions row for the new session (receipts/injections match the store exactly).
**2 probe rows**, both graded `exact`, each on its own forked session id distinct from the main
session id — the shadow-probe path fired end-to-end for the first time. `cost_usd` on this
session's ledger row is still 0.0, as expected: this run used the same raw `claude -p`/`--resume`
invocation style as run 1 (per the verification instructions), not `plateau resume` — the one call
site the cost fix is wired into; that fix is unit-tested directly instead.

**Handoff**: 1 file (the main session's), 0 spurious subagent-labeled files. No compaction
occurred in this short run to exercise the compaction-summarizer edge case live; that fix is
covered by a targeted unit test against the exact payload shape run 1 found (an `agent_id` with no
`agent_type`).

**`plateau report`**: probe recall by lag and by compactions-crossed are now real, non-null
numbers (both probes exact) instead of `{}`/`null` throughout, as in run 1.

**`plateau doctor`** (final): 7/7 PASS, same shape as before the run.

## Acceptance PASS/FAIL, run 2

| # | finding (run 1) | run 2 verdict |
|---|---|---|
| 1 | `read` nodes never appear | **PASS** — 8 read nodes from real receipts |
| 2 | `symbol` nodes never appear for JS | **PASS** — 2 symbol nodes from a real Write |
| 3 | `test` nodes never appear for `node --test` | **PASS** — 1 test node |
| 4 | `turns` table always empty | **PASS** — 2 rows, one per turn |
| 5 | markdown-wrapped decision/fact markers dropped | **PASS** — a bold-wrapped marker was lifted |
| 6 | spurious subagent handoff files per compaction | **PASS** (by absence this run; unit-tested directly for the live case, not compaction-exercised here) |
| 7 | shadow probes never fire | **PASS** — 2 probes fired, spawned detached, both graded, both on distinct fork sessions |
| 8 | 2 tool calls with no receipt, no logged cause | **PASS this run's measurement** (100% coverage; root cause fixed and unit-tested; not exercised live since no tool call errored this run) |
| 9 | ledger `cost_usd` always 0.0 | fix unit-tested and wired into the resume path; not exercised by this run's invocation style (by design, not a regression) |

Full test suite: 221 passed, 1 skipped. Legacy D-037 harness: all checks passed, B≡C store parity
held. `plateau doctor`: 7/7 PASS in both the adapter repo and the target worktree, before and
after this run.
