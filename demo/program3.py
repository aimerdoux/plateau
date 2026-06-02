"""demo3 program — pure recall, confounds removed. Deterministic, reproducible.

Same kind of task as program2 (SET verbatim values, QUERY at controlled distance), with
two fixes from demo3_prereg.md:
  1. RANDOM distinct values (seeded shuffle of 100-999) — no correlation with register
     name or set-order, so magnitude/recency leaks no information.
  2. Bigger far bin: distances near{2,3,4,5} mid{7,9,11,13} far{16,20,24,28,32,36,40,44,
     48,52} = 18 queries (far bin = 10).
The Plateau register file is shuffled per query in the harness (run_demo3), not here.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

DISTANCES = [2, 3, 4, 5, 7, 9, 11, 13, 16, 20, 24, 28, 32, 36, 40, 44, 48, 52]
N_NOISE = 8
SEED = 20260601


@dataclass
class Step:
    t: int
    kind: str
    reg: str
    value: str
    distance: int = 0
    set_at: int = 0
    transcript_steps: int = 0


def build():
    rng = random.Random(SEED)
    pool = list(range(100, 1000))
    rng.shuffle(pool)                      # distinct random values, deterministic
    vi = [0]

    steps: list[Step] = []
    t = [0]

    def val() -> str:
        v = pool[vi[0]]; vi[0] += 1
        return str(v)

    def SET(r: str) -> str:
        t[0] += 1
        v = val()
        steps.append(Step(t[0], "SET", r, v))
        return v

    for j in range(N_NOISE):
        SET(f"N{j}")

    noise_i = [0]

    def filler(n: int) -> None:
        for _ in range(n):
            SET(f"N{noise_i[0] % N_NOISE}")
            noise_i[0] += 1

    for k, d in enumerate(DISTANCES):
        reg = f"T{k}"
        v = SET(reg)
        set_at = t[0]
        filler(d - 1)
        t[0] += 1
        steps.append(Step(t[0], "QUERY", reg, v, distance=d, set_at=set_at,
                          transcript_steps=t[0] - 1))
    return steps


def gold():
    return build()


def bins(steps):
    q = [s for s in steps if s.kind == "QUERY"]
    return ([s for s in q if s.distance <= 5],
            [s for s in q if 6 <= s.distance <= 13],
            [s for s in q if s.distance >= 14])


if __name__ == "__main__":
    steps = build()
    q = [s for s in steps if s.kind == "QUERY"]
    near, mid, far = bins(steps)
    print(f"total steps {len(steps)}  queries {len(q)}  sets {len(steps)-len(q)}")
    print(f"bins: near(<=5)={len(near)} mid(6-13)={len(mid)} far(>=14)={len(far)}")
    print("distances:", [s.distance for s in q])
    print("values (random, distinct):", [s.value for s in q][:8], "...")
    print(f"distinct registers (Plateau file size): {len(set(s.reg for s in steps))}")
    print("control transcript size at far queries:", [s.transcript_steps for s in far])
