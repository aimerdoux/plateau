"""tests/test_absorb.py — owner D1 (docs/harness-0.3/PLAN-absorb.md).

Covers: the fail-closed leak scan (a planted path, symbol and decision text in a
synthetic raw/store must make `absorb` refuse), the structural code-fence/path-shaped
rules, `run.json`/`hashes.json` shape, `absorb --check`'s tamper detection, an
end-to-end experiment absorb whose `derived.json` reproduces a synthetic
`results.json` (and refuses when it does not), an end-to-end adapter absorb, and
`plateau.lab.fit.from_primitives` picking up an absorbed experiment run.
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess

import pytest

from plateau import absorb
from plateau import cli as cli_mod
from plateau.lab import fit as fit_mod

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ---------------------------------------------------------------------------
# small building blocks
# ---------------------------------------------------------------------------


def _write_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f)


def _write_jsonl(path, records):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")


def _assistant_line(msg_id, usage, tool_uses=()):
    content = [
        {"type": "tool_use", "id": tu_id, "name": name, "input": tin}
        for tu_id, name, tin in tool_uses
    ]
    return {"type": "assistant", "message": {"id": msg_id, "model": "m1", "usage": usage, "content": content}}


def _user_text_line(text):
    return {"type": "user", "message": {"content": text}}


def _user_tool_result_line(tool_use_id, result):
    return {
        "type": "user",
        "message": {"content": [{"type": "tool_result", "tool_use_id": tool_use_id}]},
        "toolUseResult": result,
    }


def _compact_boundary():
    return {"type": "system", "subtype": "compact_boundary"}


def _write_transcript(path, lines):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for line in lines:
            f.write(json.dumps(line) + "\n")


# ---------------------------------------------------------------------------
# synthetic experiment raw (D-038-shaped)
# ---------------------------------------------------------------------------

PROMPTS = ["Do task one", "Do task two"]
FOOTER = "FOOTER"


def _turns_json_doc():
    return {
        "common_footer": FOOTER,
        "epics": [{"id": "E1", "turns": [{"id": "T1", "prompt": PROMPTS[0]}, {"id": "T2", "prompt": PROMPTS[1]}]}],
    }


def _arm_transcript_lines(read_path):
    return [
        _user_text_line(PROMPTS[0] + "\n\n" + FOOTER),
        _assistant_line("m1", {"input_tokens": 100, "output_tokens": 10}, [("tu1", "Read", {"file_path": read_path})]),
        _user_tool_result_line("tu1", {"file": {"content": "print(1)"}}),
        _compact_boundary(),
        _assistant_line("m2", {"input_tokens": 50, "output_tokens": 5}, [("tu2", "Read", {"file_path": read_path})]),
        _user_tool_result_line("tu2", {"file": {"content": "print(1)"}}),
        _user_text_line(PROMPTS[1] + "\n\n" + FOOTER),
        _assistant_line("m3", {"input_tokens": 20, "output_tokens": 2}, []),
    ]


def _manifest(hooks, task_cost=1.0, probe_cost=0.5):
    return {
        "main_session": "sess1",
        "claude_version": "claude-2.0",
        "window": 1000, "pct": "10", "budget": 999,
        "target": {"commit": "deadbeef", "tree": "cafef00d", "subtree": "scripts/mytarget", "dirty": False},
        "hooks": hooks,
        "task_cost_usd": task_cost, "probe_cost_usd": probe_cost,
        "turns": [
            {"i": 1, "id": "T1", "seconds": 1.0, "cost": 0.1, "models": ["m1"]},
            {"i": 2, "id": "T2", "seconds": 1.0, "cost": 0.1, "models": ["m1"]},
        ],
    }


def _probes_for(lag_buckets_comp_buckets):
    out = []
    tokens_since = {0: 500, 1: 30_000, 2: 70_000}
    for i, (lag_b, comp_b) in enumerate(lag_buckets_comp_buckets, 1):
        out.append({
            "turn": 1, "id": "f{}".format(i), "cls": "read", "kind": "signature",
            "q": "some secret question about handleSuperSecretPayment",
            "expected": "handleSuperSecretPayment", "answer": "handleSuperSecretPayment",
            "tokens_since": tokens_since[lag_b], "compactions_crossed": comp_b,
            "lag_bucket": lag_b, "comp_bucket": comp_b, "probe_contaminates": False,
        })
    return out


def _judge_for(verdicts):
    return {
        "probes": [{"id": "f{}".format(i + 1), "verdict": v, "cite": "somefile.py:{}".format(i)} for i, v in enumerate(verdicts)],
        "epics": {"E1": {"score": 3, "cite": "irrelevant"}},
        "security_items_closed": [],
        "tests": {"runner_green": True},
        "defects": "no defects of note",
        "_cost_usd": 0.1,
    }


def _build_experiment_raw(root, read_path="/work/mytarget/foo.py"):
    raw_dir = os.path.join(root, "raw")
    run_dir = os.path.join(raw_dir, "1")
    blind = {"tok_a": "A", "tok_c": "C"}
    _write_json(os.path.join(run_dir, "blind.json"), blind)

    # arm A: native, no bridge; lag0 exact, lag1 fuzzy, lag2 wrong
    a_dir = os.path.join(run_dir, "tok_a")
    _write_json(os.path.join(a_dir, "manifest.json"), _manifest(hooks={}))
    _write_jsonl(os.path.join(a_dir, "probes.jsonl"), _probes_for([(0, 0), (1, 0), (2, 1)]))
    _write_json(os.path.join(a_dir, "judge.json"), _judge_for(["exact", "fuzzy", "wrong"]))
    _write_json(os.path.join(a_dir, "judge_view", "turns.json"), _turns_json_doc())
    _write_transcript(os.path.join(a_dir, "transcript", "sess1.jsonl"), _arm_transcript_lines(read_path))

    # arm C: bridge; lag0 exact, lag1 exact, lag2 fuzzy
    c_dir = os.path.join(run_dir, "tok_c")
    _write_json(os.path.join(c_dir, "manifest.json"), _manifest(hooks={".claude/settings.json": "sha"}))
    _write_jsonl(os.path.join(c_dir, "probes.jsonl"), _probes_for([(0, 0), (1, 0), (2, 1)]))
    _write_json(os.path.join(c_dir, "judge.json"), _judge_for(["exact", "exact", "fuzzy"]))
    _write_json(os.path.join(c_dir, "judge_view", "turns.json"), _turns_json_doc())
    _write_transcript(os.path.join(c_dir, "transcript", "sess1.jsonl"), _arm_transcript_lines(read_path))

    return raw_dir


# derived numbers a correct implementation must produce from the fixture above
EXPECTED_DERIVED = {
    "far_recall": {"A": 0.0, "C": 0.5},
    "auc": {"A": 0.5, "C": 0.875},
    "rederivations": {"A": 1, "C": 1},
    "tokens_per_turn": {"A": 93.5, "C": 93.5},
}


def _matching_results_json(run_no="1"):
    return {
        "table": [{
            "run": int(run_no),
            "far_recall_A": EXPECTED_DERIVED["far_recall"]["A"],
            "auc": dict(EXPECTED_DERIVED["auc"]),
            "rederivations": dict(EXPECTED_DERIVED["rederivations"]),
            "tokens_per_turn": dict(EXPECTED_DERIVED["tokens_per_turn"]),
        }]
    }


# ---------------------------------------------------------------------------
# synthetic adapter store
# ---------------------------------------------------------------------------


def _build_adapter_store(root, receipt_target, node_symbol, decision_text):
    store_dir = os.path.join(root, "store")
    os.makedirs(store_dir, exist_ok=True)

    conn = sqlite3.connect(os.path.join(store_dir, "index.sqlite"))
    conn.executescript("""
        CREATE TABLE receipts(id INTEGER PRIMARY KEY, ts REAL, session_id TEXT, agent TEXT,
          bridge_version TEXT, bridge_sha TEXT, tool TEXT, target TEXT, kind TEXT, outcome TEXT,
          detail TEXT, measure_kind TEXT, measure_value TEXT);
        CREATE TABLE nodes(key TEXT PRIMARY KEY, kind TEXT, first_rid INTEGER, last_rid INTEGER,
          degree INTEGER DEFAULT 0, last_outcome TEXT, last_detail TEXT, session_id TEXT, agent TEXT);
        CREATE TABLE edges(src TEXT, rel TEXT, dst TEXT, rid INTEGER);
        CREATE TABLE compactions(session_id TEXT, k INTEGER, ts REAL, rid_at INTEGER, snapshot TEXT,
          PRIMARY KEY(session_id, k));
        CREATE TABLE injections(id INTEGER PRIMARY KEY, ts REAL, session_id TEXT, event TEXT,
          compaction_k INTEGER, chars INTEGER, budget INTEGER, holdout INTEGER DEFAULT 0,
          bridge_version TEXT, bridge_sha TEXT, keys TEXT, rid_at INTEGER);
        CREATE TABLE decisions(id INTEGER PRIMARY KEY, ts REAL, session_id TEXT, agent TEXT, text TEXT,
          provenance TEXT);
        CREATE TABLE turns(session_id TEXT, n INTEGER, ts REAL, rid_at INTEGER, PRIMARY KEY(session_id, n));
        CREATE TABLE meta(k TEXT PRIMARY KEY, v TEXT);
    """)
    sid = "session-1"
    conn.execute(
        "INSERT INTO receipts(ts,session_id,agent,bridge_version,bridge_sha,tool,target,kind,outcome,detail,"
        "measure_kind,measure_value) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
        (1.0, sid, "main", "2.0", "sha1", "Edit", receipt_target, "file", "edit", node_symbol, None, None),
    )
    conn.execute(
        "INSERT INTO nodes(key,kind,first_rid,last_rid,degree,last_outcome,last_detail,session_id,agent) "
        "VALUES(?,?,?,?,?,?,?,?,?)",
        (node_symbol, "symbol", 1, 1, 1, "defined", receipt_target, sid, "main"),
    )
    conn.execute(
        "INSERT INTO decisions(ts,session_id,agent,text,provenance) VALUES(?,?,?,?,?)",
        (1.0, sid, "main", decision_text, "transcript.jsonl:12"),
    )
    conn.execute("INSERT INTO turns(session_id,n,ts,rid_at) VALUES(?,?,?,?)", (sid, 1, 1.0, 1))
    conn.commit()
    conn.close()

    lconn = sqlite3.connect(os.path.join(store_dir, "ledger.sqlite"))
    lconn.executescript("""
        CREATE TABLE sessions(session_id TEXT, agent_id TEXT, agent TEXT, model_id TEXT,
          bridge_version TEXT, bridge_sha TEXT, receipts INTEGER DEFAULT 0, compactions INTEGER DEFAULT 0,
          injections_n INTEGER DEFAULT 0, injections_chars INTEGER DEFAULT 0, holdouts INTEGER DEFAULT 0,
          lookups INTEGER DEFAULT 0, lookup_hits INTEGER DEFAULT 0, rederivations INTEGER DEFAULT 0,
          tokens_in INTEGER DEFAULT 0, tokens_out INTEGER DEFAULT 0, probes_n INTEGER DEFAULT 0,
          probes_exact INTEGER DEFAULT 0, probes_fuzzy INTEGER DEFAULT 0, probes_wrong INTEGER DEFAULT 0,
          handoff_path TEXT, cost_usd REAL DEFAULT 0.0, started REAL, ended REAL,
          PRIMARY KEY(session_id, agent_id));
        CREATE TABLE probes(session_id TEXT, turn INTEGER, cls TEXT, kind TEXT, lag_tokens INTEGER,
          compactions_crossed INTEGER, verdict TEXT, q_hash TEXT);
        CREATE TABLE rederivations(session_id TEXT, line INTEGER, path TEXT);
    """)
    lconn.execute(
        "INSERT INTO sessions(session_id, agent_id, agent, model_id, bridge_version, cost_usd) "
        "VALUES(?,?,?,?,?,?)",
        (sid, "", "main", "claude-sonnet-5", "2.0", 1.23),
    )
    lconn.execute(
        "INSERT INTO probes(session_id, turn, cls, kind, lag_tokens, compactions_crossed, verdict, q_hash) "
        "VALUES(?,?,?,?,?,?,?,?)",
        (sid, 1, "read", "signature", 500, 0, "exact", "abc123"),
    )
    lconn.commit()
    lconn.close()

    with open(os.path.join(store_dir, "hooks.log"), "w", encoding="utf-8") as f:
        f.write("1.0 receipt r1 Edit\n")

    return store_dir


# ---------------------------------------------------------------------------
# structural leak-scan rules (no forbidden set needed)
# ---------------------------------------------------------------------------


def test_code_fence_and_pathlike_string_always_flagged():
    problems = absorb._scan_value_for_leaks("here is a ```code block```", forbidden=set())
    assert any("code fence" in p for p in problems)

    problems = absorb._scan_value_for_leaks("see src/module.py for details", forbidden=set())
    assert any("path-shaped" in p for p in problems)

    assert absorb._scan_value_for_leaks("a perfectly ordinary value", forbidden=set()) == []


# ---------------------------------------------------------------------------
# the leak test: plant a path, a symbol and a decision text; absorb must refuse
# ---------------------------------------------------------------------------


def test_forbidden_set_captures_planted_path_symbol_and_decision(tmp_path):
    # Decision text is free-flowing prose (never truncated -- see
    # plateau.bridge.common.record_decision), so only its backtick-quoted identifying
    # substance is mined (the same shape-based rule judge.json's narrative gets; see
    # absorb._tokens_from_prose) -- the surrounding sentence is not itself identifying.
    store_dir = _build_adapter_store(
        str(tmp_path),
        receipt_target="app/billing/secret_widget.py",
        node_symbol="handleSuperSecretPayment",
        decision_text="Renamed the checkout flow to use `handleSuperSecretPayment` for good",
    )
    forbidden = absorb._forbidden_set_adapter(store_dir)

    assert any("secret_widget.py" in tok for tok in forbidden)
    assert "handleSuperSecretPayment" in forbidden

    # a value that echoes the planted path or symbol must be caught by the scanner
    leaking = {"detail": "touched app/billing/secret_widget.py again"}
    problems = absorb._scan_for_leaks(leaking, forbidden)
    assert problems, "planted path must be caught by the leak scan"

    leaking2 = {"note": "calls handleSuperSecretPayment internally"}
    assert absorb._scan_for_leaks(leaking2, forbidden), "planted symbol must be caught by the leak scan"


def test_absorb_adapter_refuses_when_a_planted_secret_leaks(tmp_path):
    store_dir = _build_adapter_store(
        str(tmp_path),
        receipt_target="app/billing/secret_widget.py",
        node_symbol="handleSuperSecretPayment",
        decision_text="Renamed the checkout flow to use handleSuperSecretPayment for good",
    )
    out_dir = str(tmp_path / "out")
    # the run_id is caller-supplied and, unlike every other field absorb writes, is not
    # itself derived from the raw -- stand in for "a bug wrote a raw string into some
    # primitive value" by making THIS field carry the planted path verbatim, and assert
    # absorb refuses to leave anything on disk. It is now caught even earlier than the
    # general primitive-value leak scan, by the dedicated `--run-id` naming rule
    # (`_check_run_id`, `ForbiddenRunId`) -- either way, nothing gets written.
    leaking_run_id = "run-with-app/billing/secret_widget.py-embedded"
    with pytest.raises((absorb.LeakDetected, absorb.ForbiddenRunId)):
        absorb.absorb_adapter(store_dir, leaking_run_id, out_dir)
    assert not os.path.isdir(out_dir), "a failed (leaking) absorb must not leave partial output behind"


# ---------------------------------------------------------------------------
# adapter absorb: happy path
# ---------------------------------------------------------------------------


def test_absorb_adapter_happy_path(tmp_path):
    store_dir = _build_adapter_store(
        str(tmp_path), receipt_target="ok/path.py", node_symbol="okSymbol", decision_text="an ok decision",
    )
    out_dir = str(tmp_path / "out")
    result = absorb.absorb_adapter(store_dir, "adapter-run-1", out_dir)

    run_doc = result["run_doc"]
    assert run_doc["source"] == "adapter"
    assert run_doc["run_id"] == "adapter-run-1"
    assert run_doc["sessions"] == 1
    assert len(run_doc["forbidden_digest"]) == 64

    assert os.path.isfile(os.path.join(out_dir, "run.json"))
    assert os.path.isfile(os.path.join(out_dir, "hashes.json"))
    assert os.path.isfile(os.path.join(out_dir, "nodes.jsonl"))

    nodes = [json.loads(l) for l in open(os.path.join(out_dir, "nodes.jsonl"))]
    assert nodes and all(set(n) == {"session", "kind", "count", "mean_degree"} for n in nodes)

    probes = [json.loads(l) for l in open(os.path.join(out_dir, "probes.jsonl"))]
    assert probes and probes[0]["verdict"] == "exact"
    # never the question/expected/answer text -- only lengths and a hash
    for p in probes:
        assert "q" not in p and "expected" not in p and "answer" not in p

    ok, problems = absorb.check_primitives(out_dir)
    assert ok, problems


# ---------------------------------------------------------------------------
# experiment absorb: recompute link
# ---------------------------------------------------------------------------


def test_absorb_experiment_derived_matches_expected_and_results_json(tmp_path):
    raw_dir = _build_experiment_raw(str(tmp_path))
    results_path = os.path.join(str(tmp_path), "results.json")
    _write_json(results_path, _matching_results_json())

    out_dir = str(tmp_path / "primitives" / "d038" / "d038-test-run")
    result = absorb.absorb_experiment(raw_dir, "d038-test-run", "d038", out_dir)

    derived = result["derived"]
    for key, expected_by_arm in EXPECTED_DERIVED.items():
        for arm, expected in expected_by_arm.items():
            got = derived[key][arm]
            assert got == pytest.approx(expected, abs=1e-9), (key, arm, got, expected)

    assert result["checked_against"] == results_path

    run_doc = result["run_doc"]
    assert run_doc["arms"] == {"tok_a": "A", "tok_c": "C"}
    assert run_doc["target"] == {"commit": "deadbeef", "tree": "cafef00d"}
    assert "subtree" not in json.dumps(run_doc)  # never the target's subtree name
    assert run_doc["settings"]["bridge_version"] == "d037-omega-999"

    probes = [json.loads(l) for l in open(os.path.join(out_dir, "probes.jsonl"))]
    for p in probes:
        assert "q" not in p and "expected" not in p and "answer" not in p

    judge = json.loads(open(os.path.join(out_dir, "judge.json")).read())
    assert "defects" not in judge["tok_a"]  # only defects_len, never the text itself
    assert judge["tok_a"]["defects_len"] == len("no defects of note")
    assert judge["tok_a"]["task_total"] == 3

    ok, problems = absorb.check_primitives(out_dir)
    assert ok, problems


def test_absorb_experiment_refuses_on_results_json_mismatch(tmp_path):
    raw_dir = _build_experiment_raw(str(tmp_path))
    bad_results = _matching_results_json()
    bad_results["table"][0]["far_recall_A"] = 0.9  # deliberately wrong
    _write_json(os.path.join(str(tmp_path), "results.json"), bad_results)

    out_dir = str(tmp_path / "primitives" / "d038" / "d038-bad-run")
    with pytest.raises(absorb.RecomputeMismatch):
        absorb.absorb_experiment(raw_dir, "d038-bad-run", "d038", out_dir)


def test_absorb_check_detects_tampered_hashes(tmp_path):
    store_dir = _build_adapter_store(
        str(tmp_path), receipt_target="ok/path.py", node_symbol="okSymbol", decision_text="an ok decision",
    )
    out_dir = str(tmp_path / "out")
    absorb.absorb_adapter(store_dir, "adapter-run-2", out_dir)

    hashes_path = os.path.join(out_dir, "hashes.json")
    doc = json.loads(open(hashes_path).read())
    doc["manifest_sha256"] = "0" * 64
    with open(hashes_path, "w", encoding="utf-8") as f:
        json.dump(doc, f)

    ok, problems = absorb.check_primitives(out_dir)
    assert not ok
    assert any("manifest_sha256" in p for p in problems)


# ---------------------------------------------------------------------------
# plateau fit --from-primitives
# ---------------------------------------------------------------------------


def test_fit_from_primitives_reads_absorbed_experiment(tmp_path):
    raw_dir = _build_experiment_raw(str(tmp_path))
    _write_json(os.path.join(str(tmp_path), "results.json"), _matching_results_json())
    out_dir = str(tmp_path / "primitives" / "d038" / "d038-fit-run")
    absorb.absorb_experiment(raw_dir, "d038-fit-run", "d038", out_dir)

    cells, notes = fit_mod.from_primitives(str(tmp_path / "primitives"), "2026-09-17")
    pairs = {(c["model_id"], c["bridge_version"]) for c in cells}
    assert ("m1", "none") in pairs
    assert ("m1", "d037-omega-999") in pairs
    for c in cells:
        assert c["sessions"] == 1
        assert c["last_updated"] == "2026-09-17"
        assert "d038-fit-run" in c["run_id"]

    none_cell = next(c for c in cells if c["bridge_version"] == "none")
    assert none_cell["alpha"] == pytest.approx(1.0)
    assert "lambda_by_lag" in none_cell

    bridge_cell = next(c for c in cells if c["bridge_version"] != "none")
    assert bridge_cell["alpha"] == pytest.approx(1.0)


def test_fit_from_primitives_skips_adapter_run_below_min_sessions(tmp_path):
    store_dir = _build_adapter_store(
        str(tmp_path), receipt_target="ok/path.py", node_symbol="okSymbol", decision_text="an ok decision",
    )
    out_dir = str(tmp_path / "primitives" / "adapter" / "small-run")
    absorb.absorb_adapter(store_dir, "small-run", out_dir)

    cells, notes = fit_mod.from_primitives(str(tmp_path / "primitives"), "2026-09-17")
    assert cells == []
    assert any("need >=" in n for n in notes)


def test_compare_cells_tolerance():
    existing = {"model_id": "m", "bridge_version": "none", "run_id": "D-038 run 1", "alpha": 0.909,
                "lambda_by_lag": {"l0": 0.0, "l1": 0.31}}
    close = {"model_id": "m", "bridge_version": "none", "run_id": "plateau fit x", "alpha": 0.905,
             "lambda_by_lag": {"l0": 0.0, "l1": 0.315}}
    far = {"model_id": "m", "bridge_version": "none", "run_id": "plateau fit x", "alpha": 0.5,
           "lambda_by_lag": {"l0": 0.0, "l1": 0.31}}
    ok, diffs = fit_mod.compare_cells(existing, close, tol=0.01)
    assert ok, diffs
    ok, diffs = fit_mod.compare_cells(existing, far, tol=0.01)
    assert not ok
    assert diffs


# ---------------------------------------------------------------------------
# CLI wiring
# ---------------------------------------------------------------------------


def test_cli_absorb_check_dispatch(tmp_path):
    store_dir = _build_adapter_store(
        str(tmp_path), receipt_target="ok/path.py", node_symbol="okSymbol", decision_text="an ok decision",
    )
    out_dir = str(tmp_path / "out")
    absorb.absorb_adapter(store_dir, "cli-run", out_dir)
    assert cli_mod.main(["absorb", "--check", out_dir]) == 0


def test_cli_absorb_check_fails_on_missing_dir(tmp_path):
    assert cli_mod.main(["absorb", "--check", str(tmp_path / "does-not-exist")]) == 1


# ---------------------------------------------------------------------------
# --run-id naming rule (PLAN-absorb.md "Leak rule"): a run id must not carry the
# target's own name, either via the raw/store's own forbidden set or via the target
# repo's git remote name/URL.
# ---------------------------------------------------------------------------


def test_run_id_rejected_when_it_matches_the_forbidden_set(tmp_path):
    store_dir = _build_adapter_store(
        str(tmp_path),
        receipt_target="app/billing/secretwidget.py",
        node_symbol="handleSuperSecretPayment",
        decision_text="an ok decision",
    )
    out_dir = str(tmp_path / "out")
    with pytest.raises(absorb.ForbiddenRunId):
        absorb.absorb_adapter(store_dir, "run-handleSuperSecretPayment-1", out_dir)
    assert not os.path.isdir(out_dir)

    # CLI surface: exit 2, not the leak-detected exit 1, and no output written.
    rc = cli_mod.main([
        "absorb", "--store", store_dir, "--run-id", "run-handleSuperSecretPayment-2",
        "--out", out_dir,
    ])
    assert rc == 2
    assert not os.path.isdir(out_dir)


def test_run_id_rejected_when_it_names_the_target_git_remote(tmp_path):
    root = str(tmp_path / "target-repo")
    os.makedirs(root, exist_ok=True)
    subprocess.run(["git", "init", "-q", root], check=True, timeout=10)
    subprocess.run(
        ["git", "-C", root, "remote", "add", "origin", "https://github.com/Wavex-Labs/wavex-experience-architect"],
        check=True, timeout=10,
    )
    store_dir = _build_adapter_store(
        root, receipt_target="ok/path.py", node_symbol="okSymbol", decision_text="an ok decision",
    )
    out_dir = str(tmp_path / "out")

    with pytest.raises(absorb.ForbiddenRunId):
        absorb.absorb_adapter(store_dir, "wavex-adapter-2026-09-17", out_dir)
    assert not os.path.isdir(out_dir)

    # a run id that does not echo the target's name (and isn't in the forbidden set)
    # absorbs cleanly.
    result = absorb.absorb_adapter(store_dir, "adapter-2026-09-17-a", out_dir)
    assert result["run_doc"]["run_id"] == "adapter-2026-09-17-a"


# ---------------------------------------------------------------------------
# Issue 1/2: index-consistent presence -- pi_by_comp must compare a bridge arm's
# recall at compaction bucket n against the NATIVE arm's own recall at that SAME
# compaction bucket (never a lag-bucket lambda), and the unclamped `pi_raw_by_comp`
# must surface a negative presence (eviction) rather than hide it.
# ---------------------------------------------------------------------------


def test_from_primitives_d038_presence_is_index_consistent_and_reports_negative_raw():
    # exercises the real, checked-in D-038 run-1 primitives (primitives/d038/d038-run1)
    # against the worked numbers in the task/PLAN: alpha_comp=0.933, R_A c1=0.462,
    # R_C c1=0.917 -> lambda_c1=0.505, pi_c1=0.966; c2: R_A=0.333, R_C=0.059 ->
    # lambda_c2=0.643, pi_c2=-0.457 (clamped to 0.0).
    cells, notes = fit_mod.from_primitives(os.path.join(_REPO_ROOT, "primitives"), "2026-09-17")
    bridge_cell = next(
        c for c in cells
        if c["model_id"] == "claude-sonnet-5"
        and c["bridge_version"] == "d037-omega-6000"
        and c.get("source", "").endswith("d038/d038-run1")
    )

    assert bridge_cell["pi_by_comp"]["c1"] == pytest.approx(0.9647, abs=1e-3)
    assert bridge_cell["pi_raw_by_comp"]["c1"] == pytest.approx(0.9647, abs=1e-3)

    assert bridge_cell["pi_raw_by_comp"]["c2"] < 0
    assert bridge_cell["pi_raw_by_comp"]["c2"] == pytest.approx(-0.4575, abs=1e-3)
    assert bridge_cell["pi_by_comp"]["c2"] == 0.0


def test_presence_raw_negative_means_eviction():
    from plateau.lab import model

    # alpha=0.9333..., lambda=0.6428... (native c2), r_bridge=0.0588... (bridge c2) --
    # the D-038 c2 numbers verbatim.
    alpha_comp = 0.9333333333333333
    lam_c2 = model.loss(alpha_comp, 0.3333333333333333)
    raw = model.presence_raw(alpha_comp, lam_c2, 0.058823529411764705)
    clamped = model.presence(alpha_comp, lam_c2, 0.058823529411764705)
    assert raw < 0
    assert raw == pytest.approx(-0.4575, abs=1e-3)
    assert clamped == 0.0
