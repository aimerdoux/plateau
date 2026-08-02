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

import argparse
import json
import os
import re
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
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


def _expand_braces(token: str) -> list:
    """Expand one `pre{a,b}post` group into ['prea post'...]; recurse for nested groups.
    Anything without a brace group returns unchanged."""
    m = re.match(r"^([^{]*)\{([^{}]*)\}(.*)$", token)
    if not m:
        return [token]
    pre, inner, post = m.groups()
    out = []
    for part in inner.split(","):
        out.extend(_expand_braces(pre + part.strip() + post))
    return out


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

    def touched_paths(self) -> set:
        """The file paths this task writes, derived from its DELIVERABLE column.

        Used to detect write collisions BEFORE dispatch (see `conflicts`). No grammar
        change was needed: the deliverable column already names what the task produces.
        Brace groups (`pkg/{a.py,b.py}`) expand; prose words that are not path-like are
        ignored, so a deliverable of "(none)" or "docs updated" contributes nothing and
        such a task is simply never treated as colliding."""
        paths = set()
        # split on WHITESPACE first, expand brace groups, and only then on commas — a
        # comma inside `{a.py,b.py}` belongs to the group, not to a list of deliverables.
        for token in self.deliverable.split():
            token = token.strip("`'\"()[]<>")
            if not token:
                continue
            for expanded in _expand_braces(token):
                for piece in expanded.split(","):
                    piece = piece.strip("`'\"()[]<>,")
                    if piece and ("/" in piece or re.search(r"\.[A-Za-z0-9]{1,8}$", piece)):
                        paths.add(piece.rstrip("/"))
        return paths


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


# ------------------------------------------------- dispatch safety --------
# Two preflight checks the self-hosting run showed were missing (both named in its own
# report as gaps): parallel dispatch had no collision detection — the parent hand-sequenced
# tasks that shared a file — and nothing verified that a gate could actually be RUN before
# workers were spent producing something to run it on.


def _paths_overlap(a: str, b: str) -> bool:
    """Do two declared paths refer to the same write target? Deliberately CONSERVATIVE —
    a missed collision is a clobber, a false one only costs some parallelism:

      * exact match;
      * directory containment (`demo/raw7` vs `demo/raw7/x.json`);
      * bare-filename shorthand vs a full path with the same basename — real plans write
        "plateau/agency/__main__.py + control.py", and that bare `control.py` IS
        `plateau/agency/control.py`. Matching on basename alone here is what the
        self-hosting run's own PLAN.md needed.
    """
    if a == b:
        return True
    if a.startswith(b.rstrip("/") + "/") or b.startswith(a.rstrip("/") + "/"):
        return True
    if ("/" in a) != ("/" in b):                 # one is bare shorthand
        return os.path.basename(a) == os.path.basename(b)
    return False


def conflicts(tasks: list) -> list:
    """Write collisions among tasks considered for PARALLEL dispatch.

    Returns `[(id_a, id_b, [shared paths])]` for every pair whose deliverables overlap.
    Two writing agents on one file is the shared-worktree clobber the Parent Agent Manual
    calls out; this makes it detectable instead of a thing the parent must remember."""
    out = []
    for i, a in enumerate(tasks):
        for b in tasks[i + 1:]:
            shared = sorted({f"{pa}~{pb}" if pa != pb else pa
                             for pa in a.touched_paths() for pb in b.touched_paths()
                             if _paths_overlap(pa, pb)})
            if shared:
                out.append((a.id, b.id, shared))
    return out


def parallel_batches(tasks: list) -> list:
    """Greedily pack tasks into ordered batches that are safe to dispatch concurrently:
    no two tasks in a batch write the same path. Order within the plan is preserved, so a
    task never jumps ahead of one it was written after. Every batch is collision-free by
    construction — `conflicts(batch)` is empty for each returned batch."""
    batches = []
    for task in tasks:
        placed = False
        for batch in batches:
            if not any(_paths_overlap(pa, pb) for other in batch
                       for pa in task.touched_paths() for pb in other.touched_paths()):
                batch.append(task)
                placed = True
                break
        if not placed:
            batches.append([task])
    return batches


def preflight(tasks: list, root: str) -> dict:
    """RECON's R1 capability probe, made executable: can each gate actually RUN here?

    For every task, probe the gate's leading command with `command -v` (a harmless
    existence check — the gate itself is NOT executed, so this stays cheap and has no side
    effects). A gate whose command is missing would fail at VERIFY *after* a worker had
    already been spent on the task; catching it up front turns that into a preflight error.

    Returns {ok: bool, runnable: [ids], missing: [{task, command}], batches: n,
    conflicts: [...]} — a single go/no-go the parent can read before dispatching."""
    runnable, missing = [], []
    for task in tasks:
        # leading word of the gate, ignoring env-var prefixes like FOO=bar
        words = [w for w in task.gate.split() if "=" not in w.split("/")[0]]
        cmd = words[0] if words else ""
        if not cmd:
            missing.append({"task": task.id, "command": "(empty gate)"})
            continue
        probe = subprocess.run(["/bin/sh", "-c", f"command -v {cmd}"], cwd=root,
                               capture_output=True, text=True)
        (runnable if probe.returncode == 0 else missing).append(
            task.id if probe.returncode == 0 else {"task": task.id, "command": cmd})
    cfl = conflicts(tasks)
    return {"ok": not missing, "runnable": runnable, "missing": missing,
            "batches": len(parallel_batches(tasks)), "conflicts": cfl}


# --------------------------------------------------------------- CLI ------
# `python -m plateau.agency.control {init,status,verify}` makes the loop operable from a
# shell, not just importable — the same three verbs the gatekeeper Stop hook and the parent's
# Monitor/Verify verbs already use, exposed directly so a human or a dispatch script can ask
# "where does this run stand" without reading control.py source.


def append_journal(control_dir: str, task_id: str, state: str, action: str, result: str,
                   next_step: str) -> str:
    """E3/V1: append one JOURNAL.md row — the receipt for a EXECUTE/VERIFY step. Fixed
    grammar `ts | T<n> | state | action | result | next` (mirrors the PLAN row grammar);
    fields are whitespace-flattened so an embedded '|' or newline can never desync the
    columns a reader splits on. Returns the exact line written."""
    os.makedirs(control_dir, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    def _flat(value: str) -> str:
        return " ".join(str(value).split())

    line = " | ".join([ts, _flat(task_id), _flat(state), _flat(action), _flat(result),
                       _flat(next_step)])
    with open(os.path.join(control_dir, "JOURNAL.md"), "a") as fh:
        fh.write(line + "\n")
    return line


def write_blocked(control_dir: str, klass: str, attempts: list, unblock: str,
                  options: list) -> str:
    """B3: write BLOCKED.md — the legal-pause artifact the gatekeeper's ARMED check and
    `cmd_status`'s `blocked` sensor both key off (`class:` line present). `attempts` is a
    list of either `(what, result)` pairs or pre-formatted strings; `options` is the 2-3-item
    decision menu B2 requires before escalating. Overwrites any prior BLOCKED.md — a run is
    blocked on at most one obstacle at a time. Returns the path written."""
    os.makedirs(control_dir, exist_ok=True)
    lines = ["# BLOCKED", "", f"class: {klass}", "", "## Attempts", ""]
    for i, attempt in enumerate(attempts, start=1):
        if isinstance(attempt, (tuple, list)) and len(attempt) == 2:
            what, result = attempt
            lines.append(f"{i}. {what} -> {result}")
        else:
            lines.append(f"{i}. {attempt}")
    lines += ["", "## Smallest unblocking action", "", unblock, "", "## Decision menu", ""]
    for i, option in enumerate(options, start=1):
        lines.append(f"{i}. {option}")
    lines.append("")
    path = os.path.join(control_dir, "BLOCKED.md")
    with open(path, "w") as fh:
        fh.write("\n".join(lines))
    return path


def read_status(control_dir: str) -> dict:
    """MONITOR: read the gatekeeper's `STATE.json` cheap disk meter (written by
    `adapters/claude_code/control/gatekeeper.sh` on every Stop) without recomputing
    anything — the pure-read counterpart to `cmd_status`, which re-derives verdict from
    PLAN.md/BLOCKED.md directly. Missing/unreadable state (no run has hit Stop yet, or no
    gatekeeper wired) is not an error: it reports `verdict: NO_STATE` rather than raising, so
    a poller can call this before a run has produced anything."""
    path = os.path.join(control_dir, "STATE.json")
    try:
        with open(path) as fh:
            data = json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"ts": None, "unchecked": None, "verdict": "NO_STATE", "strict": None,
                "_path": path}
    data.setdefault("_path", path)
    return data


def _read_text(path: str) -> str:
    try:
        with open(path) as fh:
            return fh.read()
    except FileNotFoundError:
        return ""


def cmd_init(control_dir: str) -> dict:
    """Scaffold a control dir. Never overwrites a file that already exists — `init` must be
    safe to re-run against a live run without clobbering RECON/PLAN work in progress."""
    templates = {
        "RECON.md": "# RECON\n\nProbe, don't assume. Every claim below cites a probe "
                    "(command + literal output).\n",
        # NOTE: the example row deliberately uses [_], NOT [ ] — a literal "- [ ]" here
        # would be parsed by parse_plan as a REAL unchecked task, arming the gatekeeper on a
        # placeholder and making a freshly-scaffolded dir look like a planned run.
        "PLAN.md": "# PLAN\n\nRow grammar (fixed, machine-parsed by `parse_plan`);\n"
                   "copy this shape, with [ ] in place of [_]:\n"
                   "    - [_] T1 | <action> | <deliverable> | GATE: <command> | EXPECT: <observable>\n",
        "JOURNAL.md": "# JOURNAL\n\nts | T<n> | state | action | result | next\n",
    }
    os.makedirs(control_dir, exist_ok=True)
    os.makedirs(os.path.join(control_dir, "workers"), exist_ok=True)
    created = []
    for name, body in templates.items():
        path = os.path.join(control_dir, name)
        if not os.path.exists(path):
            with open(path, "w") as fh:
                fh.write(body)
            created.append(name)
    return {"control_dir": control_dir, "created": created}


def cmd_status(control_dir: str) -> dict:
    """MONITOR verb as a CLI read: a cheap disk meter, zero gates executed. Reports the
    checkbox state of PLAN.md plus whether RECON.md / a valid BLOCKED.md are present — exactly
    the sensors the gatekeeper Stop hook already keys off (see adapters/claude_code/control/
    gatekeeper.sh), surfaced for a human or script to poll without shelling into bash."""
    plan_path = os.path.join(control_dir, "PLAN.md")
    tasks = parse_plan(_read_text(plan_path))
    checked = [t.id for t in tasks if t.checked]
    unchecked = [t.id for t in tasks if not t.checked]
    blocked_text = _read_text(os.path.join(control_dir, "BLOCKED.md"))
    blocked = bool(re.search(r"(?im)^class:", blocked_text))

    if not tasks:
        verdict = "NO_PLAN"
    elif blocked:
        verdict = "ALLOW_BLOCKED"
    elif unchecked:
        verdict = "BLOCK"
    else:
        verdict = "ALLOW_DONE"

    return {
        "control_dir": control_dir,
        "plan_exists": os.path.isfile(plan_path),
        "recon_exists": os.path.isfile(os.path.join(control_dir, "RECON.md")),
        "task_count": len(tasks),
        "checked": checked,
        "unchecked": unchecked,
        "blocked": blocked,
        "verdict": verdict,
    }


def cmd_verify(control_dir: str, root: str, strict: bool = False, timeout: int = 120) -> dict:
    """The DONE predicate (I2), as a CLI verb. Default is the cheap checkbox scan — safe to
    call from *inside* a task's own GATE (it never executes a command, so a plan that gates a
    task on `verify` cannot make the gate invoke itself). `--strict` re-runs EVERY gate fresh
    (`verify_plan`, the V3 regression) for the ground-truth answer; that mode shells out to
    each PLAN row's GATE command and so must not be pointed at a plan whose own GATE is this
    same `verify` invocation, or it recurses. Keep the response key `unchecked` present in
    both modes: it is the single field callers (and this task's own GATE) key off."""
    plan_path = os.path.join(control_dir, "PLAN.md")
    text = _read_text(plan_path)
    tasks = parse_plan(text)
    if not tasks:
        return {"control_dir": control_dir, "task_count": 0, "unchecked": [],
                "verdict": "NO_PLAN", "strict": strict}

    if strict:
        v = verify_plan(text, root, os.path.join(control_dir, "gates"), timeout=timeout)
        return {
            "control_dir": control_dir,
            "task_count": len(tasks),
            "passed": v.passed,
            "unchecked": v.failed,     # gates that do not re-verify right now
            "verdict": "DONE" if v.done else "BLOCK",
            "strict": True,
        }

    unchecked = [t.id for t in tasks if not t.checked]
    return {
        "control_dir": control_dir,
        "task_count": len(tasks),
        "unchecked": unchecked,
        "verdict": "BLOCK" if unchecked else "DONE",
        "strict": False,
    }


def _emit(result: dict, as_json: bool) -> None:
    if as_json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        for key, value in result.items():
            print(f"{key}: {value}")


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="python -m plateau.agency.control",
                                 description="Control-loop CLI: init / status / verify a run.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_init = sub.add_parser("init", help="scaffold a control dir (non-destructive)")
    p_init.add_argument("--control-dir", default=".plateau/control")
    p_init.add_argument("--json", action="store_true")

    p_status = sub.add_parser("status", help="MONITOR: read PLAN.md checkbox state, no gates run")
    p_status.add_argument("--control-dir", default=".plateau/control")
    p_status.add_argument("--json", action="store_true")

    p_verify = sub.add_parser("verify", help="the DONE predicate; --strict re-runs every gate")
    p_verify.add_argument("--control-dir", default=".plateau/control")
    p_verify.add_argument("--root", default=".", help="repo root gate commands run in (--strict only)")
    p_verify.add_argument("--strict", action="store_true")
    p_verify.add_argument("--timeout", type=int, default=120)
    p_verify.add_argument("--json", action="store_true")

    p_adapt = sub.add_parser("adapt", help="GAP ANALYSIS: compare FORECAST.md to the recorded "
                                           "gate artifacts; classify blockers; write RECALIBRATE.md")
    p_adapt.add_argument("--control-dir", default=".plateau/control")
    p_adapt.add_argument("--write", action="store_true",
                         help="append the DRIFT/REFUTED gaps to RECALIBRATE.md")
    p_adapt.add_argument("--json", action="store_true")

    p_pre = sub.add_parser("preflight", help="before dispatch: can every gate run, and "
                                             "which tasks are safe to run in parallel?")
    p_pre.add_argument("--control-dir", default=".plateau/control")
    p_pre.add_argument("--root", default=".", help="repo root the probes run in")
    p_pre.add_argument("--json", action="store_true")

    return ap


def cmd_adapt(control_dir: str, write: bool = False) -> dict:
    """The predict -> observe -> gap -> recalibrate read. Compares each task's FORECAST to its
    recorded gate ARTIFACT, classifies every failure into a blocker class with a smallest
    unblocking action, and (with --write) appends the DRIFT/REFUTED gaps to RECALIBRATE.md.

    Reads only — it never runs a gate, so it is safe to poll mid-run and safe to call from a
    task's own GATE. `verdict` is ADAPT when something needs recalibration, STEADY otherwise."""
    from plateau.agency import adapt as A
    tasks = parse_plan(_read_text(os.path.join(control_dir, "PLAN.md")))
    forecasts = A.parse_forecast(_read_text(os.path.join(control_dir, "FORECAST.md")))
    gaps = A.analyze_plan(tasks, forecasts, os.path.join(control_dir, "gates"))
    summary = A.summarize(gaps)
    written = A.write_recalibration(control_dir, gaps) if write else ""
    return {
        "control_dir": control_dir,
        "task_count": len(tasks),
        "forecasts": len(forecasts),
        "gaps": [g.as_dict() for g in gaps],
        "summary": summary,
        "recalibrate_path": written,
        "verdict": "ADAPT" if summary["needs_recalibration"] else "STEADY",
    }


def cmd_preflight(control_dir: str, root: str) -> dict:
    """Pre-dispatch go/no-go: gate runnability + the collision-free parallel batches.
    Exit code is non-zero when a gate cannot run, so a dispatch script can gate on it."""
    tasks = parse_plan(_read_text(os.path.join(control_dir, "PLAN.md")))
    pf = preflight(tasks, root)
    return {
        "control_dir": control_dir,
        "task_count": len(tasks),
        "gates_runnable": len(pf["runnable"]),
        "missing_commands": pf["missing"],
        "collisions": [{"a": a, "b": b, "shared": s} for a, b, s in pf["conflicts"]],
        "parallel_batches": [[t.id for t in batch] for batch in parallel_batches(tasks)],
        "verdict": "GO" if pf["ok"] else "NO_GO",
    }


def main(argv: Optional[list] = None) -> int:
    args = build_parser().parse_args(argv)
    if args.cmd == "init":
        result = cmd_init(args.control_dir)
    elif args.cmd == "status":
        result = cmd_status(args.control_dir)
    elif args.cmd == "adapt":
        result = cmd_adapt(args.control_dir, write=args.write)
    elif args.cmd == "preflight":
        result = cmd_preflight(args.control_dir, args.root)
        _emit(result, args.json)
        return 0 if result["verdict"] == "GO" else 1
    else:
        result = cmd_verify(args.control_dir, args.root, strict=args.strict, timeout=args.timeout)
    _emit(result, args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
