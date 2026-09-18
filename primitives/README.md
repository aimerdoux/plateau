# primitives/

This directory holds **primitives**: small, leak-checked JSONL/JSON distilled from a
private raw source (a sealed experiment's raw run directory, or an adapter's
`.plateau/` session store) by `plateau absorb` (`plateau/absorb.py`; contract in
`docs/harness-0.3/PLAN-absorb.md`). The raw/store itself is never committed here and
stays in the private ring; a primitives directory carries only aggregate counts,
bucketed statistics, and the SHA-256 of every raw file it was distilled from, so a
holder of the raw can re-derive it and confirm it matches.

Layout:

```
primitives/<experiment>/<run_id>/    # --raw <dir|tar.gz> --experiment <experiment>
primitives/adapter/<run_id>/         # --store <dir>
```

## What is never in here

Per `docs/harness-0.3/PLAN-absorb.md` ("Leak rule"), no primitive value may contain: a
raw file path, a symbol/identifier lifted from source code, a decision's text, or a
shadow/D-038 probe's question/expected/answer text. `absorb` builds a forbidden set
from the raw itself (every receipt target, node key, path under `snap/`/`work/`/the
store, identifier in a probe's `q`/`expected`, decision text, judge citation, and the
target's own basename) and fails closed if any primitive value contains one of those
strings (length >= 4), a code fence, or a bare `dir/file.ext`-shaped string. Relative
paths that DO need to be recorded (`hashes.json`) are hashed, never written in the
clear: `hashes.json`'s `raw_files` maps `sha256(relpath)` -> `sha256(file bytes)`.

`plateau absorb --check <this dir>` re-runs the reproducible half of that check (the
structural code-fence/path-shaped-string rules, plus `hashes.json`'s own internal
consistency) without needing the raw back — see `check_primitives` in
`plateau/absorb.py` for exactly what is and is not re-verifiable that way.

## Files

Every primitives directory has `run.json` (single object: run id, source, target
commit/tree hashes only, settings, cost, raw file count/hash, `forbidden_digest`) and
`hashes.json` (`{"raw_files": {...}, "manifest_sha256": ...}`). The rest are JSONL, one
object per line:

- `turns.jsonl` — per `(token|session, turn)`: timing/cost, token usage, tool-call
  tallies, test/error counts.
- `probes.jsonl` — per shadow/D-038 probe: class, kind, lag/compaction buckets,
  verdict, and only the *lengths* of the question/expected/answer plus a `q_hash` —
  never the text itself.
- `injections.jsonl` — per injection event: chars/budget/node counts, holdout flag.
- `compactions.jsonl` — per compaction boundary: which turn, and (experiment source)
  the surrounding token-usage context.
- `rederivations.jsonl` — per `(token|session, turn, after_compaction_k, extension)`:
  a count. Never a path, only the file's extension.
- `nodes.jsonl` (adapter source only) — per `(session, node kind)`: count and mean
  degree.
- `judge.json` (experiment source only) — per token: epic scores, counts, never the
  judge's prose (`defects_len` is a length, not the text).
- `derived.json` (experiment source only) — recall by lag/compaction bucket, AUC,
  far-lag recall, re-derivation totals and tokens/turn, recomputed from the primitives
  alone. When the experiment's own `results.json` is available at absorb time, `absorb`
  asserts these are equal to it (a mismatch is a hard error, not a warning) — this is
  the "recompute link" back to the sealed scorer's numbers.

`plateau fit --from-primitives primitives/ --date YYYY-MM-DD` reads every
`primitives/<source>/<run_id>/` here and folds them into the root `model.toml`
(`plateau/lab/fit.py::from_primitives`): one cell per experiment arm (`sessions = 1`,
tagged with its `run_id`), and one cell per adapter run once it has `sessions >= 5`. It
never deletes an existing `model.toml` cell, and a freshly-fitted cell whose
`(model_id, bridge_version)` already names a hand-seeded reference cell (e.g. the
D-038 run-1 seed) is only written when it reproduces that seed within 0.01 — otherwise
both are printed side by side and the seed is left untouched.
