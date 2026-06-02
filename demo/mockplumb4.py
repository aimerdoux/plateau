#!/usr/bin/env python3
"""demo4 MOCK-PLUMB — prove the harness free, before any paid dispatch.

Three proofs (all deterministic, no model calls):
  A. scorer branch proof — synthetic per-step records crafted to land in EACH verdict
     branch (efficiency: WIN/PARTIAL_FORGETS/NULL/UNSCORABLE; autonomy: WIN/NULL/DEGRADE/MOOT).
  B. objective-check proof — a reference-correct repo returns ok=True with >=28 tests;
     the pristine baseline returns ok=False (probe fails, only 26 tests). The reference
     impl is THROWAWAY plumbing; it is NOT used as any arm's result.
  C. seal/recompute proof — seal synthetic records write-once, verify chain+files, and
     re-run score() from the sealed bytes in-process; numbers reproduce.

Run: python3 demo/mockplumb4.py
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness4 as H  # noqa: E402

sys.path.insert(0, H.REPO)  # so the orchestrator can import plateau.integrity for proof C

REPO = H.REPO
FAILS = []


def check(name, cond, detail=""):
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" — {detail}" if detail and not cond else ""))
    if not cond:
        FAILS.append(name)


# ---------------------------------------------------------------- synthetic records
def _step(step, ctx, passed, *, failed=0, errors=0, probe_ok=True, broken=False):
    """A clean-but-incomplete step is exit=0 (existing tests green, count<28, NOT an
    error). A step is an error/rework step ONLY if it broke the build: broken/failed/
    errors -> exit=1. ok requires exit0 AND >=28 AND probe_ok."""
    exit_ = 1 if (broken or failed or errors) else 0
    ok = (exit_ == 0 and passed >= H.SUCCESS_MIN_TESTS and failed == 0 and errors == 0 and probe_ok)
    return {"step": step, "context_tokens": ctx,
            "check": {"exit": exit_, "passed": passed, "failed": failed, "errors": errors,
                      "n_tests": passed + failed + errors, "ok_pytest": ok,
                      "probe_ok": probe_ok, "ok": ok}}


def _arm(steps):
    return {"steps": steps}


def proof_A():
    print("PROOF A — scorer branch coverage (synthetic):")

    # arm1 climbing transcript (1000 -> ~9000), clean steps, PASSes at step 4.
    climb = [_step(1, 1000, 26), _step(2, 3000, 27), _step(3, 6000, 27), _step(4, 9000, 28)]
    flat_pass = [_step(1, 1200, 26), _step(2, 1250, 27), _step(3, 1230, 27), _step(4, 1260, 28)]

    # WIN: arm1 climbs, arm2 flat + PASS parity
    r = H.score({"arm1_fullhistory": _arm(climb), "arm2_efficiency": _arm(flat_pass),
                 "arm3_autonomy": _arm(flat_pass)})
    check("efficiency WIN", r["efficiency"]["verdict"] == "WIN", r["efficiency"]["verdict"])

    # PARTIAL_FORGETS: arm2 bounded but never reaches 28 while arm1 PASSES (amnesia)
    flat_fail = [_step(1, 1200, 26), _step(2, 1250, 26), _step(3, 1230, 26), _step(4, 1260, 26)]
    r = H.score({"arm1_fullhistory": _arm(climb), "arm2_efficiency": _arm(flat_fail),
                 "arm3_autonomy": _arm(flat_pass)})
    check("efficiency PARTIAL_FORGETS", r["efficiency"]["verdict"] == "PARTIAL_FORGETS", r["efficiency"]["verdict"])

    # NULL: arm2 also climbs (slope not <=25% of arm1)
    r = H.score({"arm1_fullhistory": _arm(climb), "arm2_efficiency": _arm(climb),
                 "arm3_autonomy": _arm(flat_pass)})
    check("efficiency NULL", r["efficiency"]["verdict"] == "NULL", r["efficiency"]["verdict"])

    # UNSCORABLE: arm1 does not climb (flat)
    r = H.score({"arm1_fullhistory": _arm(flat_pass), "arm2_efficiency": _arm(flat_pass),
                 "arm3_autonomy": _arm(flat_pass)})
    check("efficiency UNSCORABLE", r["efficiency"]["verdict"] == "UNSCORABLE", r["efficiency"]["verdict"])

    # ---- autonomy branches (arm1 climbs so efficiency context is scorable)
    # WIN: arm3 fewer steps than arm2, both clean
    a2_5 = [_step(1, 1200, 26), _step(2, 1250, 27), _step(3, 1230, 27), _step(4, 1240, 27),
            _step(5, 1260, 28)]
    a3_3 = [_step(1, 1300, 27), _step(2, 1320, 27), _step(3, 1340, 28)]
    r = H.score({"arm1_fullhistory": _arm(climb), "arm2_efficiency": _arm(a2_5),
                 "arm3_autonomy": _arm(a3_3)})
    check("autonomy WIN (fewer steps)", r["autonomy"]["verdict"] == "WIN", r["autonomy"]["verdict"])

    # NULL: tie on steps and errors (both clean, both PASS@4)
    r = H.score({"arm1_fullhistory": _arm(climb), "arm2_efficiency": _arm(flat_pass),
                 "arm3_autonomy": _arm(flat_pass)})
    check("autonomy NULL (tie)", r["autonomy"]["verdict"] == "NULL", r["autonomy"]["verdict"])

    # DEGRADE: arm3 has a broken (rework) step; arm2 clean -> arm3 errors 1 > arm2 errors 0
    a3_err = [_step(1, 1300, 25, broken=True), _step(2, 1320, 27), _step(3, 1340, 27),
              _step(4, 1360, 28)]
    r = H.score({"arm1_fullhistory": _arm(climb), "arm2_efficiency": _arm(flat_pass),
                 "arm3_autonomy": _arm(a3_err)})
    check("autonomy DEGRADE (more errors)", r["autonomy"]["verdict"] == "DEGRADE", r["autonomy"]["verdict"])

    # MOOT: neither arm2 nor arm3 reaches PASS within their steps
    never = [_step(1, 1200, 26), _step(2, 1250, 26)]
    r = H.score({"arm1_fullhistory": _arm(climb), "arm2_efficiency": _arm(never),
                 "arm3_autonomy": _arm(never)})
    check("autonomy MOOT (neither passes)", r["autonomy"]["verdict"] == "MOOT", r["autonomy"]["verdict"])


# ---------------------------------------------------------------- reference impl (throwaway)
def apply_reference_impl(repo: str):
    """Minimal correct command_output impl — ONLY to prove the check's PASS branch.
    Edits signal.py + adds 2 tests. Not used as any arm's measured result."""
    sp = os.path.join(repo, "plateau", "signal.py")
    s = open(sp).read()
    s = s.replace('import os\n', 'import hashlib\nimport os\nimport subprocess\n', 1)
    s = s.replace(
        'kind: Literal["file_hash", "test_result", "oracle_score", "exit_code", "operator"]',
        'kind: Literal["file_hash", "test_result", "oracle_score", "exit_code", "operator", "command_output"]')
    # whitelist + setter after ground_root()
    s = s.replace(
        "def ground_root() -> str:\n    return _GROUND_ROOT\n",
        "def ground_root() -> str:\n    return _GROUND_ROOT\n\n\n"
        "_CMD_WHITELIST: set[str] = set()\n\n\n"
        "def set_command_whitelist(cmds) -> None:\n"
        "    global _CMD_WHITELIST\n"
        "    _CMD_WHITELIST = set(cmds)\n")
    # reverify branch before the trailing fail-closed return
    s = s.replace(
        "        # operator / test_result / oracle_score / exit_code: fail closed until wired\n        return False",
        "        if self.kind == \"command_output\":\n"
        "            if not self.source or self.source not in _CMD_WHITELIST:\n"
        "                return False\n"
        "            try:\n"
        "                p = subprocess.run(self.source, shell=True, capture_output=True, timeout=15)\n"
        "            except Exception:\n"
        "                return False\n"
        "            if p.returncode != 0:\n"
        "                return False\n"
        "            return (\"sha256:\" + hashlib.sha256(p.stdout).hexdigest()) == self.value\n"
        "        # operator / test_result / oracle_score / exit_code: fail closed until wired\n        return False")
    open(sp, "w").write(s)

    tp = os.path.join(repo, "tests", "test_measurement_kinds.py")
    open(tp, "w").write(
        'import hashlib, os, subprocess, sys, tempfile\n'
        'from plateau import signal as sig\n'
        'from plateau import continuum as cont\n\n'
        'def _cmd(path):\n'
        '    return f\'{sys.executable} -c "import sys;sys.stdout.write(open(r\\\'{path}\\\').read())"\'\n\n'
        'def _val(cmd):\n'
        '    p = subprocess.run(cmd, shell=True, capture_output=True)\n'
        '    return "sha256:" + hashlib.sha256(p.stdout).hexdigest()\n\n'
        'def test_command_output_reverifies_then_goes_stale(tmp_path):\n'
        '    t = tmp_path / "o.txt"; t.write_text("A\\n")\n'
        '    cmd = _cmd(str(t)); sig.set_command_whitelist([cmd])\n'
        '    m = sig.Measurement(kind="command_output", source=cmd, value=_val(cmd))\n'
        '    assert m.reverify() is True\n'
        '    t.write_text("B-different\\n")\n'
        '    assert m.reverify() is False\n\n'
        'def test_gate_admits_only_while_live(tmp_path):\n'
        '    t = tmp_path / "o.txt"; t.write_text("X\\n")\n'
        '    cmd = _cmd(str(t)); sig.set_command_whitelist([cmd])\n'
        '    m = sig.Measurement(kind="command_output", source=cmd, value=_val(cmd))\n'
        '    assert len(sig.gate([sig.Thought("f", m)]).admitted) == 1\n'
        '    t.write_text("Y\\n")\n'
        '    g = sig.gate([sig.Thought("f", m)])\n'
        '    assert g.admitted == [] and len(g.dropped) == 1\n\n'
        'def test_non_whitelisted_fails_closed(tmp_path):\n'
        '    t = tmp_path / "o.txt"; t.write_text("Z\\n")\n'
        '    cmd = _cmd(str(t)); sig.set_command_whitelist([])\n'
        '    m = sig.Measurement(kind="command_output", source=cmd, value=_val(cmd))\n'
        '    assert m.reverify() is False\n')


def proof_B():
    print("PROOF B — objective-check on known-good and baseline:")
    base = tempfile.mkdtemp(prefix="demo4_base_")
    good = tempfile.mkdtemp(prefix="demo4_good_")
    try:
        H.make_arm_repo(base)
        H.make_arm_repo(good)
        apply_reference_impl(good)
        cb = H.run_objective_check(base)
        check("baseline FAILS check", cb["ok"] is False, f"ok={cb['ok']} {cb.get('probe_reason')}")
        check("baseline has 26 tests", cb["passed"] == 26, f"passed={cb['passed']}")
        cg = H.run_objective_check(good)
        check("reference-good PASSES check", cg["ok"] is True,
              f"ok={cg['ok']} passed={cg['passed']} probe={cg.get('probe_reason')}")
        check("reference-good >=28 tests", cg["passed"] >= 28, f"passed={cg['passed']}")
    finally:
        shutil.rmtree(base, ignore_errors=True)
        shutil.rmtree(good, ignore_errors=True)


def proof_C():
    print("PROOF C — seal/recompute round-trip (synthetic):")
    from plateau.integrity import Manifest, seal
    d = tempfile.mkdtemp(prefix="demo4_seal_")
    try:
        records = {
            "arm1_fullhistory": _arm([_step(1, 1000, 26), _step(2, 5000, 28)]),
            "arm2_efficiency": _arm([_step(1, 1200, 27), _step(2, 1250, 28)]),
            "arm3_autonomy": _arm([_step(1, 1300, 28)]),
        }
        mpath = os.path.join(d, "manifest.jsonl")
        m = Manifest(mpath)
        for arm, rec in records.items():
            fp = os.path.join(d, f"{arm}_completion.json")
            open(fp, "w").write(json.dumps(rec, sort_keys=True))
            seal(fp, m, d, kind="completion", ts=0.0)
        # sealed files are read-only
        ro = all(not (os.stat(os.path.join(d, f"{a}_completion.json")).st_mode & 0o222)
                 for a in records)
        check("sealed files read-only", ro)
        c_ok, _ = m.verify_chain()
        f_ok, _ = m.verify_files(d)
        check("manifest chain verifies", c_ok)
        check("sealed files verify", f_ok)
        # re-load from sealed bytes and score
        reloaded = {a: json.loads(open(os.path.join(d, f"{a}_completion.json")).read())
                    for a in records}
        v1 = H.score(records)
        v2 = H.score(reloaded)
        check("score reproduces from sealed bytes",
              json.dumps(v1, sort_keys=True) == json.dumps(v2, sort_keys=True))
    finally:
        for f in os.listdir(d):
            os.chmod(os.path.join(d, f), 0o644)
        shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    proof_A()
    proof_B()
    proof_C()
    print()
    if FAILS:
        print(f"MOCK-PLUMB: FAIL ({len(FAILS)}): {FAILS}")
        sys.exit(1)
    print("MOCK-PLUMB: PASS — all verdict branches fire; check PASS/FAIL correct; seal round-trips")
