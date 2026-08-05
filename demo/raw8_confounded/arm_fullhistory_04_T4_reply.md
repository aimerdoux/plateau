I don't have shell execution approval in this session, same constraint the prior workers hit. I've verified the test file's logic by hand against the actual `control.py` implementation (which I read in full — `next_task`, `resume_plan`, and the `resume` CLI subcommand are all correctly implemented from T1-T3).

**Summary:** Created `tests/test_resume.py` with 6 tests:
1. `test_next_task_returns_first_unchecked_or_none` — matches the exact gate assertion from T1
2. `test_next_task_none_when_no_rows`
3. `test_resume_plan_reports_next_gate_expect_and_unchecked_count` — matches T2's gate assertion
4. `test_resume_plan_done_case_has_no_next_and_reads_blocked_flag` — covers the `blocked` flag via BLOCKED.md's `class:` line
5. `test_resume_cli_help_lists_subcommand` — subprocess check matching T3's gate
6. `test_resume_cli_prints_resume_plan_dict` — exercises the CLI end-to-end via `C.main(["resume", ...])` with `--json`, using `capsys`

Tests match the existing file's style (tmp_path fixtures, direct `C.` module calls, plain asserts, no docstrings on individual tests). Couldn't execute pytest myself due to lack of shell approval in this session, but each assertion was checked by hand against the real implementation in `control.py`.
