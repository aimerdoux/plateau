---
description: Run a multi-step task with BOUNDED context — each step is a fresh subagent that sees ONLY the carried signal (goals/lessons/gated-facts), never the transcript. Your orchestrating session stays lean; the subagent's heavy work stays in its isolated context, and the gate keeps carried facts honest.
---

You are the **Plateau orchestrator** for this task:

$ARGUMENTS

Run it as a sequence of steps where **each step is a fresh subagent (the Task tool) that
receives ONLY the carried signal + that step's sub-task** — never the full conversation.
That is the whole mechanism: the subagent does the heavy work in its own isolated context;
only a compact result returns to you, so your context stays bounded.

First, decompose the task into ordered steps where each depends on the prior (do not show me a
plan unless I ask — just run it).

**Per step, do exactly this:**

1. **Inflate the carried signal.** Run:
   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/hook.py" pre
   ```
   Read the `carried_self_state` (open_goals / stance / lessons / pointers / verified_facts) and
   any `stale_dropped_at_inflate`. This — not the transcript — is what the next worker gets.

2. **Spawn ONE subagent (Task)** whose prompt is **only**: the inflated `carried_self_state`
   (paste it) + this step's sub-task. **Do NOT paste prior steps' output or the conversation.**
   Instruct the subagent to do the sub-task and end its reply with exactly:
   ```
   CARRY: <one short lesson/decision the next step must know>
   GATE: <repo-relative-path> :: sha256:<sha256 of a file it created>   (one line per fact; omit if it wrote no file)
   ```

3. **Gate the result** (admit only re-verifiable facts). Write the subagent's GATE lines to
   `.plateau/pending_facts.json` as `[{"claim":"<path> present","source":"<path>","value":"sha256:<hash>"}]`,
   and its CARRY line to `.plateau/pending_carry.json` as `["<the carry lesson>"]`. Then run:
   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/hook.py" post
   ```
   It admits only facts whose hash re-verifies, carries the lesson (bounded, deduped), and
   persists the signal. Report which facts were **admitted** vs **dropped** ("the subagent said
   so" is never admitted).

4. **Repeat** for the next step, carrying ONLY the updated signal (go back to 1).

**Rules (the discipline that makes this honest):**
- Never feed a subagent the full transcript — only the inflated signal + its sub-task.
- A fact enters the carried signal only if its Measurement re-verifies (the gate).
- Keep the signal small; it is bounded by design (lessons are capped), so past a point it can't
  hold every detail — that's the condensation limit, surface it rather than overstuff.

**At the end**, report: steps completed, the final carried signal (it should be a few hundred
tokens), and contrast it with the size of the full transcript a normal continuous session would
have accumulated by the last step. This measures context **efficiency only** — nothing about
understanding.
