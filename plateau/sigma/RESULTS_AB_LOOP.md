# Σ Full-Operator (schema + γ loop) Round — PARTIAL (1 of 6) + post-mortem

**Status: INCOMPLETE.** The run completed 1 of 6 tasks then stalled silently for ~15h under machine saturation and was reaped without a completion signal. Recorded honestly rather than left dangling. Manifest pre-registered + frozen (`prereg_loop.json.hash` = sha256:9d43696c…918be1).

## The one task that ran: spend (141-turn original, 49-assert V)
| arm | result | trace | reading |
|---|---|---|---|
| one-shot SIGMA (recorded) | ✗ 0/1 | died at import | structure right, never ran suite |
| **SIGMA_LOOP** (max_iters=5) | **✗ 0/5, no PASS** | coll-err → coll-err → **suite RAN @iter2 (16 failed / 2 passed)** → regressed coll-err → coll-err | loop went DEEPER than one-shot (got the suite to run) but **does not converge** |
| **COLD_LOOP** (max_iters=5) | **✗ 0/5, no PASS** | [1 error] | naive + loop also fails |

**Finding (spend only):** the γ loop pushes further into the verifier than a single pass — iteration 2 actually ran the test suite (one-shot never did). But it is **non-monotone / non-convergent**: the loop regenerates the *whole package* each iteration, so fixing one import re-breaks others already correct. It oscillates instead of climbing. The fix the evidence points to: **incremental editing (patch the missing symbol, keep the rest), not full regeneration.**

## NOT RUN (5/6): xpense, todo add/done/list/persist
Never executed — the run stalled after spend. No data; no claims.

## Post-mortem: why this stalled and was not caught
- The run spawned nested `claude -p` subprocesses with **no global concurrency cap**; under load the machine hit 17→28 concurrent `claude` procs, per-call timeouts were bumped 300s→600s, and the agent was reaped mid-run.
- It was launched **without active supervision** — no heartbeat, no wall-clock deadline, no stall detector. The completion notification it relied on is **blind to a silent hang**, so the stall went undetected for ~15h.

## Required before any re-run (control, not just compute)
1. **Active heartbeat:** poll checkpoint/commit mtimes on a cadence; alert + intervene the moment progress stalls for N minutes.
2. **Wall-clock deadline** + **stall-kill + resume-from-checkpoint** (the incremental commits already make resume cheap).
3. **Hard concurrency cap (1–2 claude -p):** treat a climbing proc count / lengthening timeouts as STOP-AND-INTERVENE, not "bump and continue."

*1/6 is not a verdict on the full operator — only spend ran, and it was non-convergent. A controlled, supervised re-run is required to actually complete the experiment.*
