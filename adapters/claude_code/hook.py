"""Thin Claude Code adapter for Plateau. All logic lives in `plateau`; this file is
only I/O + JSON plumbing at the step boundary.

Two modes, wired to Claude Code's hook events:

  pre   — inflate + ground the persisted signal, print the carried self-state (and flag
          any STALE facts) so it can be surfaced into the next step's context.
  post  — gate any newly proposed facts, fold the admitted ones into the signal, emit,
          and persist the bounded blob back to disk.

The signal lives at .plateau/signal.json in the project root. Newly proposed facts (for
post) are read from .plateau/pending_facts.json — a list of
{claim, source, value} (kind defaults to file_hash). Only facts whose Measurement
re-verifies are admitted; the rest are dropped (and reported). Nothing host-specific
leaks into the core — this adapter imports `plateau` and the standard library only.

Run directly for a dry run:
  python adapters/claude_code/hook.py pre
  python adapters/claude_code/hook.py post
"""

from __future__ import annotations

import json
import os
import sys

from plateau import (
    Measurement, Thought, RelationalState, SelfState,
    emit, inflate, apply_gate, set_ground_root,
)

PLATEAU_DIR = os.environ.get("PLATEAU_DIR", ".plateau")
SIGNAL = os.path.join(PLATEAU_DIR, "signal.json")
PENDING = os.path.join(PLATEAU_DIR, "pending_facts.json")


def _load_blob() -> str:
    if os.path.exists(SIGNAL):
        return open(SIGNAL).read()
    return emit(SelfState(signal=RelationalState()))


def _save_blob(blob: str) -> None:
    os.makedirs(PLATEAU_DIR, exist_ok=True)
    with open(SIGNAL, "w") as f:
        f.write(blob)


def pre() -> dict:
    """Inflate + ground the carried signal for the next step."""
    set_ground_root(os.getcwd())
    inf = inflate(_load_blob(), fresh=True)
    s = inf.state
    return {
        "carried_self_state": {
            "open_goals": s.open_goals, "stance": s.stance,
            "lessons": s.lessons, "pointers": s.pointers,
            "verified_facts": [vf["claim"] for vf in s.verified_facts],
        },
        "stale_dropped_at_inflate": inf.stale_claims(),
        "note": "surface carried_self_state into the next step; stale facts were dropped "
                "because reality no longer supports them",
    }


def post() -> dict:
    """Gate newly proposed facts, fold admitted into the signal, emit, persist."""
    set_ground_root(os.getcwd())
    inf = inflate(_load_blob(), fresh=True)
    proposed = json.load(open(PENDING)) if os.path.exists(PENDING) else []
    thoughts = [Thought(claim=p["claim"],
                        grounding=Measurement(kind=p.get("kind", "file_hash"),
                                              source=p.get("source", ""),
                                              value=p.get("value", "")))
                for p in proposed]
    ss = SelfState(signal=inf.state, thoughts=thoughts)
    before = {vf["claim"] for vf in inf.state.verified_facts}
    new_signal = apply_gate(ss)
    after = {vf["claim"] for vf in new_signal.verified_facts}
    admitted = sorted(after - before)
    dropped = [t.claim for t in thoughts if t.claim not in after]
    _save_blob(emit(SelfState(signal=new_signal)))
    return {"admitted": admitted, "dropped_ungrounded": dropped,
            "signal_path": SIGNAL,
            "note": "only facts whose Measurement re-verified were admitted to the signal"}


def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else "pre"
    out = pre() if mode == "pre" else post()
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
