DIFF:
- NEW `plateau/report.py` (L5): `main(argv=None)` + `__main__` guard calling `sys.exit(main())`. Reads `<blob_file>`, `inflate(blob, fresh=False)` (keeps stale facts so the report can NAME them instead of pruning), runs `ground_report(inflated.state)`, `print(json.dumps(report, indent=2, sort_keys=True))`, returns `0 iff report["n_stale"]==0 else 1`. Usage/unreadable-file errors return 2 on stderr.
- No edits to signal.py / continuum.py / __init__.py — L1-L4 already in place and untouched.
- Verified: `python -m plateau.report <blob>` → live fact rc=0; stale file_hash + all_of-with-bad-child rc=1 (failing child `plateau/nope.py` named in `stale_children`); no-arg rc=2.
- 26 tests green (`uv run --extra test --extra demo python -m pytest -q`).

CARRY:
- L6 is the only remaining layer: NEW `tests/test_verification_chain.py`, >=6 tests, total >=32 (currently 26). Cover one test per layer L1-L5 + the keystone "gate admits an all_of only while every child is live" (mutate one child file/hash → gate must drop it).
- Test fixtures: write real temp files under a `set_ground_root(tmpdir)`; build all_of source via `json.dumps([{kind,source,value}, ...])`; `file_hash()` already returns a `sha256:`-prefixed string — do NOT re-prefix (double `sha256:sha256:` silently fails reverify). For command_output children, call `set_command_whitelist([...])` first or they fail closed.
- L5 CLI test (in test_verification_chain.py): emit a blob to a temp file, call `plateau.report.main([path])` in-process and assert rc 0/1; OR subprocess `[sys.executable,"-m","plateau.report",path]`. Assert n_stale and that a failing all_of child's source appears in `stale_children`.
- Runner gotcha (unchanged): `uv run --extra test --extra demo python -m pytest -q` — the `demo`/numpy extra is REQUIRED or 4 metrics tests error on numpy import.
- Docs (not gated by the check): one paragraph each in `README.md` and `adapters/claude_code/SKILL.md` describing the serial verification chain (command_output → all_of → lossless carry → ground_report → report CLI) and the fail-closed/exit-code contract.
