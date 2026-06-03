# `/plateau:run` — in-session bounded orchestration (tested with real subagents)

`/plateau:run <task>` turns the main Claude Code session into an **orchestrator**: each step
runs as a fresh subagent (the Task tool) that sees **ONLY the carried signal — never the
transcript**. The subagent's heavy work stays in its isolated context; only a compact result
returns and is gated into the signal.

## Test — 2-layer dependent build, real subagents
- **Step 1** subagent (bounded signal only) built `vchain/l1.py` (base layer) and emitted
  `CARRY` (l1's contract) + `GATE` (l1's hash).
- **Gate:** `vchain/l1.py present` admitted (hash re-verified); l1's contract carried as a lesson.
- **Step 2** subagent received **ONLY the ~175-token carried signal** (goal + stance + the l1
  lesson + the `l1 present` fact) — *not* step 1's transcript — and built `vchain/l2.py` that
  does `from vchain import l1` and chains it.
- **Functional verification (not file-present):**
  `l2.verify(p) == sha256("L2:"+p+"|"+l1.verify(p))` → **True**, and l2 genuinely depends on l1
  (≠ a stub) → **True**. The dependency was carried by the bounded signal alone — **no amnesia.**
- **Bound:** final carried signal **701 bytes (~175 tokens)**; **~603k tokens** of subagent work
  stayed *out* of the orchestrator's context.

## Honest scope
- This is the **in-session** form (Task subagents). It bounds the per-step context the
  orchestrator pays, but the orchestrating thread still grows by (signal + compact result) each
  step — a **partial** bound, unlike the standalone driver (fresh `claude -p` per step), which is
  flat. Use `/plateau:run` for "bound a task inside my session"; use `plateau.driver` for a fully
  flat, measured A/B.
- The gate admits only facts whose Measurement re-verifies — "the subagent said so" is never
  admitted.
- Measures context **efficiency** only; silent on understanding.
