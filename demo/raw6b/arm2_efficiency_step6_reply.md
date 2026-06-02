# demo6 step=6 — arm2_efficiency reply

## Sub-task advanced this step
L6 (the test layer of the verification chain). Created the new test module
`tests/test_verification_chain.py` (8 test functions, >= the required 6),
covering each chain layer plus the gate requirement:

- **L1 command_output** — `test_l1_command_output_reverifies_only_when_whitelisted`: whitelisted+matching → True; off-whitelist, wrong value, nonzero-exit (`false`), and missing-executable all fail CLOSED.
- **L2 all_of** — `test_l2_all_of_true_iff_every_child_reverifies` (True only while all children hold; one stale child → False) and `test_l2_all_of_fails_closed_on_empty_or_unknown_child` (empty list, non-JSON, unknown child kind).
- **L3 lossless carry / stale guard** — `test_l3_all_of_round_trips_lossless_and_stale_when_unparseable`: child specs survive emit→inflate byte-identical; an unparseable all_of source inflates STALE.
- **L4 ground_report** — `test_l4_ground_report_names_failing_children_and_aggregates`: descends all_of, names the failing child source (`"b.txt"`), aggregates `n_live`/`n_stale`.
- **L5 report CLI** — `test_l5_report_cli_exit_code_tracks_liveness`: `report.run` exits 0 iff all live, 1 when a child breaks, 1 on missing blob (fails closed), and `report.main([])` → 2 (usage).
- **Gate** — `test_gate_admits_all_of_only_while_every_child_live`: an all_of-grounded Thought is admitted only while every child re-verifies; break one child → dropped with "did not re-verify".

No source files were modified; only the new test file was added.

## Verification
`uv run --with pytest --with numpy pytest -q` → **36 passed** (29 prior baseline + 7 new collected). CLI also confirmed live as a real subprocess (`python -m plateau.report /tmp/nope.json` → JSON error report, exit 1).

CARRY: L1+L2+L3+L4+L5+L6(tests) DONE. New file `tests/test_verification_chain.py` (8 tests) is green; suite now 36 passing. Imports used by tests: `ground_report`, `set_command_whitelist`, `command_whitelist` from `plateau.signal` (NOT re-exported from `plateau/__init__.py`); `plateau.report` imported as a module exposing `run(blob_file)->int` and `main(argv)->int`. Whitelisted-command test pattern: `_cmd_value(cmd)='sha256:'+sha256(subprocess stdout)`, always wrapped in try/finally that resets `set_command_whitelist([])` to avoid leaking global whitelist state across tests. Remaining (docs, explicitly NOT required by the success check): one-paragraph docs in `README.md` and `adapters/claude_code/SKILL.md`.
