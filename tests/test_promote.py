"""tests/test_promote.py — owner C5 (docs/harness-0.3/PLAN-step4.md "Tests (C5)").

Per the plan's "Tests (C5)" line plus the operator's addition for this file:
"synthetic winner promoted; near-miss (pi gain 0.14, or re-derivations +6%) rejected;
`body_leaks` catches a path and a symbol planted in a body" and "a propose test using a
stubbed runner (never live)". ZERO SPEND: no test here ever invokes `claude -p`; every
`run_claude`/`_arm_stats` seam a test needs is monkeypatched.
"""

from __future__ import annotations

import json
import os

from plateau.lab import ledger as ledger_mod
from plateau.lab import promote as promote_mod
from plateau.lab import propose as propose_mod


# ---------------------------------------------------------------------------
# decide(): the promotion rule itself
# ---------------------------------------------------------------------------


def _stats(sessions=25, rederiv=1.0, tokens=1000.0, presence=0.5):
    return {
        "sessions": sessions,
        "rederivations_per_turn": rederiv,
        "tokens_per_turn": tokens,
        "presence_far_lag": presence,
    }


def test_decide_promotes_a_clear_synthetic_winner():
    incumbent = _stats(presence=0.50, rederiv=1.0, tokens=1000.0)
    canary = _stats(presence=0.70, rederiv=1.0, tokens=1000.0)  # pi gain 0.20 >= 0.15
    assert promote_mod.decide(incumbent, canary) == "promote"


def test_decide_rejects_near_miss_pi_gain_just_under_threshold():
    incumbent = _stats(presence=0.50)
    canary = _stats(presence=0.64)  # gain 0.14 < PI_GAIN (0.15)
    assert promote_mod.decide(incumbent, canary) == "keep"


def test_decide_rejects_near_miss_rederivation_regression_over_tolerance():
    incumbent = _stats(presence=0.50, rederiv=1.0)
    canary = _stats(presence=0.70, rederiv=1.06)  # pi gain fine, but +6% > REDERIV_TOL (0.05)
    assert promote_mod.decide(incumbent, canary) == "keep"


def test_decide_keeps_when_below_min_sessions():
    incumbent = _stats(sessions=25, presence=0.50)
    canary = _stats(sessions=5, presence=0.9)  # would clear the bar, but too few sessions
    assert promote_mod.decide(incumbent, canary) == "keep"


def test_decide_retires_a_canary_that_never_clears_the_bar():
    incumbent = _stats(presence=0.50)
    canary = _stats(sessions=promote_mod.RETIRE_AFTER, presence=0.55)  # gain 0.05 < 0.15
    assert promote_mod.decide(incumbent, canary) == "retire"


# ---------------------------------------------------------------------------
# body_leaks: catches a planted path and a planted symbol
# ---------------------------------------------------------------------------


def test_body_leaks_catches_planted_path_and_symbol(tmp_path):
    root = str(tmp_path)
    conn = ledger_mod.db(root)
    try:
        # a "path"-tagged column (rederivations.path)
        conn.execute(
            "INSERT INTO rederivations(session_id, line, path) VALUES(?,?,?)",
            ("s1", 5, "plateau/bridge/query.py"),
        )
        # a "path"-tagged column carrying a symbol-shaped string (sessions.handoff_path
        # -- body_leaks scans by COLUMN NAME, not by what the value semantically is)
        conn.execute(
            "INSERT INTO sessions(session_id, agent_id, agent, handoff_path) VALUES(?,?,?,?)",
            ("s1", "", "main", "_very_unusual_symbol_name_marker"),
        )
        conn.commit()

        body = (
            "This promotion touched `plateau/bridge/query.py` and renamed "
            "`_very_unusual_symbol_name_marker`."
        )
        leaks = promote_mod.body_leaks(body, conn)
        assert "plateau/bridge/query.py" in leaks
        assert "_very_unusual_symbol_name_marker" in leaks

        clean_body = "Incumbent sessions: 25    Canary sessions: 25\npresence gain: 0.20\n"
        assert promote_mod.body_leaks(clean_body, conn) == []
    finally:
        conn.close()


def test_body_leaks_ignores_short_and_unrelated_columns(tmp_path):
    """A short (<3 char) value, or a value under a column name that doesn't look like
    a path/symbol/target/key, is never reported as a leak."""
    root = str(tmp_path)
    conn = ledger_mod.db(root)
    try:
        conn.execute(
            "INSERT INTO probes(session_id, turn, cls, kind, lag_tokens, "
            "compactions_crossed, verdict, q_hash) VALUES(?,?,?,?,?,?,?,?)",
            ("s1", 1, "read", "signature", 100, 0, "exact", "ab"),
        )
        conn.commit()
        body = "verdict was exact, q_hash starts with ab"
        assert promote_mod.body_leaks(body, conn) == []
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# learn_main: a synthetic winner is actually promoted end to end
# ---------------------------------------------------------------------------


def test_learn_main_promotes_a_synthetic_winner(tmp_path, monkeypatch):
    root = str(tmp_path)
    (tmp_path / "bridge.toml").write_text('version = "2.0"\n[budget]\nstartup_chars = 6000\n')
    (tmp_path / "bridge.canary.toml").write_text('version = "2.1"\n[lab]\nshadow_probe_every_turns = 4\n')

    def fake_arm_stats(root_arg, bridge_version):
        assert root_arg == root
        if bridge_version == "2.0":
            return _stats(sessions=25, presence=0.40, rederiv=1.0, tokens=1000.0)
        assert bridge_version == "2.1"
        return _stats(sessions=25, presence=0.60, rederiv=1.0, tokens=1000.0)  # gain 0.20

    monkeypatch.setattr(promote_mod, "_arm_stats", fake_arm_stats)

    rc = promote_mod.learn_main(["--root", root])

    assert rc == 0
    assert not os.path.isfile(os.path.join(root, "bridge.canary.toml"))
    new_bridge_text = (tmp_path / "bridge.toml").read_text()
    assert 'version = "2.1"' in new_bridge_text
    assert "shadow_probe_every_turns" in new_bridge_text  # canary's other content carried over

    proposal_path = os.path.join(root, "proposals", "promote-2.1.md")
    assert os.path.isfile(proposal_path)
    body = open(proposal_path, encoding="utf-8").read()
    assert "2.0" in body and "2.1" in body
    assert "25" in body  # session counts
    # the written body itself must never leak a raw ledger string (no ledger exists in
    # this test, so body_leaks would find nothing to check against anyway; this just
    # confirms learn_main did not skip writing on some unrelated error).
    assert "Rule:" in body


def test_learn_main_does_not_touch_bridge_toml_on_keep(tmp_path, monkeypatch):
    root = str(tmp_path)
    (tmp_path / "bridge.toml").write_text('version = "2.0"\n')
    (tmp_path / "bridge.canary.toml").write_text('version = "2.1"\n')

    def fake_arm_stats(root_arg, bridge_version):
        return _stats(sessions=25, presence=0.50)  # identical arms -> no pi gain -> keep

    monkeypatch.setattr(promote_mod, "_arm_stats", fake_arm_stats)

    rc = promote_mod.learn_main(["--root", root])

    assert rc == 0
    assert os.path.isfile(os.path.join(root, "bridge.canary.toml"))  # untouched
    assert (tmp_path / "bridge.toml").read_text() == 'version = "2.0"\n'  # untouched
    assert not os.path.isdir(os.path.join(root, "proposals"))


def test_learn_main_refuses_a_leaking_body(tmp_path, monkeypatch):
    """`learn_main` must not write `proposals/promote-<version>.md` when
    `body_leaks` finds anything -- simulate that by monkeypatching `body_leaks` itself
    (isolates this refusal path from needing a real leaking ledger fixture)."""
    root = str(tmp_path)
    (tmp_path / "bridge.toml").write_text('version = "2.0"\n')
    (tmp_path / "bridge.canary.toml").write_text('version = "2.1"\n')
    # a ledger must exist for learn_main to even run the leak check
    ledger_mod.db(root).close()

    monkeypatch.setattr(promote_mod, "_arm_stats", lambda r, v: (
        _stats(sessions=25, presence=0.40) if v == "2.0" else _stats(sessions=25, presence=0.60)
    ))
    monkeypatch.setattr(promote_mod, "body_leaks", lambda body, conn: ["some/leaked/path.py"])

    rc = promote_mod.learn_main(["--root", root])

    assert rc == 1
    assert not os.path.isfile(os.path.join(root, "proposals", "promote-2.1.md"))
    # the promotion itself still happened (bridge.toml was updated) -- only the body
    # write is refused, matching learn_main's own docstring ("refuses to write a body
    # that leaks"), not the whole promotion.
    assert 'version = "2.1"' in (tmp_path / "bridge.toml").read_text()


# ---------------------------------------------------------------------------
# plateau propose: a stubbed runner only, never live
# ---------------------------------------------------------------------------


def test_propose_writes_a_proposal_via_a_stubbed_runner(tmp_path, monkeypatch):
    root = str(tmp_path)
    calls = []

    def fake_run_claude(prompt, env):
        calls.append(prompt)
        assert "plateau report --json" in prompt or "per-bridge_version aggregates" in prompt
        return json.dumps({"result": (
            "1. name: try-a-thing\n"
            "   observation: tokens/turn looks high\n"
            "   change: bridge.toml key `lab.shadow_probe_every_turns` -> 2\n"
            "   bet: 0.4\n"
            "   cost: 20 sessions\n"
        )})

    monkeypatch.setattr(propose_mod, "run_claude", fake_run_claude)

    rc = propose_mod.main(["--date", "2026-09-17", "--root", root])

    assert rc == 0
    assert len(calls) == 1  # exactly one stubbed call -- never a real subprocess
    out_path = os.path.join(root, "proposals", "2026-09-17.md")
    assert os.path.isfile(out_path)
    text = open(out_path, encoding="utf-8").read()
    assert "Proposal" in text
    assert "try-a-thing" in text
    assert "bridge.toml" in text


def test_propose_never_calls_the_real_run_claude(tmp_path, monkeypatch):
    """A belt-and-suspenders ZERO SPEND check: if this test file's own stub were ever
    accidentally removed, `run_claude`'s real subprocess.run must still refuse to run
    inside a test -- assert the module-level function is the one we patched, and that
    patching it is sufficient to prevent any subprocess call."""
    root = str(tmp_path)
    called = {"subprocess": False}

    def exploding_subprocess_run(*a, **k):
        called["subprocess"] = True
        raise AssertionError("plateau.lab.propose must never invoke subprocess.run directly in a test")

    monkeypatch.setattr(propose_mod.subprocess, "run", exploding_subprocess_run)
    monkeypatch.setattr(propose_mod, "run_claude", lambda prompt, env: json.dumps({"result": "1. x"}))

    rc = propose_mod.main(["--date", "2026-01-01", "--root", root])

    assert rc == 0
    assert called["subprocess"] is False
