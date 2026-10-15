The gate is meant to be run by the parent, not me. I've implemented and can't execute shell commands right now, but the change is straightforward and directly satisfies the requested behavior.

Added `next_task(text)` to `plateau/agency/control.py`, right after `plan_all_checked`. It reuses `parse_plan` and returns the first `Task` where `checked` is `False`, or `None` if there are no unchecked tasks (including the empty-plan case), matching the module's existing docstring/typing style (`Optional[Task]`, already imported).
