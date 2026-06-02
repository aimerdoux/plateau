#!/usr/bin/env python3
"""Score demo6 efficiency from SEALED raw only. Reuses harness4.score byte-for-byte
(verifies its hash pin), with dummy arm3:=arm2; reports EFFICIENCY only (autonomy N/A)."""
import copy, hashlib, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness4 as H
import run_demo6 as R
PIN = "e4484988a77d52b76e37ef4a7fc73f6ff2d69cb504cb570ef8a27da65d3f1bb1"
def main():
    got = hashlib.sha256(open(os.path.join(H.REPO,"demo","harness4.py"),"rb").read()).hexdigest()
    assert got == PIN, f"harness4.py CHANGED since prereg pin! {got} != {PIN}"
    rec = {}
    for a in R.ARMS6:
        rec[a] = {"steps": json.load(open(os.path.join(R.RAW, f"{a}_completion.json")))["steps"]}
    rec["arm3_autonomy"] = copy.deepcopy(rec["arm2_efficiency"])  # pre-registered dummy; autonomy discarded
    v = H.score(rec)
    eff = v["efficiency"]
    out = {"efficiency": eff, "harness4_pin_ok": True, "note": "demo6 is 2-arm; autonomy NOT tested (demo4 NULL stands)"}
    json.dump(out, open(os.environ.get("DEMO6_VERDICT") or os.path.join(H.REPO,"demo","verdict6.json"),"w"), indent=2, sort_keys=True)
    print(json.dumps({"EFFICIENCY": eff["verdict"], "reason": eff["reason"],
                      "arm1_slope": round(eff["arm1_slope"],2), "arm2_slope": round(eff["arm2_slope"],2),
                      "arm1_climbs": eff["arm1_climbs"], "parity": eff["completion_parity"],
                      "pin_ok": True}, indent=2))
main()
