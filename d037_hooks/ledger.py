#!/usr/bin/env python3
"""Deprecated shim: moved to plateau.bridge.common (rebuild_from_transcript); kept so the
sealed D-037/D-038 instruments run unchanged. There is no `plateau.bridge.ledger` twin —
"rebuild from a transcript" is a `common.py` function, not its own hook module — so this
shim carries the small amount of glue itself instead of delegating to a twin's main()."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
os.environ["PLATEAU_DB_REL"] = ".d037/index.sqlite"
os.environ["PLATEAU_LOG_REL"] = ".d037/hooks.log"
os.environ["PLATEAU_LEGACY_TAG"] = "1"

from plateau.bridge import common
from plateau.bridge import config as bridge_config


def main(argv=None) -> None:
    payload = common.read_payload()
    root = common.root(payload)
    session_id = payload.get("session_id", "")
    try:
        cfg = bridge_config.load(root, session_id)
        dbp = os.path.join(root, common.DB_REL)
        for suffix in ("", "-wal", "-shm"):
            p = dbp + suffix
            if os.path.isfile(p):
                os.remove(p)
        conn = common.db(root)
        n = common.rebuild_from_transcript(
            conn,
            payload.get("transcript_path", ""),
            session_id=session_id,
            agent=common.agent_of(payload),
            bridge_version=cfg.version,
            bridge_sha=cfg.sha,
            root=root,
        )
        conn.close()
        common.log(root, f"ledger rebuilt {n} receipts trigger={payload.get('trigger')}")
    except Exception as e:
        common.log(root, f"ledger ERROR {e!r}")
    sys.exit(0)


if __name__ == "__main__":
    main()
