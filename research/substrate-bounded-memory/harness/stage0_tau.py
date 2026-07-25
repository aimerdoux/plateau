"""Stage 0: annihilation-time law tau(r) + packing prediction N_pack
(PREREG.md sec.2.1). No LLM.

Evolve ISOLATED vortex-antivortex pairs at separations r, record the step at
which they annihilate (defect count -> 0), capped at T. Fit tau(r) = alpha * r^2,
invert to the r_min for which tau(r_min) = T, and predict

    N_pack = floor( A_box / (r_min^2 / eta) ),  eta = 0.9069 (hex packing).

If pairs do NOT annihilate within T even at small r (a genuinely frozen glass),
r_min is at the core scale, N_pack is enormous, and the PREREG's
REFUTED-by-geometry clause does not bind — the decisive test then falls to H1's
B1 control (field vs its own lossless dict). Either way this is reported, sealed.

Usage: PYTHONPATH=<repo> python stage0_tau.py
Seals raw/tau_fit.json.
"""
from __future__ import annotations

import time

import numpy as np

from cgle import CGLE
import sealutil

B, C = 0.5, -0.6
N, SIDE, DT = 256, 128.0, 0.05
T = 20000
ETA = 0.9069
A_BOX = SIDE * SIDE
SEPARATIONS = [2.0, 3.0, 4.0, 6.0, 8.0, 12.0, 16.0, 24.0, 32.0]
SAMPLE_EVERY = 200


def annihilation_step(r, seed=0):
    """Return the step at which an isolated pair at separation r annihilates, or
    None if it survives T steps (frozen)."""
    cx = cy = SIDE / 2.0
    s = CGLE(b=B, c=C, N=N, side=SIDE, dt=DT, seed=seed)
    s.seed_vortices([(cx - r / 2, cy), (cx + r / 2, cy)], [+1, -1])
    done = 0
    while done < T:
        s.evolve(SAMPLE_EVERY)
        done += SAMPLE_EVERY
        if s.defect_count() == 0:
            return done
    return None


def main():
    seal_hash = sealutil.echo_seal()
    t0 = time.time()
    rows = []
    for r in SEPARATIONS:
        step = annihilation_step(r)
        tau = None if step is None else step * DT
        rows.append({"r": r, "annihilation_step": step, "tau": tau,
                     "survived_T": step is None})
        print(f"r={r:5.1f}: {'SURVIVED (frozen)' if step is None else f'annihilated @ step {step} (tau={tau:.1f})'}"
              f"  ({time.time()-t0:.0f}s)")

    annih = [(row["r"], row["tau"]) for row in rows if row["tau"] is not None]
    fit = None
    r_min = None
    n_pack = None
    if len(annih) >= 2:
        rs = np.array([a for a, _ in annih])
        taus = np.array([t for _, t in annih])
        # tau = alpha r^2  -> alpha = mean(tau / r^2); fit in log space for robustness
        alpha = float(np.exp(np.mean(np.log(taus) - 2 * np.log(rs))))
        r_min = float(np.sqrt((T * DT) / alpha))
        n_pack = int(np.floor(A_BOX / (r_min * r_min / ETA)))
        fit = {"model": "tau = alpha * r^2", "alpha": alpha,
               "r_min_at_T": r_min, "N_pack": n_pack}
        print(f"\nfit alpha={alpha:.3f}  r_min(T)={r_min:.2f}  N_pack={n_pack}")
    else:
        note = ("fewer than 2 pairs annihilated within T: the regime is frozen at "
                "these separations; r_min is at/below the smallest tested and N_pack "
                "is effectively unbounded -> REFUTED-by-geometry does not bind.")
        print("\n" + note)

    result = {
        "stage": "stage0_tau_fit",
        "params": {"b": B, "c": C, "N": N, "side": SIDE, "dt": DT, "T": T},
        "separations": SEPARATIONS,
        "rows": rows,
        "eta": ETA,
        "A_box": A_BOX,
        "fit": fit,
        "n_annihilated": len(annih),
        "note": None if fit else "frozen: <2 annihilations, packing clause does not bind",
        "wall_seconds": round(time.time() - t0, 1),
    }
    path = sealutil.write_and_seal("tau_fit.json", result)
    print(f"sealed -> {path}\nprereg  -> {seal_hash}")


if __name__ == "__main__":
    main()
