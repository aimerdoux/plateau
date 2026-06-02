#!/usr/bin/env python3
"""demo6 objective full-pipeline probe (part of the locked success check).

Exercises the whole serial chain end-to-end against the plateau package on
sys.argv[1] (an arm repo copy). It can pass ONLY if L1 command_output, L2 all_of
composite, L3 continuum lossless carry, L4 ground_report, and L5 the report CLI all
work. Emits one JSON line {"probe_ok": bool, "reason": str}. Fails closed on any
missing API. No grading; binary.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile


def emit(ok, reason):
    print(json.dumps({"probe_ok": bool(ok), "reason": reason}))
    sys.exit(0)


def main():
    repo = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else os.getcwd()
    sys.path.insert(0, repo)
    try:
        from plateau import signal as sig
        from plateau import continuum as cont
        from plateau.integrity import file_hash
    except Exception as e:  # noqa: BLE001
        emit(False, f"import failed: {e!r}")

    # locate ground_report (L4) — accept signal / continuum / package top-level
    import plateau
    ground_report = (getattr(sig, "ground_report", None) or getattr(cont, "ground_report", None)
                     or getattr(plateau, "ground_report", None))
    if ground_report is None:
        emit(False, "no ground_report API (L4 missing)")

    tmpd = tempfile.mkdtemp(prefix="demo6probe_")
    target = os.path.join(tmpd, "out.txt")
    with open(target, "w") as f:
        f.write("STABLE-OUTPUT-v1\n")
    stable = os.path.join(tmpd, "fixed.txt")
    with open(stable, "w") as f:
        f.write("FIXED-FOREVER\n")

    cmd = f'{sys.executable} -c "import sys;sys.stdout.write(open(r\'{target}\').read())"'
    if not hasattr(sig, "set_command_whitelist"):
        emit(False, "no set_command_whitelist (L1 missing)")
    sig.set_command_whitelist([cmd])

    p = subprocess.run(cmd, shell=True, capture_output=True)
    if p.returncode != 0:
        emit(False, "probe command nonzero exit at setup")
    cmd_val = "sha256:" + hashlib.sha256(p.stdout).hexdigest()
    child_cmd = {"kind": "command_output", "source": cmd, "value": cmd_val}
    child_file = {"kind": "file_hash", "source": stable, "value": file_hash(stable)}
    comp_source = json.dumps([child_cmd, child_file])

    # L2: all_of composite re-verifies while every child live
    try:
        comp = sig.Measurement(kind="all_of", source=comp_source, value="")
    except Exception as e:  # noqa: BLE001
        emit(False, f"Measurement(kind=all_of) rejected (L2): {e!r}")
    try:
        if not comp.reverify():
            emit(False, "all_of reverify False while all children live (L2)")
    except Exception as e:  # noqa: BLE001
        emit(False, f"all_of reverify raised (L2): {e!r}")

    # gate admits the live composite
    if len(sig.gate([sig.Thought("chain", comp)]).admitted) != 1:
        emit(False, "gate did not admit a live all_of composite")

    # L3: continuum carries the composite (with nested children) losslessly + live
    st = sig.SelfState(signal=sig.RelationalState(verified_facts=[
        {"claim": "chain", "grounding_kind": "all_of",
         "grounding_source": comp_source, "grounding_value": ""}]))
    blob = cont.emit(st)
    infl = cont.inflate(blob, fresh=True)
    if infl.stale or len(infl.state.verified_facts) != 1:
        emit(False, f"inflate dropped a LIVE all_of (L3): stale={infl.stale_claims()}")

    # L4: ground_report aggregates, n_stale == 0 while live
    rep = ground_report(infl.state)
    if not isinstance(rep, dict) or rep.get("n_stale", -1) != 0:
        emit(False, f"ground_report n_stale != 0 while live (L4): {rep}")

    # L5: the report module must exist, and the REAL `python -m plateau.report <file>`
    # CLI (the prereg's L5 spec) must exit 0 iff all live. Exercised on a FILE_HASH
    # composite: a fresh CLI process cannot carry the process-local command_output
    # whitelist, and the explicit-main(argv) calling convention is unspecified — so the
    # CLI is driven by file_hash facts (whitelist-independent, unambiguous). The
    # command_output staleness path is proven in-process (gate/inflate/ground_report).
    try:
        from plateau import report as report_mod  # noqa: F401
    except Exception as e:  # noqa: BLE001
        emit(False, f"no plateau.report module (L5): {e!r}")
    fh = os.path.join(tmpd, "cli.txt")
    open(fh, "w").write("CLI-LIVE\n")
    fh_src = json.dumps([{"kind": "file_hash", "source": fh, "value": file_hash(fh)}])
    st_fh = sig.SelfState(signal=sig.RelationalState(verified_facts=[
        {"claim": "cli", "grounding_kind": "all_of", "grounding_source": fh_src, "grounding_value": ""}]))
    blobf_fh = os.path.join(tmpd, "fh.blob")
    open(blobf_fh, "w").write(cont.emit(st_fh))
    cli = subprocess.run([sys.executable, "-m", "plateau.report", blobf_fh],
                         cwd=repo, capture_output=True, text=True)
    if cli.returncode != 0:
        emit(False, f"`-m plateau.report` exit {cli.returncode} while file_hash live (L5): {cli.stderr[:160]}")

    # ---- mutate the command output: the composite must go stale through its child ----
    with open(target, "w") as f:
        f.write("CHANGED-v2-different\n")

    if comp.reverify():
        emit(False, "all_of still reverifies True after a child changed (no propagation)")
    if sig.gate([sig.Thought("chain", comp)]).admitted:
        emit(False, "gate admitted a STALE all_of")
    infl2 = cont.inflate(blob, fresh=True)
    if "chain" not in infl2.stale_claims():
        emit(False, "inflate did NOT flag the now-stale all_of")
    rep2b = ground_report(sig.RelationalState(verified_facts=[
        {"claim": "chain", "grounding_kind": "all_of",
         "grounding_source": comp_source, "grounding_value": ""}]))
    if rep2b.get("n_stale", 0) < 1:
        emit(False, f"ground_report n_stale<1 after mutation (L4): {rep2b}")
    named = any(cmd in (f.get("stale_children") or []) for f in rep2b.get("facts", []))
    if not named:
        emit(False, "ground_report did not name the stale child source in stale_children (L4)")

    # L5 after mutation: `-m plateau.report` on the file_hash composite now exits 1
    with open(fh, "w") as f:
        f.write("CLI-CHANGED\n")
    cli2 = subprocess.run([sys.executable, "-m", "plateau.report", blobf_fh],
                          cwd=repo, capture_output=True, text=True)
    if cli2.returncode == 0:
        emit(False, "`-m plateau.report` exit 0 after file_hash child went stale (L5)")

    emit(True, "verification chain L1-L5: live-admit, stale-propagation, report+CLI all hold")


if __name__ == "__main__":
    main()
