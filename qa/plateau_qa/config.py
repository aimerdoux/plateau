"""Repo-agnostic configuration for plateau-qa.

A config is a plain dict. `load_config(repo, path)` = DEFAULTS, with repo facts
auto-detected (package.json scripts, supabase dirs, a router file, source language),
then an optional JSON override merged on top (override wins). Stdlib only — JSON, not
TOML, so this runs on Python 3.9 with no third-party dependency.

The config is what de-hardcodes the driver: bootstrap reads `layout`+`tiers` to build the
backlog, gate reads `gate_commands` to know how to verify a kind, and the denylist is
code (security-critical) but `denylist_extra`-extensible.
"""
import json
from pathlib import Path

DEFAULTS = {
    "layout": {
        # first existing candidate becomes the router file (web repos); None otherwise.
        "router_candidates": ["src/App.tsx", "src/app.tsx", "src/main.tsx",
                              "src/router.tsx", "src/routes.tsx", "app/routes.tsx"],
        "functions_dir": "supabase/functions",     # used only if it exists
        "migrations_dir": "supabase/migrations",    # used only if it exists
        "source_globs": [],                          # auto-filled for non-web repos
        "max_source_items": 300,                     # bound the generic backlog
    },
    "tiers": {
        # tier-1 SEC / tier-2 CORE: exact name sets + keyword regexes (case-insensitive).
        "sec_fn_exact": [],
        "sec_pattern": (r"admin|withdraw|wallet|crypto|onramp|stripe|payment|payout|kyc|"
                        r"webhook|transfer|fund|bank|charge|secret|token|password|login|"
                        r"session|role|grant|privilege|auth"),
        "core_fn_exact": [],
        "core_pattern": r"book|checkout|concierge|reserv|order|cart|account|profile|upload|signup",
        "route_tier1": ["/admin"],
        "route_tier2": ["/onboarding", "/rentals", "/auth", "/checkout", "/booking",
                        "/account", "/login", "/signup", "/dashboard"],
    },
    "gate_commands": {},        # kind -> argv list; auto-detected below, override-able
    "denylist_extra": [],       # extra Phase-6.5 regexes appended to the code denylist
}

_LANG_GLOBS = {
    "ts": ["src/**/*.ts", "src/**/*.tsx"],
    "js": ["src/**/*.js", "src/**/*.jsx"],
    "py": ["**/*.py"],
}


def _exists(repo, rel):
    return (Path(repo) / rel).exists()


def _pkg_scripts(repo):
    p = Path(repo) / "package.json"
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text()).get("scripts", {}) or {}
    except ValueError:
        return {}


def _detect_gate_commands(repo):
    """Map work-kinds -> one gate command, detected from the repo's tooling.
    'policy' is intentionally absent: it is the static RLS predicate (handled in gate.py)."""
    g = {}
    s = _pkg_scripts(repo)
    test_script = s.get("test", "")
    if _exists(repo, "jest.config.js") or _exists(repo, "jest.config.ts") or "jest" in test_script:
        unit = ["npx", "jest", "--silent"]
    elif "vitest" in test_script:
        unit = ["npx", "vitest", "run"]
    elif _exists(repo, "pyproject.toml") or _exists(repo, "setup.py") or _exists(repo, "tests"):
        unit = ["python", "-m", "pytest", "-q"]
    elif "test" in s:
        unit = ["npm", "run", "test", "--silent"]
    else:
        unit = None
    if unit:
        for k in ("unit", "edge_fn", "shared", "module"):
            g[k] = unit
    if "build:ci" in s:
        g["build"] = g["src"] = ["npm", "run", "build:ci"]
    elif "build" in s:
        g["build"] = g["src"] = ["npm", "run", "build"]
    if "lint" in s:
        g["lint"] = ["npm", "run", "lint"]
    if (_exists(repo, "playwright.config.ts") or _exists(repo, "playwright.config.js")
            or "playwright" in (s.get("e2e", "") + s.get("test:e2e", ""))):
        g["page"] = g["e2e"] = ["npx", "playwright", "test"]
    return g


def _detect_source_globs(repo):
    src = Path(repo) / "src"
    if src.exists():
        if any(src.rglob("*.ts")) or any(src.rglob("*.tsx")):
            return _LANG_GLOBS["ts"]
        if any(src.rglob("*.js")):
            return _LANG_GLOBS["js"]
    if any(Path(repo).rglob("*.py")):
        return _LANG_GLOBS["py"]
    return _LANG_GLOBS["ts"]


def _deep_merge(base, over):
    out = dict(base)
    for k, v in (over or {}).items():
        out[k] = _deep_merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def load_config(repo, path=None):
    """Build the effective config for `repo`. `path` is an optional JSON override file
    (its keys win over auto-detection)."""
    cfg = json.loads(json.dumps(DEFAULTS))      # deep copy
    cfg["gate_commands"] = _detect_gate_commands(repo)
    lay = cfg["layout"]
    lay["router_file"] = next((c for c in lay["router_candidates"] if _exists(repo, c)), None)
    lay["functions_dir"] = lay["functions_dir"] if _exists(repo, lay["functions_dir"]) else None
    lay["migrations_dir"] = lay["migrations_dir"] if _exists(repo, lay["migrations_dir"]) else None
    if not lay["source_globs"]:
        lay["source_globs"] = _detect_source_globs(repo)
    if path:
        cfg = _deep_merge(cfg, json.loads(Path(path).read_text()))
    return cfg
