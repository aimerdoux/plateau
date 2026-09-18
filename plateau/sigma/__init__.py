"""plateau.sigma — the Σ operator.

`Σ = ⟨ ι , V , Φ , γ ⟩`: a verifier-carrying, fossil-backed fixpoint operator that runs ON
TOP of Plateau's bounded-context + content-addressed-hashing substrate.

The §10 inner slice (anchored first, the anti-drift principle applied to the build):
  models      — the four carriers; §3 V-immutability enforced structurally at construction.
  fossils     — Φ on plateau.integrity.file_hash; put / get / reuse_report, cross-session dedup.
  evaluate    — V against a candidate, programmatic + test gates (llm_judge deferred).
  run_schema  — γ inner loop with REAL Φ-backed state; extract_schema inversion → candidate.

The Σ experiment harness (Phase 1: UNPAID build + deterministic stub-verify; runs NO live model):
  corpus      — index the operator's REAL local transcripts → candidate Σ schemas (DATA-only,
                secret VALUES redacted, local-only).
  valuate     — (a) the WITH/WITHOUT A/B capability harness (Σ pattern vs plain same-model
                baseline, both scored against the SAME objective V); (b) the §4 two-ladder
                valuation v(M) = (λ*_len, λ*_depth). `model` is an INJECTED callable.
  refine      — 𝒮, the outer self-improvement loop; §3 ENFORCED (V read-only, frozen_hash kept,
                refine-guard asserts on any V change).
  experiment  — pre-registration manifest, HASHED (plateau.integrity.file_hash) before any run.

llm_judge gates remain deferred. `valuate`/`refine`/the experiment use INJECTED models so the
Phase-1 tests run deterministically with NO live LLM.
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
from .refine import refine
from .valuate import (
    ABResult,
    ArmResult,
    LadderCurve,
    LadderRung,
    ModelValue,
    ab_capability,
    valuate,
)
from .corpus import (
    Deliverable,
    IndexStats,
    detect_deliverables,
    index_corpus,
    parse_session,
    redact,
    synthesize_candidate,
)
from .experiment import (
    PreReg,
    TaskSpec,
    build_manifest,
    prereg_from_corpus,
    task_from_corpus_row,
    verify_prereg,
    write_prereg,
)

__all__ = [
    # inner slice
    "Intent", "Gate", "Verifier", "Fossil", "LoopConfig", "Schema",
    "FossilStore", "ReuseStats",
    "GateResult", "GateResults", "evaluate", "register_check", "get_check",
    "RunResult", "run_schema", "extract_schema",
    # experiment harness
    "refine",
    "ABResult", "ArmResult", "LadderCurve", "LadderRung", "ModelValue",
    "ab_capability", "valuate",
    "Deliverable", "IndexStats", "detect_deliverables", "index_corpus",
    "parse_session", "redact", "synthesize_candidate",
    "PreReg", "TaskSpec", "build_manifest", "prereg_from_corpus",
    "task_from_corpus_row", "verify_prereg", "write_prereg",
]
