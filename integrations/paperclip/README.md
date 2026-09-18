# `plateau_local` — run Paperclip agents on the Plateau pattern

Replaces a spawned agent's **single linear `claude --print`** (which accretes
context until it hits `--max-turns` / loses the thread on long-horizon work)
with the **orchestrator + fresh-and-discarded workers** loop from
`plateau/agency/driver.py`:

- The orchestrator's entire memory is a **bounded `signal.json`** (hard caps:
  ≤12 deduped lessons, ≤1.5 KB; observed ~0.5–0.8 KB in runs).
- Each step spawns a **fresh `claude -p` worker** with `compact_signal + one
  subtask + RETURN_CONTRACT` (the repo's own prompting: `agency/prompts.py`),
  gates the one-JSON result deterministically, persists, and discards it.
- Budgets + checkpoint/resume (`--target-seconds`, `WALL_CLOCK_CEIL=3h`) carry
  work across activations via the small `RESUME.json` — **bounded context,
  indefinitely**, instead of a growing Claude session.

This is the validated loop (proved live against wavex-os: orchestrator context
stayed 87→152 tokens over 3 real worker steps while each worker read 0.6–0.9M
cached repo tokens and died).

## Files

- `plateau-local-adapter.ts` — the Paperclip `ServerAdapterModule` (`type`,
  `execute`, `testEnvironment`). Thin process shell; the driver does the work.

## Landing it (ADDITIVE — changes no existing agent until an agent opts in)

1. Copy `plateau-local-adapter.ts` into a new package
   `packages/adapters/plateau-local/src/server/index.ts` (mirror
   `claude-local`'s package.json: name `@paperclipai/adapter-plateau-local`,
   `exports["./server"]`). It already imports only `@paperclipai/adapter-utils`.
2. **Register the type** (the 2-line change):
   - `packages/shared/src/constants.ts` → add `"plateau_local"` to
     `AGENT_ADAPTER_TYPES`.
   - the server adapter registry → map `"plateau_local"` → this module's
     `execute` / `testEnvironment`.
3. Configure an agent: `adapterType: "plateau_local"`, and in `adapterConfig`
   set `plateauDir` (absolute path to this Plateau repo), `mode` (`audit`
   default; `write` opens PRs, never pushes to main), `targetSeconds` (default
   7200), and optionally `workerModel` (cost lever — cheap workers).

## Making it the default for **every** spawned agent (operator gate)

Point the agent-creation default `adapterType` at `plateau_local` (or migrate
existing agents' `adapterType`). This is a production-wide execution change —
flip deliberately, after the live long-horizon proof below.

## Cost lever

Workers are fresh `claude -p` calls. `workerModel` →
`plateau-agency --worker-model <id>` runs them on a cheap model. Use `mode:
"audit"` + a cheap `workerModel` for the longest, lowest-cost runs; `stub: true`
is a $0 machinery test (canned worker, no Claude call).
