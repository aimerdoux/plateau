"""plateau.lab.usage — `plateau usage`: is the bridge being USED, and does it help?

Read-only and zero-spend (no model call, no probe): it reads the stores' own tables and,
when it can find them, the sessions' Claude Code transcripts. Built after a hand audit on
2026-09-22 found every injection landing at its budget while no model ever cited an
injected receipt id back (0 of 17,661 tool calls), 1 of 24 injected paths was touched after
a compaction, and the lab's own recall probes had never run.

Per store it reports:
  receipts / sessions / reasons-per-receipt (how much of the work carries a `because`)
  injections by event and arm (startup, compact, compact holdout) with mean chars/budget
  after each compaction, over the next WINDOW receipts of that session:
    touch  = injected keys a later receipt touched / injected keys
    reread = Reads of a file already read before the compaction / all Reads
  the injected arm vs the holdout arm is the only controlled comparison the bridge has;
  a holdout arm under ~10 compactions is reported but not worth a conclusion.
  citations: `[rN]` ids in assistant text and `plateau lookup` calls in the transcripts.

    plateau usage [--root DIR ...] [--scan DIR] [--since YYYY-MM-DD] [--window N] [--json]
"""

from __future__ import annotations

import argparse
import datetime as _dt
import glob
import json
import os
import re
import sqlite3
from typing import Any, Dict, Iterable, List, Optional

from ..bridge import common

WINDOW = 150
MIN_ARM = 10  # compactions per arm before a comparison means anything
_RID_RE = re.compile(r"\[r\d{1,6}\]")
# an invoked lookup only: a Bash command that runs it, not text that merely names it
_LOOKUP_RE = re.compile(r"(?:^|[;&|(]\s*)(?:plateau|python3? -m plateau\.cli)\s+lookup\s")
_SKIP_DIRS = {"node_modules", ".git", "Library", ".Trash", ".cache", "venv", ".venv"}


def find_stores(top: str, max_depth: int = 7) -> List[str]:
    """Roots under `top` holding a `.plateau/index.sqlite` (skips heavy/vendored dirs)."""
    out: List[str] = []
    top = os.path.abspath(os.path.expanduser(top))
    base_depth = top.rstrip(os.sep).count(os.sep)
    for dirpath, dirnames, _files in os.walk(top):
        if os.path.isfile(os.path.join(dirpath, common.DB_REL)):
            out.append(dirpath)
        if dirpath.count(os.sep) - base_depth >= max_depth:
            dirnames[:] = []
            continue
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS and not (d.startswith(".") and d != ".claude")]
        if ".plateau" in dirnames:
            dirnames.remove(".plateau")
    return sorted(out)


def _path_of(key: str) -> Optional[str]:
    k = re.sub(r"^(read|file|symbol|error|decided):", "", key or "")
    m = re.match(r"(/[^\s:]+|[\w.\-]+/[^\s:]+)", k)
    return m.group(1) if m else None


def _compactions(conn: sqlite3.Connection, since: float, window: int) -> List[Dict[str, Any]]:
    rows = conn.execute(
        "SELECT session_id, holdout, keys, rid_at, chars FROM injections "
        "WHERE event='compact' AND ts>=? ORDER BY ts", (since,)).fetchall()
    out = []
    for sid, hold, keys, rid_at, chars in rows:
        rid_at = rid_at or 0
        keys = json.loads(keys or "[]")
        pre_read = {t for (t,) in conn.execute(
            "SELECT target FROM receipts WHERE session_id=? AND id<=? AND tool IN ('Read','Edit','Write')",
            (sid, rid_at))}
        post = conn.execute(
            "SELECT tool, target FROM receipts WHERE session_id=? AND id>? ORDER BY id LIMIT ?",
            (sid, rid_at, window)).fetchall()
        targets = [t or "" for _tool, t in post]
        reads = [t for tool, t in post if tool == "Read" and t]
        touched = sum(1 for k in keys if (_path_of(k) or k) and any((_path_of(k) or k) in t for t in targets))
        out.append({"session_id": sid, "holdout": bool(hold), "chars": chars, "post": len(post),
                    "keys": len(keys), "touched": touched, "reads": len(reads),
                    "rereads": sum(1 for t in reads if t in pre_read)})
    return out


def _arm(cs: Iterable[Dict[str, Any]], holdout: bool) -> Dict[str, Any]:
    cs = [c for c in cs if c["holdout"] == holdout and c["post"] >= 20]
    reads = sum(c["reads"] for c in cs)
    keys = sum(c["keys"] for c in cs)
    return {"n": len(cs), "reads": reads,
            "reread_rate": round(sum(c["rereads"] for c in cs) / reads, 3) if reads else None,
            "touch_rate": round(sum(c["touched"] for c in cs) / keys, 3) if keys else None,
            "enough": len(cs) >= MIN_ARM}


def _transcript(session_id: str, projects: str) -> Optional[str]:
    hits = glob.glob(os.path.join(projects, "*", session_id + ".jsonl"))
    return hits[0] if hits else None


def _citations(session_ids: Iterable[str], projects: str) -> Dict[str, int]:
    out = {"transcripts": 0, "assistant_messages": 0, "rid_citations": 0, "lookup_calls": 0}
    for sid in session_ids:
        path = _transcript(sid, projects)
        if not path:
            continue
        out["transcripts"] += 1
        with open(path, encoding="utf-8", errors="ignore") as f:
            for line in f:
                if '"assistant"' not in line:
                    continue
                try:
                    e = json.loads(line)
                except ValueError:
                    continue
                if e.get("type") != "assistant":
                    continue
                out["assistant_messages"] += 1
                for b in (e.get("message") or {}).get("content") or []:
                    if not isinstance(b, dict):
                        continue
                    if b.get("type") == "text":
                        out["rid_citations"] += len(_RID_RE.findall(b.get("text", "")))
                    elif b.get("type") == "tool_use" and b.get("name") == "Bash":
                        cmd = (b.get("input") or {}).get("command", "")
                        if isinstance(cmd, str) and _LOOKUP_RE.search(cmd):
                            out["lookup_calls"] += 1
    return out


def store_usage(root: str, since: float = 0.0, window: int = WINDOW,
                projects: Optional[str] = None) -> Dict[str, Any]:
    path = os.path.join(root, common.DB_REL)
    conn = sqlite3.connect("file:{}?mode=ro".format(path), uri=True)
    try:
        receipts, sessions = conn.execute(
            "SELECT COUNT(*), COUNT(DISTINCT session_id) FROM receipts WHERE ts>=?", (since,)).fetchone()
        reasons = conn.execute(
            "SELECT COUNT(*) FROM reasons x JOIN receipts r ON r.id=x.rid WHERE r.ts>=?", (since,)).fetchone()[0]
        inj = {}
        for event, hold, n, chars, budget in conn.execute(
                "SELECT event, holdout, COUNT(*), AVG(chars), AVG(budget) FROM injections WHERE ts>=? "
                "GROUP BY event, holdout", (since,)):
            inj[event + (" holdout" if hold else "")] = {"n": n, "mean_chars": round(chars or 0), "budget": round(budget or 0)}
        comps = _compactions(conn, since, window)
        try:  # 0.5: the compaction procedure's own events (absent from pre-0.5 stores)
            press = dict(conn.execute(
                "SELECT event, COUNT(*) FROM pressure WHERE ts>=? GROUP BY event", (since,)).fetchall())
            press["summary_markers"] = conn.execute(
                "SELECT COALESCE(SUM(tokens),0) FROM pressure WHERE event='summary' AND ts>=?", (since,)).fetchone()[0]
            crystallized_at_compact = conn.execute(
                "SELECT COUNT(*) FROM pressure WHERE event='compact' AND detail LIKE '%crystallized=yes%' AND ts>=?",
                (since,)).fetchone()[0]
        except sqlite3.Error:
            press, crystallized_at_compact = {}, 0
        sids = [s for (s,) in conn.execute("SELECT DISTINCT session_id FROM receipts WHERE ts>=?", (since,))]
    finally:
        conn.close()
    projects = projects or os.path.expanduser("~/.claude/projects")
    return {
        "root": root, "receipts": receipts, "sessions": sessions,
        "reasons_per_receipt": round(reasons / receipts, 3) if receipts else None,
        "injections": inj,
        "pressure": dict(press, compact_crystallized=crystallized_at_compact) if press else {},
        "compaction": {"inject": _arm(comps, False), "holdout": _arm(comps, True)},
        "citations": _citations(sids, projects) if os.path.isdir(projects) else None,
    }


def _render(rows: List[Dict[str, Any]]) -> str:
    lines = []
    tot = {"receipts": 0, "rid": 0, "lookup": 0, "msgs": 0}
    for r in rows:
        lines.append("{}  receipts={} sessions={} reasons/receipt={}".format(
            r["root"], r["receipts"], r["sessions"], r["reasons_per_receipt"]))
        for k, v in sorted(r["injections"].items()):
            lines.append("  inject {:<16} n={:<3} mean {}/{} chars".format(k, v["n"], v["mean_chars"], v["budget"]))
        for arm in ("inject", "holdout"):
            a = r["compaction"][arm]
            if a["n"]:
                lines.append("  after compaction [{}] n={} reread={} touch={}{}".format(
                    arm, a["n"], a["reread_rate"], a["touch_rate"], "" if a["enough"] else "  (too few to conclude)"))
        p = r.get("pressure") or {}
        if p:
            lines.append("  compaction: {} (summaries lifted {} with {} DECISION/FACT/OPEN lines; soft line {}x, "
                         "mid-task crystallized {}x; floor above soft {}x)".format(
                p.get("compact", 0), p.get("summary", 0), p.get("summary_markers", 0), p.get("soft", 0),
                p.get("crystallized", 0), p.get("floor", 0)))
        c = r["citations"]
        if c:
            lines.append("  transcripts={} [rN] citations={} lookup calls={}".format(
                c["transcripts"], c["rid_citations"], c["lookup_calls"]))
            tot["rid"] += c["rid_citations"]
            tot["lookup"] += c["lookup_calls"]
            tot["msgs"] += c["assistant_messages"]
        tot["receipts"] += r["receipts"]
    lines.append("TOTAL stores={} receipts={} [rN] citations={} lookup calls={} over {} assistant messages".format(
        len(rows), tot["receipts"], tot["rid"], tot["lookup"], tot["msgs"]))
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="plateau usage", description=__doc__.splitlines()[0])
    ap.add_argument("--root", action="append", default=[], help="a project root (repeatable)")
    ap.add_argument("--scan", default=None, help="find every store under this directory")
    ap.add_argument("--since", default=None, help="YYYY-MM-DD, local time")
    ap.add_argument("--window", type=int, default=WINDOW)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv or [])
    since = _dt.datetime.strptime(args.since, "%Y-%m-%d").timestamp() if args.since else 0.0
    roots = list(args.root)
    if args.scan:
        roots += find_stores(args.scan)
    if not roots:
        roots = [common.root({})]
    rows = []
    for root in dict.fromkeys(os.path.abspath(r) for r in roots):
        if not os.path.isfile(os.path.join(root, common.DB_REL)):
            continue
        try:
            r = store_usage(root, since, args.window)
        except sqlite3.Error:
            continue  # an empty/foreign index.sqlite (no bridge tables): nothing to report
        if r["receipts"]:
            rows.append(r)
    print(json.dumps(rows, indent=2) if args.json else _render(rows))
    return 0
