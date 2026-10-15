"""The self-prompting background loop, tested WITHOUT an LLM.

`sentinel.sh` takes `CLAUDE_BIN` from the environment, so the whole outer loop — cold start,
involuntary reinstatement, budgets, and the two legal exits — can be driven by a MOCK worker
that performs scripted filesystem actions. That makes the loop's control properties testable
deterministically, for free, in seconds:

  * self-prompting  — no human turn between spawns; the next prompt is computed from disk
  * bounded         — the reinstatement prompt does NOT grow with the number of spawns
  * background      — a worker that dies is respawned and resumes at the first unchecked row

What this canNOT test is whether a real model USES the carried signal well; that is what the
demo8 A/B measures. Here we test the machinery around it, which is where the first live
launch's bugs actually lived.
"""
import json
import os
import shutil
import subprocess

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SENTINEL = os.path.join(ROOT, "adapters", "claude_code", "control", "sentinel.sh")

pytestmark = pytest.mark.skipif(not shutil.which("bash"), reason="bash required")

ROW = "- [ ] T{n} | act{n} | f{n}.txt | GATE: true | EXPECT: exit0"


def _seed(*ns):
    """Shell snippet appending real task rows to PLAN.md. `printf '%s\\n'` repeats its
    format per argument, so each row lands on its OWN line — a single `printf "%s"` with
    embedded \\n put them all on one line, and the plan then read as complete after one edit."""
    rows = " ".join('"%s"' % ROW.format(n=n) for n in ns)
    return "printf '%s\\n' " + rows + ' >> "$1/.plateau/control/PLAN.md"'


def _check(n):
    return 'sed -i.bak "s/^- \\[ \\] T%d/- [x] T%d/" "$1/.plateau/control/PLAN.md"' % (n, n)


def _mock_claude(tmp_path, actions):
    """A fake `claude` binary. On spawn i it records the prompt it was given and runs
    `actions[i]` (a shell snippet) against the control dir, then emits the JSON envelope the
    sentinel parses. `actions` is a list of shell snippets, one per expected spawn."""
    mockdir = tmp_path / "mock"
    mockdir.mkdir()
    for i, act in enumerate(actions, start=1):
        (mockdir / f"action.{i}.sh").write_text(act)
    binp = tmp_path / "claude"
    binp.write_text(f"""#!/usr/bin/env bash
MOCK="{mockdir}"
n=$(cat "$MOCK/count" 2>/dev/null || echo 0); n=$((n+1)); echo "$n" > "$MOCK/count"
prompt="${{@: -1}}"
printf '%s' "$prompt" > "$MOCK/prompt.$n.txt"
printf '%s\\n' "$*" | head -c 400 > "$MOCK/argv.$n.txt"
[ -f "$MOCK/action.$n.sh" ] && bash "$MOCK/action.$n.sh" "$PWD"
printf '{{"session_id":"sess-%s","result":"ok"}}\\n' "$n"
""")
    binp.chmod(0o755)
    return binp, mockdir


def _run_sentinel(tmp_path, actions, **env):
    cdir = tmp_path / ".plateau" / "control"
    cdir.mkdir(parents=True, exist_ok=True)
    (cdir / "CONTROL_LOOP.md").write_text("# PROTOCOL (mock)\n")
    (cdir / "TASK.md").write_text("# MISSION\nship the thing.\n")
    (cdir / "reinstate.md").write_text("REINSTATE: resume from the files.\n")
    (cdir / "PLAN.md").write_text("# PLAN\n")          # scaffolded, no task rows yet
    binp, mockdir = _mock_claude(tmp_path, actions)
    e = dict(os.environ, CONTROL_DIR=str(cdir), CLAUDE_BIN=str(binp), BACKOFF="0",
             MAX_RESPAWNS=env.pop("MAX_RESPAWNS", "6"),
             MAX_WALL_MIN=env.pop("MAX_WALL_MIN", "60"), **env)
    p = subprocess.run(["bash", SENTINEL], cwd=str(tmp_path), env=e,
                       capture_output=True, text=True, timeout=120)
    return p, cdir, mockdir


def _prompts(mockdir):
    out = []
    for i in range(1, 50):
        f = mockdir / f"prompt.{i}.txt"
        if not f.exists():
            break
        out.append(f.read_text())
    return out


def test_cold_start_delivers_the_mission_then_warm_reinstates(tmp_path):
    """Spawn 1 must carry the PROTOCOL + TASK (the mission). Once PLAN has rows, later
    spawns switch to the short reinstatement prompt. This is the bug the first live launch
    hit: spawn #1 went down the warm path and the agent never saw TASK.md."""
    p, cdir, mockdir = _run_sentinel(tmp_path, [_seed(1), _check(1)])
    prompts = _prompts(mockdir)
    assert len(prompts) == 2, p.stderr
    assert "MISSION" in prompts[0] and "PROTOCOL" in prompts[0]      # cold: protocol + task
    assert "REINSTATE" in prompts[1]                                  # warm: reinstatement
    assert "spawn #1 (fresh)" in p.stderr
    assert p.returncode == 0                                          # all rows checked -> DONE


def test_respawns_after_a_dead_worker_until_every_row_is_checked(tmp_path):
    """Involuntary reinstatement: a worker that does nothing (or dies) is respawned, and the
    loop keeps going until the plan is genuinely complete. No human turn in between."""
    nothing = "true"                                   # worker returns having done nothing
    p, cdir, mockdir = _run_sentinel(
        tmp_path, [_seed(1, 2), nothing, _check(1), nothing, _check(2)])
    assert p.returncode == 0, p.stderr
    assert "verdict=DONE" in p.stderr
    assert len(_prompts(mockdir)) == 5                 # it did not give up on the idle spawns
    assert "- [ ]" not in (cdir / "PLAN.md").read_text()


def test_reinstatement_prompt_is_bounded_across_spawns(tmp_path):
    """The self-prompt must NOT grow with the number of spawns — that is the whole point of
    resuming from disk instead of replaying a transcript."""
    noise = 'printf "step noise\\n" >> "$1/.plateau/control/JOURNAL.md"'
    p, cdir, mockdir = _run_sentinel(
        tmp_path, [_seed(1, 2, 3), _check(1) + "; " + noise, _check(2) + "; " + noise,
                   _check(3) + "; " + noise])
    assert p.returncode == 0, p.stderr
    warm = [len(x) for x in _prompts(mockdir)[1:]]
    assert len(warm) >= 3
    assert max(warm) == min(warm)                      # byte-identical, spawn after spawn


def test_blocked_report_is_a_legal_exit(tmp_path):
    block = 'printf "class: EXTERNAL\\nattempts: 3\\n" > "$1/.plateau/control/BLOCKED.md"'
    p, cdir, mockdir = _run_sentinel(tmp_path, [_seed(1), block])
    assert p.returncode == 2, p.stderr                 # 2 = BLOCKED, human decision needed
    assert "verdict=BLOCKED" in p.stderr


def test_respawn_budget_stops_a_worker_that_never_progresses(tmp_path):
    """A worker stuck in a no-op loop must not spin forever — the budget is the backstop."""
    p, cdir, mockdir = _run_sentinel(tmp_path, [_seed(1)] + ["true"] * 10, MAX_RESPAWNS="3")
    assert p.returncode == 4, p.stderr                 # 4 = respawn budget
    assert "respawn budget" in p.stderr
    assert len(_prompts(mockdir)) == 3


def test_halts_when_the_mission_file_is_missing(tmp_path):
    cdir = tmp_path / ".plateau" / "control"
    cdir.mkdir(parents=True)
    (cdir / "CONTROL_LOOP.md").write_text("# PROTOCOL\n")
    binp, _ = _mock_claude(tmp_path, [])
    p = subprocess.run(["bash", SENTINEL], cwd=str(tmp_path), capture_output=True, text=True,
                       env=dict(os.environ, CONTROL_DIR=str(cdir), CLAUDE_BIN=str(binp),
                                BACKOFF="0"))
    assert p.returncode == 5                            # 5 = nothing to do; never spawns
    assert "no" in p.stderr.lower()
