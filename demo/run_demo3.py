"""demo3 harness — like run_demo2 but (1) program3 (random values, far bin=10) and
(2) the Plateau register file is SHUFFLED per query (deterministic seed=query index) so
the target sits at a random position — no "grab the top line" shortcut. Reuses the
identical scorer (score_demo2.score_rows) — same locked rule, proven by reuse.
"""

from __future__ import annotations

import json
import os
import random

from plateau import (
    Measurement, Thought, RelationalState, SelfState, emit, inflate, apply_gate,
    set_ground_root,
)
from plateau.integrity import file_hash
from demo.program3 import build
from demo.run_demo2 import est_tokens, score_answer

HERE = os.path.dirname(__file__)
RAW = os.path.join(HERE, "raw3")
WORK = os.path.join(RAW, "plateau_work")

INSTR = ("You are a memory test. Registers hold values. Using ONLY the information below, "
         "answer the question with ONLY the value, nothing else.")


def _reset_work():
    import shutil
    if os.path.isdir(WORK):
        for f in os.listdir(WORK):
            try:
                os.chmod(os.path.join(WORK, f), 0o644)
            except OSError:
                pass
        shutil.rmtree(WORK)
    os.makedirs(WORK, exist_ok=True)


def build_queries():
    _reset_work()
    set_ground_root(WORK)
    steps = build()
    transcript: list[str] = []
    blob = emit(SelfState(signal=RelationalState(
        open_goals=["answer recall queries from the register file"],
        stance="report the current value verbatim")))
    specs = []
    qi = 0
    for s in steps:
        if s.kind == "SET":
            transcript.append(f"  step {s.t}: {s.reg} = {s.value}")
            p = os.path.join(WORK, f"{s.reg}.txt")
            if os.path.exists(p):
                os.chmod(p, 0o644)
            with open(p, "w") as f:
                f.write(s.value)
            m = Measurement("file_hash", f"{s.reg}.txt", file_hash(p))
            inf = inflate(blob, fresh=True)
            kept = [vf for vf in inf.state.verified_facts
                    if not vf["claim"].startswith(f"{s.reg}=")]
            sig = RelationalState(open_goals=inf.state.open_goals, stance=inf.state.stance,
                                  lessons=inf.state.lessons, pointers=inf.state.pointers,
                                  verified_facts=kept)
            blob = emit(SelfState(signal=apply_gate(
                SelfState(sig, [Thought(f"{s.reg}={s.value}", m)]))))
        else:
            set_ground_root(WORK)
            inf = inflate(blob, fresh=True)
            pairs = [(vf["claim"].split("=")[0], vf["claim"].split("=", 1)[1])
                     for vf in inf.state.verified_facts]
            random.Random(1000 + qi).shuffle(pairs)        # SHUFFLE: no positional shortcut
            reg_line = "\n".join(f"  {k} = {v}" for k, v in pairs)
            cprompt = (f"{INSTR}\n\nTranscript (each line set a register):\n"
                       + "\n".join(transcript) + f"\n\nQuestion: what is {s.reg} now?")
            pprompt = (f"{INSTR}\n\nCurrent register file:\n{reg_line}\n\n"
                       f"Question: what is {s.reg} now?")
            specs.append({"k": qi, "reg": s.reg, "distance": s.distance, "gold": s.value,
                          "control_prompt": cprompt, "plateau_prompt": pprompt,
                          "control_tokens": est_tokens(cprompt),
                          "plateau_tokens": est_tokens(pprompt),
                          "control_transcript_steps": s.transcript_steps})
            qi += 1
    return specs


def mock_plumbing(mode: str = "win") -> dict:
    from demo.score_demo2 import score_rows
    specs = build_queries()
    rows = []
    for sp in specs:
        g = sp["gold"]; d = sp["distance"]
        plat = g
        if mode == "win":
            ctrl = g if d <= 13 else ("000" if d % 8 == 0 else g)   # control decays far
        elif mode == "null":
            ctrl = g; plat = g if d < 40 else "000"                  # plateau also drops far
        else:
            ctrl = g
        rows.append(score_answer(sp, ctrl, plat))
    return score_rows(rows)


if __name__ == "__main__":
    print("WIN:", mock_plumbing("win")["verdict"][:70])
    print("NULL:", mock_plumbing("null")["verdict"][:70])
    print("UNSCORABLE:", mock_plumbing("unscorable")["verdict"][:70])
