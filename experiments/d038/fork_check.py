#!/usr/bin/env python3
"""Preflight item 3, in isolation and cheaply (≤ $0.50): one throwaway turn on a fresh worktree (read two files, run the
test runner), then one forked probe; the main transcript's line count and SHA-256 are compared before and after the
fork, and the fork's own transcript must exist and contain the probe. Reuses run_task.py's assemble/claude helpers;
the sealed driver is not modified. Uses the record's real setting: --autocompact 200000, pct 40."""
import hashlib, json, os, shutil, sys, time
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import probes, run_task as rt
target, out = sys.argv[1], sys.argv[2]
if os.path.exists(out): sys.exit(f"refuse: {out} exists")
work = os.path.join(out, "work"); os.makedirs(work); rt.assemble(target, work)
env = {k: v for k, v in os.environ.items() if k not in rt.STRIP}; env["CLAUDE_AUTOCOMPACT_PCT_OVERRIDE"] = "40"
T = ("Throwaway preflight turn. Read `concierge-agent/classify.mjs` and `concierge-agent/agent.mjs` fully, then run "
     "`bash gate.sh` with Bash and report the last line of its output. Do not edit anything.")
cmd = ["claude", "-p", T, "--autocompact", "200000", "--permission-mode", "acceptEdits", "--disallowedTools", "WebSearch,WebFetch",
       "--allowedTools", rt.ALLOWED, "--output-format", "json"]
rc, dt, j = rt.claude(cmd, work, env, os.path.join(out, "out_1.json"), os.path.join(out, "err_1.txt"))
sid = j.get("session_id"); cost = j.get("total_cost_usd") or 0
print(json.dumps({"turn": 1, "rc": rc, "seconds": round(dt, 1), "cost": cost, "is_error": j.get("is_error"), "session": sid}), flush=True)
if rc != 0 or not sid: sys.exit("throwaway turn failed")
tp = rt.find_transcript(sid); sha = lambda p: hashlib.sha256(open(p, "rb").read()).hexdigest()
scan = probes.scan(tp, work, T); f = probes.choose(scan["facts"], set(), scan["pos"], scan["compactions"], 1, {}, final=True)
if not f: sys.exit("no fact to probe"); 
f = f[0]; q = rt.PROBE_PREFIX + f["q"]
before = (sum(1 for _ in open(tp)), sha(tp))
pc = ["claude", "-p", q, "--resume", sid, "--fork-session", "--disallowedTools", rt.PROBE_DISALLOWED, "--output-format", "json"]
prc, pdt, pj = rt.claude(pc, work, env, os.path.join(out, "probe.json"), os.path.join(out, "probe.err"), timeout=300)
time.sleep(2); after = (sum(1 for _ in open(tp)), sha(tp))
fsid = pj.get("session_id"); ftp = rt.find_transcript(fsid) if fsid and fsid != sid else None
fork_has_probe = bool(ftp) and f["q"][:60] in open(ftp).read()
res = {"fact": {k: f[k] for k in ("cls", "kind", "q", "expected")}, "answer": (pj.get("result") or "").strip()[:300], "probe_rc": prc, "probe_cost": pj.get("total_cost_usd"),
       "main_session": sid, "fork_session": fsid, "fork_is_new_session": bool(fsid) and fsid != sid, "fork_transcript": os.path.basename(ftp) if ftp else None,
       "fork_transcript_has_probe": fork_has_probe, "main_lines_before": before[0], "main_lines_after": after[0], "main_sha_unchanged": before[1] == after[1],
       "total_cost": cost + (pj.get("total_cost_usd") or 0)}
os.makedirs(os.path.join(out, "transcript")); shutil.copy(tp, os.path.join(out, "transcript"))
if ftp: shutil.copy(ftp, os.path.join(out, "transcript"))
json.dump(res, open(os.path.join(out, "fork_check.json"), "w"), indent=1); print(json.dumps(res, indent=1))
ok = prc == 0 and res["answer"] and res["fork_is_new_session"] and fork_has_probe and before == after and res["total_cost"] <= 0.5
print("ITEM 3", "PASS" if ok else "FAIL"); sys.exit(0 if ok else 1)
