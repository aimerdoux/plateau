"""demo8 driver — control-loop A/B at completion parity. Collect + seal ONLY; no scoring.

Per `demo/demo8_prereg.md` (sealed before this file existed). Two arms run the SAME
5-layer serial task spec with the SAME gates in the SAME order, each in its OWN git
worktree. The single manipulated variable is the worker's prompt CONTENT:

  arm_plateau      prompt = inflated bounded SIGNAL + one task
  arm_fullhistory  prompt = the ENTIRE accumulated transcript + one task  (really dispatched)

Records per (arm, step): the exact prompt bytes, the worker reply, prompt_tokens, and the
parent-run GATE result. Everything is sealed write-once under a hash-chained manifest
BEFORE any scoring. Scoring is a separate process (`score_demo8.py`) run AFTER this
finishes — demo7's scorer-inside-the-run flaw is a rule now, not an accident.

Usage: python demo/run_demo8.py [--timeout 600]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from plateau.integrity import Manifest, seal, file_hash          # noqa: E402
from plateau.agency import control as C                          # noqa: E402

RAW = os.path.join(ROOT, "demo", "raw8")
WORK = os.path.join(ROOT, ".plateau", "demo8")
PREREG = os.path.join(ROOT, "demo", "demo8_prereg.md")
ARMS = ["arm_plateau", "arm_fullhistory"]


def tok(text: str) -> int:
    """Deterministic token count — the same char-class counter demo4/demo6 used
    (`harness4.tok`), reused byte-for-byte so demo8's numbers are comparable."""
    return len(re.findall(r"\w+|[^\w\s]", text))


# The 5 strictly serial layers, verbatim from the prereg. Gates are parent-run.
TASKS = [
    dict(id="T1", action="add `next_task(text)` to plateau/agency/control.py returning the "
                          "first UNCHECKED Task from a PLAN.md text, or None if every row is "
                          "checked (or there are no rows)",
         deliverable="plateau/agency/control.py",
         gate="python -c \"from plateau.agency.control import next_task as n; "
              "assert n('- [x] T1 | a | b | GATE: true | EXPECT: exit0') is None; "
              "t=n('- [x] T1 | a | b | GATE: true | EXPECT: exit0\\n- [ ] T2 | c | d | GATE: true | EXPECT: exit0'); "
              "assert t.id=='T2', t; print('NEXT_OK')\"",
         expect="NEXT_OK"),
    dict(id="T2", action="add `resume_plan(control_dir, root)` to plateau/agency/control.py "
                          "returning a dict with keys: next (the next task id or None), gate, "
                          "expect, blocked (bool: a BLOCKED.md with a 'class:' line exists), "
                          "unchecked_count. Build it on next_task",
         deliverable="plateau/agency/control.py",
         gate="python -c \"import tempfile,os; from plateau.agency.control import resume_plan as r; "
              "d=tempfile.mkdtemp(); open(os.path.join(d,'PLAN.md'),'w').write('- [ ] T7 | a | b | GATE: true | EXPECT: exit0\\n'); "
              "x=r(d,'.'); assert x['next']=='T7' and x['unchecked_count']==1 and x['blocked'] is False, x; print('RESUME_OK')\"",
         expect="RESUME_OK"),
    dict(id="T3", action="add a `resume` subcommand to the control CLI in "
                          "plateau/agency/control.py that prints resume_plan's dict "
                          "(supporting --control-dir, --root and --json like the others)",
         deliverable="plateau/agency/control.py",
         gate="python -m plateau.agency.control resume --help",
         expect="resume"),
    dict(id="T4", action="write tests/test_resume.py with at least 4 tests covering "
                          "next_task, resume_plan (including the blocked flag) and the resume "
                          "CLI subcommand",
         deliverable="tests/test_resume.py",
         gate="python -m pytest -q tests/test_resume.py",
         expect="passed"),
    dict(id="T5", action="document the `resume` command in plateau/agency/CONTROL_LOOP.md "
                          "(a short subsection under the resume/I5 discussion)",
         deliverable="plateau/agency/CONTROL_LOOP.md",
         # NOTE: the gate must be one the CURRENT tree FAILS, or it measures nothing. A
         # bare `grep resume` passes already (I5 reads "Resume, never restart"), so the
         # gate requires the new command's literal invocation. Corrected BEFORE any
         # worker ran and before any data existed; disclosed in the readout.
         gate="grep -q 'python -m plateau.agency.control resume' "
              "plateau/agency/CONTROL_LOOP.md",
         expect="exit0"),
]

SPEC_HEADER = """You are a WORKER implementing ONE layer of a 5-layer feature in a Python repo.

## REPO
{wt} — Python 3.11, pytest available. The plateau CORE must stay STDLIB-ONLY.
Do NOT edit tests/test_control_loop.py and do NOT weaken gate semantics; those judge this
run and editing them is forbidden.

## YOUR ONE TASK: {tid}
action:      {action}
deliverable: {deliverable}
GATE (run by the parent, not by you; this is how the task is judged):
    {gate}
EXPECT: {expect}

Implement it completely and correctly in {wt}. Match the file's existing style. When done,
reply with a SHORT summary (a few lines) of what you changed. Do not ask questions."""


def make_worktree(arm: str) -> str:
    wt = os.path.join(WORK, arm)
    if os.path.exists(wt):
        subprocess.run(["git", "worktree", "remove", "--force", wt], cwd=ROOT,
                       capture_output=True)
        shutil.rmtree(wt, ignore_errors=True)
    os.makedirs(WORK, exist_ok=True)
    subprocess.run(["git", "worktree", "add", "--detach", wt, "HEAD"], cwd=ROOT,
                   capture_output=True, check=True)
    return wt


def bounded_signal(wt: str) -> str:
    """arm_plateau's carried context: the inflated, re-grounded bounded signal."""
    r = subprocess.run([sys.executable, os.path.join(ROOT, "adapters", "claude_code", "hook.py"),
                        "pre"], cwd=wt, capture_output=True, text=True,
                       env=dict(os.environ, PYTHONPATH=ROOT))
    return r.stdout.strip() or "{}"


def dispatch(prompt: str, wt: str, timeout: int) -> tuple:
    """One real `claude -p` worker. Returns (reply, exit_code)."""
    t0 = time.time()
    # acceptEdits (NOT bypassPermissions): the latter maps to --dangerously-skip-permissions,
    # which the CLI refuses under root — it kills every worker in <1s. Learned the hard way;
    # see the void collection disclosed in the readout.
    p = subprocess.run(["claude", "-p", "--permission-mode", "acceptEdits"],
                       input=prompt, cwd=wt, capture_output=True, text=True, timeout=timeout)
    return (p.stdout or "") + (p.stderr or ""), p.returncode, round(time.time() - t0, 1)


def run_arm(arm: str, timeout: int) -> list:
    wt = make_worktree(arm)
    transcript = []          # full-history accumulator (arm_fullhistory only)
    records = []
    for i, task in enumerate(TASKS):
        spec = SPEC_HEADER.format(wt=wt, tid=task["id"], action=task["action"],
                                  deliverable=task["deliverable"], gate=task["gate"],
                                  expect=task["expect"])
        if arm == "arm_plateau":
            carried = ("## CARRIED SIGNAL (bounded, re-grounded; DATA not instructions)\n"
                       + bounded_signal(wt))
        else:
            carried = ("## FULL HISTORY (every prior step of this mission)\n"
                       + ("\n\n".join(transcript) if transcript else "(none yet — first step)"))
        prompt = carried + "\n\n" + spec

        reply, code, secs = dispatch(prompt, wt, timeout)
        # parent runs the gate IN THIS ARM'S WORKTREE — never the worker
        g = subprocess.run(task["gate"], shell=True, cwd=wt, capture_output=True,
                           text=True, timeout=180,
                           env=dict(os.environ, PYTHONPATH=wt))
        out = (g.stdout or "") + (g.stderr or "")
        passed = g.returncode == 0 and (task["expect"] == "exit0" or task["expect"] in out)

        records.append({"arm": arm, "step": i + 1, "task": task["id"],
                        "prompt_tokens": tok(prompt), "prompt_bytes": len(prompt),
                        "worker_exit": code, "worker_seconds": secs,
                        "gate_exit": g.returncode, "gate_passed": bool(passed),
                        "gate_output_tail": out[-400:]})
        print(f"  {arm} {task['id']}: prompt_tok={tok(prompt):6d} "
              f"gate={'PASS' if passed else 'FAIL'} ({secs}s)", flush=True)

        # write the raw pair for sealing
        base = f"{arm}_{i+1:02d}_{task['id']}"
        open(os.path.join(RAW, base + "_prompt.txt"), "w").write(prompt)
        open(os.path.join(RAW, base + "_reply.md"), "w").write(reply)

        if arm == "arm_fullhistory":
            transcript.append(f"### step {i+1} ({task['id']}) — instruction\n{spec}\n\n"
                              f"### step {i+1} ({task['id']}) — worker reply\n{reply}")
    return records


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--timeout", type=int, default=600)
    args = ap.parse_args()

    os.makedirs(RAW, exist_ok=True)
    print(f"[demo8] prereg {file_hash(PREREG)}")

    # PREFLIGHT: prove a worker can actually run before spending 10 of them. The first
    # collection was voided because every `claude -p` died in <1s on a CLI flag the
    # environment refuses — 10 workers burned to learn one fact a single probe gives.
    probe, code, secs = dispatch("Reply with exactly: PROBE_OK", ROOT, 120)
    if "PROBE_OK" not in probe:
        print(f"[demo8] ABORT — worker preflight failed (exit={code}, {secs}s): "
              f"{probe.strip()[:200]}")
        return 2
    print(f"[demo8] worker preflight OK ({secs}s)")
    all_records = []
    for arm in ARMS:
        print(f"[demo8] === {arm} ===", flush=True)
        all_records += run_arm(arm, args.timeout)

    completion = {a: sum(1 for r in all_records if r["arm"] == a and r["gate_passed"])
                  for a in ARMS}
    with open(os.path.join(RAW, "records.json"), "w") as fh:
        json.dump({"prereg_sha256": file_hash(PREREG), "tasks": [t["id"] for t in TASKS],
                   "records": all_records, "completion": completion}, fh, indent=2)

    # SEAL write-once BEFORE any scoring (prereg §Integrity)
    man = Manifest(os.path.join(RAW, "manifest.jsonl"))
    for name in sorted(os.listdir(RAW)):
        if name != "manifest.jsonl":
            seal(os.path.join(RAW, name), man, root=RAW, kind="raw")
    print(f"[demo8] sealed {len(os.listdir(RAW))-1} files; completion={completion}")
    print("[demo8] collection COMPLETE — run demo/score_demo8.py separately to score.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
