"""plateau.sigma.ab_run_hard — the LIVE, PAID, HEADROOM A/B driver (real `claude -p`).

The DISCRIMINATING round the FLAT N=7 result could not deliver. Protocol:

  PRE-REG (before any WITH run): build + hash a manifest declaring the harder sample, the
          objective V per task, the HEADROOM-FILTER RULE, the metric (recovery-rate on
          baseline-failing tasks), both arms, k, ε, negative_result_is_valid=true.

  PHASE A — HEADROOM FILTER (objective): run ARM_WITHOUT (ONE plain `claude -p` pass) on EVERY
          hard candidate; record baseline pass/fail. The tasks WITHOUT FAILS are the measured-
          headroom core set; the tasks WITHOUT PASSES are control candidates.

  PHASE B — RECOVERY: run ARM_WITH (run_schema's Φ-hydrated Σ loop, max_iters=6, depth compounds)
          on every baseline-FAILING task. MEASURE RECOVERY RATE = (# WITH passes) / (# WITHOUT
          fails). Also run ARM_WITH on up to N_CONTROL baseline-PASSING tasks as CONTROLS to
          confirm WITH does NOT regress.

RIGOR: both arms call the SAME base model (`claude -p`). Gates are objective fixed code in
ab_tasks_hard.py, pre-verified sound (good-passes/bad-fails), authored by neither arm (A6). Every
number is from a real paid run — NO fabrication. Serialized. Checkpoints to ab_runs_hard/<task>.json
are resumable. On rate-limit back off 60-90s, retry <=3x; if limited out, bail with a resumable
checkpoint (PARTIAL).

Reuses the live `claude_call`, `_extract_code`, `_make_with_model`, `_without_pass` from ab_run.py
verbatim — same base model, same adapter, same scoring path. The ONLY differences from ab_run.py
are the harder task set, the headroom-filter sequencing, and max_iters=6.
"""

from __future__ import annotations

import json
import os
import time

from . import ab_tasks_hard
from .ab_run import _make_with_model, _without_pass, claude_call  # noqa: F401  (reuse live arms)
from .evaluate import evaluate
from .experiment import build_manifest, write_prereg, verify_prereg, PreReg, TaskSpec
from .fossils import FossilStore
from .models import Intent, LoopConfig, Schema
from .run_schema import run_schema

HERE = os.path.dirname(os.path.abspath(__file__))
AB_RUNS_HARD = os.path.join(HERE, "ab_runs_hard")
FOSSIL_ROOT = os.path.join(AB_RUNS_HARD, "_fossils")
PREREG_PATH = os.path.join(HERE, "prereg_ab_hard.json")

_MAX_ITERS = 6                 # deeper than the FLAT round's 4 — give the loop real headroom to climb
_N_CONTROL = 3                 # how many baseline-PASSING tasks to also run WITH on (regression check)
_COST_PER_CALL = 1.0


# ----------------------------------------------------------- pre-registration ----

def preregister() -> PreReg:
    """Build + hash the manifest BEFORE any WITH run. Declares the full discriminating protocol."""
    specs = ab_tasks_hard.hard_task_specs()
    tasks = []
    for sp in specs:
        v = ab_tasks_hard.verifier_for(sp)
        tasks.append(TaskSpec(
            task_id=sp["task_id"],
            session_hash="sigma-ab-hard-live",
            deliverable_kind="committed_file|sealed_verdict",   # corpus shapes these analogues mirror
            deliverable_summary=sp["kpi"],
            external_anchor=v.external_anchor,
            verifier_frozen_hash=v.frozen_hash,
            gate_ids=[g.id for g in v.gates],
        ))
    manifest = build_manifest(
        tasks=tasks, tau=1.0, k=1, epsilon=0.0,
        metric="gate_pass_objective_v",
        notes=(
            "DISCRIMINATING (headroom) round. HARDER sample than t1-t7 (multi-constraint / deep / "
            "edge-case-heavy), each with an OBJECTIVE programmatic gate pre-verified SOUND "
            "(good-passes/bad-fails) in a fresh subprocess BEFORE any paid call; gate authored by "
            "neither arm (A6). HEADROOM-FILTER RULE: run ARM_WITHOUT (one claude -p pass) on every "
            "task; the tasks where WITHOUT FAILS the gate (score<tau) are the measured-headroom "
            "core set, the tasks where WITHOUT PASSES are controls. METRIC: recovery-rate = "
            "(#ARM_WITH passes) / (#ARM_WITHOUT fails) on the baseline-failing core set. "
            "ARM_WITH = run_schema Φ-hydrated Σ loop, max_iters=6, depth compounds. CONTROLS: "
            "ARM_WITH is also run on up to 3 baseline-PASSING tasks to confirm WITH does not "
            "regress. Both arms = SAME base model (claude -p). negative_result_is_valid=TRUE: if "
            "WITH recovers ~0 of the baseline failures that is a real NEGATIVE; if WITHOUT fails ~0 "
            "tasks that is INCONCLUSIVE_CEILING (set not hard enough). NO FABRICATION."
        ),
    )
    return write_prereg(manifest, PREREG_PATH)


# --------------------------------------------------------------- arm runners ----

def _schema_for(spec: dict, verifier) -> Schema:
    intent = Intent(
        goal=spec["goal"],
        target_invariants=(spec["kpi"],),
        constraints=("output only the deliverable in the requested format",),
        excluded_paths=(),
        source_session_hash="sigma-ab-hard-live",
    )
    loop = LoopConfig(
        generator_policy="claude-p-live",
        max_iterations=_MAX_ITERS,
        stop_rule="either",
        state_handle=f"abh/{spec['task_id']}/{verifier.frozen_hash[7:23]}",
        fossil_write=True,
    )
    return Schema(intent=intent, verifier=verifier, loop=loop, phi=())


def run_without(spec: dict) -> dict:
    """ARM_WITHOUT — one plain claude -p pass, scored against the objective V. The headroom probe."""
    verifier = ab_tasks_hard.verifier_for(spec)
    log: list = []
    cand, res = _without_pass(spec["goal"], verifier, log)
    return {
        "all_pass": bool(res.all_pass),
        "feasibility": round(res.feasibility, 6),
        "iterations": 1,
        "calls": sum(log),
        "cost": sum(log) * _COST_PER_CALL,
        "candidate_code": cand.get("code", "")[:6000],
    }


def run_with(spec: dict) -> dict:
    """ARM_WITH — run_schema's Φ-hydrated Σ loop, depth compounds, max_iters=6."""
    verifier = ab_tasks_hard.verifier_for(spec)
    store = FossilStore(os.path.join(FOSSIL_ROOT, spec["task_id"], "with"))
    log: list = []
    schema = _schema_for(spec, verifier)
    model = _make_with_model(spec["goal"], verifier, log)
    rr = run_schema(schema, model, store)
    return {
        "all_pass": bool(rr.all_pass),
        "feasibility": round(rr.feasibility, 6),
        "iterations": rr.iterations,
        "calls": sum(log),
        "cost": sum(log) * _COST_PER_CALL,
        "feasibility_trace": [round(x, 6) for x in rr.feasibility_trace],
        "fossils_written": len(rr.fossils_written),
        "stop_reason": rr.stop_reason,
        "candidate_code": (rr.best_candidate or {}).get("code", "")[:6000]
            if isinstance(rr.best_candidate, dict) else "",
    }


# ----------------------------------------------------------------- driver ----

def _ckpt_path(tid: str) -> str:
    return os.path.join(AB_RUNS_HARD, f"{tid}.json")


def _load_ckpt(tid: str) -> dict:
    p = _ckpt_path(tid)
    if os.path.exists(p):
        with open(p) as f:
            return json.load(f)
    return {}


def _save_ckpt(tid: str, row: dict) -> None:
    with open(_ckpt_path(tid), "w") as f:
        json.dump(row, f, indent=2)


def run_phase_a(specs) -> dict:
    """PHASE A: baseline ARM_WITHOUT on every task. Returns {tid: bool baseline_pass}. Resumable."""
    print("[abh] === PHASE A: HEADROOM FILTER (ARM_WITHOUT baseline on all tasks) ===", flush=True)
    baseline = {}
    for sp in specs:
        tid = sp["task_id"]
        row = _load_ckpt(tid)
        if "without" in row and row["without"]:
            baseline[tid] = bool(row["without"]["all_pass"])
            print(f"[abh]   {tid}: WITHOUT (resumed) pass={baseline[tid]}", flush=True)
            continue
        row.setdefault("task_id", tid)
        row["depth"] = sp["depth"]
        row["kpi"] = sp["kpi"]
        row["frozen_hash"] = ab_tasks_hard.verifier_for(sp).frozen_hash
        try:
            row["without"] = run_without(sp)
        except Exception as e:
            row["without_error"] = f"{type(e).__name__}: {e}"
            _save_ckpt(tid, row)
            print(f"[abh]   {tid}: WITHOUT ERROR {row['without_error']}", flush=True)
            raise
        baseline[tid] = bool(row["without"]["all_pass"])
        row["ts_without"] = time.time()
        _save_ckpt(tid, row)
        print(f"[abh]   {tid}: WITHOUT pass={baseline[tid]} feas={row['without']['feasibility']}", flush=True)
    return baseline


def run_phase_b(specs, baseline: dict) -> None:
    """PHASE B: ARM_WITH on every baseline-FAILING task + up to _N_CONTROL baseline-PASSING tasks."""
    spec_by_id = {s["task_id"]: s for s in specs}
    failing = [t for t in spec_by_id if not baseline.get(t, False)]
    passing = [t for t in spec_by_id if baseline.get(t, False)]
    controls = passing[:_N_CONTROL]
    targets = failing + controls
    print(f"[abh] === PHASE B: RECOVERY ({len(failing)} baseline-FAIL) + "
          f"CONTROLS ({len(controls)} baseline-PASS) ===", flush=True)
    for tid in targets:
        sp = spec_by_id[tid]
        row = _load_ckpt(tid)
        if "with" in row and row["with"]:
            w = row["with"]
            print(f"[abh]   {tid}: WITH (resumed) pass={w['all_pass']} iters={w['iterations']} "
                  f"trace={w.get('feasibility_trace')}", flush=True)
            continue
        row["is_control"] = (tid in controls)
        try:
            row["with"] = run_with(sp)
        except Exception as e:
            row["with_error"] = f"{type(e).__name__}: {e}"
            _save_ckpt(tid, row)
            print(f"[abh]   {tid}: WITH ERROR {row['with_error']}", flush=True)
            raise
        row["ts_with"] = time.time()
        _save_ckpt(tid, row)
        w = row["with"]
        print(f"[abh]   {tid}: WITH pass={w['all_pass']} iters={w['iterations']} "
              f"calls={w['calls']} trace={w['feasibility_trace']} "
              f"({'CONTROL' if row['is_control'] else 'RECOVERY'})", flush=True)


def main():
    os.makedirs(AB_RUNS_HARD, exist_ok=True)
    specs = ab_tasks_hard.hard_task_specs()

    # 1) PRE-REGISTER + hash BEFORE any WITH run.
    pr = preregister()
    assert verify_prereg(pr), "prereg failed to re-verify immediately after writing"
    print(f"[abh] pre-registered manifest hash = {pr.manifest_hash}", flush=True)

    # 2) PHASE A — headroom filter.
    baseline = run_phase_a(specs)
    n = len(specs)
    n_fail = sum(1 for t in baseline if not baseline[t])
    print(f"[abh] HEADROOM: baseline_fail = {n_fail}/{n}", flush=True)

    # 3) PHASE B — recovery + controls. (Even if n_fail==0 we still run controls to exercise WITH.)
    run_phase_b(specs, baseline)
    print("[abh] ALL DONE", flush=True)


if __name__ == "__main__":
    main()
