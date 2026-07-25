"""H1: capacity sweep (PREREG.md sec.2). No LLM.

For each k (items) and seed: project synthetic 768-dim vectors -> (x,y)+charge,
write k vortices, evolve T steps, read out surviving defects, one-to-one match
back to items within readout resolution rho. Accuracy@1 = matched/k.

Arms (PREREG sec.2.2):
  field : the CGLE substrate (the thing under test)
  B1    : the IDENTICAL projection in a plain dict, no dynamics, read at the SAME
          rho -> the lossless-at-rho baseline. field <= B1  =>  pure projection
          loss (REFUTED).
  B2    : FIFO of fixed item capacity = the reference "arbitrary forgetting" line.

Decision (sec.2.3): N_crit[arm] = largest k with mean Accuracy@1 >= 0.90.
  H1 WIN     = field N_crit >= 50 AND field N_crit > B1 beyond CI.
  H1 REFUTED = field N_crit < 50 OR field <= B1 OR REFUTED-by-geometry (stage0).

Usage:
  full : PYTHONPATH=<repo> python h1_sweep.py            (sealed, k-grid x 20 seeds)
  smoke: PYTHONPATH=<repo> python h1_sweep.py --smoke    (tiny, UNSEALED scratch)
"""
from __future__ import annotations

import json
import os
import sys
import time

import numpy as np

from cgle import CGLE
from items import projection_matrix, synthetic_embeddings, encode
import sealutil

B, C = 0.5, -0.6
N, SIDE, DT = 256, 128.0, 0.05
T = 20000
RHO = 1.0                      # readout resolution (= 2*dx), same for every arm
K_GRID = [1, 2, 5, 10, 20, 50, 100, 200]
SEEDS = 20
ACC_BAR = 0.90
P = projection_matrix()        # fixed, sealed


def match_accuracy(item_coords, defect_pos, rho):
    """Greedy one-to-one nearest match, items -> surviving defects within rho.
    Returns Accuracy@1 = matched / n_items (periodic min-image distances)."""
    k = len(item_coords)
    if k == 0:
        return 1.0
    if len(defect_pos) == 0:
        return 0.0
    used = set()
    matched = 0
    # distance matrix with min-image
    di = item_coords[:, None, :] - defect_pos[None, :, :]
    di -= SIDE * np.round(di / SIDE)
    D = np.sqrt((di ** 2).sum(axis=2))          # [k, n_def]
    order = np.argsort(D.min(axis=1))           # items with closest survivor first
    for i in order:
        js = np.argsort(D[i])
        for j in js:
            if D[i, j] > rho:
                break
            if j not in used:
                used.add(j)
                matched += 1
                break
    return matched / k


def b1_accuracy(item_coords, rho):
    """Lossless dict read at resolution rho: an item is resolvable iff no OTHER
    item lies within rho (else the two are indistinguishable at readout)."""
    k = len(item_coords)
    if k <= 1:
        return 1.0
    di = item_coords[:, None, :] - item_coords[None, :, :]
    di -= SIDE * np.round(di / SIDE)
    D = np.sqrt((di ** 2).sum(axis=2))
    np.fill_diagonal(D, np.inf)
    return float(np.mean(D.min(axis=1) > rho))


def field_accuracy(item_coords, charges, seed):
    s = CGLE(b=B, c=C, N=N, side=SIDE, dt=DT, seed=seed)
    s.seed_vortices(item_coords.tolist(), charges.tolist())
    s.evolve(T)
    pos, _ = s.find_defects()
    return match_accuracy(item_coords, pos, RHO), len(pos)


def prep_items(k, seed):
    """k net-neutral item vortices from projected synthetic embeddings. Odd k gets
    one uncounted ballast antivortex (single vortex is topologically forbidden in a
    periodic box); the ballast is excluded from scoring."""
    emb = synthetic_embeddings(k, seed)
    coords, charges, _ = encode(emb, P, SIDE)
    ballast = None
    if int(np.sum(charges)) != 0:
        # append a corner ballast to force neutrality; excluded from scoring
        bsign = -int(np.sign(np.sum(charges)))
        coords = np.vstack([coords, [[1.0, 1.0]]])
        charges = np.append(charges, bsign)
        ballast = len(charges) - 1
    return coords, charges, ballast


def run_cell(k, seed):
    coords, charges, ballast = prep_items(k, seed)
    score_idx = [i for i in range(len(coords)) if i != ballast]
    sc = coords[score_idx]
    field_acc, n_surv = field_accuracy(coords, charges, seed)
    b1 = b1_accuracy(sc, RHO)
    return {"k": k, "seed": seed, "field_acc": field_acc, "b1_acc": b1,
            "n_survivors": int(n_surv)}


def ncrit(mean_by_k, kgrid):
    best = 0
    for k in kgrid:
        if mean_by_k.get(k, 0.0) >= ACC_BAR:
            best = k
        else:
            break
    return best


def main(smoke=False):
    kgrid = [2, 20, 100] if smoke else K_GRID
    seeds = 2 if smoke else SEEDS
    seal_hash = sealutil.echo_seal()
    t0 = time.time()
    cells = []
    for k in kgrid:
        for seed in range(seeds):
            r = run_cell(k, seed)
            cells.append(r)
            print(f"k={k:3d} seed={seed:2d}: field={r['field_acc']:.2f} "
                  f"B1={r['b1_acc']:.2f} survivors={r['n_survivors']} "
                  f"({time.time()-t0:.0f}s)")

    def agg(field):
        key = "field_acc" if field else "b1_acc"
        return {k: float(np.mean([c[key] for c in cells if c["k"] == k])) for k in kgrid}

    field_mean = agg(True)
    b1_mean = agg(False)
    result = {
        "stage": "h1_capacity" + ("_SMOKE" if smoke else ""),
        "params": {"b": B, "c": C, "N": N, "side": SIDE, "dt": DT, "T": T, "rho": RHO},
        "k_grid": kgrid, "seeds": seeds, "acc_bar": ACC_BAR,
        "cells": cells,
        "field_mean_by_k": field_mean,
        "b1_mean_by_k": b1_mean,
        "field_N_crit": ncrit(field_mean, kgrid),
        "b1_N_crit": ncrit(b1_mean, kgrid),
        "wall_seconds": round(time.time() - t0, 1),
    }
    print("\nfield mean Acc@1 by k:", {k: round(v, 3) for k, v in field_mean.items()})
    print("B1    mean Acc@1 by k:", {k: round(v, 3) for k, v in b1_mean.items()})
    print(f"field N_crit={result['field_N_crit']}  B1 N_crit={result['b1_N_crit']}")

    if smoke:
        scratch = os.path.join(sealutil.HARNESS_DIR, "_smoke_h1.json")
        with open(scratch, "w") as fh:
            json.dump(result, fh, indent=2)
        print(f"\n[SMOKE — UNSEALED] wrote {scratch}. Not a scored verdict.")
    else:
        path = sealutil.write_and_seal("h1_capacity.json", result)
        print(f"\nsealed -> {path}\nprereg  -> {seal_hash}")


if __name__ == "__main__":
    main(smoke="--smoke" in sys.argv)
