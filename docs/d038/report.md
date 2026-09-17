# D-038 — one-page report

Source of record: [`experiments/d038/D-038.md`](../../experiments/d038/D-038.md) (sealed) and
[`experiments/d038/results.json`](../../experiments/d038/results.json) (sealed, scorer `score.py`). This page
restates the Results section; the sealed file governs if they ever disagree.

**Question.** Does a compaction bridge (arm C, `d037-omega-6000`) carry attention across a real multi-epic task
better than no bridge (arm A, `none`)? Real work on the WaveX concierge agent, identical task script for both arms,
decay probes forked off the live session and graded blind.

**Status: run 1 complete and scored; run 2 not run — budget.** Nothing here is a final verdict: the pre-registered
rule (WIN = every run, PARTIAL = one of two) needs a second run, and bet B2's margin (+0.027) sits inside the
± 0.05 band that calls for a third run if run 2 also passes the gate.

## Headline numbers, D-038 run 1, one run, no verdict

| | arm A (none) | arm C (d037-omega-6000) |
|---|--:|--:|
| far-lag recall (n = 28) | **0.393** | 0.282 |
| AUC | 0.618 | **0.744** (Δ +0.127) |
| re-derivations | 142 | **105** |
| tokens/turn | 143 676 | **109 215** (24% fewer) |
| compactions | 36 | 27 |
| task score (of 12) | 12 | 12 |
| cost | $30.43 | $23.94 |

Arm A token `wt_2c23a2` (status COST_CAP after its 17th turn); arm C token `wt_85150c` (status OK). Recall by lag
bucket: 0.909 (A) vs 1.000 (C) at 0–20k; 0.625 vs 0.923 at 20–60k; 0.312 vs 0.132 past 60k. By compactions crossed:
0.933 vs 0.950 at 0; 0.462 vs 0.917 at 1; 0.333 vs 0.059 at ≥ 2. All five pre-registered bets (B1–B5) hold on this
one run; none of that is a verdict until run 2.

Reading, not a claim: the bridge's AUC lead comes entirely from the 20–60k / one-compaction region; past 60k and
two compactions arm C recalls *less* than vanilla (0.132 vs 0.312, 0.059 vs 0.333) — consistent with a
6000-char injection that bridges one compaction and evicts what it needed for the next one.

## A15 finding

`-p` under `acceptEdits` pre-approves no Bash command. In D-037, every `pytest` call (130 across 9 sessions) and
arm C's one `lookup.py` call were answered "This command requires approval" and never ran — D-037's "run pytest"
step never executed and its lookup path was dead (its recall result was unaffected: scoring was on files). D-038
fixed this by passing an explicit `--allowedTools` list of `Bash(<cmd>:*)` patterns (node, npm, npx, bash, git,
claude, python3, and the usual shell utilities; see `run_task.py`), recorded in the manifest — so this run's
`npm audit` and `node --check` calls actually produced exec facts.

## Raw tarball

`34d1724b40f022074457a11acb779dcf625bcfc10a559a47ef35a9e4bb1b77a6  d038_raw_run1.tar.gz` (22 MB: `raw/`, `raw_void/`,
`preflight/`, `raw_hashes.txt`; 2,093 files hashed). Recompute (`score.py --raw`) is verifiable by whoever holds the
tarball; per-file hashes are committed at `experiments/d038/raw_hashes.txt`. The tarball itself is not committed —
it exists only until the operator copies it to the private storage they name.
