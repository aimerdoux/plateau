#!/usr/bin/env python3
"""demo7 collector — extracts the REAL T1-T8 self-hosting dispatch records from
`.plateau/control/` (this run's own control dir, live) into `demo/raw7/` (copies, so
sealing demo/raw7/ can chmod 0o444 those copies without ever touching the live control
dir a still-running loop needs to keep writing to), then derives the two context-token
series demo7_prereg.md pre-registers, straight from the copied bytes. Nothing here is
simulated or re-enacted; every input byte already existed on disk before this ran.

A "completed dispatch" = a task with a `JOURNAL.md` line (i.e. its gate passed and it
was folded into the signal by `gate_tasks_into_signal` — see control.py). A worker dir
can exist with only a `starting` status line and no reply (dispatch never finished); that
is NOT a completed record and is excluded, matching what PLAN.md's own checkboxes show.

Series (per demo7_prereg.md "The real subject"):
  full_history[i]  = cumsum_{j<=i} tok(prompt_j) + tok(log_j)              (counterfactual)
  actual_loop[i]   = tok(signal_snapshot) + tok(state_snapshot)            (constant per
                     + cumsum_{j<=i} tok(journal_line_j)                    task: what one
                                                                             VERIFY's cheap
                                                                             reads cost)
                     + cumsum_{j<=i} tok(journal_line_j)                   (grows: one
                                                                             journal line
                                                                             per completed
                                                                             task, per
                                                                             CONTROL_LOOP.md
                                                                             "Monitor")
signal_snapshot/state_snapshot are re-grounded, bounded blobs (not cumulative history) —
that boundedness is exactly the mechanism under test, so using the one real snapshot that
exists for every task index is the honest (non-simulated) reading of "what the parent
actually held," not an approximation of missing history.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness4 as H  # noqa: E402  (tok() reused, unmodified)

REPO = H.REPO
sys.path.insert(0, REPO)
from plateau.agency.control import parse_plan  # noqa: E402
CONTROL_DIR = os.environ.get("DEMO7_CONTROL_DIR") or os.path.join(REPO, ".plateau", "control")
SIGNAL_PATH = os.environ.get("DEMO7_SIGNAL") or os.path.join(REPO, ".plateau", "signal.json")
RAW = os.environ.get("DEMO7_RAW") or os.path.join(REPO, "demo", "raw7")

_JOURNAL_ROW = re.compile(r"^\d{4}-\d{2}-\d{2}T[\d:]+Z \| (\S+) \|")


def _journal_order(journal_text: str) -> list:
    """Task ids in the chronological order they were folded into the signal (the order
    JOURNAL.md rows were appended in) — the real completion order, not PLAN.md row order."""
    order = []
    for line in journal_text.splitlines():
        m = _JOURNAL_ROW.match(line.strip())
        if m and m.group(1) not in order:
            order.append(m.group(1))
    return order


def _journal_lines_by_task(journal_text: str) -> dict:
    out = {}
    for line in journal_text.splitlines():
        m = _JOURNAL_ROW.match(line.strip())
        if m:
            out.setdefault(m.group(1), line.strip())
    return out


def collect() -> dict:
    """Copy the real per-task worker artifacts + control-dir snapshots into demo/raw7/,
    then derive completion.json from those copies. Refuses to run twice into a non-empty
    raw7 (seal_demo7.py owns the write-once guarantee; this stays re-runnable pre-seal)."""
    if os.path.isdir(RAW) and os.listdir(RAW):
        raise SystemExit(f"REFUSE: {RAW} already has content — seal_demo7.py may have run. "
                         f"Remove demo/raw7/ manually if you intend to re-collect pre-seal.")
    os.makedirs(RAW, exist_ok=True)

    journal_text = open(os.path.join(CONTROL_DIR, "JOURNAL.md")).read()
    plan_text = open(os.path.join(CONTROL_DIR, "PLAN.md")).read()
    signal_text = open(SIGNAL_PATH).read()
    state_path = os.path.join(CONTROL_DIR, "STATE.json")
    state_text = open(state_path).read() if os.path.exists(state_path) else "{}"

    order = _journal_order(journal_text)
    lines = _journal_lines_by_task(journal_text)

    # only tasks with BOTH a journal line AND a non-empty worker log are "completed
    # dispatch records" — a journal line with no matching log would mean the receipt
    # exists but the raw evidence doesn't, which must not happen for real completions.
    completed = []
    for tid in order:
        log_p = os.path.join(CONTROL_DIR, "workers", f"{tid}.log")
        prompt_p = os.path.join(CONTROL_DIR, "workers", f"{tid}.prompt.txt")
        if os.path.isfile(log_p) and os.path.getsize(log_p) > 0 and os.path.isfile(prompt_p):
            completed.append(tid)

    for idx, tid in enumerate(completed, start=1):
        shutil.copyfile(os.path.join(CONTROL_DIR, "workers", f"{tid}.prompt.txt"),
                        os.path.join(RAW, f"{idx:02d}_{tid}_prompt.txt"))
        shutil.copyfile(os.path.join(CONTROL_DIR, "workers", f"{tid}.log"),
                        os.path.join(RAW, f"{idx:02d}_{tid}_log.txt"))

    open(os.path.join(RAW, "JOURNAL.md"), "w").write(journal_text)
    open(os.path.join(RAW, "PLAN.md"), "w").write(plan_text)
    open(os.path.join(RAW, "signal_snapshot.json"), "w").write(signal_text)
    open(os.path.join(RAW, "state_snapshot.json"), "w").write(state_text)

    tasks = parse_plan(plan_text)
    plan_checked = [t.id for t in tasks if t.checked]
    plan_unchecked = [t.id for t in tasks if not t.checked]

    # ---- derive the two series from the just-copied bytes (not the live files)
    fh_cum = 0
    al_base = H.tok(signal_text) + H.tok(state_text)
    al_cum_journal = 0
    full_history, actual_loop, steps = [], [], []
    for idx, tid in enumerate(completed, start=1):
        p_txt = open(os.path.join(RAW, f"{idx:02d}_{tid}_prompt.txt")).read()
        l_txt = open(os.path.join(RAW, f"{idx:02d}_{tid}_log.txt")).read()
        fh_cum += H.tok(p_txt) + H.tok(l_txt)
        al_cum_journal += H.tok(lines[tid])
        full_history.append(fh_cum)
        actual_loop.append(al_base + al_cum_journal)
        steps.append(tid)

    completion = {
        "journal_order": order,
        "completed_dispatch_records": completed,
        "n_completed": len(completed),
        "steps": steps,
        "full_history": full_history,
        "actual_loop": actual_loop,
        "actual_loop_base": al_base,
        "plan_checked": plan_checked,
        "plan_unchecked": plan_unchecked,
        "plan_task_count": len(tasks),
    }
    json.dump(completion, open(os.path.join(RAW, "completion.json"), "w"), indent=0, sort_keys=True)
    return completion


if __name__ == "__main__":
    print(json.dumps(collect(), indent=2))
