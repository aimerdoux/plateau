# demo6 step=3 — arm2_efficiency reply

## Sub-task advanced this step: L3 (continuum.py carries `all_of` losslessly + STALE guard)

### Summary of changes
- **`plateau/continuum.py`**
  - Added helper `_all_of_source_parses(source: str) -> bool` — returns True only when an `all_of`'s `source` parses as a non-empty JSON list (per-child validity is left to `Measurement.reverify()`).
  - Wired an explicit **L3 guard** into `ground()`: a fact with `grounding_kind == "all_of"` whose source fails `_all_of_source_parses` is classified **STALE** up front with a self-describing reason `"malformed all_of source (won't parse into a non-empty child list)"`, instead of relying on `reverify()`'s incidental fail-closed (which would have reported generic "reality no longer supports" drift). `inflate()` inherits this because it calls `ground()`.
  - Confirmed (and locked in by tests) that `emit`/`inflate` already carry `all_of` **losslessly**: the JSON child-spec list rides in the `grounding.source` string field and survives the round-trip byte-identical; nested children are never flattened or dropped.
- **`tests/test_continuum.py`** (+`import json`)
  - `test_all_of_carries_losslessly` — composite survives emit→inflate with nested child specs byte-identical; re-grounds LIVE while every child is live.
  - `test_all_of_stale_when_a_child_dies` — once any child reverify fails, the carried `all_of` inflates STALE.
  - `test_malformed_all_of_source_is_stale_guard` — unparseable source → STALE in both `ground()` and `inflate()`, with the malformed-source reason surfaced.

### Verification
`uv run --with pytest --with numpy pytest -q` → **29 passed** (26 prior + 3 new). No prior tests touched.

CARRY: schema=plateau.signal.v1. L1+L2+L3 DONE. `all_of` (kind in `Measurement.kind` Literal) crosses emit/inflate/ground losslessly via the `grounding.source` JSON string (child specs `[{"kind","source","value"},...]` byte-identical through round-trip; nesting flat, child kinds limited to `_ALL_OF_CHILD_KINDS` in signal.py). continuum.py now exposes `_all_of_source_parses(source)->bool` and `ground()` flags a malformed-source `all_of` STALE with reason `"malformed all_of source (won't parse into a non-empty child list)"` (inflate inherits this). `Grounding` has fields `.live`/`.stale` (each stale dict: `{claim, grounding_source, reason}`) + `.stale_claims()`; `Inflated` has `.state`/`.stale` + `.stale_claims()`. NEXT = L4 `plateau/signal.py ground_report(state)->dict`: walk `state.verified_facts`, per fact `{claim,kind,live,stale_children}`, descend `all_of` and name failing child sources, aggregate `{n_live,n_stale}`. Then L5 `plateau/report.py` CLI (`python -m plateau.report <blob_file>` → inflate blob, run ground_report, print JSON, exit 0 iff all live else 1), then L6 `tests/test_verification_chain.py` (>=6 tests across all layers + gate admits an all_of only while every child live) + README/SKILL docs. Keep suite green (now 29).
