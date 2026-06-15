"""plateau.sigma.compress_run — the LIVE, PAID compression/decompression experiment driver.

THESIS UNDER TEST: a real deliverable D originally took a MULTI-TURN session. The Σ schema
compresses that trajectory into a short recipe. Can a FRESH single `claude -p` pass prompted with
ONLY the Σ schema reproduce a deliverable that passes the ORIGINAL's objective V — i.e. one-shot
what took N turns — where the raw turn-1 ask (COLD) cannot?

DESIGN (one pass per arm; testing DECOMPRESSION, not iteration):
  ARM_COLD  = ONE `claude -p` pass given the raw turn-1 user ask (ι_NAIVE).
  ARM_SIGMA = ONE `claude -p` pass given ONLY the distilled Σ schema (the compressed recipe).
  Both arms' replies are written to a temp package and scored against the SAME objective V — the
  ORIGINAL in-session test suite, authored by NEITHER arm (A6). D_orig is also scored vs V as a
  sanity reference (must pass).

RIGOR: objective V only; leakage-guarded (Σ prompt != D, checked + dropped programmatically);
both arms EXACTLY ONE pass, same base model (`claude -p`); NO FABRICATION; negative-capable;
the manifest is PRE-REGISTERED + hashed BEFORE any paid run. Checkpoints to
ab_runs_compress/<task>.json are resumable. Rate-limit backoff 60-90s, <=3 retries.
"""

from __future__ import annotations

import json
import os
import time

from plateau.integrity import file_hash

from .ab_run import claude_call            # reuse the SAME live base-model callable
from .compress_eval import run_v, reassemble_original
from .compress_tasks import (CompressTask, build_sigma_schema, leakage_check, select_tasks)

HERE = os.path.dirname(os.path.abspath(__file__))
RUNS = os.path.join(HERE, "ab_runs_compress")
PREREG_PATH = os.path.join(HERE, "prereg_compress.json")


# --------------------------------------------------------------- pre-registration ----

def _v_anchor(task: CompressTask) -> tuple:
    """The objective V's identity: a content hash of the ORIGINAL test source (the frozen judge)
    + the on-disk test file as the external anchor (resolves OUTSIDE any loop, §3.4)."""
    import hashlib
    vh = "sha256:" + hashlib.sha256(task.test_src.encode()).hexdigest()
    # external anchor = the real on-disk test file path for this session, if locatable
    anchor = f"{task.session_file}:{task.test_name}"
    return vh, anchor


def build_and_prereg(tasks: list) -> dict:
    """Build the leakage-guarded task set, then write + hash the pre-registration manifest.

    Returns {manifest, manifest_hash, kept, dropped_leak}. Frozen BEFORE any paid call."""
    os.makedirs(RUNS, exist_ok=True)
    kept, dropped = [], []
    for t in tasks:
        t.sigma_schema = build_sigma_schema(t)
        leaked, ratio, substr = leakage_check(t)
        row = {
            "task_id": t.task_id,
            "session_file": t.session_file,
            "n_turns_in_original": t.n_turns,
            "n_user_prompts": t.n_prompts,
            "pkg": t.pkg,
            "test_name": t.test_name,
            "v_assert_count": t.n_asserts,
            "v_test_funcs": t.n_tests,
            "impl_files": sorted(t.impl_files.keys()),
            "leakage_ratio": ratio,
            "leakage_substring_hit": substr,
        }
        vh, anchor = _v_anchor(t)
        row["verifier_frozen_hash"] = vh
        row["external_anchor"] = anchor
        if leaked:
            dropped.append(row)
        else:
            kept.append(row)

    manifest = {
        "protocol": "sigma-compress-v1",
        "thesis": ("A multi-turn deliverable D is compressed by extract_schema into a short Σ "
                   "schema. Can a FRESH single `claude -p` pass given ONLY the Σ schema reproduce a "
                   "D that passes the ORIGINAL objective V, where the raw turn-1 ask (COLD) cannot?"),
        "arms": {
            "COLD": "one claude -p pass, given the raw turn-1 user ask (iota_naive) verbatim.",
            "SIGMA": "one claude -p pass, given ONLY the distilled Σ schema (compressed recipe).",
        },
        "passes_per_arm": 1,
        "same_base_model_both_arms": "claude -p (Claude Code CLI)",
        "metric": "gate_pass_objective_v",
        "objective_v": ("the ORIGINAL in-session test suite (unittest/pytest), run in a fresh "
                        "subprocess against the arm's reproduced package. Authored by NEITHER arm. "
                        "Pass iff the runner reports success with >=1 test run and 0 failures."),
        "tau": 1.0,
        "sanity_reference": "D_orig is scored vs V and MUST pass (validates V soundness).",
        "leakage_guard": {
            "rule": ("Σ schema must NOT contain impl D verbatim/near-verbatim. Checked by "
                     "normalized-substring containment AND max per-file line-overlap; DROP if "
                     "substring-hit OR overlap > 0.30. The schema carries the RECIPE + paid "
                     "sub-results (contract derived from the TEST/V, not from D), never the dish."),
            "overlap_threshold": 0.30,
            "kept": len(kept),
            "dropped_leak": len(dropped),
        },
        "rigor": {
            "objective_v_only": True,
            "arm_never_authors_v": True,
            "one_pass_each_arm": True,
            "leakage_guarded": True,
            "no_fabrication": True,
            "negative_result_is_valid": True,
        },
        "selection_criteria": ("self-contained (stdlib-only) python package deliverables anchored "
                               "to ON-DISK ground truth, from genuinely multi-turn sessions "
                               "(>=3 user prompts, >=10 turns), with a substantive objective V "
                               "(>=2 asserts). Environment-bound / third-party-coupled deliverables "
                               "DROPPED (not reproducible-in-principle)."),
        "tasks": sorted(kept, key=lambda r: (-r["v_assert_count"], r["task_id"])),
        "dropped_for_leakage": dropped,
        "notes": ("CEILING rule: if BOTH arms pass on most tasks, the set is too easy (ceiling) — "
                  "reported honestly. enhanced <=> SIGMA passes V where COLD fails. SIGMA~COLD => "
                  "schema added nothing. Negative is first-class."),
    }

    blob = json.dumps(manifest, sort_keys=True, separators=(",", ":"))
    with open(PREREG_PATH, "w", encoding="utf-8") as f:
        f.write(blob)
    h = file_hash(PREREG_PATH)
    with open(PREREG_PATH + ".hash", "w", encoding="utf-8") as f:
        f.write(h + "\n")
    return {"manifest": manifest, "manifest_hash": h, "kept": kept, "dropped_leak": dropped}


def verify_prereg(manifest_hash: str) -> bool:
    return os.path.exists(PREREG_PATH) and file_hash(PREREG_PATH) == manifest_hash


# --------------------------------------------------------------- arm runners ----

def _ckpt(tid: str) -> str:
    return os.path.join(RUNS, f"{tid}.json")


def _run_arm(prompt: str, task: CompressTask, timeout: int = 180) -> dict:
    """One paid claude -p pass, then score the reply against the objective V. NO fabrication."""
    reply, ncalls = claude_call(prompt)
    layout = sorted(task.impl_files.keys())
    res = run_v(reply, pkg=task.pkg, test_name=task.test_name, test_src=task.test_src,
               required_layout=layout)
    return {
        "calls": ncalls,
        "reply_chars": len(reply),
        "pass": bool(res["pass"]),
        "v_summary": res["summary"],
        "runner": res.get("runner"),
        "n_ran": res.get("n_ran"),
        "n_parsed_files": res.get("n_parsed_files"),
        "wrote_layout": res.get("wrote_layout"),
        "stdout_tail": res.get("stdout_tail", "")[-900:],
        "reply_head": reply[:400],
    }


def run_task(task: CompressTask, *, resume: bool = True) -> dict:
    tid = task.task_id
    ck = _ckpt(tid)
    row = {}
    if resume and os.path.exists(ck):
        with open(ck) as f:
            row = json.load(f)
        if row.get("cold") and row.get("sigma"):
            return row
    row.setdefault("task_id", tid)
    row["session_file"] = task.session_file
    row["n_turns_in_original"] = task.n_turns
    row["n_user_prompts"] = task.n_prompts
    row["pkg"] = task.pkg
    row["test_name"] = task.test_name
    row["v_assert_count"] = task.n_asserts
    row["leakage_ratio"] = task.leak_ratio
    row["iota_naive_chars"] = len(task.iota_naive)
    row["sigma_schema_chars"] = len(task.sigma_schema)

    # D_orig vs V sanity reference (cheap, no paid call) — must pass.
    if "d_orig_pass" not in row:
        sref = run_v(reassemble_original(task.impl_files), pkg=task.pkg, test_name=task.test_name,
                     test_src=task.test_src, required_layout=sorted(task.impl_files.keys()))
        row["d_orig_pass"] = bool(sref["pass"])
        row["d_orig_summary"] = sref["summary"]
        with open(ck, "w") as f:
            json.dump(row, f, indent=2)

    # ARM_COLD
    if not row.get("cold"):
        try:
            row["cold"] = _run_arm(task.iota_naive, task)
        except Exception as e:
            row["cold_error"] = f"{type(e).__name__}: {e}"
            with open(ck, "w") as f:
                json.dump(row, f, indent=2)
            raise
        row["ts_cold"] = time.time()
        with open(ck, "w") as f:
            json.dump(row, f, indent=2)

    # ARM_SIGMA
    if not row.get("sigma"):
        try:
            row["sigma"] = _run_arm(task.sigma_schema, task)
        except Exception as e:
            row["sigma_error"] = f"{type(e).__name__}: {e}"
            with open(ck, "w") as f:
                json.dump(row, f, indent=2)
            raise
        row["ts_sigma"] = time.time()
        with open(ck, "w") as f:
            json.dump(row, f, indent=2)
    return row


def main(resume: bool = True):
    os.makedirs(RUNS, exist_ok=True)
    tasks = select_tasks()
    # build schemas + leakage-guard + PRE-REGISTER (frozen, hashed) BEFORE any paid run.
    pr = build_and_prereg(tasks)
    assert verify_prereg(pr["manifest_hash"]), "prereg failed to re-verify after writing"
    print(f"[cmp] pre-registered manifest hash = {pr['manifest_hash']}", flush=True)
    print(f"[cmp] kept={len(pr['kept'])} dropped_for_leakage={len(pr['dropped_leak'])}", flush=True)

    kept_ids = {r["task_id"] for r in pr["kept"]}
    run_tasks = [t for t in tasks if t.task_id in kept_ids]
    # carry schema/leak onto the task objects for the runner (build_and_prereg set them).
    by_id = {t.task_id: t for t in tasks}
    for tid in kept_ids:
        t = by_id[tid]
        if not t.sigma_schema:
            t.sigma_schema = build_sigma_schema(t)
            leakage_check(t)

    for t in run_tasks:
        print(f"[cmp] === {t.task_id} (turns={t.n_turns} V_asserts={t.n_asserts}) ===", flush=True)
        r = run_task(t, resume=resume)
        c = r.get("cold", {}); s = r.get("sigma", {})
        print(f"[cmp]   D_orig vs V: {'PASS' if r.get('d_orig_pass') else 'FAIL'}", flush=True)
        print(f"[cmp]   COLD  pass={c.get('pass')} [{c.get('v_summary')}]", flush=True)
        print(f"[cmp]   SIGMA pass={s.get('pass')} [{s.get('v_summary')}]", flush=True)
    print("[cmp] ALL DONE", flush=True)


if __name__ == "__main__":
    main()
