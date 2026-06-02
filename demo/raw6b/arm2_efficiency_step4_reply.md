# demo6 step=4 reply (arm2_efficiency)

## What I changed
Advanced exactly one sub-task: **L4 — `ground_report`** in `plateau/signal.py`.

- Added `ground_report(state: RelationalState) -> dict` to `plateau/signal.py`. It walks
  `state.verified_facts`, re-verifies each fact NOW, and returns
  `{"facts": [...], "n_live": int, "n_stale": int}`. Each fact entry is
  `{"claim", "kind", "live", "stale_children"}`. Leaf facts use `Measurement.reverify()`
  directly (`stale_children` always `[]`). `all_of` facts descend into their children and
  `live` is True iff there are no failing children.
- Added private helper `_all_of_failing_children(source: str) -> list[str]` (also in
  `plateau/signal.py`) that returns the `source` strings of child specs that fail to
  re-verify. Fails CLOSED structurally: malformed composite source (non-JSON / non-list /
  empty / bad child fields / unknown child kind) yields a non-empty list with a synthetic
  `<malformed ...>` marker (or the bad child's source), so such a composite reports
  `live=False`. Empty returned list ⇒ every child live.
- Neither function raises; all malformed/missing groundings fail closed.

No other files touched. L1+L2+L3 were already DONE per carried context.

## Verification
- `uv run --with pytest --with numpy pytest -q` → **29 passed** (unchanged; no regressions).
- Manual smoke (mixed live leaf / stale leaf / all_of with one missing-file child)
  confirmed: `n_live=1`, `n_stale=2`, and the all_of fact's `stale_children` named the
  exact failing child source.

CARRY: schema=plateau.signal.v1. L1+L2+L3+L4 DONE. New API in `plateau/signal.py`: `ground_report(state: RelationalState) -> dict` returns `{"facts":[{"claim":str,"kind":str,"live":bool,"stale_children":[str,...]}],"n_live":int,"n_stale":int}`; leaf facts have `stale_children==[]` and `live=Measurement.reverify()`; `all_of` facts: `live` is True iff no failing children, `stale_children` lists failing child `source` strings (or synthetic `<malformed ...>` markers on structural faults — fails closed). Helper `_all_of_failing_children(source)->list[str]` (private). `verified_facts` dict keys are `claim`/`grounding_kind`/`grounding_source`/`grounding_value` (grounding_kind defaults `"file_hash"`). Reuses `_ALL_OF_CHILD_KINDS`. Tests still 29 green. NEXT: L5 `plateau/report.py` (new) + `python -m plateau.report <blob_file>` — inflate blob (use `continuum.inflate`), run `ground_report` on the inflated `.state`, print JSON, exit 0 iff all live (`n_stale==0`) else 1. THEN L6 tests/test_verification_chain.py (>=6 tests) + README.md/SKILL.md docs paragraph.
