"""plateau.continuum — emit / ground / inflate.

The continuity loop, host-free:

  emit(state)    → a compact signal blob (JSON). ONLY the signal channel crosses;
                   raw thought content dies in the step that produced it.
  ground(state)  → re-verify every carried fact against the live environment NOW,
                   splitting them into live vs stale. The standalone re-grounding
                   primitive (inflate uses it).
  inflate(blob)  → expand a blob back into a working RelationalState, re-grounding as
                   it goes; facts reality no longer supports are flagged STALE, never
                   silently trusted.

Continuity is re-verified at every inflation, never assumed. That is the difference
between carrying *state* and carrying *claims*: the state survives because it keeps
proving itself.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

from .signal import Measurement, RelationalState, SelfState


def emit(self_state: SelfState) -> str:
    """Serialize the SIGNAL channel to a compact JSON blob. The `thoughts` list is
    deliberately NOT serialized — raw thought does not cross the step boundary.
    verified_facts already passed the gate and carry their Measurement so a later
    inflate can re-ground them."""
    sig = self_state.signal
    blob = {
        "schema": "plateau.signal.v1",
        "open_goals": sig.open_goals,
        "stance": sig.stance,
        "lessons": sig.lessons,
        "pointers": sig.pointers,
        "verified_facts": [
            {"claim": vf["claim"],
             "grounding": {"kind": vf.get("grounding_kind", "file_hash"),
                           "source": vf.get("grounding_source", ""),
                           "value": vf.get("grounding_value", "")}}
            for vf in sig.verified_facts
        ],
    }
    return json.dumps(blob, sort_keys=True, separators=(",", ":"))


@dataclass
class Grounding:
    live: list[dict] = field(default_factory=list)    # facts that re-verified
    stale: list[dict] = field(default_factory=list)    # facts reality now contradicts

    def stale_claims(self) -> list[str]:
        return [s["claim"] for s in self.stale]


def ground(state: RelationalState) -> Grounding:
    """Re-verify every carried fact against the live environment NOW. Returns the
    live/stale split. This is the re-grounding step on its own — call it any time you
    want to know which carried facts still hold without rebuilding the state."""
    live, stale = [], []
    for vf in state.verified_facts:
        m = Measurement(kind=vf.get("grounding_kind", "file_hash"),
                        source=vf.get("grounding_source", ""),
                        value=vf.get("grounding_value", ""))
        if m.reverify():
            live.append(dict(vf))
        else:
            stale.append({"claim": vf["claim"],
                          "grounding_source": vf.get("grounding_source", ""),
                          "reason": "reality no longer supports this carried fact"})
    return Grounding(live=live, stale=stale)


@dataclass
class Inflated:
    state: RelationalState
    stale: list[dict] = field(default_factory=list)

    def stale_claims(self) -> list[str]:
        return [s["claim"] for s in self.stale]


def inflate(signal_blob: str, fresh: bool = True) -> Inflated:
    """Expand a signal blob into a working RelationalState, RE-GROUNDING every carried
    fact against the real current environment. fresh=True (next-step start) forces the
    re-check; structural fields (goals/stance/lessons/pointers) always carry — they
    re-ground safely because they are not factual claims about a mutable world."""
    b = json.loads(signal_blob)
    carried = RelationalState(
        open_goals=list(b.get("open_goals", [])),
        stance=b.get("stance", ""),
        lessons=list(b.get("lessons", [])),
        pointers=list(b.get("pointers", [])),
        verified_facts=[
            {"claim": vf["claim"],
             "grounding_kind": vf.get("grounding", {}).get("kind", "file_hash"),
             "grounding_source": vf.get("grounding", {}).get("source", ""),
             "grounding_value": vf.get("grounding", {}).get("value", "")}
            for vf in b.get("verified_facts", [])
        ],
    )
    if not fresh:
        return Inflated(state=carried, stale=[])
    g = ground(carried)
    carried.verified_facts = g.live
    return Inflated(state=carried, stale=g.stale)
