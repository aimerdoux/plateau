#!/usr/bin/env bash
# Drive one run (seed = run number) for arms A, B, C in parallel. No scoring.
set -u; cd "$(dirname "$0")/../.."; r="$1"; L="experiments/d037/raw/logs"; mkdir -p "$L"
for arm in A B C; do
  python3 experiments/d037/run_arm.py --arm $arm --run "$r" --seed "$r" --n 13 --fixture-words 2650 --budget 1500 --window 200000 --pct 40 \
    --out "experiments/d037/raw/$arm/$r" > "$L/${arm}_$r.log" 2>&1 &
done; wait; echo "run $r done"; tail -n 2 "$L"/*_"$r".log
