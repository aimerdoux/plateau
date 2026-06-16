"""plateau.sigma.ab_analyze — score + analyze the LIVE A/B checkpoints, write RESULTS_AB.md.

Reads ab_runs/<task>.json (one per task, written by ab_run.py — every number from a real
claude -p run, NO fabrication), computes:
  - per-task WITH vs WITHOUT gate-pass (+ iterations, calls/cost)
  - overall pass-rate WITH vs WITHOUT
  - the DEPTH GRADIENT: does WITH's advantage grow with task depth?
  - an HONEST verdict: enhanced = YES / NO / ONLY_DEEP / FLAT
and emits plateau/sigma/RESULTS_AB.md. A result where WITH does not beat WITHOUT is reported
plainly; nothing is massaged toward "pattern wins".
"""

from __future__ import annotations

import glob
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
AB_RUNS = os.path.join(HERE, "ab_runs")
RESULTS = os.path.join(HERE, "RESULTS_AB.md")
PREREG = os.path.join(HERE, "prereg_ab.json")


def _load_rows() -> list:
    rows = []
    for p in sorted(glob.glob(os.path.join(AB_RUNS, "*.json"))):
        if os.path.basename(p).startswith("_"):
            continue
        with open(p) as f:
            rows.append(json.load(f))
    rows.sort(key=lambda r: (r.get("depth", 0), r.get("task_id", "")))
    return rows


def _manifest_hash() -> str:
    hp = PREREG + ".hash"
    if os.path.exists(hp):
        return open(hp).read().strip()
    return "(missing)"


def analyze(rows: list) -> dict:
    complete = [r for r in rows if r.get("with") and r.get("without") and not r.get("error")]
    n = len(complete)
    with_pass = sum(1 for r in complete if r["with"]["all_pass"])
    without_pass = sum(1 for r in complete if r["without"]["all_pass"])

    # depth gradient: compare WITH-advantage on shallow (depth<=2) vs deep (depth>=4) tasks.
    shallow = [r for r in complete if r["depth"] <= 2]
    deep = [r for r in complete if r["depth"] >= 4]

    def adv(group):
        # WITH advantage = (#WITH-only wins) - (#WITHOUT-only wins) over the group
        wonly = sum(1 for r in group if r["with"]["all_pass"] and not r["without"]["all_pass"])
        woonly = sum(1 for r in group if r["without"]["all_pass"] and not r["with"]["all_pass"])
        return wonly, woonly, wonly - woonly

    sh_w, sh_wo, sh_adv = adv(shallow)
    dp_w, dp_wo, dp_adv = adv(deep)

    # WITH-only wins (pattern strictly helped) and WITHOUT-only wins (pattern strictly hurt)
    with_only = [r["task_id"] for r in complete
                 if r["with"]["all_pass"] and not r["without"]["all_pass"]]
    without_only = [r["task_id"] for r in complete
                    if r["without"]["all_pass"] and not r["with"]["all_pass"]]

    # verdict
    if n == 0:
        verdict = "BLOCKED"
        depth_gradient = "flat"
        enhanced = "FLAT"
    else:
        net = len(with_only) - len(without_only)
        # depth gradient present iff deep advantage strictly exceeds shallow advantage
        # AND there is some positive deep advantage.
        if dp_adv > sh_adv and dp_adv > 0:
            depth_gradient = "yes"
        elif net == 0 and not with_only and not without_only:
            depth_gradient = "flat"
        else:
            depth_gradient = "no"

        if net <= 0 and not with_only:
            # WITH never strictly beat WITHOUT
            enhanced = "FLAT" if not without_only else "NO"
        elif depth_gradient == "yes" and sh_adv <= 0:
            enhanced = "ONLY_DEEP"
        elif net > 0:
            enhanced = "YES"
        else:
            enhanced = "NO"

    return {
        "n": n,
        "with_pass": with_pass,
        "without_pass": without_pass,
        "with_only": with_only,
        "without_only": without_only,
        "shallow_adv": (sh_w, sh_wo, sh_adv),
        "deep_adv": (dp_w, dp_wo, dp_adv),
        "depth_gradient": depth_gradient,
        "enhanced": enhanced,
        "verdict": "DONE" if n == len(rows) and n > 0 else ("PARTIAL" if n > 0 else "BLOCKED"),
        "complete": complete,
        "all_rows": rows,
    }


def write_results(a: dict) -> str:
    mh = _manifest_hash()
    rows = a["all_rows"]
    lines = []
    lines.append("# Σ / Plateau — LIVE A/B Capability Experiment — RESULTS\n")
    lines.append(f"**Manifest hash (pre-registered, frozen before any run):** `{mh}`\n")
    lines.append(f"**N (tasks with both arms scored):** {a['n']}  ")
    lines.append(f"**Metric:** gate_pass against the OBJECTIVE V (τ=1.0, programmatic gates, "
                 "fixed code in `ab_tasks.py`, neither arm authored — A6).  ")
    lines.append(f"**Arms:** WITH = `run_schema` Σ loop (Φ-hydrated, max_iters=4, depth compounds) "
                 "· WITHOUT = single `claude -p` pass. SAME base model both arms.  ")
    lines.append("**Model:** live `claude -p` (Claude Code CLI). Every number below is from a real "
                 "paid run; NO fabrication.\n")

    # verdict line
    lines.append("## Verdict\n")
    lines.append(f"- **Overall pass-rate:** WITH = {a['with_pass']}/{a['n']} · "
                 f"WITHOUT = {a['without_pass']}/{a['n']}")
    lines.append(f"- **WITH strictly helped on:** {a['with_only'] or '(none)'}")
    lines.append(f"- **WITHOUT strictly better on:** {a['without_only'] or '(none)'}")
    sh = a["shallow_adv"]; dp = a["deep_adv"]
    lines.append(f"- **Depth gradient:** shallow(depth≤2) WITH-advantage = {sh[2]} "
                 f"(WITH-only {sh[0]}, WITHOUT-only {sh[1]}); deep(depth≥4) WITH-advantage = "
                 f"{dp[2]} (WITH-only {dp[0]}, WITHOUT-only {dp[1]}) → **{a['depth_gradient']}**")
    lines.append(f"- **Capability enhanced?** **{a['enhanced']}**\n")

    # per-task table
    lines.append("## Per-task results\n")
    lines.append("| Task | Depth | WITH pass | WITHOUT pass | WITH iters | WITH trace | "
                 "WITH calls | WITHOUT calls | Δ |")
    lines.append("|---|---|---|---|---|---|---|---|---|")
    for r in sorted(rows, key=lambda x: (x.get("depth", 0), x.get("task_id", ""))):
        w = r.get("with") or {}
        wo = r.get("without") or {}
        if r.get("error"):
            lines.append(f"| {r['task_id']} | {r.get('depth','?')} | — | — | — | — | — | — | "
                         f"ERR: {r['error'][:40]} |")
            continue
        wp = "✅" if w.get("all_pass") else "❌"
        wop = "✅" if wo.get("all_pass") else "❌"
        delta = "WITH" if (w.get("all_pass") and not wo.get("all_pass")) else \
                ("WITHOUT" if (wo.get("all_pass") and not w.get("all_pass")) else "tie")
        trace = w.get("feasibility_trace", [])
        lines.append(f"| {r['task_id']} | {r.get('depth')} | {wp} | {wop} | "
                     f"{w.get('iterations','?')} | {trace} | {w.get('calls','?')} | "
                     f"{wo.get('calls','?')} | {delta} |")
    lines.append("")

    # cost
    wc = sum((r.get("with") or {}).get("calls", 0) for r in rows)
    woc = sum((r.get("without") or {}).get("calls", 0) for r in rows)
    lines.append(f"**Approx cost (claude -p invocations):** WITH arm = {wc} calls · "
                 f"WITHOUT arm = {woc} calls · total = {wc + woc} calls.\n")

    # honest caveats
    lines.append("## Honest caveats\n")
    lines.append(f"- **Bounded first pass, N={a['n']}.** Small sample; this is a directional "
                 "signal, not a powered study. Per-task k=1 (one objective scoring per produced "
                 "candidate; the gate is deterministic, but the model sample is single-draw per "
                 "arm so task-level noise is real).")
    lines.append("- **Tasks are reproducible analogues** of corpus deliverable *shapes* "
                 "(produce code / JSON / markdown / a small state machine satisfying checkable "
                 "gates). The corpus's own auto-mined gates (opened_pr, on-disk-artifact-exists, "
                 "boolean `claim_*` flags) are NOT checkable on a freshly produced candidate and "
                 "were dropped per design — so these tasks are grounded in the corpus's kinds, not "
                 "lifted verbatim.")
    lines.append("- **Ceiling effect risk:** a strong base model may pass shallow tasks in one "
                 "pass, leaving the Σ loop no room to help except on deep tasks. That is exactly "
                 "the depth-gradient hypothesis; read the deep-task rows, not just the aggregate.")
    lines.append("- **WITH spends more compute** (up to 4× calls). Any WITH win is a "
                 "compute-for-capability trade, not free.")
    lines.append("- **Objective-V only; A6 held:** neither arm authored or saw its judge; both "
                 "scored by the same fixed programmatic gates. A WITHOUT win or a tie is a "
                 "first-class, valid result and is reported as-is.\n")

    txt = "\n".join(lines)
    with open(RESULTS, "w") as f:
        f.write(txt)
    return txt


if __name__ == "__main__":
    rows = _load_rows()
    a = analyze(rows)
    write_results(a)
    print(json.dumps({k: v for k, v in a.items()
                      if k not in ("complete", "all_rows")}, indent=2, default=str))
