DIFF:
- tests/test_measurement_kinds.py (NEW, 7 tests, all green):
  - `_record(cmd, stdout)` helper builds a `command_output` Measurement with value = "sha256:"+sha256(raw stdout bytes); `_whitelisted_cat(tmp_path, text)` writes a temp file, sets ground root, whitelists `cat <file>`, returns (cmd, path) — mutating the file is the STALE lever.
  - test_command_output_reverifies_while_stable: reverify()==True twice (repeatable, not one-shot).
  - test_command_output_goes_stale_when_output_changes: True, then rewrite file → False.
  - test_gate_admits_command_output_only_while_live: gate admits (grounding_kind=="command_output"), then output drifts → same Thought dropped with "did not re-verify".
  - test_non_whitelisted_command_fails_closed: drop whitelist → reverify False + gate empty.
  - test_nonzero_exit_fails_closed: `false` (exit≠0) → False.
  - test_missing_command_fails_closed: whitelisted but missing executable → False.
  - test_whitelist_api_round_trips: set/get round-trip + returns a copy (mutation doesn't leak).
- Full suite: `uv run --with pytest --with numpy pytest -q` = 33 passed (26 prior kept green + 7 new).

CARRY:
- Tests file DONE. Uses public API only: `from plateau import set_command_whitelist, command_whitelist`; whitelist matches the EXACT full source string (e.g. `f"cat {p}"`), so whitelist the same string stored in Measurement.source.
- REMAINS: continuum.py emit/ground/inflate guard for command_output (kind already passes through via vf.get("grounding_kind", "file_hash") in ground() and emit()/inflate() default; add an explicit guard/verify); README.md + adapters/claude_code/SKILL.md one-paragraph docs (+ SKILL pending-facts command_output example).
- continuum note: ground() rebuilds Measurement from vf["grounding_kind"]/["grounding_source"]/["grounding_value"] and emit() serializes grounding_kind → already lossless for the new kind; the step-2 task wants a verifying continuum test/guard, not a behavior change.
- Value/whitelist conventions unchanged from step 1: value="sha256:"+sha256(stdout bytes); fail CLOSED on non-whitelist / nonzero exit / missing cmd / unparsable; cwd=_GROUND_ROOT.
