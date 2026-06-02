# demo6 step=2 — arm1_fullhistory

## Sub-task advanced: L2 — `all_of` composite Measurement kind

### What changed

**`plateau/signal.py`**
- Imported `json`.
- Extended `Measurement.kind` Literal to include `"all_of"` (now: file_hash / test_result / oracle_score / exit_code / operator / command_output / all_of).
- `Measurement.reverify()` now dispatches `all_of` → new method `_reverify_all_of()`.
- New method `_reverify_all_of()`:
  - `source` is a JSON list of child specs `{kind, source, value}`.
  - Parses with `json.loads`; builds each child via `Measurement(kind, source, value)` and returns True **iff EVERY child `.reverify()` is True**.
  - Fails CLOSED (returns False, never raises) on: empty `source`, malformed JSON (`ValueError`/`TypeError`), non-list payload, empty list, a child that is not a dict, a child missing/ non-string `source`/`value`, or an unknown child `kind` (validated against the explicit valid-kinds set).
  - Recurses correctly: an `all_of` may be a child of another `all_of` (nested composites verified).

### Verification
- Full suite: `26 passed` (no regressions; L6 still owns the new tests).
- Manual smoke confirmed all branches: happy (all children live)→True; one child wrong→False; empty list→False; malformed JSON→False; non-list payload→False; unknown child kind→False; child not a dict→False; missing keys→False; empty source→False; nested all_of→True.

CARRY: L2 DONE. `Measurement.kind` Literal now includes `"all_of"`. For `all_of`: `source` = JSON-encoded `list[dict]` of child specs each `{"kind":..,"source":..,"value":..}`; `value` is unused (pass `""`). `reverify()` builds `Measurement(**child)` per child and returns True iff ALL reverify; fails CLOSED on empty/malformed-JSON/non-list/empty-list/child-not-dict/missing-or-nonstring-keys/unknown-child-kind, and NEVER raises. Implemented in private method `Measurement._reverify_all_of()`. Valid child kinds set is the explicit list `{file_hash, test_result, oracle_score, exit_code, operator, command_output, all_of}` (all_of nesting supported). `Measurement` remains `@dataclass(frozen=True)`. NEXT (L3, `plateau/continuum.py`): make emit/inflate/ground carry `all_of` LOSSLESSLY — the JSON child list in `source` must survive round-trip with nested children intact (do not re-serialize/lose nesting). An `all_of` whose `source` won't `json.loads` (or isn't a non-empty list) must be treated STALE by the continuum guard (mirror how reverify fails closed). Inspect `plateau/continuum.py` for the existing emit/inflate/ground + stale-guard pattern (likely keys off `grounding_kind`/`grounding_source`/`grounding_value` from gate's admitted dicts in `signal.py`). Tests dir uses pytest `tmp_path` + `set_ground_root(str(tmp_path))`; run with `uv run --with pytest --with numpy pytest -q`.
