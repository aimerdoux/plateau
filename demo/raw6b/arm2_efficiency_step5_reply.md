# demo6 step=5 reply (arm2_efficiency)

## What changed
- **L5 DONE.** Added `plateau/report.py` implementing the `python -m plateau.report <blob_file>` CLI.
  - Reads the blob file, inflates it with `inflate(blob, fresh=False)` (keeps ALL carried facts so the report can name the stale ones; liveness is still recomputed by `ground_report` against the live environment, not trusted from the blob).
  - Runs `ground_report(inflated.state)`, prints the report as `json.dumps(..., indent=2)` to stdout.
  - Exit code: `0` iff `n_stale == 0` (every fact live), else `1`. Fails CLOSED: missing/unreadable file or malformed blob prints an error report to stdout and returns `1`; wrong arg count returns `2` with a usage line on stderr.
  - Public functions: `run(blob_file: str) -> int` and `main(argv: list[str] | None = None) -> int`.
- No other files modified. Existing suite stays green: **29 passed**.
- Smoke-verified end-to-end: live blob → exit 0; stale blob (wrong hash) → exit 1; missing file → exit 1.

## Remaining
- L6: `tests/test_verification_chain.py` (new, >=6 tests) covering each layer L1–L5 + the gate admitting an all_of only while every child is live; plus one-paragraph docs in README.md and adapters/claude_code/SKILL.md (docs not required by the success check).

CARRY: schema=plateau.signal.v1. L1+L2+L3+L4+L5 DONE. New module `plateau/report.py` exposes `run(blob_file: str) -> int` and `main(argv=None) -> int`; CLI entry `python -m plateau.report <blob_file>` inflates a blob (via `continuum.inflate(blob, fresh=False)` to preserve stale facts), runs `signal.ground_report(state)`, prints JSON (indent=2) to stdout, exits 0 iff `n_stale==0` else 1; fails closed (missing/unreadable/malformed → error JSON on stdout + exit 1; bad argc → usage on stderr + exit 2). `report.py` NOT exported from `plateau/__init__.py` (run as a module). Only L6 left: write `tests/test_verification_chain.py` (>=6 tests, one per layer L1 command_output / L2 all_of / L3 continuum all_of carry / L4 ground_report / L5 report CLI exit-code via subprocess or `report.run` / gate-admits-all_of-only-while-children-live) + one-paragraph docs in README.md and adapters/claude_code/SKILL.md. Keep the (now 29) tests green; build blobs for L5 tests with `continuum.emit(SelfState(signal=RelationalState(verified_facts=[...])))`. Arm repo: /Users/geniex/bmacp-trunk/demo6b_arms/arm2_efficiency
