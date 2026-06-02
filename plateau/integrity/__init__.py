"""plateau.integrity — write-once sealing + tamper-evident manifest. OFF by default.

The core (signal / continuum / metrics) does NOT require this module to run. It is
an optional, opt-in layer for when you want your measurement artifacts to be
tamper-evident — e.g. publishing a benchmark whose numbers others must be able to
trust. `examples/bare_loop.py` runs the whole continuity loop without ever touching
it.

Threat model (honest, single-uid): the process owns its files and could chmod +w its
own seal. This module does NOT make that physically impossible; it makes it
DETECTABLE. Every sealed file's hash is recorded in an append-only, self-hash-chained
manifest, and `Manifest.verify_files()` / `verify_chain()` FAIL LOUDLY if a sealed
file's current bytes no longer match its recorded hash, or if manifest history was
truncated/rewritten. The independent backstop is a separate process (you, or CI)
re-running verification on the sealed tree — it does not depend on trusting the
writer.

Ported from a research harness; intentionally tiny and dependency-free (stdlib only).
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
import time
from dataclasses import dataclass


def file_hash(path: str) -> str:
    """SHA-256 of a file's bytes, prefixed 'sha256:'. The one canonical measurement."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return "sha256:" + h.hexdigest()


def _is_sealed(path: str) -> bool:
    """True iff the file has no write bits for anyone (read-only = write-once held)."""
    mode = os.stat(path).st_mode
    return not (mode & (stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH))


def is_sealed(path: str) -> bool:
    return os.path.exists(path) and _is_sealed(path)


@dataclass
class Manifest:
    """Append-only, self-hash-chained ledger of sealed-file hashes."""
    path: str

    def _entries(self) -> list[dict]:
        if not os.path.exists(self.path):
            return []
        out = []
        with open(self.path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    out.append(json.loads(line))
        return out

    def _last_digest(self) -> str:
        entries = self._entries()
        return entries[-1]["entry_hash"] if entries else "sha256:genesis"

    def record(self, rel_path: str, digest: str, *, kind: str,
               ts: float | None = None) -> dict:
        """Append a tamper-evident entry chaining to the prior one."""
        prev = self._last_digest()
        body = {
            "rel_path": rel_path,
            "file_hash": digest,
            "kind": kind,
            "ts": ts if ts is not None else round(time.time(), 3),
            "prev": prev,
        }
        entry_hash = "sha256:" + hashlib.sha256(
            json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        body["entry_hash"] = entry_hash
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(body, sort_keys=True) + "\n")
        return body

    def verify_chain(self) -> tuple[bool, list[str]]:
        """Recompute the hash chain; detect truncation/rewrite of the manifest."""
        problems = []
        prev = "sha256:genesis"
        for i, e in enumerate(self._entries()):
            if e.get("prev") != prev:
                problems.append(f"entry {i} ({e.get('rel_path')}): broken chain "
                                f"(prev={e.get('prev')}, expected {prev})")
            body = {k: e[k] for k in ("rel_path", "file_hash", "kind", "ts", "prev")}
            recomputed = "sha256:" + hashlib.sha256(
                json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
            if recomputed != e.get("entry_hash"):
                problems.append(f"entry {i} ({e.get('rel_path')}): entry_hash mismatch")
            prev = e.get("entry_hash", prev)
        return (len(problems) == 0, problems)

    def verify_files(self, root: str) -> tuple[bool, list[str]]:
        """Every recorded file must exist and still hash to its manifest entry."""
        problems = []
        for e in self._entries():
            p = os.path.join(root, e["rel_path"])
            if not os.path.exists(p):
                problems.append(f"missing sealed file: {e['rel_path']}")
                continue
            cur = file_hash(p)
            if cur != e["file_hash"]:
                problems.append(f"TAMPER: {e['rel_path']} now {cur}, "
                                f"manifest {e['file_hash']}")
        return (len(problems) == 0, problems)


def seal(path: str, manifest: Manifest, root: str, *, kind: str = "raw",
         ts: float | None = None, allow_reseal: bool = False) -> dict:
    """Write-once seal: hash the file, record it in the manifest, then chmod 0o444.

    Refuses to seal an already-sealed path unless allow_reseal (tests only). After
    sealing, the file is read-only; the recorded hash is the value any later
    verification must reproduce."""
    if not os.path.exists(path):
        raise FileNotFoundError(path)
    if _is_sealed(path) and not allow_reseal:
        raise PermissionError(f"already sealed (write-once): {path}")
    digest = file_hash(path)
    rel = os.path.relpath(path, root)
    entry = manifest.record(rel, digest, kind=kind, ts=ts)
    os.chmod(path, 0o444)
    return entry
