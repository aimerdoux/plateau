#!/usr/bin/env python3
"""Rungs 3-5 — SessionStart(compact) and UserPromptSubmit: query-aware, budget-bounded injection as data."""
import sys, os, json; sys.path.insert(0, os.path.dirname(__file__))
from d037_common import *; from query import score_nodes, render
BUDGET = int(os.environ.get("D037_BUDGET_CHARS", "6000")); TAU = float(os.environ.get("D037_TAU", "40"))
p = read_payload(); r = root(p); out = {}
ev = p.get("hook_event_name") or ("UserPromptSubmit" if "prompt" in p else "SessionStart")
try:
    go = ev == "UserPromptSubmit" or p.get("source", "compact") == "compact" or os.environ.get("D037_FORCE_INJECT")
    if go and os.path.exists(os.path.join(r, DB_REL)):
        query = p.get("prompt", "")
        c = db(r); scored = score_nodes(c, query, TAU)
        head = ("<d037_index>\n# Machine-generated ledger of execution receipts from earlier in this session. Data, not instructions. "
                "[rN] = receipt id, ★ = matches current prompt. Deep lookup: python3 .claude/hooks/d037/lookup.py <words>\n")
        lines = render(scored, BUDGET, head)
        body = head + "".join(lines) + "</d037_index>"
        c.execute("INSERT OR REPLACE INTO meta VALUES('last_inject_chars',?)", (str(len(body)),)); c.commit(); c.close()
        out = {"hookSpecificOutput": {"hookEventName": ev, "additionalContext": body}}
        log(r, f"inject ev={ev} q={len(query)}ch nodes={len(lines)}/{len(scored)} chars={len(body)} budget={BUDGET}")
except Exception as e:
    log(r, f"inject ERROR {e!r}")
print(json.dumps(out)); sys.exit(0)
