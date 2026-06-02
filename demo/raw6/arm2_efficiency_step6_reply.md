DIFF:
<terse>
- NEW tests/test_verification_chain.py: 8 tests (>=6 required).
  - L1 test_l1_command_output_reverifies_then_goes_stale: whitelisted `echo`, value='sha256:'+sha256(stdout incl. newline); reverify True, then stale on changed value, then fail-closed when un-whitelisted.
  - L2 test_l2_all_of_live_iff_every_child_live: two file_hash children → True all-live; rewrite one child → False.
  - L3 test_l3_continuum_carries_all_of_losslessly: emit→inflate round-trip; json.loads(grounding_source)==[c1,c2], kind preserved, not stale.
  - L4 test_l4_ground_report_names_stale_child: n_live/n_stale counts; stale_children names the failing child source ("b.txt").
  - L5 test_l5_report_cli_exit0_live_then_exit1_after_child_stale (in-process report.main) + test_l5_report_module_subprocess_exit_codes (subprocess `python -m plateau.report`, parses JSON stdout).
  - KEYSTONE test_keystone_gate_admits_all_of_only_while_every_child_live + test_keystone_empty_all_of_fails_closed (empty list / non-JSON fail closed).
- README.md: +"The verification chain" paragraph; Layout test count 26→34.
- adapters/claude_code/SKILL.md: pending_facts format now shows command_output + all_of examples (fail-closed note).
- Edited IN PLACE under demo6_arms/arm2_efficiency only. No source/L1-L5 files touched.

CARRY:
- Full suite 34 passed, 0 failures (was 26; +8). Confirmed under both `uv run --extra test --extra demo python -m pytest -q` and `uv run --with pytest --with numpy pytest -q`.
- Feature complete: L1-L6 all done. Nothing left.
