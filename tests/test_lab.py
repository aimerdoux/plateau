"""tests/test_lab.py — owner C5 (docs/harness-0.3/PLAN-step4.md "Tests (C5)").

Per the plan's own "Tests (C5)" line: "ledger row from a synthetic store + transcript;
re-derivation count matches D-038's definition; probe grading exact/fuzzy/wrong."
"""

from __future__ import annotations

import json
import os

import pytest

from plateau.bridge import common as bridge_common
from plateau.lab import ledger as ledger_mod
from plateau.lab import probes as probes_mod


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _write_transcript(tmp_path, lines):
    path = tmp_path / "transcript.jsonl"
    with open(path, "w", encoding="utf-8") as f:
        for line in lines:
            f.write(json.dumps(line) + "\n")
    return str(path)


def _assistant_line(msg_id, usage, tool_uses=(), model="claude-x"):
    content = [
        {"type": "tool_use", "id": "tu_" + name + "_" + msg_id, "name": name, "input": tin}
        for name, tin in tool_uses
    ]
    return {"type": "assistant", "message": {"id": msg_id, "model": model, "usage": usage, "content": content}}


def _compact_boundary():
    return {"type": "system", "subtype": "compact_boundary"}


# ---------------------------------------------------------------------------
# ledger row from a synthetic store + transcript
# ---------------------------------------------------------------------------


def test_build_row_from_synthetic_store_and_transcript(tmp_path):
    root = str(tmp_path)

    store_conn = bridge_common.db(root)
    store_conn.execute(
        "INSERT INTO receipts(ts,session_id,agent,bridge_version,bridge_sha,tool,target,"
        "kind,outcome,detail,measure_kind,measure_value) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
        (1000.0, "s1", "main", "2.0", "deadbeef", "Read", "a.py", "file", "read", "", None, None),
    )
    store_conn.execute(
        "INSERT INTO turns(session_id, n, ts, rid_at) VALUES(?,?,?,?)", ("s1", 1, 1000.0, 1),
    )
    store_conn.commit()

    lines = [
        _assistant_line("m1", {"input_tokens": 100, "output_tokens": 20},
                        [("Read", {"file_path": "a.py"})]),
        _assistant_line("m2", {"input_tokens": 50, "output_tokens": 10},
                        [("Read", {"file_path": "b.py"})]),
        _compact_boundary(),
        _assistant_line("m3", {"input_tokens": 30, "output_tokens": 5},
                        [("Read", {"file_path": "a.py"})]),  # re-derivation
    ]
    transcript_path = _write_transcript(tmp_path, lines)

    ledger_conn = ledger_mod.db(root)
    try:
        row = ledger_mod.build_row(
            root, "s1", "main", "", transcript_path,
            store_conn=store_conn, ledger_conn=ledger_conn, ended=2000.0,
        )

        assert row["session_id"] == "s1"
        assert row["agent_id"] == ""
        assert row["agent"] == "main"
        assert row["model_id"] == "claude-x"
        assert row["bridge_version"] == "2.0"
        assert row["bridge_sha"] == "deadbeef"
        assert row["receipts"] == 1
        assert row["tokens_in"] == 100 + 50 + 30
        assert row["tokens_out"] == 20 + 10 + 5
        assert row["rederivations"] == 1
        assert row["ended"] == 2000.0

        ledger_mod.upsert(ledger_conn, row)

        got = ledger_conn.execute(
            "SELECT session_id, agent_id, model_id, tokens_in, tokens_out, rederivations "
            "FROM sessions WHERE session_id=? AND agent_id=?", ("s1", ""),
        ).fetchone()
        assert got == ("s1", "", "claude-x", 180, 35, 1)

        rederiv_rows = ledger_conn.execute(
            "SELECT path FROM rederivations WHERE session_id=?", ("s1",),
        ).fetchall()
        assert rederiv_rows == [("a.py",)]
    finally:
        store_conn.close()
        ledger_conn.close()


def test_build_row_upsert_overwrites_same_session_agent_key(tmp_path):
    """`PRIMARY KEY(session_id, agent_id)` (S4-A2): re-running `build_row`/`upsert` for
    the same pair replaces the row rather than duplicating it."""
    root = str(tmp_path)
    store_conn = bridge_common.db(root)
    ledger_conn = ledger_mod.db(root)
    try:
        transcript_path = _write_transcript(tmp_path, [
            _assistant_line("m1", {"input_tokens": 10, "output_tokens": 1}),
        ])
        row1 = ledger_mod.build_row(root, "s1", "main", "", transcript_path,
                                    store_conn=store_conn, ledger_conn=ledger_conn, ended=1.0)
        ledger_mod.upsert(ledger_conn, row1)

        transcript_path2 = _write_transcript(tmp_path, [
            _assistant_line("m2", {"input_tokens": 999, "output_tokens": 1}),
        ])
        row2 = ledger_mod.build_row(root, "s1", "main", "", transcript_path2,
                                    store_conn=store_conn, ledger_conn=ledger_conn, ended=2.0)
        ledger_mod.upsert(ledger_conn, row2)

        rows = ledger_conn.execute(
            "SELECT tokens_in, ended FROM sessions WHERE session_id='s1' AND agent_id=''",
        ).fetchall()
        assert rows == [(999, 2.0)]
    finally:
        store_conn.close()
        ledger_conn.close()


# ---------------------------------------------------------------------------
# re-derivation count matches D-038's definition
# ---------------------------------------------------------------------------


def test_rederivations_matches_d038_definition():
    """`experiments/d038/score.py::turn_usage`'s definition, reimplemented in
    `ledger._rederivations` (sealed reference; PLAN-step4.md "Ledger"): a Read of a
    path already read before some compaction boundary counts as a re-derivation event
    when it recurs after that boundary with NO OTHER boundary in between; a path never
    read before any boundary never counts (however often it's read); the same path
    re-read multiple times after one boundary counts once per re-read (matching the
    sealed scorer's per-event, not per-path, tally)."""
    compaction_lines = [3, 8]
    reads = [
        (1, "a.py"),   # before boundary @3
        (2, "b.py"),   # before boundary @3
        (5, "a.py"),   # after @3, before @8 -> re-derivation of a.py w.r.t. @3
        (9, "c.py"),   # never read before any boundary -> not a re-derivation
        (9, "b.py"),   # after @3 AND @8, but @8 sits between the original read (@2)
                       # and this one -> NOT counted against @3 (another boundary in
                       # between); IS counted against @8 (b.py was read before @8, at
                       # line 2, and nothing else crosses between @8 and @9)
        (10, "b.py"),  # a second re-read after the same boundary (@8) -> counts again
    ]

    out = ledger_mod._rederivations(reads, compaction_lines)

    assert out == [(5, "a.py"), (9, "b.py"), (10, "b.py")]


def test_rederivations_none_when_nothing_recurs():
    assert ledger_mod._rederivations([(1, "a.py"), (2, "b.py")], [3]) == []
    assert ledger_mod._rederivations([(1, "a.py"), (5, "b.py")], [3]) == []  # b.py: first read after the boundary


def test_rederivations_transcript_scan_matches_direct_call(tmp_path):
    """The same definition, exercised end to end through `_read_transcript` (the
    transcript-parsing half `build_row` actually calls), not just the pure function."""
    root = str(tmp_path)
    lines = [
        _assistant_line("m1", {"input_tokens": 1, "output_tokens": 1},
                        [("Read", {"file_path": "x.py"})]),
        _compact_boundary(),
        _assistant_line("m2", {"input_tokens": 1, "output_tokens": 1},
                        [("Read", {"file_path": "y.py"})]),   # first-ever read: no rederivation
        _assistant_line("m3", {"input_tokens": 1, "output_tokens": 1},
                        [("Read", {"file_path": "x.py"})]),   # rederivation
    ]
    transcript_path = _write_transcript(tmp_path, lines)
    info = ledger_mod._read_transcript(transcript_path)
    rederivs = ledger_mod._rederivations(info["reads"], info["compaction_lines"])
    assert [path for _line, path in rederivs] == ["x.py"]


# ---------------------------------------------------------------------------
# item 9: ledger.record_cost -- the only real source of a session's total_cost_usd
# ---------------------------------------------------------------------------


def test_record_cost_updates_existing_main_row(tmp_path):
    root = str(tmp_path)
    conn = ledger_mod.db(root)
    conn.execute(
        "INSERT INTO sessions(session_id, agent_id, agent, cost_usd) VALUES(?,?,?,?)",
        ("s1", "", "main", 0.0),
    )
    conn.commit()
    conn.close()

    ledger_mod.record_cost(root, "s1", 1.775487)

    conn = ledger_mod.db(root)
    cost = conn.execute("SELECT cost_usd FROM sessions WHERE session_id=? AND agent_id=''", ("s1",)).fetchone()[0]
    conn.close()
    assert cost == pytest.approx(1.775487)


def test_record_cost_inserts_bare_row_when_session_end_has_not_run_yet(tmp_path):
    root = str(tmp_path)
    ledger_mod.record_cost(root, "s2", 0.42)

    conn = ledger_mod.db(root)
    row = conn.execute(
        "SELECT agent, agent_id, cost_usd FROM sessions WHERE session_id='s2'"
    ).fetchone()
    conn.close()
    assert row == ("main", "", pytest.approx(0.42))


def test_record_cost_never_raises_on_missing_session_id_or_cost(tmp_path):
    root = str(tmp_path)
    ledger_mod.record_cost(root, "", 1.0)       # no session_id -- no-op
    ledger_mod.record_cost(root, "s3", None)    # no cost -- no-op
    conn = ledger_mod.db(root)
    assert conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 0
    conn.close()


# ---------------------------------------------------------------------------
# probe grading: exact / fuzzy / wrong
# ---------------------------------------------------------------------------


def test_grade_exact_on_normalized_equality():
    assert probes_mod.grade("foo bar", "  Foo   Bar  ") == "exact"
    assert probes_mod.grade("42", "42") == "exact"


def test_grade_fuzzy_on_token_overlap():
    # 3 of 4 expected tokens present -> overlap 0.75 >= 0.6
    assert probes_mod.grade("alpha beta gamma delta", "alpha beta gamma zzz") == "fuzzy"


def test_grade_fuzzy_on_file_line_within_one():
    assert probes_mod.grade("src/plateau/a.py:10", "src/plateau/a.py:11") == "fuzzy"
    assert probes_mod.grade("src/plateau/a.py:10", "src/plateau/a.py:9") == "fuzzy"


def test_grade_wrong_on_low_overlap_or_wrong_file():
    assert probes_mod.grade("src/plateau/a.py:10", "totally unrelated answer here") == "wrong"
    assert probes_mod.grade("src/plateau/a.py:10", "docs/readme.md:999") == "wrong"
    assert probes_mod.grade("build passes", "it crashed with a traceback") == "wrong"


# ---------------------------------------------------------------------------
# item 7: maybe() spawns detached (never blocks the Stop hook); finalizer grades
# ---------------------------------------------------------------------------


def _tool_use_line(msg_id, tool, tin, usage=None):
    return {"type": "assistant", "message": {
        "id": msg_id, "model": "claude-x",
        "usage": usage or {"input_tokens": 100, "output_tokens": 10},
        "content": [{"type": "tool_use", "id": "tu1", "name": tool, "input": tin}],
    }}


def _tool_result_line(tool_use_id, result):
    return {
        "type": "user",
        "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": tool_use_id}]},
        "toolUseResult": result,
    }


def test_maybe_spawns_detached_finalizer_instead_of_blocking(tmp_path, monkeypatch):
    """docs/harness-0.3/PLAN-step4.md item 7: `probes.maybe()` never runs a `claude -p`
    fork itself -- it writes a spec and calls `spawn_probe` (monkeypatched here to a
    zero-spend stub), so this test spends nothing and never starts a real subprocess."""
    root = str(tmp_path)
    os.makedirs(os.path.join(root, ".plateau"), exist_ok=True)
    with open(os.path.join(root, ".plateau", "config.toml"), "w") as f:
        f.write("[lab]\nshadow_probes = true\n")

    session_id = "main-sess"
    store_conn = bridge_common.db(root)
    for n in range(1, 5):  # 4 turns -- a multiple of the default shadow_probe_every_turns=4
        store_conn.execute(
            "INSERT INTO turns(session_id, n, ts, rid_at) VALUES(?,?,?,?)", (session_id, n, float(n), n),
        )
    store_conn.commit()
    store_conn.close()

    transcript_path = _write_transcript(tmp_path, [
        _tool_use_line("m1", "Read", {"file_path": os.path.join(root, "a.py")}),
        _tool_result_line("tu1", {"file": {"filePath": os.path.join(root, "a.py"),
                                            "content": "def foo(x):\n    return x\n"}}),
    ])

    calls = []

    def fake_spawn(cmd, env, stdout_path, stderr_path):
        calls.append({"cmd": cmd, "env": env, "stdout_path": stdout_path, "stderr_path": stderr_path})
        class _FakeProc:
            pid = 999999
        return _FakeProc()

    monkeypatch.setattr(probes_mod, "spawn_probe", fake_spawn)

    from plateau.bridge import config as bridge_config
    cfg = bridge_config.load(root, session_id)
    payload = {"cwd": root, "session_id": session_id, "transcript_path": transcript_path}

    result = probes_mod.maybe(payload, cfg)

    assert result is not None and result.get("spawned") is True
    assert result["pid"] == 999999
    assert len(calls) == 1
    finalize_cmd = calls[0]["cmd"]
    assert "--run-spec" in finalize_cmd
    spec_path = finalize_cmd[finalize_cmd.index("--run-spec") + 1]
    assert os.path.isfile(spec_path)
    with open(spec_path, encoding="utf-8") as f:
        spec = json.load(f)
    assert spec["session_id"] == session_id
    assert "--fork-session" in spec["cmd"] and "--resume" in spec["cmd"]

    # no ledger row yet -- grading only happens in the (never-invoked-here) finalizer
    lconn = ledger_mod.db(root)
    try:
        assert lconn.execute("SELECT COUNT(*) FROM probes").fetchone()[0] == 0
    finally:
        lconn.close()


def test_maybe_is_noop_for_subagent_or_when_disabled(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(probes_mod, "spawn_probe", lambda *a, **k: calls.append(1))

    root = str(tmp_path)
    payload = {"cwd": root, "session_id": "s1", "transcript_path": "", "agent_type": "general-purpose"}
    assert probes_mod.maybe(payload, None) is None  # subagent -- never probed
    assert calls == []

    os.makedirs(os.path.join(root, ".plateau"), exist_ok=True)
    with open(os.path.join(root, ".plateau", "config.toml"), "w") as f:
        f.write("[lab]\nshadow_probes = false\n")
    assert probes_mod.maybe({"cwd": root, "session_id": "s1"}, None) is None  # disabled by config
    assert calls == []


def test_finalize_spec_grades_and_records_ledger_row_with_fork_session_id(tmp_path, monkeypatch):
    """The finalizer (`_finalize_spec`, run inside the detached process `spawn_probe`
    starts) grades the probe's answer and writes the `probes` ledger row itself, plus a
    status file carrying the FORK's own session id (a different session from the main
    one, since the probe ran with `--fork-session`)."""
    root = str(tmp_path)
    probes_dir = os.path.join(root, ".plateau", "probes")
    os.makedirs(probes_dir, exist_ok=True)
    status_path = os.path.join(probes_dir, "test.json")
    spec_path = os.path.join(probes_dir, "test.spec.json")
    spec = {
        "root": root, "session_id": "main-sess", "turn": 4, "cls": "read", "kind": "signature",
        "expected": "x", "lag_tokens": 12345, "compactions_crossed": 1, "q_hash": "abc123",
        "cmd": ["claude", "-p", "q", "--resume", "main-sess", "--fork-session"],
        "status_path": status_path,
    }
    with open(spec_path, "w", encoding="utf-8") as f:
        json.dump(spec, f)

    fake_envelope = json.dumps({"result": "x", "session_id": "forked-session-999", "total_cost_usd": 0.01})
    monkeypatch.setattr(probes_mod, "run_probe", lambda cmd, env: fake_envelope)

    probes_mod._finalize_spec(spec_path)

    lconn = ledger_mod.db(root)
    try:
        rows = lconn.execute(
            "SELECT session_id, turn, verdict, q_hash FROM probes"
        ).fetchall()
    finally:
        lconn.close()
    assert rows == [("main-sess", 4, "exact", "abc123")]

    assert os.path.isfile(status_path)
    with open(status_path, encoding="utf-8") as f:
        status = json.load(f)
    assert status["verdict"] == "exact"
    assert status["fork_session_id"] == "forked-session-999"
    assert status["fork_session_id"] != status["session_id"]
