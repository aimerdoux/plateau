"""The runner's retry budget (control-loop E4), driven by a mock worker.

Observed live and NOT caught by any test: the autoloop re-dispatched the SAME failing task
16 consecutive times — ~25 minutes of compute, zero progress — because the runner never
implemented the retry_budget the protocol has always specified. A stuck task must become a
classified BLOCKER and let the run continue, not spin.
"""
import os
import shutil
import subprocess
import sys

import pytest

from plateau.agency import autoloop as AL

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
pytestmark = pytest.mark.skipif(not shutil.which("bash"), reason="bash required")


def _setup(tmp_path, rows, worker_script):
    cdir = tmp_path / "control"
    (cdir / "gates").mkdir(parents=True)
    (cdir / "TASK.md").write_text("# MISSION\n- do the thing\n")
    (cdir / "PLAN.md").write_text("\n".join(rows) + "\n")
    (cdir / "FORECAST.md").write_text("")
    binp = tmp_path / "claude"
    binp.write_text("#!/usr/bin/env bash\n" + worker_script + "\n")
    binp.chmod(0o755)
    return cdir, binp


def test_a_permanently_failing_task_is_blocked_not_retried_forever(tmp_path):
    rows = ["- [ ] A1 | never works | a.txt | GATE: false | EXPECT: exit0",
            "- [ ] A2 | works fine | b.txt | GATE: true | EXPECT: exit0"]
    cdir, binp = _setup(tmp_path, rows, 'echo "worker did nothing"')
    stats = AL.run(str(cdir), str(tmp_path), hours=0.2, claude_bin=str(binp),
                   worker_timeout=30, retry_budget=3)
    # A1 burns exactly its budget, then blocks — it does NOT consume the whole run
    assert stats["blocked"] == 1, stats
    assert stats["refuted"] == 3, stats            # 3 attempts, not 16
    body = (cdir / "BLOCKED.md").read_text()
    assert "class:" in body and "A1" in body
    # and the run moved ON to the task that can pass
    assert stats["passed"] == 1, stats


def test_a_task_that_recovers_clears_its_attempt_count(tmp_path):
    """A flake must not permanently consume budget: a pass resets the counter."""
    flip = tmp_path / "flip"
    rows = [f"- [ ] B1 | flaky | c.txt | GATE: test -f {flip} | EXPECT: exit0"]
    # worker creates the file on its 2nd invocation, so attempt 1 fails and attempt 2 passes
    cdir, binp = _setup(tmp_path, rows,
                        f'n=$(cat {tmp_path}/n 2>/dev/null || echo 0); n=$((n+1)); '
                        f'echo $n > {tmp_path}/n; [ "$n" -ge 2 ] && touch {flip}; true')
    stats = AL.run(str(cdir), str(tmp_path), hours=0.2, claude_bin=str(binp),
                   worker_timeout=30, retry_budget=3)
    assert stats["passed"] == 1 and stats["blocked"] == 0, stats
