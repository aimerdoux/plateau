#!/usr/bin/env python3
"""D-038 scorer. Separate process over the raw dirs after the blind judge has graded every probe. Unblinds with
<raw>/<run>/blind.json, computes recall per lag bucket / compaction bucket / class per arm, AUC over the three lag
buckets, the complexity gate, re-derivations and tokens per turn from the main transcript, and resolves bets B1–B5.
Usage: score.py --raw experiments/d038/raw --out experiments/d038/results.json"""
import argparse, glob, json, os, statistics as st, sys
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE); import probes
T = "concierge-agent"; GRADE = {"exact": 1.0, "fuzzy": 0.5, "wrong": 0.0}
GATE_RECALL = 0.70; AUC_GAP = 0.10; MIN_PROBES = 20

def auc(rb):
    """Trapezoid over the three equally spaced lag buckets: (r0 + 2 r1 + r2) / 4. None if any bucket is empty."""
    return None if any(rb.get(b) is None for b in (0, 1, 2)) else (rb[0] + 2 * rb[1] + rb[2]) / 4

def turn_usage(tp, prompts):
    """Per task turn: new tokens (input + cache_creation + output) and Read calls; compaction lines; for re-derivations."""
    cur = 0; usage = {}; reads = []; comp = []; seen = set()
    for i, l in enumerate(open(tp), 1):
        try: j = json.loads(l)
        except Exception: continue
        m = j.get("message") or {}; c = m.get("content")
        if j.get("type") == "user":
            txt = c if isinstance(c, str) else " ".join(b.get("text", "") for b in (c or []) if isinstance(b, dict) and b.get("type") == "text")
            for k, p in enumerate(prompts, 1):
                if txt.strip().startswith(p[:80]) and cur < k: cur = k
        if j.get("type") == "system" and j.get("subtype") == "compact_boundary": comp.append((cur, i))
        if j.get("type") == "assistant":
            u = m.get("usage")
            if u and m.get("id") not in seen:
                seen.add(m.get("id")); usage[cur] = usage.get(cur, 0) + u.get("input_tokens", 0) + u.get("cache_creation_input_tokens", 0) + u.get("output_tokens", 0)
            for b in (c or []) if isinstance(c, list) else []:
                if b.get("type") == "tool_use" and b.get("name") == "Read": reads.append((cur, i, (b.get("input") or {}).get("file_path", "")))
    rederiv = []
    for c_, ci in comp:
        before = {fp for _, li, fp in reads if li < ci and f"/{T}/" in fp}
        rederiv += [(li, fp) for _, li, fp in reads if li > ci and fp in before and not any(ci < cj < li for _, cj in comp)]
    return usage, comp, rederiv

def score_token(td, arm):
    man = json.load(open(os.path.join(td, "manifest.json"))); jp = os.path.join(td, "judge.json")
    judge = json.load(open(jp)) if os.path.exists(jp) else None
    plist = [json.loads(l) for l in open(os.path.join(td, "probes.jsonl"))] if os.path.exists(os.path.join(td, "probes.jsonl")) else []
    verdict = {p["id"]: p["verdict"] for p in (judge or {}).get("probes", [])}
    graded = [dict(p, grade=GRADE[verdict[p["id"]]]) for p in plist if verdict.get(p["id"]) in GRADE]
    def recall(sel):
        xs = [p["grade"] for p in graded if sel(p)]; return (st.mean(xs) if xs else None), len(xs)
    by_lag = {b: recall(lambda p, b=b: p["lag_bucket"] == b) for b in (0, 1, 2)}
    by_comp = {b: recall(lambda p, b=b: p["comp_bucket"] == b) for b in (0, 1, 2)}
    by_cls = {c: recall(lambda p, c=c: p["cls"] == c) for c in probes.CLASSES}
    far = recall(lambda p: p["lag_bucket"] == 2 or p["comp_bucket"] >= 1)
    script = json.load(open(os.path.join(HERE, "turns.json")))
    prompts = [f"{t['prompt']}\n\n{script['common_footer']}" for e in script["epics"] for t in e["turns"]]
    tps = [p for p in glob.glob(os.path.join(td, "transcript", "*.jsonl")) if os.path.basename(p)[:-6] == man.get("main_session")]
    usage, comp, rederiv = turn_usage(tps[0], prompts) if tps else ({}, [], [])
    turns_done = [t for t in man["turns"] if t.get("rc") == 0]
    out = {"arm": arm, "token": man["token"], "run": man["run"], "status": man["status"], "probe_mode": man["probe_mode"],
           "turns_completed": len(turns_done), "task_cost_usd": man["task_cost_usd"], "probe_cost_usd": man["probe_cost_usd"],
           "n_probes": len(plist), "n_graded": len(graded), "recall_by_lag": {b: by_lag[b][0] for b in by_lag}, "n_by_lag": {b: by_lag[b][1] for b in by_lag},
           "recall_by_comp": {b: by_comp[b][0] for b in by_comp}, "recall_by_class": {c: by_cls[c][0] for c in by_cls},
           "far_recall": far[0], "n_far": far[1], "auc": auc({b: by_lag[b][0] for b in by_lag}),
           "n_compactions": len(comp), "rederivations": len(rederiv), "rederivation_lines": rederiv[:50],
           "tokens_per_turn": (st.mean(usage[k] for k in usage if k >= 1) if any(k >= 1 for k in usage) else None),
           "judge": None if not judge else {"epics": {e: judge["epics"][e]["score"] for e in judge.get("epics", {})},
                                            "task_total": sum(judge["epics"][e]["score"] for e in judge.get("epics", {})),
                                            "security_items_closed": len(judge.get("security_items_closed", [])),
                                            "runner_green": (judge.get("tests") or {}).get("runner_green")},
           "void": []}
    if man["status"] not in ("OK", "COST_CAP"): out["void"].append(f"driver status {man['status']}")
    if len(comp) < 2: out["void"].append(f"<2 compactions ({len(comp)})")
    if len(graded) < MIN_PROBES: out["void"].append(f"<{MIN_PROBES} graded probes ({len(graded)})")
    if judge is None: out["void"].append("not judged")
    if (man.get("target") or {}).get("dirty"): out["void"].append("target checkout was dirty")
    return out

BETS = ("B1", "B2", "B3", "B4", "B5")
def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--raw", required=True); ap.add_argument("--out", required=True); a = ap.parse_args()
    runs = {}
    for bp in sorted(glob.glob(os.path.join(a.raw, "*", "blind.json"))):
        run = int(os.path.basename(os.path.dirname(bp))); blind = json.load(open(bp))
        for token, arm in blind.items():
            td = os.path.join(os.path.dirname(bp), token)
            if os.path.exists(os.path.join(td, "manifest.json")): runs.setdefault(run, {})[arm] = score_token(td, arm)
    table = []; bets = {b: [] for b in BETS}
    for run in sorted(runs):
        A, C = runs[run].get("A"), runs[run].get("C"); row = {"run": run}
        if not (A and C): row["note"] = "incomplete"; table.append(row); continue
        void = [f"{x['arm']}:{v}" for x in (A, C) for v in x["void"]]; row["void"] = void
        row.update(far_recall_A=A["far_recall"], auc={"A": A["auc"], "C": C["auc"]}, rederivations={"A": A["rederivations"], "C": C["rederivations"]},
                   task_score={"A": (A["judge"] or {}).get("task_total"), "C": (C["judge"] or {}).get("task_total")},
                   tokens_per_turn={"A": A["tokens_per_turn"], "C": C["tokens_per_turn"]}, compactions={"A": A["n_compactions"], "C": C["n_compactions"]},
                   probes_graded={"A": A["n_graded"], "C": C["n_graded"]}, cost={"A": A["task_cost_usd"] + A["probe_cost_usd"], "C": C["task_cost_usd"] + C["probe_cost_usd"]})
        if void: row["scored"] = False; table.append(row); continue
        row["scored"] = True
        gate = A["far_recall"] is not None and A["far_recall"] < GATE_RECALL
        b = {"B1": gate,
             "B2": gate and A["auc"] is not None and C["auc"] is not None and C["auc"] - A["auc"] >= AUC_GAP,
             "B3": C["rederivations"] < A["rederivations"],
             "B4": (C["judge"] or {}).get("task_total", -1) >= (A["judge"] or {}).get("task_total", 0),
             "B5": C["tokens_per_turn"] is not None and A["tokens_per_turn"] is not None and C["tokens_per_turn"] <= 1.05 * A["tokens_per_turn"]}
        row["bets"] = b; row["margins"] = {"B1": (GATE_RECALL - A["far_recall"]) if A["far_recall"] is not None else None,
                                          "B2": (C["auc"] - A["auc"] - AUC_GAP) if (A["auc"] is not None and C["auc"] is not None) else None}
        for k, v in b.items(): bets[k].append((run, v))
        table.append(row)
    verdicts = {}
    for k, xs in bets.items():
        n = len(xs); w = sum(v for _, v in xs)
        verdicts[k] = "UNSCORED" if n == 0 else ("WIN" if w == n else ("PARTIAL" if w >= 1 else "LOSS"))
    conclusion = None
    if verdicts["B1"] == "LOSS": conclusion = "VOID: task below decay threshold; increase horizon before testing the bridge again"
    elif verdicts["B1"] != "UNSCORED" and verdicts["B2"] == "LOSS": conclusion = "bridge does not carry attention across compaction; value limited to re-derivation savings"
    res = {"experiment": "D-038", "runs": runs, "table": table, "verdicts": verdicts, "conclusion": conclusion}
    json.dump(res, open(a.out, "w"), indent=1, default=str)
    print(json.dumps({"table": table, "verdicts": verdicts, "conclusion": conclusion}, indent=1, default=str))

if __name__ == "__main__": main()
