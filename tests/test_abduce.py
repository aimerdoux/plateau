"""The graph loop's deterministic pieces (no LLM): parse -> triage -> inject.

The paid ABDUCE dispatch is exercised separately (mock CLI). Here: a discriminator that
already passes must be REJECTED (measures nothing), duplicates dropped, the wallet capped,
and survivors injected as ordinary gated rows the ratchet can run.
"""
import os

from plateau.agency import abduce as AB
from plateau.agency import control as C


REPLY = """Here is my reasoning, which should be ignored.
H1 | explains: Anomaly:abc | cause: add() saturates at 5 so double(3) is 5 not 6 | DISCRIMINATOR-GATE: python -c "from calc import double; assert double(3)==6" | EXPECT: exit0
garbage line with no grammar
H2 | explains: Anomaly:abc | cause: unrelated | DISCRIMINATOR-GATE: false | EXPECT: exit0
"""


def test_parse_only_well_formed_hypotheses():
    hs = AB.parse_hypotheses(REPLY)
    assert [h["id"] for h in hs] == ["H1", "H2"]
    assert hs[0]["gate"].startswith("python -c")
    assert hs[0]["hkey"] != hs[1]["hkey"]


def test_triage_rejects_a_discriminator_that_already_passes(tmp_path):
    """must-fail-now: a gate green on the current tree distinguishes nothing."""
    cd = tmp_path / "c"; (cd / "gates").mkdir(parents=True)
    hs = [{"id": "H1", "explains": "A", "cause": "x", "gate": "true", "expect": "exit0",
           "hkey": "k1"},                                   # passes now -> reject
          {"id": "H2", "explains": "A", "cause": "y", "gate": "false", "expect": "exit0",
           "hkey": "k2"}]                                   # fails now -> survives
    res = AB.triage(str(cd), str(tmp_path), hs, wallet=5, seen=set())
    assert [h["id"] for h in res["survivors"]] == ["H2"]
    assert any("measures nothing" in r["reason"] for r in res["rejected"])


def test_triage_dedups_and_respects_wallet(tmp_path):
    cd = tmp_path / "c"; (cd / "gates").mkdir(parents=True)
    seen = {"dupe"}
    hs = [{"id": "H1", "cause": "a", "gate": "false", "expect": "exit0", "explains": "A",
           "hkey": "dupe"},                                 # duplicate -> reject
          {"id": "H2", "cause": "b", "gate": "false", "expect": "exit0", "explains": "A",
           "hkey": "k2"},
          {"id": "H3", "cause": "c", "gate": "false", "expect": "exit0", "explains": "A",
           "hkey": "k3"}]
    res = AB.triage(str(cd), str(tmp_path), hs, wallet=1, seen=seen)   # wallet=1
    assert [h["id"] for h in res["survivors"]] == ["H2"]              # only one admitted
    reasons = " ".join(r["reason"] for r in res["rejected"])
    assert "duplicate" in reasons and "wallet" in reasons


def test_inject_writes_gated_rows_with_provenance_tag(tmp_path):
    cd = tmp_path / "c"; cd.mkdir()
    (cd / "PLAN.md").write_text("# PLAN\n")
    (cd / "FORECAST.md").write_text("")
    survivors = [{"id": "H2", "explains": "Anomaly:abc", "cause": "add saturates",
                  "gate": "python -c \"assert 1\"", "expect": "exit0", "hkey": "k2"}]
    ids = AB.inject(str(cd), survivors)
    assert ids == ["H2"]
    plan = (cd / "PLAN.md").read_text()
    tasks = C.parse_plan(plan)
    assert len(tasks) == 1 and tasks[0].id == "H2"
    assert "origin:H2" in plan                              # provenance survives into the row
    assert "H2 |" in (cd / "FORECAST.md").read_text()
