"""Control loop — PLAN parsing, the validator, and the gate binding.

The load-bearing property: a task becomes a carried fact ONLY when its parent-authored gate
genuinely passes and its recorded artifact re-verifies. A sub-agent's word is never enough.
Also exercises the armed-only gatekeeper Stop hook as a subprocess (the real hook path).
"""
import json
import os
import shutil
import subprocess

import pytest

from plateau import RelationalState, set_ground_root
from plateau.agency import control as C

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GATEKEEPER = os.path.join(ROOT, "adapters", "claude_code", "control", "gatekeeper.sh")

PLAN = """# PLAN
- [ ] T1 | write marker | out.txt | GATE: echo hi | EXPECT: exit0
- [ ] T2 | substring check | (none) | GATE: echo hello world | EXPECT: hello
- [ ] T3 | failing gate | (none) | GATE: false | EXPECT: exit0
- [ ] T4 | expect mismatch | (none) | GATE: echo abc | EXPECT: zzz
not a task row — ignored
- [ ] T5 no pipes so not a task
"""


def test_parse_plan_reads_rows_and_skips_malformed():
    tasks = C.parse_plan(PLAN)
    assert [t.id for t in tasks] == ["T1", "T2", "T3", "T4"]   # T5 has no GATE -> not a task
    assert tasks[1].gate == "echo hello world" and tasks[1].expect == "hello"
    assert all(t.checked is False for t in tasks)


def test_plan_all_checked_predicate():
    assert C.plan_all_checked(PLAN) is False
    assert C.plan_all_checked("- [x] T1 | a | b | GATE: true | EXPECT: exit0") is True
    assert C.plan_all_checked("# no rows at all") is False


def test_run_gate_records_effective_exit_code(tmp_path):
    adir = str(tmp_path / "gates")
    passing = C.parse_plan(PLAN)[0]          # echo hi / exit0
    art = C.run_gate(passing, str(tmp_path), adir)
    assert art["exit_code"] == 0 and art["matched"] is True
    assert os.path.isfile(art["_path"])

    mismatch = C.parse_plan(PLAN)[3]         # echo abc / EXPECT zzz -> exit 0 but no match
    art2 = C.run_gate(mismatch, str(tmp_path), adir)
    assert art2["raw_exit_code"] == 0        # the command itself succeeded ...
    assert art2["matched"] is False and art2["exit_code"] != 0   # ... but the GATE did not


def test_verify_plan_is_the_done_predicate(tmp_path):
    v = C.verify_plan(PLAN, str(tmp_path), str(tmp_path / "gates"))
    assert v.passed == ["T1", "T2"]
    assert v.failed == ["T3", "T4"]
    assert v.done is False

    ok = "- [ ] TA | a | b | GATE: true | EXPECT: exit0"
    assert C.verify_plan(ok, str(tmp_path), str(tmp_path / "g2")).done is True


def test_only_passing_tasks_enter_the_signal(tmp_path):
    set_ground_root(str(tmp_path))
    sig, v = C.gate_tasks_into_signal(RelationalState(open_goals=["ship"]), PLAN,
                                      str(tmp_path), str(tmp_path / "gates"))
    claims = {f["claim"] for f in sig.verified_facts}
    assert claims == {"T1 done", "T2 done"}          # failing gates never become facts
    assert sig.open_goals == ["ship"]                # signal flows through untouched


def test_fabricated_artifact_is_refused_by_the_gate(tmp_path):
    """A sub-agent cannot fake completion: an artifact claiming success that was not
    produced by the validator has the wrong hash, or a non-zero exit_code, and the
    Measurement refuses it."""
    set_ground_root(str(tmp_path))
    adir = tmp_path / "gates"
    adir.mkdir()
    task = C.parse_plan("- [ ] T9 | x | y | GATE: false | EXPECT: exit0")[0]

    # hand-written "success" artifact (the sub-agent's word, dressed up as evidence)
    fake = adir / "T9.gate.json"
    fake.write_text(json.dumps({"task": "T9", "exit_code": 0}))
    from plateau.integrity import file_hash
    th = C.task_fact(task, str(fake), str(tmp_path))
    assert th.is_grounded_now() is True      # hash matches what we just read: admissible...

    # ...but the real validator overwrites it with the TRUE outcome, and the stale hash breaks
    art = C.run_gate(task, str(tmp_path), str(adir))
    assert art["exit_code"] != 0
    assert th.grounding.reverify() is False  # hash changed AND exit_code != 0 -> refused
    assert file_hash(str(fake)) != th.grounding.value


def _gatekeeper(tmp_path, env_extra=None):
    env = dict(os.environ, CONTROL_DIR=str(tmp_path / ".plateau" / "control"))
    env.update(env_extra or {})
    r = subprocess.run(["bash", GATEKEEPER], cwd=str(tmp_path), input="{}",
                       capture_output=True, text=True, env=env)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


@pytest.mark.skipif(not shutil.which("bash"), reason="bash required")
def test_gatekeeper_is_inert_without_a_control_run(tmp_path):
    """Not armed: no PLAN.md -> ordinary sessions are never blocked."""
    assert _gatekeeper(tmp_path) == ""


@pytest.mark.skipif(not shutil.which("bash"), reason="bash required")
def test_gatekeeper_blocks_on_unchecked_gates(tmp_path):
    cdir = tmp_path / ".plateau" / "control"
    cdir.mkdir(parents=True)
    (cdir / "PLAN.md").write_text(PLAN)
    out = json.loads(_gatekeeper(tmp_path))
    assert out["decision"] == "block"
    assert "T1" in out["reason"]


@pytest.mark.skipif(not shutil.which("bash"), reason="bash required")
def test_gatekeeper_releases_on_done_and_on_blocked(tmp_path):
    cdir = tmp_path / ".plateau" / "control"
    cdir.mkdir(parents=True)
    (cdir / "PLAN.md").write_text("- [x] T1 | a | b | GATE: true | EXPECT: exit0\n")
    assert _gatekeeper(tmp_path) == ""                       # DONE -> release

    (cdir / "PLAN.md").write_text(PLAN)                      # unchecked again -> blocks
    assert json.loads(_gatekeeper(tmp_path))["decision"] == "block"
    (cdir / "BLOCKED.md").write_text("class: EXTERNAL\nattempts: 3\n")
    assert _gatekeeper(tmp_path) == ""                       # BLOCKED-REPORT -> release


@pytest.mark.skipif(not shutil.which("bash"), reason="bash required")
def test_gatekeeper_blocks_a_checked_row_whose_artifact_says_failed(tmp_path):
    """A box can be checked in error (or go stale): if gates/<id>.gate.json — the ground
    truth written by run_gate — records exit_code != 0 for a CHECKED row, the gatekeeper
    must not let the run stop. This check is always on, no RUN_GATES needed."""
    cdir = tmp_path / ".plateau" / "control"
    cdir.mkdir(parents=True)
    (cdir / "PLAN.md").write_text("- [x] T1 | a | b | GATE: false | EXPECT: exit0\n")
    gates = cdir / "gates"
    task = C.parse_plan((cdir / "PLAN.md").read_text())[0]
    C.run_gate(task, str(tmp_path), str(gates))       # writes T1.gate.json, exit_code != 0
    out = json.loads(_gatekeeper(tmp_path))
    assert out["decision"] == "block"
    assert "T1" in out["reason"] and "FAILED" in out["reason"]


@pytest.mark.skipif(not shutil.which("bash"), reason="bash required")
def test_gatekeeper_trusts_a_checked_row_whose_artifact_says_passed(tmp_path):
    """The converse: a genuinely passing artifact must not block the checked row it backs."""
    cdir = tmp_path / ".plateau" / "control"
    cdir.mkdir(parents=True)
    (cdir / "PLAN.md").write_text("- [x] T1 | a | b | GATE: true | EXPECT: exit0\n")
    gates = cdir / "gates"
    task = C.parse_plan((cdir / "PLAN.md").read_text())[0]
    C.run_gate(task, str(tmp_path), str(gates))       # writes T1.gate.json, exit_code == 0
    assert _gatekeeper(tmp_path) == ""


@pytest.mark.skipif(not shutil.which("bash"), reason="bash required")
def test_gatekeeper_strict_mode_catches_a_regressed_checked_gate(tmp_path):
    """V3: a checked box whose gate no longer passes must not be allowed to stop."""
    cdir = tmp_path / ".plateau" / "control"
    cdir.mkdir(parents=True)
    (cdir / "PLAN.md").write_text("- [x] T1 | a | b | GATE: false | EXPECT: exit0\n")
    out = json.loads(_gatekeeper(tmp_path, {"RUN_GATES": "1"}))
    assert out["decision"] == "block"
    assert "Regression" in out["reason"] and "T1" in out["reason"]


# --------------------------------------------------- dispatch safety ------
# Preflight checks added after the self-hosting run named both as gaps: parallel dispatch
# had no collision detection (the parent hand-sequenced two tasks that shared a file), and
# nothing verified a gate could actually RUN before workers were spent.

def test_touched_paths_extracts_paths_and_ignores_prose():
    tasks = C.parse_plan(
        "- [ ] T1 | a | plateau/agency/{control.py,__main__.py} | GATE: true | EXPECT: exit0\n"
        "- [ ] T2 | a | (repo) | GATE: true | EXPECT: exit0\n"
        "- [ ] T3 | a | demo/raw7/ + demo/out.md | GATE: true | EXPECT: exit0\n"
    )
    assert tasks[0].touched_paths() == {"plateau/agency/control.py",
                                        "plateau/agency/__main__.py"}
    assert tasks[1].touched_paths() == set()          # prose deliverable -> never collides
    assert tasks[2].touched_paths() == {"demo/raw7", "demo/out.md"}


def test_paths_overlap_conservative_cases():
    assert C._paths_overlap("a/b.py", "a/b.py")                    # exact
    assert C._paths_overlap("demo/raw7", "demo/raw7/x.json")       # dir containment
    assert C._paths_overlap("control.py", "plateau/agency/control.py")  # bare shorthand
    assert not C._paths_overlap("a/b.py", "a/c.py")
    assert not C._paths_overlap("plateau/x/control.py", "plateau/y/control.py")


def test_conflicts_catches_bare_filename_shorthand_collision():
    """The real case from the self-hosting run: T1's deliverable wrote the shorthand
    'control.py' while T2 wrote the full path. A string-equality check missed it."""
    tasks = C.parse_plan(
        "- [ ] T1 | cli | plateau/agency/__main__.py + control.py CLI | GATE: true | EXPECT: exit0\n"
        "- [ ] T2 | helpers | plateau/agency/control.py | GATE: true | EXPECT: exit0\n"
        "- [ ] T3 | tests | tests/test_x.py | GATE: true | EXPECT: exit0\n"
    )
    cfl = C.conflicts(tasks)
    assert len(cfl) == 1
    assert cfl[0][0] == "T1" and cfl[0][1] == "T2"


def test_parallel_batches_are_collision_free_and_order_preserving():
    tasks = C.parse_plan(
        "- [ ] T1 | a | pkg/mod.py | GATE: true | EXPECT: exit0\n"
        "- [ ] T2 | a | pkg/mod.py | GATE: true | EXPECT: exit0\n"
        "- [ ] T3 | a | other.py | GATE: true | EXPECT: exit0\n"
    )
    batches = C.parallel_batches(tasks)
    assert [t.id for t in batches[0]] == ["T1", "T3"]   # disjoint -> same batch
    assert [t.id for t in batches[1]] == ["T2"]         # collides with T1 -> next batch
    for batch in batches:                               # the invariant that matters
        assert C.conflicts(batch) == []


def test_preflight_flags_a_gate_whose_command_is_missing(tmp_path):
    tasks = C.parse_plan(
        "- [ ] T1 | a | x.py | GATE: echo hi | EXPECT: exit0\n"
        "- [ ] T2 | a | y.py | GATE: definitely-not-a-real-binary-xyz --v | EXPECT: exit0\n"
    )
    pf = C.preflight(tasks, str(tmp_path))
    assert pf["ok"] is False
    assert pf["runnable"] == ["T1"]
    assert pf["missing"][0]["task"] == "T2"


def test_cmd_preflight_verdict_and_nonzero_exit_on_missing_command(tmp_path):
    cdir = tmp_path / "control"
    cdir.mkdir()
    (cdir / "PLAN.md").write_text(
        "- [ ] T1 | a | x.py | GATE: definitely-not-a-real-binary-xyz | EXPECT: exit0\n")
    assert C.cmd_preflight(str(cdir), str(tmp_path))["verdict"] == "NO_GO"
    assert C.main(["preflight", "--control-dir", str(cdir), "--root", str(tmp_path)]) == 1


# ------------------------------------------- scaffolded != planned --------
# A first live launch exposed this class of bug: `init` scaffolds PLAN.md/RECON.md, and
# every consumer that keyed on FILE EXISTENCE (or on "zero unchecked rows") then treated a
# freshly-scaffolded dir as a planned — or even finished — run.

def test_init_stub_contains_no_parseable_task_row(tmp_path):
    """The template row must NOT parse as a real task: a literal '- [ ]' in the stub armed
    the gatekeeper on a placeholder and made the sentinel skip its cold start."""
    cdir = tmp_path / "control"
    C.cmd_init(str(cdir))
    plan = (cdir / "PLAN.md").read_text()
    assert C.parse_plan(plan) == []
    assert "- [ ]" not in plan


def test_init_is_idempotent_and_never_clobbers(tmp_path):
    cdir = tmp_path / "control"
    C.cmd_init(str(cdir))
    (cdir / "PLAN.md").write_text("- [ ] T1 | a | b | GATE: true | EXPECT: exit0\n")
    again = C.cmd_init(str(cdir))
    assert again["created"] == []                      # nothing re-created
    assert len(C.parse_plan((cdir / "PLAN.md").read_text())) == 1   # real work preserved


@pytest.mark.skipif(not shutil.which("bash"), reason="bash required")
def test_gatekeeper_blocks_a_scaffolded_but_unplanned_dir(tmp_path):
    """Stopping before any task row exists is never legal — the run has not planned yet."""
    cdir = tmp_path / ".plateau" / "control"
    C.cmd_init(str(cdir))
    out = json.loads(_gatekeeper(tmp_path))
    assert out["decision"] == "block"
    assert "no task rows" in out["reason"]


# --------------------------------------------- id grammar / false GO ------
# Both found by dogfooding: a hardening plan using ids H0..H4 parsed to ZERO tasks, and
# preflight still reported GO on that empty parse.

def test_task_ids_are_not_restricted_to_the_letter_T():
    """The id was once hardcoded to `T`, so any other prefix was SILENTLY dropped — the only
    symptom was an empty parse, which then read as a clean plan."""
    plan = ("- [ ] H0 | a | x.py | GATE: true | EXPECT: exit0\n"
            "- [x] SEC-3 | b | y.py | GATE: true | EXPECT: exit0\n"
            "- [ ] T1 | c | z.py | GATE: true | EXPECT: exit0\n")
    ids = [t.id for t in C.parse_plan(plan)]
    assert ids == ["H0", "SEC-3", "T1"]


def test_shell_row_pattern_agrees_with_the_parser():
    """The sentinel and gatekeeper grep for task rows in shell. If that pattern and `_ROW`
    disagree, the loop's verdict and its enforcement diverge — so pin them together."""
    import re
    for line in ("- [ ] H0 | a | b | GATE: true | EXPECT: exit0",
                 "- [x] T1 | a | b | GATE: true | EXPECT: exit0"):
        assert C.parse_plan(line), line
        assert re.search(C._ID_GREP, line), line
    for line in ("# PLAN", "- [_] T1 | template row", "some prose"):
        assert not C.parse_plan(line)
        assert not re.search(C._ID_GREP, line), line


def test_preflight_on_an_empty_plan_is_NO_PLAN_not_GO(tmp_path):
    cdir = tmp_path / "control"
    cdir.mkdir()
    (cdir / "PLAN.md").write_text("# PLAN\n\nno rows yet\n")
    out = C.cmd_preflight(str(cdir), str(tmp_path))
    assert out["verdict"] == "NO_PLAN"
    assert out["task_count"] == 0
    assert "hint" in out
