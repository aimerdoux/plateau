# Recall-only demo (demo2) — readout

**Auto-rendered from `demo/verdict2.json` (sealed). Numbers not typed by hand.**
Source raw: `demo/raw2/records.json` (28 real subagent answers, 14 queries x 2 arms), sealed write-once before scoring. Seal chain verified; verdict reproduces from sealed raw in a fresh process. Pre-registration: `demo2_prereg.md` (written before the run).

## Result: NULL (near-miss)

Pure-recall task (no arithmetic): values are SET then QUERIED at increasing distance. A wrong answer can only be a memory/context failure.

| recall accuracy | near (d<=5) | mid (6-13) | far (>=14) | overall |
|---|---|---|---|---|
| full-history control | 1.0 | 0.75 | 0.5 | 0.7143 |
| Plateau (bounded) | 0.75 | 1.0 | 0.6667 | 0.7857 |

Context cost: control 95 -> 1317 tokens (slope 85.567/step); Plateau 68 -> 105 tokens (bounded).

## Pre-registered claims (locked rule, applied without override)
- **R1** control tokens climb: **True**
- **R2** control recall degrades with distance (far <= near - 0.25): **True**
- **R3** Plateau recall flat (far >= near - 0.15) AND high (far >= 0.70): **False**
- **R4** Plateau far recall > control far recall: **True**

## Verdict (full)
NULL (near-miss) — by the locked rule this is NOT a win: Plateau's far recall 0.6667 did not clear the pre-registered 0.7 floor. BUT Plateau was both flatter and higher than control (plateau near 0.75→far 0.6667, drop 0.083; control near 1.0→far 0.5, drop 0.5; plateau far 0.6667 > control far 0.5). The directional result favors Plateau; we do not claim the win. n is small (far bin = 6).

## Honest reading
- **Proven:** full-history recall degrades as facts sink (control near 1.0 -> far 0.5) while it carries an ever-growing transcript; Plateau keeps context bounded.
- **Directional, not decisive:** Plateau was flatter (near 0.75 -> far 0.6667) and higher overall (0.7857 vs 0.7143), but its far-recall did not clear the pre-registered 0.70 floor -> NULL by the locked rule. Two of Plateau's misses were top-of-file grabs (a sorted-layout artifact), not distance decay. n is small (far bin = 6).
- We ship the NULL rather than tune the layout until it crosses the line.

## Bright line
Measures context EFFICIENCY and RECALL. No claim about understanding, coherence, or phenomenality.
