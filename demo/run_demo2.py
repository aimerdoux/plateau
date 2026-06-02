"""Recall-only demo harness. Precomputes both arms' prompts for all 14 queries
(independent, deterministic), so they dispatch in parallel. Genuinely drives the Plateau
core: every SET is gated into the signal (grounded on a file hash); each query's Plateau
prompt is the inflated register file.

Control prompt = the full SET/noise transcript so far + the query (the fact is buried
`distance` steps back). Plateau prompt = the current register file + the query.
"""

from __future__ import annotations

import json
import os

from plateau import (
    Measurement, Thought, RelationalState, SelfState, emit, inflate, apply_gate,
    set_ground_root,
)
from plateau.integrity import file_hash
from demo.program2 import build

HERE = os.path.dirname(__file__)
RAW = os.path.join(HERE, "raw2")
WORK = os.path.join(RAW, "plateau_work")

INSTR = ("You are a memory test. Registers hold values. Using ONLY the information below, "
         "answer the question with ONLY the value, nothing else.")


def est_tokens(s: str) -> int:
    return max(1, len(s) // 4)


def _reset_work():
    import shutil
    if os.path.isdir(WORK):
        for f in os.listdir(WORK):
            p = os.path.join(WORK, f)
            try:
                os.chmod(p, 0o644)
            except OSError:
                pass
        shutil.rmtree(WORK)
    os.makedirs(WORK, exist_ok=True)


def build_queries():
    """Replay the program, driving the Plateau core, and emit one spec per QUERY with both
    arms' prompts + token counts. Deterministic; no agent involved here."""
    _reset_work()
    set_ground_root(WORK)
    steps = build()
    transcript: list[str] = []                 # control: rendered SET lines
    blob = emit(SelfState(signal=RelationalState(
        open_goals=["answer recall queries from the register file"],
        stance="report the current value verbatim")))
    specs = []
    for s in steps:
        if s.kind == "SET":
            transcript.append(f"  step {s.t}: {s.reg} = {s.value}")
            # gate the value into the Plateau signal (grounded on a real file)
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
        else:  # QUERY — build both arms' prompts (deterministic prefix)
            set_ground_root(WORK)
            inf = inflate(blob, fresh=True)
            regs = {vf["claim"].split("=")[0]: vf["claim"].split("=", 1)[1]
                    for vf in inf.state.verified_facts}
            reg_line = "\n".join(f"  {k} = {regs[k]}" for k in sorted(regs))
            cprompt = (f"{INSTR}\n\nTranscript (each line set a register):\n"
                       + "\n".join(transcript) + f"\n\nQuestion: what is {s.reg} now?")
            pprompt = (f"{INSTR}\n\nCurrent register file:\n{reg_line}\n\n"
                       f"Question: what is {s.reg} now?")
            specs.append({"k": len([x for x in specs]), "reg": s.reg,
                          "distance": s.distance, "gold": s.value,
                          "control_prompt": cprompt, "plateau_prompt": pprompt,
                          "control_tokens": est_tokens(cprompt),
                          "plateau_tokens": est_tokens(pprompt),
                          "control_transcript_steps": s.transcript_steps})
    return specs


import re


def _last_int(a) -> str:
    """Extract the LAST integer from a possibly-prose answer (agents sometimes wrap the
    value in explanation). Empty string if none."""
    nums = re.findall(r"-?\d+", str(a).replace(",", ""))
    return nums[-1] if nums else ""


def score_answer(spec, control_ans, plateau_ans):
    # raw answer stored verbatim for audit; correctness uses last-integer extraction
    return {"reg": spec["reg"], "distance": spec["distance"], "gold": spec["gold"],
            "control": {"answer_raw": str(control_ans).strip(),
                        "answer": _last_int(control_ans),
                        "correct": _last_int(control_ans) == spec["gold"],
                        "prompt_tokens_est": spec["control_tokens"]},
            "plateau": {"answer_raw": str(plateau_ans).strip(),
                        "answer": _last_int(plateau_ans),
                        "correct": _last_int(plateau_ans) == spec["gold"],
                        "prompt_tokens_est": spec["plateau_tokens"]}}


# ---------------- LABELED MOCK PLUMBING (free, NOT a result) ----------------

def mock_plumbing(mode: str = "win") -> dict:
    """Simulate answers to confirm scoring branches fire BEFORE spend.
    mode=win: control recall decays with distance, Plateau stays perfect.
    mode=null: both perfect (Plateau no better → NULL).
    mode=unscorable: control also perfect (no degradation → UNSCORABLE)."""
    from demo.score_demo2 import score_rows
    specs = build_queries()
    rows = []
    for sp in specs:
        d = sp["distance"]; g = sp["gold"]
        plat = g                                            # Plateau: reads short file
        if mode == "win":
            ctrl = g if d <= 6 else (g if (d % 7 != 0) and d < 20 else "99")  # decays far
        elif mode == "null":
            ctrl = g
        else:  # unscorable
            ctrl = g
            plat = g
        if mode == "win":
            # make far clearly worse: flip most far answers wrong
            ctrl = g if d <= 13 else ("99" if d >= 16 else g)
        rows.append(score_answer(sp, ctrl, plat))
    return score_rows(rows)


if __name__ == "__main__":
    print(json.dumps(mock_plumbing("win"), indent=2)[:800])
    print("NULL:", mock_plumbing("null")["verdict"][:80])
    print("UNSCORABLE:", mock_plumbing("unscorable")["verdict"][:80])
