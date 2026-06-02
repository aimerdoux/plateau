# Plateau recall re-run (demo3) — PRE-REGISTRATION

Written and committed BEFORE the harness is built and BEFORE any query is dispatched.
This is a **pre-committed replication of demo2 with two confound fixes**. The decision
rule is **identical to demo2** — same R1–R4, same 0.70 far-recall floor, same bins. Only
the sampling and the layout change. Both outcomes are pre-committed to publish (operator
directive): clear the floor → hero result; miss it → honest NULL. We will NOT relax the
floor either way.

**Bright line (kept, engineering only):** measures context EFFICIENCY and RECALL. No claim
about understanding, coherence, or phenomenality.

## Why a re-run (what demo2 left ambiguous)

demo2 returned NULL (near-miss): Plateau far-recall 0.667 missed the 0.70 floor by one
query in a far bin of only 6. Two of Plateau's misses were the agent grabbing a
top-of-file value rather than the named target. Two confounds, fixed here:

1. **Far bin too small** (n=6): a single miss swings it 0.167. Fix: enlarge the far bin.
2. **Layout/value shortcuts**: demo2's register file was alphabetically sorted (salient
   top) and its values were sequential (value ≈ set-order), so position and magnitude
   leaked information. Fix: remove both shortcuts.

## The two fixes (and why they don't favor Plateau)

- **Random distinct values.** Each SET draws a distinct value from a seeded shuffle of
  100–999 — no correlation with register name or set-order. A "grab a recent/large value"
  heuristic now lands on an unrelated number. (Conservative: removes a guess that could
  have helped *either* arm.)
- **Plateau file shuffled per query** (deterministic seed = query index). The queried
  register sits at a random position, so "grab the top line" is no longer a shortcut — the
  agent must locate the named register. This makes Plateau's job **harder**, not easier: it
  forces genuine name-lookup. If Plateau clears the floor on a shuffled file with random
  values, the result is robust.
- **Control transcript stays chronological.** A transcript is inherently time-ordered; the
  control's recency bias (grabbing a recent line) is the *real* long-context degradation we
  are measuring, not an artifact — so it is left intact.

## Task (unchanged in kind from demo2)

Pure recall, no arithmetic. 8 noise registers (N0–N7) re-set as filler; 18 TARGET
registers (T0–T17) each SET once then QUERIED at a controlled distance. Bins:
near {2,3,4,5} (4), mid {7,9,11,13} (4), far {16,20,24,28,32,36,40,44,48,52} (**10**).
Total 18 queries → 36 subagent calls. Far bin n=10: one miss = 0.90, two = 0.80 — both
still clear 0.70, so the result is robust to a single fluke.

Two arms, identical task/seeds: FULL-HISTORY control (transcript grows, fact sinks) vs
PLATEAU (bounded shuffled register file). Queries independent → parallelizable. Scored vs
GOLD.

## Metric + decision rule (IDENTICAL to demo2 — reuses score_demo2.score_rows)

- recall accuracy per distance bin, per arm; recall-vs-distance slope; control token slope.
- **R1** control tokens climb. **R2** control recall degrades (far ≤ near − 0.25).
  **R3** Plateau recall flat (far ≥ near − 0.15) AND high (**far ≥ 0.70**).
  **R4** Plateau far recall > control far recall.
- **WIN** = R1 ∧ R2 ∧ R3 ∧ R4. **NULL** = R1 ∧ R2 but ¬(R3 ∧ R4).
  **UNSCORABLE** = ¬R1 or ¬R2 (control didn't climb / didn't degrade → facts didn't sink).

## Locked predictions (honest)

| # | claim | conf | if it fails |
|---|---|---|---|
| R1 | control tokens climb | 0.95 | UNSCORABLE |
| R2 | control recall degrades far ≤ near−0.25 | 0.70 | UNSCORABLE — lengthen |
| R3 | Plateau far ≥ 0.70 AND flat | **0.70** | NULL — recall didn't hold |
| R4 | Plateau far > control far | 0.75 | NULL |
| WIN | R1∧R2∧R3∧R4 | **0.60** | report failing leg |

**NULL still live.** With shuffled positions and random values, it is genuinely possible
Plateau's lookup degrades or stays below 0.70 — if so it is a real NULL and we publish the
honest negative. We are NOT predicting a guaranteed win; we removed confounds and enlarged
n, nothing more.

## Integrity

Raw per-query records sealed write-once BEFORE scoring; score reads only the sealed file;
recompute-verify; verdict reproduces from sealed raw in a fresh process. Program + GOLD
sealed. Hero chart `demo/recall_vs_distance3.png` rendered from sealed data; it leads the
README only if R3∧R4 hold (WIN). If NULL, the README says so.
