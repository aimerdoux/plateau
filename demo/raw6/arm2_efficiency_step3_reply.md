DIFF:
plateau/continuum.py — advanced L3 (carry `all_of` losslessly + explicit guard).
- Added `_all_of_source_parses(source)`: returns False iff `source` won't `json.loads` into a list. Mirrors `Measurement._reverify_all_of`'s parse check, surfaced at the carry layer.
- `ground()` now special-cases `kind=="all_of"`: if its source won't parse, it is appended to `stale` BEFORE reverify dispatch, with a distinct named reason `"all_of source did not parse — composite treated stale (fail closed)"`. Otherwise it re-grounds normally via `Measurement.reverify()` (which for `all_of` is live only while EVERY child re-verifies).
- Docstrings on `ground` document the L3 carry contract; no signature/import changes (`json` already imported).

Lossless carry was already structurally true (emit/inflate carry `grounding_source` verbatim as an opaque JSON string — no double-encode; `inflate`→`ground` rebuilds the Measurement). L3's added value this step is the EXPLICIT, named parse-failure guard living in continuum (the carry layer) instead of being implicit inside reverify, so L4 can surface *why* a composite went stale.

Verified: 26 tests green. Manual round-trip harness confirms: (a) live all_of survives emit→inflate with `source` byte-identical and 0 stale; (b) breaking a child file → all_of goes stale (reason "no longer supports"); (c) unparseable all_of source → stale with reason "did not parse" (fail closed).

CARRY:
- L4 `ground_report(state)->dict` lives in signal.py and walks `state.verified_facts` (each a dict with `grounding_kind/grounding_source/grounding_value`), NOT continuum's Grounding split. Per-fact emit `{claim, kind, live, stale_children}`; aggregate `{n_live, n_stale, facts:[...]}`.
- To populate `stale_children` for an `all_of`: `json.loads(grounding_source)` → for each child spec build `Measurement(**spec)`, and `stale_children` = list of the `source` strings whose child `.reverify()` is False. For the parse guard (source won't load/not a list) treat the WHOLE fact as stale; surface the same fail-closed signal (e.g. `stale_children=["<unparseable all_of source>"]` or a sentinel) so L4's report names it — reuse the `_all_of_source_parses` predicate added in L3.
- `live` per fact = `Measurement(kind,source,value).reverify()`; for non-`all_of` kinds `stale_children` is `[]`. `n_live`/`n_stale` count facts (a fact is stale if `not live`), not children.
- Remaining: L4 `ground_report` (signal.py), L5 `plateau/report.py` + `python -m plateau.report <blob_file>` (inflate blob → ground_report → print JSON → exit 0 iff all live else 1), L6 `tests/test_verification_chain.py` (>=6 tests, one per layer + gate-admits-all_of-only-while-children-live) + README/SKILL one-paragraph docs (docs not gated by the check).
- Test runner: `uv run --extra test --extra demo python -m pytest -q` (the `demo`/numpy extra is REQUIRED or 4 metrics tests error on numpy import — unrelated to signal work).
