# D-037 — Graph-loop abduction on the control loop (demo9) — PRE-REGISTRATION

Written and committed **before** the abductive worker is built and **before** any paid arm is
run, so it provably precedes the data. The verdict is computed from sealed records by the
locked rule below; **this document is the rule.** Engineering only — does a surprise-driven
abduction loop raise *novel-verified yield* at a fixed budget; no phenomenality.

## What this tests (and the honest framing)

The control loop's planner only fires on `if not todo:` — discovery is gated behind
exhaustion; the evidence diet is flattened tails; and ADAPT classifies rather than
hypothesizes (DRIFT, the one abductive trigger, is written to a markdown tail). The
deterministic backbone for the fix already exists and is tested: `plateau.agency.graph`
(index + `Anomaly` detectors: drift, thrash, recurrence). This experiment tests whether
adding a **budgeted abduction loop on top of that index** converts surprise into *tested
causes* — not whether it "reasons".

Honest Zahavy framing: this is manipulative-abduction-*lite*. The graph is a manipulable
world-model surrogate; the discriminator gate is the intervention. It will not invent axioms.
The falsifiable claim is narrower and is the whole point: **surprise, routed to a bounded
worker and admitted only via a discriminating gate, yields gate-passing work whose provenance
originates in an Anomaly rather than in mission decomposition.**

## Two arms (identical mission, identical wallet, identical seed)

Same `TASK.md`, same wall-clock budget, same total worker wallet (dispatch count cap), same
model, same retry budget. The ONE manipulated variable is the loop body:

1. **arm_ratchet (CONTROL)** — the loop exactly as shipped: EXECUTE first unchecked → gate →
   adapt; planner refills on empty.
2. **arm_graph (TREATMENT)** — every round also runs SENSE (`graph.ingest`) → SURPRISE
   (`graph.detect` → `Anomaly` nodes) → ABDUCE → TRIAGE → PLAN-INJECT.

### The abduction step (the only new paid dispatch), pre-committed exactly

- **ABDUCE**: for the top open Anomaly (priority = surprise × cheapness), one bounded
  `claude -p` worker gets the anomaly + its k-hop graph neighborhood **quoted as DATA**, run
  `--disallowedTools "*"` (the D-035 no-injection convention: it may reason, not act). Output
  grammar, one line:
  `H<n> | explains: A<k> | cause: <one sentence> | DISCRIMINATOR-GATE: <cmd> | EXPECT: <observable true iff this cause>`
- **TRIAGE (no LLM)**: hash-dedup against prior hypotheses; **reject any discriminator that
  already passes on the current tree** (same must-fail-now rule the planner obeys); spend from
  an **abduction wallet** of `A` per shift; drop the rest.
- **PLAN-INJECT**: survivors append as ordinary rows tagged `origin:H<n>`. The ratchet then
  handles them like any task — the discriminator IS the gate. CONFIRMED → a `lesson` in the
  signal; REFUTED → a permanent graph memory (`Hypothesis` node, resolved=false→refuted) so
  the abducer never re-proposes it (D-META EXHAUST discipline).

The discriminator gate is the Peircean move: a hypothesis is admitted only with the cheapest
observation that would *distinguish* it. That is what keeps this budgeted, injection-safe, and
preregisterable rather than a task-spawning runaway.

## Metrics (from sealed records only; never typed)

- **Primary — novel-verified yield**: of all gate-PASSING tasks in a run, the fraction whose
  provenance chain (`graph.provenance`) originates in an `Anomaly` rather than in `Mission`
  decomposition. `arm_ratchet` yield is 0 by construction (no anomaly origins exist), so the
  real test is whether `arm_graph` yield is **> 0 and the confirmed causes are real**.
- **Secondary — rounds-to-detection**: seed ONE contradiction into the mission (two tasks
  whose gates encode incompatible assumptions about the same path). Measure rounds until an
  `Anomaly` names it in each arm. Ratchet may never detect it; that is the honest contrast.
- **Guardrail — wallet discipline**: paid abduction dispatches ≤ `A`; total worker dispatches
  equal across arms (else the comparison is confounded — see below).

## Decision rule (applied without override)

- **WIN** iff `arm_graph` novel-verified yield > 0 **AND** every counted novel task's
  discriminator genuinely FAILED on the pre-injection tree (proven from sealed gate artifacts)
  **AND** total non-abduction dispatches are within ±1 across arms (equal-budget honesty).
- **NULL** iff yield is 0, or every "novel" task's discriminator would have passed anyway
  (abduction surfaced nothing a normal gate wouldn't) — a real result: *the index helps
  humans read a run, but the abduction loop adds no verified work.*
- **REFUTED-as-runaway** iff the abduction wallet is exceeded, or an injected discriminator
  passed on the current tree (measured nothing) — the guardrails failed and the design is not
  safe to ship.
- **UNSCORABLE** iff the seeded contradiction was ill-posed (both arms detect it at round 0,
  or neither can express it as a gate).

## Pre-registered predictions (honest)

| # | claim | prediction | conf |
|---|---|---|---|
| P1 | arm_graph novel-verified yield > 0 | LIKELY | 0.65 |
| P2 | ≥ half of arm_graph's novel confirmations are causes the ratchet's planner never proposed | GENUINELY OPEN | 0.45 |
| P3 | arm_graph detects the seeded contradiction in fewer rounds than arm_ratchet | LIKELY | 0.70 |
| P4 | **WIN** (P1 ∧ discriminators all must-fail ∧ equal budget) | OPEN | 0.50 |

NULL and REFUTED-as-runaway are both live and will ship. The most likely honest failure is
P2: abduction confirms causes, but ones the planner would have reached anyway — the index
then earns its place as a *monitoring* tool, not a discovery one.

## Guards (pre-committed)

- **Equal budget or it is void.** Non-abduction dispatches must match across arms; the
  abduction wallet is separate and capped. A run where arm_graph simply did more work is
  discarded, not scored.
- **Discriminator must-fail-now**, checked by the parent before injection — the same rule that
  already governs planner gates. An injected gate that passes on the current tree is a
  REFUTED-as-runaway, not a free win.
- **`--disallowedTools "*"` on every abductive dispatch**; anomaly + neighborhood are quoted
  as DATA. The abducer reasons; it never touches the tree.
- **Trust boundary unchanged**: nothing in the graph is executed; signal admission is still
  only through the gate. (Already tested: `test_nothing_in_the_graph_is_executed`.)
- No re-run to improve a number; first sealed run per arm stands.

## Integrity

Per-round records — anomalies detected, hypotheses proposed, triage decisions, injected rows,
gate artifacts, provenance of every passing task — sealed write-once under a hash-chained
manifest **before** scoring. The scorer reads only sealed records, recomputes novel-verified
yield from the sealed graph, and reproduces the verdict in a fresh process. Results are LOCAL;
nothing is promoted into README/RESULTS/BENCHMARKS without a WIN and operator go.

## Status

Backbone shipped and tested (`plateau/agency/graph.py`, `tests/test_graph.py`, 10 tests). The
abductive worker, TRIAGE wallet, and PLAN-INJECT are **NOT yet built** — this prereg is the
binding rule for building and running them, and no paid arm runs until it is committed.
