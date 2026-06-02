#!/usr/bin/env python3
"""demo4 charts from SEALED data only: (left) context-per-step, 3 arms; (right)
steps + error-rework count, arm2 vs arm3. Renders demo/context_per_step4.png."""
from __future__ import annotations

import json
import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(REPO, "demo", "raw4")


def load(a):
    return json.load(open(os.path.join(RAW, f"{a}_completion.json")))


a1, a2, a3 = load("arm1_fullhistory"), load("arm2_efficiency"), load("arm3_autonomy")

fig, (ax, bx) = plt.subplots(1, 2, figsize=(12, 4.6))

for comp, lab, mk in ((a1, "arm1 full-history", "o-"),
                      (a2, "arm2 plateau-efficiency", "s-"),
                      (a3, "arm3 plateau-autonomy", "^-")):
    xs = list(range(1, len(comp["context"]) + 1))
    ax.plot(xs, comp["context"], mk, label=f"{lab} (slope {comp['slope']:.0f}/step)")
    ax.annotate("PASS", (comp["steps_to_done"], comp["context"][comp["steps_to_done"] - 1]),
                textcoords="offset points", xytext=(0, 8), fontsize=8, ha="center")
ax.set_title("demo4 context per step (sealed)\nEfficiency: UNSCORABLE — arm1 reached PASS in 2 steps")
ax.set_xlabel("agent step")
ax.set_ylabel("prompt tokens (deterministic count of sealed prompt)")
ax.set_xticks([1, 2, 3])
ax.legend(fontsize=8)
ax.grid(alpha=0.3)

labels = ["arm2 efficiency", "arm3 autonomy"]
steps = [a2["steps_to_done"], a3["steps_to_done"]]
errs = [a2["errors"], a3["errors"]]
x = range(len(labels))
bx.bar([i - 0.18 for i in x], steps, width=0.36, label="steps_to_done", color="#4a86e8")
bx.bar([i + 0.18 for i in x], errs, width=0.36, label="error/rework steps", color="#e07798")
for i, (s, e) in enumerate(zip(steps, errs)):
    bx.text(i - 0.18, s + 0.03, str(s), ha="center", fontsize=9)
    bx.text(i + 0.18, e + 0.03, str(e), ha="center", fontsize=9)
bx.set_xticks(list(x))
bx.set_xticklabels(labels)
bx.set_title("demo4 autonomy: arm3 vs arm2 (sealed)\nNULL — tie: 3=3 steps, 0=0 errors")
bx.set_ylabel("count")
bx.set_ylim(0, 4)
bx.legend(fontsize=8)
bx.grid(alpha=0.3, axis="y")

fig.tight_layout()
out = os.path.join(REPO, "demo", "context_per_step4.png")
fig.savefig(out, dpi=110)
print("wrote", out)
