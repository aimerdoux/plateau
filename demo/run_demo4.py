#!/usr/bin/env python3
"""demo4 real-run driver — CLI mechanics the orchestrator calls between paid dispatches.

Bounded-orchestrator design: arm1's full-history transcript is assembled by `prep`
(reading prior on-disk prompt/reply files) and written to a prompt FILE. The coding
subagent reads that file itself; the orchestrator never ingests the growing transcript.

Subcommands (all print one JSON line):
  setup                         make 3 pristine arm repos + staging, init signals
  prep   <arm> <k>              assemble + write step prompt; -> {tokens, prompt_path, reply_path}
  record <arm> <k>              run objective check; fold reply into bounded signal (arm2/3)
  build_completions             assemble per-arm completion.json from per-step files

Staging (pre-seal, plain files) lives in demo/raw4/ ; arm repos live in a scratch base.
"""
from __future__ import annotations

import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness4 as H  # noqa: E402
sys.path.insert(0, H.REPO)
from plateau.signal import RelationalState, SelfState, Measurement  # noqa: E402
from plateau.continuum import emit  # noqa: E402
from plateau.integrity import file_hash  # noqa: E402

RAW = os.path.join(H.REPO, "demo", "raw4")
ARM_BASE = os.path.join(os.path.dirname(H.REPO), "demo4_arms")  # scratch, OUTSIDE plateau git
ARM_DIR = {a: os.path.join(ARM_BASE, a) for a in H.ARMS}
LESS_CAP = 15  # bounded signal: keep at most this many lessons (the bound that must hold)


def _sigpath(arm):
    return os.path.join(RAW, f"{arm}_signal.json")


def _fplanpath(arm):
    return os.path.join(RAW, f"{arm}_fplan.txt")


def _load_sig(arm) -> dict:
    return json.load(open(_sigpath(arm)))


def _save_sig(arm, sig):
    json.dump(sig, open(_sigpath(arm), "w"), indent=0, sort_keys=True)


def _emit_blob(arm) -> str:
    s = _load_sig(arm)
    rs = RelationalState(open_goals=s["open_goals"], stance=s["stance"],
                         lessons=s["lessons"], pointers=s["pointers"],
                         verified_facts=s["verified_facts"])
    return emit(SelfState(signal=rs))


# ---------------------------------------------------------------- setup
def setup():
    os.makedirs(RAW, exist_ok=True)
    os.makedirs(ARM_BASE, exist_ok=True)
    goals = ["1 signal.py: command_output reverify branch (whitelist, sha256 stdout, fail-closed)",
             "2 continuum.py: carry kind losslessly (verify + guard)",
             "3 tests/test_measurement_kinds.py: >=2 tests live-admit + stale-drop",
             "4 README.md + adapters/claude_code/SKILL.md: document kind + pending-facts example"]
    stance = ("implement command_output end-to-end; value='sha256:'+sha256(raw stdout); "
              "fail closed on nonzero-exit/non-whitelisted/missing; keep existing 26 tests green")
    for a in H.ARMS:
        H.make_arm_repo(ARM_DIR[a])
        json.dump({"open_goals": goals, "stance": stance, "lessons": [], "pointers": [],
                   "verified_facts": []}, open(_sigpath(a), "w"), indent=0, sort_keys=True)
        open(_fplanpath(a), "w").write("(no forward-plan yet — step 1)")
    print(json.dumps({"ok": True, "arms": ARM_DIR, "raw": RAW,
                      "baseline_tests": H.SUCCESS_MIN_TESTS - 2}))


# ---------------------------------------------------------------- prep
def prep(arm, k):
    k = int(k)
    prompt_path = os.path.join(RAW, f"{arm}_step{k}_prompt.txt")
    reply_path = os.path.join(RAW, f"{arm}_step{k}_reply.md")
    prior_prompts, prior_replies = [], []
    if arm == "arm1_fullhistory":
        for i in range(1, k):
            pp = os.path.join(RAW, f"{arm}_step{i}_prompt.txt")
            rp = os.path.join(RAW, f"{arm}_step{i}_reply.md")
            prior_prompts.append(open(pp).read() if os.path.exists(pp) else "")
            prior_replies.append(open(rp).read() if os.path.exists(rp) else "")
        prompt = H.assemble_prompt(arm, k, prior_prompts, prior_replies, "")
    else:
        blob = _emit_blob(arm)
        fplan = open(_fplanpath(arm)).read() if arm == "arm3_autonomy" else ""
        prompt = H.assemble_prompt(arm, k, [], [], blob, forward_plan=fplan)
    open(prompt_path, "w").write(prompt)
    print(json.dumps({"tokens": H.tok(prompt), "prompt_path": prompt_path,
                      "reply_path": reply_path, "arm_repo": ARM_DIR[arm]}))


# ---------------------------------------------------------------- record
def _parse_section(text, name):
    m = re.search(rf"{name}:(.*?)(?:\n[A-Z_]+:|\Z)", text, flags=re.S)
    return m.group(1).strip() if m else ""


def _bullets(block):
    out = []
    for ln in block.splitlines():
        ln = ln.strip().lstrip("-*0123456789. ").strip()
        if ln:
            out.append(ln[:200])
    return out


def record(arm, k):
    k = int(k)
    repo = ARM_DIR[arm]
    chk = H.run_objective_check(repo)
    json.dump(chk, open(os.path.join(RAW, f"{arm}_step{k}_check.json"), "w"),
              indent=0, sort_keys=True)

    # fold the agent's reply into the BOUNDED signal (arm2/arm3 only); arm1 carries the
    # whole transcript already (nothing to compress).
    if arm != "arm1_fullhistory":
        rp = os.path.join(RAW, f"{arm}_step{k}_reply.md")
        reply = open(rp).read() if os.path.exists(rp) else ""
        sig = _load_sig(arm)
        carry = _bullets(_parse_section(reply, "CARRY"))
        for c in carry:
            if c not in sig["lessons"]:
                sig["lessons"].append(c)
        sig["lessons"] = sig["lessons"][-LESS_CAP:]  # the bound
        # ground a fact on each touched core file (re-grounds every step)
        sig["verified_facts"] = []
        for rel in ("plateau/signal.py", "plateau/continuum.py",
                    "tests/test_measurement_kinds.py"):
            fp = os.path.join(repo, rel)
            if os.path.isfile(fp):
                sig["verified_facts"].append(
                    {"claim": f"{rel} present", "grounding_kind": "file_hash",
                     "grounding_source": fp, "grounding_value": file_hash(fp)})
        sig["pointers"] = [f"arm_repo:{repo}", f"last_reply:{rp}"]
        _save_sig(arm, sig)
        if arm == "arm3_autonomy":
            fplan = _parse_section(reply, "FORWARD_PLAN") or "(agent produced no forward-plan)"
            open(_fplanpath(arm), "w").write(fplan[:4000])

    print(json.dumps({"arm": arm, "step": k, "ok": chk["ok"], "passed": chk["passed"],
                      "failed": chk["failed"], "errors": chk["errors"], "exit": chk["exit"],
                      "probe_ok": chk["probe_ok"], "probe_reason": chk["probe_reason"][:120]}))


# ---------------------------------------------------------------- build completions
def build_completions():
    out = {}
    for a in H.ARMS:
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
        json.dump(comp, open(os.path.join(RAW, f"{a}_completion.json"), "w"),
                  indent=0, sort_keys=True)
        out[a] = {"steps": len(steps), "completion": summ["completion"],
                  "steps_to_done": summ["steps_to_done"], "errors": summ["errors"]}
    print(json.dumps({"ok": True, "summary": out}))


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "setup":
        setup()
    elif cmd == "prep":
        prep(sys.argv[2], sys.argv[3])
    elif cmd == "record":
        record(sys.argv[2], sys.argv[3])
    elif cmd == "build_completions":
        build_completions()
    else:
        print(json.dumps({"error": f"unknown cmd {cmd}"}))
        sys.exit(2)
