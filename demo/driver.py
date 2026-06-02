"""Stateful driver for the live paid run. State persists to demo/raw/state.json so the
growing control transcript lives on disk, not in the orchestrator's context.

Usage:
  python demo/driver.py prompts <step>          # print both arms' prompts + token est
  python demo/driver.py record <step> <c> <p>   # record answers, advance state
  python demo/driver.py finalize                # write demo/raw/records.json (pre-seal)
"""

from __future__ import annotations

import json
import os
import sys

from demo.program import gold, SEED
from demo import run_demo as R

HERE = os.path.dirname(__file__)
RAW = os.path.join(HERE, "raw")
STATE = os.path.join(RAW, "state.json")
RECORDS = os.path.join(RAW, "records.json")


def _load() -> R.RunState:
    st = R.RunState()
    if os.path.exists(STATE):
        d = json.load(open(STATE))
        st.control_history = [tuple(x) for x in d["control_history"]]
        st.plateau_blob = d["plateau_blob"]
        st.work = d["work"]
        R.set_ground_root(st.work)
    else:
        os.makedirs(RAW, exist_ok=True)
        st.init_plateau()
        _save(st, rows=[])
    return st


def _save(st: R.RunState, rows=None) -> None:
    d = {"control_history": [list(x) for x in st.control_history],
         "plateau_blob": st.plateau_blob, "work": st.work}
    if rows is not None:
        d["rows"] = rows
    elif os.path.exists(STATE):
        d["rows"] = json.load(open(STATE)).get("rows", [])
    else:
        d["rows"] = []
    json.dump(d, open(STATE, "w"), indent=2)


def cmd_prompts(step_no: int) -> None:
    st = _load()
    step = gold()[step_no - 1]
    cp = R.control_prompt(st, step)
    pp, stale = R.plateau_prompt(st, step)
    print("===CONTROL_TOKENS===", R.est_tokens(cp))
    print("===PLATEAU_TOKENS===", R.est_tokens(pp))
    print("===STALE===", stale)
    print("===CONTROL_PROMPT===")
    print(cp)
    print("===PLATEAU_PROMPT===")
    print(pp)


def cmd_record(step_no: int, c_ans: str, p_ans: str) -> None:
    st = _load()
    step = gold()[step_no - 1]
    cp = R.control_prompt(st, step)
    pp, _ = R.plateau_prompt(st, step)
    row = R.apply_answers(st, step, c_ans, p_ans, R.est_tokens(cp), R.est_tokens(pp))
    rows = json.load(open(STATE)).get("rows", []) if os.path.exists(STATE) else []
    rows.append(row)
    _save(st, rows=rows)
    print(json.dumps({"recorded": step_no, "kind": row["kind"], "gold": row["gold"],
                      "control": row["control"], "plateau": row["plateau"]}, indent=2))


def cmd_finalize() -> None:
    rows = json.load(open(STATE)).get("rows", [])
    out = {"task": "register-ledger long-shot demo",
           "n_steps": len(rows), "seed": SEED, "rows": rows,
           "token_metric": "estimated tokens (chars/4), identical proxy both arms"}
    json.dump(out, open(RECORDS, "w"), indent=2)
    print(f"wrote {RECORDS} with {len(rows)} rows")


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "prompts":
        cmd_prompts(int(sys.argv[2]))
    elif cmd == "record":
        cmd_record(int(sys.argv[2]), sys.argv[3], sys.argv[4])
    elif cmd == "finalize":
        cmd_finalize()
