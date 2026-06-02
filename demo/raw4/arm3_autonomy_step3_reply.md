DIFF:
- tests/test_measurement_kinds.py (NEW): 4 tests for the command_output kind. autouse fixture resets BOTH module globals (set_command_whitelist([]) + set_ground_root(".")) after each test to stop whitelist/ground-root leakage into test_signal_gate/test_continuum.
  - test_command_output_reverifies_then_stale: `cat f.txt` over write_bytes(b"alpha\n"); recorded value = "sha256:"+sha256(b"alpha\n"); reverify()→True; mutate to b"beta\n"→False.
  - test_command_output_gate_admits_only_while_live: whitelist+ground_root set BEFORE apply_gate; fact "out=alpha" admitted; emit→mutate file→inflate(fresh=True); stale_claims()==["out=alpha"] and dropped from verified_facts.
  - test_command_output_fails_closed_when_not_whitelisted: true stdout but empty whitelist → reverify()→False.
  - test_command_output_fails_closed_on_nonzero_exit: `cat missing.txt` whitelisted but exits nonzero → reverify()→False.
- No source changes this step (sub-tasks 1+2 already complete & verified: command_output reverify branch in signal.py, KNOWN_KINDS guard in continuum.ground()).
- Suite: 30 passed (was 26; +4). Requirement >=28 met. All prior tests green.

CARRY:
- Tests live & green at /Users/geniex/bmacp-trunk/demo4_arms/arm3_autonomy/tests/test_measurement_kinds.py (30 total).
- Code is feature-complete; ONLY remaining sub-task is docs (README.md + adapters/claude_code/SKILL.md).
- Value convention locked: `"sha256:"+sha256(raw stdout bytes)`, identical prefix to integrity.file_hash. Whitelist match = EXACT full command string == Measurement.source. Fail-closed set: nonzero exit / non-whitelisted / missing-or-unparseable command. Whitelist defaults EMPTY.
- Public API (already exported from plateau root): Measurement, set_command_whitelist, command_whitelist, set_ground_root. KNOWN_KINDS is in plateau.signal and includes "command_output".
- Test-author gotcha for any future test: reset BOTH _CMD_WHITELIST and _GROUND_ROOT in teardown — they are process-global and leak.

FORWARD_PLAN:
- SUB-TASK 4 (NEXT, FINAL) — docs. Depends only on sub-task 1 (done). No code/test dependency.
  PRE-EXPLORE (concrete):
  - README.md (/Users/geniex/bmacp-trunk/demo4_arms/arm3_autonomy/README.md, 5583 bytes): locate the existing file_hash paragraph (it is the canonical Measurement-kind prose). Add ONE adjacent paragraph for command_output stating: (a) value convention "sha256:"+sha256(raw stdout bytes) — same prefix as file_hash; (b) the whitelist requirement — host must call set_command_whitelist([...]) with the EXACT command string or the fact fails closed (default whitelist is empty); (c) the fail-closed triggers: nonzero exit, non-whitelisted command, missing/unparseable command. Match the surrounding heading depth and tone; do NOT restructure existing sections.
  - adapters/claude_code/SKILL.md (/Users/geniex/bmacp-trunk/demo4_arms/arm3_autonomy/adapters/claude_code/SKILL.md): (i) one paragraph documenting the kind mirroring the README wording; (ii) extend the pending-facts example block with a command_output entry. CRITICAL — read the existing pending-facts schema FIRST to copy the EXACT field names (the gate emits grounding_kind/grounding_source/grounding_value, but the SKILL doc example likely uses the emit() blob shape `grounding: {kind, source, value}` — confirm which the doc uses and match it byte-for-byte so the example parses). Example fact to add: claim "out=alpha", grounding kind="command_output", source="cat f.txt", value="sha256:<hexdigest>".
  - RISK to avoid: inventing field names in the SKILL pending-facts example. The two serializations differ (flat grounding_* in GateResult/RelationalState.verified_facts vs nested grounding:{kind,source,value} in the emit() JSON blob). Read the file's current example block and reuse its exact shape; a mismatched example would mis-teach the host adapter. Also: docs-only step — do not touch signal.py/continuum.py/tests; the 30 tests must stay green (no test changes expected, run pytest once as a no-op sanity check).
