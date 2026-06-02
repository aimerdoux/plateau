# demo6 step=4 — arm1_fullhistory

## Sub-task advanced: L4 — `ground_report(state) -> dict`

### What changed

**`plateau/signal.py`**
- New private helper `_all_of_failing_children(source: str) -> Optional[list[str]]`:
  parses an `all_of` `grounding_source`; returns the list of child `source`s whose
  `Measurement(**child).reverify()` is False. Returns `None` when the composite is
  itself malformed (won't parse into a non-empty list of well-formed child specs —
  same fail-closed split as `_reverify_all_of`). A well-formed all_of with every child
  live returns `[]`.
- New public fn `ground_report(state: RelationalState) -> dict`:
  - Walks `state.verified_facts` (each `{claim, grounding_kind, grounding_source,
    grounding_value}`).
  - Per fact emits `{claim, kind, live, stale_children}`.
  - For `all_of`: descends children via the helper; `live = (failing == [])`; names
    the failing child `source`s in `stale_children`. A malformed/empty all_of reports
    `live=False` with `stale_children=[]` (no nameable children), consistent with
    `ground()`'s parse-guard.
  - Non-composite facts: `live = Measurement(...).reverify()`, `stale_children` always `[]`.
  - Returns `{"facts": [...], "n_live": int, "n_stale": int}` where `n_stale = len(facts) - n_live`.

**`plateau/__init__.py`**
- Exported `ground_report` (added to the `.signal` import block and to `__all__`).

### Verification
- Full suite: `26 passed` (no regressions; L6 still owns the new tests).
- Manual smoke confirmed: live file_hash fact → live, empty stale_children; all-children-live all_of → live; one-child-stale all_of → live False with only the failing child source named; malformed-JSON all_of → live False, stale_children []; empty-list all_of → live False, stale_children []; missing-file non-composite → live False; nested all_of whose inner child fails → live False with the nested all_of's JSON source named as the one failing child. Aggregate `{n_live:2, n_stale:4}` matched expectation.

CARRY: L4 DONE. `plateau.signal.ground_report(state: RelationalState) -> dict` (exported from `plateau`). Return shape: `{"facts": list[dict], "n_live": int, "n_stale": int}` where each fact dict is `{"claim": str, "kind": str, "live": bool, "stale_children": list[str]}` and `n_stale == len(facts) - n_live`. `stale_children` is `[]` for non-composite facts AND for malformed/empty all_of (fail-closed, no nameable children); for a well-formed all_of it lists the child `source` strings that failed to reverify (a nested-all_of child is named by its full JSON `source` string). Live logic: non-composite → `Measurement(grounding_kind, grounding_source, grounding_value).reverify()`; all_of → live iff every child reverifies, malformed all_of → live False. Helper `plateau.signal._all_of_failing_children(source) -> Optional[list[str]]` returns failing child sources, or `None` if the composite source is malformed (reused valid-kinds set `{file_hash,test_result,oracle_score,exit_code,operator,command_output,all_of}`). `ground_report` mirrors but is independent of `continuum.ground()`; it does NOT mutate state. NEXT (L5, NEW FILE `plateau/report.py` + `python -m plateau.report <blob_file>`): read the blob file path from argv, `inflate(blob, fresh=False)` to get the carried RelationalState WITHOUT dropping stale facts (use fresh=False so ground_report sees ALL carried facts, not just the pre-filtered live ones — `inflate(..., fresh=True)` would already have stripped stale facts from `verified_facts`), then run `plateau.ground_report(inflated.state)`, `print(json.dumps(report))`, and `sys.exit(0 if report["n_stale"]==0 else 1)`. Add a `if __name__=="__main__":` guard and a `main()`/`if __name__` so `python -m plateau.report` works. `inflate` is in `plateau.continuum`; `Inflated.state` is the RelationalState. Run: `cd <repo> && uv run --with pytest --with numpy pytest -q`.
