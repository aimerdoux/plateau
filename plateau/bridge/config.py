"""plateau.bridge.config — resolves a BridgeConfig from packaged defaults, the user's
global override, the repo's bridge.toml (or a canary variant of it), and the session's
`.plateau/config.toml` [bridge] on/off switch.

Resolution order (each layer overlays the previous one, table by table, key by key):

    packaged defaults (bridge.default.toml, always present)
      <- ~/.plateau/bridge.toml (global override, optional)
      <- <root>/bridge.toml OR <root>/bridge.canary.toml (the "winner"; see below)
      <- <root>/.plateau/config.toml [bridge] table (only its `enabled` flag is read)

Canary: if `<root>/bridge.canary.toml` exists, the session is deterministically bucketed
by `session_id` (same formula shape as `plateau.lab.holdout`); a bucketed session loads
the canary file instead of the incumbent `bridge.toml` and `role` becomes "canary".
`sha`/`path` describe whichever of those two root-level files actually won — never the
packaged defaults or the global override, and never a merge of more than that one file.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from typing import Any, Dict

try:
    import tomllib as _tomllib  # Python >= 3.11
except ImportError:  # pragma: no cover - exercised on 3.9/3.10
    _tomllib = None  # type: ignore[assignment]

from . import _toml

_HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_TOML = os.path.join(_HERE, "bridge.default.toml")


def _loads(text: str) -> Dict[str, Any]:
    """Parse TOML text, preferring the stdlib parser when it exists."""
    if _tomllib is not None:
        return _tomllib.loads(text)
    return _toml.loads(text)


def _read_bytes(path: str) -> bytes:
    with open(path, "rb") as f:
        return f.read()


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    """Recursive per-key merge: nested tables merge, everything else is replaced."""
    out = dict(base)
    for k, v in override.items():
        if k in out and isinstance(out[k], dict) and isinstance(v, dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


@dataclass
class BridgeConfig:
    version: str
    budget: dict
    selector: dict
    nodes: dict
    lab: dict
    continuum: dict
    sha: str
    path: str
    role: str  # "incumbent" | "canary" | "off"


def load(root: str, session_id: str = "") -> BridgeConfig:
    cfg: Dict[str, Any] = _loads(_read_bytes(DEFAULT_TOML).decode("utf-8"))

    global_path = os.path.join(os.path.expanduser("~"), ".plateau", "bridge.toml")
    if os.path.isfile(global_path):
        cfg = _deep_merge(cfg, _loads(_read_bytes(global_path).decode("utf-8")))

    canary_share = cfg.get("lab", {}).get("canary_share", 0.0) or 0.0
    incumbent_path = os.path.join(root, "bridge.toml")
    canary_path = os.path.join(root, "bridge.canary.toml")
    role = "incumbent"
    winning_path = incumbent_path
    if os.path.isfile(canary_path):
        bucket = int(hashlib.sha256(session_id.encode("utf-8")).hexdigest(), 16) % 100
        if bucket < float(canary_share) * 100:
            role = "canary"
            winning_path = canary_path

    if os.path.isfile(winning_path):
        raw = _read_bytes(winning_path)
        cfg = _deep_merge(cfg, _loads(raw.decode("utf-8")))
        sha = hashlib.sha256(raw).hexdigest()
    else:
        # No root-level bridge.toml at all (unusual, but never fatal): fall back to the
        # packaged defaults as the identity of "the file that won".
        raw = _read_bytes(DEFAULT_TOML)
        sha = hashlib.sha256(raw).hexdigest()
        winning_path = DEFAULT_TOML
        role = "incumbent"

    config_toml_path = os.path.join(root, ".plateau", "config.toml")
    if os.path.isfile(config_toml_path):
        try:
            ccfg = _loads(_read_bytes(config_toml_path).decode("utf-8"))
        except Exception:
            ccfg = {}
        bridge_section = ccfg.get("bridge") if isinstance(ccfg, dict) else None
        if isinstance(bridge_section, dict) and bridge_section.get("enabled") is False:
            role = "off"

    return BridgeConfig(
        version=str(cfg.get("version", "")),
        budget=dict(cfg.get("budget") or {}),
        selector=dict(cfg.get("selector") or {}),
        nodes=dict(cfg.get("nodes") or {}),
        lab=dict(cfg.get("lab") or {}),
        continuum=dict(cfg.get("continuum") or {}),
        sha=sha,
        path=winning_path,
        role=role,
    )
