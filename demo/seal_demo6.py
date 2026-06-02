#!/usr/bin/env python3
"""Seal demo6 raw write-once BEFORE scoring (root=demo/raw6, matching raw4's convention)."""
import glob, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from plateau.integrity import Manifest, is_sealed, seal
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.environ.get("DEMO6_RAW") or os.path.join(REPO, "demo", "raw6")
def main():
    man = os.path.join(RAW, "manifest.jsonl")
    if os.path.exists(man):
        print("REFUSE: raw6 already sealed."); sys.exit(1)
    m = Manifest(man); n = 0
    for pat, kind in [("*_step*_prompt.txt","prompt"),("*_step*_reply.md","reply"),
                      ("*_step*_check.json","check"),("*_completion.json","completion")]:
        for fp in sorted(glob.glob(os.path.join(RAW, pat))):
            if not is_sealed(fp): seal(fp, m, RAW, kind=kind); n += 1
    c = m.verify_chain()[0]; f = m.verify_files(RAW)[0]
    print(f"SEALED {n} files ; chain={'PASS' if c else 'FAIL'} files={'PASS' if f else 'FAIL'}")
    sys.exit(0 if (c and f) else 1)
main()
