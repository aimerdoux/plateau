"""tests/test_reason.py — 0.4 section 1: the `because` arrow (docs/toy/continuum-toy.html).

Covers `plateau.bridge.lift.reasons_from_transcript` (pairing a tool call with the
assistant text that preceded it, in Claude Code's one-block-per-line transcript shape),
`plateau.bridge.common.record_reason` (the reason row plus its `because` edges to earlier
knowledge nodes), the `tool_use_id` receipt column, and the Stop-path end to end.
"""

from __future__ import annotations

import io
import json
import os
import sqlite3
import sys

from plateau.bridge import common, lift


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _write_lines(path, entries) -> None:
    """entries: list of (message_id, blocks) written one block per line, sharing
    `message.id` -- the shape Claude Code 2.1.x actually writes."""
    with open(path, "w", encoding="utf-8") as f:
        for mid, blocks in entries:
            for block in blocks:
                f.write(json.dumps({"type": "assistant", "uuid": "u",
                                    "message": {"id": mid, "role": "assistant", "content": [block]}}) + "\n")


def _text(s):
    return {"type": "text", "text": s}


def _thinking(s):
    return {"type": "thinking", "thinking": s}


def _use(uid, name="Read", **inp):
    return {"type": "tool_use", "id": uid, "name": name, "input": inp}


def _record(conn, root, tool, tin, resp, uid=None, session_id="s1"):
    return common.record(conn, tool, tin, resp, session_id=session_id, agent="main",
                         bridge_version="v", bridge_sha="sha", root=root, tool_use_id=uid)


def _edges(conn, rel="because"):
    return conn.execute("SELECT src, rel, dst, rid FROM edges WHERE rel=? ORDER BY rid, src", (rel,)).fetchall()


# ---------------------------------------------------------------------------
# reasons_from_transcript(): pairing text with the calls that follow it
# ---------------------------------------------------------------------------

def test_text_before_tool_use_in_same_message_is_its_reason(tmp_path):
    t = tmp_path / "t.jsonl"
    _write_lines(str(t), [
        ("m1", [_thinking("private"), _text("The timeout points at the payment client."), _use("tu1")]),
    ])
    assert lift.reasons_from_transcript(str(t)) == {"tu1": "The timeout points at the payment client."}


def test_parallel_calls_after_one_sentence_share_the_reason(tmp_path):
    t = tmp_path / "t.jsonl"
    _write_lines(str(t), [("m1", [_text("Who calls charge()?"), _use("tu1", "Grep"), _use("tu2", "Read")])])
    r = lift.reasons_from_transcript(str(t))
    assert r == {"tu1": "Who calls charge()?", "tu2": "Who calls charge()?"}


def test_text_does_not_leak_across_messages_and_thinking_is_never_a_reason(tmp_path):
    t = tmp_path / "t.jsonl"
    _write_lines(str(t), [
        ("m1", [_text("reason for the first message")]),
        ("m2", [_thinking("only raw thought here"), _use("tu2")]),
        ("m3", [_use("tu3")]),
    ])
    assert lift.reasons_from_transcript(str(t)) == {}


def test_multi_block_single_line_message_shape_is_also_read(tmp_path):
    """A whole assistant message on one line (older transcripts / other writers)."""
    t = tmp_path / "t.jsonl"
    with open(t, "w", encoding="utf-8") as f:
        f.write(json.dumps({"message": {"role": "assistant",
                                        "content": [_text("apply the decision"), _use("tu9", "Edit")]}}) + "\n")
    assert lift.reasons_from_transcript(str(t)) == {"tu9": "apply the decision"}


def test_missing_transcript_yields_empty_dict(tmp_path):
    assert lift.reasons_from_transcript(str(tmp_path / "nope.jsonl")) == {}


# ---------------------------------------------------------------------------
# record(): tool_use_id lands on the receipt; pre-0.4 stores gain the column
# ---------------------------------------------------------------------------

def test_receipt_carries_tool_use_id(tmp_path):
    conn = common.db(str(tmp_path))
    rid = _record(conn, str(tmp_path), "Bash", {"command": "ls"}, {"stdout": "x"}, uid="toolu_1")
    assert conn.execute("SELECT tool_use_id FROM receipts WHERE id=?", (rid,)).fetchone() == ("toolu_1",)


def test_pre_0_4_store_gains_tool_use_id_column_and_reasons_table(tmp_path):
    db = tmp_path / ".plateau" / "index.sqlite"
    db.parent.mkdir()
    v1 = sqlite3.connect(str(db))
    v1.execute("CREATE TABLE receipts(id INTEGER PRIMARY KEY, ts REAL, session_id TEXT, agent TEXT,"
               " bridge_version TEXT, bridge_sha TEXT, tool TEXT, target TEXT, kind TEXT, outcome TEXT,"
               " detail TEXT, measure_kind TEXT, measure_value TEXT)")
    v1.commit()
    v1.close()

    conn = common.db(str(tmp_path))
    cols = {r[1] for r in conn.execute("PRAGMA table_info(receipts)")}
    assert "tool_use_id" in cols
    assert conn.execute("SELECT name FROM sqlite_master WHERE name='reasons'").fetchone()


# ---------------------------------------------------------------------------
# record_reason(): the because edges
# ---------------------------------------------------------------------------

def test_reason_links_earlier_knowledge_by_token_overlap(tmp_path):
    root = str(tmp_path)
    conn = common.db(root)
    # r1: a test run that fails -> error node "TimeoutError in payment.charge"
    r1 = _record(conn, root, "Bash", {"command": "pytest"},
                 {"stdout": "TimeoutError in payment.charge", "exitCode": 1})
    # r2: the read taken because of it
    r2 = _record(conn, root, "Read", {"file_path": "payment/client.py"}, {"file": {"content": ""}}, uid="tu2")

    linked = common.record_reason(conn, r2, "s1", "tu2", "the timeout points at the payment client")

    assert linked == ["TimeoutError in payment.charge"]
    assert _edges(conn) == [("TimeoutError in payment.charge", "because", f"r{r2}", r2)]
    assert conn.execute("SELECT text FROM reasons WHERE rid=?", (r2,)).fetchone() == \
        ("the timeout points at the payment client",)
    assert r1 < r2


def test_reason_never_links_footprints_or_newer_nodes_or_stopwords_only(tmp_path):
    root = str(tmp_path)
    conn = common.db(root)
    r1 = _record(conn, root, "Read", {"file_path": "payment/client.py"}, {"file": {"content": ""}}, uid="tu1")
    # a decision recorded AFTER r1 (first_rid == r1 is not "< r1")
    common.record_decision(conn, "s1", "main", "payment client retries=2", "t.jsonl:1")

    # "payment client" overlaps the file node (footprint) and the decided node (newer) --
    # neither may be linked; "in the at" is stopwords only
    assert common.record_reason(conn, r1, "s1", "tu1", "read the payment client, in the at") == []
    assert _edges(conn) == []


def test_reason_is_recorded_once_per_receipt(tmp_path):
    root = str(tmp_path)
    conn = common.db(root)
    _record(conn, root, "Bash", {"command": "pytest"}, {"stdout": "KeyError idempotency_key", "exitCode": 1})
    r2 = _record(conn, root, "Read", {"file_path": "payment/refund.py"}, {"file": {"content": ""}}, uid="tu2")
    first = common.record_reason(conn, r2, "s1", "tu2", "the KeyError idempotency_key comes from refund")
    second = common.record_reason(conn, r2, "s1", "tu2", "the KeyError idempotency_key comes from refund")
    assert first and second == []
    assert len(_edges(conn)) == 1
    assert conn.execute("SELECT COUNT(*) FROM reasons").fetchone() == (1,)


def test_decision_descends_from_the_facts_it_cites(tmp_path):
    """The toy's `f1 → d1 "retries alone are not safe"`: a decision recorded at Stop
    gets because edges from the earlier knowledge it shares tokens with, never from
    itself or from a footprint."""
    root = str(tmp_path)
    conn = common.db(root)
    _record(conn, root, "Read", {"file_path": "payment/client.py"},
            {"file": {"content": "def charge(amount, retries=0, timeout=2):\n    pass\n"}}, uid="tu1")
    did = common.record_decision(conn, "s1", "main", "charge retries=2 with an idempotency key", "t.jsonl:9")

    assert _edges(conn) == [("read:payment/client.py:charge", "because", f"decided:{did}",
                             conn.execute("SELECT MAX(id) FROM receipts").fetchone()[0])]


def test_reason_keeps_the_tail_of_long_text(tmp_path):
    root = str(tmp_path)
    conn = common.db(root)
    r1 = _record(conn, root, "Bash", {"command": "ls"}, {"stdout": ""}, uid="tu1")
    long = "narration " * 100 + "the actual reason"
    common.record_reason(conn, r1, "s1", "tu1", long)
    (text,) = conn.execute("SELECT text FROM reasons WHERE rid=?", (r1,)).fetchone()
    assert text.endswith("the actual reason")
    assert len(text) <= common.REASON_CHARS + 1


# ---------------------------------------------------------------------------
# main(): Stop end to end -- receipts + transcript -> reasons + edges, idempotent
# ---------------------------------------------------------------------------

def _run_lift_main(monkeypatch, payload) -> None:
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    lift.main([])


def test_stop_lifts_reasons_for_this_sessions_receipts_and_is_idempotent(tmp_path, monkeypatch):
    root = str(tmp_path)
    conn = common.db(root)
    _record(conn, root, "Bash", {"command": "pytest"},
            {"stdout": "TimeoutError in payment.charge", "exitCode": 1}, uid="tu1")
    r2 = _record(conn, root, "Read", {"file_path": "payment/client.py"}, {"file": {"content": ""}}, uid="tu2")
    conn.close()

    transcript = tmp_path / "t.jsonl"
    _write_lines(str(transcript), [
        ("m1", [_text("run the tests"), _use("tu1", "Bash")]),
        ("m2", [_text("The timeout points at the payment client."), _use("tu2", "Read")]),
    ])
    payload = {"cwd": root, "session_id": "s1", "transcript_path": str(transcript), "hook_event_name": "Stop"}

    _run_lift_main(monkeypatch, payload)
    _run_lift_main(monkeypatch, payload)  # a second Stop over the same transcript

    conn = sqlite3.connect(os.path.join(root, common.DB_REL))
    assert conn.execute("SELECT COUNT(*) FROM reasons").fetchone() == (2,)
    assert _edges(conn) == [("TimeoutError in payment.charge", "because", f"r{r2}", r2)]


def test_stop_ignores_receipts_of_other_sessions(tmp_path, monkeypatch):
    root = str(tmp_path)
    conn = common.db(root)
    _record(conn, root, "Bash", {"command": "ls"}, {"stdout": ""}, uid="tu1", session_id="other")
    conn.close()
    transcript = tmp_path / "t.jsonl"
    _write_lines(str(transcript), [("m1", [_text("list files"), _use("tu1", "Bash")])])

    _run_lift_main(monkeypatch, {"cwd": root, "session_id": "s1", "transcript_path": str(transcript)})

    conn = sqlite3.connect(os.path.join(root, common.DB_REL))
    assert conn.execute("SELECT COUNT(*) FROM reasons").fetchone() == (0,)


# ---------------------------------------------------------------------------
# 0.4.2: parallel calls share a boundary; the subagent's Stop lifts its own transcript
# ---------------------------------------------------------------------------

def test_parallel_calls_link_against_the_store_before_the_batch(tmp_path):
    """Two calls issued from one message share one reason, written before either ran.
    The second call's reason must not descend from the FIRST call's result: before
    0.4.2 `before_rid` was each call's own rid, so r2's reason cited r1's read."""
    root = str(tmp_path)
    conn = common.db(root)
    r1 = _record(conn, root, "Read", {"file_path": "payment/client.py"},
                 {"file": {"content": "def charge(amount, retries=0):\n    pass\n"}}, uid="tu1")
    r2 = _record(conn, root, "Read", {"file_path": "payment/refund.py"}, {"file": {"content": ""}}, uid="tu2")
    transcript = tmp_path / "t.jsonl"
    _write_lines(str(transcript), [
        ("m1", [_text("look at charge retries in the payment client and the refund path"),
                _use("tu1", "Read"), _use("tu2", "Read")]),
    ])

    assert lift.lift_reasons(conn, "s1", str(transcript)) == 2
    # r1's read produced `read:payment/client.py:charge` (first_rid == r1); the batch
    # reason overlaps it ("charge", "payment", "client") but the edge is NOT drawn for r2
    assert _edges(conn) == []
    assert conn.execute("SELECT COUNT(*) FROM reasons").fetchone() == (2,)

    # a later message CAN descend from that read
    _write_lines(str(transcript), [
        ("m1", [_text("look at charge retries in the payment client and the refund path"),
                _use("tu1", "Read"), _use("tu2", "Read")]),
        ("m2", [_text("charge retries in the payment client: change the default"), _use("tu3", "Edit")]),
    ])
    r3 = _record(conn, root, "Edit", {"file_path": "payment/client.py", "old_string": "a", "new_string": "b"},
                 {"ok": True}, uid="tu3")
    assert lift.lift_reasons(conn, "s1", str(transcript)) == 1
    assert ("read:payment/client.py:charge", "because", f"r{r3}", r3) in _edges(conn)
    assert r1 < r2 < r3


def test_record_reason_never_raises_the_boundary_above_the_receipt(tmp_path):
    root = str(tmp_path)
    conn = common.db(root)
    r1 = _record(conn, root, "Read", {"file_path": "payment/client.py"},
                 {"file": {"content": "def charge():\n    pass\n"}}, uid="tu1")
    r2 = _record(conn, root, "Bash", {"command": "pytest"}, {"stdout": "", "exitCode": 0}, uid="tu2")
    # before_rid past r2 must still exclude r2's own nodes and anything newer
    linked = common.record_reason(conn, r1, "s1", "tu1", "payment client charge", before_rid=r2 + 5)
    assert linked == []


def _subagent_fixture(tmp_path):
    """A parent session with one main call and one subagent (its own transcript +
    sidecar), the shape Claude Code 2.1.27x writes."""
    root = str(tmp_path)
    conn = common.db(root)
    _record(conn, root, "Bash", {"command": "pytest"},
            {"stdout": "TimeoutError in payment.charge", "exitCode": 1}, uid="tu-main")
    r_sub = common.record(conn, "Read", {"file_path": "payment/client.py"}, {"file": {"content": ""}},
                          session_id="s1", agent="subagent:general-purpose", bridge_version="v",
                          bridge_sha="sha", root=root, tool_use_id="tu-sub")
    conn.close()
    main_t = tmp_path / "main.jsonl"
    _write_lines(str(main_t), [
        ("m1", [_text("run the tests"), _use("tu-main", "Bash")]),
        ("m2", [_text("DECISION: the parent decides nothing yet")]),
    ])
    sub_dir = tmp_path / "subagents"
    sub_dir.mkdir()
    sub_t = sub_dir / "agent-abc.jsonl"
    _write_lines(str(sub_t), [
        ("sm1", [_text("The timeout points at the payment client."), _use("tu-sub", "Read")]),
        ("sm2", [_text("FACT: payment.charge has no retry budget")]),
    ])
    (sub_dir / "agent-abc.meta.json").write_text(json.dumps({"agentType": "general-purpose"}), encoding="utf-8")
    return root, r_sub, main_t, sub_t


def test_subagentstop_lifts_the_subagents_reasons_and_decisions_from_its_own_transcript(tmp_path, monkeypatch):
    root, r_sub, main_t, sub_t = _subagent_fixture(tmp_path)
    payload = {"cwd": root, "session_id": "s1", "hook_event_name": "SubagentStop",
               "transcript_path": str(main_t), "agent_transcript_path": str(sub_t),
               "agent_id": "abc", "agent_type": ""}
    _run_lift_main(monkeypatch, payload)
    _run_lift_main(monkeypatch, payload)  # idempotent

    conn = sqlite3.connect(os.path.join(root, common.DB_REL))
    assert conn.execute("SELECT rid, tool_use_id FROM reasons").fetchall() == [(r_sub, "tu-sub")]
    # the subagent's read descends from the parent's error, and so does its FACT
    assert sorted(_edges(conn)) == [
        ("TimeoutError in payment.charge", "because", "decided:1", r_sub),
        ("TimeoutError in payment.charge", "because", f"r{r_sub}", r_sub),
    ]
    assert conn.execute("SELECT agent, text, provenance FROM decisions").fetchall() == [
        ("subagent:general-purpose", "payment.charge has no retry budget", "agent-abc.jsonl:3"),
    ]
    # the parent's transcript was NOT read under the subagent's name, and no turn was marked
    assert conn.execute("SELECT COUNT(*) FROM turns").fetchone() == (0,)


def test_subagentstop_without_a_readable_transcript_lifts_nothing_and_says_so(tmp_path, monkeypatch):
    root, _r_sub, main_t, sub_t = _subagent_fixture(tmp_path)
    os.remove(sub_t)
    payload = {"cwd": root, "session_id": "s1", "hook_event_name": "SubagentStop",
               "transcript_path": str(main_t), "agent_transcript_path": str(sub_t),
               "agent_id": "abc", "agent_type": "general-purpose"}
    _run_lift_main(monkeypatch, payload)
    conn = sqlite3.connect(os.path.join(root, common.DB_REL))
    assert conn.execute("SELECT COUNT(*) FROM reasons").fetchone() == (0,)
    assert conn.execute("SELECT COUNT(*) FROM decisions").fetchone() == (0,)
    with open(os.path.join(root, ".plateau", "hooks.log"), encoding="utf-8") as f:
        assert "lift subagent skip: agent_transcript_path=missing agent=subagent:general-purpose agent_id=abc" in f.read()


def test_agent_flag_alone_keeps_a_typeless_subagent_off_the_main_turn(tmp_path, monkeypatch):
    """`hooks.json` passes `--agent subagent` at SubagentStop; a payload with no type and
    no sidecar is still lifted from its transcript as a subagent, never as a main Stop."""
    root, r_sub, main_t, sub_t = _subagent_fixture(tmp_path)
    os.remove(os.path.join(root, "subagents", "agent-abc.meta.json"))
    payload = {"cwd": root, "session_id": "s1", "transcript_path": str(main_t),
               "agent_transcript_path": str(sub_t), "agent_id": "abc"}
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    lift.main(["--agent", "subagent"])
    conn = sqlite3.connect(os.path.join(root, common.DB_REL))
    assert conn.execute("SELECT agent FROM decisions").fetchall() == [("subagent:abc",)]
    assert conn.execute("SELECT rid FROM reasons").fetchall() == [(r_sub,)]
    assert conn.execute("SELECT COUNT(*) FROM turns").fetchone() == (0,)


def test_main_stop_still_marks_the_turn_and_reads_the_parent_transcript(tmp_path, monkeypatch):
    root, _r_sub, main_t, _sub_t = _subagent_fixture(tmp_path)
    _run_lift_main(monkeypatch, {"cwd": root, "session_id": "s1", "hook_event_name": "Stop",
                                 "transcript_path": str(main_t)})
    conn = sqlite3.connect(os.path.join(root, common.DB_REL))
    assert conn.execute("SELECT COUNT(*) FROM turns").fetchone() == (1,)
    assert conn.execute("SELECT agent, text FROM decisions").fetchall() == [("main", "the parent decides nothing yet")]
    assert conn.execute("SELECT tool_use_id FROM reasons").fetchall() == [("tu-main",)]
