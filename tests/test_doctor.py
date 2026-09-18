"""tests/test_doctor.py — owner C5 (docs/harness-0.3/PLAN-step4.md "Tests (C5)").

Per the plan's "Tests (C5)" line: "doctor exits 0 in a temp root with the package
hooks." `HOME` and the project root are both isolated to fresh temp directories, so
this test never installs a hook table anywhere -- `plateau doctor` must therefore
resolve every check to the package-module fallback (`_FALLBACK_COMMANDS` /
"via package module" in each PASS line), never to a real `.claude/settings.json`.
"""

from __future__ import annotations

import os
import subprocess
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _init_temp_git_repo(root):
    subprocess.run(["git", "init", "-q", root], check=True, capture_output=True)
    subprocess.run(["git", "-C", root, "config", "user.email", "doctor-test@plateau.local"],
                   check=True, capture_output=True)
    subprocess.run(["git", "-C", root, "config", "user.name", "plateau doctor test"],
                   check=True, capture_output=True)


def _run_doctor(root, env_extra=None):
    env = dict(os.environ, PYTHONPATH=REPO_ROOT)
    env["HOME"] = str(root.parent / "home")
    os.makedirs(env["HOME"], exist_ok=True)
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        [sys.executable, "-m", "plateau.doctor"],
        cwd=str(root), capture_output=True, text=True, env=env, timeout=60,
    )


def test_doctor_exits_0_in_a_temp_root_with_the_package_hooks(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    _init_temp_git_repo(str(root))

    r = _run_doctor(root)

    assert r.returncode == 0, "stdout:\n{}\nstderr:\n{}".format(r.stdout, r.stderr)
    lines = [l for l in r.stdout.splitlines() if l.strip()]
    assert lines, "plateau doctor printed nothing"
    for line in lines:
        assert line.startswith(("PASS:", "FAIL:", "SKIP:")), "unrecognized doctor line: {!r}".format(line)
    assert not any(line.startswith("FAIL:") for line in lines), "\n".join(lines)

    # no .claude/settings.json exists anywhere findable from this isolated root/HOME
    # -> every one of the four hook checks must fall back to running the package
    # module directly, not an "installed" command.
    scratch_repo_lines = [l for l in lines if "via " in l]
    assert scratch_repo_lines, "\n".join(lines)
    assert all("via package module" in l for l in scratch_repo_lines), "\n".join(lines)

    # the three real-project checks (ledger writable / config resolves / ring status)
    # are present and passed too.
    assert any("ledger is writable" in l for l in lines)
    assert any("config resolves" in l for l in lines)
    assert any("private ring status" in l for l in lines)


def test_doctor_prints_pass_for_all_four_scratch_repo_checks(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    _init_temp_git_repo(str(root))

    r = _run_doctor(root)
    assert r.returncode == 0, r.stderr

    expected_substrings = (
        "a receipt row exists",
        "a snapshot exists",
        "the injection is under budget",
        "a handoff block renders",
    )
    for needle in expected_substrings:
        matches = [l for l in r.stdout.splitlines() if needle in l]
        assert matches, "missing check {!r} in doctor output:\n{}".format(needle, r.stdout)
        assert matches[0].startswith("PASS:"), matches[0]


def test_doctor_never_mutates_the_real_project_it_is_run_from(tmp_path):
    """The four scratch-repo checks execute against a disposable temp git repo, never
    against the project root doctor was invoked from -- running doctor from an empty
    temp root must not create a `.plateau/index.sqlite` full of scratch-repo-only
    fixtures there beyond the ledger `doctor` itself is documented to touch."""
    root = tmp_path / "project"
    root.mkdir()
    _init_temp_git_repo(str(root))

    r = _run_doctor(root)
    assert r.returncode == 0, r.stderr

    # doctor's own real-project checks are allowed to create .plateau/ledger.sqlite
    # (an idempotent CREATE TABLE IF NOT EXISTS -- see the module docstring) but never
    # the scratch repo's own probe file or index.sqlite receipt rows for "doctor-session".
    assert not os.path.isfile(str(root / "doctor_probe.py"))
    index_path = root / ".plateau" / "index.sqlite"
    if index_path.is_file():
        import sqlite3
        conn = sqlite3.connect(str(index_path))
        try:
            row = conn.execute(
                "SELECT COUNT(*) FROM receipts WHERE session_id='doctor-session'"
            ).fetchone()
        finally:
            conn.close()
        assert row[0] == 0
