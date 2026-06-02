# demo6 step=6 — arm1_fullhistory

## Sub-task advanced: L6 — `tests/test_verification_chain.py` (+ feature docs)

This is the FINAL layer. L1–L5 were already implemented and verified in prior steps;
L6 adds the test coverage that pins each layer end-to-end plus the composite gate rule,
and the (not-check-required) one-paragraph docs.

### What changed

**`tests/test_verification_chain.py` (NEW, 6 tests)**
- `test_l1_command_output_whitelist_and_hash` — L1: a `command_output` Measurement
  (`sys.executable -c ...`) re-verifies only when whitelisted via `set_command_whitelist`
  AND `'sha256:'+sha256(stdout)` matches; fails closed when not whitelisted (no execution)
  and on a wrong recorded hash. Saves/restores `signal._CMD_WHITELIST` so the module-global
  whitelist does not leak into other tests.
- `test_l2_all_of_true_iff_every_child_reverifies` — L2: `all_of` is True iff every child
  reverifies; one moved child → False; fail-closed on empty list / malformed JSON / unknown
  child kind.
- `test_l3_all_of_round_trips_lossless_and_guards_malformed` — L3: a nested `all_of` survives
  `emit`→`inflate` with child JSON byte-intact (`json.loads(source) == children`) and grounds
  live; a malformed `all_of` source is flagged STALE via the continuum guard (reason contains
  "did not parse").
- `test_l4_ground_report_names_failing_children_and_aggregates` — L4: live `all_of` →
  `stale_children == []`; after one child moves, `live=False` and `stale_children` names ONLY
  the failing child source; `{n_live,n_stale}` aggregate correct across a composite + a dead
  solo fact.
- `test_l5_report_cli_exit_codes` — L5: `subprocess` runs `python -m plateau.report <blob>`
  with `cwd=ground_root` and `PYTHONPATH=repo`; asserts exit 0 (all live, JSON report on
  stdout, `n_stale==0`), exit 1 (file mutated after emit so the fact is stale; confirms the
  CLI's `fresh=False` keeps the stale fact visible), exit 2 (missing file, empty stdout).
- `test_gate_admits_all_of_only_while_every_child_live` — THE composite gate rule: the gate
  admits an `all_of`-grounded Thought while both children are live, and drops the same Thought
  ("did not re-verify") the moment one child's reality moves.

Helpers: `_file_measurement` (live `file_hash` rooted at `tmp_path` via `set_ground_root`),
`_all_of_source` (json-encode child specs), `_emit_blob`/`_run_report` for the CLI test.

**`README.md`** — added a "Verification chain (composite grounding)" paragraph
(command_output + all_of + lossless carry + ground_report + `python -m plateau.report`);
updated the stale Layout test count 26 → 32.

**`adapters/claude_code/SKILL.md`** — added a "Composite grounding (`all_of` /
`command_output`)" paragraph describing the new fact kinds, the gate's all-children-live
admission rule, and the report CLI.

### Verification
- New file alone: `6 passed`.
- Full suite: `32 passed` (was 26; +6 new, no regressions) via
  `uv run --with pytest --with numpy pytest -q`.

CARRY: L6 DONE — feature COMPLETE (all of L1–L5 implemented in prior steps; L6 adds tests +
docs). New file `tests/test_verification_chain.py` has 6 tests, one per layer L1–L5 plus the
composite gate rule (`test_gate_admits_all_of_only_while_every_child_live`). Full suite =
32 passed. Test conventions used: `tmp_path` + `plateau.set_ground_root(str(tmp_path))`;
`file_hash` from `plateau.integrity`; for `command_output` save/restore
`plateau.signal._CMD_WHITELIST` around `set_command_whitelist([cmd_string])` (cmd is the
shlex-quoted `[sys.executable,"-c",...]` argv — whitelist matches the FULL argv); for the L5
CLI use `subprocess.run([sys.executable,"-m","plateau.report",blob_path], cwd=ground_root,
env={**os.environ,"PYTHONPATH":<repo parents[1]>})` and assert returncode 0/1/2 parsing
stdout JSON. Run: `cd <repo> && uv run --with pytest --with numpy pytest -q`. No further
sub-tasks remain; docs in README.md + adapters/claude_code/SKILL.md are in place (they are
markdown-only and not gated by the success check).
