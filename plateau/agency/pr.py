"""PR emission for write mode. The driver does ALL git/gh here, in code, AFTER the
deterministic gate passes — subagents never get git/gh tools. Allowlisted verbs only:
`git switch -c`, `git commit`, `git push -u origin <branch>`, `gh pr create`. NEVER
`merge`, `--auto`, `push --force`, and never a push to a protected branch. `dry_run`
builds the local branch + PR body for inspection but does NOT push or open a PR.
"""
import re
from pathlib import Path

from . import gate

PROTECTED = {"main", "master", "develop"}
PROTECTED_PREFIXES = ("release/", "prod", "hotfix/")
TIER_NAME = {1: "sec", 2: "core", 3: "ux", 4: "hardening"}


def _slug(s, n=40):
    s = re.sub(r"[^A-Za-z0-9]+", "-", str(s)).strip("-").lower()
    return s[:n] or "fix"


def _branch(item, step):
    return "fix/%s-%d" % (_slug(item["id"]), step)


def _safe_branch(name):
    if name in PROTECTED or name.startswith(PROTECTED_PREFIXES):
        return False
    return bool(re.match(r"^[A-Za-z0-9._/\-]+$", name)) and ".." not in name


def _title(item, agent):
    scope = TIER_NAME.get(item.get("tier"), "qa")
    summary = agent.get("finding") or agent.get("recommendation") or item["id"]
    return "fix(%s): %s" % (scope, str(summary).strip().splitlines()[0][:60])


def _body(item, agent, facts, verdict_path):
    out = ["Automated QA fix by plateau.agency (deterministically gate-verified).", "",
           "**Item:** `%s` (kind %s, tier %s)" % (item["id"], item["kind"], item.get("tier"))]
    if agent.get("finding"):
        out += ["", "**Finding:** %s" % agent["finding"]]
    if agent.get("recommendation"):
        out += ["", "**Fix:** %s" % agent["recommendation"]]
    for e in agent.get("evidence", []):
        out.append("- `%s` — %s: %s" % (e.get("location", "?"), e.get("check", ""), e.get("observed", "")))
    out += ["", "**Changed files (sha256):**"]
    for f in facts:
        if f.get("file"):
            out.append("- `%s` `%s`" % (f["file"], (f.get("sha256") or "")[:23]))
    out += ["", "Gate result: `%s`" % verdict_path, "",
            "_Opened by an automated run; **not merged**. Human review required._"]
    return "\n".join(out)


def open_pr(repo, item, agent, facts, step, artifact_dir, base="main", dry_run=False):
    """The fix files are already STAGED by gate_fix (path-scoped). Commit them on a fresh
    branch off the current HEAD, push, open a PR, and switch back to `base`. Returns
    {opened, number?, url?, branch, dry_run?, reason?}. On any failure the working tree is
    restored to `base`."""
    branch = _branch(item, step)
    if not _safe_branch(branch):
        gate.run(["git", "reset", "-q"], repo)
        return {"opened": False, "reason": "unsafe branch name: %s" % branch}
    title = _title(item, agent)
    body_path = Path(artifact_dir) / "pr_body.md"
    body_path.write_text(_body(item, agent, facts, str(Path(artifact_dir) / "result.json")))

    rc, _, err = gate.run(["git", "switch", "-c", branch], repo)
    if rc != 0:
        gate.run(["git", "reset", "-q"], repo)
        return {"opened": False, "reason": "git switch -c failed: %s" % err[:120], "branch": branch}
    rc, _, err = gate.run(["git", "commit", "-m", title], repo)
    if rc != 0:
        gate.run(["git", "switch", base], repo)
        gate.run(["git", "branch", "-D", branch], repo)
        return {"opened": False, "reason": "git commit failed: %s" % err[:120], "branch": branch}

    if dry_run:
        gate.run(["git", "switch", base], repo)
        return {"opened": False, "dry_run": True, "branch": branch, "title": title,
                "body_path": str(body_path), "base": base,
                "note": "local branch committed for inspection; NOT pushed, no PR opened"}

    rc, _, err = gate.run(["git", "push", "-u", "origin", branch], repo, timeout=180)
    if rc != 0:
        gate.run(["git", "switch", base], repo)
        return {"opened": False, "reason": "git push failed: %s" % err[:160], "branch": branch}
    rc, out, err = gate.run(["gh", "pr", "create", "--base", base, "--head", branch,
                             "--title", title, "--body-file", str(body_path)], repo, timeout=120)
    gate.run(["git", "switch", base], repo)
    if rc != 0:
        return {"opened": False, "reason": "gh pr create failed: %s" % err[:160], "branch": branch}
    url = out.strip().splitlines()[-1] if out.strip() else ""
    number = url.rstrip("/").split("/")[-1] if url else "?"
    return {"opened": True, "number": number, "url": url, "branch": branch}
