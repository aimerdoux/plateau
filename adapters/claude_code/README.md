# Plateau — Claude Code plugin (adapter)

This directory is the Claude Code plugin for Plateau. It is published to the marketplace as a
`git-subdir` whose `path` is `adapters/claude_code`, so **only the files in this directory ship in
the installed plugin** — the rest of the repo (including `plateau/agency/`) is not present at
runtime. Keep that in mind when wiring paths.

## What the plugin does (hooks)

`hook.py` holds no hook logic of its own — it is a thin shim over the `plateau` package for
all nine modes (`plateau/harness-0.3/PLAN-step4.md` "S4-A1 One install story"), whether
`plateau` is pip-installed alongside this plugin or run straight out of a dev checkout:
`parent`/`pre`/`post` dispatch to `plateau.hooks.signal`, `receipt`/`snapshot`/`inject`/
`handoff`/`lift` to their `plateau.bridge.*` twins, and `ledger` to `plateau.lab.ledger`.
`plateau hook <mode>` is the console-script twin of the same dispatch table, so a plugin
install and a `pip install`-only checkout see byte-for-byte identical hook JSON. `hook.py`
never raises: an unavailable target module degrades to a no-op with one line in
`.plateau/hooks.log` instead of failing the hook.

| Hook event | Mode | Effect |
|---|---|---|
| `SessionStart` (`startup\|clear`) | `hook.py parent --cc` | Injects the **parent-agent discipline** as standing context, so the delegation laws are active for as long as the plugin is enabled. |
| `SessionStart` (`startup\|clear`) | `hook.py inject --cc` | Injects a budget-bounded (`startup_chars`) slice of the session's receipt graph as `additionalContext`. |
| `SessionStart` (`compact`) | `hook.py inject --cc` | Same, query-aware from the last user prompt, budgeted by `compaction_chars`. |
| `UserPromptSubmit` | `hook.py pre --cc` | Inflates + re-grounds the carried signal and injects it as `additionalContext` for the next step. |
| `PostToolUse` | `hook.py receipt --cc` | Records one receipt (+ its nodes/edges) for the tool call into `.plateau/index.sqlite`. |
| `PreCompact` | `hook.py snapshot --cc` | Snapshots the store to `.plateau/snapshots/`, marks a compaction, and tells the summarizer to preserve `<plateau_index>` facts verbatim. |
| `Stop` | `hook.py post --cc` | Gates newly proposed facts against the repo and persists the bounded signal to `.plateau/signal.json`. |
| `Stop` | `hook.py lift --cc` | Lifts `DECISION:`/`FACT:` lines from the last assistant message into the receipt graph. |
| `Stop` | `hook.py handoff --cc --print` | Emits the session's `<plateau_handoff v=1>` block as the turn's `systemMessage`. |
| `SessionEnd` | `hook.py ledger --cc` | Rebuilds the receipt graph from the full transcript (batch reconciliation). |
| `SessionEnd` | `hook.py handoff --cc --write` | Writes the handoff block to `.plateau/handoff/<session_id>.json`. |
| `SubagentStop` | `hook.py handoff --cc --write --agent subagent` | Same, tagged `agent: subagent:<name>` for parent pickup. |

Dry-run the legacy modes without `--cc` to see the raw decision dict; the step-3 modes
above are Claude-Code-hook-shaped by design (payload on stdin) and are best exercised
with `--cc` and a JSON payload on stdin, or via `plateau doctor`:

```bash
python3 adapters/claude_code/hook.py parent   # the parent system-prompt block + which manual it read
python3 adapters/claude_code/hook.py pre
python3 adapters/claude_code/hook.py post
echo '{}' | python3 adapters/claude_code/hook.py receipt --cc
```

## Parent-discipline autoload (SessionStart)

**Goal:** when this plugin is enabled, the `PARENT_AGENT_MANUAL` discipline is *automatically*
active — the Claude Code instance receives the parent-agent laws and starts delegating without the
user prompting it — and the discipline disappears when the plugin is disabled.

**Mechanism:** a `SessionStart` hook (matcher `startup|clear|compact`) runs
`hook.py parent --cc`. That mode reads the **Parent Agent Manual**, extracts its
**section-4 `PARENT SYSTEM-PROMPT BLOCK`** (the fenced block of parent laws, verbatim), and emits it
as the session's `additionalContext`:

```json
{
  "hookSpecificOutput": {
    "hookEventName": "SessionStart",
    "additionalContext": "[Plateau — parent-agent discipline, active while the Plateau plugin is enabled]\n…\n1. Do NOT do the task yourself. Delegate everything. …"
  }
}
```

Because Claude Code adds `additionalContext` before the first user prompt, the discipline is loaded
*passively* on every new/cleared/compacted session while the plugin is enabled — and is simply not
emitted once the plugin is disabled. The `resume` matcher is intentionally excluded: a resumed
session already carries the block from its prior context, so re-injecting it would be redundant.

If the manual cannot be found, the hook emits `{"suppressOutput": true}` (no half-formed prompt)
rather than injecting a partial block.

### Why a packaged copy of the manual lives here

The canonical manual is `plateau/agency/PARENT_AGENT_MANUAL.md` at the repo root — but that file is
**outside** the packaged `adapters/claude_code` subdir, so it is absent in an installed plugin. To
make the hook work identically in a dev checkout and an installed plugin, a byte-identical copy is
shipped as `adapters/claude_code/PARENT_AGENT_MANUAL.md`. `hook.py` resolves the manual from the
first candidate that exists, in order:

1. `${CLAUDE_PLUGIN_ROOT}/PARENT_AGENT_MANUAL.md` (the shipped copy — used by an installed plugin),
2. `PARENT_AGENT_MANUAL.md` next to `hook.py`,
3. `../../plateau/agency/PARENT_AGENT_MANUAL.md` (the canonical source — used in a dev checkout).

### Keeping the copy from drifting

The shipped copy must stay byte-identical to the canonical source. After editing the manual,
regenerate it:

```bash
cp plateau/agency/PARENT_AGENT_MANUAL.md adapters/claude_code/PARENT_AGENT_MANUAL.md
```

A quick drift check:

```bash
diff -q plateau/agency/PARENT_AGENT_MANUAL.md adapters/claude_code/PARENT_AGENT_MANUAL.md \
  && echo "in sync"
```

Because the hook injects section 4 *verbatim* from whichever file it reads, the two never diverge in
what the agent actually sees as long as the copy is kept in sync.
