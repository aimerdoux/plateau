# Absorb — private raw → public primitives → model.toml

Contract addendum to PLAN.md. Purpose: every private run (a sealed experiment's raw dir, or an adapter session's
`.plateau/` store and ledger) is distilled by a deterministic, leak-checked process into **primitives**: small,
target-free JSONL that lives in this public repo under `primitives/<source>/<run_id>/` and from which `plateau fit`
recomputes `model.toml`. The raw stays in the private ring; the primitives carry the SHA-256 of every raw file they
were distilled from, so a holder of the raw can recompute them. Primitives are not a substitute for the raw for
recompute of a sealed verdict; they are what the repo learns from.

## CLI

```
plateau absorb --raw <dir|tar.gz> --run-id <id> [--experiment d038] --out primitives/<experiment>/<id>/
plateau absorb --store <dir with index.sqlite, ledger.sqlite, handoff/, hooks.log> --run-id <id> --out primitives/adapter/<id>/
plateau absorb --check <primitives dir>        # re-runs the leak check and the schema check, exit 1 on failure
plateau fit --from-primitives primitives/ --date <YYYY-MM-DD>   # cells from every primitives dir (sessions ≥ 1 for
                                                                 # experiment cells, marked run_id; ≥ 5 for adapter cells)
```

## Primitive files (all JSONL, one object per line, keys fixed; `run.json` is a single JSON object)

- `run.json`: `{run_id, source: "experiment"|"adapter", experiment, arms: {token: arm} (experiment only), target: {commit, tree}
  (hashes only, never a name), settings: {window, pct, model_ids[], cli_version, bridge_version, bridge_sha}, cost_usd:
  {task, probe, judge}, raw_files: <n>, raw_sha256: <sha of sorted "hash  relpath" lines>, tarball_sha256|null, absorbed_by:
  "plateau <version>"}`.
- `turns.jsonl`: `{token|session, i, turn_id|null, seconds|null, cost|null, api_calls, tokens_in, tokens_cache_read,
  tokens_cache_create, tokens_out, compactions_in_turn, tools: {Read, Edit, Write, Bash, Grep, Glob, other}, reads_of_code,
  tests_run, tests_passed|null, tests_failed|null, errors_seen}`.
- `probes.jsonl`: `{token|session, turn, cls, kind, lag_tokens, compactions_crossed, lag_bucket, comp_bucket, verdict|null,
  expected_len, answer_len, q_hash, probe_contaminates}` — never the question, expected or answer text.
- `injections.jsonl`: `{token|session, event, compaction_k, chars, budget, nodes, of_nodes, holdout, rid_at}`.
- `compactions.jsonl`: `{token|session, k, turn, line, context_before, context_after}` (from usage fields).
- `rederivations.jsonl`: `{token|session, turn, after_compaction_k, ext, count}` — extension only, never a path.
- `nodes.jsonl`: `{session, kind, count, mean_degree}` (adapter source) — kinds only.
- `judge.json` (experiment only): `{token: {epics: {E1..E4}, task_total, security_items_closed, runner_green, defects_len}}`.
- `payload_shapes.json`: `{event: [sorted key names]}` observed in a payload dump when present, else `{}`.
- `hashes.json`: `{raw_files: {relpath_hash: sha256}}` — relpaths are themselves hashed (sha256 of the relpath), so no
  file name from the private target appears; plus `manifest_sha256`.

## Leak rule (fail closed)

`absorb` builds a forbidden set from the raw: every receipt `target`, every node key, every path under `snap/`, `work/`
and the store, every symbol/identifier in probe `expected` and `q`, every decision text, every judge citation, and
every string of a Wavex/target file basename. It then scans every primitive value (recursively) and fails if any
forbidden string of length ≥ 4 occurs, or if any value matches `/[\w.-]+/[\w.-]+\.(mjs|js|ts|py|md|json)` or contains
a code fence. `plateau absorb --check` re-runs this using `hashes.json` and the forbidden-set digest stored in
`run.json` (`forbidden_digest`: sha256 of the sorted forbidden set) so the check is reproducible without the raw.
The `tests/test_absorb.py` leak test plants a path, a symbol and a decision text into a synthetic raw and asserts
absorb refuses.

## Recompute link

For an experiment source, `absorb` also emits `derived.json` with the scorer-level numbers it can recompute from the
primitives alone (recall per bucket per arm, AUC, far-lag recall, re-derivation totals, tokens per turn) and asserts
them equal to the values in the experiment's `results.json` when that file is present (D-038 run 1: A far-lag 0.393,
AUC 0.618 / 0.744, re-derivations 142 / 105, tokens per turn 143 676 / 109 215). A mismatch is an error, not a warning.

## Ownership

| owner | files |
|---|---|
| D1 absorb | `plateau/absorb.py` (new), `plateau/cli.py` (`absorb` subcommand + `fit --from-primitives` flag delegating to `plateau.lab.fit.from_primitives`), `plateau/lab/fit.py` (`from_primitives`), `tests/test_absorb.py`, `primitives/README.md` |
| orchestrator | runs absorb on the D-038 tarball and on the adapter store, reviews, commits `primitives/` |

Conventions as PLAN.md. Zero spend.
