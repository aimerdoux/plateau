"""Pure-recall program for demo2 (NO arithmetic). Deterministic, reproducible.

Registers hold VERBATIM, globally-unique 2-digit+ values. Two op kinds:
  SET   R, v   — establish R = v. Deterministic; grows the control transcript and updates
                 the Plateau register file. Not a recall test → not sent to an agent.
  QUERY R      — "what is R now?" answer = R's latest value, VERBATIM. A wrong answer can
                 ONLY be a memory/context failure, never arithmetic.

Design that keeps the test fair AND keeps Plateau bounded:
  - A small pool of NOISE registers (N0..N7) is re-set repeatedly as filler — this grows
    the control transcript without growing the register FILE (Plateau stays bounded).
  - 14 TARGET registers (T0..T13) are each SET once, then QUERIED exactly `distance` steps
    later (the intervening steps are noise re-sets). distance is controlled precisely.
  - Because state changes only at SET steps (fixed by this program), every QUERY's control
    prompt is a deterministic prefix → all queries are independent and parallelizable.

The queried value is always still CURRENT (targets are set once), so it lives in BOTH
arms' context: in the Plateau file (one short line) and in the control transcript (buried
`distance`+ steps back, under noise). The empirical question is whether retrieval degrades
with distance — flat for Plateau, degrading for full-history control.

Bins: near 1-5, mid 6-13, far 14+.
"""

from __future__ import annotations

from dataclasses import dataclass

# distance for each of the 14 target registers (4 near, 4 mid, 6 far)
DISTANCES = [2, 3, 4, 5, 7, 9, 11, 13, 16, 22, 28, 34, 40, 48]
N_NOISE = 8


@dataclass
class Step:
    t: int
    kind: str            # SET | QUERY
    reg: str
    value: str
    distance: int = 0
    set_at: int = 0
    transcript_steps: int = 0   # QUERY only: how many steps precede it (control size proxy)


def build():
    steps: list[Step] = []
    nv = [10]
    t = [0]

    def val() -> str:
        nv[0] += 1
        return str(nv[0])

    def SET(r: str) -> str:
        t[0] += 1
        v = val()
        steps.append(Step(t[0], "SET", r, v))
        return v

    # seed the noise pool so fillers have something to re-set
    for j in range(N_NOISE):
        SET(f"N{j}")

    noise_i = [0]

    def filler(n: int) -> None:
        for _ in range(n):
            SET(f"N{noise_i[0] % N_NOISE}")
            noise_i[0] += 1

    for k, d in enumerate(DISTANCES):
        reg = f"T{k}"
        v = SET(reg)            # set the target (unique value)
        set_at = t[0]
        filler(d - 1)           # d-1 noise steps so the query lands exactly `d` away
        t[0] += 1               # the QUERY step
        steps.append(Step(t[0], "QUERY", reg, v, distance=d, set_at=set_at,
                          transcript_steps=t[0] - 1))
    return steps


def gold():
    return build()


def bins(steps):
    q = [s for s in steps if s.kind == "QUERY"]
    near = [s for s in q if s.distance <= 5]
    mid = [s for s in q if 6 <= s.distance <= 13]
    far = [s for s in q if s.distance >= 14]
    return near, mid, far


if __name__ == "__main__":
    steps = build()
    q = [s for s in steps if s.kind == "QUERY"]
    near, mid, far = bins(steps)
    print(f"total steps {len(steps)}  queries {len(q)}  sets {len(steps)-len(q)}")
    print(f"bins: near(<=5)={len(near)} mid(6-13)={len(mid)} far(>=14)={len(far)}")
    print("distances:", [s.distance for s in q])
    print("control transcript size at each query (steps):", [s.transcript_steps for s in q])
    print(f"distinct registers (Plateau file size): {len(set(s.reg for s in steps))} (bounded)")
