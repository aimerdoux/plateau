#!/usr/bin/env python3
"""plateau.bridge.install — Claude Code `settings.json` hook-table merge.

`plateau init` (see `plateau.cli`) writes the bridge's own hook table (the modes
`plateau hook` itself dispatches: `receipt`, `snapshot`, `inject`, `lift`, `handoff`,
`ledger` — never the adapter's own `parent`/`pre`/`post` signal-demo hooks, which live in
`adapters/claude_code/hook.py` and are that adapter's concern, not this package's) into a
Claude Code `settings.json`: the project's `<root>/.claude/settings.json`, or
`~/.claude/settings.json` for `--global`.

Merge rule (docs/harness-0.3/PLAN-step3.md "`plateau init` and `plateau hook`"): parse the
existing JSON (starting from `{}` if the file is missing or unreadable); for each event,
append our hook entries unless a hook entry with the SAME `command` string already exists
anywhere under that event (idempotent — installing twice never duplicates); never remove or
reorder anything we did not add ourselves; write back with `indent=2`; back up the
pre-existing file to `<file>.plateau.bak` exactly once (only the first time a write actually
changes the file, and only if that backup does not already exist). `--uninstall`
(`strip_settings`) removes only the hook entries whose `command` contains `plateau hook` or
`plateau.cli hook` — everything else, ours in shape but foreign in content or truly foreign,
survives untouched.
"""

from __future__ import annotations

import json
import os
import shutil
from typing import Any, Dict, List, Optional, Tuple

# A hook entry is "ours" (removable by --uninstall) iff its command contains either marker.
MARKERS = ("plateau hook", "plateau.cli hook")


def hook_binary_available() -> bool:
    """True when the `plateau` console script resolves on PATH."""
    return shutil.which("plateau") is not None


def hook_command(mode: str, args: Optional[List[str]] = None) -> str:
    """The exact command string `plateau init` writes for one hook mode: `plateau hook
    <mode> [args...]` when the `plateau` console script resolves, else `python3 -m
    plateau.cli hook <mode> [args...]` (PLAN-step3.md "`plateau init` and `plateau hook`")."""
    prefix = "plateau hook" if hook_binary_available() else "python3 -m plateau.cli hook"
    parts = [prefix, mode] + list(args or [])
    return " ".join(parts)


def _group(event: str, matcher: Optional[str], mode: str, args: Optional[List[str]], timeout: int) -> Dict[str, Any]:
    hook = {"type": "command", "command": hook_command(mode, args), "timeout": timeout}
    entry: Dict[str, Any] = {}
    if matcher is not None:
        entry["matcher"] = matcher
    entry["hooks"] = [hook]
    return {"event": event, "group": entry}


def hook_table() -> Dict[str, List[Dict[str, Any]]]:
    """`event -> [{matcher?, hooks:[{type,command,timeout}]}, ...]` — the bridge's own
    slice of PLAN-step3.md's hooks.json, restricted to the modes `plateau hook` itself
    dispatches (see module docstring). One group per hooks.json line; SessionStart keeps
    its two matchers (`startup|clear` and `compact`) as separate groups so re-running
    `plateau init` after a matcher's group was hand-edited still recognizes each command
    independently."""
    specs = [
        _group("SessionStart", "startup|clear", "inject", None, 15),
        _group("SessionStart", "compact", "inject", None, 30),
        _group("PostToolUse", "", "receipt", None, 10),
        _group("PreCompact", None, "snapshot", None, 30),
        _group("Stop", None, "lift", None, 10),
        _group("Stop", None, "handoff", ["--print"], 10),
        _group("SessionEnd", None, "ledger", None, 20),
        _group("SessionEnd", None, "handoff", ["--write"], 10),
        _group("SubagentStop", None, "handoff", ["--write", "--agent", "subagent"], 10),
    ]
    table: Dict[str, List[Dict[str, Any]]] = {}
    for spec in specs:
        table.setdefault(spec["event"], []).append(spec["group"])
    return table


def _existing_pairs(groups: Any) -> set:
    """Every `(matcher, command)` pair already present under one event's group list
    (any shape we don't recognize just yields no pairs, never raises). Keyed on the pair,
    not the command alone: `SessionStart` legitimately carries the SAME `inject` command
    twice, once per matcher (`startup|clear` vs `compact`, with different timeouts) --
    deduping on command alone would silently drop the second one."""
    pairs: set = set()
    if not isinstance(groups, list):
        return pairs
    for group in groups:
        if not isinstance(group, dict):
            continue
        matcher = group.get("matcher")
        for hook in group.get("hooks") or []:
            if isinstance(hook, dict) and isinstance(hook.get("command"), str):
                pairs.add((matcher, hook["command"]))
    return pairs


def merge_settings(existing: Dict[str, Any]) -> Tuple[Dict[str, Any], bool]:
    """Return `(new_settings, changed)`; `existing` is never mutated in place. Foreign
    top-level keys (permissions, env, ...) and foreign hook entries are copied through
    untouched; ours are appended only where their exact command is not already present."""
    result: Dict[str, Any] = json.loads(json.dumps(existing)) if existing else {}
    hooks = result.get("hooks")
    if not isinstance(hooks, dict):
        hooks = {}
    result["hooks"] = hooks

    changed = False
    for event, groups in hook_table().items():
        bucket = hooks.get(event)
        if bucket is None:
            bucket = []
            hooks[event] = bucket
        if not isinstance(bucket, list):
            continue  # a foreign, unrecognized shape for this event -- leave it alone
        existing_pairs = _existing_pairs(bucket)
        for group in groups:
            key = (group.get("matcher"), group["hooks"][0]["command"])
            if key in existing_pairs:
                continue
            bucket.append(json.loads(json.dumps(group)))
            existing_pairs.add(key)
            changed = True
    return result, changed


def _strip_ours(groups: Any) -> Tuple[Any, bool]:
    if not isinstance(groups, list):
        return groups, False
    changed = False
    kept: List[Any] = []
    for group in groups:
        if not isinstance(group, dict) or not isinstance(group.get("hooks"), list):
            kept.append(group)
            continue
        kept_hooks = []
        for hook in group["hooks"]:
            cmd = hook.get("command", "") if isinstance(hook, dict) else ""
            if isinstance(cmd, str) and any(marker in cmd for marker in MARKERS):
                changed = True
                continue
            kept_hooks.append(hook)
        if not kept_hooks:
            continue  # the whole group was ours -- drop it entirely
        if len(kept_hooks) != len(group["hooks"]):
            group = dict(group)
            group["hooks"] = kept_hooks
        kept.append(group)
    return kept, changed


def strip_settings(existing: Dict[str, Any]) -> Tuple[Dict[str, Any], bool]:
    """`--uninstall`: remove only hook entries whose `command` contains `plateau hook`
    or `plateau.cli hook`. Returns `(new_settings, changed)`; `existing` untouched."""
    result: Dict[str, Any] = json.loads(json.dumps(existing)) if existing else {}
    hooks = result.get("hooks")
    if not isinstance(hooks, dict):
        return result, False
    changed = False
    for event in list(hooks.keys()):
        new_groups, ev_changed = _strip_ours(hooks[event])
        if not ev_changed:
            continue
        changed = True
        if new_groups:
            hooks[event] = new_groups
        else:
            del hooks[event]
    return result, changed


# --- file IO --------------------------------------------------------------------------

def _load_json(path: str) -> Dict[str, Any]:
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _backup_once(path: str) -> None:
    """Copy the pre-existing file to `<path>.plateau.bak`, but only the first time (a
    backup that already exists is never overwritten, so a second `plateau init` run does
    not clobber the ORIGINAL pre-plateau file with an already-merged one)."""
    if not os.path.isfile(path):
        return
    backup = path + ".plateau.bak"
    if os.path.exists(backup):
        return
    shutil.copyfile(path, backup)


def _write_json(path: str, data: Dict[str, Any]) -> None:
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
        f.write("\n")


def settings_path(root: str, is_global: bool = False) -> str:
    if is_global:
        return os.path.join(os.path.expanduser("~"), ".claude", "settings.json")
    return os.path.join(root, ".claude", "settings.json")


def install_settings(root: str, is_global: bool = False) -> Tuple[str, bool]:
    """Merge our hook table into the target settings.json. Returns `(path, changed)` —
    `changed` is False when the file already had every one of our commands (the
    idempotent case: `plateau init` run twice touches nothing the second time)."""
    path = settings_path(root, is_global)
    existing = _load_json(path)
    merged, changed = merge_settings(existing)
    if changed:
        _backup_once(path)
        _write_json(path, merged)
    elif not os.path.isfile(path):
        _write_json(path, merged)
    return path, changed


def uninstall_settings(root: str, is_global: bool = False) -> Tuple[str, bool]:
    """Remove only our hook entries from the target settings.json. Returns
    `(path, changed)`."""
    path = settings_path(root, is_global)
    existing = _load_json(path)
    stripped, changed = strip_settings(existing)
    if changed:
        _backup_once(path)
        _write_json(path, stripped)
    return path, changed


def copy_global_bridge_toml(force: bool = False) -> Optional[str]:
    """Copy the packaged `bridge.toml` to `~/.plateau/bridge.toml` (no overwrite unless
    `force`). Returns the destination path, or None only if no source copy can be found
    at all (never raises for an ordinary missing-destination-dir case)."""
    here = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.path.join(here, "bridge.default.toml"),
        # dev checkout fallback: plateau/bridge/install.py -> repo root -> bridge.toml
        os.path.join(os.path.dirname(os.path.dirname(here)), "bridge.toml"),
    ]
    src = next((c for c in candidates if os.path.isfile(c)), None)
    if src is None:
        return None
    dest_dir = os.path.join(os.path.expanduser("~"), ".plateau")
    dest = os.path.join(dest_dir, "bridge.toml")
    if os.path.isfile(dest) and not force:
        return dest
    os.makedirs(dest_dir, exist_ok=True)
    shutil.copyfile(src, dest)
    return dest
