DIFF:
plateau/signal.py — L2 `all_of` composite Measurement kind.
- `import json` added.
- `"all_of"` added to `Measurement.kind` Literal.
- `reverify()` dispatch: `if self.kind == "all_of": return self._reverify_all_of()`.
- New `_reverify_all_of()`: parses `source` as JSON list of child specs `{kind,source,value}`; builds a child `Measurement(**spec)` per element and re-verifies it; returns True iff EVERY child re-verifies. Fails CLOSED on: unparseable JSON (ValueError/TypeError), non-list top level, EMPTY list, any element not a dict, spec keys != exactly {kind,source,value}, any non-string field, or any child that does not re-verify. Children may be file_hash/command_output/nested all_of.
- 26 existing tests still green; manual matrix (all-live True; one-stale/empty/malformed/non-list/unknown-child/missing-key all False; nested all_of True) confirmed.

CARRY:
- all_of source shape: `Measurement(kind="all_of", source=json.dumps([{kind,source,value}, ...]), value="")`. `value` is unused/ignored for all_of (the conjunction IS the value); children re-verify recursively via the same `reverify()` contract, so nesting is lossless.
- L3 (continuum.py emit/inflate/ground) must round-trip the all_of `source` string verbatim — it is itself JSON containing child specs; do NOT re-encode/double-escape. An all_of whose `source` won't `json.loads` must be treated STALE by continuum's guard (mirror the fail-closed in `_reverify_all_of`).
- Fail-closed contract to preserve downstream: empty list, malformed/non-list source, bad spec keys, and any non-reverifying child → not live. L4 `ground_report` will need to descend all_of and name the specific failing child `source`(s); the per-spec validation lives in `_reverify_all_of` and short-circuits on first failure, so a reporting walk should re-walk all children rather than reuse the boolean.
- Remaining open: L3 continuum carry, L4 ground_report, L5 plateau/report.py CLI, L6 tests/test_verification_chain.py (>=6) + README/SKILL docs.
- Test runner: `uv run --extra test --extra demo python -m pytest -q` (the `demo`/numpy extra is required or 4 metrics tests error on numpy import — unrelated to signal work).
