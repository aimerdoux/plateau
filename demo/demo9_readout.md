# demo9 (D-037) readout — graph-loop abduction A/B

LOCAL ARTIFACT. Prereg `demo/demo9_prereg.md` (sha256 `7ea50085…`), committed before the
runner. Raw sealed in `demo/raw9/` (chain + files verify; `score_demo9.py --verify` →
`RECOMPUTE_OK`). Results kept local per the prereg — and this one is **not a WIN to promote;
it is a negative to learn from.**

## Verdict: UNSCORABLE — and, underneath the label, the graph loop was HARMFUL here

```
arm_ratchet   dispatches=3  passing=3  novel_verified=0   final run([-1,2,3]) = (2,3,2.5)  ✓ CORRECT
arm_graph     dispatches=7  passing=4  novel_verified=1   final run([-1,2,3]) RAISES        ✗ BROKEN
```

The equal-budget guard fires first: **3 vs 7 non-abduction dispatches → UNSCORABLE** (a run
where the graph arm simply did more work is void, per prereg). But the qualitative finding is
sharper and worse than "void":

**The graph arm regressed a working solution.** It passed P1/P2/P3 — so its pipeline was
CORRECT at P3 (the sealed `P3.gate.json` exit is 0). Then abduction injected H1/H2, and a
worker executing an injected task **rewrote `clean` back to identity** (`return [x for x in
xs]`), which breaks `run` on negatives. The graph arm ended broken; the ratchet ended correct.

The ratchet solved the whole seeded mission in 3 dispatches, unaided. The graph loop spent
2.3× that and **destroyed** the solution.

## Why — three mechanical failures (the abduction *reasoning* was actually sharp)

The abducer's hypotheses were good diagnoses, which makes the loss instructive:
- one correctly identified the seeded risk: *"clean is near-identity and does not strip
  negatives, so it will corrupt P2/P3 on mixed input"*;
- another correctly critiqued **my own gate**: *"the P2 gate only matches the literal stdout
  'P2_OK' and never exercises the raise path"* — a real gate-quality observation.

The failure was in the loop mechanics around that reasoning:

1. **No regression gate.** An injected task's discriminator tested its own narrow claim; nothing
   re-ran the EARLIER passing gates (P1/P2/P3). So a worker "improving" one thing silently
   broke `clean`, and the loop never noticed. The control loop's own V3 regression exists for
   exactly this and the graph loop bypassed it.
2. **Abduction fired on FALSE drift.** No `contradiction` ever arose — real workers wrote a
   correct pipeline, so the seed never triggered. The anomalies were `drift`: a gate passed
   but its prose forecast wasn't found in the terse `P2_OK` output. That is the UNCHECKABLE
   false-positive class demo-scoring already identified — and abduction should NOT fire on it.
   It chased a non-surprise into two injected tasks.
3. **Equal-budget is unachievable as specified.** Injected tasks draw from the same task
   wallet, so the graph arm *always* out-spends the ratchet → always UNSCORABLE by that guard.
   The comparison needs a fixed TOTAL budget both arms share, not "equal non-abduction
   dispatches."

## What this means for the self-improvement thesis

**It does not support it — it cautions against it.** The proposed value was "surprise →
tested cause → novel verified work." What this run shows is that, wired as built and pointed
at a mission competent workers can already solve, the graph loop **spends more and can degrade
a correct solution**, because abduction fires on false surprises and injected work has no
regression protection. Unsupervised abduction on a runtime budget, on this evidence, is a way
to make a working system worse, not better.

The abduction *reasoning* being sharp is the one encouraging signal — the problem is the
harness, not the model's ability to hypothesize. That is fixable, but it is unproven.

## Honest run ledger (all disclosed)

| run | disposition |
|---|---|
| `demo/raw9_void_p2parse/` | **VOID** — my P2 gate had literal newlines; `parse_plan` dropped the row; mission ran as P1+P3. A harness bug in my mission, caught only after spend. |
| `demo/raw9/` | **UNSCORABLE** (budget 3 vs 7) + qualitatively HARMFUL (graph arm regressed to a broken pipeline). Reported. |

## What a valid D-037b would need (not built)

1. **A shared TOTAL dispatch budget** across arms; abduction+injected+task all count.
2. **Regression protection**: every injected task's gate must include re-running the prior
   passing gates (V3), so abduction can never regress solved work.
3. **Abduce only on genuine surprise**: `contradiction` / `thrash` / drift with a *checkable*
   expectation — never on UNCHECKABLE prose-vs-terse drift.
4. **A mission the ratchet genuinely cannot solve unaided** — the honest hard part; without it
   there is no surprise for abduction to add value on, only cost.

Until those hold, the graph *index* (monitoring: `graph touching`, `neighbors`, `detect`) is
the part that earns its place; the abduction *loop* does not, on this evidence.
