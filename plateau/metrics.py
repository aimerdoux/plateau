"""plateau.metrics — context-growth slope, completion parity, bounded-context warning.

The benefit Plateau claims is measurable, so here is the measurement:

  slope(steps, prompt_tokens)            — per-step context-token growth (least sq).
  ArmCurve / decide(control, plateau)    — the two-arm verdict: does the bounded arm
                                           flatten context WITHOUT dropping completion?
  control_leaks(arm)                     — anti-rig gate: if the full-history control
                                           does NOT climb, the task is too easy and the
                                           comparison is UNSCORABLE, not a win.
  early_warning(prompt_tokens, budget)   — bounded-context foresight: fit the slope and
                                           predict how many steps until the context
                                           budget is breached. Flat slope ⇒ never.

The decision rule is the honesty contract:
  WIN        = bounded arm flattens slope AND keeps completion parity AND the slope
               difference's 95% CI excludes zero.
  PARTIAL    = flat context but completion DROPPED → amnesia, not continuity.
  NULL       = bounded arm's slope ≈ control → the signal carried nothing useful.
  UNSCORABLE = control didn't climb → can't claim a flattening that wasn't possible.

Pure-Python for the core slope/parity; the bootstrap CI imports numpy lazily so the
rest of the module (and bare_loop) needs no third-party dependency.
"""

from __future__ import annotations

from dataclasses import dataclass

SIGNAL_SLOPE_MAX_FRAC = 0.25     # bounded arm slope must be ≤ 25% of control slope


def slope(xs: list[float], ys: list[float]) -> float:
    """Least-squares slope of ys ~ xs. 0.0 if <2 points or x has no spread."""
    n = len(xs)
    if n < 2:
        return 0.0
    mx = sum(xs) / n
    my = sum(ys) / n
    denom = sum((x - mx) ** 2 for x in xs)
    if denom == 0:
        return 0.0
    return sum((xs[i] - mx) * (ys[i] - my) for i in range(n)) / denom


@dataclass
class ArmCurve:
    arm: str
    steps: list[int]
    prompt_tokens: list[int]
    completions: list[int]            # per-step completion outcome (1/0)
    slope: float = 0.0
    mean_prompt: float = 0.0
    mean_completion: float = 0.0

    def finalize(self) -> "ArmCurve":
        self.slope = round(slope([float(s) for s in self.steps],
                                 [float(t) for t in self.prompt_tokens]), 3)
        self.mean_prompt = round(sum(self.prompt_tokens) / len(self.prompt_tokens), 1)
        self.mean_completion = round(sum(self.completions) / len(self.completions), 4)
        return self


def control_leaks(control: ArmCurve) -> bool:
    """ANTI-RIG: the full-history control MUST genuinely climb. If it does not, the
    chain is too short / too easy and a flat bounded arm proves nothing → UNSCORABLE."""
    return control.slope > 0.0 and control.prompt_tokens[-1] > control.prompt_tokens[0]


def early_warning(prompt_tokens: list[int], budget: int,
                  steps: list[int] | None = None) -> dict:
    """Bounded-context foresight: fit the recent slope and predict steps-to-ceiling.

    The point of bounded context is that you can SEE the wall coming. Given the
    per-step prompt sizes so far and a context budget, extrapolate: at the current
    slope, how many more steps until prompt size crosses `budget`? Flat/negative slope
    ⇒ never breaches (steps_to_breach=None)."""
    n = len(prompt_tokens)
    xs = [float(s) for s in (steps if steps is not None else range(n))]
    m = slope(xs, [float(t) for t in prompt_tokens])
    cur = prompt_tokens[-1]
    if m <= 0:
        return {"slope": round(m, 3), "current": cur, "budget": budget,
                "steps_to_breach": None, "will_breach": False,
                "note": "slope ≤ 0 — bounded; context will not breach the budget"}
    steps_to = (budget - cur) / m
    breached = cur >= budget
    return {"slope": round(m, 3), "current": cur, "budget": budget,
            "steps_to_breach": 0 if breached else round(steps_to, 1),
            "will_breach": True,
            "note": ("ALREADY over budget" if breached
                     else f"at this slope, ~{round(steps_to,1)} steps until budget")}


def _bootstrap_slope_diff_ci(control: ArmCurve, plateau: ArmCurve,
                             n_boot: int = 5000, seed: int = 0) -> dict:
    """Bootstrap 95% CI on (slope_control - slope_plateau) by paired resampling of
    step indices. Deterministic via fixed seed. CI excluding zero ⇒ real difference.
    Imports numpy lazily so the core has no hard third-party dependency."""
    import numpy as np
    rng = np.random.default_rng(seed)
    k = len(control.steps)
    diffs = np.empty(n_boot)
    for i in range(n_boot):
        idx = rng.integers(0, k, size=k)
        cs = slope([float(j) for j in idx], [float(control.prompt_tokens[j]) for j in idx])
        ss = slope([float(j) for j in idx], [float(plateau.prompt_tokens[j]) for j in idx])
        diffs[i] = cs - ss
    lo, hi = float(np.percentile(diffs, 2.5)), float(np.percentile(diffs, 97.5))
    return {"lo": round(lo, 3), "hi": round(hi, 3),
            "excludes_zero": (lo > 0.0) or (hi < 0.0)}


def decide(control: ArmCurve, plateau: ArmCurve, *, with_ci: bool = True) -> dict:
    """Apply the locked decision rule. Returns the verdict + every sub-claim.

    `plateau` is the bounded-context arm (emit/inflate/gate); `control` is the
    full-history arm. with_ci=False skips the numpy bootstrap (pure-Python path)."""
    control = control.finalize()
    plateau = plateau.finalize()

    leaks = control_leaks(control)
    c_slope_flat = leaks and plateau.slope <= SIGNAL_SLOPE_MAX_FRAC * control.slope
    parity = plateau.mean_completion >= control.mean_completion
    if with_ci and leaks:
        ci = _bootstrap_slope_diff_ci(control, plateau)
    else:
        ci = {"lo": None, "hi": None, "excludes_zero": bool(leaks and c_slope_flat)}

    if not leaks:
        verdict = ("UNSCORABLE — full-history control did not climb (slope not "
                   "materially positive). Task too easy/short; lengthen, do not score.")
    elif c_slope_flat and parity and ci["excludes_zero"]:
        verdict = ("WIN — Plateau holds a near-flat context slope at completion parity "
                   "while full-history climbs. Bounded context, no amnesia.")
    elif c_slope_flat and not parity:
        verdict = ("PARTIAL — Plateau flattened context but DROPPED completion: "
                   "amnesia, not continuity. Report the lost-step class; NOT a win.")
    elif not c_slope_flat:
        verdict = ("NULL — Plateau's slope ≈ control: the signal carried as much as "
                   "full history (or failed to compress). Fix emit before scaling.")
    else:
        verdict = "INCONCLUSIVE — slope flattened but CI includes zero; needs more steps."

    return {
        "metric": "context_growth_slope",
        "control": {"slope": control.slope, "mean_prompt": control.mean_prompt,
                    "mean_completion": control.mean_completion,
                    "prompt_first_last": [control.prompt_tokens[0], control.prompt_tokens[-1]]},
        "plateau": {"slope": plateau.slope, "mean_prompt": plateau.mean_prompt,
                    "mean_completion": plateau.mean_completion,
                    "prompt_first_last": [plateau.prompt_tokens[0], plateau.prompt_tokens[-1]]},
        "headline_slope_diff": round(control.slope - plateau.slope, 3),
        "claims": {"context_flattened_<=25%_control": bool(c_slope_flat),
                   "completion_parity": bool(parity),
                   "anti_rig_control_climbs": bool(leaks)},
        "slope_diff_ci95": ci,
        "verdict": verdict,
    }


def run_mock_plumbing() -> dict:
    """LABELED PLUMBING — synthetic per-step token series, NOT a result. Proves the
    slope math, the anti-rig gate, and each verdict branch fire before any real run."""
    out = {}
    control = ArmCurve("control", list(range(6)),
                       [3000, 8000, 13000, 18000, 23000, 28000], [1, 1, 1, 1, 1, 1])
    flat = ArmCurve("plateau", list(range(6)),
                    [1200, 1250, 1230, 1280, 1260, 1270], [1, 1, 1, 1, 1, 1])
    out["WIN_shape"] = decide(control, flat)
    amnesia = ArmCurve("plateau", list(range(6)),
                       [1200, 1250, 1230, 1280, 1260, 1270], [1, 0, 0, 0, 1, 0])
    out["PARTIAL_shape"] = decide(control, amnesia)
    flat_control = ArmCurve("control", list(range(6)), [3000] * 6, [1] * 6)
    out["UNSCORABLE_shape"] = decide(flat_control, flat)
    out["LABEL"] = "MOCK PLUMBING — synthetic token series, NOT a continuity result"
    return out
