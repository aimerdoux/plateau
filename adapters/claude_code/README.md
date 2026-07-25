# Plateau — Claude Code plugin (adapter)

This directory is the Claude Code plugin for Plateau. It is published to the marketplace as a
`git-subdir` whose `path` is `adapters/claude_code`, so **only the files in this directory ship in
the installed plugin** — the rest of the repo (including `plateau/agency/`) is not present at
runtime. Keep that in mind when wiring paths.

## What the plugin does (hooks)

All three hooks call the thin adapter `hook.py`; the real logic lives in the `plateau` package.

| Hook event | Mode | Effect |
|---|---|---|
| `SessionStart` (`startup\|clear\|compact`) | `hook.py parent --cc` | Injects the **parent-agent discipline** as standing context, so the delegation laws are active for as long as the plugin is enabled. |
| `UserPromptSubmit` | `hook.py pre --cc` | Inflates + re-grounds the carried signal and injects it as `additionalContext` for the next step. |
| `Stop` | `hook.py post --cc` | Gates newly proposed facts against the repo and persists the bounded signal to `.plateau/signal.json`. |

Dry-run any mode without `--cc` to see the raw decision dict:

```bash
python3 adapters/claude_code/hook.py parent   # the parent system-prompt block + which manual it read
python3 adapters/claude_code/hook.py pre
python3 adapters/claude_code/hook.py post
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

## Control loop (`/plateau:orchestrate`) — DONE made mechanical

`control/` ships the long-horizon control loop: `RECON → PLAN → EXECUTE → VERIFY → {DONE |
BLOCKED}`, state on disk under `.plateau/control/`, and **DONE as a predicate** (done ⇔ every
gate passes when re-run now). The parent agent does not do the work — it *monitors, controls,
assigns, and verifies*, delegating each task to a fresh bounded sub-agent that sees only the
carried signal + one task.

| file | role |
|---|---|
| `control/CONTROL_LOOP.md` | the protocol (generated copy of `plateau/agency/CONTROL_LOOP.md`) |
| `control/gatekeeper.sh` | Stop hook, **armed only when `.plateau/control/PLAN.md` exists** — blocks stopping while unchecked gates remain; releases on DONE or a `BLOCKED.md` with `class:`. `RUN_GATES=1` re-runs every gate (V3 regression). |
| `control/sentinel.sh` | external supervisor — respawns `claude -p` on any illegal exit, resuming from the files (`control/reinstate.md`) |
| `control/reinstate.md` | the warm-reinstatement prompt (inflate signal, resume at first unchecked gate) |

A PLAN row is a Measurement: `plateau.agency.control` runs the parent-authored gate, records a
result artifact, and folds passing tasks into the signal as `T<n> done` verified_facts — so the
checked boxes *are* the carried facts. **Injection-safe:** only parent-authored gates are ever
executed; a sub-agent's "done" is admitted solely by hash-binding its recorded, unchanged,
successful artifact (`exit_code` Measurement), never by running its words.

Keep the shipped protocol copy in sync after editing the canonical one:

```bash
cp plateau/agency/CONTROL_LOOP.md adapters/claude_code/control/CONTROL_LOOP.md
```
