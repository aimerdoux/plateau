# D-037 preflight raw artifacts (3 throwaway sessions, sealed as-is)

Not scored. Each pfN/ holds: payloads.jsonl (every hook payload, dumped by dump.py), outN.json (`claude -p --output-format json` result per task), transcript.jsonl (worker transcript copied from ~/.claude/projects), core.py.final, settings.json.

| session | window flag | PCT override | tasks | compactions | exit codes |
|---|---|---|---|---|---|
| pf1 | (default, 1M) | unset | 1 | 0 | 0 |
| pf2 | --autocompact 100000 | 40 | 3 (--continue) | 9 | 1 (rapid_refill_breaker), 0, 0 |
| pf3 | --autocompact 200000 | 40 | 3 (--continue) | 0 | 0, 0, 0 |

Worker model in all three: claude-sonnet-5 (from modelUsage). Runner uid 0.

