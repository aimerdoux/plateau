#!/usr/bin/env python3
"""Arm C — PreCompact: freeze a copy of the store. No extraction from prose."""
import sys, os, shutil, time; sys.path.insert(0, os.path.dirname(__file__))
from d037_common import *
p = read_payload(); r = root(p)
try:
    src = os.path.join(r, DB_REL); d = os.path.join(r, ".d037/snapshots"); os.makedirs(d, exist_ok=True)
    if os.path.exists(src): shutil.copy(src, os.path.join(d, f"{int(time.time())}_{p.get('trigger','?')}.sqlite"))
    log(r, f"snapshot trigger={p.get('trigger')}")
except Exception as e:
    log(r, f"snapshot ERROR {e!r}")
sys.exit(0)
