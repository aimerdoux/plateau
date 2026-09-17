#!/usr/bin/env python3
"""plateau.bridge.lift — the decided-fact lifter (Stop hook).

At Stop, the assistant's own last message often states outcomes in plain language:
"DECISION: use sqlite WAL mode" or "FACT: the API rate-limits at 60 rpm". This hook reads
the session transcript, finds the text of the LAST assistant message, and lifts every line
matching `^(DECISION|FACT):\\s*(.+)$` (case-sensitive — an incidental lowercase "decision:"
in prose is not a marker) into a `decisions` row + a `decided:<id>` node
(`common.record_decision`), each carrying its own provenance (`<transcript
basename>:<line>`) so a handoff block or `plateau lookup` can point back at exactly where it
was said. Exact-text duplicates within the same session are skipped (idempotent across a
Stop that fires more than once, and across an unrelated later Stop that repeats an
already-recorded line). Prints nothing: this hook never adds or shapes any
`hookSpecificOutput`.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from os.path import basename
from typing import Any, List, Optional, Tuple

from . import common
from . import config

MARKER_RE = re.compile(r"^(DECISION|FACT):\s*(.+)$")


def _last_assistant_text_blocks(transcript_path: str) -> List[Tuple[int, str]]:
    """`(line_no, text)` for every text block of the LAST assistant message in the
    transcript (`line_no` is the transcript file's own 1-indexed line number for that
    message — provenance points at the transcript entry, not an offset within a
    multi-line text block). Returns `[]` on any read/parse trouble, or if the transcript
    has no assistant message at all."""
    last: Optional[Tuple[int, Any]] = None
    try:
        with open(transcript_path, encoding="utf-8") as f:
            for line_no, raw in enumerate(f, start=1):
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    entry = json.loads(raw)
                except ValueError:
                    continue
                if not isinstance(entry, dict):
                    continue
                msg = entry.get("message")
                if not isinstance(msg, dict) or msg.get("role") != "assistant":
                    continue
                last = (line_no, msg.get("content"))
    except OSError:
        return []
    if last is None:
        return []
    line_no, content = last
    blocks: List[Tuple[int, str]] = []
    if isinstance(content, str):
        blocks.append((line_no, content))
    elif isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text" and isinstance(block.get("text"), str):
                blocks.append((line_no, block["text"]))
    return blocks


def lift_decisions(transcript_path: str) -> List[Tuple[str, str, int]]:
    """`[(marker, text, line_no), ...]` lifted from the last assistant message, in the
    order the lines appear (one message can carry several marker lines)."""
    found: List[Tuple[str, str, int]] = []
    for line_no, text in _last_assistant_text_blocks(transcript_path):
        for raw_line in text.splitlines():
            m = MARKER_RE.match(raw_line.strip())
            if m:
                found.append((m.group(1), m.group(2).strip(), line_no))
    return found


def _already_recorded(conn, session_id: str, text: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM decisions WHERE session_id=? AND text=? LIMIT 1", (session_id, text),
    ).fetchone()
    return row is not None


def main(argv: Optional[List[str]] = None) -> None:
    argv = sys.argv[1:] if argv is None else argv
    argparse.ArgumentParser(add_help=False).parse_known_args(argv)  # lift takes no flags

    payload = common.read_payload()
    root = common.root(payload)
    session_id = payload.get("session_id", "")
    transcript_path = payload.get("transcript_path", "")

    try:
        cfg = config.load(root, session_id)
        if cfg.role == "off" or not cfg.nodes.get("decided_facts", True):
            return
        if not transcript_path:
            return
        lifted = lift_decisions(transcript_path)
        if not lifted:
            return

        agent = common.agent_of(payload)
        conn = common.db(root)
        try:
            lifted_n = 0
            for _marker, text, line_no in lifted:
                if not text or _already_recorded(conn, session_id, text):
                    continue
                provenance = "{}:{}".format(basename(transcript_path), line_no)
                common.record_decision(conn, session_id, agent, text, provenance)
                lifted_n += 1
            if lifted_n:
                common.log(root, "lift session={} n={}".format(session_id, lifted_n))
        finally:
            conn.close()
    except Exception as exc:  # never raise out of a hook -- log and exit clean
        try:
            common.log(root, "lift ERROR {!r}".format(exc))
        except Exception:
            pass


if __name__ == "__main__":
    main()
