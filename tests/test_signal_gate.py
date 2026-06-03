"""The gate is the sacred boundary — these tests pin it. A claim enters the signal
ONLY if its grounding re-verifies against reality now."""

from __future__ import annotations

import json
import os

from plateau import (
    Measurement, Thought, RelationalState, SelfState, gate, apply_gate, set_ground_root,
)
from plateau.integrity import file_hash


def _grounded_thought(tmp_path, claim="x=1"):
    p = tmp_path / "fact.txt"
    p.write_text("1")
    set_ground_root(str(tmp_path))
    m = Measurement(kind="file_hash", source="fact.txt", value=file_hash(str(p)))
    return Thought(claim=claim, grounding=m), p


def test_ungrounded_thought_is_dropped():
    res = gate([Thought(claim="probably true", grounding=None)])
    assert res.admitted == []
    assert len(res.dropped) == 1
    assert "ungrounded" in res.dropped[0]["reason"]


def test_grounded_thought_is_admitted(tmp_path):
    th, _ = _grounded_thought(tmp_path)
    res = gate([th])
    assert len(res.admitted) == 1
    assert res.admitted[0]["claim"] == "x=1"
    assert res.dropped == []


def test_stale_grounding_is_dropped(tmp_path):
    th, p = _grounded_thought(tmp_path)
    p.write_text("2")  # reality changed → recorded hash no longer matches
    res = gate([th])
    assert res.admitted == []
    assert "did not re-verify" in res.dropped[0]["reason"]


def test_operator_kind_fails_closed():
    # operator-feel is real but not filesystem-checkable → must NOT pass the gate
    m = Measurement(kind="operator", source="i feel continuous", value="yes")
    res = gate([Thought(claim="i am continuous", grounding=m)])
    assert res.admitted == []


def test_unimplemented_kind_fails_closed():
    m = Measurement(kind="oracle_score", source="?", value="0.9")
    assert m.reverify() is False


def test_apply_gate_folds_only_admitted(tmp_path):
    th, _ = _grounded_thought(tmp_path, claim="total=5")
    sig = RelationalState(open_goals=["g"], stance="s")
    ss = SelfState(signal=sig, thoughts=[th, Thought("noise", None)])
    new = apply_gate(ss)
    assert new.open_goals == ["g"] and new.stance == "s"
    assert len(new.verified_facts) == 1
    assert new.verified_facts[0]["claim"] == "total=5"


def test_missing_source_file_fails_closed(tmp_path):
    set_ground_root(str(tmp_path))
    m = Measurement(kind="file_hash", source="nope.txt", value="sha256:deadbeef")
    assert m.reverify() is False


def test_empty_or_directory_source_fails_closed(tmp_path):
    # an empty source resolves to the ground-root DIRECTORY — must fail closed, not crash
    set_ground_root(str(tmp_path))
    assert Measurement("file_hash", "", "x").reverify() is False
    assert Measurement("file_hash", ".", "x").reverify() is False
    res = gate([Thought("ungrounded-empty-source",
                        Measurement("file_hash", "", ""))])
    assert res.admitted == []


# ── integrity-bound success kinds: test_result / exit_code ───────────────────────
# A result artifact earns a seat only if its bytes are UNCHANGED since the claim
# (hash binding) AND it records a success. No command is ever executed by the gate.

def _result_measurement(tmp_path, kind, *, normalized_pass=True, exit_code=0, name="result.json"):
    """Write a deterministic result.json and return a Measurement bound to its hash."""
    p = tmp_path / name
    p.write_text(json.dumps({"repo": "demo", "cmd": "pytest",
                             "exit_code": exit_code, "normalized_pass": normalized_pass}))
    set_ground_root(str(tmp_path))
    return Measurement(kind=kind, source=name, value=file_hash(str(p))), p


def test_test_result_pass_is_admitted(tmp_path):
    m, _ = _result_measurement(tmp_path, "test_result", normalized_pass=True)
    assert m.reverify() is True
    res = gate([Thought("milestone tests pass", m)])
    assert len(res.admitted) == 1 and res.dropped == []


def test_test_result_fail_is_dropped(tmp_path):
    m, _ = _result_measurement(tmp_path, "test_result", normalized_pass=False)
    assert m.reverify() is False


def test_exit_code_zero_is_admitted(tmp_path):
    m, _ = _result_measurement(tmp_path, "exit_code", exit_code=0)
    assert m.reverify() is True


def test_exit_code_nonzero_is_dropped(tmp_path):
    m, _ = _result_measurement(tmp_path, "exit_code", exit_code=1)
    assert m.reverify() is False


def test_result_kind_tampered_artifact_is_dropped(tmp_path):
    # integrity first: editing the result file after the claim breaks the hash → drop,
    # even when the edit keeps the verdict "pass". The gate certifies UNCHANGED bytes.
    m, p = _result_measurement(tmp_path, "test_result", normalized_pass=True)
    p.write_text(json.dumps({"exit_code": 0, "normalized_pass": True, "tampered": 1}))
    assert m.reverify() is False


def test_result_kind_missing_file_fails_closed(tmp_path):
    set_ground_root(str(tmp_path))
    assert Measurement("test_result", "nope.json", "sha256:" + "0" * 64).reverify() is False
    assert Measurement("exit_code", "nope.json", "sha256:" + "0" * 64).reverify() is False


def test_result_kind_malformed_json_fails_closed(tmp_path):
    # hash matches the bytes, but the body isn't JSON → semantic check fails closed (no crash).
    p = tmp_path / "bad.json"
    p.write_text("not json {")
    set_ground_root(str(tmp_path))
    m = Measurement("test_result", "bad.json", file_hash(str(p)))
    assert m.reverify() is False
