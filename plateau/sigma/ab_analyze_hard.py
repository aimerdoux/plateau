"""plateau.sigma.ab_analyze_hard — read the HARD checkpoints, compute the honest verdict.

Reads ab_runs_hard/<task>.json (written by ab_run_hard.py) + the frozen prereg hash, computes:
  - baseline_fail = #tasks where ARM_WITHOUT failed the objective gate (the measured headroom).
  - recovery = #baseline-FAILING tasks that ARM_WITH passed  /  baseline_fail.
  - controls_regress = #baseline-PASSING control tasks where ARM_WITH did NOT pass.
  - verdict:
      INCONCLUSIVE_CEILING  if baseline_fail == 0 (set still not hard enough).
      ENHANCED (YES)        if recovery fraction is MEANINGFUL (>0; stated explicitly).
      NEGATIVE (NO)         if recovery ~0 (pattern doesn't help even with headroom).

Emits the per-task markdown table + the one-line summary string. Pure read; runs no model.
"""

from __future__ import annotations

import json
import os

from . import ab_tasks_hard

HERE = os.path.dirname(os.path.abspath(__file__))
AB_RUNS_HARD = os.path.join(HERE, "ab_runs_hard")
PREREG_HASH = os.path.join(HERE, "prereg_ab_hard.json.hash")


def load_rows():
    specs = ab_tasks_hard.hard_task_specs()
    rows = []
    for sp in specs:
        p = os.path.join(AB_RUNS_HARD, f"{sp['task_id']}.json")
        row = {"task_id": sp["task_id"], "depth": sp["depth"], "kpi": sp["kpi"]}
        if os.path.exists(p):
            with open(p) as f:
                row.update(json.load(f))
        rows.append(row)
    return rows


def analyze():
    rows = load_rows()
    manifest_hash = ""
    if os.path.exists(PREREG_HASH):
        manifest_hash = open(PREREG_HASH).read().strip()

    baseline_done = [r for r in rows if r.get("without")]
    baseline_fail = [r for r in baseline_done if not r["without"]["all_pass"]]
    baseline_pass = [r for r in baseline_done if r["without"]["all_pass"]]

    # recovery: of baseline-failing tasks, how many did WITH pass?
    recovered = [r for r in baseline_fail if r.get("with") and r["with"]["all_pass"]]
    with_attempted_fail = [r for r in baseline_fail if r.get("with")]

    # controls: baseline-passing tasks WITH was also run on; regress = WITH did NOT pass
    controls = [r for r in baseline_pass if r.get("with")]
    controls_regress = [r for r in controls if not r["with"]["all_pass"]]

    n = len(rows)
    n_baseline_done = len(baseline_done)
    b = len(baseline_fail)
    r_rec = len(recovered)
    c_reg = len(controls_regress)

    if n_baseline_done < n:
        verdict = "PARTIAL_INCOMPLETE"
    elif b == 0:
        verdict = "INCONCLUSIVE_CEILING"
    elif len(with_attempted_fail) < b:
        verdict = "PARTIAL_INCOMPLETE"
    elif r_rec == 0:
        verdict = "NO"            # real negative: headroom existed, pattern recovered nothing
    else:
        verdict = "YES"           # enhanced: recovered a meaningful (>0) fraction; fraction stated

    return {
        "manifest_hash": manifest_hash,
        "rows": rows,
        "n": n,
        "n_baseline_done": n_baseline_done,
        "baseline_fail": b,
        "baseline_fail_ids": [r["task_id"] for r in baseline_fail],
        "recovered": r_rec,
        "recovered_ids": [r["task_id"] for r in recovered],
        "with_attempted_fail": len(with_attempted_fail),
        "controls": len(controls),
        "controls_regress": c_reg,
        "controls_regress_ids": [r["task_id"] for r in controls_regress],
        "verdict": verdict,
    }


def table(rows):
    out = ["| Task | Depth | Baseline (WITHOUT) | WITH recover | WITH iters | WITH trace | role |",
           "|---|---|---|---|---|---|---|"]
    for r in rows:
        wo = r.get("without")
        w = r.get("with")
        base = ("PASS" if wo["all_pass"] else "FAIL") if wo else "—"
        if w is None:
            rec = "—"; iters = "—"; trace = "—"
        else:
            rec = "PASS" if w["all_pass"] else "fail"
            iters = str(w["iterations"])
            trace = str(w.get("feasibility_trace"))
        if wo and not wo["all_pass"]:
            role = "RECOVERY"
        elif w is not None and wo and wo["all_pass"]:
            role = "control"
        else:
            role = "baseline-pass (no WITH)"
        out.append(f"| {r['task_id']} | {r['depth']} | {base} | {rec} | {iters} | {trace} | {role} |")
    return "\n".join(out)


if __name__ == "__main__":
    a = analyze()
    print(table(a["rows"]))
    print()
    frac = f"{a['recovered']}/{a['baseline_fail']}" if a["baseline_fail"] else "n/a (ceiling)"
    print(f"baseline_fail={a['baseline_fail']}/{a['n']}  recovery={frac}  "
          f"controls_regress={a['controls_regress']}/{a['controls']}  verdict={a['verdict']}  "
          f"manifest={a['manifest_hash']}")
