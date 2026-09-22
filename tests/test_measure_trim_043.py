"""0.4.3: trim what the models never used, and stop littering stores.

Measured on the operator machine 2026-09-22 (39 transcripts, 17,661 tool calls): no
injected receipt id was ever cited back, one research session's gated facts rode 1,127
prompts of unrelated work, ~215 `.plateau/` stores existed of which 12 held a receipt,
and the startup index was headed "from earlier in this session" while every line in it
came from other sessions. These tests pin the four fixes.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
import types

import pytest

from plateau.bridge import common, query as query_mod
from plateau.hooks import signal as hooks_signal

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SIG = {"schema": "continuum.signal.v1", "open_goals": [], "stance": "",
        "lessons": [], "pointers": [], "verified_facts": []}


def _pre(tmp_path, monkeypatch, capsys, payload):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    hooks_signal.main("pre", ["--cc"])
    return json.loads(capsys.readouterr().out)


def _grounded_fact(tmp_path, name, claim):
    (tmp_path / name).write_text(claim)
    digest = "sha256:" + hashlib.sha256(claim.encode()).hexdigest()
    return {"claim": claim, "grounding": {"kind": "file_hash", "source": name, "value": digest}}


def test_pre_carries_only_the_facts_relevant_to_the_prompt(tmp_path, monkeypatch, capsys):
    pd = tmp_path / ".plateau"
    pd.mkdir()
    facts = [_grounded_fact(tmp_path, "a.txt", "calibration miners failed held label adjudication"),
             _grounded_fact(tmp_path, "b.txt", "checkout sheet renders deposit option for yachts")]
    (pd / "signal.json").write_text(json.dumps(dict(_SIG, verified_facts=facts)))

    out = _pre(tmp_path, monkeypatch, capsys, {"prompt": "why does the checkout sheet hide the deposit?"})
    ctx = out["hookSpecificOutput"]["additionalContext"]
    assert "checkout sheet renders deposit" in ctx
    assert "calibration miners" not in ctx


def test_pre_injects_nothing_when_no_fact_is_relevant_and_nothing_else_rides(tmp_path, monkeypatch, capsys):
    pd = tmp_path / ".plateau"
    pd.mkdir()
    fact = _grounded_fact(tmp_path, "a.txt", "calibration miners failed held label adjudication")
    (pd / "signal.json").write_text(json.dumps(dict(_SIG, verified_facts=[fact])))

    out = _pre(tmp_path, monkeypatch, capsys, {"prompt": "please make all the relevant adjustments"})
    assert out == {"suppressOutput": True}


def test_pre_keeps_goals_whatever_the_prompt(tmp_path, monkeypatch, capsys):
    pd = tmp_path / ".plateau"
    pd.mkdir()
    (pd / "signal.json").write_text(json.dumps(dict(_SIG, open_goals=["ship plateau plugin"])))

    out = _pre(tmp_path, monkeypatch, capsys, {"prompt": "unrelated words entirely"})
    assert "ship plateau plugin" in out["hookSpecificOutput"]["additionalContext"]


def _run_inject(root, payload):
    env = dict(os.environ)
    env["PYTHONPATH"] = REPO_ROOT + os.pathsep + env.get("PYTHONPATH", "")
    for k in ("PLATEAU_LEGACY_TAG", "PLATEAU_DB_REL", "PLATEAU_LOG_REL", "PLATEAU_AGENT", "PLATEAU_RESUME_FROM"):
        env.pop(k, None)
    proc = subprocess.run([sys.executable, "-m", "plateau.bridge.inject"], input=json.dumps(payload),
                          cwd=root, env=env, capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def _git_root():
    root = tempfile.mkdtemp(prefix="plateau-043-")
    subprocess.run(["git", "init", "-q", root], capture_output=True, text=True, timeout=10)
    return root


def test_startup_where_no_store_exists_injects_nothing_and_creates_nothing():
    root = _git_root()
    out = _run_inject(root, {"cwd": root, "session_id": "s-new", "source": "startup"})
    assert out == {}
    assert not os.path.exists(os.path.join(root, ".plateau"))


def test_startup_head_says_the_receipts_come_from_earlier_sessions():
    root = _git_root()
    conn = common.db(root)
    conn.execute("INSERT INTO receipts(id,ts,session_id,agent,tool,target,kind,outcome) "
                 "VALUES (1,1.0,'old','main','Read','src/app.py','file','read')")
    conn.execute("INSERT INTO nodes(key,kind,first_rid,last_rid,degree,last_outcome,last_detail,session_id,agent) "
                 "VALUES ('src/app.py','file',1,1,1,'read','','old','main')")
    conn.commit()
    conn.close()

    out = _run_inject(root, {"cwd": root, "session_id": "s-new", "source": "startup"})
    ctx = out["hookSpecificOutput"]["additionalContext"]
    assert "from earlier sessions in this project" in ctx
    assert "earlier in this session" not in ctx
    assert "src/app.py" in ctx


def test_a_zero_weight_kind_is_left_out_of_the_index():
    conn = common.db(tempfile.mkdtemp(prefix="plateau-043-db-"))
    for rid, (key, kind) in enumerate([("mcp__x__y", "tool"), ("src/app.py", "file")], start=1):
        conn.execute("INSERT INTO receipts(id,ts,session_id,agent,tool,target,kind,outcome) "
                     "VALUES (?,?,?,?,?,?,?,?)", (rid, float(rid), "s", "main", "T", key, kind, "ok"))
        conn.execute("INSERT INTO nodes(key,kind,first_rid,last_rid,degree,last_outcome,last_detail,session_id,agent) "
                     "VALUES (?,?,?,?,?,?,?,?,?)", (key, kind, rid, rid, 3, "ok", "", "s", "main"))
    cfg = types.SimpleNamespace(selector={
        "tau_turns": 3, "degree_cap": 3, "lexical": True,
        "weights": {"file": 0.7, "tool": 0.0},
    })
    keys = [n["key"] for n in query_mod.score_nodes(conn, "", cfg, "s")]
    assert keys == ["src/app.py"]


def test_usage_reports_both_compaction_arms_and_citations(tmp_path):
    from plateau.lab import usage

    root = _git_root()
    conn = common.db(root)
    rid = 0

    def rec(sid, tool, target):
        nonlocal rid
        rid += 1
        conn.execute("INSERT INTO receipts(id,ts,session_id,agent,tool,target,kind,outcome) "
                     "VALUES (?,?,?,?,?,?,?,?)", (rid, float(rid), sid, "main", tool, target, "file", "read"))
        return rid

    for sid, hold in (("s-inj", 0), ("s-hold", 1)):
        rec(sid, "Read", "a.py")
        at = rec(sid, "Read", "b.py")
        conn.execute("INSERT INTO injections(ts,session_id,event,compaction_k,chars,budget,holdout,keys,rid_at) "
                     "VALUES (?,?,?,?,?,?,?,?,?)",
                     (float(at), sid, "compact", 1, 0 if hold else 100, 12000, hold,
                      json.dumps([] if hold else ["a.py", "c.py"]), at))
        for _ in range(10):
            rec(sid, "Read", "a.py")
        for _ in range(10):
            rec(sid, "Read", "new.py")
    conn.commit()
    conn.close()

    projects = tmp_path / "projects" / "p"
    projects.mkdir(parents=True)
    msg = {"type": "assistant", "message": {"content": [
        {"type": "text", "text": "per [r12] the file was read"},
        {"type": "tool_use", "name": "Bash", "input": {"command": "plateau lookup a.py"}},
        {"type": "tool_use", "name": "Bash", "input": {"command": "grep -n 'plateau lookup' README.md"}},
    ]}}
    (projects / "s-inj.jsonl").write_text(json.dumps(msg) + "\n")

    r = usage.store_usage(root, projects=str(tmp_path / "projects"))
    assert r["compaction"]["inject"] == {"n": 1, "reads": 20, "reread_rate": 0.5, "touch_rate": 0.5, "enough": False}
    assert r["compaction"]["holdout"]["n"] == 1 and r["compaction"]["holdout"]["reread_rate"] == 0.5
    assert r["citations"]["rid_citations"] == 1
    assert r["citations"]["lookup_calls"] == 1


def test_doctor_flags_a_core_that_does_not_match_the_plugin(tmp_path, monkeypatch):
    from plateau import doctor, __version__
    plugins = tmp_path / ".claude" / "plugins"
    plugins.mkdir(parents=True)
    monkeypatch.setenv("HOME", str(tmp_path))
    (plugins / "installed_plugins.json").write_text(json.dumps(
        {"plugins": {"plateau@plateau": [{"version": "0.0.1"}]}}))
    assert doctor._check_core_matches_plugin()[0] == "FAIL"
    (plugins / "installed_plugins.json").write_text(json.dumps(
        {"plugins": {"plateau@plateau": [{"version": __version__}]}}))
    assert doctor._check_core_matches_plugin()[0] == "PASS"
