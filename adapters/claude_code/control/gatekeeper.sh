#!/usr/bin/env bash
# gatekeeper.sh — Plateau control-loop Stop-hook controller (inner loop).
#
# Makes the control loop's I4 ("only legal exits are DONE or BLOCKED-REPORT") MECHANICAL:
# on Stop, block stopping while unchecked gates remain and no valid BLOCKED.md exists.
#
# ARMED-ONLY: it enforces ONLY when a control run is active — a PLAN.md exists under
# CONTROL_DIR (default .plateau/control). With no such PLAN.md it exits 0 silently, so
# ordinary Plateau sessions (and the signal Stop hook it runs alongside) are untouched.
#
# Sensor: PLAN.md / BLOCKED.md.  Actuator: {"decision":"block"} on stdout.
# Release  <=>  DONE (zero unchecked gates; strict mode additionally re-runs every gate green)
#          OR   valid BLOCKED.md (contains a 'class:' line).
# Env: CONTROL_DIR (default .plateau/control), RUN_GATES=1 (strict regression),
#      GATE_TIMEOUT (s, default 120).
set -u
DIR="${CONTROL_DIR:-.plateau/control}"
PLAN="$DIR/PLAN.md"; BLOCKED="$DIR/BLOCKED.md"; STATE="$DIR/STATE.json"
STRICT="${RUN_GATES:-0}"; GTO="${GATE_TIMEOUT:-120}"

cat >/dev/null 2>&1 || true   # drain the hook's stdin JSON (telemetry); we sense the files
now="$(date -u +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || echo now)"

# NOT ARMED: no control run in progress -> never interfere with a normal session.
[ -f "$PLAN" ] || exit 0

emit_state() { # $1=unchecked $2=verdict
  printf '{"ts":"%s","unchecked":%s,"verdict":"%s","strict":%s}\n' \
    "$now" "$1" "$2" "$STRICT" > "$STATE" 2>/dev/null || true
}
block() { # $1=reason $2=unchecked
  emit_state "$2" "BLOCK"
  r="$(printf '%s' "$1" | tr '\n' ' ' | tr '"' "'" | cut -c1-400)"
  printf '{"decision":"block","reason":"%s"}\n' "$r"
  exit 0
}

# Release 1: a valid blocker report on disk (BLOCKED-REPORT is a legal pause).
if [ -f "$BLOCKED" ] && grep -qi '^class:' "$BLOCKED"; then
  u="$(grep -c '^- \[ \]' "$PLAN" 2>/dev/null || true)"; [ -n "$u" ] || u=0
  emit_state "$u" "ALLOW_BLOCKED"
  exit 0
fi

# A scaffolded-but-unplanned PLAN.md (no task rows at all) is NOT done — stopping there
# would end a run before it ever planned anything.
if ! grep -qE '^- \[[ xX]\] *T' "$PLAN"; then
  block "PLAN.md exists but contains no task rows. Finish RECON, then write rows in the fixed grammar ('- [ ] Tn | action | deliverable | GATE: cmd | EXPECT: result') covering the mission in TASK.md. Exit is legal only on DONE or a BLOCKED.md containing 'class:'." "-1"
fi

unchecked="$(grep -c '^- \[ \]' "$PLAN" 2>/dev/null || true)"; [ -n "$unchecked" ] || unchecked=0
if [ "$unchecked" -gt 0 ]; then
  first="$(grep -m1 '^- \[ \]' "$PLAN" | cut -c1-140 | tr '"' "'")"
  block "$unchecked unchecked gate(s) in PLAN.md. Next: $first — return to EXECUTE, assign it to a bounded sub-agent (signal + one task), run its GATE, paste literal output into JOURNAL.md, check the box only when the fact is admitted. Legal exits: DONE (all gates green now) or a BLOCKED.md with 'class:'." "$unchecked"
fi

# Strict regression (mirrors control-loop V3): re-run EVERY checked gate fresh. A checked
# row is trusted only if its gate still passes now. Pass <=> exit 0 AND
# (EXPECT=='exit0' OR EXPECT substring of output).
if [ "$STRICT" = "1" ]; then
  TO=""; command -v timeout >/dev/null 2>&1 && TO="timeout $GTO"
  command -v gtimeout >/dev/null 2>&1 && TO="gtimeout $GTO"
  while IFS= read -r row; do
    case "$row" in "- [x]"*|"- [X]"*) ;; *) continue ;; esac
    case "$row" in *"GATE: "*" | EXPECT: "*) ;; *)
      block "Malformed checked row (missing 'GATE:'/'EXPECT:'): $(printf '%s' "$row" | cut -c1-100). Fix the row grammar, then re-verify." "0" ;;
    esac
    gate="${row#*GATE: }"; gate="${gate%% | EXPECT:*}"
    expect="${row##*| EXPECT: }"
    out="$($TO bash -c "$gate" 2>&1)"; code=$?
    ok=0
    if [ "$code" -eq 0 ]; then
      if [ "$expect" = "exit0" ] || printf '%s' "$out" | grep -qF -- "$expect"; then ok=1; fi
    fi
    if [ "$ok" -ne 1 ]; then
      tid="$(printf '%s' "$row" | sed -n 's/^- \[[xX]\] \(T[^ |]*\).*/\1/p')"
      snip="$(printf '%s' "$out" | tail -c 200 | tr '\n' ' ' | tr '"' "'")"
      block "Regression: gate ${tid:-?} failed (exit $code). Output tail: $snip — uncheck that row, fix, re-verify. DONE means every gate is green when run now." "0"
    fi
  done < "$PLAN"
fi

emit_state 0 "ALLOW_DONE"
exit 0
