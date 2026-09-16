#!/usr/bin/env python3
"""Offline self-test of the D-038 instrument. No Claude tokens. Assembles a worktree from the real target (--target),
simulates a worker that does every task correctly (arm A) and one that plants a wrong name in task 7 (arm B), runs the
gate after every simulated task, fakes a transcript with compactions inside tasks 5, 10 and 15, and checks that score.py
recovers R = 1 (or the planted miss), the S/NS split, the nonce rate and the citations. Exits 0 with SKIP if --target is
absent (CI has no checkout of the private repo)."""
import argparse, json, os, re, shutil, subprocess, sys
HERE = os.path.dirname(os.path.abspath(__file__)); T = "concierge-agent"
NAME = lambda kind, k: {"constant": f"SIM_LIMIT_{k}", "function": f"simHandler{k}", "module": f"sim{k}"}[kind]

def sim_task(work, t, wrong=False):
    td = os.path.join(work, T); k = t["k"]; kind = t["kind"]; f = t["file"]; calls = []
    fx = open(os.path.join(td, f"FIXTURE_{k}.md")).read(); calls.append(("Read", f"{td}/FIXTURE_{k}.md"))
    open(os.path.join(td, f"nonce_{k}.txt"), "w").write(re.search(r"NONCE-[0-9a-f]{8}", fx).group(0) + "\n")
    name = NAME(kind, k)
    if kind == "module": open(os.path.join(td, f"{name}-util.mjs"), "w").write("export function ping() { return 'pong'; }\n")
    calls.append(("Read", f"{td}/{f}"))
    with open(os.path.join(td, f), "a") as fh:
        if kind == "constant": fh.write(f"\nexport const {name} = {k};\n")
        if kind == "function": fh.write(f"\nexport function {name}() {{ return 7; }}\n")
        fh.write("".join(f"export function h{k}_{s}() {{ return 'h{k}_{s}'; }}\n" for s in ("alpha", "beta", "gamma")))
    if t["dep"]:
        d = t["dep"]; dn = NAME(d["kind"], d["k"]) + ("X" if wrong else "")
        if d["kind"] == "module": code = f"\nimport {{ ping as ping_{k} }} from './{dn}-util.mjs';\nexport function link_{k}() {{ return ping_{k}(); }}\n"
        elif d["kind"] == "constant": code = f"\nimport {{ {dn} }} from './{d['file']}';\nexport function link_{k}() {{ return {dn}; }}\n"
        else: code = f"\nimport {{ {dn} }} from './{d['file']}';\nexport function link_{k}() {{ return {dn}(); }}\n"
        with open(os.path.join(td, t["use_file"]), "a") as fh: fh.write(code)
        calls.append(("Edit", f"{td}/{t['use_file']}", f"link_{k}"))
    calls.append(("Bash", "bash gate.sh"))
    return calls

def fake_transcript(path, tasks, per_task_calls, compact_in):
    n = 0
    with open(path, "w") as fh:
        for t, calls in zip(tasks, per_task_calls):
            fh.write(json.dumps({"type": "user", "message": {"role": "user", "content": [{"type": "text", "text": t["prompt"]}]}}) + "\n")
            for i, c in enumerate(calls):
                if t["k"] in compact_in and i == 1:            # boundary lands after the fixture read, before the edit
                    fh.write(json.dumps({"type": "system", "subtype": "compact_boundary"}) + "\n")
                tin = {"file_path": c[1]} if c[0] in ("Read",) else ({"file_path": c[1], "old_string": "x", "new_string": f"export function {c[2]}()"} if c[0] == "Edit" else {"command": c[1]})
                n += 1
                fh.write(json.dumps({"type": "assistant", "message": {"id": f"msg_{n}", "role": "assistant", "usage": {"input_tokens": 100, "cache_read_input_tokens": 40000, "output_tokens": 200},
                                     "content": [{"type": "tool_use", "id": f"toolu_{n}", "name": c[0], "input": tin}]}}) + "\n")
                fh.write(json.dumps({"type": "user", "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": f"toolu_{n}", "content": "ok"}]}}) + "\n")

def build_run(out, arm, target, wrong_k=None):
    rd = os.path.join(out, "raw", arm, "1")
    subprocess.check_call([sys.executable, os.path.join(HERE, "run_arm.py"), "--arm", arm, "--run", "1", "--seed", "1", "--n", "18",
                           "--fixture-words", "300", "--target", target, "--out", rd, "--dry-run"], stdout=subprocess.DEVNULL)
    work = os.path.join(rd, "work"); tasks = json.load(open(os.path.join(work, "tasks.json")))["tasks"]
    shutil.copytree(os.path.join(work, T), os.path.join(rd, "snap", "0")); per = []
    for t in tasks:
        per.append(sim_task(work, t, wrong=(t["k"] == wrong_k)))
        g = subprocess.run(["bash", "gate.sh"], cwd=work, capture_output=True, text=True)
        assert g.returncode == 0, f"gate failed after simulated task {t['k']} ({arm}):\n{g.stdout}{g.stderr}"
        shutil.copytree(os.path.join(work, T), os.path.join(rd, "snap", str(t["k"])))
    os.makedirs(os.path.join(rd, "transcript")); fake_transcript(os.path.join(rd, "transcript", f"sim-{arm}.jsonl"), tasks, per, {5, 10, 15})
    man = json.load(open(os.path.join(rd, "manifest.json"))); man["status"] = "OK"
    man["tasks"] = [{"k": t["k"], "rc": 0, "cost": 0.1} for t in tasks]
    json.dump(man, open(os.path.join(rd, "manifest.json"), "w"), indent=1)
    if arm == "B": open(os.path.join(rd, "hooks.log"), "w").write("1.0 inject ev=SessionStart q=0ch nodes=5/9 chars=1400 budget=1500\n" * 3)
    return rd

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--target"); ap.add_argument("--out", default=os.path.join(HERE, "selftest_out")); a = ap.parse_args()
    if not a.target or not os.path.isdir(a.target): print("SKIP: --target (the private subtree) not available"); return
    shutil.rmtree(a.out, ignore_errors=True); os.makedirs(a.out)
    build_run(a.out, "A", a.target); build_run(a.out, "B", a.target, wrong_k=7)
    res_p = os.path.join(a.out, "results.json")
    subprocess.check_call([sys.executable, os.path.join(HERE, "score.py"), "--raw", os.path.join(a.out, "raw"), "--out", res_p], stdout=subprocess.DEVNULL)
    res = json.load(open(res_p)); A = res["runs"]["A"]["1"]; B = res["runs"]["B"]["1"]
    for X in (A, B):
        assert X["n_compactions"] == 3 and [c["task"] for c in X["compactions"]] == [5, 10, 15], X["compactions"]
        assert X["S_tasks"] == [6, 7, 8, 11, 12, 13, 16, 17, 18] and X["NS_tasks"] == [4, 5, 9, 10, 14, 15], (X["S_tasks"], X["NS_tasks"])
        assert X["nonce_rate"] == 1.0 and not X["confounded"], (X["nonce_rate"], X["confounded"])
        assert all(i["prompt_line"] for i in X["items"]) and all(i.get("link_edit_line") for i in X["items"] if "used" in i)
        assert all(len(i["facts"]) == 1 for i in X["items"] if "used" in i), [i["facts"] for i in X["items"] if "used" in i]
    assert A["R_S"] == [1.0, 9] and A["R_NS"] == [1.0, 6], (A["R_S"], A["R_NS"])
    assert B["R_S"] == [8 / 9, 9] and B["R_NS"] == [1.0, 6], (B["R_S"], B["R_NS"])
    miss = [i for i in B["items"] if i.get("used") is False]; assert [i["k"] for i in miss] == [7], miss
    assert A["dep_rereads"] == 0 and A["rederivations"] > 0                      # sim re-reads its own file after each boundary
    assert B["inject_events"] == 3 and not B["inject_over_budget"]
    row = res["table"][0]; assert row["scored"] and row["alpha"] == 1.0 and row["lam"] == 0.0 and row["pi_B"] is None, row
    assert res["verdicts"] == {"B1": "LOSS", "B2": "LOSS", "B3": "LOSS", "B4": "UNSCORED"} or res["verdicts"]["B1"] == "LOSS", res["verdicts"]
    kinds = {i["k"]: i["facts"][0] for i in A["items"] if "used" in i}
    print(json.dumps({"A": {k: A[k] for k in ("R_S", "R_NS", "S_tasks", "NS_tasks", "nonce_rate", "rederivations")},
                      "B": {k: B[k] for k in ("R_S", "R_NS", "inject_events")}, "planted_miss": [i["why"] for i in miss],
                      "facts_by_task": kinds, "verdicts": res["verdicts"]}, indent=1))
    print("ALL CHECKS PASSED (offline; no tokens)")

if __name__ == "__main__": main()
