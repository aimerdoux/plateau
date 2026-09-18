#!/usr/bin/env python3
"""Offline self-test of the D-038 instrument. No Claude tokens.
1. Probe extractor over D-037's nine sealed transcripts: ≥ 30 facts per transcript after the mandated filter is NOT
   expected there (13 tiny tasks); the requirement checked is ≥ 30 facts in total per class-set across the nine, with all
   three classes present, plus per-transcript position/compaction tracking.
2. Scheduler simulation on one transcript: probes land in all three lag buckets.
3. Scorer on a synthetic run: two blind tokens with fabricated probe logs and judge verdicts, real D-037 transcripts
   standing in as main transcripts; checks recall, AUC, the gate, bet resolution and the VOID rules.
Optional: --target <wavex>/scripts/concierge-agent also dry-runs run_task.py (assemble + gate) on the real subtree."""
import argparse, glob, json, os, shutil, subprocess, sys
HERE = os.path.dirname(os.path.abspath(__file__)); REPO = os.path.dirname(os.path.dirname(HERE)); sys.path.insert(0, HERE); import probes
D037 = os.path.join(REPO, "experiments", "d037", "raw")

def part1():
    tot = {c: 0 for c in probes.CLASSES}; per = {}
    for tp in sorted(glob.glob(os.path.join(D037, "*", "*", "transcript", "*.jsonl"))):
        rd = os.path.dirname(os.path.dirname(tp)); mand = " ".join(t["prompt"] for t in json.load(open(os.path.join(rd, "work", "tasks.json")))["tasks"])
        r = probes.scan(tp, os.path.join(rd, "work"), mand); by = {c: sum(f["cls"] == c for f in r["facts"]) for c in probes.CLASSES}
        assert r["compactions"] >= 3 and r["pos"] > 100_000, (tp, r["compactions"], r["pos"])
        import re
        assert all(f["expected"] and f["q"] and not re.search(r"(?<![\w/.\-])" + re.escape(f["expected"]) + r"(?![\w/.\-])", f["q"]) for f in r["facts"]), "a question leaks its answer"
        per[os.path.relpath(rd, D037)] = dict(by, total=len(r["facts"]), pos=r["pos"], compactions=r["compactions"])
        for c in by: tot[c] += by[c]
    assert len(per) == 9 and sum(tot.values()) >= 30 and all(tot[c] > 0 for c in probes.CLASSES), (len(per), tot)
    return per, tot

def part2():
    tp = glob.glob(os.path.join(D037, "C", "2", "transcript", "*.jsonl"))[0]; rd = os.path.join(D037, "C", "2")
    r = probes.scan(tp, os.path.join(rd, "work"), " ".join(t["prompt"] for t in json.load(open(os.path.join(rd, "work", "tasks.json")))["tasks"]))
    probed = set(); counts = {}; log = []; cps = list(range(12000, r["pos"] + 1, 12000))
    for cp in cps:
        avail = [f for f in r["facts"] if f["last_pos"] <= cp]; comp_at = max([f["comp"] for f in avail] + [0])
        for f in probes.choose(avail, probed, cp, comp_at, 2, counts, final=(cp == cps[-1])):
            assert f["id"] not in probed; probed.add(f["id"]); log.append((probes.lag_bucket(cp - f["last_pos"]), f["cls"]))
    dist = {k: sum(1 for x in log if x == k) for k in sorted(set(log))}
    assert {b for b, _ in log} == {0, 1, 2}, dist
    return len(log), len(r["facts"]), dist

def part3(out):
    shutil.rmtree(out, ignore_errors=True); raw = os.path.join(out, "raw"); rows = {}
    script = json.load(open(os.path.join(HERE, "turns.json")))
    def fake(run, token, arm, recall_far, auc_shape, rederiv_reads, judge_total):
        td = os.path.join(raw, str(run), token); os.makedirs(os.path.join(td, "transcript"))
        src = glob.glob(os.path.join(D037, "C" if arm == "C" else "A", str(run), "transcript", "*.jsonl"))[0]
        sid = os.path.basename(src)[:-6]; shutil.copy(src, os.path.join(td, "transcript"))
        man = {"token": token, "run": run, "status": "OK", "probe_mode": "fork", "task_cost_usd": 3.0, "probe_cost_usd": 0.5, "main_session": sid,
               "target": {"dirty": False}, "turns": [{"i": i, "rc": 0} for i in range(1, 18)]}
        json.dump(man, open(os.path.join(td, "manifest.json"), "w"))
        plist = []; verd = []; n = 0
        for lb, rec in enumerate(auc_shape):
            for cb in (0, 1, 2):
                for k in range(4):
                    n += 1; fid = f"f{n:03d}"; cls = probes.CLASSES[n % 3]
                    plist.append({"id": fid, "turn_id": "E1.1", "cls": cls, "kind": "x", "q": "q?", "expected": "e", "answer": "a", "lag_bucket": lb, "comp_bucket": cb, "tokens_since": lb * 30000, "compactions_crossed": cb})
                    verd.append({"id": fid, "verdict": "exact" if (k / 4) < rec else "wrong", "cite": f"probes_blind.jsonl:{n}"})
        with open(os.path.join(td, "probes.jsonl"), "w") as fo: fo.write("".join(json.dumps(p) + "\n" for p in plist))
        json.dump({"probes": verd, "epics": {e: {"score": s, "cite": "x:1"} for e, s in zip(("E1", "E2", "E3", "E4"), judge_total)}, "security_items_closed": [], "tests": {"runner_green": True}, "defects": ""},
                  open(os.path.join(td, "judge.json"), "w"))
        bp = os.path.join(raw, str(run), "blind.json"); b = json.load(open(bp)) if os.path.exists(bp) else {}; b[token] = arm; json.dump(b, open(bp, "w"))
    # run 1: A decays (far recall 0.5), C flat: gate passes, B2 holds; run 2: A does not decay: gate fails
    fake(1, "wt_aaaaaa", "A", 0.5, (1.0, 0.5, 0.5), 0, (2, 2, 1, 1)); fake(1, "wt_cccccc", "C", 1.0, (1.0, 1.0, 1.0), 0, (2, 2, 2, 1))
    fake(2, "wt_dddddd", "A", 1.0, (1.0, 1.0, 1.0), 0, (3, 2, 2, 2)); fake(2, "wt_eeeeee", "C", 1.0, (1.0, 1.0, 1.0), 0, (2, 2, 2, 2))
    res_p = os.path.join(out, "results.json")
    subprocess.check_call([sys.executable, os.path.join(HERE, "score.py"), "--raw", raw, "--out", res_p], stdout=subprocess.DEVNULL)
    res = json.load(open(res_p)); r1, r2 = res["table"]
    # far set = lag bucket 2 (12 probes at 0.5) + lag 0/1 with ≥1 compaction crossed (8 at 1.0, 8 at 0.5) = 18/28
    assert r1["scored"] and abs(r1["far_recall_A"] - 18 / 28) < 1e-9 and abs(r1["auc"]["A"] - 0.625) < 1e-9 and r1["auc"]["C"] == 1.0, r1
    assert r1["bets"]["B1"] and r1["bets"]["B2"] and r1["bets"]["B4"], r1["bets"]
    assert r2["scored"] and r2["far_recall_A"] == 1.0 and not r2["bets"]["B1"] and not r2["bets"]["B2"] and not r2["bets"]["B4"], r2
    assert res["verdicts"]["B1"] == "PARTIAL" and res["verdicts"]["B2"] == "PARTIAL" and res["conclusion"] is None, res["verdicts"]
    A1 = res["runs"]["1"]["A"]; assert A1["n_compactions"] >= 3 and A1["tokens_per_turn"] is None or A1["tokens_per_turn"] >= 0
    assert A1["n_graded"] == 36 and A1["recall_by_lag"]["0"] == 1.0 and A1["recall_by_lag"]["2"] == 0.5, A1["recall_by_lag"]
    # VOID rule: fewer than 20 graded probes
    td = os.path.join(raw, "2", "wt_eeeeee"); j = json.load(open(os.path.join(td, "judge.json"))); j["probes"] = j["probes"][:10]; json.dump(j, open(os.path.join(td, "judge.json"), "w"))
    subprocess.check_call([sys.executable, os.path.join(HERE, "score.py"), "--raw", raw, "--out", res_p], stdout=subprocess.DEVNULL)
    res = json.load(open(res_p)); assert res["table"][1]["scored"] is False and "C:<20 graded probes (10)" in res["table"][1]["void"], res["table"][1]
    return res["verdicts"]

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--target"); ap.add_argument("--out", default=os.path.join(HERE, "selftest_out")); a = ap.parse_args()
    per, tot = part1(); n_probes, n_facts, dist = part2(); verdicts = part3(a.out)
    dry = None
    if a.target and os.path.isdir(a.target):
        r = subprocess.run([sys.executable, os.path.join(HERE, "run_task.py"), "--arm", "C", "--run", 0, "--target", a.target, "--out-root", os.path.join(a.out, "dry"), "--dry-run"] if False else
                           [sys.executable, os.path.join(HERE, "run_task.py"), "--arm", "C", "--run", "0", "--target", a.target, "--out-root", os.path.join(a.out, "dry"), "--dry-run"],
                           capture_output=True, text=True)
        assert r.returncode == 0 and "GATE OK" in r.stdout, r.stdout + r.stderr
        m = json.load(open(glob.glob(os.path.join(a.out, "dry", "0", "wt_*", "manifest.json"))[0]))
        s = json.load(open(glob.glob(os.path.join(a.out, "dry", "0", "wt_*", "work", ".claude", "settings.json"))[0]))
        assert "UserPromptSubmit" not in s["hooks"] and "D037_BUDGET_CHARS=6000" in s["hooks"]["SessionStart"][0]["hooks"][0]["command"], s
        assert not os.path.exists(os.path.join(os.path.dirname(glob.glob(os.path.join(a.out, "dry", "0", "wt_*", "work"))[0]), "judge_view"))
        g = subprocess.run(["git", "-C", glob.glob(os.path.join(a.out, "dry", "0", "wt_*", "work"))[0], "ls-files"], capture_output=True, text=True).stdout.split()
        assert not any(p.startswith(".claude") or p == "CLAUDE.md" for p in g), "arm-revealing files are tracked by git"
        dry = {"target": m["target"], "copied": m["target_copied_files"], "gate": m["dry_run_gate"]["rc"], "hooks_installed": len(m["hooks"]), "git_tracked": len(g)}
    print(json.dumps({"extractor_per_transcript": per, "extractor_totals": tot, "scheduler_sim": {"probes": n_probes, "facts": n_facts, "by_lag_bucket_class": {str(k): v for k, v in dist.items()}},
                      "scorer_synthetic_verdicts": verdicts, "dry_run": dry}, indent=1))
    print("ALL CHECKS PASSED (offline; no tokens)")

if __name__ == "__main__": main()
