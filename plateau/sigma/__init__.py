"""plateau.sigma — the Σ operator (smallest shippable slice, §10).

`Σ = ⟨ ι , V , Φ , γ ⟩`: a verifier-carrying, fossil-backed fixpoint operator that runs ON
TOP of Plateau's bounded-context + content-addressed-hashing substrate. This package ships
the §10 slice only:

  models      — the four carriers; §3 V-immutability enforced structurally at construction.
  fossils     — Φ on plateau.integrity.file_hash; put / get / reuse_report, cross-session dedup.
  evaluate    — V against a candidate, programmatic + test gates (llm_judge deferred).
  run_schema  — γ inner loop with REAL Φ-backed state; extract_schema inversion → candidate.

Deferred to AFTER the slice (do NOT assume present): refine() (𝒮, the outer loop),
valuate() (the two-ladder valuation), and llm_judge gates. The build order is the anti-drift
principle applied to itself: anchor the inner loop first.
"""

from __future__ import annotations

from .models import Fossil, Gate, Intent, LoopConfig, Schema, Verifier
from .fossils import FossilStore, ReuseStats
from .evaluate import (
    GateResult,
    GateResults,
    evaluate,
    register_check,
    get_check,
)
from .run_schema import RunResult, extract_schema, run_schema

__all__ = [
    "Intent", "Gate", "Verifier", "Fossil", "LoopConfig", "Schema",
    "FossilStore", "ReuseStats",
    "GateResult", "GateResults", "evaluate", "register_check", "get_check",
    "RunResult", "run_schema", "extract_schema",
]
