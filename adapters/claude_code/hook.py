"""Thin Claude Code adapter for Plateau. All logic lives in `plateau`; this file is
only I/O + JSON plumbing at the step boundary.

docs/harness-0.3/PLAN-step4.md "S4-A1 One install story": this file is now a thin shim
for all nine hook modes -- it holds no hook logic of its own. It dispatches:

  parent, pre, post                          -> plateau.hooks.signal.main(mode, argv)
  receipt, snapshot, inject, handoff, lift    -> plateau.bridge.<mode>.main(argv)
  ledger                                      -> plateau.lab.ledger.main(argv)

`plateau hook <mode>` (see `plateau.cli`) dispatches the exact same nine modes to the
exact same targets -- this file and that console-script command are two entry points
sharing one implementation, never two.

Run directly for a dry run:
  python adapters/claude_code/hook.py parent
  python adapters/claude_code/hook.py pre
  python adapters/claude_code/hook.py post
  python adapters/claude_code/hook.py receipt --cc   # (and snapshot/inject/handoff/lift/ledger)
"""

from __future__ import annotations

import importlib
import os
import sys

# --- make `plateau` importable whether pip-installed or run from a checkout ---------
# This file ships both as a plugin file (CLAUDE_PLUGIN_ROOT points here, `plateau` is
# pip-installed alongside it) and straight out of a dev checkout (`adapters/claude_code/
# hook.py` two directories under the repo root that contains the `plateau/` package,
# with nothing installed). Try the normal import first; only fall back to a sys.path
# insertion of the checkout's repo root when that fails, so an installed `plateau` is
# never shadowed by this source tree.
try:
    import plateau  # noqa: F401
except ImportError:
    _repo_root = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
    if _repo_root not in sys.path:
        sys.path.insert(0, _repo_root)

# All nine modes' targets. `parent`/`pre`/`post` share one module (`plateau.hooks.signal`,
# dispatched with the mode name as its first argument); the other six each own a module
# whose `main(argv)` reads the hook payload from stdin and prints its own hook JSON (or
# nothing) itself.
SIGNAL_MODES = ("parent", "pre", "post")
MODULE_MODES = {
    "receipt": "plateau.bridge.receipt",
    "snapshot": "plateau.bridge.snapshot",
    "inject": "plateau.bridge.inject",
    "handoff": "plateau.bridge.handoff",
    "lift": "plateau.bridge.lift",
    "ledger": "plateau.lab.ledger",
}
ALL_MODES = SIGNAL_MODES + tuple(MODULE_MODES)


def _log_fallback(mode: str, msg: str) -> None:
    """Best-effort log line when a target module can't be imported or raises -- never
    raises itself, never writes to a hook's stdout (which may be parsed as JSON)."""
    try:
        from plateau.bridge import common as bridge_common
        payload = bridge_common.read_payload()
        bridge_common.log(bridge_common.root(payload), f"{mode} {msg}")
    except Exception:
        pass


def _dispatch_module_mode(mode: str, rest: list) -> None:
    module_path = MODULE_MODES[mode]
    try:
        mod = importlib.import_module(module_path)
    except Exception as exc:
        _log_fallback(mode, f"SKIP {module_path} not available ({exc!r})")
        return

    try:
        mod.main(rest)
    except SystemExit:
        pass
    except Exception as exc:
        _log_fallback(mode, f"ERROR {exc!r}")


def _dispatch_signal_mode(mode: str, rest: list) -> None:
    """`parent`/`pre`/`post` -> `plateau.hooks.signal.main(mode, rest)`. These modes
    ground via cwd, not stdin, but the caller (Claude Code, for `--cc`) still writes a
    JSON payload to stdin that `plateau.hooks.signal.main` itself drains -- this
    dispatcher must not touch stdin before or instead of that."""
    try:
        from plateau.hooks import signal as hooks_signal
    except Exception as exc:
        _log_fallback(mode, f"SKIP plateau.hooks.signal not available ({exc!r})")
        return

    try:
        hooks_signal.main(mode, rest)
    except SystemExit:
        pass
    except Exception as exc:
        _log_fallback(mode, f"ERROR {exc!r}")


def main() -> None:
    """CLI + Claude Code hook entry, dispatching all nine modes into the package (see
    module docstring). `--cc` is stripped from argv up front (as the pre-step-4
    `hook.py` did): the six module modes' own `main(argv)` never take `--cc` -- they
    always emit their own hook JSON regardless -- so it would otherwise reach their
    argparse as an unrecognized argument. `args[0]` (after stripping) is the mode
    (default `pre`, matching the pre-step-4 default); everything after it (`--print`,
    `--write`, `--agent subagent`, ...) is passed straight through to the target's own
    `main`. For the three signal modes, `--cc` IS meaningful (it selects Claude-Code
    hook JSON vs. a plain dict) and is passed back in explicitly."""
    cc = "--cc" in sys.argv[1:]
    args = [a for a in sys.argv[1:] if a != "--cc"]
    mode = args[0] if args else "pre"
    rest = args[1:]
    if mode in SIGNAL_MODES:
        _dispatch_signal_mode(mode, (["--cc"] if cc else []) + rest)
    elif mode in MODULE_MODES:
        _dispatch_module_mode(mode, rest)
    else:
        _log_fallback(mode, "not recognized -- no-op")


if __name__ == "__main__":
    main()
