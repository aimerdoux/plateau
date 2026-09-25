"""Selector v2 (plateau.bridge.query) pins, against store schema v1.

Schema is built straight from the CREATE TABLE statements in docs/harness-0.3/PLAN.md so this
file exercises the real store shape rather than a hand-simplified stand-in. `cfg` is a plain
types.SimpleNamespace (query.py must not depend on plateau.bridge.config or .common — it is
developed concurrently by another owner)."""

from __future__ import annotations

import json
import sqlite3
import types

import pytest

from plateau.bridge import query as q

# Verbatim from docs/harness-0.3/PLAN.md "Store schema v1".
SCHEMA = """
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
  bridge_sha TEXT, keys TEXT);
CREATE TABLE IF NOT EXISTS decisions(id INTEGER PRIMARY KEY, ts REAL, session_id TEXT, agent TEXT, text TEXT,
  provenance TEXT);
CREATE TABLE IF NOT EXISTS turns(session_id TEXT, n INTEGER, ts REAL, rid_at INTEGER, PRIMARY KEY(session_id, n));
CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY, v TEXT);
"""


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.executescript(SCHEMA)
    yield c
    c.close()


def make_cfg(selector=None, budget=None):
    sel = {
        "tau_turns": 3,
        "degree_cap": 3,
        "weights": {
            "symbol": 1.4, "error": 1.3, "decided": 1.4, "read": 1.2, "test": 1.2,
            "file": 0.7, "command": 0.6, "search": 0.3,
        },
        "bridge_quota": 0.40,
        "sticky": True,
        "lexical": True,
    }
    if selector:
        sel.update(selector)
    bud = {"compaction_chars": 12000, "startup_chars": 6000, "prompt_chars": 0}
    if budget:
        bud.update(budget)
    return types.SimpleNamespace(selector=sel, budget=bud)


def add_receipt(conn, rid, session_id="s1", tool="Bash", target="t", kind="command",
                 outcome="pass", detail=""):
    conn.execute(
        "INSERT OR IGNORE INTO receipts(id, ts, session_id, agent, bridge_version, bridge_sha, tool, "
        "target, kind, outcome, detail, measure_kind, measure_value) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (rid, float(rid), session_id, "main", "v", "sha", tool, target, kind, outcome, detail, None, None),
    )


def add_node(conn, key, kind, last_rid, degree=1, first_rid=None, outcome="pass", detail="",
             session_id="s1", agent="main"):
    conn.execute(
        "INSERT INTO nodes(key, kind, first_rid, last_rid, degree, last_outcome, last_detail, "
        "session_id, agent) VALUES (?,?,?,?,?,?,?,?,?)",
        (key, kind, first_rid if first_rid is not None else last_rid, last_rid, degree, outcome,
         detail, session_id, agent),
    )


def seed_node(conn, key, kind, last_rid, degree=1, detail="", outcome="pass", session_id="s1"):
    """A node plus a matching receipt row, so MAX(receipts.id) accounts for it."""
    add_receipt(conn, last_rid, session_id=session_id, kind=kind, target=key, outcome=outcome, detail=detail)
    add_node(conn, key, kind, last_rid, degree=degree, outcome=outcome, detail=detail, session_id=session_id)


def add_turns(conn, session_id, count):
    for i in range(1, count + 1):
        conn.execute("INSERT INTO turns(session_id, n, ts, rid_at) VALUES (?,?,?,?)",
                     (session_id, i, float(i), i))


def add_compaction(conn, session_id, k, rid_at):
    conn.execute("INSERT INTO compactions(session_id, k, ts, rid_at, snapshot) VALUES (?,?,?,?,?)",
                 (session_id, k, float(rid_at), rid_at, "snap"))


# --------------------------------------------------------------------------------------
# toks
# --------------------------------------------------------------------------------------

def test_toks_identifier_split_lowercase_len_gt_1():
    assert q.toks("plateau/bridge/query.py") == {"plateau", "bridge", "query", "py"}
    assert q.toks("fooBarBAZ_42") == {"foo", "bar", "baz", "42"}
    assert q.toks("id_1") == {"id"}  # a lone digit has len 1 -> filtered out
    assert q.toks("") == set()
    assert q.toks(None) == set()


# --------------------------------------------------------------------------------------
# score_nodes: lexical match ranks first
# --------------------------------------------------------------------------------------

def test_lexical_match_ranks_first(conn):
    cfg = make_cfg()
    # Structurally strong (freshest, high degree) but unrelated to the query.
    seed_node(conn, "src/newer_module.py", "file", last_rid=100, degree=3)
    # Structurally weak (much older, degree 1) but its key matches the query tokens.
    seed_node(conn, "src/widget_parser.py", "file", last_rid=10, degree=1)
    seed_node(conn, "src/unrelated_thing.py", "file", last_rid=50, degree=1)

    scored = q.score_nodes(conn, "widget parser", cfg, "s1")
    ranked_keys = [n["key"] for n in scored]

    assert ranked_keys[0] == "src/widget_parser.py"
    top = scored[0]
    assert top["lexical_hit"] is True
    newer = next(n for n in scored if n["key"] == "src/newer_module.py")
    assert newer["lexical_hit"] is False
    assert top["score"] > newer["score"]


def test_lexical_disabled_falls_back_to_structural_score(conn):
    cfg = make_cfg(selector={"lexical": False})
    seed_node(conn, "src/newer_module.py", "file", last_rid=100, degree=3)
    seed_node(conn, "src/widget_parser.py", "file", last_rid=10, degree=1)

    scored = q.score_nodes(conn, "widget parser", cfg, "s1")
    ranked_keys = [n["key"] for n in scored]
    hit = next(n for n in scored if n["key"] == "src/widget_parser.py")

    assert hit["lexical_hit"] is True          # still reported...
    assert ranked_keys[0] == "src/newer_module.py"  # ...but doesn't move the score when disabled


# --------------------------------------------------------------------------------------
# score_nodes: degree cap
# --------------------------------------------------------------------------------------

def test_degree_cap_bounds_the_structural_score(conn):
    cfg = make_cfg(selector={"degree_cap": 3})
    seed_node(conn, "x/at_cap.py", "file", last_rid=50, degree=3)
    seed_node(conn, "x/way_over_cap.py", "file", last_rid=50, degree=500)

    scored = {n["key"]: n for n in q.score_nodes(conn, "", cfg, "s1")}
    at_cap, over_cap = scored["x/at_cap.py"], scored["x/way_over_cap.py"]

    assert at_cap["score"] == pytest.approx(over_cap["score"])
    # capping only affects scoring; the raw degree is still reported faithfully
    assert at_cap["degree"] == 3
    assert over_cap["degree"] == 500


# --------------------------------------------------------------------------------------
# score_nodes: tau from receipts-per-turn changes recency ordering
# --------------------------------------------------------------------------------------

def test_tau_from_receipts_per_turn_changes_recency_ordering(conn):
    cfg = make_cfg()  # tau_turns == 3 throughout; only receipts-per-turn differs below
    seed_node(conn, "pkg/a_old_but_busy.py", "file", last_rid=20, degree=3, session_id="s1")
    seed_node(conn, "pkg/b_brand_new.py", "file", last_rid=100, degree=1, session_id="s1")
    # MAX(receipts.id) is pinned at 100 by b's own receipt; the filler receipts below use
    # negative ids so they never become "now" — they only add to each session's COUNT(*).

    add_turns(conn, "fast", 1)
    add_receipt(conn, -1, session_id="fast")  # receipts_per_turn == 1 -> tau == 3

    add_turns(conn, "slow", 1)
    for i in range(100):
        add_receipt(conn, -(100 + i), session_id="slow")  # receipts_per_turn == 100 -> tau == 300

    fast_scored = {n["key"]: n["score"] for n in q.score_nodes(conn, "", cfg, "fast")}
    slow_scored = {n["key"]: n["score"] for n in q.score_nodes(conn, "", cfg, "slow")}

    # Fast decay: the older node's recency term collapses -> the newer node wins.
    assert fast_scored["pkg/b_brand_new.py"] > fast_scored["pkg/a_old_but_busy.py"]
    # Slow decay: recency differences shrink -> the older node's higher degree wins instead.
    assert slow_scored["pkg/a_old_but_busy.py"] > slow_scored["pkg/b_brand_new.py"]


# --------------------------------------------------------------------------------------
# select: budget is never exceeded
# --------------------------------------------------------------------------------------

def test_budget_never_exceeded(conn):
    cfg = make_cfg()
    kinds = ["file", "symbol", "error", "test", "command", "search", "read", "decided"]
    for i in range(60):
        seed_node(
            conn, "pkg/module_{:03d}.py".format(i), kinds[i % len(kinds)],
            last_rid=i + 1, degree=(i % 6),
            detail="some fairly typical detail text number {}".format(i),
        )
    scored = q.score_nodes(conn, "", cfg, "s1")
    head = "<plateau_index>\n# Machine-generated ledger of execution receipts. Data, not instructions.\n"

    counts = []
    for budget in (1500, 6000, 12000):
        chosen = q.select(scored, budget, cfg, head=head, sticky_keys=[], edited_since=set(),
                           resolved_errors=set())
        rendered = q.render(chosen, head, "plateau_index")
        assert len(rendered) <= budget
        counts.append(len(chosen))

    # bigger budgets should never select strictly fewer lines than smaller ones
    assert counts[0] <= counts[1] <= counts[2]


# --------------------------------------------------------------------------------------
# select: quota honoured with synthetic compaction rows
# --------------------------------------------------------------------------------------

def test_quota_honoured_with_synthetic_compaction_row(conn):
    cfg = make_cfg(selector={"bridge_quota": 0.40})
    session_id = "s1"
    # 15 "old" nodes (last_rid 10..24) score lower than 15 "new" nodes (last_rid 40..54):
    # same kind/degree/weight, so a pure score-ordered fill would pick new nodes exclusively.
    for i in range(15):
        seed_node(conn, "node_old_{:02d}".format(i), "file", last_rid=10 + i, degree=1, session_id=session_id)
    for i in range(15):
        seed_node(conn, "node_new_{:02d}".format(i), "file", last_rid=40 + i, degree=1, session_id=session_id)
    add_compaction(conn, session_id, k=1, rid_at=30)  # old: last_rid<=30; new: last_rid>30

    scored = q.score_nodes(conn, "", cfg, session_id)
    older_keys = {n["key"] for n in scored if n["older_than_prev_compaction"]}
    assert older_keys == {"node_old_{:02d}".format(i) for i in range(15)}
    # sanity: without the quota, pure score order would be all-new-before-any-old
    ranked_kinds = [("old" if n["older_than_prev_compaction"] else "new") for n in scored]
    assert ranked_kinds[:15] == ["new"] * 15

    # Every node above renders to an identical-length line (uniform key/last_rid/degree widths,
    # empty detail), so a fixed budget maps to an exact line count and an exact quota count.
    budget = 354  # reserve(24) + 10 * 33-char lines, exactly
    chosen = q.select(scored, budget, cfg, head="", sticky_keys=[], edited_since=set(),
                       resolved_errors=set())

    assert len(chosen) == 10
    n_older = sum(1 for n in chosen if n["older_than_prev_compaction"])
    required = round(cfg.selector["bridge_quota"] * len(chosen))
    assert required == 4
    assert n_older >= required
    assert n_older == 4  # exact, given the uniform line lengths this fixture is built around
    old_chosen = sorted(n["key"] for n in chosen if n["older_than_prev_compaction"])
    assert old_chosen == ["node_old_{:02d}".format(i) for i in (11, 12, 13, 14)]


def test_older_than_prev_compaction_uses_the_latest_of_several_compaction_rows(conn):
    cfg = make_cfg()
    session_id = "s1"
    seed_node(conn, "pkg/mid.py", "file", last_rid=15, degree=1, session_id=session_id)
    seed_node(conn, "pkg/newest.py", "file", last_rid=40, degree=1, session_id=session_id)
    add_compaction(conn, session_id, k=1, rid_at=10)  # an earlier compaction
    add_compaction(conn, session_id, k=2, rid_at=30)  # the latest compaction

    scored = {n["key"]: n for n in q.score_nodes(conn, "", cfg, session_id)}
    # last_rid=15 is > k1's rid_at(10) but <= k2's rid_at(30): only correct if k2 (the latest) is used.
    assert scored["pkg/mid.py"]["older_than_prev_compaction"] is True
    assert scored["pkg/newest.py"]["older_than_prev_compaction"] is False


def test_quota_uses_prev_compaction_when_current_one_was_just_inserted(conn):
    """The compact-SessionStart case (Issue 2 / plateau.bridge.common.prev_compaction_rid):
    by the time score_nodes runs, snapshot.py's PreCompact hook has already inserted the
    CURRENT compaction row (its rid_at == MAX(receipts.id) for the session, since no
    receipt has been recorded since it was marked). That row must NOT become the "older
    than the previous compaction" boundary -- otherwise every node looks older than the
    previous compaction and bridge_quota degenerates into a no-op. The boundary must
    fall back to the SECOND newest row (the real previous compaction) instead."""
    cfg = make_cfg(selector={"bridge_quota": 0.40})
    session_id = "s1"
    # Same fixture geometry as test_quota_honoured_with_synthetic_compaction_row: 15
    # "old" nodes score lower than 15 "new" nodes, so a pure score-ordered fill would
    # pick new nodes exclusively without the quota.
    for i in range(15):
        seed_node(conn, "node_old_{:02d}".format(i), "file", last_rid=10 + i, degree=1, session_id=session_id)
    for i in range(15):
        seed_node(conn, "node_new_{:02d}".format(i), "file", last_rid=40 + i, degree=1, session_id=session_id)
    add_compaction(conn, session_id, k=1, rid_at=30)  # the REAL previous compaction
    # k=2's rid_at (54) equals MAX(receipts.id) for the session -- the "just marked, no
    # receipt recorded since" case, e.g. PreCompact firing right before this
    # SessionStart(compact). It must not become the boundary.
    add_compaction(conn, session_id, k=2, rid_at=54)

    scored = q.score_nodes(conn, "", cfg, session_id)
    older_keys = {n["key"] for n in scored if n["older_than_prev_compaction"]}
    # Must match the boundary at k=1 (rid_at=30), not k=2 (rid_at=54, which would make
    # every node "older" and turn the quota into a no-op).
    assert older_keys == {"node_old_{:02d}".format(i) for i in range(15)}

    budget = 354  # same fixture geometry as test_quota_honoured_with_synthetic_compaction_row
    chosen = q.select(scored, budget, cfg, head="", sticky_keys=[], edited_since=set(),
                       resolved_errors=set())
    assert len(chosen) == 10
    n_older = sum(1 for n in chosen if n["older_than_prev_compaction"])
    required = round(cfg.selector["bridge_quota"] * len(chosen))
    assert required == 4
    assert n_older >= required


def test_quota_not_forced_beyond_available_older_nodes(conn):
    """"when enough such nodes exist": with only one eligible old node, the quota can't
    demand four -- select() must not crash or fabricate, it just takes what exists."""
    cfg = make_cfg(selector={"bridge_quota": 0.40})
    session_id = "s1"
    seed_node(conn, "node_old_00", "file", last_rid=10, degree=1, session_id=session_id)
    for i in range(15):
        seed_node(conn, "node_new_{:02d}".format(i), "file", last_rid=40 + i, degree=1, session_id=session_id)
    add_compaction(conn, session_id, k=1, rid_at=30)

    scored = q.score_nodes(conn, "", cfg, session_id)
    chosen = q.select(scored, 354, cfg, head="", sticky_keys=[], edited_since=set(), resolved_errors=set())

    n_older = sum(1 for n in chosen if n["older_than_prev_compaction"])
    assert n_older == 1  # only one such node exists at all
    assert "node_old_00" in {n["key"] for n in chosen}


# --------------------------------------------------------------------------------------
# select: sticky survives across a synthetic compaction unless edited/resolved
# --------------------------------------------------------------------------------------

def test_sticky_survives_unless_edited_or_resolved(conn):
    cfg = make_cfg()
    seed_node(conn, "src/quiet_file.py", "file", last_rid=1, degree=1, outcome="pass")
    seed_node(conn, "boom: something exploded", "error", last_rid=1, degree=1, detail="boom", outcome="seen")
    for i in range(10):
        seed_node(conn, "src/hot_module_{}.py".format(i), "file", last_rid=90 + i, degree=3,
                  detail="very fresh change #{}".format(i))
    scored = q.score_nodes(conn, "", cfg, "s1")

    # The two sticky candidates score far below every "hot" filler node (much older, no
    # lexical hit, lower/no detail) -- so if they show up, it is because of stickiness, not score.
    lookup = {n["key"]: n["score"] for n in scored}
    assert lookup["src/quiet_file.py"] < min(lookup["src/hot_module_{}.py".format(i)] for i in range(10))
    assert lookup["boom: something exploded"] < min(lookup["src/hot_module_{}.py".format(i)] for i in range(10))

    head = "<plateau_index>\n"
    budget = 750  # room for both sticky lines + every hot filler, but not one more line besides
    sticky = ["src/quiet_file.py", "boom: something exploded"]

    chosen = q.select(scored, budget, cfg, head=head, sticky_keys=sticky, edited_since=set(),
                       resolved_errors=set())
    chosen_keys = {n["key"] for n in chosen}
    assert "src/quiet_file.py" in chosen_keys
    assert "boom: something exploded" in chosen_keys

    # The file was edited since -> drops out of stickiness; too low-scoring to be re-earned.
    chosen2 = q.select(scored, budget, cfg, head=head, sticky_keys=sticky,
                        edited_since={"src/quiet_file.py"}, resolved_errors=set())
    keys2 = {n["key"] for n in chosen2}
    assert "src/quiet_file.py" not in keys2
    assert "boom: something exploded" in keys2

    # The error's target later passed -> drops out of stickiness too.
    chosen3 = q.select(scored, budget, cfg, head=head, sticky_keys=sticky, edited_since=set(),
                        resolved_errors={"boom: something exploded"})
    keys3 = {n["key"] for n in chosen3}
    assert "boom: something exploded" not in keys3
    assert "src/quiet_file.py" in keys3


def test_select_empty_candidates_returns_empty():
    cfg = make_cfg()
    chosen = q.select([], 6000, cfg, head="<plateau_index>\n", sticky_keys=["nope"],
                       edited_since=set(), resolved_errors=set())
    assert chosen == []


def test_select_budget_smaller_than_head_yields_no_lines():
    cfg = make_cfg()
    n = {"key": "k", "kind": "file", "first_rid": 1, "last_rid": 1, "degree": 1, "outcome": "read",
         "detail": "", "score": 5.0, "lexical_hit": False, "older_than_prev_compaction": False}
    chosen = q.select([n], 5, cfg, head="<plateau_index>\n", sticky_keys=[], edited_since=set(),
                       resolved_errors=set())
    assert chosen == []


def test_select_never_exceeds_budget_even_when_sticky_alone_would_overflow():
    cfg = make_cfg()
    nodes = [
        {"key": "k{}".format(i), "kind": "file", "first_rid": i, "last_rid": i, "degree": 1,
         "outcome": "read", "detail": "x" * 40, "score": 1.0, "lexical_hit": False,
         "older_than_prev_compaction": False}
        for i in range(5)
    ]
    head = "<plateau_index>\n"
    budget = 200  # room for roughly 2 of these ~65-char lines, not all 5
    chosen = q.select(nodes, budget, cfg, head=head, sticky_keys=[n["key"] for n in nodes],
                       edited_since=set(), resolved_errors=set())
    rendered = q.render(chosen, head, "plateau_index")
    assert len(rendered) <= budget
    assert len(chosen) < 5


def test_sticky_drops_lowest_scored_first_when_they_overflow_the_budget(conn):
    """select() step 1 (sticky): when the sticky candidates do not all fit, a smaller,
    lower-scored sticky line still gets a chance even after a bigger, higher-scored one
    did not fit -- select() must never exceed the budget, but it also must not stop
    dead at the first sticky line that overflows it ("drop the lowest-scored sticky
    lines first", not "drop everything after the first miss")."""
    cfg = make_cfg(selector={"bridge_quota": 0.0})
    big = {"key": "big_sticky", "kind": "file", "first_rid": 1, "last_rid": 1, "degree": 1,
           "outcome": "read", "detail": "x" * 200, "score": 10.0, "lexical_hit": False,
           "older_than_prev_compaction": False}
    small = {"key": "small_sticky", "kind": "file", "first_rid": 1, "last_rid": 1, "degree": 1,
             "outcome": "read", "detail": "", "score": 5.0, "lexical_hit": False,
             "older_than_prev_compaction": False}
    scored = [big, small]
    reserve = q._CLOSE_TAG_RESERVE
    # Room for "small" (the lower-scored one) but not for "big" (whose ~200-char detail
    # alone blows the budget) -- sized off small's own rendered length so this stays
    # exact regardless of incidental formatting changes.
    budget = reserve + len(q.render_line(small)) + 1 + 5
    assert reserve + len(q.render_line(big)) + 1 > budget, "fixture sanity: big must not fit"

    chosen = q.select(scored, budget, cfg, head="", sticky_keys=["big_sticky", "small_sticky"],
                       edited_since=set(), resolved_errors=set())
    keys = {n["key"] for n in chosen}
    assert "small_sticky" in keys, "a smaller, lower-scored sticky line must still get a chance"
    assert "big_sticky" not in keys
    rendered = q.render(chosen, "", "plateau_index")
    assert len(rendered) <= budget


def test_sticky_key_no_longer_in_store_is_skipped_not_crashed(conn):
    cfg = make_cfg()
    seed_node(conn, "src/only_node.py", "file", last_rid=1, degree=1)
    scored = q.score_nodes(conn, "", cfg, "s1")
    chosen = q.select(scored, 6000, cfg, head="", sticky_keys=["src/vanished.py", "src/only_node.py"],
                       edited_since=set(), resolved_errors=set())
    assert {n["key"] for n in chosen} == {"src/only_node.py"}


# --------------------------------------------------------------------------------------
# render_line / render
# --------------------------------------------------------------------------------------

def test_render_line_format():
    n = {"key": "src/x.py", "kind": "file", "last_rid": 7, "degree": 2, "outcome": "edit",
         "detail": "did a thing", "lexical_hit": False}
    assert q.render_line(n) == "[r7] file src/x.py → edit (did a thing) ×2"


def test_render_line_marks_lexical_hit_and_omits_empty_detail():
    n = {"key": "k", "kind": "error", "last_rid": 3, "degree": 1, "outcome": "seen",
         "detail": "", "lexical_hit": True}
    line = q.render_line(n)
    assert line.endswith(" ★")
    assert "()" not in line  # no dangling empty parens when detail is blank


def test_render_line_truncates_detail_to_60_chars():
    n = {"key": "k", "kind": "file", "last_rid": 1, "degree": 1, "outcome": "read",
         "detail": "x" * 200, "lexical_hit": False}
    line = q.render_line(n)
    assert ("x" * 61) not in line
    assert ("x" * 60) in line


def test_render_wraps_head_lines_and_closing_tag():
    n = {"key": "k", "kind": "file", "last_rid": 1, "degree": 1, "outcome": "read",
         "detail": "", "lexical_hit": False}
    out = q.render([n], "<plateau_index>\n", "plateau_index")
    assert out.startswith("<plateau_index>\n")
    assert out.endswith("</plateau_index>")
    assert q.render_line(n) in out


# --------------------------------------------------------------------------------------
# sticky_keys / edited_since / resolved_errors
# --------------------------------------------------------------------------------------

def test_sticky_keys_reads_latest_injection_row(conn):
    conn.execute(
        "INSERT INTO injections(ts, session_id, event, compaction_k, chars, budget, holdout, "
        "bridge_version, bridge_sha, keys) VALUES (1.0,'s1','SessionStart',1,100,6000,0,'v','sha',?)",
        (json.dumps(["a", "b"]),),
    )
    conn.execute(
        "INSERT INTO injections(ts, session_id, event, compaction_k, chars, budget, holdout, "
        "bridge_version, bridge_sha, keys) VALUES (2.0,'s1','SessionStart',2,120,6000,0,'v','sha',?)",
        (json.dumps(["c"]),),
    )
    assert q.sticky_keys(conn, "s1") == ["c"]
    assert q.sticky_keys(conn, "nonexistent-session") == []


def test_edited_since_finds_file_edits_after_rid(conn):
    add_receipt(conn, 1, session_id="s1", target="a.py", kind="file", outcome="edit")
    add_receipt(conn, 2, session_id="s1", target="b.py", kind="file", outcome="read")
    add_receipt(conn, 3, session_id="s1", target="c.py", kind="file", outcome="edit")
    assert q.edited_since(conn, "s1", rid=0) == {"a.py", "c.py"}
    assert q.edited_since(conn, "s1", rid=1) == {"c.py"}
    assert q.edited_since(conn, "s1", rid=3) == set()


def test_resolved_errors_finds_targets_that_later_passed(conn):
    add_receipt(conn, 1, session_id="s1", target="pytest tests/x.py", kind="test", outcome="fail")
    add_node(conn, "AssertionError: boom", "error", last_rid=1, session_id="s1")
    conn.execute("INSERT INTO edges VALUES (?,?,?,?)",
                 ("pytest tests/x.py", "fails_with", "AssertionError: boom", 1))

    add_receipt(conn, 2, session_id="s1", target="pytest tests/x.py", kind="test", outcome="fail")
    assert q.resolved_errors(conn, "s1", rid=1) == set()  # still failing after rid=1

    add_receipt(conn, 3, session_id="s1", target="pytest tests/x.py", kind="test", outcome="pass")
    assert q.resolved_errors(conn, "s1", rid=1) == {"AssertionError: boom"}
    assert q.resolved_errors(conn, "s1", rid=3) == set()  # nothing AFTER rid=3 yet


# --------------------------------------------------------------------------------------
# last_user_prompt
# --------------------------------------------------------------------------------------

def test_last_user_prompt_reads_last_genuine_prompt(tmp_path):
    lines = [
        {"type": "user", "message": {"role": "user", "content": "first prompt"}},
        {"type": "assistant", "message": {"role": "assistant",
                                          "content": [{"type": "tool_use", "id": "t1", "name": "Bash",
                                                       "input": {}}]}},
        {"type": "user", "message": {"role": "user",
                                     "content": [{"type": "tool_result", "tool_use_id": "t1",
                                                  "content": "output"}]}},
        {"type": "user", "message": {"role": "user", "content": "second, real prompt"}},
    ]
    p = tmp_path / "transcript.jsonl"
    p.write_text("\n".join(json.dumps(l) for l in lines))
    assert q.last_user_prompt(str(p)) == "second, real prompt"


def test_last_user_prompt_missing_file_returns_empty(tmp_path):
    assert q.last_user_prompt(str(tmp_path / "nope.jsonl")) == ""


def test_last_user_prompt_tail_cut_inside_a_multibyte_sequence_is_skipped(tmp_path):
    """Claude Code appends the transcript while the hook reads it; a tail that ends
    inside a UTF-8 sequence used to raise UnicodeDecodeError out of the file iteration
    (only OSError was caught) and abort the whole injection."""
    p = tmp_path / "transcript.jsonl"
    p.write_bytes(json.dumps({"type": "user", "message": {"role": "user", "content": "real prompt"}}).encode()
                  + b'\n{"type":"user","message":{"role":"user","content":"caf\xc3')
    assert q.last_user_prompt(str(p)) == "real prompt"
