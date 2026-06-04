"""Dataset loaders + standard scorers for the QA suites.

Each loader returns a list of ``Item`` dicts with at least ``question`` and ``gold``.
Scorers implement the suite's *standard* metric, nothing bespoke:

  GSM8K       — exact-match on the final integer (the number after ``####``).
  TruthfulQA  — MC1: the model must pick the single correct option out of the
                shuffled mc1_targets options (one option has value 1).

Datasets are fetched once to a local cache dir (default ``/tmp/qa_cache``) from public
raw sources. If a source is unreachable the loader raises; the caller notes it and skips
that suite rather than fabricating data.
"""
from __future__ import annotations

import json
import os
import re
import urllib.request

CACHE = os.environ.get("QA_CACHE", "/tmp/qa_cache")

GSM8K_URL = ("https://raw.githubusercontent.com/openai/grade-school-math/"
             "master/grade_school_math/data/test.jsonl")
TRUTHFULQA_URL = ("https://raw.githubusercontent.com/sylinrl/TruthfulQA/"
                  "main/data/mc_task.json")


def _fetch(url: str, fname: str) -> str:
    os.makedirs(CACHE, exist_ok=True)
    path = os.path.join(CACHE, fname)
    if not os.path.isfile(path) or os.path.getsize(path) == 0:
        with urllib.request.urlopen(url, timeout=60) as r:
            data = r.read()
        with open(path, "wb") as f:
            f.write(data)
    return path


# ----------------------------------------------------------------------- GSM8K
_GSM_GOLD = re.compile(r"####\s*([\-0-9,\.]+)")
# pull the LAST standalone number out of a free-text model reply
_NUM = re.compile(r"(-?\$?\d[\d,]*(?:\.\d+)?)")


def load_gsm8k(n: int, seed: int = 0):
    """Return the first ``n`` GSM8K test items (deterministic order — the suite's own
    test order; seed kept for signature symmetry). Each item: question, gold (str int)."""
    path = _fetch(GSM8K_URL, "gsm8k_test.jsonl")
    out = []
    with open(path) as f:
        for line in f:
            if len(out) >= n:
                break
            d = json.loads(line)
            m = _GSM_GOLD.search(d["answer"])
            if not m:
                continue
            out.append({"question": d["question"].strip(),
                        "gold": m.group(1).replace(",", "").rstrip(".")})
    return out


def gsm8k_extract(reply: str) -> str | None:
    """Standard GSM8K answer extraction: the final number in the reply (handles a
    trailing 'The answer is N.' or a bare number)."""
    if reply is None:
        return None
    nums = _NUM.findall(reply.replace(",", ""))
    if not nums:
        return None
    return nums[-1].lstrip("$").rstrip(".")


def gsm8k_score(reply: str, gold: str) -> int:
    pred = gsm8k_extract(reply)
    if pred is None:
        return 0
    try:
        return 1 if abs(float(pred) - float(gold)) < 1e-6 else 0
    except ValueError:
        return 1 if pred.strip() == gold.strip() else 0


# ------------------------------------------------------------------ TruthfulQA MC1
def load_truthfulqa_mc1(n: int, seed: int = 0):
    """Return the first ``n`` TruthfulQA MC1 items. Each item:
       question, options (list[str], shuffled deterministically by seed),
       gold_index (int — index of the single correct option in the shuffled list),
       gold (str — the correct option text)."""
    import random
    path = _fetch(TRUTHFULQA_URL, "truthfulqa_mc.json")
    data = json.load(open(path))
    rng = random.Random(seed)
    out = []
    for d in data[:n]:
        mc1 = d["mc1_targets"]
        opts = list(mc1.keys())
        rng.shuffle(opts)
        gold_text = next(k for k, v in mc1.items() if v == 1)
        out.append({"question": d["question"].strip(),
                    "options": opts,
                    "gold_index": opts.index(gold_text),
                    "gold": gold_text})
    return out


_LETTER = re.compile(r"\b([A-H])\b")


def truthfulqa_extract(reply: str, n_options: int) -> int | None:
    """Pull the chosen option LETTER (A,B,C,...) from a free-text reply. Returns a
    0-based index, or None if no valid letter is found."""
    if reply is None:
        return None
    # prefer the last standalone letter mention in A..(A+n-1)
    valid = {chr(ord("A") + i) for i in range(n_options)}
    found = [m.group(1) for m in _LETTER.finditer(reply.upper()) if m.group(1) in valid]
    if not found:
        return None
    return ord(found[-1]) - ord("A")


def truthfulqa_score(reply: str, item: dict) -> int:
    pred = truthfulqa_extract(reply, len(item["options"]))
    if pred is None:
        return 0
    return 1 if pred == item["gold_index"] else 0
