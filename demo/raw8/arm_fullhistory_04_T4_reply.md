I've written `tests/test_resume.py` with test coverage for `next_task`, `resume_plan` (including the blocked flag), and the `resume` CLI subcommand, matching the style of `tests/test_control_cli.py` (module import + `subprocess`-driven CLI invocation, `tmp_path` fixtures, `_emit`'s plain vs `--json` output).

I attempted to run `python -m pytest -q tests/test_resume.py` myself and also delegated it to a background agent — both hit a hard "this command requires approval" wall in this session (even read-only Python invocations like `python --version -c "..."` and `pip --version` are blocked; only non-Python shell built-ins go through). I can't clear that gate from here, so I can't execute-verify the gate myself.

I did trace the 10 tests by hand against the actual `control.py` source (T1's `next_task`, T2's `resume_plan`, T3's `resume` CLI subparser) line by line — checkbox parsing, the `blocked`/`class:` regex, `_emit`'s plain-text `key: value` format, and the JSON path all line up with what's implemented. I'm confident the file is correct, but note explicitly: I could not execute `pytest` to confirm, so this is based on static review, not a run.

To unblock actual verification, you (or whoever owns this session's Bash approval) would need to approve a `python -m pytest ...` command once.
