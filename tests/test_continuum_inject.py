"""tests/test_continuum_inject.py — 0.4 section 3: the carry step in the SessionStart hook.

Covers the wiring of the continuum into `plateau.bridge.inject` on a `compact` event:
`because` arrows the transcript holds for receipts without a reason yet are lifted first
(Stop has not run for the open turn; tests/test_carry_store.py::test_open_turn_before_its_stop_has_no_reasons
is the finding this closes), `plateau.bridge.carry.carry_from_store` names what the
current request descends from with `window=0` -- the compaction: a real one summarizes the
open turn's own earlier calls too, so what they produced is evicted exactly like a previous
turn's and the ancestry is carried in full -- `query.select(carried_keys=...)` forces those
lines in ahead of everything else and marks them `◉`, the head gains its `◉` legend, and
the log line gains ` carried=<m>`. Also the exclusions -- `[continuum] carry = false`, the
legacy tag, a `startup` source, a held-out compaction -- each of which must leave the 0.3
block and log line byte-identical (no legend, no marker, no suffix); the failure modes
(a lift that raises is rolled back, a transcript tail cut mid-multibyte is skipped); the
`select()` / `render_line()` unit behaviour; and the config key.

The hook runs the way tests/test_bridge.py runs it: a real subprocess (`python -m
plateau.bridge.inject`) over a `git init`-ed temp root, the store built through the real
API (`common.record` / `mark_turn` / `record_reason` / `mark_compaction`), `HOME` pointed
at an empty temp dir so no `~/.plateau/bridge.toml` leaks in, env scrubbed of the legacy
overrides. The helpers are copied, not imported, so this file stands alone.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import types
from typing import Dict, List, Optional, Tuple

import pytest

from plateau.bridge import _toml as bridge_toml
from plateau.bridge import carry as carry_mod
from plateau.bridge import common
from plateau.bridge import config as bridge_config
from plateau.bridge import inject as inject_mod
from plateau.bridge import lift as lift_mod
from plateau.bridge import query as q
from plateau.lab import holdout

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

E1 = "TimeoutError in payment.charge"
F1 = "read:payment/client.py:charge"
REASON2 = "the timeout points at the payment client"
REASON3 = "Apply the charge retries plan from the client read."
LEGEND_03 = "★ = matches current prompt. "                  # the 0.3 head, verbatim
LEGEND_04 = "★ = matches current prompt, ◉ = this request descends from it."

LOG_RE = re.compile(r"^\d+\.\d+ inject ev=SessionStart q=\d+ch nodes=\d+/\d+ chars=\d+ budget=(\d+)(.*)$")

# a truncated multibyte sequence: what the hook reads when Claude Code is mid-append
TRUNCATED_TAIL = b'{"type":"user","message":{"role":"user","content":"caf\xc3'


# ---------------------------------------------------------------------------
# helpers (copied from tests/test_bridge.py; HOME isolation from tests/test_doctor.py)
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _isolated_env(monkeypatch, tmp_path):
    """Every config resolution -- in-process or in the hook subprocess, which inherits
    os.environ -- sees an empty HOME (config.py merges ~/.plateau/bridge.toml) and no
    resume handoff; the legacy overrides are scrubbed per subprocess below."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    for k in ("PLATEAU_RESUME_FROM", "PLATEAU_LEGACY_TAG", "PLATEAU_DB_REL", "PLATEAU_LOG_REL", "PLATEAU_AGENT"):
        monkeypatch.delenv(k, raising=False)


def _git_root() -> str:
    root = tempfile.mkdtemp(prefix="plateau-continuum-test-")
    subprocess.run(["git", "init", "-q", root], capture_output=True, text=True, timeout=10)
    return root


def _clean_subprocess_env() -> Dict[str, str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = REPO_ROOT + os.pathsep + env.get("PYTHONPATH", "")
    for k in ("PLATEAU_LEGACY_TAG", "PLATEAU_DB_REL", "PLATEAU_LOG_REL", "PLATEAU_AGENT", "PLATEAU_RESUME_FROM"):
        env.pop(k, None)
    return env


def run_hook(module: str, payload: dict, root: str, extra_env: Optional[dict] = None,
             argv: Optional[List[str]] = None) -> Tuple[str, str, int]:
    env = _clean_subprocess_env()
    if extra_env:
        env.update(extra_env)
    cmd = [sys.executable, "-m", module] + list(argv or [])
    proc = subprocess.run(cmd, input=json.dumps(payload), cwd=root, env=env,
                          capture_output=True, text=True, timeout=30)
    return proc.stdout, proc.stderr, proc.returncode


def _rate(root: str) -> float:
    return float(bridge_config.load(root, "lab-probe").lab.get("holdout_rate", 0.10))


def _non_holdout_session_id(root: str, ks, prefix: str = "cont") -> str:
    rate = _rate(root)
    for i in range(1000):
        candidate = f"{prefix}-{i}"
        if all(not holdout.is_holdout(candidate, k, rate) for k in ks):
            return candidate
    raise AssertionError("could not find a non-holdout session id")


def _holdout_session_id(root: str, k: int, prefix: str = "hcont") -> str:
    rate = _rate(root)
    for i in range(1000):
        candidate = f"{prefix}-{i}"
        if holdout.is_holdout(candidate, k, rate):
            return candidate
    raise AssertionError("could not find a holdout session id")


def _add_node(conn: sqlite3.Connection, key: str, kind: str, last_rid: int, degree: int = 1,
              detail: str = "", session_id: str = "s1") -> None:
    conn.execute(
        "INSERT INTO nodes(key,kind,first_rid,last_rid,degree,last_outcome,last_detail,"
        "session_id,agent) VALUES(?,?,?,?,?,?,?,?,?)",
        (key, kind, last_rid, last_rid, degree, "pass", detail, session_id, "main"),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# the session: turn 1 fails, turn 2 reads because of it, turn 3 (open) edits
# ---------------------------------------------------------------------------

def _record(conn, root, session_id, tool, tin, resp, uid):
    return common.record(conn, tool, tin, resp, session_id=session_id, agent="main",
                         bridge_version="v", bridge_sha="sha", root=root, tool_use_id=uid)


READ_INPUT = {"file_path": "payment/client.py"}
READ_RESPONSE = {"file": {"content": "def charge(amount, retries=0, timeout=2):\n    pass\n"}}
EDIT_INPUT = {"file_path": "payment/client.py", "old_string": "retries=0", "new_string": "retries=2"}


def _assistant(mid: str, uuid: str, block: dict) -> dict:
    return {"type": "assistant", "uuid": uuid, "message": {"id": mid, "role": "assistant", "content": [block]}}


def _write_transcript(path: str, *, read_in_transcript: bool = False) -> None:
    """Claude Code's real shape: one content block per line, all lines of a message
    sharing `message.id`; a user prompt first so last_user_prompt() has a query. With
    `read_in_transcript` the Read call (tu2) and its reason are in the transcript too,
    as they are when the read happened in the open turn."""
    entries = [{"type": "user", "message": {"role": "user", "content": "make charge retry"}}]
    if read_in_transcript:
        entries += [
            _assistant("msg_2", "u1", {"type": "text", "text": REASON2}),
            _assistant("msg_2", "u2", {"type": "tool_use", "id": "tu2", "name": "Read", "input": READ_INPUT}),
        ]
    entries += [
        _assistant("msg_3", "u3", {"type": "text", "text": REASON3}),
        _assistant("msg_3", "u4", {"type": "tool_use", "id": "tu3", "name": "Edit", "input": EDIT_INPUT}),
    ]
    with open(path, "w", encoding="utf-8") as f:
        for e in entries:
            f.write(json.dumps(e) + "\n")


def _build(root: str, session_id: str, *, extra_symbols: int = 0, read_in_open_turn: bool = False) -> Dict[str, int]:
    """The store through the real API, then the PreCompact row (mark_compaction) as the
    real event order has it -- the SessionStart `compact` hook runs after this. With
    `read_in_open_turn` there is no Stop between the Read and the Edit: both are the
    open turn's, and the Read's reason is not recorded either (it is in the transcript)."""
    conn = common.db(root)
    rids: Dict[str, int] = {}
    rids["r1"] = _record(conn, root, session_id, "Bash", {"command": "pytest -q"},
                         {"stdout": E1, "exitCode": 1}, "tu1")
    common.mark_turn(conn, session_id)
    rids["r2"] = _record(conn, root, session_id, "Read", READ_INPUT, READ_RESPONSE, "tu2")
    if not read_in_open_turn:
        assert common.record_reason(conn, rids["r2"], session_id, "tu2", REASON2) == [E1]
        common.mark_turn(conn, session_id)
    rids["r3"] = _record(conn, root, session_id, "Edit", EDIT_INPUT, {}, "tu3")
    # NO record_reason for r3: the open turn's reason must come from the transcript.
    last = conn.execute("SELECT MAX(id) FROM receipts").fetchone()[0]
    for i in range(extra_symbols):
        # high-degree, newest, a full lexical hit on the query, and only one token
        # ("charge") in common with REASON3 -- below REASON_MIN_OVERLAP, so the lift at
        # inject time cannot draw a `because` edge to them and they are never carried
        _add_node(conn, f"zeta_omega_{i}", "symbol", last, degree=9, detail="make charge retry",
                  session_id=session_id)
    common.mark_compaction(conn, session_id, os.path.join(root, ".plateau", "snapshots", "x.sqlite"))
    conn.close()
    return rids


def _payload(root: str, session_id: str, source: str = "compact", **transcript_kw) -> dict:
    transcript_path = os.path.join(root, "t.jsonl")
    _write_transcript(transcript_path, **transcript_kw)
    return {"cwd": root, "session_id": session_id, "transcript_path": transcript_path,
            "hook_event_name": "SessionStart", "source": source}


def _ctx(out: str, tag: str = common.TAG) -> str:
    j = json.loads(out)
    assert j["hookSpecificOutput"]["hookEventName"] == "SessionStart"
    ctx = j["hookSpecificOutput"]["additionalContext"]
    assert ctx.startswith(f"<{tag}>") and ctx.endswith(f"</{tag}>")
    return ctx


def _head_of(ctx: str) -> str:
    return ctx.split("\n", 2)[1]


def _lines(ctx: str) -> List[str]:
    return [ln for ln in ctx.split("\n") if ln.startswith("[r")]


def _line_for(ctx: str, key: str) -> str:
    hits = [ln for ln in _lines(ctx) if f" {key} " in ln]
    assert len(hits) == 1, (key, _lines(ctx))
    return hits[0]


def _log_lines(root: str) -> List[str]:
    with open(os.path.join(root, ".plateau", "hooks.log"), encoding="utf-8") as f:
        return [ln.rstrip("\n") for ln in f]


def _last_inject_log(root: str) -> str:
    lines = [ln for ln in _log_lines(root) if " inject ev=" in ln]
    assert lines
    return lines[-1]


def _reasons_for(root: str, rid: int):
    conn = sqlite3.connect(os.path.join(root, common.DB_REL))
    try:
        rows = conn.execute("SELECT text FROM reasons WHERE rid=?", (rid,)).fetchall()
        edges = conn.execute("SELECT src, rel, dst FROM edges WHERE rel='because' AND dst=?",
                             (f"r{rid}",)).fetchall()
        return rows, edges
    finally:
        conn.close()


def _injections(root: str):
    conn = sqlite3.connect(os.path.join(root, common.DB_REL))
    try:
        return conn.execute("SELECT keys, holdout, event FROM injections ORDER BY id").fetchall()
    finally:
        conn.close()


@pytest.fixture
def root():
    r = _git_root()
    try:
        yield r
    finally:
        shutil.rmtree(r, ignore_errors=True)


# ---------------------------------------------------------------------------
# (1)-(6) the compaction carries E1 and F1, having lifted the open turn's reason
# ---------------------------------------------------------------------------

def test_compaction_lifts_the_open_turns_reason_and_carries_its_ancestry(root):
    session_id = _non_holdout_session_id(root, (0, 1))
    rids = _build(root, session_id)
    payload = _payload(root, session_id)

    out, err, rc = run_hook("plateau.bridge.inject", payload, root)
    assert rc == 0 and err == "", err
    ctx = _ctx(out)
    assert len(ctx) <= 12000
    assert LEGEND_04 in _head_of(ctx)

    # (2) F1 was cited by the open turn's reason; E1 via F1 <- r2 <- E1. Nothing else.
    assert _line_for(ctx, F1).endswith(" ◉")
    assert _line_for(ctx, E1).endswith(" ◉")
    assert sum(1 for ln in _lines(ctx) if ln.endswith(" ◉")) == 2

    # (3) inject lifted the open turn's reason from the transcript
    rows, edges = _reasons_for(root, rids["r3"])
    assert len(rows) == 1 and "charge retries plan" in rows[0][0]
    assert (F1, "because", f"r{rids['r3']}") in edges

    # (4) the 0.3 log line, with the carried suffix appended
    m = LOG_RE.match(_last_inject_log(root))
    assert m and m.group(1) == "12000" and m.group(2) == " carried=2"

    # (5) the injections row lists the carried keys; not a holdout
    (keys, held, event), = _injections(root)
    assert set(json.loads(keys)) >= {F1, E1} and held == 0 and event == "compact"

    # (6) a second compaction over the same payload: lift is idempotent, carry repeats
    conn = common.db(root)
    common.mark_compaction(conn, session_id, os.path.join(root, ".plateau", "snapshots", "y.sqlite"))
    conn.close()
    out2, err, rc = run_hook("plateau.bridge.inject", payload, root)
    assert rc == 0 and err == "", err
    ctx2 = _ctx(out2)
    assert _line_for(ctx2, F1).endswith(" ◉") and _line_for(ctx2, E1).endswith(" ◉")
    rows2, _ = _reasons_for(root, rids["r3"])
    assert len(rows2) == 1
    m2 = LOG_RE.match(_last_inject_log(root))
    assert m2 and m2.group(2) == " carried=2"
    assert len(_injections(root)) == 2


def test_same_turn_ancestry_is_carried_because_a_compaction_evicts_the_open_turn_too(root):
    """The common real case: an auto-compaction fires mid-turn, after the open turn read
    `payment/client.py` and while it is acting on that read. A window of one request
    (the toy's "current request stays visible") would keep same-turn knowledge out of
    `carried`, but a Claude Code compaction summarizes the open turn as well, so the hook
    asks with `window=0` -- nothing stays -- and F1 is `◉` alongside E1."""
    session_id = _non_holdout_session_id(root, (0,))
    rids = _build(root, session_id, read_in_open_turn=True)
    payload = _payload(root, session_id, read_in_transcript=True)

    out, err, rc = run_hook("plateau.bridge.inject", payload, root)
    assert rc == 0 and err == "", err
    ctx = _ctx(out)
    assert _line_for(ctx, F1).endswith(" ◉") and _line_for(ctx, E1).endswith(" ◉")
    assert sum(1 for ln in _lines(ctx) if ln.endswith(" ◉")) == 2
    m = LOG_RE.match(_last_inject_log(root))
    assert m and m.group(2) == " carried=2"

    # both of the open turn's reasons were lifted at inject time
    rows2, edges2 = _reasons_for(root, rids["r2"])
    rows3, edges3 = _reasons_for(root, rids["r3"])
    assert len(rows2) == 1 and (E1, "because", f"r{rids['r2']}") in edges2
    assert len(rows3) == 1 and (F1, "because", f"r{rids['r3']}") in edges3

    # and why the hook asks with window=0, pinned against the store adapter itself
    conn = sqlite3.connect(os.path.join(root, common.DB_REL))
    try:
        one = carry_mod.carry_from_store(conn, session_id, window=1)
        none = carry_mod.carry_from_store(conn, session_id, window=0)
    finally:
        conn.close()
    assert one.turn == 2 and one.carried == [E1] and one.need == {E1, F1}
    assert none.carried == sorted([E1, F1]) and none.reachable == "2/2"


# ---------------------------------------------------------------------------
# (7) carried wins the budget over higher-scored nodes
# ---------------------------------------------------------------------------

def test_carried_line_wins_a_budget_with_room_for_one_line(root):
    session_id = _non_holdout_session_id(root, (0,))
    _build(root, session_id, extra_symbols=4)
    payload = _payload(root, session_id)

    # size the budget for the carrying head, the longer carried line, and a little slack
    # -- select() reserves for the closing tag on top of that
    head = inject_mod._head(common.TAG, carrying=True)
    conn = sqlite3.connect(os.path.join(root, common.DB_REL))
    cfg = bridge_config.load(root, session_id)
    scored = q.score_nodes(conn, "make charge retry", cfg, session_id)
    conn.close()
    by_key = {n["key"]: n for n in scored}
    assert all(by_key[f"zeta_omega_{i}"]["score"] > max(by_key[F1]["score"], by_key[E1]["score"])
               for i in range(4)), "the symbol nodes must outscore the carried ones for this test to bite"
    one_line = max(len(q.render_line(dict(by_key[k], carried=True))) for k in (F1, E1))
    budget = len(head) + one_line + 40

    out, err, rc = run_hook("plateau.bridge.inject", payload, root, argv=["--budget", str(budget)])
    assert rc == 0 and err == "", err
    ctx = _ctx(out)
    assert len(ctx) <= budget
    lines = _lines(ctx)
    assert len(lines) == 1 and lines[0].endswith(" ◉")
    assert "zeta_omega" not in ctx
    m = LOG_RE.match(_last_inject_log(root))
    assert m and m.group(1) == str(budget) and m.group(2) == " carried=1"


# ---------------------------------------------------------------------------
# (8)-(11) the exclusions leave the 0.3 block and log line byte-identical
# ---------------------------------------------------------------------------

def _write_root_toml(root: str, carry: bool) -> None:
    with open(bridge_config.DEFAULT_TOML, encoding="utf-8") as f:
        text = f.read()
    assert "[continuum]\ncarry = true" in text
    if not carry:
        text = text.replace("[continuum]\ncarry = true", "[continuum]\ncarry = false", 1)
    with open(os.path.join(root, "bridge.toml"), "w", encoding="utf-8") as f:
        f.write(text)


@pytest.mark.parametrize("carry_flag, extra_env, source, tag, budget", [
    pytest.param(False, None, "compact", common.TAG, "12000", id="kill-switch"),
    pytest.param(True, {"PLATEAU_LEGACY_TAG": "1"}, "compact", common.LEGACY_TAG, "12000", id="legacy-tag"),
    pytest.param(True, None, "startup", common.TAG, "6000", id="startup-source"),
])
def test_exclusions_neither_lift_nor_carry_and_keep_the_03_head(root, carry_flag, extra_env, source, tag, budget):
    """`[continuum] carry = false`, `PLATEAU_LEGACY_TAG=1` and a `startup` source each
    produce the 0.3 block byte-for-byte: no `◉` line, the 0.3 legend with no `◉` clause,
    no reasons row lifted for the open turn, and a log line with no ` carried=` suffix."""
    if not carry_flag:
        _write_root_toml(root, carry=False)
        assert bridge_config.load(root, "x").continuum["carry"] is False
    session_id = _non_holdout_session_id(root, (0,))
    rids = _build(root, session_id)

    out, err, rc = run_hook("plateau.bridge.inject", _payload(root, session_id, source=source), root,
                            extra_env=extra_env)
    assert rc == 0 and err == "", err
    ctx = _ctx(out, tag=tag)
    assert "◉" not in ctx
    assert LEGEND_03 in _head_of(ctx)
    rows, _ = _reasons_for(root, rids["r3"])
    assert rows == []
    m = LOG_RE.match(_last_inject_log(root))
    assert m and m.group(1) == budget and m.group(2) == ""


def test_holdout_compaction_returns_before_the_carry_step(root):
    session_id = _holdout_session_id(root, 0)
    rids = _build(root, session_id)

    out, err, rc = run_hook("plateau.bridge.inject", _payload(root, session_id), root)
    assert rc == 0 and err == "", err
    assert json.loads(out) == {}
    line = _last_inject_log(root)
    assert line.endswith(" holdout=1") and "carried=" not in line
    rows, _ = _reasons_for(root, rids["r3"])
    assert rows == []
    (keys, held, _event), = _injections(root)
    assert json.loads(keys) == [] and held == 1


# ---------------------------------------------------------------------------
# failure modes: a lift that raises is rolled back; a transcript cut mid-byte is skipped
# ---------------------------------------------------------------------------

def test_carry_step_rolls_back_a_lift_that_raises_and_still_carries(root, monkeypatch):
    """`common.record_reason` inserts the reasons row and its edges before its own
    commit; if the lift raises in between, a reasons row without its arrows must not
    reach the store (every later Stop would skip that receipt for good). The carry half
    still runs over what the store already holds."""
    session_id = _non_holdout_session_id(root, (0,))
    rids = _build(root, session_id, read_in_open_turn=True)
    conn = common.db(root)
    assert common.record_reason(conn, rids["r2"], session_id, "tu2", REASON2) == [E1]   # already in the store

    def half_lift(conn_, sid, path):
        conn_.execute("INSERT INTO reasons(rid,session_id,tool_use_id,text) VALUES(?,?,?,?)",
                      (rids["r3"], sid, "tu3", REASON3))
        raise RuntimeError("boom mid-link")

    monkeypatch.setattr(lift_mod, "lift_reasons", half_lift)
    carried = inject_mod._carry_step(conn, root, session_id, os.path.join(root, "t.jsonl"))
    conn.commit()   # what main() does next, for the injections row
    conn.close()

    rows, _ = _reasons_for(root, rids["r3"])
    assert rows == []                                          # rolled back, not persisted
    assert carried == [E1]                                     # via r2's arrow, already in the store
    errors = [ln for ln in _log_lines(root) if "inject carry ERROR" in ln]
    assert len(errors) == 1 and "boom mid-link" in errors[0]


def test_transcript_cut_inside_a_multibyte_sequence_is_skipped_not_raised(root, tmp_path):
    """Claude Code appends the JSONL while the hook reads it, so the tail can end inside
    a multibyte sequence. Before this fix both readers raised UnicodeDecodeError out of
    the hook (`inject ERROR`, `{}` printed, no injection at all); now the half line is
    skipped like any other garbage line and the compaction carries as usual."""
    p = tmp_path / "t.jsonl"
    p.write_bytes(json.dumps({"type": "user", "message": {"role": "user", "content": "real prompt"}}).encode()
                  + b"\n" + TRUNCATED_TAIL)
    assert q.last_user_prompt(str(p)) == "real prompt"
    assert lift_mod.reasons_from_transcript(str(p)) == {}

    session_id = _non_holdout_session_id(root, (0,))
    rids = _build(root, session_id)
    payload = _payload(root, session_id)
    with open(payload["transcript_path"], "ab") as f:
        f.write(TRUNCATED_TAIL)

    out, err, rc = run_hook("plateau.bridge.inject", payload, root)
    assert rc == 0 and err == "", err
    ctx = _ctx(out)
    assert _line_for(ctx, F1).endswith(" ◉") and _line_for(ctx, E1).endswith(" ◉")
    rows, _ = _reasons_for(root, rids["r3"])
    assert len(rows) == 1
    assert not any("ERROR" in ln for ln in _log_lines(root))
    m = LOG_RE.match(_last_inject_log(root))
    assert m and m.group(2) == " carried=2"


def test_stop_over_a_transcript_cut_mid_multibyte_still_lifts_the_last_decision(root):
    """The third transcript reader, `lift._last_assistant_text_blocks` (the Stop hook's
    DECISION/FACT lifter), kept a strict decode after the fix above: a Stop over the same
    truncated tail raised UnicodeDecodeError out of lift_decisions (`lift ERROR`), lifted
    no decision -- lost for good, since only the LAST assistant message is scanned -- and,
    because lift_decisions runs before lift_reasons in main(), lifted no reason either.
    Now the half line is skipped there too: the FACT lands, the open turn's reason lands,
    and the log holds no ERROR."""
    session_id = _non_holdout_session_id(root, (0,))
    rids = _build(root, session_id)
    payload = _payload(root, session_id)
    payload["hook_event_name"] = "Stop"
    del payload["source"]
    with open(payload["transcript_path"], "ab") as f:
        f.write(json.dumps(_assistant("msg_4", "u5", {"type": "text", "text": "FACT: charge retries now 2"})).encode()
                + b"\n" + TRUNCATED_TAIL)

    out, err, rc = run_hook("plateau.bridge.lift", payload, root)
    assert rc == 0 and err == "", err
    conn = sqlite3.connect(os.path.join(root, common.DB_REL))
    try:
        decisions = [r[0] for r in conn.execute("SELECT text FROM decisions WHERE session_id=?", (session_id,))]
    finally:
        conn.close()
    assert decisions == ["charge retries now 2"]
    rows, edges = _reasons_for(root, rids["r3"])
    assert len(rows) == 1 and (F1, "because", f"r{rids['r3']}") in edges
    assert not any("ERROR" in ln for ln in _log_lines(root))


# ---------------------------------------------------------------------------
# (12) select() / render_line() unit behaviour (tests/test_selector.py style)
# ---------------------------------------------------------------------------

def make_cfg():
    sel = {
        "tau_turns": 3, "degree_cap": 3,
        "weights": {"symbol": 1.4, "error": 1.3, "decided": 1.4, "read": 1.2, "test": 1.2,
                    "file": 0.7, "command": 0.6, "search": 0.3},
        "bridge_quota": 0.40, "sticky": True, "lexical": True,
    }
    return types.SimpleNamespace(selector=sel, budget={"compaction_chars": 12000})


def _n(key: str, kind: str, score: float, rid: int = 1, older: bool = False) -> dict:
    return {"key": key, "kind": kind, "first_rid": rid, "last_rid": rid, "degree": 1,
            "outcome": "seen", "detail": "", "score": score, "lexical_hit": False,
            "older_than_prev_compaction": older}


HEAD = "<plateau_index>\n"


def _select(scored, budget, **kw):
    kw.setdefault("sticky_keys", [])
    kw.setdefault("edited_since", set())
    kw.setdefault("resolved_errors", set())
    return q.select(scored, budget, make_cfg(), head=HEAD, **kw)


def test_select_carried_come_first_regardless_of_score_and_are_marked_copies():
    scored = [_n("hot", "symbol", 9.0), _n("warm", "file", 5.0), _n("old_fact", "read", 0.1),
              _n("old_err", "error", 0.2)]
    before = [dict(n) for n in scored]
    chosen = _select(scored, 12000, carried_keys=["old_fact", "old_err"])
    assert [n["key"] for n in chosen][:2] == ["old_err", "old_fact"]      # score order within carried
    assert [n["key"] for n in chosen][2:] == ["hot", "warm"]
    assert all(n.get("carried") is True for n in chosen[:2])
    assert all("carried" not in n for n in chosen[2:])
    assert scored == before                                                # inputs untouched
    assert all(c is not s for c in chosen[:2] for s in scored)             # copies


def test_select_carried_error_is_kept_even_when_resolved_and_unknown_or_duplicate_keys_are_harmless():
    scored = [_n("boom", "error", 0.1), _n("f.py", "file", 0.2), _n("x", "symbol", 3.0)]
    chosen = _select(scored, 12000, sticky_keys=["boom", "f.py"],
                     edited_since={"f.py"}, resolved_errors={"boom"},
                     carried_keys=["boom", "boom", "nope", "f.py"])
    keys = [n["key"] for n in chosen]
    assert keys == ["f.py", "boom", "x"]                                   # once each, carried first
    assert keys.count("boom") == 1 and "nope" not in keys
    assert chosen[0]["carried"] and chosen[1]["carried"]


def test_select_budget_never_exceeded_with_carried_and_carried_wins_the_last_slot():
    scored = [_n("hot%d" % i, "symbol", 9.0 - i) for i in range(5)] + [_n("old", "read", 0.01)]
    one = len(q.render_line(dict(scored[-1], carried=True))) + 1
    budget = len(HEAD) + q._CLOSE_TAG_RESERVE + one + 10                    # room for one line only
    chosen = _select(scored, budget, carried_keys=["old"])
    assert [n["key"] for n in chosen] == ["old"]
    assert len(q.render(chosen, HEAD, "plateau_index")) <= budget


def test_select_without_carried_keys_is_the_03_selection():
    """Pinned against the 0.3 selector's output worked by hand, not against itself:
    sticky `c` is re-included first; the dry-run fill would produce 3 lines, so the
    quota wants round(0.4 * 3) = 1 older line, which `c` (older) already satisfies;
    then `a`, `b` by score. No entry gains a `carried` key, and the entries are the
    input dicts themselves, as 0.3 returned them."""
    scored = [_n("a", "symbol", 2.0), _n("b", "file", 1.0, older=True), _n("c", "read", 0.5, older=True)]
    expected = ["c", "a", "b"]
    for kw in ({}, {"carried_keys": ()}):
        chosen = _select(scored, 12000, sticky_keys=["c"], **kw)
        assert [n["key"] for n in chosen] == expected
        assert all("carried" not in n for n in chosen)
        assert all(any(n is s for s in scored) for n in chosen)


@pytest.mark.parametrize("flags, rendered", [
    pytest.param({"carried": True}, "[r3] read k → seen ×1 ◉", id="carried-only"),
    pytest.param({"lexical_hit": True, "carried": True}, "[r3] read k → seen ×1 ★ ◉", id="star-then-fisheye"),
    pytest.param({"lexical_hit": True}, "[r3] read k → seen ×1 ★", id="star-only"),
    pytest.param({"carried": False}, "[r3] read k → seen ×1", id="carried-false"),
])
def test_render_line_marks_carried_after_the_lexical_star(flags, rendered):
    base = {"key": "k", "kind": "read", "last_rid": 3, "degree": 1, "outcome": "seen", "detail": ""}
    assert q.render_line(dict(base, **flags)) == rendered


# ---------------------------------------------------------------------------
# (13) config: the [continuum] table and the 2.1 version
# ---------------------------------------------------------------------------

def test_config_continuum_defaults_and_root_override(tmp_path):
    cfg = bridge_config.load(str(tmp_path))
    assert cfg.continuum == {"carry": True}
    assert cfg.version == "2.1"
    (tmp_path / "bridge.toml").write_text('version = "2.1"\n[continuum]\ncarry = false\n')
    assert bridge_config.load(str(tmp_path)).continuum["carry"] is False


def test_packaged_default_and_root_toml_are_identical_and_the_fallback_parser_reads_continuum():
    """Byte identity of the two files, and that the dependency-free parser reads the new
    table (its agreement with tomllib on this file is already pinned by
    tests/test_bridge.py::test_fallback_toml_matches_tomllib_on_bridge_toml)."""
    with open(bridge_config.DEFAULT_TOML, "rb") as f:
        packaged = f.read()
    with open(os.path.join(REPO_ROOT, "bridge.toml"), "rb") as f:
        root_toml = f.read()
    assert packaged == root_toml
    parsed = bridge_toml.loads(packaged.decode("utf-8"))
    assert parsed["version"] == "2.1" and parsed["continuum"] == {"carry": True}


def _compact_summary(text: str) -> dict:
    """The user-side entry Claude Code writes after a compaction boundary."""
    return {"type": "user", "isCompactSummary": True, "isVisibleInTranscriptOnly": True,
            "message": {"role": "user", "content": text}}


def test_last_user_prompt_skips_compaction_summaries_and_meta_turns(tmp_path):
    """Defect 1 (docs/mechanism.md): when two compactions fall in one turn, the last
    user-side entry at the second is the first one's summary. The query must be the
    prompt the person typed, which the append-only transcript still holds."""
    summary = "This session is being continued from a previous conversation. " * 400
    entries = [
        {"type": "user", "message": {"role": "user", "content": "make charge retry"}},
        {"type": "system", "subtype": "compact_boundary"},
        _compact_summary(summary),
        {"type": "user", "isMeta": True,
         "message": {"role": "user", "content": "Caveat: the messages below were generated by local commands."}},
    ]
    p = tmp_path / "t.jsonl"
    p.write_text("".join(json.dumps(e) + "\n" for e in entries), encoding="utf-8")
    assert q.last_user_prompt(str(p)) == "make charge retry"

    # A prompt typed after the summary is still the one taken.
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps({"type": "user", "message": {"role": "user", "content": "now add jitter"}}) + "\n")
    assert q.last_user_prompt(str(p)) == "now add jitter"

    # Summary as a content-block list is skipped the same way.
    only = tmp_path / "only.jsonl"
    only.write_text(json.dumps({"type": "user", "isCompactSummary": True,
                                "message": {"role": "user", "content": [{"type": "text", "text": summary}]}}) + "\n",
                    encoding="utf-8")
    assert q.last_user_prompt(str(only)) == ""


def test_second_compaction_in_one_turn_queries_the_prompt_not_the_summary(root):
    """End to end through the hook: the logged query length is the typed prompt's, not
    the summary's (the 5-turn adapter run logged q=25583ch here)."""
    session_id = _non_holdout_session_id(root, (0,))
    _build(root, session_id)
    payload = _payload(root, session_id)
    with open(payload["transcript_path"], "a", encoding="utf-8") as f:
        f.write(json.dumps({"type": "system", "subtype": "compact_boundary"}) + "\n")
        f.write(json.dumps(_compact_summary("summary " * 3000)) + "\n")

    out, err, rc = run_hook("plateau.bridge.inject", payload, root)
    assert rc == 0, err
    assert f" q={len('make charge retry')}ch " in _last_inject_log(root)
