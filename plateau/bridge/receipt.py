#!/usr/bin/env python3
"""plateau.bridge.receipt — PostToolUse / PostToolUseFailure hook: one receipt per
tool call, online.

Reads the hook payload from stdin, records it via `common.record`, logs
`receipt r<id> <Tool>`, and always exits 0 printing nothing (neither event consumes
stdout). Skipped entirely when the resolved bridge role is "off".

docs/harness-0.3/target-run-wavex.md finding #9 (item 8): a real target run showed 38
Bash/Read/Write `tool_use` blocks in the transcript but only 36 receipts, with no
`receipt ERROR` line near either gap. Checking the installed Claude Code CLI's own hook-
event enum (`claude`'s bundled `cli.js`) confirms a call that ERRORS fires a wholly
separate `PostToolUseFailure` event instead of `PostToolUse` -- its payload carries
`tool_name`/`tool_input`/`tool_use_id`/`error` (a string), never `tool_response` at all,
so the old code's `payload.get("tool_response")` was always `None` for these and (had
this hook even been wired to that event, which it was not) `classify()` would have seen
an empty response and classified it as an ordinary success. This hook is now wired to
BOTH events (`adapters/claude_code/hooks/hooks.json` / `plateau.bridge.install`); a
`PostToolUseFailure` payload is turned into the synthetic failure response shape
`common.classify()` already recognizes (`{"success": False, "stderr": <error>}`, via
`_resp_text`'s `ok is False`), so it always records outcome `fail`.
"""

from __future__ import annotations

import sys

from . import common
from . import config


def _tool_response_for(payload) -> object:
    """The value to feed `common.record` as `tool_response`: the payload's own
    `tool_response` for an ordinary `PostToolUse` call, or a synthetic failure shape
    built from `PostToolUseFailure`'s `error` string (see module docstring) -- that
    event never carries a `tool_response` key at all."""
    if payload.get("hook_event_name") == "PostToolUseFailure":
        return {"success": False, "stderr": str(payload.get("error") or "")}
    return payload.get("tool_response")


def main(argv=None) -> None:
    payload = common.read_payload()
    root = common.root(payload)
    try:
        session_id = payload.get("session_id", "")
        cfg = config.load(root, session_id)
        if cfg.role != "off":
            conn = common.db(root)
            rid = common.record(
                conn,
                payload.get("tool_name", "?"),
                payload.get("tool_input"),
                _tool_response_for(payload),
                session_id=session_id,
                agent=common.agent_of(payload),
                bridge_version=cfg.version,
                bridge_sha=cfg.sha,
                root=root,
            )
            conn.close()
            common.log(root, f"receipt r{rid} {payload.get('tool_name')}")
    except Exception as e:
        common.log(root, f"receipt ERROR {e!r}")
    sys.exit(0)


if __name__ == "__main__":
    main()
