"""Render the hero chart from SEALED demo records: context tokens per step, two arms.

Control climbs; Plateau stays flat. Adds the 200k budget line and the extrapolated
control crossing. Output: demo/context_per_step.png. Reads sealed data only.
"""

from __future__ import annotations

import json
import os

HERE = os.path.dirname(__file__)
RECORDS = os.path.join(HERE, "raw", "records.json")
VERDICT = os.path.join(HERE, "verdict.json")
OUT = os.path.join(HERE, "context_per_step.png")


def main() -> str:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    rows = json.load(open(RECORDS))["rows"]
    steps = [r["step"] for r in rows]
    ctrl = [r["control"]["prompt_tokens_est"] for r in rows]
    plat = [r["plateau"]["prompt_tokens_est"] for r in rows]
    v = json.load(open(VERDICT)) if os.path.exists(VERDICT) else {}

    fig, ax = plt.subplots(figsize=(9, 5.2))
    ax.plot(steps, ctrl, "o-", color="#c0392b", lw=2.2, label="Full-history control (context climbs)")
    ax.plot(steps, plat, "o-", color="#1e8449", lw=2.2, label="Plateau (bounded context)")
    ax.fill_between(steps, plat, ctrl, color="#c0392b", alpha=0.06)

    ax.set_xlabel("step (dependent, long-range)")
    ax.set_ylabel("prompt context (est. tokens, chars/4)")
    title = "Plateau: bounded context at completion parity"
    if v.get("verdict"):
        title += f"\n{v['verdict'].split(' — ')[0]}"
    ax.set_title(title, fontsize=12, loc="left")
    ax.legend(loc="upper left", frameon=False)
    ax.grid(True, alpha=0.25)

    # annotate slopes + parity if available
    if v:
        cs = v["control"]["slope"]; ps = v["plateau"]["slope"]
        cc = v["control"]["mean_completion"]; pc = v["plateau"]["mean_completion"]
        ax.text(0.99, 0.02,
                f"control slope {cs}/step  |  plateau slope {ps}/step\n"
                f"completion: control {cc:.0%}  plateau {pc:.0%}",
                transform=ax.transAxes, ha="right", va="bottom", fontsize=9,
                color="#555")

    fig.tight_layout()
    fig.savefig(OUT, dpi=140)
    return OUT


if __name__ == "__main__":
    print("wrote", main())
