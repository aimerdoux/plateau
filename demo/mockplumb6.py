#!/usr/bin/env python3
"""demo6 MOCK-PLUMB — prove the harness free before any paid dispatch.
A) efficiency branches fire via the REUSED harness4.score (dummy arm3:=arm2);
B) objective check PASSes a reference 6-layer impl, FAILs baseline;
C) seal/recompute round-trip.
The reference impl is THROWAWAY plumbing, NOT used as any arm's result.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness4 as H  # noqa: E402
import run_demo6 as R  # noqa: E402
sys.path.insert(0, H.REPO)

FAILS = []


def ck(name, cond, d=""):
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" — {d}" if d and not cond else ""))
    if not cond:
        FAILS.append(name)


def _step(step, ctx, passed, *, failed=0, errors=0, probe_ok=True, broken=False):
    exit_ = 1 if (broken or failed or errors) else 0
    ok = (exit_ == 0 and passed >= R.SUCCESS_MIN_TESTS6 and failed == 0 and errors == 0 and probe_ok)
    return {"step": step, "context_tokens": ctx,
            "check": {"exit": exit_, "passed": passed, "failed": failed, "errors": errors,
                      "n_tests": passed, "ok_pytest": ok, "probe_ok": probe_ok, "ok": ok}}


def _eff(a1, a2):
    """Score efficiency the demo6 way: reuse harness4.score with a VALID dummy arm3:=arm2
    (deepcopy, the pre-registered construction) so the 3-arm scorer doesn't KeyError. We
    read ONLY the efficiency field."""
    import copy
    rec = {"arm1_fullhistory": {"steps": a1}, "arm2_efficiency": {"steps": a2}}
    rec["arm3_autonomy"] = copy.deepcopy(rec["arm2_efficiency"])
    return H.score(rec)["efficiency"]["verdict"]


def proof_A():
    print("PROOF A — efficiency branches via REUSED harness4.score (dummy arm3):")
    climb = [_step(1, 1000, 26), _step(2, 3000, 28), _step(3, 6000, 30),
             _step(4, 9000, 31), _step(5, 13000, 32)]
    flat_pass = [_step(1, 1200, 28), _step(2, 1260, 30), _step(3, 1290, 31),
                 _step(4, 1300, 31), _step(5, 1320, 32)]
    ck("WIN", _eff(climb, flat_pass) == "WIN", _eff(climb, flat_pass))
    flat_fail = [_step(1, 1200, 28), _step(2, 1260, 30), _step(3, 1290, 31)]
    ck("PARTIAL_FORGETS", _eff(climb, flat_fail) == "PARTIAL_FORGETS", _eff(climb, flat_fail))
    ck("NULL", _eff(climb, climb) == "NULL", _eff(climb, climb))
    ck("UNSCORABLE (arm1 flat)", _eff(flat_pass, flat_pass) == "UNSCORABLE", _eff(flat_pass, flat_pass))

    # ISOLATION INVARIANT: prompt HEAD byte-identical across arms; ONLY the trailing
    # context payload differs. Build both arms at the same step and assert the shared
    # head prefix is byte-for-byte equal and carries no arm token.
    head = f"[demo6 step=3]\n{R.TASK_SPEC6}\n\n{R.CONTEXT_HEADER}"
    p1 = R.assemble_prompt6("arm1_fullhistory", 3, ["pp"], ["rr"], "BLOB")
    p2 = R.assemble_prompt6("arm2_efficiency", 3, [], [], "BLOB")
    ck("prompt head byte-identical across arms",
       p1.startswith(head) and p2.startswith(head), "head prefix differs")
    ck("no arm token in either prompt head",
       "arm1" not in head and "arm2" not in head and "arm=" not in head, "arm token leaked into head")
    ck("only the context payload differs between arms",
       p1[len(head):] != p2[len(head):] and p1[:len(head)] == p2[:len(head)],
       "difference is not confined to the payload")
    ck("per-step instruction is the pre-registered string (verbatim)",
       "advance ONE coherent sub-task this step, then STOP; do not attempt the whole "
       "feature at once." in R.TASK_SPEC6, "per-step instruction was reworded")


def apply_reference_impl6(repo):
    """Minimal correct L1-L5 + >=6 tests. ONLY to prove the check's PASS branch."""
    sp = os.path.join(repo, "plateau", "signal.py")
    s = open(sp).read()
    s = s.replace("import os\n", "import hashlib\nimport json\nimport os\nimport subprocess\n", 1)
    s = s.replace(
        'kind: Literal["file_hash", "test_result", "oracle_score", "exit_code", "operator"]',
        'kind: Literal["file_hash", "test_result", "oracle_score", "exit_code", "operator", '
        '"command_output", "all_of"]')
    s = s.replace(
        "def ground_root() -> str:\n    return _GROUND_ROOT\n",
        "def ground_root() -> str:\n    return _GROUND_ROOT\n\n\n"
        "_CMD_WHITELIST: set = set()\n\n\n"
        "def set_command_whitelist(cmds) -> None:\n    global _CMD_WHITELIST\n"
        "    _CMD_WHITELIST = set(cmds)\n")
    s = s.replace(
        "        # operator / test_result / oracle_score / exit_code: fail closed until wired\n        return False",
        "        if self.kind == \"command_output\":\n"
        "            if not self.source or self.source not in _CMD_WHITELIST:\n                return False\n"
        "            try:\n                p = subprocess.run(self.source, shell=True, capture_output=True, timeout=15)\n"
        "            except Exception:\n                return False\n"
        "            if p.returncode != 0:\n                return False\n"
        "            return (\"sha256:\" + hashlib.sha256(p.stdout).hexdigest()) == self.value\n"
        "        if self.kind == \"all_of\":\n"
        "            try:\n                children = json.loads(self.source)\n"
        "            except Exception:\n                return False\n"
        "            if not isinstance(children, list) or not children:\n                return False\n"
        "            for ch in children:\n"
        "                if not isinstance(ch, dict):\n                    return False\n"
        "                m = Measurement(kind=ch.get(\"kind\", \"\"), source=ch.get(\"source\", \"\"), value=ch.get(\"value\", \"\"))\n"
        "                if not m.reverify():\n                    return False\n"
        "            return True\n"
        "        # operator / test_result / oracle_score / exit_code: fail closed until wired\n        return False")
    s += (
        "\n\ndef ground_report(state) -> dict:\n"
        "    \"\"\"Walk verified_facts, re-ground each; descend all_of and name stale children.\"\"\"\n"
        "    facts = []\n    n_live = 0\n    n_stale = 0\n"
        "    for vf in state.verified_facts:\n"
        "        kind = vf.get(\"grounding_kind\", \"file_hash\")\n"
        "        m = Measurement(kind=kind, source=vf.get(\"grounding_source\", \"\"), value=vf.get(\"grounding_value\", \"\"))\n"
        "        live = m.reverify()\n        stale_children = []\n"
        "        if kind == \"all_of\" and not live:\n"
        "            try:\n                for ch in json.loads(m.source):\n"
        "                    cm = Measurement(kind=ch.get(\"kind\", \"\"), source=ch.get(\"source\", \"\"), value=ch.get(\"value\", \"\"))\n"
        "                    if not cm.reverify():\n                        stale_children.append(ch.get(\"source\", \"\"))\n"
        "            except Exception:\n                stale_children = [\"<unparseable all_of source>\"]\n"
        "        facts.append({\"claim\": vf.get(\"claim\", \"\"), \"kind\": kind, \"live\": live, \"stale_children\": stale_children})\n"
        "        n_live += 1 if live else 0\n        n_stale += 0 if live else 1\n"
        "    return {\"n_live\": n_live, \"n_stale\": n_stale, \"facts\": facts}\n")
    open(sp, "w").write(s)

    rp = os.path.join(repo, "plateau", "report.py")
    open(rp, "w").write(
        "import json\nimport sys\nfrom .continuum import inflate\nfrom .signal import ground_report\n\n"
        "def main(argv=None):\n    argv = argv or sys.argv\n"
        "    state = inflate(open(argv[1]).read(), fresh=False).state\n"
        "    rep = ground_report(state)\n    print(json.dumps(rep))\n"
        "    return 0 if rep[\"n_stale\"] == 0 else 1\n\n"
        "if __name__ == \"__main__\":\n    sys.exit(main(sys.argv))\n")

    tp = os.path.join(repo, "tests", "test_verification_chain.py")
    open(tp, "w").write(
        'import hashlib, json, subprocess, sys\n'
        'from plateau import signal as sig\nfrom plateau import continuum as cont\n'
        'from plateau.integrity import file_hash\nfrom plateau import report\n\n'
        'def _cmd(p):\n    return f\'{sys.executable} -c "import sys;sys.stdout.write(open(r\\\'{p}\\\').read())"\'\n\n'
        'def _cv(c):\n    p=subprocess.run(c,shell=True,capture_output=True);return "sha256:"+hashlib.sha256(p.stdout).hexdigest()\n\n'
        'def _comp(tmp):\n'
        '    t=tmp/"o.txt";t.write_text("A\\n");f=tmp/"f.txt";f.write_text("F\\n")\n'
        '    c=_cmd(str(t));sig.set_command_whitelist([c])\n'
        '    src=json.dumps([{"kind":"command_output","source":c,"value":_cv(c)},{"kind":"file_hash","source":str(f),"value":file_hash(str(f))}])\n'
        '    return t,c,src\n\n'
        'def test_l1_command_output(tmp_path):\n'
        '    t=tmp_path/"o.txt";t.write_text("A\\n");c=_cmd(str(t));sig.set_command_whitelist([c])\n'
        '    m=sig.Measurement(kind="command_output",source=c,value=_cv(c));assert m.reverify()\n'
        '    t.write_text("B\\n");assert not m.reverify()\n\n'
        'def test_l2_all_of_all_live(tmp_path):\n'
        '    _,_,src=_comp(tmp_path);assert sig.Measurement(kind="all_of",source=src,value="").reverify()\n\n'
        'def test_l2_all_of_stale_propagates(tmp_path):\n'
        '    t,_,src=_comp(tmp_path);m=sig.Measurement(kind="all_of",source=src,value="")\n'
        '    assert m.reverify();t.write_text("Z\\n");assert not m.reverify()\n\n'
        'def test_l3_continuum_carries_all_of(tmp_path):\n'
        '    _,_,src=_comp(tmp_path)\n'
        '    st=sig.SelfState(signal=sig.RelationalState(verified_facts=[{"claim":"ch","grounding_kind":"all_of","grounding_source":src,"grounding_value":""}]))\n'
        '    inf=cont.inflate(cont.emit(st),fresh=True);assert not inf.stale and len(inf.state.verified_facts)==1\n\n'
        'def test_l4_ground_report(tmp_path):\n'
        '    t,c,src=_comp(tmp_path)\n'
        '    rs=sig.RelationalState(verified_facts=[{"claim":"ch","grounding_kind":"all_of","grounding_source":src,"grounding_value":""}])\n'
        '    assert sig.ground_report(rs)["n_stale"]==0\n'
        '    t.write_text("Z\\n");r=sig.ground_report(rs);assert r["n_stale"]==1 and c in r["facts"][0]["stale_children"]\n\n'
        'def test_l5_report_cli_exit(tmp_path):\n'
        '    t,_,src=_comp(tmp_path)\n'
        '    st=sig.SelfState(signal=sig.RelationalState(verified_facts=[{"claim":"ch","grounding_kind":"all_of","grounding_source":src,"grounding_value":""}]))\n'
        '    bf=tmp_path/"b";bf.write_text(cont.emit(st));assert report.main(["report",str(bf)])==0\n'
        '    t.write_text("Z\\n");assert report.main(["report",str(bf)])==1\n\n'
        'def test_gate_admits_only_live_composite(tmp_path):\n'
        '    t,_,src=_comp(tmp_path);m=sig.Measurement(kind="all_of",source=src,value="")\n'
        '    assert len(sig.gate([sig.Thought("ch",m)]).admitted)==1\n'
        '    t.write_text("Z\\n");assert sig.gate([sig.Thought("ch",m)]).admitted==[]\n')


def proof_B():
    print("PROOF B — objective check on reference-good vs baseline:")
    base = tempfile.mkdtemp(prefix="d6_base_")
    good = tempfile.mkdtemp(prefix="d6_good_")
    try:
        H.make_arm_repo(base)
        H.make_arm_repo(good)
        apply_reference_impl6(good)
        cb = R.run_objective_check6(base)
        ck("baseline FAILS", cb["ok"] is False, f"ok={cb['ok']}")
        ck("baseline has 26 tests", cb["passed"] == 26, f"passed={cb['passed']}")
        cg = R.run_objective_check6(good)
        ck("reference-good PASSES", cg["ok"] is True,
           f"ok={cg['ok']} passed={cg['passed']} probe={cg.get('probe_reason')}")
        ck("reference-good >=32 tests", cg["passed"] >= 32, f"passed={cg['passed']}")
    finally:
        shutil.rmtree(base, ignore_errors=True)
        shutil.rmtree(good, ignore_errors=True)


def proof_C():
    print("PROOF C — seal/recompute round-trip (synthetic, root=seal dir):")
    from plateau.integrity import Manifest, seal
    d = tempfile.mkdtemp(prefix="d6_seal_")
    try:
        recs = {"arm1_fullhistory": {"steps": [_step(1, 1000, 26), _step(2, 5000, 32)]},
                "arm2_efficiency": {"steps": [_step(1, 1200, 30), _step(2, 1260, 32)]}}
        m = Manifest(os.path.join(d, "manifest.jsonl"))
        for a, r in recs.items():
            fp = os.path.join(d, f"{a}_completion.json")
            open(fp, "w").write(json.dumps(r, sort_keys=True))
            seal(fp, m, d, kind="completion", ts=0.0)
        ck("chain", m.verify_chain()[0])
        ck("files", m.verify_files(d)[0])
        rl = {a: {"steps": json.loads(open(os.path.join(d, f"{a}_completion.json")).read())["steps"]} for a in recs}
        v1 = _eff(recs["arm1_fullhistory"]["steps"], recs["arm2_efficiency"]["steps"])
        v2 = _eff(rl["arm1_fullhistory"]["steps"], rl["arm2_efficiency"]["steps"])
        ck("score reproduces from sealed", v1 == v2)
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
    print("MOCK-PLUMB: PASS")
    sys.exit(0)
