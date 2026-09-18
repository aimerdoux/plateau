"""plateau.sigma.refine — 𝒮, the outer self-improvement loop (§2, §3).

`refine(schema, outcomes) -> Schema`. The SAME fixpoint search as γ, but at the SCHEMA altitude:
given a Schema and the outcomes of running it (RunResults / ABResults / gate failures), 𝒮 returns
a BETTER Schema. It MAY rewrite ι (sharpen the goal, accrue excluded_paths from observed dead
ends), Φ (carry forward fossils paid in the run), and γ (adjust the loop budget). It MUST NOT
rewrite V.

§3 — THE INVARIANT (NON-NEGOTIABLE), enforced three ways here:
  1. V is taken READ-ONLY: the returned Schema carries the SAME `Verifier` object (same identity,
     therefore the same frozen_hash). We never construct a new Verifier in refine().
  2. The refine-guard `Schema.assert_v_unchanged(original)` is CALLED on the output before return
     — it asserts frozen_hash equality and raises INVARIANT VIOLATION otherwise.
  3. A belt-and-suspenders assertion on frozen_hash directly, so the guarantee holds even if the
     guard is ever weakened.

An unanchored outer loop would optimize Σ to pass gates it also authored, collapsing into a
private idiolect (drift, §9.3). Holding V frozen + externally anchored is the ONLY guard. 𝒮
sharpens how we *reach* D; it can never redefine *what D is*. A genuinely different verifier is a
NEW session with a new V — never an in-session mutation.

`outcomes` is intentionally permissive: a list of RunResult-like / ABResult-like objects, or
dicts. refine() reads only fields it understands and ignores the rest, so it composes with both
the inner loop and the A/B harness.
"""

from __future__ import annotations

from typing import Iterable

from .models import Intent, LoopConfig, Schema


def _excluded_from_outcomes(outcomes: Iterable) -> list:
    """Mine NEW dead ends from run outcomes → accrete into ι.excluded_paths (negative info, §1.1).

    A run that did NOT pass its gates is evidence the approach it took is (so far) a dead end; we
    record a compact, deterministic marker so a weaker decoder on the next pass does not re-pay
    for the same failure. We never invent dead ends not grounded in an outcome."""
    dead = []
    for o in outcomes or []:
        all_pass = _get(o, "all_pass", None)
        if all_pass is False:
            failing = _get(o, "failing", None)
            if callable(failing):
                try:
                    failing = failing()
                except Exception:
                    failing = None
            if not failing:
                res = _get(o, "results", None)
                if res is not None and hasattr(res, "failing"):
                    try:
                        failing = res.failing()
                    except Exception:
                        failing = None
            marker = ("failed-gates:" + ",".join(sorted(map(str, failing)))) if failing \
                else "failed-run"
            if marker not in dead:
                dead.append(marker)
    return dead


def _fossils_from_outcomes(outcomes: Iterable) -> list:
    """Collect fossil hashes paid during the runs → carry forward in Φ (depth paid once, §1.3)."""
    hashes = []
    for o in outcomes or []:
        fw = _get(o, "fossils_written", None)
        if isinstance(fw, (list, tuple)):
            for h in fw:
                if h not in hashes:
                    hashes.append(h)
    return hashes


def _best_feasibility(outcomes: Iterable) -> float:
    best = 0.0
    for o in outcomes or []:
        f = _get(o, "feasibility", None)
        if isinstance(f, (int, float)):
            best = max(best, float(f))
    return best


def _get(o, attr, default):
    if isinstance(o, dict):
        return o.get(attr, default)
    return getattr(o, attr, default)


def refine(schema: Schema, outcomes) -> Schema:
    """𝒮 — return a NEW Schema improved from `outcomes`, carrying V UNCHANGED (§3).

    Rewrites permitted (and only these):
      ι : accrete newly-observed dead ends into excluded_paths (negative information).
      γ : widen max_iterations when the last runs exhausted budget without passing (give the
          inner loop more room), keep state_handle so depth still compounds.
      Φ : carry forward the fossils paid during the runs.
    V is NEVER touched: the same Verifier object is reused, and the §3 guard certifies it.
    """
    original = schema

    # ---- ι : accrete dead ends, keep everything else ----
    new_excluded = tuple(schema.intent.excluded_paths) + tuple(
        d for d in _excluded_from_outcomes(outcomes)
        if d not in schema.intent.excluded_paths
    )
    new_intent = Intent(
        goal=schema.intent.goal,
        target_invariants=schema.intent.target_invariants,
        constraints=schema.intent.constraints,
        excluded_paths=new_excluded,
        source_session_hash=schema.intent.source_session_hash,
    )

    # ---- γ : widen the wall iff a run exhausted budget without passing; never shrink it ----
    exhausted_without_pass = any(
        _get(o, "stop_reason", None) == "budget_exhausted" and _get(o, "all_pass", None) is False
        for o in (outcomes or [])
    )
    new_max = schema.loop.max_iterations + (2 if exhausted_without_pass else 0)
    new_loop = LoopConfig(
        generator_policy=schema.loop.generator_policy,
        max_iterations=new_max,
        stop_rule=schema.loop.stop_rule,
        state_handle=schema.loop.state_handle,   # REAL handle preserved → depth keeps compounding
        fossil_write=schema.loop.fossil_write,
    )

    # ---- Φ : carry forward paid fossils (as carried records; the durable store is separate) ----
    carried_phi = tuple(schema.phi) + tuple(
        h for h in _fossils_from_outcomes(outcomes) if h not in schema.phi
    )

    # ---- V : READ-ONLY. Reuse the SAME Verifier object — identity ⇒ same frozen_hash. ----
    refined = Schema(
        intent=new_intent,
        verifier=schema.verifier,   # ← unchanged, by reference. §3.1/§3.2.
        loop=new_loop,
        phi=carried_phi,
    )

    # ---- §3.3 refine-guard + belt-and-suspenders direct assertion ----
    refined.assert_v_unchanged(original)
    assert refined.verifier.frozen_hash == original.verifier.frozen_hash, \
        "INVARIANT VIOLATION: V mutated across refine()"
    return refined
