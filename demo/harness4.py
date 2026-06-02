#!/usr/bin/env python3
"""demo4 harness — 3-arm real-workload driver mechanics + locked scorer.

This module is pure mechanics. It does NOT decide verdicts by judgment; `score()`
implements the demo4_prereg.md decision rules verbatim, fixed BEFORE any data
exists. The same `score()` is used by the mock-plumb and by the real run, and is
re-run in a fresh process during recompute — it reads ONLY sealed per-step records.

Arms differ ONLY in the context carried into each step's prompt:
  arm1 full-history     — entire prior transcript (prompts+replies) concatenated; climbs.
  arm2 plateau-efficiency — bounded signal blob only (emit/inflate), re-ground; flat.
  arm3 plateau-autonomy   — bounded signal blob + the agent's forward-plan (carried in
                            lessons/pointers, so still bounded), spending freed headroom.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # plateau repo root
ARMS = ("arm1_fullhistory", "arm2_efficiency", "arm3_autonomy")
STEP_CAP = 12
SUCCESS_MIN_TESTS = 28  # 26 baseline + >=2 new (locked)


# ---------------------------------------------------------------- tokens
def tok(s: str) -> int:
    """Deterministic, dependency-free token proxy. Reproduces in any fresh process
    from the sealed prompt text — no tiktoken/model-usage dependency, so recompute
    is exact."""
    return len(re.findall(r"\w+|[^\w\s]", s, flags=re.UNICODE))


# ---------------------------------------------------------------- prompt assembly
TASK_SPEC = (
    "TASK (identical for all arms): add a new Measurement kind `command_output` to the "
    "plateau package, end-to-end.\n"
    "1. plateau/signal.py: add 'command_output' to Measurement.kind; reverify() runs a "
    "WHITELISTED command, hashes stdout as 'sha256:'+sha256(raw stdout bytes) (same "
    "convention as file_hash), compares to recorded value; fail CLOSED on nonzero exit, "
    "non-whitelisted command, or missing command. Provide a whitelist API "
    "(set_command_whitelist(list) and/or module set _CMD_WHITELIST).\n"
    "2. plateau/continuum.py: ensure emit/ground/inflate carry the new kind losslessly "
    "(kind already passes through; verify + add a guard).\n"
    "3. tests/test_measurement_kinds.py (NEW): >=2 tests — a command_output fact "
    "re-verifies while output stable and goes STALE when it changes; gate admits only "
    "while live.\n"
    "4. README.md + adapters/claude_code/SKILL.md: one paragraph each documenting the "
    "kind; SKILL pending-facts format gains a command_output example.\n"
    "Advance the feature this step, then STOP. The harness runs the objective check."
)


def assemble_prompt(arm: str, step: int, prior_prompts: list[str],
                    prior_replies: list[str], signal_blob: str,
                    forward_plan: str = "") -> str:
    head = f"[demo4 arm={arm} step={step}]\n{TASK_SPEC}\n"
    if arm == "arm1_fullhistory":
        transcript = ""
        for i, (p, r) in enumerate(zip(prior_prompts, prior_replies), 1):
            transcript += f"\n--- prior step {i} PROMPT ---\n{p}\n--- prior step {i} REPLY ---\n{r}\n"
        return head + "\nFULL PRIOR TRANSCRIPT (carried):\n" + transcript
    if arm == "arm2_efficiency":
        return head + "\nBOUNDED SIGNAL (re-grounded each step):\n" + signal_blob
    # arm3
    return (head + "\nBOUNDED SIGNAL (re-grounded each step):\n" + signal_blob +
            "\nFORWARD-PLAN (freed headroom spent on real planning):\n" + forward_plan)


# ---------------------------------------------------------------- arm repos
def make_arm_repo(dst: str) -> None:
    """Pristine copy of plateau HEAD into dst (git archive => no .git/.venv/scratch)."""
    if os.path.exists(dst):
        shutil.rmtree(dst)
    os.makedirs(dst, exist_ok=True)
    p = subprocess.run(["bash", "-lc", f"git -C {REPO} archive HEAD | tar -x -C {dst}"],
                       capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(f"git archive failed: {p.stderr}")


# ---------------------------------------------------------------- objective check
_PYTEST_PASS = re.compile(r"(\d+) passed")
_PYTEST_FAIL = re.compile(r"(\d+) failed")
_PYTEST_ERR = re.compile(r"(\d+) error")


def run_objective_check(repo: str) -> dict:
    """The locked binary success check, run by the harness (not judged):
    pytest exits 0 with >=28 tests AND the command_output stale-detection probe passes."""
    pt = subprocess.run(
        ["bash", "-lc", f"cd {repo} && uv run --with pytest --with numpy pytest -q 2>&1"],
        capture_output=True, text=True)
    out = pt.stdout + pt.stderr
    passed = int(_PYTEST_PASS.search(out).group(1)) if _PYTEST_PASS.search(out) else 0
    failed = int(_PYTEST_FAIL.search(out).group(1)) if _PYTEST_FAIL.search(out) else 0
    errors = int(_PYTEST_ERR.search(out).group(1)) if _PYTEST_ERR.search(out) else 0
    probe = subprocess.run(
        ["bash", "-lc",
         f"PYTHONPATH={repo} python3 {REPO}/demo/probe_command_output.py {repo}"],
        capture_output=True, text=True)
    probe_ok, probe_reason = False, "probe produced no json"
    for line in probe.stdout.splitlines():
        line = line.strip()
        if line.startswith("{"):
            try:
                j = json.loads(line)
                probe_ok, probe_reason = bool(j.get("probe_ok")), j.get("reason", "")
            except Exception:  # noqa: BLE001
                pass
    ok_pytest = (pt.returncode == 0 and passed >= SUCCESS_MIN_TESTS and failed == 0 and errors == 0)
    ok = bool(ok_pytest and probe_ok)
    return {"exit": pt.returncode, "passed": passed, "failed": failed, "errors": errors,
            "n_tests": passed + failed + errors, "ok_pytest": ok_pytest,
            "probe_ok": probe_ok, "probe_reason": probe_reason, "ok": ok,
            "pytest_tail": "\n".join(out.splitlines()[-4:])}


# ---------------------------------------------------------------- scorer (LOCKED)
def _slope(ys: list[float]) -> float:
    n = len(ys)
    if n < 2:
        return 0.0
    xs = list(range(1, n + 1))
    mx = sum(xs) / n
    my = sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    den = sum((x - mx) ** 2 for x in xs)
    return num / den if den else 0.0


def _arm_summary(records: dict, arm: str) -> dict:
    steps = sorted(records[arm]["steps"], key=lambda s: s["step"])
    ctx = [s["context_tokens"] for s in steps]
    checks = [s["check"] for s in steps]
    completion = any(c["ok"] for c in checks)
    steps_to_done = next((s["step"] for s in steps if s["check"]["ok"]), STEP_CAP + 1)
    # an error/rework step: build broken after that step (nonzero exit / failed / errors),
    # counted up to and including completion.
    upto = steps_to_done if completion else len(steps)
    errors = sum(1 for s in steps[:upto]
                 if (s["check"]["exit"] != 0 or s["check"]["failed"] > 0 or s["check"]["errors"] > 0))
    return {"context": ctx, "slope": _slope([float(c) for c in ctx]),
            "completion": completion, "steps_to_done": steps_to_done, "errors": errors,
            "n_steps": len(steps)}


def score(records: dict) -> dict:
    """Apply demo4_prereg.md decision rules WITHOUT override. Two separate verdicts.
    Pre-committed thresholds: arm1 'materially climbs' = slope>0 AND last>=1.5*first;
    efficiency WIN band = arm2 slope <= 25% of arm1 slope; autonomy precedence (fixed
    here before data, logged as a fork): DEGRADE > WIN > NULL on the prereg's own rules."""
    a1 = _arm_summary(records, "arm1_fullhistory")
    a2 = _arm_summary(records, "arm2_efficiency")
    a3 = _arm_summary(records, "arm3_autonomy")

    # ---- efficiency (arm2 vs arm1)
    climbs = (a1["slope"] > 0 and len(a1["context"]) >= 2
              and a1["context"][-1] >= 1.5 * max(1, a1["context"][0]))
    parity = (not (a1["completion"] and not a2["completion"]))  # arm2 not FAIL while arm1 PASS
    if not climbs:
        eff = "UNSCORABLE"
        eff_reason = (f"arm1 did not materially climb (slope={a1['slope']:.1f}, "
                      f"first={a1['context'][0] if a1['context'] else 0}, "
                      f"last={a1['context'][-1] if a1['context'] else 0}) -> task too short")
    elif a1["completion"] and not a2["completion"]:
        eff = "PARTIAL_FORGETS"
        eff_reason = "arm2 bounded but FAILED while arm1 PASSED (amnesia, not a win)"
    elif a2["slope"] <= 0.25 * a1["slope"] and parity:
        eff = "WIN"
        eff_reason = (f"arm1 climbs (slope {a1['slope']:.1f}); arm2 slope {a2['slope']:.1f} "
                      f"<= 25% of arm1; completion parity held")
    else:
        eff = "NULL"
        eff_reason = (f"arm2 slope {a2['slope']:.1f} not <= 25% of arm1 {a1['slope']:.1f} "
                      f"(no bound achieved)")

    # ---- autonomy (arm3 vs arm2)
    both_pass = a2["completion"] and a3["completion"]
    if not both_pass:
        if a2["completion"] and not a3["completion"]:
            aut, aut_reason = "DEGRADE", "arm3 FAILED while arm2 PASSED (autonomy broke completion)"
        else:
            aut, aut_reason = "MOOT", "precondition: both arms must PASS (arm2 or arm3 did not)"
    elif a3["errors"] > a2["errors"]:
        aut, aut_reason = "DEGRADE", (f"arm3 added noise: errors {a3['errors']} > arm2 {a2['errors']}")
    elif a3["steps_to_done"] < a2["steps_to_done"] or a3["errors"] < a2["errors"]:
        aut, aut_reason = "WIN", (f"freed context productive: steps {a3['steps_to_done']} vs "
                                  f"{a2['steps_to_done']}, errors {a3['errors']} vs {a2['errors']}")
    else:
        aut, aut_reason = "NULL", (f"arm3 ties/underperforms arm2 (steps {a3['steps_to_done']} vs "
                                   f"{a2['steps_to_done']}, errors {a3['errors']} vs {a2['errors']}) "
                                   f"-> Plateau is an efficiency tool, not a capability tool at this scale")

    return {
        "efficiency": {"verdict": eff, "reason": eff_reason,
                       "arm1_slope": a1["slope"], "arm2_slope": a2["slope"],
                       "arm1_climbs": climbs, "completion_parity": parity},
        "autonomy": {"verdict": aut, "reason": aut_reason,
                     "arm2_steps": a2["steps_to_done"], "arm3_steps": a3["steps_to_done"],
                     "arm2_errors": a2["errors"], "arm3_errors": a3["errors"]},
        "arms": {"arm1_fullhistory": a1, "arm2_efficiency": a2, "arm3_autonomy": a3},
    }


if __name__ == "__main__":
    # quick self-check of tok + slope determinism
    print("tok demo:", tok("hello world, command_output!"))
    print("slope [1,2,3,4]:", _slope([1, 2, 3, 4]))
