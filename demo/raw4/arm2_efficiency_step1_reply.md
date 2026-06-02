DIFF:
plateau/signal.py:
- Added imports: hashlib, shlex, subprocess.
- Added module-level `_CMD_WHITELIST: set[str] = set()` (empty default ⇒ fail closed).
- Added `set_command_whitelist(commands: list[str]) -> None` (replaces the set) and read-only `command_whitelist() -> set[str]`.
- Added `"command_output"` to `Measurement.kind` Literal.
- `Measurement.reverify()`: added `command_output` branch dispatching to new `_reverify_command_output()`.
- `_reverify_command_output()`: fails closed unless `source` is exactly in `_CMD_WHITELIST`; shlex.split → subprocess.run (cwd=_GROUND_ROOT, stdout=PIPE, stderr=DEVNULL); fails closed on empty/non-whitelisted command, OSError/ValueError (missing/launch failure), nonzero exit; else compares `"sha256:" + sha256(proc.stdout).hexdigest()` to recorded `value`.
- 26 existing tests still green; smoke-verified stable=True, changed-value/missing-cmd/nonzero-exit/non-whitelisted all False.

CARRY:
- Whitelist API: `set_command_whitelist(list[str])` replaces set; module set is `_CMD_WHITELIST`; read-only helper `command_whitelist()` returns a copy. Empty whitelist ⇒ every command_output fails closed.
- Value convention: `value = "sha256:" + sha256(raw stdout BYTES).hexdigest()` (matches integrity.file_hash 'sha256:' prefix). `source` is the EXACT command string (must equal a whitelist entry verbatim); split via shlex; run with cwd=_GROUND_ROOT.
- `"command_output"` is now in the Measurement.kind Literal. continuum.py already passes kind through dicts — step 2 just needs verify + a guard, no Literal change there.
- For tests (step 3): toggle liveness by editing the whitelist (admit only while live) AND/OR by changing the command's stdout to flip STALE; gate()/apply_gate() already key off reverify() with no kind-specific logic.
- DONE this step: sub-task 1 (signal.py command_output reverify branch + whitelist API + Literal). REMAINS: continuum.py guard, tests/test_measurement_kinds.py (>=2), README.md + adapters/claude_code/SKILL.md docs.
