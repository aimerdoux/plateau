# CONFOUNDED collection — mechanically a WIN, but NOT a valid test of the claim

Second demo8 collection. Sealed and intact; the numbers below are real and reproduce.
It is disclosed in full, and it is NOT the reported result.

## What it measured
    arm_fullhistory  tokens=[332, 807, 1195, 1531, 2029]  slope=+411.8  completed=5/5
    arm_plateau      tokens=[401, 444, 312, 292, 303]     slope= -34.8  completed=5/5
    -> mechanical verdict WIN (bounded slope <= 25% of control, at completion parity)

## Why it does not count
The treatment arm's CARRIED SIGNAL was **empty at every step**:

    "carried_self_state": {"open_goals": [], "stance": "", "lessons": [],
                           "pointers": [], "verified_facts": []}

Each arm runs in a fresh git worktree, `.plateau/signal.json` is gitignored so it does not
exist there, and the driver never populated it between steps. So `arm_plateau` was a
**NO-CONTEXT arm**, not a bounded-context arm.

That makes the WIN degenerate. What was actually shown is "these 5 tasks are independent
enough that a worker needs no carried context at all" — which is a fact about the task
chain, not evidence that a bounded signal preserves completion. Reporting it as a win for
the mechanism would be exactly the kind of over-claim this repo's guards exist to stop.

## Disposition
Re-run with the signal genuinely populated (each passed gate admitted as `T<n> done`
through the real gate, plus one bounded carry lesson per step). This is not a re-run for a
better number — the prereg forbids that, and this run ALREADY passes the WIN bar; fixing
the treatment arm risks losing it. It is a re-run because the treatment was never applied.
