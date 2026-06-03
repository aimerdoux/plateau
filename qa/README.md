# plateau-qa — external bounded-context QA driver (Plateau Option-1)

An **external** loop that holds a small re-grounded signal on disk and spawns each step as a
**fresh `claude -p` process**. The orchestrator is this Python process — its only memory is
`signal.json`, so it does not grow. That removes the in-session compaction ceiling that the
in-session `/plateau:run` (Option 2) hits. Stdlib-only (Python ≥3.9), repo-agnostic.

```
plateau_qa/
  config.py     repo-agnostic config: auto-detect gate cmds + layout, JSON override, source fallback
  state.py      bounded signal (caps) + tiered coverage backlog + sha256 Measurement
  gate.py       deterministic gates: hash verify, Phase-6.5 diff denylist, config gate cmds
  prompts.py    safety floor (system prompt) + per-step subtask + tool allowlists
  bootstrap.py  scan repo -> tiered coverage.json (routes/edge-fns/RLS, or generic modules)
  driver.py     the loop, CLI, exits, KPIs, checkpoint/resume   (entry: plateau-qa / -m plateau_qa.driver)
  configs/      example override configs (wavex.json = parity for wavex-experience-architect)
```

## Install / run

```bash
cd /Users/geniex/plateau-qa
pip install -e .                       # then: plateau-qa --repo <path> ...
# or, no install:
python3 -m plateau_qa.driver --repo <path> ...
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
plateau-qa --repo /Users/geniex/wavex-experience-architect \
           --config plateau_qa/configs/wavex.json --mode audit --max-steps 80
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
