"""plateau.signal — the SIGNAL/THOUGHT separation and the gate.

The one architectural separation that makes bounded continuity safe:

  SIGNAL  (continuity)  — relational structure carried forward; it inflates into the
                          next step's context. Flows freely because it re-grounds.
  THOUGHT (content)     — concrete factual claims made THIS step. Must be GATED
                          before any of it is allowed to persist into the signal.

The gate rule (the whole point — keep it sacred): a Thought may enter the SIGNAL only
if its grounding is a real Measurement that RE-VERIFIES against the live environment
right now. grounding=None → dropped. grounding that no longer re-derives → dropped as
stale. A model's own assertion is never a Measurement. "Probably right" is never
grounding. This is what stops a bounded context from quietly filling with plausible
fabrications: the bound is cheap, but only *checkable* state earns a seat.

A Measurement is something the machine can re-read deterministically. The canonical
kind is a file hash; test-result / exit-code / oracle-score kinds plug in via the
same `reverify()` contract. Grounding resolves relative paths against a configurable
root (default: current working directory) — no host-specific paths are baked in.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Literal, Optional

from .integrity import file_hash

# Where relative Measurement sources are resolved from. Defaults to CWD so the core
# carries no host-specific path. Override for a fixed project root if you prefer.
_GROUND_ROOT = os.getcwd()


def set_ground_root(path: str) -> None:
    """Set the root that relative Measurement sources resolve against."""
    global _GROUND_ROOT
    _GROUND_ROOT = os.path.abspath(path)


def ground_root() -> str:
    return _GROUND_ROOT


@dataclass(frozen=True)
class Measurement:
    """A value read from the real environment, re-verifiable on demand."""
    kind: Literal["file_hash", "test_result", "oracle_score", "exit_code", "operator"]
    source: str          # what was read (e.g. a path); where the value came from
    value: str           # the value recorded at grounding time

    def reverify(self) -> bool:
        """Re-read reality and report whether the recorded value still holds.

        Three live kinds, all file-backed and integrity-bound; every other kind fails
        CLOSED (a gate must never admit on an unverifiable kind):

          file_hash    — the file's bytes still hash to `value` (the canonical measurement).
          test_result  — `value` is the sha256 of a JSON result artifact: the file's bytes
                         still match it AND the artifact records ``normalized_pass is True``.
          exit_code    — same hash binding, AND the artifact records ``exit_code == 0`` (success).

        The two result kinds bind the artifact's HASH first, so the file cannot be fabricated
        or edited after the claim — exactly the file_hash guarantee — and only then assert that
        the recorded run succeeded. They deliberately DO NOT execute `source` as a command:
        GATE measurements originate in untrusted sub-agent replies, so running them would be an
        injection vector. The gate certifies a recorded, UNCHANGED success artifact; actually
        re-running the test for TRUTH is the validator's job, not the gate's. 'operator' and
        'oracle_score' are not filesystem-checkable here, so they fail closed."""
        if not self.source:
            return False
        p = self.source if os.path.isabs(self.source) else os.path.join(_GROUND_ROOT, self.source)
        if not os.path.isfile(p):   # missing OR a directory ⇒ fail closed, never crash
            return False
        if self.kind == "file_hash":
            return file_hash(p) == self.value
        if self.kind in ("test_result", "exit_code"):
            if file_hash(p) != self.value:        # integrity first: exact, unchanged bytes
                return False
            try:
                with open(p) as f:
                    data = json.load(f)
            except (OSError, ValueError):
                return False                      # unreadable / not JSON ⇒ fail closed
            if not isinstance(data, dict):
                return False
            if self.kind == "test_result":
                return data.get("normalized_pass") is True
            return data.get("exit_code") == 0     # exit_code: success (0) only
        # operator / oracle_score: not filesystem-checkable here ⇒ fail closed
        return False


@dataclass
class Thought:
    """A concrete factual claim of this step. grounding=None ⇒ UNVERIFIED ⇒ forbidden
    from the signal."""
    claim: str
    grounding: Optional[Measurement] = None

    def is_grounded_now(self) -> bool:
        return self.grounding is not None and self.grounding.reverify()


@dataclass
class RelationalState:
    """The SIGNAL channel: relational structure safe to carry forward (it re-grounds).

    Five fields, each a different kind of carried structure:
      open_goals     — what we're trying to do (persists)
      stance         — how we're approaching it (persists)
      lessons        — what we learned the hard way (accumulates)
      pointers       — references to sealed/external artifacts (addresses, not copies)
      verified_facts — claims that PASSED the gate, each keeping its Measurement
    """
    open_goals: list[str] = field(default_factory=list)
    stance: str = ""
    lessons: list[str] = field(default_factory=list)
    pointers: list[str] = field(default_factory=list)
    verified_facts: list[dict] = field(default_factory=list)

    def tuples(self) -> set:
        """Order-agnostic relational tuple set (used by overlap/geometry metrics)."""
        t = set()
        for g in self.open_goals:
            t.add(("goal", g))
        if self.stance:
            t.add(("stance", self.stance))
        for ls in self.lessons:
            t.add(("lesson", ls))
        for p in self.pointers:
            t.add(("pointer", p))
        for vf in self.verified_facts:
            t.add(("fact", vf["claim"]))
        return t


@dataclass
class SelfState:
    signal: RelationalState
    thoughts: list[Thought] = field(default_factory=list)


@dataclass
class GateResult:
    admitted: list[dict]   # {claim, grounding_kind, grounding_source, grounding_value}
    dropped: list[dict]    # {claim, reason}


def gate(thoughts: list[Thought]) -> GateResult:
    """Admit ONLY thoughts whose grounding re-verifies against reality NOW. Every drop
    is logged with its reason. This is the measurement-vs-chatter line; do not relax
    it. A bounded context is only trustworthy because of what this function refuses."""
    admitted, dropped = [], []
    for th in thoughts:
        if th.grounding is None:
            dropped.append({"claim": th.claim, "reason": "ungrounded (grounding=None)"})
            continue
        if not th.grounding.reverify():
            dropped.append({"claim": th.claim,
                            "reason": f"grounding did not re-verify "
                                      f"({th.grounding.kind}:{th.grounding.source})"})
            continue
        admitted.append({"claim": th.claim,
                         "grounding_kind": th.grounding.kind,
                         "grounding_source": th.grounding.source,
                         "grounding_value": th.grounding.value})
    return GateResult(admitted=admitted, dropped=dropped)


def apply_gate(self_state: SelfState) -> RelationalState:
    """Run the gate and fold admitted facts into a COPY of the signal. Signal flows
    freely; only gated thoughts become persisted verified_facts."""
    res = gate(self_state.thoughts)
    sig = self_state.signal
    return RelationalState(
        open_goals=list(sig.open_goals), stance=sig.stance,
        lessons=list(sig.lessons), pointers=list(sig.pointers),
        verified_facts=list(sig.verified_facts) + res.admitted,
    )
