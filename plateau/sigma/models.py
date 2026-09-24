"""plateau.sigma.models — the four load-bearing carriers of a Schema (§1).

`Σ = ⟨ ι , V , Φ , γ ⟩`. A Schema is exactly four carriers; none is optional, none
collapses into another. This module is the constitution: the §3 V-immutability
invariant is enforced *structurally* here, not by convention downstream.

  ι — Intent     : clean intent, false starts stripped (what D is, never how we found it)
  V — Verifier   : the gate set, FROZEN at construction; the operational definition of "is this D"
  Φ — Fossil(s)  : paid logical depth, content-addressed (lives in fossils.py / the store)
  γ — LoopConfig : the propose-and-check controller; state_handle is REAL, not a stub

§3 enforcement (NON-NEGOTIABLE), wired in below:
  1. `Verifier` is a frozen dataclass — in-session mutation raises FrozenInstanceError.
  2. `frozen_hash` is computed over the gate set at construction (in __post_init__).
  3. `external_anchor` must be non-empty AND resolvable outside the loop, else the
     Verifier is REJECTED at construction (ValueError).
  4. `assert_v_unchanged()` is the refine-guard: 𝒮 (refine, built later) must call it to
     prove it carried V across unchanged. A weaker decoder cannot smuggle a new V.

The repo is stdlib-only (no pydantic); the SPEC's `BaseModel` sketches are realized as
frozen dataclasses, matching plateau.integrity / plateau.signal house style. The carriers
and the invariant are preserved exactly; only the serialization base differs.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from typing import Optional

# Gate kinds the slice understands. `llm_judge` is declared (it is part of V's vocabulary)
# but deferred — evaluate.py raises on it rather than silently passing (§10).
_GATE_KINDS = ("programmatic", "test", "llm_judge")
_STOP_RULES = ("all_gates_pass", "budget_exhausted", "either")


# --------------------------------------------------------------- ι — Intent ----

@dataclass(frozen=True)
class Intent:
    """ι — clean intent (§1.1). The fixpoint of intent discovery, trajectory stripped.

    Compresses *what* the deliverable is. `excluded_paths` carries ruled-out dead ends
    forward so a weaker decoder does not re-pay for known failures — negative information
    is information. Frozen: ι is data the loop reads, not scratch it mutates."""
    goal: str
    target_invariants: tuple = ()    # properties that make D *this* deliverable
    constraints: tuple = ()          # hard limits D must respect
    excluded_paths: tuple = ()       # approaches proven dead
    source_session_hash: str = ""    # provenance


# ---------------------------------------------------------------- V — gates ----

@dataclass(frozen=True)
class Gate:
    """A single checkable gate, anchored to a KPI of the real deliverable (§1.2).

    decidable kinds (programmatic / test) can report FAILURE → a true semi-decision.
    `check` is a kind-specific reference (a code ref, a test/artifact ref, or a rubric)."""
    id: str
    kpi: str
    kind: str                        # one of _GATE_KINDS
    check: str
    threshold: float = 1.0
    weight: float = 1.0

    def __post_init__(self) -> None:
        if self.kind not in _GATE_KINDS:
            raise ValueError(f"gate {self.id!r}: unknown kind {self.kind!r} "
                             f"(expected one of {_GATE_KINDS})")
        if not self.id:
            raise ValueError("gate id must be non-empty")


def _gate_fingerprint(gates: tuple) -> str:
    """Canonical content hash of the gate set. Deterministic over the gate fields that
    define V — id/kpi/kind/check/threshold/weight — order-independent (gates sorted by id)
    so two verifiers with the same gates in a different order share a frozen_hash."""
    rows = sorted(
        ({"id": g.id, "kpi": g.kpi, "kind": g.kind, "check": g.check,
          "threshold": g.threshold, "weight": g.weight} for g in gates),
        key=lambda r: r["id"],
    )
    blob = json.dumps(rows, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(blob).hexdigest()


def _anchor_resolves(anchor: str) -> bool:
    """Does `external_anchor` resolve to something OUTSIDE the loop (§3.4)?

    The anchor is a real, externally-checkable referent. We accept either:
      - a 'sha256:<hex>' content hash (a sealed measurement that exists independently), or
      - a 'sha256:<hex>@<path>' / bare path form whose file exists on disk right now.
    A bare non-empty token with neither a hash prefix nor an existing path does NOT resolve
    — an anchor you cannot point at is not an anchor. Fail closed."""
    if not anchor:
        return False
    # 'sha256:<hex>@<path>' — verify the path component exists (strongest form).
    if "@" in anchor:
        _, _, path = anchor.partition("@")
        return bool(path) and os.path.exists(path)
    # bare content hash — a sealed measurement is itself an external referent.
    if anchor.startswith("sha256:") and len(anchor) > len("sha256:"):
        return True
    # otherwise it must be an existing path.
    return os.path.exists(anchor)


@dataclass(frozen=True)
class Verifier:
    """V — the verifier / gate set (§1.2), FROZEN/immutable (§3).

    The operational definition of "is this D". Constructed once and never mutated within a
    session: `frozen=True` makes attribute assignment raise FrozenInstanceError, and
    `frozen_hash` is computed over the gate set at construction. `external_anchor` is
    non-negotiable — a verifier with no resolvable external anchor is REJECTED here, before
    it can ever gate anything. This is the structural form of the §3 invariant."""
    gates: tuple
    external_anchor: str                 # REQUIRED, non-empty, resolves OUTSIDE the loop
    frozen_hash: str = ""                # computed at construction; do not pass

    def __post_init__(self) -> None:
        if not self.gates:
            raise ValueError("Verifier requires at least one gate (V is the stop signal)")
        # §3.4 — anchor required + must resolve outside the loop, else reject at construction.
        if not self.external_anchor or not _anchor_resolves(self.external_anchor):
            raise ValueError(
                "INVARIANT VIOLATION (§3.4): external_anchor must be non-empty and resolve "
                f"OUTSIDE the loop; got {self.external_anchor!r}. A verifier with no external "
                "anchor optimizes gates it also authored — rejected at construction."
            )
        # frozen=True forbids normal assignment; set the computed hash via object.__setattr__,
        # the standard idiom for a derived field on a frozen dataclass.
        object.__setattr__(self, "frozen_hash", _gate_fingerprint(tuple(self.gates)))

    def gate_ids(self) -> list:
        return [g.id for g in self.gates]


# ---------------------------------------------------------------- Φ — Fossil ----

@dataclass(frozen=True)
class Fossil:
    """Φ — a single fossil: paid logical depth, content-addressed (§1.3).

    `hash` is the content address (integrity + dedup key) — same depth ⇒ same hash ⇒
    cross-session reuse. `provenance` is mandatory on write (session hash, turn, cost).
    The store (fossils.py) owns put/get/reuse; this is the carried record."""
    hash: str
    artifact: bytes | str
    satisfies: tuple = ()            # gate ids this helps satisfy
    self_verifiable: bool = False    # can the receiver re-check without re-deriving?
    provenance: dict = field(default_factory=dict)


# ---------------------------------------------------------------- γ — loop ----

@dataclass(frozen=True)
class LoopConfig:
    """γ — the propose-and-check controller (§1.4). `/loop` made concrete.

    `max_iterations` is the REQUIRED wall (Rice: halting is bounded, not solved). `state_handle`
    is a REAL pointer into Φ — iteration-state persists there so depth COMPOUNDS across passes;
    a stateless re-roll is a bug (§9.1). `fossil_write` toggles hashing successful expensive
    sub-results back into Φ."""
    generator_policy: str
    max_iterations: int                  # REQUIRED wall — never a loop without one
    stop_rule: str = "either"            # one of _STOP_RULES
    state_handle: str = ""               # pointer into Φ — REAL, not a stub
    fossil_write: bool = True

    def __post_init__(self) -> None:
        if self.max_iterations < 1:
            raise ValueError("LoopConfig.max_iterations must be >= 1 (the required wall, §9.2)")
        if self.stop_rule not in _STOP_RULES:
            raise ValueError(f"unknown stop_rule {self.stop_rule!r} (expected {_STOP_RULES})")
        if not self.state_handle:
            raise ValueError(
                "LoopConfig.state_handle must be REAL, not empty (§9.1): iteration-state must "
                "externalize through Φ so depth compounds; a stateless loop is a bug."
            )


# --------------------------------------------------------------- Σ — Schema ----

@dataclass(frozen=True)
class Schema:
    """Σ = ⟨ ι , V , Φ , γ ⟩ (§1) — exactly four carriers, none optional.

    Frozen at the schema altitude too: the inner loop (γ) and the later outer loop (𝒮)
    produce NEW Schemas, they do not mutate this one in place. `phi` holds the fossils
    carried with the schema (the store is the durable backing); the live store is passed
    to run_schema separately so a Schema stays a value."""
    intent: Intent                   # ι
    verifier: Verifier               # V
    loop: LoopConfig                 # γ
    phi: tuple = ()                  # Φ — fossils carried with the schema

    def assert_v_unchanged(self, original: "Schema") -> None:
        """Refine-guard (§3.3). 𝒮 (built later) MUST call this on its output: the returned
        Schema must carry the SAME Verifier.frozen_hash as the original. A mismatch means V
        was rewritten — the one thing 𝒮 may NEVER do — so we fail loudly.

        Lives here, on the constitution, so refine() cannot ship without honoring it."""
        if self.verifier.frozen_hash != original.verifier.frozen_hash:
            raise ValueError(
                "INVARIANT VIOLATION (§3): V mutated across refine() — "
                f"frozen_hash {self.verifier.frozen_hash} != {original.verifier.frozen_hash}. "
                "𝒮 may rewrite ι, Φ, γ but NEVER V."
            )
