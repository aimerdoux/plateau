#!/usr/bin/env python3
"""Score demo7 from SEALED raw only (demo/raw7/), per demo7_prereg.md's decision rule.

Two modes:
  python demo/score_demo7.py            score: verify seal, derive verdict, write
                                         demo/verdict7.json, print a summary.
  python demo/score_demo7.py --verify   fresh-process recompute (T5's own GATE): manifest
                                         chain+files verify, context_tokens re-derive from
                                         the sealed prompt/log/journal/signal bytes (not
                                         from the cached completion.json numbers), verdict
                                         reproduces from that re-derivation, and matches
                                         demo/verdict7.json. Prints RECOMPUTE_OK on success
                                         (matches PLAN.md T5's EXPECT), else RECOMPUTE_FAIL
                                         + reasons and exits 1.

Only `harness4.tok()` and its slope helper are reused (byte-for-byte, per demo7_prereg.md
"What is reused"); the 2-series decision rule below is demo7's own, applied verbatim from
the pre-registered rule — not re-derived after seeing the data.
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness4 as H  # noqa: E402  (tok, _slope reused unmodified)
import run_demo7 as R  # noqa: E402  (shared JOURNAL.md row parsing)
sys.path.insert(0, H.REPO)
from plateau.integrity import Manifest  # noqa: E402

RAW = os.environ.get("DEMO7_RAW") or os.path.join(H.REPO, "demo", "raw7")
VERDICT_PATH = os.environ.get("DEMO7_VERDICT") or os.path.join(H.REPO, "demo", "verdict7.json")
MIN_COMPLETED = 5  # pre-registered guard (demo7_prereg.md "Guards")
CLIMB_RATIO = 1.5  # "materially climbs" — same definition harness4.score uses for arm1
WIN_RATIO = 0.25   # the 25%/4x WIN bar, unmodified


def _materially_climbs(series: list) -> bool:
    return bool(series) and len(series) >= 2 and series[-1] >= CLIMB_RATIO * max(1, series[0])


def decide(completion: dict) -> dict:
    """Apply demo7_prereg.md's decision rule verbatim to a derived {full_history,
    actual_loop, n_completed, plan_unchecked} record. Pure function — same on cached or
    freshly re-derived input, which is what makes --verify meaningful."""
    n = completion["n_completed"]
    fh = completion["full_history"]
    al = completion["actual_loop"]
    # rounded to 4dp: makes the stored/compared verdict robust to the last-bit float
    # noise a repeating-decimal mean (sum/n) can introduce between recomputes, without
    # affecting any real decision at this scale (thresholds are 25%/1.5x, not per-bit).
    fh_slope = round(H._slope([float(x) for x in fh]), 4)
    al_slope = round(H._slope([float(x) for x in al]), 4)
    climbs = n >= MIN_COMPLETED and _materially_climbs(fh)
    done = len(completion["plan_unchecked"]) == 0

    if not climbs:
        verdict = "UNSCORABLE"
        reason = (f"only {n} completed dispatch record(s) (< {MIN_COMPLETED} required) "
                  f"and/or full-history series does not materially climb "
                  f"(first={fh[0] if fh else 0}, last={fh[-1] if fh else 0}) -> "
                  f"run too short to test the efficiency axis, per the pre-registered guard")
    elif al_slope <= WIN_RATIO * fh_slope:
        if done:
            verdict = "WIN"
            reason = (f"full-history climbs (slope {fh_slope:.1f}); actual-loop slope "
                      f"{al_slope:.1f} <= 25% of that; control loop reached DONE")
        else:
            verdict = "PARTIAL_BLOCKED"
            reason = (f"actual-loop slope {al_slope:.1f} stayed <= 25% of full-history "
                      f"{fh_slope:.1f}, but the run ended BLOCK, not DONE "
                      f"({len(completion['plan_unchecked'])} unchecked task(s))")
    else:
        verdict = "NULL"
        reason = (f"actual-loop slope {al_slope:.1f} not <= 25% of full-history "
                  f"{fh_slope:.1f} -> the loop's context bound did not hold in practice")

    return {"verdict": verdict, "reason": reason, "n_completed": n,
            "full_history_slope": fh_slope, "actual_loop_slope": al_slope,
            "full_history": fh, "actual_loop": al, "steps": completion["steps"],
            "completion_parity_done": done, "plan_unchecked": completion["plan_unchecked"]}


def _load_sealed_completion() -> dict:
    return json.load(open(os.path.join(RAW, "completion.json")))


def score() -> dict:
    completion = _load_sealed_completion()
    verdict = decide(completion)
    json.dump(verdict, open(VERDICT_PATH, "w"), indent=2, sort_keys=True)
    return verdict


def verify() -> int:
    problems = []
    man = Manifest(os.path.join(RAW, "manifest.jsonl"))
    c_ok, c_pr = man.verify_chain()
    f_ok, f_pr = man.verify_files(RAW)
    if not c_ok:
        problems.extend(c_pr)
    if not f_ok:
        problems.extend(f_pr)

    completion = _load_sealed_completion()

    # re-derive context_tokens from the sealed raw bytes directly (not from completion.json's
    # cached arrays) — the whole point of --verify is to trust nothing but the sealed bytes.
    signal_text = open(os.path.join(RAW, "signal_snapshot.json")).read()
    state_text = open(os.path.join(RAW, "state_snapshot.json")).read()
    journal_lines = R._journal_lines_by_task(open(os.path.join(RAW, "JOURNAL.md")).read())

    al_base = H.tok(signal_text) + H.tok(state_text)
    fh_cum = 0
    al_cum = 0
    re_fh, re_al = [], []
    for idx, tid in enumerate(completion["steps"], start=1):
        p = os.path.join(RAW, f"{idx:02d}_{tid}_prompt.txt")
        lg = os.path.join(RAW, f"{idx:02d}_{tid}_log.txt")
        fh_cum += H.tok(open(p).read()) + H.tok(open(lg).read())
        al_cum += H.tok(journal_lines.get(tid, ""))
        re_fh.append(fh_cum)
        re_al.append(al_base + al_cum)

    if re_fh != completion["full_history"]:
        problems.append(f"full_history re-derive mismatch: {re_fh} != {completion['full_history']}")
    if re_al != completion["actual_loop"]:
        problems.append(f"actual_loop re-derive mismatch: {re_al} != {completion['actual_loop']}")

    re_completion = dict(completion)
    re_completion["full_history"], re_completion["actual_loop"] = re_fh, re_al
    v_new = decide(re_completion)
    if os.path.exists(VERDICT_PATH):
        v_old = json.load(open(VERDICT_PATH))
        if json.dumps(v_new, sort_keys=True) != json.dumps(v_old, sort_keys=True):
            problems.append("verdict7.json does not reproduce from sealed raw")
    else:
        problems.append("demo/verdict7.json missing -- run `python demo/score_demo7.py` first")

    if problems:
        print(f"RECOMPUTE_FAIL ({len(problems)} problem(s))")
        for p in problems[:12]:
            print("  -", p)
        return 1

    print(f"RECOMPUTE_OK — chain+files verify, context_tokens re-derive from sealed bytes, "
         f"verdict reproduces ({len(man._entries())} sealed files)")
    print(f"  VERDICT={v_new['verdict']} n_completed={v_new['n_completed']} "
         f"reason={v_new['reason']}")
    return 0


if __name__ == "__main__":
    if "--verify" in sys.argv[1:]:
        sys.exit(verify())
    v = score()
    print(json.dumps({"VERDICT": v["verdict"], "reason": v["reason"],
                      "n_completed": v["n_completed"],
                      "full_history_slope": round(v["full_history_slope"], 2),
                      "actual_loop_slope": round(v["actual_loop_slope"], 2),
                      "completion_parity_done": v["completion_parity_done"],
                      "verdict_path": VERDICT_PATH}, indent=2))
