#!/usr/bin/env bash
# Ω toy on a real `claude -p` session. Run on a machine with an authenticated Claude Code (Max OAuth). No API key assumed.
# Usage: ./launch_toy.sh [workdir]   — creates a toy repo, installs hooks, runs a 4-task chain with forced compaction, scores recall.
set -euo pipefail
WD="${1:-$HOME/d037_toy}"; HERE="$(cd "$(dirname "$0")" && pwd)"
command -v claude >/dev/null || { echo "claude not found"; exit 1; }
MODE="${D037_PERMISSION_MODE:-acceptEdits}"
{ [ "$MODE" = bypassPermissions ] && [ "$(id -u)" -eq 0 ]; } && { echo "refuse to run bypassPermissions as root (demo8 run1 lesson)"; exit 1; }
rm -rf "$WD"; mkdir -p "$WD/.claude/hooks/d037" "$WD/toy"; cd "$WD"
cp "$HERE"/{d037_common,query,receipt,snapshot,inject,lookup}.py .claude/hooks/d037/
cp "$HERE/settings.arm_omega.json" .claude/settings.json
cp "$HERE/CLAUDE.md.snippet" CLAUDE.md
python3 - << 'PY'
import random; random.seed(1)
words=[w for w in open('/usr/share/dict/words').read().split() if w.islower() and 5<len(w)<9][:4000] if __import__('os').path.exists('/usr/share/dict/words') else [f"lorem{i}" for i in range(4000)]
open('toy/FIXTURE.md','w').write("# Design notes (read fully)\n\n"+" ".join(random.choice(words) for _ in range(11000)))
open('toy/core.py','w').write("def run(x):\n    return x\n")
open('toy/test_core.py','w').write("from core import run\ndef test_run():\n    assert run(2)==2\n")
PY
export CLAUDE_AUTOCOMPACT_PCT_OVERRIDE=25
T1="Read toy/FIXTURE.md fully. Then in toy/core.py add a module-level integer constant for a request rate limit; pick the name yourself. Run pytest -q toy."
T2="Read toy/FIXTURE.md fully. Then add a function to toy/core.py that returns the string 'ok' and name it however you like. Run pytest -q toy."
T3="Read toy/FIXTURE.md fully. Then add a docstring to run() in toy/core.py. Run pytest -q toy."
T4="Without re-reading toy/core.py, write toy/limits.py that imports the rate-limit constant you defined earlier from core and exposes it as LIMIT. Run pytest -q toy."
OPTS=(--permission-mode "$MODE" --disallowedTools "WebSearch,WebFetch")
claude -p "$T1" "${OPTS[@]}" > out1.txt
for i in 2 3 4; do v="T$i"; claude -p "${!v}" --continue "${OPTS[@]}" > out$i.txt; done
echo "== hook log"; cat .d037/hooks.log
echo "== compactions seen:"; grep -c "snapshot trigger" .d037/hooks.log || true
echo "== recall check (T4 must import the T1 constant without reading core.py)"
C=$(grep -oE "^[A-Z][A-Z0-9_]{2,}\s*=" toy/core.py | head -1 | tr -d ' ='); echo "T1 constant: $C"
grep -q "$C" toy/limits.py && echo "RECALL: HIT" || echo "RECALL: MISS"
grep -c '"tool_name": "Read"' out4.txt 2>/dev/null || true
echo "== last injection"; tail -3 .d037/hooks.log
