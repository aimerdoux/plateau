"""D-037 shared store: receipts -> bounded graph. stdlib only."""
import json, os, re, sqlite3, sys, time

DB_REL = ".d037/index.sqlite"
LOG_REL = ".d037/hooks.log"
SYM_RE = re.compile(r"^(?:def|class)\s+([A-Za-z_]\w*)|^([A-Z][A-Z0-9_]{2,})\s*=", re.M)
ERR_RE = re.compile(r"^(Traceback|.*Error\b.*|.*FAILED.*|.*Exception\b.*)$", re.M)

def root(payload):
    r = payload.get("cwd") or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    return r

def log(r, msg):
    p = os.path.join(r, LOG_REL); os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "a") as f: f.write(f"{time.time():.3f} {msg}\n")

def db(r):
    p = os.path.join(r, DB_REL); os.makedirs(os.path.dirname(p), exist_ok=True)
    c = sqlite3.connect(p, timeout=5)
    c.executescript("""
    CREATE TABLE IF NOT EXISTS receipts(id INTEGER PRIMARY KEY, ts REAL, tool TEXT, target TEXT,
        kind TEXT, outcome TEXT, detail TEXT);
    CREATE TABLE IF NOT EXISTS nodes(key TEXT PRIMARY KEY, kind TEXT, first_rid INTEGER,
        last_rid INTEGER, degree INTEGER DEFAULT 0, last_outcome TEXT, last_detail TEXT);
    CREATE TABLE IF NOT EXISTS edges(src TEXT, rel TEXT, dst TEXT, rid INTEGER);
    CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY, v TEXT);
    """)
    return c

def _short(s, n): 
    s = (s or "").strip().replace("\n", " ")
    return s if len(s) <= n else s[:n] + "…"

def _resp_text(resp):
    if resp is None: return "", None, None
    if isinstance(resp, str): return resp, None, None
    if isinstance(resp, dict):
        txt = resp.get("output") or resp.get("stdout") or resp.get("content") or ""
        if isinstance(txt, list): txt = " ".join(str(x.get("text", x)) if isinstance(x, dict) else str(x) for x in txt)
        err = resp.get("stderr") or ""
        return str(txt) + ("\n" + str(err) if err else ""), resp.get("exitCode"), resp.get("success")
    return str(resp), None, None

def classify(tool, tin, resp):
    """Return (kind, target, outcome, detail, symbols, error)."""
    tin = tin or {}
    text, code, ok = _resp_text(resp)
    symbols, error = [], None
    if tool in ("Read", "NotebookRead"):
        return "file", tin.get("file_path") or tin.get("notebook_path") or "?", "read", "", symbols, None
    if tool in ("Edit", "Write", "MultiEdit", "NotebookEdit"):
        src = tin.get("new_string") or tin.get("content") or " ".join(e.get("new_string", "") for e in tin.get("edits", []))
        symbols = [a or b for a, b in SYM_RE.findall(src or "")]
        return "file", tin.get("file_path") or tin.get("notebook_path") or "?", "edit", ", ".join(symbols[:6]), symbols, None
    if tool == "Bash":
        cmd = _short(tin.get("command", ""), 120)
        failed = (code not in (None, 0)) or (ok is False) or bool(re.search(r"\bFAILED\b|Traceback|\d+ failed", text))
        m = ERR_RE.search(text)
        if failed and m: error = _short(m.group(0), 160)
        kind = "test" if re.search(r"pytest|unittest|npm test|cargo test|go test", cmd) else "command"
        return kind, cmd, ("fail" if failed else "pass"), (error or ""), symbols, error
    if tool in ("Grep", "Glob"):
        return "search", _short(tin.get("pattern", "?"), 80), "read", "", symbols, None
    return "tool", tool, "ok", "", symbols, None

def record(c, tool, tin, resp, ts=None):
    kind, target, outcome, detail, symbols, error = classify(tool, tin, resp)
    ts = ts or time.time()
    cur = c.execute("INSERT INTO receipts(ts,tool,target,kind,outcome,detail) VALUES(?,?,?,?,?,?)",
                    (ts, tool, target, kind, outcome, detail))
    rid = cur.lastrowid
    def touch(key, k, out, det=""):
        c.execute("""INSERT INTO nodes(key,kind,first_rid,last_rid,degree,last_outcome,last_detail)
                     VALUES(?,?,?,?,1,?,?) ON CONFLICT(key) DO UPDATE SET last_rid=excluded.last_rid,
                     degree=degree+1, last_outcome=excluded.last_outcome, last_detail=excluded.last_detail""",
                  (key, k, rid, rid, out, det))
    touch(target, kind, outcome, detail)
    c.execute("INSERT INTO edges VALUES(?,?,?,?)", (target, outcome, f"r{rid}", rid))
    for s in symbols:
        touch(s, "symbol", "defined", target)
        c.execute("INSERT INTO edges VALUES(?,?,?,?)", (target, "defines", s, rid))
    if error:
        touch(error, "error", "seen", target)
        c.execute("INSERT INTO edges VALUES(?,?,?,?)", (target, "fails_with", error, rid))
    c.commit()
    return rid

def read_payload():
    try: return json.load(sys.stdin)
    except Exception: return {}
