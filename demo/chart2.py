"""Hero chart for the recall-only demo: recall accuracy vs fact-distance, both arms.
Rendered from sealed data only. Honest title reflects the locked-rule verdict."""

from __future__ import annotations

import json
import os

HERE = os.path.dirname(__file__)
RECORDS = os.path.join(HERE, "raw2", "records.json")
VERDICT = os.path.join(HERE, "verdict2.json")
OUT = os.path.join(HERE, "recall_vs_distance.png")


def main() -> str:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    rows = json.load(open(RECORDS))["rows"]
    v = json.load(open(VERDICT)) if os.path.exists(VERDICT) else {}
    acc = v.get("recall_by_bin", {})

    # per-query scatter (jittered y for visibility) + bin-mean lines
    bins = [("near\n(d≤5)", "near"), ("mid\n(6–13)", "mid"), ("far\n(≥14)", "far")]
    xs = [0, 1, 2]
    cvals = [acc.get("control", {}).get(k) for _, k in bins]
    pvals = [acc.get("plateau", {}).get(k) for _, k in bins]

    fig, ax = plt.subplots(figsize=(9, 5.2))
    ax.plot(xs, cvals, "o-", color="#c0392b", lw=2.4, ms=9,
            label="Full-history control (recall degrades)")
    ax.plot(xs, pvals, "o-", color="#1e8449", lw=2.4, ms=9,
            label="Plateau (bounded context)")
    ax.axhline(0.70, ls="--", color="#888", lw=1, label="pre-registered 0.70 far-recall floor")
    ax.set_xticks(xs); ax.set_xticklabels([b for b, _ in bins])
    ax.set_ylim(-0.05, 1.08)
    ax.set_ylabel("recall accuracy (fraction correct)")
    ax.set_xlabel("fact distance (steps since the value was set)")
    head = (v.get("verdict", "").split(" — ")[0]) if v else ""
    ax.set_title(f"Recall vs distance — {head}", fontsize=12, loc="left")
    ax.legend(loc="lower left", frameon=False, fontsize=9)
    ax.grid(True, axis="y", alpha=0.25)
    if v:
        ax.text(0.99, 0.97,
                f"control context {v['control_prompt_first_last'][0]}→"
                f"{v['control_prompt_first_last'][1]} tok (slope {v['control_token_slope']}/step)\n"
                f"plateau context {v['plateau_prompt_first_last'][0]}→"
                f"{v['plateau_prompt_first_last'][1]} tok (bounded)\n"
                f"overall recall: control {acc.get('control',{}).get('overall')}  "
                f"plateau {acc.get('plateau',{}).get('overall')}",
                transform=ax.transAxes, ha="right", va="top", fontsize=8.5, color="#555")
    fig.tight_layout(); fig.savefig(OUT, dpi=140)
    return OUT


if __name__ == "__main__":
    print("wrote", main())
