"""tests/test_carry.py — 0.4 section 2: the carry rule (docs/toy/continuum-toy.html).

Covers `plateau.bridge.carry`: the pure rule (`cutoff`, `ancestors`, `carry`) replayed
against the toy's exported ground truth (tests/fixtures/continuum_toy.json, both arms,
requests 1..8), the two literal contract cases (continuum request 8 carries
d1/e1/f1/f2; truncated request 8 reaches 0/4), the edge cases (cycles, unknown ids,
empty graph, carrying off, window / turn below 1, self and duplicate edges, generator
inputs), and the store part (`turn_of_rid`, `graph_from_store`, `carry_from_store`)
over a 3-turn session built with the real `common` API, extended by a decision lifted
at its Stop and by another session's receipt that must not enter `now`.
"""

from __future__ import annotations

import json
import os

import pytest

from plateau.bridge import common
from plateau.bridge.carry import Node, ancestors, carry, carry_from_store, cutoff, graph_from_store, turn_of_rid

_FIXTURE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "continuum_toy.json")

with open(_FIXTURE, encoding="utf-8") as _f:
    TOY = json.load(_f)

ARMS = ("truncated", "continuum")


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _arm_graph(arm):
    """The toy's `present()`: truncated_only nodes exist only in mode T."""
    nodes = {
        n["id"]: Node(n["id"], n["kind"], n["turn"])
        for n in TOY["nodes"] if arm == "truncated" or not n["truncated_only"]
    }
    edges = [(e["src"], e["dst"]) for e in TOY["edges"]]
    return nodes, edges


def _start(t):
    """The request's own nodes at turn t -- never the re-derived ones."""
    return [n["id"] for n in TOY["nodes"] if n["turn"] == t and not n["truncated_only"]]


def _toy_carry(arm, t):
    nodes, edges = _arm_graph(arm)
    return carry(nodes, edges, t, TOY["window_requests"], knowledge=set(TOY["knowledge_kinds"]),
                 carrying=(arm == "continuum"), start=_start(t))


def _record(conn, root, tool, tin, resp, uid=None, session_id="s1"):
    return common.record(conn, tool, tin, resp, session_id=session_id, agent="main",
                         bridge_version="v", bridge_sha="sha", root=root, tool_use_id=uid)


# ---------------------------------------------------------------------------
# the fixture, verbatim: every request in both arms
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("arm,t", [(arm, t) for arm in ARMS for t in range(1, 9)])
def test_toy_ground_truth(arm, t):
    exp = TOY["expected"][arm][str(t)]
    c = _toy_carry(arm, t)
    assert c.reachable == exp["reachable"]
    assert c.carried == exp["carried"]
    assert c.cutoff == exp["window_cutoff"]
    nodes, _ = _arm_graph(arm)
    rederived = sum(1 for n in TOY["nodes"] if n["truncated_only"] and n["turn"] <= t and n["id"] in nodes)
    assert rederived == exp["rederived_actions"]
    # the same count out of carry() itself: the re-derived nodes of turn t are in `now`
    # (the toy's `now`) in the truncated arm and absent in the continuum arm
    in_now = [n["id"] for n in TOY["nodes"] if n["truncated_only"] and n["turn"] == t and n["id"] in c.now]
    assert len(in_now) == (exp["rederived_actions"] if arm == "truncated" else 0)


def test_continuum_request_8_carries_the_four_reasons_it_descends_from():
    assert TOY["expected"]["continuum"]["8"]["carried"] == ["d1", "e1", "f1", "f2"]
    assert _toy_carry("continuum", 8).carried == ["d1", "e1", "f1", "f2"]


def test_truncated_request_8_reaches_none_of_its_old_reasons():
    assert TOY["expected"]["truncated"]["8"]["reachable"] == "0/4"
    assert _toy_carry("truncated", 8).reachable == "0/4"


# ---------------------------------------------------------------------------
# the pure rule: edges of the rule
# ---------------------------------------------------------------------------

def test_ancestors_terminates_on_a_cycle_and_returns_both():
    assert ancestors(["a"], {"a": ["b"], "b": ["a"]}) == {"a", "b"}


def test_edges_naming_unknown_ids_are_ignored():
    nodes = {"x": Node("x", "fact", 1), "a": Node("a", "act", 2)}
    c = carry(nodes, [("ghost", "a"), ("x", "a"), ("a", "phantom")], 2, 1, knowledge={"fact"})
    assert c.need == {"x"}
    assert c.carried == ["x"]
    assert c.reachable == "1/1"


def test_carry_on_empty_graph():
    c = carry({}, [], 3, 2, knowledge={"fact"})
    assert c.reachable == "—"
    assert c.need == set()
    assert c.carried == []
    assert c.now == []


def test_carrying_false_never_carries():
    nodes = {"x": Node("x", "fact", 1), "a": Node("a", "act", 5)}
    c = carry(nodes, [("x", "a")], 5, 1, knowledge={"fact"}, carrying=False)
    assert c.need == {"x"}
    assert c.carried == []
    assert c.old == ["x"]
    assert c.reachable == "0/1"


def test_window_and_turn_below_1_are_rejected():
    nodes = {"x": Node("x", "fact", 5), "a": Node("a", "act", 5)}
    with pytest.raises(ValueError):
        cutoff(5, 0)
    with pytest.raises(ValueError):
        carry(nodes, [("x", "a")], 5, -3, knowledge={"fact"})       # would make x "old" at its own turn
    with pytest.raises(ValueError):
        carry(nodes, [("x", "a")], 0, 1, knowledge={"fact"})
    assert cutoff(5, 1) == 5 and cutoff(1, 4) == 1


def test_self_edge_and_duplicate_edges_are_harmless():
    nodes = {"x": Node("x", "fact", 1), "a": Node("a", "act", 2)}
    c = carry(nodes, [("x", "a"), ("x", "a"), ("a", "a"), ("x", "x")], 2, 1, knowledge={"fact"})
    assert c.need == {"x"} and c.carried == ["x"] and c.reachable == "1/1"
    assert ancestors(["a"], {"a": ["a"]}) == {"a"}                  # a self-edge reaches its own start


def test_edges_and_start_may_be_generators():
    nodes = {"x": Node("x", "fact", 1), "q": Node("q", "req", 2), "a": Node("a", "act", 2)}
    c = carry(nodes, ((s, d) for s, d in [("q", "a"), ("x", "a")]), 2, 1, knowledge={"fact"},
              start=(s for s in ["a"]))
    assert c.now == ["a", "q"] and c.need == {"x"} and c.carried == ["x"]


def test_turn_of_rid():
    assert [turn_of_rid([3, 7], r) for r in (1, 3, 4, 7, 8)] == [1, 1, 2, 2, 3]
    assert [turn_of_rid([], r) for r in (1, 5, 99)] == [1, 1, 1]
    assert turn_of_rid([3, 3], 4) == 3


# ---------------------------------------------------------------------------
# the store part: a 3-turn session through the real API
# ---------------------------------------------------------------------------

ERR = "TimeoutError in payment.charge"
READ = "read:payment/client.py:charge"


def _three_turn_session(tmp_path):
    root = str(tmp_path)
    conn = common.db(root)
    # turn 1: the failing test run -> error node
    r1 = _record(conn, root, "Bash", {"command": "pytest tests/test_checkout.py"},
                 {"stdout": ERR, "exitCode": 1}, uid="tu1")
    common.mark_turn(conn, "s1")
    # turn 2: the read taken because of it -> read fact
    r2 = _record(conn, root, "Read", {"file_path": "payment/client.py"},
                 {"file": {"content": "def charge(amount, retries=0, timeout=2):\n    pass\n"}}, uid="tu2")
    linked = common.record_reason(conn, r2, "s1", "tu2", "the TimeoutError in payment.charge points at the payment client")
    assert linked == [ERR]
    common.mark_turn(conn, "s1")
    # turn 3 (open): the passing rerun, because of what the read showed
    r3 = _record(conn, root, "Bash", {"command": "pytest"}, {"stdout": "3 passed", "exitCode": 0}, uid="tu3")
    linked = common.record_reason(conn, r3, "s1", "tu3", "charge retries timeout")
    assert READ in linked
    return conn, (r1, r2, r3)


def test_graph_from_store_turns_and_edges(tmp_path):
    conn, (r1, r2, r3) = _three_turn_session(tmp_path)
    nodes, edges, current = graph_from_store(conn, "s1")
    assert current == 3
    assert nodes[f"r{r1}"].turn == 1 and nodes[f"r{r1}"].kind == "act"
    assert nodes[ERR].turn == 1 and nodes[ERR].kind == "error"
    assert nodes[f"r{r2}"].turn == 2
    assert nodes[READ].turn == 2 and nodes[READ].kind == "read"
    assert nodes[f"r{r3}"].turn == 3
    assert (ERR, f"r{r2}") in edges          # because: the read was taken because of the error
    assert (f"r{r2}", READ) in edges         # provenance: the read produced the fact
    assert (READ, f"r{r3}") in edges         # because: the rerun cites the fact
    # footprints (the file / command targets) never enter the graph
    assert not any(k in nodes for k in ("payment/client.py", "pytest"))


def test_carry_from_store_at_the_open_turn(tmp_path):
    conn, _ = _three_turn_session(tmp_path)
    c = carry_from_store(conn, "s1", window=1)
    assert c.turn == 3 and c.cutoff == 3
    assert c.carried == sorted([ERR, READ])
    assert c.reachable == "2/2"
    wide = carry_from_store(conn, "s1", window=3)
    assert wide.cutoff == 1
    assert wide.carried == []
    assert wide.reachable == "all"


def test_another_sessions_receipts_sit_at_turn_0_and_never_reach_now(tmp_path):
    """s2's receipt lands in s1's open-turn rid range; it and the error it lifted are in
    the graph at turn 0 (walkable), not in s1's `now`, and never in `need` unless s1's
    request descends from them."""
    conn, (_r1, _r2, r3) = _three_turn_session(tmp_path)
    root = str(tmp_path)
    r_other = _record(conn, root, "Bash", {"command": "pytest"}, {"stdout": "KeyError other", "exitCode": 1},
                      uid="tu9", session_id="s2")
    nodes, edges, current = graph_from_store(conn, "s1")
    assert current == 3
    assert nodes[f"r{r_other}"].turn == 0 and nodes["KeyError other"].turn == 0
    assert (f"r{r_other}", "KeyError other") in edges
    c = carry_from_store(conn, "s1", window=1)
    assert c.now == [f"r{r3}"]
    assert c.need == {ERR, READ} and c.carried == sorted([ERR, READ])


def test_carry_from_store_with_a_decision(tmp_path):
    """The toy's `dec` kind through the real API: a decision lifted at a Stop descends
    from the error it cites (`f1 -> d1` in the toy's shape) and is carried like a fact
    once the turn that made it leaves the window."""
    conn, (r1, r2, r3) = _three_turn_session(tmp_path)
    common.mark_turn(conn, "s1")                                     # Stop of turn 3
    did = common.record_decision(conn, "s1", "main", "charge with retries=2 and a timeout", "t.jsonl:9")
    dec = f"decided:{did}"
    assert (READ, "because", dec) in {(s, r, d) for s, r, d in conn.execute("SELECT src, rel, dst FROM edges")}
    r4 = _record(conn, str(tmp_path), "Edit", {"file_path": "payment/client.py", "new_string": "retries=2"},
                 {"success": True}, uid="tu4")
    assert common.record_reason(conn, r4, "s1", "tu4", "apply the decided retries") == [dec]
    nodes, edges, current = graph_from_store(conn, "s1")
    assert current == 4
    assert nodes[dec].kind == "decided" and nodes[dec].turn == 3
    assert (READ, dec) in edges and (dec, f"r{r4}") in edges
    c = carry_from_store(conn, "s1", window=1)
    assert c.now == [f"r{r4}"]
    assert c.need == {dec, READ, ERR}
    assert c.carried == sorted([dec, READ, ERR]) and c.reachable == "3/3"
    wide = carry_from_store(conn, "s1", window=2)                    # turn 3 is back in: only e1 / f1 are old
    assert wide.carried == sorted([ERR, READ]) and wide.reachable == "2/2"
