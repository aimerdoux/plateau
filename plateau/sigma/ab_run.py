"""plateau.sigma.ab_run — the LIVE, PAID A/B driver (real `claude -p` calls).

Runs the pre-registered WITH/WITHOUT experiment (see experiment.py + ab_tasks.py) for real:

  ARM_WITH    : run_schema's Σ loop. Each iteration HYDRATES Φ (prior best candidate + which
                gates failed + paid-depth fossils) INTO the prompt, calls `claude -p` to PROPOSE a
                candidate, scores it against the OBJECTIVE V, writes paid depth back to Φ, and
                iterates to max_iterations (≈4). Depth compounds (state_handle is real).
  ARM_WITHOUT : ONE plain `claude -p` pass on the SAME clean intent ι (goal only), fresh EMPTY
                FossilStore, scored against the SAME objective V. No scaffolding.

RIGOR: both arms call the SAME base model (the same `claude -p` callable). The ONLY difference is
the Σ scaffolding. Gates are objective (fixed code in ab_tasks.py); neither arm authors its judge.
No number in the results is fabricated — every gate-pass comes from a real subprocess check of a
real `claude -p` reply. A result where WITH does not beat WITHOUT is a VALID finding.

Serialized (one task/one arm at a time). On rate-limit ("temporarily limiting" / 429 / overload)
back off 60-90s and retry <=3x. Per-task results CHECKPOINT to ab_runs/<task>.json so a bail is
resumable: a task whose checkpoint exists + has both arms is skipped on resume.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import time

from . import ab_tasks
from .evaluate import evaluate
from .fossils import FossilStore
from .models import Intent, LoopConfig, Schema
from .run_schema import run_schema

HERE = os.path.dirname(os.path.abspath(__file__))
AB_RUNS = os.path.join(HERE, "ab_runs")
FOSSIL_ROOT = os.path.join(AB_RUNS, "_fossils")

_RATE_LIMIT_MARKERS = ("temporarily limiting", "rate limit", "429", "overloaded",
                       "overload", "too many requests", "please try again")
_MAX_ITERS = 4
_RL_RETRIES = 3
_COST_PER_CALL = 1.0          # accounting unit = one claude -p invocation


# --------------------------------------------------------- live claude -p ----

def _extract_code(text: str) -> str:
    """Pull the deliverable out of a `claude -p` reply. Prefer a fenced code block; else the
    raw text (for markdown-table / JSON tasks that may be unfenced). Never executes anything."""
    if not text:
        return ""
    m = re.search(r"```(?:python|json|md|markdown)?\s*\n(.*?)```", text, re.S | re.I)
    if m:
        return m.group(1).strip()
    return text.strip()


def claude_call(prompt: str) -> tuple:
    """One real `claude -p` invocation. Returns (reply_text, n_calls_charged). Retries on
    rate-limit with 60-90s backoff, up to _RL_RETRIES. Raises RuntimeError if still limited."""
    calls = 0
    last_err = ""
    for attempt in range(_RL_RETRIES + 1):
        calls += 1
        try:
            p = subprocess.run(["claude", "-p"], input=prompt, capture_output=True,
                               text=True, timeout=300)
        except subprocess.TimeoutExpired:
            last_err = "claude -p TIMEOUT (300s)"
            time.sleep(60 + 30 * attempt)
            continue
        out = (p.stdout or "").strip()
        err = (p.stderr or "").strip()
        combined = (out + "\n" + err).lower()
        limited = (p.returncode != 0 and not out) or \
                  any(mk in combined for mk in _RATE_LIMIT_MARKERS)
        # a non-empty plausible reply that merely *mentions* a marker word in normal prose
        # should not be treated as limited; only treat as limited when the reply is empty/short.
        if limited and len(out) < 40:
            last_err = (err or out or "empty reply")[:200]
            if attempt < _RL_RETRIES:
                back = 60 + 15 * attempt + (attempt * 5)
                time.sleep(min(90, back))
                continue
            raise RuntimeError(f"rate-limited after {_RL_RETRIES} retries: {last_err}")
        return out, calls
    raise RuntimeError(f"claude -p failed: {last_err}")


# ----------------------------------------------- WITH-arm model adapter ----
# run_schema calls model(intent, context, iteration) -> candidate. We build a prompt that
# HYDRATES Φ context (prior best + failed gates + paid-depth note) so depth compounds, then call
# claude -p. The recorded answer is NEVER leaked — only the clean intent goal + the loop's own
# prior attempt (which the arm itself produced) feed the prompt.

def _make_with_model(goal: str, verifier, call_log: list):
    last = {"code": "", "fails": [], "feas": 0.0}

    def model(intent: Intent, context: dict, iteration: int):
        parts = [goal]
        # hydrate from Φ-carried state (prior attempt + which objective gates failed)
        if last["code"]:
            parts.append(
                "\n\nYour PREVIOUS attempt did not pass every objective check. Previous attempt:\n"
                "```\n" + last["code"][:4000] + "\n```\n"
                "It failed these requirement(s): " + "; ".join(last["fails"]) +
                ".\nProduce a corrected version that satisfies ALL stated requirements. "
                "Output ONLY the deliverable in the requested format, no commentary."
            )
        prompt = "".join(parts)
        reply, n = claude_call(prompt)
        call_log.append(n)
        code = _extract_code(reply)
        cand = {"text": reply, "code": code}
        # score now (the loop also scores, but we capture failed-gate names for next hydration)
        res = evaluate(cand, verifier)
        last["code"] = code
        last["feas"] = res.feasibility
        last["fails"] = [r.kpi for r in res.results if not r.passed] or ["(unknown)"]
        return cand

    return model


# -------------------------------------------------- WITHOUT-arm single pass ----

def _without_pass(goal: str, verifier, call_log: list):
    reply, n = claude_call(goal)        # bare clean intent, ONE pass, no scaffolding
    call_log.append(n)
    cand = {"text": reply, "code": _extract_code(reply)}
    res = evaluate(cand, verifier)
    return cand, res


# ------------------------------------------------------------- per-task run ----

def _schema_for(spec: dict, verifier) -> Schema:
    intent = Intent(
        goal=spec["goal"],
        target_invariants=(spec["kpi"],),
        constraints=("output only the deliverable in the requested format",),
        excluded_paths=(),
        source_session_hash="sigma-ab-live",
    )
    loop = LoopConfig(
        generator_policy="claude-p-live",
        max_iterations=_MAX_ITERS,
        stop_rule="either",
        state_handle=f"ab/{spec['task_id']}/{verifier.frozen_hash[7:23]}",
        fossil_write=True,
    )
    return Schema(intent=intent, verifier=verifier, loop=loop, phi=())


def run_one_task(spec: dict, *, resume: bool = True) -> dict:
    """Run BOTH arms for one task, serialized. Checkpoint to ab_runs/<task>.json. Resumable."""
    tid = spec["task_id"]
    ckpt = os.path.join(AB_RUNS, f"{tid}.json")
    if resume and os.path.exists(ckpt):
        with open(ckpt) as f:
            prev = json.load(f)
        if prev.get("with") and prev.get("without") and not prev.get("error"):
            return prev          # already complete — skip (resume)

    verifier = ab_tasks.verifier_for(spec)
    row = {"task_id": tid, "depth": spec["depth"], "frozen_hash": verifier.frozen_hash,
           "kpi": spec["kpi"], "ts": time.time()}

    # fresh fossil store per arm so WITHOUT gets zero Φ benefit and arms don't share state.
    with_store = FossilStore(os.path.join(FOSSIL_ROOT, tid, "with"))
    with_log: list = []
    try:
        schema = _schema_for(spec, verifier)
        with_model = _make_with_model(spec["goal"], verifier, with_log)
        rr = run_schema(schema, with_model, with_store)
        row["with"] = {
            "all_pass": bool(rr.all_pass),
            "feasibility": round(rr.feasibility, 6),
            "iterations": rr.iterations,
            "calls": sum(with_log),
            "cost": sum(with_log) * _COST_PER_CALL,
            "feasibility_trace": [round(x, 6) for x in rr.feasibility_trace],
            "fossils_written": len(rr.fossils_written),
            "stop_reason": rr.stop_reason,
            "candidate_code": (rr.best_candidate or {}).get("code", "")[:6000]
                if isinstance(rr.best_candidate, dict) else "",
        }
        with open(ckpt, "w") as f:
            json.dump(row, f, indent=2)
    except Exception as e:
        row["error"] = f"WITH arm: {type(e).__name__}: {e}"
        with open(ckpt, "w") as f:
            json.dump(row, f, indent=2)
        return row

    without_log: list = []
    try:
        cand_wo, res_wo = _without_pass(spec["goal"], verifier, without_log)
        row["without"] = {
            "all_pass": bool(res_wo.all_pass),
            "feasibility": round(res_wo.feasibility, 6),
            "iterations": 1,
            "calls": sum(without_log),
            "cost": sum(without_log) * _COST_PER_CALL,
            "candidate_code": cand_wo.get("code", "")[:6000],
        }
    except Exception as e:
        row["error"] = f"WITHOUT arm: {type(e).__name__}: {e}"

    row["done_ts"] = time.time()
    with open(ckpt, "w") as f:
        json.dump(row, f, indent=2)
    return row


def run_all(specs=None, *, resume: bool = True) -> list:
    specs = specs or ab_tasks.task_specs()
    os.makedirs(AB_RUNS, exist_ok=True)
    rows = []
    for sp in specs:
        print(f"[ab] === {sp['task_id']} (depth {sp['depth']}) ===", flush=True)
        r = run_one_task(sp, resume=resume)
        w = r.get("with", {})
        wo = r.get("without", {})
        print(f"[ab]   WITH  pass={w.get('all_pass')} iters={w.get('iterations')} "
              f"calls={w.get('calls')} trace={w.get('feasibility_trace')}", flush=True)
        print(f"[ab]   WITHOUT pass={wo.get('all_pass')} calls={wo.get('calls')} "
              f"err={r.get('error','')}", flush=True)
        rows.append(r)
    return rows
