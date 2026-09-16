#!/usr/bin/env python3
"""Arm B — PreCompact: rebuild the same store from the transcript JSONL (batch, tool blocks only, no prose)."""
import sys, os, json; sys.path.insert(0, os.path.dirname(__file__))
from d037_common import *
p = read_payload(); r = root(p)
try:
    tp = p.get("transcript_path"); uses, results = {}, {}
    order = []
    with open(tp) as f:
        for line in f:
            try: j = json.loads(line)
            except Exception: continue
            msg = j.get("message") or {}
            for b in (msg.get("content") or []) if isinstance(msg.get("content"), list) else []:
                if b.get("type") == "tool_use":
                    uses[b["id"]] = (b.get("name"), b.get("input")); order.append(b["id"])
                elif b.get("type") == "tool_result":
                    results[b.get("tool_use_id")] = j.get("toolUseResult", b.get("content"))
    dbp = os.path.join(r, DB_REL)
    if os.path.exists(dbp): os.remove(dbp)
    c = db(r); n = 0
    for uid in order:
        tool, tin = uses[uid]; record(c, tool, tin, results.get(uid)); n += 1
    c.execute("INSERT OR REPLACE INTO meta VALUES('built_from','transcript')"); c.commit(); c.close()
    log(r, f"ledger rebuilt {n} receipts trigger={p.get('trigger')}")
except Exception as e:
    log(r, f"ledger ERROR {e!r}")
sys.exit(0)
