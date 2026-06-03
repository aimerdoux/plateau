# Changelog

All notable changes to Plateau are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.0] — 2026-06-03

The release that adds the **agency layer** on top of the bounded-context core: a
parent → orchestrator → worker delegation hierarchy that keeps a *parent* agent's
context flat across an arbitrarily long mission, proven on a live run.

### Added

- **`plateau.agency` subpackage** — the external bounded-context QA driver, folded into
  the core. The orchestrator is a plain Python process whose only memory is `signal.json`,
  so it does not grow; each step spawns a fresh `claude -p` worker that sees only the
  carried signal plus one subtask. Console entry point: **`plateau-agency`**
  (`plateau.agency.driver:main`). It **reuses the core** rather than duplicating it —
  facts bind via `plateau.signal.Measurement(kind="file_hash").reverify()` and
  `plateau.integrity.file_hash`, not a private hasher.
- **Three prose layer contracts** shipped with the package:
  - **`PARENT_AGENT_MANUAL.md`** — usable verbatim as a parent system prompt; turns a
    one-line operator mission into N background orchestrators and holds the parent's
    footprint at O(A + R), independent of internal step count N.
  - **`ORCHESTRATOR_PROMPT.md`** — the bounded loop: pick one, spawn one worker, gate,
    meter to disk, shed; return to the parent EXACTLY ONCE.
  - **`BACKGROUND_AGENCY.md`** — the worker contract (fresh per unit, one-line return,
    detail to disk, then discarded).
- **Gate re-verify** in `plateau.agency.gate`: a fact is admitted only after a real
  re-ground — `file_hash` sha256 binds to file *content* (the core `Measurement`), and
  command gates capture an `exit_code` / normalized `test_result` in a hashed
  `result.json`. The agent's word is never "done."
- **CHANGELOG.md** (this file).

### Changed

- **Bounded control loop** in `plateau.orchestrator`: `serve_forever` drives the
  never-returning loop and `should_continue` is the single bounded stop-decision, so the
  loop is provably flat (see `context_proven_bounded`) instead of growing per step.
- **Packaging** — the wheel now ships the agency `*.md` contracts (including
  `PARENT_AGENT_MANUAL.md`) and the example override configs under `plateau/agency/configs/`,
  via explicit `[tool.hatch.build.targets.wheel].artifacts` (neither `*.md` nor `*.json`
  is auto-included by hatchling).

### Validated

- **Live `wavex-os` case study** — the agency drove a real bounded QA-hardening run:
  **4 bounded orchestrators** (`connectors`, `fleet-observe`, `fleet-launch`, `onboarding`),
  a **live 19-agent sonnet fleet** of ephemeral workers beneath them, and **3 PRs**
  emitted in `write` mode and never merged by the agency
  ([wavex-os #44](https://github.com/aimerdoux/wavex-os/pull/44),
  [#45](https://github.com/aimerdoux/wavex-os/pull/45),
  [#46](https://github.com/aimerdoux/wavex-os/pull/46)). **The parent never compacted.**
  Full report: `/Users/geniex/wavex-os/.plateau-agency/reports/AGENCY_RUN_REPORT.pdf`.

## [0.1.0] — 2026-06-02

Initial release of the bounded-context core.

### Added

- **Core** (`plateau`, zero third-party dependencies): `signal` (the gate — a fact enters
  the carried signal only when backed by a re-verifying `Measurement`), `continuum`
  (emit / inflate / ground), `metrics` (arm curves, slope, decision rules), and `integrity`
  (`file_hash`).
- **`examples/bare_loop.py`** — the whole bounded loop in plain Python, no agent framework.
- **Claude Code plugin** under `adapters/claude_code/` — `plugin.json`, a `plateau` skill,
  hooks, and the `/plateau:status | gate | run` commands.
- Pre-registered, sealed demos under `demo/` (recall + real-code efficiency) with
  recompute-verifiable verdicts; results in `RESULTS.md`.

[0.2.0]: https://github.com/aimerdoux/plateau/releases/tag/v0.2.0
[0.1.0]: https://github.com/aimerdoux/plateau/releases/tag/v0.1.0
