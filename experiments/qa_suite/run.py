"""experiments.qa_suite.run — CLI driver for the QA accuracy-under-compression bench.

  # FREE plumbing proof (mock backend, NOT a result):
  PYTHONPATH=<repo>/plateau python -m experiments.qa_suite.run --suite gsm8k --n 5

  # PAID real run (claude -p), cost-bounded:
  PYTHONPATH=<repo>/plateau python -m experiments.qa_suite.run --suite gsm8k --n 50 --go

Default backend is the FREE mock; pass --go to use the real PAID `claude -p` backend.
The runner skips SQuAD v2 / BFCL with a logged reason (their QA mapping is strained —
see harness METHODOLOGY) rather than fabricating a score.
"""
from __future__ import annotations

import json
import os
import sys
import time

from experiments.qa_suite.harness import run_suite, OUT_DEFAULT, ROOT

SKIPPED = {
    "squad_v2": ("The conditioning context is the passage that CONTAINS the answer span; "
                 "collapsing it deletes the bytes the answer is read from — compressing "
                 "the ANSWER, not a redundant few-shot prior. Not a fair Plateau mapping."),
    "bfcl": ("The conditioning context is the tool/function schema the call must match "
             "argument-for-argument; collapsing it removes the names the answer needs. "
             "Compressing the answer substrate, not a prior. Not a fair Plateau mapping."),
}


def _arg(flag, default=None):
    if flag in sys.argv:
        i = sys.argv.index(flag)
        return sys.argv[i + 1] if i + 1 < len(sys.argv) else default
    return default


def main():
    suite = _arg("--suite", "gsm8k")
    n = int(_arg("--n", "5"))
    seed = int(_arg("--seed", "0"))
    go = "--go" in sys.argv
    out_dir = _arg("--out", OUT_DEFAULT)
    backend = "claude_p" if go else "mock"

    if suite in SKIPPED:
        print(json.dumps({"suite": suite, "status": "SKIPPED", "reason": SKIPPED[suite]},
                         indent=2))
        return

    print(f"[qa_suite] suite={suite} n={n} backend={backend} "
          f"({'PAID' if go else 'FREE mock'}) seed={seed}", file=sys.stderr)
    t0 = time.time()
    verdict = run_suite(suite, n, backend=backend, out_dir=out_dir, seed=seed)
    verdict["wall_secs"] = round(time.time() - t0, 1)
    with open(os.path.join(out_dir, suite, "verdict.json"), "w") as f:
        json.dump(verdict, f, indent=2)
    print(json.dumps(verdict, indent=2))


if __name__ == "__main__":
    main()
