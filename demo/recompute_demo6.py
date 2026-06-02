#!/usr/bin/env python3
"""Fresh-process recompute for demo6: chain+files verify (root=demo/raw6), context_tokens
re-derive from sealed prompt bytes, harness4 hash unchanged, verdict reproduces."""
import copy, hashlib, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness4 as H
import run_demo6 as R
sys.path.insert(0, H.REPO)
from plateau.integrity import Manifest
PIN = "e4484988a77d52b76e37ef4a7fc73f6ff2d69cb504cb570ef8a27da65d3f1bb1"
probs = []
def main():
    if hashlib.sha256(open(os.path.join(H.REPO,"demo","harness4.py"),"rb").read()).hexdigest() != PIN:
        probs.append("harness4.py hash changed since prereg pin")
    m = Manifest(os.path.join(R.RAW, "manifest.jsonl"))
    if not m.verify_chain()[0]: probs.append("chain FAIL")
    if not m.verify_files(R.RAW)[0]: probs.append("files FAIL")
    rec = {}
    for a in R.ARMS6:
        comp = json.load(open(os.path.join(R.RAW, f"{a}_completion.json")))
        rec[a] = {"steps": comp["steps"]}
        for s in comp["steps"]:
            pp = os.path.join(R.RAW, f"{a}_step{s['step']}_prompt.txt")
            if H.tok(open(pp).read()) != s["context_tokens"]:
                probs.append(f"{a} step{s['step']} context_tokens mismatch")
    rec["arm3_autonomy"] = copy.deepcopy(rec["arm2_efficiency"])  # SAME dummy construction as score_demo6
    v = H.score(rec)["efficiency"]
    old = json.load(open(os.environ.get("DEMO6_VERDICT") or os.path.join(H.REPO,"demo","verdict6.json")))["efficiency"]
    if json.dumps(v, sort_keys=True) != json.dumps(old, sort_keys=True):
        probs.append("efficiency verdict does not reproduce")
    if probs:
        print("RECOMPUTE: FAIL"); [print("  -",p) for p in probs]; sys.exit(1)
    print(f"RECOMPUTE: PASS — chain+files verify, context_tokens re-derive, harness4 pin intact, "
          f"verdict reproduces ({len(m._entries())} sealed files)")
    print(f"  EFFICIENCY={v['verdict']}")
main()
