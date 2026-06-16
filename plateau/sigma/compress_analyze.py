"""plateau.sigma.compress_analyze — read ab_runs_compress/*.json, classify, emit the verdict.

NO FABRICATION: every cell is read from the fsync'd on-disk checkpoints written by the paid run.

Per task:  COLD_pass, SIGMA_pass (each scored against the SAME objective V = the original suite).
  enhanced  <=> SIGMA passes V where COLD fails.
Counts:  SIGMA_only, COLD_only, both_pass (task easy / schema redundant),
         both_fail (V too hard / schema insufficient).
Verdict (honest):
  CEILING  — both arms pass on most tasks (set too easy; schema had no headroom).
  YES      — SIGMA_only > 0 and SIGMA_only > COLD_only (schema decompresses where cold can't).
  MIXED    — SIGMA_only > 0 but COLD_only comparable (signal noisy / task-dependent).
  NO       — SIGMA_only == 0 (schema added nothing over the raw ask) OR COLD_only >= SIGMA_only.
"""

from __future__ import annotations

import glob
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
RUNS = os.path.join(HERE, "ab_runs_compress")
PREREG_PATH = os.path.join(HERE, "prereg_compress.json")


def load_rows() -> list:
    rows = []
    for p in sorted(glob.glob(os.path.join(RUNS, "*.json"))):
        if os.path.basename(p).startswith("_"):
            continue
        with open(p) as f:
            rows.append(json.load(f))
    return rows


def classify(rows: list) -> dict:
    complete = [r for r in rows if r.get("cold") and r.get("sigma")]
    sigma_only = cold_only = both_pass = both_fail = 0
    d_orig_pass = 0
    per = []
    for r in complete:
        c = bool(r["cold"]["pass"])
        s = bool(r["sigma"]["pass"])
        dop = bool(r.get("d_orig_pass"))
        d_orig_pass += int(dop)
        if s and not c:
            sigma_only += 1; cls = "SIGMA_only(enhanced)"
        elif c and not s:
            cold_only += 1; cls = "COLD_only"
        elif c and s:
            both_pass += 1; cls = "both_pass"
        else:
            both_fail += 1; cls = "both_fail"
        per.append({
            "task_id": r["task_id"], "pkg": r.get("pkg"), "test": r.get("test_name"),
            "turns_in_original": r.get("n_turns_in_original"),
            "v_asserts": r.get("v_assert_count"),
            "d_orig_pass": dop,
            "cold_pass": c, "cold_v": r["cold"].get("v_summary"),
            "sigma_pass": s, "sigma_v": r["sigma"].get("v_summary"),
            "leakage_ratio": r.get("leakage_ratio"),
            "class": cls,
        })
    n = len(complete)
    verdict = _verdict(n, sigma_only, cold_only, both_pass, both_fail)
    return {
        "n_complete": n, "n_total_rows": len(rows),
        "sigma_only": sigma_only, "cold_only": cold_only,
        "both_pass": both_pass, "both_fail": both_fail,
        "d_orig_pass": d_orig_pass,
        "verdict": verdict,
        "per_task": sorted(per, key=lambda x: (-(x["v_asserts"] or 0), x["task_id"])),
    }


def _verdict(n, sigma_only, cold_only, both_pass, both_fail) -> str:
    if n == 0:
        return "NO_DATA"
    # ceiling: most tasks pass BOTH arms -> set too easy, no headroom for the schema to help.
    if both_pass >= max(1, (n + 1) // 2) and sigma_only == 0:
        return "CEILING"
    if sigma_only == 0:
        return "NO"                       # schema never recovered a cold failure
    if sigma_only > cold_only:
        return "YES"
    if sigma_only == cold_only:
        return "MIXED"
    return "NO"                            # cold recovered more than sigma


if __name__ == "__main__":
    rows = load_rows()
    res = classify(rows)
    print(json.dumps(res, indent=2))
