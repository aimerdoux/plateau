# Integrity model

Plateau ships an optional, opt-in integrity layer (`plateau.integrity`) and uses it to
make the demo's numbers tamper-evident. This document states exactly what that does and
does not guarantee, so the demo's PASS is not over-read.

## What "PASS" means for the demo

The demo's raw per-step records are sealed write-once (`chmod 0o444`) and their SHA-256
hashes recorded in an append-only, self-hash-chained manifest
(`demo/raw/manifest.jsonl`) **before** any scoring. "PASS" means, in a fresh process:

1. the manifest's hash chain recomputes (no truncation/rewrite of history),
2. every sealed file still hashes to its recorded value (no tamper),
3. the verdict (`demo/verdict.json`) reproduces from the sealed raw.

You can re-run this yourself:

```python
from plateau.integrity import Manifest
m = Manifest("demo/raw/manifest.jsonl")
print(m.verify_chain())          # (True, [])
print(m.verify_files("."))       # (True, [])
# then: python demo/score_demo.py  and diff against demo/verdict.json
```

## Self-contained — by construction

This repository's integrity is **independent of any other project**:

- The verifier reads only `demo/raw/manifest.jsonl` within this repo. It does not glob,
  reference, or depend on any manifest outside this tree.
- The demo PASS asserts nothing about any parent or sibling project. It is entirely about
  the bytes in `demo/raw/`.

(For provenance: this code was extracted from a research monorepo. That monorepo's own
separate recompute, on a different path tree and a different manifest filename, is
unrelated to this repo and has no bearing on the demo PASS here. Nothing from it is
carried in.)

## Threat model (honest, single-uid)

The process owns its files and could `chmod +w` its own seal. This layer does **not**
make tampering physically impossible; it makes it **detectable**: any edit to a sealed
file, or any rewrite of manifest history, fails verification loudly. The real backstop is
an *independent* re-verification (you, or CI) running the checks above on the sealed tree
— it does not require trusting whoever wrote the data.

This was not theoretical during development. A deliberate one-line tamper of a sealed
file in the source project was caught immediately by exactly this mechanism — it named
the file and the precise hash mismatch, with no human in the loop. See
`examples/continuum_story.md`.

True "physically cannot" requires a second uid / root-owned directory only an operator
can set up; that is out of scope for this library.
