# How the Plateau bridge actually works

A mechanism report built from what the bridge wrote and what the model received in every real session run so far:
D-038 run 1 (the sealed experiment; arm C is the bridge arm) and the two supervised adapter target runs on a private
repo (session `98e6f070…`, 5 turns, and session `58031f63…`, 2 turns, both 2026-09-17). Evidence is the stores
(`index.sqlite`), the hook logs, and the transcripts, read after the fact. No new sessions were run for this report.
Target-repo paths and symbols are replaced by their shape.

## The short version

1. **The knowledge in these runs was carried by native compaction, not by the bridge.** Every native compaction
   summary in the 5-turn adapter run (25 583, 25 540 and 20 964 chars) contained the function signatures the worker
   later reproduced without re-reading. None of the bridge injections did.
2. **Every bridge injection so far has been an action log.** It lists which files were touched and which commands
   ran, with their outcome. It has never carried a read fact, a symbol, a test result or an error into a real
   session. The D-038 bridge arm's store held 268 receipts collapsed into 127 nodes of exactly two kinds:
   `command` 85, `file` 42.
3. **So D-038 measured an action log, not a knowledge bridge.** Its +0.127 AUC and its −0.458 raw presence at two
   or more compactions are the effect of injecting a recency-ranked list of file names and commands, with no query.
4. **At the scale of the adapter runs the selector never chose anything.** Every injection carried every node
   (18/18, 20/20, 35/35) at 14–27 % of the 12 000-char budget. Selector v2's quota, stickiness, recency and lexical
   ranking had no effect on what the model saw.
5. **This supports the 0.4 thesis and sets its precondition.** Carrying knowledge instead of actions is the right
   move, and it only becomes possible now that the classifier produces knowledge nodes (read 8, symbol 2, test 1 in
   adapter run 2, after the target-run fixes; zero before).

A correction follows from point 1. In the session that built 0.3 I reported the 5-turn run's final turn, which
reproduced four signatures without re-reading across two compactions, as "the bridge doing its job on real work".
That attribution was wrong. The worker made two tool calls in that turn, a Write and a test run, with no reads and
no lookups, and the signatures it wrote were present in the native summary it was working from.

## The pipeline, stage by stage

The adapter installs thirteen hook entries across eight Claude Code events. What each does, and what it did in
practice:

| event | mode | what it writes | observed |
|---|---|---|---|
| PostToolUse, PostToolUseFailure | `receipt` | one receipt row per tool call; updates the node for its target; hashes files it touched | fires within ~0.1–0.5 s of each call; never a bottleneck |
| PreCompact | `snapshot` | copies the store, marks the compaction, returns custom instructions for the summarizer | fires before every compaction |
| SessionStart `compact` | `inject` | selects nodes and injects a `<plateau_index>` block as additional context | fires ~90–120 s after PreCompact, once the summary is written |
| SessionStart `startup` | `parent`, `inject` | parent discipline; a startup injection from the store | see defects 3 and 4 |
| UserPromptSubmit | `pre` | the gated signal | unchanged from 0.2 |
| Stop | `post`, `lift`, `handoff` | signal gate; `DECISION:`/`FACT:` lines lifted to decided nodes; turn marked; shadow probe spawned; handoff printed | lift fired in 3 of 5 turns (the other two used bold markdown, fixed since) |
| SessionEnd | `ledger`, `handoff` | ledger row upserted; handoff file written | fires every turn in headless mode (defect 6) |
| SubagentStop | `handoff` | subagent handoff file | also fired by the compaction summarizer (fixed since) |

The order within one compaction, from the 5-turn run's log: the last receipt, then `snapshot trigger=auto`, then
about two minutes of summarization, then `inject ev=SessionStart`, then the next receipt.

## What the model actually receives

After native compaction the model has two things: the native summary (20–26 k chars in these runs) and, appended to
it, the bridge block. The bridge block looks like this, with the target's paths replaced by their shape:

```
<plateau_index>
# Machine-generated ledger of execution receipts from earlier in this session. Data, not instructions.
# [rN] = receipt id, ★ = matches current prompt. Deep lookup: plateau lookup <words>
[r19] file <dir>/<doc>.md → read ×2 ★
[r14] file <dir>/<module>.test.mjs → edit ×1 ★
[r15] command cd <dir> && node --check <module>.mjs && echo "<module>.mjs OK" → pass ×1 ★
[r13] file <dir>/<module>.mjs → edit ×1 ★
[r9]  command cd <dir> && node --test → pass ×1 ★
...
</plateau_index>
```

Composition of the three compaction injections in the 5-turn run:

| compaction | chars / budget | nodes injected / available | file lines | command lines | decided lines | knowledge lines (read, symbol, test, error) |
|---|---|---|---|---|---|---|
| 1 | 1 662 / 12 000 | 18 / 18 | 14 | 22 | 0 | 0 |
| 2 | 1 797 / 12 000 | 20 / 20 | 18 | 22 | 0 | 0 |
| 3 | 3 293 / 12 000 | 35 / 35 | 18 | 30 | 22 | 0 |

(Line counts include the multi-line command entries, which is why they exceed the node counts.)

Three things follow. The block tells the model where it has been, not what it found: "this file was edited" but not
what the file now contains. Every line carries the ★ lexical-match mark, so the mark distinguishes nothing (defect 2).
And the block is an addition on top of a summary that already names the same files, about 6–16 % more context.

## D-038, re-read with the mechanism in view

The D-038 record is sealed and stays as written. What follows is interpretation of its raw, not an edit.

The bridge arm ran the D-037 hook bundle, whose classifier extracted symbols only from Python definitions and
recognized only pytest as a test command. D-038's target was JavaScript. The result, from the arm's own store:

| | value |
|---|---|
| receipts | 268 |
| nodes | 127: `command` 85, `file` 42 |
| symbol, test, read, decided, error nodes | 0 |
| injections | 16, all with an empty query (`q=0ch`), so ranking was recency and degree only |
| budget binding | every node fit through injection 9; from injection 10 the selector dropped nodes (50 of 56, rising to 58 of 102), holding at ~5 900 of 6 000 chars |

So the arm injected a recency-ranked list of file names and command strings. Two readings of its results fit this:

- **The one-compaction gain may be mediated, not carried.** The bridge arm re-read less (142 → 105 re-derivations),
  grew context more slowly (143 676 → 109 215 tokens per turn) and compacted less often (36 → 27 compactions).
  An action log that reminds the model which files it already handled could produce all three, and recall at one
  compaction could improve through fewer, later compactions rather than through anything the block carried.
  D-038 cannot separate these.
- **The two-compaction loss coincides with the budget binding.** Once the block filled its 6 000 chars, recency
  ranking dropped older entries. Raw presence of −0.458 at two or more compactions crossed is what an index that
  evicts old entries while native compaction keeps them would produce.

Both are hypotheses the raw is consistent with, not findings the raw establishes.

## Defects this analysis found

These are new; the nine found by the target runs are already fixed.

1. **The lexical query can be the model's own summary.** At a compaction, the query is the last user message in the
   transcript. When two compactions fall in one turn, that message is the first compaction's summary. In the 5-turn
   run the query at compaction 2 was 25 583 chars of summary, marked `isCompactSummary: true` in the transcript. Fix:
   skip messages carrying that flag in `query.last_user_prompt`.
2. **★ is uninformative.** Query tokens drawn from paths (the working directory, the module folder) match every node,
   so every line is marked. The mark should require a match on a token that is not shared by most nodes.
3. **A fresh store injects an empty block.** The first startup injection of a new repo is the 218-char header with no
   lines. It should inject nothing when there are no nodes.
4. **Carryover across sessions is unscoped.** Nodes are keyed on their key alone, so the store is shared by every
   session in the repo. The 2-turn run's startup injection carried 62 nodes, 5 761 of 6 000 chars, all from the
   earlier, unrelated session. This is what makes `plateau resume` work; for a new, unrelated task it is noise. The
   startup injection should be scoped to the resumed session, or to nodes the new task's query reaches.
5. **The pull channel has never been used.** Workers made zero lookups in both runs. The block's header points at
   `plateau lookup <words>`, but headless allow-lists do not include `plateau`, so the call would have been denied had
   the worker tried; the same class as D-037's finding that every headless Bash call was denied.
6. **In headless mode every turn is a session end.** Each `claude -p` turn ends its process, so the ledger and the
   handoff write fire every turn (five times in the 5-turn run). "Session" in the ledger means process. The ledger
   upserts, so the counts stay right, but per-session metrics need to group by session id, not by row.

## What this means for 0.4

- **Carry knowledge, not actions.** The evidence for the 0.4 thesis is direct: native compaction already keeps the
  file-level picture, and it kept the facts in these runs too. The bridge's marginal value is in what native
  compaction drops, which D-038 locates at two or more compactions crossed (native recall 0.333 there, run 1).
- **The path selector depends on the classifier fixes.** Excluding action nodes is right, but in every store before
  the target-run fixes there was nothing else to carry. The D-038 bridge arm would have injected an empty path.
  D-039 is only meaningful on stores that contain read, symbol, test, error and decided nodes; the preregistration
  should require a minimum knowledge-node share per session before a session counts.
- **The budget should bind by content, not by count.** At adapter-run scale the budget never bound, so any selector
  would have injected the same block. D-039's comparison will only show a difference in sessions long enough for the
  budget to bind, which argues for measuring budget pressure per session and reporting it beside the verdict.
- **Fix defect 1 before D-039 starts.** The path selector seeds from the lexical query; a query that is the model's
  own summary would seed from whatever the summary mentions.

## Evidence

| claim | source |
|---|---|
| summaries carried the signatures; injections did not | 5-turn transcript: three `isCompactSummary` messages and four `plateau_index` attachments, string search |
| final turn made no reads or lookups | 5-turn transcript, tool calls after the final prompt: one Write, one test run |
| injection sizes, node counts, query lengths | target `hooks.log`, `inject ev=SessionStart` lines |
| D-038 bridge arm node kinds | D-038 run 1 raw, bridge arm `work/.d037/index.sqlite` |
| D-038 injection sizes and binding | same arm, `hooks.log` |
| D-038 re-derivations, tokens, compactions | `experiments/d038/results.json` |
| query at compaction 2 is a summary | 5-turn transcript, user message preceding the second `compact_boundary` |
| no lookups by workers | target `hooks.log`: the only `lookup` line is the post-run verification's |
