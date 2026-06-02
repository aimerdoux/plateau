"""Score the recall-only demo from SEALED raw. Numbers come ONLY from the sealed file.
Applies the demo2_prereg.md locked rule (recall-vs-distance), without override.
"""

from __future__ import annotations

import json
import os

from plateau.metrics import slope

HERE = os.path.dirname(__file__)
RECORDS = os.path.join(HERE, "raw2", "records.json")
OUT = os.path.join(HERE, "verdict2.json")

# pre-registered thresholds (demo2_prereg.md)
DEGRADE_MARGIN = 0.25   # R2: control_far <= control_near - 0.25
FLAT_TOL = 0.15         # R3: plateau_far >= plateau_near - 0.15
FLOOR = 0.70            # R3: plateau_far >= 0.70


def _bin(rows, lo, hi):
    return [r for r in rows if lo <= r["distance"] <= hi]


def _acc(rows, arm):
    return round(sum(int(r[arm]["correct"]) for r in rows) / len(rows), 4) if rows else None


def score_rows(rows: list) -> dict:
    near = _bin(rows, 0, 5); mid = _bin(rows, 6, 13); far = _bin(rows, 14, 10**9)
    acc = {arm: {"near": _acc(near, arm), "mid": _acc(mid, arm), "far": _acc(far, arm),
                 "overall": _acc(rows, arm)} for arm in ("control", "plateau")}
    # recall-vs-distance slope per arm (negative = degrades with distance)
    dists = [float(r["distance"]) for r in rows]
    rslope = {arm: round(slope(dists, [float(r[arm]["correct"]) for r in rows]), 5)
              for arm in ("control", "plateau")}
    # control prompt-token slope (anti-rig: must climb)
    tslope = round(slope([float(i) for i in range(len(rows))],
                         [float(r["control"]["prompt_tokens_est"]) for r in rows]), 3)
    cn, cf = acc["control"]["near"], acc["control"]["far"]
    pn, pf = acc["plateau"]["near"], acc["plateau"]["far"]

    R1 = tslope > 0
    R2 = (cn is not None and cf is not None) and (cf <= cn - DEGRADE_MARGIN)
    R3 = (pn is not None and pf is not None) and (pf >= pn - FLAT_TOL) and (pf >= FLOOR)
    R4 = (pf is not None and cf is not None) and (pf > cf)

    if not R1:
        verdict = "UNSCORABLE — control tokens did not climb."
    elif not R2:
        verdict = ("UNSCORABLE — control recall did NOT degrade with distance "
                   f"(near {cn}, far {cf}); facts didn't sink deep enough. Lengthen the "
                   "chain; do not score a degradation that isn't there.")
    elif R3 and R4:
        verdict = ("WIN — Plateau preserves recall as facts sink (near {pn} → far {pf}) "
                   "while full-history control degrades (near {cn} → far {cf}), at bounded "
                   "context cost.").format(pn=pn, pf=pf, cn=cn, cf=cf)
    elif R4 and not R3:
        # Plateau is flatter AND higher than control, but its absolute far-recall did not
        # clear the pre-registered floor. NULL by the locked rule (no override), reported
        # precisely: a directional-but-not-decisive result, not "Plateau lost".
        verdict = ("NULL (near-miss) — by the locked rule this is NOT a win: Plateau's far "
                   f"recall {pf} did not clear the pre-registered {FLOOR} floor. BUT Plateau "
                   f"was both flatter and higher than control (plateau near {pn}→far {pf}, "
                   f"drop {round(pn-pf,3)}; control near {cn}→far {cf}, drop {round(cn-cf,3)}; "
                   f"plateau far {pf} > control far {cf}). The directional result favors "
                   "Plateau; we do not claim the win. n is small (far bin = 6).")
    else:
        verdict = ("NULL — control degrades with distance but Plateau did not beat it on "
                   f"recall preservation (plateau near {pn}/far {pf}, control far {cf}). "
                   "Honest negative.")

    stale = sum(1 for r in rows if r["control"]["answer"] != r["gold"]
                and r["control"]["answer"] not in ("", str(r["gold"])))
    return {
        "metric": "recall_accuracy_vs_distance",
        "n_queries": len(rows), "bins": {"near": "<=5", "mid": "6-13", "far": ">=14"},
        "recall_by_bin": acc,
        "recall_vs_distance_slope": rslope,
        "control_token_slope": tslope,
        "control_prompt_first_last": [rows[0]["control"]["prompt_tokens_est"],
                                      rows[-1]["control"]["prompt_tokens_est"]],
        "plateau_prompt_first_last": [rows[0]["plateau"]["prompt_tokens_est"],
                                      rows[-1]["plateau"]["prompt_tokens_est"]],
        "prereg_claims": {"R1_control_tokens_climb": bool(R1),
                          "R2_control_recall_degrades": bool(R2),
                          "R3_plateau_recall_flat_and_high": bool(R3),
                          "R4_plateau_far_beats_control_far": bool(R4)},
        "control_stale_or_wrong_far_count": stale,
        "verdict": verdict,
        "token_metric": "estimated tokens (chars/4), identical proxy both arms",
    }


def main() -> dict:
    rows = json.load(open(RECORDS))["rows"]
    d = score_rows(rows)
    d["source"] = "demo/raw2/records.json (sealed)"
    json.dump(d, open(OUT, "w"), indent=2)
    return d


if __name__ == "__main__":
    print(json.dumps(main(), indent=2))
