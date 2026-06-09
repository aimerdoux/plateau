# Contributing to Plateau

Thanks for considering a contribution. Plateau is small, dependency-light, and
**evidence-first** — the bar is not "does it sound right" but "does it re-ground."

## Dev setup

```bash
git clone https://github.com/aimerdoux/plateau && cd plateau
pip install -e ".[test,demo]"   # core is zero-dep; [demo] adds numpy/matplotlib for charts
pytest -q                       # the suite must be green
```

Python 3.9+ (the core is stdlib-only and `from __future__ import annotations`-clean, so it
runs on the macOS system `python3`).

## The one rule that makes this project different

**A claim is a thought until it re-grounds against a sealed artifact.** If you add or change a
result:

1. **Pre-register** the expected outcome in writing *before* you run it.
2. **Seal** the raw inputs write-once (`plateau.integrity`) *before* scoring.
3. Make it **recompute-verifiable** — a fresh process must re-derive the verdict from the sealed
   raw (`python -m experiments.recompute`, or the demo's `recompute_*.py`).
4. **Publish nulls and ties.** We don't lengthen a chain until a baseline breaks; a NULL that
   bounds the claim is a welcome contribution, not a failure.

Numbers in docs are sourced to a sealed file or auto-rendered from JSON behind a self-consistency
gate — never hand-typed. The `demo/context_growth.gif` is generated from the sealed completion
files by `demo/make_context_gif.py`; regenerate it rather than editing the image.

## What we're looking for

- Honest benchmarks (especially a **harder regime** where a competent compressor would start
  dropping facts — the open question Plateau hasn't beaten yet).
- New grounding kinds for the gate, new runtime adapters, docs, repros on other machines.
- We do **not** want claims the sealed artifacts don't support — no recall/capability/"smarter"
  framing. Plateau is an efficiency tool: bounded context, cheaper not smarter.

## PRs

- Branch off `main`, keep changes surgical, add/keep tests green.
- One logical change per PR; describe what re-grounds it.
- Be kind. Apache-2.0; by contributing you agree your work ships under it.
