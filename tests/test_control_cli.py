"""Control-loop CLI + helpers — journal append, BLOCKED round-trip, status verdict,
and `python -m plateau.agency.control` exit codes.

Complements test_control_loop.py (parse/gate/signal-binding); this file exercises the
disk-facing helpers (`append_journal`, `write_blocked`, `read_status`) and the CLI verbs
(`init`/`status`/`verify`) both as direct function calls and as the real subprocess a
human or the gatekeeper hook would invoke.
"""
import json
import os
import subprocess
import sys

import pytest

from plateau.agency import control as C

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLI = [sys.executable, "-m", "plateau.agency.control"]


def _run(args, cwd=None):
    # cwd is always ROOT (mirrors test_agency_driver.py): `python -m plateau...` resolves the
    # package via the current working directory, and this repo's `plateau` is not installed
    # into site-packages. All --control-dir/--root args passed in are absolute tmp_path paths,
    # so running from ROOT is transparent to what each test actually checks.
    return subprocess.run(CLI + args, cwd=ROOT, capture_output=True, text=True)


# --------------------------------------------------------------- append_journal ------


def test_append_journal_writes_a_six_field_row(tmp_path):
    line = C.append_journal(str(tmp_path), "T1", "EXECUTE", "wrote file", "ok", "verify")
    path = tmp_path / "JOURNAL.md"
    assert path.is_file()
    content = path.read_text()
    assert content.splitlines()[-1] == line
    fields = line.split(" | ")
    assert len(fields) == 6
    assert fields[1:] == ["T1", "EXECUTE", "wrote file", "ok", "verify"]


def test_append_journal_flattens_embedded_newlines_into_one_row(tmp_path):
    line = C.append_journal(str(tmp_path), "T2", "VERIFY", "a\nmultiline\naction", "result\nline", "next")
    # a newline inside a field can never fork one JOURNAL row into two lines
    assert "\n" not in line
    rows = (tmp_path / "JOURNAL.md").read_text().splitlines()
    assert len(rows) == 1
    assert rows[0] == line


def test_append_journal_appends_across_calls(tmp_path):
    C.append_journal(str(tmp_path), "T1", "EXECUTE", "a", "ok", "next")
    C.append_journal(str(tmp_path), "T2", "EXECUTE", "b", "ok", "next")
    rows = (tmp_path / "JOURNAL.md").read_text().splitlines()
    assert len(rows) == 2
    assert rows[0].split(" | ")[1] == "T1"
    assert rows[1].split(" | ")[1] == "T2"


# --------------------------------------------------------------- write_blocked / round-trip ------


def test_write_blocked_round_trip(tmp_path):
    path = C.write_blocked(
        str(tmp_path),
        "EXTERNAL",
        [("tried x", "failed"), "tried y as a plain string"],
        "ask the operator to unblock",
        ["retry", "escalate", "abandon"],
    )
    assert path == str(tmp_path / "BLOCKED.md")
    text = open(path).read()
    assert "class: EXTERNAL" in text
    assert "1. tried x -> failed" in text
    assert "2. tried y as a plain string" in text
    assert "ask the operator to unblock" in text
    assert "1. retry" in text and "2. escalate" in text and "3. abandon" in text

    # status/gatekeeper key off a "class:" line being present
    status = C.cmd_status(str(tmp_path))
    assert status["blocked"] is True


def test_write_blocked_overwrites_prior_block(tmp_path):
    C.write_blocked(str(tmp_path), "EXTERNAL", ["a"], "u1", ["o1"])
    C.write_blocked(str(tmp_path), "INTERNAL", ["b"], "u2", ["o2"])
    text = (tmp_path / "BLOCKED.md").read_text()
    assert "class: INTERNAL" in text
    assert "class: EXTERNAL" not in text        # a run is blocked on at most one obstacle


# --------------------------------------------------------------- read_status ------


def test_read_status_reports_no_state_when_missing(tmp_path):
    st = C.read_status(str(tmp_path))
    assert st["verdict"] == "NO_STATE"
    assert st["ts"] is None and st["unchecked"] is None


def test_read_status_reads_written_state_json(tmp_path):
    data = {"ts": "2026-01-01T00:00:00Z", "unchecked": ["T1"], "verdict": "BLOCK", "strict": False}
    with open(tmp_path / "STATE.json", "w") as fh:
        json.dump(data, fh)
    st = C.read_status(str(tmp_path))
    assert st["verdict"] == "BLOCK"
    assert st["unchecked"] == ["T1"]
    assert st["_path"] == str(tmp_path / "STATE.json")


def test_read_status_tolerates_corrupt_json(tmp_path):
    (tmp_path / "STATE.json").write_text("{not json")
    st = C.read_status(str(tmp_path))
    assert st["verdict"] == "NO_STATE"


# --------------------------------------------------------------- cmd_* verdicts ------


def test_cmd_init_is_idempotent_and_non_destructive(tmp_path):
    cdir = str(tmp_path / "control")
    r1 = C.cmd_init(cdir)
    assert set(r1["created"]) == {"RECON.md", "PLAN.md", "JOURNAL.md"}
    assert os.path.isdir(os.path.join(cdir, "workers"))

    # hand-edit PLAN.md, then re-run init -> must not clobber it
    marker = "# hand-edited, must survive re-init\n"
    with open(os.path.join(cdir, "PLAN.md"), "w") as fh:
        fh.write(marker)
    r2 = C.cmd_init(cdir)
    assert r2["created"] == []
    assert open(os.path.join(cdir, "PLAN.md")).read() == marker


def test_cmd_status_verdicts(tmp_path):
    cdir = str(tmp_path)
    assert C.cmd_status(cdir)["verdict"] == "NO_PLAN"

    with open(tmp_path / "PLAN.md", "w") as fh:
        fh.write("- [ ] T1 | a | b | GATE: true | EXPECT: exit0\n")
    st = C.cmd_status(cdir)
    assert st["verdict"] == "BLOCK"
    assert st["unchecked"] == ["T1"] and st["checked"] == []

    with open(tmp_path / "PLAN.md", "w") as fh:
        fh.write("- [x] T1 | a | b | GATE: true | EXPECT: exit0\n")
    assert C.cmd_status(cdir)["verdict"] == "ALLOW_DONE"

    C.write_blocked(cdir, "EXTERNAL", ["tried"], "unblock", ["opt"])
    with open(tmp_path / "PLAN.md", "w") as fh:
        fh.write("- [ ] T1 | a | b | GATE: true | EXPECT: exit0\n")
    assert C.cmd_status(cdir)["verdict"] == "ALLOW_BLOCKED"


def test_cmd_verify_default_is_checkbox_scan_not_strict(tmp_path):
    cdir = str(tmp_path)
    # checked box but the underlying gate would actually fail now -> cheap scan still says DONE
    with open(tmp_path / "PLAN.md", "w") as fh:
        fh.write("- [x] T1 | a | b | GATE: false | EXPECT: exit0\n")
    result = C.cmd_verify(cdir, str(tmp_path))
    assert result["strict"] is False
    assert result["verdict"] == "DONE"
    assert result["unchecked"] == []


def test_cmd_verify_strict_reruns_gates_and_catches_regression(tmp_path):
    cdir = str(tmp_path)
    with open(tmp_path / "PLAN.md", "w") as fh:
        fh.write("- [x] T1 | a | b | GATE: false | EXPECT: exit0\n")
    result = C.cmd_verify(cdir, str(tmp_path), strict=True)
    assert result["strict"] is True
    assert result["verdict"] == "BLOCK"
    assert result["unchecked"] == ["T1"]     # the checked box does not save it from strict re-verify


def test_cmd_verify_no_plan(tmp_path):
    result = C.cmd_verify(str(tmp_path), str(tmp_path))
    assert result["verdict"] == "NO_PLAN"
    assert result["unchecked"] == []


# --------------------------------------------------------------- CLI subprocess / exit codes ------


def test_cli_init_exits_zero_and_scaffolds(tmp_path):
    cdir = tmp_path / "control"
    r = _run(["init", "--control-dir", str(cdir), "--json"], tmp_path)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert set(out["created"]) == {"RECON.md", "PLAN.md", "JOURNAL.md"}
    assert (cdir / "PLAN.md").is_file()


def test_cli_status_exits_zero_regardless_of_verdict(tmp_path):
    cdir = tmp_path / "control"
    r = _run(["status", "--control-dir", str(cdir), "--json"], tmp_path)
    assert r.returncode == 0, r.stderr          # status never fails the process, just reports
    assert json.loads(r.stdout)["verdict"] == "NO_PLAN"


def test_cli_verify_exits_zero_and_reports_plain_text_by_default(tmp_path):
    cdir = tmp_path / "control"
    cdir.mkdir()
    (cdir / "PLAN.md").write_text("- [x] T1 | a | b | GATE: true | EXPECT: exit0\n")
    r = _run(["verify", "--control-dir", str(cdir)], tmp_path)
    assert r.returncode == 0, r.stderr
    assert "verdict: DONE" in r.stdout           # plain key: value form, no --json


def test_cli_verify_strict_shells_out_and_reflects_gate_failure_in_output(tmp_path):
    cdir = tmp_path / "control"
    cdir.mkdir()
    (cdir / "PLAN.md").write_text("- [x] T1 | a | b | GATE: false | EXPECT: exit0\n")
    r = _run(["verify", "--control-dir", str(cdir), "--root", str(tmp_path), "--strict", "--json"], tmp_path)
    assert r.returncode == 0, r.stderr           # the CLI process itself exits 0 either way ...
    out = json.loads(r.stdout)
    assert out["verdict"] == "BLOCK"             # ... the DONE/BLOCK verdict is carried in the payload
    assert out["unchecked"] == ["T1"]


def test_cli_missing_subcommand_exits_nonzero():
    r = subprocess.run(CLI, cwd=ROOT, capture_output=True, text=True)
    assert r.returncode != 0
    assert r.stderr.strip() != ""


def test_cli_unknown_subcommand_exits_nonzero():
    r = subprocess.run(CLI + ["bogus"], cwd=ROOT, capture_output=True, text=True)
    assert r.returncode != 0


@pytest.mark.parametrize("cmd", ["init", "status", "verify"])
def test_cli_module_entrypoint_matches_agency_alias(tmp_path, cmd):
    """`python -m plateau.agency` is documented (__main__.py) as an alias for
    `python -m plateau.agency.control`; both must agree on the same verdict."""
    cdir = tmp_path / "control"
    if cmd in ("status", "verify"):
        cdir.mkdir()
        (cdir / "PLAN.md").write_text("- [x] T1 | a | b | GATE: true | EXPECT: exit0\n")
    direct = subprocess.run(CLI + [cmd, "--control-dir", str(cdir), "--json"],
                            cwd=ROOT, capture_output=True, text=True)
    alias = subprocess.run([sys.executable, "-m", "plateau.agency", cmd,
                            "--control-dir", str(cdir), "--json"],
                           cwd=ROOT, capture_output=True, text=True)
    assert direct.returncode == 0 and alias.returncode == 0
    if cmd == "init":
        return  # init is non-destructive/idempotent but touches disk; compared separately above
    assert json.loads(direct.stdout) == json.loads(alias.stdout)
