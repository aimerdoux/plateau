# D-037 preflight raw artifacts (3 throwaway sessions, sealed as-is)

Not scored. Each pfN/ holds: payloads.jsonl (every hook payload, dumped by dump.py), outN.json (`claude -p --output-format json` result per task), transcript.jsonl (worker transcript copied from ~/.claude/projects), core.py.final, settings.json.

| session | window flag | PCT override | tasks | compactions | exit codes |
|---|---|---|---|---|---|
| pf1 | (default, 1M) | unset | 1 | 0 | 0 |
| pf2 | --autocompact 100000 | 40 | 3 (--continue) | 9 | 1 (rapid_refill_breaker), 0, 0 |
| pf3 | --autocompact 200000 | 40 | 3 (--continue) | 0 | 0, 0, 0 |

Worker model in all three: claude-sonnet-5 (from modelUsage). Runner uid 0.


| pf4 | --autocompact 200000 (via run_arm.py, arm A) | 40 | 3 (seed 999, 6500-word fixtures) | 1 (in task 3) | 0, 0, 0 |

pf4 measured (transcript usage fields): startup 35 301; fixture read (6500 words) +16 744; per-task growth g 17 935; post-compaction residual 36 229 (end of task 3: 36 927). All 3 nonces echoed correctly; all symbols created.
Threshold formula read from the CLI bundle (2.1.273): effective = W − min(maxOutput, 20000); θ = min(floor(effective·pct/100), effective − 13000) → θ = 72 000 for W = 200 000, pct = 40; θ = 32 000 for W = 100 000 (explains pf2 thrash).
