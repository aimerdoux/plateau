"""Driver (the real, context-owning adapter) — free mock plumbing pins the bound + gate.
No paid spend: deterministic mock worker. The live `claude_p` backend is operator-gated."""

from plateau.driver import run_mock_plumbing, gate_reply
from plateau.signal import RelationalState
from plateau.integrity import file_hash


def test_mock_plumbing_bounds_context_and_wins():
    r = run_mock_plumbing()
    assert r["context_flattened_<=25pct_control"] is True
    assert r["completion_parity"] is True
    assert r["anti_rig_control_climbs"] is True
    assert r["verdict_on_mock"].startswith("WIN")
    # the bounded signal arm grows far slower than the full-history control
    assert r["control_slope"] > 50 * r["signal_slope"]
    # signal arm's per-step context stays small; control explodes
    assert max(r["signal_context_per_step"]) < min(r["control_context_per_step"][2:])


def test_gate_admits_real_drops_bogus(tmp_path):
    (tmp_path / "a.py").write_text("# a\n")
    reply = (f"CARRY: did a\n"
             f"GATE: a.py :: {file_hash(str(tmp_path / 'a.py'))}\n"
             f"GATE: b.py :: sha256:{'0' * 64}")
    _, rep = gate_reply(RelationalState(), reply, str(tmp_path))
    assert rep["admitted"] == ["a.py present"]          # real file, hash re-verifies
    assert rep["dropped_ungrounded"] == ["b.py present"]  # fabricated hash → dropped
