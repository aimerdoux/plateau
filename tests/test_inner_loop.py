"""The INNER loop, tested end to end with real subprocesses and no LLM.

One inner-loop "turn" chains four independently-owned pieces that all run inside a single
Claude Code session:

  hook.py pre         — UserPromptSubmit: inflate + ground the carried signal.
  scripted gate turn  — VERIFY (V1): the parent-authored GATE is executed by
                        `plateau.agency.control.run_gate` (via `python -m
                        plateau.agency.control verify --strict`), which records the ground
                        truth to `gates/<id>.gate.json`.
  gatekeeper.sh Stop  — I4 enforcement: block stopping while PLAN.md is not truly done.
  hook.py post        — VERIFY (V2): fold a proposed fact into signal.json, but ONLY if its
                        Measurement (an `exit_code` binding to the gate artifact) re-verifies.

Nothing here trusts another piece's word: hook.py post never runs a gate, gatekeeper.sh
never reads signal.json, and neither ever executes an untrusted claim. Mirroring the
CLAUDE_BIN-substitution mocking `tests/test_sentinel_loop.py` uses for the outer loop, this
file substitutes a scripted GATE command (`true`/`false`) for whatever a real task would run,
so the whole chain is deterministic and needs no model. The properties under test:

  * verified_facts (signal.json, via hook.py post) advance ONLY when the gate genuinely
    passes — a fabricated "it's done" claim over a failing artifact is dropped, not admitted.
  * gatekeeper.sh blocks the Stop hook whenever the plan is not genuinely done, including the
    defense-in-depth case where a box was checked despite its recorded artifact having failed.
"""
import json
import os
import shutil
import subprocess
import sys

import pytest

from plateau.integrity import file_hash

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOOK = os.path.join(ROOT, "adapters", "claude_code", "hook.py")
GATEKEEPER = os.path.join(ROOT, "adapters", "claude_code", "control", "gatekeeper.sh")
CLI = [sys.executable, "-m", "plateau.agency.control"]

pytestmark = pytest.mark.skipif(not shutil.which("bash"), reason="bash required")


def _hook(mode, tmp_path):
    """Run hook.py <mode> as the real subprocess a Claude Code hook would invoke (dry,
    non-`--cc`, so the raw result dict is easy to assert on)."""
    env = dict(os.environ, PYTHONPATH=ROOT)
    r = subprocess.run([sys.executable, HOOK, mode], cwd=str(tmp_path), input="",
                       capture_output=True, text=True, env=env)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def _gate_turn(cdir, root):
    """The scripted VERIFY step (V1): run every PLAN gate for real and record the artifact —
    exactly what the parent's V1 step does, done here via the same CLI a human/gatekeeper
    would use, so no test-only shortcut exists between 'gate ran' and 'artifact written'."""
    r = subprocess.run(CLI + ["verify", "--control-dir", str(cdir), "--root", str(root),
                              "--strict", "--json"], cwd=ROOT, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def _gatekeeper(tmp_path, cdir):
    env = dict(os.environ, CONTROL_DIR=str(cdir))
    r = subprocess.run(["bash", GATEKEEPER], cwd=str(tmp_path), input="{}",
                       capture_output=True, text=True, env=env)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


def _write_pending(tmp_path, claim, artifact_path):
    """Propose ONE fact grounded in the gate artifact via an `exit_code` Measurement — the
    same grounding `control.task_fact` builds. hook.py post admits it only if the artifact's
    hash is unchanged AND its recorded exit_code is 0."""
    pd = tmp_path / ".plateau"
    pd.mkdir(exist_ok=True)
    rel = os.path.relpath(str(artifact_path), str(tmp_path))
    pending = [{"claim": claim, "kind": "exit_code", "source": rel,
               "value": file_hash(str(artifact_path))}]
    (pd / "pending_facts.json").write_text(json.dumps(pending))


def test_turn_where_the_gate_passes_admits_the_fact_and_releases_the_stop_hook(tmp_path):
    """The happy path, chained end to end: pre -> gate turn -> post -> Stop. A genuinely
    passing gate is what makes both the signal AND the Stop hook agree the turn is done."""
    cdir = tmp_path / ".plateau" / "control"
    cdir.mkdir(parents=True)
    (cdir / "PLAN.md").write_text("- [ ] T1 | write marker | out.txt | GATE: true | EXPECT: exit0\n")

    pre = _hook("pre", tmp_path)
    assert pre["carried_self_state"]["verified_facts"] == []       # nothing carried in yet

    gate = _gate_turn(cdir, tmp_path)
    assert gate["verdict"] == "DONE" and gate["passed"] == ["T1"]
    artifact_path = cdir / "gates" / "T1.gate.json"
    artifact = json.loads(artifact_path.read_text())
    assert artifact["exit_code"] == 0

    _write_pending(tmp_path, "T1 done", artifact_path)
    post = _hook("post", tmp_path)
    assert post["admitted"] == ["T1 done"]
    assert post["dropped_ungrounded"] == []
    signal = json.loads((tmp_path / ".plateau" / "signal.json").read_text())
    assert [vf["claim"] for vf in signal["verified_facts"]] == ["T1 done"]

    # V2: the box is checked iff the fact was admitted.
    (cdir / "PLAN.md").write_text("- [x] T1 | write marker | out.txt | GATE: true | EXPECT: exit0\n")
    assert _gatekeeper(tmp_path, cdir) == ""                        # ALLOW_DONE -> release
    state = json.loads((cdir / "STATE.json").read_text())
    assert state["verdict"] == "ALLOW_DONE"


def test_turn_where_the_gate_fails_drops_the_fact_and_gatekeeper_keeps_blocking(tmp_path):
    """A gate that genuinely fails must move NOTHING forward: hook.py post refuses the
    fabricated claim, and gatekeeper.sh will not let the Stop hook release."""
    cdir = tmp_path / ".plateau" / "control"
    cdir.mkdir(parents=True)
    (cdir / "PLAN.md").write_text("- [ ] T1 | write marker | out.txt | GATE: false | EXPECT: exit0\n")

    pre = _hook("pre", tmp_path)
    assert pre["carried_self_state"]["verified_facts"] == []

    gate = _gate_turn(cdir, tmp_path)
    assert gate["verdict"] == "BLOCK" and gate["unchecked"] == ["T1"]
    artifact_path = cdir / "gates" / "T1.gate.json"
    artifact = json.loads(artifact_path.read_text())
    assert artifact["exit_code"] != 0

    # A worker claiming "T1 done" anyway over the FAILING artifact — must be refused.
    _write_pending(tmp_path, "T1 done", artifact_path)
    post = _hook("post", tmp_path)
    assert post["admitted"] == []
    assert post["dropped_ungrounded"] == ["T1 done"]
    signal = json.loads((tmp_path / ".plateau" / "signal.json").read_text())
    assert signal["verified_facts"] == []

    # PLAN.md correctly stays unchecked -> gatekeeper still blocks.
    out = json.loads(_gatekeeper(tmp_path, cdir))
    assert out["decision"] == "block"
    assert "T1" in out["reason"]
    state = json.loads((cdir / "STATE.json").read_text())
    assert state["verdict"] == "BLOCK"


def test_mischecked_row_is_blocked_by_gatekeeper_and_its_fact_still_refused(tmp_path):
    """Defense in depth: even if a box gets checked despite its own recorded artifact having
    FAILED (a stale/mischecked row), gatekeeper.sh must still block the Stop hook, AND
    hook.py post must still refuse to fold the corresponding fact into the signal — one bad
    checkbox must not be enough to fool either mechanism."""
    cdir = tmp_path / ".plateau" / "control"
    cdir.mkdir(parents=True)
    # checked from the start, but its gate genuinely fails
    (cdir / "PLAN.md").write_text("- [x] T1 | write marker | out.txt | GATE: false | EXPECT: exit0\n")

    _hook("pre", tmp_path)

    gate = _gate_turn(cdir, tmp_path)
    assert gate["verdict"] == "BLOCK" and gate["unchecked"] == ["T1"]     # strict catches it too
    artifact_path = cdir / "gates" / "T1.gate.json"
    artifact = json.loads(artifact_path.read_text())
    assert artifact["exit_code"] != 0

    _write_pending(tmp_path, "T1 done", artifact_path)
    post = _hook("post", tmp_path)
    assert post["admitted"] == []
    assert post["dropped_ungrounded"] == ["T1 done"]

    out = json.loads(_gatekeeper(tmp_path, cdir))
    assert out["decision"] == "block"
    assert "T1" in out["reason"] and "FAILED" in out["reason"]
