"""Deterministic gates. In the external-driver model these are plain code:
the gate judges the subagent's work, the subagent never judges itself.

- hash verify (sha256 Measurement: a fact binds to file content, not HEAD)
- Phase 6.5 diff-policy denylist scan (rejects RLS-weakening / dangerous diffs
  even when tests are green)
- run a gate command (from the repo config) -> result.json
"""
import re
import subprocess
from pathlib import Path

from . import state

# Phase 6.5 — ANY added-line hit REJECTS the change regardless of green tests.
# Security-critical, so it lives in code; the repo config may only APPEND via denylist_extra.
DIFF_DENYLIST = [
    r"USING\s*\(\s*true\s*\)",
    r"WITH\s+CHECK\s*\(\s*true\s*\)",
    r"DISABLE\s+ROW\s+LEVEL\s+SECURITY",
    r"DROP\s+POLICY",
    r"ALTER\s+POLICY",
    r"GRANT\b.*\bTO\s+(anon|public|authenticated)\b",
    r"service_role",
    r"gh\s+pr\s+merge",
    r"--auto\b",
    r"git\s+push\s+--force",
]

# Touching any gate/config file -> the change must be AUDIT-ONLY + needs-review:
# a subagent may not author the script that judges it.
CONFIG_TOUCH = re.compile(
    r"(^|/)(package\.json|jest\.config\.[jt]s|playwright\.config\.[jt]s|vite\.config\.[jt]s|[^/]+\.config\.[jt]s)$"
)

# Staging discipline: these must never be staged.
SECRET_SUFFIX = (".env", ".pem", ".key")


def run(cmd, cwd, timeout=1200):
    """Run a subprocess; return (exit_code, stdout, stderr). Output is captured
    into local vars and discarded by the caller -- it never enters any
    persistent context."""
    try:
        p = subprocess.run(
            cmd, cwd=str(cwd), capture_output=True, text=True, timeout=timeout
        )
        return p.returncode, p.stdout, p.stderr
    except subprocess.TimeoutExpired:
        return 124, "", "TIMEOUT after %ss" % timeout
    except FileNotFoundError as e:
        return 127, "", str(e)


# ------------------------------------------------------------ hash gate ----

def verify_hash(repo, rel_path, claimed):
    """Admit only if the file's current sha256 equals the claimed value."""
    actual = state.sha256_file(Path(repo) / rel_path)
    return actual is not None and actual == claimed, actual


# --------------------------------------------------- diff-policy (6.5) -----

def staged_diff(repo):
    rc, out, _ = run(["git", "diff", "--cached", "--unified=0"], repo, timeout=120)
    return out if rc == 0 else ""


def staged_names(repo):
    rc, out, _ = run(["git", "diff", "--cached", "--name-only"], repo, timeout=120)
    return [l.strip() for l in out.splitlines() if l.strip()] if rc == 0 else []


def scan_diff_policy(diff_text, extra=()):
    """Return denylist hits on ADDED lines only. Non-empty -> REJECT. `extra` appends
    the repo config's denylist patterns to the code base list."""
    patterns = DIFF_DENYLIST + list(extra or ())
    hits = []
    for line in diff_text.splitlines():
        if not line.startswith("+") or line.startswith("+++"):
            continue
        body = line[1:]
        for pat in patterns:
            if re.search(pat, body, re.IGNORECASE):
                hits.append({"pattern": pat, "line": body.strip()[:200]})
    return hits


def classify_diff(repo):
    """{loc_changed, files_changed, touches_logic, touches_config, secret_paths}.
    touches_logic=False for comment/whitespace/import-only changes -> trivial."""
    names = staged_names(repo)
    secret = [n for n in names if n.endswith(SECRET_SUFFIX)]
    config = [n for n in names if CONFIG_TOUCH.search(n)]
    diff = staged_diff(repo)
    added, removed, logic = 0, 0, False
    for line in diff.splitlines():
        if line.startswith("+") and not line.startswith("+++"):
            added += 1
            if _is_logic(line[1:]):
                logic = True
        elif line.startswith("-") and not line.startswith("---"):
            removed += 1
    return {
        "loc_changed": added + removed,
        "files_changed": len(names),
        "touches_logic": logic,
        "touches_config": bool(config),
        "secret_paths": secret,
    }


def _is_logic(text):
    s = text.strip()
    if not s:
        return False
    if s.startswith(("//", "#", "/*", "*", "*/")):
        return False
    if re.match(r"^import\s|^export\s+\{[^}]*\}\s+from", s):
        return False  # bare import/re-export reorder
    return True


# ------------------------------------------------------- gate commands -----

def gate_command(kind, cfg):
    """The single gate command for a work kind, from the repo config. RLS uses a static
    predicate (no live DB). Returns an argv list, the sentinel ('rls', None), or None."""
    if kind == "policy":
        return ("rls", None)  # handled by rls_predicate
    return (cfg or {}).get("gate_commands", {}).get(kind)


def run_gate(kind, repo, artifact_dir, classify=None, cfg=None):
    """Run the gate, write result.json, return its path + a parsed verdict dict.

    result.json = {kind, exit_code, normalized_pass, loc_changed, files_changed,
                   touches_logic, ...}. The hash of THIS file is what gets
                   admitted into verified_facts -- a claim becomes proof only
                   after the driver re-runs the gate itself.
    """
    Path(artifact_dir).mkdir(parents=True, exist_ok=True)
    result_path = Path(artifact_dir) / "result.json"
    cmd = gate_command(kind, cfg)
    cls = classify if classify is not None else classify_diff(repo)

    if cmd == ("rls", None):
        verdict = rls_predicate(repo, (cfg or {}).get("denylist_extra", []))
    elif cmd is None:
        verdict = {"exit_code": 2, "normalized_pass": False,
                   "note": "no gate command configured for kind=%s" % kind}
    else:
        rc, out, err = run(cmd, repo)
        # jest/playwright/pytest: exit 0 AND not a zero-test no-op
        empty = bool(re.search(r"No tests found|0 (?:tests|passed)|no tests ran", out + err, re.I))
        verdict = {
            "exit_code": rc,
            "normalized_pass": (rc == 0 and not empty),
            "empty_suite": empty,
            "cmd": " ".join(cmd),
        }

    verdict.update({
        "kind": kind,
        "loc_changed": cls["loc_changed"],
        "files_changed": cls["files_changed"],
        "touches_logic": cls["touches_logic"],
        "touches_config": cls["touches_config"],
    })
    state.save_json(result_path, verdict)
    return str(result_path), verdict


def rls_predicate(repo, extra=()):
    """Static RLS gate: PASS iff the staged diff adds no over-permissive policy
    and no DROP/ALTER POLICY in place. No live DB, ever."""
    diff = staged_diff(repo)
    hits = scan_diff_policy(diff, extra)
    rls_hits = [h for h in hits if not re.search(r"gh |git |--auto|service_role", h["pattern"])]
    return {
        "exit_code": 0 if not rls_hits else 1,
        "normalized_pass": not rls_hits,
        "rls_violations": rls_hits,
        "cmd": "static rls predicate",
    }
