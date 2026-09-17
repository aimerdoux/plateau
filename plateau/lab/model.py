"""plateau.lab.model — the recall/loss/presence model over lag and compaction buckets.

Six pure, dependency-free functions (no I/O, no store/bridge access) implementing the
small decay model this refactor's lab uses to score a bridge_version's effect on recall
before promoting it. Every quantity is a fraction in (conceptually) [0, 1] — recall,
loss, presence — except `alpha`, the model's ceiling recall at zero lag, which callers
may fit slightly outside that range; only `presence()` is asked to clamp its result.

    R = alpha * (1 - phi * lambda * (1 - pi))

  alpha  — ceiling recall at lag 0 (before any decay has had a chance to act).
  phi    — how far decay has progressed for this bucket (0 = none yet, 1 = fully).
  lambda — how much of a fact WOULD be lost to decay with nothing compensating for it;
           measured on the arm with no bridge: lambda_hat = 1 - r_native / alpha.
  pi     — how much of that loss the bridge's injected context actually covers
           (0 = no help, 1 = fully covers it): pi_hat = 1 - (1 - r_bridge/alpha) / lambda.

See `docs/harness-0.3/PLAN.md` "Lab model" for the contract these six functions follow,
and `model.toml` (repo root) for the D-038 run-1 numbers they are fit against.
"""

from __future__ import annotations

from typing import Any, Dict, Optional


def recall(alpha: float, phi: float, lam: float, pi: float) -> float:
    """R = alpha * (1 - phi * lam * (1 - pi))."""
    return alpha * (1 - phi * lam * (1 - pi))


def auc(r0: float, r1: float, r2: float) -> float:
    """Trapezoid-weighted area under the 3-bucket recall-vs-lag curve:
    (r0 + 2*r1 + r2) / 4."""
    return (r0 + 2 * r1 + r2) / 4


def presence(alpha: float, lam: float, r_bridge: float) -> Optional[float]:
    """pi_hat = 1 - (1 - r_bridge/alpha) / lam, clamped to [0, 1].

    None when lam == 0: a native run with no measured loss leaves nothing for the
    bridge's presence to have covered, so the ratio is undefined (not infinite, not
    zero) rather than a number a caller could mistake for a real estimate.
    """
    if lam == 0:
        return None
    pi_hat = 1 - (1 - r_bridge / alpha) / lam
    if pi_hat < 0.0:
        return 0.0
    if pi_hat > 1.0:
        return 1.0
    return pi_hat


def loss(alpha: float, r_native: float) -> float:
    """lambda_hat = 1 - r_native / alpha."""
    return 1 - r_native / alpha


def break_even_chars(
    rederiv_native: float,
    rederiv_bridge: float,
    mean_read_tokens: float,
    inject_tokens: float,
) -> float:
    """Net tokens the bridge saves this run: tokens saved by the re-derivations it let
    the agent skip, minus what it cost to inject. Positive means the bridge pays for
    itself.

        (rederiv_native - rederiv_bridge) * mean_read_tokens - inject_tokens
    """
    return (rederiv_native - rederiv_bridge) * mean_read_tokens - inject_tokens


def _lag_index(key: Any) -> Optional[int]:
    """The integer lag index a by-lag dict key names (`'l2'`, `'c2'`, `'2'`, `2`, ...):
    its trailing run of digits. None for a key with no digits (never matched)."""
    if isinstance(key, bool):
        return None
    if isinstance(key, int):
        return key
    digits = "".join(ch for ch in str(key) if ch.isdigit())
    return int(digits) if digits else None


def crossover_lag(
    alpha: float,
    lam_by_lag: Dict[Any, float],
    pi_by_lag: Dict[Any, float],
) -> Optional[int]:
    """The first lag bucket (ascending) where `recall(bridge)` — using the measured
    presence for that bucket — is LESS than `recall(native)` at pi=0, given the same
    alpha/lambda. This is a regression signal (the bridge measurably hurting recall at
    that lag), not the expected case. phi is fixed at 1.0: each bucket already names a
    discrete lag, so no further within-bucket progression applies. A lag present in
    `lam_by_lag` but absent from `pi_by_lag` is treated as pi=0 (no measured presence,
    so native and bridge tie there — never a crossover on its own). Lag keys may be
    bare ints/strings (`2`) or prefixed (`l2`, `c2`); the two dicts are matched by their
    trailing integer, not by literal key equality. Returns None if no bucket crosses
    (the normal, healthy case) or if `lam_by_lag` is empty.
    """
    pi_by_index: Dict[int, float] = {}
    for key, value in (pi_by_lag or {}).items():
        idx = _lag_index(key)
        if idx is not None:
            pi_by_index[idx] = value

    buckets = []
    for key, lam in (lam_by_lag or {}).items():
        idx = _lag_index(key)
        if idx is not None:
            buckets.append((idx, lam))
    buckets.sort(key=lambda pair: pair[0])

    for idx, lam in buckets:
        pi = pi_by_index.get(idx, 0.0)
        r_native = recall(alpha, 1.0, lam, 0.0)
        r_bridge = recall(alpha, 1.0, lam, pi)
        if r_bridge < r_native:
            return idx
    return None
