"""Deterministic register-ledger program + GOLD evaluator for the long-shot demo.

Fully reproducible (a literal program, no RNG). Eight registers seeded at step 0;
14 steps mixing UPDATEs and long-range QUERIES (each QUERY references a register last
written >= 5 steps earlier — the recall stress). GOLD (the true register file after
every step) is computed here, independently of any agent.
"""

from __future__ import annotations

from dataclasses import dataclass

SEED = {"R0": 3, "R1": 5, "R2": 2, "R3": 7, "R4": 4, "R5": 9, "R6": 6, "R7": 8}

# Each step: ("UPDATE", dst, a, op, b) or ("QUERY", reg)
PROGRAM = [
    ("UPDATE", "R2", "R0", "+", "R1"),   # 1  3+5=8
    ("UPDATE", "R4", "R3", "*", "R2"),   # 2  7*8=56
    ("UPDATE", "R0", "R5", "-", "R1"),   # 3  9-5=4
    ("UPDATE", "R6", "R4", "+", "R3"),   # 4  56+7=63
    ("UPDATE", "R1", "R2", "*", "R0"),   # 5  8*4=32
    ("QUERY",  "R3"),                     # 6  =7  (set@seed, 6 steps old)
    ("UPDATE", "R5", "R6", "-", "R2"),   # 7  63-8=55
    ("UPDATE", "R3", "R1", "+", "R4"),   # 8  32+56=88
    ("QUERY",  "R0"),                     # 9  =4  (set@3, 6 steps old)
    ("UPDATE", "R7", "R5", "*", "R0"),   # 10 55*4=220
    ("QUERY",  "R2"),                     # 11 =8  (set@1, 10 steps old)
    ("UPDATE", "R4", "R7", "-", "R6"),   # 12 220-63=157
    ("QUERY",  "R1"),                     # 13 =32 (set@5, 8 steps old)
    ("UPDATE", "R0", "R4", "+", "R3"),   # 14 157+88=245
]

_OPS = {"+": lambda a, b: a + b, "-": lambda a, b: a - b, "*": lambda a, b: a * b}


@dataclass
class StepGold:
    step: int
    kind: str            # UPDATE | QUERY
    instruction: str     # human-readable instruction shown to the agent
    answer: int          # the correct integer answer for THIS step
    registers: dict      # full register file AFTER this step (for QUERY: unchanged)
    queried_age: int = 0  # for QUERY: how many steps since the register was last written


def gold() -> list[StepGold]:
    regs = dict(SEED)
    last_write = {r: 0 for r in SEED}   # step index of last write (0 = seed)
    out = []
    for i, step in enumerate(PROGRAM, start=1):
        if step[0] == "UPDATE":
            _, dst, a, op, b = step
            val = _OPS[op](regs[a], regs[b])
            regs[dst] = val
            last_write[dst] = i
            instr = f"Set {dst} = {a} {op} {b}. Report the new value of {dst}."
            out.append(StepGold(i, "UPDATE", instr, val, dict(regs)))
        else:
            _, reg = step
            instr = f"Report the current value of {reg}."
            age = i - last_write[reg]
            out.append(StepGold(i, "QUERY", instr, regs[reg], dict(regs), queried_age=age))
    return out


def seed_text() -> str:
    return ", ".join(f"{k}={v}" for k, v in SEED.items())


if __name__ == "__main__":
    g = gold()
    print("seed:", seed_text())
    for s in g:
        extra = f"  (queried reg is {s.queried_age} steps old)" if s.kind == "QUERY" else ""
        print(f"  step {s.step:>2} [{s.kind}] {s.instruction}  GOLD={s.answer}{extra}")
    longrange = [s for s in g if s.kind == "QUERY"]
    print(f"\n{len(longrange)} QUERY steps, ages: {[s.queried_age for s in longrange]} "
          f"(all >= 5 = long-range recall stress)")
