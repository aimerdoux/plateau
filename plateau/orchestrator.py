"""plateau.orchestrator — the never-returning bounded-context control loop.

`serve_forever()` drives a long task across many steps but NEVER returns before an
EXPLICIT exit condition fires: a wall-clock or spend ceiling, a guaranteed graceful
terminal (runtime floor met AND milestone work drained), a loose iteration backstop, or
a stall that cannot make gated progress. Its own carried state is ONE signal blob per
step, so context stays FLAT — and the loop logs `_tok(blob)` every step so the bound is
MEASURED, not asserted (drop the `blob_tokens` series into `metrics.decide` / read the
`context_bounded` verdict here).

Separation of concerns — and the safety boundary:

  THIS MODULE is pure control + KPI accounting. It decides go / throttle / stop, tracks
  runtime and gated completions, and proves the context bound. It cannot spend money,
  run a shell, touch git, or open a PR.

  THE INJECTED `step(ctx) -> StepResult` callback owns every side effect — spawning a
  headless worker (PAID), running repo tests, opening a DRAFT PR. The human PR-gate lives
  there too (surfaced via `StepResult.pr_ready` + an `on_event` hook). Wire a real `step`
  at launch; a deterministic mock proves the whole machine for free.

Bright line: this measures runtime, gated completions, and context efficiency. It is
silent on understanding or quality — a gated artifact means a test passed and the result
re-verifies, NOT that the code is correct or the tests meaningful.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

from .driver import _tok            # SAME tokenizer the driver/metrics use ⇒ bound is comparable
from .metrics import early_warning


# ──────────────────────────────────────────────────────────── options & I/O shapes
@dataclass(frozen=True)
class LoopOptions:
    """Every knob the control loop reads. Seconds, not ms (Python idiom)."""
    budget_s: float = 8 * 3600          # runtime FLOOR — never idle-exit before this while work remains
    grace_s: float = 30 * 60            # hard ceiling ABOVE the floor; unconditional stop
    max_iterations: int = 10_000        # loose backstop; must never bind a healthy run first
    stall_window: int = 8               # iters of ZERO gated progress before a reseed
    max_reseeds: int = 3                # zero-progress reseeds before STOP
    max_retries: int = 6                # consecutive recoverable retries at one site
    max_backoff_s: float = 60.0         # backoff ceiling
    spin_rate_per_min: int = 20         # iters/min that signals a fast-spin (throttle)
    budget_usd: float = 40.0            # HARD spend ceiling
    ctx_budget: int = 180_000           # context-token budget for the breach forecast
    drift_cap_tokens: int = 2_000       # carried-blob drift band (max - baseline)
    warmup: int = 3                     # iters used to establish the blob-token baseline


@dataclass
class StepContext:
    """What the injected `step` receives. The `directive` tells it what the controller
    decided this iteration so item-level mechanics (pick/reseed/skip) stay in the step's
    domain, not in the controller."""
    blob: str
    iter: int
    directive: str          # "normal" | "retry_same" | "reseed" | "quarantine"
    last_error: object
    runtime_s: float


@dataclass
class StepResult:
    """What the injected `step` returns. `blob` is the ONLY thing carried to the next
    iteration — keep it bounded (that is the whole point)."""
    blob: str
    gated: int = 0                       # facts the gate ADMITTED this step (hash-reverified)
    dropped_stale: int = 0               # carried facts dropped at inflate ⇒ negative progress
    spend_usd: float = 0.0               # incremental PAID spend this step
    pr_ready: bool = False               # milestone hit a push/PR boundary (human gate)
    milestone_work_remains: bool = True  # is there still MILESTONE (not improvement) work?
    backlog_nonempty: bool = True        # any next item at all (milestone OR improvement)?
    error: object = None                 # an exception/marker if the step failed (drives triage)


# ──────────────────────────────────────────────────────────── error classification
_AUTH = re.compile(r"\b401\b|\b403\b|auth|token expired|unauthor", re.I)
_RECOVERABLE = re.compile(r"rate.?limit|\b429\b|\b503\b|ETIMEDOUT|overloaded|ECONNRESET|timeout", re.I)


def default_classify_error(e: object) -> str:
    """auth → re-auth-or-stop (never backoff-spin on dead creds); recoverable → capped
    retry then quarantine; everything else → fatal (quarantine; storm ⇒ stop)."""
    s = str(e)
    if _AUTH.search(s):
        return "auth"
    if _RECOVERABLE.search(s):
        return "recoverable"
    return "fatal"


# ──────────────────────────────────────────────────────────── controller state
@dataclass
class _State:
    opts: LoopOptions
    t0: float
    classify: Callable[[object], str]
    reauth: Callable[[], bool]
    on_event: Callable[[dict], None]
    blob: str = ""
    iter: int = 0
    no_progress_iters: int = 0
    reseed_count: int = 0
    retries_here: int = 0
    consecutive_deadletters: int = 0
    spend_usd: float = 0.0
    last_error: object = None
    task_completions: int = 0
    runtime_s: float = 0.0
    pending_backoff: float = 0.0
    directive: str = "normal"
    milestone_work_remains: bool = True
    backlog_nonempty: bool = True
    stop_reason: str = ""
    blob_tokens: list = field(default_factory=list)
    iter_times: list = field(default_factory=list)


def _iters_in_last_60s(c: _State, now: float) -> int:
    return sum(1 for t in c.iter_times if t > now - 60.0)


def _bump_backoff(c: _State) -> None:
    c.pending_backoff = min(c.opts.max_backoff_s, c.pending_backoff * 2 or 1.0)


# ──────────────────────────────────────────────────────────── the decision function
def should_continue(c: _State, now: float) -> tuple[str, str]:
    """Decide the next action at the TOP of an iteration. Returns (action, reason) where
    action ∈ {"go", "throttle", "stop"}; mutates `c` for the bookkeeping each branch
    implies (backoff, retry/reseed counters, directive). First match wins, in this order:
    unconditional ceilings → error triage → backstop → stall → graceful terminal → floor."""
    o = c.opts
    el = now - c.t0

    # 0 ── UNCONDITIONAL CEILINGS (nothing overrides) ─────────────────────────────
    if el >= o.budget_s + o.grace_s:
        return ("stop", "hard wall-clock ceiling (budget+grace) reached")
    if c.spend_usd >= o.budget_usd:
        return ("stop", "spend ceiling reached")
    if _iters_in_last_60s(c, now) > o.spin_rate_per_min:
        _bump_backoff(c)
        return ("throttle", "fast-spin guard: backoff, do not advance")

    # 1 ── ERROR TRIAGE ───────────────────────────────────────────────────────────
    e = c.last_error
    if e is not None:
        cls = c.classify(e)
        if cls == "auth":
            if c.reauth():
                c.last_error = None
                c.directive = "retry_same"
                c.pending_backoff = 0.0
                return ("go", "re-authed; retry the same item")
            return ("stop", "unrecoverable auth — needs human re-auth")
        if cls == "recoverable":
            if c.retries_here >= o.max_retries:
                c.last_error = None
                c.retries_here = 0
                c.consecutive_deadletters += 1
                c.directive = "quarantine"
                if c.consecutive_deadletters >= 3:
                    return ("stop", "fatal storm: retries exhausted on 3 items")
                return ("go", "retry budget exhausted → quarantine item, take next")
            c.retries_here += 1
            _bump_backoff(c)
            c.directive = "retry_same"
            return ("go", f"recoverable retry {c.retries_here}/{o.max_retries}")
        # fatal / unknown
        c.last_error = None
        c.consecutive_deadletters += 1
        c.directive = "quarantine"
        if c.consecutive_deadletters >= 3:
            return ("stop", "fatal storm: 3 non-recoverable errors")
        return ("go", "non-recoverable error → quarantine item, take next")

    # no error ⇒ the transient counters reset
    c.retries_here = 0
    c.pending_backoff = 0.0

    # 2 ── BACKSTOP (loose; must never end a real run first) ──────────────────────
    if c.iter >= o.max_iterations:
        return ("stop", "maxIterations absolute backstop")

    # 3 ── STALL on GATED progress (NOT wall-clock) ───────────────────────────────
    if c.no_progress_iters >= o.stall_window:
        if c.backlog_nonempty:
            if c.reseed_count >= o.max_reseeds:
                return ("stop", "stall: no gated progress after max reseeds")
            c.reseed_count += 1
            c.no_progress_iters = 0
            c.directive = "reseed"
            return ("go", "stall → reseed the designer")
        # nothing queued ⇒ fall through to terminal

    # 4 ── GRACEFUL TERMINAL (floor met AND milestone work drained) ───────────────
    # Improvement work does NOT keep the loop alive past the floor — only milestone work
    # does. Before the floor, `el < budget_s`, so this never fires and the floor branch
    # keeps the loop working (the step supplies improvement items so there is always a next).
    if el >= o.budget_s and not c.milestone_work_remains:
        return ("stop", "graceful terminal: runtime floor met and milestone work drained")

    # 5 ── THE FLOOR ──────────────────────────────────────────────────────────────
    c.directive = "normal"
    return ("go", "runtime floor: <budget or work remains")


# ──────────────────────────────────────────────────────────── bounded-context proof
def _median(xs: list) -> float:
    s = sorted(xs)
    n = len(s)
    if n == 0:
        return 0.0
    m = n // 2
    return float(s[m]) if n % 2 else (s[m - 1] + s[m]) / 2.0


def context_proven_bounded(blob_tokens: list, opts: LoopOptions) -> tuple[bool, dict]:
    """The decisive self-proof: the CARRIED blob (emit(signal)) must stay inside a drift
    BAND over a trailing window — bounded iff `max(window) - min(window) ≤ drift_cap`.

    A trailing-window band, deliberately, not a slope/forecast gate:
      • A band (not slope≤0) so a healthy noisy-flat trace doesn't false-fail on jitter.
      • A trailing window (not drift from the first baseline) so a series that fills its
        caps early and then plateaus HIGHER reads as bounded — it is flat *now*, which is
        what "bounded context" means; only an ongoing climb breaks the band.
    `early_warning` (slope / will_breach / steps_to_breach) is reported as a DIAGNOSTIC
    only — it flags True for any positive slope regardless of how distant the budget is,
    so it must not gate the verdict. <2 samples ⇒ not yet falsifiable (returns True)."""
    if len(blob_tokens) < 2:
        return True, {"status": "insufficient-samples", "n": len(blob_tokens)}
    win = blob_tokens[-max(opts.warmup * 2, 4):]
    drift = max(win) - min(win)
    ew = early_warning(blob_tokens, opts.ctx_budget)
    ok = drift <= opts.drift_cap_tokens
    return ok, {"status": "scored", "window": len(win), "drift": round(drift, 1),
                "drift_cap": opts.drift_cap_tokens, "slope": ew["slope"],
                "will_breach": ew["will_breach"], "steps_to_breach": ew["steps_to_breach"],
                "ctx_budget": opts.ctx_budget}


# ──────────────────────────────────────────────────────────── the never-returning loop
def serve_forever(
    opts: LoopOptions,
    step: Callable[[StepContext], StepResult],
    *,
    initial_blob: str = "",
    now: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    classify_error: Callable[[object], str] = default_classify_error,
    reauth: Callable[[], bool] = lambda: False,
    on_event: Callable[[dict], None] = lambda ev: None,
    max_loops: Optional[int] = None,
) -> dict:
    """Run the bounded loop until an explicit exit condition fires, then return a report.

    `step` is the only required injection — it does the (paid, side-effecting) work and
    returns a `StepResult` whose `blob` is carried forward. `now`/`sleep`/`reauth` are
    injectable so the whole machine is deterministic + free in tests. `max_loops` is a
    test-only hard stop so a misconfigured run can't spin forever in CI; leave it None in
    production (the ceilings are the real bound)."""
    c = _State(opts=opts, t0=now(), classify=classify_error, reauth=reauth,
               on_event=on_event, blob=initial_blob)

    while True:
        action, reason = should_continue(c, now())

        if action == "stop":
            c.stop_reason = reason
            on_event({"type": "stop", "reason": reason, "iter": c.iter})
            break

        if action == "throttle":
            on_event({"type": "throttle", "reason": reason, "backoff_s": c.pending_backoff})
            sleep(c.pending_backoff)
            if max_loops is not None and c.iter >= max_loops:
                c.stop_reason = "test cap: max_loops"
                break
            continue

        # action == "go"
        if c.pending_backoff:
            sleep(c.pending_backoff)
        ctx = StepContext(blob=c.blob, iter=c.iter, directive=c.directive,
                          last_error=c.last_error, runtime_s=now() - c.t0)
        try:
            res = step(ctx)
        except Exception as exc:                 # a raised step error becomes last_error
            res = StepResult(blob=c.blob, error=exc)

        c.iter += 1
        c.iter_times.append(now())
        c.spend_usd += max(0.0, res.spend_usd)
        c.last_error = res.error
        c.blob = res.blob
        c.blob_tokens.append(_tok(res.blob))

        # task_completions advances ONLY on gated progress with no stale drop (the gate,
        # never the model's word, moves this counter).
        if res.error is None and res.gated > 0 and res.dropped_stale == 0:
            c.task_completions += 1
            c.no_progress_iters = 0
            c.reseed_count = 0
            c.consecutive_deadletters = 0
        else:
            c.no_progress_iters += 1

        c.milestone_work_remains = res.milestone_work_remains
        c.backlog_nonempty = res.backlog_nonempty
        c.runtime_s = now() - c.t0

        ok, detail = context_proven_bounded(c.blob_tokens, opts)
        on_event({"type": "kpi", "iter": c.iter, "runtime_s": round(c.runtime_s, 1),
                  "task_completions": c.task_completions, "blob_tokens": c.blob_tokens[-1],
                  "blob_drift": detail.get("drift"), "facts_dropped": res.dropped_stale,
                  "spend_usd": round(c.spend_usd, 4), "context_bounded": ok,
                  "will_breach": detail.get("will_breach")})

        if res.pr_ready and res.error is None:
            on_event({"type": "pr_gate", "iter": c.iter,
                      "note": "milestone push/PR-ready — human approve required; parked, continuing"})

        if max_loops is not None and c.iter >= max_loops:
            c.stop_reason = "test cap: max_loops"
            break

    ok, detail = context_proven_bounded(c.blob_tokens, opts)
    return {"stop_reason": c.stop_reason, "iterations": c.iter,
            "runtime_s": round(c.runtime_s, 1), "task_completions": c.task_completions,
            "spend_usd": round(c.spend_usd, 4),
            "exited_before_budget_floor": c.runtime_s < opts.budget_s,
            "context_bounded": ok, "bounded_detail": detail, "blob_tokens": c.blob_tokens}


# ──────────────────────────────────────────────────────────── free dry-run self-proof
def _demo() -> dict:
    """FREE, deterministic dry-run: a fake clock + a mock step compress an '8h' run into
    microseconds and SELF-PROVE the context bound. NOT a paid run and NOT a result — it
    proves the loop + the bounded-context verdict (and that the verdict discriminates a
    growing transcript) before any real PAID `step` is wired."""
    clk = [0.0]
    def now() -> float: return clk[0]
    def sleep(dt: float) -> None: clk[0] += dt
    opts = LoopOptions(budget_s=60.0, grace_s=10.0, stall_window=4, max_reseeds=2)

    # bounded arm: the carried blob stays small no matter how many steps run (the point)
    st = {"n": 0}
    def bounded_step(ctx: StepContext) -> StepResult:
        clk[0] += 5.0
        st["n"] += 1
        blob = '{"goals":["m1","m2","m3"],"stance":"bounded","facts":%d}' % (st["n"] % 4)
        return StepResult(blob=blob, gated=1, dropped_stale=0,
                          milestone_work_remains=st["n"] < 3, pr_ready=st["n"] <= 3)
    bounded = serve_forever(opts, bounded_step, now=now, sleep=sleep, max_loops=10_000)

    # control arm: the carried blob GROWS like a transcript ⇒ the proof MUST fail
    clk[0] = 0.0
    g = {"n": 0, "buf": ""}
    def growing_step(ctx: StepContext) -> StepResult:
        clk[0] += 5.0
        g["n"] += 1
        g["buf"] += "x" * 4000
        return StepResult(blob='{"t":"%s"}' % g["buf"], gated=1,
                          milestone_work_remains=g["n"] < 3)
    control = serve_forever(opts, growing_step, now=now, sleep=sleep, max_loops=10_000)

    bt, ct = bounded["blob_tokens"], control["blob_tokens"]
    return {
        "LABEL": "DRY / MOCK — fake clock, mock step; NOT a paid run and NOT a result",
        "bounded_arm": {"stop": bounded["stop_reason"], "iterations": bounded["iterations"],
                        "task_completions": bounded["task_completions"],
                        "context_bounded": bounded["context_bounded"],
                        "blob_tokens_first_last": [bt[0], bt[-1]],
                        "drift": bounded["bounded_detail"].get("drift")},
        "control_arm_growing": {"stop": control["stop_reason"],
                                "context_bounded": control["context_bounded"],
                                "blob_tokens_first_last": [ct[0], ct[-1]],
                                "drift": control["bounded_detail"].get("drift")},
        "reading": ("bounded arm holds context_bounded=True (flat carried blob, graceful "
                    "terminal at the runtime floor); growing arm is False (the blob climbs). "
                    "The self-proof discriminates. Wire a real PAID `step` to run for real."),
    }


if __name__ == "__main__":
    import json
    print(json.dumps(_demo(), indent=2))
