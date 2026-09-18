#!/usr/bin/env python3
"""plateau.bridge.lift — the decided-fact lifter (Stop hook).

At Stop, the assistant's own last message often states outcomes in plain language:
"DECISION: use sqlite WAL mode" or "FACT: the API rate-limits at 60 rpm". This hook reads
the session transcript, finds the text of the LAST assistant message, and lifts every line
matching `^(DECISION|FACT):\\s*(.+)$` (case-sensitive — an incidental lowercase "decision:"
in prose is not a marker), tolerating the markdown a model commonly wraps the marker in
(docs/harness-0.3/target-run-wavex.md finding #6: 2 of 5 turns in the target run wrote
`**FACT:** ...` instead of the literal `FACT: ...` the footer asked for, and were silently
dropped) — a leading `- `/`* `/`+ ` list bullet and/or a `**DECISION:**`/`**FACT:**` bold
wrap are stripped before matching, but the line must still START with the marker right
after that stripping; a marker anywhere else in a sentence is still not lifted — into a
`decisions` row + a `decided:<id>` node (`common.record_decision`), each carrying its own
provenance (`<transcript basename>:<line>`) so a handoff block or `plateau lookup` can point
back at exactly where it was said. Exact-text duplicates within the same session are
skipped (idempotent across a Stop that fires more than once, and across an unrelated later
Stop that repeats an already-recorded line). Prints nothing: this hook never adds or shapes
any `hookSpecificOutput`.

This is also THE Stop-path turn boundary (docs/harness-0.3/target-run-wavex.md finding #4):
`common.mark_turn()` was defined but never called from anywhere in the shipped hook
pipeline, so the `turns` table was always empty and `receipts_per_turn()`/the selector's
`tau` always used their hardcoded fallback. `main()` below calls `mark_turn()` exactly once
per Stop, unconditionally (whether or not this turn's message happens to lift any
decisions) — chosen here, rather than in a separate hook.py mode, per PLAN-step4.md's "pick
one place so it runs exactly once per Stop"; `hooks.json`'s Stop entry fires `post`, `lift`,
`handoff --print` once each per Stop, so `lift` firing once IS one Stop. `main()` also wires
`plateau.lab.probes.maybe()` in immediately after (docs/harness-0.3/PLAN-step4.md "Shadow
probes"): main-agent-only, config-gated, every-N-turns shadow probing that depends on this
same `turns` table being real.
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

MARKER_RE = re.compile(
    r"^(?:[-*+]\s+)?"                              # optional markdown bullet
    r"(?:\*\*(DECISION|FACT):\*\*|(DECISION|FACT):)"  # "**WORD:**" (bold) or plain "WORD:"
    r"\s*(.+)$"
)


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
                marker = m.group(1) or m.group(2)
                found.append((marker, m.group(3).strip(), line_no))
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
        if cfg.role == "off":
            return

        conn = common.db(root)
        try:
            # One turn boundary per Stop, unconditionally (see module docstring finding
            # #4) -- this must happen even when this turn lifts no decisions at all, so
            # it runs before the decided_facts / transcript / lifted-lines early-outs
            # below rather than after them.
            common.mark_turn(conn, session_id)

            if cfg.nodes.get("decided_facts", True) and transcript_path:
                lifted = lift_decisions(transcript_path)
                if lifted:
                    agent = common.agent_of(payload)
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

        # Shadow probes (docs/harness-0.3/PLAN-step4.md "Shadow probes"; see module
        # docstring finding #7): wired into the Stop dispatch right after lift's own
        # work, for the main agent only -- `probes.maybe()` itself checks agent/config/
        # turn-count and never blocks (it spawns the actual `claude -p` fork detached).
        # Imported lazily and never allowed to fail this hook: `plateau.lab` landing
        # after `plateau.bridge` (or not at all, in a minimal install) must never turn
        # a missing-module import into a Stop-hook failure.
        try:
            from ..lab import probes as lab_probes
            lab_probes.maybe(payload, cfg)
        except Exception as exc:
            try:
                common.log(root, "lift probe-wiring ERROR {!r}".format(exc))
            except Exception:
                pass
    except Exception as exc:  # never raise out of a hook -- log and exit clean
        try:
            common.log(root, "lift ERROR {!r}".format(exc))
        except Exception:
            pass


if __name__ == "__main__":
    main()
