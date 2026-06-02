"""emit → inflate → ground round-trip: structure carries; facts re-ground; raw thought
never crosses; reality-contradicted facts are flagged STALE."""

from __future__ import annotations

from plateau import (
    Measurement, Thought, RelationalState, SelfState,
    emit, inflate, ground, apply_gate, set_ground_root,
)
from plateau.integrity import file_hash


def test_emit_drops_raw_thought():
    sig = RelationalState(open_goals=["g"], stance="s", lessons=["l"])
    ss = SelfState(signal=sig, thoughts=[Thought("secret raw thought", None)])
    blob = emit(ss)
    assert "secret raw thought" not in blob
    assert "g" in blob and "l" in blob


def test_structure_round_trips(tmp_path):
    sig = RelationalState(open_goals=["a", "b"], stance="careful",
                          lessons=["x"], pointers=["seal://1"])
    blob = emit(SelfState(signal=sig))
    inf = inflate(blob, fresh=True)
    assert inf.state.open_goals == ["a", "b"]
    assert inf.state.stance == "careful"
    assert inf.state.lessons == ["x"]
    assert inf.state.pointers == ["seal://1"]


def test_fact_reverifies_and_carries(tmp_path):
    p = tmp_path / "f.txt"; p.write_text("42")
    set_ground_root(str(tmp_path))
    m = Measurement("file_hash", "f.txt", file_hash(str(p)))
    sig = apply_gate(SelfState(RelationalState(), [Thought("v=42", m)]))
    blob = emit(SelfState(signal=sig))
    inf = inflate(blob, fresh=True)
    assert not inf.stale
    assert any(vf["claim"] == "v=42" for vf in inf.state.verified_facts)


def test_changed_reality_flags_stale(tmp_path):
    p = tmp_path / "f.txt"; p.write_text("42")
    set_ground_root(str(tmp_path))
    m = Measurement("file_hash", "f.txt", file_hash(str(p)))
    sig = apply_gate(SelfState(RelationalState(), [Thought("v=42", m)]))
    blob = emit(SelfState(signal=sig))
    p.write_text("43")  # reality moved
    inf = inflate(blob, fresh=True)
    assert inf.stale_claims() == ["v=42"]
    assert all(vf["claim"] != "v=42" for vf in inf.state.verified_facts)


def test_ground_standalone_splits_live_stale(tmp_path):
    p = tmp_path / "f.txt"; p.write_text("1")
    set_ground_root(str(tmp_path))
    m = Measurement("file_hash", "f.txt", file_hash(str(p)))
    sig = apply_gate(SelfState(RelationalState(), [Thought("k=1", m)]))
    g = ground(sig)
    assert len(g.live) == 1 and not g.stale
    p.write_text("2")
    g2 = ground(sig)
    assert not g2.live and g2.stale_claims() == ["k=1"]
