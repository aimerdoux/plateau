The gate command itself is meant to be run by the parent, so I won't force it. The implementation is done.

Summary: Added `resume_plan(control_dir, root)` to `plateau/agency/control.py` (right before `run_gate`), built on `next_task` plus the same `blocked` sensor `cmd_status` uses. It reads `PLAN.md`, finds the first unchecked task via `next_task`, and reads `BLOCKED.md` for a `class:` line, returning `{next, gate, expect, blocked, unchecked_count}`.
