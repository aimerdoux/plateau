#!/usr/bin/env python3
"""demo4 objective stale-detection probe (part of the locked success check).

Runs ENTIRELY against the plateau package importable on sys.path[0] (an ARM repo
copy). Pre-registered in demo4_prereg.md step "objective success check":

  create a command_output Measurement on a temp command, confirm it re-verifies;
  mutate the command's output; confirm gate/inflate now drop it as stale.

Emits a single JSON line: {"probe_ok": bool, "reason": str}. probe_ok is True
ONLY if every assertion below holds. Fails closed (probe_ok False) on any
AttributeError/missing-API — i.e. an arm that has not implemented command_output
yet cannot pass. No grading; binary.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile


def _emit(ok: bool, reason: str) -> None:
    print(json.dumps({"probe_ok": bool(ok), "reason": reason}))
    sys.exit(0)


def main() -> None:
    repo = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else os.getcwd()
    sys.path.insert(0, repo)
    try:
        from plateau import signal as sig
        from plateau import continuum as cont
    except Exception as e:  # noqa: BLE001
        _emit(False, f"import failed: {e!r}")

    # The command_output kind must exist on the Measurement type at all.
    kinds = getattr(sig.Measurement, "__annotations__", {})
    # (annotations are a weak check; the real check is behavioural below.)

    tmpd = tempfile.mkdtemp(prefix="demo4probe_")
    target = os.path.join(tmpd, "out.txt")
    with open(target, "w") as f:
        f.write("STABLE-OUTPUT-v1\n")

    # A whitelisted command whose stdout we control by editing `target`.
    # Use the running interpreter to avoid PATH assumptions; print the file.
    cmd = f'{sys.executable} -c "import sys;sys.stdout.write(open(r\'{target}\').read())"'

    # Whitelist mechanism must exist (fail-closed design). Accept either a
    # set_command_whitelist(...) setter or a module-level _CMD_WHITELIST set.
    try:
        if hasattr(sig, "set_command_whitelist"):
            sig.set_command_whitelist([cmd])
        elif hasattr(sig, "_CMD_WHITELIST"):
            sig._CMD_WHITELIST.clear()
            sig._CMD_WHITELIST.add(cmd)
        else:
            _emit(False, "no command whitelist API (set_command_whitelist/_CMD_WHITELIST)")
    except Exception as e:  # noqa: BLE001
        _emit(False, f"whitelist setup failed: {e!r}")

    # Build a command_output Measurement: value = hash of stdout at grounding time.
    try:
        m_probe = sig.Measurement(kind="command_output", source=cmd, value="")
        # Recompute the live value the way the implementation must: hash of stdout.
        # We don't know its internal hashing, so we ground by: create with a
        # placeholder, then read the value the impl considers current via a fresh
        # grounding helper if present; otherwise require reverify with the correct
        # recorded value. The robust contract: there must be a way to record the
        # current value such that reverify() is True while stable.
    except Exception as e:  # noqa: BLE001
        _emit(False, f"Measurement(kind=command_output) rejected: {e!r}")

    # Obtain the canonical recorded value. The implementation hashes stdout; expose
    # that via a fresh Measurement whose value we set by asking the impl to ground.
    # Contract probe: the impl must make reverify() True when value == hash(stdout).
    # We discover hash(stdout) by trying the impl's own file_hash-style helper if it
    # mirrors file_hash, else by a 'record_command_output' helper if provided.
    recorded = None
    if hasattr(sig, "record_command_output"):
        try:
            recorded = sig.record_command_output(cmd)  # returns the value string
        except Exception as e:  # noqa: BLE001
            _emit(False, f"record_command_output failed: {e!r}")
    else:
        # Derive the expected value by the documented rule: sha256 of stdout bytes,
        # 'sha256:'-prefixed (same convention as file_hash). The impl MUST match this.
        import hashlib
        import subprocess
        try:
            p = subprocess.run(cmd, shell=True, capture_output=True, timeout=15)
            if p.returncode != 0:
                _emit(False, f"probe command nonzero exit during setup: {p.returncode}")
            recorded = "sha256:" + hashlib.sha256(p.stdout).hexdigest()
        except Exception as e:  # noqa: BLE001
            _emit(False, f"probe command run failed: {e!r}")

    m = sig.Measurement(kind="command_output", source=cmd, value=recorded)

    # 1) reverifies True while stable
    try:
        if not m.reverify():
            _emit(False, "reverify() False while output stable (value rule mismatch)")
    except Exception as e:  # noqa: BLE001
        _emit(False, f"reverify() raised while stable: {e!r}")

    # 2) gate admits it while live
    th = sig.Thought(claim="probe fact", grounding=m)
    gres = sig.gate([th])
    if len(gres.admitted) != 1 or gres.dropped:
        _emit(False, f"gate did not admit live command_output fact: {gres}")

    # 3) carries through emit/inflate while live (continuum lossless + re-grounds live)
    st = sig.SelfState(signal=sig.RelationalState(
        verified_facts=[{"claim": "probe fact",
                         "grounding_kind": "command_output",
                         "grounding_source": cmd,
                         "grounding_value": recorded}]))
    blob = cont.emit(st)
    infl_live = cont.inflate(blob, fresh=True)
    if infl_live.stale or len(infl_live.state.verified_facts) != 1:
        _emit(False, f"inflate dropped a LIVE command_output fact: stale={infl_live.stale_claims()}")

    # ---- mutate the command's output ----
    with open(target, "w") as f:
        f.write("CHANGED-OUTPUT-v2-different\n")

    # 4) reverify now False
    try:
        if m.reverify():
            _emit(False, "reverify() still True AFTER output changed (no stale detection)")
    except Exception as e:  # noqa: BLE001
        _emit(False, f"reverify() raised after change: {e!r}")

    # 5) gate now drops it
    gres2 = sig.gate([sig.Thought(claim="probe fact", grounding=m)])
    if gres2.admitted or len(gres2.dropped) != 1:
        _emit(False, f"gate admitted a STALE command_output fact: {gres2}")

    # 6) inflate now flags it stale
    infl_stale = cont.inflate(blob, fresh=True)
    if "probe fact" not in infl_stale.stale_claims():
        _emit(False, "inflate did NOT flag the now-stale command_output fact")

    # 7) fail-closed: a non-whitelisted command must reverify False (security contract)
    bad = sig.Measurement(kind="command_output", source="echo not-whitelisted", value=recorded)
    try:
        if bad.reverify():
            _emit(False, "non-whitelisted command reverified True (whitelist not enforced)")
    except Exception as e:  # noqa: BLE001
        _emit(False, f"non-whitelisted reverify raised instead of failing closed: {e!r}")

    _emit(True, "command_output kind: live-admit, stale-drop, fail-closed all hold")


if __name__ == "__main__":
    main()
