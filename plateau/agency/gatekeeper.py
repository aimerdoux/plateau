#!/usr/bin/env python3
"""plateau.agency.gatekeeper — the control loop's Stop-hook controller (the `gatekeeper` hook mode).

Makes the control loop's I4 ("the only legal exits are DONE or a BLOCKED report")
mechanical: on Stop it blocks stopping while the run is not done. This module is the whole
implementation; `adapters/claude_code/control/gatekeeper.sh` is a shim that runs it.

ARMED-ONLY: it acts solely when a control run is active, i.e. `<CONTROL_DIR>/PLAN.md` exists
(`CONTROL_DIR`, default `.plateau/control`; a relative path is resolved against the payload's
`cwd`, then against that directory's git toplevel). With no PLAN.md it prints nothing, so an
ordinary session -- and every other Plateau hook alongside it -- is untouched.

Release (prints nothing) <=> a BLOCKED.md with a `class:` line, OR DONE: the plan has task rows,
none is `- [ ]`, and no checked row's `gates/<id>.gate.json` records a non-zero `exit_code`.
Anything else prints one `{"decision": "block", "reason": ...}` line. `RUN_GATES=1` (strict)
also re-runs every checked row's GATE with `bash -c` under `GATE_TIMEOUT` (seconds, default
120): a gate passes iff it exits 0 AND (EXPECT is `exit0` OR EXPECT occurs in its output).

STATE.json in the control dir is the cheap disk meter (`ts`, `unchecked`, `verdict`, `strict`,
`blocks`, `fingerprint`, `started`; `plateau.agency.control.read_status` reads it). Stall cap: a
run whose PLAN.md and JOURNAL.md have not changed across `GATEKEEPER_MAX_BLOCKS` consecutive
blocks (default 10, `0` disables) is released with verdict `ALLOW_STALLED` and a stderr note, so
a stuck agent can never be trapped by its own hook forever. A block that starts within
`_TWIN_S` of the previous one over the same files is taken as the same Stop reaching a doubly
registered hook: it repeats that decision and is not counted again.

Env: CONTROL_DIR, RUN_GATES, GATE_TIMEOUT, GATEKEEPER_MAX_BLOCKS. Stdlib only. Like every
Plateau hook it never raises and always exits 0 -- a hook must not be why a session breaks.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

DEFAULT_CONTROL_DIR = ".plateau/control"
DEFAULT_GATE_TIMEOUT_S = 120.0
DEFAULT_MAX_BLOCKS = 10
# Two copies of one Stop (plugin + `plateau init --global`) start milliseconds apart; a real
# next Stop needs a model turn in between, so it starts seconds later.
_TWIN_S = 1.0

# One PLAN task row. Identical to `plateau.agency.control._ID_GREP` (tests/test_gatekeeper.py
# pins the two together); duplicated, not imported, so a hook never fails on a heavier import.
_TASK_ROW = re.compile(r"^- \[[ xX]\] *[A-Za-z]")
# BLOCKED.md is a legal pause only if some line starts with `class:`, in any case.
_BLOCKED_CLASS = re.compile(r"^class:", re.IGNORECASE | re.MULTILINE | re.ASCII)
# A checked row's id: what sits between `- [x]` and the first `|`.
_CHECKED_ID = re.compile(r"^- \[[xX]\][ \t\r\f\v]*([^|]*)\|")
# The id a Regression message names. Only `T...` ids are named; any other prints `?`.
_REGRESSION_ID = re.compile(r"^- \[[xX]\] (T[^ |]*)")
# The first `"exit_code": <int>` on one line of a gate artifact (never spans lines).
_ARTIFACT_EXIT = re.compile(r'"exit_code"[ \t\r\f\v]*:[ \t\r\f\v]*(-?[0-9]+)')
# `timeout(1)` durations: 90, 1.5, 90s, 2m, 1h, 1d.
_DURATION = re.compile(r"^(\d+\.?\d*|\.\d+)([smhd]?)$")
_UNIT_S = {"": 1, "s": 1, "m": 60, "h": 3600, "d": 86400}
_WS = " \t\r\n\f\v"

_NO_ROWS = (
    "PLAN.md exists but contains no task rows. Finish RECON, then write rows in the fixed "
    "grammar ('- [ ] Tn | action | deliverable | GATE: cmd | EXPECT: result') covering the "
    "mission in TASK.md. Exit is legal only on DONE or a BLOCKED.md containing 'class:'."
)


# --- environment -------------------------------------------------------------------------

def _gate_timeout() -> Optional[float]:
    """`GATE_TIMEOUT` as seconds (or a `timeout(1)` duration like `2m`); default 120, `0` = no
    limit. Junk falls back to the default rather than failing every gate."""
    m = _DURATION.match((os.environ.get("GATE_TIMEOUT") or "").strip())
    if not m:
        return DEFAULT_GATE_TIMEOUT_S
    seconds = float(m.group(1)) * _UNIT_S[m.group(2)]
    return seconds if seconds > 0 else None


def _max_blocks() -> int:
    """`GATEKEEPER_MAX_BLOCKS`: default 10; `0` (or less) disables the stall cap; junk = default."""
    try:
        return max(int((os.environ.get("GATEKEEPER_MAX_BLOCKS") or "").strip()), 0)
    except ValueError:
        return DEFAULT_MAX_BLOCKS


def _read_payload() -> Dict[str, Any]:
    """Drain stdin (a hook always gets a JSON payload; it may be empty, `{}` or garbage) and
    return it as a dict, `{}` on anything else. Never blocks on an interactive terminal."""
    try:
        if sys.stdin is None or sys.stdin.isatty():
            return {}
        stream = getattr(sys.stdin, "buffer", None)
        raw = stream.read() if stream is not None else sys.stdin.read()
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", "replace")
        data = json.loads(raw) if raw.strip() else {}
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _git_toplevel(base: str) -> Optional[str]:
    try:
        r = subprocess.run(["git", "-C", base, "rev-parse", "--show-toplevel"],
                           stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=5)
    except Exception:
        return None
    top = r.stdout.strip() if r.returncode == 0 else ""
    return top or None


def _resolve(payload: Dict[str, Any]) -> Optional[Tuple[str, str]]:
    """`(control_dir, root)` of the armed run, or None when there is no PLAN.md (not armed).
    `root` is the project directory the control dir was found under; gates run there."""
    rel = os.environ.get("CONTROL_DIR") or DEFAULT_CONTROL_DIR
    cwd = payload.get("cwd")
    base = cwd if isinstance(cwd, str) and cwd and os.path.isdir(cwd) else os.getcwd()
    if os.path.isabs(rel):
        return (rel, base) if os.path.isfile(f"{rel}/PLAN.md") else None
    direct = os.path.join(base, rel)
    if os.path.isfile(f"{direct}/PLAN.md"):
        return direct, base
    # The session may have `cd`'d into a subdirectory of the project: try the repo root.
    top = _git_toplevel(base)
    if top and os.path.isfile(f"{os.path.join(top, rel)}/PLAN.md"):
        return os.path.join(top, rel), top
    return None


# --- files -------------------------------------------------------------------------------

def _read_bytes(path: str) -> bytes:
    try:
        with open(path, "rb") as fh:
            return fh.read()
    except OSError:
        return b""


def _read_text(path: str) -> str:
    return _read_bytes(path).decode("utf-8", "replace")


def _fingerprint(plan: bytes, control_dir: str) -> str:
    """sha256 over PLAN.md then JOURNAL.md (a missing file is empty): the run's progress."""
    h = hashlib.sha256()
    h.update(plan)
    h.update(_read_bytes(f"{control_dir}/JOURNAL.md"))
    return h.hexdigest()


def _read_state(control_dir: str) -> Dict[str, Any]:
    try:
        data = json.loads(_read_text(f"{control_dir}/STATE.json"))
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _write_state(control_dir: str, state: Dict[str, Any]) -> None:
    """Atomic (a monitor polling STATE.json never reads half a file); failures are ignored."""
    path = f"{control_dir}/STATE.json"
    tmp = f"{path}.{os.getpid()}.tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(state) + "\n")
        os.replace(tmp, path)
    except OSError:
        try:
            os.remove(tmp)
        except OSError:
            pass


# --- the decision ------------------------------------------------------------------------

def _run_gate(gate: str, cwd: str, timeout: Optional[float]) -> Tuple[int, bytes]:
    """`timeout T bash -c GATE 2>&1`: (exit code, combined stdout+stderr). A gate over its time
    is killed together with its process group and reported as 124, like timeout(1)."""
    shell = shutil.which("bash") or shutil.which("sh") or "bash"
    try:
        proc = subprocess.Popen([shell, "-c", gate], cwd=cwd if os.path.isdir(cwd) else None,
                                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, start_new_session=True)
    except OSError as exc:
        return 127, str(exc).encode("utf-8", "replace")
    try:
        out, _ = proc.communicate(timeout=timeout)
        rc = proc.returncode
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except Exception:
            proc.kill()
        try:
            out, _ = proc.communicate(timeout=5)
        except Exception:
            out = b""
        rc = 124
    return (rc if rc >= 0 else 128 - rc), out or b""


def _failed_artifact(control_dir: str, row: str) -> Optional[str]:
    """Cheap, always-on check (no re-execution): a checked row's `gates/<id>.gate.json`, written
    by `control.run_gate`, is the ground truth for its box. If it records a non-zero
    `exit_code` the box was checked in error -- never trust "checked" over its own artifact."""
    m = _CHECKED_ID.match(row)
    tid = m.group(1).rstrip(_WS) if m else ""
    art = f"{control_dir}/gates/{tid}.gate.json"
    if not tid or not os.path.isfile(art):
        return None
    for line in _read_text(art).split("\n"):
        hit = _ARTIFACT_EXIT.search(line)
        if hit:
            if int(hit.group(1)) == 0:
                return None
            return (f"Checked row {tid}'s recorded gate artifact ({art}) says the gate FAILED "
                    f"(exit_code={hit.group(1)}) — a stale or mischecked box. Uncheck {tid}, "
                    f"fix, re-run its GATE, and only check it once the artifact records "
                    f"exit_code 0.")
    return None


def _regressed(root: str, row: str, timeout: Optional[float]) -> Optional[str]:
    """Strict regression (V3): re-run one checked row's GATE fresh. Pass <=> exit 0 AND
    (EXPECT == 'exit0' OR EXPECT is a substring of the output)."""
    i = row.find("GATE: ")
    if i < 0 or row.find(" | EXPECT: ", i + len("GATE: ")) < 0:
        return (f"Malformed checked row (missing 'GATE:'/'EXPECT:'): {row[:100]}. "
                f"Fix the row grammar, then re-verify.")
    gate = row.split("GATE: ", 1)[1].split(" | EXPECT:", 1)[0]
    expect = row.rsplit("| EXPECT: ", 1)[-1]
    code, raw = _run_gate(gate, root, timeout)
    out = raw.replace(b"\0", b"").rstrip(b"\n")      # what `$(...)` would have kept
    text = out.decode("utf-8", "replace")
    # An empty output matches nothing, not even an empty EXPECT (grep -F on no input).
    if code == 0 and (expect == "exit0" or (text != "" and expect in text)):
        return None
    m = _REGRESSION_ID.match(row)
    snip = out[-200:].decode("utf-8", "replace").replace("\n", " ").replace('"', "'")
    return (f"Regression: gate {m.group(1) if m else '?'} failed (exit {code}). Output tail: "
            f"{snip} — uncheck that row, fix, re-verify. DONE means every gate is green when "
            f"run now.")


def _decide(control_dir: str, root: str, plan: str, strict: bool) -> Tuple[str, str, int]:
    """`(verdict, reason, unchecked)`. BLOCK carries the reason handed to the model; the two
    ALLOW_* verdicts carry none."""
    lines = plan.split("\n")
    open_rows = [ln for ln in lines if ln.startswith("- [ ]")]

    # Release 1: a valid blocker report on disk (BLOCKED-REPORT is a legal pause).
    if _BLOCKED_CLASS.search(_read_text(f"{control_dir}/BLOCKED.md")):
        return "ALLOW_BLOCKED", "", len(open_rows)

    # A scaffolded-but-unplanned PLAN.md (no task rows at all) is NOT done.
    if not any(_TASK_ROW.match(ln) for ln in lines):
        return "BLOCK", _NO_ROWS, -1

    if open_rows:
        first = open_rows[0][:140].replace('"', "'")
        return "BLOCK", (
            f"{len(open_rows)} unchecked gate(s) in PLAN.md. Next: {first} — return to "
            f"EXECUTE, assign it to a bounded sub-agent (signal + one task), run its GATE, "
            f"paste literal output into JOURNAL.md, check the box only when the fact is "
            f"admitted. Legal exits: DONE (all gates green now) or a BLOCKED.md with "
            f"'class:'."), len(open_rows)

    checked = [ln for ln in lines if ln.startswith(("- [x]", "- [X]"))]
    for row in checked:
        reason = _failed_artifact(control_dir, row)
        if reason:
            return "BLOCK", reason, 0
    if strict:
        timeout = _gate_timeout()
        for row in checked:
            reason = _regressed(root, row, timeout)
            if reason:
                return "BLOCK", reason, 0
    return "ALLOW_DONE", "", 0


# --- the hook ----------------------------------------------------------------------------

def _twin(prev: Dict[str, Any], fingerprint: str, started: float) -> bool:
    """Whether `prev` was written for this same Stop by the other copy of a doubly
    registered gatekeeper (plugin + `plateau init --global`; `plateau.bridge.dedupe` never
    holds a gatekeeper back): same fingerprint, started within `_TWIN_S` of this one. A
    genuinely new Stop that fast is still decided normally -- it just is not counted."""
    t = prev.get("started")
    return (prev.get("fingerprint") == fingerprint and isinstance(t, (int, float))
            and not isinstance(t, bool) and abs(started - t) < _TWIN_S)


def _run(payload: Dict[str, Any]) -> None:
    started = time.time()
    found = _resolve(payload)
    if found is None:
        return                                        # NOT ARMED: never interfere
    control_dir, root = found
    strict = os.environ.get("RUN_GATES") == "1"
    ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    plan = _read_bytes(f"{control_dir}/PLAN.md")
    verdict, reason, unchecked = _decide(control_dir, root, plan.decode("utf-8", "replace"),
                                         strict)
    fingerprint = _fingerprint(plan, control_dir)

    blocks = 0
    if verdict == "BLOCK":
        # Consecutive blocks over an unchanged PLAN.md + JOURNAL.md are a stall, not progress.
        prev = _read_state(control_dir)
        before = prev.get("blocks")
        before = before if isinstance(before, int) and not isinstance(before, bool) else 0
        twin = _twin(prev, fingerprint, started)
        if twin and prev.get("verdict") == "ALLOW_STALLED":
            verdict = "ALLOW_STALLED"                 # the first copy released this Stop
        elif twin and prev.get("verdict") == "BLOCK":
            blocks = max(before, 1)                   # the first copy counted this Stop
        else:
            same = prev.get("verdict") == "BLOCK" and prev.get("fingerprint") == fingerprint
            blocks = before + 1 if same else 1
            cap = _max_blocks()
            if cap and blocks > cap:
                verdict, blocks = "ALLOW_STALLED", 0
                print(f"gatekeeper: released after {cap} consecutive blocks with no change to "
                      f"PLAN.md or JOURNAL.md (GATEKEEPER_MAX_BLOCKS={cap}; 0 disables the "
                      f"cap). Nothing was verified -- finish the plan or write BLOCKED.md.",
                      file=sys.stderr)

    _write_state(control_dir, {"ts": ts, "unchecked": unchecked, "verdict": verdict,
                               "strict": 1 if strict else 0, "blocks": blocks,
                               "fingerprint": fingerprint, "started": started})
    if verdict == "BLOCK":
        # One short line: newlines -> spaces, `"` -> `'`, cut to 400 characters.
        reason = reason.replace("\n", " ").replace('"', "'")[:400]
        print(json.dumps({"decision": "block", "reason": reason}), flush=True)


def main(argv: Optional[List[str]] = None) -> int:
    """Stop-hook entry (`hook.py gatekeeper --cc` / `plateau hook gatekeeper`). `argv` is
    ignored. Always returns 0 and never raises: a gatekeeper that crashes must not trap or
    break the session it guards."""
    try:
        _run(_read_payload())
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
