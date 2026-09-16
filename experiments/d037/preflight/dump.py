#!/usr/bin/env python3
import sys, json, os
p = json.load(sys.stdin)
with open(os.path.join(p.get("cwd") or os.getcwd(), "payloads.jsonl"), "a") as f: f.write(json.dumps(p) + "\n")
ev = p.get("hook_event_name")
if ev in ("SessionStart", "UserPromptSubmit"):
    print(json.dumps({"hookSpecificOutput": {"hookEventName": ev, "additionalContext": "<pf_marker>PF_TOKEN_9137</pf_marker>"}}))
