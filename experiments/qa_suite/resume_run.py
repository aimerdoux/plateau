"""experiments.qa_suite.resume_run — resume-aware, cost-bounded paid runner.

This is the FINISH driver for the QA accuracy-under-compression bench. It differs from
``run.py`` in three ways that matter for a resumed paid run:

  1. RESUME — it reads any already-written per-item records in ``items.jsonl`` and runs
     ONLY the missing ``(item_index, arm)`` pairs, so a partially-completed paid suite is
     not re-paid from scratch (no double-spend on the 11 GSM8K items already logged).
  2. COST GUARD — every paid ``claude -p`` reply's REAL usage is tallied; if the cumulative
     *billed-new* tokens (input + output + cache_creation, summed across THIS resume) would
     cross ``--budget`` it stops cleanly and writes a PARTIAL verdict with the real numbers
     gathered so far. cache_read is logged but not counted against the budget (same cached
     bytes re-read, not newly billed context).
  3. HONEST VERDICT — the final verdict is computed from the FULL merged log (recovered +
     new), and records exactly how many items were reused vs newly run.

Same collapse path, same scorers, same prompts as the harness — it imports them directly.
"""
from __future__ import annotations

import json
import os
import sys
import time

from plateau.driver import _tok
from experiments.qa_suite import harness as H
from experiments.qa_suite import datasets as ds


METER = "/Users/geniex/wavex-os/.plateau-agency/meters/qa-bench.jsonl"


def _meter(rec: dict):
    rec = {"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), **rec}
    try:
        with open(METER, "a") as f:
            f.write(json.dumps(rec) + "\n")
    except Exception:
        pass


def _read_existing(log_path: str) -> dict:
    """Return {(i, arm): record} for already-logged items that look like REAL paid items
    (secs > 0 — the mock backend writes secs == 0.0, so mock smoke rows are ignored and
    will be overwritten by a real run)."""
    done = {}
    if not os.path.isfile(log_path):
        return done
    for line in open(log_path):
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
        except Exception:
            continue
        if r.get("secs", 0) and r.get("secs", 0) > 0:  # real paid row
            done[(r["i"], r["arm"])] = r
    return done


def run(suite: str, n: int, *, out_dir: str, seed: int, budget_tok: int) -> dict:
    spec = H.SUITES[suite]
    items = spec["load"](n, seed=seed)
    sdir = os.path.join(out_dir, suite)
    os.makedirs(os.path.join(sdir, "raw"), exist_ok=True)
    log_path = os.path.join(sdir, "items.jsonl")

    recovered = _read_existing(log_path)
    n_recovered = len(recovered)

    # constant per-arm conditioning payload size (measure once on item 0)
    payload_tok = {}
    for arm in ("baseline", "plateau"):
        payload_tok[arm] = _tok(spec["prompt"](items[0], arm)) - _tok(
            H._question_only(suite, items[0]))

    # reset the harness real-cost meter; we accumulate across this resume
    for k in H.COST:
        H.COST[k] = 0 if k != "usd" else 0.0
    billed_new = 0  # input + output + cache_creation accumulated THIS resume
    n_new = 0
    stopped_early = False

    # merge store: start from recovered, fill in as we go
    records = dict(recovered)

    for idx, item in enumerate(items):
        for arm in ("baseline", "plateau"):
            if (idx, arm) in records:
                continue  # reuse recovered paid row — no re-spend
            # budget guard BEFORE spending: stop if we are at/over budget
            if billed_new >= budget_tok:
                stopped_early = True
                break
            prompt = spec["prompt"](item, arm)
            before = (H.COST["input"], H.COST["output"], H.COST["cache_creation"])
            t0 = time.time()
            reply = H._metered_claude_p(prompt, sdir)
            dt = time.time() - t0
            after = (H.COST["input"], H.COST["output"], H.COST["cache_creation"])
            call_billed = (after[0] - before[0]) + (after[1] - before[1]) + (
                after[2] - before[2])
            billed_new += call_billed
            n_new += 1
            sc = spec["score"](reply, item)
            pred = spec["extract"](reply, item)
            rec = {"i": idx, "arm": arm, "question": item["question"][:200],
                   "gold": item.get("gold"), "pred": pred, "correct": sc,
                   "prompt_tok": _tok(prompt), "reply_tok": _tok(reply or ""),
                   "secs": round(dt, 2)}
            records[(idx, arm)] = rec
            with open(os.path.join(sdir, "raw", f"{suite}_{idx}_{arm}.txt"), "w") as rf:
                rf.write("PROMPT:\n" + prompt + "\n\n=== REPLY ===\n" + (reply or ""))
            print(f"  [{suite}] item {idx+1}/{len(items)} {arm:8s} pred={pred} "
                  f"gold={item.get('gold')} {'OK' if sc else 'X'} "
                  f"billed_new={billed_new}", file=sys.stderr)
            if n_new % 10 == 0:
                _meter({"step": f"{suite}-progress", "new_calls": n_new,
                        "billed_new_tok": billed_new, "usd": round(H.COST["usd"], 2)})
        if stopped_early:
            break

    # rewrite the merged log in index/arm order (recovered + new, deduped)
    with open(log_path, "w") as logf:
        for idx in range(len(items)):
            for arm in ("baseline", "plateau"):
                if (idx, arm) in records:
                    logf.write(json.dumps(records[(idx, arm)]) + "\n")

    # tally accuracy from the FULL merged log (only over items where BOTH arms present,
    # so the two arms are compared on the same item set — honest paired accuracy)
    complete = [idx for idx in range(len(items))
                if (idx, "baseline") in records and (idx, "plateau") in records]
    base_correct = sum(records[(i, "baseline")]["correct"] for i in complete)
    plat_correct = sum(records[(i, "plateau")]["correct"] for i in complete)
    n_scored = len(complete)
    base_acc = base_correct / max(1, n_scored)
    plat_acc = plat_correct / max(1, n_scored)
    comp = 1.0 - (payload_tok["plateau"] / max(1, payload_tok["baseline"]))

    verdict = {
        "suite": suite, "n_requested": n, "n_scored": n_scored,
        "backend": "claude_p", "seed": seed, "metric": spec["metric"],
        "baseline_accuracy": round(base_acc, 4),
        "plateau_accuracy": round(plat_acc, 4),
        "accuracy_delta": round(plat_acc - base_acc, 4),
        "baseline_payload_tok": payload_tok["baseline"],
        "plateau_payload_tok": payload_tok["plateau"],
        "compression_pct": round(100.0 * comp, 1),
        "baseline_correct": base_correct, "plateau_correct": plat_correct,
        "items_recovered": n_recovered // 2, "items_run_this_resume": n_new // 2,
        "stopped_early_on_budget": stopped_early,
        "real_cost_this_resume": {
            "calls": H.COST["calls"], "input_tokens": H.COST["input"],
            "output_tokens": H.COST["output"], "cache_read_tokens": H.COST["cache_read"],
            "cache_creation_tokens": H.COST["cache_creation"],
            "billed_new_tokens": billed_new,
            "total_tokens_incl_cache": (H.COST["input"] + H.COST["output"]
                                        + H.COST["cache_read"] + H.COST["cache_creation"]),
            "total_cost_usd": round(H.COST["usd"], 4)},
        "log": os.path.relpath(log_path, H.ROOT),
        "reproduce": (f"PYTHONPATH={H.ROOT}/plateau python -m experiments.qa_suite.run "
                      f"--suite {suite} --n {n} --go"),
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    with open(os.path.join(sdir, "verdict.json"), "w") as f:
        json.dump(verdict, f, indent=2)
    return verdict


def _arg(flag, default=None):
    if flag in sys.argv:
        i = sys.argv.index(flag)
        return sys.argv[i + 1] if i + 1 < len(sys.argv) else default
    return default


def main():
    suite = _arg("--suite", "gsm8k")
    n = int(_arg("--n", "50"))
    seed = int(_arg("--seed", "0"))
    out_dir = _arg("--out", H.OUT_DEFAULT)
    budget = int(_arg("--budget", "1500000"))
    _meter({"step": f"{suite}-resume-start", "n": n, "budget_tok": budget})
    t0 = time.time()
    v = run(suite, n, out_dir=out_dir, seed=seed, budget_tok=budget)
    v["wall_secs"] = round(time.time() - t0, 1)
    with open(os.path.join(out_dir, suite, "verdict.json"), "w") as f:
        json.dump(v, f, indent=2)
    _meter({"step": f"{suite}-resume-done", "n_scored": v["n_scored"],
            "base_acc": v["baseline_accuracy"], "plat_acc": v["plateau_accuracy"],
            "billed_new_tok": v["real_cost_this_resume"]["billed_new_tokens"],
            "usd": v["real_cost_this_resume"]["total_cost_usd"]})
    print(json.dumps(v, indent=2))


if __name__ == "__main__":
    main()
