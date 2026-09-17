#!/usr/bin/env python3
"""plateau.bridge.lookup — on-demand deep lookup.

`python3 -m plateau.bridge.lookup <words>` or the `plateau lookup <words>` CLI: prints
up to 2400 chars of rendered lines matching the query, untagged, or `(no receipts
match)` -- or `(bridge off)` when the resolved bridge role is "off" ("off means off
everywhere"; docs/harness-0.3/PLAN.md deviations), without ever opening the store.
Eviction from the injected context is never terminal — anything scored here was
always re-derivable from the receipt store, never lost.
"""

from __future__ import annotations

import sys

from . import common
from . import config
from . import query as query_mod

BUDGET_CHARS = 2400


def main(argv=None) -> None:
    argv = sys.argv[1:] if argv is None else argv
    q = " ".join(argv)
    root = common.root({})
    cfg = config.load(root)
    if cfg.role == "off":
        print("(bridge off)")
        return
    conn = common.db(root)
    session_id = ""
    scored = query_mod.score_nodes(conn, q, cfg, session_id)
    chosen = query_mod.select(
        scored, BUDGET_CHARS, cfg,
        head="", sticky_keys=[], edited_since=set(), resolved_errors=set(),
    )
    text = "\n".join(query_mod.render_line(n) for n in chosen)
    print(text if text else "(no receipts match)")


if __name__ == "__main__":
    main()
