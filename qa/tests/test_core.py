"""state caps/triage/dedupe + gate denylist/classify/command."""
import json

from plateau_qa import state, gate


def test_enforce_caps_lessons():
    sig = state.new_signal("r", 0.0)
    sig["lessons"] = ["x" * 200] + ["lesson %d" % i for i in range(20)]
    state.enforce_caps(sig)
    assert len(sig["lessons"]) <= state.LESSON_MAX
    assert all(len(l) <= state.LESSON_CHARS for l in sig["lessons"])


def test_next_pending_ascending_tier():
    cov = [{"id": "a", "tier": 3, "status": "pending"},
           {"id": "b", "tier": 1, "status": "pending"},
           {"id": "c", "tier": 1, "status": "covered"},
           {"id": "d", "tier": 2, "status": "pending"}]
    assert state.next_pending(cov)["id"] == "b"      # tier-1 pending wins
    cov[1]["status"] = "covered"
    assert state.next_pending(cov)["id"] == "d"      # then tier-2 before tier-3


def test_pattern_seen(tmp_path):
    led = tmp_path / "ledger.jsonl"
    led.write_text(json.dumps({"pattern_key": "pk1", "outcome": "found"}) + "\n")
    assert state.pattern_seen(str(led), "pk1") is True
    assert state.pattern_seen(str(led), "pk2") is False
    assert state.pattern_seen(str(led), None) is False


def test_sha256_file(tmp_path):
    p = tmp_path / "f.txt"
    p.write_text("hi")
    h = state.sha256_file(p)
    assert h and h.startswith("sha256:")
    assert state.sha256_file(tmp_path / "nope") is None


def test_scan_diff_policy_added_lines_only():
    diff = "\n".join(["+++ b/x.sql",
                      "+CREATE POLICY p ON t USING (true);",  # added -> HIT
                      "-DROP POLICY old;",                    # removed -> ignored
                      " ctx USING (true)"])                   # context -> ignored
    hits = gate.scan_diff_policy(diff)
    assert len(hits) == 1 and "true" in hits[0]["line"]


def test_scan_diff_policy_extra():
    diff = "+const x = BANNED_TOKEN"
    assert gate.scan_diff_policy(diff) == []
    assert len(gate.scan_diff_policy(diff, extra=[r"BANNED_TOKEN"])) == 1


def test_scan_diff_policy_dangerous_verbs():
    diff = "+  gh pr merge --auto\n+service_role key"
    pats = {h["pattern"] for h in gate.scan_diff_policy(diff)}
    assert any("merge" in p for p in pats) and any("service_role" in p for p in pats)


def test_classify_is_logic():
    assert gate._is_logic("const x = 1") is True
    assert gate._is_logic("// comment") is False
    assert gate._is_logic("   ") is False
    assert gate._is_logic("import x from 'y'") is False


def test_gate_command_from_cfg():
    cfg = {"gate_commands": {"unit": ["npx", "jest"]}}
    assert gate.gate_command("unit", cfg) == ["npx", "jest"]
    assert gate.gate_command("policy", cfg) == ("rls", None)
    assert gate.gate_command("missing", cfg) is None
