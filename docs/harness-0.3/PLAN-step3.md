# Step 3 — adapter wiring, handoff at Stop, init/resume, two preflights (≤ $2)

Contract addendum to PLAN.md (which still governs conventions and ownership rules). Implementers edit only the files
named here. Sealed records untouched.

## Ownership

| owner | files |
|---|---|
| B1 adapter | `adapters/claude_code/hooks/hooks.json`, `adapters/claude_code/hook.py` (modes receipt, snapshot, inject, handoff, ledger, lift added; parent/pre/post unchanged), `adapters/claude_code/.claude-plugin/plugin.json` (version 0.3.0, description), `adapters/claude_code/README.md` (hook table only) |
| B2 cli-init-resume | `plateau/cli.py` (`init [--global]`, `resume`, `hook <mode>`), `plateau/bridge/install.py` (settings merge), `plateau/bridge/lift.py` (decided-fact lifter), `plateau/bridge/handoff.py` (Stop/SessionEnd/SubagentStop integration only), `plateau/agency/driver.py` (return path only, see below), `plateau/agency/prompts.py` (worker footer line only) |
| B3 preflight | `experiments/`-free: writes `docs/harness-0.3/preflight-step3.md` and `plateau/bridge/common.py` `agent_of` only, after inspecting real payloads |
| B4 tests | `tests/test_cc_adapter.py` (extend), `tests/test_install.py`, `tests/test_lift.py` |

## hooks.json (plugin) — exact events

```json
{"hooks": {
 "SessionStart": [
  {"matcher": "startup|clear", "hooks": [
    {"type": "command", "command": "python3 ${CLAUDE_PLUGIN_ROOT}/hook.py parent --cc", "timeout": 15},
    {"type": "command", "command": "python3 ${CLAUDE_PLUGIN_ROOT}/hook.py inject --cc", "timeout": 15}]},
  {"matcher": "compact", "hooks": [
    {"type": "command", "command": "python3 ${CLAUDE_PLUGIN_ROOT}/hook.py inject --cc", "timeout": 30}]}],
 "UserPromptSubmit": [{"hooks": [{"type": "command", "command": "python3 ${CLAUDE_PLUGIN_ROOT}/hook.py pre --cc", "timeout": 15}]}],
 "PostToolUse": [{"matcher": "", "hooks": [{"type": "command", "command": "python3 ${CLAUDE_PLUGIN_ROOT}/hook.py receipt --cc", "timeout": 10}]}],
 "PreCompact": [{"hooks": [{"type": "command", "command": "python3 ${CLAUDE_PLUGIN_ROOT}/hook.py snapshot --cc", "timeout": 30}]}],
 "Stop": [{"hooks": [
    {"type": "command", "command": "python3 ${CLAUDE_PLUGIN_ROOT}/hook.py post --cc", "timeout": 15},
    {"type": "command", "command": "python3 ${CLAUDE_PLUGIN_ROOT}/hook.py lift --cc", "timeout": 10},
    {"type": "command", "command": "python3 ${CLAUDE_PLUGIN_ROOT}/hook.py handoff --cc --print", "timeout": 10}]}],
 "SessionEnd": [{"hooks": [
    {"type": "command", "command": "python3 ${CLAUDE_PLUGIN_ROOT}/hook.py ledger --cc", "timeout": 20},
    {"type": "command", "command": "python3 ${CLAUDE_PLUGIN_ROOT}/hook.py handoff --cc --write", "timeout": 10}]}],
 "SubagentStop": [{"hooks": [{"type": "command", "command": "python3 ${CLAUDE_PLUGIN_ROOT}/hook.py handoff --cc --write --agent subagent", "timeout": 10}]}]
}}
```
`hook.py <mode> --cc`: `receipt|snapshot|inject|handoff|lift` call `plateau.bridge.<module>.main(argv)` after inserting
the repo/package path (`hook.py` must work both as a plugin file with `plateau` pip-installed and from a checkout:
try `import plateau`, else insert `../..` of the file into `sys.path`). `ledger` calls `plateau.lab.ledger.main` and
must degrade to a no-op with a log line when `plateau.lab.ledger` is absent (it arrives in step 4). `inject` on
startup passes `--query` = the first user prompt if the payload carries one (it does not in 2.1.x; leave empty).

Stop output: `post` keeps its systemMessage; `handoff --print` emits `{"systemMessage": "<plateau_handoff …>"}` so the
block is the last thing shown in the turn; `--write` also writes `.plateau/handoff/<session_id>.json`.

## `plateau init` and `plateau hook`

- `plateau hook <mode>` = the console-script twin of `hook.py <mode> --cc` (reads stdin, same outputs). `init` writes
  commands as `plateau hook <mode>` when `shutil.which("plateau")` resolves, else `python3 -m plateau.cli hook <mode>`.
- `plateau init` writes the same hook table into `<root>/.claude/settings.json`; `plateau init --global` into
  `~/.claude/settings.json` and copies `bridge.toml` to `~/.plateau/bridge.toml` (no overwrite unless `--force`).
  Merge rule (`plateau/bridge/install.py`): parse existing JSON; for each event append our hook entries unless an entry
  with the same `command` already exists (idempotent); never remove or reorder foreign entries; write with indent 2;
  back up the previous file to `<file>.plateau.bak` once. `plateau init --uninstall` removes only entries whose
  command contains `plateau hook` or `plateau.cli hook`.
- `.plateau/config.toml` `[bridge] enabled = false` opts a project out (config.load role "off" ⇒ every hook exits 0
  silently).

## Decided-fact lifter (`plateau/bridge/lift.py`)

At Stop: read `transcript_path`, take the last assistant message's text blocks, lift lines matching
`^(DECISION|FACT):\s*(.+)$` (case-sensitive), call `common.record_decision(conn, session_id, agent, text,
provenance=f"{basename(transcript_path)}:{line_no}")`, dedupe by exact text within the session. Prints nothing.

## Agency worker return path (B2; control loop unchanged)

`plateau/agency/prompts.py`: append to the worker footer: "End by running `plateau handoff --print` and pasting its
block verbatim as your last lines." `driver.py`: where the one-line return is parsed, first look for a
`<plateau_handoff v=1>` block in the worker output (or `.plateau/handoff/<session_id>.json` when the output has none)
and expose `cursor` and `open` to the parent; keep the old one-line path as fallback. No other driver change.

## `plateau resume <session_id> [prompt]`

Fresh `claude -p` in the repo root (never `--resume`): env `PLATEAU_RESUME_FROM=<session_id>` makes `inject` on
`startup` prepend the stored handoff block for that session to the injection, under `budget.startup_chars`; the new
session's receipts continue the shared store (ids continue). Flags pass through: `--model`, `--permission-mode`.
Default prompt: "Continue the work described by the handoff block; consult `plateau lookup` before re-reading."

## Preflights (B3; ≤ $2 total; report both from transcripts into docs/harness-0.3/preflight-step3.md)

(a) Scratch repo (`/tmp/plateau-pf3a`, `git init`, two small files), `plateau init --global` (back up and restore the
user's `~/.claude/settings.json` afterwards), set `PLATEAU_DUMP_PAYLOADS=/tmp/plateau-pf3a/payloads.jsonl` (the hooks
append every raw payload there when set — add this to `common.read_payload`), then one `claude -p` turn:
"Use the Agent tool to spawn a subagent that reads both files and reports their line counts; then say done." with
`--permission-mode acceptEdits --allowedTools "Agent,Read,Bash(wc:*)" --output-format json`. Verify from the store
and the payload dump: receipt rows exist for the subagent's Read calls, their `agent` column is `subagent:<name>`
(finalize `agent_of` from the real payload fields — record which keys identify a subagent), and
`.plateau/handoff/` contains a block written by SubagentStop with `agent: subagent:<name>`.
(b) `plateau resume <that session>` with a one-line prompt "Report the cursor from the handoff you were given, then
read one file." Verify: a new session id, the startup injection contains the handoff block and `<plateau_index>`,
and the first receipt id of the new session is r<N+1> where r<N> was the previous cursor. Cost of (a)+(b) ≤ $2 from
the JSON results.

## Tests (B4)

`tests/test_install.py`: merge idempotent, foreign entries preserved, uninstall removes only ours, backup written
once. `tests/test_lift.py`: DECISION/FACT lines lifted with provenance, dedup, non-marker lines ignored.
`tests/test_cc_adapter.py`: every hooks.json command resolves to an existing hook.py mode; `hook.py inject --cc` on a
compact payload returns additionalContext under budget in a temp root; `hook.py handoff --cc --print` returns a
systemMessage containing `<plateau_handoff v=1>`.
