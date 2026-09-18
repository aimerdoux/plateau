"""Claude Code adapter — `--cc` hook JSON shape. Exercises hook.py end-to-end as a
subprocess (the real hook path), independent of the host. Core 26 tests untouched.

Extended for step 3 (docs/harness-0.3/PLAN-step3.md "Tests (B4)"): every command in
adapters/claude_code/hooks/hooks.json resolves to a hook.py mode that actually runs
clean; `hook.py inject --cc` on a `compact` payload returns additionalContext under
budget in a temp root; `hook.py handoff --cc --print` returns a systemMessage
containing `<plateau_handoff v=1>`.
"""

import json
import os
import re
import shlex
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # plateau project dir
ADAPTER_DIR = os.path.join(ROOT, "adapters", "claude_code")
HOOK = os.path.join(ADAPTER_DIR, "hook.py")
HOOKS_JSON = os.path.join(ADAPTER_DIR, "hooks", "hooks.json")
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


# ---------------------------------------------------------------------------
# step 3: hooks.json <-> hook.py wiring, inject, handoff
# ---------------------------------------------------------------------------

KNOWN_HOOK_PY_MODES = {
    "parent", "pre", "post",                       # legacy (0.1) modes
    "receipt", "snapshot", "inject", "handoff", "lift", "ledger",  # step-3 modes
}


def _iter_hooks_json_commands():
    with open(HOOKS_JSON, encoding="utf-8") as f:
        data = json.load(f)
    for event, groups in data["hooks"].items():
        for group in groups:
            for hook in group["hooks"]:
                yield event, hook["command"], hook.get("timeout")


def test_every_hooks_json_command_names_a_known_hook_py_mode():
    seen_modes = set()
    for event, command, _timeout in _iter_hooks_json_commands():
        assert "hook.py" in command, "{}: command has no hook.py: {!r}".format(event, command)
        m = re.search(r"hook\.py\s+(\S+)", command)
        assert m, "{}: could not find a mode in {!r}".format(event, command)
        mode = m.group(1)
        assert mode in KNOWN_HOOK_PY_MODES, "{}: unknown hook.py mode {!r}".format(event, mode)
        seen_modes.add(mode)
    # every mode PLAN-step3.md's hooks.json table lists actually appears somewhere
    for expected in ("parent", "inject", "pre", "receipt", "snapshot", "post", "lift", "handoff", "ledger"):
        assert expected in seen_modes, "hooks.json is missing a {!r} entry".format(expected)


def test_every_hooks_json_command_runs_clean(tmp_path):
    """Every literal command string in hooks.json, run the way Claude Code itself
    would invoke it (`${CLAUDE_PLUGIN_ROOT}` substituted, payload on stdin, cwd = the
    project root), exits 0 and never raises -- including modes whose target module
    (`plateau.lab.ledger`) does not exist yet, which must degrade to a clean no-op."""
    env = dict(os.environ, PYTHONPATH=ROOT, CLAUDE_PLUGIN_ROOT=ADAPTER_DIR)
    payload = json.dumps({"cwd": str(tmp_path), "session_id": "hooks-json-sess",
                          "transcript_path": "", "hook_event_name": "PostToolUse",
                          "source": "startup", "tool_name": "Bash",
                          "tool_input": {}, "tool_response": {}})
    for event, command, _timeout in _iter_hooks_json_commands():
        cmd = command.replace("${CLAUDE_PLUGIN_ROOT}", ADAPTER_DIR)
        argv = shlex.split(cmd)
        argv[0] = sys.executable  # use this interpreter, not whatever "python3" resolves to
        r = subprocess.run(argv, cwd=str(tmp_path), input=payload,
                           capture_output=True, text=True, env=env, timeout=30)
        assert r.returncode == 0, "{} ({!r}): rc={} stderr={}".format(
            event, command, r.returncode, r.stderr)


def test_cc_inject_on_compact_returns_additional_context_under_budget(tmp_path):
    root = str(tmp_path)
    transcript = tmp_path / "t.jsonl"
    transcript.write_text(json.dumps(
        {"message": {"role": "user", "content": "what should I do next?"}}) + "\n")
    payload = {"cwd": root, "session_id": "cc-inject-sess", "transcript_path": str(transcript),
              "hook_event_name": "SessionStart", "source": "compact"}
    env = dict(os.environ, PYTHONPATH=ROOT)
    r = subprocess.run([sys.executable, HOOK, "inject", "--cc"], cwd=root,
                       input=json.dumps(payload), capture_output=True, text=True, env=env)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    hso = out["hookSpecificOutput"]
    assert hso["hookEventName"] == "SessionStart"
    ctx = hso["additionalContext"]
    assert ctx.startswith("<plateau_index>")
    assert ctx.endswith("</plateau_index>")
    assert len(ctx) <= 12000  # bridge.default.toml [budget] compaction_chars


def test_cc_handoff_print_returns_systemmessage_with_handoff_block(tmp_path):
    root = str(tmp_path)
    payload = {"cwd": root, "session_id": "cc-handoff-sess", "hook_event_name": "Stop"}
    env = dict(os.environ, PYTHONPATH=ROOT)
    r = subprocess.run([sys.executable, HOOK, "handoff", "--cc", "--print"], cwd=root,
                       input=json.dumps(payload), capture_output=True, text=True, env=env)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert "systemMessage" in out
    msg = out["systemMessage"]
    assert "<plateau_handoff v=1>" in msg
    # the systemMessage IS the rendered block (PLAN-step3.md hooks.json: `handoff
    # --print emits {"systemMessage": "<plateau_handoff ...>"}` so the block is the
    # last thing shown in the turn) -- not the block re-wrapped as a JSON string.
    assert msg.startswith("<plateau_handoff v=1>")
    assert msg.rstrip("\n").endswith("</plateau_handoff>")
