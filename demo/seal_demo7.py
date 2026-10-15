#!/usr/bin/env python3
"""Seal demo7 raw write-once BEFORE scoring (root=demo/raw7, matching raw4/raw6's
convention: sha256-chained manifest + chmod 0o444 on every file collect() wrote)."""
import glob
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from plateau.integrity import Manifest, is_sealed, seal

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.environ.get("DEMO7_RAW") or os.path.join(REPO, "demo", "raw7")


def main():
    man = os.path.join(RAW, "manifest.jsonl")
    if os.path.exists(man):
        print("REFUSE: raw7 already sealed.")
        sys.exit(1)
    m = Manifest(man)
    n = 0
    patterns = [
        ("*_prompt.txt", "prompt"),
        ("*_log.txt", "log"),
        ("JOURNAL.md", "journal"),
        ("PLAN.md", "plan"),
        ("signal_snapshot.json", "signal"),
        ("state_snapshot.json", "state"),
        ("completion.json", "completion"),
    ]
    for pat, kind in patterns:
        for fp in sorted(glob.glob(os.path.join(RAW, pat))):
            if not is_sealed(fp):
                seal(fp, m, RAW, kind=kind)
                n += 1
    c = m.verify_chain()[0]
    f = m.verify_files(RAW)[0]
    print(f"SEALED {n} files ; chain={'PASS' if c else 'FAIL'} files={'PASS' if f else 'FAIL'}")
    sys.exit(0 if (c and f) else 1)


main()
