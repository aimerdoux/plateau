#!/usr/bin/env bash
# sentinel.sh — Plateau control-loop external supervisor (outer loop).
#
# Involuntary reinstatement: respawns `claude -p` whenever the session ends WITHOUT a legal
# exit, so a crash / usage cap / early stop cannot end the mission. Measures the same file
# state the gatekeeper does. Terminates only on DONE, BLOCKED, or its own budgets.
#
# It carries Plateau's SIGNAL across every respawn: each warm reinstatement reads the
# on-disk RECON/PLAN/JOURNAL + the persisted signal (.plateau/signal.json) and resumes at
# the first unchecked gate — never restarting from zero (control-loop I5).
#
# Env: CONTROL_DIR (default .plateau/control), PROTO (CONTROL_LOOP.md), TASK (TASK.md),
#      MAX_RESPAWNS (8), MAX_WALL_MIN (240), BACKOFF (15s), CLAUDE_BIN (claude),
#      CLAUDE_ARGS (extra flags, e.g. --allowedTools ...).
set -u
DIR="${CONTROL_DIR:-.plateau/control}"
mkdir -p "$DIR" || exit 1
PROTO="${PROTO:-$DIR/CONTROL_LOOP.md}"
TASK="${TASK:-$DIR/TASK.md}"
REINSTATE="${REINSTATE:-$DIR/reinstate.md}"
MAX_RESPAWNS="${MAX_RESPAWNS:-8}"
MAX_WALL_MIN="${MAX_WALL_MIN:-240}"
BACKOFF="${BACKOFF:-15}"
CLAUDE_BIN="${CLAUDE_BIN:-claude}"
LOG="$DIR/SENTINEL.log"
start="$(date +%s)"; n=0; sid=""

log(){ printf '%s | sentinel | %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" | tee -a "$LOG" >&2; }
trap 'log "interrupted (SIGINT) after $n respawn(s)"; exit 130' INT

# A PLAN is "written" only once it holds at least one real task row. A freshly scaffolded
# PLAN.md (or one with only prose) is NOT a finished plan — treating it as one would let a
# run report DONE having never planned anything.
has_task_rows() { [ -f "$DIR/PLAN.md" ] && grep -qE '^- \[[ xX]\] *[A-Za-z]' "$DIR/PLAN.md"; }

verdict() {
  if [ -f "$DIR/BLOCKED.md" ] && grep -qi '^class:' "$DIR/BLOCKED.md"; then echo BLOCKED; return; fi
  if has_task_rows && ! grep -q '^- \[ \]' "$DIR/PLAN.md"; then echo DONE; return; fi
  echo RUNNING
}

[ -f "$TASK" ]  || { log "HALT: no $TASK (write the goal as one observable end state)"; exit 5; }
[ -f "$PROTO" ] || { log "HALT: no $PROTO (the control-loop protocol)"; exit 5; }

while :; do
  case "$(verdict)" in
    DONE)    log "verdict=DONE after $n respawn(s)"; exit 0 ;;
    BLOCKED) log "verdict=BLOCKED — human decision required, see $DIR/BLOCKED.md"; exit 2 ;;
  esac
  now="$(date +%s)"
  [ $(( (now - start) / 60 )) -ge "$MAX_WALL_MIN" ] && { log "HALT: wall-clock budget (${MAX_WALL_MIN}m)"; exit 3; }
  [ "$n" -ge "$MAX_RESPAWNS" ] && { log "HALT: respawn budget ($MAX_RESPAWNS)"; exit 4; }

  resume=""
  # Cold start = no PLAN rows yet. `init` legitimately scaffolds PLAN.md/RECON.md, so
  # keying on file EXISTENCE sent the very first spawn down the warm path with
  # reinstate.md and never delivered TASK.md.
  if ! has_task_rows; then
    prompt="$(cat "$PROTO"; printf '\n\n# TASK\n'; cat "$TASK")"          # cold start
  else
    prompt="$(cat "$REINSTATE" 2>/dev/null || printf 'REINSTATE: read RECON.md, PLAN.md, JOURNAL.md under %s + inflate .plateau/signal.json; resume at first unchecked gate; legal exits: DONE or BLOCKED.md.' "$DIR")"
    if [ -n "$sid" ]; then resume="--resume $sid"; else resume="-c"; fi   # warm reinstatement
  fi

  n=$((n+1)); log "spawn #$n (${resume:-fresh})"
  out="$("$CLAUDE_BIN" -p --output-format json ${resume} ${CLAUDE_ARGS:-} "$prompt" 2>>"$LOG")" \
    || log "claude exited non-zero (crash/cap/limit) — will re-measure"
  printf '%s\n' "$out" >> "$LOG"
  if command -v jq >/dev/null 2>&1; then
    s="$(printf '%s' "$out" | jq -r '.session_id // empty' 2>/dev/null)"; [ -n "$s" ] && sid="$s"
  fi
  sleep "$BACKOFF"
done
