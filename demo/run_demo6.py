#!/usr/bin/env python3
"""demo6 driver — 2-arm (full-history vs plateau-efficiency) over a strictly serial
>=5-layer feature. Reuses harness4 for tok/make_arm_repo and (at scoring) score().
Only the TASK and its probe/threshold differ from demo4 — the rule is unchanged.

Subcommands print one JSON line: setup | prep <arm> <k> | record <arm> <k> | build_completions
"""
from __future__ import annotations

import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness4 as H  # noqa: E402  (REUSED byte-for-byte)
sys.path.insert(0, H.REPO)
from plateau.signal import RelationalState, SelfState  # noqa: E402
from plateau.continuum import emit  # noqa: E402
from plateau.integrity import file_hash  # noqa: E402

ARMS6 = ("arm1_fullhistory", "arm2_efficiency")
SUCCESS_MIN_TESTS6 = 32  # 26 baseline + >=6 new (locked in demo6_prereg.md)
RAW = os.environ.get("DEMO6_RAW") or os.path.join(H.REPO, "demo", "raw6")
ARM_BASE = os.environ.get("DEMO6_ARM_BASE") or os.path.join(os.path.dirname(H.REPO), "demo6_arms")
ARM_DIR = {a: os.path.join(ARM_BASE, a) for a in ARMS6}
LESS_CAP = 15

TASK_SPEC6 = (
    "TASK (identical for both arms): build a STRICTLY SERIAL 'verification chain' feature "
    "in the plateau package. Each layer depends on the prior; the success check passes "
    "only when ALL layers work.\n"
    "L1 plateau/signal.py: add Measurement kind 'command_output' — whitelisted command, "
    "value='sha256:'+sha256(raw stdout), fail CLOSED on nonzero-exit/non-whitelisted/"
    "missing; whitelist API set_command_whitelist(list)/_CMD_WHITELIST.\n"
    "L2 plateau/signal.py: add composite kind 'all_of' — source is a JSON list of child "
    "specs {kind,source,value}; reverify() True iff EVERY child reverifies; fail closed on "
    "empty/malformed/unknown-child kind.\n"
    "L3 plateau/continuum.py: emit/inflate/ground carry 'all_of' losslessly (nested children "
    "intact); an all_of whose source won't parse is treated STALE (guard).\n"
    "L4 plateau/signal.py: ground_report(state)->dict that walks verified_facts; per fact "
    "{claim,kind,live,stale_children}; descends all_of and names failing child sources; "
    "aggregate {n_live,n_stale}.\n"
    "L5 plateau/report.py (new) + `python -m plateau.report <blob_file>`: inflate a signal "
    "blob, run ground_report, print JSON, exit 0 iff all live else 1.\n"
    "L6 tests/test_verification_chain.py (new, >=6 tests) covering each layer + gate admits "
    "an all_of only while every child live; plus one-paragraph docs in README.md + "
    "adapters/claude_code/SKILL.md (docs not required by the check).\n"
    "advance ONE coherent sub-task this step, then STOP; do not attempt the whole feature "
    "at once."
)

# ONE fixed introducer used by BOTH arms — carries NO arm-distinguishing token. The arm
# difference is ONLY the context payload appended after it (see assemble_prompt6).
CONTEXT_HEADER = "CONTEXT CARRIED INTO THIS STEP (read this, then do the sub-task above):\n"


def _sig(a):
    return os.path.join(RAW, f"{a}_signal.json")


def _emit_blob(a):
    s = json.load(open(_sig(a)))
    rs = RelationalState(open_goals=s["open_goals"], stance=s["stance"], lessons=s["lessons"],
                         pointers=s["pointers"], verified_facts=s["verified_facts"])
    return emit(SelfState(signal=rs))


def assemble_prompt6(arm, step, prior_prompts, prior_replies, signal_blob):
    """ISOLATION INVARIANT: the HEAD is byte-identical across both arms at the same step.
    head = f"[demo6 step={step}]\\n{TASK_SPEC6}\\n\\n{CONTEXT_HEADER}"  — no arm token.
    The ONLY per-arm difference is the trailing context payload appended after the head:
      arm1 = concatenated prior transcript (prompts+replies);
      arm2 = the bounded signal_blob.
    A diff of arm1 vs arm2 at the same step shows ONLY the payload bytes changed."""
    head = f"[demo6 step={step}]\n{TASK_SPEC6}\n\n{CONTEXT_HEADER}"
    if arm == "arm1_fullhistory":
        payload = ""
        for i, (p, r) in enumerate(zip(prior_prompts, prior_replies), 1):
            payload += f"\n--- prior step {i} PROMPT ---\n{p}\n--- prior step {i} REPLY ---\n{r}\n"
        return head + payload
    return head + signal_blob


def run_objective_check6(repo):
    pt = __import__("subprocess").run(
        ["bash", "-lc", f"cd {repo} && uv run --with pytest --with numpy pytest -q 2>&1"],
        capture_output=True, text=True)
    out = pt.stdout + pt.stderr
    passed = int(H._PYTEST_PASS.search(out).group(1)) if H._PYTEST_PASS.search(out) else 0
    failed = int(H._PYTEST_FAIL.search(out).group(1)) if H._PYTEST_FAIL.search(out) else 0
    errors = int(H._PYTEST_ERR.search(out).group(1)) if H._PYTEST_ERR.search(out) else 0
    probe = __import__("subprocess").run(
        ["bash", "-lc",
         f"PYTHONPATH={repo} python3 {H.REPO}/demo/probe_verification_chain.py {repo}"],
        capture_output=True, text=True)
    probe_ok, reason = False, "no probe json"
    for ln in probe.stdout.splitlines():
        ln = ln.strip()
        if ln.startswith("{"):
            try:
                j = json.loads(ln); probe_ok, reason = bool(j.get("probe_ok")), j.get("reason", "")
            except Exception:  # noqa: BLE001
                pass
    ok_pytest = (pt.returncode == 0 and passed >= SUCCESS_MIN_TESTS6 and failed == 0 and errors == 0)
    return {"exit": pt.returncode, "passed": passed, "failed": failed, "errors": errors,
            "n_tests": passed + failed + errors, "ok_pytest": ok_pytest, "probe_ok": probe_ok,
            "probe_reason": reason, "ok": bool(ok_pytest and probe_ok),
            "pytest_tail": "\n".join(out.splitlines()[-3:])}


def setup():
    os.makedirs(RAW, exist_ok=True)
    os.makedirs(ARM_BASE, exist_ok=True)
    goals = ["L1 signal.py command_output", "L2 signal.py all_of composite",
             "L3 continuum.py carry all_of lossless", "L4 signal.py ground_report",
             "L5 plateau/report.py CLI", "L6 tests/test_verification_chain.py >=6 + docs"]
    stance = ("serial verification-chain; each layer depends on prior; value='sha256:'+sha256"
              "(stdout); all_of reverifies iff all children live; fail closed; keep 26 tests green")
    for a in ARMS6:
        H.make_arm_repo(ARM_DIR[a])
        json.dump({"open_goals": goals, "stance": stance, "lessons": [], "pointers": [],
                   "verified_facts": []}, open(_sig(a), "w"), indent=0, sort_keys=True)
    print(json.dumps({"ok": True, "arms": ARM_DIR, "raw": RAW, "threshold": SUCCESS_MIN_TESTS6}))


def prep(arm, k):
    k = int(k)
    pp = os.path.join(RAW, f"{arm}_step{k}_prompt.txt")
    rp = os.path.join(RAW, f"{arm}_step{k}_reply.md")
    pri_p, pri_r = [], []
    if arm == "arm1_fullhistory":
        for i in range(1, k):
            a = os.path.join(RAW, f"{arm}_step{i}_prompt.txt")
            b = os.path.join(RAW, f"{arm}_step{i}_reply.md")
            pri_p.append(open(a).read() if os.path.exists(a) else "")
            pri_r.append(open(b).read() if os.path.exists(b) else "")
        prompt = assemble_prompt6(arm, k, pri_p, pri_r, "")
    else:
        prompt = assemble_prompt6(arm, k, [], [], _emit_blob(arm))
    open(pp, "w").write(prompt)
    print(json.dumps({"tokens": H.tok(prompt), "prompt_path": pp, "reply_path": rp,
                      "arm_repo": ARM_DIR[arm]}))


def _section(t, name):
    m = re.search(rf"{name}:(.*?)(?:\n[A-Z_]+:|\Z)", t, flags=re.S)
    return m.group(1).strip() if m else ""


def record(arm, k):
    k = int(k)
    repo = ARM_DIR[arm]
    chk = run_objective_check6(repo)
    json.dump(chk, open(os.path.join(RAW, f"{arm}_step{k}_check.json"), "w"), indent=0, sort_keys=True)
    if arm != "arm1_fullhistory":
        reply = open(os.path.join(RAW, f"{arm}_step{k}_reply.md")).read() if os.path.exists(
            os.path.join(RAW, f"{arm}_step{k}_reply.md")) else ""
        s = json.load(open(_sig(arm)))
        for c in [x.strip().lstrip("-*0123456789. ").strip()[:200]
                  for x in _section(reply, "CARRY").splitlines() if x.strip()]:
            if c and c not in s["lessons"]:
                s["lessons"].append(c)
        s["lessons"] = s["lessons"][-LESS_CAP:]
        s["verified_facts"] = []
        for rel in ("plateau/signal.py", "plateau/continuum.py", "plateau/report.py",
                    "tests/test_verification_chain.py"):
            fp = os.path.join(repo, rel)
            if os.path.isfile(fp):
                s["verified_facts"].append({"claim": f"{rel} present", "grounding_kind": "file_hash",
                                            "grounding_source": fp, "grounding_value": file_hash(fp)})
        s["pointers"] = [f"arm_repo:{repo}"]
        json.dump(s, open(_sig(arm), "w"), indent=0, sort_keys=True)
    print(json.dumps({"arm": arm, "step": k, "ok": chk["ok"], "passed": chk["passed"],
                      "failed": chk["failed"], "errors": chk["errors"], "exit": chk["exit"],
                      "probe_ok": chk["probe_ok"], "probe_reason": chk["probe_reason"][:130]}))


def build_completions():
    out = {}
    for a in ARMS6:
        steps = []
        k = 1
        while os.path.exists(os.path.join(RAW, f"{a}_step{k}_check.json")):
            chk = json.load(open(os.path.join(RAW, f"{a}_step{k}_check.json")))
            ptxt = open(os.path.join(RAW, f"{a}_step{k}_prompt.txt")).read()
            steps.append({"step": k, "context_tokens": H.tok(ptxt), "check": chk})
            k += 1
        summ = H._arm_summary({a: {"steps": steps}}, a)
        comp = {"arm": a, "steps": steps, "completion": summ["completion"],
                "steps_to_done": summ["steps_to_done"], "errors": summ["errors"],
                "context": summ["context"], "slope": summ["slope"]}
        json.dump(comp, open(os.path.join(RAW, f"{a}_completion.json"), "w"), indent=0, sort_keys=True)
        out[a] = {"steps": len(steps), "completion": summ["completion"],
                  "steps_to_done": summ["steps_to_done"], "errors": summ["errors"], "slope": summ["slope"]}
    print(json.dumps({"ok": True, "summary": out}))


if __name__ == "__main__":
    c = sys.argv[1]
    {"setup": lambda: setup(),
     "prep": lambda: prep(sys.argv[2], sys.argv[3]),
     "record": lambda: record(sys.argv[2], sys.argv[3]),
     "build_completions": lambda: build_completions()}.get(c, lambda: print(json.dumps({"error": c})))()
