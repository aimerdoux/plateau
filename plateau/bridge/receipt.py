#!/usr/bin/env python3
"""plateau.bridge.receipt — PostToolUse hook: one receipt per tool call, online.

Reads the hook payload from stdin, records it via `common.record`, logs
`receipt r<id> <Tool>`, and always exits 0 printing nothing (PostToolUse does not
consume stdout). Skipped entirely when the resolved bridge role is "off".
"""

from __future__ import annotations

import sys

from . import common
from . import config


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
                payload.get("tool_response"),
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
