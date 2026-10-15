"""The `gatekeeper` hook mode -- the control loop's Stop-hook controller.

`plateau.agency.gatekeeper` is dispatched like every other Plateau hook mode, by BOTH entry
points (`adapters/claude_code/hook.py gatekeeper --cc` and `plateau hook gatekeeper`), and it
is only armed by `<project>/.plateau/control/PLAN.md`. The two real entry points are driven
as subprocesses below; the in-process `main()` covers the many-call and strict-mode cases.
The `control/gatekeeper.sh` shim is exercised, unchanged, by test_control_loop.py and
test_inner_loop.py, and once more at the end of this file.
"""

import hashlib
import importlib.util
import io
import json
import os
import re
import shutil
import subprocess
import sys
import time
from types import SimpleNamespace

import pytest

from plateau import cli
from plateau.agency import control as C
from plateau.agency import gatekeeper as G
from plateau.bridge import dedupe, install

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOOK_PY = os.path.join(ROOT, "adapters", "claude_code", "hook.py")
HOOKS_JSON = os.path.join(ROOT, "adapters", "claude_code", "hooks", "hooks.json")
SHIM = os.path.join(ROOT, "adapters", "claude_code", "control", "gatekeeper.sh")

ENTRY_POINTS = {
    "hook.py": [sys.executable, HOOK_PY, "gatekeeper", "--cc"],
    "plateau-hook": [sys.executable, "-m", "plateau.cli", "hook", "gatekeeper"],
}
both_entry_points = pytest.mark.parametrize("entry", sorted(ENTRY_POINTS))

ROW_OPEN = "- [ ] T1 | write marker | out.txt | GATE: echo hi | EXPECT: exit0"
PLAN_ONE_OPEN = "# PLAN\n" + ROW_OPEN + "\n"


@pytest.fixture(autouse=True)
def _no_ambient_knobs(monkeypatch):
    """A developer's own CONTROL_DIR / RUN_GATES / ... must never leak into these tests."""
    for name in ("CONTROL_DIR", "RUN_GATES", "GATE_TIMEOUT", "GATEKEEPER_MAX_BLOCKS",
                 "PLATEAU_NO_DEDUPE"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def project(tmp_path):
    path = tmp_path / "project"
    path.mkdir()
    return path


@pytest.fixture
def elsewhere(tmp_path):
    """A plain directory with no control run: where the hook process starts in the tests that
    hand it the project through the payload's `cwd`."""
    path = tmp_path / "elsewhere"
    path.mkdir()
    return path


@pytest.fixture
def call(monkeypatch, capsys):
    """One in-process `gatekeeper.main()` call: `call(cwd, payload, **env)` returns
    `(rc, out, err)`. An env value of None unsets the variable; the rest are set (and undone
    when the test ends). Cheap enough to loop fifteen times. Each call is its own Stop: the
    twin window (one Stop reaching a doubly registered hook) is closed here and exercised by
    the subprocess tests at the end of the stall-cap section."""
    monkeypatch.setattr(G, "_TWIN_S", 0.0)

    def _call(cwd, payload="{}", **env):
        monkeypatch.chdir(cwd)
        for key, value in env.items():
            if value is None:
                monkeypatch.delenv(key, raising=False)
            else:
                monkeypatch.setenv(key, str(value))
        raw = payload if isinstance(payload, str) else json.dumps(payload)
        monkeypatch.setattr(sys, "stdin", io.StringIO(raw))
        rc = G.main([])
        captured = capsys.readouterr()
        return SimpleNamespace(rc=rc, out=captured.out, err=captured.err)
    return _call


def _spawn(entry, cwd, payload="{}", **env):
    """Run one real entry point as a subprocess, exactly as Claude Code would -- dedupe on
    (`_no_ambient_knobs` unsets PLATEAU_NO_DEDUPE), since it must never hold a Stop back."""
    full = dict(os.environ, **env)
    full["PYTHONPATH"] = os.pathsep.join(p for p in (ROOT, os.environ.get("PYTHONPATH")) if p)
    return subprocess.run(ENTRY_POINTS[entry], cwd=str(cwd), input=payload, capture_output=True,
                          text=True, env=full, timeout=60)


def _age(cdir, seconds=60.0):
    """Move the last Stop's `started` into the past: the next spawn is then a new Stop, not
    that one's twin (back-to-back subprocesses start well inside `_TWIN_S`)."""
    path = cdir / "STATE.json"
    state = json.loads(path.read_text(encoding="utf-8"))
    state["started"] -= seconds
    path.write_text(json.dumps(state), encoding="utf-8")


def _arm(project, plan=PLAN_ONE_OPEN):
    """Create `<project>/.plateau/control/PLAN.md` -- the one thing that arms the hook."""
    cdir = project / ".plateau" / "control"
    cdir.mkdir(parents=True, exist_ok=True)
    (cdir / "PLAN.md").write_text(plan, encoding="utf-8")
    return cdir


def _state(cdir):
    return json.loads((cdir / "STATE.json").read_text(encoding="utf-8"))


def _blocks(result):
    """True when one call blocked; asserts the block is exactly one parseable JSON line."""
    if not result.out:
        return False
    assert len(result.out.splitlines()) == 1, result.out
    assert json.loads(result.out)["decision"] == "block"
    return True


# ---------------------------------------------------------------- armed-only ------

@both_entry_points
def test_not_armed_prints_nothing(entry, tmp_path):
    """No PLAN.md, no opinion: an ordinary session is never touched, and not even a
    `.plateau` directory is left behind."""
    plain = tmp_path / "plain"
    plain.mkdir()
    r = _spawn(entry, plain)
    assert (r.returncode, r.stdout) == (0, "")
    assert not (plain / ".plateau").exists()

    # A control dir holding everything BUT a PLAN.md is still not armed.
    cdir = plain / ".plateau" / "control"
    cdir.mkdir(parents=True)
    (cdir / "RECON.md").write_text("# RECON\n")
    r = _spawn(entry, plain)
    assert (r.returncode, r.stdout) == (0, "")
    assert not (cdir / "STATE.json").exists()


@both_entry_points
def test_armed_with_an_unchecked_row_blocks(entry, project):
    cdir = _arm(project)
    r = _spawn(entry, project)
    assert r.returncode == 0, r.stderr
    assert len(r.stdout.splitlines()) == 1                       # exactly one JSON object
    out = json.loads(r.stdout)
    assert set(out) == {"decision", "reason"} and out["decision"] == "block"
    assert ROW_OPEN in out["reason"] and "1 unchecked gate(s)" in out["reason"]

    state = _state(cdir)
    assert (state["verdict"], state["unchecked"], state["blocks"], state["strict"]) == \
        ("BLOCK", 1, 1, 0)
    assert re.fullmatch(r"[0-9a-f]{64}", state["fingerprint"])
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", state["ts"])


def test_both_entry_points_print_byte_identical_json(project):
    """The plugin (`hook.py`) and a pip-only install (`plateau hook`) must be
    indistinguishable to Claude Code."""
    _arm(project)
    printed = {entry: _spawn(entry, project).stdout for entry in ENTRY_POINTS}
    assert printed["hook.py"] == printed["plateau-hook"] != ""


@both_entry_points
def test_payload_cwd_locates_the_run_when_the_process_cwd_is_elsewhere(entry, project, elsewhere):
    cdir = _arm(project)
    assert _spawn(entry, elsewhere, payload="{}").stdout == ""   # nothing to find from here
    r = _spawn(entry, elsewhere, payload=json.dumps({"cwd": str(project)}))
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)["decision"] == "block"
    assert _state(cdir)["verdict"] == "BLOCK"                    # state lands in the project ...
    assert not (elsewhere / ".plateau").exists()                 # ... never beside the process


def test_control_dir_env_relative_follows_the_payload_cwd_absolute_is_taken_as_is(
        call, project, elsewhere, tmp_path):
    run = project / "ops" / "run1"
    run.mkdir(parents=True)
    (run / "PLAN.md").write_text(PLAN_ONE_OPEN)
    assert call(project).out == ""                               # the default location is empty
    assert _blocks(call(elsewhere, {"cwd": str(project)}, CONTROL_DIR="ops/run1"))
    assert _blocks(call(elsewhere, CONTROL_DIR=str(run)))        # absolute: cwd is irrelevant
    assert call(elsewhere, CONTROL_DIR=str(tmp_path / "missing")).out == ""
    assert (run / "STATE.json").is_file()


@pytest.mark.skipif(not shutil.which("git"), reason="git required")
def test_a_subdirectory_of_the_project_resolves_through_the_git_toplevel(call, project):
    cdir = _arm(project)
    sub = project / "src" / "pkg"
    sub.mkdir(parents=True)
    assert call(sub).out == ""                                   # not a git repo yet: not armed
    subprocess.run(["git", "init", "-q", str(project)], check=True, capture_output=True)
    assert _blocks(call(sub))                                    # process cwd in a subdirectory
    assert _blocks(call(project, {"cwd": str(sub)}))             # payload cwd in a subdirectory
    assert _state(cdir)["blocks"] == 2


def test_a_payload_cwd_that_is_not_a_directory_falls_back_to_the_process_cwd(
        call, project, tmp_path):
    _arm(project)
    for bad in (str(tmp_path / "gone"), "", 7, None, ["x"]):
        assert _blocks(call(project, {"cwd": bad})), bad


@pytest.mark.parametrize("raw", ["", "not json", "[1, 2]", "null", '{"cwd": ', "\ufeff{}"])
def test_garbage_stdin_neither_disarms_nor_breaks_the_hook(call, project, raw):
    _arm(project)
    r = call(project, raw)
    assert r.rc == 0 and _blocks(r)


def test_main_ignores_argv_and_never_raises(project, monkeypatch, capsys):
    _arm(project)
    monkeypatch.chdir(project)
    monkeypatch.setattr(sys, "stdin", io.StringIO("{}"))
    assert G.main(["--cc", "--whatever", "x"]) == 0              # argv is ignored
    assert json.loads(capsys.readouterr().out)["decision"] == "block"

    def boom(_payload):
        raise RuntimeError("boom")

    monkeypatch.setattr(G, "_run", boom)
    monkeypatch.setattr(sys, "stdin", io.StringIO("{}"))
    assert G.main() == 0                                         # a crash must not trap the session
    assert capsys.readouterr().out == ""


def test_stdin_is_drained_whether_or_not_it_is_armed(project, monkeypatch):
    monkeypatch.chdir(project)
    for arm in (False, True):
        if arm:
            _arm(project)
        stdin = io.StringIO(json.dumps({"cwd": str(project), "pad": "x" * 200000}))
        monkeypatch.setattr(sys, "stdin", stdin)
        assert G.main([]) == 0
        assert stdin.read() == ""


# ------------------------------------------------------------------ the stall cap ------

@both_entry_points
def test_stall_cap_releases_after_the_cap_and_a_journal_line_starts_over(entry, project):
    cdir = _arm(project)

    def stop():
        if (cdir / "STATE.json").exists():
            _age(cdir)
        return _spawn(entry, project, GATEKEEPER_MAX_BLOCKS="3")

    for n in (1, 2, 3):                                          # calls 1-3 block ...
        r = stop()
        assert json.loads(r.stdout)["decision"] == "block", n
        assert _state(cdir)["blocks"] == n

    r = stop()                                                   # ... call 4 is released
    assert r.returncode == 0 and r.stdout == ""
    assert "GATEKEEPER_MAX_BLOCKS=3" in r.stderr
    state = _state(cdir)
    assert (state["verdict"], state["blocks"]) == ("ALLOW_STALLED", 0)

    with open(str(cdir / "JOURNAL.md"), "a", encoding="utf-8") as fh:
        fh.write("2026-01-01T00:00:00Z | T1 | EXECUTE | wrote it | ok | VERIFY\n")
    r = stop()                                                   # progress: a fresh window
    assert json.loads(r.stdout)["decision"] == "block"
    state = _state(cdir)
    assert (state["verdict"], state["blocks"]) == ("BLOCK", 1)


@pytest.mark.parametrize("progress", ["JOURNAL.md", "PLAN.md"])
def test_progress_restarts_the_stall_window(call, project, progress):
    """Without progress the fourth call would be released; any change to PLAN.md or
    JOURNAL.md (the fingerprint) means the agent is moving, so the count starts over."""
    cdir = _arm(project)
    for _ in range(3):
        assert _blocks(call(project, GATEKEEPER_MAX_BLOCKS=3))
    with open(str(cdir / progress), "a", encoding="utf-8") as fh:
        fh.write("- [ ] T2 | next | b | GATE: true | EXPECT: exit0\n" if progress == "PLAN.md"
                 else "a journal line\n")
    r = call(project, GATEKEEPER_MAX_BLOCKS=3)
    assert _blocks(r) and r.err == ""
    assert (_state(cdir)["verdict"], _state(cdir)["blocks"]) == ("BLOCK", 1)


def test_a_stall_release_is_one_release_then_a_fresh_window(call, project):
    _arm(project)
    seen = ["block" if call(project, GATEKEEPER_MAX_BLOCKS=2).out else "release"
            for _ in range(6)]
    assert seen == ["block", "block", "release", "block", "block", "release"]


@pytest.mark.parametrize("value, blocked_before_release", [
    ("1", 1), ("3", 3), (" 4 ", 4),
    (None, 10), ("", 10), ("junk", 10),                          # the default, and junk -> default
])
def test_cap_value_and_its_default(call, project, value, blocked_before_release):
    cdir = _arm(project)
    results = [call(project, GATEKEEPER_MAX_BLOCKS=value)
               for _ in range(blocked_before_release + 1)]
    assert all(_blocks(r) for r in results[:-1])
    assert results[-1].out == "" and "GATEKEEPER_MAX_BLOCKS" in results[-1].err
    assert _state(cdir)["verdict"] == "ALLOW_STALLED"


@pytest.mark.parametrize("value", ["0", "-1"])
def test_cap_zero_disables_the_release(call, project, value):
    cdir = _arm(project)
    for n in range(1, 16):
        r = call(project, GATEKEEPER_MAX_BLOCKS=value)
        assert _blocks(r) and r.err == "", n
    assert (_state(cdir)["verdict"], _state(cdir)["blocks"]) == ("BLOCK", 15)


def test_the_fingerprint_is_sha256_of_plan_then_journal(call, project):
    cdir = _arm(project)
    (cdir / "JOURNAL.md").write_text("line\n")
    call(project)
    plan, journal = (cdir / "PLAN.md").read_bytes(), (cdir / "JOURNAL.md").read_bytes()
    assert _state(cdir)["fingerprint"] == hashlib.sha256(plan + journal).hexdigest()
    (cdir / "JOURNAL.md").unlink()                               # a missing journal is empty
    call(project)
    assert _state(cdir)["fingerprint"] == hashlib.sha256(plan).hexdigest()


# ------------------------------------------------------------------- the verdicts ------

def test_a_non_block_verdict_writes_blocks_zero_and_restarts_the_count(call, project):
    cdir = _arm(project)
    call(project)
    call(project)
    assert _state(cdir)["blocks"] == 2
    (cdir / "BLOCKED.md").write_text("class: EXTERNAL\nattempts: 3\n")
    assert call(project).out == ""
    assert (_state(cdir)["verdict"], _state(cdir)["blocks"]) == ("ALLOW_BLOCKED", 0)
    (cdir / "BLOCKED.md").unlink()
    assert _blocks(call(project))
    assert _state(cdir)["blocks"] == 1


@pytest.mark.parametrize("text", [
    "class: EXTERNAL\nattempts: 3\n",
    "# BLOCKED\n\nCLASS: MISSING-INFO\n",
    "no trailing newline\nclass: PERMISSION",
])
def test_blocked_md_with_a_class_line_releases(call, project, text):
    cdir = _arm(project)
    (cdir / "BLOCKED.md").write_text(text)
    r = call(project)
    assert (r.rc, r.out, r.err) == (0, "", "")
    assert (_state(cdir)["verdict"], _state(cdir)["unchecked"]) == ("ALLOW_BLOCKED", 1)


@pytest.mark.parametrize("text", [
    "", "we are blocked, sorry\n", "  class: indented\n", "the class: is mid-line\n", "classy: no\n",
])
def test_blocked_md_without_a_class_line_does_not_release(call, project, text):
    cdir = _arm(project)
    (cdir / "BLOCKED.md").write_text(text)
    assert _blocks(call(project))


def test_all_rows_checked_releases_with_allow_done(call, project):
    cdir = _arm(project, "# PLAN\n"
                         "- [x] T1 | a | b | GATE: true | EXPECT: exit0\n"
                         "- [X] T2 | c | d | GATE: true | EXPECT: exit0\n")
    r = call(project)
    assert (r.rc, r.out, r.err) == (0, "", "")
    state = _state(cdir)
    assert (state["verdict"], state["unchecked"], state["blocks"], state["strict"]) == \
        ("ALLOW_DONE", 0, 0, 0)


def test_a_scaffolded_plan_without_task_rows_is_not_done(call, project):
    cdir = _arm(project, "# PLAN\n\n(no rows yet)\n")
    out = json.loads(call(project).out)
    assert out["decision"] == "block" and "no task rows" in out["reason"]
    assert _state(cdir)["unchecked"] == -1


def test_the_reason_names_the_first_open_row_and_counts_them(call, project):
    _arm(project, "# PLAN\n"
                  "- [x] T0 | done | a | GATE: true | EXPECT: exit0\n"
                  "- [ ] T1 | first | b | GATE: true | EXPECT: exit0\n"
                  "- [ ] T2 | second | c | GATE: true | EXPECT: exit0\n")
    reason = json.loads(call(project).out)["reason"]
    assert reason.startswith("2 unchecked gate(s) in PLAN.md. Next: - [ ] T1 | first | b")
    assert "T2 | second" not in reason


def test_the_reason_is_one_short_sanitized_line(call, project):
    long_row = '- [ ] T1 | say "hi" | out | GATE: echo "' + "x" * 600 + '" | EXPECT: exit0'
    _arm(project, "# PLAN\n" + long_row + "\n- [ ] T2 | b | c | GATE: true | EXPECT: exit0\n")
    r = call(project)
    assert len(r.out.splitlines()) == 1
    reason = json.loads(r.out)["reason"]
    assert len(reason) <= 400 and '"' not in reason and "\n" not in reason
    assert reason.startswith("2 unchecked gate(s) in PLAN.md. Next: - [ ] T1 | say 'hi'")


@pytest.mark.skipif(os.name == "nt", reason="a double quote cannot be part of a file name")
def test_a_quote_in_a_row_id_cannot_break_out_of_the_reason(call, project):
    """The id is copied from PLAN.md into the reason; whatever the plan holds, the hook's
    output stays one JSON line whose text carries no double quote."""
    cdir = _arm(project, '- [x] T"1 | a | b | GATE: true | EXPECT: exit0\n')
    art = cdir / "gates" / 'T"1.gate.json'
    art.parent.mkdir()
    art.write_text('{"exit_code": 5}\n')
    r = call(project)
    reason = json.loads(r.out)["reason"]
    assert len(r.out.splitlines()) == 1
    assert "FAILED" in reason and "T'1" in reason and '"' not in reason


def test_a_failed_gate_artifact_blocks_a_checked_row_without_strict_mode(call, project):
    cdir = _arm(project, "- [x] T1 | a | b | GATE: true | EXPECT: exit0\n")
    art = cdir / "gates" / "T1.gate.json"
    art.parent.mkdir()
    art.write_text('{"id": "T1", "exit_code": 2}\n')
    reason = json.loads(call(project).out)["reason"]
    assert "T1" in reason and "FAILED" in reason and "exit_code=2" in reason
    art.write_text('{\n  "id": "T1",\n  "exit_code": 0\n}\n')
    assert call(project).out == ""


# --------------------------------------------------------------------- strict mode ------

def test_strict_mode_reruns_checked_gates_and_blocks_on_a_regression(call, project):
    cdir = _arm(project, "- [x] T1 | a | b | GATE: false | EXPECT: exit0\n")
    assert call(project).out == ""                               # default: a checked box is trusted
    r = call(project, RUN_GATES="1")
    out = json.loads(r.out)
    assert out["decision"] == "block"
    assert "Regression" in out["reason"] and "T1" in out["reason"]
    assert (_state(cdir)["verdict"], _state(cdir)["strict"]) == ("BLOCK", 1)


@pytest.mark.parametrize("row, expected", [
    ("- [x] T1 | a | b | GATE: true | EXPECT: exit0", None),
    ("- [x] T1 | a | b | GATE: echo hello world | EXPECT: hello", None),
    ("- [x] T1 | a | b | GATE: echo hello world | EXPECT: zzz", "Regression"),   # exit 0, no match
    ("- [x] T1 | a | b | GATE: true | EXPECT: something", "Regression"),         # no output at all
    ("- [x] T1 | a | b | GATE: echo ok; exit 3 | EXPECT: ok", "Regression"),     # matched, exit 3
    ("- [x] T1 | a | b | no gate or expectation here", "Malformed checked row"),
])
def test_strict_gate_verdicts(call, project, row, expected):
    cdir = _arm(project, row + "\n")
    r = call(project, RUN_GATES="1")
    if expected is None:
        assert (r.out, _state(cdir)["verdict"]) == ("", "ALLOW_DONE")
    else:
        assert expected in json.loads(r.out)["reason"]


def test_strict_gates_run_in_the_project_root(call, project, elsewhere):
    (project / "marker.txt").write_text("x")
    cdir = _arm(project, "- [x] T1 | a | b | GATE: test -f marker.txt | EXPECT: exit0\n")
    r = call(elsewhere, {"cwd": str(project)}, RUN_GATES="1")
    assert r.out == "" and _state(cdir)["verdict"] == "ALLOW_DONE"


def test_a_strict_gate_over_its_timeout_is_killed_and_reported_as_exit_124(call, project):
    _arm(project, "- [x] T1 | slow | b | GATE: sleep 30 | EXPECT: exit0\n")
    started = time.monotonic()
    r = call(project, RUN_GATES="1", GATE_TIMEOUT="0.5")
    assert time.monotonic() - started < 20                       # killed, not waited out
    reason = json.loads(r.out)["reason"]
    assert "Regression" in reason and "exit 124" in reason


# -------------------------------------------------------------- STATE.json contract ------

def test_state_json_is_what_the_monitor_reads(call, project):
    cdir = _arm(project)
    call(project)
    status = C.read_status(str(cdir))
    assert (status["verdict"], status["unchecked"], status["strict"], status["blocks"]) == \
        ("BLOCK", 1, 0, 1)


def test_an_unwritable_state_file_never_changes_the_verdict(call, project):
    cdir = _arm(project)
    (cdir / "STATE.json").mkdir()                                # a file cannot replace this
    r = call(project)
    assert r.rc == 0 and _blocks(r)
    assert sorted(p.name for p in cdir.iterdir()) == ["PLAN.md", "STATE.json"]   # no stray .tmp


@pytest.mark.parametrize("old", [
    "{not json",
    "[]",
    '{"ts": "x", "unchecked": 1, "verdict": "BLOCK", "strict": 0}',   # the pre-cap format
    '{"verdict": "BLOCK", "blocks": "many", "fingerprint": "zz"}',
])
def test_a_corrupt_or_legacy_state_file_starts_a_fresh_window(call, project, old):
    cdir = _arm(project)
    (cdir / "STATE.json").write_text(old)
    assert _blocks(call(project))
    assert _state(cdir)["blocks"] == 1


# --------------------------------------------------------- wiring and dispatch pins ------

def test_task_row_pattern_is_pinned_to_the_control_parser():
    """The gatekeeper duplicates control's row pattern so a hook never fails on a heavier
    import; this is what keeps the two from drifting apart."""
    assert G._TASK_ROW.pattern == C._ID_GREP


def test_dedupe_never_holds_a_gatekeeper_stop_back(tmp_path, monkeypatch):
    """Every Stop after a turn's first block carries the same session and
    `stop_hook_active: true`, so identical payloads inside the window are real Stops."""
    monkeypatch.setattr(dedupe, "_claims_dir", lambda: str(tmp_path / "claims"))
    raw = json.dumps({"session_id": "s", "stop_hook_active": True})
    assert [dedupe.claim("gatekeeper", [], raw) for _ in range(3)] == [True, True, True]
    assert not os.path.exists(str(tmp_path / "claims"))          # not even bookkept
    assert [dedupe.claim("lift", [], raw) for _ in range(2)] == [True, False]  # others still are
    assert dedupe.emits_json("gatekeeper", []) is False          # so never a `{}` duplicate


@both_entry_points
def test_back_to_back_identical_stops_are_both_blocked(entry, project):
    """The regression: with dedupe keyed on the payload, the second of two identical Stops
    printed `{}` and the session stopped with T1 still open."""
    cdir = _arm(project)
    payload = json.dumps({"session_id": "s", "stop_hook_active": True, "cwd": str(project)})
    for _ in range(2):
        r = _spawn(entry, project, payload)
        assert json.loads(r.stdout)["decision"] == "block", r.stdout
    assert _state(cdir)["blocks"] == 1                           # inside _TWIN_S: not counted


def test_a_doubly_registered_stop_blocks_twice_and_counts_once(project):
    """Plugin + `plateau init --global` both registered: the same Stop reaches the gatekeeper
    twice, both copies block, and the stall cap counts it once."""
    cdir = _arm(project)
    for n in (1, 2):
        if n == 2:
            _age(cdir)                                           # the next Stop event
        for entry in ("hook.py", "plateau-hook"):
            r = _spawn(entry, project, GATEKEEPER_MAX_BLOCKS="5")
            assert json.loads(r.stdout)["decision"] == "block", (n, entry)
        assert _state(cdir)["blocks"] == n


def test_a_doubly_registered_stall_release_releases_both_copies(project):
    """The copy that runs second must not re-block the Stop the first one released, or
    the cap could never release a doubly registered hook."""
    cdir = _arm(project)
    for entry in ("hook.py", "plateau-hook"):
        assert json.loads(_spawn(entry, project, GATEKEEPER_MAX_BLOCKS="1").stdout)
    _age(cdir)
    first = _spawn("hook.py", project, GATEKEEPER_MAX_BLOCKS="1")
    second = _spawn("plateau-hook", project, GATEKEEPER_MAX_BLOCKS="1")
    assert (first.stdout, second.stdout) == ("", "")
    assert "GATEKEEPER_MAX_BLOCKS=1" in first.stderr
    assert (_state(cdir)["verdict"], _state(cdir)["blocks"]) == ("ALLOW_STALLED", 0)


def test_a_twin_needs_the_same_files(call, project, monkeypatch):
    """Progress between two quick Stops is a new Stop, never a twin of the last one."""
    cdir = _arm(project)
    assert _blocks(call(project, GATEKEEPER_MAX_BLOCKS=1))
    assert not _blocks(call(project, GATEKEEPER_MAX_BLOCKS=1))     # stalled: released
    monkeypatch.setattr(G, "_TWIN_S", 3600.0)                      # every Stop is "quick" now
    (cdir / "JOURNAL.md").write_text("progress\n")
    assert _blocks(call(project, GATEKEEPER_MAX_BLOCKS=1))         # new files: blocked again
    assert (_state(cdir)["verdict"], _state(cdir)["blocks"]) == ("BLOCK", 1)


def _stop_hooks(events):
    return [(hook["command"], hook.get("timeout"))
            for group in events["Stop"] for hook in group["hooks"]]


def test_gatekeeper_is_registered_last_on_stop_by_the_plugin_and_by_init():
    with open(HOOKS_JSON, encoding="utf-8") as fh:
        plugin = _stop_hooks(json.load(fh)["hooks"])
    init = _stop_hooks(install.hook_table())
    assert plugin[-1] == ("python3 ${CLAUDE_PLUGIN_ROOT}/hook.py gatekeeper --cc", 150)
    assert init[-1][0].split()[-1] == "gatekeeper" and init[-1][1] == 150
    for table in (plugin, init):
        assert sum("gatekeeper" in command for command, _ in table) == 1


def test_both_dispatchers_route_gatekeeper_to_the_same_module():
    spec = importlib.util.spec_from_file_location("plateau_cc_hook_under_test", HOOK_PY)
    hook_py = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(hook_py)
    assert hook_py.MODULE_MODES["gatekeeper"] == "plateau.agency.gatekeeper"
    assert "gatekeeper" in hook_py.ALL_MODES
    assert cli._HOOK_MODULES["gatekeeper"] == "plateau.agency.gatekeeper"


@pytest.mark.skipif(not shutil.which("bash"), reason="bash required")
def test_the_shim_is_executable_and_runs_the_same_module(project, elsewhere):
    assert os.access(SHIM, os.X_OK)
    _arm(project)
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)                                  # the shim finds the repo itself

    def shim(cwd, *args):
        return subprocess.run(["bash", SHIM, *args], cwd=str(cwd), input="{}",
                              capture_output=True, text=True, env=env, timeout=60)

    armed = shim(project, "--cc", "ignored")
    assert armed.returncode == 0, armed.stderr
    assert armed.stdout != "" and armed.stdout == _spawn("hook.py", project).stdout
    assert shim(elsewhere).stdout == ""


# ------------------------------------------------ `python3 -m plateau.hooks.signal` ------
# The orchestrate command and reinstate.md call the signal hooks this way, so it must work
# from a plugin-only install as well as from a checkout.

def _signal(args, cwd):
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(p for p in (ROOT, os.environ.get("PYTHONPATH")) if p)
    return subprocess.run([sys.executable, "-m", "plateau.hooks.signal", *args], cwd=str(cwd),
                          input="", capture_output=True, text=True, env=env, timeout=60)


def test_signal_module_runs_as_main(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    r = _signal(["pre"], work)
    assert r.returncode == 0, r.stderr
    assert "carried_self_state" in json.loads(r.stdout)
    assert not (work / ".plateau").exists()


@pytest.mark.parametrize("args", [["bogus"], []])
def test_signal_module_rejects_an_unknown_or_missing_mode(tmp_path, args):
    r = _signal(args, tmp_path)
    assert r.returncode == 2 and r.stdout == ""
    assert "usage" in r.stderr.lower()
