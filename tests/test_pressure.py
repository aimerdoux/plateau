"""0.5: compaction as a Plateau procedure (plateau.bridge.pressure)."""

from __future__ import annotations

import datetime as dt
import json
import os
import subprocess
import sys
import tempfile
import types

from plateau.bridge import common, pressure

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _cfg(**c):
    base = {"enabled": True, "mid_task": True, "soft_pct": 50, "hard_pct": 60, "window": 1000, "steer_summary": True}
    base.update(c)
    return types.SimpleNamespace(compaction=base)


def _iso(ts):
    return dt.datetime.fromtimestamp(ts, dt.timezone.utc).isoformat().replace("+00:00", "Z")


class Transcript:
    def __init__(self, path):
        self.path = path
        open(path, "w").close()

    def assistant(self, tokens, text="", sidechain=False, ts=None):
        e = {"type": "assistant", "isSidechain": sidechain, "timestamp": _iso(ts or 0) if ts else _iso(1),
             "message": {"usage": {"input_tokens": 1, "cache_read_input_tokens": tokens - 1,
                                   "cache_creation_input_tokens": 0},
                         "content": [{"type": "text", "text": text}] if text else []}}
        with open(self.path, "a") as f:
            f.write(json.dumps(e) + "\n")


def _setup(tmp_path):
    root = str(tmp_path)
    conn = common.db(root)
    t = Transcript(str(tmp_path / "t.jsonl"))
    payload = {"session_id": "s1", "transcript_path": t.path}
    return root, conn, t, payload


def test_context_tokens_reads_the_last_main_agent_usage(tmp_path):
    t = Transcript(str(tmp_path / "t.jsonl"))
    t.assistant(100)
    t.assistant(400)
    t.assistant(900, sidechain=True)
    assert pressure.context_tokens(t.path) == 400


def test_below_soft_nothing_then_the_procedure_once(tmp_path):
    root, conn, t, payload = _setup(tmp_path)
    t.assistant(400)
    assert pressure.check(conn, root, payload, _cfg()) is None
    t.assistant(520)
    text = pressure.check(conn, root, payload, _cfg())
    assert text and "compaction procedure" in text and "52%" in text and "60%" in text
    t.assistant(530)
    assert pressure.check(conn, root, payload, _cfg()) is None  # once per cycle


def test_markers_after_the_procedure_crystallize_into_decisions(tmp_path):
    root, conn, t, payload = _setup(tmp_path)
    t.assistant(520)
    assert pressure.check(conn, root, payload, _cfg())
    later = dt.datetime.now().timestamp() + 5
    t.assistant(530, text="DECISION: keep WAL mode\nFACT: api caps at 60 rpm (docs/api.md)\nOPEN: wire the retry", ts=later)
    assert pressure.check(conn, root, payload, _cfg()) is None
    texts = [r[0] for r in conn.execute("SELECT text FROM decisions WHERE session_id='s1'")]
    assert "keep WAL mode" in texts and "OPEN: wire the retry" in texts
    events = [r[0] for r in conn.execute("SELECT event FROM pressure ORDER BY ts")]
    assert events == ["soft", "crystallized"]


def test_a_reminder_at_the_midpoint_when_nothing_was_written(tmp_path):
    root, conn, t, payload = _setup(tmp_path)
    t.assistant(510)
    assert pressure.check(conn, root, payload, _cfg())
    t.assistant(560)
    text = pressure.check(conn, root, payload, _cfg())
    assert text and "no DECISION:/FACT:/OPEN: line" in text
    t.assistant(590)
    assert pressure.check(conn, root, payload, _cfg()) is None


def test_a_floor_above_the_soft_line_is_logged_not_nagged(tmp_path):
    root, conn, t, payload = _setup(tmp_path)
    t.assistant(700, ts=dt.datetime.now().timestamp() - 60)  # the pre-compaction reading
    pressure._record(conn, "s1", 0, "compact", 700, 1000)  # a main-agent compaction
    assert pressure.check(conn, root, payload, _cfg()) is None
    assert conn.execute("SELECT COUNT(*) FROM pressure WHERE event='floor'").fetchone()[0] == 0  # stale: not a floor
    t.assistant(700, ts=dt.datetime.now().timestamp() + 5)  # first real reading after it, still past soft
    assert pressure.check(conn, root, payload, _cfg()) is None
    assert pressure.check(conn, root, payload, _cfg()) is None
    assert [r[0] for r in conn.execute("SELECT event FROM pressure")] == ["compact", "floor"]


def test_disabled_and_subagents_never_inject(tmp_path):
    root, conn, t, payload = _setup(tmp_path)
    t.assistant(900)
    assert pressure.check(conn, root, payload, _cfg(enabled=False)) is None
    assert pressure.check(conn, root, dict(payload, agent_id="a1", agent_type="general-purpose"), _cfg()) is None


def test_thresholds_follow_the_live_override_and_window_the_settings(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_AUTOCOMPACT_PCT_OVERRIDE", "30")
    assert pressure.thresholds(_cfg(soft_pct=0, hard_pct=0)) == (25.0, 30.0)
    monkeypatch.delenv("CLAUDE_AUTOCOMPACT_PCT_OVERRIDE")
    assert pressure.thresholds(_cfg(soft_pct=0, hard_pct=0)) == (90.0, 95.0)
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "settings.json").write_text(json.dumps({"autoCompactWindow": 800000}))
    assert pressure.window_tokens(str(tmp_path), _cfg(window=0)) == 800000
    assert pressure.window_tokens(str(tmp_path), _cfg(window=5000)) == 5000


def _hook(module, payload, root):
    env = dict(os.environ, PYTHONPATH=REPO_ROOT)
    return subprocess.run([sys.executable, "-m", module], input=json.dumps(payload), cwd=root,
                          env=env, capture_output=True, text=True, timeout=30)


def _git_root():
    root = tempfile.mkdtemp(prefix="plateau-050-")
    subprocess.run(["git", "init", "-q", root], capture_output=True, timeout=10)
    return root


def test_precompact_prints_plain_text_instructions_and_logs_the_compaction():
    root = _git_root()
    with open(os.path.join(root, "bridge.toml"), "w") as f:
        f.write("[compaction]\nenabled = true\nwindow = 1000\nhard_pct = 60\nsoft_pct = 50\n")
    t = Transcript(os.path.join(root, "t.jsonl"))
    t.assistant(650)
    conn = common.db(root)
    conn.close()
    r = _hook("plateau.bridge.snapshot", {"session_id": "s1", "transcript_path": t.path, "trigger": "auto"}, root)
    assert r.returncode == 0, r.stderr
    assert r.stdout.startswith("Plateau compaction procedure.")
    assert "hookSpecificOutput" not in r.stdout
    conn = common.db(root)
    assert conn.execute("SELECT event, tokens FROM pressure").fetchall() == [("compact", 650)]


def test_the_receipt_hook_emits_the_procedure_when_the_line_is_crossed():
    root = _git_root()
    with open(os.path.join(root, "bridge.toml"), "w") as f:
        f.write("[compaction]\nenabled = true\nmid_task = true\nwindow = 1000\nhard_pct = 60\nsoft_pct = 50\n")
    t = Transcript(os.path.join(root, "t.jsonl"))
    t.assistant(520)
    payload = {"session_id": "s1", "transcript_path": t.path, "hook_event_name": "PostToolUse",
               "tool_name": "Bash", "tool_input": {"command": "ls"}, "tool_response": {"stdout": "a"}}
    r = _hook("plateau.bridge.receipt", payload, root)
    out = json.loads(r.stdout)
    assert out["hookSpecificOutput"]["hookEventName"] == "PostToolUse"
    assert "compaction procedure" in out["hookSpecificOutput"]["additionalContext"]
    r2 = _hook("plateau.bridge.receipt", payload, root)
    assert r2.stdout.strip() == ""


def test_compaction_cli_applies_and_reverts(tmp_path, monkeypatch, capsys):
    from plateau.bridge import compaction
    home = os.environ["HOME"]
    os.makedirs(os.path.join(home, ".claude"))
    with open(os.path.join(home, ".claude", "settings.json"), "w") as f:
        json.dump({"autoCompactWindow": 800000, "env": {"KEEP": "1"}}, f)
    os.makedirs(os.path.join(home, ".plateau"))
    with open(os.path.join(home, ".plateau", "bridge.toml"), "w") as f:
        f.write("[lab]\nholdout_rate = 0.50\n")
    monkeypatch.chdir(tmp_path)

    assert compaction.main(["--apply", "25", "--soft", "20"]) == 0
    s = json.load(open(os.path.join(home, ".claude", "settings.json")))
    assert s["env"] == {"KEEP": "1", "CLAUDE_AUTOCOMPACT_PCT_OVERRIDE": "25"}
    toml = open(os.path.join(home, ".plateau", "bridge.toml")).read()
    assert "holdout_rate = 0.50" in toml and "enabled = true" in toml and "soft_pct = 20" in toml
    out = capsys.readouterr().out
    assert "procedure: on" in out and "hard line (native compaction): 25% = 200k" in out

    assert compaction.main(["--off"]) == 0
    s = json.load(open(os.path.join(home, ".claude", "settings.json")))
    assert s["env"] == {"KEEP": "1"}
    assert open(os.path.join(home, ".plateau", "bridge.toml")).read() == "[lab]\nholdout_rate = 0.50\n"


def test_the_hard_line_calibrates_to_where_compaction_really_fired(tmp_path):
    root, conn, t, payload = _setup(tmp_path)
    pressure._record(conn, "s1", 0, "compact", 0, 1000)
    with open(t.path, "a") as f:  # Claude Code's own record of the compaction
        f.write(json.dumps({"type": "system", "subtype": "compact_boundary",
                            "compactMetadata": {"trigger": "auto", "preTokens": 300}}) + "\n")
    t.assistant(200, ts=dt.datetime.now().timestamp() + 5)
    assert pressure.check(conn, root, payload, _cfg()) is None
    assert pressure.observed_hard_tokens(conn) == 300
    # hard 60% now means 300 tokens, so soft 50% is 250 tokens -- not 500 of the nominal 1000
    t.assistant(260, ts=dt.datetime.now().timestamp() + 6)
    text = pressure.check(conn, root, payload, _cfg())
    assert text and "compaction procedure" in text


def test_a_subagent_precompact_does_not_advance_the_parent_cycle(tmp_path):
    root, conn, t, payload = _setup(tmp_path)
    t.assistant(400)
    sub = dict(payload, agent_type="general-purpose", agent_id="a1", trigger="auto")
    pressure.before_compaction(conn, root, sub, _cfg())
    assert pressure._k(conn, "s1") == 0
    pressure.before_compaction(conn, root, dict(payload, trigger="auto"), _cfg())
    assert pressure._k(conn, "s1") == 1


def test_the_soft_margin_widens_when_compaction_beats_crystallization(tmp_path):
    root, conn, t, payload = _setup(tmp_path)
    t.assistant(520)
    assert pressure.check(conn, root, payload, _cfg())       # soft at 520 (line 500 of 1000)
    pressure.before_compaction(conn, root, dict(payload, trigger="auto"), _cfg())  # no markers
    with open(t.path, "a") as f:  # where Claude Code really compacted
        f.write(json.dumps({"type": "system", "subtype": "compact_boundary",
                            "compactMetadata": {"trigger": "auto", "preTokens": 620}}) + "\n")
    t.assistant(300, ts=dt.datetime.now().timestamp() + 10)  # post-compaction size
    assert pressure.check(conn, root, payload, _cfg()) is None
    # hard = 620 observed; margin = 1.5 x (620 - 520) = 150 -> soft line 470 (not 516)
    assert pressure.lines(conn, 1000, 50, 60) == (620, 470)
    t.assistant(480, ts=dt.datetime.now().timestamp() + 11)
    assert pressure.check(conn, root, payload, _cfg())


def test_a_large_tool_result_fires_the_procedure_one_step_early(tmp_path):
    root, conn, t, payload = _setup(tmp_path)
    t.assistant(400)  # below the 500 line by itself
    big = dict(payload, tool_response={"content": "x" * 420})  # ~120 tokens arriving now
    assert pressure.check(conn, root, big, _cfg())
    assert pressure._meta_int(conn, "compaction.step_tokens") >= 120


def test_the_summary_crystallizes_into_the_graph_after_compaction(tmp_path):
    root, conn, t, payload = _setup(tmp_path)
    t.assistant(600)
    pressure.before_compaction(conn, root, dict(payload, trigger="auto"), _cfg())
    summary = ("Summary:\n1. Primary request: audit data.py\nCrystallized\n"
               "DECISION: read the file myself, no subagents (user asked)\n"
               "- FACT: MAGIC_CONSTANT = 48213 at data.py:280\n"
               "OPEN: reads 6-9 remain\nDetails: `plateau lookup <words>` before re-reading any file.")
    with open(t.path, "a") as f:
        f.write(json.dumps({"type": "system", "subtype": "compact_boundary",
                            "compactMetadata": {"trigger": "auto", "preTokens": 640}}) + "\n")
        f.write(json.dumps({"type": "user", "isCompactSummary": True,
                            "message": {"role": "user", "content": summary}}) + "\n")
    t.assistant(200, ts=dt.datetime.now().timestamp() + 5)
    pressure.check(conn, root, payload, _cfg(mid_task=False))
    texts = {r[0] for r in conn.execute("SELECT text FROM decisions")}
    assert {"read the file myself, no subagents (user asked)",
            "MAGIC_CONSTANT = 48213 at data.py:280", "OPEN: reads 6-9 remain"} <= texts
    assert conn.execute("SELECT tokens FROM pressure WHERE event='summary'").fetchone()[0] == 3


def test_without_mid_task_the_soft_line_is_recorded_but_not_injected(tmp_path):
    root, conn, t, payload = _setup(tmp_path)
    t.assistant(520)
    assert pressure.check(conn, root, payload, _cfg(mid_task=False)) is None
    assert [r[0] for r in conn.execute("SELECT event FROM pressure")] == ["soft"]
