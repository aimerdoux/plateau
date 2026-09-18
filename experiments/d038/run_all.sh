#!/usr/bin/env bash
# One run (both arms in parallel, blind tokens), then the blind judge on each view. No scoring.
# D038_TARGET must point at the Wavex checkout's scripts/concierge-agent at the pinned commit (D-038.md).
set -u; cd "$(dirname "$0")/../.."; r="$1"; L="experiments/d038/raw/logs"; mkdir -p "$L"
: "${D038_TARGET:?set D038_TARGET=<wavex checkout>/scripts/concierge-agent}"
for arm in A C; do
  python3 experiments/d038/run_task.py --arm $arm --run "$r" --target "$D038_TARGET" --window "${D038_WINDOW:-200000}" > "$L/${arm}_$r.log" 2>&1 &
done; wait; echo "run $r workers done"; tail -n 1 "$L"/*_"$r".log
for v in experiments/d038/raw/"$r"/wt_*/judge_view; do python3 experiments/d038/judge.py --view "$v" >> "$L/judge_$r.log" 2>&1; done
tail -n 2 "$L/judge_$r.log"
