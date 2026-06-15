"""plateau.sigma.evaluate — run V against a candidate (§6, §10.3).

`evaluate(candidate, verifier) -> GateResults`. Decidable gates only for the slice:

  programmatic — a registered Python predicate scores the candidate against the gate's KPI.
                 Returns a real number in [0,1]; pass iff score >= gate.threshold. Decidable
                 gates can report FAILURE → a true semi-decision (§1.2).
  test         — the gate's `check` names an on-disk result/verdict artifact; the gate passes
                 iff that artifact re-verifies as a recorded success. This reuses the same
                 file-backed, integrity-bound discipline as plateau.signal.Measurement (the
                 gate certifies a recorded UNCHANGED success artifact; it never executes a
                 command from candidate-controlled text — that would be an injection vector).
  llm_judge    — DEFERRED for the slice (§10). Raises NotImplementedError rather than silently
                 passing — a soft judge masquerading as a hard gate is exactly the drift the
                 invariant guards against.

Aggregate feasibility = weight-normalized mean of per-gate scores. `all_pass` is the true
stop signal (every gate at/above its own threshold); `feasibility` is the soft headroom number
the loop can climb. `programmatic` checks are resolved through a small registry so candidate
text is never eval'd.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from plateau.signal import Measurement


# --------------------------------------------------------- programmatic registry ----
# `programmatic` gates reference a checker BY NAME here; we never eval() candidate-derived
# strings. A checker takes (candidate, gate) and returns a score in [0,1].
_CHECKERS: dict = {}


def register_check(name: str):
    """Decorator: register a programmatic gate checker under `name` (the gate's `check` ref)."""
    def _wrap(fn):
        _CHECKERS[name] = fn
        return fn
    return _wrap


def get_check(name: str):
    if name not in _CHECKERS:
        raise KeyError(f"no programmatic checker registered as {name!r} "
                       f"(known: {sorted(_CHECKERS)})")
    return _CHECKERS[name]


# ------------------------------------------------------------------- results ----

@dataclass
class GateResult:
    gate_id: str
    kpi: str
    kind: str
    score: float
    threshold: float
    weight: float
    passed: bool
    detail: str = ""


@dataclass
class GateResults:
    results: list = field(default_factory=list)

    @property
    def all_pass(self) -> bool:
        return bool(self.results) and all(r.passed for r in self.results)

    @property
    def feasibility(self) -> float:
        """Weight-normalized mean of per-gate scores in [0,1] — the soft signal γ climbs."""
        total_w = sum(r.weight for r in self.results)
        if total_w <= 0:
            return 0.0
        return sum(r.score * r.weight for r in self.results) / total_w

    def failing(self) -> list:
        return [r.gate_id for r in self.results if not r.passed]


# ------------------------------------------------------------------- per-kind ----

def _eval_programmatic(candidate, gate) -> tuple:
    checker = get_check(gate.check)
    score = float(checker(candidate, gate))
    score = max(0.0, min(1.0, score))
    return score, f"programmatic:{gate.check} -> {score:.3f}"


def _eval_test(candidate, gate) -> tuple:
    """`gate.check` is a path to a result/verdict artifact. The gate passes iff that artifact
    re-verifies as a recorded success — same file-backed integrity discipline as the core's
    Measurement. We bind the candidate's claimed artifact hash if present, else treat presence
    of the named success artifact on disk as the measurement.

    `candidate` may carry {gate.id: {"artifact": path, "hash": "sha256:..."}} to pin an exact
    success artifact (the integrity-first form). Falls back to existence of `gate.check`."""
    pin = None
    if isinstance(candidate, dict):
        pin = candidate.get(gate.id)
    if isinstance(pin, dict) and pin.get("hash"):
        ok = Measurement(kind="file_hash", source=pin.get("artifact", gate.check),
                         value=pin["hash"]).reverify()
        return (1.0 if ok else 0.0), f"test:hash-pinned {gate.check} -> {ok}"
    # No pin: the gate's own artifact must exist and hash-verify against a recorded value if
    # the gate.check carries one as 'path@sha256:...'; otherwise existence is the signal.
    src = gate.check
    if "@" in gate.check:
        src, _, claimed = gate.check.partition("@")
        ok = Measurement(kind="file_hash", source=src, value=claimed).reverify()
        return (1.0 if ok else 0.0), f"test:anchored {src} -> {ok}"
    import os
    ok = os.path.exists(src)
    return (1.0 if ok else 0.0), f"test:exists {src} -> {ok}"


def evaluate(candidate, verifier) -> GateResults:
    """Run every gate in V against `candidate`; return per-gate + aggregate results (§6)."""
    out = GateResults()
    for g in verifier.gates:
        if g.kind == "programmatic":
            score, detail = _eval_programmatic(candidate, g)
        elif g.kind == "test":
            score, detail = _eval_test(candidate, g)
        elif g.kind == "llm_judge":
            # §10: deferred. Fail LOUD, never silently pass — a soft judge is not a hard gate.
            raise NotImplementedError(
                f"gate {g.id!r}: llm_judge is deferred per §10 (the slice ships programmatic + "
                "test only). A confidence-only judge must never be the sole gate on a KPI."
            )
        else:
            raise ValueError(f"gate {g.id!r}: unknown kind {g.kind!r}")
        out.results.append(GateResult(
            gate_id=g.id, kpi=g.kpi, kind=g.kind, score=score,
            threshold=g.threshold, weight=g.weight, passed=score >= g.threshold,
            detail=detail,
        ))
    return out
