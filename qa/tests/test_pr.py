"""PR-layer guards (pure) + local dry-run git mechanics. The live push/create path is
operator-gated and not exercised here."""
import subprocess

from plateau_qa import pr


def _git(args, cwd):
    return subprocess.run(["git"] + args, cwd=str(cwd), capture_output=True, text=True)


def test_safe_branch_rejects_protected_and_injection():
    assert pr._safe_branch("fix/policy-1-3") is True
    for bad in ("main", "master", "develop", "release/1.0", "prod-deploy", "hotfix/x",
                "fix/../escape", "fix/weird;rm -rf", "fix/a b"):
        assert pr._safe_branch(bad) is False, bad


def test_branch_name():
    item = {"id": "policy:1_x.sql", "kind": "policy", "tier": 1}
    assert pr._branch(item, 3) == "fix/policy-1-x-sql-3"


def test_title_scope_and_summary():
    item = {"id": "edge_fn:pay-anyone", "kind": "edge_fn", "tier": 1}
    t = pr._title(item, {"finding": "missing authz on withdraw"})
    assert t.startswith("fix(sec):") and "authz" in t


def test_body_lists_hashes_and_no_merge_note():
    item = {"id": "m", "kind": "module", "tier": 2}
    facts = [{"file": "src/a.ts", "sha256": "sha256:abcd"}]
    b = pr._body(item, {"finding": "f", "evidence": []}, facts, "result.json")
    assert "src/a.ts" in b and "not merged" in b.lower()


def test_open_pr_dry_run_local_branch(tmp_path):
    repo = tmp_path / "r"
    repo.mkdir()
    _git(["init", "-b", "main"], repo)
    _git(["config", "user.email", "t@t"], repo)
    _git(["config", "user.name", "t"], repo)
    (repo / "README").write_text("base")
    _git(["add", "README"], repo)
    _git(["commit", "-m", "init"], repo)
    (repo / "fix.txt").write_text("patched")          # the "fix", staged like gate_fix does
    _git(["add", "fix.txt"], repo)
    art = tmp_path / "art"
    art.mkdir()
    res = pr.open_pr(str(repo), {"id": "module:fix.txt", "kind": "module", "tier": 2},
                     {"finding": "x", "evidence": []},
                     [{"file": "fix.txt", "sha256": "sha256:z"}], 5, str(art),
                     base="main", dry_run=True)
    assert res["dry_run"] is True and res["opened"] is False
    assert "fix/module-fix-txt-5" in _git(["branch"], repo).stdout      # branch committed
    assert _git(["rev-parse", "--abbrev-ref", "HEAD"], repo).stdout.strip() == "main"
    assert not (repo / "fix.txt").exists()             # committed to branch, off main worktree
    assert (art / "pr_body.md").exists()
