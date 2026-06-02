#!/usr/bin/env python3
"""demo6 chart from SEALED data: context-per-step, arm1 full-history vs arm2 efficiency."""
import json, os, sys
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(REPO, "demo", "raw6")
def load(a): return json.load(open(os.path.join(RAW, f"{a}_completion.json")))
a1, a2 = load("arm1_fullhistory"), load("arm2_efficiency")
v = json.load(open(os.path.join(REPO, "demo", "verdict6.json")))["efficiency"]
fig, ax = plt.subplots(figsize=(8.5, 5))
for comp, lab, mk, col in ((a1,"arm1 full-history","o-","#cc3a21"),(a2,"arm2 plateau-efficiency","s-","#1c4587")):
    xs = list(range(1, len(comp["context"])+1))
    ax.plot(xs, comp["context"], mk, color=col, label=f"{lab} (slope {comp['slope']:.0f}/step, {comp['steps_to_done']} steps→PASS)")
    ax.annotate("PASS", (comp["steps_to_done"], comp["context"][comp["steps_to_done"]-1]),
                textcoords="offset points", xytext=(0,9), fontsize=8, ha="center")
ax.set_title(f"demo6 context per step (sealed) — EFFICIENCY: {v['verdict']}\n"
             f"arm1 slope {v['arm1_slope']:.0f} vs arm2 {v['arm2_slope']:.0f} "
             f"(arm2 {'<=' if v['arm2_slope']<=0.25*v['arm1_slope'] else '>'} 25% bar); parity={v['completion_parity']}")
ax.set_xlabel("agent step"); ax.set_ylabel("prompt tokens (deterministic count of sealed prompt)")
ax.legend(fontsize=9); ax.grid(alpha=0.3)
fig.tight_layout()
out = os.path.join(REPO, "demo", "context_per_step6.png"); fig.savefig(out, dpi=110)
print("wrote", out)
