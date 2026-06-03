"""Scan the target repo into a tiered coverage.json backlog — config-driven.

Web repos (router file + supabase dirs present) tier by routes / edge functions / RLS
policies, exactly as before. Repos without those (a Python lib, a TS monorepo) fall back
to a generic source-file scan tiered by the same SEC/CORE keyword rules — so the tool has
a backlog on ANY repo.

Tiering: 1 SEC, 2 CORE, 3 UX, 4 HARDENING (faithful to the triage order).
"""
import re
import subprocess
from pathlib import Path

from . import state

# Vendored / build / cache dirs never belong in the backlog (matched by path segment,
# since relative paths have no leading slash).
_SKIP_DIRS = {".venv", "venv", "node_modules", "dist", "build", ".git",
              "__pycache__", ".mypy_cache", ".pytest_cache", "site-packages", "coverage"}


def _run(cmd, cwd):
    p = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True)
    return p.stdout


def _entry(item_id, kind, tier, extra=None):
    e = {"id": item_id, "kind": kind, "tier": tier, "status": "pending",
         "pattern_key": None, "last_gated_step": None}
    if extra:
        e.update(extra)
    return e


def _name_tier(name, cfg):
    """SEC(1)/CORE(2)/UX(3) for an edge-fn or module name, per config patterns."""
    t = cfg["tiers"]
    if name in set(t["sec_fn_exact"]) or re.search(t["sec_pattern"], name, re.I):
        return 1
    if name in set(t["core_fn_exact"]) or re.search(t["core_pattern"], name, re.I):
        return 2
    return 3


def scan_routes(repo, cfg):
    router = cfg["layout"].get("router_file")
    if not router or not (Path(repo) / router).exists():
        return []
    text = (Path(repo) / router).read_text(errors="replace")
    t = cfg["tiers"]
    entries, seen = [], set()
    for m in re.finditer(r'<Route\s+[^>]*\bpath=(?:"([^"]*)"|\{?[`\'"]([^`\'"]*)[`\'"])', text):
        path = m.group(1) or m.group(2) or ""
        if path in seen:
            continue
        seen.add(path)
        low = path.lower()
        if any(k in low for k in t["route_tier1"]):
            tier = 1
        elif any(k in low for k in t["route_tier2"]):
            tier = 2
        else:
            tier = 3
        entries.append(_entry("page:%s" % (path or "/"), "page", tier))
    return entries


def scan_edge_fns(repo, cfg):
    fdir = cfg["layout"].get("functions_dir")
    if not fdir or not (Path(repo) / fdir).exists():
        return []
    entries = []
    for d in sorted(p for p in (Path(repo) / fdir).iterdir() if p.is_dir()):
        name = d.name
        if name.startswith((".", "_")):
            continue
        tier = _name_tier(name, cfg)
        if tier == 3:
            tier = 4  # an unlisted edge fn is hardening, not auto tier-1
        entries.append(_entry("edge_fn:%s" % name, "edge_fn", tier))
    return entries


def scan_policies(repo, cfg):
    mdir = cfg["layout"].get("migrations_dir")
    if not mdir or not (Path(repo) / mdir).exists():
        return []
    out = _run(["grep", "-rlEi", r"USING\s*\(\s*true\s*\)|WITH\s+CHECK\s*\(\s*true\s*\)",
                str(Path(repo) / mdir)], repo)
    entries = []
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        rel = str(Path(line).relative_to(repo)) if line.startswith(str(repo)) else line
        entries.append(_entry("policy:%s" % Path(line).name, "policy", 1, extra={"file": rel}))
    return entries


def scan_source(repo, cfg):
    """Generic backlog for repos with no router/supabase surface: every source file is a
    `module` item, tiered by the SEC/CORE keyword rules on its path. Bounded by max_source_items."""
    globs = cfg["layout"].get("source_globs", [])
    cap = cfg["layout"].get("max_source_items", 300)
    seen, entries = set(), []
    for g in globs:
        for p in sorted(Path(repo).glob(g)):
            if not p.is_file():
                continue
            rel = str(p.relative_to(repo))
            if rel in seen or set(p.relative_to(repo).parts) & _SKIP_DIRS:
                continue
            seen.add(rel)
            entries.append(_entry("module:%s" % rel, "module", _name_tier(rel, cfg),
                                  extra={"file": rel}))
    entries.sort(key=lambda e: e["tier"])      # SEC/CORE first when we truncate
    return entries[:cap]


def build_coverage(repo, cfg):
    cov = scan_policies(repo, cfg) + scan_edge_fns(repo, cfg) + scan_routes(repo, cfg)
    if not cov:                                # non-web repo -> generic source backlog
        cov = scan_source(repo, cfg)
    return cov
