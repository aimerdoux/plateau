"""demo8 scorer — reads ONLY sealed records, applies the locked rule, reproduces the verdict.

Run AFTER `run_demo8.py` has finished and sealed (prereg guard: "no scoring process may run
while any worker is in flight" — demo7's flaw #1, now a rule). Re-derives prompt_tokens from
the sealed PROMPT BYTES rather than trusting records.json, verifies the manifest chain and
every file hash, then applies demo4/demo6's decision rule without override.

  UNSCORABLE      fullhistory does not climb materially, or <5 completed control steps
  WIN             fullhistory climbs AND slope[plateau] <= 0.25*slope[fullhistory]
                  AND completion parity
  PARTIAL_FORGETS plateau bounded but FAILS a gate fullhistory passes
  NULL            plateau slope not materially below fullhistory

Usage: python demo/score_demo8.py [--verify]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from plateau.integrity import Manifest, file_hash                # noqa: E402

RAW = os.path.join(ROOT, "demo", "raw8")
VERDICT = os.path.join(ROOT, "demo", "verdict8.json")
PREREG = os.path.join(ROOT, "demo", "demo8_prereg.md")
SLOPE_BAR = 0.25          # sealed: plateau must be <= 25% of fullhistory
MIN_COMPLETED = 5         # sealed: fewer completed control steps -> UNSCORABLE
CLIMB_MIN = 50.0          # sealed materiality: tokens/step the control arm must climb


def tok(text: str) -> int:
    return len(re.findall(r"\w+|[^\w\s]", text))


def _slope(ys: list) -> float:
    n = len(ys)
    if n < 2:
        return 0.0
    xs = list(range(n))
    mx, my = sum(xs) / n, sum(ys) / n
    den = sum((x - mx) ** 2 for x in xs)
    return 0.0 if den == 0 else sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / den


def score(records: list) -> dict:
    arms = sorted({r["arm"] for r in records})
    series, completion = {}, {}
    for a in arms:
        rs = sorted([r for r in records if r["arm"] == a], key=lambda r: r["step"])
        series[a] = [r["prompt_tokens_rederived"] for r in rs]
        completion[a] = sum(1 for r in rs if r["gate_passed"])
    sl = {a: _slope(series[a]) for a in arms}

    p, f = "arm_plateau", "arm_fullhistory"
    climbed = sl.get(f, 0.0) >= CLIMB_MIN
    n_done_control = completion.get(f, 0)
    parity = completion.get(p, 0) >= completion.get(f, 0)

    if n_done_control < MIN_COMPLETED or not climbed:
        verdict = "UNSCORABLE"
        why = (f"control arm completed {n_done_control} (<{MIN_COMPLETED}) "
               if n_done_control < MIN_COMPLETED else "") + \
              (f"control slope {sl.get(f,0):.1f} < materiality {CLIMB_MIN} tok/step "
               "-> chain too short to test the axis" if not climbed else "")
    elif sl.get(p, 0.0) <= SLOPE_BAR * sl[f] and parity:
        verdict, why = "WIN", (f"bounded slope {sl[p]:.1f} <= {SLOPE_BAR:.0%} of control "
                               f"{sl[f]:.1f}, at completion parity")
    elif sl.get(p, 0.0) <= SLOPE_BAR * sl[f] and not parity:
        verdict, why = "PARTIAL_FORGETS", (f"bounded arm stayed bounded ({sl[p]:.1f}) but "
                                           f"completed {completion[p]}/{completion[f]} of the "
                                           "control arm's gates — condensation limit, not a win")
    else:
        verdict, why = "NULL", (f"bounded slope {sl[p]:.1f} not materially below control "
                                f"{sl[f]:.1f}")

    return {"arms": arms, "series": series, "slopes": sl, "completion": completion,
            "climbed": climbed, "parity": parity, "verdict": verdict, "why": why,
            "rule": {"slope_bar": SLOPE_BAR, "min_completed": MIN_COMPLETED,
                     "climb_min": CLIMB_MIN}}


def load_sealed() -> tuple:
    man = Manifest(os.path.join(RAW, "manifest.jsonl"))
    ok_chain, chain_bad = man.verify_chain()
    ok_files, file_bad = man.verify_files(RAW)
    data = json.load(open(os.path.join(RAW, "records.json")))
    # re-derive prompt_tokens FROM THE SEALED PROMPT BYTES — never trust the recorded number
    for r in data["records"]:
        pf = os.path.join(RAW, f"{r['arm']}_{r['step']:02d}_{r['task']}_prompt.txt")
        r["prompt_tokens_rederived"] = tok(open(pf).read())
    mismatches = [f"{r['arm']}/{r['task']}" for r in data["records"]
                  if r["prompt_tokens_rederived"] != r["prompt_tokens"]]
    return data, (ok_chain, chain_bad), (ok_files, file_bad), mismatches


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--verify", action="store_true",
                    help="recompute-verify in a fresh process and reproduce the verdict")
    args = ap.parse_args()

    data, (ok_chain, cb), (ok_files, fb), mism = load_sealed()
    result = score(data["records"])
    result["prereg_sha256"] = file_hash(PREREG)
    result["sealed_prereg_sha256"] = data.get("prereg_sha256")
    result["integrity"] = {"chain_ok": ok_chain, "files_ok": ok_files,
                           "token_rederivation_mismatches": mism}

    if args.verify:
        prior = json.load(open(VERDICT)) if os.path.exists(VERDICT) else None
        same = prior is not None and prior.get("verdict") == result["verdict"] and \
            prior.get("slopes") == result["slopes"]
        if ok_chain and ok_files and not mism and same:
            print(f"RECOMPUTE_OK — chain+files verify, {len(data['records'])} records, "
                  f"tokens re-derive from sealed bytes, verdict reproduces")
        else:
            print(f"RECOMPUTE_FAILED chain={ok_chain} files={ok_files} "
                  f"token_mismatches={mism} verdict_reproduces={same}")
            return 1
    else:
        with open(VERDICT, "w") as fh:
            json.dump(result, fh, indent=2, sort_keys=True)

    print(f"  VERDICT={result['verdict']} — {result['why']}")
    for a in result["arms"]:
        print(f"  {a}: tokens={result['series'][a]} slope={result['slopes'][a]:.1f} "
              f"completed={result['completion'][a]}/5")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
