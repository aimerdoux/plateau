# demo6 step=1 — arm1_fullhistory

## Sub-task advanced: L1 — `command_output` Measurement kind

### What changed

**`plateau/signal.py`**
- Imports added: `hashlib`, `shlex`, `subprocess`.
- New module global `_CMD_WHITELIST: list[list[str]]` (EMPTY by default — fail closed until host opts in). Each entry is an argv token list.
- New public fn `set_command_whitelist(commands: list) -> None`: shlex-splits each command string into an argv list and replaces the whitelist. `[]` forbids all command_output. Unparseable/empty entries are ignored, never silently allowed. Matching is on the FULL argv list (`'ls -1'` ≠ `'ls'`).
- New private helper `_command_is_whitelisted(argv) -> bool` (exact `argv in _CMD_WHITELIST`).
- `Measurement.kind` Literal extended with `"command_output"`.
- `Measurement.reverify()` now dispatches `command_output` → new method `_reverify_command_output()`:
  - `value` == `'sha256:' + sha256(raw stdout bytes)`.
  - Fails CLOSED (returns False, never raises) on: empty/unparseable source, non-whitelisted argv (refused WITHOUT executing), missing executable / spawn error / timeout (30s), nonzero exit code, or hash mismatch.
  - Runs with `cwd=_GROUND_ROOT`, `capture_output=True`.

**`plateau/__init__.py`**
- Exported `set_command_whitelist` (added to the `.signal` import block and to `__all__`).

### Verification
- Full suite: `26 passed` (was 26 — no regressions; no new tests added this step, L6 owns tests).
- Manual smoke confirmed: empty-whitelist→fail, whitelisted+matching→pass, wrong value→fail, non-whitelisted argv→fail, nonzero exit→fail, missing exec→fail, empty/unbalanced-quote source→fail.

CARRY: L1 DONE. `plateau.signal.Measurement(kind, source, value)`; kind Literal now includes `"command_output"` (alongside file_hash/test_result/oracle_score/exit_code/operator). For command_output: `source`=command string (shlex-split to argv), `value`=`"sha256:"+sha256(raw_stdout_bytes).hexdigest()`. Whitelist API: `set_command_whitelist(list_of_command_strings)` (exported from `plateau`) + module global `plateau.signal._CMD_WHITELIST` (list[list[str]], argv lists, EMPTY default) + helper `plateau.signal._command_is_whitelisted(argv)`. `reverify()` fails CLOSED on nonzero-exit/non-whitelisted/missing/unparseable/mismatch and NEVER raises. `Measurement` is `@dataclass(frozen=True)`; gate admits a Thought only if `grounding.reverify()` is True. NEXT (L2): add composite kind `"all_of"` to the SAME `Measurement.kind` Literal — `source` is a JSON list of child specs `{kind,source,value}`; `reverify()` True iff EVERY child Measurement reverifies; fail closed on empty list / malformed JSON / unknown child kind. Reuse `Measurement(**child).reverify()` per child. Remember to add `"all_of"` to the kind Literal and keep the file_hash/command_output branches intact. Tests dir uses pytest `tmp_path` + `set_ground_root(str(tmp_path))` pattern; run with `uv run --with pytest --with numpy pytest -q`.
