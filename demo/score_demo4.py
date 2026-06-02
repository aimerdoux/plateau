#!/usr/bin/env python3
"""Score demo4 from SEALED raw only. Reads raw4/{arm}_completion.json (sealed),
applies harness4.score (the locked rules), writes demo/verdict4.json. No judgment."""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness4 as H  # noqa: E402

REPO = H.REPO
RAW = os.path.join(REPO, "demo", "raw4")


def load_records():
    rec = {}
    for a in H.ARMS:
        comp = json.load(open(os.path.join(RAW, f"{a}_completion.json")))
        rec[a] = {"steps": comp["steps"]}
    return rec


def main():
    rec = load_records()
    verdict = H.score(rec)
    out = os.path.join(REPO, "demo", "verdict4.json")
    json.dump(verdict, open(out, "w"), indent=2, sort_keys=True)
    e, a = verdict["efficiency"], verdict["autonomy"]
    print(json.dumps({
        "EFFICIENCY": e["verdict"], "efficiency_reason": e["reason"],
        "AUTONOMY": a["verdict"], "autonomy_reason": a["reason"],
        "arm1_slope": round(e["arm1_slope"], 2), "arm2_slope": round(e["arm2_slope"], 2),
        "arm2_steps": a["arm2_steps"], "arm3_steps": a["arm3_steps"],
        "arm2_errors": a["arm2_errors"], "arm3_errors": a["arm3_errors"],
        "verdict_path": out}, indent=2))


if __name__ == "__main__":
    main()
