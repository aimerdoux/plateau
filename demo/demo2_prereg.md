# Plateau recall-only demo (demo2) — PRE-REGISTRATION

Written and committed BEFORE the harness is built and BEFORE any query is dispatched.
The verdict is computed from sealed data by the locked rule below; this document is the
rule. This replaces demo1's confounded completion axis (which mixed in arithmetic).

**Bright line (kept, engineering only):** this measures context EFFICIENCY and
RECALL-PRESERVATION — how many tokens of context each arm carries, and whether a stored
fact can still be retrieved as it sinks into history. It makes NO claim about
understanding, coherence-as-experience, or phenomenality.

## The task (pure recall, no arithmetic)

A register ledger of VERBATIM values (`program2.py`, deterministic). `SET R = v` stores a
globally-unique value; `QUERY R` asks "what is R now?" — the correct answer is R's latest
value, copied verbatim. **There is no computation**, so a wrong answer can only be a
memory/context failure, never arithmetic. That is the whole point: it makes the recall
axis interpretable.

- A small pool of NOISE registers (N0–N7) is re-set repeatedly as filler, growing the
  control transcript WITHOUT growing the register file (so Plateau stays bounded).
- 14 TARGET registers are each set once, then queried at a controlled **distance** (steps
  between the set and the query): near {2,3,4,5}, mid {7,9,11,13}, far {16,22,28,34,40,48}.
- At each query the control transcript is 10 → 263 steps long (grows with distance); the
  Plateau register file is a fixed 22 entries. The queried value is still current, so it
  is present in BOTH arms' context — buried `distance` steps back for control, one short
  line for Plateau.

## Two arms (identical task, identical scoring)

1. **FULL-HISTORY control** — prompt = the whole prior transcript (all sets + noise) + the
   query. Grows every step.
2. **PLATEAU** — prompt = the current register file (gated signal) + the query. Bounded.

Queries are independent (state changes only at deterministic SET steps), so all 14 run in
parallel; each is scored against the program's GOLD.

## Primary metric: recall accuracy vs distance, per arm

For each arm, recall accuracy in each distance bin (near/mid/far), plus the recall-vs-
distance least-squares slope across all 14 queries. Also: control prompt-token slope
(anti-rig) and a "stale-distractor" error count (control returning an overwritten value).

## Anti-rig (gating) + degeneracy guard

- Control prompt tokens MUST climb with step (they will: 10→263 steps). If not → UNSCORABLE.
- **Control recall MUST degrade with distance**: `control_far ≤ control_near − 0.25`. If
  control recall is flat across distance, the chain didn't bury facts deeply enough →
  **UNSCORABLE, lengthen** (do not score a non-existent degradation).
- Queried facts genuinely sink: far distances 16–48, buried under 86–263 steps of noise.

## Locked predictions (honest, both directions)

| # | claim | conf | if it fails |
|---|---|---|---|
| R1 | control tokens climb | 0.95 | UNSCORABLE |
| R2 | control recall degrades with distance (far ≤ near − 0.25) | 0.65 | UNSCORABLE — facts didn't sink; lengthen |
| R3 | Plateau recall stays flat (far ≥ near − 0.15) AND high (far ≥ 0.70) | 0.80 | NULL — Plateau also degrades |
| R4 | Plateau far recall > control far recall | 0.70 | NULL — no recall advantage |
| R5 | WIN = R1 ∧ R2 ∧ R3 ∧ R4 | 0.55 | report the failing leg |

**Honest stance — NULL can win.** Two ways this is NOT a win, pre-committed:
- If a strong model reads the long transcript fine and **control recall does NOT degrade**
  (R2 fails) → UNSCORABLE: the task is too easy to bury facts; I will say the demo could
  not create the degradation it set out to measure, and the headline stays the (trivial)
  token-bound result.
- If **Plateau's recall also degrades** with distance (R3 fails — the signal drops facts
  under its own compression) → NULL, and I will say Plateau did not beat full-history on
  recall preservation on this task. The README then ships as an honest negative + a
  working tool.

## Decision rule (applied without override)

- **WIN:** R1 ∧ R2 ∧ R3 ∧ R4.
- **NULL:** R1 ∧ R2 hold (control degrades) but R3 or R4 fails (Plateau no better).
- **UNSCORABLE:** R1 fails (no token climb) OR R2 fails (control recall didn't degrade →
  facts didn't sink → can't measure preservation).

## Integrity (seal-before-score)

Raw per-query records (arm, distance, answer, correct, stale-distractor flag,
prompt_tokens) are written to `demo/raw2/` and SEALED write-once BEFORE scoring. The score
reads only the sealed file; `plateau.integrity` recompute-verifies; the verdict reproduces
from sealed raw in a fresh process. The program + GOLD are sealed too.

## Hero chart

`demo/recall_vs_distance.png` — recall accuracy vs fact-distance, both arms. This becomes
the README headline IF it wins; if NULL/UNSCORABLE, the README says so and this chart is
shown as the honest negative.

## Condensation limit (stated up front, regardless of verdict)

Plateau does not claim flat-forever recall. Its signal is bounded, so it can only carry so
much; past the point where genuinely more distinct facts must be live than the signal
holds, recall MUST fall and real context has to be added back. This demo tests recall of
facts that remain within the bounded file; it does not claim infinite compression.
