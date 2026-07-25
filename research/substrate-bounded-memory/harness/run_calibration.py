"""Stage: CALIBRATION GATE (PREREG.md sec.1) — run before anything. No LLM.

Write one vortex-antivortex pair, evolve 10*T = 200000 steps, and confirm the
pair persists with zero spontaneous defect nucleation anywhere. PASS admits the
sealed (b,c) as a genuine frozen vortex glass; FAIL means turbulence and every
downstream number would be noise -> re-tune (b,c) and re-run.

Usage: PYTHONPATH=<repo> python run_calibration.py
Seals raw/calibration.json.
"""
from __future__ import annotations

import time

import numpy as np

from cgle import CGLE
import sealutil

# ---- sealed constants (PREREG.md sec.0) ----
B, C = 0.5, -0.6
N, SIDE, DT = 256, 128.0, 0.05
T = 20000
GATE_STEPS = 10 * T           # 200000
SAMPLE_EVERY = 2000
PAIR_SEP = 40.0               # well-separated pair, centred


def main():
    seal_hash = sealutil.echo_seal()
    cx = SIDE / 2.0
    cy = SIDE / 2.0
    s = CGLE(b=B, c=C, N=N, side=SIDE, dt=DT, seed=0)
    s.seed_vortices([(cx - PAIR_SEP / 2, cy), (cx + PAIR_SEP / 2, cy)], [+1, -1])

    series = []           # (step, defect_count)
    n0 = s.defect_count()
    series.append([0, n0])
    print(f"step {0:7d}: defects={n0}")

    t0 = time.time()
    done = 0
    max_count = n0
    while done < GATE_STEPS:
        s.evolve(SAMPLE_EVERY)
        done += SAMPLE_EVERY
        n = s.defect_count()
        max_count = max(max_count, n)
        series.append([done, n])
        if done % 20000 == 0:
            print(f"step {done:7d}: defects={n}  |A|max={float(np.abs(s.A).max()):.3f}"
                  f"  ({time.time()-t0:.0f}s)")

    counts = [c for _, c in series]
    persisted = all(c == 2 for c in counts)          # exactly the pair, all the way
    no_nucleation = max_count <= 2
    result = {
        "stage": "calibration_gate",
        "params": {"b": B, "c": C, "N": N, "side": SIDE, "dt": DT},
        "gate_steps": GATE_STEPS,
        "pair_separation": PAIR_SEP,
        "sample_every": SAMPLE_EVERY,
        "defect_series": series,
        "initial_defects": n0,
        "max_defects": max_count,
        "final_defects": counts[-1],
        "pair_persists": bool(persisted),
        "no_spontaneous_nucleation": bool(no_nucleation),
        "PASS": bool(persisted and no_nucleation),
        "wall_seconds": round(time.time() - t0, 1),
    }
    path = sealutil.write_and_seal("calibration.json", result)
    verdict = "PASS" if result["PASS"] else "FAIL"
    print(f"\nCALIBRATION GATE: {verdict}  (max_defects={max_count}, "
          f"final={counts[-1]})")
    print(f"sealed -> {path}")
    print(f"prereg  -> {seal_hash}")


if __name__ == "__main__":
    main()
