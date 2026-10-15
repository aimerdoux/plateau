# Control-loop self-hosting run — PARENT REPORT

Mission: `.plateau/control/TASK.md` — *harden and prove the control loop by using it on this
repo*. The loop drove its own completion: every task was executed by a bounded `claude -p`
sub-agent whose entire prompt was **the carried signal + one task**, and was marked done only
when its parent-authored GATE re-verified through Plateau's gate.

Run start 16:00:06Z. Parent = this session. Workers = 7 real `claude -p` dispatches.

## Per-task verdicts (receipts in `JOURNAL.md`, gate artifacts in `gates/`)

| task | deliverable | gate | verdict |
|---|---|---|---|
| T1 | `plateau/agency/{control.py,__main__.py}` — `init/status/verify` CLI | `python -m plateau.agency.control verify --json` contains `unchecked` | **PASS → admitted** |
| T2 | `append_journal` / `write_blocked` / `read_status` helpers | helpers at module scope → `HELPERS_OK` | **PASS → admitted** |
| T3 | `tests/test_control_cli.py` | `pytest -q tests/test_control_cli.py` → `22 passed` | **PASS → admitted** (red on first check, see below) |
| T4 | `demo/demo7_prereg.md` (NULL live, decision rule) | file + `NULL` + `decision rule` present | **PASS → admitted** |
| T5 | `demo/raw7/` sealed + `score_demo7.py` | `score_demo7.py --verify` → `RECOMPUTE_OK` | **PASS → admitted** |
| T6 | `README.md` control-loop section | `orchestrate` + `control loop` present | **PASS → admitted** |
| T7 | full regression | `pytest -q` → `107 passed, 1 skipped` | **PASS → admitted** |
| T8 | this report | report exists + `control status` exits 0 | **PASS → admitted** |

## EXIT: DONE (legal)

V3 strict regression — every gate re-run fresh, right now:

```
python -m plateau.agency.control verify --control-dir .plateau/control --strict --json
{"passed": ["T1","T2","T3","T4","T5","T6","T7","T8"], "unchecked": [], "verdict": "DONE"}
```

The gatekeeper, armed throughout, then **released** (empty output = allow stop). Run
16:00:06Z → 16:31:59Z. Suite 85 → **107 passed, 1 skipped** (+22, floor never breached).

## What the run demonstrated (measured, not asserted)

**1. Worker context is flat.** Prompt bytes per dispatch, in dispatch order:

```
T1 2894 · T4 2924 · T6 2853 · T2 3018 · T5 2912 · T3 2940
```

Mean ≈ 2923, range ±3%, **no trend**. The sixth worker received the same context as the
first despite five completed tasks before it — because a worker gets the *signal*, never the
transcript. This is the mechanism's whole claim, observed on real dispatch.

**2. The carried signal stayed bounded** while accumulating facts: 737 → 1100 → 1282 → 1646
bytes across 5 admitted facts (`T4 done`, `T6 done`, `T1 done`, `T2 done`, `T5 done`).

**3. The gatekeeper enforced I4 mechanically.** With `PLAN.md` present and rows unchecked it
returned `{"decision":"block","reason":"8 unchecked gate(s) in PLAN.md. Next: T1 …"}`. It is
armed only by the presence of a control run, so ordinary sessions are unaffected.

**4. The trust boundary held under a real accident.** The T1, T2 and T5 workers' sandboxes
**blocked all python execution**, so none of them could run its own gate. Each reported
`GATE_SELFCHECK: unknown / not run` rather than claiming success, and the **parent** ran the
gate and admitted the fact on real evidence. A worker's self-report never checked a box. This
was not staged — the environment produced it, and the design absorbed it.

**5. The honesty discipline propagated down.** T5 sealed the run's real records, then scored
**UNSCORABLE** because the pre-registered guard (n ≥ 5 completed records) was not met at n=3.
It disclosed the mechanical ratio (≈2.1%, under the 25% WIN bar) as *informational only* and
explicitly labelled the full-history arm a **counterfactual**, not a second measured run. The
run was not padded or re-enacted to clear the bar. No demo7 number was promoted into
`README`/`RESULTS`/`BENCHMARKS`.

**6. The parent verified rather than trusted.** The seal was independently re-checked by the
parent: `Manifest.verify_chain() → (True, [])`, `verify_files() → True`.

**7. A red gate actually held the line.** T3's first gate run returned `5 failed, 17 passed`
(a mid-write snapshot). The box stayed unchecked and nothing was committed — the loop does not
mark a task done because a file exists. The worker, unable to run pytest in its sandbox,
found the two real bugs by manual trace (a wrong `cwd` that broke `plateau` module
resolution, and a bad pipe-escaping assertion); the re-run gate returned `22 passed` and only
then was the fact admitted.

## Honest limits

- **demo7 is UNSCORABLE.** The efficiency axis was not established by this run; the flat
  prompt sizes above are a direct observation, but the "what full-history would have cost"
  comparison is modelled, not measured. It is disclosed as such and claims nothing.
- **Parallelism was parent-sequenced, not automatic.** The parent serialized tasks sharing a
  file (T2 after T1) and parallelized disjoint ones (T4 ‖ T6 ‖ T1); nothing in the harness
  detects collisions for you.
- **Worker sandboxes vary.** Several workers could not execute code at all. They still
  produced correct code, but a task whose completion genuinely *requires* the worker to run
  something would have to be re-scoped or run by the parent.
- **This is one run, n=1.** It shows the loop operates end-to-end on a real repo; it does not
  establish a performance claim.

## Reproduce

```bash
python -m plateau.agency.control status --control-dir .plateau/control   # checkbox state
python -m plateau.agency.control verify --control-dir .plateau/control --strict --json
python demo/score_demo7.py --verify                                      # RECOMPUTE_OK
python -m pytest -q                                                      # suite green
```
