# Recall re-run (demo3) — readout

**Auto-rendered from `demo/verdict3.json` (sealed). Numbers not typed by hand.**
Source: `demo/raw3/records.json` (36 real subagent answers, 18 queries x 2 arms), sealed before scoring; verdict reproduces from sealed raw in a fresh process. Pre-reg: `demo3_prereg.md`. Same locked rule as demo2 (reuses score_demo2.score_rows) — only the confounds + far-bin size changed.

## Result: UNSCORABLE

Confounds removed vs demo2: random distinct values (no ordinal shortcut), Plateau register file shuffled per query (no positional shortcut), far bin enlarged to 10 queries.

| recall accuracy | near (d<=5) | mid (6-13) | far (>=14) | overall |
|---|---|---|---|---|
| full-history control | 1.0 | 0.75 | 0.8 | 0.8333 |
| Plateau (bounded) | 1.0 | 1.0 | 1.0 | 1.0 |

Context cost: control 98 -> 2138 tokens (slope 114.836/step); Plateau 71 -> 120 tokens (bounded). ~18x less context at the deepest query.

## Pre-registered claims (locked rule, no override)
- R1 control tokens climb: True
- R2 control recall degrades (far <= near - 0.25): **False**
- R3 Plateau recall flat AND >= 0.70 floor: True
- R4 Plateau far > control far: True

## Honest reading
- **Plateau is perfect and flat:** 18/18 correct at every distance, on a shuffled file with random values — bounding imposes NO recall penalty. R3 and R4 both hold.
- **But the comparison is UNSCORABLE:** once the value/position confounds were removed, the full-history control recalled random facts well even from a ~2000-token transcript (far 0.8, overall 0.8333). It degraded only 0.2 at far — below the pre-registered 0.25 anti-rig margin (R2 fails). So the chain did not bury facts deeply enough to *score* a recall-preservation win; we do not claim one.
- This is the prereg's pre-committed UNSCORABLE branch. We publish it rather than lengthen the chain until the control breaks (that would be chasing the result).
- Net: Plateau matched-or-beat full-history recall (1.0 vs 0.8333) at ~18x less context. The honest win is the bounded cost with no recall penalty — not a proven recall *advantage*.

## Bright line
Measures context EFFICIENCY and RECALL. No claim about understanding, coherence, or phenomenality.
