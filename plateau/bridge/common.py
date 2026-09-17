"""plateau.bridge.common — the receipt store: tool calls -> a small bounded graph.

Every tool call `record()`s a receipt row and folds it into `nodes`/`edges`: a running,
deduplicated graph of what a session actually touched (files, symbols it defined, errors
it hit, tests/commands it ran, searches, "read facts" lifted from Read/Grep results, and
decisions lifted at Stop). `plateau.bridge.query` scores and selects a budget-bounded
slice of that graph for injection; nothing here decides what gets shown.

`classify()` keeps the D-037 rules verbatim (see `d037_hooks/d037_common.py` at git tag
`d037-hooks-sealed`) for the base (kind, target, outcome, detail, symbols, error) tuple,
and adds a 7th element: read facts (signatures / config keys from Read results of code
files, and the first `path:line` hit from a Grep result) — mirroring the "class read"
facts in `experiments/d038/probes.py` (read-only reference; sealed, never imported).

Env overrides `PLATEAU_DB_REL` / `PLATEAU_LOG_REL` let the legacy `d037_hooks/` shims
point this same module at the old `.d037/` paths without duplicating any logic.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import subprocess
import sys
import time
from typing import Any, Dict, List, Optional, Set, Tuple

from ..integrity import file_hash
from ..signal import Measurement

DB_REL = os.environ.get("PLATEAU_DB_REL", ".plateau/index.sqlite")
LOG_REL = os.environ.get("PLATEAU_LOG_REL", ".plateau/hooks.log")
SCHEMA = 1
TAG = "plateau_index"
LEGACY_TAG = "d037_index"
TAGS_ON_READ = (TAG, LEGACY_TAG)

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS receipts(id INTEGER PRIMARY KEY, ts REAL, session_id TEXT, agent TEXT,
  bridge_version TEXT, bridge_sha TEXT, tool TEXT, target TEXT, kind TEXT, outcome TEXT, detail TEXT,
  measure_kind TEXT, measure_value TEXT);
CREATE TABLE IF NOT EXISTS nodes(key TEXT PRIMARY KEY, kind TEXT, first_rid INTEGER, last_rid INTEGER,
  degree INTEGER DEFAULT 0, last_outcome TEXT, last_detail TEXT, session_id TEXT, agent TEXT);
CREATE TABLE IF NOT EXISTS edges(src TEXT, rel TEXT, dst TEXT, rid INTEGER);
CREATE TABLE IF NOT EXISTS compactions(session_id TEXT, k INTEGER, ts REAL, rid_at INTEGER, snapshot TEXT,
  PRIMARY KEY(session_id, k));
CREATE TABLE IF NOT EXISTS injections(id INTEGER PRIMARY KEY, ts REAL, session_id TEXT, event TEXT,
  compaction_k INTEGER, chars INTEGER, budget INTEGER, holdout INTEGER DEFAULT 0, bridge_version TEXT,
  bridge_sha TEXT, keys TEXT, rid_at INTEGER);
CREATE TABLE IF NOT EXISTS decisions(id INTEGER PRIMARY KEY, ts REAL, session_id TEXT, agent TEXT, text TEXT,
  provenance TEXT);
CREATE TABLE IF NOT EXISTS turns(session_id TEXT, n INTEGER, ts REAL, rid_at INTEGER, PRIMARY KEY(session_id, n));
CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY, v TEXT);
"""

# --- D-037 rules, kept verbatim (see d037_hooks/d037_common.py @ d037-hooks-sealed) ---
SYM_RE = re.compile(r"^(?:def|class)\s+([A-Za-z_]\w*)|^([A-Z][A-Z0-9_]{2,})\s*=", re.M)
ERR_RE = re.compile(r"^(Traceback|.*Error\b.*|.*FAILED.*|.*Exception\b.*)$", re.M)

# --- new in the bridge: "read facts" from Read/Grep results (see module docstring) ---
CODE_EXT = (".py", ".mjs", ".js", ".ts", ".tsx", ".cjs")
READ_SIG_RE = re.compile(r"^[ \t]*(?:def|function|export function|class)\s+([A-Za-z_$][\w$]*)\s*\(([^)]*)\)", re.M)
READ_CFG_RE = re.compile(
    r"process\.env\.([A-Z][A-Z0-9_]*)"
    r"|os\.environ(?:\.get\(\s*|\[)\s*['\"]([A-Z][A-Z0-9_]*)['\"]"
    r"|^[ \t]*([A-Z][A-Z0-9_]{2,})\s*=",
    re.M,
)
READ_GREP_RE = re.compile(r"^([^\s:][^:\n]*):(\d+):", re.M)
MAX_READ_FACTS = 4


def root(payload: Dict[str, Any]) -> str:
    """Store root: `git rev-parse --show-toplevel` of the payload's cwd, else
    CLAUDE_PROJECT_DIR, else that cwd (or os.getcwd() if the payload has none)."""
    payload = payload or {}
    base = payload.get("cwd") or os.getcwd()
    try:
        cp = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=base, capture_output=True, text=True, timeout=5,
        )
        if cp.returncode == 0:
            top = cp.stdout.strip()
            if top:
                return top
    except Exception:
        pass
    env = os.environ.get("CLAUDE_PROJECT_DIR")
    if env:
        return env
    return base


def log(root_dir: str, msg: str) -> None:
    p = os.path.join(root_dir, LOG_REL)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "a", encoding="utf-8") as f:
        f.write(f"{time.time():.3f} {msg}\n")


def db(root_dir: str) -> sqlite3.Connection:
    p = os.path.join(root_dir, DB_REL)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    conn = sqlite3.connect(p, timeout=5)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.executescript(_SCHEMA_SQL)
    conn.execute("INSERT OR IGNORE INTO meta(k, v) VALUES ('schema', ?)", (str(SCHEMA),))
    conn.commit()
    return conn


def read_payload() -> Dict[str, Any]:
    try:
        data = sys.stdin.read()
    except Exception:
        return {}
    try:
        payload = json.loads(data) if data else {}
    except Exception:
        payload = {}
    dump_path = os.environ.get("PLATEAU_DUMP_PAYLOADS")
    if dump_path:
        try:
            os.makedirs(os.path.dirname(dump_path) or ".", exist_ok=True)
            with open(dump_path, "a", encoding="utf-8") as f:
                f.write(data if data else json.dumps(payload))
                f.write("\n")
        except Exception:
            pass
    return payload if isinstance(payload, dict) else {}


def agent_of(payload: Dict[str, Any]) -> str:
    """"main" | "subagent:<name>" | "p" — from the real Claude Code 2.1.x hook payload,
    a subagent's PostToolUse/Stop calls carry `agent_type` (e.g. "general-purpose", the
    Task/Agent tool's `subagent_type`) and `agent_id` (an opaque per-instance hex id);
    neither key is present on the main agent's own calls (see
    docs/harness-0.3/preflight-step3.md for the payload keys as inspected against a
    real subagent run). Order, finalized by docs/harness-0.3/PLAN-step3.md "Amendments
    after preflight run 1" (S3-A3): `agent_type` first, then `agent_id` (a payload can
    carry an id with no type), then `agent_name` (in case a future Claude Code version
    uses that key instead), then env PLATEAU_AGENT (set by plateau.agency for its own
    "p" worker role, outside Claude Code hooks entirely), else "main"."""
    payload = payload or {}
    agent_type = payload.get("agent_type")
    if agent_type:
        return f"subagent:{agent_type}"
    agent_id = payload.get("agent_id")
    if agent_id:
        return f"subagent:{agent_id}"
    agent_name = payload.get("agent_name")
    if agent_name:
        return f"subagent:{agent_name}"
    env = os.environ.get("PLATEAU_AGENT")
    if env:
        return env
    return "main"


_CHILD_ENV_STRIP = (
    "CLAUDECODE", "CLAUDE_CODE_SESSION_ID", "CLAUDE_CODE_REMOTE_SESSION_ID",
    "CLAUDE_AUTOCOMPACT_PCT_OVERRIDE",
)


def child_env() -> Dict[str, str]:
    """`os.environ` minus the Claude-Code-session identity variables (S3-A2,
    docs/harness-0.3/PLAN-step3.md "Amendments after preflight run 1"): every `claude
    -p` this package spawns (`plateau resume`, later shadow probes and `plateau
    propose`) must run in an environment that cannot make the child think it is still
    inside the parent Claude Code session -- otherwise it can inherit the parent's
    session id instead of minting a fresh one, which is exactly what `plateau resume`
    (never `--resume`) depends on. Mirrors the scrubbing `experiments/d038/run_task.py`
    does (sealed reference; never imported). Every other environment variable is kept
    as-is."""
    env = dict(os.environ)
    for k in _CHILD_ENV_STRIP:
        env.pop(k, None)
    return env


def _short(s: Optional[str], n: int) -> str:
    s = (s or "").strip().replace("\n", " ")
    return s if len(s) <= n else s[:n] + "…"


def _resp_text(resp: Any) -> Tuple[str, Optional[int], Optional[bool]]:
    if resp is None:
        return "", None, None
    if isinstance(resp, str):
        return resp, None, None
    if isinstance(resp, dict):
        txt = resp.get("output") or resp.get("stdout") or resp.get("content") or ""
        if isinstance(txt, list):
            txt = " ".join(str(x.get("text", x)) if isinstance(x, dict) else str(x) for x in txt)
        err = resp.get("stderr") or ""
        return str(txt) + ("\n" + str(err) if err else ""), resp.get("exitCode"), resp.get("success")
    return str(resp), None, None


def _read_facts_from_text(path: str, text: str) -> List[Tuple[str, str, str]]:
    """Signatures and config keys from a Read of a code file. Returns (path, name, detail)."""
    facts: List[Tuple[str, str, str]] = []
    if not path or not text or not path.endswith(CODE_EXT):
        return facts
    seen: Set[str] = set()
    for name, params in READ_SIG_RE.findall(text):
        if name in seen:
            continue
        seen.add(name)
        facts.append((path, name, _short(params.strip(), 120)))
        if len(facts) >= MAX_READ_FACTS:
            return facts
    for m in READ_CFG_RE.finditer(text):
        name = m.group(1) or m.group(2) or m.group(3)
        if not name or name in seen:
            continue
        seen.add(name)
        facts.append((path, name, "config key"))
        if len(facts) >= MAX_READ_FACTS:
            break
    return facts[:MAX_READ_FACTS]


def _grep_read_facts(pattern: str, text: str) -> List[Tuple[str, str, str]]:
    """The first `path:line` hit of a Grep result. Returns (path, pattern, "line N")."""
    m = READ_GREP_RE.search(text or "")
    if not m:
        return []
    return [(m.group(1), pattern, f"line {m.group(2)}")]


def classify(tool: str, tool_input: Any, tool_response: Any) -> tuple:
    """Return (kind, target, outcome, detail, symbols, error, read_facts).

    read_facts is a list of (path, name, detail) triples, each becoming a `read` node
    keyed `read:<relpath>:<name>` once `record()` resolves `path` against the store root.
    """
    tin = tool_input or {}
    text, code, ok = _resp_text(tool_response)
    symbols: List[str] = []
    error: Optional[str] = None
    read_facts: List[Tuple[str, str, str]] = []

    if tool in ("Read", "NotebookRead"):
        target = tin.get("file_path") or tin.get("notebook_path") or "?"
        read_facts = _read_facts_from_text(target, text)
        return "file", target, "read", "", symbols, None, read_facts

    if tool in ("Edit", "Write", "MultiEdit", "NotebookEdit"):
        src = tin.get("new_string") or tin.get("content") or " ".join(
            e.get("new_string", "") for e in tin.get("edits", [])
        )
        symbols = [a or b for a, b in SYM_RE.findall(src or "")]
        target = tin.get("file_path") or tin.get("notebook_path") or "?"
        return "file", target, "edit", ", ".join(symbols[:6]), symbols, None, read_facts

    if tool == "Bash":
        cmd = _short(tin.get("command", ""), 120)
        failed = (code not in (None, 0)) or (ok is False) or bool(re.search(r"\bFAILED\b|Traceback|\d+ failed", text))
        m = ERR_RE.search(text)
        if failed and m:
            error = _short(m.group(0), 160)
        kind = "test" if re.search(r"pytest|unittest|npm test|cargo test|go test", cmd) else "command"
        return kind, cmd, ("fail" if failed else "pass"), (error or ""), symbols, error, read_facts

    if tool in ("Grep", "Glob"):
        pattern = _short(tin.get("pattern", "?"), 80)
        if tool == "Grep":
            read_facts = _grep_read_facts(pattern, text)
        return "search", pattern, "read", "", symbols, None, read_facts

    return "tool", tool, "ok", "", symbols, None, read_facts


def _relpath(root_dir: str, path: Optional[str]) -> Optional[str]:
    if not path or not root_dir:
        return path
    if path.startswith(root_dir):
        return os.path.relpath(path, root_dir)
    return path


def record(
    conn: sqlite3.Connection,
    tool: str,
    tool_input: Any,
    tool_response: Any,
    *,
    session_id: str,
    agent: str,
    bridge_version: str,
    bridge_sha: str,
    root: str,
    ts: Optional[float] = None,
) -> int:
    """Insert one receipt (+ its nodes/edges) for a single tool call. Returns the receipt id."""
    kind, target, outcome, detail, symbols, error, read_facts = classify(tool, tool_input, tool_response)
    ts = time.time() if ts is None else ts

    measure_kind: Optional[str] = None
    measure_value: Optional[str] = None
    if kind == "file" and target and target != "?":
        target = _relpath(root, target)
        full = target if os.path.isabs(target) else os.path.join(root, target)
        if os.path.isfile(full):
            try:
                measure_value = file_hash(full)
                measure_kind = "file_hash"
            except OSError:
                measure_value = measure_kind = None

    cur = conn.execute(
        "INSERT INTO receipts(ts,session_id,agent,bridge_version,bridge_sha,tool,target,kind,outcome,detail,"
        "measure_kind,measure_value) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
        (ts, session_id, agent, bridge_version, bridge_sha, tool, target, kind, outcome, detail,
         measure_kind, measure_value),
    )
    rid = cur.lastrowid

    def touch(key: str, node_kind: str, out: str, det: str = "") -> None:
        conn.execute(
            """INSERT INTO nodes(key,kind,first_rid,last_rid,degree,last_outcome,last_detail,session_id,agent)
               VALUES(?,?,?,?,1,?,?,?,?)
               ON CONFLICT(key) DO UPDATE SET
                 last_rid=excluded.last_rid, degree=degree+1,
                 last_outcome=excluded.last_outcome, last_detail=excluded.last_detail,
                 session_id=excluded.session_id, agent=excluded.agent""",
            (key, node_kind, rid, rid, out, det, session_id, agent),
        )

    touch(target, kind, outcome, detail)
    conn.execute("INSERT INTO edges(src,rel,dst,rid) VALUES(?,?,?,?)", (target, outcome, f"r{rid}", rid))

    for s in symbols:
        touch(s, "symbol", "defined", target)
        conn.execute("INSERT INTO edges(src,rel,dst,rid) VALUES(?,?,?,?)", (target, "defines", s, rid))

    if error:
        touch(error, "error", "seen", target)
        conn.execute("INSERT INTO edges(src,rel,dst,rid) VALUES(?,?,?,?)", (target, "fails_with", error, rid))

    for path, name, fdetail in read_facts:
        rel = _relpath(root, path)
        key = f"read:{rel}:{name}"
        touch(key, "read", "found", fdetail)
        conn.execute("INSERT INTO edges(src,rel,dst,rid) VALUES(?,?,?,?)", (target, "reveals", key, rid))

    conn.commit()
    return rid


def rebuild_from_transcript(conn: sqlite3.Connection, transcript_path: str, **prov: Any) -> int:
    """Replay a transcript JSONL's tool_use/tool_result pairs through `record()`, in
    order (tool blocks only — prose never becomes a node). `prov` supplies `record`'s
    keyword-only provenance (session_id, agent, bridge_version, bridge_sha, root).
    Returns the number of tool calls replayed."""
    uses: Dict[str, Tuple[str, Any]] = {}
    results: Dict[str, Any] = {}
    order: List[str] = []
    with open(transcript_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                j = json.loads(line)
            except Exception:
                continue
            msg = j.get("message") or {}
            content = msg.get("content")
            if not isinstance(content, list):
                continue
            for b in content:
                if not isinstance(b, dict):
                    continue
                if b.get("type") == "tool_use":
                    uid = b.get("id")
                    uses[uid] = (b.get("name"), b.get("input"))
                    order.append(uid)
                elif b.get("type") == "tool_result":
                    results[b.get("tool_use_id")] = j.get("toolUseResult", b.get("content"))
    n = 0
    for uid in order:
        tool, tin = uses[uid]
        record(conn, tool, tin, results.get(uid), **prov)
        n += 1
    return n


def measurements(conn: sqlite3.Connection, session_id: str) -> List[Tuple[str, Measurement]]:
    """(claim, Measurement) for every file node's most recent hash, for this session."""
    rows = conn.execute(
        """SELECT n.key, r.measure_kind, r.measure_value
           FROM nodes n JOIN receipts r ON r.id = n.last_rid
           WHERE n.kind = 'file' AND n.session_id = ? AND r.measure_value IS NOT NULL""",
        (session_id,),
    ).fetchall()
    out: List[Tuple[str, Measurement]] = []
    for key, measure_kind, measure_value in rows:
        claim = f"{key} hashed to {measure_value}"
        out.append((claim, Measurement(kind=measure_kind, source=key, value=measure_value)))
    return out


def mark_compaction(conn: sqlite3.Connection, session_id: str, snapshot_path: str) -> int:
    """Record a new compaction event for the session (0-indexed). Returns its k."""
    row = conn.execute("SELECT MAX(k) FROM compactions WHERE session_id=?", (session_id,)).fetchone()
    k = (row[0] + 1) if row and row[0] is not None else 0
    rid_at = conn.execute("SELECT COALESCE(MAX(id),0) FROM receipts").fetchone()[0]
    conn.execute(
        "INSERT INTO compactions(session_id,k,ts,rid_at,snapshot) VALUES(?,?,?,?,?)",
        (session_id, k, time.time(), rid_at, snapshot_path),
    )
    conn.commit()
    return k


def prev_compaction_rid(conn: sqlite3.Connection, session_id: str) -> Optional[int]:
    """The rid_at boundary of the compaction BEFORE the session's most recent one --
    the single definition of "older than the previous compaction" (PLAN.md 'Selector
    v2'; used by both plateau.bridge.query.score_nodes and plateau.bridge.inject).

    On a `compact` SessionStart, snapshot.py's PreCompact hook has ALREADY inserted the
    row for the compaction currently being handled (PreCompact always fires before
    SessionStart) -- so the session's newest `compactions` row is not "the previous
    compaction", it is "this one". We detect that case generically (no dependency on
    the caller's event name): if the newest row's rid_at is >= the session's current
    MAX(receipts.id), it was marked with no receipt recorded since, i.e. it is that
    just-inserted current-compaction row, and the boundary is the SECOND newest row's
    rid_at instead. Otherwise the newest row already IS the previous compaction (no
    compaction is pending right now), and its own rid_at is the boundary. None when no
    row qualifies (no compactions at all, or the only row is the just-inserted one)."""
    rows = conn.execute(
        "SELECT k, rid_at FROM compactions WHERE session_id=? ORDER BY k DESC LIMIT 2",
        (session_id,),
    ).fetchall()
    if not rows:
        return None
    max_rid = conn.execute(
        "SELECT COALESCE(MAX(id), 0) FROM receipts WHERE session_id=?", (session_id,)
    ).fetchone()[0]
    newest_rid_at = rows[0][1]
    if newest_rid_at >= max_rid:
        return rows[1][1] if len(rows) > 1 else None
    return newest_rid_at


def mark_turn(conn: sqlite3.Connection, session_id: str) -> int:
    """Record a new turn boundary for the session (1-indexed). Returns its n."""
    row = conn.execute("SELECT MAX(n) FROM turns WHERE session_id=?", (session_id,)).fetchone()
    n = (row[0] + 1) if row and row[0] is not None else 1
    rid_at = conn.execute("SELECT COALESCE(MAX(id),0) FROM receipts").fetchone()[0]
    conn.execute(
        "INSERT INTO turns(session_id,n,ts,rid_at) VALUES(?,?,?,?)",
        (session_id, n, time.time(), rid_at),
    )
    conn.commit()
    return n


def receipts_per_turn(conn: sqlite3.Connection, session_id: str) -> float:
    """receipts / max(turns, 1) for the session; 30.0 if no turns are recorded yet."""
    n_turns = conn.execute("SELECT COUNT(*) FROM turns WHERE session_id=?", (session_id,)).fetchone()[0]
    if not n_turns:
        return 30.0
    n_receipts = conn.execute("SELECT COUNT(*) FROM receipts WHERE session_id=?", (session_id,)).fetchone()[0]
    return n_receipts / max(n_turns, 1)


def record_decision(conn: sqlite3.Connection, session_id: str, agent: str, text: str, provenance: str) -> int:
    """Insert a `decisions` row and its `decided:<id>` node. Returns the decision id."""
    ts = time.time()
    cur = conn.execute(
        "INSERT INTO decisions(ts,session_id,agent,text,provenance) VALUES(?,?,?,?,?)",
        (ts, session_id, agent, text, provenance),
    )
    did = cur.lastrowid
    rid = conn.execute("SELECT COALESCE(MAX(id),0) FROM receipts").fetchone()[0]
    key = f"decided:{did}"
    conn.execute(
        """INSERT INTO nodes(key,kind,first_rid,last_rid,degree,last_outcome,last_detail,session_id,agent)
           VALUES(?,?,?,?,1,?,?,?,?)
           ON CONFLICT(key) DO UPDATE SET
             last_rid=excluded.last_rid, degree=degree+1,
             last_outcome=excluded.last_outcome, last_detail=excluded.last_detail,
             session_id=excluded.session_id, agent=excluded.agent""",
        (key, "decided", rid, rid, "decided", _short(text, 160), session_id, agent),
    )
    conn.commit()
    return did
