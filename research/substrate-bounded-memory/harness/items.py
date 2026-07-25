"""Item -> (x, y, charge) encoding for D-036. No LLM in H1: synthetic 768-dim
Gaussian vectors stand in for embeddings (H1 capacity is agnostic to semantics;
only H2 needs real embeddings). A fixed seeded random projection maps 768 -> 2,
exactly the lossy Pi the PREREG's B1 control isolates.

Net-neutrality (periodic BCs force total winding 0) is satisfied by a MEDIAN
SPLIT of a third projected coordinate into equal +/- halves — a data-derived sign
that is guaranteed balanced. Documented as part of the sealed method.
"""
from __future__ import annotations

import numpy as np

EMBED_DIM = 768


def projection_matrix(seed: int = 20240117):
    """Fixed, sealed 768->3 Gaussian random projection (x, y, sign-axis)."""
    rng = np.random.default_rng(seed)
    return rng.standard_normal((EMBED_DIM, 3)) / np.sqrt(EMBED_DIM)


def synthetic_embeddings(k: int, seed: int):
    rng = np.random.default_rng(seed)
    return rng.standard_normal((k, EMBED_DIM))


def encode(embeddings, P, side: float, margin: float = 0.0):
    """Project embeddings -> (x, y) in [margin, side-margin]^2 and a net-neutral
    charge from the median split of the 3rd projected axis. Returns (coords[k,2],
    charges[k], raw2[k,2]) where raw2 is the pre-rescale projection (for B1)."""
    proj = embeddings @ P                      # [k,3]
    raw2 = proj[:, :2]
    # robust rescale of each axis to [margin, side-margin] by empirical min/max
    lo = raw2.min(axis=0)
    hi = raw2.max(axis=0)
    span = np.where(hi > lo, hi - lo, 1.0)
    coords = margin + (raw2 - lo) / span * (side - 2 * margin)
    # net-neutral charge: median split of axis 3 (exactly balanced for even k)
    a3 = proj[:, 2]
    med = np.median(a3)
    charges = np.where(a3 >= med, 1, -1).astype(int)
    # enforce exact neutrality if k is odd or ties land unevenly
    imbalance = int(np.sum(charges))
    if imbalance != 0:
        order = np.argsort(np.abs(a3 - med))   # flip the most-ambiguous signs
        flip_to = -1 if imbalance > 0 else 1
        need = abs(imbalance) // 2
        flipped = 0
        for idx in order:
            if charges[idx] == -flip_to:
                charges[idx] = flip_to
                flipped += 1
                if flipped >= need:
                    break
    return coords, charges, raw2
