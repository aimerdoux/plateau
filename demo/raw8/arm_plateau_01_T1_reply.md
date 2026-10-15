Added `next_task(text)` to `plateau/agency/control.py` (right before `run_gate`): it iterates `parse_plan(text)` and returns the first `Task` with `checked == False`, or `None` if every row is checked or there are no rows — matching the existing `Optional[Task]` / docstring style used elsewhere in the file.

Note: the gate command is meant to be run by the parent, not me, and my sandbox required approval to execute it directly — but the implementation is a straightforward wrapper over the already-tested `parse_plan`.
