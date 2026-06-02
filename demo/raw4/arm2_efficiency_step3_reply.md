DIFF:
- tests/test_measurement_kinds.py (NEW): 4 tests, all green.
  1. test_command_output_reverifies_stable_then_stale_on_change — `cat out.txt` whitelisted; reverify() True while stdout=="hello", flips False after rewriting the file (rehash != recorded).
  2. test_gate_admits_command_output_only_while_live — gate() admits the command_output-grounded Thought while whitelisted; after set_command_whitelist([]) it fails closed and lands in dropped.
  3. test_apply_gate_carries_live_command_output_fact — apply_gate folds the live fact into verified_facts; excluded after de-whitelisting.
  4. test_command_output_fails_closed_on_nonzero_exit — whitelisted `cat does_not_exist.txt` reverifies False (nonzero exit ⇒ fail closed).
  Helper `_stdout_value(text)` = "sha256:"+sha256(text.encode()).hexdigest() (value convention). Uses set_ground_root(str(tmp_path)) + tmp file under root, mirroring tests/test_continuum.py.
- Suite: 30 passed (was 26; +4). >=28 satisfied. No source files touched this step.

CARRY:
- signal.py (step1) + continuum.py guard (step2) + tests/test_measurement_kinds.py (step3) DONE. REMAINS: README.md paragraph + adapters/claude_code/SKILL.md paragraph & pending-facts command_output example.
- command_output contract proven by tests: value="sha256:"+sha256(raw stdout bytes); source must equal a whitelist entry verbatim; fail closed on de-whitelist / nonzero-exit / missing.
- Docs step can reuse the example: source="cat out.txt", value="sha256:<hex>", kind="command_output"; note whitelist is required (set_command_whitelist) or the fact never re-grounds.
- 30 tests green; keep green when adding docs (docs are non-code, no test impact expected).
