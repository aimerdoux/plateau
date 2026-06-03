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
PENDING_CARRY = os.path.join(PLATEAU_DIR, "pending_carry.json")  # optional CARRY lessons
LESS_CAP = 12  # bound the carried lessons so the signal can't grow unbounded


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
    # carry CARRY lessons (decisions the next step needs) — bounded + deduped
    carried = []
    if os.path.exists(PENDING_CARRY):
        for les in json.load(open(PENDING_CARRY)):
            les = str(les).strip()[:200]
            if les and les not in new_signal.lessons:
                new_signal.lessons = (new_signal.lessons + [les])[-LESS_CAP:]
                carried.append(les)
    _save_blob(emit(SelfState(signal=new_signal)))
    return {"admitted": admitted, "dropped_ungrounded": dropped,
            "carried_lessons": carried, "signal_path": SIGNAL,
            "note": "only facts whose Measurement re-verified were admitted; lessons are bounded"}


def _render_carried(cs: dict, stale: list) -> str:
    """Compact rendering of the carried self-state for injection as additionalContext.
    This IS the bounded signal — keep it small."""
    parts = ["[Plateau — carried self-state, re-grounded against the repo this step]"]
    if cs["open_goals"]:
        parts.append("open goals: " + "; ".join(cs["open_goals"]))
    if cs["stance"]:
        parts.append("stance: " + cs["stance"])
    if cs["lessons"]:
        parts.append("lessons: " + "; ".join(cs["lessons"]))
    if cs["pointers"]:
        parts.append("pointers: " + "; ".join(cs["pointers"]))
    if cs["verified_facts"]:
        parts.append("verified facts (gated): " + "; ".join(cs["verified_facts"]))
    if stale:
        parts.append("DROPPED as stale (reality moved — do not trust): " + "; ".join(stale))
    if len(parts) == 1:
        parts.append("(empty — no signal carried yet)")
    return "\n".join(parts)


def main() -> None:
    """CLI + Claude Code hook entry. `--cc` emits Claude-Code-hook JSON:
    UserPromptSubmit (pre) injects the carried signal as additionalContext; Stop (post)
    gates+persists and returns a one-line systemMessage. Without `--cc`, prints the raw
    dict (manual/dry use). The pre()/post() decision logic is unchanged either way."""
    args = [a for a in sys.argv[1:] if a != "--cc"]
    cc = "--cc" in sys.argv[1:]
    mode = args[0] if args else "pre"
    if cc:
        try:
            sys.stdin.read()  # drain the hook's stdin JSON; we ground via cwd, not stdin
        except Exception:
            pass
    out = pre() if mode == "pre" else post()
    if not cc:
        print(json.dumps(out, indent=2))
        return
    if mode == "pre":
        ctx = _render_carried(out["carried_self_state"], out["stale_dropped_at_inflate"])
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit", "additionalContext": ctx}}))
    else:
        n_adm, n_drop = len(out.get("admitted", [])), len(out.get("dropped_ungrounded", []))
        print(json.dumps({"suppressOutput": True,
                          "systemMessage": f"Plateau: signal persisted to {out['signal_path']} "
                                           f"({n_adm} fact(s) admitted, {n_drop} dropped ungrounded)."}))


if __name__ == "__main__":
    main()
