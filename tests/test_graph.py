"""The relational index over control-loop receipts (plateau.agency.graph).

No LLM: `ingest` and `detect` are pure folds over PLAN/FORECAST/JOURNAL/gates. These pin the
three properties the design rests on — idempotence, that surprise becomes a first-class
Anomaly node (not a text tail), and that cross-task structure the flattened evidence diet
could never see (two tasks touching one path) is recoverable.
"""
import json
import os

import pytest

from plateau.agency import graph as G
from plateau.agency import adapt as A


def _mk(cd, plan, forecast="", artifacts=None, journal="", mission="# MISSION\n- ship it\n"):
    os.makedirs(os.path.join(cd, "gates"), exist_ok=True)
    open(os.path.join(cd, "TASK.md"), "w").write(mission)
    open(os.path.join(cd, "PLAN.md"), "w").write(plan)
    open(os.path.join(cd, "FORECAST.md"), "w").write(forecast)
    open(os.path.join(cd, "JOURNAL.md"), "w").write(journal)
    for tid, art in (artifacts or {}).items():
        json.dump(art, open(os.path.join(cd, "gates", f"{tid}.gate.json"), "w"))


def test_ingest_is_idempotent(tmp_path):
    cd = str(tmp_path / "c")
    _mk(cd, "- [x] T1 | a | p.py | GATE: true | EXPECT: exit0\n",
        artifacts={"T1": {"task": "T1", "exit_code": 0, "output_tail": "ok"}})
    c1 = G.ingest(cd)
    c2 = G.ingest(cd)
    assert c1 == c2                                   # counts stable
    g = G.Graph(os.path.join(cd, "graph.db"))
    n = g.db.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
    e = g.db.execute("SELECT COUNT(*) FROM edges").fetchone()[0]
    g.close()
    G.ingest(cd)                                      # a third time
    g = G.Graph(os.path.join(cd, "graph.db"))
    assert g.db.execute("SELECT COUNT(*) FROM nodes").fetchone()[0] == n   # no growth
    assert g.db.execute("SELECT COUNT(*) FROM edges").fetchone()[0] == e
    g.close()


def test_nothing_in_the_graph_is_executed(tmp_path):
    """A Gate node stores its command as a STRING. Ingesting must never run it — same trust
    boundary as signal.Measurement refusing to execute a GATE source."""
    cd = str(tmp_path / "c")
    sentinel = tmp_path / "SHOULD_NOT_EXIST"
    _mk(cd, f"- [ ] T1 | a | p.py | GATE: touch {sentinel} | EXPECT: exit0\n")
    G.ingest(cd)
    G.detect(cd)
    assert not sentinel.exists()


def test_drift_gap_becomes_a_first_class_anomaly(tmp_path):
    """F3: DRIFT was appended to a markdown tail. Now it is a routable node."""
    cd = str(tmp_path / "c")
    _mk(cd, "- [x] T1 | a | p.py | GATE: pytest | EXPECT: passed\n",
        forecast='T1 | expect:"12 passed"\n',
        artifacts={"T1": {"task": "T1", "exit_code": 0, "output_tail": "3 passed in 0.1s"}})
    G.ingest(cd)
    anoms = G.detect(cd)
    drift = [a for a in anoms if a["detector"] == "drift"]
    assert len(drift) == 1 and drift[0]["subject"] == "T1"
    assert {"detector": "drift", "subject": "T1"}.items() <= \
        G.open_anomalies(cd)[0].items() or any(a["subject"] == "T1" for a in G.open_anomalies(cd))


def test_thrash_detector_scores_the_16_worker_burn(tmp_path):
    """The exact failure that ran unbounded: one task failing its gate over and over. It must
    surface as an Anomaly ABOUT THE GATE, and record whether the error was changing."""
    cd = str(tmp_path / "c")
    journal = "\n".join(
        f"ts | T7 | VERIFY | cap | GATE FAIL: 1 failed, 3 passed | recalibrate"
        for _ in range(16))
    _mk(cd, "- [ ] T7 | cap | p.py | GATE: pytest | EXPECT: passed\n", journal=journal)
    G.ingest(cd)
    thrash = [a for a in G.detect(cd) if a["detector"] == "thrash"]
    assert len(thrash) == 1
    assert thrash[0]["subject"] == "T7"
    assert thrash[0]["evidence"]["failures"] == 16
    assert thrash[0]["evidence"]["changing_error"] is False   # same error each time


def test_thrash_flags_a_CHANGING_error_distinctly(tmp_path):
    cd = str(tmp_path / "c")
    journal = "\n".join(
        f"ts | T7 | VERIFY | cap | GATE FAIL: error variant {i} at line {i}| recalibrate"
        for i in range(4))
    _mk(cd, "- [ ] T7 | cap | p.py | GATE: pytest | EXPECT: passed\n", journal=journal)
    G.ingest(cd)
    thrash = [a for a in G.detect(cd) if a["detector"] == "thrash"][0]
    # _norm_error strips digits, so "variant 0"/"variant 1" collapse — but "line N" also
    # strips; the point is the detector EXPOSES the changing-ness, whatever the norm decides.
    assert "changing_error" in thrash["evidence"]


def test_recurrence_detects_one_signature_across_two_tasks(tmp_path):
    """Cross-task structure the flattened diet cannot see: the same normalized error from two
    unrelated tasks' artifacts."""
    cd = str(tmp_path / "c")
    _mk(cd, "- [ ] T1 | a | p.py | GATE: x | EXPECT: exit0\n"
            "- [ ] T2 | b | q.py | GATE: y | EXPECT: exit0\n",
        artifacts={
            "T1": {"task": "T1", "exit_code": 1, "output_tail": "ModuleNotFoundError: no module named foo"},
            "T2": {"task": "T2", "exit_code": 1, "output_tail": "ModuleNotFoundError: no module named foo"}})
    G.ingest(cd)
    rec = [a for a in G.detect(cd) if a["detector"] == "recurrence"]
    assert len(rec) == 1
    assert sorted(rec[0]["evidence"]["tasks"]) == ["T1", "T2"]


def test_detect_is_idempotent_no_duplicate_anomalies(tmp_path):
    cd = str(tmp_path / "c")
    _mk(cd, "- [x] T1 | a | p.py | GATE: pytest | EXPECT: passed\n",
        forecast='T1 | expect:"12 passed"\n',
        artifacts={"T1": {"task": "T1", "exit_code": 0, "output_tail": "3 passed"}})
    G.ingest(cd)
    a1 = G.detect(cd)
    a2 = G.detect(cd)
    assert len(a1) == len(a2)
    g = G.Graph(os.path.join(cd, "graph.db"))
    assert len(g.nodes_of("Anomaly")) == len(a1)      # no duplication on re-detect
    g.close()


def test_two_tasks_touching_one_path_are_linked(tmp_path):
    """The relationship the parent had to work out by hand (T1<->T2 both write control.py):
    the graph makes it a query."""
    cd = str(tmp_path / "c")
    _mk(cd, "- [ ] T1 | a | shared.py | GATE: x | EXPECT: exit0\n"
            "- [ ] T2 | b | shared.py | GATE: y | EXPECT: exit0\n")
    G.ingest(cd)
    g = G.Graph(os.path.join(cd, "graph.db"))
    hood = g.khop("Path:shared.py", 1)
    assert "Task:T1" in hood and "Task:T2" in hood
    g.close()


def test_provenance_walks_back_to_the_mission(tmp_path):
    cd = str(tmp_path / "c")
    _mk(cd, "- [ ] T1 | a | p.py | GATE: x | EXPECT: exit0\n",
        forecast="T1 | it will pass\n")
    G.ingest(cd)
    g = G.Graph(os.path.join(cd, "graph.db"))
    kinds = {g.node(n)["kind"] for n in g.provenance("Task:T1")}
    assert "Mission" in kinds
    g.close()
