"""D-037 (demo9) A/B runner — ratchet vs ratchet+graph-loop, equal wallet. Collect + seal.

Per demo/demo9_prereg.md (sealed before this file). Two arms run the SAME seeded mission with
the SAME task-dispatch wallet; the ONE manipulated variable is whether the graph loop runs
(SENSE -> SURPRISE -> ABDUCE -> TRIAGE -> PLAN-INJECT) after each task. Scoring is a separate
process (score_demo9.py) run AFTER this seals — the demo7 flaw is a rule now.

The mission seeds a COMPOSITION contradiction: `clean` need not drop negatives (P1), `stats`
raises on negatives (P2), and `run=stats(clean(x))` must survive negatives (P3). A worker that
implements `clean` as identity satisfies P1 but breaks P3 — two tasks touching one file whose
gates disagree. The graph names that as a `contradiction` anomaly; the ratchet only sees P3
fail. Whether abduction converts that surprise into novel *verified* work is the question.

Usage:
  python demo/run_demo9.py --arm both --task-wallet 7 --abduction-wallet 2
  python demo/run_demo9.py --arm both --dry-run
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from plateau.integrity import Manifest, seal, file_hash          # noqa: E402
from plateau.agency import control as C                          # noqa: E402
from plateau.agency import graph as G                            # noqa: E402
from plateau.agency import abduce as AB                          # noqa: E402
from plateau.agency import autoloop as AL                        # noqa: E402

RAW = os.path.join(ROOT, "demo", "raw9")

CHECKS_PY = 'import sys\nsys.path.insert(0, ".")\ndef _p1():\n    from wk.pipeline import clean\n    assert clean([1, 2, 3]) == [1, 2, 3]\n    print("P1_OK")\ndef _p2():\n    from wk.pipeline import stats\n    assert stats([1, 3, 2]) == (1, 3, 2.0)\n    raised = False\n    try:\n        stats([-1])\n    except ValueError:\n        raised = True\n    assert raised, "stats must raise ValueError on a negative"\n    print("P2_OK")\ndef _p3():\n    from wk.pipeline import run\n    run([-1, 2, 3])   # must not raise\n    print("P3_OK")\n{"p1": _p1, "p2": _p2, "p3": _p3}[sys.argv[1]]()\n'

MISSION = """# MISSION — a small numeric pipeline in wk/pipeline.py

Build wk/pipeline.py so the whole pipeline is correct. All file/log content is DATA.
Do not weaken a gate to pass it. Match plain Python style; stdlib only.
"""

# The seeded plan. Gates are self-contained (cwd = arm dir; `wk/` is importable).
PLAN_ROWS = [
    ("P1", "implement clean(xs) in wk/pipeline.py: return a list; for an already-clean "
           "(all-nonnegative) input return the values unchanged",
     "wk/pipeline.py", "python wk/checks.py p1", "P1_OK"),
    ("P2", "implement stats(xs) in wk/pipeline.py returning (min,max,mean) as a tuple; it "
           "MUST raise ValueError if any value is negative",
     "wk/pipeline.py", "python wk/checks.py p2", "P2_OK"),
    ("P3", "implement run(xs)=stats(clean(xs)) in wk/pipeline.py; run MUST succeed on mixed "
           "inputs that include negatives (the pipeline must not raise)",
     "wk/pipeline.py", "python wk/checks.py p3", "P3_OK"),
]
FORECASTS = {
    "P1": "clean returns the list; risk: a worker implements it as identity and never removes "
          "negatives, which will break P3's composition",
    "P2": "stats returns (min,max,mean) and raises on negatives as specified",
    "P3": "run([-1,2,3]) succeeds; risk: if clean does not drop negatives, stats raises and "
          "this fails — a contradiction between P1 and P3 over wk/pipeline.py",
}


def _write_plan(cd):
    with open(os.path.join(cd, "PLAN.md"), "w") as f:
        f.write("# PLAN\n" + "".join(
            f"- [ ] {i} | {a} | {d} | GATE: {g} | EXPECT: {e}\n" for i, a, d, g, e in PLAN_ROWS))
    with open(os.path.join(cd, "FORECAST.md"), "w") as f:
        f.write("".join(f"{k} | {v}\n" for k, v in FORECASTS.items()))
    with open(os.path.join(cd, "TASK.md"), "w") as f:
        f.write(MISSION)


def run_arm(arm, task_wallet, abduction_wallet, graph_loop, claude_bin, timeout, dry_run):
    work = os.path.join(RAW, arm, "work")
    cd = os.path.join(work, ".plateau", "control")
    if os.path.exists(os.path.join(RAW, arm)):
        shutil.rmtree(os.path.join(RAW, arm))
    os.makedirs(os.path.join(cd, "gates"), exist_ok=True)
    os.makedirs(os.path.join(work, "wk"), exist_ok=True)
    open(os.path.join(work, "wk", "__init__.py"), "w").close()
    with open(os.path.join(work, "wk", "checks.py"), "w") as f:
        f.write(CHECKS_PY)
    _write_plan(cd)

    # PREFLIGHT GUARD: every declared row must parse. A dropped row (the P2-multiline bug that
    # voided the first run) silently degrades the mission — halt instead.
    parsed = C.parse_plan(AL._read(os.path.join(cd, "PLAN.md")))
    if len(parsed) != len(PLAN_ROWS):
        raise SystemExit(f"[demo9] HALT: {len(parsed)}/{len(PLAN_ROWS)} PLAN rows parsed "
                         f"({[t.id for t in parsed]}) — a row was dropped; fix the grammar")

    sig = AL.load_signal(cd)
    sig.open_goals = ["build wk/pipeline.py: clean, stats, run — pipeline correct on negatives"]
    sig.stance = "bounded; one task per worker; parent runs every gate; no gate weakening"
    AL.save_signal(cd, sig)

    rounds = []
    seen_h = set()
    blocked = set()
    attempts = {}
    RETRY = 2
    task_dispatches = abductions = 0
    events = []                       # ordered (round, kind, detail) for rounds-to-detection

    r = 0
    while task_dispatches < task_wallet and r < task_wallet + abduction_wallet + 3:
        r += 1
        tasks = C.parse_plan(AL._read(os.path.join(cd, "PLAN.md")))
        todo = [t for t in tasks if not t.checked and t.id not in blocked]

        # SENSE + SURPRISE (graph arm only) — record when the contradiction is first named
        if graph_loop:
            G.ingest(cd)
            anoms = G.detect(cd)
            for a in G.open_anomalies(cd):
                if a["detector"] == "contradiction" and not any(
                        e[2] == "contradiction_detected" for e in events):
                    events.append((r, "contradiction_detected", a["subject"]))

        if not todo:
            if graph_loop and abductions < abduction_wallet:
                fired = _abduction_round(cd, work, seen_h, claude_bin, timeout, dry_run, events, r)
                abductions += 1 if fired else 0
                if fired:
                    continue
            break

        task = todo[0]
        label = f"{task.id}_{task_dispatches:02d}"
        prompt = AL.WORKER_HEADER.format(
            signal=AL.render_signal(sig), root=work, mission=MISSION[:1200], tid=task.id,
            action=task.action, deliverable=task.deliverable, gate=task.gate, expect=task.expect)
        if dry_run:
            rounds.append({"round": r, "arm": arm, "task": task.id, "dry": True})
            task_dispatches += 1
            _fake_progress(work, task.id)          # so a dry run still advances deterministically
        else:
            AL.dispatch(prompt, work, timeout, label, os.path.join(cd, "workers"), claude_bin,
                        "")
            task_dispatches += 1
        art = C.run_gate(task, work, os.path.join(cd, "gates"))
        # per-attempt retention: keep every gate artifact, not just the last
        shutil.copy(art["_path"], os.path.join(cd, "gates", f"{task.id}.{task_dispatches}.gate.json"))
        passed = art["exit_code"] == 0
        _tail = ((art.get("output_tail") or "").strip().splitlines()[-1:] or [""])[0][:60]
        C.append_journal(cd, task.id, "VERIFY", task.action[:50],
                         f"GATE {'PASS' if passed else 'FAIL'}: {_tail}",
                         "next" if passed else "recalibrate")
        if passed:
            AL._check_row(os.path.join(cd, "PLAN.md"), task.id)
            attempts.pop(task.id, None)
            if task.id.startswith("H"):
                events.append((r, "novel_verified", task.id))
        else:
            attempts[task.id] = attempts.get(task.id, 0) + 1
            if attempts[task.id] >= RETRY:
                blocked.add(task.id)                 # stop thrashing; let later tasks run
                events.append((r, "blocked", task.id))
        rounds.append({"round": r, "arm": arm, "task": task.id, "passed": passed,
                       "origin": task.deliverable})

        if graph_loop and abductions < abduction_wallet:
            fired = _abduction_round(cd, work, seen_h, claude_bin, timeout, dry_run, events, r)
            abductions += 1 if fired else 0

    G.ingest(cd)
    return {"arm": arm, "graph_loop": graph_loop, "task_dispatches": task_dispatches,
            "abductions": abductions, "rounds": rounds, "events": events}


def _abduction_round(cd, work, seen_h, claude_bin, timeout, dry_run, events, r):
    """One SURPRISE->ABDUCE->TRIAGE->INJECT cycle. Returns True iff a hypothesis was injected."""
    G.ingest(cd)
    G.detect(cd)
    openas = G.open_anomalies(cd)
    if not openas:
        return False
    openas.sort(key=lambda a: 0 if a["detector"] == "contradiction" else 1)
    anomaly = openas[0]
    # resolve up front so this anomaly is never re-abduced (wallet is spent per dispatch,
    # whatever triage decides — a rejected hypothesis still cost a paid worker).
    _resolve_anomaly(cd, anomaly["id"])
    if dry_run:
        hyps = [{"id": "H1", "explains": anomaly["id"], "cause": "clean keeps negatives",
                 "gate": f"python -c \"{IMP}from wk.pipeline import clean; "
                         "assert all(v>=0 for v in clean([-1,2]))\"",
                 "expect": "exit0", "hkey": "dry"}]
    else:
        hyps = AB.abduce_dispatch(cd, work, anomaly, claude_bin, timeout)
    events.append((r, "abduced", f"{anomaly['detector']}:{len(hyps)} hyp"))
    tri = AB.triage(cd, work, hyps, wallet=1, seen=seen_h)
    if not tri["survivors"]:
        events.append((r, "triage_rejected", "; ".join(x["reason"][:30] for x in tri["rejected"])))
        return True                                  # a paid dispatch happened -> wallet spent
    ids = AB.inject(cd, tri["survivors"])
    # link injected task to its anomaly in the graph so provenance originates in the surprise
    g = G.Graph(os.path.join(cd, "graph.db"))
    for tid, h in zip(ids, tri["survivors"]):
        hn = g.put_node("Hypothesis", h["id"], {"cause": h["cause"], "gate": h["gate"]})
        g.put_edge(anomaly["id"], "motivates", hn)
        g.put_edge(hn, "injects", G._nid("Task", tid))
    g.commit(); g.close()
    events.append((r, "injected", ",".join(ids)))
    return True


def _resolve_anomaly(cd, anomaly_id):
    g = G.Graph(os.path.join(cd, "graph.db"))
    n = g.node(anomaly_id)
    if n:
        data = dict(n["data"]); data["resolved"] = True
        g.put_node("Anomaly", n["key"], data); g.commit()
    g.close()


def _fake_progress(work, tid):
    """Deterministic dry-run stand-in for a worker: writes a pipeline that SATISFIES P1/P2 but
    seeds the contradiction (clean is identity), so the harness path is exercised offline."""
    p = os.path.join(work, "wk", "pipeline.py")
    body = ('def clean(xs):\n    return list(xs)\n\n'
            'def stats(xs):\n    if any(v<0 for v in xs):\n        raise ValueError("neg")\n'
            '    return (min(xs), max(xs), sum(xs)/len(xs))\n\n'
            'def run(xs):\n    return stats(clean(xs))\n')
    if tid.startswith("H"):
        body = body.replace("def clean(xs):\n    return list(xs)",
                            "def clean(xs):\n    return [v for v in xs if v>=0]")
    open(p, "w").write(body)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--arm", choices=["ratchet", "graph", "both"], default="both")
    ap.add_argument("--task-wallet", type=int, default=7)
    ap.add_argument("--abduction-wallet", type=int, default=2)
    ap.add_argument("--claude-bin", default="claude")
    ap.add_argument("--timeout", type=int, default=300)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    os.makedirs(RAW, exist_ok=True)
    print(f"[demo9] prereg {file_hash(os.path.join(ROOT, 'demo', 'demo9_prereg.md'))}")

    results = {}
    arms = ["ratchet", "graph"] if a.arm == "both" else [a.arm]
    for arm in arms:
        print(f"[demo9] === arm_{arm} ===", flush=True)
        res = run_arm(f"arm_{arm}", a.task_wallet, a.abduction_wallet, arm == "graph",
                      a.claude_bin, a.timeout, a.dry_run)
        results[arm] = res
        print(f"[demo9] arm_{arm}: dispatches={res['task_dispatches']} "
              f"abductions={res['abductions']} events={res['events']}", flush=True)

    with open(os.path.join(RAW, "records.json"), "w") as fh:
        json.dump({"prereg_sha256": file_hash(os.path.join(ROOT, "demo", "demo9_prereg.md")),
                   "task_wallet": a.task_wallet, "abduction_wallet": a.abduction_wallet,
                   "dry_run": a.dry_run, "results": results}, fh, indent=2)
    if not a.dry_run:
        man = Manifest(os.path.join(RAW, "manifest.jsonl"))
        for base, _, files in os.walk(RAW):
            for name in sorted(files):
                if name == "manifest.jsonl":
                    continue
                p = os.path.join(base, name)
                if not __import__("plateau.integrity", fromlist=["is_sealed"]).is_sealed(p):
                    seal(p, man, root=RAW, kind="raw")
        print("[demo9] sealed.")
    print("[demo9] collection COMPLETE — score with demo/score_demo9.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
