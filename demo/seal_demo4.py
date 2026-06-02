#!/usr/bin/env python3
"""Seal demo4 raw write-once BEFORE scoring. Seals the measured artifacts only
(per-step prompts/replies/checks + per-arm completion records); working scratch
(signal.json / fplan.txt) is NOT a result and is not sealed. After this, every
sealed file is chmod 0o444 and its hash is in raw4/manifest.jsonl."""
from __future__ import annotations

import glob
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from plateau.integrity import Manifest, is_sealed, seal  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(REPO, "demo", "raw4")


def main():
    man = os.path.join(RAW, "manifest.jsonl")
    if os.path.exists(man):
        print("REFUSE: manifest already exists — raw4 already sealed (write-once).")
        sys.exit(1)
    m = Manifest(man)
    n = 0
    pats = [("*_step*_prompt.txt", "prompt"), ("*_step*_reply.md", "reply"),
            ("*_step*_check.json", "check"), ("*_completion.json", "completion")]
    for pat, kind in pats:
        for fp in sorted(glob.glob(os.path.join(RAW, pat))):
            if not is_sealed(fp):
                seal(fp, m, RAW, kind=kind)
                n += 1
    c_ok, _ = m.verify_chain()
    f_ok, _ = m.verify_files(RAW)
    print(f"SEALED {n} files into {os.path.relpath(man, REPO)} ; "
          f"chain={'PASS' if c_ok else 'FAIL'} files={'PASS' if f_ok else 'FAIL'}")
    sys.exit(0 if (c_ok and f_ok) else 1)


if __name__ == "__main__":
    main()
