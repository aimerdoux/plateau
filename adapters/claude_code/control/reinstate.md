REINSTATE — the session stopped without a legal exit. You are the PARENT of a Plateau
control loop. Resume; do not restart, do not narrate — act.

1. Inflate the carried SIGNAL and read the on-disk ledger. Never restart from zero (I5):
   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT:-adapters/claude_code}/hook.py" pre
   ```
   then read `.plateau/control/TASK.md` (THE MISSION), `RECON.md`, `PLAN.md`, `JOURNAL.md`
   (and `STATE.json` if present).
2. If `PLAN.md` is missing: resume the protocol at the earliest missing deliverable
   (RECON → PLAN), per `CONTROL_LOOP.md`.
3. Otherwise resume at the first `- [ ]` row: FORECAST it if `FORECAST.md` has no row for it
   (`python3 -m plateau.agency.control forecast --task T<n> --predict "..."`) → EXECUTE (assign
   it to ONE bounded sub-agent that sees only the inflated signal + that task) → VERIFY (run its
   GATE, paste the literal output into `JOURNAL.md`, admit `T<n> done` only when the gate
   re-verifies) → GAP (`python3 -m plateau.agency.control adapt --write`; adjust `PLAN.md` from
   any DRIFT/REFUTED before moving on — see `CONTROL_LOOP.md` §5b).
4. Legal exits only: DONE (every gate re-run green now, receipts journaled) or a `BLOCKED.md`
   containing a `class:` line, attempts, smallest unblocking action, and a decision menu.
5. Do not re-plan unless E5 applies. Do not repeat an identical failed action (E3). You are
   the last decision-maker — resolve ambiguity with the safest reasonable choice and log it.
