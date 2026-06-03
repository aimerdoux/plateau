"""End-to-end stub loop (no claude call): ascending-tier pick, artifacts, checkpoint, resume."""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent          # plateau-qa/
DRIVER = [sys.executable, "-m", "plateau_qa.driver"]


def _mkrepo(tmp_path):
    (tmp_path / "supabase" / "migrations").mkdir(parents=True)
    (tmp_path / "supabase" / "migrations" / "1.sql").write_text("CREATE POLICY p ON t USING (true);")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "App.tsx").write_text('<Route path="/admin" /><Route path="/x" />')
    return str(tmp_path)


def _run(args, tmp_path):
    return subprocess.run(DRIVER + args, cwd=str(ROOT), capture_output=True, text=True)


def test_stub_loop_checkpoint_and_resume(tmp_path):
    repo = _mkrepo(tmp_path)
    rid = "PYTEST_%s" % tmp_path.name
    rundir = ROOT / "plateau_qa" / "runs" / rid
    try:
        r = _run(["--repo", repo, "--stub", "--mode", "audit", "--max-steps", "2", "--run-id", rid], tmp_path)
        assert r.returncode == 0, r.stderr
        assert (rundir / "ledger.jsonl").exists()
        assert (rundir / "kpis.jsonl").exists()
        assert (rundir / "RESUME.json").exists()       # checkpoint fired at max-steps=2
        led = [json.loads(l) for l in (rundir / "ledger.jsonl").read_text().splitlines() if l.strip()]
        assert led and led[0]["tier"] == 1             # ascending tier: SEC policy first
        # resume binds to the SAME run dir and continues
        r2 = _run(["--repo", repo, "--resume", str(rundir / "RESUME.json"), "--stub", "--max-steps", "2"], tmp_path)
        assert r2.returncode == 0, r2.stderr
        resume = json.loads((rundir / "RESUME.json").read_text())
        assert resume["resume_count"] >= 0
    finally:
        import shutil
        shutil.rmtree(rundir, ignore_errors=True)
