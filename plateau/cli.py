#!/usr/bin/env python3
"""plateau.cli — the `plateau` command line (`[project.scripts] plateau = "plateau.cli:main"`).

Step 2 (see `docs/harness-0.3/PLAN.md` "CLI") implements `lookup` (delegates to
`plateau.bridge.lookup`), `handoff` (delegates to `plateau.bridge.handoff`), `version`,
and `doctor` (a self-check of the bridge's three hook entry points plus the handoff
block, run against a scratch git repo — never this repo, never `.plateau/` here).

Step 3 (see `docs/harness-0.3/PLAN-step3.md`) adds `hook <mode>` (the console-script twin
of `adapters/claude_code/hook.py <mode> --cc`: reads the payload from stdin, dispatches to
`plateau.bridge.<module>.main` / `plateau.lab.ledger.main`, no-ops with a log line when the
target module is absent), `init [--global] [--force] [--uninstall]` (merges the bridge's
hook table into a Claude Code `settings.json`; delegates to `plateau.bridge.install`), and
`resume <session_id> [prompt]` (a fresh `claude -p`, never `--resume`, with
`PLATEAU_RESUME_FROM=<session_id>` so `inject` prepends that session's stored handoff
block). `report | fit | propose | learn | sync` remain registered so the full command
surface exists, and each prints `not implemented in 0.3.0-step2` and exits 2 until a later
step fills it in.
"""

from __future__ import annotations

import argparse
import importlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from typing import List, Optional, Tuple

COMMANDS = (
    "init", "doctor", "lookup", "handoff", "resume", "hook",
    "report", "fit", "propose", "learn", "sync", "version",
)
NOT_IMPLEMENTED_COMMANDS = ("report", "fit", "propose", "learn", "sync")

# `plateau hook <mode>` -- the console-script twin of `hook.py <mode> --cc`
# (docs/harness-0.3/PLAN-step3.md "`plateau init` and `plateau hook`"): dispatches to the
# named module's `main(argv)`, passing through whatever args followed the mode
# (`--print`, `--write`, `--agent ...`, ...). A module that is not (yet) importable --
# `plateau.lab.ledger` arrives in step 4 -- degrades to a no-op with a log line rather
# than failing the hook (hooks must never raise; see PLAN.md conventions).
_HOOK_MODULES = {
    "receipt": "plateau.bridge.receipt",
    "snapshot": "plateau.bridge.snapshot",
    "inject": "plateau.bridge.inject",
    "handoff": "plateau.bridge.handoff",
    "lift": "plateau.bridge.lift",
    "ledger": "plateau.lab.ledger",
}

DEFAULT_RESUME_PROMPT = (
    "Continue the work described by the handoff block; "
    "consult `plateau lookup` before re-reading."
)


def _repo_root() -> str:
    """The directory containing the top-level `plateau` package (two dirs up from this
    file: `plateau/cli.py` -> `plateau/` -> repo root) — added to a subprocess's
    PYTHONPATH so `python -m plateau.bridge.<name>` can find the package even when this
    process was started some other way than `python -m plateau.cli`."""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _version() -> str:
    """The version string from `[project] version` in the repo's `pyproject.toml` —
    read directly rather than via `importlib.metadata`, so this always matches the
    source tree even when the package is not (or is stale-ly) installed."""
    pyproject_path = os.path.join(_repo_root(), "pyproject.toml")
    try:
        with open(pyproject_path, encoding="utf-8") as f:
            in_project = False
            for raw_line in f:
                line = raw_line.strip()
                if line.startswith("["):
                    in_project = (line == "[project]")
                    continue
                if in_project and line.startswith("version"):
                    _, _, rhs = line.partition("=")
                    return rhs.strip().strip('"').strip("'")
    except OSError:
        pass
    return "0.0.0"


def _cmd_version() -> int:
    print("plateau {}".format(_version()))
    return 0


def _cmd_lookup(rest: List[str]) -> int:
    from .bridge import lookup as lookup_mod
    lookup_mod.main(rest)
    return 0


def _cmd_handoff(rest: List[str]) -> int:
    from .bridge import handoff as handoff_mod
    handoff_mod.main(rest)
    return 0


def _cmd_not_implemented() -> int:
    print("not implemented in 0.3.0-step2")
    return 2


def _git_toplevel_or_cwd() -> str:
    """`git rev-parse --show-toplevel` of the current directory, else the current
    directory itself (mirrors `plateau.bridge.handoff._resolve_root`)."""
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


def _hook_log(msg: str) -> None:
    """Best-effort `.plateau/hooks.log` line for a mode this process could not
    dispatch -- never raises, never blocks a hook on logging trouble."""
    try:
        from .bridge import common as bridge_common
        bridge_common.log(bridge_common.root({}), "hook {}".format(msg))
    except Exception:
        pass


def _cmd_hook(rest: List[str]) -> int:
    if not rest:
        print("usage: plateau hook <mode> [args...]", file=sys.stderr)
        return 2
    mode, mode_args = rest[0], rest[1:]

    module_name = _HOOK_MODULES.get(mode)
    if module_name is None:
        _hook_log("mode '{}' not recognized -- no-op".format(mode))
        print(json.dumps({}))
        return 0

    try:
        module = importlib.import_module(module_name)
        main_fn = getattr(module, "main", None)
        if not callable(main_fn):
            raise AttributeError("{} has no main()".format(module_name))
    except Exception as exc:
        # e.g. `plateau.lab.ledger` doesn't exist until step 4 -- degrade to a no-op
        # with a log line rather than fail the hook.
        _hook_log("mode '{}' ({}) unavailable: {!r} -- no-op".format(mode, module_name, exc))
        print(json.dumps({}))
        return 0

    main_fn(mode_args)
    return 0


# --- init (settings.json hook-table install) -----------------------------------------

def _build_init_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="plateau init", add_help=True)
    ap.add_argument("--global", action="store_true", dest="is_global")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--uninstall", action="store_true")
    return ap


def _cmd_init(rest: List[str]) -> int:
    from .bridge import install as bridge_install

    args = _build_init_parser().parse_args(rest)
    root = _git_toplevel_or_cwd()

    if args.uninstall:
        path, changed = bridge_install.uninstall_settings(root, is_global=args.is_global)
        print("{}: {}".format("removed plateau hooks from" if changed else "no plateau hooks found in", path))
        return 0

    path, changed = bridge_install.install_settings(root, is_global=args.is_global)
    print("{}: {}".format("updated" if changed else "already up to date", path))

    if args.is_global:
        dest = bridge_install.copy_global_bridge_toml(force=args.force)
        if dest:
            print("bridge.toml -> {}".format(dest))
    return 0


# --- resume (fresh `claude -p`, PLATEAU_RESUME_FROM=<session_id>) ---------------------

def _build_resume_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="plateau resume", add_help=True)
    ap.add_argument("session_id")
    ap.add_argument("prompt", nargs="?", default=None)
    ap.add_argument("--model", default=None)
    ap.add_argument("--permission-mode", default=None)
    ap.add_argument("--output-format", default=None)
    return ap


def _cmd_resume(rest: List[str]) -> int:
    args = _build_resume_parser().parse_args(rest)
    root = _git_toplevel_or_cwd()
    prompt = args.prompt or DEFAULT_RESUME_PROMPT

    # Never `--resume`: a fresh `claude -p` session, continuing the SHARED store via
    # PLATEAU_RESUME_FROM (docs/harness-0.3/PLAN-step3.md "`plateau resume`").
    cmd = ["claude", "-p", prompt]
    if args.output_format:
        cmd += ["--output-format", args.output_format]
    if args.model:
        cmd += ["--model", args.model]
    if args.permission_mode:
        cmd += ["--permission-mode", args.permission_mode]

    from .bridge import common as bridge_common

    # S3-A2 (docs/harness-0.3/PLAN-step3.md "Amendments after preflight run 1"): strip
    # the Claude-Code-session identity vars so this fresh `claude -p` cannot inherit
    # the parent session's id -- a fresh session id is exactly what "never --resume"
    # depends on.
    env = bridge_common.child_env()
    env["PLATEAU_RESUME_FROM"] = args.session_id

    try:
        proc = subprocess.run(cmd, cwd=root, env=env, capture_output=True, text=True, timeout=1800)
    except (OSError, subprocess.SubprocessError) as exc:
        print("plateau resume: failed to launch claude: {!r}".format(exc), file=sys.stderr)
        return 1

    sys.stdout.write(proc.stdout)
    if proc.stdout and not proc.stdout.endswith("\n"):
        sys.stdout.write("\n")
    if proc.stderr:
        sys.stderr.write(proc.stderr)

    if args.output_format == "json":
        # Summary only, printed to stderr so stdout stays exactly the JSON the caller
        # asked for (a script doing json.loads(stdout) must not see anything appended).
        try:
            result = json.loads(proc.stdout)
            print(
                "plateau resume: session_id={} cost_usd={}".format(
                    result.get("session_id"), result.get("total_cost_usd")
                ),
                file=sys.stderr,
            )
        except Exception:
            pass

    return proc.returncode


# --- doctor (bridge self-check) ------------------------------------------------------

def _run_module(module: str, payload: dict, cwd: str, env: dict) -> subprocess.CompletedProcess:
    """`python -m <module>` with `payload` piped in as JSON on stdin. Never raises: a
    launch failure (bad PYTHONPATH, missing interpreter, timeout, ...) comes back as a
    synthetic nonzero-exit CompletedProcess instead, so callers can treat every doctor
    check uniformly as pass/fail rather than needing a second error path."""
    try:
        return subprocess.run(
            [sys.executable, "-m", module],
            input=json.dumps(payload),
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return subprocess.CompletedProcess(args=[module], returncode=1, stdout="", stderr=str(exc))


def _doctor_env() -> dict:
    env = dict(os.environ)
    env["PYTHONPATH"] = _repo_root() + os.pathsep + env.get("PYTHONPATH", "")
    # This is a check of the CURRENT (public `.plateau/`) hook behaviour, never the
    # `d037_hooks/` legacy shims — strip any legacy overrides that might be ambient.
    for legacy_var in ("PLATEAU_LEGACY_TAG", "PLATEAU_DB_REL", "PLATEAU_LOG_REL"):
        env.pop(legacy_var, None)
    return env


def _run_doctor_checks(bridge_handoff, bridge_config) -> List[Tuple[str, bool]]:
    """Run one fake PostToolUse(Read), PreCompact, and SessionStart(compact) through the
    bridge hooks (as subprocesses, `python -m plateau.bridge.<name>`) in a scratch git
    repo, then check: a receipts row exists; a snapshot file exists; the injection's
    `additionalContext` is within budget; `handoff.build` renders a block. Returns
    `[(label, passed), ...]` in that order — never raises."""
    checks: List[Tuple[str, bool]] = []
    tmp = tempfile.mkdtemp(prefix="plateau-doctor-")
    try:
        subprocess.run(["git", "init", "-q", tmp], capture_output=True, text=True, timeout=10)
        env = _doctor_env()
        session_id = "doctor-session"

        # --- PostToolUse: a Read of a file we create -------------------------------
        probe_path = os.path.join(tmp, "doctor_probe.py")
        probe_src = "def doctor_probe():\n    return True\n"
        with open(probe_path, "w", encoding="utf-8") as f:
            f.write(probe_src)
        read_payload = {
            "session_id": session_id,
            "cwd": tmp,
            "hook_event_name": "PostToolUse",
            "tool_name": "Read",
            "tool_input": {"file_path": probe_path},
            "tool_response": {"content": probe_src},
        }
        _run_module("plateau.bridge.receipt", read_payload, tmp, env)

        receipts_ok = False
        db_path = os.path.join(tmp, ".plateau", "index.sqlite")
        if os.path.isfile(db_path):
            try:
                conn = sqlite3.connect(db_path)
                try:
                    receipts_ok = conn.execute("SELECT COUNT(*) FROM receipts").fetchone()[0] >= 1
                finally:
                    conn.close()
            except sqlite3.Error:
                receipts_ok = False
        checks.append(("a receipts row exists", receipts_ok))

        # --- PreCompact: trigger=auto -----------------------------------------------
        precompact_payload = {
            "session_id": session_id, "cwd": tmp,
            "hook_event_name": "PreCompact", "trigger": "auto",
        }
        _run_module("plateau.bridge.snapshot", precompact_payload, tmp, env)

        snap_dir = os.path.join(tmp, ".plateau", "snapshots")
        snap_ok = os.path.isdir(snap_dir) and len(os.listdir(snap_dir)) >= 1
        checks.append(("a file exists under .plateau/snapshots/", snap_ok))

        # --- SessionStart: source=compact, with a tiny transcript --------------------
        transcript_path = os.path.join(tmp, "transcript.jsonl")
        transcript_line = {"type": "user", "message": {"role": "user", "content": "fix doctor_probe"}}
        with open(transcript_path, "w", encoding="utf-8") as f:
            f.write(json.dumps(transcript_line) + "\n")
        start_payload = {
            "session_id": session_id, "cwd": tmp,
            "hook_event_name": "SessionStart", "source": "compact",
            "transcript_path": transcript_path,
        }
        inject_proc = _run_module("plateau.bridge.inject", start_payload, tmp, env)

        budget_ok = False
        try:
            stdout_lines = [line for line in inject_proc.stdout.splitlines() if line.strip()]
            out = json.loads(stdout_lines[-1]) if stdout_lines else {}
            ctx = out.get("hookSpecificOutput", {}).get("additionalContext", "")
            cfg = bridge_config.load(tmp, session_id)
            budget = cfg.budget.get("compaction_chars", 12000)
            budget_ok = len(ctx) <= budget
        except Exception:
            budget_ok = False
        checks.append(("the injection's additionalContext is within budget", budget_ok))

        # --- handoff.build renders a block -------------------------------------------
        handoff_ok = False
        try:
            block = bridge_handoff.build(tmp, session_id)
            text = bridge_handoff.render(block)
            handoff_ok = bool(text) and text.startswith("<plateau_handoff")
        except Exception:
            handoff_ok = False
        checks.append(("handoff.build renders a block", handoff_ok))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return checks


def _cmd_doctor() -> int:
    try:
        from .bridge import common as _bridge_common  # noqa: F401 -- importability probe
        from .bridge import config as bridge_config
        from .bridge import receipt as _bridge_receipt  # noqa: F401
        from .bridge import snapshot as _bridge_snapshot  # noqa: F401
        from .bridge import inject as _bridge_inject  # noqa: F401
        from .bridge import handoff as bridge_handoff
    except Exception as exc:  # bridge package mid-edit by another owner: not a failure
        print("SKIP: bridge modules not importable yet ({!r})".format(exc))
        return 3

    checks = _run_doctor_checks(bridge_handoff, bridge_config)
    exit_code = 0
    for label, passed in checks:
        print("{}: {}".format("PASS" if passed else "FAIL", label))
        if not passed:
            exit_code = 1
    return exit_code


# --- argument parsing / dispatch -----------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    # Deliberately NOT `add_subparsers()`: an `argparse.REMAINDER` positional inside a
    # sub-parser fails to capture a remaining token that looks like an option (e.g.
    # `handoff --print` raises "unrecognized arguments: --print" at the top level) —
    # a longstanding argparse quirk. A single flat `command` (restricted to COMMANDS)
    # plus one REMAINDER positional forwards everything after it verbatim, is not
    # subject to that quirk, and still leaves each delegate (`lookup`, `handoff`) free
    # to run its own argparse over `rest`.
    parser = argparse.ArgumentParser(
        prog="plateau", description="Plateau bridge/lab CLI (docs/harness-0.3/PLAN.md).",
    )
    parser.add_argument("command", choices=COMMANDS, metavar="command", help=" | ".join(COMMANDS))
    parser.add_argument("rest", nargs=argparse.REMAINDER, help=argparse.SUPPRESS)
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    args = _build_parser().parse_args(argv)
    rest = args.rest or []

    if args.command == "version":
        return _cmd_version()
    if args.command == "lookup":
        return _cmd_lookup(rest)
    if args.command == "handoff":
        return _cmd_handoff(rest)
    if args.command == "hook":
        return _cmd_hook(rest)
    if args.command == "init":
        return _cmd_init(rest)
    if args.command == "resume":
        return _cmd_resume(rest)
    if args.command == "doctor":
        return _cmd_doctor()
    if args.command in NOT_IMPLEMENTED_COMMANDS:
        return _cmd_not_implemented()
    return 2  # unreachable: argparse already restricted `command` to COMMANDS


if __name__ == "__main__":
    sys.exit(main())
