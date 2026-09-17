#!/usr/bin/env python3
"""plateau.lab.ledger — SessionEnd hook: one ledger row per (session, agent).

`.plateau/ledger.sqlite` (private-ring-bound, unlike `.plateau/index.sqlite` which the
bridge itself reads/writes) holds three tables (docs/harness-0.3/PLAN-step4.md
"Ledger"): `sessions` — one row per `(session_id, agent_id)` (S4-A2: the main agent's
`agent_id` is the empty string) summarizing a session's receipts, compactions,
injections, holdouts, lookups, re-derivations, token usage, probe outcomes, its handoff
file, and its cost; `probes` — one row per shadow probe `plateau.lab.probes.maybe()`
ran, written directly by that module (see `record_probe()` below); `rederivations` —
one row per D-038-style re-derivation event this module itself detects from the
transcript.

`main()` runs at SessionEnd, reading the hook payload from stdin exactly like every
other `plateau.bridge.*` hook module (never raises; logs and returns on error). It reads
three sources: the receipt store (`plateau.bridge.common.db`), the session's transcript
(usage fields, `message.model`, compaction boundaries, and every `Read`/`NotebookRead`
call — the D-038 re-derivation definition, `experiments/d038/score.py::turn_usage`,
sealed reference, reimplemented here rather than imported), and `.plateau/hooks.log`
for lookup counts. `plateau.bridge.lookup` (not owned by this module — PLAN-step4.md
Ledger section names it as "written by lookup.py") does not currently emit the
`lookup q=…` log line the Ledger section describes, so `_count_lookups()` is written
defensively: it counts any line containing the word "lookup" and only pulls a hit count
out of lines that DO match the described shape. Today that means `lookups`/
`lookup_hits` read 0 for every session — flagged in this module's owner's return text,
not silently swallowed.

`report_main(argv)` implements `plateau report` (see that function's docstring for the
exact aggregates and the interpretive choices it documents where the contract text
underdetermines the grouping).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

from ..bridge import common
from ..bridge import config as bridge_config

try:
    import tomllib as _tomllib  # Python >= 3.11
except ImportError:  # pragma: no cover - exercised on 3.9/3.10
    _tomllib = None  # type: ignore[assignment]

LEDGER_REL = ".plateau/ledger.sqlite"

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS sessions(
  session_id TEXT, agent_id TEXT, agent TEXT, model_id TEXT, bridge_version TEXT, bridge_sha TEXT,
  receipts INTEGER DEFAULT 0, compactions INTEGER DEFAULT 0, injections_n INTEGER DEFAULT 0,
  injections_chars INTEGER DEFAULT 0, holdouts INTEGER DEFAULT 0, lookups INTEGER DEFAULT 0,
  lookup_hits INTEGER DEFAULT 0, rederivations INTEGER DEFAULT 0, tokens_in INTEGER DEFAULT 0,
  tokens_out INTEGER DEFAULT 0, probes_n INTEGER DEFAULT 0, probes_exact INTEGER DEFAULT 0,
  probes_fuzzy INTEGER DEFAULT 0, probes_wrong INTEGER DEFAULT 0, handoff_path TEXT,
  cost_usd REAL DEFAULT 0.0, started REAL, ended REAL,
  PRIMARY KEY(session_id, agent_id)
);
CREATE TABLE IF NOT EXISTS probes(
  session_id TEXT, turn INTEGER, cls TEXT, kind TEXT, lag_tokens INTEGER,
  compactions_crossed INTEGER, verdict TEXT, q_hash TEXT
);
CREATE TABLE IF NOT EXISTS rederivations(
  session_id TEXT, line INTEGER, path TEXT
);
"""

_SESSION_FIELDS = [
    "session_id", "agent_id", "agent", "model_id", "bridge_version", "bridge_sha",
    "receipts", "compactions", "injections_n", "injections_chars", "holdouts",
    "lookups", "lookup_hits", "rederivations", "tokens_in", "tokens_out",
    "probes_n", "probes_exact", "probes_fuzzy", "probes_wrong", "handoff_path",
    "cost_usd", "started", "ended",
]

GRADE = {"exact": 1.0, "fuzzy": 0.5, "wrong": 0.0}


# --- store open ----------------------------------------------------------------------

def db(root: str) -> sqlite3.Connection:
    """Open (creating if needed) `<root>/.plateau/ledger.sqlite`, schema applied."""
    path = os.path.join(root, LEDGER_REL)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = sqlite3.connect(path, timeout=5)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.executescript(_SCHEMA_SQL)
    conn.commit()
    return conn


# --- identity --------------------------------------------------------------------------

def agent_id_of(agent: str, payload: Dict[str, Any]) -> str:
    """The empty string for the main agent (S4-A2: "the main agent's `agent_id` is the
    empty string"); otherwise the payload's own per-instance id. Mirrors
    `plateau.bridge.handoff._resolve_agent_id`'s fallback order, reimplemented locally
    so this module carries no import-time dependency on that module's private
    helpers."""
    if not agent or not agent.startswith("subagent:"):
        return ""
    payload = payload or {}
    return str(
        payload.get("agent_id") or payload.get("agent_type") or payload.get("agent_name") or ""
    ).strip()


# --- hooks.log lookups (defensive; see module docstring) ------------------------------

_LOOKUP_LOG_RE = re.compile(r"\blookup\b.*?q=(\d+)ch(?:.*?hits=(\d+))?", re.I)


def _count_lookups(root: str) -> Tuple[int, int]:
    """`(lookups, lookup_hits)` counted from `.plateau/hooks.log` lines that merely
    CONTAIN the word "lookup" (defensive: `plateau.bridge.lookup` — not owned by this
    module — does not currently write any log line at all, so this reads `(0, 0)` on
    an unmodified checkout; the regex is written against the `lookup q=<n>ch ...`
    shape PLAN-step4.md's Ledger section names, so a hit count is only ever pulled out
    of a line actually shaped that way)."""
    path = os.path.join(root, common.LOG_REL)
    if not os.path.isfile(path):
        return 0, 0
    lookups = 0
    hits = 0
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                if "lookup" not in line:
                    continue
                lookups += 1
                m = _LOOKUP_LOG_RE.search(line)
                if m and m.group(2) is not None:
                    try:
                        hits += int(m.group(2))
                    except ValueError:
                        pass
    except OSError:
        return 0, 0
    return lookups, hits


# --- transcript scan --------------------------------------------------------------------

def _read_transcript(transcript_path: str) -> Dict[str, Any]:
    """Best-effort scan of a transcript JSONL: `model_id` (last non-empty
    `message.model` seen), summed `tokens_in`/`tokens_out` (deduplicated by assistant
    message id, same rule `experiments/d038/probes.py::scan` uses), every compaction
    boundary's 1-indexed line number, every `Read`/`NotebookRead` tool_use's
    `(line, path)`, and — defensively, since neither the transcript format PLAN.md
    documents nor the SessionEnd hook payload carries a total session cost — any
    `total_cost_usd` value that happens to appear on a line. Never raises; a
    missing/unreadable file yields all-empty results."""
    out: Dict[str, Any] = {
        "model_id": None, "tokens_in": 0, "tokens_out": 0,
        "compaction_lines": [], "reads": [], "cost_usd": 0.0,
    }
    if not transcript_path or not os.path.isfile(transcript_path):
        return out
    seen_msg_ids: set = set()
    try:
        with open(transcript_path, encoding="utf-8", errors="replace") as f:
            for i, raw in enumerate(f, 1):
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    j = json.loads(raw)
                except Exception:
                    continue
                if not isinstance(j, dict):
                    continue
                cost = j.get("total_cost_usd")
                if cost is not None:
                    try:
                        out["cost_usd"] = float(cost)
                    except (TypeError, ValueError):
                        pass
                if j.get("type") == "system" and j.get("subtype") == "compact_boundary":
                    out["compaction_lines"].append(i)
                    continue
                msg = j.get("message")
                if not isinstance(msg, dict):
                    continue
                model = msg.get("model")
                if model:
                    out["model_id"] = model
                if j.get("type") == "assistant":
                    usage = msg.get("usage")
                    mid = msg.get("id")
                    if isinstance(usage, dict) and mid not in seen_msg_ids:
                        seen_msg_ids.add(mid)
                        out["tokens_in"] += int(usage.get("input_tokens", 0) or 0)
                        out["tokens_in"] += int(usage.get("cache_creation_input_tokens", 0) or 0)
                        out["tokens_in"] += int(usage.get("cache_read_input_tokens", 0) or 0)
                        out["tokens_out"] += int(usage.get("output_tokens", 0) or 0)
                    content = msg.get("content")
                    if isinstance(content, list):
                        for b in content:
                            if not isinstance(b, dict) or b.get("type") != "tool_use":
                                continue
                            if b.get("name") not in ("Read", "NotebookRead"):
                                continue
                            tin = b.get("input") or {}
                            path = tin.get("file_path") or tin.get("notebook_path") or ""
                            if path:
                                out["reads"].append((i, path))
    except OSError:
        pass
    return out


def _rederivations(reads: List[Tuple[int, str]], compaction_lines: List[int]) -> List[Tuple[int, str]]:
    """Every Read whose target was already read before some earlier compaction boundary
    and is read again after it with no OTHER compaction boundary in between — the
    D-038 definition (`experiments/d038/score.py::turn_usage`, sealed reference;
    reimplemented here, generalised from that experiment's one task directory to any
    path). Returns one `(line, path)` pair per re-derivation EVENT: a file read twice
    after the same boundary counts twice, matching the sealed scorer."""
    out: List[Tuple[int, str]] = []
    for ci in compaction_lines:
        before = {path for (line, path) in reads if line < ci}
        for line, path in reads:
            if line <= ci or path not in before:
                continue
            if any(ci < cj < line for cj in compaction_lines):
                continue
            out.append((line, path))
    return out


def _handoff_path(root: str, session_id: str, agent_id: str) -> Optional[str]:
    if not session_id:
        return None
    name = f"{session_id}.subagent-{agent_id}.json" if agent_id else f"{session_id}.json"
    path = os.path.join(root, ".plateau", "handoff", name)
    return path if os.path.isfile(path) else None


# --- store-derived counts ---------------------------------------------------------------

def _store_counts(conn: sqlite3.Connection, session_id: str, agent: str) -> Dict[str, Any]:
    """Receipt/compaction/injection/holdout counts for `(session_id, agent)`.
    Compactions and injections are session-wide events that only ever fire for the
    MAIN agent (SessionStart(compact) never runs for a subagent) — a subagent row
    reads 0 for all four, by construction, not by omission."""
    row = conn.execute(
        "SELECT COUNT(*), MIN(ts), MAX(bridge_version), MAX(bridge_sha) "
        "FROM receipts WHERE session_id=? AND agent=?", (session_id, agent),
    ).fetchone()
    receipts, started = row[0] or 0, row[1]
    bv_row = conn.execute(
        "SELECT bridge_version, bridge_sha FROM receipts WHERE session_id=? AND agent=? "
        "ORDER BY id DESC LIMIT 1", (session_id, agent),
    ).fetchone()
    bridge_version, bridge_sha = (bv_row[0], bv_row[1]) if bv_row else (None, None)

    compactions = injections_n = injections_chars = holdouts = 0
    if agent == "main":
        compactions = conn.execute(
            "SELECT COUNT(*) FROM compactions WHERE session_id=?", (session_id,),
        ).fetchone()[0]
        inj = conn.execute(
            "SELECT COUNT(*), COALESCE(SUM(chars),0), COALESCE(SUM(holdout),0) "
            "FROM injections WHERE session_id=?", (session_id,),
        ).fetchone()
        injections_n, injections_chars, holdouts = inj[0], inj[1], inj[2]

    turns = conn.execute(
        "SELECT COUNT(*) FROM turns WHERE session_id=?", (session_id,),
    ).fetchone()[0]

    return {
        "receipts": receipts, "started": started,
        "bridge_version": bridge_version, "bridge_sha": bridge_sha,
        "compactions": compactions, "injections_n": injections_n,
        "injections_chars": injections_chars, "holdouts": holdouts,
        "turns": turns,
    }


def _probe_counts(conn: sqlite3.Connection, session_id: str) -> Dict[str, int]:
    row = conn.execute(
        "SELECT COUNT(*), "
        "COALESCE(SUM(CASE WHEN verdict='exact' THEN 1 ELSE 0 END),0), "
        "COALESCE(SUM(CASE WHEN verdict='fuzzy' THEN 1 ELSE 0 END),0), "
        "COALESCE(SUM(CASE WHEN verdict='wrong' THEN 1 ELSE 0 END),0) "
        "FROM probes WHERE session_id=?", (session_id,),
    ).fetchone()
    n, exact, fuzzy, wrong = row
    return {"probes_n": n or 0, "probes_exact": exact, "probes_fuzzy": fuzzy, "probes_wrong": wrong}


# --- row assembly + upsert ---------------------------------------------------------------

def build_row(
    root: str,
    session_id: str,
    agent: str,
    agent_id: str,
    transcript_path: str,
    *,
    store_conn: Optional[sqlite3.Connection] = None,
    ledger_conn: Optional[sqlite3.Connection] = None,
    ended: Optional[float] = None,
) -> Dict[str, Any]:
    """Assemble one `sessions` row (PLAN-step4.md "Ledger") for `(session_id,
    agent_id)`. `store_conn`/`ledger_conn` let a caller (tests; `main()` when it opens
    its own) pass an already-open connection instead of this function opening
    `root`'s real files. Only the MAIN agent's row carries lookups/rederivations (both
    are session-wide, main-only phenomena — see `_store_counts`, and shadow probes are
    "main agent only" per PLAN-step4.md "Shadow probes"). The returned dict carries one
    extra key, `_rederivation_rows`, consumed and stripped by `upsert()`; it is not a
    `sessions` column."""
    own_store = store_conn is None
    conn = store_conn if store_conn is not None else common.db(root)
    try:
        counts = _store_counts(conn, session_id, agent)
    finally:
        if own_store:
            conn.close()

    own_ledger = ledger_conn is None
    lconn = ledger_conn if ledger_conn is not None else db(root)
    try:
        probe_counts = _probe_counts(lconn, session_id)
    finally:
        if own_ledger:
            lconn.close()

    tinfo = _read_transcript(transcript_path)
    is_main = agent == "main"
    rederivs = _rederivations(tinfo["reads"], tinfo["compaction_lines"]) if is_main else []
    lookups, lookup_hits = _count_lookups(root) if is_main else (0, 0)

    row: Dict[str, Any] = {
        "session_id": session_id,
        "agent_id": agent_id,
        "agent": agent,
        "model_id": tinfo["model_id"],
        "bridge_version": counts["bridge_version"],
        "bridge_sha": counts["bridge_sha"],
        "receipts": counts["receipts"],
        "compactions": counts["compactions"],
        "injections_n": counts["injections_n"],
        "injections_chars": counts["injections_chars"],
        "holdouts": counts["holdouts"],
        "lookups": lookups,
        "lookup_hits": lookup_hits,
        "rederivations": len(rederivs),
        "tokens_in": tinfo["tokens_in"],
        "tokens_out": tinfo["tokens_out"],
        "handoff_path": _handoff_path(root, session_id, agent_id),
        "cost_usd": tinfo["cost_usd"],
        "started": counts["started"],
        "ended": time.time() if ended is None else ended,
    }
    row.update(probe_counts)
    row["_rederivation_rows"] = rederivs
    row["_turns"] = counts["turns"]  # not a sessions column either; report_main's own use
    return row


def upsert(conn: sqlite3.Connection, row: Dict[str, Any]) -> None:
    """Insert or overwrite the `sessions` row keyed `(session_id, agent_id)` (S4-A2),
    plus one `rederivations` row per event named by the row's `_rederivation_rows`
    (`build_row`'s private carry field — dropped before the INSERT, never written as a
    column)."""
    values = [row.get(f) for f in _SESSION_FIELDS]
    placeholders = ", ".join("?" for _ in _SESSION_FIELDS)
    columns = ", ".join(_SESSION_FIELDS)
    updates = ", ".join(f"{f}=excluded.{f}" for f in _SESSION_FIELDS if f not in ("session_id", "agent_id"))
    conn.execute(
        f"INSERT INTO sessions({columns}) VALUES({placeholders}) "
        f"ON CONFLICT(session_id, agent_id) DO UPDATE SET {updates}",
        values,
    )
    session_id = row.get("session_id")
    for line, path in row.get("_rederivation_rows") or []:
        conn.execute(
            "INSERT INTO rederivations(session_id, line, path) VALUES(?,?,?)",
            (session_id, line, path),
        )
    conn.commit()


def record_probe(
    conn: sqlite3.Connection,
    session_id: str,
    turn: int,
    cls: str,
    kind: str,
    lag_tokens: int,
    compactions_crossed: int,
    verdict: str,
    q_hash: str,
) -> None:
    """Insert one `probes` row. Called by `plateau.lab.probes.maybe()` on its own
    ledger connection — this is the ONLY writer of that table."""
    conn.execute(
        "INSERT INTO probes(session_id, turn, cls, kind, lag_tokens, compactions_crossed, "
        "verdict, q_hash) VALUES(?,?,?,?,?,?,?,?)",
        (session_id, turn, cls, kind, lag_tokens, compactions_crossed, verdict, q_hash),
    )
    conn.commit()


# --- SessionEnd hook entry point ---------------------------------------------------------

def main(argv: Optional[List[str]] = None) -> None:
    """SessionEnd hook: reads the payload from stdin, upserts one `sessions` row for
    this `(session_id, agent_id)`. Never raises (logs and returns instead, matching
    every other `plateau.bridge.*` hook module); prints nothing (SessionEnd's output is
    not consumed by Claude Code). Skipped entirely when the resolved bridge role is
    "off" ("off means off everywhere"; docs/harness-0.3/PLAN.md deviations)."""
    payload = common.read_payload()
    root = common.root(payload)
    session_id = payload.get("session_id", "")
    try:
        cfg = bridge_config.load(root, session_id)
        if cfg.role == "off":
            return
        agent = common.agent_of(payload)
        agent_id = agent_id_of(agent, payload)
        row = build_row(root, session_id, agent, agent_id, payload.get("transcript_path", ""))
        conn = db(root)
        try:
            upsert(conn, row)
        finally:
            conn.close()
        common.log(root, f"ledger session={session_id} agent={agent}")
    except Exception as e:
        try:
            common.log(root, f"ledger ERROR {e!r}")
        except Exception:
            pass


# --- `plateau report` -------------------------------------------------------------------

def _lag_bucket(lag_tokens: Optional[int]) -> int:
    """Same three buckets `experiments/d038/probes.py::LAG_BUCKETS` uses (sealed
    reference; the boundary VALUES are duplicated here rather than imported, since
    that module is a frozen experiment record, never a dependency)."""
    if lag_tokens is None:
        lag_tokens = 0
    if lag_tokens < 20_000:
        return 0
    if lag_tokens < 60_000:
        return 1
    return 2


def _mean(xs: List[float]) -> Optional[float]:
    xs = [x for x in xs if x is not None]
    return (sum(xs) / len(xs)) if xs else None


def _load_model_cells(root: str) -> List[Dict[str, Any]]:
    """Every `[[cell]]` table in `<root>/model.toml`, as plain dicts. Uses `tomllib`
    when available; `plateau.bridge._toml`'s fallback parser explicitly does not
    support array-of-tables (`[[x]]}` — see its own docstring), so on 3.9/3.10 this
    splits the file on `[[cell]]` markers itself and parses each block as its own
    flat top-level document (a cell's keys never nest a `[section]` of their own, so
    this is lossless for `model.toml` specifically, not a general TOML fallback)."""
    path = os.path.join(root, "model.toml")
    if not os.path.isfile(path):
        return []
    try:
        with open(path, "rb") as f:
            raw = f.read()
        text = raw.decode("utf-8")
    except OSError:
        return []
    if _tomllib is not None:
        try:
            data = _tomllib.loads(text)
        except Exception:
            return []
        return [dict(c) for c in (data.get("cell") or []) if isinstance(c, dict)]
    from ..bridge import _toml
    cells: List[Dict[str, Any]] = []
    for block in re.split(r"(?m)^\[\[cell\]\]\s*$", text)[1:]:
        try:
            cells.append(_toml.loads(block))
        except Exception:
            continue
    return cells


def _residuals(group_key: str, model_id: Optional[str], observed_recall_by_comp: Dict[int, Optional[float]], root: str) -> Dict[str, float]:
    """`observed - predicted` for every `c<N>` bucket a matching `model.toml` cell
    (same `model_id` and `bridge_version` as this group) names in its own
    `recall_by_comp` table. `{}` when no cell matches or `model_id` is unknown for the
    group (mixed/absent across its sessions)."""
    if not model_id:
        return {}
    for cell in _load_model_cells(root):
        if cell.get("model_id") == model_id and cell.get("bridge_version") == group_key:
            predicted = cell.get("recall_by_comp") or {}
            out: Dict[str, float] = {}
            for key, pred_val in predicted.items():
                idx_digits = "".join(ch for ch in str(key) if ch.isdigit())
                if not idx_digits:
                    continue
                idx = int(idx_digits)
                obs = observed_recall_by_comp.get(idx)
                if obs is not None:
                    out[f"c{idx}"] = obs - pred_val
            return out
    return {}


def _report_data(root: str) -> Dict[str, Any]:
    """Per-`bridge_version` aggregates (PLAN-step4.md "`plateau report`"): session
    count; mean compactions/turn; mean injection size (chars per injection); holdout
    vs non-holdout re-derivations per turn — since the `sessions` table records one
    total re-derivation count per session rather than per compaction, this groups
    SESSIONS by whether they had ANY holdout compaction (`holdouts > 0`) vs none at
    all, the coarsest split the stored schema supports, and documents that choice
    here rather than silently picking a finer one the data cannot actually back;
    probe recall by lag bucket and by `compactions_crossed`; mean tokens/turn; and
    residuals against `model.toml` cells sharing the group's `bridge_version` and
    (when the group's sessions agree on one) `model_id`."""
    ledger_path = os.path.join(root, LEDGER_REL)
    if not os.path.isfile(ledger_path):
        return {"groups": {}}
    conn = db(root)
    conn.row_factory = sqlite3.Row
    try:
        sessions = conn.execute("SELECT * FROM sessions").fetchall()
        probes = conn.execute("SELECT * FROM probes").fetchall()
    finally:
        conn.close()

    by_version: Dict[str, List[sqlite3.Row]] = {}
    for row in sessions:
        by_version.setdefault(row["bridge_version"] or "?", []).append(row)

    probes_by_version: Dict[str, List[sqlite3.Row]] = {}
    session_version = {row["session_id"]: (row["bridge_version"] or "?") for row in sessions}
    for p in probes:
        v = session_version.get(p["session_id"], "?")
        probes_by_version.setdefault(v, []).append(p)

    groups: Dict[str, Any] = {}
    for version, rows in by_version.items():
        # Turn counts are never a `sessions` column (`build_row`'s `_turns` carry key
        # is stripped before the INSERT) -- read them straight from the store instead,
        # one lookup per session_id in this group.
        store_path = os.path.join(root, common.DB_REL)
        turn_counts: Dict[str, int] = {}
        if os.path.isfile(store_path):
            sconn = common.db(root)
            try:
                for r in rows:
                    turn_counts[r["session_id"]] = sconn.execute(
                        "SELECT COUNT(*) FROM turns WHERE session_id=?", (r["session_id"],),
                    ).fetchone()[0]
            finally:
                sconn.close()

        def per_turn(row: sqlite3.Row, field: str) -> Optional[float]:
            t = max(turn_counts.get(row["session_id"], 0), 1)
            return row[field] / t

        compactions_per_turn = _mean([per_turn(r, "compactions") for r in rows])
        inj_chars_mean = _mean(
            [r["injections_chars"] / r["injections_n"] for r in rows if r["injections_n"]]
        )
        holdout_rederiv = _mean([per_turn(r, "rederivations") for r in rows if r["holdouts"] > 0])
        non_holdout_rederiv = _mean([per_turn(r, "rederivations") for r in rows if r["holdouts"] == 0])
        tokens_per_turn = _mean(
            [(r["tokens_in"] + r["tokens_out"]) / max(turn_counts.get(r["session_id"], 0), 1) for r in rows]
        )

        vprobes = probes_by_version.get(version, [])
        recall_by_lag: Dict[int, Optional[float]] = {}
        for lag in (0, 1, 2):
            grades = [GRADE[p["verdict"]] for p in vprobes if _lag_bucket(p["lag_tokens"]) == lag and p["verdict"] in GRADE]
            recall_by_lag[lag] = _mean(grades)
        recall_by_comp: Dict[int, Optional[float]] = {}
        crossed_values = sorted({p["compactions_crossed"] for p in vprobes if p["compactions_crossed"] is not None})
        for c in crossed_values:
            grades = [GRADE[p["verdict"]] for p in vprobes if p["compactions_crossed"] == c and p["verdict"] in GRADE]
            recall_by_comp[c] = _mean(grades)

        model_ids = {r["model_id"] for r in rows if r["model_id"]}
        model_id = next(iter(model_ids)) if len(model_ids) == 1 else None

        groups[version] = {
            "sessions": len(rows),
            "compactions_per_turn": compactions_per_turn,
            "injections_chars_mean": inj_chars_mean,
            "rederivations_per_turn": {"holdout": holdout_rederiv, "non_holdout": non_holdout_rederiv},
            "probe_recall_by_lag": recall_by_lag,
            "probe_recall_by_compactions_crossed": recall_by_comp,
            "tokens_per_turn": tokens_per_turn,
            "residuals": _residuals(version, model_id, recall_by_comp, root),
        }
    return {"groups": groups}


def _fmt(v: Any) -> str:
    if v is None:
        return "-"
    if isinstance(v, float):
        return f"{v:.3f}"
    return str(v)


def _print_table(data: Dict[str, Any]) -> None:
    groups = data.get("groups") or {}
    if not groups:
        print("(no ledger data)")
        return
    header = ["bridge_version", "sessions", "compact/turn", "inj_chars_mean",
              "rederiv/turn(holdout)", "rederiv/turn(bridge)", "tokens/turn"]
    print("  ".join(header))
    for version, g in sorted(groups.items()):
        rederiv = g.get("rederivations_per_turn") or {}
        row = [
            version, _fmt(g.get("sessions")), _fmt(g.get("compactions_per_turn")),
            _fmt(g.get("injections_chars_mean")), _fmt(rederiv.get("holdout")),
            _fmt(rederiv.get("non_holdout")), _fmt(g.get("tokens_per_turn")),
        ]
        print("  ".join(row))
        lag = g.get("probe_recall_by_lag") or {}
        if any(v is not None for v in lag.values()):
            print(f"    probe recall by lag: {{{', '.join(f'{k}: {_fmt(v)}' for k, v in sorted(lag.items()))}}}")
        comp = g.get("probe_recall_by_compactions_crossed") or {}
        if comp:
            print(f"    probe recall by compactions crossed: {{{', '.join(f'{k}: {_fmt(v)}' for k, v in sorted(comp.items()))}}}")
        residuals = g.get("residuals") or {}
        if residuals:
            print(f"    residuals vs model.toml: {{{', '.join(f'{k}: {_fmt(v)}' for k, v in sorted(residuals.items()))}}}")


def report_main(argv: Optional[List[str]] = None) -> None:
    """`plateau report`: per-`bridge_version` aggregates from this repo's ledger,
    printed as a table, or as JSON with `--json` (see `_report_data`'s docstring for
    exactly what each aggregate means)."""
    argv = sys.argv[1:] if argv is None else argv
    ap = argparse.ArgumentParser(prog="plateau report")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--root", default=None, help="repo root (default: git toplevel of cwd)")
    args = ap.parse_args(argv)

    root = args.root or common.root({})
    data = _report_data(root)
    if args.json:
        print(json.dumps(data, indent=2, sort_keys=True))
    else:
        _print_table(data)


if __name__ == "__main__":
    main()
