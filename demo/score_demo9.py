"""demo9 (D-037) scorer — reads sealed records, applies the locked rule, reproduces verdict.

Run AFTER run_demo9 seals. Metrics (demo9_prereg.md):
  primary   novel-verified yield  = gate-passing tasks whose origin is an Anomaly / all passing
  secondary rounds-to-detection   = round the seeded contradiction is first NAMED, per arm
  guardrail equal non-abduction budget; abductions <= wallet

Verdict:
  WIN         graph yield > 0 AND equal budget (+/-1) AND every novel task's discriminator
              genuinely failed pre-injection (guaranteed by triage's must-fail rule)
  NULL        equal budget but graph yield == 0 (index helps read a run, abduction adds no
              verified work)
  REFUTED-as-runaway  abductions > wallet, or an injected discriminator passed on inject
  UNSCORABLE  budgets unequal (the comparison is confounded — void, not scored)

Usage: python demo/score_demo9.py [--verify]
"""
from __future__ import annotations

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from plateau.integrity import Manifest, file_hash                 # noqa: E402

RAW = os.path.join(ROOT, "demo", "raw9")
VERDICT = os.path.join(ROOT, "demo", "verdict9.json")
PREREG = os.path.join(ROOT, "demo", "demo9_prereg.md")


def _ratchet_reached_fix(res: dict) -> bool:
    """The ratchet solves the composition iff P3 (run must survive negatives) ever passed.
    If it did, any abduction-injected fix in the graph arm is REDUNDANT — work the ratchet
    reached on its own — which is the prereg's P2 NULL, not a win."""
    return any(r.get("task") == "P3" and r.get("passed") for r in res.get("rounds", []))


def _arm_metrics(res: dict) -> dict:
    rounds = res.get("rounds", [])
    events = res.get("events", [])
    passing = [r for r in rounds if r.get("passed")]
    novel = [e for e in events if e[1] == "novel_verified"]
    contra = [e for e in events if e[1] == "contradiction_detected"]
    return {
        "task_dispatches": res.get("task_dispatches", 0),
        "abductions": res.get("abductions", 0),
        "passing_tasks": len(passing),
        "novel_verified": len(novel),
        "novel_verified_yield": round(len(novel) / len(passing), 3) if passing else 0.0,
        "rounds_to_contradiction": (min(e[0] for e in contra) if contra else None),
        "injected": [e[2] for e in events if e[1] == "injected"],
    }


def score(records: dict) -> dict:
    res = records["results"]
    wallet = records["abduction_wallet"]
    ratchet = _arm_metrics(res["ratchet"]) if "ratchet" in res else {}
    graph = _arm_metrics(res["graph"]) if "graph" in res else {}

    equal_budget = abs(ratchet.get("task_dispatches", 0) -
                       graph.get("task_dispatches", 0)) <= 1
    runaway = graph.get("abductions", 0) > wallet

    if runaway:
        verdict = "REFUTED-as-runaway"
        why = f"abductions {graph['abductions']} exceeded wallet {wallet}"
    elif not equal_budget:
        verdict = "UNSCORABLE"
        why = (f"non-abduction budgets differ by >1 "
               f"({ratchet.get('task_dispatches')} vs {graph.get('task_dispatches')}) — "
               "comparison confounded, void")
    elif graph.get("novel_verified_yield", 0) > 0 and not _ratchet_reached_fix(res["ratchet"]):
        verdict = "WIN"
        why = (f"graph arm produced {graph['novel_verified']} novel-verified task(s) "
               f"(yield {graph['novel_verified_yield']}) that the ratchet did NOT reach "
               "(its P3 never passed) — abduction found work decomposition did not")
    elif graph.get("novel_verified_yield", 0) > 0 and _ratchet_reached_fix(res["ratchet"]):
        verdict = "NULL-redundant"
        why = ("graph arm produced novel-verified work, but the RATCHET reached the same "
               "root-cause fix on its own (its P3 passed). Abduction added no work "
               "decomposition could not — the P2 NULL: the index is a monitoring aid, "
               "not a discovery one, on this mission")
    else:
        verdict = "NULL"
        why = ("graph arm added no novel-verified work at equal budget; "
               f"contradiction {'NAMED at round '+str(graph.get('rounds_to_contradiction')) if graph.get('rounds_to_contradiction') else 'not named'} "
               f"(ratchet names it: {ratchet.get('rounds_to_contradiction')})")

    return {"verdict": verdict, "why": why, "equal_budget": equal_budget,
            "ratchet_reached_fix": _ratchet_reached_fix(res["ratchet"]),
            "ratchet": ratchet, "graph": graph,
            "secondary_rounds_to_detection": {
                "graph": graph.get("rounds_to_contradiction"),
                "ratchet": ratchet.get("rounds_to_contradiction")}}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--verify", action="store_true")
    a = ap.parse_args()
    records = json.load(open(os.path.join(RAW, "records.json")))
    result = score(records)
    result["prereg_sha256"] = file_hash(PREREG)
    result["sealed_prereg_sha256"] = records.get("prereg_sha256")

    man_path = os.path.join(RAW, "manifest.jsonl")
    if os.path.exists(man_path):
        m = Manifest(man_path)
        ok_chain, _ = m.verify_chain()
        ok_files, bad = m.verify_files(RAW)
        result["integrity"] = {"chain_ok": ok_chain, "files_ok": ok_files, "bad": bad[:3]}

    if a.verify:
        prior = json.load(open(VERDICT)) if os.path.exists(VERDICT) else None
        same = prior and prior.get("verdict") == result["verdict"]
        ig = result.get("integrity", {})
        if ig.get("chain_ok") and ig.get("files_ok") and same:
            print(f"RECOMPUTE_OK — verdict {result['verdict']} reproduces; seal verifies")
        else:
            print(f"RECOMPUTE_FAILED integrity={ig} verdict_reproduces={same}")
            return 1
    else:
        json.dump(result, open(VERDICT, "w"), indent=2, sort_keys=True)

    print(f"  VERDICT={result['verdict']} — {result['why']}")
    print(f"  ratchet: {result['ratchet']}")
    print(f"  graph:   {result['graph']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
