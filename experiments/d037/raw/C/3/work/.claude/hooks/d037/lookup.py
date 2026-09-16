#!/usr/bin/env python3
"""Rung 6 — on-demand lookup the worker calls via Bash: python3 lookup.py <words>. Eviction is never terminal."""
import sys, os; sys.path.insert(0, os.path.dirname(__file__))
from d037_common import *; from query import score_nodes, render
r = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd(); q = " ".join(sys.argv[1:])
c = db(r); print("".join(render(score_nodes(c, q), 2400, "")) or "(no receipts match)")
