# demo6 step=3 — arm1_fullhistory

## Sub-task advanced: L3 — continuum carries `all_of` losslessly + explicit STALE guard

### What changed

**`plateau/continuum.py`**
- New helper `_all_of_source_parses(source: str) -> bool`: returns True only if `source`
  `json.loads`-es into a NON-EMPTY list. Mirrors how `Measurement._reverify_all_of`
  fails closed, but lifts the parse check up to the continuum layer.
- `ground(state)` now has an explicit guard: a fact with `grounding_kind == "all_of"`
  whose `grounding_source` fails `_all_of_source_parses` is appended to `stale` BEFORE
  any child is touched, with a distinct reason
  `"all_of source did not parse into a non-empty list (composite grounding is malformed)"`.
  Well-formed `all_of` facts still flow through `Measurement(...).reverify()` as before;
  if a child's reality moved they get the existing generic reason
  `"reality no longer supports this carried fact"` — so the two failure modes are
  distinguishable (useful for L4's `ground_report` which descends `all_of` and names
  failing child sources).
- Updated `ground()` docstring to document lossless `all_of` carry + the guard.

### Lossless carry: already structural (verified, not re-implemented)
`emit` / `inflate` pass `grounding.kind/source/value` through verbatim. For an `all_of`,
the JSON child list lives in `source` as an opaque string, so it survives the
`json.dumps`/`json.loads` round-trip with nested children (including `all_of`-in-`all_of`)
fully intact. Confirmed by smoke: a nested `all_of` round-trips through emit→inflate with
`grounding_kind == "all_of"` preserved and `grounding_source == original`; nested child
source strings (e.g. `a.txt`, its `sha256:` value) all present in the blob. No change to
`emit`/`inflate` was needed — the lossless requirement was met by the existing
pass-through; only the explicit guard was missing.

### Verification
- Full suite: `26 passed` (no regressions; L6 still owns the new tests).
- Smoke confirmed: nested `all_of` lossless round-trip + all-live; malformed-JSON source →
  STALE via guard; empty-list `[]` source → STALE via guard (distinct reason);
  well-formed `all_of` with a child whose reality moved → STALE via reverify (generic
  reason); all-children-live `all_of` → live, no stale.

CARRY: L3 DONE. Continuum now carries `all_of` losslessly and guards it. Lossless carry
is STRUCTURAL: `emit`/`inflate` pass `grounding.kind/source/value` unchanged, so an
`all_of`'s JSON child list (in `grounding_source`, value `""`) round-trips with nested
children intact — including `all_of` nested in `all_of`. STALE guard lives in
`plateau.continuum.ground()`: a `grounding_kind=="all_of"` fact whose `grounding_source`
fails new helper `plateau.continuum._all_of_source_parses(source)` (True iff `json.loads`
→ non-empty list) is put in `Grounding.stale` BEFORE any child runs, reason
`"all_of source did not parse into a non-empty list (composite grounding is malformed)"`.
Well-formed-but-failing all_of gets the generic reason
`"reality no longer supports this carried fact"`. `Grounding` (continuum) has
`.live: list[dict]` / `.stale: list[dict]` (+ `.stale_claims()`); each stale entry is
`{claim, grounding_source, reason}`. `inflate(blob, fresh=True)` re-grounds and sets
`Inflated.state.verified_facts = g.live`, `Inflated.stale = g.stale` (+ `.stale_claims()`).
A carried verified_fact dict shape is
`{claim, grounding_kind, grounding_source, grounding_value}`.
NEXT (L4, `plateau/signal.py`): add `ground_report(state) -> dict` that walks
`state.verified_facts`; per fact emit `{claim, kind, live, stale_children}` — for an
`all_of`, DESCEND its children (parse `grounding_source`/the child `source` JSON) and
name the failing child `source`s in `stale_children` (reuse the live/malformed split
logic — malformed/empty all_of ⇒ live False; reuse `Measurement(**child).reverify()` per
child to decide which children are live); aggregate `{n_live, n_stale}` over all facts.
Mirror `ground()`'s parse-guard so a malformed all_of reports live False with an empty or
sentinel `stale_children` consistently. Run: `uv run --with pytest --with numpy pytest -q`.
