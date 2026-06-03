"""Plateau real adapter — a context-bounded step DRIVER (headless Claude Code worker).

The bound comes from owning the message loop, NOT from a hook (a Claude Code hook can
only append `additionalContext`; it cannot remove the transcript). So the driver *is* the
loop. Each step it assembles a prompt for a FRESH `claude -p` worker that sees ONLY the
inflated bounded signal + the step's sub-task — never the prior transcript. The worker's
huge intermediate context stays isolated in its own headless session; only a compact reply
returns. Facts are gated into the signal between steps (a Measurement that re-verifies —
e.g. a file hash). A paired CONTROL arm carries the full transcript, so the context bound is
MEASURED against it, not asserted.

This is `demo/run_demo6.py` generalized: operator-hand-dispatch -> autonomous driver, the
demo task -> any task. Backends: `mock` (free, deterministic plumbing — NOT a result) and
`claude_p` (real headless Claude Code = PAID).

Bright line: measures context EFFICIENCY (carried-token bound at completion parity). It
says nothing about understanding or any inner state.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import dataclass, field

from .signal import (Measurement, Thought, RelationalState, SelfState,
                     apply_gate, set_ground_root)
from .continuum import emit, inflate
from .metrics import ArmCurve, decide

LESS_CAP = 12  # bound the carried lessons so the signal can't grow unbounded


def _tok(s: str) -> int:
    return max(1, len(s) // 4)


# ---------------------------------------------------------------- task + step spec
@dataclass
class Step:
    subtask: str                 # what the worker must do this step (depends on prior)
    expect_file: str = ""        # repo-relative path the step should leave grounded (optional)


@dataclass
class Task:
    spec: str                    # fixed task header, identical for both arms (no arm token)
    steps: list[Step]


# ---------------------------------------------------------------- prompt assembly
HEADER = ("CONTEXT CARRIED INTO THIS STEP (read it, do ONLY this step's sub-task, then STOP):\n")
EMIT_RULES = (
    "\n\nWhen done, end your reply with two sections, nothing after them:\n"
    "CARRY: <one short lesson/decision the next step must know>\n"
    "GATE: <repo-relative-path> :: sha256:<hash of that file you just wrote>   (one per fact; "
    "omit if you wrote no file). Only facts whose hash re-verifies will be carried.")


def _render(sig: RelationalState) -> str:
    p = []
    if sig.open_goals: p.append("goals: " + " | ".join(sig.open_goals))
    if sig.stance: p.append("stance: " + sig.stance)
    if sig.lessons: p.append("lessons: " + " | ".join(sig.lessons))
    if sig.pointers: p.append("pointers: " + " | ".join(sig.pointers))
    if sig.verified_facts:
        p.append("verified facts: " + " | ".join(vf["claim"] for vf in sig.verified_facts))
    return "\n".join(p) if p else "(seed — no signal yet)"


def assemble(task: Task, k: int, *, mode: str, transcript: list, signal_blob: str) -> str:
    """HEAD is byte-identical across arms; ONLY the trailing payload differs (transcript vs
    bounded signal) — a diff at the same step shows only the payload bytes changed."""
    head = f"[step {k+1}/{len(task.steps)}] {task.spec}\n\nSUB-TASK: {task.steps[k].subtask}\n\n{HEADER}"
    if mode == "control":
        payload = ""
        for i, (p, r) in enumerate(transcript, 1):
            payload += f"\n--- prior step {i} PROMPT ---\n{p}\n--- prior step {i} REPLY ---\n{r}\n"
        return head + payload + EMIT_RULES
    return head + inflate_render(signal_blob) + EMIT_RULES


def inflate_render(signal_blob: str) -> str:
    return _render(inflate(signal_blob, fresh=True).state)


# ---------------------------------------------------------------- the gate (between steps)
_GATE = re.compile(r"GATE:\s*(?P<src>[^\s:][^:]*?)\s*::\s*(?P<val>sha256:[0-9a-f]{64})", re.I)
_CARRY = re.compile(r"CARRY:\s*(?P<c>.+)")


def gate_reply(signal: RelationalState, reply: str, cwd: str) -> tuple[RelationalState, dict]:
    """Fold the worker's reply into the signal: admit ONLY GATE facts whose file-hash
    re-verifies in `cwd` now; append the CARRY lesson (capped). Returns (new_signal, report)."""
    set_ground_root(cwd)
    thoughts = [Thought(claim=f"{m.group('src').strip()} present",
                        grounding=Measurement("file_hash", m.group("src").strip(), m.group("val")))
                for m in _GATE.finditer(reply)]
    before = {vf["claim"] for vf in signal.verified_facts}
    new = apply_gate(SelfState(signal=signal, thoughts=thoughts))
    admitted = sorted({vf["claim"] for vf in new.verified_facts} - before)
    dropped = [t.claim for t in thoughts if t.claim not in {vf["claim"] for vf in new.verified_facts}]
    cm = _CARRY.search(reply)
    if cm:
        les = cm.group("c").strip()[:200]
        if les and les not in new.lessons:
            new.lessons = (new.lessons + [les])[-LESS_CAP:]
    return new, {"admitted": admitted, "dropped_ungrounded": dropped}


# ---------------------------------------------------------------- worker backends
def worker_claude_p(prompt: str, cwd: str) -> str:
    """Real headless Claude Code — a fresh session that sees ONLY `prompt`. PAID."""
    r = subprocess.run(["claude", "-p", prompt, "--output-format", "json"],
                       cwd=cwd, capture_output=True, text=True, timeout=1800)
    try:
        return json.loads(r.stdout).get("result", r.stdout)
    except Exception:
        return r.stdout or r.stderr


def make_mock_worker():
    """Deterministic FREE stub — NOT a result. 'Does' the sub-task by writing expect_file,
    then emits a CARRY line + a correct GATE line (admitted) AND a bogus one (must drop)."""
    from .integrity import file_hash

    def w(prompt: str, cwd: str) -> str:
        m = re.search(r"SUB-TASK: (.+)", prompt)
        sub = m.group(1) if m else "step"
        # find the expect_file the harness embedded for this step
        fm = re.search(r"EXPECT_FILE=(\S+)", prompt)
        out = f"did: {sub}\nCARRY: completed '{sub[:60]}'; next step builds on it."
        if fm:
            rel = fm.group(1)
            p = os.path.join(cwd, rel)
            os.makedirs(os.path.dirname(p) or cwd, exist_ok=True)
            with open(p, "w") as f:
                f.write(f"# {sub}\n")
            out += f"\nGATE: {rel} :: {file_hash(p)}"
            out += f"\nGATE: nonexistent_{rel} :: sha256:{'0'*64}"  # bogus -> must be DROPPED
        return out
    return w


# ---------------------------------------------------------------- the loop
def run_arm(task: Task, mode: str, worker, cwd: str, raw_dir: str = "") -> ArmCurve:
    """Run one arm. mode='signal' carries the bounded signal; mode='control' carries the
    full transcript. Returns the ArmCurve (per-step CONTEXT TOKENS = size of the prompt the
    worker actually received — the thing being bounded). If raw_dir is set, each step's
    prompt+reply is written there (for seal-before-score on a paid run)."""
    os.makedirs(cwd, exist_ok=True)
    signal = RelationalState(open_goals=[task.steps[-1].subtask[:60]], stance="bounded, re-grounded")
    blob = emit(SelfState(signal=signal))
    transcript, ctx_tokens, completions = [], [], []
    for k, step in enumerate(task.steps):
        prompt = assemble(task, k, mode=mode, transcript=transcript, signal_blob=blob)
        if step.expect_file:
            prompt += f"\n\nEXPECT_FILE={step.expect_file}"
        ctx_tokens.append(_tok(prompt))                      # <-- the measured bound
        reply = worker(prompt, cwd)
        transcript.append((prompt, reply))                   # control carries this; signal won't
        if raw_dir:
            os.makedirs(raw_dir, exist_ok=True)
            open(os.path.join(raw_dir, f"{mode}_step{k}_prompt.txt"), "w").write(prompt)
            open(os.path.join(raw_dir, f"{mode}_step{k}_reply.md"), "w").write(reply)
        if mode == "signal":
            signal, _ = gate_reply(signal, reply, cwd)
            blob = emit(SelfState(signal=signal))
        # completion = the expected file is grounded on disk (objective, not the model's word)
        done = (not step.expect_file) or os.path.isfile(os.path.join(cwd, step.expect_file))
        completions.append(1 if done else 0)
    return ArmCurve(mode, list(range(len(task.steps))), ctx_tokens, completions).finalize()


def run(task: Task, backend: str, work_root: str, raw_dir: str = "") -> dict:
    """Run both arms (control=full history, signal=bounded) and score the bound. If raw_dir
    is set, every step's prompt+reply is written there (seal it BEFORE reading this verdict)."""
    worker = worker_claude_p if backend == "claude_p" else make_mock_worker()
    control = run_arm(task, "control", worker, os.path.join(work_root, "control"), raw_dir)
    signal = run_arm(task, "signal", worker, os.path.join(work_root, "signal"), raw_dir)
    d = decide(control, signal)
    d["backend"] = backend
    d["control_context"] = control.prompt_tokens
    d["signal_context"] = signal.prompt_tokens
    return d


# ---------------------------------------------------------------- labeled free plumbing
def run_mock_plumbing(work_root: str | None = None) -> dict:
    """LABELED PLUMBING (FREE) — deterministic mock worker, NOT a result. Proves the loop:
    the signal arm's per-step context stays bounded while the control arm grows, the gate
    admits a real fact and drops a bogus one, and the scorer returns a verdict."""
    import tempfile
    work_root = work_root or tempfile.mkdtemp(prefix="plateau_driver_")
    task = Task(spec="Build a tiny module incrementally; each step adds one file the next needs.",
                steps=[Step(f"add layer {i} (depends on all prior)", expect_file=f"layer{i}.py")
                       for i in range(8)])
    d = run(task, backend="mock", work_root=work_root)
    sc, cc = d["signal_context"], d["control_context"]
    # prove the gate fired on a real reply (admit real, drop bogus)
    from .integrity import file_hash
    import tempfile as _t
    probe = _t.mkdtemp()
    open(os.path.join(probe, "x.py"), "w").write("# x\n")
    sig0 = RelationalState()
    reply = f"CARRY: did x\nGATE: x.py :: {file_hash(os.path.join(probe,'x.py'))}\nGATE: y.py :: sha256:{'0'*64}"
    _, rep = gate_reply(sig0, reply, probe)
    return {"LABEL": "MOCK PLUMBING — deterministic mock worker, NOT a continuity result",
            "signal_context_per_step": sc, "control_context_per_step": cc,
            "signal_slope": d["plateau"]["slope"], "control_slope": d["control"]["slope"],
            "context_flattened_<=25pct_control": d["claims"]["context_flattened_<=25%_control"],
            "completion_parity": d["claims"]["completion_parity"],
            "anti_rig_control_climbs": d["claims"]["anti_rig_control_climbs"],
            "verdict_on_mock": d["verdict"],
            "gate_admitted": rep["admitted"], "gate_dropped": rep["dropped_ungrounded"]}


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "mock":
        print(json.dumps(run_mock_plumbing(), indent=2))
    else:
        print("usage: python -m plateau.driver mock   "
              "(live `claude_p` run is paid — call run(task, 'claude_p', work_root) explicitly)")
