DIFF:
- plateau/signal.py:
  - Imports: added `hashlib`, `shlex`, `subprocess`.
  - Added module-level `_CMD_WHITELIST: set[str] = set()` plus `set_command_whitelist(commands: list[str]) -> None` (replaces the set) and `command_whitelist() -> set[str]` (returns a copy).
  - `Measurement.kind` Literal now includes `"command_output"` (inserted right after `"file_hash"`).
  - `reverify()` dispatches `command_output` to new private `_reverify_command_output()`.
  - `_reverify_command_output()`: matches `self.source` (the FULL command string) EXACTLY against `_CMD_WHITELIST`; `shlex.split`s it; runs via `subprocess.run(argv, cwd=_GROUND_ROOT, stdout=PIPE, stderr=DEVNULL)`; on success+exit0 computes `"sha256:" + sha256(raw stdout bytes).hexdigest()` and compares to `self.value`. Fails CLOSED (returns False) on: empty/unparsable/empty-argv command, command not in whitelist, OSError/ValueError (missing executable), or nonzero exit.
- plateau/__init__.py: export `set_command_whitelist`, `command_whitelist` (import block + `__all__`).
- Verified: full suite `uv run --with pytest --with numpy pytest -q` = 26 passed; manual smoke confirms stable=True and all four fail-closed cases (changed value, non-whitelisted, nonzero exit, missing cmd) = False.

CARRY:
- Whitelist API: `set_command_whitelist(list[str])` (replace, not append), `command_whitelist() -> set[str]` (copy), module set `_CMD_WHITELIST`. Match is on the EXACT full command string stored in `Measurement.source` (e.g. `"printf hello"`), NOT argv[0]. Both API + `_CMD_WHITELIST` exist per contract.
- Value convention: `value = "sha256:" + sha256(raw stdout bytes).hexdigest()` — identical prefix convention to `integrity.file_hash`. stderr is discarded; only stdout is hashed.
- Measurement.kind Literal order: `["file_hash","command_output","test_result","oracle_score","exit_code","operator"]`. command runs with `cwd=_GROUND_ROOT` (so `set_ground_root` affects it).
- DONE this step: signal.py reverify branch + whitelist API + Literal + package exports. REMAINS (next steps): continuum.py emit/ground/inflate guard for new kind; NEW tests/test_measurement_kinds.py (>=2: stable re-verify, STALE on change, gate admits only while live); README.md + adapters/claude_code/SKILL.md docs (+ SKILL pending-facts command_output example).
- Test wiring note for next step: gate()/apply_gate() already route through `reverify()`, so a `command_output` Thought is admitted iff whitelisted+stable. To make a fact go STALE, change what the command outputs (e.g. point at a temp file the command cats, then rewrite the file) while keeping the command whitelisted.
