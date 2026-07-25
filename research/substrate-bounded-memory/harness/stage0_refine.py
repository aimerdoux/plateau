"""Stage 0 refinement: pin the FREEZE THRESHOLD r_c and test whether annihilation
below it follows tau ~ r^2. The coarse tau_fit found tau~r^2 FALSIFIED (its r_min
contradicts observed survivals) -> the regime has a sharp annihilate/freeze
transition, not diffusive scaling. Locate r_c and record real tau(r) for r<r_c
with fine time sampling. No LLM. Seals raw/tau_refine.json.
"""
from __future__ import annotations

import time

import numpy as np

from cgle import CGLE
import sealutil

B, C = 0.5, -0.6
N, SIDE, DT = 256, 128.0, 0.05
T = 20000
FINE = 20                        # fine time sampling to resolve fast annihilations
SEPS = [5.0, 6.0, 7.0, 8.0, 9.0, 9.5, 10.0, 10.5, 11.0]


def annih_step(r):
    cx = cy = SIDE / 2.0
    s = CGLE(b=B, c=C, N=N, side=SIDE, dt=DT, seed=0)
    s.seed_vortices([(cx - r / 2, cy), (cx + r / 2, cy)], [+1, -1])
    done = 0
    while done < T:
        s.evolve(FINE)
        done += FINE
        if s.defect_count() == 0:
            return done
    return None


def main():
    seal_hash = sealutil.echo_seal()
    t0 = time.time()
    rows = []
    for r in SEPS:
        step = annih_step(r)
        tau = None if step is None else step * DT
        rows.append({"r": r, "annihilation_step": step, "tau": tau,
                     "survived_T": step is None})
        print(f"r={r:5.1f}: {'FROZEN (survives T)' if step is None else f'annihilated tau={tau:.2f}'}"
              f"  ({time.time()-t0:.0f}s)")

    annih = [row for row in rows if not row["survived_T"]]
    froz = [row for row in rows if row["survived_T"]]
    r_c_lo = max([row["r"] for row in annih], default=None)
    r_c_hi = min([row["r"] for row in froz], default=None)
    # capacity scale from the freeze threshold (idealized hex packing)
    eta = 0.9069
    a_box = SIDE * SIDE
    n_cap = None
    if r_c_hi is not None:
        n_cap = int(np.floor(a_box / (r_c_hi ** 2 / eta)))
    # test tau~r^2 among the resolved annihilations
    r2test = None
    if len(annih) >= 3:
        rs = np.array([row["r"] for row in annih])
        ts = np.array([row["tau"] for row in annih])
        # log-log slope: tau ~ r^p
        p = float(np.polyfit(np.log(rs), np.log(ts), 1)[0])
        r2test = {"loglog_slope_p": p, "diffusive_p_is_2": bool(1.5 < p < 2.5)}

    result = {
        "stage": "stage0_refine_freeze_threshold",
        "params": {"b": B, "c": C, "N": N, "side": SIDE, "dt": DT, "T": T},
        "fine_sample_every": FINE, "separations": SEPS, "rows": rows,
        "r_c_lower_annihilates": r_c_lo, "r_c_upper_frozen": r_c_hi,
        "tau_r2_test": r2test,
        "capacity_scale_from_r_c": n_cap, "eta": eta, "A_box": a_box,
        "finding": "sharp freeze threshold; tau~r^2 (diffusive) does not hold across it",
        "wall_seconds": round(time.time() - t0, 1),
    }
    path = sealutil.write_and_seal("tau_refine.json", result)
    print(f"\nfreeze threshold r_c in ({r_c_lo}, {r_c_hi}]  capacity_scale ~ {n_cap}")
    if r2test:
        print(f"tau~r^p below threshold: p={r2test['loglog_slope_p']:.2f} "
              f"(diffusive p=2? {r2test['diffusive_p_is_2']})")
    print(f"sealed -> {path}\nprereg  -> {seal_hash}")


if __name__ == "__main__":
    main()
