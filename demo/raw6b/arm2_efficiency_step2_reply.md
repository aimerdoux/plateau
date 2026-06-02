# demo6 step=2 reply — arm2_efficiency (L2: all_of composite)

## What I changed
Advanced exactly ONE sub-task: **L2 — the `all_of` composite Measurement kind** in
`plateau/signal.py`. (L1 `command_output` was already DONE per carried context.)

- `plateau/signal.py`:
  - Added `import json`.
  - Added `_ALL_OF_CHILD_KINDS` frozenset of leaf child kinds an `all_of` may contain
    (`file_hash, command_output, test_result, oracle_score, exit_code, operator`).
    `all_of` is intentionally NOT a child kind — composites stay flat so reverify can't
    recurse unboundedly.
  - Added `_reverify_all_of(source) -> bool`: parses `source` as a JSON list of child
    specs `{kind, source, value}`; returns True iff EVERY child `Measurement.reverify()`
    is True. Fails CLOSED (returns False, never raises) on: non-JSON, non-list, EMPTY
    list, non-object element, non-str kind/source/value, unknown child kind, or any
    single failing child.
  - Extended `Measurement.kind` Literal to include `"all_of"`.
  - Dispatched `all_of` in `Measurement.reverify()` to `_reverify_all_of(self.source)`
    (the composite's `value` is unused; the proof lives in the children in `source`).

## Verification
- Full suite green: **26 passed** (`uv run --with pytest --with numpy pytest -q`).
- Manual sanity: live-child→True; stale-child/empty/malformed/unknown-kind→False.

CARRY: schema=plateau.signal.v1. L1+L2 DONE. signal.py API: `Measurement.kind` Literal now includes `"all_of"`; an all_of's `source` = JSON list of child specs `[{"kind","source","value"}, ...]` and its `value` is ignored. `Measurement(kind="all_of", source=<json>, value="").reverify()` → True iff every child Measurement reverifies, fail-closed on empty/malformed-JSON/non-list/non-str-field/unknown-child-kind. Allowed child kinds = `_ALL_OF_CHILD_KINDS` (file_hash, command_output, test_result, oracle_score, exit_code, operator — NOT all_of itself, so composites are flat/non-recursive). Helper `_reverify_all_of(source)` private in signal.py. NEXT OPEN GOALS: L3 continuum.py emit/inflate/ground carry all_of losslessly (nested children intact) + treat an all_of whose source won't JSON-parse as STALE guard; L4 signal.py `ground_report(state)->dict` (per-fact {claim,kind,live,stale_children}, descend all_of naming failing child sources, aggregate {n_live,n_stale}); L5 `plateau/report.py` + `python -m plateau.report <blob_file>` (inflate→ground_report→print JSON→exit 0 iff all live else 1); L6 `tests/test_verification_chain.py` (>=6 tests, gate admits all_of only while every child live) + README/SKILL docs. Current test count to keep green: 26 (will rise to >=32 after L6).
