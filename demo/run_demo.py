"""Long-shot demo harness — build per-arm prompts, record sealed per-step records.

Two independent executions of the SAME register-ledger task (demo/program.py):

  CONTROL : carries the full transcript (every prior instruction + its own prior
            answer). Prompt grows every step.
  PLATEAU : carries only the inflated signal — the register file as gated facts, each
            grounded on a file hash. Prompt is bounded.

Python cannot call the agent runtime, so the orchestrator drives it:
  1. next_prompts(state, step) -> (control_prompt, plateau_prompt) + token counts
  2. orchestrator dispatches the two subagents, gets two integer answers
  3. apply_answers(...) records the sealed per-step row and advances each arm's state

Token count is an estimate (chars / 4), applied IDENTICALLY to both arms — the slope
comparison is invariant to the constant. Recorded as `prompt_tokens_est`.

mock_plumbing() runs the whole thing with simulated answers (perfect agent, and an
amnesia variant) to prove the wiring + both verdict branches BEFORE any spend.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

from plateau import (
    Measurement, Thought, RelationalState, SelfState, emit, inflate, apply_gate,
    set_ground_root,
)
from plateau.integrity import file_hash
from demo.program import gold, seed_text, SEED, StepGold

HERE = os.path.dirname(__file__)
RAW = os.path.join(HERE, "raw")

INSTR = ("You are doing register arithmetic. Registers hold integers. Using ONLY the "
         "register values available to you below, answer this step. Reply with ONLY the "
         "integer, nothing else.")


def est_tokens(s: str) -> int:
    return max(1, len(s) // 4)


@dataclass
class RunState:
    # control arm: full transcript of (instruction, its own answer)
    control_history: list[tuple[str, str]] = field(default_factory=list)
    # plateau arm: register file carried as a signal blob (built from its own answers)
    plateau_blob: str = ""
    work: str = ""   # ground root for plateau measurement files

    def init_plateau(self) -> None:
        self.work = RAW + "/plateau_work"
        os.makedirs(self.work, exist_ok=True)
        set_ground_root(self.work)
        facts = []
        for r, v in SEED.items():
            p = os.path.join(self.work, f"{r}.txt")
            with open(p, "w") as f:
                f.write(str(v))
            facts.append({"claim": f"{r}={v}", "grounding_kind": "file_hash",
                          "grounding_source": f"{r}.txt", "grounding_value": file_hash(p)})
        sig = RelationalState(open_goals=["maintain register file"],
                              stance="answer from the carried register values",
                              verified_facts=facts)
        self.plateau_blob = emit(SelfState(signal=sig))


def control_prompt(state: RunState, step: StepGold) -> str:
    lines = [INSTR, f"\nSeed registers (step 0): {seed_text()}", "\nTranscript so far:"]
    if not state.control_history:
        lines.append("  (none yet)")
    for i, (instr, ans) in enumerate(state.control_history, start=1):
        lines.append(f"  step {i}: {instr}  -> you answered {ans}")
    lines.append(f"\nStep {step.step}: {step.instruction}")
    return "\n".join(lines)


def plateau_prompt(state: RunState, step: StepGold) -> tuple[str, list[str]]:
    set_ground_root(state.work)
    inf = inflate(state.plateau_blob, fresh=True)
    regs = {vf["claim"].split("=")[0]: vf["claim"].split("=")[1]
            for vf in inf.state.verified_facts}
    reg_line = ", ".join(f"{k}={regs[k]}" for k in sorted(regs))
    p = (f"{INSTR}\n\nCurrent register values (your carried signal): {reg_line}\n\n"
         f"Step {step.step}: {step.instruction}")
    return p, inf.stale_claims()


def apply_answers(state: RunState, step: StepGold, control_ans: str, plateau_ans: str,
                  c_tokens: int, p_tokens: int) -> dict:
    """Record the sealed per-step row and advance each arm's carried state from ITS OWN
    answer. Returns the raw row (correctness scored vs GOLD)."""
    c_correct = _as_int(control_ans) == step.answer
    p_correct = _as_int(plateau_ans) == step.answer

    # advance control: append (instruction, its own answer) to the transcript
    state.control_history.append((step.instruction, str(control_ans).strip()))

    # advance plateau: on UPDATE, gate the plateau arm's own answer as the register's
    # new value (grounded on a rewritten file). QUERY changes no register.
    if step.kind == "UPDATE":
        dst = step.instruction.split()[1]  # "Set R2 = ..."
        set_ground_root(state.work)
        p = os.path.join(state.work, f"{dst}.txt")
        os.chmod(p, 0o644) if os.path.exists(p) else None
        with open(p, "w") as f:
            f.write(str(_as_int(plateau_ans)))
        m = Measurement("file_hash", f"{dst}.txt", file_hash(p))
        inf = inflate(state.plateau_blob, fresh=True)
        kept = [vf for vf in inf.state.verified_facts
                if not vf["claim"].startswith(f"{dst}=")]
        sig = RelationalState(
            open_goals=inf.state.open_goals, stance=inf.state.stance,
            lessons=inf.state.lessons, pointers=inf.state.pointers,
            verified_facts=kept)
        ss = SelfState(signal=sig, thoughts=[Thought(f"{dst}={_as_int(plateau_ans)}", m)])
        state.plateau_blob = emit(SelfState(signal=apply_gate(ss)))

    return {
        "step": step.step, "kind": step.kind, "instruction": step.instruction,
        "gold": step.answer, "queried_age": step.queried_age,
        "control": {"answer": str(control_ans).strip(), "correct": c_correct,
                    "prompt_tokens_est": c_tokens},
        "plateau": {"answer": str(plateau_ans).strip(), "correct": p_correct,
                    "prompt_tokens_est": p_tokens},
    }


def _as_int(s) -> int:
    try:
        return int(str(s).strip().split()[0].rstrip(".").replace(",", ""))
    except (ValueError, IndexError):
        return 10**18  # unparseable answer -> never matches GOLD


# ----------------- LABELED MOCK PLUMBING (free, NOT a result) -----------------

def mock_plumbing(amnesia: bool = False) -> dict:
    """Run the whole harness with simulated answers. perfect agent => WIN shape;
    amnesia=True makes plateau miss the long-range QUERY steps => PARTIAL shape."""
    from plateau.metrics import ArmCurve, decide
    g = gold()
    state = RunState()
    state.init_plateau()
    rows = []
    for step in g:
        cp = control_prompt(state, step)
        pp, _ = plateau_prompt(state, step)
        c_ans = step.answer                                  # control: perfect
        if amnesia and step.kind == "QUERY" and step.queried_age >= 5:
            p_ans = step.answer + 1                           # plateau forgets old state
        else:
            p_ans = step.answer
        rows.append(apply_answers(state, step, str(c_ans), str(p_ans),
                                  est_tokens(cp), est_tokens(pp)))
    ctrl = ArmCurve("control", [r["step"] for r in rows],
                    [r["control"]["prompt_tokens_est"] for r in rows],
                    [int(r["control"]["correct"]) for r in rows])
    plat = ArmCurve("plateau", [r["step"] for r in rows],
                    [r["plateau"]["prompt_tokens_est"] for r in rows],
                    [int(r["plateau"]["correct"]) for r in rows])
    d = decide(ctrl, plat)
    return {"LABEL": "MOCK PLUMBING — simulated answers, NOT a result",
            "amnesia_variant": amnesia,
            "control_slope": d["control"]["slope"], "plateau_slope": d["plateau"]["slope"],
            "control_completion": d["control"]["mean_completion"],
            "plateau_completion": d["plateau"]["mean_completion"],
            "verdict": d["verdict"]}


if __name__ == "__main__":
    print(json.dumps(mock_plumbing(amnesia=False), indent=2))
    print(json.dumps(mock_plumbing(amnesia=True), indent=2))
