"""plateau.agency.graph — a relational index over the receipts the control loop already writes.

The control loop's evidence diet is flattened tails: the planner sees `RECALIBRATE.md[-3000:]`,
verify keeps `output_tail[-1][:80]`, and nothing ever reads gate artifacts *across* tasks. So
relational structure — "T4's artifact contradicts T9's assumption", "this error signature
recurred in three unrelated gates", "the same gate failed 16 times with a *changing* error" —
has nowhere to live. This module gives it a home.

`ingest` is a **pure, idempotent fold** over PLAN.md / FORECAST.md / JOURNAL.md / gates/*.json
into a SQLite graph at `.plateau/control/graph.db`. Re-running it on unchanged inputs yields a
byte-identical graph. It is READ-ONLY over the loop's authority in the sense that matters:

  * Nothing in the graph is ever executed. Rows are derived DATA. A gate command stored on a
    Gate node is a string, never run from here — same trust boundary as `signal.Measurement`.
  * The graph never admits a fact into the signal. Admission still happens only through the
    gate. The graph *observes*; it does not *decide*.

Nodes:  Mission Task Gate Artifact Forecast Gap Anomaly Hypothesis Blocker Worker Path
Edges:  decomposes tests produced forecast_of touches contradicts explains discriminates
        spawned_by

`detect` runs deterministic SURPRISE detectors over the folded graph and emits `Anomaly`
nodes — no LLM. That is the first-class representation F3 says is missing; routing an anomaly
to an abductive worker is a separate, budgeted, prereg-gated step (not in this module).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3

from plateau.agency import adapt as A
from plateau.agency import control as C

_SCHEMA = """
CREATE TABLE IF NOT EXISTS nodes (
    id   TEXT PRIMARY KEY,   -- "<kind>:<key>"
    kind TEXT NOT NULL,
    key  TEXT NOT NULL,
    data TEXT NOT NULL,      -- JSON, sorted keys (idempotent)
    ts   TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS edges (
    src  TEXT NOT NULL,
    rel  TEXT NOT NULL,
    dst  TEXT NOT NULL,
    data TEXT NOT NULL DEFAULT '{}',
    PRIMARY KEY (src, rel, dst)
);
CREATE INDEX IF NOT EXISTS idx_edges_src ON edges(src);
CREATE INDEX IF NOT EXISTS idx_edges_dst ON edges(dst);
CREATE INDEX IF NOT EXISTS idx_nodes_kind ON nodes(kind);
"""

# How many consecutive REFUTED journal lines for one task counts as thrash (the 16-worker
# burn). 3 == the default retry budget: a task that hits its budget is by definition thrash.
THRASH_THRESHOLD = 3


def _nid(kind: str, key: str) -> str:
    return f"{kind}:{key}"


def _dumps(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


class Graph:
    def __init__(self, path: str):
        self.path = path
        self.db = sqlite3.connect(path)
        self.db.executescript(_SCHEMA)
        self.db.commit()

    def close(self):
        self.db.close()

    # -- writes are upserts, so ingest is idempotent -----------------------
    def put_node(self, kind: str, key: str, data: dict, ts: str = "") -> str:
        nid = _nid(kind, key)
        self.db.execute(
            "INSERT INTO nodes(id,kind,key,data,ts) VALUES(?,?,?,?,?) "
            "ON CONFLICT(id) DO UPDATE SET data=excluded.data, ts=excluded.ts",
            (nid, kind, key, _dumps(data), ts))
        return nid

    def put_edge(self, src: str, rel: str, dst: str, data: dict | None = None) -> None:
        self.db.execute(
            "INSERT INTO edges(src,rel,dst,data) VALUES(?,?,?,?) "
            "ON CONFLICT(src,rel,dst) DO UPDATE SET data=excluded.data",
            (src, rel, dst, _dumps(data or {})))

    # -- reads -------------------------------------------------------------
    def node(self, nid: str) -> dict | None:
        r = self.db.execute("SELECT id,kind,key,data,ts FROM nodes WHERE id=?", (nid,)).fetchone()
        if not r:
            return None
        return {"id": r[0], "kind": r[1], "key": r[2], "data": json.loads(r[3]), "ts": r[4]}

    def nodes_of(self, kind: str) -> list:
        rows = self.db.execute("SELECT id FROM nodes WHERE kind=? ORDER BY id", (kind,)).fetchall()
        return [self.node(r[0]) for r in rows]

    def neighbors(self, nid: str) -> dict:
        out = {"out": [], "in": []}
        for s, rel, d in self.db.execute(
                "SELECT src,rel,dst FROM edges WHERE src=? ORDER BY rel,dst", (nid,)):
            out["out"].append({"rel": rel, "dst": d})
        for s, rel, d in self.db.execute(
                "SELECT src,rel,dst FROM edges WHERE dst=? ORDER BY rel,src", (nid,)):
            out["in"].append({"rel": rel, "src": s})
        return out

    def provenance(self, nid: str, max_hops: int = 8) -> list:
        """Walk INBOUND edges from a node back toward the mission — the 'why does this exist'
        chain. Deterministic BFS, capped, cycle-safe."""
        seen, order, frontier, hops = {nid}, [nid], [nid], 0
        while frontier and hops < max_hops:
            nxt = []
            for cur in frontier:
                for s, rel, d in self.db.execute(
                        "SELECT src,rel,dst FROM edges WHERE dst=? ORDER BY src", (cur,)):
                    if s not in seen:
                        seen.add(s); order.append(s); nxt.append(s)
            frontier, hops = nxt, hops + 1
        return order

    def khop(self, nid: str, k: int = 1) -> set:
        """The k-hop neighborhood id set (both directions) — the structural analogue of the
        bounded signal: a worker gets THIS, not the whole graph."""
        seen, frontier = {nid}, {nid}
        for _ in range(k):
            nxt = set()
            for cur in frontier:
                n = self.neighbors(cur)
                nxt |= {e["dst"] for e in n["out"]} | {e["src"] for e in n["in"]}
            frontier = nxt - seen
            seen |= nxt
        return seen

    def commit(self):
        self.db.commit()


def _norm_error(text: str) -> str:
    """A stable signature for an error line: strip digits/paths/hex so the same failure from
    two gates hashes alike (novelty/recurrence detection)."""
    t = (text or "").strip().splitlines()[-1:] or [""]
    s = t[0].lower()
    s = re.sub(r"0x[0-9a-f]+|[0-9a-f]{7,}", "", s)      # hashes/addresses
    s = re.sub(r"/[^\s:]+", "", s)                       # paths
    s = re.sub(r"\d+", "", s)                            # counts, line numbers
    return re.sub(r"\s+", " ", s).strip()[:120]


def ingest(control_dir: str) -> dict:
    """Fold the on-disk receipts into the graph. Pure and idempotent: no wall-clock is
    stamped (timestamps come from the journal), so re-ingesting unchanged inputs is a no-op.
    Returns node/edge counts by kind/rel."""
    g = Graph(os.path.join(control_dir, "graph.db"))
    mission_text = _read_file(os.path.join(control_dir, "TASK.md")).strip()
    m_key = hashlib.sha256(mission_text.encode()).hexdigest()[:12] if mission_text else "none"
    mission = g.put_node("Mission", m_key, {"text": mission_text[:400]})

    tasks = C.parse_plan(_read_file(os.path.join(control_dir, "PLAN.md")))
    forecasts = A.parse_forecast(_read_file(os.path.join(control_dir, "FORECAST.md")))
    gates_dir = os.path.join(control_dir, "gates")

    for t in tasks:
        tnode = g.put_node("Task", t.id, {"action": t.action, "checked": t.checked,
                                          "deliverable": t.deliverable})
        g.put_edge(mission, "decomposes", tnode)
        gnode = g.put_node("Gate", t.id, {"cmd": t.gate, "expect": t.expect})
        g.put_edge(tnode, "tests", gnode)
        for p in sorted(t.touched_paths()):
            pnode = g.put_node("Path", p, {})
            g.put_edge(tnode, "touches", pnode)
        if t.id in forecasts:
            fnode = g.put_node("Forecast", t.id, {"text": forecasts[t.id]})
            g.put_edge(fnode, "forecast_of", tnode)

        art = _load_json(os.path.join(gates_dir, f"{t.id}.gate.json"))
        if art is not None:
            content_hash = hashlib.sha256(_dumps(art).encode()).hexdigest()[:16]
            anode = g.put_node("Artifact", content_hash,
                               {"task": t.id, "exit_code": art.get("exit_code"),
                                "error_sig": _norm_error(art.get("output_tail", "")),
                                "output_tail": (art.get("output_tail") or "")[-200:]})
            g.put_edge(gnode, "produced", anode)
            gap = A.analyze_gap(t.id, forecasts.get(t.id, ""), art)
            gapnode = g.put_node("Gap", t.id, {"class": gap.klass, "note": gap.note})
            g.put_edge(gapnode, "explains", anode)     # gap explains the artifact's outcome

    g.commit()
    counts = _counts(g)
    g.close()
    return counts


def _counts(g: Graph) -> dict:
    kinds = dict(g.db.execute("SELECT kind, COUNT(*) FROM nodes GROUP BY kind").fetchall())
    rels = dict(g.db.execute("SELECT rel, COUNT(*) FROM edges GROUP BY rel").fetchall())
    return {"nodes": kinds, "edges": rels,
            "n_nodes": sum(kinds.values()), "n_edges": sum(rels.values())}


def detect(control_dir: str) -> list:
    """Deterministic SURPRISE detectors -> Anomaly nodes (no LLM). Idempotent: an anomaly's
    id is a stable hash of its evidence, so re-running never duplicates. Returns the anomalies
    as dicts."""
    g = Graph(os.path.join(control_dir, "graph.db"))
    journal = _read_file(os.path.join(control_dir, "JOURNAL.md"))
    anomalies = []

    def emit(kind: str, subject: str, evidence: dict, edge_to: str | None):
        key = hashlib.sha256(f"{kind}|{subject}|{_dumps(evidence)}".encode()).hexdigest()[:16]
        nid = g.put_node("Anomaly", key, {"detector": kind, "subject": subject,
                                          "evidence": evidence, "resolved": False})
        if edge_to and g.node(edge_to):
            g.put_edge(edge_to, "surfaced", nid)
        anomalies.append({"id": nid, "detector": kind, "subject": subject, "evidence": evidence})

    # (1) DRIFT / UNCHECKABLE gaps — the abductive trigger, promoted from a text tail.
    for gap in g.nodes_of("Gap"):
        if gap["data"].get("class") in (A.DRIFT, A.UNCHECKABLE):
            emit("drift", gap["key"], {"class": gap["data"]["class"], "note": gap["data"]["note"]},
                 gap["id"])

    # (2) THRASH — the same task REFUTED/FAILED >= threshold times in the journal. This is the
    # 16-worker burn, scored: a repeatedly-failing gate is a surprise about the GATE, not a
    # task to keep retrying.
    fail_counts: dict = {}
    errors: dict = {}
    for line in journal.splitlines():
        if "GATE FAIL" not in line and "REFUTED" not in line:
            continue
        m = re.search(r"\|\s*([A-Za-z][\w.-]*)\s*\|", line)
        if not m:
            continue
        tid = m.group(1)
        fail_counts[tid] = fail_counts.get(tid, 0) + 1
        errors.setdefault(tid, set()).add(_norm_error(line))
    for tid, n in fail_counts.items():
        if n >= THRASH_THRESHOLD:
            emit("thrash", tid, {"failures": n, "distinct_errors": len(errors[tid]),
                                 "changing_error": len(errors[tid]) > 1}, _nid("Task", tid))

    # (3) RECURRENCE — one normalized error signature across >= 2 DISTINCT tasks' artifacts.
    sig_tasks: dict = {}
    for art in g.nodes_of("Artifact"):
        sig = art["data"].get("error_sig")
        if sig and art["data"].get("exit_code") not in (0, None):
            sig_tasks.setdefault(sig, set()).add(art["data"].get("task"))
    for sig, ts in sig_tasks.items():
        if len(ts) >= 2:
            emit("recurrence", sig, {"tasks": sorted(ts), "signature": sig}, None)

    # (4) CONTRADICTION — one Path touched by >= 2 tasks whose artifacts DISAGREE (at least
    # one gate passed, at least one failed). The shared file has conflicting requirements: a
    # composition surprise no single task's tail reveals. This is the seeded-contradiction
    # detector for D-037's rounds-to-detection metric.
    path_outcomes: dict = {}
    for t in g.nodes_of("Task"):
        for e in g.neighbors(t["id"])["out"]:
            if e["rel"] != "touches":
                continue
            # the artifact for this task, if any
            for a in g.nodes_of("Artifact"):
                if a["data"].get("task") == t["key"]:
                    path_outcomes.setdefault(e["dst"], {}).setdefault(
                        "pass" if a["data"].get("exit_code") == 0 else "fail", set()).add(t["key"])
    for path, outc in path_outcomes.items():
        if outc.get("pass") and outc.get("fail"):
            emit("contradiction", path.split(":", 1)[-1],
                 {"path": path.split(":", 1)[-1], "passed": sorted(outc["pass"]),
                  "failed": sorted(outc["fail"])}, path)

    g.commit()
    g.close()
    return anomalies


def open_anomalies(control_dir: str) -> list:
    """Anomaly nodes not yet marked resolved and with no Hypothesis explaining them — the
    work queue the (future, prereg-gated) abductive step would draw from."""
    g = Graph(os.path.join(control_dir, "graph.db"))
    out = []
    for a in g.nodes_of("Anomaly"):
        if a["data"].get("resolved"):
            continue
        explained = any(e["rel"] == "explains" and g.node(e["src"]) and
                        g.node(e["src"])["kind"] == "Hypothesis"
                        for e in g.neighbors(a["id"])["in"])
        if not explained:
            out.append({"id": a["id"], "detector": a["data"]["detector"],
                        "subject": a["data"]["subject"], "evidence": a["data"]["evidence"]})
    g.close()
    return out


def _read_file(path: str) -> str:
    try:
        with open(path) as fh:
            return fh.read()
    except OSError:
        return ""


def _load_json(path: str):
    try:
        with open(path) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


# ------------------------------------------------------------------- CLI ---
# `python -m plateau.agency.graph {ingest,detect,q}` — read-only navigation over the index,
# safe to poll during a run (nothing here executes a gate). The bounded-signal thesis applied
# to structure: `q khop <id>` is the extract a future abductive worker would receive.


def _cli(argv=None):
    import argparse
    ap = argparse.ArgumentParser(prog="python -m plateau.agency.graph")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("ingest", "detect", "open-anomalies"):
        s = sub.add_parser(name)
        s.add_argument("--control-dir", default=".plateau/control")
    for name, arg in (("neighbors", "node"), ("provenance", "node"),
                      ("khop", "node"), ("touching", "path")):
        s = sub.add_parser(name)
        s.add_argument("--control-dir", default=".plateau/control")
        s.add_argument(arg)
        if name == "khop":
            s.add_argument("-k", type=int, default=1)
    a = ap.parse_args(argv)

    if a.cmd == "ingest":
        print(json.dumps(ingest(a.control_dir), indent=2, sort_keys=True)); return 0
    if a.cmd == "detect":
        print(json.dumps(detect(a.control_dir), indent=2, sort_keys=True)); return 0
    if a.cmd == "open-anomalies":
        print(json.dumps(open_anomalies(a.control_dir), indent=2, sort_keys=True)); return 0

    g = Graph(os.path.join(a.control_dir, "graph.db"))
    try:
        if a.cmd == "neighbors":
            print(json.dumps(g.neighbors(a.node), indent=2, sort_keys=True))
        elif a.cmd == "provenance":
            print(json.dumps([g.node(n) for n in g.provenance(a.node)], indent=2, sort_keys=True))
        elif a.cmd == "khop":
            print(json.dumps(sorted(g.khop(a.node, a.k)), indent=2))
        elif a.cmd == "touching":
            hood = g.khop(_nid("Path", a.path), 1)
            print(json.dumps(sorted(n for n in hood if n.startswith("Task:")), indent=2))
    finally:
        g.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
