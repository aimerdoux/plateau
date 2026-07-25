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


# raw projected axes are ~N(0,1) (emb~N(0,1), P~N(0,1/768)); SCALE*3sigma ~ 60
# fills the 128 box centred at 64; the small tails wrap periodically. Fixed and
# k-independent -> no degenerate small-k stacking (the old min/max rescale put a
# lone point at the origin).
SCALE = 20.0


def encode(embeddings, P, side: float):
    """Project embeddings -> (x, y) via a fixed centred periodic map, and an
    EXACTLY net-neutral charge from the median split of the 3rd projected axis.
    Requires an even number of items (odd counts cannot be charge-balanced, and a
    single vortex is topologically forbidden in a periodic box). Returns
    (coords[k,2], charges[k], raw2[k,2]); raw2 is the pre-map projection (B1)."""
    k = len(embeddings)
    if k % 2 != 0:
        raise ValueError("encode requires an even item count (net-neutral charge)")
    proj = embeddings @ P                      # [k,3]
    raw2 = proj[:, :2]
    coords = (raw2 * SCALE + side / 2.0) % side
    # exactly balanced sign: the k/2 items above the median are +1, the rest -1
    a3 = proj[:, 2]
    order = np.argsort(a3)
    charges = np.empty(k, dtype=int)
    charges[order[: k // 2]] = -1
    charges[order[k // 2:]] = +1
    return coords, charges, raw2
