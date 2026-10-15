#!/usr/bin/env bash
# gatekeeper.sh — compatibility shim. The gatekeeper is `plateau.agency.gatekeeper`,
# installed as the `gatekeeper` hook mode (hooks.json / `plateau init`); run directly, this
# shim behaves identically. Env: CONTROL_DIR, RUN_GATES, GATE_TIMEOUT, GATEKEEPER_MAX_BLOCKS.
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../../.." && pwd)"
PYTHONPATH="$REPO${PYTHONPATH:+:$PYTHONPATH}" exec python3 -m plateau.agency.gatekeeper "$@"
