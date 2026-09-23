"""plateau.bridge.compaction — `plateau compaction`: see and set the compaction procedure.

    plateau compaction                     status: window, soft/hard lines and where each comes from
    plateau compaction --apply 25 [--soft 20]
        writes CLAUDE_AUTOCOMPACT_PCT_OVERRIDE=25 into ~/.claude/settings.json `env` (so
        native compaction fires at 25% of the auto-compact window) and turns the procedure
        on in ~/.plateau/bridge.toml ([compaction] enabled/soft_pct). New sessions pick it up.
    plateau compaction --off               removes both again

Both files are backed up once (`<file>.plateau-bak`) before the first write.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
from typing import List, Optional

from . import common, config, pressure

_SECTION_RE = re.compile(r"(?ms)^\[compaction\]\n.*?(?=^\[|\Z)")


def _settings_path() -> str:
    return os.path.join(os.path.expanduser("~"), ".claude", "settings.json")


def _toml_path() -> str:
    return os.path.join(os.path.expanduser("~"), ".plateau", "bridge.toml")


def _backup(path: str) -> None:
    bak = path + ".plateau-bak"
    if os.path.isfile(path) and not os.path.exists(bak):
        shutil.copy(path, bak)


def _set_env(value: Optional[int]) -> None:
    path = _settings_path()
    data = {}
    if os.path.isfile(path):
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    _backup(path)
    env = dict(data.get("env") or {})
    if value is None:
        env.pop(pressure.PCT_ENV, None)
    else:
        env[pressure.PCT_ENV] = str(value)
    if env:
        data["env"] = env
    else:
        data.pop("env", None)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
        f.write("\n")


def _set_toml(section: Optional[str]) -> None:
    path = _toml_path()
    text = open(path, encoding="utf-8").read() if os.path.isfile(path) else ""
    _backup(path)
    text = _SECTION_RE.sub("", text).rstrip("\n")
    if section:
        text = (text + "\n\n" if text else "") + section
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text.rstrip("\n") + "\n" if text else "")


def status(root: str) -> str:
    cfg = config.load(root, "compaction-status")
    c = cfg.compaction or {}
    soft, hard = pressure.thresholds(cfg)
    window = pressure.window_tokens(root, cfg)
    live = os.environ.get(pressure.PCT_ENV)
    try:
        with open(_settings_path(), encoding="utf-8") as f:
            configured = (json.load(f).get("env") or {}).get(pressure.PCT_ENV)
    except (OSError, ValueError):
        configured = None
    return "\n".join([
        "procedure: {}".format("on" if c.get("enabled") else "off"),
        "window: {}k tokens".format(window // 1000),
        "soft line (crystallize): {:g}% = {}k".format(soft, int(window * soft / 100) // 1000),
        "hard line (native compaction): {:g}% = {}k".format(hard, int(window * hard / 100) // 1000),
        "{} in settings.json: {}; in this process: {}".format(pressure.PCT_ENV, configured, live),
        "summary steering: {}".format("on" if c.get("steer_summary", True) else "off"),
    ])


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="plateau compaction", description=__doc__.splitlines()[0])
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--apply", type=int, metavar="HARD_PCT")
    g.add_argument("--off", action="store_true")
    ap.add_argument("--soft", type=int, metavar="SOFT_PCT", default=None)
    args = ap.parse_args(argv or [])
    if args.apply is not None:
        if not 1 <= args.apply <= 95:
            ap.error("--apply takes a percentage between 1 and 95")
        soft = args.soft if args.soft is not None else max(1, args.apply - 5)
        if not 1 <= soft < args.apply:
            ap.error("--soft must be below the hard line")
        _set_env(args.apply)
        _set_toml("[compaction]\nenabled = true\nsoft_pct = {}\nhard_pct = {}\n".format(soft, args.apply))
        os.environ[pressure.PCT_ENV] = str(args.apply)
    elif args.off:
        _set_env(None)
        _set_toml(None)
        os.environ.pop(pressure.PCT_ENV, None)
    print(status(common.root({})))
    if args.apply is not None or args.off:
        print("new sessions pick this up; running sessions keep their launch environment")
    return 0
