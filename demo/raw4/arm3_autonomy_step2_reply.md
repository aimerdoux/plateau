DIFF:
- plateau/signal.py:
  - Added module-level `KNOWN_KINDS: tuple[str, ...]` = the closed 6-member set (file_hash, command_output, test_result, oracle_score, exit_code, operator). Single source of truth for the `Measurement.kind` Literal AND continuum's lossless-carry guard. Placed directly above the `Measurement` dataclass. No behavioral change to `reverify()`.
- plateau/continuum.py:
  - Imported `KNOWN_KINDS` from `.signal` (now `from .signal import KNOWN_KINDS, Measurement, RelationalState, SelfState`).
  - `ground()`: added a guard at the top of the per-fact loop — if `vf["grounding_kind"]` (default "file_hash") is NOT in `KNOWN_KINDS`, the fact is appended to `stale` with reason `"unknown measurement kind {kind!r}; carried fact is unverifiable"` and we `continue` (never construct a `Measurement` or call `reverify()` for a malformed kind). Known kinds — including `command_output` — flow through unchanged to `Measurement(...).reverify()` exactly as before, so the new kind carries losslessly through emit→ground→inflate.
- Verified: all 26 existing tests pass (0.23s). `command_output` round-trips through the gate/continuum with kind/source/value intact; only malformed kinds are newly diverted to STALE.

CARRY:
- `KNOWN_KINDS` (tuple) is now exported from `plateau.signal` and is the canonical kinds set; `command_output` IS a member, so continuum re-grounds it normally. Unknown kinds now go STALE in `ground()` BEFORE any reverify call.
- emit/inflate are untouched: kind passes as a free-form string via `grounding.kind` ⇄ `grounding_kind`. The guard lives only in `ground()` (which `inflate(fresh=True)` calls), so inflate's stale list now also captures malformed-kind facts.
- Module-global state to reset in tests: `set_command_whitelist([])` AND `set_ground_root(...)` per test (both leak across tests).
- Value convention (unchanged, harness-matching): `"sha256:" + hashlib.sha256(proc.stdout).hexdigest()` on RAW stdout bytes. Whitelist match = EXACT string == `Measurement.source` (full cmd). Command runs `cwd=_GROUND_ROOT`, `shell=False`, argv via `shlex.split`.
- gate()/apply_gate() are kind-agnostic; no gate changes needed for command_output.

FORWARD_PLAN:
- SUB-TASK 3 (NEXT) — tests/test_measurement_kinds.py (NEW), >=2 tests. Depends on 1+2 (both done).
  - PRE-EXPLORE (concrete):
    - Imports: `from plateau import Measurement, Thought, RelationalState, SelfState, emit, inflate, ground, apply_gate, set_ground_root, set_command_whitelist`. (All are exported from package root per step-1 reply; confirm `Thought`/`apply_gate` are re-exported in plateau/__init__.py — they are used by test_continuum.py so they are.)
    - Fixture/teardown (CRITICAL — module-global leakage): add a pytest fixture with `autouse=True` that yields then calls `set_command_whitelist([])` and `set_ground_root(".")` (or the original root) to reset both globals after EVERY test. Without this, a whitelisted cmd or moved ground root leaks into other test modules.
    - Stale-transition mechanism: stdout must be controllable. Use `cat f.txt` against a tmp ground root:
      `set_ground_root(str(tmp_path))`; write `f.txt` = "alpha\n"; whitelist EXACTLY `"cat f.txt"` via `set_command_whitelist(["cat f.txt"])`; compute recorded value = `"sha256:" + hashlib.sha256(b"alpha\n").hexdigest()` (RAW bytes incl. trailing newline that `cat` emits — must match the file's exact bytes, so write_bytes(b"alpha\n") not write_text to avoid platform newline ambiguity).
      `m = Measurement("command_output", "cat f.txt", recorded)`; assert `m.reverify() is True`. Then `(tmp_path/"f.txt").write_bytes(b"beta\n")`; assert `m.reverify() is False` (STALE).
    - Test A `test_command_output_reverifies_then_stale`: the above — stable→True, mutate→False.
    - Test B `test_command_output_gate_admits_only_while_live`: drive through the gate/continuum. Build `sig = apply_gate(SelfState(RelationalState(), [Thought("out=alpha", m)]))`; assert the fact is admitted (`any(vf["claim"]=="out=alpha" for vf in sig.verified_facts)`). Then `emit`→mutate file→`inflate(blob, fresh=True)` and assert `inf.stale_claims()==["out=alpha"]` and it is NOT in `inf.state.verified_facts`. NOTE: apply_gate itself calls reverify at gate time, so the whitelist+ground_root must be set BEFORE apply_gate or the fact won't admit even while "live".
    - Optional Test C (cheap, exercises sub-task 2 guard): a fact with `grounding_kind="bogus_kind"` fed through `ground()` lands in stale with the "unknown measurement kind" reason — but build it via a RelationalState dict directly since Measurement's Literal won't type a bogus kind; construct `RelationalState(verified_facts=[{"claim":"x","grounding_kind":"bogus","grounding_source":"","grounding_value":""}])` and assert `ground(rs).stale_claims()==["x"]`.
    - PITFALLS:
      1. Whitelist string MUST be byte-identical to `Measurement.source` ("cat f.txt"), NOT "cat" — match is on the full command.
      2. `cat` appends nothing but emits the file bytes verbatim; the recorded sha256 must be over the EXACT file bytes. Use `write_bytes` to control newlines precisely.
      3. apply_gate reverifies at admit time → set globals first.
      4. Reset BOTH globals in teardown or test_signal_gate/test_continuum (same process) may see a leaked whitelist/ground_root.
      5. Verify `apply_gate` returns the RelationalState (signal) — in test_continuum it is used as `sig = apply_gate(...)` then `emit(SelfState(signal=sig))`. Mirror that exact shape.
- SUB-TASK 4 — README.md + adapters/claude_code/SKILL.md: one paragraph each documenting command_output (whitelist requirement, sha256-stdout convention, fail-closed list: nonzero exit / non-whitelisted / missing); SKILL pending-facts format gains a command_output example. Depends on 1. PITFALL: read the existing file_hash paragraph in README.md and the pending-facts schema (field names kind/source/value) in adapters/claude_code/SKILL.md FIRST; match style/placement and exact field names so the example parses.
