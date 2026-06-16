# Σ / Plateau — LIVE A/B Capability Experiment — RESULTS

**Manifest hash (pre-registered, frozen before any run):** `sha256:bbd6d4e020c273f1b1303c5bb9ca3ceeaaa3dff8b1146f98c0d6ae905bc2784a`

**N (tasks with both arms scored):** 7  
**Metric:** gate_pass against the OBJECTIVE V (τ=1.0, programmatic gates, fixed code in `ab_tasks.py`, neither arm authored — A6).  
**Arms:** WITH = `run_schema` Σ loop (Φ-hydrated, max_iters=4, depth compounds) · WITHOUT = single `claude -p` pass. SAME base model both arms.  
**Model:** live `claude -p` (Claude Code CLI). Every number below is from a real paid run; NO fabrication.

## Verdict

- **Overall pass-rate:** WITH = 7/7 · WITHOUT = 7/7
- **WITH strictly helped on:** (none)
- **WITHOUT strictly better on:** (none)
- **Depth gradient:** shallow(depth≤2) WITH-advantage = 0 (WITH-only 0, WITHOUT-only 0); deep(depth≥4) WITH-advantage = 0 (WITH-only 0, WITHOUT-only 0) → **flat**
- **Capability enhanced?** **FLAT**

## Per-task results

| Task | Depth | WITH pass | WITHOUT pass | WITH iters | WITH trace | WITH calls | WITHOUT calls | Δ |
|---|---|---|---|---|---|---|---|---|
| t1_palindrome | 1 | ✅ | ✅ | 1 | [1.0] | 1 | 1 | tie |
| t2_fizzbuzz | 1 | ✅ | ✅ | 1 | [1.0] | 1 | 1 | tie |
| t3_json_config | 2 | ✅ | ✅ | 1 | [1.0] | 1 | 1 | tie |
| t4_rpn | 3 | ✅ | ✅ | 1 | [1.0] | 1 | 1 | tie |
| t5_md_table | 3 | ✅ | ✅ | 2 | [0.0, 1.0] | 2 | 1 | tie |
| t6_ledger | 4 | ✅ | ✅ | 2 | [0.0, 1.0] | 2 | 1 | tie |
| t7_fsm | 5 | ✅ | ✅ | 1 | [1.0] | 1 | 1 | tie |

**Approx cost (claude -p invocations):** WITH arm = 9 calls · WITHOUT arm = 7 calls · total = 16 calls.

## Honest caveats

- **Bounded first pass, N=7.** Small sample; this is a directional signal, not a powered study. Per-task k=1 (one objective scoring per produced candidate; the gate is deterministic, but the model sample is single-draw per arm so task-level noise is real).
- **Tasks are reproducible analogues** of corpus deliverable *shapes* (produce code / JSON / markdown / a small state machine satisfying checkable gates). The corpus's own auto-mined gates (opened_pr, on-disk-artifact-exists, boolean `claim_*` flags) are NOT checkable on a freshly produced candidate and were dropped per design — so these tasks are grounded in the corpus's kinds, not lifted verbatim.
- **Ceiling effect risk:** a strong base model may pass shallow tasks in one pass, leaving the Σ loop no room to help except on deep tasks. That is exactly the depth-gradient hypothesis; read the deep-task rows, not just the aggregate.
- **WITH spends more compute** (up to 4× calls). Any WITH win is a compute-for-capability trade, not free.
- **Objective-V only; A6 held:** neither arm authored or saw its judge; both scored by the same fixed programmatic gates. A WITHOUT win or a tie is a first-class, valid result and is reported as-is.

## Observed: the loop mechanically worked, the base model just didn't need it

On **t5** and **t6** the WITH feasibility trace is `[0.0, 1.0]`: the FIRST live `claude -p` pass FAILED the objective gate, and the Σ loop's SECOND iteration — which hydrated the failed attempt + the specific failed-requirement KPI back into the prompt from Φ — produced a corrected candidate that PASSED. So the depth-compounding loop demonstrably did its job (state externalized through Φ, failure fed forward, recovery achieved). But on those same two tasks the WITHOUT single pass ALSO passed on its one draw. Net capability gain on the objective V was therefore zero: every task was within the base model's single-pass reach (a ceiling effect), so the only thing the loop bought was a second chance the baseline did not happen to need. The pattern's value would surface on tasks the base model CANNOT one-shot — none of these 7 were that hard for this model. This is the honest **FLAT** verdict, not a pattern win.
