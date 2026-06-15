"""plateau.sigma.experiment — pre-registration of the Σ A/B experiment (§4).

The protocol is PRE-REGISTERED and HASHED before any run. The frozen manifest IS the protocol:
the (later, paid) run executes exactly it, and the manifest hash lets anyone confirm the
protocol was not edited after seeing results. This is the §4 discipline ("pre-registration
manifest hashed + stored before any run") applied to the whole experiment.

A manifest records, deterministically and in full:
  - sampled       : the corpus deliverables under test (session_hash, deliverable, frozen_hash
                    of the objective V per task) — the EXACT tasks, fixed in advance.
  - verifier_per_task : the objective V's frozen_hash for each task (the judge is fixed + external).
  - metric        : how an arm is scored (gate_pass against the objective V — never a self-judge).
  - tau           : the pass threshold τ.
  - arms          : ["WITH", "WITHOUT"] — the Σ pattern vs the plain same-model baseline.
  - k, epsilon    : the §4 valuation parameters (runs per rung, ε for λ*).
  - negative_result_is_valid : TRUE — a result where WITH does NOT beat WITHOUT is first-class.

`write_prereg(...)` serializes the manifest to disk DETERMINISTICALLY (sorted keys), then hashes
the on-disk bytes with `plateau.integrity.file_hash` — the one canonical measurement. The returned
PreReg carries that hash. Nothing in this module runs a model; Phase-1 builds + hashes the
protocol only.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Optional

from plateau.integrity import file_hash


# the metric is fixed vocabulary: an arm is scored by GATE-PASS against the OBJECTIVE V only.
# (A6: never a judge an arm authored. "self_judge" is explicitly NOT an allowed metric.)
_ALLOWED_METRICS = ("gate_pass_objective_v",)


@dataclass
class TaskSpec:
    """One pre-registered task: a corpus deliverable + the objective V it is scored against."""
    task_id: str
    session_hash: str
    deliverable_kind: str
    deliverable_summary: str
    external_anchor: str             # the V's external anchor (resolves OUTSIDE the loop, §3.4)
    verifier_frozen_hash: str        # the objective V, fixed in advance — the judge can't drift
    gate_ids: list = field(default_factory=list)


@dataclass
class PreReg:
    """A hashed pre-registration. `manifest_hash` is file_hash of the on-disk manifest bytes."""
    path: str
    manifest_hash: str
    manifest: dict


def build_manifest(
    *,
    tasks: list,
    tau: float,
    k: int,
    epsilon: float,
    metric: str = "gate_pass_objective_v",
    notes: str = "",
) -> dict:
    """Assemble the (not-yet-hashed) manifest dict. Validates the rigor invariants up front."""
    if metric not in _ALLOWED_METRICS:
        raise ValueError(
            f"metric {metric!r} not allowed; an arm must be scored by the OBJECTIVE V only "
            f"(A6 anti-drift). Allowed: {_ALLOWED_METRICS}."
        )
    if not (0.0 <= tau <= 1.0):
        raise ValueError("tau (pass threshold) must be in [0, 1]")
    if k < 1:
        raise ValueError("k (runs per rung) must be >= 1")
    if not (0.0 <= epsilon < 1.0):
        raise ValueError("epsilon must be in [0, 1)")
    if not tasks:
        raise ValueError("a pre-registration with zero tasks proves nothing; need >= 1 task")

    # every task must carry an external anchor + a frozen V hash, or it is not admissible.
    task_rows = []
    for t in tasks:
        if not t.external_anchor:
            raise ValueError(f"task {t.task_id!r}: missing external_anchor (§3.4)")
        if not t.verifier_frozen_hash:
            raise ValueError(f"task {t.task_id!r}: missing objective verifier frozen_hash")
        task_rows.append({
            "task_id": t.task_id,
            "session_hash": t.session_hash,
            "deliverable_kind": t.deliverable_kind,
            "deliverable_summary": t.deliverable_summary,
            "external_anchor": t.external_anchor,
            "verifier_frozen_hash": t.verifier_frozen_hash,
            "gate_ids": list(t.gate_ids),
        })

    return {
        "protocol": "sigma-ab-v1",
        "description": "WITH (Σ pattern) vs WITHOUT (plain same-model baseline), scored against "
                       "the SAME objective V per task. Negative results are first-class.",
        "arms": ["WITH", "WITHOUT"],
        "metric": metric,
        "tau": tau,
        "k": k,
        "epsilon": epsilon,
        "rigor": {
            "same_base_model_both_arms": True,
            "objective_v_only": True,
            "arm_never_scored_by_self_authored_judge": True,   # A6
            "negative_result_is_valid": True,                  # pattern may NOT help — that's fine
            "no_fabrication": True,
        },
        "sampled": task_rows,
        "verifier_per_task": {t["task_id"]: t["verifier_frozen_hash"] for t in task_rows},
        "notes": notes,
    }


def write_prereg(manifest: dict, out_path: str) -> PreReg:
    """Serialize the manifest DETERMINISTICALLY, then hash the on-disk bytes (§4).

    The hash is computed AFTER the bytes land on disk, with `plateau.integrity.file_hash` — the
    exact measurement the rest of Plateau seals with. The hash is recorded in a sidecar
    ``<out_path>.hash`` so the protocol's identity is itself an on-disk, re-checkable referent;
    the run later re-hashes the manifest and confirms it equals this value before executing."""
    os.makedirs(os.path.dirname(os.path.abspath(out_path)) or ".", exist_ok=True)
    blob = json.dumps(manifest, sort_keys=True, separators=(",", ":"))
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(blob)
    h = file_hash(out_path)            # hash the bytes that are actually on disk
    with open(out_path + ".hash", "w", encoding="utf-8") as f:
        f.write(h + "\n")
    return PreReg(path=out_path, manifest_hash=h, manifest=manifest)


def verify_prereg(prereg: PreReg) -> bool:
    """Re-hash the on-disk manifest and confirm it still matches `prereg.manifest_hash`.

    The frozen manifest IS the protocol; this is the check the paid run runs FIRST — if the
    manifest bytes changed after pre-registration, the protocol was edited and the run must
    refuse. Pure re-measurement; executes nothing."""
    if not os.path.exists(prereg.path):
        return False
    return file_hash(prereg.path) == prereg.manifest_hash


def task_from_corpus_row(row: dict) -> TaskSpec:
    """Adapt one corpus index row ({session_hash, deliverable, schema}) into a pre-reg TaskSpec.

    The objective V is the schema's verifier (its frozen_hash + external_anchor); the task_id is
    derived deterministically from the session + frozen_hash so the manifest is stable."""
    deliverable = row["deliverable"]
    verifier = row["schema"]["verifier"]
    sess = row["session_hash"]
    fh = verifier["frozen_hash"]
    task_id = f"{sess[:16]}:{fh[7:23]}"
    return TaskSpec(
        task_id=task_id,
        session_hash=sess,
        deliverable_kind=deliverable.get("kind", "?"),
        deliverable_summary=deliverable.get("summary", ""),
        external_anchor=verifier["external_anchor"],
        verifier_frozen_hash=fh,
        gate_ids=[g["id"] for g in verifier.get("gates", [])],
    )


def prereg_from_corpus(rows: list, *, out_path: str, tau: float, k: int,
                       epsilon: float, notes: str = "") -> Optional[PreReg]:
    """Convenience: build + write + hash a pre-registration directly from corpus index rows.

    Returns None if `rows` is empty (nothing admissible to pre-register — no fabrication)."""
    if not rows:
        return None
    tasks = [task_from_corpus_row(r) for r in rows]
    manifest = build_manifest(tasks=tasks, tau=tau, k=k, epsilon=epsilon, notes=notes)
    return write_prereg(manifest, out_path)
