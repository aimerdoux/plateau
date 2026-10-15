"""Standing regression guard: no verdict-bearing verb may report a false ALL-CLEAR on an
EMPTY control dir (freshly scaffolded, zero PLAN.md task rows).

Three bugs of exactly this class have already shipped: `adapt` returning STEADY on no plan,
`preflight` returning GO on no plan, and a scaffolded-but-still-empty PLAN.md being read as a
real, planned task. Each is the same failure — "nothing is here" and "verified clear" sharing
a verdict. This test scaffolds a control dir the real way (`cmd_init`, never a hand-written
PLAN.md) and then drives every verdict-bearing verb — as a direct function call AND as the
real subprocess CLI — asserting none of them ever returns a success verdict on it, only an
EMPTY-safe one such as NO_PLAN.
"""
import json
import os
import subprocess
import sys

import pytest

from plateau.agency import control as C

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLI = [sys.executable, "-m", "plateau.agency.control"]

# Verdicts that mean "all clear" for SOME non-empty plan state. None of them may ever be
# reported against a control dir that has no plan rows at all.
FALSE_CLEAR = {"DONE", "ALLOW_DONE", "STEADY", "GO"}

# The only verdicts these verbs are allowed to report on a plan-less control dir.
EMPTY_SAFE = {"NO_PLAN"}


def _empty_control_dir(tmp_path):
    """A freshly scaffolded control dir, produced the real way (`cmd_init`), never hand-written.
    `cmd_init`'s PLAN.md template uses `[_]` for its example row, not `[ ]`, precisely so a
    freshly scaffolded dir parses to zero task rows -- this is the direct regression test for
    that design choice, exercised through every verb rather than just `parse_plan`."""
    cdir = str(tmp_path / "control")
    C.cmd_init(cdir)
    return cdir


DIRECT_VERBS = [
    ("status", lambda cdir, root: C.cmd_status(cdir)),
    ("verify", lambda cdir, root: C.cmd_verify(cdir, root)),
    ("verify --strict", lambda cdir, root: C.cmd_verify(cdir, root, strict=True)),
    ("adapt", lambda cdir, root: C.cmd_adapt(cdir)),
    ("adapt --write", lambda cdir, root: C.cmd_adapt(cdir, write=True)),
    ("preflight", lambda cdir, root: C.cmd_preflight(cdir, root)),
]


@pytest.mark.parametrize("label,call", DIRECT_VERBS, ids=[v[0] for v in DIRECT_VERBS])
def test_direct_verb_never_reports_false_clear_on_empty_control_dir(tmp_path, label, call):
    cdir = _empty_control_dir(tmp_path)
    result = call(cdir, str(tmp_path))
    assert result["verdict"] not in FALSE_CLEAR, (
        f"{label} reported {result['verdict']!r} on an EMPTY control dir "
        f"(zero PLAN.md task rows) -- a false ALL-CLEAR"
    )
    assert result["verdict"] in EMPTY_SAFE, (
        f"{label} reported {result['verdict']!r} on an EMPTY control dir; "
        f"expected one of {EMPTY_SAFE}"
    )


def _run_cli(args):
    return subprocess.run(CLI + args, cwd=ROOT, capture_output=True, text=True)


CLI_VERBS = [
    ("status", ["status"]),
    ("verify", ["verify", "--root", "{root}"]),
    ("verify --strict", ["verify", "--root", "{root}", "--strict"]),
    ("adapt", ["adapt"]),
    ("adapt --write", ["adapt", "--write"]),
    ("preflight", ["preflight", "--root", "{root}"]),
]


@pytest.mark.parametrize("label,argv", CLI_VERBS, ids=[v[0] for v in CLI_VERBS])
def test_cli_verb_never_reports_false_clear_on_empty_control_dir(tmp_path, label, argv):
    cdir = _empty_control_dir(tmp_path)
    root = str(tmp_path)
    cmd, rest = argv[0], [a.format(root=root) for a in argv[1:]]
    r = _run_cli([cmd, "--control-dir", cdir] + rest + ["--json"])
    out = json.loads(r.stdout)
    assert out["verdict"] not in FALSE_CLEAR, (
        f"`{' '.join(argv)}` reported {out['verdict']!r} on an EMPTY control dir "
        f"(zero PLAN.md task rows) -- a false ALL-CLEAR. stderr: {r.stderr}"
    )
    assert out["verdict"] in EMPTY_SAFE, (
        f"`{' '.join(argv)}` reported {out['verdict']!r} on an EMPTY control dir; "
        f"expected one of {EMPTY_SAFE}. stderr: {r.stderr}"
    )


def test_scaffolded_plan_template_itself_parses_to_zero_tasks(tmp_path):
    """Guards the scaffolded-reads-as-planned bug directly, independent of any verb: `cmd_init`'s
    own PLAN.md template row must never parse as a real, gated task."""
    cdir = _empty_control_dir(tmp_path)
    text = open(os.path.join(cdir, "PLAN.md")).read()
    assert C.parse_plan(text) == []


def test_adapt_write_leaves_no_recalibrate_trace_on_empty_plan(tmp_path):
    cdir = _empty_control_dir(tmp_path)
    result = C.cmd_adapt(cdir, write=True)
    assert result["recalibrate_path"] == ""
    assert not os.path.exists(os.path.join(cdir, "RECALIBRATE.md"))
