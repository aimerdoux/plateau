#!/usr/bin/env python3
"""D-038 driver: one arm (A vanilla | C bridge), one run, one continuing `claude -p` session over the 17-turn task script
in turns.json, with decay probes between task turns (on forked sessions by default). The worktree carries the real,
private target: everything under --out-root is gitignored and hashed by hash_raw.py. The worktree name is a blind token;
the token→arm map is written to <out-root>/<run>/blind.json, which the judge never sees. stdlib only."""
import argparse, glob, hashlib, json, os, secrets, shutil, subprocess, sys, time
HERE = os.path.dirname(os.path.abspath(__file__)); REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE); import probes
HOOKS = os.path.join(REPO, "d037_hooks"); T = "concierge-agent"
STRIP = ("CLAUDECODE", "CLAUDE_CODE_SESSION_ID", "CLAUDE_CODE_REMOTE_SESSION_ID", "CLAUDE_AUTOCOMPACT_PCT_OVERRIDE")
SKIP = {".plateau", "node_modules", "logs", ".DS_Store"}           # never copied from the target; .env* likewise
# `-p` pre-approves nothing under acceptEdits (D-037: every pytest call was denied). The task needs these.
ALLOWED = ",".join(f"Bash({c}:*)" for c in ("node", "npm", "npx", "bash", "sh", "git", "claude", "python3", "ls", "cat", "mkdir", "rm", "mv",
                   "cp", "grep", "rg", "find", "sed", "awk", "head", "tail", "wc", "diff", "echo", "chmod", "touch", "sort", "uniq", "xargs",
                   "env", "printenv", "pwd", "true", "test", "tree", "jq", "date"))
PROBE_DISALLOWED = "Bash,Read,Edit,Write,MultiEdit,NotebookEdit,Grep,Glob,Task,Agent,WebSearch,WebFetch,TodoWrite,LSP"
PROBE_PREFIX = "Answer in one line, no tools, from memory only. "
GATE = """#!/usr/bin/env bash
# D-038 gate / test runner: every module must parse; every *.test.mjs must pass (node:test).
set -eu; cd "$(dirname "$0")/concierge-agent"
for f in *.mjs; do node --check "$f"; done
node --test
echo GATE OK
"""
TEST = """import { test } from 'node:test';
import assert from 'node:assert/strict';
import { classify } from './classify.mjs';
test('classify still exports a working classifier', () => {
  assert.equal(typeof classify, 'function');
  assert.equal(classify({ product_type: 'rental', product_name: 'Sunset yacht' }, { category: 'boat' }), 'boat');
  assert.equal(classify({ product_type: 'rental', product_name: 'Lamborghini' }, { category: 'exotic car' }), 'car');
  assert.equal(classify({ product_type: 'experience', product_name: 'Spa day' }, null), 'manual');
});
"""
JUDGE_HIDE = {".claude", ".d037", "CLAUDE.md"}                        # arm-revealing; excluded from git and from the judge view

def sha(p): return hashlib.sha256(open(p, "rb").read()).hexdigest()
def git(work, *args): return subprocess.run(["git", "-C", work, *args], capture_output=True, text=True)

def pin(src):
    g = lambda *args: subprocess.check_output(["git", "-C", src, *args], text=True).strip()
    try:
        top = g("rev-parse", "--show-toplevel"); rel = os.path.relpath(os.path.realpath(src), os.path.realpath(top))
        return {"commit": g("rev-parse", "HEAD"), "subtree": rel, "tree": g("rev-parse", f"HEAD:{rel}"), "dirty": bool(g("status", "--porcelain", "--", "."))}
    except Exception as e: return {"error": repr(e)}

def assemble(target, work):
    dst = os.path.join(work, T); os.makedirs(dst); n = 0
    for name in sorted(os.listdir(target)):
        if name in SKIP or name.startswith(".env"): continue
        s, d = os.path.join(target, name), os.path.join(dst, name)
        shutil.copytree(s, d) if os.path.isdir(s) else shutil.copy(s, d); n += 1
    g = os.path.join(work, "gate.sh"); open(g, "w").write(GATE); os.chmod(g, 0o755)
    open(os.path.join(dst, "d038.test.mjs"), "w").write(TEST)
    open(os.path.join(work, ".gitignore"), "w").write("".join(x + "\n" for x in sorted(JUDGE_HIDE)) + "node_modules/\n")
    git(work, "init", "-q"); git(work, "config", "user.email", "d038@plateau"); git(work, "config", "user.name", "d038")
    git(work, "add", "-A"); git(work, "commit", "-q", "-m", "baseline: target copy + gate")
    return n

def install(arm, work, budget):
    if arm == "A": return {}
    hd = os.path.join(work, ".claude", "hooks", "d037"); os.makedirs(hd, exist_ok=True)
    for f in ("d037_common", "query", "receipt", "snapshot", "inject", "lookup"): shutil.copy(os.path.join(HOOKS, f + ".py"), hd)
    s = json.load(open(os.path.join(HOOKS, "settings.arm_omega.json")))
    s["hooks"].pop("UserPromptSubmit", None)                            # S' = 0: inject at SessionStart(compact) only
    for h in s["hooks"]["SessionStart"]:
        for hh in h["hooks"]: hh["command"] = hh["command"].replace("D037_BUDGET_CHARS=6000", f"D037_BUDGET_CHARS={budget}")
    json.dump(s, open(os.path.join(work, ".claude", "settings.json"), "w"), indent=1)
    shutil.copy(os.path.join(HOOKS, "CLAUDE.md.snippet"), os.path.join(work, "CLAUDE.md"))
    return {os.path.relpath(p, work): sha(p) for p in glob.glob(os.path.join(work, ".claude", "**", "*"), recursive=True) if os.path.isfile(p)} | {"CLAUDE.md": sha(os.path.join(work, "CLAUDE.md"))}

def find_transcript(sid):
    hits = glob.glob(os.path.join(os.path.expanduser("~"), ".claude", "projects", "*", f"{sid}.jsonl"))
    return max(hits, key=os.path.getmtime) if hits else None

def claude(cmd, cwd, env, out_json, err_txt, timeout=1800):
    t0 = time.time()
    with open(out_json, "w") as fo, open(err_txt, "w") as fe:
        rc = subprocess.run(cmd, cwd=cwd, env=env, stdin=subprocess.DEVNULL, stdout=fo, stderr=fe, timeout=timeout).returncode
    try: j = json.load(open(out_json))
    except Exception: j = {}
    return rc, time.time() - t0, j

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--arm", choices="AC", required=True); ap.add_argument("--run", type=int, required=True)
    ap.add_argument("--target", required=True); ap.add_argument("--out-root", default=os.path.join(HERE, "raw"))
    ap.add_argument("--token", help="blind worktree token (default: random)")
    ap.add_argument("--budget", type=int, default=6000); ap.add_argument("--window", type=int, default=200000); ap.add_argument("--pct", default="40")
    ap.add_argument("--probes-per-turn", type=int, default=2); ap.add_argument("--probe-mode", choices=("fork", "inline"), default="fork")
    ap.add_argument("--cost-cap", type=float, default=25.0); ap.add_argument("--max-turns", type=int, default=0)
    ap.add_argument("--dry-run", action="store_true", help="assemble the worktree, run the gate, no worker")
    ap.add_argument("--preflight", action="store_true", help="after the task turns, one extra turn that runs lookup.py (arm C) so preflight can verify it executes")
    a = ap.parse_args()
    token = a.token or "wt_" + secrets.token_hex(3); run_dir = os.path.join(a.out_root, str(a.run)); out = os.path.join(run_dir, token)
    if os.path.exists(out): sys.exit(f"refuse: {out} exists (never overwritten)")
    if not shutil.which("node"): sys.exit("node not on PATH")
    work = os.path.join(out, "work"); os.makedirs(work)
    n_copied = assemble(a.target, work); hook_hashes = install(a.arm, work, a.budget)
    blind_p = os.path.join(run_dir, "blind.json"); blind = json.load(open(blind_p)) if os.path.exists(blind_p) else {}
    blind[token] = a.arm; json.dump(blind, open(blind_p, "w"), indent=1); os.chmod(blind_p, 0o600)
    script = json.load(open(os.path.join(HERE, "turns.json")))
    turns = [dict(t, epic=e["id"]) for e in script["epics"] for t in e["turns"]]
    if a.max_turns: turns = turns[:a.max_turns]
    mandated = " ".join(t["prompt"] for t in turns) + " " + script["common_footer"]
    env = {k: v for k, v in os.environ.items() if k not in STRIP}; env["CLAUDE_AUTOCOMPACT_PCT_OVERRIDE"] = a.pct
    manifest = {"experiment": "D-038", "token": token, "run": a.run, "budget": a.budget, "window": a.window, "pct": a.pct, "uid": os.getuid(),
                "probe_mode": a.probe_mode, "probes_per_turn": a.probes_per_turn, "cost_cap": a.cost_cap, "hooks": hook_hashes,
                "target": pin(a.target), "target_copied_files": n_copied, "turns_json_sha": sha(os.path.join(HERE, "turns.json")),
                "node_version": subprocess.run(["node", "--version"], capture_output=True, text=True).stdout.strip(),
                "claude_version": subprocess.run(["claude", "--version"], capture_output=True, text=True, env=env).stdout.strip() if shutil.which("claude") else None,
                "allowed_tools": ALLOWED, "turns": [], "probes": 0, "task_cost_usd": 0.0, "probe_cost_usd": 0.0, "status": "OK"}
    # the arm is deliberately absent from the manifest; blind.json holds it
    if a.dry_run:
        g = subprocess.run(["bash", "gate.sh"], cwd=work, capture_output=True, text=True)
        manifest.update(status="DRY_RUN", dry_run_gate={"rc": g.returncode, "tail": (g.stdout + g.stderr)[-500:]})
        json.dump(manifest, open(os.path.join(out, "manifest.json"), "w"), indent=1)
        print("dry run: gate rc", g.returncode, "->", out); print((g.stdout + g.stderr)[-300:]); sys.exit(g.returncode)
    base = ["claude", "-p", None, "--autocompact", str(a.window), "--permission-mode", "acceptEdits",
            "--disallowedTools", "WebSearch,WebFetch", "--allowedTools", ALLOWED, "--output-format", "json"]
    sid = None; probed = set(); counts = {}; fork_sids = []; probes_f = open(os.path.join(out, "probes.jsonl"), "a")
    for i, t in enumerate(turns, 1):
        cmd = list(base); cmd[2] = f"{t['prompt']}\n\n{script['common_footer']}"
        if sid: cmd += ["--resume", sid]
        rc, dt, j = claude(cmd, work, env, os.path.join(out, f"out_{i}.json"), os.path.join(out, f"err_{i}.txt"))
        sid = sid or j.get("session_id")
        rec = {"i": i, "id": t["id"], "rc": rc, "seconds": round(dt, 1), "session_id": j.get("session_id"), "subtype": j.get("subtype"),
               "cost": j.get("total_cost_usd"), "num_turns": j.get("num_turns"), "models": list((j.get("modelUsage") or {}).keys())}
        manifest["turns"].append(rec); manifest["task_cost_usd"] += rec["cost"] or 0; print(json.dumps(rec), flush=True)
        git(work, "add", "-A"); git(work, "commit", "-q", "--allow-empty", "-m", f"after {t['id']}")
        if dt < 5: manifest["status"] = "VOID"; print("VOID: worker died in <5s"); break
        if rc != 0 or not sid: manifest["status"] = "WORKER_ERROR"; print("worker rc", rc); break
        tp = find_transcript(sid)
        if not tp: manifest["status"] = "NO_TRANSCRIPT"; print("transcript not found for", sid); break
        scan = probes.scan(tp, work, mandated); n_probes = a.probes_per_turn + (1 if i >= 9 else 0)
        for f in probes.choose(scan["facts"], probed, scan["pos"], scan["compactions"], n_probes, counts, final=(i == len(turns))):
            probed.add(f["id"]); q = PROBE_PREFIX + f["q"]
            pc = ["claude", "-p", q, "--resume", sid, "--disallowedTools", PROBE_DISALLOWED, "--output-format", "json"]
            if a.probe_mode == "fork": pc.append("--fork-session")
            lines_before = sum(1 for _ in open(tp))
            prc, pdt, pj = claude(pc, work, env, os.path.join(out, f"probe_{i}_{f['id']}.json"), os.path.join(out, f"probe_{i}_{f['id']}.err"), timeout=300)
            lines_after = sum(1 for _ in open(tp))
            if a.probe_mode == "fork" and pj.get("session_id") and pj["session_id"] != sid: fork_sids.append(pj["session_id"])
            ans = pj.get("result") if isinstance(pj.get("result"), str) else ""
            p = {"turn": i, "turn_id": t["id"], "id": f["id"], "cls": f["cls"], "kind": f["kind"], "q": f["q"], "expected": f["expected"], "answer": ans.strip(),
                 "fact_line": f["last_line"], "fact_first_line": f["first_line"], "fact_pos": f["last_pos"], "probe_pos": scan["pos"],
                 "tokens_since": scan["pos"] - f["last_pos"], "compactions_crossed": scan["compactions"] - f["last_comp"],
                 "lag_bucket": probes.lag_bucket(scan["pos"] - f["last_pos"]), "comp_bucket": probes.comp_bucket(scan["compactions"] - f["last_comp"]),
                 "mode": a.probe_mode, "probe_contaminates": a.probe_mode == "inline", "probe_session": pj.get("session_id"), "rc": prc, "cost": pj.get("total_cost_usd"),
                 "main_lines_before": lines_before, "main_lines_after": lines_after}
            probes_f.write(json.dumps(p) + "\n"); probes_f.flush(); manifest["probes"] += 1; manifest["probe_cost_usd"] += p["cost"] or 0
        if manifest["task_cost_usd"] >= a.cost_cap: manifest["status"] = "COST_CAP"; print("cost cap reached; scoring what exists"); break
    probes_f.close()
    if a.preflight and sid and manifest["status"] in ("OK", "COST_CAP"):
        q = ("Preflight check: run exactly this command with Bash and then paste every line it printed, verbatim: "
             "`python3 .claude/hooks/d037/lookup.py error handler server`")
        cmd = list(base); cmd[2] = q; cmd += ["--resume", sid]
        rc, dt, j = claude(cmd, work, env, os.path.join(out, "out_preflight_lookup.json"), os.path.join(out, "err_preflight_lookup.txt"))
        manifest["preflight_lookup_turn"] = {"rc": rc, "seconds": round(dt, 1), "cost": j.get("total_cost_usd"), "result": (j.get("result") or "")[:2000]}
        manifest["task_cost_usd"] += j.get("total_cost_usd") or 0
    td = os.path.join(out, "transcript"); os.makedirs(td, exist_ok=True)
    for s in [sid] + fork_sids:
        tp = find_transcript(s) if s else None
        if tp: shutil.copy(tp, td)
    manifest["transcripts"] = {os.path.basename(f): sha(f) for f in glob.glob(os.path.join(td, "*.jsonl"))}; manifest["main_session"] = sid
    hl = os.path.join(work, ".d037", "hooks.log")
    if os.path.exists(hl): shutil.copy(hl, os.path.join(out, "hooks.log"))
    # judge view: the worktree without anything that names the arm, plus the script and the blind probe log
    jv = os.path.join(out, "judge_view"); shutil.copytree(work, jv, ignore=lambda d, names: [n for n in names if n in JUDGE_HIDE])
    shutil.copy(os.path.join(HERE, "turns.json"), jv)
    with open(os.path.join(jv, "probes_blind.jsonl"), "w") as fo:
        for l in open(os.path.join(out, "probes.jsonl")):
            p = json.loads(l); fo.write(json.dumps({k: p[k] for k in ("id", "turn_id", "cls", "q", "expected", "answer")}) + "\n")
    json.dump(manifest, open(os.path.join(out, "manifest.json"), "w"), indent=1)
    print("status", manifest["status"], "task $", round(manifest["task_cost_usd"], 2), "probe $", round(manifest["probe_cost_usd"], 2), "probes", manifest["probes"], "->", out)

if __name__ == "__main__": main()
