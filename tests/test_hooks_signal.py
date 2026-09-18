"""tests/test_hooks_signal.py — owner C5 (docs/harness-0.3/PLAN-step4.md "Tests (C5)").

S4-A1 ("One install story") moved the `parent`/`pre`/`post` hook logic out of
`adapters/claude_code/hook.py` and into the package (`plateau/hooks/signal.py`), with
`adapters/claude_code/hook.py` becoming a thin shim that dispatches to it. This file
checks two things the plan calls out explicitly:

1. `plateau.hooks.signal` produces the SAME hook JSON the old (pre-step-4) inline modes
   did — the expectations here are the ones `tests/test_cc_adapter.py` already encodes
   for `pre`/`post`/`parent` (that file's own subprocess-level tests keep passing
   because `hook.py` now just delegates to this module; the tests below additionally
   exercise `plateau.hooks.signal.main` directly, in-process, against the same
   expectations, so a regression in the package module itself — not just in the shim's
   wiring — is caught here too).
2. `adapters/claude_code/hook.py <mode> --cc` still works for all nine modes (the full
   set S4-A1 dispatches: `parent, pre, post, receipt, snapshot, inject, handoff, lift,
   ledger`), not just the three signal ones.
"""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys

import pytest

from plateau.hooks import signal as hooks_signal

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # plateau project dir
ADAPTER_DIR = os.path.join(ROOT, "adapters", "claude_code")
HOOK = os.path.join(ADAPTER_DIR, "hook.py")

# Same carried-signal fixture `tests/test_cc_adapter.py` uses for its `_run("pre", ...)`
# / `_run("post", ...)` expectations.
_SIG = {"schema": "continuum.signal.v1", "open_goals": [], "stance": "",
        "lessons": [], "pointers": [], "verified_facts": []}

ALL_NINE_MODES = (
    "parent", "pre", "post",                                       # plateau.hooks.signal
    "receipt", "snapshot", "inject", "handoff", "lift", "ledger",  # module modes
)


def _call_signal_in_process(mode, tmp_path, monkeypatch, capsys, stdin_payload="{}"):
    """Invoke `plateau.hooks.signal.main(mode, ["--cc"])` in-process with `tmp_path` as
    the project root (the module grounds via `os.getcwd()`, not the hook payload) and
    the given stdin JSON (drained, never parsed, by `--cc` mode — see the module's own
    `main()` docstring). Returns the parsed hook JSON it printed."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "stdin", io.StringIO(stdin_payload))
    hooks_signal.main(mode, ["--cc"])
    out = capsys.readouterr().out
    return json.loads(out)


# ---------------------------------------------------------------------------
# 1. plateau.hooks.signal produces the same JSON as the old inline modes did
#    (expectations mirrored from tests/test_cc_adapter.py)
# ---------------------------------------------------------------------------


def test_signal_pre_injects_carried_signal_as_additional_context(tmp_path, monkeypatch, capsys):
    pd = tmp_path / ".plateau"
    pd.mkdir()
    sig = dict(_SIG, open_goals=["ship plateau plugin"], stance="bounded context")
    (pd / "signal.json").write_text(json.dumps(sig))

    out = _call_signal_in_process("pre", tmp_path, monkeypatch, capsys)

    hso = out["hookSpecificOutput"]
    assert hso["hookEventName"] == "UserPromptSubmit"
    assert "ship plateau plugin" in hso["additionalContext"]
    assert "Plateau" in hso["additionalContext"]


def test_signal_post_drops_ungrounded_fact_and_persists(tmp_path, monkeypatch, capsys):
    pd = tmp_path / ".plateau"
    pd.mkdir()
    (pd / "signal.json").write_text(json.dumps(_SIG))
    (pd / "pending_facts.json").write_text(json.dumps(
        [{"claim": "build passes", "source": "nope.txt", "value": "sha256:deadbeef"}]
    ))

    out = _call_signal_in_process("post", tmp_path, monkeypatch, capsys)

    assert out.get("suppressOutput") is True
    assert "persisted" in out["systemMessage"]
    # the bounded signal on disk carries no fabricated fact -- same assertion
    # tests/test_cc_adapter.py makes against the subprocess path.
    blob = json.loads((pd / "signal.json").read_text())
    assert blob["verified_facts"] == []


def test_signal_post_admits_a_grounded_fact(tmp_path, monkeypatch, capsys):
    pd = tmp_path / ".plateau"
    pd.mkdir()
    (pd / "signal.json").write_text(json.dumps(_SIG))
    src = tmp_path / "real.txt"
    src.write_text("hello")
    import hashlib
    digest = "sha256:" + hashlib.sha256(b"hello").hexdigest()
    (pd / "pending_facts.json").write_text(json.dumps(
        [{"claim": "real.txt says hello", "source": "real.txt", "value": digest}]
    ))

    out = _call_signal_in_process("post", tmp_path, monkeypatch, capsys)

    assert out.get("suppressOutput") is True
    n_admitted = int(out["systemMessage"].split("(")[1].split(" fact")[0])
    assert n_admitted == 1
    blob = json.loads((pd / "signal.json").read_text())
    assert [vf["claim"] for vf in blob["verified_facts"]] == ["real.txt says hello"]


def test_signal_post_is_quiet_when_nothing_was_proposed(tmp_path, monkeypatch, capsys):
    """0.4.1: an idle Stop (no queue) persists the signal without a notice. Before, every
    Stop of every session printed `Plateau: signal persisted ... (0 fact(s) admitted, 0
    dropped ungrounded)` whether or not anything had been proposed."""
    pd = tmp_path / ".plateau"
    pd.mkdir()
    sig = dict(_SIG, open_goals=["keep me"])
    (pd / "signal.json").write_text(json.dumps(sig))

    out = _call_signal_in_process("post", tmp_path, monkeypatch, capsys)

    assert out == {"suppressOutput": True}
    blob = json.loads((pd / "signal.json").read_text())
    assert blob["open_goals"] == ["keep me"] and blob["verified_facts"] == []
    # quiet, but it did persist: the seed was written with the old schema tag and only
    # emit() writes the current one, so a rewrite is visible (a no-op _save_blob is not).
    assert blob["schema"] == "plateau.signal.v1"


def test_signal_post_consumes_the_queue_so_a_fact_is_gated_once(tmp_path, monkeypatch, capsys):
    """0.4.1, the reproduced defect: `pending_facts.json` was read at every Stop and
    never removed, so a queue left behind re-admitted its facts on every Stop -- the
    signal grew a copy each time while the notice said 0 admitted. Now the first Stop
    gates and consumes it; the second finds nothing, says nothing, and the signal holds
    exactly one copy."""
    pd = tmp_path / ".plateau"
    pd.mkdir()
    (pd / "signal.json").write_text(json.dumps(_SIG))
    src = tmp_path / "real.txt"
    src.write_text("hello")
    import hashlib
    digest = "sha256:" + hashlib.sha256(b"hello").hexdigest()
    (pd / "pending_facts.json").write_text(json.dumps(
        [{"claim": "real.txt says hello", "source": "real.txt", "value": digest}]
    ))
    (pd / "pending_carry.json").write_text(json.dumps(["always hash before trusting"]))

    first = _call_signal_in_process("post", tmp_path, monkeypatch, capsys)
    assert "1 fact(s) admitted" in first["systemMessage"]
    assert not (pd / "pending_facts.json").exists()
    assert not (pd / "pending_carry.json").exists()

    second = _call_signal_in_process("post", tmp_path, monkeypatch, capsys)
    assert second == {"suppressOutput": True}
    blob = json.loads((pd / "signal.json").read_text())
    assert [vf["claim"] for vf in blob["verified_facts"]] == ["real.txt says hello"]
    assert blob["lessons"] == ["always hash before trusting"]


def test_signal_post_leaves_the_queue_when_the_blob_cannot_be_persisted(tmp_path, monkeypatch, capsys):
    """The queue is consumed only after the new blob is on disk: a Stop whose persist
    fails leaves the proposal for the next Stop instead of losing it."""
    pd = tmp_path / ".plateau"
    pd.mkdir()
    (pd / "signal.json").write_text(json.dumps(_SIG))
    (pd / "pending_facts.json").write_text(json.dumps(
        [{"claim": "build passes", "source": "nope.txt", "value": "sha256:deadbeef"}]
    ))

    def boom(_blob):
        raise OSError("disk full")
    monkeypatch.setattr(hooks_signal, "_save_blob", boom)
    monkeypatch.chdir(tmp_path)
    with pytest.raises(OSError):
        hooks_signal.post()
    assert (pd / "pending_facts.json").exists()
    # ...and the next Stop, persisting fine, gates it and consumes it (the old hook never
    # consumed the queue at all, so this half is what tells the two apart).
    monkeypatch.undo()
    monkeypatch.chdir(tmp_path)
    out = hooks_signal.post()
    assert out["dropped_ungrounded"] == ["build passes"]
    assert not (pd / "pending_facts.json").exists()


def test_signal_pre_injects_a_bloated_signal_once_per_claim(tmp_path, monkeypatch, capsys):
    """0.4.1: the same claim persisted N times (the pre-0.4.1 growth) is injected once,
    and the next Stop rewrites the blob with one copy -- every directory that grew such
    a file heals on its own."""
    pd = tmp_path / ".plateau"
    pd.mkdir()
    src = tmp_path / "real.txt"
    src.write_text("hello")
    import hashlib
    digest = "sha256:" + hashlib.sha256(b"hello").hexdigest()
    vf = {"claim": "real.txt says hello", "grounding": {"kind": "file_hash", "source": "real.txt", "value": digest}}
    (pd / "signal.json").write_text(json.dumps(dict(_SIG, verified_facts=[vf] * 247)))

    out = _call_signal_in_process("pre", tmp_path, monkeypatch, capsys)
    ctx = out["hookSpecificOutput"]["additionalContext"]
    assert ctx.count("real.txt says hello") == 1

    _call_signal_in_process("post", tmp_path, monkeypatch, capsys)
    blob = json.loads((pd / "signal.json").read_text())
    assert [x["claim"] for x in blob["verified_facts"]] == ["real.txt says hello"]


def test_signal_parent_reads_the_canonical_package_manual(tmp_path, monkeypatch, capsys):
    """S4-A1's one behavior change: no more plugin-root/adapter-relative candidate
    search -- the manual is always the package copy
    `plateau/agency/PARENT_AGENT_MANUAL.md`."""
    out = _call_signal_in_process("parent", tmp_path, monkeypatch, capsys)

    hso = out["hookSpecificOutput"]
    manual_path = hooks_signal._manual_path()
    assert manual_path.endswith(os.path.join("plateau", "agency", "PARENT_AGENT_MANUAL.md"))
    assert os.path.isfile(manual_path), "the package copy must ship (pyproject.toml artifacts)"
    assert hso["hookEventName"] == "SessionStart"
    # the manual exists in this checkout, so the section-4 block must have been found
    # and injected -- not suppressed.
    assert "additionalContext" in hso
    assert "parent-agent discipline" in hso["additionalContext"]


def test_signal_parent_dict_mode_reports_the_resolved_manual_path(tmp_path, monkeypatch, capsys):
    """Without --cc, `parent()`'s raw dict names the manual path it read from -- always
    the package copy now, never a plugin-root/adapter-relative candidate."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "stdin", io.StringIO("{}"))
    hooks_signal.main("parent", [])
    out = json.loads(capsys.readouterr().out)
    assert out["found"] is True
    assert out["manual_path"] == os.path.abspath(hooks_signal._manual_path())


# ---------------------------------------------------------------------------
# 2. adapters/claude_code/hook.py <mode> --cc still works, for all nine modes
# ---------------------------------------------------------------------------


def _generic_hook_payload(tmp_path):
    """One payload shape that every one of the nine modes can run against cleanly --
    the module modes read only the keys relevant to their own event and ignore the
    rest (mirrors tests/test_cc_adapter.py's `test_every_hooks_json_command_runs_clean`
    fixture, extended with the Stop/PreCompact/SessionStart fields those tests already
    exercised individually)."""
    return json.dumps({
        "cwd": str(tmp_path), "session_id": "sig-parity-sess",
        "transcript_path": "", "hook_event_name": "PostToolUse",
        "source": "startup", "trigger": "manual", "stop_hook_active": False,
        "tool_name": "Bash", "tool_input": {}, "tool_response": {},
    })


@pytest.mark.parametrize("mode", ALL_NINE_MODES)
def test_hook_py_cc_works_for_every_mode(tmp_path, mode):
    pd = tmp_path / ".plateau"
    pd.mkdir()
    (pd / "signal.json").write_text(json.dumps(_SIG))

    env = dict(os.environ, PYTHONPATH=ROOT)
    r = subprocess.run(
        [sys.executable, HOOK, mode, "--cc"], cwd=str(tmp_path),
        input=_generic_hook_payload(tmp_path), capture_output=True, text=True,
        env=env, timeout=30,
    )
    assert r.returncode == 0, "{}: rc={} stderr={}".format(mode, r.returncode, r.stderr)
    assert "Traceback" not in r.stderr, "{}: stderr={}".format(mode, r.stderr)


def test_hook_py_cc_signal_modes_emit_valid_hook_json(tmp_path):
    """The three signal modes always print exactly one JSON object with `--cc` --
    unlike the six module modes, which may legitimately print nothing (e.g. `ledger`,
    a SessionEnd hook) or plain text (e.g. `lift`, `handoff` without `--print`)."""
    pd = tmp_path / ".plateau"
    pd.mkdir()
    (pd / "signal.json").write_text(json.dumps(_SIG))
    env = dict(os.environ, PYTHONPATH=ROOT)

    for mode in ("parent", "pre", "post"):
        r = subprocess.run(
            [sys.executable, HOOK, mode, "--cc"], cwd=str(tmp_path),
            input=_generic_hook_payload(tmp_path), capture_output=True, text=True,
            env=env, timeout=30,
        )
        assert r.returncode == 0, "{}: stderr={}".format(mode, r.stderr)
        out = json.loads(r.stdout)
        assert isinstance(out, dict) and out, "{}: empty/invalid hook JSON: {!r}".format(mode, r.stdout)
