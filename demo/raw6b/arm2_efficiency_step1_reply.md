# demo6 step=1 reply (arm2_efficiency)

## What changed
Advanced **L1 only** — the `command_output` Measurement kind in `plateau/signal.py`. No other layer touched.

- `plateau/signal.py`:
  - Added imports `hashlib`, `shlex`, `subprocess`.
  - Added module-level whitelist `_CMD_WHITELIST: set[str] = set()` (empty default ⇒ fail closed), plus `set_command_whitelist(list[str])` and a read-only `command_whitelist()` helper.
  - Added `command_output` to the `Measurement.kind` `Literal`.
  - Added `_reverify_command_output(source, value)` helper and wired it into `Measurement.reverify()`.
  - Behavior (all fail CLOSED, never raise): empty source, source not in `_CMD_WHITELIST`, unparseable/missing executable, or nonzero exit ⇒ `False`. On whitelisted command with exit 0, value is `'sha256:' + sha256(raw stdout bytes)`; matches recorded value ⇒ `True`. Commands run with `cwd=_GROUND_ROOT`, stderr discarded, stdout captured as bytes.

## Verification
- Manual smoke confirmed: empty-whitelist→False, whitelisted+correct-hash→True, wrong-hash→False, nonzero-exit (`false`)→False, non-whitelisted→False, missing-executable→False (no crash).
- Full suite still green: **26 passed** (unchanged).

CARRY: schema=plateau.signal.v1. L1 DONE. signal.py API now: `Measurement.kind` Literal includes `"command_output"`; value format = `'sha256:'+sha256(raw stdout bytes)`; whitelist via `set_command_whitelist(list[str])` / `command_whitelist()` / module global `_CMD_WHITELIST: set[str]` (empty default = fail closed); helper `_reverify_command_output(source, value)->bool` runs `shlex.split(source)` with `cwd=_GROUND_ROOT`, stdout=PIPE, stderr=DEVNULL, fails closed on empty/non-whitelisted/OSError/ValueError/nonzero-exit. Existing kinds {file_hash(live), test_result, oracle_score, exit_code, operator(all fail closed)}. NEXT = L2: add `all_of` composite kind to signal.py — `source` is a JSON list of child specs `{kind,source,value}`; `reverify()` True iff EVERY child reverifies; fail closed on empty/malformed/unknown-child-kind. To build children from specs, reuse `Measurement(kind=spec["kind"], source=spec["source"], value=spec["value"]).reverify()`. Remaining open: L3 continuum carry all_of lossless (continuum.py reconstructs Measurement at signal.py:66 via `vf.get("grounding_kind",...)`), L4 ground_report(state)->dict, L5 plateau/report.py CLI, L6 tests/test_verification_chain.py (>=6) + README/SKILL docs. Keep base 26 tests green.
