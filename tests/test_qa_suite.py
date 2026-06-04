"""Tests for the QA accuracy-under-compression harness (experiments.qa_suite).

These exercise the dataset scorers, the Plateau-collapse payload builders, and the
end-to-end runner against the FREE mock backend — no paid calls, no network (datasets
are cached under QA_CACHE; tests that need data are skipped if the cache is absent so CI
without network still passes)."""
from __future__ import annotations

import json
import os

import pytest

from experiments.qa_suite import datasets as ds
from experiments.qa_suite import harness as H


# --------------------------------------------------------------- scorers
def test_gsm8k_extract_and_score():
    assert ds.gsm8k_extract("blah blah. The answer is 42.") == "42"
    assert ds.gsm8k_extract("so 5 * 3 = 15, then 23 - 15 = 8. The answer is 8") == "8"
    assert ds.gsm8k_extract("no number here") is None
    assert ds.gsm8k_score("The answer is 18.", "18") == 1
    assert ds.gsm8k_score("The answer is 19.", "18") == 0
    assert ds.gsm8k_score("$1,000 total. The answer is 1000", "1000") == 1


def test_truthfulqa_extract_and_score():
    item = {"options": ["a", "b", "c"], "gold_index": 1}
    assert ds.truthfulqa_extract("I pick B.", 3) == 1
    assert ds.truthfulqa_extract("The answer is C", 3) == 2
    assert ds.truthfulqa_extract("none", 3) is None
    assert ds.truthfulqa_score("B", item) == 1
    assert ds.truthfulqa_score("A", item) == 0


# --------------------------------------------------------------- collapse is the real path
def test_plateau_collapse_uses_emit_inflate():
    """The plateau payload must be produced by the production emit/inflate/_render path,
    and must be strictly smaller than the baseline exemplar block (real compression)."""
    blob = H._build_gsm8k_signal()
    # it is a real plateau signal blob
    d = json.loads(blob)
    assert d["schema"] == "plateau.signal.v1"
    assert d["lessons"]  # carries distilled procedure, not per-example replay
    rendered = H._render_signal(blob)
    assert "lessons:" in rendered and "stance:" in rendered


def test_compression_is_positive_both_suites():
    from plateau.driver import _tok
    for suite, item, pf in [
        ("gsm8k", {"question": "x", "gold": "1"}, H.gsm8k_prompt),
        ("truthfulqa",
         {"question": "x", "options": ["a", "b"], "gold_index": 0, "gold": "a"},
         H.truthfulqa_prompt),
    ]:
        base = _tok(pf(item, "baseline")) - _tok(H._question_only(suite, item))
        plat = _tok(pf(item, "plateau")) - _tok(H._question_only(suite, item))
        assert 0 < plat < base, f"{suite}: expected real compression, got {plat} vs {base}"


# --------------------------------------------------------------- end-to-end (mock backend)
def test_runner_mock_end_to_end(tmp_path):
    if not os.path.isfile(os.path.join(ds.CACHE, "gsm8k_test.jsonl")):
        pytest.skip("gsm8k dataset not cached (no network) — runner smoke skipped")
    v = H.run_suite("gsm8k", 2, backend="mock", out_dir=str(tmp_path), progress=False)
    assert v["n"] == 2
    assert v["backend"] == "mock"
    assert 0.0 <= v["baseline_accuracy"] <= 1.0
    assert 0.0 <= v["plateau_accuracy"] <= 1.0
    assert v["compression_pct"] > 0
    # per-item log written, one line per (item, arm)
    log = os.path.join(str(tmp_path), "gsm8k", "items.jsonl")
    assert os.path.isfile(log)
    assert sum(1 for _ in open(log)) == 4  # 2 items × 2 arms
