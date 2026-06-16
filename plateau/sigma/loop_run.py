"""plateau.sigma.loop_run — the COMPLETING Σ experiment: the FULL operator (schema + γ loop).

Finishes what the one-shot compression round (compress_run.py / RESULTS_AB_COMPRESS.md) set up.
The one-shot round proved: SIGMA reproduced correct STRUCTURE on the 2 substantial tasks (spend:
exact 10-module layout, 1 missing symbol SCHEMA_VERSION; xpense: structure importable, suite ran,
10 failed) but passed 0/6 at the strict τ=1.0 gate; COLD died at the first import on all 6.

THESIS UNDER TEST (the completing experiment): the γ inner loop recovers exactly the
"structure correct, 1 symbol short" failure mode — a failed attempt + the SPECIFIC missed
KPI (pytest stdout) fed back through Φ → fixed next iteration. Does SIGMA+loop close the gap
to PASS, and does it beat naive+loop (isolating the SCHEMA's value from the mere extra iters)?

ARMS (same base model `claude -p`; same objective V = the original's REAL pytest, τ=1.0):
  ARM_SIGMA_LOOP : γ loop seeded with the Σ schema, max_iters=5. Each iter: claude -p proposes
                   → run_v (real pytest) gates → on fail, the SPECIFIC failure (stdout_tail /
                   which import or assertion failed) is written into Φ and HYDRATED into the
                   next iteration's prompt. Depth compounds via the REAL on-disk state_handle.
  ARM_COLD_LOOP  : the SAME γ loop seeded with iota_naive (the raw turn-1 ask), max_iters=5.
                   CONTROL — both arms get the loop, so any SIGMA_LOOP-over-COLD_LOOP gap is
                   attributable to the SCHEMA, not the extra iterations.

One-shot SIGMA + COLD are ALREADY on record (ab_runs_compress) — read, never rerun.

RIGOR: objective V only (the original suite, authored by NEITHER arm); same base model both
arms; same shared output-protocol preamble both arms (only the seed payload differs); the loop
state is REAL (a stateless re-roll would be a bug); NO FABRICATION (every number from a real
claude -p + real pytest run); negative-capable; manifest PRE-REGISTERED + hashed BEFORE any
paid run. Checkpoints per task+arm to ab_runs_loop/<task>__<arm>.json are resumable.
Rate-limit backoff 60-90s, <=3 retries (inherited from ab_run.claude_call).
"""

from __future__ import annotations

import json
import os
import time

from plateau.integrity import file_hash

from .ab_run import claude_call                       # SAME live base-model callable
from .compress_eval import run_v, reassemble_original
from .compress_run import _shared_preamble, PREREG_PATH as CMP_PREREG_PATH
from .compress_tasks import CompressTask, build_sigma_schema, leakage_check, select_tasks
from .fossils import FossilStore

HERE = os.path.dirname(os.path.abspath(__file__))
RUNS = os.path.join(HERE, "ab_runs_loop")
FOSSIL_ROOT = os.path.join(RUNS, "_fossils")
PREREG_PATH = os.path.join(HERE, "prereg_loop.json")

MAX_ITERS = 5
# substantial tasks FIRST (most headroom), then the 4 thin todos — matches the prompt's order.
_TASK_ORDER = {"8b3e2489-73e__test_spend": 0, "c8c7a298-bab__test_xpense": 1}


# --------------------------------------------------------------- pre-registration ----

def build_and_prereg(tasks: list) -> dict:
    """Extend the one-shot manifest with the 2 loop arms + max_iters + the attribution rule.
    Hash BEFORE any paid run. The task set, objective V, and leakage-clean schemas are REUSED
    from the one-shot prereg verbatim — we do NOT re-select tasks."""
    os.makedirs(RUNS, exist_ok=True)
    # carry the one-shot prereg's frozen task rows forward verbatim (same 6 tasks, same V hashes).
    with open(CMP_PREREG_PATH, encoding="utf-8") as f:
        oneshot = json.load(f)
    oneshot_hash = file_hash(CMP_PREREG_PATH)

    # build the leakage-clean schemas on the live task objects (same builder as the one-shot round)
    kept = []
    for t in tasks:
        t.sigma_schema = build_sigma_schema(t)
        leaked, ratio, substr = leakage_check(t)
        kept.append({"task_id": t.task_id, "leakage_ratio": ratio, "leakage_substring_hit": substr,
                     "leaked": leaked})

    manifest = {
        "protocol": "sigma-loop-v1",
        "completes": "sigma-compress-v1",
        "oneshot_prereg_hash": oneshot_hash,
        "thesis": ("The COMPLETING experiment. One-shot SIGMA reproduced correct STRUCTURE on the "
                   "substantial tasks but 0/6 at the strict gate (spend: 1 symbol short; xpense: "
                   "suite ran, 10 failed). Does the γ loop — failed attempt + the SPECIFIC missed "
                   "KPI (real pytest stdout) fed back through Φ → re-propose — close the gap to "
                   "PASS, and does it beat naive+loop (isolating the SCHEMA from mere iteration)?"),
        "arms": {
            "SIGMA_LOOP": ("the γ loop seeded with the Σ schema, max_iters=5. Each iter: claude -p "
                           "proposes the deliverable under the shared preamble → run_v (the real "
                           "original pytest) gates → on fail, the SPECIFIC failure (pytest "
                           "stdout_tail / which import or assertion failed) is written into Φ and "
                           "hydrated into the next iteration's prompt. Depth compounds via the REAL "
                           "on-disk state_handle (FossilStore + _loopstate JSON), not a re-roll."),
            "COLD_LOOP": ("the SAME γ loop seeded with iota_naive (raw turn-1 ask), max_iters=5. "
                          "CONTROL: both arms get the loop, so any SIGMA_LOOP-over-COLD_LOOP gap "
                          "is attributable to the SCHEMA, not the extra iterations."),
        },
        "oneshot_on_record": ("one-shot SIGMA + COLD are already recorded in ab_runs_compress/ and "
                              "are NOT rerun; this round reads them for the per-task comparison."),
        "shared_preamble_identical_to_oneshot": True,
        "max_iters": MAX_ITERS,
        "same_base_model_all_arms": "claude -p (Claude Code CLI), identical to the one-shot round",
        "objective_v": ("the SAME original in-session pytest suite as the one-shot round (byte-"
                        "identical; verifier_frozen_hash carried from the one-shot prereg). Run in "
                        "a fresh subprocess each iteration. Authored by NEITHER arm. PASS iff the "
                        "runner reports >=1 test run and 0 failures/errors."),
        "tau": 1.0,
        "loop_state_is_real": ("iteration-state (best summary so far, the SPECIFIC last failure, "
                               "the paid-depth fossil hashes) is externalized to disk under a "
                               "state_handle (FossilStore blob + _loopstate_<handle>.json) and "
                               "read back IN each iteration — a longer run COMPOUNDS, a stateless "
                               "re-roll would be a bug (§9.1)."),
        "stop_rule": "all_gates_pass OR max_iters exhausted (whichever first)",
        "attribution_rule": ("ENHANCED <=> (a) SIGMA_LOOP passes tasks that one-shot SIGMA FAILED "
                             "(the loop closes the gap) AND (b) SIGMA_LOOP >= COLD_LOOP (the schema "
                             "adds value beyond merely iterating). Report BOTH. SIGMA_LOOP > "
                             "COLD_LOOP => schema beats naive under the loop. SIGMA_LOOP == "
                             "COLD_LOOP => the loop, not the schema, did the work. SIGMA_LOOP < "
                             "COLD_LOOP => schema HURT under the loop. A negative (loop doesn't "
                             "close the gap) is first-class."),
        "rigor": {
            "objective_v_only": True,
            "arm_never_authors_v": True,
            "same_base_model_all_arms": True,
            "both_arms_get_the_loop": True,
            "loop_state_compounds": True,
            "no_fabrication": True,
            "negative_result_is_valid": True,
        },
        "reused_oneshot_tasks": oneshot.get("tasks", []),
        "schema_leakage_recheck": sorted(kept, key=lambda r: r["task_id"]),
        "task_run_order": ("substantial first (spend, xpense), then the 4 todos "
                           "(add, done, list, persist)"),
        "notes": ("Same 6 tasks + same objective V + same leakage-clean schemas as the one-shot "
                  "round — NOT re-selected. enhanced is judged by the attribution_rule above. "
                  "Negative is first-class and reported plainly."),
    }
    blob = json.dumps(manifest, sort_keys=True, separators=(",", ":"))
    with open(PREREG_PATH, "w", encoding="utf-8") as f:
        f.write(blob)
    h = file_hash(PREREG_PATH)
    with open(PREREG_PATH + ".hash", "w", encoding="utf-8") as f:
        f.write(h + "\n")
    return {"manifest": manifest, "manifest_hash": h, "kept": kept}


def verify_prereg(manifest_hash: str) -> bool:
    return os.path.exists(PREREG_PATH) and file_hash(PREREG_PATH) == manifest_hash


# --------------------------------------------------------------- the γ loop ----

def _ckpt(tid: str, arm: str) -> str:
    return os.path.join(RUNS, f"{tid}__{arm}.json")


def _state_path(handle: str) -> str:
    safe = handle.replace("/", "_").replace(":", "_")
    return os.path.join(FOSSIL_ROOT, f"_loopstate_{safe}.json")


def _failure_signal(res: dict) -> str:
    """Distill the SPECIFIC failure from a run_v result into the signal fed back through Φ.

    This is the crux of the completing experiment: the loop must see WHICH import/assertion
    failed, not just 'it failed'. We carry the runner summary + the most informative tail lines
    (the ImportError / E-lines / FAILED lines pytest emits)."""
    tail = res.get("stdout_tail", "") or ""
    lines = [ln.rstrip() for ln in tail.splitlines() if ln.strip()]
    keep = [ln for ln in lines
            if ("Error" in ln or ln.strip().startswith("E ") or ln.strip().startswith("E   ")
                or "FAILED" in ln or "assert" in ln.lower() or "ImportError" in ln
                or "cannot import" in ln or "No module" in ln or "collected" in ln)]
    signal = (res.get("summary", "") + "\n" + "\n".join(keep[-18:])).strip()
    return signal[:2200]


def _hydrate_prompt(seed: str, task: CompressTask, st: dict, iteration: int) -> str:
    """Build iteration `iteration`'s full prompt: shared preamble + seed payload, plus (from
    iter>=1) the HYDRATED Φ context — the prior best attempt + the SPECIFIC pytest failure it
    hit. The hydration is what makes the loop a depth-accumulating fixpoint, not a re-roll."""
    base = _shared_preamble(task) + seed
    last_reply = st.get("last_reply", "")
    last_fail = st.get("last_failure", "")
    if not last_reply or not last_fail:
        return base
    return (
        base
        + "\n\n----- PRIOR ATTEMPT (iteration " + str(iteration - 1) + ") -----\n"
        "Your previous attempt did NOT pass the objective test suite. Here is that attempt "
        "VERBATIM (same `# FILE:` format):\n\n" + last_reply[:11000]
        + "\n\n----- HOW IT FAILED (the objective suite's own output) -----\n"
        + last_fail
        + "\n\n----- FIX -----\n"
        "Produce a CORRECTED complete package that fixes EXACTLY this failure while keeping "
        "everything that already worked. The suite re-runs unchanged. Output ONLY the full "
        "`# FILE:`-labeled package, no prose."
    )


def run_arm_loop(task: CompressTask, arm: str, seed: str, store: FossilStore, *,
                 max_iters: int = MAX_ITERS, resume: bool = True) -> dict:
    """Drive γ to a fixpoint for one arm. Real claude -p propose → real run_v gate → on fail,
    write the SPECIFIC failure to Φ + persist it under the state_handle → next iter hydrates it.

    Returns a checkpoint dict. Resumable: an existing ckpt with `done` is returned as-is; a
    partially-run ckpt resumes from the last completed iteration (state persisted on disk)."""
    tid = task.task_id
    ck = _ckpt(tid, arm)
    handle = f"loop/{arm}/{tid}"
    layout = sorted(task.impl_files.keys())

    row = {}
    if resume and os.path.exists(ck):
        with open(ck) as f:
            row = json.load(f)
        if row.get("done"):
            return row
    row.setdefault("task_id", tid)
    row["arm"] = arm
    row["pkg"] = task.pkg
    row["test_name"] = task.test_name
    row["v_assert_count"] = task.n_asserts
    row["max_iters"] = max_iters
    row.setdefault("iters", [])
    row.setdefault("done", False)

    os.makedirs(FOSSIL_ROOT, exist_ok=True)
    # HYDRATE persisted loop-state (real state_handle); resume picks up exactly where it stopped.
    sp = _state_path(handle)
    if os.path.exists(sp):
        with open(sp) as f:
            st = json.load(f)
    else:
        st = {"iteration": 0, "best_pass": False, "best_summary": "",
              "last_reply": "", "last_failure": "", "paid_depth": []}

    start_iter = st["iteration"]
    if row.get("passed"):
        row["done"] = True
        return row

    for i in range(start_iter, max_iters):
        prompt = _hydrate_prompt(seed, task, st, i)
        reply, ncalls = claude_call(prompt)               # PROPOSE (real, paid)
        res = run_v(reply, pkg=task.pkg, test_name=task.test_name, test_src=task.test_src,
                    required_layout=layout)               # GATE (real pytest)
        passed = bool(res["pass"])
        fail_sig = "" if passed else _failure_signal(res)

        # WRITE newly-paid depth back into Φ (content-addressed) so depth compounds.
        fhash = store.put(
            json.dumps({"iter": i, "reply": reply, "summary": res["summary"]}, sort_keys=True),
            provenance={"task": tid, "arm": arm, "iteration": i, "pass": passed,
                        "summary": res.get("summary", "")},
            satisfies=[f"{tid}:pytest"] if passed else [],
            self_verifiable=True,
        )
        if fhash not in st["paid_depth"]:
            st["paid_depth"].append(fhash)

        row["iters"].append({
            "iter": i,
            "calls": ncalls,
            "pass": passed,
            "v_summary": res["summary"],
            "runner": res.get("runner"),
            "n_ran": res.get("n_ran"),
            "n_parsed_files": res.get("n_parsed_files"),
            "wrote_layout": res.get("wrote_layout"),
            "reply_chars": len(reply),
            "fossil": fhash,
            "stdout_tail": res.get("stdout_tail", "")[-900:],
            "reply_head": reply[:300],
        })

        # advance + PERSIST loop-state under the state_handle (the REAL compounding state).
        st["iteration"] = i + 1
        st["last_reply"] = reply
        st["last_failure"] = fail_sig
        st["last_summary"] = res["summary"]
        if passed and not st["best_pass"]:
            st["best_pass"] = True
            st["best_summary"] = res["summary"]
        with open(sp, "w") as f:
            json.dump(st, f, sort_keys=True)

        # checkpoint the row every iteration so a kill mid-loop loses nothing.
        row["passed"] = passed
        row["iters_run"] = i + 1
        with open(ck, "w") as f:
            json.dump(row, f, indent=2)

        if passed:
            break

    row["passed"] = bool(st["best_pass"])
    row["pass_at_iter"] = next((it["iter"] for it in row["iters"] if it["pass"]), None)
    row["final_summary"] = row["iters"][-1]["v_summary"] if row["iters"] else ""
    row["done"] = True
    row["ts"] = time.time()
    with open(ck, "w") as f:
        json.dump(row, f, indent=2)
    return row


def run_task(task: CompressTask, *, resume: bool = True) -> dict:
    """Run BOTH loop arms for one task, serialized (SIGMA_LOOP then COLD_LOOP). Each arm gets a
    FRESH FossilStore so the arms never share paid depth (the control stays clean)."""
    out = {"task_id": task.task_id}
    sigma_store = FossilStore(os.path.join(FOSSIL_ROOT, task.task_id, "sigma"))
    out["sigma_loop"] = run_arm_loop(task, "SIGMA_LOOP", task.sigma_schema, sigma_store,
                                     resume=resume)
    cold_store = FossilStore(os.path.join(FOSSIL_ROOT, task.task_id, "cold"))
    out["cold_loop"] = run_arm_loop(task, "COLD_LOOP", task.iota_naive, cold_store, resume=resume)
    return out


def select_ordered() -> list:
    tasks = select_tasks()
    # build schemas + leakage-guard on the live objects (same as the one-shot round).
    for t in tasks:
        t.sigma_schema = build_sigma_schema(t)
        leakage_check(t)
    tasks.sort(key=lambda t: (_TASK_ORDER.get(t.task_id, 9), -t.n_asserts, t.task_id))
    return tasks


def main(resume: bool = True, only: list = None):
    os.makedirs(RUNS, exist_ok=True)
    tasks = select_ordered()
    pr = build_and_prereg(tasks)
    assert verify_prereg(pr["manifest_hash"]), "prereg failed to re-verify after writing"
    print(f"[loop] pre-registered manifest hash = {pr['manifest_hash']}", flush=True)
    print(f"[loop] max_iters={MAX_ITERS} tasks={[t.task_id for t in tasks]}", flush=True)
    if only:
        tasks = [t for t in tasks if t.task_id in set(only)]
    for t in tasks:
        print(f"[loop] === {t.task_id} (turns={t.n_turns} V_asserts={t.n_asserts}) ===", flush=True)
        r = run_task(t, resume=resume)
        s = r["sigma_loop"]; c = r["cold_loop"]
        print(f"[loop]   SIGMA_LOOP pass={s.get('passed')} @iter={s.get('pass_at_iter')} "
              f"final=[{s.get('final_summary')}] iters={s.get('iters_run')}", flush=True)
        print(f"[loop]   COLD_LOOP  pass={c.get('passed')} @iter={c.get('pass_at_iter')} "
              f"final=[{c.get('final_summary')}] iters={c.get('iters_run')}", flush=True)
    print("[loop] ALL DONE", flush=True)


if __name__ == "__main__":
    import sys
    only = sys.argv[1:] or None
    main(only=only)
