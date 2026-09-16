#!/usr/bin/env python3
"""D-037 driver: one arm, one run, one continuing `claude -p` session per chain. No scoring here.
Raw output under --out (refuses to overwrite). stdlib only."""
import argparse, hashlib, json, os, shutil, subprocess, sys, time, glob
HERE = os.path.dirname(os.path.abspath(__file__)); REPO = os.path.dirname(os.path.dirname(HERE))
HOOKS = os.path.join(REPO, "d037_hooks")
STRIP = ("CLAUDECODE", "CLAUDE_CODE_SESSION_ID", "CLAUDE_CODE_REMOTE_SESSION_ID", "CLAUDE_AUTOCOMPACT_PCT_OVERRIDE")

def sha(p): return hashlib.sha256(open(p, "rb").read()).hexdigest()

def install(arm, work, budget):
    if arm == "A": return {}
    hd = os.path.join(work, ".claude", "hooks", "d037"); os.makedirs(hd, exist_ok=True)
    for f in ("d037_common", "query", "receipt", "snapshot", "inject", "lookup", "ledger"):
        shutil.copy(os.path.join(HOOKS, f + ".py"), hd)
    src = {"B": "settings.arm_B.json", "C": "settings.arm_omega.json"}[arm]
    s = open(os.path.join(HOOKS, src)).read()
    # headline budget at compaction: explicit in the SessionStart(compact) command for both arms
    s = s.replace("D037_BUDGET_CHARS=6000 python3", f"D037_BUDGET_CHARS={budget} python3")
    s = s.replace('"command":"python3 $CLAUDE_PROJECT_DIR/.claude/hooks/d037/inject.py"',
                  f'"command":"D037_BUDGET_CHARS={budget} python3 $CLAUDE_PROJECT_DIR/.claude/hooks/d037/inject.py"')
    open(os.path.join(work, ".claude", "settings.json"), "w").write(s)
    if arm == "C": shutil.copy(os.path.join(HOOKS, "CLAUDE.md.snippet"), os.path.join(work, "CLAUDE.md"))
    return {p: sha(p) for p in glob.glob(os.path.join(work, ".claude", "**", "*"), recursive=True) if os.path.isfile(p)}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--arm", choices="ABC", required=True); ap.add_argument("--run", type=int, required=True)
    ap.add_argument("--seed", type=int, required=True); ap.add_argument("--n", type=int, required=True)
    ap.add_argument("--fixture-words", type=int, required=True); ap.add_argument("--out", required=True)
    ap.add_argument("--budget", type=int, default=1500); ap.add_argument("--window", type=int, default=200000)
    ap.add_argument("--pct", default="40"); ap.add_argument("--max-tasks", type=int, default=0)
    a = ap.parse_args()
    if os.path.exists(a.out): sys.exit(f"refuse: {a.out} exists (never overwritten)")
    work = os.path.join(a.out, "work"); os.makedirs(work)
    subprocess.check_call([sys.executable, os.path.join(HERE, "gen_chain.py"), "--seed", str(a.seed), "--out", work,
                           "--n", str(a.n), "--fixture-words", str(a.fixture_words)])
    hook_hashes = install(a.arm, work, a.budget)
    tasks = json.load(open(os.path.join(work, "tasks.json")))["tasks"]
    if a.max_tasks: tasks = tasks[:a.max_tasks]
    env = {k: v for k, v in os.environ.items() if k not in STRIP}
    env["CLAUDE_AUTOCOMPACT_PCT_OVERRIDE"] = a.pct
    env["PATH"] = os.path.join(REPO, ".venv", "bin") + os.pathsep + env.get("PATH", "")
    base = ["claude", "-p", None, "--autocompact", str(a.window), "--permission-mode", "acceptEdits",
            "--disallowedTools", "WebSearch,WebFetch", "--output-format", "json"]
    manifest = {"arm": a.arm, "run": a.run, "seed": a.seed, "n": a.n, "fixture_words": a.fixture_words, "budget": a.budget,
                "window": a.window, "pct": a.pct, "uid": os.getuid(), "hooks": hook_hashes, "tasks": [], "status": "OK",
                "claude_version": subprocess.run(["claude", "--version"], capture_output=True, text=True, env=env).stdout.strip()}
    for t in tasks:
        k = t["k"]; cmd = list(base); cmd[2] = t["prompt"]
        if k > 1: cmd.insert(3, "--continue")
        t0 = time.time()
        with open(os.path.join(a.out, f"out_{k}.json"), "w") as fo, open(os.path.join(a.out, f"err_{k}.txt"), "w") as fe:
            rc = subprocess.run(cmd, cwd=work, env=env, stdin=subprocess.DEVNULL, stdout=fo, stderr=fe, timeout=1800).returncode
        dt = time.time() - t0
        snap = os.path.join(a.out, "snap", str(k)); shutil.copytree(os.path.join(work, "d037_target"), snap)
        rec = {"k": k, "rc": rc, "seconds": round(dt, 1)}
        try:
            j = json.load(open(os.path.join(a.out, f"out_{k}.json")))
            rec.update(session_id=j.get("session_id"), subtype=j.get("subtype"), cost=j.get("total_cost_usd"),
                       models=list((j.get("modelUsage") or {}).keys()), num_turns=j.get("num_turns"))
        except Exception as e: rec["parse_error"] = repr(e)
        manifest["tasks"].append(rec); print(json.dumps(rec), flush=True)
        if dt < 5: manifest["status"] = "VOID"; print("VOID: worker died in <5s; stopping"); break
        if rc != 0: manifest["status"] = "WORKER_ERROR"; print("worker rc", rc, "; stopping"); break
    td = os.path.join(a.out, "transcript"); os.makedirs(td)
    sids = {t.get("session_id") for t in manifest["tasks"] if t.get("session_id")}
    for f in glob.glob(os.path.join(os.path.expanduser("~"), ".claude", "projects", "*", "*.jsonl")):
        if os.path.basename(f)[:-6] in sids: shutil.copy(f, td)
    manifest["transcripts"] = {os.path.basename(f): sha(f) for f in glob.glob(os.path.join(td, "*.jsonl"))}
    hl = os.path.join(work, ".d037", "hooks.log")
    if os.path.exists(hl): shutil.copy(hl, os.path.join(a.out, "hooks.log"))
    manifest["tasks_json_sha"] = sha(os.path.join(work, "tasks.json"))
    json.dump(manifest, open(os.path.join(a.out, "manifest.json"), "w"), indent=1)
    print("status", manifest["status"], "->", a.out)

if __name__ == "__main__": main()
