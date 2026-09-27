"""tests/test_duplicate_hooks.py — the double-registration bug (see
`plateau.bridge.dedupe`'s module docstring): Plateau's hooks registered both by the
Claude Code plugin and by `plateau init --global` fire every event twice, within a
handful of milliseconds, with an identical stdin payload.

Covers: `plateau.bridge.dedupe.claim()` in isolation; the two race sites in
`plateau.bridge.common` (`mark_compaction`, `mark_turn`, `record_reason`) made safe on
their own; `plateau.doctor`'s "hooks registered once" check and `plateau init
--global`'s post-install warning; and one end-to-end run of BOTH dispatch entry points
(`adapters/claude_code/hook.py` and `plateau hook`) against the same payload, to prove
the whole chain actually collapses a real duplicate.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from typing import Dict, Iterable

import pytest

from plateau import doctor
from plateau.bridge import common
from plateau.bridge import config as bridge_config
from plateau.bridge import dedupe
from plateau.lab import holdout

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ADAPTER_DIR = os.path.join(REPO_ROOT, "adapters", "claude_code")
HOOK_PY = os.path.join(ADAPTER_DIR, "hook.py")


def _write_json(path: str, data: Dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)


# ---------------------------------------------------------------------------
# dedupe.claim()
# ---------------------------------------------------------------------------

@pytest.fixture
def claims_dir(tmp_path, monkeypatch):
    """Point `dedupe._claims_dir()` at an empty tmp dir, isolated from both the real
    machine tmp (other tests, other runs) and from `PLATEAU_NO_DEDUPE` leaking in from
    the ambient environment."""
    d = tmp_path / "claims"
    monkeypatch.setattr(dedupe, "_claims_dir", lambda: str(d))
    monkeypatch.delenv("PLATEAU_NO_DEDUPE", raising=False)
    return d


def test_first_claim_wins(claims_dir):
    assert dedupe.claim("inject", [], "{}") is True


def test_immediate_identical_second_is_a_duplicate(claims_dir):
    assert dedupe.claim("inject", [], "{}") is True
    assert dedupe.claim("inject", [], "{}") is False


def test_different_payload_is_not_a_duplicate(claims_dir):
    assert dedupe.claim("inject", [], "{}") is True
    assert dedupe.claim("inject", [], '{"session_id": "other"}') is True


def test_different_mode_is_not_a_duplicate(claims_dir):
    assert dedupe.claim("inject", [], "{}") is True
    assert dedupe.claim("receipt", [], "{}") is True


def test_different_argv_is_not_a_duplicate(claims_dir):
    assert dedupe.claim("lift", [], "{}") is True
    assert dedupe.claim("lift", ["--agent", "subagent"], "{}") is True


def test_cc_flag_difference_is_ignored(claims_dir):
    # `adapters/claude_code/hook.py inject --cc` vs `plateau hook inject` (no literal
    # `--cc` at all): the same real invocation, just spelled differently by the two
    # dispatch entry points -- must collide.
    assert dedupe.claim("inject", ["--cc"], "{}") is True
    assert dedupe.claim("inject", [], "{}") is False


def test_claim_after_the_window_elapses_is_not_a_duplicate(claims_dir):
    assert dedupe.claim("inject", [], "{}") is True
    path = claims_dir / dedupe._key("inject", [], "{}")
    old = time.time() - 10.0
    os.utime(str(path), (old, old))
    assert dedupe.claim("inject", [], "{}", window_s=2.0) is True


def test_no_dedupe_env_always_claims(claims_dir, monkeypatch):
    monkeypatch.setenv("PLATEAU_NO_DEDUPE", "1")
    assert dedupe.claim("inject", [], "{}") is True
    assert dedupe.claim("inject", [], "{}") is True  # still True -- dedupe is off


def test_unwritable_claims_dir_fails_open(tmp_path, monkeypatch):
    # `_claims_dir()` resolves to a path THROUGH a plain file, so `os.makedirs` raises
    # NotADirectoryError (an OSError) -- claim() must still return True (fail open).
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory")
    monkeypatch.setattr(dedupe, "_claims_dir", lambda: str(blocker / "claims"))
    monkeypatch.delenv("PLATEAU_NO_DEDUPE", raising=False)
    assert dedupe.claim("inject", [], "{}") is True
    assert dedupe.claim("inject", [], "{}") is True


# ---------------------------------------------------------------------------
# common.mark_compaction / mark_turn / record_reason: the race sites made safe
# ---------------------------------------------------------------------------

@pytest.fixture
def store_root(tmp_path):
    root = str(tmp_path / "proj")
    os.makedirs(root, exist_ok=True)
    return root


def test_mark_compaction_back_to_back_returns_the_same_k_and_leaves_one_row(store_root):
    conn = common.db(store_root)
    k1 = common.mark_compaction(conn, "s1", "snap1.sqlite")
    k2 = common.mark_compaction(conn, "s1", "snap2.sqlite")
    assert k1 == 0 and k2 == 0
    rows = conn.execute(
        "SELECT COUNT(*) FROM compactions WHERE session_id=?", ("s1",)
    ).fetchone()[0]
    assert rows == 1
    conn.close()


def test_mark_compaction_after_5s_inserts_k_plus_1(store_root):
    conn = common.db(store_root)
    k1 = common.mark_compaction(conn, "s1", "snap1.sqlite")
    # Fake the row as more than 5s old: two REAL compactions this far apart both count.
    conn.execute("UPDATE compactions SET ts = ts - 10 WHERE session_id=? AND k=?", ("s1", k1))
    conn.commit()
    k2 = common.mark_compaction(conn, "s1", "snap2.sqlite")
    assert k2 == k1 + 1
    rows = conn.execute(
        "SELECT COUNT(*) FROM compactions WHERE session_id=?", ("s1",)
    ).fetchone()[0]
    assert rows == 2
    conn.close()


def _run_concurrently(fns: Iterable) -> list:
    """Run each zero-arg callable on its own thread; return the exceptions it raised
    (empty list means none did)."""
    errors: list = []
    lock = threading.Lock()

    def wrap(fn):
        try:
            fn()
        except Exception as exc:  # noqa: BLE001 -- we want every kind, to assert none
            with lock:
                errors.append(exc)

    threads = [threading.Thread(target=wrap, args=(fn,)) for fn in fns]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return errors


def test_mark_turn_concurrent_callers_never_raise_integrity_error(store_root):
    common.db(store_root).close()  # create the schema up front

    def one_turn():
        conn = common.db(store_root)
        try:
            common.mark_turn(conn, "s1")
        finally:
            conn.close()

    errors = _run_concurrently([one_turn] * 8)
    assert not errors, errors

    conn = common.db(store_root)
    ns = [row[0] for row in conn.execute(
        "SELECT n FROM turns WHERE session_id=? ORDER BY n", ("s1",)
    ).fetchall()]
    conn.close()
    assert ns == list(range(1, 9))  # every n is distinct and contiguous -- no lost update


def test_record_reason_concurrent_duplicate_does_not_raise(store_root):
    conn = common.db(store_root)
    rid = common.record(
        conn, "Bash", {"command": "pytest -q"}, {"exitCode": 1, "output": "FAILED tests/x.py"},
        session_id="s1", agent="main", bridge_version="v", bridge_sha="sha", root=store_root,
    )
    conn.close()

    def one_reason():
        conn = common.db(store_root)
        try:
            common.record_reason(conn, rid, "s1", "tu1", "the FAILED tests/x.py points here")
        finally:
            conn.close()

    errors = _run_concurrently([one_reason] * 6)
    assert not errors, errors

    conn = common.db(store_root)
    count = conn.execute("SELECT COUNT(*) FROM reasons WHERE rid=?", (rid,)).fetchone()[0]
    conn.close()
    assert count == 1


# ---------------------------------------------------------------------------
# plateau.doctor: "hooks registered once"
# ---------------------------------------------------------------------------

def _install_plugin(home: str, version: str = "9.9.9") -> None:
    _write_json(
        os.path.join(home, ".claude", "plugins", "installed_plugins.json"),
        {"plugins": {"plateau@plateau": [{"version": version}]}},
    )


def test_hooks_registered_once_passes_with_only_the_plugin(tmp_path, monkeypatch):
    home, project = tmp_path / "home", tmp_path / "project"
    home.mkdir()
    project.mkdir()
    monkeypatch.setenv("HOME", str(home))
    _install_plugin(str(home))

    status, _label, detail = doctor._check_hooks_registered_once(str(project))
    assert status == "PASS", detail


def test_hooks_registered_once_fails_for_plugin_plus_global_settings(tmp_path, monkeypatch):
    home, project = tmp_path / "home", tmp_path / "project"
    home.mkdir()
    project.mkdir()
    monkeypatch.setenv("HOME", str(home))
    _install_plugin(str(home))
    _write_json(
        os.path.join(str(home), ".claude", "settings.json"),
        {"hooks": {"Stop": [{"hooks": [
            {"type": "command", "command": "plateau hook post", "timeout": 15},
        ]}]}},
    )

    status, _label, detail = doctor._check_hooks_registered_once(str(project))
    assert status == "FAIL", detail
    assert "plugin" in detail


def test_hooks_registered_once_fails_for_plugin_plus_project_settings(tmp_path, monkeypatch):
    home, project = tmp_path / "home", tmp_path / "project"
    home.mkdir()
    project.mkdir()
    monkeypatch.setenv("HOME", str(home))
    _install_plugin(str(home))
    _write_json(
        os.path.join(str(project), ".claude", "settings.local.json"),
        {"hooks": {"Stop": [{"hooks": [
            {"type": "command", "command": "python3 -m plateau.cli hook post", "timeout": 15},
        ]}]}},
    )

    status, _label, detail = doctor._check_hooks_registered_once(str(project))
    assert status == "FAIL", detail


def test_hooks_registered_once_ignores_a_disabled_plugin(tmp_path, monkeypatch):
    home, project = tmp_path / "home", tmp_path / "project"
    home.mkdir()
    project.mkdir()
    monkeypatch.setenv("HOME", str(home))
    _install_plugin(str(home))
    _write_json(
        os.path.join(str(home), ".claude", "settings.json"),
        {
            "enabledPlugins": {"plateau@plateau": False},
            "hooks": {"Stop": [{"hooks": [
                {"type": "command", "command": "plateau hook post", "timeout": 15},
            ]}]},
        },
    )

    # the plugin is explicitly disabled -> only the global settings.json place is left
    status, _label, detail = doctor._check_hooks_registered_once(str(project))
    assert status == "PASS", detail


# ---------------------------------------------------------------------------
# `plateau init --global`: warns when the plugin is also installed+enabled
# ---------------------------------------------------------------------------

def test_init_global_warns_when_the_plugin_is_also_installed(tmp_path, monkeypatch, capsys):
    home, project = tmp_path / "home", tmp_path / "project"
    home.mkdir()
    project.mkdir()
    monkeypatch.setenv("HOME", str(home))
    _install_plugin(str(home))
    monkeypatch.chdir(str(project))

    from plateau import cli

    rc = cli.main(["init", "--global"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "WARNING" in out
    assert "registered" in out


def test_init_global_is_quiet_without_the_plugin(tmp_path, monkeypatch, capsys):
    home, project = tmp_path / "home", tmp_path / "project"
    home.mkdir()
    project.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(str(project))

    from plateau import cli

    rc = cli.main(["init", "--global"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "WARNING" not in out


# ---------------------------------------------------------------------------
# end to end: both dispatch entry points against the exact same payload
# ---------------------------------------------------------------------------

def _rate(root: str) -> float:
    return float(bridge_config.load(root, "lab-probe").lab.get("holdout_rate", 0.10))


def _non_holdout_session_id(root: str, k: int, prefix: str = "dup") -> str:
    rate = _rate(root)
    for i in range(1000):
        candidate = f"{prefix}-{i}"
        if not holdout.is_holdout(candidate, k, rate):
            return candidate
    raise AssertionError("could not find a non-holdout session id")


def _subprocess_env(home: str, tmp_for_claims: str) -> Dict[str, str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = REPO_ROOT + os.pathsep + env.get("PYTHONPATH", "")
    env["HOME"] = home
    env["TMPDIR"] = tmp_for_claims  # isolate plateau.bridge.dedupe's claims dir
    for k in ("PLATEAU_LEGACY_TAG", "PLATEAU_DB_REL", "PLATEAU_LOG_REL", "PLATEAU_AGENT",
              "PLATEAU_RESUME_FROM", "PLATEAU_NO_DEDUPE"):
        env.pop(k, None)
    return env


def test_end_to_end_both_dispatch_entry_points_collapse_the_duplicate(tmp_path, monkeypatch):
    """The exact bug: the plugin's `hook.py inject --cc` and `plateau init --global`'s
    `plateau hook inject` both fire for the same real SessionStart(compact) event, with
    the same stdin. Exactly one must emit the real `additionalContext`; the other must
    emit `{}`; the log must show exactly one `inject ev=` line and one `dup` line."""
    root = str(tmp_path / "proj")
    os.makedirs(root, exist_ok=True)
    subprocess.run(["git", "init", "-q", root], capture_output=True, text=True, timeout=10)
    home = tmp_path / "home"
    home.mkdir()
    tmp_for_claims = tmp_path / "tmp"
    tmp_for_claims.mkdir()
    monkeypatch.setenv("HOME", str(home))  # this process's own config/holdout reads

    session_id = _non_holdout_session_id(root, 0)
    conn = common.db(root)
    common.record(
        conn, "Bash", {"command": "pytest -q"}, {"exitCode": 0, "output": "1 passed"},
        session_id=session_id, agent="main", bridge_version="v", bridge_sha="sha", root=root,
    )
    common.mark_turn(conn, session_id)
    conn.close()

    transcript = tmp_path / "t.jsonl"
    transcript.write_text(json.dumps({"message": {"role": "user", "content": "what next?"}}) + "\n")
    payload = json.dumps({
        "cwd": root, "session_id": session_id, "transcript_path": str(transcript),
        "hook_event_name": "SessionStart", "source": "compact",
    })

    env = _subprocess_env(str(home), str(tmp_for_claims))

    r1 = subprocess.run(
        [sys.executable, HOOK_PY, "inject", "--cc"], cwd=root, input=payload,
        capture_output=True, text=True, env=env, timeout=30,
    )
    r2 = subprocess.run(
        [sys.executable, "-m", "plateau.cli", "hook", "inject"], cwd=root, input=payload,
        capture_output=True, text=True, env=env, timeout=30,
    )

    assert r1.returncode == 0, r1.stderr
    assert r2.returncode == 0, r2.stderr
    out1 = json.loads(r1.stdout)
    out2 = json.loads(r2.stdout)

    outs = [out1, out2]
    real = [o for o in outs if o != {}]
    dups = [o for o in outs if o == {}]
    assert len(real) == 1, outs
    assert len(dups) == 1, outs
    assert "additionalContext" in real[0]["hookSpecificOutput"]

    log_path = os.path.join(root, ".plateau", "hooks.log")
    with open(log_path, encoding="utf-8") as f:
        lines = f.read().splitlines()
    inject_lines = [ln for ln in lines if " inject ev=" in ln]
    dup_lines = [ln for ln in lines if " dup " in ln]
    assert len(inject_lines) == 1, lines
    assert len(dup_lines) == 1, lines
