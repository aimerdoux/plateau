# Step 4 — lab mode and private ring (offline only), doctor, docs, guardrails

Contract addendum to PLAN.md. Offline only: no `claude -p` is run in this step except by `plateau propose`, which is
implemented but not executed. Sealed records untouched.

## Ownership

| owner | files |
|---|---|
| C1 ledger-probes-holdout | `plateau/lab/ledger.py`, `plateau/lab/probes.py`, `plateau/lab/holdout.py` (unchanged unless needed), `plateau/cli.py` (`report` only) |
| C2 model-fit-promote | `plateau/lab/fit.py`, `plateau/lab/promote.py`, `plateau/lab/propose.py`, `plateau/cli.py` (`fit`, `propose`, `learn`), `model.toml` (schema only if needed), `.github/CODEOWNERS`, `.github/workflows/guardrails.yml` |
| C3 private-ring-doctor | `plateau/ring.py` (curated layer + sync), `plateau/cli.py` (`sync`, `doctor` full), `.plateau/config.toml` template `plateau/bridge/config.default.toml` |
| C4 docs | `README.md` ("The bridge and the lab", "What Plateau does NOT do" addition), `docs/d038/report.md`, `adapters/claude_code/README.md`, `.claude-plugin/marketplace.json`, `CHANGELOG.md` |
| C5 tests | `tests/test_lab.py`, `tests/test_promote.py`, `tests/test_ring.py`, `tests/test_doctor.py` |

## Ledger (`plateau/lab/ledger.py`) — `.plateau/ledger.sqlite`

One row per session (`sessions` table): session_id, agent, model_id, bridge_version, bridge_sha, receipts,
compactions, injections_n, injections_chars, holdouts, lookups, lookup_hits, rederivations, tokens_in, tokens_out,
probes_n, probes_exact, probes_fuzzy, probes_wrong, handoff_path, cost_usd, started, ended. Plus `probes`
(session_id, turn, cls, kind, lag_tokens, compactions_crossed, verdict, q_hash) and `rederivations`
(session_id, line, path). `main()` at SessionEnd: read the store, the transcript (usage fields, model id from
`message.model`, compaction lines, Read re-opens after a compaction of files read before it — D-038 definition) and
`.plateau/hooks.log` (lookups: lines `lookup q=…` written by lookup.py; add that log line), upsert the row.

## Shadow probes (`plateau/lab/probes.py`)

Generalize `experiments/d038/probes.py` (copy, then edit; the sealed file stays): `scan(transcript, root, mandated)`
and `choose(...)` unchanged in behaviour; `main()` runs from a UserPromptSubmit-independent trigger: the Stop hook
calls `plateau.lab.probes.maybe(payload, cfg)` which, every `lab.shadow_probe_every_turns` turns (turn count from the
`turns` table), picks one unprobed fact and asks it on a fork: `claude -p "<prefix><q>" --resume <session_id>
--fork-session --disallowedTools <all> --output-format json`, grades deterministically (exact: normalized equality;
fuzzy: token overlap ≥ 0.6 or line ±1 for file:line; wrong otherwise), writes the probe row to the ledger. Never in the
main session. Off unless `.plateau/config.toml` `[lab] shadow_probes = true` (default false: it spends tokens).

## Holdout

Already in `inject.py` (step 2). Ledger counts holdouts from the injections table.

## `plateau report`, `plateau fit` (`plateau/lab/fit.py`)

`report`: for this repo's ledger, per bridge_version: sessions, compactions/turn, injections chars mean, holdout vs
non-holdout re-derivations per turn (the causal estimate), probe recall by lag bucket and compactions crossed, tokens
per turn; residuals against `model.toml` cells for the same model_id × bridge_version. Prints a table; `--json`.
`fit`: refit α (recall at lag bucket 0), λ by lag/comp bucket from holdout sessions, π by bucket from non-holdout
sessions, using `lab.model`; write cells to `model.toml` only where sessions ≥ 5, else omit; never delete existing
cells; `last_updated` from `--date` (no wall clock inside library code).

## `plateau propose` (`plateau/lab/propose.py`)

Builds the prompt from `report --json` + the formal model docstrings, runs `claude -p <prompt> --disallowedTools
<all tools> --output-format json`, writes `proposals/<date>.md` (date from `--date`), ≤ 3 hypotheses, each with a
discriminating change limited to `bridge.toml` keys or `plateau/bridge/query.py`, bets with probabilities, cost.
Not executed in this step; tested with a stubbed runner.

## `plateau learn` and promotion (`plateau/lab/promote.py`)

Promotion rule (constants at the top of promote.py, changed only by a human commit):
`MIN_SESSIONS = 20` per arm, `PI_GAIN = 0.15` on far-lag presence (≥ 2 compactions crossed), `REDERIV_TOL = 0.05`,
`TOKENS_TOL = 0.05`, `RETIRE_AFTER = 60` sessions. `decide(incumbent_stats, canary_stats) -> "promote" | "keep" |
"retire"`. `learn`: computes stats from the ledger; on "promote": writes `bridge.canary.toml` over `bridge.toml`,
bumps `version` (minor), removes the canary file, writes a PR body to `proposals/promote-<version>.md` containing
only aggregates (session counts, means, margins, bucket tables) plus the sha256 of the private ledger slice, and
opens the PR through `gh` only when `--open-pr` is passed (default: write the body only). Leak test helper:
`body_leaks(body, ledger_conn) -> list[str]` returns every string from the ledger's path/symbol/target columns that
occurs in the body; `learn` refuses to write a body that leaks.

Guardrails: `.github/CODEOWNERS` lists `plateau/lab/model.py`, `plateau/lab/fit.py`, `plateau/lab/promote.py`,
`experiments/`, `docs/harness-0.3/PLAN*.md` for `@aimerdoux`; `.github/workflows/guardrails.yml` fails a PR whose
author login ends with `[bot]` or whose head branch starts with `plateau/learn-` if it touches those paths.

## Private ring (`plateau/ring.py`)

`.plateau/config.toml` template (`plateau/bridge/config.default.toml`):
```toml
[bridge]
enabled = true
[lab]
shadow_probes = false
[private_ring]
remote = ""     # git URL or path; empty = no private ring
key = ""        # env var name holding the token, never the token
```
`plateau sync`: if `remote` is empty or the env var named by `key` is unset ⇒ print "private ring: off" and exit 0.
Otherwise clone/pull the remote into `~/.plateau/ring/<sha of this repo's origin url>/`, push `.plateau/ledger.sqlite`
and `.plateau/curated.sqlite` under `<repo-key>/`, and pull them on `init`. Curated layer (`curated.sqlite`): tables
`files(path, role, uses, last_used)`, `fixes(error, fix, uses)`, `decisions(text, held, uses)`, `procedures(name,
receipt_shape, evidence_rids, uses)`. `ring.curate(store_conn, curated_conn)`: promote a receipt shape that repeats
3× into a named procedure; demote entries with `uses == 0` over the last 10 sessions (tracked by `last_used` session
count). Path-based remotes work without network (tests use a temp dir remote).

## `plateau doctor` (full)

Runs one fake PostToolUse, PreCompact, SessionStart(compact) and Stop through the *installed* hooks (reads the
project or global settings.json to find the commands; falls back to the package modules) and asserts: a receipt row,
a snapshot, an injection under budget, a handoff block; plus ledger writable, config resolves, private ring status.
Prints PASS/FAIL/SKIP per check; exit 1 on FAIL.

## Docs (C4)

README section "The bridge and the lab": what a receipt is, the three rings, the D-038 run-1 numbers **by run id**
(A far-lag 0.393, AUC 0.618 vs 0.744, re-derivations 142 vs 105, tokens/turn 143 676 vs 109 215, all "D-038 run 1,
one run, no verdict"), the two limits stated plainly (facts that never passed through a tool call are invisible to
the bridge; paraphrase queries miss lexical matches), link `docs/d038/report.md` (a one-page report of the sealed
record with the same numbers and the raw tarball hash). Add to "What Plateau does NOT do": the bridge does not make
the model smarter; it carries what it already found. Update plugin/marketplace descriptions (hooks now: SessionStart
inject, PostToolUse receipt, PreCompact snapshot, Stop handoff, SessionEnd ledger), CHANGELOG 0.3.0.

## Tests (C5)

`test_lab.py`: ledger row from a synthetic store + transcript; re-derivation count matches D-038's definition;
probe grading exact/fuzzy/wrong. `test_promote.py`: synthetic winner promoted; near-miss (π gain 0.14, or
re-derivations +6 %) rejected; `body_leaks` catches a path and a symbol planted in a body. `test_ring.py`: sync off
without key; path remote round-trip; curate promotes a 3× shape and demotes an unused entry. `test_doctor.py`: doctor
exits 0 in a temp root with the package hooks.

## Additions (operator, before step 4 started)

### S4-A1 One install story
- Move `parent`, `pre`, `post` out of `adapters/claude_code/hook.py` into the package: `plateau/hooks/__init__.py`,
  `plateau/hooks/signal.py` (same functions and outputs, byte-for-byte hook JSON; the manual's section-4 block is
  read from the package copy `plateau/agency/PARENT_AGENT_MANUAL.md`, which already ships as package data).
  `adapters/claude_code/hook.py` becomes a thin shim: every mode (nine: parent, pre, post, receipt, snapshot, inject,
  handoff, lift, ledger) dispatches to the package. `plateau hook <mode>` and `plateau init [--global]` cover all
  nine modes with the same events, matchers and timeouts as the plugin's `hooks.json`.
- Test: normalize both hook tables (plugin `hooks.json` → strip `python3 ${CLAUDE_PLUGIN_ROOT}/hook.py ` and
  ` --cc`; init output → strip `plateau hook ` / `python3 -m plateau.cli hook `) and assert they are identical:
  same events, same matchers, same mode sequence per matcher, same timeouts.
- `pyproject.toml` packages add `plateau.hooks`.

### S4-A2 Session identity everywhere a process is spawned
- Every spawn uses `plateau.bridge.common.child_env()`: `plateau resume` (done), `plateau/lab/probes.py` fork
  spawning, `plateau/agency/driver.py` `spawn_agent`, `plateau/lab/propose.py`.
- Ledger rows, handoff files and holdout hashes key on `(session_id, agent_id)`; the main agent's `agent_id` is the
  empty string. Shadow probes run for the main agent only. Holdout is keyed on the main session id.
- Evidence: preflight step 3 run 2 (`docs/harness-0.3/preflight-step3.md`, sessions `60ae9ca1…` → `607c71e2…`).
  Update PLAN.md §Handoff block v1 and the docs to say so.

### S4-A3 Guardrails are part of this step
- `.github/CODEOWNERS`: `plateau/lab/model.py`, `plateau/lab/fit.py`, `plateau/lab/promote.py`, `experiments/`,
  `docs/harness-0.3/PLAN*.md` → `@aimerdoux`.
- `.github/workflows/guardrails.yml`: fails a PR when the author login ends with `[bot]` or the head branch starts
  with `plateau/learn-` and the changed files touch those paths.
- PR-body leak test (`promote.body_leaks`) and `plateau propose` tested against a stub runner only; no live
  `claude -p` anywhere in this step. Spend in step 4: zero.

### S4-A4 Single owner for `plateau/cli.py` (concurrency rule)
`plateau/cli.py` is owned by C0 only. Every new subcommand is a thin delegation to a module entry point the module
owner implements: `plateau.hooks.signal.main(mode, argv)` (parent/pre/post), `plateau.lab.ledger.report_main(argv)`
(`report`), `plateau.lab.fit.main(argv)` (`fit`), `plateau.lab.propose.main(argv)` (`propose`),
`plateau.lab.promote.learn_main(argv)` (`learn`), `plateau.ring.sync_main(argv)` (`sync`), `plateau.doctor.main(argv)`
(`doctor`, full version; C3 owns `plateau/doctor.py`; the step-2 bridge checks move there). C0 wires them with
`importlib` and a `not available` message on ImportError, so cli.py never depends on landing order.

### Ownership for step 4 (supersedes the table above where they differ)
| owner | files |
|---|---|
| C0 install-story | `plateau/hooks/*`, `adapters/claude_code/hook.py` (shim), `plateau/cli.py`, `plateau/bridge/install.py` (nine modes), `pyproject.toml`, `tests/test_install.py` (identity test) |
| C1 ledger-probes | `plateau/lab/ledger.py`, `plateau/lab/probes.py`, `plateau/lab/holdout.py`, `plateau/agency/driver.py` (spawn env only), `plateau/bridge/handoff.py` and `plateau/bridge/inject.py` (agent_id keying only) |
| C2 model-fit-promote-guardrails | `plateau/lab/fit.py`, `plateau/lab/promote.py`, `plateau/lab/propose.py`, `.github/CODEOWNERS`, `.github/workflows/guardrails.yml` |
| C3 ring-doctor | `plateau/ring.py`, `plateau/doctor.py`, `plateau/bridge/config.default.toml` |
| C4 docs | `README.md`, `docs/d038/report.md`, `adapters/claude_code/README.md`, `.claude-plugin/marketplace.json`, `adapters/claude_code/.claude-plugin/plugin.json` (description), `CHANGELOG.md`, `docs/harness-0.3/PLAN.md` §Handoff (S4-A2 note only) |
| C5 tests | `tests/test_lab.py`, `tests/test_promote.py`, `tests/test_ring.py`, `tests/test_doctor.py`, `tests/test_hooks_signal.py` |
