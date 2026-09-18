#!/usr/bin/env python3
"""plateau.cli — the `plateau` command line (`[project.scripts] plateau = "plateau.cli:main"`).

Step 2 (see `docs/harness-0.3/PLAN.md` "CLI") implements `lookup` (delegates to
`plateau.bridge.lookup`), `handoff` (delegates to `plateau.bridge.handoff`), `version`.

Step 3 (see `docs/harness-0.3/PLAN-step3.md`) adds `hook <mode>` (the console-script twin
of `adapters/claude_code/hook.py <mode> --cc`: reads the payload from stdin, dispatches to
a target module, no-ops with a log line when the target module is absent), `init
[--global] [--force] [--uninstall]` (merges the bridge's hook table into a Claude Code
`settings.json`; delegates to `plateau.bridge.install`), and `resume <session_id>
[prompt]` (a fresh `claude -p`, never `--resume`, with `PLATEAU_RESUME_FROM=<session_id>`
so `inject` prepends that session's stored handoff block).

Step 4 (docs/harness-0.3/PLAN-step4.md "S4-A4 Single owner for `plateau/cli.py`") makes
this file the SOLE owner of the command surface: every subcommand beyond
lookup/handoff/version/init/resume/hook is a thin `importlib` delegation to another
module's entry point (`_LAB_ENTRY_POINTS` below), so this file never depends on landing
order between concurrently-developed owners -- a not-yet-landed module degrades to a
"not available" message and exit 2, exactly like a hook mode degrades to a no-op.
`hook <mode>` also grew three more modes in step 4 (S4-A1 "One install story"): `parent`,
`pre`, `post` now dispatch to `plateau.hooks.signal.main(mode, argv)` alongside the six
step-3 modes, so `plateau hook` and `adapters/claude_code/hook.py` cover the exact same
nine modes from the exact same implementations.
"""

from __future__ import annotations

import argparse
import importlib
import json
import os
import subprocess
import sys
from typing import List, Optional

COMMANDS = (
    "init", "doctor", "lookup", "handoff", "resume", "hook",
    "report", "fit", "propose", "learn", "sync", "version", "absorb",
)

# `plateau hook <mode>` -- the console-script twin of `hook.py <mode> --cc`
# (docs/harness-0.3/PLAN-step3.md "`plateau init` and `plateau hook`"; S4-A1 adds the
# first three): dispatches to the named module's `main(argv)` (or, for the signal
# modes, `plateau.hooks.signal.main(mode, argv)`), passing through whatever args
# followed the mode (`--cc`, `--print`, `--write`, `--agent ...`, ...). A module that is
# not (yet) importable degrades to a no-op with a log line rather than failing the hook
# (hooks must never raise; see PLAN.md conventions).
_SIGNAL_MODES = ("parent", "pre", "post")
_HOOK_MODULES = {
    "receipt": "plateau.bridge.receipt",
    "snapshot": "plateau.bridge.snapshot",
    "inject": "plateau.bridge.inject",
    "handoff": "plateau.bridge.handoff",
    "lift": "plateau.bridge.lift",
    "ledger": "plateau.lab.ledger",
}

# S4-A4: every new subcommand beyond lookup/handoff/version/init/resume/hook is a thin
# delegation to the named module's entry point, wired through `importlib` so this file
# never depends on landing order. `(module, function)` -- the function takes `argv`
# (a `List[str]`) and returns an int exit code (or `None`, taken as 0).
_LAB_ENTRY_POINTS = {
    "report": ("plateau.lab.ledger", "report_main"),
    "fit": ("plateau.lab.fit", "main"),
    "propose": ("plateau.lab.propose", "main"),
    "learn": ("plateau.lab.promote", "learn_main"),
    "sync": ("plateau.ring", "sync_main"),
    "doctor": ("plateau.doctor", "main"),
    # docs/harness-0.3/PLAN-absorb.md (owner D1): `plateau absorb` is a thin delegation
    # to `plateau.absorb.main`, the same S4-A4 pattern every other subcommand here uses.
    "absorb": ("plateau.absorb", "main"),
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

    if mode in _SIGNAL_MODES:
        # parent/pre/post -> plateau.hooks.signal.main(mode, argv) (S4-A1). `plateau
        # hook <mode>` is the console-script TWIN of `hook.py <mode> --cc` -- it always
        # runs as an installed hook, so `--cc` is implied here even if the caller did
        # not type it (mirroring the six module modes below, which have no dry-run
        # shape at all and likewise need no `--cc`). `plateau init` therefore never
        # writes a literal `--cc` for these three modes either.
        try:
            from .hooks import signal as hooks_signal
        except Exception as exc:
            _hook_log("mode '{}' (plateau.hooks.signal) unavailable: {!r} -- no-op".format(mode, exc))
            print(json.dumps({}))
            return 0
        try:
            hooks_signal.main(mode, list(mode_args) + ["--cc"])
        except SystemExit:
            pass
        except Exception as exc:
            _hook_log("mode '{}' raised: {!r}".format(mode, exc))
            print(json.dumps({}))
        return 0

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
            new_session_id = result.get("session_id")
            cost = result.get("total_cost_usd")
            print(
                "plateau resume: session_id={} cost_usd={}".format(new_session_id, cost),
                file=sys.stderr,
            )
            # docs/harness-0.3/target-run-wavex.md finding #8 / PLAN item 9: this JSON
            # result is the ONLY place a real `total_cost_usd` is ever available (the
            # transcript file never carries it) -- push it into the ledger row for the
            # fresh session this `claude -p` just ran.
            try:
                from .lab import ledger as lab_ledger
                lab_ledger.record_cost(root, new_session_id, cost)
            except Exception:
                pass
        except Exception:
            pass

    return proc.returncode


# --- report/fit/propose/learn/sync/doctor (S4-A4: thin importlib delegation) ----------

def _cmd_lab_entry(command: str, rest: List[str]) -> int:
    """`plateau report|fit|propose|learn|sync|doctor` (docs/harness-0.3/PLAN-step4.md
    "S4-A4 Single owner for `plateau/cli.py`"): a thin delegation to the owning module's
    entry point via `importlib`, so this file never depends on landing order between
    concurrently-developed owners. A module/function that is not (yet) importable
    prints a "not available" message and exits 2 -- never a traceback."""
    module_name, func_name = _LAB_ENTRY_POINTS[command]
    try:
        module = importlib.import_module(module_name)
        func = getattr(module, func_name)
        if not callable(func):
            raise AttributeError("{} has no {}()".format(module_name, func_name))
    except Exception as exc:
        print("plateau {}: not available ({}.{} could not be imported: {!r})".format(
            command, module_name, func_name, exc))
        return 2
    result = func(rest)
    return result if isinstance(result, int) else 0


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
    if args.command in _LAB_ENTRY_POINTS:
        return _cmd_lab_entry(args.command, rest)
    return 2  # unreachable: argparse already restricted `command` to COMMANDS


if __name__ == "__main__":
    sys.exit(main())
