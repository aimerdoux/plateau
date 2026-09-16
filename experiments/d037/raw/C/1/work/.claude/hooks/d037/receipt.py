#!/usr/bin/env python3
"""Arm C — PostToolUse: one receipt per tool call, online. Emits nothing."""
import sys; sys.path.insert(0, __import__("os").path.dirname(__file__))
from d037_common import *
p = read_payload(); r = root(p)
try:
    c = db(r); rid = record(c, p.get("tool_name", "?"), p.get("tool_input"), p.get("tool_response")); c.close()
    log(r, f"receipt r{rid} {p.get('tool_name')}")
except Exception as e:
    log(r, f"receipt ERROR {e!r}")
sys.exit(0)
