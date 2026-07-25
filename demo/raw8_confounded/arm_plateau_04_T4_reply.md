I can't execute pytest in this sandboxed worker context (all `python -c`/`-m` invocations require approval that isn't available here), so I traced the test logic by hand against `plateau/agency/control.py`'s actual implementation to confirm correctness instead.

Summary: Created `tests/test_resume.py` with 8 tests covering:
- `next_task`: returns first unchecked row in plan order; returns `None` when all checked or plan empty.
- `resume_plan`: correct `next`/`gate`/`expect`/`unchecked_count` when tasks remain; all-`None`/zero when fully checked; `blocked=True` when `BLOCKED.md` has a `class:` line (while still reporting the cursor); graceful handling of missing PLAN.md/BLOCKED.md.
- `resume` CLI subcommand: `--json` output and plain `key: value` output, including reflecting blocked state, run via subprocess against the real `python -m plateau.agency.control` entrypoint (mirroring `tests/test_control_cli.py`'s style/helpers).
