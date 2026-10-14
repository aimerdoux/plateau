"""plateau.bridge.dedupe — collapse an identical hook invocation fired more than once.

A user can end up with Plateau's hooks registered twice at once: once by the Claude Code
plugin (`adapters/claude_code/hooks/hooks.json`, `python3 ${CLAUDE_PLUGIN_ROOT}/hook.py
<mode> --cc`) and once by `plateau init --global` (`plateau hook <mode> ...` written into
`~/.claude/settings.json`). Claude Code treats these as two distinct hook commands (the
strings differ) and runs both, so every hook event fires twice within a handful of
milliseconds carrying the exact same stdin payload. Left alone this doubles every
`snapshot`/`inject`/... side effect: `common.mark_compaction`/`common.mark_turn`'s
SELECT-then-INSERT race and raise `IntegrityError` on their UNIQUE keys, a `reasons` row
collides the same way, and a mode that injects text (e.g. `inject`) hands the model that
same block twice in one turn.

`claim()` is the ONE place both dispatch entry points (`adapters/claude_code/hook.py` and
`plateau hook <mode>` in `plateau.cli`) ask "am I the first process handling this exact
invocation, or is this a duplicate within the race window?" -- see `plateau.doctor`'s
"hooks registered once" check for catching the double registration itself, which this
module does not attempt to fix (there is no way to know from inside a single hook process
which of the two registrations to remove).
"""

from __future__ import annotations

import hashlib
import os
import sys
import tempfile
import time
from typing import List, Optional

DEFAULT_WINDOW_S = 2.0
# Opportunistic cleanup horizon for stale claim files -- far larger than any real
# DEFAULT_WINDOW_S so it never interferes with an in-progress dedupe, just keeps the
# claims directory from growing forever on a long-lived machine.
_STALE_S = 60.0

# Modes whose normal (non-duplicate) invocation ALWAYS prints a JSON dict that Claude
# Code parses as hook output (see their own `main`s: `plateau.hooks.signal` for
# parent/pre/post, `plateau.bridge.inject`) -- a duplicate must still print `{}` so a
# caller expecting JSON on stdout never sees an empty pipe instead. Every other mode
# (receipt, snapshot, lift, ledger, a bare `handoff`) prints nothing or plain text on its
# own normal path, so a duplicate printing nothing matches that path exactly.
_JSON_MODES = ("parent", "pre", "post", "inject")


def _claims_dir() -> str:
    """`<tmp>/plateau-claims-<uid>` -- per-user, so two users on a shared machine never
    collide on (or can never even see) each other's claim files. `os.getuid` is missing
    on Windows; fall back to a fixed suffix rather than raising (dedupe still works, just
    without that per-user isolation)."""
    try:
        uid = os.getuid()
    except AttributeError:
        uid = "nouid"
    return os.path.join(tempfile.gettempdir(), f"plateau-claims-{uid}")


def _key(mode: str, argv: List[str], raw: str) -> str:
    """sha256 of mode + normalized argv (`--cc` excluded -- the two dispatch entry
    points disagree on whether it is even present, but a real duplicate always shares
    every OTHER arg) + the raw stdin bytes + this process's cwd.

    The cwd is folded in even though it is not part of the hook's own argv or stdin: a
    real duplicate pair is always two child processes of the SAME hook event, so they
    always share it, while two genuinely unrelated invocations (different repos, e.g.
    two separate `claude` sessions) can otherwise carry a trivially identical payload
    (a `Stop` with no pending facts is just `{}`) and would collide on this key without
    it."""
    normalized = [a for a in argv if a != "--cc"]
    h = hashlib.sha256()
    h.update(mode.encode("utf-8", "replace"))
    h.update(b"\0")
    h.update("\0".join(normalized).encode("utf-8", "replace"))
    h.update(b"\0")
    h.update((raw or "").encode("utf-8", "replace"))
    h.update(b"\0")
    h.update(os.getcwd().encode("utf-8", "replace"))
    return h.hexdigest()


def _cleanup_stale(dir_path: str) -> None:
    """Best-effort removal of claim files older than `_STALE_S`. Cheap (one listdir),
    and never raises -- a cleanup failure must never be why a hook fails."""
    try:
        now = time.time()
        for name in os.listdir(dir_path):
            p = os.path.join(dir_path, name)
            try:
                if now - os.stat(p).st_mtime > _STALE_S:
                    os.remove(p)
            except OSError:
                pass
    except OSError:
        pass


def claim(mode: str, argv: List[str], raw: str, window_s: float = DEFAULT_WINDOW_S) -> bool:
    """True if this process is the first to handle this exact hook invocation (same
    mode, same argv excluding `--cc`, same raw stdin) within `window_s` seconds; False
    when an identical one already claimed it inside that window -- the caller should
    then skip its side effects entirely (see module docstring).

    Mechanism: a lock-free claim file `<claims dir>/<key>`, created with
    `O_CREAT|O_EXCL` so two processes racing the same key can never both "win" the
    create. If it already exists and is younger than `window_s`, this is the duplicate.
    If it exists but is older, this is a genuinely new invocation reusing the same key
    later (real hooks fire far more than `window_s` apart) -- refresh its mtime and
    claim it.

    `PLATEAU_NO_DEDUPE=1` disables this outright (always True) -- an escape hatch for a
    setup where the same payload legitimately recurs quickly. Any `OSError` (no /tmp,
    read-only filesystem, permissions, ...) also returns True: this must fail OPEN,
    never drop a real hook invocation because dedupe bookkeeping itself broke."""
    if os.environ.get("PLATEAU_NO_DEDUPE") == "1":
        return True
    dir_path = _claims_dir()
    path = os.path.join(dir_path, _key(mode, argv, raw))
    try:
        os.makedirs(dir_path, exist_ok=True)
        _cleanup_stale(dir_path)
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.close(fd)
        return True
    except FileExistsError:
        try:
            age = time.time() - os.stat(path).st_mtime
        except OSError:
            # Vanished between the failed create and this stat (another cleanup pass,
            # or the other claimant raced us again) -- failing open is always the safe
            # direction, so treat this as a fresh claim.
            return True
        if age < window_s:
            return False
        try:
            os.utime(path, None)
        except OSError:
            pass
        return True
    except OSError:
        return True


def read_for_dedupe() -> Optional[str]:
    """The raw stdin payload to key a claim on, or `None` when this invocation must not
    be deduped at all: an interactive TTY (someone typed `hook.py <mode>` / `plateau
    hook <mode>` directly for a manual dry run -- never a real Claude Code hook, and
    `sys.stdin.read()` would just hang) or an empty pipe (nothing to key a claim on, and
    proceeding is always safe: there is no real payload for a genuine duplicate to
    collide with)."""
    try:
        if sys.stdin.isatty():
            return None
    except Exception:
        pass
    try:
        raw = sys.stdin.read()
    except Exception:
        return None
    return raw or None


def emits_json(mode: str, argv: List[str]) -> bool:
    """Whether `mode`'s normal invocation always prints a JSON dict Claude Code parses
    as hook output, so a *duplicate* must print `{}` instead of nothing to keep both
    dispatch paths' stdout contracts identical for it. `argv` is the mode's own args
    (already stripped of `--cc`, matching what `claim()` was keyed on).

    `parent`/`pre`/`post`/`inject` always do (see `_JSON_MODES`). `handoff --print` (the
    Stop hooks.json entry) does too; `handoff --write` (SessionEnd/SubagentStop) and a
    bare `handoff` print plain text instead -- see `plateau.bridge.handoff.main`."""
    if mode in _JSON_MODES:
        return True
    if mode == "handoff":
        return "--print" in argv
    return False
