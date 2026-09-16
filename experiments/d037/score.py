#!/usr/bin/env python3
"""D-037 scorer. Separate process over sealed raw dirs. Deterministic AST/string checks; every scored item
cites transcript file + line. Usage: score.py --raw experiments/d037/raw --out experiments/d037/results.json"""
import argparse, ast, glob, json, os, re, statistics as st
D = 3                                   # dependency distance
SPEC_S = lambda k, comp: any(k - 3 <= c <= k - 1 for c in comp)          # spec: boundary in [k-3, k-1]

def facts(kind, snap_prev, snap_cur, module):
    """Symbols of `kind` newly present in snap_cur/module vs snap_prev."""
    def names(snap):
        if kind == "module":
            return {os.path.basename(p)[:-3] for p in glob.glob(os.path.join(snap, "*_util.py"))} if snap else set()
        if not snap: return set()
        p = os.path.join(snap, module + ".py")
        if not os.path.exists(p): return set()
        try: tree = ast.parse(open(p).read())
        except SyntaxError: return set()
        out = set()
        for n in tree.body:
            if kind == "constant" and isinstance(n, ast.Assign):
                for t in n.targets:
                    if isinstance(t, ast.Name) and t.id.endswith("_LIMIT"): out.add(t.id)
            if kind == "function" and isinstance(n, ast.FunctionDef) and n.name.endswith("_handler"): out.add(n.name)
        return out
    return names(snap_cur) - names(snap_prev)

def used(kind, snap, use_module, k, F):
    p = os.path.join(snap, use_module + ".py")
    if not os.path.exists(p): return False, "use module missing"
    try: tree = ast.parse(open(p).read())
    except SyntaxError: return False, "syntax error"
    refs = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom):
            refs.add(n.module or ""); refs |= {a.name for a in n.names}
            if n.module: refs |= set(n.module.split("."))
        if isinstance(n, ast.Import): refs |= {a.name.split(".")[-1] for a in n.names}
        if isinstance(n, ast.Name): refs.add(n.id)
        if isinstance(n, ast.Attribute): refs.add(n.attr)
    has_link = any(isinstance(n, ast.FunctionDef) and n.name == f"link_{k}" for n in tree.body)
    hit = sorted(F & refs)
    return bool(hit) and has_link, f"link_{k}={'present' if has_link else 'absent'} refs∩facts={hit}"

def segment(tp, tasks):
    """Walk the transcript: task segments, compaction lines, Read calls, usage per task, link-edit lines."""
    prompts = {t["prompt"]: t["k"] for t in tasks}
    cur = 0; comp = []; reads = []; usage = {}; prompt_line = {}; edit_lines = {}
    for i, l in enumerate(open(tp), 1):
        try: j = json.loads(l)
        except Exception: continue
        m = j.get("message") or {}; c = m.get("content")
        if j.get("type") == "user":
            txt = c if isinstance(c, str) else " ".join(b.get("text", "") for b in (c or []) if isinstance(b, dict) and b.get("type") == "text")
            for p, k in prompts.items():
                if txt.strip().startswith(p[:80]) and cur < k: cur = k; prompt_line[k] = i
        if j.get("type") == "system" and j.get("subtype") == "compact_boundary": comp.append((cur, i))
        if j.get("type") == "assistant":
            u = m.get("usage")
            if u:
                s = usage.setdefault(cur, {"in": 0, "out": 0, "calls": 0, "ids": set()})
                if m.get("id") not in s["ids"]:          # one API call may be logged across several lines
                    s["ids"].add(m.get("id")); s["calls"] += 1
                    s["in"] += u.get("input_tokens", 0) + u.get("cache_read_input_tokens", 0) + u.get("cache_creation_input_tokens", 0)
                    s["out"] += u.get("output_tokens", 0)
            for b in (c or []) if isinstance(c, list) else []:
                if b.get("type") != "tool_use": continue
                tin = b.get("input") or {}
                if b.get("name") == "Read": reads.append((cur, i, tin.get("file_path", "")))
                if b.get("name") in ("Edit", "Write", "MultiEdit") and f"link_{cur}" in json.dumps(tin): edit_lines.setdefault(cur, i)
    for s in usage.values(): s.pop("ids", None)
    return comp, reads, usage, prompt_line, edit_lines

def score_run(rd):
    man = json.load(open(os.path.join(rd, "manifest.json")))
    tasks = json.load(open(os.path.join(rd, "work", "tasks.json")))["tasks"]
    tps = sorted(glob.glob(os.path.join(rd, "transcript", "*.jsonl")))
    tp = max(tps, key=os.path.getsize); tname = os.path.basename(tp)
    comp, reads, usage, pline, eline = segment(tp, tasks)
    comp_tasks = [c for c, _ in comp]
    snap = lambda k: os.path.join(rd, "snap", str(k)) if os.path.isdir(os.path.join(rd, "snap", str(k))) else None
    items = []
    for t in tasks:
        if not snap(t["k"]): break                      # driver stopped early (VOID / error): score only what ran
        k = t["k"]; it = {"k": k, "prompt_line": pline.get(k), "cite": tname}
        it["nonce_ok"] = os.path.exists(os.path.join(snap(k), f"nonce_{k}.txt")) and open(os.path.join(snap(k), f"nonce_{k}.txt")).read().strip() == t["nonce"]
        if t["dep"]:
            d = t["dep"]; F = facts(d["kind"], snap(d["k"] - 1), snap(d["k"]), d["module"])
            ok, why = used(d["kind"], snap(k), t["use_module"], k, F)
            it.update(dep_k=d["k"], facts=sorted(F), used=ok, why=why, link_edit_line=eline.get(k),
                      straddle_spec=SPEC_S(k, comp_tasks),
                      # secondary: a compaction inside task k before the link edit also separates fact from use
                      straddle_eff=SPEC_S(k, comp_tasks) or any(c == k and (eline.get(k) is None or li < eline[k]) for c, li in comp),
                      compactions_between=[li for c, li in comp if k - 3 <= c <= k],
                      dep_reread=[li for c, li, fp in reads if c == k and fp.endswith(d["module"] + ".py")])
        u = usage.get(k, {}); it["tokens_in"] = u.get("in", 0); it["tokens_out"] = u.get("out", 0); it["api_calls"] = u.get("calls", 0)
        items.append(it)
    # re-derivations: Reads after a compaction of a target .py file that was Read before that compaction
    rederiv = []
    for c, ci in comp:
        before = {fp for _, li, fp in reads if li < ci and "d037_target" in fp and fp.endswith(".py")}
        rederiv += [(li, fp) for _, li, fp in reads if li > ci and fp in before and not any(ci < cj < li for _, cj in comp)]
    inj = []
    hl = os.path.join(rd, "hooks.log")
    if os.path.exists(hl):
        for l in open(hl):
            m = re.search(r"inject ev=(\w+) .* chars=(\d+) budget=(\d+)", l)
            if m: inj.append((m.group(1), int(m.group(2)), int(m.group(3))))
    scored = [i for i in items if "used" in i]
    def R(sel): 
        xs = [i["used"] for i in scored if sel(i)]; return (sum(xs) / len(xs) if xs else None), len(xs)
    out = {"arm": man["arm"], "run": man["run"], "seed": man["seed"], "status": man["status"], "transcript": tname,
           "compactions": [{"task": c, "line": li} for c, li in comp], "n_compactions": len(comp),
           "R_S": R(lambda i: i["straddle_spec"]), "R_NS": R(lambda i: not i["straddle_spec"]),
           "R_S_eff": R(lambda i: i["straddle_eff"]), "R_NS_eff": R(lambda i: not i["straddle_eff"]),
           "S_tasks": [i["k"] for i in scored if i["straddle_spec"]], "NS_tasks": [i["k"] for i in scored if not i["straddle_spec"]],
           "nonce_rate": sum(i["nonce_ok"] for i in items) / len(items),
           "rederivations": len(rederiv), "rederivation_lines": rederiv, "dep_rereads": sum(len(i.get("dep_reread", [])) for i in scored),
           "tokens_per_task_in": st.mean(i["tokens_in"] for i in items), "tokens_per_task_out": st.mean(i["tokens_out"] for i in items),
           "tokens_per_task": st.mean(i["tokens_in"] + i["tokens_out"] for i in items),
           "inject_events": len(inj), "inject_chars": sum(c for _, c, _ in inj), "inject_over_budget": [x for x in inj if x[1] > x[2]],
           "cost_usd": sum(t.get("cost") or 0 for t in man["tasks"]), "confounded": [], "items": items}
    if len(comp) < 2: out["confounded"].append(f"<2 compactions ({len(comp)})")
    if out["inject_over_budget"]: out["confounded"].append("injection over budget")
    if man["status"] != "OK": out["confounded"].append(f"driver status {man['status']}")
    tot_out = sum(i["tokens_out"] for i in items)
    out["rho"] = (out["inject_chars"] / 4) / tot_out if (man["arm"] == "C" and tot_out) else None
    return out

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--raw", required=True); ap.add_argument("--out", required=True); a = ap.parse_args()
    runs = {}
    for rd in sorted(glob.glob(os.path.join(a.raw, "*", "*"))):
        if not os.path.exists(os.path.join(rd, "manifest.json")): continue
        r = score_run(rd); runs.setdefault(r["arm"], {})[r["run"]] = r
    table = []; bets = {b: [] for b in ("B1", "B2", "B3", "B4", "B5")}
    for run in sorted({r for arm in runs.values() for r in arm}):
        A, B, C = (runs.get(x, {}).get(run) for x in "ABC")
        row = {"run": run}
        if not (A and B and C): row["note"] = "incomplete"; table.append(row); continue
        conf = [f"{x['arm']}:{c}" for x in (A, B, C) for c in x["confounded"]]
        row["confounded"] = conf
        alpha = A["R_NS"][0]; lam = (1 - A["R_S"][0] / alpha) if alpha else None
        pi = {}
        for X in (B, C):
            pi[X["arm"]] = (1 - (1 - X["R_S"][0] / alpha) / lam) if (alpha and lam) else None
        row.update(alpha=alpha, lam=lam, pi_B=pi["B"], pi_C=pi["C"], R_S={x["arm"]: x["R_S"][0] for x in (A, B, C)},
                   R_NS={x["arm"]: x["R_NS"][0] for x in (A, B, C)}, rho_C=C["rho"],
                   tokens_per_task={x["arm"]: round(x["tokens_per_task"]) for x in (A, B, C)},
                   rederivations={x["arm"]: x["rederivations"] for x in (A, B, C)},
                   compactions={x["arm"]: x["n_compactions"] for x in (A, B, C)},
                   nonce={x["arm"]: x["nonce_rate"] for x in (A, B, C)})
        if conf: row["scored"] = False; table.append(row); continue
        row["scored"] = True
        b = {"B1": C["R_S"][0] > A["R_S"][0], "B2": (pi["C"] is not None and pi["B"] is not None and pi["C"] - pi["B"] >= 0.15),
             "B3": B["R_S"][0] > A["R_S"][0], "B4": (C["rho"] is not None and C["rho"] < 0.05),
             "B5": C["tokens_per_task"] <= A["tokens_per_task"]}
        row["bets"] = b
        row["margins"] = {"B1": C["R_S"][0] - A["R_S"][0], "B2": (pi["C"] - pi["B"]) if (pi["C"] is not None and pi["B"] is not None) else None,
                          "B3": B["R_S"][0] - A["R_S"][0]}
        for k, v in b.items(): bets[k].append((run, v, row["margins"].get(k)))
        table.append(row)
    verdicts = {}
    for k, xs in bets.items():
        wins = sum(v for _, v, _ in xs); n = len(xs)
        if n == 0: verdicts[k] = "UNSCORED"; continue
        small = any((mg is not None) and v and ((k == "B2" and mg < 0.15) or (k in ("B1", "B3") and mg < 0.05)) for _, v, mg in xs)
        verdicts[k] = "WIN" if wins >= 2 and not (wins == 2 and small) else ("PARTIAL" if wins == 2 else "LOSS")
    res = {"runs": runs, "table": table, "verdicts": verdicts}
    json.dump(res, open(a.out, "w"), indent=1, default=str)
    print(json.dumps({"table": table, "verdicts": verdicts}, indent=1, default=str))

if __name__ == "__main__": main()
