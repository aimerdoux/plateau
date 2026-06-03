"""The never-returning control loop — these tests pin the exit-condition state machine
and the bounded-context self-proof. Everything is deterministic: an injected fake clock
+ a mock step, no real time, no spend, no subprocess."""

from __future__ import annotations

from plateau.orchestrator import (
    LoopOptions, StepContext, StepResult, serve_forever,
    context_proven_bounded, default_classify_error,
)


class Clock:
    """Controllable monotonic clock. `sleep` and the mock step advance it explicitly."""
    def __init__(self):
        self.t = 0.0

    def now(self):
        return self.t

    def advance(self, dt):
        self.t += dt


def _collect(events):
    return lambda ev: events.append(ev)


def _opts(**kw):
    base = dict(budget_s=100.0, grace_s=10.0, max_iterations=10_000, stall_window=3,
                max_reseeds=2, max_retries=3, max_backoff_s=8.0, spin_rate_per_min=5,
                budget_usd=10.0, ctx_budget=180_000, drift_cap_tokens=2_000, warmup=3)
    base.update(kw)
    return LoopOptions(**base)


# ── bounded-context self-proof (the decisive evidence) ───────────────────────────
def test_context_proven_bounded_flat_is_true():
    flat = [1200, 1250, 1230, 1280, 1260, 1270, 1255]
    ok, d = context_proven_bounded(flat, _opts())
    assert ok is True
    assert d["drift"] <= 2000          # the trailing-window band gates; will_breach is diagnostic only


def test_context_proven_bounded_growing_is_false():
    grow = [1200, 6000, 11000, 16000, 21000, 26000]   # climbs toward the ceiling
    ok, d = context_proven_bounded(grow, _opts(drift_cap_tokens=2000))
    assert ok is False
    assert d["drift"] > 2000


def test_context_proven_bounded_insufficient_samples():
    ok, d = context_proven_bounded([1200], _opts())
    assert ok is True and d["status"] == "insufficient-samples"


# ── exit conditions ──────────────────────────────────────────────────────────────
def test_graceful_terminal_runs_to_floor_then_stops():
    """Milestones drain early; the loop must KEEP working (improvement) until the runtime
    floor, then stop gracefully — never idle-exit before the floor while work remains."""
    clk = Clock()
    o = _opts(budget_s=100.0)
    state = {"done": 0}

    def step(ctx: StepContext) -> StepResult:
        clk.advance(7.0)                          # each step ~7s of "work"
        state["done"] += 1
        # milestones finished by step 3; after that only improvement work remains
        mwr = state["done"] < 3
        return StepResult(blob='{"k":"%d"}' % (state["done"] % 2), gated=1,
                          dropped_stale=0, milestone_work_remains=mwr)

    rep = serve_forever(o, step, now=clk.now, sleep=clk.advance, max_loops=1000)
    assert rep["stop_reason"].startswith("graceful terminal")
    assert rep["runtime_s"] >= o.budget_s          # met the floor
    assert rep["exited_before_budget_floor"] is False
    assert rep["iterations"] > 3                    # kept working past milestone drain
    assert rep["context_bounded"] is True           # flat blob ⇒ bound holds


def test_hard_ceiling_stops_even_with_work():
    """The ceiling is unconditional: it fires past budget+grace even if work remains."""
    clk = Clock()
    o = _opts(budget_s=100.0, grace_s=10.0)

    def step(ctx):
        clk.advance(40.0)                           # blow past 110s quickly
        return StepResult(blob="{}", gated=1, milestone_work_remains=True)

    rep = serve_forever(o, step, now=clk.now, sleep=clk.advance, max_loops=1000)
    assert rep["stop_reason"].startswith("hard wall-clock ceiling")
    assert clk.now() >= o.budget_s + o.grace_s


def test_spend_ceiling_stops():
    clk = Clock()
    o = _opts(budget_usd=5.0)

    def step(ctx):
        clk.advance(1.0)
        return StepResult(blob="{}", gated=1, spend_usd=2.0, milestone_work_remains=True)

    rep = serve_forever(o, step, now=clk.now, sleep=clk.advance, max_loops=1000)
    assert rep["stop_reason"] == "spend ceiling reached"
    assert rep["spend_usd"] >= o.budget_usd


def test_maxiterations_backstop_stops():
    clk = Clock()
    o = _opts(budget_s=10_000.0, max_iterations=5)   # clock never nears budget

    def step(ctx):
        clk.advance(1.0)
        return StepResult(blob="{}", gated=1, milestone_work_remains=True)

    rep = serve_forever(o, step, now=clk.now, sleep=clk.advance, max_loops=1000)
    assert rep["stop_reason"] == "maxIterations absolute backstop"
    assert rep["iterations"] == 5


def test_stall_reseeds_then_stops():
    """Zero gated progress ⇒ reseed (not stop) while backlog remains; only stop after
    max_reseeds zero-progress reseeds."""
    clk = Clock()
    o = _opts(budget_s=10_000.0, stall_window=3, max_reseeds=2)
    seen_reseed = {"n": 0}

    def step(ctx):
        clk.advance(1.0)
        if ctx.directive == "reseed":
            seen_reseed["n"] += 1
        return StepResult(blob="{}", gated=0, milestone_work_remains=True,
                          backlog_nonempty=True)            # never makes gated progress

    rep = serve_forever(o, step, now=clk.now, sleep=clk.advance, max_loops=1000)
    assert rep["stop_reason"] == "stall: no gated progress after max reseeds"
    assert rep["task_completions"] == 0
    assert seen_reseed["n"] >= 1                            # it tried reseeding before giving up


def test_task_completion_only_on_gated_progress_no_stale_drop():
    clk = Clock()
    o = _opts(budget_s=10_000.0, max_iterations=4, stall_window=999)
    seq = [dict(gated=1, dropped_stale=0),   # counts
           dict(gated=1, dropped_stale=1),   # stale drop ⇒ negative progress, no count
           dict(gated=0, dropped_stale=0),   # no gated fact, no count
           dict(gated=2, dropped_stale=0)]   # counts

    def step(ctx):
        clk.advance(1.0)
        s = seq[ctx.iter]
        return StepResult(blob="{}", gated=s["gated"], dropped_stale=s["dropped_stale"],
                          milestone_work_remains=True)

    rep = serve_forever(o, step, now=clk.now, sleep=clk.advance, max_loops=4)
    assert rep["task_completions"] == 2     # only iters 0 and 3


def test_auth_error_stops_when_reauth_fails():
    clk = Clock()
    o = _opts(budget_s=10_000.0)

    def step(ctx):
        clk.advance(1.0)
        return StepResult(blob="{}", error="HTTP 401 Unauthorized", milestone_work_remains=True)

    rep = serve_forever(o, step, now=clk.now, sleep=clk.advance,
                        reauth=lambda: False, max_loops=1000)
    assert rep["stop_reason"].startswith("unrecoverable auth")


def test_recoverable_error_retries_then_succeeds():
    """A 429 storm backs off + retries the same item, then succeeds — does NOT crash or
    quarantine prematurely."""
    clk = Clock()
    o = _opts(budget_s=10_000.0, max_retries=5, stall_window=999)
    n = {"i": 0}
    directives = []

    def step(ctx):
        clk.advance(1.0)
        directives.append(ctx.directive)
        n["i"] += 1
        if n["i"] <= 2:
            return StepResult(blob="{}", error="429 rate limit", milestone_work_remains=True)
        # third attempt succeeds, milestones then drain
        return StepResult(blob='{"ok":1}', gated=1, milestone_work_remains=False)

    rep = serve_forever(o, step, now=clk.now, sleep=clk.advance, max_loops=50)
    # after the recoverable errors, the next attempt is flagged retry_same, and it completed
    assert "retry_same" in directives
    assert rep["task_completions"] >= 1


def test_spin_guard_throttles():
    """Many iterations inside one minute trip the spin guard, which throttles (backoff,
    no advance) rather than terminating the run."""
    clk = Clock()
    o = _opts(budget_s=50.0, grace_s=10.0, spin_rate_per_min=5)
    events = []

    def step(ctx):
        # near-zero work time ⇒ many iters land in the same 60s window
        clk.advance(0.001)
        return StepResult(blob="{}", gated=1, milestone_work_remains=True)

    rep = serve_forever(o, step, now=clk.now, sleep=clk.advance,
                        on_event=_collect(events), max_loops=1000)
    assert any(ev.get("type") == "throttle" for ev in events)
    # the ceiling (backoff-advanced clock crosses budget+grace) ultimately stops it
    assert rep["stop_reason"].startswith("hard wall-clock ceiling")


def test_step_raising_is_caught_and_triaged():
    """A raised exception becomes last_error (not a crash) and is triaged like any error."""
    clk = Clock()
    o = _opts(budget_s=10_000.0)

    def step(ctx):
        clk.advance(1.0)
        raise RuntimeError("disk corrupt: unrecoverable")   # fatal class

    # three fatals ⇒ fatal storm stop; the loop never propagates the exception
    rep = serve_forever(o, step, now=clk.now, sleep=clk.advance, max_loops=1000)
    assert rep["stop_reason"].startswith("fatal storm")


def test_default_classify_error():
    assert default_classify_error("HTTP 401") == "auth"
    assert default_classify_error("token expired") == "auth"
    assert default_classify_error("429 rate limit exceeded") == "recoverable"
    assert default_classify_error("ETIMEDOUT") == "recoverable"
    assert default_classify_error("ValueError: bad thing") == "fatal"
