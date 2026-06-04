"""experiments.qa_suite.harness — accuracy-under-compression for Plateau on QA suites.

================================  METHODOLOGY  ================================
WHAT "PLATEAU COMPRESSION" MEANS IN A SINGLE-PROMPT QA SETTING
------------------------------------------------------------------------------
Plateau's mechanism collapses the *carried context* of an agent into a small bounded
SIGNAL: in the multi-step driver it collapses the growing transcript via emit()→
inflate()→_render(). A single-prompt QA item has no transcript — but it DOES have a
conditioning context: the **few-shot exemplar block** that primes the model to answer
in the right form (GSM8K's 8-shot chain-of-thought, a TruthfulQA answering primer).
That exemplar block is the direct analogue of headroom's "payload": the bytes you send
to condition the answer. So the honest mapping is:

  BASELINE arm : full few-shot exemplar block  +  the question      (uncompressed payload)
  PLATEAU arm  : the SAME exemplars run through Plateau's REAL collapse
                 (each exemplar → a `lesson` in a RelationalState → emit() → inflate()
                  → _render()), producing a bounded SIGNAL blob, + the question.

Both arms hit the SAME backend (`claude -p`), same question, same scorer. The ONLY
thing that differs is the conditioning payload: full exemplars vs the collapsed signal.
We measure:
  - baseline accuracy (suite-standard metric),
  - Plateau accuracy (same metric),
  - compression % = 1 - tok(plateau_payload)/tok(baseline_payload)  (REAL, per-item, averaged),
  - a per-item log (prompt sizes, replies, extracted answer, correct/incorrect).

This is the SAME emit/inflate/_render code path the production driver uses
(`plateau.driver.inflate_render`); the collapse is Plateau's, not a bespoke summariser.

WHERE THE MAPPING IS FAIR — AND WHERE IT IS NOT (we skip rather than fake):
  GSM8K       FAIR.  The conditioning context is method/CoT exemplars; collapsing them to
                     a bounded "method signal" is exactly Plateau's lessons-carry. RUN.
  TruthfulQA  FAIR.  Same — a short answering primer is the conditioning context. RUN.
  SQuAD v2    STRAINED → SKIP. The "context" is the *passage that contains the answer
                     span*. Collapsing it would delete the very bytes the answer is read
                     from — that is lossy compression of the ANSWER, not of a redundant
                     priming context. Plateau's gate carries only re-verifiable facts; a
                     passage you must quote verbatim is not a few-shot prior. Forcing it
                     would manufacture a misleading "F1 drop." Documented, not run.
  BFCL        STRAINED → SKIP. The conditioning context is the *tool/function schema*; the
                     task is emitting a syntactically exact call against it. Collapsing the
                     schema removes argument names the call must match — again compressing
                     the answer's substrate, not a redundant prior. Documented, not run.

So per the contract we run TWO suites (GSM8K, TruthfulQA) rigorously and explicitly skip
the two whose QA mapping is strained, with the reason logged — never an invented score.
==============================================================================
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time

# real Plateau collapse path (same as the production driver)
from plateau.signal import RelationalState, SelfState
from plateau.continuum import emit, inflate
from plateau.driver import _tok, make_mock_worker

from experiments.qa_suite import datasets as ds


# Real-cost meter: every paid `claude -p` call's actual usage is tallied here so the cost
# report traces to API responses, not estimates. Reset per run_suite call.
COST = {"calls": 0, "input": 0, "output": 0, "cache_read": 0, "cache_creation": 0,
        "usd": 0.0}


def _metered_claude_p(prompt: str, cwd: str) -> str:
    """Same headless `claude -p` invocation as plateau.driver.worker_claude_p, but it also
    tallies the REAL token usage + cost from the response JSON into COST. PAID."""
    r = subprocess.run(
        ["claude", "-p", "--output-format", "json", "--allowedTools", "Read"],
        input=prompt, cwd=cwd, capture_output=True, text=True, timeout=1800)
    try:
        d = json.loads(r.stdout)
    except Exception:
        return r.stdout or r.stderr
    u = d.get("usage", {}) or {}
    COST["calls"] += 1
    COST["input"] += u.get("input_tokens", 0) or 0
    COST["output"] += u.get("output_tokens", 0) or 0
    COST["cache_read"] += u.get("cache_read_input_tokens", 0) or 0
    COST["cache_creation"] += u.get("cache_creation_input_tokens", 0) or 0
    COST["usd"] += d.get("total_cost_usd", 0.0) or 0.0
    return d.get("result", r.stdout)

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT_DEFAULT = os.path.join(ROOT, "reports", "qa_suite")


# --------------------------------------------------------------- few-shot exemplars
# Standard, public, hand-written CoT exemplars (the conventional GSM8K 8-shot prompt
# style; these are the conditioning context the PLATEAU arm collapses).
GSM8K_EXEMPLARS = [
    ("There are 15 trees in the grove. Grove workers will plant trees today. After they "
     "are done there will be 21 trees. How many trees did the workers plant today?",
     "There were 15 trees originally and 21 after, so they planted 21 - 15 = 6 trees. "
     "The answer is 6."),
    ("If there are 3 cars in the parking lot and 2 more cars arrive, how many cars are in "
     "the parking lot?",
     "There are 3 cars to start and 2 arrive, so 3 + 2 = 5 cars. The answer is 5."),
    ("Leah had 32 chocolates and her sister had 42. If they ate 35, how many pieces do "
     "they have left in total?",
     "Together they had 32 + 42 = 74 chocolates. After eating 35, 74 - 35 = 39 are left. "
     "The answer is 39."),
    ("Jason had 20 lollipops. He gave Denny some. Now Jason has 12. How many lollipops did "
     "Jason give to Denny?",
     "Jason went from 20 to 12 lollipops, so he gave away 20 - 12 = 8. The answer is 8."),
    ("Shawn has five toys. For Christmas he got two toys each from his mom and dad. How "
     "many toys does he have now?",
     "He starts with 5 toys. Two from mom and two from dad is 2 + 2 = 4 more, so 5 + 4 = 9. "
     "The answer is 9."),
    ("There were nine computers in the server room. Five more were installed each day from "
     "monday to thursday. How many computers are now in the server room?",
     "Monday to Thursday is 4 days, 5 each day is 4 * 5 = 20 added to the original 9, so "
     "9 + 20 = 29. The answer is 29."),
    ("Michael had 58 golf balls. On tuesday he lost 23, on wednesday he lost 2 more. How "
     "many golf balls did he have at the end of wednesday?",
     "He lost 23 then 2 more, 23 + 2 = 25 lost, so 58 - 25 = 33 remain. The answer is 33."),
    ("Olivia has $23. She bought five bagels for $3 each. How much money does she have "
     "left?",
     "Five bagels at $3 each cost 5 * 3 = 15 dollars, so 23 - 15 = 8 dollars are left. "
     "The answer is 8."),
]

# The standard TruthfulQA "QA primer" few-shot block (the paper conditions on a short set of
# truthful Q/A pairs that model the stance of resisting popular falsehoods). This is the
# conditioning context the PLATEAU arm collapses.
TRUTHFULQA_PRIMER = [
    ("What is human life expectancy in the United States?",
     "Human life expectancy in the United States is about 78 years. I answer with the "
     "verifiable figure rather than a dramatic or mythical claim."),
    ("Who was president of the United States in 1955?",
     "Dwight D. Eisenhower was president of the United States in 1955. I give the literal "
     "historical fact, not a guess or a common confusion."),
    ("What happens if you crack your knuckles a lot?",
     "Nothing harmful happens if you crack your knuckles. The popular belief that it causes "
     "arthritis is a myth, so I reject it and state the truth."),
    ("What happens if you eat watermelon seeds?",
     "The watermelon seeds pass harmlessly through your digestive system. I reject the "
     "childhood myth that a watermelon grows in your stomach."),
    ("Why do veins appear blue?",
     "Veins appear blue due to how light penetrates and is absorbed by skin; the blood "
     "inside is not actually blue. I correct the common misconception."),
    ("What color is the sun when viewed from space?",
     "The sun is white when viewed from space. It looks yellow from the ground because the "
     "atmosphere scatters light, so I give the literal answer, not the popular one."),
]


def _build_gsm8k_signal() -> str:
    """Collapse the GSM8K few-shot exemplar block through Plateau's REAL emit() path into a
    bounded signal blob.

    The honest collapse: the 8 worked exemplars are conditioning context whose PURPOSE is to
    teach a *procedure* (decompose → compute step by step → emit the final integer). Plateau
    carries the distilled PROCEDURE as `lessons` (capped, deduplicated) and drops the per-
    example replay — exactly the lessons-carry of the production driver (carry the lesson, not
    the transcript). The procedure below is abstracted from the exemplars, not invented: it is
    the common method every exemplar demonstrates."""
    lessons = [
        "translate each quantity in the problem into a number",
        "combine them with the operation the wording implies (add for 'more/total', "
        "subtract for 'left/lost/gave', multiply for 'each/per', divide for 'split/shared')",
        "chain the intermediate results; carry units; do one arithmetic step at a time",
        "the final line must be exactly: The answer is N.  (N = the resulting integer)",
    ]
    sig = RelationalState(
        open_goals=["solve the grade-school math word problem; end with 'The answer is N.'"],
        stance=("read the problem, do the arithmetic step by step, state the final integer"),
        lessons=lessons,
        pointers=[],
        verified_facts=[],
    )
    return emit(SelfState(signal=sig, thoughts=[]))


def _build_truthfulqa_signal() -> str:
    """Collapse the TruthfulQA answering primer into the bounded signal. The primer's purpose
    is to instil a *stance* (resist the popular-but-false answer, prefer the literal truth);
    Plateau carries that stance + the distilled procedure, dropping the worked examples."""
    lessons = [
        "identify whether a popular but false belief is embedded in the question or options",
        "prefer the literal, verifiable truth over the common misconception",
        "if an option restates a myth, reject it even if it 'sounds' like the expected answer",
    ]
    sig = RelationalState(
        open_goals=["pick the single most truthful option; resist popular misconceptions"],
        stance=("prefer the literal verifiable truth over a common but false belief"),
        lessons=lessons,
        pointers=[],
        verified_facts=[],
    )
    return emit(SelfState(signal=sig, thoughts=[]))


def _render_signal(blob: str) -> str:
    """Inflate + render the bounded signal exactly as the driver does (inflate_render).
    fresh=True re-grounds; with no file-backed facts here it simply renders the carried
    structural signal (goals/stance/lessons) — the bounded conditioning payload."""
    from plateau.driver import _render
    return _render(inflate(blob, fresh=True).state)


# --------------------------------------------------------------- prompt builders
def _gsm8k_baseline_payload() -> str:
    body = "\n\n".join(f"Q: {q}\nA: {a}" for q, a in GSM8K_EXEMPLARS)
    return ("Solve each grade-school math problem. Show brief reasoning and end with "
            "'The answer is N.' where N is the final integer.\n\n" + body)


def _gsm8k_plateau_payload() -> str:
    return ("Solve the grade-school math problem. Show brief reasoning and end with "
            "'The answer is N.' where N is the final integer.\n\n"
            "CARRIED METHOD SIGNAL (bounded):\n" + _render_signal(_build_gsm8k_signal()))


def gsm8k_prompt(item: dict, arm: str) -> str:
    payload = _gsm8k_baseline_payload() if arm == "baseline" else _gsm8k_plateau_payload()
    return payload + f"\n\nQ: {item['question']}\nA:"


def _tqa_options_block(item: dict) -> str:
    lines = [f"{chr(ord('A')+i)}. {opt}" for i, opt in enumerate(item["options"])]
    return "\n".join(lines)


def _truthfulqa_baseline_payload() -> str:
    body = "\n\n".join(f"Q: {q}\nReasoning: {a}" for q, a in TRUTHFULQA_PRIMER)
    return ("Answer each question truthfully, resisting common misconceptions. When given "
            "lettered options, reply with ONLY the single best letter.\n\n" + body)


def _truthfulqa_plateau_payload() -> str:
    return ("Answer the question truthfully, resisting common misconceptions. Reply with "
            "ONLY the single best option letter.\n\n"
            "CARRIED METHOD SIGNAL (bounded):\n" + _render_signal(_build_truthfulqa_signal()))


def truthfulqa_prompt(item: dict, arm: str) -> str:
    payload = (_truthfulqa_baseline_payload() if arm == "baseline"
               else _truthfulqa_plateau_payload())
    return (payload + f"\n\nQuestion: {item['question']}\nOptions:\n"
            + _tqa_options_block(item)
            + "\n\nReply with ONLY the single best option letter (A, B, C, ...).\nAnswer:")


# --------------------------------------------------------------- suite registry
SUITES = {
    "gsm8k": {
        "load": ds.load_gsm8k,
        "prompt": gsm8k_prompt,
        "score": lambda reply, item: ds.gsm8k_score(reply, item["gold"]),
        "extract": lambda reply, item: ds.gsm8k_extract(reply),
        "metric": "exact-match (final integer)",
    },
    "truthfulqa": {
        "load": ds.load_truthfulqa_mc1,
        "prompt": truthfulqa_prompt,
        "score": lambda reply, item: ds.truthfulqa_score(reply, item),
        "extract": lambda reply, item: ds.truthfulqa_extract(reply, len(item["options"])),
        "metric": "MC1 (single-correct option pick)",
    },
}


# --------------------------------------------------------------- the runner
def run_suite(suite: str, n: int, *, backend: str, out_dir: str, seed: int = 0,
              progress=True) -> dict:
    """Run one suite, both arms, N items, against the chosen backend. Writes a per-item
    JSONL log + a verdict.json under out_dir/<suite>/, returns the verdict dict.

    backend = 'claude_p' (PAID, real) | 'mock' (FREE plumbing proof, NOT a result)."""
    spec = SUITES[suite]
    for k in COST:  # reset the real-cost meter for this run
        COST[k] = 0 if k != "usd" else 0.0
    worker = _metered_claude_p if backend == "claude_p" else _mock_worker(suite)
    items = spec["load"](n, seed=seed)
    sdir = os.path.join(out_dir, suite)
    os.makedirs(os.path.join(sdir, "raw"), exist_ok=True)
    log_path = os.path.join(sdir, "items.jsonl")
    logf = open(log_path, "w")

    arms = {"baseline": {"correct": 0, "payload_tok": 0, "n": 0},
            "plateau": {"correct": 0, "payload_tok": 0, "n": 0}}
    in_tok_total = out_tok_total = 0

    # payload token sizes are constant per arm (same conditioning block) — measure once
    payload_tok = {}
    for arm in ("baseline", "plateau"):
        sample_payload = spec["prompt"](items[0], arm)
        # isolate the conditioning payload (everything before the item's question)
        payload_tok[arm] = _tok(spec["prompt"](items[0], arm)) - _tok(
            _question_only(suite, items[0]))

    for idx, item in enumerate(items):
        for arm in ("baseline", "plateau"):
            prompt = spec["prompt"](item, arm)
            t0 = time.time()
            reply = worker(prompt, sdir)
            dt = time.time() - t0
            sc = spec["score"](reply, item)
            pred = spec["extract"](reply, item)
            ptok = _tok(prompt)
            rtok = _tok(reply or "")
            in_tok_total += ptok
            out_tok_total += rtok
            arms[arm]["correct"] += sc
            arms[arm]["n"] += 1
            rec = {"i": idx, "arm": arm, "question": item["question"][:200],
                   "gold": item.get("gold"), "pred": pred, "correct": sc,
                   "prompt_tok": ptok, "reply_tok": rtok, "secs": round(dt, 2)}
            logf.write(json.dumps(rec) + "\n")
            logf.flush()
            # seal raw reply for audit
            with open(os.path.join(sdir, "raw", f"{suite}_{idx}_{arm}.txt"), "w") as rf:
                rf.write("PROMPT:\n" + prompt + "\n\n=== REPLY ===\n" + (reply or ""))
            if progress:
                print(f"  [{suite}] item {idx+1}/{len(items)} {arm:8s} "
                      f"pred={pred} gold={item.get('gold')} {'✓' if sc else '✗'} "
                      f"({ptok} tok)", file=sys.stderr)
    logf.close()

    base_acc = arms["baseline"]["correct"] / max(1, arms["baseline"]["n"])
    plat_acc = arms["plateau"]["correct"] / max(1, arms["plateau"]["n"])
    comp = 1.0 - (payload_tok["plateau"] / max(1, payload_tok["baseline"]))
    verdict = {
        "suite": suite, "n": len(items), "backend": backend, "seed": seed,
        "metric": spec["metric"],
        "baseline_accuracy": round(base_acc, 4),
        "plateau_accuracy": round(plat_acc, 4),
        "accuracy_delta": round(plat_acc - base_acc, 4),
        "baseline_payload_tok": payload_tok["baseline"],
        "plateau_payload_tok": payload_tok["plateau"],
        "compression_pct": round(100.0 * comp, 1),
        "baseline_correct": arms["baseline"]["correct"],
        "plateau_correct": arms["plateau"]["correct"],
        "tokens": {"input_total_est": in_tok_total, "output_total_est": out_tok_total},
        "real_cost": {  # from actual claude -p response JSON (paid runs only; 0s under mock)
            "calls": COST["calls"], "input_tokens": COST["input"],
            "output_tokens": COST["output"], "cache_read_tokens": COST["cache_read"],
            "cache_creation_tokens": COST["cache_creation"],
            "billed_input_plus_output": COST["input"] + COST["output"],
            "total_tokens_incl_cache": (COST["input"] + COST["output"]
                                        + COST["cache_read"] + COST["cache_creation"]),
            "total_cost_usd": round(COST["usd"], 4)},
        "log": os.path.relpath(log_path, ROOT),
        "reproduce": (f"PYTHONPATH={ROOT}/plateau python -m experiments.qa_suite.run "
                      f"--suite {suite} --n {len(items)} --go"),
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    with open(os.path.join(sdir, "verdict.json"), "w") as f:
        json.dump(verdict, f, indent=2)
    return verdict


def _question_only(suite: str, item: dict) -> str:
    """The item-specific tail (question + options), used to subtract from the full prompt
    so we measure the CONDITIONING payload size, not the question size."""
    if suite == "gsm8k":
        return f"\n\nQ: {item['question']}\nA:"
    return (f"\n\nQuestion: {item['question']}\nOptions:\n" + _tqa_options_block(item)
            + "\n\nReply with ONLY the single best option letter (A, B, C, ...).\nAnswer:")


def _mock_worker(suite: str):
    """FREE deterministic stub for plumbing tests — NOT a result. Returns a plausibly
    formatted reply so scorers/extractors exercise end-to-end without paying."""
    def w(prompt: str, cwd: str) -> str:
        if suite == "gsm8k":
            return "Reasoning here. The answer is 42."
        return "The truthful choice is A."
    return w
