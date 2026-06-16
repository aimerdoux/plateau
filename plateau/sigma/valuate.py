"""plateau.sigma.valuate — the A/B capability harness + the §4 two-ladder valuation v(M).

Two distinct things live here, both scored ONLY against an OBJECTIVE verifier:

(a) `ab_capability(task, model, ...) -> ABResult` — the WITH/WITHOUT A/B harness.
    ARM_WITH   runs the Σ pattern: run_schema's bounded-context γ (Φ-hydrated, depth compounds)
               + the held clean intent (ι) + any Φ fossils carried in.
    ARM_WITHOUT runs a plain baseline: a SINGLE unstructured pass of the SAME base model on the
               SAME task, with NO Σ scaffolding (no Φ hydration, no held intent, no loop).
    BOTH arms are scored against the SAME objective V (the task's verifier). The harness returns
    per-arm gate-pass + cost + iterations.

    A6 ANTI-DRIFT (hard): an arm is NEVER scored by a judge it authored. The verifier is supplied
    by the caller (the task's objective V); neither arm constructs or mutates it. Both arms use
    the SAME base `model` callable — the ONLY difference is the scaffolding. This is what makes a
    fair test: if the pattern does not help, ARM_WITH will NOT out-pass ARM_WITHOUT, and that
    negative result is a first-class, valid outcome. The harness does not bias toward "WITH wins".

(b) `valuate(model, deliverable, verifier, ladder, k, epsilon) -> ModelValue` — §4 two-ladder
    decoder-relative valuation. Runs each prompt rung `P_λ` against M exactly k times, computes
    the pass-rate `s_M(λ)` against V, and reports `v(M) = (λ*_len, λ*_depth)` =
    `sup{ λ : s_M(λ) ≥ 1−ε }` on each of the two ladders (length@fixed-depth, depth@fixed-length).

`model` is an INJECTED callable so Phase-1 tests run deterministically with NO live LLM. Its
contract is the same as run_schema's generator: `model(intent, context, iteration) -> candidate`.
For the WITHOUT arm and the ladder, we adapt that same callable to a single-pass form.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

from .evaluate import GateResults, evaluate
from .fossils import FossilStore
from .models import Intent, Schema, Verifier
from .run_schema import RunResult, run_schema


# =============================================================================
#  (a)  WITH / WITHOUT  A/B capability harness
# =============================================================================

@dataclass
class ArmResult:
    """One arm's outcome against the OBJECTIVE V."""
    arm: str                         # "WITH" | "WITHOUT"
    all_pass: bool
    feasibility: float
    gate_pass_count: int
    gate_total: int
    iterations: int
    cost: float                      # injected per-call cost summed over the arm's model calls
    results: Optional[GateResults] = None
    candidate: object = None


@dataclass
class ABResult:
    """The A/B comparison. `winner` is descriptive only — 'WITHOUT' or 'tie' is a VALID,
    first-class outcome (the pattern is allowed to not help)."""
    task_id: str
    frozen_hash: str                 # the objective V both arms were scored against (provenance)
    with_arm: ArmResult
    without_arm: ArmResult

    @property
    def winner(self) -> str:
        w, wo = self.with_arm, self.without_arm
        # rank by (all_pass, feasibility, -cost) — higher pass, higher feasibility, lower cost.
        def key(a: ArmResult):
            return (1 if a.all_pass else 0, round(a.feasibility, 9), -a.cost)
        kw, kwo = key(w), key(wo)
        if kw == kwo:
            return "tie"
        return "WITH" if kw > kwo else "WITHOUT"

    @property
    def pattern_helped(self) -> bool:
        """True iff ARM_WITH strictly beats ARM_WITHOUT on the objective V. Reported, never
        assumed — the harness is explicitly capable of returning False."""
        return self.winner == "WITH"


def _gate_passes(results: GateResults) -> tuple:
    passed = sum(1 for r in results.results if r.passed)
    return passed, len(results.results)


def ab_capability(
    *,
    task_id: str,
    schema: Schema,
    verifier: Verifier,
    model: Callable,
    store_factory: Callable[[], FossilStore],
    cost_per_call: float = 1.0,
) -> ABResult:
    """Run both arms of the WITH/WITHOUT A/B against the SAME objective `verifier`.

    Parameters
    ----------
    schema      : the Σ Schema for ARM_WITH (its γ/Φ/ι is the scaffolding under test). Its own
                  verifier MUST be the objective `verifier` (same frozen_hash) — enforced below,
                  so an arm can never be scored by a gate set it quietly swapped (A6).
    verifier    : the OBJECTIVE V. Supplied by the caller (the task/corpus deliverable). Neither
                  arm authors or mutates it.
    model       : the shared base model callable `(intent, context, iteration) -> candidate`.
                  IDENTICAL object used by both arms — the only delta is the scaffolding.
    store_factory : returns a FRESH FossilStore per arm so ARM_WITHOUT gets no Φ benefit and the
                  two arms do not share state.
    cost_per_call : injected scalar cost charged per model invocation (deterministic accounting).
    """
    if schema.verifier.frozen_hash != verifier.frozen_hash:
        raise ValueError(
            "A6 VIOLATION: ARM_WITH schema.verifier != objective verifier "
            f"({schema.verifier.frozen_hash} != {verifier.frozen_hash}). Both arms must be "
            "scored by the SAME externally-supplied V; an arm may not author its own judge."
        )

    # instrument cost: wrap the shared model so each call is counted, without changing behavior.
    with_calls = {"n": 0}
    without_calls = {"n": 0}

    def _counting(counter):
        def _m(intent, context, iteration):
            counter["n"] += 1
            return model(intent, context, iteration)
        return _m

    # ---------------- ARM_WITH : the Σ pattern ----------------
    with_store = store_factory()
    with_run: RunResult = run_schema(schema, _counting(with_calls), with_store)
    w_passed, w_total = _gate_passes(with_run.results) if with_run.results else (0, len(verifier.gates))
    with_arm = ArmResult(
        arm="WITH",
        all_pass=with_run.all_pass,
        feasibility=with_run.feasibility,
        gate_pass_count=w_passed,
        gate_total=w_total,
        iterations=with_run.iterations,
        cost=with_calls["n"] * cost_per_call,
        results=with_run.results,
        candidate=with_run.best_candidate,
    )

    # ---------------- ARM_WITHOUT : plain single-pass baseline ----------------
    # SAME base model, SAME task, NO Σ scaffolding: no Φ hydration, no held intent carried as
    # context, no loop. We hand the model an EMPTY context and a bare intent (goal only, no
    # excluded_paths / target_invariants fed in), invoke it ONCE, and score against the SAME V.
    bare_intent = Intent(goal=schema.intent.goal)   # stripped: no Σ-held negative info / invariants
    counting_wo = _counting(without_calls)
    candidate_wo = counting_wo(bare_intent, {}, 0)   # single unstructured pass
    results_wo = evaluate(candidate_wo, verifier)    # SAME objective V
    wo_passed, wo_total = _gate_passes(results_wo)
    without_arm = ArmResult(
        arm="WITHOUT",
        all_pass=results_wo.all_pass,
        feasibility=results_wo.feasibility,
        gate_pass_count=wo_passed,
        gate_total=wo_total,
        iterations=1,
        cost=without_calls["n"] * cost_per_call,
        results=results_wo,
        candidate=candidate_wo,
    )

    return ABResult(task_id=task_id, frozen_hash=verifier.frozen_hash,
                    with_arm=with_arm, without_arm=without_arm)


# =============================================================================
#  (b)  §4 two-ladder valuation  v(M) = (λ*_len, λ*_depth)
# =============================================================================
# Decoder-relative: minimal prompt length ≈ K(D | π_M); feasible depth bounded by per-pass
# compute C_M. The ladder, k, and ε are PRE-REGISTERED before any run (the experiment manifest).
# A "ladder rung" P_λ is a prompt abstraction level; λ=0 is the full session, λ=L the maximal
# abstraction. For Phase-1 determinism, a rung is realized as a callable
# `prompt(intent, context, iteration) -> candidate` whose capability degrades as λ grows, so the
# pass-rate s_M(λ) is a real, monotone-decreasing function we can measure.

@dataclass
class LadderRung:
    """One rung P_λ of a compression ladder (§4)."""
    lam: int                         # λ index (0 = full prompt, larger = more abstraction)
    length: int                      # ℓ(P_λ) — prompt length proxy, strictly decreasing in λ
    prompt: Callable                 # (intent, context, iteration) -> candidate


@dataclass
class LadderCurve:
    """`s_M(λ)` for one ladder: pass-rate vs V at each rung (the rate-distortion curve)."""
    name: str                        # "length" | "depth"
    lambdas: list = field(default_factory=list)        # [λ]
    pass_rates: list = field(default_factory=list)      # [s_M(λ)] aligned to lambdas
    lengths: list = field(default_factory=list)         # [ℓ(P_λ)]
    lam_star: Optional[int] = None   # sup{ λ : s_M(λ) ≥ 1−ε }

    def is_monotone(self, tol: float = 1e-9) -> bool:
        """A4 sanity gate: s_M(λ) is monotone-DECREASING in λ (more abstraction ⇒ not easier)."""
        return all(b <= a + tol for a, b in zip(self.pass_rates, self.pass_rates[1:]))


@dataclass
class ModelValue:
    """v(M) = (λ*_len, λ*_depth) plus the two s_M(λ) curves (§4)."""
    lam_star_len: Optional[int]
    lam_star_depth: Optional[int]
    length_curve: LadderCurve
    depth_curve: LadderCurve
    k: int
    epsilon: float


def _pass_rate(rung: LadderRung, model_for_rung: Callable, intent: Intent,
               verifier: Verifier, k: int) -> float:
    """Run rung P_λ against M exactly k times; fraction of runs whose candidate passes ALL of V.

    `model_for_rung` is the rung's own prompt callable bound to the base model. Each of the k
    runs is an independent single pass (the ladder measures the prior π_M / per-pass compute
    C_M, not the inner loop). Scored against the OBJECTIVE V."""
    if k < 1:
        raise ValueError("valuate requires k >= 1 runs per rung")
    passes = 0
    for run_i in range(k):
        cand = model_for_rung(intent, {"lam": rung.lam}, run_i)
        if evaluate(cand, verifier).all_pass:
            passes += 1
    return passes / k


def _run_ladder(name: str, ladder: list, intent: Intent, verifier: Verifier,
                k: int, epsilon: float) -> LadderCurve:
    curve = LadderCurve(name=name)
    target = 1.0 - epsilon
    lam_star = None
    # ladder must be ordered by increasing λ with strictly decreasing length (sanity, §4.1).
    rungs = sorted(ladder, key=lambda r: r.lam)
    for r in rungs:
        s = _pass_rate(r, r.prompt, intent, verifier, k)
        curve.lambdas.append(r.lam)
        curve.pass_rates.append(s)
        curve.lengths.append(r.length)
        if s >= target - 1e-9:
            lam_star = r.lam if lam_star is None else max(lam_star, r.lam)
    curve.lam_star = lam_star
    return curve


def valuate(model, deliverable, verifier: Verifier, ladder, k: int,
            epsilon: float) -> ModelValue:
    """§4 two-ladder valuation. `ladder` is a dict with two keys, each a list of LadderRung:

        {"length": [LadderRung...],   # length@fixed-depth → prior π_M → λ*_len
         "depth":  [LadderRung...]}   # depth@fixed-length → per-pass compute C_M → λ*_depth

    `model` is the injected base callable; each rung carries its own `prompt` closure (which may
    wrap `model`). `deliverable` supplies the intent (its goal/invariants). Returns v(M) with
    both s_M(λ) curves. PRE-REGISTRATION of (ladder, k, ε) is the experiment harness's job; this
    function just executes a pre-registered protocol deterministically."""
    if k < 1:
        raise ValueError("k must be >= 1")
    if not (0.0 <= epsilon < 1.0):
        raise ValueError("epsilon must be in [0, 1)")
    if "length" not in ladder or "depth" not in ladder:
        raise ValueError("ladder must provide both 'length' and 'depth' rung lists (§4)")

    goal = deliverable.get("summary") or deliverable.get("goal") or "deliverable"
    intent = Intent(goal=str(goal))

    length_curve = _run_ladder("length", ladder["length"], intent, verifier, k, epsilon)
    depth_curve = _run_ladder("depth", ladder["depth"], intent, verifier, k, epsilon)

    return ModelValue(
        lam_star_len=length_curve.lam_star,
        lam_star_depth=depth_curve.lam_star,
        length_curve=length_curve,
        depth_curve=depth_curve,
        k=k,
        epsilon=epsilon,
    )
