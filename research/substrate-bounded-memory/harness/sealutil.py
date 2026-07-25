"""Shared sealing + prereg-hash echo for the D-036 runners.

Every scored run must echo the sealed PREREG.md hash before writing a datum, and
must seal its raw output write-once into a self-hash-chained manifest under raw/,
per PREREG.md sec.7 (same convention as demo/raw*/).
"""
from __future__ import annotations

import json
import os

HARNESS_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HARNESS_DIR)                    # research/substrate-bounded-memory
RAW = os.path.join(ROOT, "raw")
PREREG = os.path.join(ROOT, "PREREG.md")


def prereg_hash():
    from plateau.integrity import file_hash
    return file_hash(PREREG)


def echo_seal():
    h = prereg_hash()
    print(f"[seal] PREREG.md sha256 = {h}")
    return h


def manifest():
    from plateau.integrity import Manifest
    os.makedirs(RAW, exist_ok=True)
    return Manifest(os.path.join(RAW, "manifest.jsonl"))


def write_and_seal(rel_name: str, obj: dict, man=None):
    """Write obj as JSON into raw/, stamp the prereg hash, seal write-once."""
    from plateau.integrity import seal
    man = man or manifest()
    obj = dict(obj)
    obj["_prereg_sha256"] = prereg_hash()
    path = os.path.join(RAW, rel_name)
    with open(path, "w") as fh:
        json.dump(obj, fh, indent=2, sort_keys=True)
    seal(path, man, root=RAW, kind="raw")
    return path
