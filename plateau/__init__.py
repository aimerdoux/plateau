"""plateau — bounded, predictable context for long-horizon agents.

A long-running agent's context window is its scarcest resource. The naive loop carries
the full transcript forward, so context grows every step until it hits the ceiling and
the agent degrades or dies. Plateau replaces "carry everything" with "carry a small,
re-grounded signal": at each step you emit a compact RelationalState (goals, stance,
lessons, pointers, gated facts), and inflate it at the next step instead of replaying
history. Context stays flat. The catch that keeps it honest: a fact may only enter the
carried signal if it passes the gate — it must be backed by a Measurement that
re-verifies against the live environment. Bounded context is cheap; this is what keeps
it from filling with confident fabrications.

Host-agnostic by construction: this package imports nothing host-specific. Wire it to
any agent runtime with a thin adapter (see adapters/). examples/bare_loop.py runs the
whole loop in plain Python with no agent framework at all.
"""

from __future__ import annotations

from .signal import (
    Measurement,
    Thought,
    RelationalState,
    SelfState,
    GateResult,
    gate,
    apply_gate,
    set_ground_root,
    ground_root,
)
from .continuum import emit, inflate, ground, Inflated, Grounding
from .metrics import (
    ArmCurve,
    slope,
    decide,
    control_leaks,
    early_warning,
)
from .orchestrator import (
    LoopOptions,
    StepContext,
    StepResult,
    serve_forever,
    should_continue,
    context_proven_bounded,
    default_classify_error,
)

__version__ = "0.2.0"

__all__ = [
    "Measurement", "Thought", "RelationalState", "SelfState", "GateResult",
    "gate", "apply_gate", "set_ground_root", "ground_root",
    "emit", "inflate", "ground", "Inflated", "Grounding",
    "ArmCurve", "slope", "decide", "control_leaks", "early_warning",
    "LoopOptions", "StepContext", "StepResult", "serve_forever",
    "should_continue", "context_proven_bounded", "default_classify_error",
]
