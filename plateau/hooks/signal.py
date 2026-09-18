"""plateau.hooks.signal — the `parent` / `pre` / `post` hook modes.

docs/harness-0.3/PLAN-step4.md "S4-A1 One install story": these three modes used to live
directly in `adapters/claude_code/hook.py` (unchanged since 0.1). They move here
byte-for-byte in behaviour and hook JSON; `adapters/claude_code/hook.py` becomes a thin
shim that calls `main(mode, argv)` below, and so does `plateau hook <mode>`
(`plateau.cli`) — one implementation, two entry points.

  parent — read the Parent Agent Manual's section-4 SYSTEM-PROMPT BLOCK and inject it as
           standing context at SessionStart, so the parent-agent delegation discipline is
           active for as long as the plugin is enabled (and absent when it is disabled).
  pre    — inflate + ground the persisted signal, print the carried self-state (and flag
           any STALE facts) so it can be surfaced into the next step's context.
  post   — gate any newly proposed facts, fold the admitted ones into the signal, emit,
           and persist the bounded blob back to disk.

The signal lives at .plateau/signal.json in the project root. Newly proposed facts (for
post) are read from .plateau/pending_facts.json — a list of
{claim, source, value} (kind defaults to file_hash). Only facts whose Measurement
re-verifies are admitted; the rest are dropped (and reported). The queue (and
.plateau/pending_carry.json) is consumed once the new blob is on disk: a proposal is
gated by the Stop that finds it, never by every later Stop as well (before 0.4.1 a
queue left behind re-admitted the same facts on every Stop and the signal grew a copy
each time while the notice kept saying "0 admitted"). The Stop notice itself speaks only
when something was admitted, dropped, or carried; an idle Stop persists silently.

One change from the pre-step-4 behaviour (S4-A1): the Parent Agent Manual is read from a
single canonical location, the package copy `plateau/agency/PARENT_AGENT_MANUAL.md`,
which ships as package data (`pyproject.toml` artifacts) whether `plateau` is pip-installed
or run out of a dev checkout. There is no more plugin-root / adapter-relative candidate
search — that always resolved to a generated copy of this same file anyway (see
`adapters/claude_code/README.md` "Parent-discipline autoload").
"""

from __future__ import annotations

import json
import os
import re
import sys
from typing import List, Tuple

from plateau import (
    Measurement, Thought, RelationalState, SelfState,
    emit, inflate, apply_gate, set_ground_root,
)

PLATEAU_DIR = os.environ.get("PLATEAU_DIR", ".plateau")
SIGNAL = os.path.join(PLATEAU_DIR, "signal.json")
PENDING = os.path.join(PLATEAU_DIR, "pending_facts.json")
PENDING_CARRY = os.path.join(PLATEAU_DIR, "pending_carry.json")  # optional CARRY lessons
LESS_CAP = 12  # bound the carried lessons so the signal can't grow unbounded

MODES = ("parent", "pre", "post")


def _manual_path() -> str:
    """The package copy of the Parent Agent Manual: `plateau/hooks/signal.py` ->
    `plateau/` -> `agency/PARENT_AGENT_MANUAL.md`. Ships as package data either way
    (pip-installed wheel or a dev checkout) — see `pyproject.toml` `[tool.hatch.build...]
    artifacts`."""
    pkg_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(pkg_root, "agency", "PARENT_AGENT_MANUAL.md")


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
    # The queues are consumed only after the blob is on disk, so a failed persist leaves
    # them for the next Stop (re-gating is idempotent now: a carried claim never folds in twice).
    for queue in (PENDING, PENDING_CARRY):
        if os.path.exists(queue):
            os.remove(queue)
    return {"admitted": admitted, "dropped_ungrounded": dropped,
            "carried_lessons": carried, "signal_path": SIGNAL,
            "note": "only facts whose Measurement re-verified were admitted; lessons are bounded"}


def _read_manual() -> Tuple[str, str]:
    """Return (text, path) for the package copy of the Parent Agent Manual, or
    ("", "") if it cannot be found (e.g. a stripped install)."""
    path = _manual_path()
    if os.path.exists(path):
        return open(path, encoding="utf-8").read(), os.path.abspath(path)
    return "", ""


def _extract_section4_block(manual: str) -> str:
    """Pull the fenced SYSTEM-PROMPT BLOCK out of section 4 of the manual.

    Section 4 ('## 4. PARENT SYSTEM-PROMPT BLOCK ...') wraps the copy-paste parent
    laws in a single fenced ``` block. We return that block's body verbatim so the
    injected context IS the manual's section-4 text — no paraphrase, no drift."""
    m = re.search(r'^##\s*4\.[^\n]*$', manual, re.M)
    if not m:
        return ""
    after = manual[m.end():]
    fb = re.search(r'```[^\n]*\n(.*?)\n```', after, re.S)
    return fb.group(1).strip() if fb else ""


def parent() -> dict:
    """Load the parent-agent discipline (manual section 4) for SessionStart injection."""
    manual, path = _read_manual()
    block = _extract_section4_block(manual) if manual else ""
    return {
        "parent_system_prompt_block": block,
        "manual_path": path,
        "found": bool(block),
        "note": "section-4 SYSTEM-PROMPT BLOCK of the Parent Agent Manual; injected as "
                "standing context at SessionStart so the parent discipline is active "
                "whenever the plugin is enabled",
    }


def _render_parent(out: dict) -> str:
    """Wrap the parent laws as standing additionalContext for the session."""
    block = out.get("parent_system_prompt_block", "")
    if not block:
        return ""
    return ("[Plateau — parent-agent discipline, active while the Plateau plugin is enabled]\n"
            "Operate as the PARENT agent per these standing laws. Delegate the work to bounded "
            "background orchestrators; spend your own turns only to spawn and to verify.\n\n"
            + block)


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


def main(mode: str, argv: List[str]) -> None:
    """Shared entry point for both callers (`adapters/claude_code/hook.py <mode> [--cc]`
    and `plateau hook <mode> [--cc]`). `mode` must be one of `MODES`; `argv` is whatever
    followed the mode on the command line (only `--cc` is recognized here — same as the
    original `adapters/claude_code/hook.py`). `--cc` emits Claude-Code-hook JSON:
    SessionStart (parent) injects the parent-agent discipline as standing context;
    UserPromptSubmit (pre) injects the carried signal as additionalContext; Stop (post)
    gates+persists and returns a one-line systemMessage only when it admitted, dropped or carried something. Without `--cc`, prints the raw
    dict (manual/dry use). The decision logic is unchanged either way."""
    cc = "--cc" in argv
    if cc:
        try:
            sys.stdin.read()  # drain the hook's stdin JSON; we ground via cwd, not stdin
        except Exception:
            pass
    if mode == "parent":
        out = parent()
    elif mode == "post":
        out = post()
    else:
        out = pre()
    if not cc:
        print(json.dumps(out, indent=2))
        return
    if mode == "parent":
        ctx = _render_parent(out)
        # When the manual cannot be found, emit nothing rather than a half-formed prompt.
        payload = {"hookSpecificOutput": {"hookEventName": "SessionStart"}}
        if ctx:
            payload["hookSpecificOutput"]["additionalContext"] = ctx
        else:
            payload["suppressOutput"] = True
        print(json.dumps(payload))
    elif mode == "pre":
        ctx = _render_carried(out["carried_self_state"], out["stale_dropped_at_inflate"])
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit", "additionalContext": ctx}}))
    else:
        n_adm, n_drop = len(out.get("admitted", [])), len(out.get("dropped_ungrounded", []))
        payload: dict = {"suppressOutput": True}
        # Speak only when this Stop changed or refused something; an idle Stop (no queue,
        # nothing to gate) persists the signal without a notice.
        if n_adm or n_drop or out.get("carried_lessons"):
            payload["systemMessage"] = (f"Plateau: signal persisted to {out['signal_path']} "
                                        f"({n_adm} fact(s) admitted, {n_drop} dropped ungrounded).")
        print(json.dumps(payload))
