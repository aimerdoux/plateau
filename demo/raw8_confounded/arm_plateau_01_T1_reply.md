The gate is run by the parent per the task instructions, so I won't force the command through. The implementation is straightforward and mirrors `plan_all_checked`'s parsing logic, so I'm confident it's correct.

Added `next_task(text)` to `plateau/agency/control.py`, right after `plan_all_checked`. It parses the PLAN text with the existing `parse_plan` and returns the first `Task` where `checked` is `False`, or `None` if there are no rows or all are checked.
