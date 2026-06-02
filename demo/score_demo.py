"""Score the demo from SEALED raw records. Numbers come ONLY from the sealed file.

Reads demo/raw/records.json (sealed write-once before this runs), builds the two
ArmCurves, applies plateau.metrics.decide (the locked rule), adds the early-warning
ceiling extrapolation, and writes demo/verdict.json. Never types a number by hand.
"""

from __future__ import annotations

import json
import os

from plateau.metrics import ArmCurve, decide, early_warning

HERE = os.path.dirname(__file__)
RECORDS = os.path.join(HERE, "raw", "records.json")
OUT = os.path.join(HERE, "verdict.json")
CONTEXT_BUDGET = 200_000   # typical large-model context ceiling, for extrapolation


def main() -> dict:
    rec = json.load(open(RECORDS))
    rows = rec["rows"]
    ctrl = ArmCurve("control", [r["step"] for r in rows],
                    [r["control"]["prompt_tokens_est"] for r in rows],
                    [int(r["control"]["correct"]) for r in rows])
    plat = ArmCurve("plateau", [r["step"] for r in rows],
                    [r["plateau"]["prompt_tokens_est"] for r in rows],
                    [int(r["plateau"]["correct"]) for r in rows])
    d = decide(ctrl, plat)

    # ---- apply the PRE-REGISTERED rule (demo_prereg.md), which is STRICTER than the
    # library decide(): D3 requires plateau completion >= 90% AND >= control. The library
    # decide() only checks >= control, so it can read WIN where the prereg does not. The
    # prereg is binding; enforce its floor here (this can only make the verdict harsher).
    PARITY_FLOOR = 0.90
    d["library_decide_verdict"] = d["verdict"]   # keep the looser library verdict, labeled
    D1 = d["claims"]["anti_rig_control_climbs"]
    D2 = d["claims"]["context_flattened_<=25%_control"]
    D3_ge_control = plat.mean_completion >= ctrl.mean_completion
    D3_floor = plat.mean_completion >= PARITY_FLOOR
    D3 = D3_ge_control and D3_floor
    D4 = d["slope_diff_ci95"]["excludes_zero"]
    d["prereg_claims"] = {
        "D1_control_climbs": bool(D1), "D2_context_flat": bool(D2),
        "D3_parity_ge_control": bool(D3_ge_control),
        "D3_parity_ge_90pct_floor": bool(D3_floor),
        "D4_ci_excludes_zero": bool(D4),
        "parity_floor": PARITY_FLOOR,
        "plateau_completion": plat.mean_completion,
        "control_completion": ctrl.mean_completion,
    }
    if not D1:
        v = "UNSCORABLE — control did not climb."
    elif D1 and D2 and D3 and D4:
        v = "WIN — bounded context at completion parity (>=90%), control climbs."
    elif D2 and not D3_floor and D3_ge_control:
        v = ("NOT-A-CLEAN-WIN — context-slope win is decisive (D1,D2,D4 hold) and Plateau "
             "BEAT control on completion, but neither arm cleared the pre-registered 90% "
             "parity floor: an INSTRUMENT CONFOUND (unreliable subagent arithmetic + GOLD-"
             "vs-error-propagation scoring) swamped the completion axis. NOT 'Plateau "
             "forgets' (Plateau > control). Re-run with a recall-only task to isolate the "
             "mechanism. Reported honestly as not-a-win per the locked rule.")
    elif D2 and not D3_ge_control:
        v = ("PARTIAL (FORGETS) — context flat but Plateau dropped completion BELOW control: "
             "amnesia. Report lost-step class; NOT a win.")
    elif not D2:
        v = "NULL — Plateau slope ~= control; signal carried as much as full history."
    else:
        v = "INCONCLUSIVE — slope flattened but CI includes zero."
    d["verdict"] = v

    # long-range QUERY breakdown (the recall stress)
    q = [r for r in rows if r["kind"] == "QUERY"]
    d["long_range_queries"] = {
        "n": len(q),
        "ages": [r["queried_age"] for r in q],
        "control_correct": sum(int(r["control"]["correct"]) for r in q),
        "plateau_correct": sum(int(r["plateau"]["correct"]) for r in q),
    }

    # ceiling extrapolation from MEASURED slope (labeled, not a measured death)
    d["ceiling_extrapolation"] = {
        "budget_tokens": CONTEXT_BUDGET,
        "control": early_warning([r["control"]["prompt_tokens_est"] for r in rows],
                                 CONTEXT_BUDGET, [r["step"] for r in rows]),
        "plateau": early_warning([r["plateau"]["prompt_tokens_est"] for r in rows],
                                 CONTEXT_BUDGET, [r["step"] for r in rows]),
        "note": "extrapolation from measured slope; not run to the literal ceiling",
    }
    d["token_metric"] = "estimated tokens (chars/4), identical proxy both arms"
    d["source"] = "demo/raw/records.json (sealed)"
    d["n_steps"] = len(rows)
    json.dump(d, open(OUT, "w"), indent=2)
    return d


if __name__ == "__main__":
    print(json.dumps(main(), indent=2))
