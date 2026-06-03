# plateau.agency — external bounded-context QA driver (Plateau Option-1)

An **external** loop that holds a small re-grounded signal on disk and spawns each step as a
**fresh `claude -p` process**. The orchestrator is this Python process — its only memory is
`signal.json`, so it does not grow. That removes the in-session compaction ceiling that the
in-session `/plateau:run` (Option 2) hits. Folded into the core as the `plateau.agency`
subpackage; it reuses `plateau.integrity.file_hash` / `plateau.signal` for hashing + the gate.

## The three layers (prose contracts, handed down by path)

The driver is the executable orchestrator, but the *delegation discipline* it enforces is written
out as three prose contracts — one per layer of the depth-of-agency hierarchy. They ship with the
package and are meant to be read top-down and handed down by path:

| Layer | Doc | What it is |
|---|---|---|
| **PARENT** | [`PARENT_AGENT_MANUAL.md`](PARENT_AGENT_MANUAL.md) | Usable verbatim as a parent system prompt. Turns a one-line operator mission into N independent background orchestrators, then keeps the parent's context flat (O(1) per agent, independent of internal steps). |
| **ORCHESTRATOR** | [`ORCHESTRATOR_PROMPT.md`](ORCHESTRATOR_PROMPT.md) | The bounded loop spawned by the parent. Picks one item, spawns one worker, gates the result, meters to disk, sheds — and returns to the parent EXACTLY ONCE. |
| **WORKER** | [`BACKGROUND_AGENCY.md`](BACKGROUND_AGENCY.md) | The worker contract (Parts A/B/C): fresh `claude -p` per unit, sees only `signal + one subtask`, does all heavy I/O in-process, returns ONE line, writes detail to disk, then dies. |

The law they all serve: **context lives at the bottom and dies there; only the small capped SIGNAL
climbs.** `PARENT_AGENT_MANUAL.md` is the layer *above* the other two — it does not re-teach the
orchestrator/worker contracts, it hands them down.

## Case study — the live wavex-os run

These contracts are not theory: the agency drove a real bounded QA-hardening run against
[`wavex-os`](https://github.com/aimerdoux/wavex-os) and the parent never compacted.

- **4 bounded orchestrators**, one per workstream — `connectors`, `fleet-observe`, `fleet-launch`,
  `onboarding` — spawned once and run to completion.
- **A live 19-agent sonnet fleet** of ephemeral workers underneath them, each fresh-and-discarded.
- **3 PRs** emitted in `write` mode, never merged by the agency:
  [`wavex-os#44`](https://github.com/aimerdoux/wavex-os/pull/44) (force devDeps so paperclip boots
  under `NODE_ENV=production`), [`#45`](https://github.com/aimerdoux/wavex-os/pull/45) (gate
  unauthenticated `/api/connectors/*` routes + harden env write),
  [`#46`](https://github.com/aimerdoux/wavex-os/pull/46) (gate 4 unauthenticated control-plane +
  inference-allocation endpoints).
- **The parent stayed flat the whole run** — it spawned once per workstream, read disk meters /
  findings on demand, and verified from one-line returns; the heavy reading and editing lived and
  died in the workers.

Full write-up (4 orchestrators, the fleet, the PRs, the bounded-parent footprint):
`/Users/geniex/wavex-os/.plateau-agency/reports/AGENCY_RUN_REPORT.pdf`.

```
plateau/agency/
  config.py     repo-agnostic config: auto-detect gate cmds + layout, JSON override, source fallback
  state.py      bounded signal (caps) + tiered coverage backlog + core file_hash Measurement
  gate.py       deterministic gates: hash verify (core Measurement), Phase-6.5 diff denylist, config gate cmds
  prompts.py    safety floor (system prompt) + per-step subtask + tool allowlists
  bootstrap.py  scan repo -> tiered coverage.json (routes/edge-fns/RLS, or generic modules)
  driver.py     the loop, CLI, exits, KPIs, checkpoint/resume   (entry: plateau-agency / -m plateau.agency.driver)
  configs/      example override configs (wavex.json = parity for wavex-experience-architect)
```

## Install / run

```bash
cd /Users/geniex/bmacp-trunk/plateau
pip install -e .                       # then: plateau-agency --repo <path> ...
# or, no install:
python3 -m plateau.agency.driver --repo <path> ...
```

## Repo-agnostic by config

Point it at any repo. `config.load_config(repo)` auto-detects gate commands from `package.json`
scripts (jest/vitest/playwright/build/lint) or falls back to `pytest` for Python repos, finds the
router file + `supabase/` dirs if present, and otherwise scans source files into a generic tiered
backlog. Override anything with `--config path/to.json` (keys win over auto-detection); a security
denylist stays in code and is only *extended* by config. Web repos tier by routes / edge functions /
RLS policies; non-web repos tier source modules by the same SEC/CORE keyword rules.

```bash
# wavex parity (reproduces SEC=86):
plateau-agency --repo /Users/geniex/wavex-experience-architect \
           --config plateau/agency/configs/wavex.json --mode audit --max-steps 80
```

## Modes

- **`--mode audit`** (default; **zero remote risk**): each backlog item is audited by a fresh agent
  with Read/Grep only; clean-with-evidence covers it, a repro-anchored problem becomes a `FINDINGS.md`
  entry. Nothing touches git.
- **`--mode write`**: the agent may edit files; the driver does path-scoped staging, the Phase-6.5
  denylist scan, runs the real gate command itself, and admits a sha256 fact. PR emission
  (branch/commit/`gh pr create`) is the outward-facing step — see `pr.py` / `--dry-run-pr`. **Never
  merges**, never force-pushes, never pushes to `main`.

## Safety model (code-enforced, not prose)

- Subagents have **no git/gh/supabase tools** (`prompts.DISALLOWED_TOOLS`) — they can only read
  (audit) or edit files (write). They physically cannot push, merge, or read `.env`.
- The driver does all git/gh in code, only after the deterministic gate passes.
- **Phase 6.5** rejects any `USING(true)`, `DROP/ALTER POLICY`, `service_role`, `gh pr merge`,
  `git push --force` in the staged diff — even when tests are green.
- Path-scoped `git add --` only (never `-A`); secret-suffix paths abort; config/gate-file touches
  are demoted to `needs-review`.

## Flags

```
--repo PATH           target repo (required)
--config PATH         JSON config override (else auto-detect)
--mode audit|write    default audit
--run-id ID           default timestamp
--max-steps N         STEP_BUDGET checkpoint (default 80)
--target-seconds N    primary time target (default 7200)
--pr-cap N            max open PRs (write mode; default 8)
--resume PATH         resume from runs/<id>/RESUME.json (binds same dir, cumulative counters)
--stub                canned agent result (no claude call) — machinery test only
```

## Resume / KPIs

Checkpoints unconditionally at `--max-steps` and prints the exact resume line (binds the same run
dir, restores cumulative counters; ceiling `resume_count<=2`, wall-clock ≤3h). Watch progress with
`tail -f runs/<id>/kpis.jsonl`; findings in `runs/<id>/FINDINGS.md`; audit trail `ledger.jsonl`.
