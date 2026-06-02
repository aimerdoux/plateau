"""Claude Code adapter — `--cc` hook JSON shape. Exercises hook.py end-to-end as a
subprocess (the real hook path), independent of the host. Core 26 tests untouched."""

import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # plateau project dir
HOOK = os.path.join(ROOT, "adapters", "claude_code", "hook.py")
_SIG = {"schema": "continuum.signal.v1", "open_goals": [], "stance": "",
        "lessons": [], "pointers": [], "verified_facts": []}


def _run(mode, tmp_path, signal=None, pending=None):
    pd = tmp_path / ".plateau"
    pd.mkdir(exist_ok=True)
    (pd / "signal.json").write_text(json.dumps(signal or _SIG))
    if pending is not None:
        (pd / "pending_facts.json").write_text(json.dumps(pending))
    env = dict(os.environ, PYTHONPATH=ROOT)  # ensure `import plateau` resolves
    r = subprocess.run([sys.executable, HOOK, mode, "--cc"], cwd=str(tmp_path),
                       input="{}", capture_output=True, text=True, env=env)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def test_cc_pre_injects_carried_signal_as_additional_context(tmp_path):
    sig = dict(_SIG, open_goals=["ship plateau plugin"], stance="bounded context")
    out = _run("pre", tmp_path, signal=sig)
    hso = out["hookSpecificOutput"]
    assert hso["hookEventName"] == "UserPromptSubmit"
    assert "ship plateau plugin" in hso["additionalContext"]
    assert "Plateau" in hso["additionalContext"]


def test_cc_post_drops_ungrounded_fact_and_persists(tmp_path):
    # a fact whose source file does not exist must NOT be admitted (the gate)
    out = _run("post", tmp_path,
               pending=[{"claim": "build passes", "source": "nope.txt",
                         "value": "sha256:deadbeef"}])
    assert out.get("suppressOutput") is True
    assert "persisted" in out["systemMessage"]
    # the bounded signal on disk carries no fabricated fact
    blob = json.loads((tmp_path / ".plateau" / "signal.json").read_text())
    assert blob["verified_facts"] == []
