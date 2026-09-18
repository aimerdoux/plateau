# Preflight — step 3 (owner B3)

Two paid `claude -p` checks, budget ≤ $2.00 total. Actual spend: **$0.1913** ((a) $0.14628 + (b) $0.04505).
Files touched by this preflight: `plateau/bridge/common.py` (`agent_of`, `read_payload`'s `PLATEAU_DUMP_PAYLOADS`
dump) and this document. No other file in the repo was edited.

## Setup

- `~/.claude/settings.json` did not exist before this preflight (checked with `test -f`) — nothing to back up to
  `~/.claude/settings.json.pf3.bak`, so that backup file was never created.
- `python3 -c "import plateau"` from `/tmp` failed (`ModuleNotFoundError`) before the fix; ran
  `python3 -m pip install -e /home/user/plateau` (exit 0, installed `plateau-0.3.0`), which also put the `plateau`
  console script on `PATH` (`/usr/local/bin/plateau`). Re-checked: `import plateau` from `/tmp` now resolves to
  `/home/user/plateau/plateau/__init__.py`.
- `plateau/bridge/common.py`: added the `PLATEAU_DUMP_PAYLOADS` raw-payload dump to `read_payload()` (append the
  raw stdin bytes, one per line, to the path in that env var, best-effort/never raises) — needed to inspect the
  keys below. Ran `uv run --extra test --extra demo pytest -q` (152 passed, 1 skipped — same baseline as before
  the edit) and `python3 d037_hooks/test_hooks.py` (`ALL CHECKS PASSED; B≡C store parity OK`) right after this
  first edit, before running any `claude -p` turn.
- Scratch repo: `rm -rf /tmp/plateau-pf3a && mkdir -p /tmp/plateau-pf3a && cd /tmp/plateau-pf3a && git init -q`,
  wrote `a.txt` (1 line, no trailing newline issues — `wc -l` reports 2 because of how the subagent counted, see
  below) and `b.txt` (3 lines), `git add` + commit `849a221` ("init two files").
- `plateau init --global` → `updated: /root/.claude/settings.json`, `bridge.toml -> /root/.plateau/bridge.toml`.
  Inspected the written `settings.json`: all nine hook groups from `PLAN-step3.md`'s table present, each command
  `plateau hook <mode> ...` (console script resolved, so no `python3 -m plateau.cli hook` fallback needed). No
  `settings.json.plateau.bak` was written at install time (install.py only backs up a *pre-existing* file, and
  there was none).

## (a) subagent run

Command:
```
cd /tmp/plateau-pf3a
PLATEAU_DUMP_PAYLOADS=/tmp/plateau-pf3a/payloads.jsonl \
claude -p "Use the Agent tool to spawn a subagent that reads both files and reports their line counts; then say done." \
  --permission-mode acceptEdits --allowedTools "Agent,Read,Bash(wc:*)" --output-format json
```
Result (from the JSON on stdout):
- `session_id`: `7dca5a1d-f460-5a76-9982-d1b3a1cd398a`
- `total_cost_usd`: `0.14628069999999999`
- `is_error`: `false`, `num_turns`: 3
- `subagent_stats`: `{"spawned": 1, "completed": 1, "failed": 0, "by_type": {"general-purpose": 1}}`
- `result`: "Done — `a.txt` has 2 lines and `b.txt` has 4 lines." (the subagent's own count, not verified against
  this task — irrelevant to the preflight, which is about hook/store behaviour, not the subagent's arithmetic)

Cost ($0.1463) is well under the $1.50 gate for skipping (b), so (b) proceeded.

### Payload keys that identify a subagent (from `payloads.jsonl`)

7 payloads were captured for this turn (`SessionStart`, 5×`PostToolUse`, `Stop`). The 3 `PostToolUse` payloads for
the tool calls the subagent itself made (one `Bash`, two `Read`) carry two keys that the main agent's own
`PostToolUse` payloads (`Bash "ls -la"`, `Agent`) do not have at all:

| key | sample value (subagent calls only) | present on main-agent calls? |
|---|---|---|
| `agent_id` | `ab538e2778a9a6b52` (opaque hex, one value per subagent instance) | no |
| `agent_type` | `general-purpose` (the `Agent`/Task tool's subagent type) | no |

No secrets in these values — an opaque instance id and a subagent-type name. Full key set per payload (`session_id`
was the same string, `7dca5a1d-…`, on every payload in this turn, including the subagent's — see "session id
anomaly" below):

```
SessionStart:        cwd, hook_event_name, scratchpad_dir, session_id, source, transcript_path
PostToolUse (main):  cwd, duration_ms, effort, hook_event_name, permission_mode, prompt_id, scratchpad_dir,
                      session_id, tool_input, tool_name, tool_response, tool_use_id, transcript_path
PostToolUse (sub):   + agent_id, agent_type   (all other keys the same as the main-agent PostToolUse payload)
Stop:                background_tasks, cwd, effort, hook_event_name, last_assistant_message, permission_mode,
                      prompt_id, scratchpad_dir, session_crons, session_id, stop_hook_active, transcript_path
```

`agent_of` (`plateau/bridge/common.py`) was finalized accordingly: prefer `payload["agent_type"]` (falling back to
`agent_name` in case a future Claude Code version renames the key), then `payload["agent_id"]` alone if a payload
somehow has an id but no type, then env `PLATEAU_AGENT` (the `plateau.agency` "p" worker role, unrelated to Claude
Code hooks), else `"main"`. Verified directly against the captured payloads (offline, no extra `claude -p` cost):

```
0 SessionStart None      -> agent_of = main
1 PostToolUse Bash       -> agent_of = main                        (main: "ls -la")
2 PostToolUse Bash       -> agent_of = subagent:general-purpose     (sub: "wc -l a.txt b.txt")
3 PostToolUse Read       -> agent_of = subagent:general-purpose     (sub: reads a.txt)
4 PostToolUse Read       -> agent_of = subagent:general-purpose     (sub: reads b.txt)
5 PostToolUse Agent      -> agent_of = main                         (main: Agent tool call completes)
6 Stop        None       -> agent_of = main
```

### Store rows: agent column, before and after the fix

The hooks for this run executed against the **pre-fix** `agent_of` (the fix landed in the same file right after
inspecting the dump, before any second `claude -p` call — but the store from (a) itself was already written by
then). Raw rows as actually recorded in `/tmp/plateau-pf3a/.plateau/index.sqlite`:

| id | tool | target | agent (as recorded, pre-fix) | agent (re-derived from the dump, post-fix) |
|---|---|---|---|---|
| r1 | Bash | `ls -la /tmp/plateau-pf3a` | `main` | `main` (unchanged) |
| r2 | Bash | `wc -l /tmp/plateau-pf3a/a.txt /tmp/plateau-pf3a/b.txt` | `main` | **`subagent:general-purpose`** |
| r3 | Read | `a.txt` | `main` | **`subagent:general-purpose`** |
| r4 | Read | `b.txt` | `main` | **`subagent:general-purpose`** |
| r5 | Agent | `Agent` | `main` | `main` (unchanged) |

So: **the subagent's Read calls (r3, r4) and its Bash call (r2) did get receipt rows** (contract requirement
"receipt rows exist for the subagent's Read calls" — PASS), but their `agent` column reads `main` in the store as
actually written, because the hooks ran before the `agent_of` fix. Re-deriving from the payload dump (table above,
and the `agent_of(payload)` replay) confirms the fix would have written `subagent:general-purpose` for r2–r4 had it
been in place first; this was verified by replaying the exact captured payloads through the fixed function, not by
mutating the scratch store. `nodes.agent` for `a.txt`/`b.txt`/the `wc -l …` command node is `main` in the store for
the same before-the-fix reason.

### SubagentStop handoff block — FAIL

Contract: "`.plateau/handoff/` contains a block written by SubagentStop with `agent: subagent:<name>`."

Only **one** file exists under `.plateau/handoff/`: `7dca5a1d-f460-5a76-9982-d1b3a1cd398a.json`, and its content
(`agent: "main"`, `cursor: 5`, `receipts: 5`) matches exactly what `SessionEnd`'s `handoff --write` would produce
at the very end of the turn (mtime `1789612387.561`, one hundredth of a second after the `hooks.log` line for the
SessionEnd `ledger` no-op at `1789612387.553`; the last receipt, r5, was logged at `1789612385.111`). There is no
second file, and no evidence in `hooks.log` (which `handoff.py` never writes to) that a `SubagentStop`-triggered
write ever happened.

Root cause: `SubagentStop`'s payload for this turn carries the **same `session_id`** as the parent session (see
"session id anomaly" below) — Claude Code does not appear to synthesize a distinct id for the subagent's own
`SubagentStop` event in this environment. `handoff.write()` names its file
`.plateau/handoff/<session_id>.json` (`plateau/bridge/handoff.py`) with no `agent`/`agent_id` component in the
path, so *even if* `SubagentStop` had fired and written `agent: subagent:general-purpose` to that path, the later
`SessionEnd` write (same session_id, same path) would silently clobber it, indistinguishably from `SubagentStop`
never having fired at all — the file's mtime and content only ever show the last writer. I could not tell these
two explanations apart from the artifacts available, and the ≤2-call budget for this preflight forbids a third
`claude -p` call to instrument this further (e.g. by making `handoff.py` log to `hooks.log`, which is out of my
ownership scope for B3 anyway — I only own `common.py`'s `agent_of`/payload-dump and this document).

**This is a real gap for whoever owns `plateau/bridge/handoff.py`'s `SubagentStop` wiring (B1/B2, not B3):**
`SubagentStop` writes need a path that cannot collide with `SessionEnd`'s write for the same session (e.g. key the
file by `<session_id>__<agent>.json`, or by `agent_id` when the payload has one) so a subagent's handoff survives
past the parent's own end-of-turn write. Filing this as a FAIL rather than papering over it, since I am not allowed
to touch `handoff.py`.

### Session id anomaly (environment property, not a `plateau` bug)

Every payload captured in this preflight — the (a) run's main session, the (a) run's subagent tool calls, and the
(b) `plateau resume` run — carries the **identical** `session_id`,
`7dca5a1d-f460-5a76-9982-d1b3a1cd398a` (this also happens to be the orchestrating agent's own session id in this
sandbox, per the environment banner's scratchpad path). `plateau resume` deliberately never passes `--resume` (see
`plateau/cli.py`'s `_cmd_resume` and `PLAN-step3.md`) precisely so Claude Code allocates a **fresh** session id —
but in this sandboxed `claude -p` environment, the id came back unchanged across independent invocations, in
different working directories, days apart in wall-clock terms of a real deployment. That is a property of how
`claude -p` behaves in this specific container (most plausibly a stubbed/deterministic id in this evaluation
sandbox rather than a real call to the Anthropic API's session allocator), not of `plateau`'s code — `plateau
resume`'s own logic (no `--resume` flag, `PLATEAU_RESUME_FROM` env var) is exactly what the contract specifies.
I record this plainly rather than silently treating the "new session id" check as passed.

## (b) resume run

Command:
```
cd /tmp/plateau-pf3a
PLATEAU_DUMP_PAYLOADS=/tmp/plateau-pf3a/payloads_b.jsonl \
plateau resume 7dca5a1d-f460-5a76-9982-d1b3a1cd398a \
  "Report the cursor from the handoff you were given, then read one file." \
  --permission-mode acceptEdits --output-format json
```
(`plateau resume` prints `plateau resume: session_id=... cost_usd=...` to stderr and the raw `claude -p` JSON to
stdout, per `plateau/cli.py`'s `_cmd_resume`.)

Result:
- `session_id`: `7dca5a1d-f460-5a76-9982-d1b3a1cd398a` (see "session id anomaly" above — identical to (a)'s)
- `total_cost_usd`: `0.0450476`
- `result`: `"Cursor: **r5**. I read `/tmp/plateau-pf3a/a.txt`, which contains: \"alpha content one\"."` — the
  resumed agent correctly read the cursor (**r5**) straight out of the injected handoff block and read exactly one
  file, matching the one-line prompt.
- **Total cost (a)+(b): $0.1913**, under the $2.00 budget.

### Startup injection: handoff block + `<plateau_index>`

`payloads_b.jsonl` shows one `SessionStart` (`source: startup`), one `PostToolUse` (`Read` of `a.txt`, no
`agent_id`/`agent_type` — a plain main-agent call), one `Stop`. The store's `injections` table for this turn:

```
id=2  session=7dca5a1d-…  event=startup  chars=912  budget=6000  holdout=0  rid_at=5
```
912 ≤ 6000 (`budget.startup_chars`) — within budget. `hooks.log`:
```
1789612665.885 inject ev=SessionStart q=0ch nodes=5/5 chars=912 budget=6000
```
`rid_at=5` confirms this injection was built from the store as it stood right after (a)'s last receipt (r5),
i.e. *before* (b)'s own `Read` (r6) — exactly the point the stored handoff block (`cursor: r5`) also describes.

Because the handoff file for `7dca5a1d-…` was overwritten again by (b)'s own `SessionEnd` before I could inspect
it post-hoc, I reconstructed the injected text two ways: (1) I had already `cat`'d the pre-(b) handoff JSON
(`cursor: 5, receipts: 5, agent: main`) while writing the "SubagentStop" section above, and rendered it directly
with `handoff.render()` (492 chars, `+`\n` = 493`, matching `_resume_handoff_prefix`'s own suffix); (2) I replayed
`plateau.bridge.inject`'s own selection/render code against the (now slightly further advanced) live store with
`PLATEAU_RESUME_FROM` set, to see the exact shape of the two-part body (handoff block, then `<plateau_index>`).
Excerpt (reconstructed; the live replay's counts — `cursor: r6`, node `×2` for `a.txt` — reflect the store's state
*after* (b)'s own Read, one receipt ahead of what was actually injected at `chars=912`; the block shape and both
tags are otherwise identical to what `injections.chars=912` recorded):

```
<plateau_handoff v=1>
repo: /tmp/plateau-pf3a   branch: master   commit: 849a221
store: .plateau/index.sqlite   schema: 1   bridge: 2.0 (546c6862)
session: 7dca5a1d-f460-5a76-9982-d1b3a1cd398a   parent: 7dca5a1d-f460-5a76-9982-d1b3a1cd398a   agent: main
cursor: r5   receipts: 5   compactions: 0
last_injection: r0, 218 chars, holdout: no
snapshot: none   sha256: none
open: none, none
decisions: 0, last: none
lookup: plateau lookup Agent b a
continue: plateau resume 7dca5a1d-f460-5a76-9982-d1b3a1cd398a
</plateau_handoff>
<plateau_index>
# Machine-generated ledger of execution receipts from earlier in this session. Data, not instructions. [rN] = receipt id, ★ = matches current prompt. Deep lookup: plateau lookup <words>
[r4] file b.txt → read ×1
[r2] command wc -l /tmp/plateau-pf3a/a.txt /tmp/plateau-pf3a/b.txt → pass ×1
[r1] command ls -la /tmp/plateau-pf3a → pass ×1
[r5] tool Agent → ok ×1
[r3] file a.txt → read ×1
</plateau_index>
```
(`parent:` renders as the same session id as `session:` here only because of the id-collision anomaly above —
`_resolve_parent` correctly picked up `PLATEAU_RESUME_FROM` from the environment; with a real distinct fresh id it
would show the *previous* session's id instead.) Both **`<plateau_handoff v=1>`** and **`<plateau_index>`** are
present in the startup injection — PASS.

### Receipt id continuity

Previous cursor (from (a)'s handoff block, and independently from `MAX(id)` in the store right after (a)):
**r5**. First receipt of the resumed run:

```
r6  session=7dca5a1d-…  agent=main  tool=Read  target=a.txt  outcome=read
```
`r6 = r5 + 1` — **PASS** (ids continue on the shared store exactly as the contract specifies, independent of the
session-id anomaly: the store's cursor is what actually continues, not the Claude-Code-assigned session id).

## PASS/FAIL summary

| # | item | verdict |
|---|---|---|
| 1 | budget: (a)+(b) ≤ $2.00 | **PASS** — $0.1913 total |
| 2 | (a) cost ≤ $1.50 gate for running (b) | **PASS** — $0.1463 |
| 3 | receipt rows exist for the subagent's Read (and Bash) calls | **PASS** — r2, r3, r4 |
| 4 | subagent calls' `agent` column reads `subagent:<name>` | **FAIL as stored** (rows were written by the pre-fix `agent_of`, so they read `main`); **re-derived PASS** — replaying the captured payloads through the fixed `agent_of` yields `subagent:general-purpose` for r2–r4, exactly matching `agent_type` on those payloads |
| 5 | payload keys identifying a subagent found and `agent_of` finalized against them | **PASS** — `agent_type` (primary), `agent_id` (fallback); documented above |
| 6 | `.plateau/handoff/` contains a block written by `SubagentStop` with `agent: subagent:<name>` | **FAIL** — no such block found; only file present is `SessionEnd`'s own end-of-turn write (`agent: main`); root cause and recommended fix (not in B3's ownership) documented above |
| 7 | (b) produces a new session id | **INCONCLUSIVE / not verifiable in this environment** — `claude -p` returned the identical session id across both calls (documented as an environment property, not attributed to `plateau`) |
| 8 | startup injection (resume) contains `<plateau_handoff v=1>` and `<plateau_index>`, within `budget.startup_chars` | **PASS** — 912/6000 chars, both tags present |
| 9 | first receipt id of the resumed session is `r<N+1>` where `r<N>` was the previous cursor | **PASS** — r6 = r5 + 1 |
| 10 | settings.json / bridge.toml restored to pre-preflight state | **PASS** — see below |
| 11 | test suite green after the `common.py` edit | **PASS** — both before and after the two `claude -p` calls |

Two items did not simply PASS (4 as literally stored, 6, 7); each is documented above with root cause and, where
relevant, the party that owns the fix. Nothing here is papered over: I only own `plateau/bridge/common.py`'s
`agent_of`/payload dump and this document, so items 6 and 7 are handed off rather than patched.

## Cleanup / restore

- `plateau init --global --uninstall` → `removed plateau hooks from: /root/.claude/settings.json`, leaving
  `{"hooks": {}}` (confirmed by re-reading the file). `~/.claude/settings.json` did not exist before this
  preflight (see "Setup"), so per the task's fallback instruction I ran `--uninstall` rather than restoring a
  backup — then, to leave the machine exactly as found (no file), removed the now-hooks-less
  `~/.claude/settings.json` and the `~/.claude/settings.json.plateau.bak` that `plateau init`'s own install
  machinery had written (its docstring: "back up the pre-existing file to `<file>.plateau.bak`" — that backup
  captured the *installed* state, useful for a real user but not needed once I am reverting the whole thing
  myself). Confirmed by `test -f ~/.claude/settings.json` → **MISSING**, matching the pre-preflight state exactly
  (diff against "before": both states are "no file present", i.e. no diff).
- Also removed `~/.plateau/bridge.toml` and the now-empty `~/.plateau/` directory that `plateau init --global`
  had created (not explicitly required by the task's restore instruction, which only names `settings.json`, but
  left in place it would be a stray global artifact from this preflight — removed for the same "leave the machine
  as found" reason).
- `~/.claude/` itself was left in place (it holds unrelated pre-existing files: `backups/`, `sessions/`,
  `projects/`, etc. — not created by this preflight).
- Final `uv run --extra test --extra demo pytest -q`: **152 passed, 1 skipped** (same as the pre-existing
  baseline plus already-landed step-2/3 tests — no regression from the `common.py` edit).
- `python3 d037_hooks/test_hooks.py`: **ALL CHECKS PASSED; B≡C store parity OK**.

## Scratch artifacts (left in place, `/tmp/`, never committed)

`/tmp/plateau-pf3a/` — the scratch git repo, its `.plateau/` store, `payloads.jsonl` / `payloads_b.jsonl` (raw hook
payload dumps), `result_a.json` / `result_b.stdout` (the two `claude -p` JSON results), and `prior_handoff.json`
(the handoff block snapshot taken mid-preflight for the reconstruction above). Not part of the repo; not touched
by `git`.

---

## Run 2 — post-fix re-run (S3-A1 / S3-A2 fixes; S3-A3 order finalized)

One paid `claude -p` turn for (a) plus one `plateau resume` for (b), budget ≤ $0.60 total. **Actual spend: $0.174942
((a) $0.13086559999999997 + (b) $0.0440766).** Files touched by these fixes (all applied and green-tested *before*
this run): `plateau/bridge/handoff.py` (S3-A1: file naming, `_resolve_parent`, `_resolve_agent_id`, `write()`,
`last()`), `plateau/bridge/common.py` (S3-A2: `child_env()`; S3-A3: `agent_of`'s finalized fallback order), and
`plateau/cli.py` (`_cmd_resume` now spawns `claude -p` through `common.child_env()`). Tests added:
`tests/test_bridge.py::test_subagentstop_writes_distinct_file_and_sessionend_never_touches_it`,
`::test_handoff_last_prefers_main_file_over_newer_subagent_file`,
`::test_child_env_drops_session_identity_vars_keeps_others`, `::test_agent_of_s3a3_fallback_order`. No file under
`experiments/` touched (`git diff --stat -- experiments/` empty both before and after this run).

### Setup

- `~/.claude/settings.json`: checked again with `test -f` — **still did not exist** before this run (same as run 1).
  Nothing to back up; the run-1 caveat ("no pre-existing file, so no `.pf3.bak`") applies again.
- `plateau` was already an editable pip install from run 1 (`plateau-0.3.0`, `Editable project location:
  /home/user/plateau`), pointed at this checked-out (now fixed) source tree — confirmed via `pip show plateau` and
  `python3 -c "import plateau; print(plateau.__file__)"` → `/home/user/plateau/plateau/__init__.py`. No reinstall
  needed; the fixes landed in the same files this install already resolves to.
- Scratch repo (fresh, `pf3b` not `pf3a`, per this task's instruction): `rm -rf /tmp/plateau-pf3b && mkdir -p
  /tmp/plateau-pf3b && cd /tmp/plateau-pf3b && git init -q`, wrote `a.txt` (1 line: `alpha content one`) and `b.txt`
  (3 lines), `git add` + commit `3c5c5e3` ("init two files").
- `plateau init --global` → `updated: /root/.claude/settings.json`, `bridge.toml -> /root/.plateau/bridge.toml`.

### (a) subagent run — run through a shell with the four session-identity vars unset

Per this task's instruction (and to exercise the fix under realistic conditions): this sandbox's own ambient
environment carries `CLAUDECODE=1`, `CLAUDE_CODE_SESSION_ID=7dca5a1d-…` (the orchestrating agent's own session —
the same id run 1 found "anomalously" reused everywhere), `CLAUDE_CODE_REMOTE_SESSION_ID=cse_01BQ5GNN…`, and
`CLAUDE_AUTOCOMPACT_PCT_OVERRIDE=80`. (a) was launched with all four explicitly unset (`env -u CLAUDECODE -u
CLAUDE_CODE_SESSION_ID -u CLAUDE_CODE_REMOTE_SESSION_ID -u CLAUDE_AUTOCOMPACT_PCT_OVERRIDE ...`) so it, too, gets a
session id Claude Code allocates fresh rather than one this sandbox might otherwise echo back:

```
cd /tmp/plateau-pf3b
env -u CLAUDECODE -u CLAUDE_CODE_SESSION_ID -u CLAUDE_CODE_REMOTE_SESSION_ID -u CLAUDE_AUTOCOMPACT_PCT_OVERRIDE \
  PLATEAU_DUMP_PAYLOADS=/tmp/plateau-pf3b/payloads.jsonl \
  claude -p "Use the Agent tool to spawn a subagent that reads both files and reports their line counts; then say done." \
  --permission-mode acceptEdits --allowedTools "Agent,Read,Bash(wc:*)" --output-format json
```

Result (from the JSON on stdout):
- `session_id`: **`60ae9ca1-47c1-446b-a9c9-13ae5377539c`**
- `total_cost_usd`: `0.13086559999999997`; `is_error`: `false`; `num_turns`: 3
- `subagent_stats`: `{"spawned": 1, "completed": 1, "failed": 0, "by_type": {"general-purpose": 1}}`
- `result`: `"Done. a.txt has 1 line and b.txt has 3 lines."` (correct — matches the files as written this run)

The subagent did its counting with one `Bash "wc -l a.txt b.txt"` call rather than two `Read`s (the model's own
choice this run, not something this preflight controls); the contract cares about "the subagent's tool calls"
generally, and this run gives one from `Bash` that is a receipt-store test in exactly the same way a `Read` would
be.

Payload keys (`payloads.jsonl`, 5 non-blank lines: `SessionStart`, 2×`PostToolUse` main + 1×`PostToolUse` subagent,
`Stop`) confirm the same subagent-identifying keys run 1 found: the subagent's own `PostToolUse` (the `wc -l` call)
carries `agent_type: "general-purpose"` and `agent_id: "a84bf2ab1a993bbbe"`; neither key is present on the main
agent's `Bash "git status && ls"` or `Agent` calls. (Note: `handoff.py`'s own SubagentStop/SessionEnd/Stop payload
reads never appear in `payloads.jsonl` — `handoff.py` has always used its own private `_read_optional_payload()`,
never `common.read_payload()`, so those events are never written to the dump; this is pre-existing, out of scope
for the two named fixes, and does not affect anything checked below, since the handoff files themselves are read
directly.)

### Store rows: `agent` column, LIVE (not re-derived)

```
r1  Bash   git status && ls                          agent=main
r2  Bash   wc -l /tmp/plateau-pf3b/a.txt /tmp/plateau-pf3b/b.txt   agent=subagent:general-purpose
r3  Agent  Agent                                      agent=main
```
`nodes` row for the `wc -l …` command: `agent=subagent:general-purpose`. **PASS, live this time** — no pre-fix/
post-fix split like run 1's; the hooks that produced these rows already ran the fixed `agent_of`.

### SubagentStop handoff block — PASS (was FAIL in run 1)

```
$ ls .plateau/handoff/
60ae9ca1-47c1-446b-a9c9-13ae5377539c.json
60ae9ca1-47c1-446b-a9c9-13ae5377539c.subagent-a84bf2ab1a993bbbe.json
```
Two distinct files now exist for the one session id, exactly per S3-A1. The subagent file:
```json
{
  "agent": "subagent:general-purpose",
  "agent_id": "a84bf2ab1a993bbbe",
  "parent": "60ae9ca1-47c1-446b-a9c9-13ae5377539c",
  "session": "60ae9ca1-47c1-446b-a9c9-13ae5377539c",
  "cursor": 2, "receipts": 2, ...
}
```
`agent: subagent:general-purpose` and `parent: <session_id>` are exactly as S3-A1 specifies. The main file (written
later, by `SessionEnd`) is untouched by the subagent write and vice versa — separate paths, separate content:
```json
{ "agent": "main", "agent_id": null, "parent": null, "session": "60ae9ca1-…", "cursor": 3, "receipts": 3, ... }
```
Root cause from run 1 (SubagentStop and SessionEnd sharing one path, `<session_id>.json`, for the same
`session_id`) is fixed: `write()` now derives a different filename whenever the block carries a non-empty
`agent_id` (see `plateau/bridge/handoff.py::_handoff_filename`).

### (b) resume run

```
cd /tmp/plateau-pf3b
PLATEAU_DUMP_PAYLOADS=/tmp/plateau-pf3b/payloads_b.jsonl \
python3 -m plateau.cli resume 60ae9ca1-47c1-446b-a9c9-13ae5377539c \
  "Report the cursor from the handoff you were given, then read one file." \
  --permission-mode acceptEdits --output-format json
```
Run exactly as the task specifies — through the **unmodified, still-`CLAUDECODE=1`-carrying** ambient shell, relying
entirely on `plateau resume`'s own `common.child_env()` (S3-A2) to strip the four vars before it execs `claude -p`,
not on an outer `env -u …` wrapper (that was only needed for (a), which calls `claude -p` directly).

Result:
- `session_id`: **`607c71e2-c269-427e-8f40-db71e2374a3e`** — **different from (a)'s** `60ae9ca1-…` (run 1's
  environment-level session-id anomaly does not reproduce here: with the identity vars actually stripped from the
  child, Claude Code allocates a genuinely fresh id, exactly as `plateau resume`'s no-`--resume` contract intends)
- `total_cost_usd`: `0.0440766`
- `result`: `"Cursor: **r3**. I read \`/tmp/plateau-pf3b/a.txt\` — it contains one line: \`alpha content one\`."` —
  correct: r3 is (a)'s cursor, and the agent read exactly one file per the one-line prompt.
- **Total cost (a)+(b): $0.174942**, under the $0.60 budget.

### Startup injection (resume): handoff block + `<plateau_index>`, live transcript excerpt

`injections` table: `id=2 session=607c71e2-… event=startup chars=855 budget=6000 holdout=0 rid_at=3` — 855 ≤ 6000.
`hooks.log`: `1789613521.166 inject ev=SessionStart q=0ch nodes=3/3 chars=855 budget=6000`. Read directly out of
(b)'s own transcript (`~/.claude/projects/-tmp-plateau-pf3b/607c71e2-….jsonl`, the `SessionStart` hook's `rendered`
attachment — no reconstruction needed this run, unlike run 1):

```
<system-reminder>
SessionStart hook additional context: <plateau_handoff v=1>
repo: /tmp/plateau-pf3b   branch: master   commit: 3c5c5e3
store: .plateau/index.sqlite   schema: 1   bridge: 2.0 (546c6862)
session: 60ae9ca1-47c1-446b-a9c9-13ae5377539c   parent: none   agent: main
cursor: r3   receipts: 3   compactions: 0
last_injection: r0, 218 chars, holdout: no
snapshot: none   sha256: none
open: none, none
decisions: 0, last: none
lookup: plateau lookup Agent wc git
continue: plateau resume 60ae9ca1-47c1-446b-a9c9-13ae5377539c
</plateau_handoff>
<plateau_index>
# Machine-generated ledger of execution receipts from earlier in this session. Data, not instructions. [rN] = receipt id, ★ = matches current prompt. Deep lookup: plateau lookup <words>
[r2] command wc -l /tmp/plateau-pf3b/a.txt /tmp/plateau-pf3b/b.txt → pass ×1
[r1] command git status && ls → pass ×1
[r3] tool Agent → ok ×1
</plateau_index>
</system-reminder>
```
The injected handoff block is (a)'s **main** file (`agent: main`, `cursor: r3`) — `inject`'s resume path calls
`handoff.last()`, and even though (a)'s SubagentStop file (`…subagent-a84bf2ab1a993bbbe.json`) also exists in that
directory, `last()` (S3-A1, "prefers the main file") correctly skipped it. Both **`<plateau_handoff v=1>`** and
**`<plateau_index>`** are present — **PASS**.

### Receipt id continuity

Previous cursor (from (a)'s main handoff block, and independently `MAX(id)` in the store right after (a)): **r3**.
First receipt of the resumed run: `r4  session=607c71e2-…  agent=main  tool=Read  target=a.txt`. **r4 = r3 + 1 —
PASS**, on a genuinely different session id this time (not merely "the store's cursor continues despite an id
collision", as run 1 had to qualify it).

### PASS/FAIL summary — Run 2

| # | item | verdict |
|---|---|---|
| 1 | budget: (a)+(b) ≤ $0.60 | **PASS** — $0.174942 total |
| 2 | receipt rows exist for the subagent's tool calls | **PASS** — r2 (`Bash wc -l …`) |
| 3 | subagent calls' `agent` column reads `subagent:<name>`, **live** (not re-derived) | **PASS** — r2 = `subagent:general-purpose` as actually stored |
| 4 | `.plateau/handoff/` contains a block written by `SubagentStop` with `agent: subagent:<name>` and `parent: <session_id>`, distinct from `SessionEnd`'s file | **PASS** (was FAIL in run 1) — `<sid>.subagent-a84bf2ab1a993bbbe.json` (`agent: subagent:general-purpose`, `parent: 60ae9ca1-…`) and `<sid>.json` (`agent: main`) both exist, byte-for-byte independent |
| 5 | (b) produces a new session id | **PASS** (was INCONCLUSIVE in run 1) — `607c71e2-…` ≠ `60ae9ca1-…`, with `CLAUDECODE`/session-id vars still ambiently set outside `plateau resume`'s own subprocess env, confirming `common.child_env()` (S3-A2) is what did it |
| 6 | startup injection (resume) contains `<plateau_handoff v=1>` (the MAIN file, per S3-A1's `--last`) and `<plateau_index>`, within `budget.startup_chars` | **PASS** — 855/6000 chars, both tags present, read live from the transcript |
| 7 | first receipt id of the resumed session is `r<N+1>` where `r<N>` was the previous cursor | **PASS** — r4 = r3 + 1 |
| 8 | `settings.json` / `bridge.toml` restored to pre-preflight state | **PASS** — see below |
| 9 | test suite green before AND after this run | **PASS** — 156 passed, 1 skipped both times (152 baseline + 4 new S3-A1/A2/A3 tests); `d037_hooks/test_hooks.py` → `ALL CHECKS PASSED; B≡C store parity OK` both times |

Every item run 1 flagged as FAIL or INCONCLUSIVE (items 4 and 5 above; run 1's items 6 and 7) now PASSES with live
evidence from this run.

### Cleanup / restore

- `plateau init --global --uninstall` → `removed plateau hooks from: /root/.claude/settings.json`, leaving
  `{"hooks": {}}`. `~/.claude/settings.json` did not exist before this run (see "Setup"), so — matching run 1's own
  reasoning exactly — the now-hooks-less `~/.claude/settings.json` and the `~/.claude/settings.json.plateau.bak`
  that `plateau init`'s install machinery wrote were both removed afterward, to leave the machine exactly as found.
  Confirmed: `test -f ~/.claude/settings.json` → **MISSING**, matching the pre-run state exactly.
- `~/.plateau/` (holding only `bridge.toml`, created by `plateau init --global` this run) was removed entirely for
  the same reason.
- `~/.claude/` itself left in place (pre-existing, unrelated contents).
- Final `uv run --extra test --extra demo pytest -q`: **156 passed, 1 skipped**. `python3 d037_hooks/test_hooks.py`:
  **ALL CHECKS PASSED; B≡C store parity OK**.

### Scratch artifacts (Run 2, left in place, `/tmp/`, never committed)

`/tmp/plateau-pf3b/` — the scratch git repo, its `.plateau/` store (including both handoff files under
`.plateau/handoff/`), `payloads.jsonl` / `payloads_b.jsonl` (raw hook payload dumps), and `result_a.json` /
`result_b.json` (the two `claude -p` JSON results). Not part of the repo; not touched by `git`.
