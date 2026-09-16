#!/usr/bin/env python3
"""Record SHA-256 of every file under experiments/d038/raw/ into raw_hashes.txt (committed) — the raw dir itself is
gitignored because it carries content of the private target. Re-run after each completed run; never edit by hand."""
import hashlib, os
HERE = os.path.dirname(os.path.abspath(__file__)); RAW = os.path.join(HERE, "raw"); OUT = os.path.join(HERE, "raw_hashes.txt")
lines = []
for root, _, files in sorted(os.walk(RAW)):
    for f in sorted(files):
        p = os.path.join(root, f)
        lines.append(f"{hashlib.sha256(open(p, 'rb').read()).hexdigest()}  {os.path.relpath(p, HERE)}")
open(OUT, "w").write("\n".join(lines) + ("\n" if lines else ""))
print(f"{len(lines)} files hashed -> {os.path.relpath(OUT)}")
