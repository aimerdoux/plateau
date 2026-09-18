"""tests/test_carry_store.py — 0.4 section 2: the store adapter, mirrored against the toy.

Covers `plateau.bridge.carry.graph_from_store` / `turn_of_rid` / `carry_from_store` by
replaying the toy session (docs/toy/continuum-toy.html, tests/fixtures/continuum_toy.json)
through the REAL store API -- one toy request per turn, `common.record` for every action,
`common.mark_turn` at each Stop, `common.record_decision` after the boundary exactly as
`lift.main` orders it, `common.record_reason` for every `because` arrow -- and comparing
what the store's graph yields with the toy's `expected.continuum`.

The mapping (toy id -> store node):
  a1..a9  act   -> receipt `r<rid>` (Bash / Read / Edit)
  e1, e2  err   -> `error` node lifted from a failing Bash receipt's Error line
  f1..f3  fact  -> `read` node `read:<relpath>:<name>` lifted from a Read of a def
  d1      dec   -> `decided:1` from `record_decision` at turn 4's Stop
  q1, q2  req   -> nothing (the store has no request node)
  p1      pass  -> nothing (a passing run lifts no knowledge node)

Reason texts are chosen so their non-stopword token overlap with the INTENDED knowledge
node is >= `common.REASON_MIN_OVERLAP` and < 2 with every other knowledge node alive at
that moment (`_overlaps()` below prints the arithmetic). Every `because` edge the store
draws is asserted exactly; the toy arrows the store cannot draw are listed, not papered
over: arrows out of a request (`q1 -> a1`, `q2 -> a9`), action-to-action arrows (`a4 ->
a5 "verify the edit"`, `a7 -> a8 "verify"`) -- `_link_because` only starts an edge at a
knowledge node -- and `d1 -> a4 "apply the decision"`: the decision is lifted at Stop,
after the edit it justified, so its `first_rid` is never `< rid` of that edit.

Those gaps are what makes request 5 diverge from the toy (the store has no path from
`a5` back to `a4`), so turn 5 asserts the honest store value (`carried [] / "—"`), not
the toy's (`[e1] / "1/1"`). Requests 1-4 and 6-8 agree with the toy, including the
contract case: at the open request 8 the continuum carries d1, e1, f1, f2 and reaches 4/4.

Also probed: a store with no `turns` rows, duplicate boundaries, a boundary before any
receipt, a node whose `first_rid` predates every boundary, the open turn before its Stop
has lifted any reason, a symbol literally named `r<N>` shadowed by receipt `r<N>`, a
decision lifted at the Stop of a turn with no tool calls landing in that turn (also when
`mark_turn` and `record_decision` share one `ts`, or when another session's receipt lands
between the two), a decision recorded mid-turn after a receipt keeping that turn, `turn=0`
and a negative window rejected, and `window=0` (the compaction) carrying all of `need`.

A second session sharing the store (`plateau resume` is a fresh session id over the same
store): everything it did sits at turn 0 -- its receipts, the knowledge only its receipts
produced, its decisions. Turn 0 is walkable ancestry that is never `now` and never inside
this session's window, so whatever the current request descends from is carried whole:
a fact the other session read, a decision it made WITH the facts beneath it, a fact WITH
the error it was read because of; what the request does not descend from never enters
`need`. A decision's `because` edges survive its cursor being another session's receipt.
`graph_from_store`'s `edges` list is in the store's row order, whatever PYTHONHASHSEED
says.
"""

from __future__ import annotations

import json
import os

import pytest

from plateau.bridge import common
from plateau.bridge.carry import Node, carry_from_store, graph_from_store, turn_of_rid
from plateau.bridge.query import toks

_FIXTURE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "continuum_toy.json")
with open(_FIXTURE, encoding="utf-8") as _f:
    TOY = json.load(_f)

WINDOW = TOY["window_requests"]  # 4

# store keys of the toy's knowledge nodes
E1 = "TimeoutError in payment.charge"
F1 = "read:payment/client.py:charge"
F2 = "read:payment/checkout.py:charge_in_transaction"
D1 = "decided:1"
E2 = "test_refund: KeyError idempotency_key"
F3 = "read:payment/refund.py:refund"

S1 = "s1"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _record(conn, root, tool, tin, resp, uid, session_id=S1):
    return common.record(conn, tool, tin, resp, session_id=session_id, agent="main",
                         bridge_version="v", bridge_sha="sha", root=root, tool_use_id=uid)


def _because(conn):
    return conn.execute(
        "SELECT src, dst, rid FROM edges WHERE rel='because' ORDER BY rid, src"
    ).fetchall()


def _knowledge_rows(conn):
    ph = ",".join("?" for _ in common.KNOWLEDGE_KINDS)
    return conn.execute(
        "SELECT key, last_detail FROM nodes WHERE kind IN ({})".format(ph), common.KNOWLEDGE_KINDS
    ).fetchall()


def _overlaps(conn, text):
    """{key: overlap count} of `text` against every knowledge node alive right now --
    the arithmetic `_link_because` does, so a test can show why a reason links what
    it links."""
    t = toks(text) - common._STOPWORDS
    return {key: len(t & (toks(key) | toks(detail or ""))) for key, detail in _knowledge_rows(conn)}


def _read_resp(src):
    return {"file": {"content": src}}


def _mirror(tmp_path, *, open_turn_reason=True):
    """The toy session through the real API. Returns (conn, rids) where rids maps the
    toy's action ids a1..a9 to receipt ids. Reasons are recorded at each closed turn's
    Stop, after `mark_turn` and after the decision, in `lift.main`'s order; the open
    turn's reason (a9) is recorded immediately when `open_turn_reason` (lift.py would
    only lift it at the NEXT Stop -- see test_open_turn_before_its_stop_has_no_reasons)."""
    root = str(tmp_path)
    conn = common.db(root)
    rids = {}
    reasons = {}          # toy action id -> (rid, tool_use_id, reason text)
    linked = {}           # toy action id -> keys _link_because drew

    def stop(*acts, decision=None):
        common.mark_turn(conn, S1)
        if decision is not None:
            common.record_decision(conn, S1, "main", decision, "t.jsonl:9")
        for a in acts:
            rid, uid, text = reasons[a]
            linked[a] = common.record_reason(conn, rid, S1, uid, text)

    # request 1 -- q1 "checkout test is flaky": a1 run tests -> e1
    rids["a1"] = _record(conn, root, "Bash", {"command": "pytest -q"},
                         {"stdout": E1, "exitCode": 1}, "tu1")
    reasons["a1"] = (rids["a1"], "tu1", "start from the failure")           # q1 -> a1
    stop("a1")

    # request 2 -- a2 read payment/client.py -> f1
    rids["a2"] = _record(conn, root, "Read", {"file_path": "payment/client.py"},
                         _read_resp("def charge(amount, retries=0, timeout=2):\n    pass\n"), "tu2")
    reasons["a2"] = (rids["a2"], "tu2", "the timeout points at the payment client")   # e1 -> a2
    stop("a2")

    # request 3 -- a3 grep "charge(" (mirrored as a Read of the caller) -> f2
    rids["a3"] = _record(conn, root, "Read", {"file_path": "payment/checkout.py"},
                         _read_resp("def charge_in_transaction(order, db):\n"
                                    "    with db.transaction():\n        charge(order.amount)\n"), "tu3")
    reasons["a3"] = (rids["a3"], "tu3", "the client has retries=0: who calls it?")     # f1 -> a3
    stop("a3")

    # request 4 -- d1 "idempotency key + retries=2" (at Stop), a4 edit payment/client.py
    rids["a4"] = _record(conn, root, "Edit",
                         {"file_path": "payment/client.py", "old_string": "retries=0",
                          "new_string": "retries=2, idempotency_key=key"}, {"success": True}, "tu4")
    reasons["a4"] = (rids["a4"], "tu4", "apply the decision")                         # d1 -> a4
    stop("a4", decision="idempotency key on the client with retries=2 since checkout "
                        "wraps it in a db transaction")                             # f1 -> d1, f2 -> d1

    # request 5 -- a5 run tests -> e2
    rids["a5"] = _record(conn, root, "Bash", {"command": "pytest -q"},
                         {"stdout": E2, "exitCode": 1}, "tu5")
    reasons["a5"] = (rids["a5"], "tu5", "verify the edit")                            # a4 -> a5
    stop("a5")

    # request 6 -- a6 read payment/refund.py -> f3
    rids["a6"] = _record(conn, root, "Read", {"file_path": "payment/refund.py"},
                         _read_resp("def refund(charge_id, amount):\n"
                                    "    request = build_request(charge_id, amount)\n"), "tu6")
    reasons["a6"] = (rids["a6"], "tu6",
                     "the test_refund KeyError: the idempotency key I added to the client "
                     "is what broke it; refund shares the request builder")            # e2 -> a6, d1 -> a6
    stop("a6")

    # request 7 -- a7 edit payment/refund.py, a8 run tests -> p1 (pass: no node)
    rids["a7"] = _record(conn, root, "Edit",
                         {"file_path": "payment/refund.py", "old_string": "x",
                          "new_string": "    request = build_request(charge_id, amount, idempotency_key=None)\n"},
                         {"success": True}, "tu7")
    reasons["a7"] = (rids["a7"], "tu7", "make refund's charge_id optional there")     # f3 -> a7
    rids["a8"] = _record(conn, root, "Bash", {"command": "pytest -q"},
                         {"stdout": "12 passed", "exitCode": 0}, "tu8")
    reasons["a8"] = (rids["a8"], "tu8", "verify")                                     # a7 -> a8
    stop("a7", "a8")

    # request 8 (open) -- q2 "do the same for subscriptions": a9 edit billing/subscriptions.py
    rids["a9"] = _record(conn, root, "Edit",
                         {"file_path": "billing/subscriptions.py", "old_string": "x",
                          "new_string": "    charge(order.amount, retries=2, idempotency_key=key)\n"},
                         {"success": True}, "tu9")
    reasons["a9"] = (rids["a9"], "tu9",
                     "same decision applies: the key on the client; subscriptions also run "
                     "inside a db transaction")                                        # d1 -> a9, f2 -> a9
    if open_turn_reason:
        rid, uid, text = reasons["a9"]
        linked["a9"] = common.record_reason(conn, rid, S1, uid, text)
    return conn, rids


def _store_id(toy_id, rids):
    """toy node id -> store key, or None when the store has no node for it."""
    if toy_id in rids:
        return "r{}".format(rids[toy_id])
    return {"e1": E1, "f1": F1, "f2": F2, "d1": D1, "e2": E2, "f3": F3}.get(toy_id)


# The toy's because arrows the store DID draw (observed in
# test_store_reproduces_exactly_these_toy_because_edges; every other toy arrow is listed
# there as a gap).
REPRODUCED_BECAUSE = {
    ("e1", "a2"), ("f1", "a3"), ("f1", "d1"), ("f2", "d1"),
    ("e2", "a6"), ("d1", "a6"), ("f3", "a7"), ("d1", "a9"), ("f2", "a9"),
}
REPRODUCED_PROVENANCE = {("a1", "e1"), ("a2", "f1"), ("a3", "f2"), ("a5", "e2"), ("a6", "f3")}


# ---------------------------------------------------------------------------
# the mirror: which toy arrows the store draws, and which it cannot
# ---------------------------------------------------------------------------

def test_store_reproduces_exactly_these_toy_because_edges(tmp_path, capsys):
    conn, rids = _mirror(tmp_path)
    store_because = {(src, dst) for src, dst, _rid in _because(conn)}

    toy_because = [(e["src"], e["dst"]) for e in TOY["edges"] if e["rel"] == "because"]
    reproduced, missing = [], []
    for src, dst in toy_because:
        pair = (_store_id(src, rids), _store_id(dst, rids))
        (reproduced if pair in store_because else missing).append((src, dst, pair))

    with capsys.disabled():
        print("\n[carry_store] because edges in the store:")
        for row in _because(conn):
            print("   ", row)
        print("[carry_store] toy because arrows reproduced ({}):".format(len(reproduced)))
        for src, dst, pair in reproduced:
            print("    {} -> {}  as  {}".format(src, dst, pair))
        print("[carry_store] toy because arrows NOT reproduced ({}):".format(len(missing)))
        for src, dst, pair in missing:
            print("    {} -> {}  ({})".format(src, dst, pair))

    assert {(s, d) for s, d, _ in reproduced} == REPRODUCED_BECAUSE
    # nothing the toy does not have: every store because edge is one of the reproduced arrows
    expected_pairs = {(_store_id(s, rids), _store_id(d, rids)) for s, d in REPRODUCED_BECAUSE}
    assert store_because == expected_pairs
    # the gaps are exactly the arrows out of a request or an action, plus d1 -> a4
    gap_ids = {(s, d) for s, d, _ in missing}
    assert gap_ids == {
        ("q1", "a1"), ("d1", "a4"), ("a4", "a5"), ("a7", "a8"), ("q2", "a9"),
        ("q2", "r1"), ("r1", "r2"), ("r2", "r3"), ("r3", "a9"),   # truncated-arm only
    }


def test_each_reason_links_only_its_intended_node(tmp_path):
    """Overlap arithmetic per reason: >= REASON_MIN_OVERLAP with the intended node(s),
    < 2 with every other knowledge node alive at that moment."""
    conn, rids = _mirror(tmp_path)
    rows = conn.execute("SELECT rid, text FROM reasons ORDER BY rid").fetchall()
    intended = {
        rids["a1"]: set(), rids["a2"]: {E1}, rids["a3"]: {F1}, rids["a4"]: set(), rids["a5"]: set(),
        rids["a6"]: {E2, D1}, rids["a7"]: {F3}, rids["a8"]: set(), rids["a9"]: {D1, F2},
    }
    alive_before = {}
    for key, kind, first_rid in conn.execute("SELECT key, kind, first_rid FROM nodes").fetchall():
        if kind in common.KNOWLEDGE_KINDS:
            alive_before[key] = first_rid
    for rid, text in rows:
        ov = _overlaps(conn, text)
        for key, n in ov.items():
            if alive_before[key] >= rid:
                continue  # not linkable at that moment (record_reason: first_rid < rid)
            if key in intended[rid]:
                assert n >= common.REASON_MIN_OVERLAP, (rid, key, text, n)
            else:
                assert n < common.REASON_MIN_OVERLAP, (rid, key, text, n)


def test_provenance_edges_land_on_the_receipt_that_produced_the_knowledge(tmp_path):
    conn, rids = _mirror(tmp_path)
    _nodes, edges, _cur = graph_from_store(conn, S1)
    for src, dst in REPRODUCED_PROVENANCE:
        assert (_store_id(src, rids), _store_id(dst, rids)) in edges
    # a8 -> p1: a passing run lifts no node, so there is no provenance edge out of a8
    assert not any(s == _store_id("a8", rids) for s, _ in edges)
    # footprints (file / command targets) never enter the node map
    assert not any(k in _nodes for k in ("payment/client.py", "payment/refund.py", "pytest -q",
                                         "billing/subscriptions.py"))


# ---------------------------------------------------------------------------
# turns: every mirrored node sits at its toy turn; request 8 is the open turn
# ---------------------------------------------------------------------------

def test_graph_from_store_puts_every_mirrored_node_at_its_toy_turn(tmp_path):
    conn, rids = _mirror(tmp_path)
    nodes, _edges, current = graph_from_store(conn, S1)
    assert current == 8
    toy_turn = {n["id"]: n["turn"] for n in TOY["nodes"]}
    toy_kind = {n["id"]: n["kind"] for n in TOY["nodes"]}
    kind_map = {"act": "act", "err": "error", "fact": "read", "dec": "decided"}
    for toy_id in ("a1", "e1", "a2", "f1", "a3", "f2", "d1", "a4", "a5", "e2", "a6", "f3", "a7", "a8", "a9"):
        key = _store_id(toy_id, rids)
        assert nodes[key].turn == toy_turn[toy_id], (toy_id, key, nodes[key])
        assert nodes[key].kind == kind_map[toy_kind[toy_id]], (toy_id, key, nodes[key])
    # the request / pass nodes have no store counterpart
    assert set(nodes) == {_store_id(i, rids) for i in ("a1", "e1", "a2", "f1", "a3", "f2", "d1", "a4",
                                                        "a5", "e2", "a6", "f3", "a7", "a8", "a9")}


def test_e1_first_rid_predates_every_boundary_and_is_turn_1(tmp_path):
    conn, rids = _mirror(tmp_path)
    (first_rid,) = conn.execute("SELECT first_rid FROM nodes WHERE key=?", (E1,)).fetchone()
    boundaries = [r[0] for r in conn.execute("SELECT rid_at FROM turns WHERE session_id=? ORDER BY n", (S1,))]
    assert boundaries == [1, 2, 3, 4, 5, 6, 8]
    assert first_rid == 1 and min(boundaries) == first_rid   # `b < rid` is false for the first boundary
    assert turn_of_rid(boundaries, first_rid) == 1
    assert graph_from_store(conn, S1)[0][E1].turn == 1


# ---------------------------------------------------------------------------
# the carry rule over the store, request by request
# ---------------------------------------------------------------------------

def _expected_continuum(t):
    """The toy's expected.continuum[t] in store keys -- except request 5, where the
    store's honest answer differs (no action-to-action arrow exists in the store, so a5
    has no ancestry: see the module docstring)."""
    exp = TOY["expected"]["continuum"][str(t)]
    to_store = {"e1": E1, "f1": F1, "f2": F2, "d1": D1}
    carried = sorted(to_store[i] for i in exp["carried"])
    reachable = exp["reachable"]
    if t == 5:
        carried, reachable = [], "—"     # toy: [e1], "1/1"
    return carried, reachable, exp["window_cutoff"]


@pytest.mark.parametrize("t", range(1, 9))
def test_carry_from_store_request_by_request(tmp_path, t):
    conn, _rids = _mirror(tmp_path)
    carried, reachable, cut = _expected_continuum(t)
    c = carry_from_store(conn, S1, window=WINDOW, turn=t)
    assert c.turn == t and c.cutoff == cut
    assert c.carried == carried, (t, c)
    assert c.reachable == reachable, (t, c)


def test_open_request_8_carries_d1_e1_f1_f2_and_reaches_4_of_4(tmp_path):
    conn, rids = _mirror(tmp_path)
    assert TOY["expected"]["continuum"]["8"]["carried"] == ["d1", "e1", "f1", "f2"]
    c = carry_from_store(conn, S1, window=WINDOW)            # the open turn, no `turn=`
    assert c.turn == 8 and c.cutoff == 5
    assert c.now == ["r{}".format(rids["a9"])]
    assert c.need == {D1, E1, F1, F2}
    assert c.carried == sorted([D1, E1, F1, F2])
    assert c.old == sorted([D1, E1, F1, F2])
    assert c.reachable == "4/4"


def test_open_request_8_with_window_1(tmp_path):
    conn, _rids = _mirror(tmp_path)
    c = carry_from_store(conn, S1, window=1)
    assert c.turn == 8 and c.cutoff == 8
    assert c.need == {D1, E1, F1, F2}
    assert c.carried == sorted([D1, E1, F1, F2])
    assert c.reachable == "4/4"


def test_request_5_honest_store_value_vs_toy(tmp_path):
    """Toy: a5 descends from a4 ("verify the edit") -> d1 -> f1, f2 -> ... -> e1, so at
    request 5 with window 4 it carries [e1] and reaches 1/1. The store has no
    action-to-action arrow (`_link_because` starts only at knowledge nodes) and the
    decision cannot be the cause of the same-turn edit it was lifted after, so a5's
    ancestry is empty: nothing is needed, nothing carried."""
    conn, rids = _mirror(tmp_path)
    assert TOY["expected"]["continuum"]["5"] == {"reachable": "1/1", "rederived_actions": 0,
                                                 "carried": ["e1"], "window_cutoff": 2}
    c = carry_from_store(conn, S1, window=WINDOW, turn=5)
    assert c.cutoff == 2
    assert c.now == sorted(["r{}".format(rids["a5"]), E2])
    assert c.need == set()
    assert c.carried == []
    assert c.reachable == "—"


def test_open_turn_before_its_stop_has_no_reasons(tmp_path):
    """lift.py records reasons at Stop. A carry taken mid-turn (the PreCompact moment)
    therefore sees the open turn's receipts with no `because` edge yet: nothing is
    needed and nothing is carried, whatever the earlier turns hold."""
    conn, rids = _mirror(tmp_path, open_turn_reason=False)
    assert conn.execute("SELECT COUNT(*) FROM reasons WHERE rid=?", (rids["a9"],)).fetchone() == (0,)
    c = carry_from_store(conn, S1, window=WINDOW)
    assert c.turn == 8 and c.now == ["r{}".format(rids["a9"])]
    assert c.need == set() and c.carried == [] and c.reachable == "—"


# ---------------------------------------------------------------------------
# probes: degenerate turn tables
# ---------------------------------------------------------------------------

def test_store_with_no_turns_rows_is_one_open_turn(tmp_path):
    root = str(tmp_path)
    conn = common.db(root)
    r1 = _record(conn, root, "Bash", {"command": "pytest"}, {"stdout": "TimeoutError x", "exitCode": 1}, "tu1")
    r2 = _record(conn, root, "Read", {"file_path": "a.py"}, _read_resp("def f(a):\n    pass\n"), "tu2")
    assert common.record_reason(conn, r2, S1, "tu2", "TimeoutError x points here") == ["TimeoutError x"]
    nodes, edges, current = graph_from_store(conn, S1)
    assert current == 1
    assert {n.turn for n in nodes.values()} == {1}
    assert set(nodes) == {"r{}".format(r1), "r{}".format(r2), "TimeoutError x", "read:a.py:f"}
    c = carry_from_store(conn, S1, window=1)
    assert c.turn == 1 and c.cutoff == 1
    assert c.need == {"TimeoutError x"} and c.carried == [] and c.reachable == "all"


def test_two_consecutive_boundaries_make_an_empty_turn(tmp_path):
    root = str(tmp_path)
    conn = common.db(root)
    r1 = _record(conn, root, "Bash", {"command": "pytest"}, {"stdout": "TimeoutError x", "exitCode": 1}, "tu1")
    common.mark_turn(conn, S1)
    common.mark_turn(conn, S1)                       # a Stop with no receipt since the last one
    r2 = _record(conn, root, "Read", {"file_path": "a.py"}, _read_resp("def f(a):\n    pass\n"), "tu2")
    assert common.record_reason(conn, r2, S1, "tu2", "TimeoutError x points here") == ["TimeoutError x"]
    assert [r[0] for r in conn.execute("SELECT rid_at FROM turns ORDER BY n")] == [r1, r1]
    assert turn_of_rid([r1, r1], r2) == 3
    nodes, _edges, current = graph_from_store(conn, S1)
    assert current == 3
    assert nodes["r{}".format(r1)].turn == 1 and nodes["TimeoutError x"].turn == 1
    assert nodes["r{}".format(r2)].turn == 3 and nodes["read:a.py:f"].turn == 3
    assert not any(n.turn == 2 for n in nodes.values())
    c = carry_from_store(conn, S1, window=1)
    assert c.cutoff == 3 and c.carried == ["TimeoutError x"] and c.reachable == "1/1"
    assert carry_from_store(conn, S1, window=2).carried == ["TimeoutError x"]   # turn 2 is empty, 1 is still out
    assert carry_from_store(conn, S1, window=3).carried == [] and carry_from_store(conn, S1, window=3).reachable == "all"


def test_boundary_before_any_receipt_puts_the_first_receipt_in_turn_2(tmp_path):
    root = str(tmp_path)
    conn = common.db(root)
    common.mark_turn(conn, S1)                       # rid_at = 0
    r1 = _record(conn, root, "Bash", {"command": "ls"}, {"stdout": ""}, "tu1")
    assert conn.execute("SELECT rid_at FROM turns").fetchone() == (0,)
    nodes, _edges, current = graph_from_store(conn, S1)
    assert current == 2 and nodes["r{}".format(r1)].turn == 2
    assert carry_from_store(conn, S1, window=1).now == ["r{}".format(r1)]


# ---------------------------------------------------------------------------
# probes: a second session sharing the store
# ---------------------------------------------------------------------------

def test_second_session_sits_at_turn_0_and_never_reaches_the_first_sessions_now_or_need(tmp_path):
    root = str(tmp_path)
    pre = common.db(root)
    # s2 acts first: its receipt id 1 predates every s1 boundary
    r_s2 = _record(pre, root, "Bash", {"command": "make"}, {"stdout": "LinkError in vendor.blob", "exitCode": 1},
                   "tx1", session_id="s2")
    assert r_s2 == 1
    pre.close()
    # s1 runs the toy on top of it (same store file, its own handle)
    conn, rids = _mirror(tmp_path)
    # s2 keeps acting after s1's turns: another receipt, a reason of its own
    r_s2b = _record(conn, root, "Read", {"file_path": "vendor/blob.py"}, _read_resp("def blob(x):\n    pass\n"),
                    "tx2", session_id="s2")
    assert common.record_reason(conn, r_s2b, "s2", "tx2", "the LinkError in vendor.blob") == ["LinkError in vendor.blob"]

    nodes, edges, current = graph_from_store(conn, S1)
    assert current == 8
    # s2's receipts, its knowledge and its reason are in the graph -- at turn 0, whether
    # its receipt id predates s1's boundaries or lands in s1's open-turn range
    for key in ("r{}".format(r_s2), "r{}".format(r_s2b), "LinkError in vendor.blob", "read:vendor/blob.py:blob"):
        assert nodes[key].turn == 0, (key, nodes[key])
    assert ("LinkError in vendor.blob", "r{}".format(r_s2b)) in edges
    c = carry_from_store(conn, S1, window=WINDOW)
    assert c.now == ["r{}".format(rids["a9"])]                       # nothing of s2's is s1's `now`
    assert c.need == {D1, E1, F1, F2}                                 # nor descends from s1's request
    assert c.carried == sorted([D1, E1, F1, F2]) and c.reachable == "4/4"
    # s1's own boundaries were pushed by s2's receipt ids, and every s1 node still sits at its toy turn
    assert nodes[E1].turn == 1 and nodes[D1].turn == 4 and nodes["r{}".format(rids["a9"])].turn == 8


def test_a_fact_another_session_read_is_carried_when_this_session_cites_it(tmp_path):
    """The store is shared across resumes: a knowledge node another session produced sits
    at turn 0 with its kind and the foreign receipt that read it (provenance intact);
    the `because` edge that cites it puts it in `need`, and turn 0 is outside every
    window, so it is carried."""
    root = str(tmp_path)
    conn = common.db(root)
    r_s2 = _record(conn, root, "Read", {"file_path": "vendor/blob.py"}, _read_resp("def blob(x):\n    pass\n"),
                   "tx1", session_id="s2")
    r1 = _record(conn, root, "Bash", {"command": "ls"}, {"stdout": ""}, "tu1")
    common.mark_turn(conn, S1)
    r2 = _record(conn, root, "Edit", {"file_path": "vendor/blob.py", "old_string": "x", "new_string": "y"},
                 {"success": True}, "tu2")
    assert common.record_reason(conn, r2, S1, "tu2", "vendor blob takes x") == ["read:vendor/blob.py:blob"]
    nodes, edges, current = graph_from_store(conn, S1)
    assert current == 2
    assert nodes["r{}".format(r_s2)] == Node("r{}".format(r_s2), "act", 0)   # s2's receipt: turn 0
    assert nodes["read:vendor/blob.py:blob"] == Node("read:vendor/blob.py:blob", "read", 0)
    assert ("read:vendor/blob.py:blob", "r{}".format(r2)) in edges
    assert ("r{}".format(r_s2), "read:vendor/blob.py:blob") in edges           # s2's provenance comes with it
    c = carry_from_store(conn, S1, window=1)
    assert c.now == ["r{}".format(r2)] and nodes["r{}".format(r1)].turn == 1
    assert c.need == {"read:vendor/blob.py:blob"} and c.carried == ["read:vendor/blob.py:blob"]
    assert c.reachable == "1/1"


def test_another_sessions_decision_with_this_sessions_cursor_is_turn_0(tmp_path):
    """A decision another session lifts while this session's receipt is the store-wide
    cursor gets first_rid == that receipt; it is that session's decision (turn 0), not
    a node this session produced -- and not in this session's `now`."""
    root = str(tmp_path)
    conn = common.db(root)
    r1 = _record(conn, root, "Bash", {"command": "pytest"}, {"stdout": "TimeoutError x", "exitCode": 1}, "tu1")
    common.record_decision(conn, "s2", "main", "retry the TimeoutError x path", "t:1")
    assert conn.execute("SELECT first_rid, session_id FROM nodes WHERE key='decided:1'").fetchone() == (r1, "s2")
    nodes, edges, _cur = graph_from_store(conn, S1)
    assert nodes["decided:1"] == Node("decided:1", "decided", 0)
    assert edges == [("r{}".format(r1), "TimeoutError x"), ("TimeoutError x", "decided:1")]
    assert carry_from_store(conn, S1, window=1).now == sorted(["r{}".format(r1), "TimeoutError x"])


# ---------------------------------------------------------------------------
# probes: receipt / knowledge key collisions, and a decision's place in time
# ---------------------------------------------------------------------------

def test_symbol_named_like_a_receipt_does_not_hide_the_receipt(tmp_path):
    """Receipt ids and knowledge keys share the node map; the receipt wins and the
    symbol spelled like it is shadowed -- left out with its `defines` edge."""
    root = str(tmp_path)
    conn = common.db(root)
    r1 = _record(conn, root, "Write", {"file_path": "x.py", "content": "def r2():\n    pass\n"}, {"success": True}, "tu1")
    common.mark_turn(conn, S1)
    r2 = _record(conn, root, "Bash", {"command": "ls"}, {"stdout": ""}, "tu2")
    assert (r1, r2) == (1, 2)
    assert conn.execute("SELECT kind FROM nodes WHERE key='r2'").fetchone() == ("symbol",)
    nodes, edges, current = graph_from_store(conn, S1)
    assert current == 2
    assert nodes["r2"].kind == "act" and nodes["r2"].turn == 2
    assert edges == []                                                # not ("r1", "r2"): the symbol is out
    assert carry_from_store(conn, S1, window=1).now == ["r2"]


def test_decision_edges_survive_another_sessions_receipt_at_stop(tmp_path):
    root = str(tmp_path)
    conn = common.db(root)
    r1 = _record(conn, root, "Read", {"file_path": "payment/client.py"},
                 _read_resp("def charge(amount, retries=0, timeout=2):\n    pass\n"), "tu1")
    r_other = _record(conn, root, "Bash", {"command": "ls"}, {"stdout": "zzz"}, "tx1", session_id="s2")
    common.mark_turn(conn, S1)                                       # rid_at == r_other
    common.record_decision(conn, S1, "main", "charge with retries=2 and a timeout", "t:1")
    # the store DID draw f1 -> d1 ... stamped with s2's rid
    assert _because(conn) == [(F1, D1, r_other)]
    r3 = _record(conn, root, "Edit", {"file_path": "payment/client.py", "new_string": "retries=2"},
                 {"success": True}, "tu3")
    assert common.record_reason(conn, r3, S1, "tu3", "the decided plan: retries") == [D1]
    nodes, edges, _cur = graph_from_store(conn, S1)
    assert nodes[D1].turn == 1 and nodes["r{}".format(r3)].turn == 2
    assert (F1, D1) in edges
    c = carry_from_store(conn, S1, window=1)
    assert c.need == {D1, F1} and c.reachable == "2/2"


def test_decision_at_the_stop_of_an_empty_turn_lands_in_that_turn(tmp_path):
    """lift.main marks the turn, then records the decision. A turn with no tool calls
    leaves the decision's cursor (first_rid) equal to the previous boundary, which
    `turn_of_rid` alone would put one turn back; the count of Stops before the
    decision puts it where it was made."""
    root = str(tmp_path)
    conn = common.db(root)
    r1 = _record(conn, root, "Bash", {"command": "pytest"}, {"stdout": E1, "exitCode": 1}, "tu1")
    common.mark_turn(conn, S1)                                        # Stop of turn 1
    common.mark_turn(conn, S1)                                        # Stop of turn 2: no tool call
    common.record_decision(conn, S1, "main", "the TimeoutError in payment.charge needs retries", "t:2")
    assert conn.execute("SELECT first_rid FROM nodes WHERE key=?", (D1,)).fetchone() == (r1,)
    assert [r[0] for r in conn.execute("SELECT rid_at FROM turns ORDER BY n")] == [r1, r1]
    r2 = _record(conn, root, "Edit", {"file_path": "payment/client.py", "new_string": "retries=2"},
                 {"success": True}, "tu2")
    assert common.record_reason(conn, r2, S1, "tu2", "the decided retries plan") == [D1]
    nodes, edges, current = graph_from_store(conn, S1)
    assert current == 3
    assert turn_of_rid([r1, r1], r1) == 1 and nodes[D1].turn == 2
    assert nodes[E1].turn == 1 and nodes["r{}".format(r2)].turn == 3
    assert (E1, D1) in edges and (D1, "r{}".format(r2)) in edges
    c = carry_from_store(conn, S1, window=2)                          # turns 2..3 in the window
    assert c.cutoff == 2 and c.need == {D1, E1}
    assert c.carried == [E1] and c.old == [E1] and c.reachable == "1/1"
    assert carry_from_store(conn, S1, window=1).carried == sorted([D1, E1])


def test_decision_in_the_open_turn_after_a_receipt_stays_in_the_open_turn(tmp_path):
    """The other bound: a decision recorded after this turn's first receipt takes the
    receipt's turn, not the count of Stops before it."""
    root = str(tmp_path)
    conn = common.db(root)
    _record(conn, root, "Bash", {"command": "ls"}, {"stdout": ""}, "tu1")
    common.mark_turn(conn, S1)
    _record(conn, root, "Bash", {"command": "pytest"}, {"stdout": E1, "exitCode": 1}, "tu2")
    common.record_decision(conn, S1, "main", "the TimeoutError in payment.charge needs retries", "t:2")
    nodes, _edges, current = graph_from_store(conn, S1)
    assert current == 2 and nodes[D1].turn == 2
    assert carry_from_store(conn, S1, window=1).now == sorted([D1, E1, "r2"])


# ---------------------------------------------------------------------------
# probes: a second session's receipt as the decision cursor; foreign ancestry
# ---------------------------------------------------------------------------

def test_decision_at_stop_stays_in_the_closed_turn_when_a_foreign_receipt_lands_before_it(tmp_path):
    """test_decision_edges_survive_another_sessions_receipt_at_stop has the foreign receipt
    BEFORE mark_turn (rid_at == it); this one has it between mark_turn and
    record_decision, the two calls lift.main makes back to back. The decision's cursor is then past this session's boundary, so `turn_of_rid` of
    the cursor would say the open turn; the turn of this session's own newest receipt at
    or before the cursor (r1, turn 1) is what places it -- a decision lifted at the Stop
    of turn 1 never sits in `now` at turn 2 dragging its ancestry into `need` for a
    request that has cited nothing yet."""
    root = str(tmp_path)
    conn = common.db(root)
    r1 = _record(conn, root, "Read", {"file_path": "payment/client.py"},
                 _read_resp("def charge(amount, retries=0, timeout=2):\n    pass\n"), "tu1")
    common.mark_turn(conn, S1)                                       # rid_at == r1
    r_other = _record(conn, root, "Bash", {"command": "ls"}, {"stdout": "zzz"}, "tx1", session_id="s2")
    common.record_decision(conn, S1, "main", "charge with retries=2 and a timeout", "t:1")
    assert conn.execute("SELECT first_rid FROM nodes WHERE key=?", (D1,)).fetchone() == (r_other,)
    nodes, edges, current = graph_from_store(conn, S1)
    assert current == 2 and (F1, D1) in edges
    assert nodes[D1].turn == 1, nodes[D1]                            # not the open turn 2
    c = carry_from_store(conn, S1, window=1)
    assert c.now == [] and c.need == set() and c.reachable == "—", c
    # once the request cites it, the decision is carried from turn 1 with its fact
    r3 = _record(conn, root, "Edit", {"file_path": "payment/client.py", "new_string": "retries=2"},
                 {"success": True}, "tu3")
    assert common.record_reason(conn, r3, S1, "tu3", "the decided plan: retries") == [D1]
    c = carry_from_store(conn, S1, window=1)
    assert c.now == [f"r{r3}"] and c.need == {D1, F1}
    assert c.carried == sorted([D1, F1]) and c.reachable == "2/2"


def test_a_decision_another_session_made_brings_its_facts_when_this_session_cites_it(tmp_path):
    """`plateau resume` is a fresh session id over the shared store (cli.py). When the
    resumed session cites the earlier session's decision, the walk goes on through it:
    `(f1, because, decided:1)` is an edge like any other, so f1 is in `need` as the pure
    rule (every arrow) says -- and both sit at turn 0, outside the resumed session's
    window, so they are carried even before its first Stop."""
    root = str(tmp_path)
    conn = common.db(root)
    _record(conn, root, "Read", {"file_path": "payment/client.py"},
            _read_resp("def charge(amount, retries=0, timeout=2):\n    pass\n"), "tx1", session_id="s2")
    common.mark_turn(conn, "s2")
    common.record_decision(conn, "s2", "main", "charge with retries=2 and a timeout", "t:1")
    assert _because(conn) == [(F1, D1, 1)]
    r2 = _record(conn, root, "Edit", {"file_path": "payment/client.py", "new_string": "retries=2"},
                 {"success": True}, "tu1")
    assert common.record_reason(conn, r2, S1, "tu1", "the decided plan: retries") == [D1]
    nodes, edges, _cur = graph_from_store(conn, S1)
    assert D1 in nodes and (D1, "r{}".format(r2)) in edges
    assert (F1, D1) in edges, edges
    assert nodes[F1] == Node(F1, "read", 0) and nodes[D1] == Node(D1, "decided", 0)
    assert nodes["r1"] == Node("r1", "act", 0) and ("r1", F1) in edges   # s2's receipt read f1
    c = carry_from_store(conn, S1, window=1)
    assert c.now == ["r{}".format(r2)]
    assert c.need == {D1, F1}, c
    assert c.carried == sorted([D1, F1]) and c.reachable == "2/2"


def test_a_cited_foreign_decision_walks_back_through_the_decision_beneath_it(tmp_path):
    """The walk is transitive: a foreign decision made because of an earlier foreign
    decision brings that one and its facts too, through the store's own because rows."""
    root = str(tmp_path)
    conn = common.db(root)
    _record(conn, root, "Read", {"file_path": "payment/client.py"},
            _read_resp("def charge(amount, retries=0, timeout=2):\n    pass\n"), "tx1", session_id="s2")
    common.mark_turn(conn, "s2")
    common.record_decision(conn, "s2", "main", "charge with retries=2 and a timeout", "t:1")
    common.mark_turn(conn, "s2")
    common.record_decision(conn, "s2", "main", "the decided retries plan also covers refunds", "t:2")
    assert (D1, "decided:2", 1) in _because(conn)
    r3 = _record(conn, root, "Edit", {"file_path": "payment/refund.py", "new_string": "retries=2"},
                 {"success": True}, "tu1")
    assert common.record_reason(conn, r3, S1, "tu1", "the plan covers refunds") == ["decided:2"]
    nodes, edges, _cur = graph_from_store(conn, S1)
    assert set(nodes) == {f"r{r3}", "decided:2", D1, F1, "r1"}     # r1: s2's read of f1, walked through
    assert (D1, "decided:2") in edges and (F1, D1) in edges and ("decided:2", f"r{r3}") in edges
    assert ("r1", F1) in edges
    assert carry_from_store(conn, S1, window=1).need == {"decided:2", D1, F1}


# ---------------------------------------------------------------------------
# probes: decision placement corner cases; the walk across sessions; edge order
# ---------------------------------------------------------------------------

def test_this_sessions_decision_descending_from_a_foreign_decision_walks_to_its_facts(tmp_path):
    """The walk also starts from THIS session's decisions: d2 (s1) because d1 (s2)
    because f1 -- d1 is named by d2's edge, expanded, and f1 enters."""
    root = str(tmp_path)
    conn = common.db(root)
    _record(conn, root, "Read", {"file_path": "payment/client.py"},
            _read_resp("def charge(amount, retries=0, timeout=2):\n    pass\n"), "tx1", session_id="s2")
    common.mark_turn(conn, "s2")
    common.record_decision(conn, "s2", "main", "charge with retries=2 and a timeout", "t:1")
    r2 = _record(conn, root, "Bash", {"command": "ls"}, {"stdout": ""}, "tu1")
    common.mark_turn(conn, S1)
    common.record_decision(conn, S1, "main", "the decided retries plan also covers refunds", "t:2")
    assert (D1, "decided:2", r2) in _because(conn)
    nodes, edges, current = graph_from_store(conn, S1)
    assert current == 2
    assert set(nodes) == {f"r{r2}", "decided:2", D1, F1, "r1"}     # r1: s2's read of f1
    assert nodes["decided:2"].turn == 1                              # s1's own decision, at its Stop
    assert nodes[D1].turn == 0 and nodes[F1].turn == 0 and nodes["r1"].turn == 0   # s2's
    assert (D1, "decided:2") in edges and (F1, D1) in edges
    assert carry_from_store(conn, S1, window=1).now == []           # nothing of turn 2 yet
    r3 = _record(conn, root, "Edit", {"file_path": "payment/refund.py", "new_string": "retries=2"},
                 {"success": True}, "tu2")
    assert common.record_reason(conn, r3, S1, "tu2", "the plan covers refunds") == ["decided:2"]
    c = carry_from_store(conn, S1, window=1)
    assert c.need == {"decided:2", D1, F1} and c.carried == sorted(["decided:2", D1, F1]) and c.reachable == "3/3"


def test_mark_turn_and_record_decision_sharing_one_ts_place_the_decision_at_that_stop(tmp_path, monkeypatch):
    """`turns.ts <= decisions.ts` counts the boundary when the two calls lift.main makes
    land on the same clock reading."""
    root = str(tmp_path)
    conn = common.db(root)
    r1 = _record(conn, root, "Read", {"file_path": "payment/client.py"},
                 _read_resp("def charge(amount, retries=0, timeout=2):\n    pass\n"), "tu1")
    common.mark_turn(conn, S1)                                        # Stop of turn 1
    frozen = common.time.time() + 1.0                                 # after Stop 1, never before it
    monkeypatch.setattr(common.time, "time", lambda: frozen)
    common.mark_turn(conn, S1)                                        # Stop of turn 2 (empty)
    common.record_decision(conn, S1, "main", "charge with retries=2 and a timeout", "t:2")
    assert conn.execute("SELECT ts FROM turns WHERE n=2").fetchone() == (frozen,)
    assert conn.execute("SELECT ts FROM decisions").fetchone() == (frozen,)
    nodes, edges, current = graph_from_store(conn, S1)
    assert current == 3 and nodes[D1].turn == 2 and nodes[f"r{r1}"].turn == 1
    assert (F1, D1) in edges


def test_decision_recorded_mid_turn_after_a_receipt_keeps_that_turn_once_it_closes(tmp_path):
    root = str(tmp_path)
    conn = common.db(root)
    _record(conn, root, "Read", {"file_path": "payment/client.py"},
            _read_resp("def charge(amount, retries=0, timeout=2):\n    pass\n"), "tu1")
    common.mark_turn(conn, S1)                                        # Stop 1
    r2 = _record(conn, root, "Bash", {"command": "ls"}, {"stdout": ""}, "tu2")   # turn 2
    common.record_decision(conn, S1, "main", "charge with retries=2 and a timeout", "t:1")
    assert graph_from_store(conn, S1)[0][D1].turn == 2
    common.mark_turn(conn, S1)                                        # Stop 2
    nodes, _edges, current = graph_from_store(conn, S1)
    assert current == 3 and nodes[D1].turn == 2 and nodes[f"r{r2}"].turn == 2
    assert carry_from_store(conn, S1, window=1).now == []


def test_a_foreign_because_edge_out_of_this_sessions_fact_never_reaches_need(tmp_path):
    """s2 cites a fact s1 read: `(f1, because, r<s2>)`. The edge and s2's receipt (turn
    0) are in the graph, but nothing of s1's descends from that receipt, so s1's `need`
    is untouched and its `now` stays its own."""
    root = str(tmp_path)
    conn = common.db(root)
    r1 = _record(conn, root, "Read", {"file_path": "payment/client.py"},
                 _read_resp("def charge(amount, retries=0, timeout=2):\n    pass\n"), "tu1")
    rx = _record(conn, root, "Edit", {"file_path": "payment/client.py", "new_string": "retries=2"},
                 {"success": True}, "tx1", session_id="s2")
    assert common.record_reason(conn, rx, "s2", "tx1", "charge in the client takes retries") == [F1]
    nodes, edges, _cur = graph_from_store(conn, S1)
    assert nodes[f"r{rx}"].turn == 0 and nodes[F1].turn == 1          # f1 is s1's: read by its own r1
    assert edges == [(f"r{r1}", F1), (F1, f"r{rx}")]
    c = carry_from_store(conn, S1, window=1)
    assert c.now == [f"r{r1}", F1] and c.need == set()


def test_a_decision_of_a_session_with_no_receipts_sits_at_its_stop(tmp_path):
    root = str(tmp_path)
    conn = common.db(root)
    _record(conn, root, "Read", {"file_path": "payment/client.py"},
            _read_resp("def charge(amount, retries=0, timeout=2):\n    pass\n"), "tx1", session_id="s2")
    common.mark_turn(conn, S1)                                        # s1's Stop 1, rid_at = s2's receipt
    common.record_decision(conn, S1, "main", "charge with retries=2 and a timeout", "t:1")
    nodes, edges, current = graph_from_store(conn, S1)
    assert current == 2
    assert set(nodes) == {D1, F1, "r1"} and nodes[D1].turn == 1       # s1's decision, at its Stop
    assert nodes[F1].turn == 0 and nodes["r1"] == Node("r1", "act", 0)   # s2's read of f1
    assert edges == [("r1", F1), (F1, D1)]
    c = carry_from_store(conn, S1, window=1)
    assert c.now == [] and c.need == set() and c.reachable == "—"


def test_symbol_named_like_a_foreign_receipt_is_shadowed_too(tmp_path):
    """Every receipt in the store is a node, so any receipt id shadows a knowledge key
    spelled like it: a symbol `r1` s1 defines while s2's receipt 1 exists is left out
    with its `defines` edge, exactly as with one of s1's own receipts."""
    root = str(tmp_path)
    conn = common.db(root)
    r_s2 = _record(conn, root, "Bash", {"command": "ls"}, {"stdout": ""}, "tx1", session_id="s2")
    r2 = _record(conn, root, "Write", {"file_path": "x.py", "content": "def r1():\n    pass\n"}, {"success": True}, "tu1")
    assert (r_s2, r2) == (1, 2)
    nodes, edges, _cur = graph_from_store(conn, S1)
    assert nodes["r1"] == Node("r1", "act", 0) and nodes["r2"].kind == "act"
    assert edges == []
    assert carry_from_store(conn, S1, window=1).now == ["r2"]


def test_a_cited_foreign_fact_brings_the_error_it_was_read_because_of(tmp_path):
    """s2: a failing run lifts e1 (rid 1); s2 reads payment/client.py because of e1 (rid
    2, reveals f1, `(e1, because, r2)`). s1 (a resume) edits the client citing f1. The
    pure rule walks f1 <- r2 <- e1, so e1 is needed -- as it is when the same chain is
    this session's own (test_provenance_edges_land_on_the_receipt...); the whole chain
    sits at turn 0 and is carried at once, before s1's first Stop as after it."""
    root = str(tmp_path)
    conn = common.db(root)
    r_s1 = _record(conn, root, "Bash", {"command": "pytest -q"}, {"stdout": E1, "exitCode": 1}, "tx1", session_id="s2")
    r_s2 = _record(conn, root, "Read", {"file_path": "payment/client.py"},
                   _read_resp("def charge(amount, retries=0, timeout=2):\n    pass\n"), "tx2", session_id="s2")
    assert common.record_reason(conn, r_s2, "s2", "tx2", "the timeout points at the payment client") == [E1]
    r3 = _record(conn, root, "Edit", {"file_path": "payment/client.py", "new_string": "retries=2"},
                 {"success": True}, "tu1")
    assert common.record_reason(conn, r3, S1, "tu1", "charge in the client takes retries") == [F1]
    nodes, edges, _cur = graph_from_store(conn, S1)
    assert set(nodes) == {f"r{r3}", F1, f"r{r_s2}", E1, f"r{r_s1}"}
    for key in (F1, f"r{r_s2}", E1, f"r{r_s1}"):
        assert nodes[key].turn == 0, (key, nodes[key])
    assert nodes[E1].kind == "error"
    assert (F1, f"r{r3}") in edges and (f"r{r_s2}", F1) in edges
    assert (E1, f"r{r_s2}") in edges and (f"r{r_s1}", E1) in edges
    c = carry_from_store(conn, S1, window=1)
    assert c.now == [f"r{r3}"]
    assert c.need == {E1, F1} and c.carried == sorted([E1, F1]) and c.reachable == "2/2"
    # the same after s1 closes a turn
    common.mark_turn(conn, S1)
    r4 = _record(conn, root, "Bash", {"command": "pytest -q"}, {"stdout": "1 passed", "exitCode": 0}, "tu2")
    assert common.record_reason(conn, r4, S1, "tu2", "charge in the client takes retries") == [F1]
    c = carry_from_store(conn, S1, window=1)
    assert c.now == [f"r{r4}"] and c.need == {E1, F1}
    assert c.carried == sorted([E1, F1]) and c.reachable == "2/2"


def test_a_foreign_receipt_that_produced_nothing_cited_never_enters_need(tmp_path):
    """s2's other receipts, and the facts they produced, are in the graph at turn 0 but
    nothing of s1's descends from them -- only the chain behind what s1 cites is needed."""
    root = str(tmp_path)
    conn = common.db(root)
    r_s1 = _record(conn, root, "Read", {"file_path": "vendor/blob.py"}, _read_resp("def blob(x):\n    pass\n"),
                   "tx1", session_id="s2")
    r_s2 = _record(conn, root, "Read", {"file_path": "payment/client.py"},
                   _read_resp("def charge(amount, retries=0, timeout=2):\n    pass\n"), "tx2", session_id="s2")
    r3 = _record(conn, root, "Edit", {"file_path": "payment/client.py", "new_string": "retries=2"},
                 {"success": True}, "tu1")
    assert common.record_reason(conn, r3, S1, "tu1", "charge in the client takes retries") == [F1]
    nodes, edges, _cur = graph_from_store(conn, S1)
    assert nodes[f"r{r_s1}"].turn == 0 and nodes["read:vendor/blob.py:blob"].turn == 0
    assert edges == [(f"r{r_s1}", "read:vendor/blob.py:blob"), (f"r{r_s2}", F1), (F1, f"r{r3}")]
    c = carry_from_store(conn, S1, window=1)
    assert c.need == {F1} and c.carried == [F1]


def test_graph_from_store_edges_are_in_a_fixed_order(tmp_path):
    """Two foreign decisions cited by one receipt: `edges` is the store's row order
    (rid, then rowid), so it does not depend on set iteration order (PYTHONHASHSEED)."""
    root = str(tmp_path)
    conn = common.db(root)
    _record(conn, root, "Bash", {"command": "pytest -q"}, {"stdout": E1, "exitCode": 1}, "tx1", session_id="s2")
    _record(conn, root, "Bash", {"command": "pytest -q"}, {"stdout": E2, "exitCode": 1}, "tx2", session_id="s2")
    common.mark_turn(conn, "s2")
    common.record_decision(conn, "s2", "main", "the TimeoutError in payment.charge needs retries", "t:1")
    common.record_decision(conn, "s2", "main", "idempotency_key default for test_refund", "t:1")
    assert {(s, d) for s, d, _r in _because(conn)} == {(E1, D1), (E2, "decided:2")}
    r3 = _record(conn, root, "Edit", {"file_path": "payment/client.py", "new_string": "retries=2"},
                 {"success": True}, "tu1")
    assert sorted(common.record_reason(conn, r3, S1, "tu1",
                                       "the decided retries plan and the decided default")) == [D1, "decided:2"]
    _nodes, edges, _cur = graph_from_store(conn, S1)
    assert edges == [("r1", E1), ("r2", E2), (E1, D1), (E2, "decided:2"),
                     (D1, f"r{r3}"), ("decided:2", f"r{r3}")]
    assert carry_from_store(conn, S1, window=1).need == {D1, "decided:2", E1, E2}


def test_turn_0_and_a_negative_window_are_rejected_and_window_0_carries_all_of_need(tmp_path):
    conn, _rids = _mirror(tmp_path)
    with pytest.raises(ValueError):
        carry_from_store(conn, S1, window=1, turn=0)
    with pytest.raises(ValueError):
        carry_from_store(conn, S1, window=-1)
    c = carry_from_store(conn, S1, window=0)                       # the compaction: nothing stays
    assert c.cutoff == 9 and c.carried == sorted(c.need) == sorted([D1, E1, F1, F2]) and c.reachable == "4/4"
