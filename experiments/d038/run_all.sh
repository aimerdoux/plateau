#!/usr/bin/env bash
# Drive one run (seed = run number) for arms A and B in parallel. No scoring.
# D038_TARGET must point at the Wavex checkout's scripts/concierge-agent (pinned commit; see D-038.md).
set -u; cd "$(dirname "$0")/../.."; r="$1"; L="experiments/d038/raw/logs"; mkdir -p "$L"
: "${D038_TARGET:?set D038_TARGET=<wavex checkout>/scripts/concierge-agent}"
: "${D038_FIXTURE_WORDS:?set D038_FIXTURE_WORDS from preflight (D-038.md, compaction control)}"
for arm in A B; do
  python3 experiments/d038/run_arm.py --arm $arm --run "$r" --seed "$r" --n 18 --fixture-words "$D038_FIXTURE_WORDS" \
    --target "$D038_TARGET" --budget 1500 --window 200000 --pct 40 \
    --out "experiments/d038/raw/$arm/$r" > "$L/${arm}_$r.log" 2>&1 &
done; wait; echo "run $r done"; tail -n 2 "$L"/*_"$r".log
