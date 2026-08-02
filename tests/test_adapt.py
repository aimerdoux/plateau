"""The gap-analysis / recalibration layer: predict -> observe -> gap -> recalibrate.

The property that removes babysitting: a gate that fails must become a CLASSIFIED blocker
with a next action, automatically, without a human reading the log first.
"""
import json
import os

from plateau.agency import adapt as A
from plateau.agency import control as C

ROW = "- [{m}] {tid} | act | f.txt | GATE: true | EXPECT: exit0"


def _plan(*specs):
    return "\n".join(ROW.format(m=m, tid=t) for t, m in specs) + "\n"


def _artifact(gates_dir, tid, exit_code, output=""):
    os.makedirs(gates_dir, exist_ok=True)
    with open(os.path.join(gates_dir, f"{tid}.gate.json"), "w") as fh:
        json.dump({"task": tid, "exit_code": exit_code, "output_tail": output}, fh)


def test_blocker_classification_covers_the_taxonomy():
    cases = [
        ("bash: permission denied", "PERMISSION"),
        ("This operation requires approval", "PERMISSION"),
        ("zsh: command not found: pytest", "CAPABILITY"),
        ("ModuleNotFoundError: No module named 'plateau'", "CAPABILITY"),
        ("curl: (7) Connection refused", "EXTERNAL"),
        ("HTTP 429 rate limit exceeded", "EXTERNAL"),
        ("ENOENT: no such file or directory", "MISSING-INFO"),
        ("wibble frobnicated unexpectedly", "AMBIGUITY"),
    ]
    for output, expected in cases:
        klass, action = A.classify_blocker(output)
        assert klass == expected, (output, klass)
        assert action, "every class must carry a smallest unblocking action"


def test_failed_gate_becomes_a_classified_blocker_with_a_next_action():
    """No human in the loop: the failure classifies itself and proposes the next move."""
    g = A.analyze_gap("T3", "pytest reports 12 passed",
                      {"exit_code": 1, "output_tail": "zsh: command not found: pytest"})
    assert g.klass == A.REFUTED
    assert g.blocker == "CAPABILITY"
    assert "install or substitute" in g.unblock
    assert "not a stop" in g.note          # a blocker is the next unit of work


def test_gate_passing_for_the_wrong_reason_is_DRIFT_not_success():
    """The adaptive catch: the gate went green, but nothing the forecast predicted was
    observed — often a gate too loose to prove its claim."""
    g = A.analyze_gap("T2", "admin route returns 401 for anonymous callers",
                      {"exit_code": 0, "output_tail": "Done in 0.4s"})
    assert g.klass == A.DRIFT
    assert g.magnitude == 1
    assert "too loose" in g.note or "not observed" in g.note


def test_forecast_borne_out_is_CONFIRMED():
    g = A.analyze_gap("T1", "12 passed",
                      {"exit_code": 0, "output_tail": "collected 12 items ... 12 passed in 1.2s"})
    assert g.klass == A.CONFIRMED
    assert g.magnitude == 0


def test_no_artifact_is_UNVERIFIED_not_a_pass():
    g = A.analyze_gap("T9", "something", None)
    assert g.klass == A.UNVERIFIED and g.magnitude == -1


def test_parse_forecast_ignores_prose_and_headers():
    text = ("# FORECAST\n\nSome prose about the plan.\n"
            "T1 | the suite reports 12 passed\n"
            "T2 | anonymous GET /admin returns 401\n")
    f = A.parse_forecast(text)
    assert f == {"T1": "the suite reports 12 passed",
                 "T2": "anonymous GET /admin returns 401"}


def test_recalibration_file_records_only_actionable_gaps(tmp_path):
    gaps = [
        A.Gap(task="T1", klass=A.CONFIRMED),
        A.Gap(task="T2", klass=A.DRIFT, predicted="p", observed="o"),
        A.Gap(task="T3", klass=A.REFUTED, predicted="p", observed="boom",
              blocker="EXTERNAL", unblock="retry with backoff"),
        A.Gap(task="T4", klass=A.UNVERIFIED),
    ]
    path = A.write_recalibration(str(tmp_path), gaps, note="step 3")
    body = open(path).read()
    # Match the STRUCTURED marker, never a bare id: the ISO timestamp in the header
    # (2026-08-02T13:47Z) contains "T1" for any hour 10-19, so a substring assertion here
    # passes in the morning and fails in the afternoon. Caught exactly that way.
    assert "**T2 [" in body and "**T3 [" in body
    assert "**T1 [" not in body and "**T4 [" not in body   # nothing to adjust for those
    assert "EXTERNAL" in body and "retry with backoff" in body


def test_write_recalibration_is_a_noop_when_everything_confirmed(tmp_path):
    assert A.write_recalibration(str(tmp_path), [A.Gap(task="T1", klass=A.CONFIRMED)]) == ""
    assert not os.path.exists(tmp_path / "RECALIBRATE.md")


def test_cmd_adapt_end_to_end_verdict_and_summary(tmp_path):
    cdir = tmp_path / "control"
    cdir.mkdir()
    (cdir / "PLAN.md").write_text(_plan(("T1", "x"), ("T2", "x"), ("T3", " ")))
    (cdir / "FORECAST.md").write_text("T1 | 12 passed\nT2 | route returns 401\n")
    gates = cdir / "gates"
    _artifact(gates, "T1", 0, "collected 12 items ... 12 passed")     # CONFIRMED
    _artifact(gates, "T2", 0, "ok")                                    # DRIFT (not observed)
    # T3 has no artifact -> UNVERIFIED
    out = C.cmd_adapt(str(cdir), write=True)
    assert out["verdict"] == "ADAPT"
    assert out["summary"]["counts"][A.CONFIRMED] == 1
    assert out["summary"]["counts"][A.DRIFT] == 1
    assert out["summary"]["counts"][A.UNVERIFIED] == 1
    assert out["summary"]["needs_recalibration"] == 1
    assert os.path.exists(out["recalibrate_path"])


def test_cmd_adapt_is_STEADY_when_reality_matches_the_plan(tmp_path):
    cdir = tmp_path / "control"
    cdir.mkdir()
    (cdir / "PLAN.md").write_text(_plan(("T1", "x")))
    (cdir / "FORECAST.md").write_text("T1 | 12 passed\n")
    _artifact(cdir / "gates", "T1", 0, "12 passed in 0.3s")
    out = C.cmd_adapt(str(cdir))
    assert out["verdict"] == "STEADY"
    assert out["recalibrate_path"] == ""


def test_cmd_adapt_never_runs_a_gate(tmp_path):
    """It must be safe to poll mid-run and safe to call from a task's own GATE: read-only."""
    cdir = tmp_path / "control"
    cdir.mkdir()
    sentinel = tmp_path / "SHOULD_NOT_EXIST"
    (cdir / "PLAN.md").write_text(
        f"- [ ] T1 | a | b | GATE: touch {sentinel} | EXPECT: exit0\n")
    C.cmd_adapt(str(cdir), write=True)
    assert not sentinel.exists()


def test_no_plan_is_NOT_reported_as_steady(tmp_path):
    """A missing/empty PLAN.md must not read as a clean bill of health. Observed live: run
    from the wrong directory, `adapt` printed verdict STEADY with task_count 0 — which looks
    like "all good" and means "nothing here"."""
    cdir = tmp_path / "control"
    cdir.mkdir()
    out = C.cmd_adapt(str(cdir))
    assert out["verdict"] == "NO_PLAN"
    assert out["task_count"] == 0
    assert "hint" in out and "target repo" in out["hint"]
    assert os.path.isabs(out["control_dir"])      # echo where it actually looked


def test_plan_with_only_prose_is_also_NO_PLAN(tmp_path):
    cdir = tmp_path / "control"
    cdir.mkdir()
    (cdir / "PLAN.md").write_text("# PLAN\n\nsome prose, no rows yet\n")
    assert C.cmd_adapt(str(cdir))["verdict"] == "NO_PLAN"


def test_forecast_ids_are_not_restricted_to_the_letter_T():
    """Same hardcoded-`T` bug as the PLAN parser, in the adaptive layer. It is worse here:
    a dropped forecast degrades silently to CONFIRMED, so the DRIFT check stops working
    without ever erroring."""
    f = A.parse_forecast("H0 | the suite reports 22 passed\nSEC-3 | anon GET returns 401\n"
                         "T1 | still works\n")
    assert f == {"H0": "the suite reports 22 passed", "SEC-3": "anon GET returns 401",
                 "T1": "still works"}


def test_missing_forecast_does_not_silently_become_confirmed_for_a_failed_gate():
    """A task with no forecast still REFUTES on a failed gate — the absence of a prediction
    must never launder a failure into a pass."""
    g = A.analyze_gap("H9", "", {"exit_code": 1, "output_tail": "ENOENT: no such file"})
    assert g.klass == A.REFUTED and g.blocker == "MISSING-INFO"
