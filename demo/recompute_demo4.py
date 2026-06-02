#!/usr/bin/env python3
"""Fresh-process recompute for demo4. Independent backstop — trusts nothing but the
sealed bytes:
  1. manifest hash-chain recomputes (no truncation/rewrite),
  2. every sealed file still hashes to its recorded value (no tamper),
  3. context_tokens in each sealed completion.json re-derive EXACTLY from the sealed
     prompt .txt bytes (tok() recompute) — couples the numbers to the raw,
  4. the verdict re-derives from sealed completion.json and matches demo/verdict4.json.
Exit 0 only if all hold. Run in a fresh interpreter: python3 demo/recompute_demo4.py
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness4 as H  # noqa: E402
sys.path.insert(0, H.REPO)
from plateau.integrity import Manifest  # noqa: E402

RAW = os.path.join(H.REPO, "demo", "raw4")
probs = []


def main():
    m = Manifest(os.path.join(RAW, "manifest.jsonl"))
    c_ok, c_pr = m.verify_chain()
    f_ok, f_pr = m.verify_files(RAW)
    if not c_ok:
        probs.extend(c_pr)
    if not f_ok:
        probs.extend(f_pr)

    # context_tokens re-derive from sealed prompt bytes
    rec = {}
    for a in H.ARMS:
        comp = json.load(open(os.path.join(RAW, f"{a}_completion.json")))
        rec[a] = {"steps": comp["steps"]}
        for s in comp["steps"]:
            pp = os.path.join(RAW, f"{a}_step{s['step']}_prompt.txt")
            re_tok = H.tok(open(pp).read())
            if re_tok != s["context_tokens"]:
                probs.append(f"{a} step{s['step']}: context_tokens {s['context_tokens']} "
                             f"!= recomputed {re_tok}")

    # verdict reproduces
    v_new = H.score(rec)
    v_old = json.load(open(os.path.join(H.REPO, "demo", "verdict4.json")))
    if json.dumps(v_new, sort_keys=True) != json.dumps(v_old, sort_keys=True):
        probs.append("verdict4.json does not reproduce from sealed raw")

    files = len(m._entries())
    if probs:
        print(f"RECOMPUTE: FAIL ({len(probs)} problems, {files} sealed files)")
        for p in probs[:12]:
            print("  -", p)
        sys.exit(1)
    print(f"RECOMPUTE: PASS — chain+files verify, context_tokens re-derive from sealed "
          f"prompts, verdict reproduces ({files} sealed files)")
    print(f"  EFFICIENCY={v_new['efficiency']['verdict']}  AUTONOMY={v_new['autonomy']['verdict']}")


if __name__ == "__main__":
    main()
