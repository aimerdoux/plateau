#!/usr/bin/env python3
"""D-038 judge runner: one blind, read-only `claude -p` session per judge view. Writes <token>/judge.json next to the
view. Never sees blind.json, .claude/, .d037/ or CLAUDE.md (run_task.py builds the view without them). stdlib only."""
import argparse, json, os, re, subprocess, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ALLOWED = "Read,Grep,Glob,Bash(git diff:*),Bash(git log:*),Bash(node --check:*),Bash(npm test:*),Bash(bash gate.sh:*)"
DISALLOWED = "Edit,Write,MultiEdit,NotebookEdit,Task,Agent,WebSearch,WebFetch,TodoWrite"
STRIP = ("CLAUDECODE", "CLAUDE_CODE_SESSION_ID", "CLAUDE_CODE_REMOTE_SESSION_ID", "CLAUDE_AUTOCOMPACT_PCT_OVERRIDE")

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--view", required=True, help="<raw>/<run>/<token>/judge_view"); ap.add_argument("--model")
    a = ap.parse_args(); out = os.path.join(os.path.dirname(a.view), "judge.json")
    if os.path.exists(out): sys.exit(f"refuse: {out} exists")
    prompt = open(os.path.join(HERE, "judge_prompt.md")).read().replace("WORKTREE", os.path.abspath(a.view))
    cmd = ["claude", "-p", prompt, "--permission-mode", "default", "--allowedTools", ALLOWED, "--disallowedTools", DISALLOWED, "--output-format", "json"]
    if a.model: cmd += ["--model", a.model]
    env = {k: v for k, v in os.environ.items() if k not in STRIP}
    r = subprocess.run(cmd, cwd=a.view, env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=3600)
    open(os.path.join(os.path.dirname(a.view), "judge_raw.json"), "w").write(r.stdout); open(os.path.join(os.path.dirname(a.view), "judge_err.txt"), "w").write(r.stderr)
    try: text = json.loads(r.stdout).get("result", "")
    except Exception: sys.exit(f"judge produced no JSON result (rc {r.returncode})")
    m = re.search(r"```json\s*(\{.*\})\s*```", text, re.S)
    if not m: sys.exit("judge output has no fenced json block")
    verdict = json.loads(m.group(1)); verdict["_session"] = json.loads(r.stdout).get("session_id"); verdict["_cost_usd"] = json.loads(r.stdout).get("total_cost_usd")
    json.dump(verdict, open(out, "w"), indent=1); print("judge ->", out, "probes graded", len(verdict.get("probes", [])), "cost", verdict["_cost_usd"])

if __name__ == "__main__": main()
