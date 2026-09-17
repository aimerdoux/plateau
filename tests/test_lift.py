"""tests/test_lift.py — owner B4 (docs/harness-0.3/PLAN-step3.md "Tests (B4)",
"Decided-fact lifter").

Covers `plateau.bridge.lift`: DECISION:/FACT: lines lifted from the last assistant
message with correct provenance, exact-text dedup within a session, and non-marker
prose lines ignored.
"""

from __future__ import annotations

import io
import json
import os
import sqlite3
import sys

from plateau.bridge import common, lift


def _write_transcript(path: str, entries) -> None:
    """entries: list of (role, content) where content is a str or a list of blocks,
    matching the transcript JSONL shape `plateau.bridge.lift` reads
    (`{"message": {"role": ..., "content": ...}}` per line)."""
    with open(path, "w", encoding="utf-8") as f:
        for role, content in entries:
            f.write(json.dumps({"message": {"role": role, "content": content}}) + "\n")


def _assistant_text_blocks(*lines: str):
    return [{"type": "text", "text": "\n".join(lines)}]


# ---------------------------------------------------------------------------
# lift_decisions(): pure extraction
# ---------------------------------------------------------------------------

def test_marker_lines_lifted_and_prose_ignored(tmp_path):
    transcript = tmp_path / "t.jsonl"
    entries = [
        ("user", "hello"),
        ("assistant", _assistant_text_blocks(
            "some ordinary prose line",
            "DECISION: use sqlite WAL mode",
            "decision: lowercase must not match",
            "FACT: the API rate-limits at 60 rpm",
            "another line of prose",
        )),
    ]
    _write_transcript(str(transcript), entries)

    found = lift.lift_decisions(str(transcript))
    assert [(m, t) for m, t, _ln in found] == [
        ("DECISION", "use sqlite WAL mode"),
        ("FACT", "the API rate-limits at 60 rpm"),
    ]


def test_provenance_line_no_points_at_the_assistant_message(tmp_path):
    transcript = tmp_path / "t.jsonl"
    entries = [
        ("user", "hello"),               # line 1
        ("assistant", _assistant_text_blocks("DECISION: pick sqlite")),  # line 2
    ]
    _write_transcript(str(transcript), entries)

    found = lift.lift_decisions(str(transcript))
    assert len(found) == 1
    _marker, _text, line_no = found[0]
    assert line_no == 2


def test_only_last_assistant_message_is_considered(tmp_path):
    transcript = tmp_path / "t.jsonl"
    entries = [
        ("assistant", _assistant_text_blocks("DECISION: first one, must be ignored")),
        ("user", "ok, continue"),
        ("assistant", _assistant_text_blocks("DECISION: second one, must count")),
    ]
    _write_transcript(str(transcript), entries)

    found = lift.lift_decisions(str(transcript))
    assert [t for _m, t, _ln in found] == ["second one, must count"]


def test_no_markers_yields_empty_list(tmp_path):
    transcript = tmp_path / "t.jsonl"
    _write_transcript(str(transcript), [("assistant", _assistant_text_blocks("just prose, nothing to lift"))])
    assert lift.lift_decisions(str(transcript)) == []


def test_missing_transcript_yields_empty_list_not_an_error(tmp_path):
    assert lift.lift_decisions(str(tmp_path / "does-not-exist.jsonl")) == []


def test_string_content_message_is_supported(tmp_path):
    """A transcript entry whose `content` is a plain string (not a list of blocks)."""
    transcript = tmp_path / "t.jsonl"
    _write_transcript(str(transcript), [("assistant", "DECISION: plain string content works too")])
    found = lift.lift_decisions(str(transcript))
    assert [t for _m, t, _ln in found] == ["plain string content works too"]


# ---------------------------------------------------------------------------
# main(): end-to-end -- records into the store with provenance, dedups
# ---------------------------------------------------------------------------

def _run_lift_main(monkeypatch, payload) -> None:
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    lift.main([])


def _decisions_rows(root: str):
    conn = sqlite3.connect(os.path.join(root, common.DB_REL))
    try:
        return conn.execute(
            "SELECT text, provenance, session_id, agent FROM decisions ORDER BY id"
        ).fetchall()
    finally:
        conn.close()


def _decided_node_count(root: str) -> int:
    conn = sqlite3.connect(os.path.join(root, common.DB_REL))
    try:
        return conn.execute("SELECT COUNT(*) FROM nodes WHERE kind='decided'").fetchone()[0]
    finally:
        conn.close()


def test_main_records_decisions_with_provenance(tmp_path, monkeypatch):
    root = str(tmp_path)
    transcript = tmp_path / "t.jsonl"
    _write_transcript(str(transcript), [
        ("assistant", _assistant_text_blocks(
            "DECISION: use sqlite WAL mode",
            "FACT: the API rate-limits at 60 rpm",
        )),
    ])
    payload = {
        "cwd": root, "session_id": "s1", "transcript_path": str(transcript),
        "hook_event_name": "Stop",
    }

    _run_lift_main(monkeypatch, payload)

    rows = _decisions_rows(root)
    assert [r[0] for r in rows] == ["use sqlite WAL mode", "the API rate-limits at 60 rpm"]
    assert all(r[1] == "t.jsonl:1" for r in rows), rows
    assert all(r[2] == "s1" for r in rows)
    assert all(r[3] == "main" for r in rows)
    assert _decided_node_count(root) == 2


def test_main_dedups_exact_text_within_session(tmp_path, monkeypatch):
    root = str(tmp_path)
    transcript = tmp_path / "t.jsonl"
    _write_transcript(str(transcript), [
        ("assistant", _assistant_text_blocks("DECISION: use sqlite WAL mode")),
    ])
    payload = {"cwd": root, "session_id": "s1", "transcript_path": str(transcript)}

    _run_lift_main(monkeypatch, payload)
    _run_lift_main(monkeypatch, payload)  # a repeated Stop firing on the same transcript

    rows = _decisions_rows(root)
    assert len(rows) == 1, "exact-text duplicate within the same session must not be re-recorded"


def test_main_does_not_dedup_across_different_sessions(tmp_path, monkeypatch):
    root = str(tmp_path)
    transcript = tmp_path / "t.jsonl"
    _write_transcript(str(transcript), [
        ("assistant", _assistant_text_blocks("DECISION: use sqlite WAL mode")),
    ])

    _run_lift_main(monkeypatch, {"cwd": root, "session_id": "s1", "transcript_path": str(transcript)})
    _run_lift_main(monkeypatch, {"cwd": root, "session_id": "s2", "transcript_path": str(transcript)})

    rows = _decisions_rows(root)
    assert len(rows) == 2
    assert {r[2] for r in rows} == {"s1", "s2"}


def test_main_records_nothing_when_no_markers_present(tmp_path, monkeypatch):
    root = str(tmp_path)
    transcript = tmp_path / "t.jsonl"
    _write_transcript(str(transcript), [("assistant", _assistant_text_blocks("no markers here"))])
    payload = {"cwd": root, "session_id": "s1", "transcript_path": str(transcript)}

    _run_lift_main(monkeypatch, payload)

    # main() returns early when nothing was lifted -- the store may not even exist yet
    db_path = os.path.join(root, common.DB_REL)
    if os.path.isfile(db_path):
        assert _decisions_rows(root) == []


def test_main_prints_nothing(tmp_path, monkeypatch, capsys):
    root = str(tmp_path)
    transcript = tmp_path / "t.jsonl"
    _write_transcript(str(transcript), [("assistant", _assistant_text_blocks("DECISION: quiet please"))])
    payload = {"cwd": root, "session_id": "s1", "transcript_path": str(transcript)}

    _run_lift_main(monkeypatch, payload)

    captured = capsys.readouterr()
    assert captured.out == ""


def test_main_never_raises_on_missing_transcript(tmp_path, monkeypatch):
    root = str(tmp_path)
    payload = {"cwd": root, "session_id": "s1", "transcript_path": os.path.join(root, "nope.jsonl")}
    _run_lift_main(monkeypatch, payload)  # must not raise
