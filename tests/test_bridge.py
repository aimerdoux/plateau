"""tests/test_bridge.py — owner A4 (docs/harness-0.3/PLAN.md "Tests").

Two things live here:

1. A mechanical port of every check in `d037_hooks/test_hooks.py` (the sealed D-037
   offline harness), retargeted at the new `plateau.bridge` package instead of the
   `d037_hooks/` shims: the `<plateau_index>` tag instead of `<d037_index>`,
   `PLATEAU_DB_REL` left unset (so the store lands at the public `.plateau/` layout
   instead of `.d037/`), and a temp root this file `git init`s itself (the hooks
   resolve their store root via `git rev-parse --show-toplevel` of the payload's
   `cwd`; see `plateau.bridge.common.root`).
2. The extensions PLAN.md's "Tests" section lists on top of that port: the bridge
   quota, sticky lines across synthetic compactions, read/decided nodes, lexical
   ranking, budget enforcement at 12000/6000/1500, holdout determinism and rate,
   concurrent writers, the handoff JSON round-trip, `<d037_index>` acceptance on the
   legacy path, config resolution (incumbent/canary/off), the fallback TOML parser
   against `tomllib`, and provenance columns on every receipt/injection row.

Every hook invocation here goes through a real subprocess (`python -m
plateau.bridge.<name>`), the same way `d037_hooks/test_hooks.py` subprocesses the
`d037_hooks/*.py` scripts — this file never imports `plateau.bridge.receipt` /
`snapshot` / `inject` directly and calls their `main()` in-process, so a hook that
would only misbehave as an actual separate process (argv parsing, stdin/stdout
framing, on-disk paths) is exercised the same way it runs for real.
"""

from __future__ import annotations

import hashlib
import json
import os
import random
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import types
from typing import Any, Dict, List, Optional, Set, Tuple

import pytest

from plateau.bridge import common
from plateau.bridge import config as bridge_config
from plateau.bridge import query as query_mod
from plateau.bridge import handoff as handoff_mod
from plateau.bridge import _toml as bridge_toml
from plateau.lab import holdout

try:
    import tomllib as _tomllib  # Python >= 3.11
except ImportError:  # pragma: no cover - exercised on 3.9/3.10
    _tomllib = None

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ============================================================================
# Shared helpers
# ============================================================================

def make_root() -> str:
    return tempfile.mkdtemp(prefix="plateau-bridge-test-")


def git_init(root: str) -> str:
    subprocess.run(["git", "init", "-q", root], capture_output=True, text=True, timeout=10)
    return root


@pytest.fixture
def scratch_root():
    """A plain temp directory (no git needed: nothing in these tests that uses it
    calls `common.root()` / `git rev-parse`)."""
    root = make_root()
    try:
        yield root
    finally:
        shutil.rmtree(root, ignore_errors=True)


def _db_path(root: str) -> str:
    return os.path.join(root, common.DB_REL)


def _snapshots_dir(root: str) -> str:
    return os.path.join(root, os.path.dirname(common.DB_REL) or ".plateau", "snapshots")


def _clean_subprocess_env() -> Dict[str, str]:
    """Env for subprocess hook invocations: the repo root importable on PYTHONPATH,
    and no legacy env overrides leaking in from the outer test process (PLAN.md's
    'PLATEAU_DB_REL unset' -- and PLATEAU_LOG_REL / PLATEAU_LEGACY_TAG / PLATEAU_AGENT
    with it, so nothing ambient can quietly retarget these hooks at `.d037/`)."""
    env = dict(os.environ)
    env["PYTHONPATH"] = REPO_ROOT + os.pathsep + env.get("PYTHONPATH", "")
    for k in ("PLATEAU_LEGACY_TAG", "PLATEAU_DB_REL", "PLATEAU_LOG_REL", "PLATEAU_AGENT"):
        env.pop(k, None)
    return env


def run_hook(module: str, payload: dict, root: str, extra_env: Optional[dict] = None,
             argv: Optional[List[str]] = None) -> Tuple[str, str, int]:
    """`python -m <module> [argv...]` with `payload` piped as JSON on stdin, cwd=root."""
    env = _clean_subprocess_env()
    if extra_env:
        env.update(extra_env)
    cmd = [sys.executable, "-m", module] + list(argv or [])
    proc = subprocess.run(cmd, input=json.dumps(payload), cwd=root, env=env,
                          capture_output=True, text=True, timeout=30)
    return proc.stdout, proc.stderr, proc.returncode


def _resolve_lab(root: str, probe_session: str = "lab-probe") -> Dict[str, float]:
    cfg = bridge_config.load(root, probe_session)
    return {
        "holdout_rate": float(cfg.lab.get("holdout_rate", 0.10)),
        "canary_share": float(cfg.lab.get("canary_share", 0.0)),
    }


def _non_holdout_session_id(root: str, ks, prefix: str = "sess", tries: int = 1000) -> str:
    """A session_id for which `holdout.is_holdout(session_id, k, rate)` is False for
    every k in `ks`, against this root's *actual* resolved holdout_rate (never
    hard-coded), so a test that isn't about holdout doesn't accidentally collide with
    it."""
    rate = _resolve_lab(root)["holdout_rate"]
    for i in range(tries):
        candidate = "{}-{}".format(prefix, i)
        if all(not holdout.is_holdout(candidate, k, rate) for k in ks):
            return candidate
    raise AssertionError("could not find a non-holdout session id; is holdout_rate 1.0?")


def _holdout_session_id(root: str, k: int, prefix: str = "hsess", tries: int = 1000) -> str:
    rate = _resolve_lab(root)["holdout_rate"]
    for i in range(tries):
        candidate = "{}-{}".format(prefix, i)
        if holdout.is_holdout(candidate, k, rate):
            return candidate
    raise AssertionError("could not find a holdout session id; is holdout_rate 0.0?")


# --- raw store fixtures (schema v1, same technique as tests/test_selector.py) --------

def _add_receipt(conn: sqlite3.Connection, rid: int, session_id: str = "s1", agent: str = "main",
                  bridge_version: str = "2.0", bridge_sha: str = "deadbeef", tool: str = "Bash",
                  target: str = "t", kind: str = "command", outcome: str = "pass",
                  detail: str = "", ts: Optional[float] = None) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO receipts(id,ts,session_id,agent,bridge_version,bridge_sha,tool,"
        "target,kind,outcome,detail,measure_kind,measure_value) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (rid, ts if ts is not None else float(rid), session_id, agent, bridge_version, bridge_sha,
         tool, target, kind, outcome, detail, None, None),
    )
    conn.commit()


def _add_node(conn: sqlite3.Connection, key: str, kind: str, last_rid: int, degree: int = 1,
              first_rid: Optional[int] = None, outcome: str = "pass", detail: str = "",
              session_id: str = "s1", agent: str = "main") -> None:
    conn.execute(
        "INSERT INTO nodes(key,kind,first_rid,last_rid,degree,last_outcome,last_detail,"
        "session_id,agent) VALUES(?,?,?,?,?,?,?,?,?)",
        (key, kind, first_rid if first_rid is not None else last_rid, last_rid, degree,
         outcome, detail, session_id, agent),
    )
    conn.commit()


def _add_compaction(conn: sqlite3.Connection, session_id: str, k: int, rid_at: int,
                     snapshot: str = "snap") -> None:
    conn.execute(
        "INSERT INTO compactions(session_id,k,ts,rid_at,snapshot) VALUES(?,?,?,?,?)",
        (session_id, k, float(k), rid_at, snapshot),
    )
    conn.commit()


# ============================================================================
# 1) Port of d037_hooks/test_hooks.py -> plateau.bridge / <plateau_index>
# ============================================================================

def fake_calls(seed: int, n: int = 120) -> List[Tuple[str, dict, Any]]:
    """Mechanical port of d037_hooks/test_hooks.py's fake_calls(): same statistical
    mix of Read/Edit/Bash/Grep calls, so plateau.bridge.common.classify() is put
    through the same paces the sealed D-037 classify() was (its base rules are kept
    verbatim; see plateau/bridge/common.py's module docstring)."""
    random.seed(seed)
    calls: List[Tuple[str, dict, Any]] = []
    files = ["bridge_target/mod{}.py".format(i) for i in range(6)]
    for i in range(n):
        k = random.random()
        if k < 0.45:
            calls.append(("Read", {"file_path": random.choice(files)},
                          {"output": "def x(): pass\n" * 200}))
        elif k < 0.75:
            f = random.choice(files)
            name = "RATE_LIMIT_{}".format(i) if i % 7 == 0 else "helper_{}".format(i)
            calls.append((
                "Edit",
                {"file_path": f, "old_string": "pass",
                 "new_string": "{0} = 42\ndef {1}_fn():\n    return {0}".format(name, name.lower())},
                {"filePath": f, "success": True},
            ))
        elif k < 0.9:
            fail = random.random() < 0.4
            calls.append((
                "Bash", {"command": "pytest -q bridge_target"},
                {"exitCode": 1 if fail else 0,
                 "output": ("FAILED bridge_target/test_a.py::test_b - AssertionError: expected 42\n1 failed"
                            if fail else "12 passed")},
            ))
        else:
            calls.append(("Grep", {"pattern": "RATE_LIMIT"}, {"output": "mod1.py:3"}))
    return calls


def fake_transcript(path: str, calls: List[Tuple[str, dict, Any]]) -> None:
    """Mechanical port of d037_hooks/test_hooks.py's fake_transcript()."""
    with open(path, "w") as f:
        for i, (tool, tin, resp) in enumerate(calls):
            uid = "toolu_{:04d}".format(i)
            f.write(json.dumps({"type": "assistant", "message": {"role": "assistant", "content": [
                {"type": "text", "text": "IGNORE ME: prose that must not become a node"},
                {"type": "tool_use", "id": uid, "name": tool, "input": tin}]}}) + "\n")
            f.write(json.dumps({"type": "user", "message": {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": uid, "content": "ok"}]}, "toolUseResult": resp}) + "\n")


def _check_inject(out: str, budget: int, label: str) -> str:
    """Port of d037_hooks/test_hooks.py's check_inject(), retargeted at <plateau_index>."""
    j = json.loads(out)
    ctx = j["hookSpecificOutput"]["additionalContext"]
    assert j["hookSpecificOutput"]["hookEventName"] == "SessionStart"
    assert len(ctx) <= budget, "{}: {} > {}".format(label, len(ctx), budget)
    assert ctx.startswith("<{}>".format(common.TAG)) and ctx.endswith("</{}>".format(common.TAG))
    assert "[r" in ctx and "IGNORE ME" not in ctx
    return ctx


def _run_arm(arm: str, root: str, session_id: str, calls: List[Tuple[str, dict, Any]]) -> Dict[str, Any]:
    """Arm 'C': online -- one PostToolUse per call via plateau.bridge.receipt, then a
    PreCompact via plateau.bridge.snapshot (port of the original arm C).
    Arm 'B': one batch rebuild from the transcript via common.rebuild_from_transcript
    (port of the original arm B's ledger.py -- PLAN.md is explicit that there is no
    standalone `plateau.bridge.ledger` hook module, "rebuild from a transcript" is a
    common.py function; d037_hooks/ledger.py's own shim calls it the same way,
    in-process, rather than delegating to some other module's main())."""
    transcript_path = os.path.join(root, "t.jsonl")
    fake_transcript(transcript_path, calls)
    base_payload = {"cwd": root, "session_id": session_id, "transcript_path": transcript_path}

    if arm == "C":
        for tool, tin, resp in calls:
            payload = dict(base_payload, hook_event_name="PostToolUse", tool_name=tool,
                           tool_input=tin, tool_response=resp)
            _out, err, rc = run_hook("plateau.bridge.receipt", payload, root)
            assert not err and rc == 0, err
        _out, err, rc = run_hook(
            "plateau.bridge.snapshot",
            dict(base_payload, hook_event_name="PreCompact", trigger="auto"),
            root,
        )
        assert not err and rc == 0, err
        snap_dir = _snapshots_dir(root)
        assert os.path.isdir(snap_dir) and os.listdir(snap_dir), "no snapshot"
    else:
        cfg = bridge_config.load(root, session_id)
        conn = common.db(root)
        common.rebuild_from_transcript(
            conn, transcript_path, session_id=session_id, agent=common.agent_of({}),
            bridge_version=cfg.version, bridge_sha=cfg.sha, root=root,
        )
        conn.close()

    return base_payload


def test_ported_d037_hooks_suite():
    """Direct port of d037_hooks/test_hooks.py's whole per-arm loop plus its final
    B-equiv-C convergence assertion, at plateau.bridge / <plateau_index>,
    PLATEAU_DB_REL unset, a git-init'd temp root per arm -- with the provenance
    extension (every receipt/injection row carries bridge_version/bridge_sha) folded
    in inline, the way it naturally falls out of re-running the same checks."""
    calls = fake_calls(37)
    roots: Dict[str, str] = {}
    conns: Dict[str, sqlite3.Connection] = {}
    try:
        for arm in ("C", "B"):
            root = git_init(make_root())
            roots[arm] = root
            session_id = _non_holdout_session_id(root, (0,), prefix="port" + arm)
            base_payload = _run_arm(arm, root, session_id, calls)

            conn = sqlite3.connect(_db_path(root))
            conns[arm] = conn
            n_r = conn.execute("SELECT COUNT(*) FROM receipts").fetchone()[0]
            n_sym = conn.execute("SELECT COUNT(*) FROM nodes WHERE kind='symbol'").fetchone()[0]
            n_err = conn.execute("SELECT COUNT(*) FROM nodes WHERE kind='error'").fetchone()[0]
            assert n_r == len(calls), (arm, n_r, len(calls))
            assert n_sym > 0 and n_err > 0

            for version, sha in conn.execute("SELECT bridge_version, bridge_sha FROM receipts"):
                assert version, (arm, "receipt row missing bridge_version")
                assert sha, (arm, "receipt row missing bridge_sha")

            ctx = None
            for budget in (6000, 1500):
                out, err, rc = run_hook(
                    "plateau.bridge.inject",
                    dict(base_payload, hook_event_name="SessionStart", source="compact"),
                    root, argv=["--budget", str(budget)],
                )
                assert not err and rc == 0, (arm, budget, err)
                ctx = _check_inject(out, budget, "{}@{}".format(arm, budget))
            assert ctx is not None

            out, _err, rc = run_hook(
                "plateau.bridge.inject",
                dict(base_payload, hook_event_name="SessionStart", source="resume"),
                root,
            )
            assert rc == 0
            assert json.loads(out) == {}

            inj_rows = conn.execute("SELECT bridge_version, bridge_sha FROM injections").fetchall()
            assert inj_rows, (arm, "no injections rows recorded")
            for version, sha in inj_rows:
                assert version and sha, (arm, "injection row missing provenance")

        q = "SELECT key, kind, degree, last_outcome FROM nodes ORDER BY key"
        assert conns["B"].execute(q).fetchall() == conns["C"].execute(q).fetchall(), \
            "B and C stores diverge"
    finally:
        for conn in conns.values():
            conn.close()
        for root in roots.values():
            shutil.rmtree(root, ignore_errors=True)


# ============================================================================
# 2) Budgets respected at 12000 / 6000 / 1500
# ============================================================================

def test_budgets_respected():
    root = git_init(make_root())
    try:
        calls = fake_calls(101, n=120)
        session_id = _non_holdout_session_id(root, (0,), prefix="budgets")
        base_payload = _run_arm("C", root, session_id, calls)
        for budget in (12000, 6000, 1500):
            out, err, rc = run_hook(
                "plateau.bridge.inject",
                dict(base_payload, hook_event_name="SessionStart", source="compact"),
                root, argv=["--budget", str(budget)],
            )
            assert not err and rc == 0, (budget, err)
            ctx = _check_inject(out, budget, "budget={}".format(budget))
            assert "[r" in ctx
    finally:
        shutil.rmtree(root, ignore_errors=True)


# ============================================================================
# 3) Quota honoured
# ============================================================================

def test_quota_honoured(scratch_root):
    """select()'s bridge_quota reserves budget for nodes older than the previous
    compaction, so a burst of very recent, high-scoring activity cannot starve them
    out (PLAN.md 'Selector v2', select() step 2)."""
    root = scratch_root
    conn = common.db(root)
    session_id = "quota-sess"
    for rid in range(1, 21):
        _add_receipt(conn, rid, session_id=session_id, target="r{}".format(rid))
    _add_compaction(conn, session_id, 0, rid_at=10)

    for i in range(8):
        _add_node(conn, "old_{}.py".format(i), "file", last_rid=5, degree=1, session_id=session_id)
    for i in range(8):
        _add_node(conn, "new_sym_{}".format(i), "symbol", last_rid=20, degree=1, session_id=session_id)

    cfg = bridge_config.load(root, session_id)
    scored = query_mod.score_nodes(conn, "", cfg, session_id)
    old_nodes = [n for n in scored if n["key"].startswith("old_")]
    new_nodes = [n for n in scored if n["key"].startswith("new_sym_")]
    assert len(old_nodes) == 8 and len(new_nodes) == 8
    assert all(n["older_than_prev_compaction"] for n in old_nodes)
    assert not any(n["older_than_prev_compaction"] for n in new_nodes)
    assert min(n["score"] for n in new_nodes) > max(n["score"] for n in old_nodes), (
        "fixture sanity: every 'new' node must plainly outscore every 'old' one"
    )

    full_text = query_mod.render(sorted(scored, key=lambda n: n["score"], reverse=True),
                                 head="", tag=common.TAG)
    budget = len(full_text) // 2

    cfg.selector["bridge_quota"] = 0.0
    chosen_no_quota = query_mod.select(scored, budget, cfg, head="", sticky_keys=[],
                                       edited_since=set(), resolved_errors=set())
    older_no_quota = sum(1 for n in chosen_no_quota if n["older_than_prev_compaction"])

    cfg.selector["bridge_quota"] = 0.5
    chosen_with_quota = query_mod.select(scored, budget, cfg, head="", sticky_keys=[],
                                         edited_since=set(), resolved_errors=set())
    older_with_quota = sum(1 for n in chosen_with_quota if n["older_than_prev_compaction"])

    assert len(chosen_no_quota) < 16, "fixture sanity: budget must not fit every node"
    assert older_with_quota > older_no_quota, "bridge_quota did not reserve room for older nodes"
    assert older_with_quota >= 2
    for n in chosen_no_quota + chosen_with_quota:
        assert len(query_mod.render_line(n)) + 1 <= budget
    conn.close()


# ============================================================================
# 4) Sticky lines across two synthetic compactions
# ============================================================================

def test_sticky_across_two_compactions():
    """End to end: a line injected at compaction k=0 is re-injected at k=1 when
    nothing invalidates it (PLAN.md select() step 1)."""
    root = git_init(make_root())
    try:
        session_id = _non_holdout_session_id(root, (0, 1), prefix="sticky")
        transcript_path = os.path.join(root, "t.jsonl")
        seed_calls: List[Tuple[str, dict, Any]] = [
            ("Read", {"file_path": "keepme.py"}, {"output": "def keepme(): pass\n"}),
            ("Edit", {"file_path": "keepme.py", "old_string": "pass",
                      "new_string": "def keepme():\n    return 1\ndef ANOTHER_ONE(): pass\n"},
             {"filePath": "keepme.py", "success": True}),
            ("Bash", {"command": "pytest -q"},
             {"exitCode": 1, "output": "FAILED test_x.py::test_y - AssertionError\n1 failed"}),
        ]
        fake_transcript(transcript_path, seed_calls)
        base = {"cwd": root, "session_id": session_id, "transcript_path": transcript_path}
        for tool, tin, resp in seed_calls:
            _out, err, rc = run_hook(
                "plateau.bridge.receipt",
                dict(base, hook_event_name="PostToolUse", tool_name=tool, tool_input=tin,
                     tool_response=resp),
                root,
            )
            assert not err and rc == 0, err

        # --- compaction k=0 ---------------------------------------------------------
        _out, err, rc = run_hook(
            "plateau.bridge.snapshot", dict(base, hook_event_name="PreCompact", trigger="auto"), root,
        )
        assert not err and rc == 0, err
        out0, err, rc = run_hook(
            "plateau.bridge.inject", dict(base, hook_event_name="SessionStart", source="compact"), root,
        )
        assert not err and rc == 0, err
        _check_inject(out0, 12000, "k0")

        conn = sqlite3.connect(_db_path(root))
        keys0 = json.loads(conn.execute(
            "SELECT keys FROM injections WHERE session_id=? ORDER BY id DESC LIMIT 1", (session_id,)
        ).fetchone()[0])
        assert "keepme.py" in keys0

        # --- compaction k=1: nothing edited/resolved -> keepme.py must still show ----
        _out, err, rc = run_hook(
            "plateau.bridge.snapshot", dict(base, hook_event_name="PreCompact", trigger="auto"), root,
        )
        assert not err and rc == 0, err
        out1, err, rc = run_hook(
            "plateau.bridge.inject", dict(base, hook_event_name="SessionStart", source="compact"), root,
        )
        assert not err and rc == 0, err
        ctx1 = _check_inject(out1, 12000, "k1")
        assert "keepme.py" in ctx1, "sticky line dropped though nothing invalidated it"

        # --- keepme.py gets edited: it must no longer be eligible via stickiness -----
        edit2 = ("Edit", {"file_path": "keepme.py", "old_string": "return 1", "new_string": "return 2"},
                {"filePath": "keepme.py", "success": True})
        _out, err, rc = run_hook(
            "plateau.bridge.receipt",
            dict(base, hook_event_name="PostToolUse", tool_name=edit2[0], tool_input=edit2[1],
                 tool_response=edit2[2]),
            root,
        )
        assert not err and rc == 0, err
        _out, err, rc = run_hook(
            "plateau.bridge.snapshot", dict(base, hook_event_name="PreCompact", trigger="auto"), root,
        )
        assert not err and rc == 0, err
        out2, err, rc = run_hook(
            "plateau.bridge.inject", dict(base, hook_event_name="SessionStart", source="compact"), root,
        )
        assert not err and rc == 0, err
        _check_inject(out2, 12000, "k2")

        # The re-edited file may still be selected on pure score merit (it is now the
        # most recently touched file) -- what actually matters is the *mechanism*:
        # it is no longer coming back for free via stickiness, checked directly.
        conn2 = sqlite3.connect(_db_path(root))
        rows = conn2.execute(
            "SELECT rid_at FROM compactions WHERE session_id=? ORDER BY k DESC LIMIT 2", (session_id,)
        ).fetchall()
        prev_rid = rows[-1][0]
        edited = query_mod.edited_since(conn2, session_id, prev_rid)
        assert "keepme.py" in edited
        conn.close()
        conn2.close()
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_sticky_survives_or_drops_by_key_kind():
    """Precise unit-level pin of select() step 1: a sticky key whose OWN score would
    not have earned it a spot is re-admitted unless it is an edited file / a resolved
    error, in which case it is not, even though it was in `sticky_keys`."""
    cfg = types.SimpleNamespace(selector={
        "weights": {"file": 0.7, "error": 1.3, "symbol": 1.4},
        "degree_cap": 3, "bridge_quota": 0.0, "sticky": True, "lexical": False,
    })
    low_file = {"key": "a_file.py", "kind": "file", "first_rid": 1, "last_rid": 1, "degree": 1,
               "outcome": "read", "detail": "", "score": 0.01, "lexical_hit": False,
               "older_than_prev_compaction": False}
    low_err = {"key": "boom Error", "kind": "error", "first_rid": 1, "last_rid": 1, "degree": 1,
              "outcome": "seen", "detail": "", "score": 0.02, "lexical_hit": False,
              "older_than_prev_compaction": False}
    hot = {"key": "hot_symbol", "kind": "symbol", "first_rid": 5, "last_rid": 5, "degree": 3,
          "outcome": "defined", "detail": "", "score": 99.0, "lexical_hit": False,
          "older_than_prev_compaction": False}
    scored = [low_file, low_err, hot]
    # select() reserves `len(head) + <closing-tag allowance>` chars up front (it is
    # given `head` but never the tag itself; see plateau/bridge/query.py); head="" here,
    # so that reserve is exactly `_CLOSE_TAG_RESERVE`. Re-reading it (rather than
    # guessing a number) keeps this test's budget math exact regardless of the tags
    # a future version might reserve room for.
    reserve = query_mod._CLOSE_TAG_RESERVE

    # Scenario 1: a budget that comfortably fits both low-scoring sticky lines. Their
    # own score (0.01 / 0.02) is nowhere near enough to win a spot via a plain
    # score-ordered fill (`hot` alone scores 99.0), so their presence here can only be
    # explained by stickiness.
    budget_sticky = (
        reserve + len(query_mod.render_line(low_file)) + 1
        + len(query_mod.render_line(low_err)) + 1 + 10
    )
    chosen = query_mod.select(scored, budget_sticky, cfg,
                              head="", sticky_keys=["a_file.py", "boom Error"],
                              edited_since=set(), resolved_errors=set())
    keys1 = {n["key"] for n in chosen}
    assert "a_file.py" in keys1
    assert "boom Error" in keys1

    # Scenario 2: same sticky_keys, but both are now invalidated, and the budget is
    # sized to fit only ONE line -- so neither can sneak back in via the plain
    # score-ordered fill either (their score is far below `hot`'s).
    budget_fill_only = reserve + len(query_mod.render_line(hot)) + 1 + 5
    chosen2 = query_mod.select(scored, budget_fill_only, cfg,
                               head="", sticky_keys=["a_file.py", "boom Error"],
                               edited_since={"a_file.py"}, resolved_errors={"boom Error"})
    keys2 = {n["key"] for n in chosen2}
    assert "a_file.py" not in keys2
    assert "boom Error" not in keys2
    assert "hot_symbol" in keys2


# ============================================================================
# 5) Read and decided nodes created
# ============================================================================

def test_read_and_decided_nodes(scratch_root):
    root = scratch_root
    conn = common.db(root)
    session_id = "facts-sess"
    code = (
        "import os\n"
        "def handle_request(req, ctx):\n"
        "    return ctx\n"
        "API_KEY = os.environ['API_KEY']\n"
    )
    rid = common.record(conn, "Read", {"file_path": "svc/handlers.py"}, {"output": code},
                        session_id=session_id, agent="main", bridge_version="2.0",
                        bridge_sha="sha", root=root)
    assert rid >= 1
    keys = {row[0] for row in conn.execute("SELECT key FROM nodes WHERE kind='read'")}
    assert "read:svc/handlers.py:handle_request" in keys
    assert "read:svc/handlers.py:API_KEY" in keys

    did = common.record_decision(conn, session_id, "main", "Use SQLite WAL mode for the store",
                                 provenance="t.jsonl:42")
    assert did >= 1
    drow = conn.execute(
        "SELECT session_id, agent, text, provenance FROM decisions WHERE id=?", (did,)
    ).fetchone()
    assert drow == (session_id, "main", "Use SQLite WAL mode for the store", "t.jsonl:42")
    node = conn.execute("SELECT kind FROM nodes WHERE key=?", ("decided:{}".format(did),)).fetchone()
    assert node is not None and node[0] == "decided"
    conn.close()


# ============================================================================
# 5b) target-run-wavex.md findings #1/#2/#3: real Read shape, JS symbols, node --test
# ============================================================================

def test_read_facts_from_real_claude_code_read_response_shape(scratch_root):
    """docs/harness-0.3/target-run-wavex.md finding #1: the real Claude Code 2.1.x
    `tool_response` for a Read nests text under `resp["file"]["content"]`, not
    "output"/"stdout"/"content" -- `_resp_text` (hence `read_facts`) must read it."""
    root = scratch_root
    conn = common.db(root)
    real_resp = {
        "type": "text",
        "file": {
            "filePath": os.path.join(root, "guard.mjs"),
            "content": "export function validateIntent(payload) {\n  return true;\n}\n",
            "numLines": 3,
        },
    }
    rid = common.record(conn, "Read", {"file_path": "guard.mjs"}, real_resp,
                        session_id="s1", agent="main", bridge_version="2.0",
                        bridge_sha="sha", root=root)
    assert rid >= 1
    keys = {row[0] for row in conn.execute("SELECT key FROM nodes WHERE kind='read'")}
    assert "read:guard.mjs:validateIntent" in keys
    conn.close()


def test_symbol_nodes_from_js_write_and_edit(scratch_root):
    """docs/harness-0.3/target-run-wavex.md finding #2: SYM_RE must recognize the JS
    shapes a real Write/Edit of `.mjs`/`.js`/`.ts` code actually produces."""
    root = scratch_root
    conn = common.db(root)
    js_src = "\n".join([
        "export function validateIntent(payload) {",
        "  return true;",
        "}",
        "function rateLimit(key) {",
        "  return true;",
        "}",
        "export async function scoreIntent(intent) {",
        "  return 0;",
        "}",
        "class Watcher {}",
        "export class Guard {}",
        "export const DEFAULT_LIMITS = { capacity: 10 };",
        "const describeLimits = (limits) => JSON.stringify(limits);",
    ])
    rid = common.record(conn, "Write", {"file_path": "defense/limits.mjs", "content": js_src},
                        {"filePath": "defense/limits.mjs", "type": "create", "success": True},
                        session_id="s1", agent="main", bridge_version="2.0",
                        bridge_sha="sha", root=root)
    assert rid >= 1
    symbols = {row[0] for row in conn.execute("SELECT key FROM nodes WHERE kind='symbol'")}
    assert symbols == {
        "validateIntent", "rateLimit", "scoreIntent", "Watcher", "Guard",
        "DEFAULT_LIMITS", "describeLimits",
    }, symbols
    conn.close()


def test_node_test_and_friends_classify_as_test_node_check_stays_command(scratch_root):
    """docs/harness-0.3/target-run-wavex.md finding #3: `node --test`, `vitest`,
    `jest`, `mocha`, `npm run test` are test runs; `node --check` (a syntax check) must
    keep classifying as `command`."""
    root = scratch_root
    conn = common.db(root)
    test_cmds = ["node --test", "node --test scripts/concierge-agent",
                 "npx vitest run", "npx jest", "npx mocha", "npm run test"]
    for i, cmd in enumerate(test_cmds):
        common.record(conn, "Bash", {"command": cmd}, {"exitCode": 0, "output": "ok"},
                     session_id="s1", agent="main", bridge_version="2.0", bridge_sha="sha", root=root)
    kinds = dict(conn.execute(
        "SELECT target, kind FROM receipts WHERE session_id='s1' ORDER BY id"
    ).fetchall())
    for cmd in test_cmds:
        assert kinds[cmd] == "test", (cmd, kinds[cmd])

    common.record(conn, "Bash", {"command": "node --check defense/limits.mjs"},
                 {"exitCode": 0, "output": ""},
                 session_id="s1", agent="main", bridge_version="2.0", bridge_sha="sha", root=root)
    check_kind = conn.execute(
        "SELECT kind FROM receipts WHERE session_id='s1' AND target='node --check defense/limits.mjs'"
    ).fetchone()[0]
    assert check_kind == "command"
    conn.close()


def test_post_tool_use_failure_records_outcome_fail(scratch_root):
    """docs/harness-0.3/target-run-wavex.md finding #9 (item 8): a synthetic failure
    `tool_response` (what `receipt.py` builds from a `PostToolUseFailure` payload's
    `error` field) must record outcome 'fail', for any tool kind, not just Bash."""
    root = scratch_root
    conn = common.db(root)
    fail_resp = {"success": False, "stderr": "EISDIR: illegal operation on a directory"}
    common.record(conn, "Read", {"file_path": "scripts/concierge-agent/defense"}, fail_resp,
                 session_id="s1", agent="main", bridge_version="2.0", bridge_sha="sha", root=root)
    outcome = conn.execute(
        "SELECT outcome FROM receipts WHERE session_id='s1' AND tool='Read'"
    ).fetchone()[0]
    assert outcome == "fail"
    conn.close()


def test_receipt_hook_records_a_row_for_post_tool_use_failure_event(scratch_root):
    """docs/harness-0.3/target-run-wavex.md finding #9 (item 8), end-to-end: a real
    `PostToolUseFailure` payload (no `tool_response` key at all -- an `error` string
    instead) run through the actual `plateau.bridge.receipt` hook must still produce a
    receipt row, with outcome 'fail'."""
    root = git_init(scratch_root)
    session_id = "failure-event-sess"
    payload = {
        "cwd": root, "session_id": session_id, "hook_event_name": "PostToolUseFailure",
        "tool_name": "Bash", "tool_input": {"command": "for f in a b; do node --check \"$f\"; done"},
        "tool_use_id": "toolu_x", "error": "command not found: node",
    }
    _out, err, rc = run_hook("plateau.bridge.receipt", payload, root)
    assert rc == 0, err

    conn = sqlite3.connect(_db_path(root))
    row = conn.execute(
        "SELECT tool, outcome FROM receipts WHERE session_id=?", (session_id,)
    ).fetchone()
    conn.close()
    assert row == ("Bash", "fail")


# ============================================================================
# 6) Lexical ranking: a matching query ranks the matched node first
# ============================================================================

def test_lexical_query_ranks_match_first(scratch_root):
    root = scratch_root
    conn = common.db(root)
    session_id = "lex-sess"
    for rid in range(1, 6):
        _add_receipt(conn, rid, session_id=session_id)
    _add_node(conn, "unrelated_symbol", "symbol", last_rid=5, degree=1, session_id=session_id)
    _add_node(conn, "auth/login_handler.py", "file", last_rid=1, degree=1, session_id=session_id,
              detail="handles user login")

    cfg = bridge_config.load(root, session_id)
    no_query = query_mod.score_nodes(conn, "", cfg, session_id)
    assert no_query[0]["key"] == "unrelated_symbol", (
        "fixture sanity: structural score alone should favor the symbol"
    )

    scored = query_mod.score_nodes(conn, "how does login work", cfg, session_id)
    assert scored[0]["key"] == "auth/login_handler.py"
    assert scored[0]["lexical_hit"] is True
    conn.close()


# ============================================================================
# 7) Holdout: deterministic, ~10% of 1000 keys
# ============================================================================

def test_holdout_deterministic_and_rate():
    rate = 0.10
    ids = ["session-{}".format(i) for i in range(1000)]
    results = {sid: holdout.is_holdout(sid, 0, rate) for sid in ids}
    for sid in ids[:200]:
        assert holdout.is_holdout(sid, 0, rate) == results[sid]
        assert holdout.is_holdout(sid, 0, rate) == holdout.is_holdout(sid, 0, rate)
    frac = sum(results.values()) / len(results)
    assert 0.05 <= frac <= 0.15, "holdout rate drifted too far from 10%: {}".format(frac)


def test_holdout_skips_injection_end_to_end():
    root = git_init(make_root())
    try:
        session_id = _holdout_session_id(root, 0, prefix="force-holdout")
        transcript_path = os.path.join(root, "t.jsonl")
        fake_transcript(transcript_path, [("Read", {"file_path": "a.py"}, {"output": "def a(): pass\n"})])
        base = {"cwd": root, "session_id": session_id, "transcript_path": transcript_path}
        _out, err, rc = run_hook(
            "plateau.bridge.receipt",
            dict(base, hook_event_name="PostToolUse", tool_name="Read",
                 tool_input={"file_path": "a.py"}, tool_response={"output": "def a(): pass\n"}),
            root,
        )
        assert not err and rc == 0, err

        out, err, rc = run_hook(
            "plateau.bridge.inject", dict(base, hook_event_name="SessionStart", source="compact"), root,
        )
        assert not err and rc == 0, err
        assert json.loads(out) == {}, "a held-out compaction must print {}"

        conn = sqlite3.connect(_db_path(root))
        row = conn.execute(
            "SELECT holdout, chars, bridge_version, bridge_sha FROM injections WHERE session_id=? "
            "ORDER BY id DESC LIMIT 1", (session_id,),
        ).fetchone()
        assert row is not None
        assert row[0] == 1 and row[1] == 0
        assert row[2] and row[3]  # provenance columns present even on a held-out row
        conn.close()
    finally:
        shutil.rmtree(root, ignore_errors=True)


# ============================================================================
# 8) Concurrent writers: two processes x two agents
# ============================================================================

_CONCURRENT_WORKER = '''
import os
import sys

sys.path.insert(0, sys.argv[1])
os.environ.pop("PLATEAU_DB_REL", None)
os.environ.pop("PLATEAU_LOG_REL", None)
os.environ.pop("PLATEAU_LEGACY_TAG", None)
os.environ.pop("PLATEAU_AGENT", None)

from plateau.bridge import common

root = sys.argv[2]
n = int(sys.argv[3])
label = sys.argv[4]
conn = common.db(root)
for i in range(n):
    agent = "main" if i % 2 == 0 else "subagent:helper"
    common.record(
        conn, "Bash", {"command": "echo concurrent-writer-target"}, {"exitCode": 0, "output": "ok"},
        session_id="concurrent-session", agent=agent,
        bridge_version="2.0", bridge_sha="concurrent-sha", root=root,
    )
conn.close()
print(label, "done")
'''


def test_concurrent_writers_two_processes_two_agents(tmp_path):
    root = git_init(str(tmp_path / "store"))
    worker_path = tmp_path / "concurrent_worker.py"
    worker_path.write_text(_CONCURRENT_WORKER)

    calls_per_worker = 40
    env = _clean_subprocess_env()
    procs = [
        subprocess.Popen(
            [sys.executable, str(worker_path), REPO_ROOT, root, str(calls_per_worker), "p{}".format(i)],
            env=env, cwd=root, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        for i in range(2)
    ]
    outs = [p.communicate(timeout=60) for p in procs]
    for i, (_out, err) in enumerate(outs):
        assert procs[i].returncode == 0, "worker {} failed: {}".format(i, err)

    conn = sqlite3.connect(_db_path(root))
    n_receipts = conn.execute("SELECT COUNT(*) FROM receipts").fetchone()[0]
    assert n_receipts == 2 * calls_per_worker

    nodes = conn.execute("SELECT key, degree FROM nodes").fetchall()
    # every record() call in both workers hits the exact same Bash command, i.e. the
    # exact same node key -- so the store must show exactly one node whose degree
    # equals the total number of calls: proof WAL + busy_timeout serialized every
    # writer's read-modify-write on that row without a lost update.
    assert len(nodes) == 1
    assert nodes[0][1] == 2 * calls_per_worker

    n_agents = conn.execute(
        "SELECT COUNT(DISTINCT agent) FROM receipts WHERE session_id='concurrent-session'"
    ).fetchone()[0]
    assert n_agents == 2
    conn.close()


# ============================================================================
# 9) Handoff block round-trips through JSON
# ============================================================================

def test_handoff_round_trips_through_json(scratch_root):
    root = scratch_root
    conn = common.db(root)
    session_id = "handoff-sess"
    common.record(conn, "Bash", {"command": "pytest -q tests/a.py"},
                  {"exitCode": 1, "output": "FAILED tests/a.py::test_a - AssertionError\n1 failed"},
                  session_id=session_id, agent="main", bridge_version="2.0", bridge_sha="abc123",
                  root=root)
    common.record(conn, "Bash", {"command": "pytest -q tests/b.py"},
                  {"exitCode": 1, "output": "FAILED tests/b.py::test_b - AssertionError\n1 failed"},
                  session_id=session_id, agent="main", bridge_version="2.0", bridge_sha="abc123",
                  root=root)
    common.record(conn, "Bash", {"command": "pytest -q tests/a.py"}, {"exitCode": 0, "output": "1 passed"},
                  session_id=session_id, agent="main", bridge_version="2.0", bridge_sha="abc123",
                  root=root)
    common.record_decision(conn, session_id, "main", "Adopt WAL mode", "t.jsonl:10")

    snap_dir = _snapshots_dir(root)
    os.makedirs(snap_dir, exist_ok=True)
    snap_path = os.path.join(snap_dir, "123_auto.sqlite")
    shutil.copy(_db_path(root), snap_path)
    common.mark_compaction(conn, session_id, snap_path)

    conn.execute(
        "INSERT INTO injections(ts,session_id,event,compaction_k,chars,budget,holdout,"
        "bridge_version,bridge_sha,keys) VALUES(?,?,?,?,?,?,?,?,?,?)",
        (time.time(), session_id, "compact", 0, 4200, 12000, 0, "2.0", "abc123",
         json.dumps(["tests/a.py"])),
    )
    conn.commit()
    conn.close()

    block = handoff_mod.build(root, session_id)
    rendered = handoff_mod.render(block)
    roundtripped = json.loads(json.dumps(block))
    assert roundtripped == block
    assert handoff_mod.render(roundtripped) == rendered

    assert rendered.startswith("<plateau_handoff v=1>")
    assert rendered.endswith("</plateau_handoff>")
    assert block["receipts"] == 3
    assert block["compactions"] == 1
    assert block["decisions"]["count"] == 1
    # tests/a.py later passed (resolved); tests/b.py never did (stays open).
    assert len(block["open"]["errors"]) == 1
    assert "tests/b.py" in block["open"]["errors"][0]


# ============================================================================
# 9b) S3-A1 handoff file naming (SubagentStop vs SessionEnd), S3-A2 child_env(),
#     S3-A3 agent_of() fallback order -- docs/harness-0.3/PLAN-step3.md "Amendments
#     after preflight run 1"
# ============================================================================

def test_subagentstop_writes_distinct_file_and_sessionend_never_touches_it(scratch_root):
    """S3-A1: a `SubagentStop` payload (carries `agent_type`/`agent_id`, the SAME
    `session_id` as its parent -- the payload shape docs/harness-0.3/preflight-step3.md
    found for real) writes `.plateau/handoff/<sid>.subagent-<agent_id>.json` with
    `agent: subagent:<agent_type>` and `parent: <sid>`. A later `SessionEnd` payload for
    that SAME `session_id` then writes the separate `.plateau/handoff/<sid>.json` main
    file -- a different path, so it is asserted here that the subagent file survives
    byte-for-byte (this is what the fix makes automatic; run 1 found the opposite: a
    single shared path that SessionEnd silently clobbered)."""
    root = scratch_root
    session_id = "sess-s3a1"

    sub_payload = {
        "cwd": root, "session_id": session_id, "hook_event_name": "SubagentStop",
        "agent_type": "general-purpose", "agent_id": "abc123",
    }
    out, err, rc = run_hook("plateau.bridge.handoff", sub_payload, root,
                            argv=["--write", "--agent", "subagent"])
    assert rc == 0, err

    handoff_dir = os.path.join(root, ".plateau", "handoff")
    sub_path = os.path.join(handoff_dir, "{}.subagent-abc123.json".format(session_id))
    assert os.path.isfile(sub_path), "expected {!r}, found {}".format(
        sub_path, sorted(os.listdir(handoff_dir)) if os.path.isdir(handoff_dir) else "(no dir)")
    with open(sub_path, encoding="utf-8") as f:
        sub_block = json.load(f)
    assert sub_block["agent"] == "subagent:general-purpose"
    assert sub_block["parent"] == session_id
    assert sub_block["session"] == session_id

    with open(sub_path, encoding="utf-8") as f:
        sub_bytes_before = f.read()
    sub_mtime_before = os.path.getmtime(sub_path)

    end_payload = {"cwd": root, "session_id": session_id, "hook_event_name": "SessionEnd"}
    out, err, rc = run_hook("plateau.bridge.handoff", end_payload, root, argv=["--write"])
    assert rc == 0, err

    main_path = os.path.join(handoff_dir, "{}.json".format(session_id))
    assert os.path.isfile(main_path)
    with open(main_path, encoding="utf-8") as f:
        main_block = json.load(f)
    assert main_block["agent"] == "main"
    assert main_path != sub_path

    # The explicit assertion the plan calls for: SessionEnd's write never overwrites
    # the subagent file (automatic given the distinct paths -- asserted directly).
    assert os.path.isfile(sub_path)
    assert os.path.getmtime(sub_path) == sub_mtime_before
    with open(sub_path, encoding="utf-8") as f:
        assert f.read() == sub_bytes_before


def test_compaction_summarizer_subagentstop_writes_nothing(scratch_root):
    """docs/harness-0.3/target-run-wavex.md finding #7: Claude Code fires SubagentStop
    for its internal auto-compaction summarizer with an `agent_id` but NO `agent_type`.
    That must produce NO handoff file at all (not a `subagent:<hash>` one, and NOT a
    clobber of the main file either) -- `handoff --write --agent subagent` on that exact
    payload shape is a no-op, logged."""
    root = scratch_root
    session_id = "sess-compaction-summarizer"

    summarizer_payload = {
        "cwd": root, "session_id": session_id, "hook_event_name": "SubagentStop",
        "agent_id": "a393962501cde927b",  # no agent_type -- the compaction quirk
    }
    out, err, rc = run_hook("plateau.bridge.handoff", summarizer_payload, root,
                            argv=["--write", "--agent", "subagent"])
    assert rc == 0, err

    handoff_dir = os.path.join(root, ".plateau", "handoff")
    assert not os.path.isdir(handoff_dir) or os.listdir(handoff_dir) == [], (
        "no handoff file should be written for an agent_id-only payload: {}".format(
            sorted(os.listdir(handoff_dir)) if os.path.isdir(handoff_dir) else []
        )
    )

    log_path = os.path.join(root, ".plateau", "hooks.log")
    assert os.path.isfile(log_path)
    with open(log_path, encoding="utf-8") as f:
        assert "handoff skip: no agent_type" in f.read()


def test_handoff_last_prefers_main_file_over_newer_subagent_file(scratch_root):
    """S3-A1: `--last` (`handoff.last()`) prefers the main `<sid>.json` file even when
    a subagent file for the same session is strictly newer; it falls back to the
    subagent file only when no main file exists at all."""
    root = scratch_root
    session_id = "sess-last-pref"

    main_path = handoff_mod.write(root, handoff_mod.build(root, session_id, agent="main"))
    time.sleep(0.01)  # ensure a strictly later mtime on the subagent file below
    sub_block = handoff_mod.build(
        root, session_id, agent="subagent:general-purpose", parent=session_id, agent_id="zz9",
    )
    sub_path = handoff_mod.write(root, sub_block)
    assert sub_path != main_path
    assert os.path.getmtime(sub_path) >= os.path.getmtime(main_path)

    preferred = handoff_mod.last(root)
    assert preferred is not None and preferred["agent"] == "main"

    os.remove(main_path)  # only the subagent file remains
    fallback = handoff_mod.last(root)
    assert fallback is not None and fallback["agent"] == "subagent:general-purpose"


def test_child_env_drops_session_identity_vars_keeps_others():
    """S3-A2 (`plateau.bridge.common.child_env`): drops CLAUDECODE,
    CLAUDE_CODE_SESSION_ID, CLAUDE_CODE_REMOTE_SESSION_ID and
    CLAUDE_AUTOCOMPACT_PCT_OVERRIDE; keeps every other variable untouched."""
    strip_vars = ("CLAUDECODE", "CLAUDE_CODE_SESSION_ID",
                  "CLAUDE_CODE_REMOTE_SESSION_ID", "CLAUDE_AUTOCOMPACT_PCT_OVERRIDE")
    saved = {k: os.environ.get(k) for k in strip_vars}
    try:
        for k in strip_vars:
            os.environ[k] = "x"
        os.environ["PLATEAU_TEST_KEEP_ME"] = "kept"
        env = common.child_env()
        for k in strip_vars:
            assert k not in env, "{} should have been stripped".format(k)
        assert env.get("PLATEAU_TEST_KEEP_ME") == "kept"
        assert "PATH" in env or len(env) > 0  # ordinary vars pass through untouched
    finally:
        for k in strip_vars:
            if saved[k] is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = saved[k]
        os.environ.pop("PLATEAU_TEST_KEEP_ME", None)


def test_agent_of_s3a3_fallback_order():
    """S3-A3, amended by docs/harness-0.3/target-run-wavex.md finding #7: `agent_type` >
    `agent_name` > env `PLATEAU_AGENT` > `main`. `agent_id` ALONE no longer identifies a
    subagent -- Claude Code's own internal auto-compaction summarizer fires SubagentStop
    with an `agent_id` but no `agent_type`, and treating `agent_id` alone as sufficient
    mislabeled that as `subagent:<hash>` (3 spurious handoff files in the target run,
    one per compaction, with no real subagent behind any of them)."""
    assert common.agent_of({}) == "main"
    assert common.agent_of({"agent_type": "general-purpose"}) == "subagent:general-purpose"
    # agent_id alone (no agent_type): the compaction-summarizer shape -- main, not subagent
    assert common.agent_of({"agent_id": "abc123"}) == "main"
    assert common.agent_of({"agent_name": "helper"}) == "subagent:helper"
    # agent_type wins whenever more than one key is present
    assert common.agent_of({"agent_type": "t", "agent_id": "i", "agent_name": "n"}) == "subagent:t"
    # agent_name still applies when agent_type is absent (agent_id no longer competes)
    assert common.agent_of({"agent_id": "i", "agent_name": "n"}) == "subagent:n"
    old = os.environ.get("PLATEAU_AGENT")
    try:
        os.environ["PLATEAU_AGENT"] = "p"
        # env only applies when no payload key identifies a subagent
        assert common.agent_of({}) == "p"
        assert common.agent_of({"agent_type": "t"}) == "subagent:t"
        # agent_id-only still resolves to env/main, never a fabricated subagent id
        assert common.agent_of({"agent_id": "i"}) == "p"
    finally:
        if old is None:
            os.environ.pop("PLATEAU_AGENT", None)
        else:
            os.environ["PLATEAU_AGENT"] = old


# ============================================================================
# 10) <d037_index> accepted on read via inject's legacy path (+ sticky, + holdout off)
# ============================================================================

def test_legacy_tag_accepted_via_inject_legacy_env():
    root = git_init(make_root())
    try:
        session_id = _non_holdout_session_id(root, (0,), prefix="legacy")
        transcript_path = os.path.join(root, "t.jsonl")
        fake_transcript(transcript_path, [("Read", {"file_path": "a.py"}, {"output": "def a(): pass\n"})])
        base = {"cwd": root, "session_id": session_id, "transcript_path": transcript_path}
        # PLATEAU_LEGACY_TAG=1 is what d037_hooks/*.py shims set before delegating to
        # plateau.bridge.*; set here directly against plateau.bridge.* itself, to pin
        # the *bridge* package's own legacy switch rather than the shim's plumbing.
        _out, err, rc = run_hook(
            "plateau.bridge.receipt",
            dict(base, hook_event_name="PostToolUse", tool_name="Read",
                 tool_input={"file_path": "a.py"}, tool_response={"output": "def a(): pass\n"}),
            root, extra_env={"PLATEAU_LEGACY_TAG": "1"},
        )
        assert not err and rc == 0, err

        out, err, rc = run_hook(
            "plateau.bridge.inject",
            dict(base, hook_event_name="SessionStart", source="compact"),
            root, extra_env={"PLATEAU_LEGACY_TAG": "1"},
        )
        assert not err and rc == 0, err
        j = json.loads(out)
        ctx = j["hookSpecificOutput"]["additionalContext"]
        assert ctx.startswith("<{}>".format(common.LEGACY_TAG))
        assert ctx.endswith("</{}>".format(common.LEGACY_TAG))
        assert common.LEGACY_TAG in common.TAGS_ON_READ
        assert common.TAG in common.TAGS_ON_READ

        # sticky under the legacy tag too: the same file line survives a second
        # legacy compaction when nothing invalidated it.
        _out, err, rc = run_hook(
            "plateau.bridge.snapshot",
            dict(base, hook_event_name="PreCompact", trigger="auto"),
            root, extra_env={"PLATEAU_LEGACY_TAG": "1"},
        )
        assert not err and rc == 0, err
        out2, err, rc = run_hook(
            "plateau.bridge.inject",
            dict(base, hook_event_name="SessionStart", source="compact"),
            root, extra_env={"PLATEAU_LEGACY_TAG": "1"},
        )
        assert not err and rc == 0, err
        ctx2 = json.loads(out2)["hookSpecificOutput"]["additionalContext"]
        assert "a.py" in ctx2

        # legacy mode also disables holdout outright (PLAN.md deviations): even a
        # session/k pair that WOULD be held out under the real path must still inject.
        held = _holdout_session_id(root, 0, prefix="legacy-holdout")
        out3, err, rc = run_hook(
            "plateau.bridge.inject",
            {"cwd": root, "session_id": held, "transcript_path": transcript_path,
             "hook_event_name": "SessionStart", "source": "compact"},
            root, extra_env={"PLATEAU_LEGACY_TAG": "1"},
        )
        assert not err and rc == 0, err
        j3 = json.loads(out3)
        assert j3.get("hookSpecificOutput", {}).get("hookEventName") == "SessionStart"
        assert j3["hookSpecificOutput"]["additionalContext"].startswith("<{}>".format(common.LEGACY_TAG))
    finally:
        shutil.rmtree(root, ignore_errors=True)


# ============================================================================
# 11) Config resolution: incumbent vs canary deterministic by session id; off
# ============================================================================

def test_config_resolution_incumbent_canary_off(scratch_root):
    root = scratch_root
    incumbent_toml = 'version = "2.0-incumbent-test"\n[lab]\nholdout_rate = 0.10\ncanary_share = 0.20\n'
    canary_toml = 'version = "2.0-canary-test"\n[lab]\nholdout_rate = 0.10\ncanary_share = 0.20\n'
    with open(os.path.join(root, "bridge.toml"), "w") as f:
        f.write(incumbent_toml)

    # --- incumbent: no canary file at all yet -----------------------------------
    cfg_plain = bridge_config.load(root, "whatever")
    assert cfg_plain.role == "incumbent"
    assert cfg_plain.version == "2.0-incumbent-test"
    assert cfg_plain.sha == hashlib.sha256(incumbent_toml.encode("utf-8")).hexdigest()

    # --- add the canary file: bucketing must be deterministic by session_id -----
    with open(os.path.join(root, "bridge.canary.toml"), "w") as f:
        f.write(canary_toml)
    canary_share = float(cfg_plain.lab.get("canary_share", 0.0))

    def bucket(sid: str) -> int:
        return int(hashlib.sha256(sid.encode("utf-8")).hexdigest(), 16) % 100

    canary_id = next(
        "cid-{}".format(i) for i in range(5000) if bucket("cid-{}".format(i)) < canary_share * 100
    )
    incumbent_id = next(
        "iid-{}".format(i) for i in range(5000) if bucket("iid-{}".format(i)) >= canary_share * 100
    )

    cfg_canary = bridge_config.load(root, canary_id)
    assert cfg_canary.role == "canary"
    assert cfg_canary.version == "2.0-canary-test"
    assert cfg_canary.sha == hashlib.sha256(canary_toml.encode("utf-8")).hexdigest()

    cfg_incumbent = bridge_config.load(root, incumbent_id)
    assert cfg_incumbent.role == "incumbent"
    assert cfg_incumbent.version == "2.0-incumbent-test"

    # determinism: same session_id always resolves to the same role
    assert bridge_config.load(root, canary_id).role == "canary"
    assert bridge_config.load(root, incumbent_id).role == "incumbent"

    # --- enabled=false in .plateau/config.toml forces role "off" ----------------
    os.makedirs(os.path.join(root, ".plateau"), exist_ok=True)
    with open(os.path.join(root, ".plateau", "config.toml"), "w") as f:
        f.write("[bridge]\nenabled = false\n")
    cfg_off = bridge_config.load(root, incumbent_id)
    assert cfg_off.role == "off"
    # "off" layers on top of whichever file already won -- it doesn't change which
    # file supplied version/sha.
    assert cfg_off.version == "2.0-incumbent-test"


# ============================================================================
# 11b) target-run-wavex.md finding #4: mark_turn wired into the Stop path (lift.py)
# ============================================================================

def test_lift_marks_one_turn_per_stop_and_receipts_per_turn_leaves_default(scratch_root):
    """`common.mark_turn()` was defined but never called from any installed hook
    (docs/harness-0.3/target-run-wavex.md finding #4), so `turns` stayed empty forever
    and `receipts_per_turn()` always returned its 30.0 fallback. `plateau.bridge.lift`
    now calls it once per Stop, unconditionally -- verified here across two Stops with
    receipts recorded in between, against the real subprocess hook path."""
    root = git_init(scratch_root)
    session_id = "turns-sess"
    transcript_path = os.path.join(root, "t.jsonl")
    fake_transcript(transcript_path, [])  # no DECISION/FACT markers -- still must mark_turn
    base_payload = {"cwd": root, "session_id": session_id, "transcript_path": transcript_path}

    conn = common.db(root)
    for rid in range(1, 5):  # 4 receipts before the first Stop
        common.record(conn, "Bash", {"command": "echo hi"}, {"exitCode": 0, "output": "hi"},
                     session_id=session_id, agent="main", bridge_version="2.0",
                     bridge_sha="sha", root=root)
    conn.close()

    out, err, rc = run_hook("plateau.bridge.lift", dict(base_payload, hook_event_name="Stop"), root)
    assert rc == 0, err

    conn = common.db(root)
    for rid in range(5, 7):  # 2 more receipts before the second Stop
        common.record(conn, "Bash", {"command": "echo hi"}, {"exitCode": 0, "output": "hi"},
                     session_id=session_id, agent="main", bridge_version="2.0",
                     bridge_sha="sha", root=root)
    conn.close()

    out, err, rc = run_hook("plateau.bridge.lift", dict(base_payload, hook_event_name="Stop"), root)
    assert rc == 0, err

    conn = common.db(root)
    n_turns = conn.execute("SELECT COUNT(*) FROM turns WHERE session_id=?", (session_id,)).fetchone()[0]
    assert n_turns == 2, "two Stops must mark exactly two turns"
    rpt = common.receipts_per_turn(conn, session_id)
    assert rpt != 30.0, "receipts_per_turn must no longer be stuck at its no-turns-recorded default"
    assert rpt == pytest.approx(6 / 2)
    conn.close()


# ============================================================================
# 12) Fallback TOML parser equals tomllib
# ============================================================================

@pytest.mark.skipif(_tomllib is None, reason="tomllib not available on this interpreter (<3.11)")
def test_fallback_toml_matches_tomllib_on_bridge_toml():
    path = os.path.join(REPO_ROOT, "bridge.toml")
    with open(path, "rb") as f:
        text = f.read().decode("utf-8")
    assert bridge_toml.loads(text) == _tomllib.loads(text)


@pytest.mark.skipif(_tomllib is None, reason="tomllib not available on this interpreter (<3.11)")
def test_fallback_toml_matches_tomllib_on_packaged_default():
    path = os.path.join(REPO_ROOT, "plateau", "bridge", "bridge.default.toml")
    with open(path, "rb") as f:
        text = f.read().decode("utf-8")
    assert bridge_toml.loads(text) == _tomllib.loads(text)


# ============================================================================
# 13) Provenance columns on every receipt and injection row
# ============================================================================

def test_provenance_columns_on_receipts_and_injections(scratch_root):
    root = scratch_root
    conn = common.db(root)
    rid = common.record(conn, "Bash", {"command": "echo hi"}, {"exitCode": 0, "output": "hi"},
                        session_id="prov-sess", agent="main", bridge_version="9.9.9",
                        bridge_sha="feedfeed", root=root)
    row = conn.execute("SELECT bridge_version, bridge_sha FROM receipts WHERE id=?", (rid,)).fetchone()
    assert row == ("9.9.9", "feedfeed")

    conn.execute(
        "INSERT INTO injections(ts,session_id,event,compaction_k,chars,budget,holdout,"
        "bridge_version,bridge_sha,keys) VALUES(?,?,?,?,?,?,?,?,?,?)",
        (time.time(), "prov-sess", "startup", None, 10, 6000, 0, "9.9.9", "feedfeed", "[]"),
    )
    conn.commit()
    inj = conn.execute(
        "SELECT bridge_version, bridge_sha FROM injections ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert inj == ("9.9.9", "feedfeed")
    conn.close()


# ============================================================================
# 14) "Off means off everywhere": enabled=false disables every bridge hook
# ============================================================================

def test_bridge_off_disables_every_hook():
    """PLAN.md's `.plateau/config.toml` [bridge] `enabled = false` -> role "off" must be
    honoured by every bridge hook, not just receipt.py (Issue 1, "off means off
    everywhere"): snapshot prints nothing and creates nothing; inject prints {} and
    records nothing -- in particular, a compact SessionStart must not create
    .plateau/index.sqlite at all; lookup prints "(bridge off)"."""
    root = git_init(make_root())
    try:
        os.makedirs(os.path.join(root, ".plateau"), exist_ok=True)
        with open(os.path.join(root, ".plateau", "config.toml"), "w") as f:
            f.write("[bridge]\nenabled = false\n")
        session_id = "off-sess"
        db_path = _db_path(root)

        # --- receipt.py (PostToolUse): records nothing ------------------------------
        out, err, rc = run_hook(
            "plateau.bridge.receipt",
            {"cwd": root, "session_id": session_id, "hook_event_name": "PostToolUse",
             "tool_name": "Read", "tool_input": {"file_path": "a.py"},
             "tool_response": {"output": "def a(): pass\n"}},
            root,
        )
        assert not err and rc == 0, err
        assert out == ""
        assert not os.path.isfile(db_path), "receipt must create no store while off"

        # --- snapshot.py (PreCompact): prints nothing and creates nothing -----------
        out, err, rc = run_hook(
            "plateau.bridge.snapshot",
            {"cwd": root, "session_id": session_id, "hook_event_name": "PreCompact", "trigger": "auto"},
            root,
        )
        assert not err and rc == 0, err
        assert out == "", "snapshot must print nothing while off"
        assert not os.path.isdir(_snapshots_dir(root)), "snapshot must create nothing while off"
        assert not os.path.isfile(db_path)

        # --- inject.py (SessionStart, compact): prints {} and records nothing -------
        out, err, rc = run_hook(
            "plateau.bridge.inject",
            {"cwd": root, "session_id": session_id, "hook_event_name": "SessionStart",
             "source": "compact", "transcript_path": ""},
            root,
        )
        assert not err and rc == 0, err
        assert json.loads(out) == {}
        assert not os.path.isfile(db_path), "off must create no .plateau/index.sqlite"

        # --- lookup: prints "(bridge off)" without ever opening the store -----------
        proc = subprocess.run(
            [sys.executable, "-m", "plateau.bridge.lookup"],
            cwd=root, env=_clean_subprocess_env(), capture_output=True, text=True, timeout=30,
        )
        assert proc.returncode == 0 and not proc.stderr, proc.stderr
        assert proc.stdout.strip() == "(bridge off)"
        assert not os.path.isfile(db_path)
    finally:
        shutil.rmtree(root, ignore_errors=True)


# ============================================================================
# 15) Bridge quota honoured end-to-end via inject.py, with the current-compaction-
#     just-inserted edge case (Issue 2; plateau.bridge.common.prev_compaction_rid)
# ============================================================================

def test_quota_honoured_via_inject_with_two_synthetic_compactions():
    """Exercises the REAL plateau.bridge.inject SessionStart(compact) path end to end
    (not just query.score_nodes/select in isolation): with two synthetic compactions --
    an earlier, real one (k=0), and a second (k=1) that mimics snapshot.py's PreCompact
    having just inserted the CURRENT compaction row (rid_at == MAX(receipts.id) for the
    session -- the exact condition Issue 2 is about) -- at least round(0.40 * n_lines)
    of the actually-injected lines must have last_rid <= the PREVIOUS boundary (k=0's
    rid_at), not the just-inserted one (which would make the quota a no-op)."""
    root = git_init(make_root())
    try:
        session_id = _non_holdout_session_id(root, (1,), prefix="quota-e2e")
        conn = common.db(root)
        for rid in range(1, 21):
            _add_receipt(conn, rid, session_id=session_id, target="r{}".format(rid))
        for i in range(8):
            _add_node(conn, "old_{}.py".format(i), "file", last_rid=5, degree=1, session_id=session_id)
        for i in range(8):
            _add_node(conn, "new_sym_{}".format(i), "symbol", last_rid=20, degree=1, session_id=session_id)
        prev_boundary = 10
        _add_compaction(conn, session_id, 0, rid_at=prev_boundary)
        # k=1 mimics snapshot.py's PreCompact having *just* inserted the current
        # compaction row before this SessionStart(compact) fires: rid_at == the
        # session's current MAX(receipts.id), i.e. no receipt recorded since it was
        # marked. This must NOT become the boundary (Issue 2 / common.prev_compaction_rid).
        _add_compaction(conn, session_id, 1, rid_at=20)
        conn.close()

        out, err, rc = run_hook(
            "plateau.bridge.inject",
            {"cwd": root, "session_id": session_id, "hook_event_name": "SessionStart",
             "source": "compact", "transcript_path": ""},
            root, argv=["--budget", "700"],
        )
        assert not err and rc == 0, err
        ctx = _check_inject(out, 700, "quota-e2e")

        lines = [l for l in ctx.splitlines() if l.startswith("[r")]
        n_lines = len(lines)
        assert 0 < n_lines < 16, "fixture sanity: budget must select some but not all nodes"
        rids = [int(l.split("]", 1)[0][2:]) for l in lines]
        n_older = sum(1 for r in rids if r <= prev_boundary)
        required = round(0.40 * n_lines)
        assert n_older >= required, (n_older, required, n_lines, rids)
        assert any(r > prev_boundary for r in rids), "fixture sanity: some 'new' lines chosen too"
    finally:
        shutil.rmtree(root, ignore_errors=True)


# ============================================================================
# 16) inject.py passes sticky_keys=[] to select() when cfg.selector["sticky"] is false
# ============================================================================

def test_inject_disables_stickiness_when_config_sticky_is_false():
    """PLAN.md 'Selector v2': `sticky` is a config toggle. When cfg.selector["sticky"]
    is false, inject.py must pass sticky_keys=[] to select() -- a node that was injected
    at the previous compaction (and would normally survive via stickiness, since nothing
    invalidated it) must NOT come back once the toggle is off, unless it also wins on
    pure score merit, which this fixture makes it clearly unable to do."""
    root = git_init(make_root())
    try:
        with open(os.path.join(root, "bridge.toml"), "w") as f:
            f.write(
                'version = "2.0"\n'
                "[selector]\n"
                "tau_turns = 3\n"
                "degree_cap = 3\n"
                "weights = { symbol = 1.4, error = 1.3, decided = 1.4, read = 1.2, test = 1.2, "
                "file = 0.7, command = 0.6, search = 0.3 }\n"
                "bridge_quota = 0.0\n"
                "sticky = false\n"
                "lexical = false\n"
            )
        session_id = "nosticky-sess"
        conn = common.db(root)
        for rid in range(1, 22):
            _add_receipt(conn, rid, session_id=session_id, target="r{}".format(rid))
        _add_node(conn, "quiet.py", "file", last_rid=1, degree=1, session_id=session_id)
        for i in range(8):
            _add_node(conn, "hot_{}.py".format(i), "file", last_rid=21, degree=1, session_id=session_id)
        _add_compaction(conn, session_id, 0, rid_at=1)
        # Simulate quiet.py having been injected at the previous compaction (k=0):
        # with sticky=true this alone would be enough to bring it back at k=1.
        conn.execute(
            "INSERT INTO injections(ts,session_id,event,compaction_k,chars,budget,holdout,"
            "bridge_version,bridge_sha,keys,rid_at) VALUES(?,?,?,?,?,?,0,?,?,?,?)",
            (time.time(), session_id, "compact", 0, 100, 12000, "2.0", "sha",
             json.dumps(["quiet.py"]), 1),
        )
        conn.commit()

        cfg = bridge_config.load(root, session_id)
        scored = query_mod.score_nodes(conn, "", cfg, session_id)
        lookup = {n["key"]: n["score"] for n in scored}
        assert lookup["quiet.py"] < min(lookup["hot_{}.py".format(i)] for i in range(8)), (
            "fixture sanity: quiet.py must not be able to win a spot on score alone"
        )
        conn.close()

        out, err, rc = run_hook(
            "plateau.bridge.inject",
            {"cwd": root, "session_id": session_id, "hook_event_name": "SessionStart",
             "source": "compact", "transcript_path": ""},
            root, argv=["--budget", "320"],
        )
        assert not err and rc == 0, err
        ctx = _check_inject(out, 320, "nosticky")
        assert "quiet.py" not in ctx, "sticky=false must not re-inject quiet.py by stickiness alone"
        assert "hot_" in ctx, "fixture sanity: some hot node must have been chosen"
    finally:
        shutil.rmtree(root, ignore_errors=True)


# ============================================================================
# 17) Handoff's last_injection cursor: r<N> is the receipt cursor at injection time
#     (Issue 3), not the injections row's own id
# ============================================================================

def test_handoff_last_injection_shows_receipt_cursor_end_to_end():
    """After a receipt with id N followed by an injection, the handoff block's
    `last_injection` cursor is r<N> -- the receipt cursor AT INJECTION TIME
    (injections.rid_at), not the injections row's own auto-increment id (PLAN.md
    'Handoff block v1'; Issue 3)."""
    root = git_init(make_root())
    try:
        session_id = "cursor-e2e-sess"
        out, err, rc = run_hook(
            "plateau.bridge.receipt",
            {"cwd": root, "session_id": session_id, "hook_event_name": "PostToolUse",
             "tool_name": "Read", "tool_input": {"file_path": "a.py"},
             "tool_response": {"output": "def a(): pass\n"}},
            root,
        )
        assert not err and rc == 0, err
        conn = sqlite3.connect(_db_path(root))
        n = conn.execute("SELECT MAX(id) FROM receipts WHERE session_id=?", (session_id,)).fetchone()[0]
        conn.close()
        assert n is not None

        out, err, rc = run_hook(
            "plateau.bridge.inject",
            {"cwd": root, "session_id": session_id, "hook_event_name": "SessionStart", "source": "startup"},
            root,
        )
        assert not err and rc == 0, err

        block = handoff_mod.build(root, session_id)
        assert block["last_injection"]["rid"] == n
        rendered = handoff_mod.render(block)
        assert "last_injection: r{}".format(n) in rendered
    finally:
        shutil.rmtree(root, ignore_errors=True)
