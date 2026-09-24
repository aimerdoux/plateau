"""plateau.sigma.fossils — Φ, the content-addressed fossil store (§1.3, §5).

Logical depth (Bennett) is expensive to pay and cheap to reuse. Φ caches paid depth,
hashed once, never re-spent. Built directly ON Plateau's existing content-addressed
hashing — `plateau.integrity.file_hash` is the one canonical 'sha256:' measurement, and
we DO NOT reinvent it: an artifact is written to a store file and that file's bytes are
hashed by `file_hash`, so a fossil's address is literally the same measurement the rest
of Plateau trusts.

Contract:
  put(artifact, *, satisfies, provenance, ...) -> hash
        content-addressed write. Identical content ⇒ identical hash ⇒ DEDUP (the second
        write of the same bytes reuses the first). Provenance is MANDATORY (§5).
  get(hash) -> artifact
        integrity-checked read. If the stored bytes no longer hash to `hash`, that is a
        HARD ERROR (tamper / corruption), never a silent return.
  reuse_report() -> ReuseStats
        cross-session dedup measured + reported — the headline property (§7 A3).

Cross-session is the point: two independent sessions that pay the same depth land on the
same address, and the store records the second as a reuse of the first. Stdlib only;
disk-backed; matches plateau.integrity house style.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field

from plateau.integrity import file_hash


def _to_bytes(artifact) -> bytes:
    return artifact if isinstance(artifact, bytes) else str(artifact).encode("utf-8")


def _hash_bytes(data: bytes) -> str:
    """Content address of `data`, via the SAME primitive as the rest of Plateau.

    We write the bytes to a temp file and hash THAT with `plateau.integrity.file_hash`,
    rather than calling hashlib directly — so the fossil address is provably the identical
    measurement (`file_hash` of the content) that integrity/seal use. Reuse, not reinvent."""
    fd, tmp = tempfile.mkstemp(prefix="sigma_fossil_", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        return file_hash(tmp)
    finally:
        os.unlink(tmp)


@dataclass
class ReuseStats:
    """Cross-session dedup measurement (§5, §7 A3)."""
    puts: int = 0                    # total put() calls
    unique: int = 0                  # distinct content addresses stored
    reused: int = 0                  # put() calls that hit an already-stored address
    reused_hashes: list = field(default_factory=list)

    @property
    def reuse_rate(self) -> float:
        return (self.reused / self.puts) if self.puts else 0.0


class FossilStore:
    """Disk-backed content-addressed fossil store (Φ).

    Layout under `root`:
      <root>/<hash-hex>.blob   — the raw artifact bytes (the address IS file_hash of these)
      <root>/<hash-hex>.meta   — provenance + satisfies + flags (sidecar JSON)
    The store is a value-stable substrate across 'sessions' — point two FossilStore
    instances at the same root and the second sees the first's fossils, which is exactly
    the cross-session dedup the SPEC requires."""

    def __init__(self, root: str):
        self.root = os.path.abspath(root)
        os.makedirs(self.root, exist_ok=True)
        self._stats = ReuseStats()

    # -------------------------------------------------------------- paths ----
    def _hex(self, h: str) -> str:
        return h.split(":", 1)[1] if ":" in h else h

    def _blob_path(self, h: str) -> str:
        return os.path.join(self.root, self._hex(h) + ".blob")

    def _meta_path(self, h: str) -> str:
        return os.path.join(self.root, self._hex(h) + ".meta")

    # ----------------------------------------------------------------- put ----
    def put(self, artifact, *, provenance: dict, satisfies=(),
            self_verifiable: bool = False) -> str:
        """Write `artifact` content-addressed; return its hash. Provenance MANDATORY (§5).

        Identical bytes ⇒ identical hash ⇒ the file already exists ⇒ DEDUP: we record a reuse
        and do NOT rewrite the blob. Cross-session reuse falls out for free because the address
        is purely a function of content."""
        if not provenance:
            raise ValueError("fossil put() requires non-empty provenance (§5: provenance is "
                             "mandatory on write — session hash, turn index, cost paid)")
        data = _to_bytes(artifact)
        h = _hash_bytes(data)
        blob = self._blob_path(h)
        self._stats.puts += 1
        if os.path.exists(blob):
            # Same depth already paid for — reuse the existing fossil (dedup is a feature).
            self._stats.reused += 1
            self._stats.reused_hashes.append(h)
            return h
        # New depth: persist blob + provenance sidecar.
        with open(blob, "wb") as f:
            f.write(data)
        meta = {
            "hash": h,
            "satisfies": list(satisfies),
            "self_verifiable": bool(self_verifiable),
            "provenance": provenance,
            "is_bytes": isinstance(artifact, bytes),
        }
        with open(self._meta_path(h), "w", encoding="utf-8") as f:
            json.dump(meta, f, sort_keys=True)
        self._stats.unique += 1
        return h

    # ----------------------------------------------------------------- get ----
    def get(self, h: str):
        """Read the artifact at `h`, integrity-checked. Hash mismatch = HARD ERROR (§5).

        We re-hash the stored bytes with the canonical `file_hash` and refuse to return on any
        mismatch — a fossil whose content no longer matches its address is corruption/tamper,
        not data. Returns bytes or str per the original write."""
        blob = self._blob_path(h)
        if not os.path.exists(blob):
            raise KeyError(f"no fossil at {h}")
        actual = file_hash(blob)
        if actual != h:
            raise ValueError(f"FOSSIL INTEGRITY FAILURE: {h} now hashes to {actual} "
                             "(content-address mismatch — corruption or tamper)")
        with open(blob, "rb") as f:
            data = f.read()
        meta_path = self._meta_path(h)
        is_bytes = True
        if os.path.exists(meta_path):
            with open(meta_path, encoding="utf-8") as f:
                is_bytes = json.load(f).get("is_bytes", True)
        return data if is_bytes else data.decode("utf-8")

    def has(self, h: str) -> bool:
        return os.path.exists(self._blob_path(h))

    def provenance(self, h: str) -> dict:
        meta_path = self._meta_path(h)
        if not os.path.exists(meta_path):
            raise KeyError(f"no provenance for {h}")
        with open(meta_path, encoding="utf-8") as f:
            return json.load(f).get("provenance", {})

    # -------------------------------------------------------------- report ----
    def reuse_report(self) -> ReuseStats:
        """Cross-session dedup, measured (§5, §7 A3)."""
        return self._stats
