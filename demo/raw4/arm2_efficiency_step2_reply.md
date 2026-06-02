DIFF:
- plateau/continuum.py: added `_KNOWN_KINDS` (frozenset derived from the `Measurement.kind` Literal via `typing.get_type_hints` + `get_args` — resolves the PEP 563 string annotation, so any new kind in signal.py is auto-recognized here). Added the lossless-kind GUARD inside `ground()`: a carried fact whose `grounding_kind` is not in `_KNOWN_KINDS` is NOT coerced to the `file_hash` default — it fails closed as stale with reason "unknown grounding kind '<k>' — not carried losslessly". `command_output` is in `_KNOWN_KINDS`, so it round-trips emit→inflate→ground intact. Imported `typing`.
- plateau/__init__.py: exported `set_command_whitelist` and `command_whitelist` (both in the import block and `__all__`) so tests/SKILL can import the whitelist API cleanly.
- Sanity: `_KNOWN_KINDS == {file_hash, test_result, oracle_score, exit_code, operator, command_output}`; full suite still 26 passed.

CARRY:
- signal.py (step1) + continuum.py guard (step2) DONE. REMAINS: tests/test_measurement_kinds.py (>=2), README.md, adapters/claude_code/SKILL.md.
- Test harness pattern (mirror tests/test_continuum.py): use `set_ground_root(str(tmp_path))`; write a tiny script file under tmp_path and whitelist a stable command e.g. `set_command_whitelist(["cat out.txt"])`; record value = "sha256:"+sha256(raw stdout bytes); reverify() True while stable, flip STALE by editing the file's bytes (stdout changes) OR by `set_command_whitelist([])` (de-whitelist ⇒ fail closed ⇒ gate/apply_gate drops it). Both prove "admit only while live".
- Whitelist API now importable from top-level `plateau`: `set_command_whitelist`, `command_whitelist`. `source` must equal a whitelist entry VERBATIM. Empty whitelist ⇒ all command_output fail closed.
- Guard means a command_output fact only stays live if (a) command whitelisted AND (b) clean exit AND (c) stdout re-hashes to recorded value AND (d) kind known. Tests can rely on de-whitelisting as a clean liveness toggle.
- 26 existing tests must stay green (currently green). New test file makes it 28+.
