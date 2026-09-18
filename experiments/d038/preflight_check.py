#!/usr/bin/env python3
"""Evaluate the five preflight items of D-038 (record, execution step 2) from one preflight raw dir. Prints PASS/FAIL
per item with the transcript evidence (line numbers) and exits non-zero if any item fails. stdlib only."""
import glob, json, os, sys
td = sys.argv[1]; man = json.load(open(os.path.join(td, "manifest.json"))); sid = man.get("main_session")
main_tp = os.path.join(td, "transcript", f"{sid}.jsonl"); items = {}
rows = [json.loads(l) for l in open(main_tp)]
pending = {}; bash_ok = []; denied = []; lookup_ok = []; hook_pairs = []; comp_lines = []
for i, j in enumerate(rows, 1):
    t = j.get("type"); m = j.get("message") or {}; c = m.get("content")
    if t == "system" and j.get("subtype") == "compact_boundary": comp_lines.append(i)
    if t == "assistant" and isinstance(c, list):
        for b in c:
            if b.get("type") == "tool_use": pending[b["id"]] = (b.get("name"), b.get("input") or {})
    if t == "user" and isinstance(c, list) and c and c[0].get("type") == "tool_result":
        name, tin = pending.get(c[0].get("tool_use_id"), (None, {})); r = j.get("toolUseResult"); cmd = str(tin.get("command", ""))
        if isinstance(r, str) and "requires approval" in r: denied.append((i, name, cmd[:80]))
        if name == "Bash" and isinstance(r, dict) and (r.get("stdout") or "").strip() and ("node --check" in cmd or "gate.sh" in cmd or "npm test" in cmd or "node --test" in cmd):
            bash_ok.append((i, cmd[:60], (r.get("stdout") or "").strip().splitlines()[-1][:80]))
        if name == "Bash" and "lookup.py" in cmd and isinstance(r, dict) and len((r.get("stdout") or "").strip().splitlines()) >= 1 and "no receipts" not in (r.get("stdout") or ""):
            lookup_ok.append((i, cmd[:80], (r.get("stdout") or "").strip().splitlines()[:3]))
# all session files (main + forks + probes): no denial anywhere
for tp in glob.glob(os.path.join(td, "transcript", "*.jsonl")):
    for i, l in enumerate(open(tp), 1):
        if "requires approval" in l and os.path.basename(tp) != f"{sid}.jsonl": denied.append((f"{os.path.basename(tp)}:{i}", "?", ""))
items["1 bash executed, no denial"] = (bool(bash_ok) and not denied, {"bash_ok": bash_ok[:3], "denied": denied[:5]})
items["2 lookup.py executed"] = (bool(lookup_ok), {"lookup": lookup_ok[:2], "manifest_turn": (man.get("preflight_lookup_turn") or {}).get("result", "")[:300]})
probes = [json.loads(l) for l in open(os.path.join(td, "probes.jsonl"))] if os.path.exists(os.path.join(td, "probes.jsonl")) else []
answered = [p for p in probes if p.get("answer") and p.get("rc") == 0 and p.get("mode") == "fork" and p.get("probe_session") and p["probe_session"] != sid]
unchanged = [p for p in answered if p.get("main_lines_before") == p.get("main_lines_after")]
items["3 forked probe answered, main transcript unchanged"] = (bool(answered) and len(unchanged) == len(answered),
    {"answered": len(answered), "unchanged": len(unchanged), "sample": [{k: p[k] for k in ("id", "q", "expected", "answer", "main_lines_before", "main_lines_after")} for p in answered[:2]]})
hl = os.path.join(td, "hooks.log"); hooks = open(hl).read().splitlines() if os.path.exists(hl) else []
snap = [l for l in hooks if "snapshot trigger=" in l]; inj = [l for l in hooks if "inject ev=SessionStart" in l]
items["4 compaction with PreCompact -> SessionStart(compact)"] = (bool(comp_lines) and bool(snap) and bool(inj), {"compact_boundary_lines": comp_lines, "precompact": snap[:3], "sessionstart_inject": inj[:3]})
cost = (man.get("task_cost_usd") or 0) + (man.get("probe_cost_usd") or 0)
items["5 cost <= $2"] = (cost <= 2.0, {"task_usd": round(man.get("task_cost_usd") or 0, 3), "probe_usd": round(man.get("probe_cost_usd") or 0, 3), "total_usd": round(cost, 3)})
ok = True
for k, (p, ev) in items.items():
    ok &= p; print(("PASS" if p else "FAIL"), k, json.dumps(ev, default=str)[:600])
print("models:", sorted({m for t in man["turns"] for m in (t.get("models") or [])}), "status", man["status"], "turns", len(man["turns"]), "probes", man["probes"])
sys.exit(0 if ok else 1)
