"""plateau.sigma.loop_analyze — read the recorded one-shot SIGMA/COLD (ab_runs_compress) + the
loop checkpoints (ab_runs_loop) and emit the per-task comparison + the honest verdict.

NO FABRICATION: every cell comes from a recorded real claude -p + real pytest run. A task with
no loop checkpoint yet is reported as PENDING (partial-capable). The verdict applies the
pre-registered attribution_rule: enhanced <=> (a) the loop converts a one-shot SIGMA fail->pass
AND (b) SIGMA_LOOP >= COLD_LOOP.
"""

from __future__ import annotations

import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ONESHOT = os.path.join(HERE, "ab_runs_compress")
LOOP = os.path.join(HERE, "ab_runs_loop")

# canonical order: substantial first, then todos
ORDER = [
    "8b3e2489-73e__test_spend",
    "c8c7a298-bab__test_xpense",
    "f7e6348e-943__test_add",
    "f7e6348e-943__test_done",
    "f7e6348e-943__test_persist",
    "f7e6348e-943__test_list",
]


def _load(path):
    if not os.path.exists(path):
        return None
    with open(path) as f:
        return json.load(f)


def collect() -> list:
    rows = []
    for tid in ORDER:
        one = _load(os.path.join(ONESHOT, f"{tid}.json"))
        sl = _load(os.path.join(LOOP, f"{tid}__SIGMA_LOOP.json"))
        cl = _load(os.path.join(LOOP, f"{tid}__COLD_LOOP.json"))
        row = {
            "task_id": tid,
            "v_asserts": (one or {}).get("v_assert_count"),
            "d_orig": (one or {}).get("d_orig_summary"),
            "oneshot_sigma_pass": bool((one or {}).get("sigma", {}).get("pass")),
            "oneshot_sigma_summary": (one or {}).get("sigma", {}).get("v_summary"),
            "oneshot_cold_pass": bool((one or {}).get("cold", {}).get("pass")),
            "oneshot_cold_summary": (one or {}).get("cold", {}).get("v_summary"),
            "sigma_loop": sl,
            "cold_loop": cl,
        }
        rows.append(row)
    return rows


def summarize():
    rows = collect()
    n = 0
    sigma_loop_pass = cold_loop_pass = oneshot_sigma_pass = 0
    closed = 0           # tasks where loop converted a one-shot SIGMA fail -> SIGMA_LOOP pass
    sigma_ge_cold = sigma_gt_cold = 0
    table = []
    for r in rows:
        sl, cl = r["sigma_loop"], r["cold_loop"]
        if not (sl and sl.get("done")) or not (cl and cl.get("done")):
            table.append({**{k: r[k] for k in ("task_id", "v_asserts")},
                          "status": "PENDING"})
            continue
        n += 1
        slp = bool(sl.get("passed")); clp = bool(cl.get("passed"))
        sigma_loop_pass += int(slp)
        cold_loop_pass += int(clp)
        oneshot_sigma_pass += int(r["oneshot_sigma_pass"])
        if slp and not r["oneshot_sigma_pass"]:
            closed += 1
        if slp >= clp:
            sigma_ge_cold += 1
        if slp and not clp:
            sigma_gt_cold += 1
        table.append({
            "task_id": r["task_id"],
            "v_asserts": r["v_asserts"],
            "oneshot_sigma": "PASS" if r["oneshot_sigma_pass"] else f"fail ({r['oneshot_sigma_summary']})",
            "sigma_loop": ("PASS@%s" % sl.get("pass_at_iter")) if slp
                          else f"fail ({sl.get('final_summary')}) /{sl.get('iters_run')}it",
            "cold_loop": ("PASS@%s" % cl.get("pass_at_iter")) if clp
                         else f"fail ({cl.get('final_summary')}) /{cl.get('iters_run')}it",
            "sigma_loop_pass": slp,
            "cold_loop_pass": clp,
        })
    # attribution / verdict
    schema_beats_naive = sigma_loop_pass > cold_loop_pass
    schema_ge_naive = sigma_loop_pass >= cold_loop_pass
    loop_closed = closed > 0
    if loop_closed and schema_ge_naive and schema_beats_naive:
        enhanced = "YES"
    elif loop_closed and schema_ge_naive:
        enhanced = "MIXED"   # loop closed gap but schema only ties naive => loop, not schema
    elif loop_closed and not schema_ge_naive:
        enhanced = "MIXED"   # loop closed gap on schema arm but naive arm did better overall
    else:
        enhanced = "NO"      # loop did not close the gap at all
    return {
        "n": n,
        "sigma_loop_pass": sigma_loop_pass,
        "cold_loop_pass": cold_loop_pass,
        "oneshot_sigma_pass": oneshot_sigma_pass,
        "loop_closed_gap_tasks": closed,
        "schema_beats_naive_under_loop": "yes" if schema_beats_naive else "no",
        "schema_ge_naive_under_loop": schema_ge_naive,
        "enhanced": enhanced,
        "table": table,
        "rows": rows,
    }


if __name__ == "__main__":
    s = summarize()
    print(json.dumps({k: v for k, v in s.items() if k not in ("rows",)}, indent=2, default=str))
