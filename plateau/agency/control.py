"""plateau.agency.control — the file-state control loop, wired to Plateau's gate.

The control loop (RECON -> PLAN -> EXECUTE -> VERIFY -> {DONE | BLOCKED}) externalizes an
agent's working state to disk (RECON.md, PLAN.md, JOURNAL.md) so it survives context loss,
and makes **DONE a predicate, never a feeling**: DONE iff every PLAN gate re-verifies now.

That predicate is *exactly Plateau's gate*. A PLAN row

    - [ ] T3 | add report CLI | plateau/report.py | GATE: pytest -q tests/test_report.py | EXPECT: exit0

says "T3 is done only while its GATE re-verifies." Plateau already has one rule for
"a claim persists only while its Measurement re-verifies" — the gate (`plateau.signal`).
This module is the bridge: it turns PLAN rows into gated facts so the carried SIGNAL's
`verified_facts` ARE the checked boxes, re-grounded every step.

Trust boundary (injection-safe by construction, mirroring
`signal.Measurement.reverify`'s refusal to execute GATE sources):

  * PLAN GATE commands are authored by the PARENT/operator. Only the VALIDATOR here
    (`run_gate`) executes them, and it records the outcome to a result ARTIFACT on disk.
  * A sub-agent's "I finished T3" reply is UNTRUSTED and is NEVER executed. It is admitted
    into the signal only by hash-binding that recorded artifact via an `exit_code`
    Measurement. So parent-authored gates run; untrusted claims are only ever hash-checked.

Pure stdlib; imports only `plateau`. No host paths baked in (grounding resolves via
`set_ground_root` / the artifact's path).
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import dataclass, field
from typing import Optional

from plateau import Measurement, Thought, RelationalState, SelfState, apply_gate
from plateau.integrity import file_hash

# PLAN row grammar (fixed):
#   - [ ] T<n> | <action> | <deliverable> | GATE: <command or check> | EXPECT: <observable>
# Checked rows use "- [x]". Everything after GATE:/EXPECT: is taken verbatim.
_ROW = re.compile(
    r"^- \[(?P<mark>[ xX])\]\s*(?P<id>T[^|]*?)\s*\|"
    r"\s*(?P<action>.*?)\s*\|"
    r"\s*(?P<deliverable>.*?)\s*\|"
    r"\s*GATE:\s*(?P<gate>.*?)\s*\|"
    r"\s*EXPECT:\s*(?P<expect>.*?)\s*$"
)


@dataclass
class Task:
    id: str
    action: str
    deliverable: str
    gate: str
    expect: str          # "exit0" or a substring that must appear in the gate output
    checked: bool = False
    raw: str = ""

    def fact_claim(self) -> str:
        return f"{self.id} done"


def parse_plan(text: str) -> list[Task]:
    """Parse PLAN.md into Tasks. Malformed rows (a task without an executable GATE) are
    skipped — per the protocol, 'a task without an executable gate is not a task.'"""
    tasks = []
    for line in text.splitlines():
        m = _ROW.match(line.strip())
        if not m:
            continue
        tasks.append(Task(
            id=m.group("id").strip(),
            action=m.group("action").strip(),
            deliverable=m.group("deliverable").strip(),
            gate=m.group("gate").strip(),
            expect=m.group("expect").strip(),
            checked=m.group("mark").lower() == "x",
            raw=line.strip(),
        ))
    return tasks


def plan_all_checked(text: str) -> bool:
    """Pure predicate over checkbox state: are there zero unchecked rows? (Cheap DONE
    proxy; the TRUE predicate is `verify_plan` re-running every gate — see V3.)"""
    tasks = parse_plan(text)
    return bool(tasks) and all(t.checked for t in tasks)


def run_gate(task: Task, root: str, artifact_dir: str, timeout: int = 120) -> dict:
    """VALIDATOR: execute a PARENT-AUTHORED gate and record the outcome to a JSON artifact.

    The artifact's ``exit_code`` is 0 iff the gate genuinely PASSED — the command exited 0
    AND (EXPECT == 'exit0' OR EXPECT is a substring of the output). That way an
    ``exit_code`` Measurement over the artifact re-verifies True exactly when the task is
    done, and the gate (which never runs the command itself) can certify it safely.

    Returns the artifact dict; also writes it to ``artifact_dir/<id>.gate.json``.
    """
    os.makedirs(artifact_dir, exist_ok=True)
    try:
        proc = subprocess.run(task.gate, shell=True, cwd=root, capture_output=True,
                              text=True, timeout=timeout)
        raw_code = proc.returncode
        output = (proc.stdout or "") + (proc.stderr or "")
        timed_out = False
    except subprocess.TimeoutExpired as e:
        raw_code = 124
        output = (e.stdout or "") if isinstance(e.stdout, str) else ""
        timed_out = True

    if task.expect.lower() in ("", "exit0", "exit 0"):
        matched = raw_code == 0
    else:
        matched = raw_code == 0 and (task.expect in output)

    # exit_code the Measurement will read: 0 iff the whole gate passed, else non-zero.
    effective = 0 if matched else (raw_code if raw_code != 0 else 1)
    artifact = {
        "task": task.id,
        "gate": task.gate,
        "expect": task.expect,
        "raw_exit_code": raw_code,
        "matched": matched,
        "timed_out": timed_out,
        "exit_code": effective,                 # what the exit_code Measurement asserts == 0
        "output_tail": output[-800:],
    }
    path = os.path.join(artifact_dir, f"{task.id}.gate.json")
    with open(path, "w") as fh:
        json.dump(artifact, fh, indent=2, sort_keys=True)
    artifact["_path"] = path
    return artifact


def task_fact(task: Task, artifact_path: str, root: str) -> Thought:
    """Build the gated fact for a task from its result ARTIFACT (never from the sub-agent's
    word). grounding = an ``exit_code`` Measurement: the artifact must hash unchanged AND
    record ``exit_code == 0``. The signal gate admits it only then."""
    rel = os.path.relpath(artifact_path, root)
    return Thought(
        claim=task.fact_claim(),
        grounding=Measurement(kind="exit_code", source=rel, value=file_hash(artifact_path)),
    )


@dataclass
class PlanVerdict:
    passed: list[str] = field(default_factory=list)     # task ids whose gate re-verifies now
    failed: list[str] = field(default_factory=list)     # task ids whose gate does not
    artifacts: dict = field(default_factory=dict)       # id -> artifact path

    @property
    def done(self) -> bool:
        return bool(self.passed or self.failed) and not self.failed


def verify_plan(text: str, root: str, artifact_dir: str, timeout: int = 120) -> PlanVerdict:
    """The TRUE DONE predicate (V3 regression): re-run EVERY gate fresh, right now. DONE
    iff all pass. This is Plateau's rule applied to the plan — a plan is done only while
    every one of its gates re-verifies against reality."""
    v = PlanVerdict()
    for task in parse_plan(text):
        art = run_gate(task, root, artifact_dir, timeout=timeout)
        v.artifacts[task.id] = art["_path"]
        (v.passed if art["exit_code"] == 0 else v.failed).append(task.id)
    return v


def gate_tasks_into_signal(signal: RelationalState, text: str, root: str,
                           artifact_dir: str, timeout: int = 120) -> tuple[RelationalState, PlanVerdict]:
    """Run every PLAN gate (validator), then fold the PASSING tasks into the SIGNAL through
    Plateau's real gate as ``T<n> done`` verified_facts. The returned signal's
    verified_facts are precisely the tasks whose recorded gate artifact re-verifies — so
    the carried state IS the checked-box set, and a task that stops passing drops out on the
    next inflate/ground. Returns (new_signal, verdict)."""
    v = verify_plan(text, root, artifact_dir, timeout=timeout)
    thoughts = []
    for task in parse_plan(text):
        if task.id in v.passed:
            thoughts.append(task_fact(task, v.artifacts[task.id], root))
    new_signal = apply_gate(SelfState(signal=signal, thoughts=thoughts))
    return new_signal, v
