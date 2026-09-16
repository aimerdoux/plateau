#!/usr/bin/env python3
"""D-038 driver: one arm (A|B), one run, one continuing `claude -p` session per chain. No scoring here.
Worktree = <out>/work: the generated chain plus a copy of --target (the real, private subtree). Everything under --out
carries target content: it is gitignored, never overwritten, and hashed by hash_raw.py. stdlib only."""
import argparse, hashlib, json, os, shutil, subprocess, sys, time, glob
HERE = os.path.dirname(os.path.abspath(__file__)); REPO = os.path.dirname(os.path.dirname(HERE))
HOOKS = os.path.join(REPO, "d037_hooks"); T = "concierge-agent"
STRIP = ("CLAUDECODE", "CLAUDE_CODE_SESSION_ID", "CLAUDE_CODE_REMOTE_SESSION_ID", "CLAUDE_AUTOCOMPACT_PCT_OVERRIDE")
SKIP = {".plateau", "node_modules", "logs", ".DS_Store"}           # never copied from the target; .env* likewise

def sha(p): return hashlib.sha256(open(p, "rb").read()).hexdigest()

def dir_sha(d):
    h = hashlib.sha256()
    for root, _, files in sorted(os.walk(d)):
        for f in sorted(files):
            p = os.path.join(root, f); h.update(os.path.relpath(p, d).encode() + b"\0" + open(p, "rb").read() + b"\0")
    return h.hexdigest()

def pin(src):
    """Git identity of the target subtree (commit, tree hash, dirty flag). The seal cites these, never the content."""
    g = lambda *args: subprocess.check_output(["git", "-C", src, *args], text=True).strip()
    try:
        top = g("rev-parse", "--show-toplevel"); rel = os.path.relpath(os.path.realpath(src), os.path.realpath(top))
        return {"commit": g("rev-parse", "HEAD"), "subtree": rel, "tree": g("rev-parse", f"HEAD:{rel}"),
                "dirty": bool(g("status", "--porcelain", "--", "."))}
    except Exception as e:
        return {"error": repr(e)}

def copy_target(src, work):
    dst = os.path.join(work, T); os.makedirs(dst, exist_ok=True); n = 0
    for name in sorted(os.listdir(src)):
        if name in SKIP or name.startswith(".env"): continue
        s, d = os.path.join(src, name), os.path.join(dst, name)
        shutil.copytree(s, d) if os.path.isdir(s) else shutil.copy(s, d); n += 1
    return n

def install(arm, work, budget):
    if arm == "A": return {}
    hd = os.path.join(work, ".claude", "hooks", "d037"); os.makedirs(hd, exist_ok=True)
    for f in ("d037_common", "query", "inject", "lookup", "ledger"):
        shutil.copy(os.path.join(HOOKS, f + ".py"), hd)
    s = open(os.path.join(HOOKS, "settings.arm_B.json")).read()
    s = s.replace('"command":"python3 $CLAUDE_PROJECT_DIR/.claude/hooks/d037/inject.py"',
                  f'"command":"D037_BUDGET_CHARS={budget} python3 $CLAUDE_PROJECT_DIR/.claude/hooks/d037/inject.py"')
    open(os.path.join(work, ".claude", "settings.json"), "w").write(s)
    return {p: sha(p) for p in glob.glob(os.path.join(work, ".claude", "**", "*"), recursive=True) if os.path.isfile(p)}

def gate(work): return subprocess.run(["bash", "gate.sh"], cwd=work, capture_output=True, text=True)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--arm", choices="AB", required=True); ap.add_argument("--run", type=int, required=True)
    ap.add_argument("--seed", type=int, required=True); ap.add_argument("--n", type=int, required=True)
    ap.add_argument("--fixture-words", type=int, required=True); ap.add_argument("--out", required=True)
    ap.add_argument("--target", required=True, help="path to the real subtree (a git checkout of the Wavex repo, scripts/concierge-agent)")
    ap.add_argument("--budget", type=int, default=1500); ap.add_argument("--window", type=int, default=200000)
    ap.add_argument("--pct", default="40"); ap.add_argument("--max-tasks", type=int, default=0)
    ap.add_argument("--dry-run", action="store_true", help="assemble the worktree and run the gate; no worker session")
    a = ap.parse_args()
    if os.path.exists(a.out): sys.exit(f"refuse: {a.out} exists (never overwritten)")
    if not shutil.which("node"): sys.exit("node not on PATH (the gate needs it)")
    work = os.path.join(a.out, "work"); os.makedirs(work)
    subprocess.check_call([sys.executable, os.path.join(HERE, "gen_chain.py"), "--seed", str(a.seed), "--out", work,
                           "--n", str(a.n), "--fixture-words", str(a.fixture_words)])
    n_copied = copy_target(a.target, work)
    hook_hashes = install(a.arm, work, a.budget)
    env = {k: v for k, v in os.environ.items() if k not in STRIP}
    env["CLAUDE_AUTOCOMPACT_PCT_OVERRIDE"] = a.pct
    manifest = {"experiment": "D-038", "arm": a.arm, "run": a.run, "seed": a.seed, "n": a.n, "fixture_words": a.fixture_words,
                "budget": a.budget, "window": a.window, "pct": a.pct, "uid": os.getuid(), "hooks": hook_hashes,
                "target": pin(a.target), "target_copied_files": n_copied, "work_target_sha": dir_sha(os.path.join(work, T)),
                "node_version": subprocess.run(["node", "--version"], capture_output=True, text=True).stdout.strip(),
                "claude_version": subprocess.run(["claude", "--version"], capture_output=True, text=True, env=env).stdout.strip() if shutil.which("claude") else None,
                "tasks": [], "status": "OK"}
    if a.dry_run:
        g = gate(work); manifest["dry_run_gate"] = {"rc": g.returncode, "tail": (g.stdout + g.stderr)[-600:]}
        manifest["status"] = "DRY_RUN"; json.dump(manifest, open(os.path.join(a.out, "manifest.json"), "w"), indent=1)
        print("dry run: gate rc", g.returncode, "->", a.out); print((g.stdout + g.stderr)[-600:]); sys.exit(g.returncode)
    tasks = json.load(open(os.path.join(work, "tasks.json")))["tasks"]
    if a.max_tasks: tasks = tasks[:a.max_tasks]
    base = ["claude", "-p", None, "--autocompact", str(a.window), "--permission-mode", "acceptEdits",
            "--disallowedTools", "WebSearch,WebFetch", "--output-format", "json"]
    shutil.copytree(os.path.join(work, T), os.path.join(a.out, "snap", "0"))
    for t in tasks:
        k = t["k"]; cmd = list(base); cmd[2] = t["prompt"]
        if k > 1: cmd.insert(3, "--continue")
        t0 = time.time()
        with open(os.path.join(a.out, f"out_{k}.json"), "w") as fo, open(os.path.join(a.out, f"err_{k}.txt"), "w") as fe:
            rc = subprocess.run(cmd, cwd=work, env=env, stdin=subprocess.DEVNULL, stdout=fo, stderr=fe, timeout=1800).returncode
        dt = time.time() - t0
        shutil.copytree(os.path.join(work, T), os.path.join(a.out, "snap", str(k)))
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
