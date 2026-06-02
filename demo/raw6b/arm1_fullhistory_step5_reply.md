# demo6 step=5 — arm1_fullhistory

## Sub-task advanced: L5 — `plateau/report.py` + `python -m plateau.report <blob_file>` CLI

### What changed

**`plateau/report.py` (NEW)**
- New `main(argv: list[str] | None = None) -> int` entry point + `if __name__ == "__main__": sys.exit(main())` guard, so `python -m plateau.report <blob_file>` works.
- Flow: read the single blob-file path from argv → read file → `inflate(blob, fresh=False)` (deliberately `fresh=False` so stale facts are NOT pre-stripped and `ground_report` sees ALL carried facts) → `ground_report(inflated.state)` → `print(json.dumps(report, sort_keys=True))` to stdout → `return 0 if report["n_stale"] == 0 else 1`.
- Imports only `json`, `sys`, `.continuum.inflate`, `.signal.ground_report` (no host-specific deps; package stays host-agnostic).
- Exit codes: `0` all live (`n_stale==0`), `1` ≥1 stale, `2` usage error (wrong arg count / missing-or-unreadable file via `OSError` / unparseable blob via `ValueError`/`TypeError`). Only the JSON report goes to stdout; all diagnostics go to stderr. Never raises out of `main()` for the file/usage/parse error paths.

No changes to `__init__.py` (the task only requires the `python -m plateau.report` module entry, and `inflate`/`ground_report` were already exported in L3/L4). No other files touched.

### Verification
- Full suite: `26 passed` (no regressions; L6 still owns the new `tests/test_verification_chain.py`).
- CLI smoke (subprocess `python -m plateau.report`): LIVE blob → exit 0, `{"facts":[...],"n_live":1,"n_stale":0}`; STALE blob (file mutated after emit so `file_hash` mismatches) → exit 1, `n_stale=1` (confirms `fresh=False` keeps the stale fact visible to the report rather than dropping it); missing file → exit 2 (stderr only, empty stdout); malformed-JSON blob → exit 2; no args → exit 2 with usage message.

CARRY: L5 DONE. NEW FILE `plateau/report.py` with `main(argv: list[str] | None = None) -> int` and a `__main__` guard; invoked as `python -m plateau.report <blob_file>`. Behavior: reads ONE blob-file path from argv, `plateau.continuum.inflate(blob, fresh=False)` (fresh=False is REQUIRED so `verified_facts` keeps stale facts for honest counting), runs `plateau.signal.ground_report(inflated.state)`, `print(json.dumps(report, sort_keys=True))` to stdout, returns `0 if report["n_stale"]==0 else 1`. Exit code `2` for usage errors: wrong arg count, missing/unreadable file (`OSError`), or unparseable blob (`ValueError`/`TypeError`); usage/error messages go to STDERR, stdout stays empty on exit 2. `report["n_stale"]` is the authoritative all-live check (== `len(facts) - n_live`). The printed JSON is exactly `ground_report`'s dict `{"facts": list[{"claim","kind","live","stale_children"}], "n_live": int, "n_stale": int}` with `sort_keys=True`. Only L6 remains: NEXT (L6) create `tests/test_verification_chain.py` (>=6 tests) covering each layer L1–L5 PLUS that the gate admits an all_of only while every child is live; use pytest `tmp_path` + `set_ground_root(str(tmp_path))`; for L5 invoke the CLI via `subprocess.run([sys.executable,"-m","plateau.report",blob_path], cwd=<ground_root>, env={...,"PYTHONPATH":<repo>})` and assert returncode 0 (all live) vs 1 (stale) vs 2 (missing/malformed/no-arg), parsing stdout JSON. Also add the one-paragraph docs to `README.md` + `adapters/claude_code/SKILL.md` (docs not required by the success check). Run: `cd <repo> && uv run --with pytest --with numpy pytest -q`.
