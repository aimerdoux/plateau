#!/usr/bin/env python3
"""Record SHA-256 of every file under experiments/d038/raw/, raw_void/ and preflight/ into raw_hashes.txt (committed) —
those dirs are gitignored because they carry content of the private target. Re-run after each completed run; never
edit by hand."""
import hashlib, os
HERE = os.path.dirname(os.path.abspath(__file__)); OUT = os.path.join(HERE, "raw_hashes.txt")
lines = []
for d in ("raw", "raw_void", "preflight"):
    for root, _, files in sorted(os.walk(os.path.join(HERE, d))):
        for f in sorted(files):
            p = os.path.join(root, f)
            lines.append(f"{hashlib.sha256(open(p, 'rb').read()).hexdigest()}  {os.path.relpath(p, HERE)}")
open(OUT, "w").write("\n".join(lines) + ("\n" if lines else ""))
print(f"{len(lines)} files hashed -> {os.path.relpath(OUT)}")
