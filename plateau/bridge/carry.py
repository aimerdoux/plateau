"""plateau.bridge.carry — the carry rule: what the continuum brings across a compaction.

The rule is the toy's `compute()` (docs/toy/continuum-toy.html), transliterated. A
context window holds the last WINDOW requests; compaction evicts everything older. The
continuum does not carry "everything old" -- it carries exactly the *knowledge* the
current request descends from: walk every arrow back from the request's own nodes
(`because` reasons AND provenance, `(target, reveals|fails_with|defines, key)` in the
store), keep the facts / decisions / errors / symbols on that path
(`common.KNOWLEDGE_KINDS`), and of those, the ones that have already left the window
are `carried`. Actions -- receipts, `r<rid>` -- are footprints: they are walked through
but never carried, which is what keeps the carried set bounded. `reachable` is the toy's
headline number: of the knowledge this request needs that is older than the window
cutoff, how much is still visible (`"k/n"`, or `"all"` when nothing needed is old, or
`"—"` when nothing is needed). The ground truth for all of this is
tests/fixtures/continuum_toy.json, exported from the toy: 21 nodes, 24 edges, the
expected answer for every request in both arms.

Two parts. The pure part (`Node`, `Carry`, `cutoff`, `ancestors`, `carry`) is the rule
over any node map and edge list -- no sqlite, testable against the fixture verbatim. The
store part (`turn_of_rid`, `graph_from_store`, `carry_from_store`) builds that graph from
the whole receipt store (`common._SCHEMA_SQL`) as seen from one session: every receipt
is an `act` node and every knowledge row keeps its kind; the session only decides *when*
a node is -- its own receipts at the turn of their id (`turns.rid_at` boundaries), the
knowledge its receipts produced at the turn of the first that did, its decisions at the
turn whose Stop lifted them, the open turn (no Stop yet) as the current request, and
everything another session did at turn 0: walkable ancestry, never `now`, never inside
this session's window. Nothing here decides how a carried node is rendered; that stays
with the selector.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Collection, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

from . import common

CARRY_RELS = ("because", "reveals", "fails_with", "defines")


@dataclass(frozen=True)
class Node:
    id: str
    kind: str
    turn: int


@dataclass
class Carry:
    turn: int
    cutoff: int
    now: List[str]
    need: Set[str]          # a set, as the toy's `need`; `carried` / `old` are its sorted views
    carried: List[str]
    old: List[str]
    reachable: str


def cutoff(turn: int, window: int) -> int:
    """The toy's `cutoff`: the oldest request still in the window at `turn`. Turns are
    1-based and a window holds at least one request: `turn < 1` or `window < 1` is a
    ValueError (a cutoff past `turn` would make the request's own nodes "old")."""
    if turn < 1:
        raise ValueError(f"turn must be >= 1, got {turn}")
    if window < 1:
        raise ValueError(f"window must be >= 1, got {window}")
    return max(1, turn - window + 1)


def ancestors(start: Iterable[str], parents: Mapping[str, Iterable[str]]) -> Set[str]:
    """Everything reachable by walking `parents` back from `start` (iterative; a cycle
    terminates because, beyond the starts, an id is only pushed when it enters `seen`,
    which happens once). A start id is in the result only when it is reached from a
    start -- another one, or itself around a cycle; a start nothing points at is never
    its own ancestor."""
    seen: Set[str] = set()
    stack: List[str] = list(start)
    while stack:
        i = stack.pop()
        for p in parents.get(i, ()):
            if p not in seen:
                seen.add(p)
                stack.append(p)
    return seen


def carry(
    nodes: Mapping[str, Node],
    edges: Iterable[Tuple[str, str]],
    turn: int,
    window: int,
    *,
    knowledge: Collection[str],
    carrying: bool = True,
    start: Optional[Iterable[str]] = None,
) -> Carry:
    """The toy's `compute(t)`. `now` is the toy's `now`: every node of `turn`, re-derived
    ones included. `need` = knowledge ancestors of `start` via ALL edges; `start`
    defaults to `now`, and is where a caller reproduces the toy's ancestry walk exactly
    -- the toy walks from the request's own nodes, never from re-derived ones, so in its
    truncated arm the caller passes `start=` without them (tests/test_carry.py `_start`).
    `carried` = the part of `need` older than the cutoff, when `carrying`; `reachable`
    counts how much of the old need is visible. `edges` and `start` are iterated once
    (a generator is fine); unknown ids, duplicate edges and self-edges are harmless."""
    c = cutoff(turn, window)
    present = {nid: n for nid, n in nodes.items() if n.turn <= turn}
    now = sorted(nid for nid, n in present.items() if n.turn == turn)
    parents: Dict[str, List[str]] = {}
    for src, dst in edges:
        if src in present and dst in present:
            parents.setdefault(dst, []).append(src)
    starts = [s for s in (start if start is not None else now) if s in present]
    need = {a for a in ancestors(starts, parents) if present[a].kind in knowledge}
    in_win = {nid for nid, n in present.items() if n.turn >= c}
    # When carrying, `carried` is exactly `old` (need ⊆ present, and present - in_win is
    # the part older than the cutoff), so `visible` is len(old); when not carrying it is
    # 0. Both are kept as the toy spells them.
    carried = sorted(need - in_win) if carrying else []
    carried_set = set(carried)
    old = sorted(nid for nid in need if present[nid].turn < c)
    if old:
        visible = sum(1 for nid in old if nid in in_win or nid in carried_set)
        reachable = f"{visible}/{len(old)}"
    else:
        reachable = "all" if need else "—"
    return Carry(turn=turn, cutoff=c, now=now, need=need, carried=carried, old=old, reachable=reachable)


def turn_of_rid(boundaries: Sequence[int], rid: int) -> int:
    """1 + the number of turn boundaries (`turns.rid_at`, ascending) below `rid`: a
    receipt belongs to the first turn n whose boundary reaches it, `rid_at[n-2] < id
    <= rid_at[n-1]`; past the last boundary is the open turn."""
    return 1 + sum(1 for b in boundaries if b < rid)


def graph_from_store(conn: sqlite3.Connection, session_id: str) -> Tuple[Dict[str, Node], List[Tuple[str, str]], int]:
    """(nodes, edges, current turn): the whole store's graph, dated by `session_id`.

    Every receipt is an `act` node `r<rid>`; every knowledge row (`common.KNOWLEDGE_KINDS`)
    keeps its kind. Every `because` row is the edge `(src, dst)`; every provenance row
    `(target, reveals|fails_with|defines, key, rid)` is the edge `("r<rid>", key)` -- the
    receipt that produced the knowledge is its parent; the `src` column, a file / command
    footprint, is not a node. `edges` is in the store's row order.

    The session decides only *when* a node is. Its own receipts sit at `turn_of_rid` of
    their id, past the last boundary being the open turn (the current request). A
    knowledge node sits at the turn of the first of THIS session's receipts that produced
    it. One of its own decisions sits at the turn whose Stop lifted it: the later of the
    number of its Stops recorded before it (`turns.ts <= decisions.ts`; lift.main marks
    the turn and then records the decision, so a decision at the Stop of a turn with no
    tool calls lands in that turn) and the turn of its newest own receipt at or before the
    decision's cursor (`first_rid`, the store-wide MAX(receipts.id) at Stop -- possibly
    another session's receipt, which must not push the decision forward). A decision
    recorded mid-turn before any receipt of that turn is indistinguishable from one at
    the previous Stop and lands there.

    Everything another session did -- its receipts, the knowledge only its receipts
    produced, its decisions -- sits at turn 0: walkable ancestry, never `now`, never
    inside this session's window, so it is carried whenever the current request descends
    from it. Another session's transcript is never in this context, whatever its receipt
    ids say; and `plateau resume` is a fresh session id over the same store, citing the
    earlier session's knowledge -- that is exactly what turn 0 carries back.

    Receipt ids and knowledge keys share the node map: a knowledge key spelled like a
    receipt id (a symbol literally named `r2`) is shadowed by the receipt and left out
    with its edges."""
    boundaries: List[int] = []
    turn_ts: List[float] = []
    for rid_at, ts in conn.execute(
        "SELECT rid_at, ts FROM turns WHERE session_id=? ORDER BY n", (session_id,)
    ).fetchall():
        boundaries.append(rid_at)
        turn_ts.append(ts)
    current = len(boundaries) + 1

    rids = {rid for (rid,) in conn.execute("SELECT id FROM receipts WHERE session_id=?", (session_id,))}
    nodes: Dict[str, Node] = {}
    for (rid,) in conn.execute("SELECT id FROM receipts ORDER BY id").fetchall():
        nodes[f"r{rid}"] = Node(f"r{rid}", "act", turn_of_rid(boundaries, rid) if rid in rids else 0)

    # this session's decisions -> the number of its Stops recorded before each
    decided: Dict[str, int] = {}
    for did, ts in conn.execute("SELECT id, ts FROM decisions WHERE session_id=?", (session_id,)).fetchall():
        decided[f"decided:{did}"] = sum(1 for t in turn_ts if t <= ts)

    pairs: List[Tuple[str, str, str]] = []           # (src, dst, the knowledge endpoint)
    produced: Dict[str, int] = {}                    # knowledge key -> first own receipt that produced it
    placeholders = ",".join("?" for _ in CARRY_RELS)
    for src, rel, dst, rid in conn.execute(
        f"SELECT src, rel, dst, rid FROM edges WHERE rel IN ({placeholders}) ORDER BY rid, rowid", CARRY_RELS,
    ).fetchall():
        if rel == "because":
            pairs.append((src, dst, src))
        else:
            pairs.append((f"r{rid}", dst, dst))
            if rid in rids:
                produced.setdefault(dst, rid)        # rows come in rid order: the first own producer wins

    placeholders = ",".join("?" for _ in common.KNOWLEDGE_KINDS)
    for key, kind, first_rid in conn.execute(
        f"SELECT key, kind, first_rid FROM nodes WHERE kind IN ({placeholders}) ORDER BY key",
        tuple(common.KNOWLEDGE_KINDS),
    ).fetchall():
        if key in nodes:
            continue                                 # shadowed by a receipt id
        if key in decided:
            own = max((r for r in rids if r <= first_rid), default=0)
            turn = max(turn_of_rid(boundaries, own), decided[key])
        elif key in produced:
            turn = turn_of_rid(boundaries, produced[key])
        else:
            turn = 0                                 # another session's
        nodes[key] = Node(key, kind, turn)

    # an edge whose knowledge endpoint was shadowed (`nodes[k]` is the receipt) goes with it
    edges = [(src, dst) for src, dst, k in pairs if src in nodes and dst in nodes and nodes[k].kind != "act"]
    return nodes, edges, current


def carry_from_store(conn: sqlite3.Connection, session_id: str, window: int = 1, *,
                     turn: Optional[int] = None) -> Carry:
    """`carry()` over `graph_from_store`, at the session's open turn unless `turn` is
    given (`turn=0` is not "the open turn": it is rejected by `cutoff`)."""
    nodes, edges, current = graph_from_store(conn, session_id)
    return carry(nodes, edges, current if turn is None else turn, window,
                 knowledge=set(common.KNOWLEDGE_KINDS))
