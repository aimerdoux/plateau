"""bare_loop — Plateau running a real multi-step task in PLAIN PYTHON, no agent.

This is the host-free proof. If the core needs an agent framework to function, the
host-agnostic claim is fake. So here is the whole continuity loop — emit, inflate,
ground, gate — driving a genuinely dependent computation, with nothing but the
standard library and `plateau`.

The task: a running sum over N steps. Step k must know the total from step k-1. We do
NOT carry the history of all prior steps; we carry only the emitted signal, and each
step inflates it. Each step writes its result to a real file and grounds a fact on
that file's hash — so the carried "total = X" is not the model's word, it is a claim
backed by a Measurement that re-verifies. Run it:

    python examples/bare_loop.py

Expected: the final total is correct, every carried fact re-verifies, the gate drops
an ungrounded claim, a tampered file is caught as STALE at inflation, and the emitted
signal size stays flat across steps (bounded context).
"""

from __future__ import annotations

import os
import tempfile

from plateau import (
    Measurement, Thought, RelationalState, SelfState,
    emit, inflate, apply_gate, set_ground_root,
)
from plateau.integrity import file_hash


def run(n_steps: int = 8) -> dict:
    work = tempfile.mkdtemp(prefix="plateau_bare_")
    set_ground_root(work)  # ground relative measurement sources here — no host paths

    blob_sizes: list[int] = []
    # seed signal: the goal + an initial total of 0 (no fact yet)
    signal = RelationalState(open_goals=["compute running sum 0..N"],
                             stance="carry only the signal; re-ground each step")
    blob = emit(SelfState(signal=signal))
    total = 0

    for k in range(1, n_steps + 1):
        # 1. inflate the carried signal (NOT the history) and re-ground its facts
        inf = inflate(blob, fresh=True)
        assert not inf.stale, f"step {k}: unexpected stale facts {inf.stale_claims()}"
        # recover the prior total from the single carried, re-verified fact (if any)
        carried = [vf for vf in inf.state.verified_facts if vf["claim"].startswith("total=")]
        prior = int(carried[-1]["claim"].split("=")[1]) if carried else 0

        # 2. do this step's dependent work
        total = prior + k

        # 3. write the result to a real file → a re-readable Measurement source
        fname = f"step{k}.txt"
        with open(os.path.join(work, fname), "w") as f:
            f.write(str(total))
        m = Measurement(kind="file_hash", source=fname,
                        value=file_hash(os.path.join(work, fname)))

        # 4. build this step's thoughts: one GROUNDED fact + one UNGROUNDED claim that
        #    the gate must refuse (proves the gate actually gates).
        grounded = Thought(claim=f"total={total}", grounding=m)
        chatter = Thought(claim=f"total is definitely {total + 999} (i'm sure)",
                          grounding=None)

        # 5. gate → fold only admitted facts into the signal, replacing the prior total
        fresh_signal = RelationalState(
            open_goals=inf.state.open_goals, stance=inf.state.stance,
            lessons=inf.state.lessons, pointers=inf.state.pointers,
            verified_facts=[],  # keep only this step's gated total (bounded, not growing)
        )
        ss = SelfState(signal=fresh_signal, thoughts=[grounded, chatter])
        new_signal = apply_gate(ss)
        assert len(new_signal.verified_facts) == 1, "gate should admit exactly the grounded fact"

        # 6. emit the new signal for the next step; record its size (the context cost)
        blob = emit(SelfState(signal=new_signal))
        blob_sizes.append(len(blob))

    expected = n_steps * (n_steps + 1) // 2

    # staleness demo: tamper a measurement source, confirm inflate flags it STALE
    with open(os.path.join(work, f"step{n_steps}.txt"), "w") as f:
        f.write("999999")  # reality no longer matches the carried fact's hash
    stale_inf = inflate(blob, fresh=True)
    staleness_caught = len(stale_inf.stale) == 1

    return {
        "n_steps": n_steps,
        "final_total": total,
        "expected_total": expected,
        "correct": total == expected,
        "blob_sizes": blob_sizes,
        "blob_size_first_last": [blob_sizes[0], blob_sizes[-1]],
        "context_bounded": max(blob_sizes) - min(blob_sizes) < 0.25 * max(blob_sizes),
        "gate_refused_ungrounded": True,  # asserted above (exactly 1 admitted each step)
        "staleness_caught": staleness_caught,
    }


if __name__ == "__main__":
    import json
    r = run()
    print(json.dumps(r, indent=2))
    ok = (r["correct"] and r["context_bounded"] and r["staleness_caught"])
    print("\nHOST-FREE CORE:", "OK — bounded context, dependent work completed, gate + "
          "staleness enforced, no agent framework." if ok else "FAILED")
    raise SystemExit(0 if ok else 1)
