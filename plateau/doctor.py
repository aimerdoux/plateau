#!/usr/bin/env python3
"""plateau.doctor — `plateau doctor` (full self-check).

Owner C3 (docs/harness-0.3/PLAN-step4.md "`plateau doctor` (full)"). This module
absorbs the step-2 bridge checks that used to live directly in `plateau/cli.py`
(receipt / snapshot / injection / handoff, run through a scratch git repo — never this
repo, never a real `.plateau/`) and extends them per the step-4 contract:

  1. Resolve the INSTALLED hook commands for four events (PostToolUse -> receipt,
     PreCompact -> snapshot, SessionStart[compact] -> inject, Stop -> handoff --print)
     from the project's `.claude/settings.json`, else the user's global
     `~/.claude/settings.json`, else fall back to running the package module directly
     (`python -m plateau.bridge.<name>`) when neither settings.json installs that mode
     at all. This makes `doctor` a check of what is ACTUALLY wired up to fire on this
     machine, not just of the bridge code in isolation.
  2. Run one fake PostToolUse(Read), PreCompact(manual), SessionStart(compact) and
     Stop through whichever command was resolved, in a disposable scratch git repo, and
     assert: a receipt row exists; a snapshot file exists; the injection's
     `additionalContext` is within budget; the Stop hook's handoff block renders.
  3. Three more checks against THIS project's real root (read-only, or write-only to
     `.plateau/ledger.sqlite`'s schema, which `CREATE TABLE IF NOT EXISTS` makes an
     idempotent no-op when it already exists): the ledger is writable, `bridge.toml`
     config resolves, and the private ring's on/off status.

Every line is `PASS: <label>`, `FAIL: <label>`, or `SKIP: <label> (<why>)` — SKIP is for
a module another owner has not landed yet (mid-refactor importability), never for a
check that ran and failed. Exit 1 iff any line is FAIL; SKIP and PASS both leave the
exit code alone.
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from typing import Any, Dict, List, Optional, Tuple

Check = Tuple[str, str, str]  # (status, label, detail)

_FALLBACK_COMMANDS = {
    "receipt": [sys.executable, "-m", "plateau.bridge.receipt"],
    "snapshot": [sys.executable, "-m", "plateau.bridge.snapshot"],
    "inject": [sys.executable, "-m", "plateau.bridge.inject"],
    "handoff": [sys.executable, "-m", "plateau.bridge.handoff", "--print"],
}


# --- resolving the INSTALLED hook command for one (event, mode[, matcher]) -----------


def _load_json_settings(path: str) -> Dict[str, Any]:
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _settings_paths(root: str) -> List[str]:
    """Project settings first, then the user's global settings — same precedence
    `plateau init` installs into (project by default, global with `--global`)."""
    try:
        from .bridge import install as bridge_install
        return [
            bridge_install.settings_path(root, is_global=False),
            bridge_install.settings_path(root, is_global=True),
        ]
    except Exception:
        return [
            os.path.join(root, ".claude", "settings.json"),
            os.path.join(os.path.expanduser("~"), ".claude", "settings.json"),
        ]


def _command_is_mode(command: str, mode: str) -> bool:
    """True iff `command` is one of ours for `mode` — i.e. it contains the token
    sequence `hook <mode>` (works for both `plateau hook <mode>` and
    `python3 -m plateau.cli hook <mode>`, whatever args follow)."""
    try:
        tokens = shlex.split(command)
    except ValueError:
        tokens = command.split()
    for i, tok in enumerate(tokens):
        if tok == "hook" and i + 1 < len(tokens) and tokens[i + 1] == mode:
            return True
    return False


def _resolve_hook_commands(
    root: str, event: str, mode: str, matcher: Optional[str] = None,
) -> Tuple[List[List[str]], str]:
    """`([argv, ...], source)` for every installed hook entry matching `event`
    (+ `matcher`, when given) whose command is this `mode` — checked against the
    project settings.json, then the global one; the first file that has ANY match for
    this mode wins. Falls back to `_FALLBACK_COMMANDS[mode]` (the package module run
    directly) when neither settings.json installs this mode at all — `source` is then
    `"package module"` rather than a settings.json path."""
    for path in _settings_paths(root):
        settings = _load_json_settings(path)
        hooks = settings.get("hooks") if isinstance(settings, dict) else None
        if not isinstance(hooks, dict):
            continue
        groups = hooks.get(event)
        if not isinstance(groups, list):
            continue
        found: List[List[str]] = []
        for group in groups:
            if not isinstance(group, dict):
                continue
            if matcher is not None and group.get("matcher") != matcher:
                continue
            for hook in group.get("hooks") or []:
                if not isinstance(hook, dict):
                    continue
                command = hook.get("command")
                if isinstance(command, str) and _command_is_mode(command, mode):
                    try:
                        found.append(shlex.split(command))
                    except ValueError:
                        found.append(command.split())
        if found:
            return found, path
    return [list(_FALLBACK_COMMANDS[mode])], "package module"


# --- running a resolved command with a fake hook payload on stdin --------------------


def _repo_root_of_this_package() -> str:
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _doctor_env() -> Dict[str, str]:
    """`plateau.bridge.common.child_env()` (S3-A2/S4-A2: strip the Claude-Code-session
    identity vars from anything this process spawns) plus a PYTHONPATH that can find
    this checkout's `plateau` package even when it is not (or is stale-ly) installed,
    and with any `d037_hooks/`-legacy env override stripped — this is a check of the
    CURRENT public `.plateau/` behaviour, never the legacy shims."""
    try:
        from .bridge import common as bridge_common
        env = bridge_common.child_env()
    except Exception:
        env = dict(os.environ)
    env["PYTHONPATH"] = _repo_root_of_this_package() + os.pathsep + env.get("PYTHONPATH", "")
    for legacy_var in ("PLATEAU_LEGACY_TAG", "PLATEAU_DB_REL", "PLATEAU_LOG_REL"):
        env.pop(legacy_var, None)
    return env


def _run(argv: List[str], payload: Dict[str, Any], cwd: str, env: Dict[str, str]) -> subprocess.CompletedProcess:
    """Run one hook command with `payload` piped in as JSON on stdin. Never raises: a
    launch failure (bad PATH, missing interpreter, timeout, ...) comes back as a
    synthetic nonzero-exit CompletedProcess, so every doctor check stays pass/fail
    rather than needing a second error path — and, for an INSTALLED command that
    genuinely cannot run (e.g. `plateau` not on PATH), that IS the failure doctor
    exists to surface."""
    try:
        return subprocess.run(
            argv, input=json.dumps(payload), cwd=cwd, env=env,
            capture_output=True, text=True, timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return subprocess.CompletedProcess(args=argv, returncode=1, stdout="", stderr=repr(exc))


def _last_json_line(stdout: str) -> Dict[str, Any]:
    lines = [line for line in stdout.splitlines() if line.strip()]
    if not lines:
        return {}
    try:
        parsed = json.loads(lines[-1])
    except ValueError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


# --- the four scratch-repo checks -----------------------------------------------------


def _check_receipt(settings_root: str, run_root: str, session_id: str, env: Dict[str, str]) -> Check:
    probe_path = os.path.join(run_root, "doctor_probe.py")
    probe_src = "def doctor_probe():\n    return True\n"
    with open(probe_path, "w", encoding="utf-8") as f:
        f.write(probe_src)
    payload = {
        "session_id": session_id, "cwd": run_root,
        "hook_event_name": "PostToolUse", "tool_name": "Read",
        "tool_input": {"file_path": probe_path},
        "tool_response": {"content": probe_src},
    }
    argvs, source = _resolve_hook_commands(settings_root, "PostToolUse", "receipt")
    for argv in argvs:
        _run(argv, payload, run_root, env)

    ok = False
    db_path = os.path.join(run_root, ".plateau", "index.sqlite")
    if os.path.isfile(db_path):
        try:
            conn = sqlite3.connect(db_path)
            try:
                ok = conn.execute("SELECT COUNT(*) FROM receipts").fetchone()[0] >= 1
            finally:
                conn.close()
        except sqlite3.Error:
            ok = False
    label = "a receipt row exists (PostToolUse -> receipt, via {})".format(source)
    return ("PASS" if ok else "FAIL", label, "")


def _check_snapshot(settings_root: str, run_root: str, session_id: str, env: Dict[str, str]) -> Check:
    payload = {"session_id": session_id, "cwd": run_root, "hook_event_name": "PreCompact", "trigger": "manual"}
    argvs, source = _resolve_hook_commands(settings_root, "PreCompact", "snapshot")
    for argv in argvs:
        _run(argv, payload, run_root, env)

    snap_dir = os.path.join(run_root, ".plateau", "snapshots")
    ok = os.path.isdir(snap_dir) and len(os.listdir(snap_dir)) >= 1
    label = "a snapshot exists under .plateau/snapshots/ (PreCompact -> snapshot, via {})".format(source)
    return ("PASS" if ok else "FAIL", label, "")


def _write_transcript(root: str) -> str:
    transcript_path = os.path.join(root, "transcript.jsonl")
    line = {"type": "user", "message": {"role": "user", "content": "fix doctor_probe"}}
    with open(transcript_path, "w", encoding="utf-8") as f:
        f.write(json.dumps(line) + "\n")
    return transcript_path


def _check_inject(settings_root: str, run_root: str, session_id: str, env: Dict[str, str], transcript_path: str) -> Check:
    payload = {
        "session_id": session_id, "cwd": run_root,
        "hook_event_name": "SessionStart", "source": "compact",
        "transcript_path": transcript_path,
    }
    argvs, source = _resolve_hook_commands(settings_root, "SessionStart", "inject", matcher="compact")
    last_stdout = ""
    for argv in argvs:
        proc = _run(argv, payload, run_root, env)
        last_stdout = proc.stdout

    ok = False
    try:
        out = _last_json_line(last_stdout)
        ctx = out.get("hookSpecificOutput", {}).get("additionalContext", "")
        from .bridge import config as bridge_config
        cfg = bridge_config.load(run_root, session_id)
        budget = cfg.budget.get("compaction_chars", 12000)
        ok = len(ctx) <= budget
    except Exception:
        ok = False
    label = "the injection is under budget (SessionStart[compact] -> inject, via {})".format(source)
    return ("PASS" if ok else "FAIL", label, "")


def _check_stop_handoff(settings_root: str, run_root: str, session_id: str, env: Dict[str, str], transcript_path: str) -> Check:
    payload = {
        "session_id": session_id, "cwd": run_root,
        "hook_event_name": "Stop", "transcript_path": transcript_path,
        "stop_hook_active": False,
    }
    argvs, source = _resolve_hook_commands(settings_root, "Stop", "handoff")
    last_stdout = ""
    for argv in argvs:
        proc = _run(argv, payload, run_root, env)
        last_stdout = proc.stdout

    ok = False
    try:
        out = _last_json_line(last_stdout)
        text = out.get("systemMessage", "")
        ok = bool(text) and text.startswith("<plateau_handoff")
    except Exception:
        ok = False
    label = "a handoff block renders (Stop -> handoff, via {})".format(source)
    return ("PASS" if ok else "FAIL", label, "")


def _run_scratch_repo_checks(settings_root: str) -> List[Check]:
    """Resolve each hook's command from `settings_root` (the REAL project — its
    project settings.json, else the user's global one, else the package-module
    fallback), but always EXECUTE it against a disposable scratch git repo (`run_root`,
    a fresh `tempfile.mkdtemp()`), never against `settings_root`'s own `.plateau/` —
    this is a check of what is installed, not a mutation of the real project."""
    checks: List[Check] = []
    run_root = tempfile.mkdtemp(prefix="plateau-doctor-")
    try:
        subprocess.run(["git", "init", "-q", run_root], capture_output=True, text=True, timeout=10)
        subprocess.run(
            ["git", "-C", run_root, "config", "user.email", "doctor@plateau.local"],
            capture_output=True, text=True, timeout=10,
        )
        subprocess.run(
            ["git", "-C", run_root, "config", "user.name", "plateau doctor"],
            capture_output=True, text=True, timeout=10,
        )
        session_id = "doctor-session"
        env = _doctor_env()
        transcript_path = _write_transcript(run_root)

        # Order matters: snapshot must run before inject (it records the compaction
        # row `prev_compaction_rid`/`_current_compaction_k` reason about), and both
        # must run before the Stop check shares the same store/session.
        checks.append(_check_receipt(settings_root, run_root, session_id, env))
        checks.append(_check_snapshot(settings_root, run_root, session_id, env))
        checks.append(_check_inject(settings_root, run_root, session_id, env, transcript_path))
        checks.append(_check_stop_handoff(settings_root, run_root, session_id, env, transcript_path))
    finally:
        shutil.rmtree(run_root, ignore_errors=True)
    return checks


# --- the three real-project checks ----------------------------------------------------


def _real_root() -> str:
    try:
        cp = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True, timeout=5,
        )
        if cp.returncode == 0:
            top = cp.stdout.strip()
            if top:
                return top
    except (OSError, subprocess.SubprocessError):
        pass
    return os.getcwd()


def _check_ledger_writable(root: str) -> Check:
    try:
        from .lab import ledger as lab_ledger
    except Exception as exc:
        return ("SKIP", "the ledger is writable", "plateau.lab.ledger not available yet: {!r}".format(exc))
    try:
        conn = lab_ledger.db(root)
        try:
            conn.execute("SELECT COUNT(*) FROM sessions")
        finally:
            conn.close()
        ok = os.path.isfile(os.path.join(root, lab_ledger.LEDGER_REL))
    except Exception as exc:
        return ("FAIL", "the ledger is writable", repr(exc))
    return ("PASS" if ok else "FAIL", "the ledger is writable", lab_ledger.LEDGER_REL)


def _check_config_resolves(root: str) -> Check:
    try:
        from .bridge import config as bridge_config
    except Exception as exc:
        return ("SKIP", "config resolves", "plateau.bridge.config not available yet: {!r}".format(exc))
    try:
        cfg = bridge_config.load(root, "doctor-session")
        ok = bool(cfg.version) and cfg.role in ("incumbent", "canary", "off")
    except Exception as exc:
        return ("FAIL", "config resolves", repr(exc))
    detail = "role={} version={} sha={}".format(cfg.role, cfg.version, (cfg.sha or "")[:8] or "none")
    return ("PASS" if ok else "FAIL", "config resolves", detail)


def _check_private_ring_status(root: str) -> Check:
    try:
        from . import ring as plateau_ring
    except Exception as exc:
        return ("FAIL", "private ring status", repr(exc))
    try:
        detail = plateau_ring.status(root)
    except Exception as exc:
        return ("FAIL", "private ring status", repr(exc))
    return ("PASS", "private ring status", detail)


# --- main ------------------------------------------------------------------------------


def main(argv: Optional[List[str]] = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    argparse.ArgumentParser(prog="plateau doctor", add_help=True).parse_args(argv)

    real_root = _real_root()
    checks: List[Check] = []
    checks.extend(_run_scratch_repo_checks(real_root))

    checks.append(_check_ledger_writable(real_root))
    checks.append(_check_config_resolves(real_root))
    checks.append(_check_private_ring_status(real_root))

    exit_code = 0
    for status, label, detail in checks:
        line = "{}: {}".format(status, label)
        if detail:
            line += " ({})".format(detail)
        print(line)
        if status == "FAIL":
            exit_code = 1
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
