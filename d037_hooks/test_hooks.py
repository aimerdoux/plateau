#!/usr/bin/env python3
"""Offline harness: fake hook payloads + fake transcript. No Claude tokens burned."""
import json, os, shutil, subprocess, sys, time, random, sqlite3
H = os.path.dirname(os.path.abspath(__file__))
def run(script, payload, env=None):
    t = time.time()
    p = subprocess.run([sys.executable, os.path.join(H, script)], input=json.dumps(payload), capture_output=True, text=True,
                       env={**os.environ, **(env or {})})
    return p.stdout, p.stderr, (time.time() - t) * 1000

def fake_calls(seed, n=120):
    random.seed(seed); calls = []
    files = [f"d037_target/mod{i}.py" for i in range(6)]
    for i in range(n):
        k = random.random()
        if k < 0.45: calls.append(("Read", {"file_path": random.choice(files)}, {"output": "def x(): pass\n" * 200}))
        elif k < 0.75:
            f = random.choice(files); name = f"RATE_LIMIT_{i}" if i % 7 == 0 else f"helper_{i}"
            calls.append(("Edit", {"file_path": f, "old_string": "pass", "new_string": f"{name} = 42\ndef {name.lower()}_fn():\n    return {name}"},
                          {"filePath": f, "success": True}))
        elif k < 0.9:
            fail = random.random() < 0.4
            calls.append(("Bash", {"command": "pytest -q d037_target"},
                          {"exitCode": 1 if fail else 0, "output": "FAILED d037_target/test_a.py::test_b - AssertionError: expected 42\n1 failed" if fail else "12 passed"}))
        else: calls.append(("Grep", {"pattern": "RATE_LIMIT"}, {"output": "mod1.py:3"}))
    return calls

def fake_transcript(path, calls):
    with open(path, "w") as f:
        for i, (tool, tin, resp) in enumerate(calls):
            uid = f"toolu_{i:04d}"
            f.write(json.dumps({"type": "assistant", "message": {"role": "assistant", "content": [
                {"type": "text", "text": "IGNORE ME: prose that must not become a node"},
                {"type": "tool_use", "id": uid, "name": tool, "input": tin}]}}) + "\n")
            f.write(json.dumps({"type": "user", "message": {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": uid, "content": "ok"}]}, "toolUseResult": resp}) + "\n")

def check_inject(out, budget, label):
    j = json.loads(out); ctx = j["hookSpecificOutput"]["additionalContext"]
    assert j["hookSpecificOutput"]["hookEventName"] == "SessionStart"
    assert len(ctx) <= budget, f"{label}: {len(ctx)} > {budget}"
    assert ctx.startswith("<d037_index>") and ctx.endswith("</d037_index>")
    assert "[r" in ctx and "IGNORE ME" not in ctx
    return ctx

results = {}
for arm in ("C", "B"):
    root = f"/tmp/d037_{arm}"; shutil.rmtree(root, ignore_errors=True); os.makedirs(root)
    calls = fake_calls(37); base = {"cwd": root, "session_id": "s1", "transcript_path": f"{root}/t.jsonl"}
    fake_transcript(base["transcript_path"], calls)
    times = []
    if arm == "C":
        for tool, tin, resp in calls:
            _, err, ms = run("receipt.py", {**base, "hook_event_name": "PostToolUse", "tool_name": tool, "tool_input": tin, "tool_response": resp})
            assert not err, err; times.append(ms)
        _, err, ms = run("snapshot.py", {**base, "trigger": "auto"}); assert not err; times.append(ms)
        assert os.listdir(f"{root}/.d037/snapshots"), "no snapshot"
    else:
        _, err, ms = run("ledger.py", {**base, "trigger": "auto"}); assert not err, err; times.append(ms)
    c = sqlite3.connect(f"{root}/.d037/index.sqlite")
    n_r = c.execute("SELECT COUNT(*) FROM receipts").fetchone()[0]
    n_sym = c.execute("SELECT COUNT(*) FROM nodes WHERE kind='symbol'").fetchone()[0]
    n_err = c.execute("SELECT COUNT(*) FROM nodes WHERE kind='error'").fetchone()[0]
    assert n_r == len(calls), (n_r, len(calls))
    assert n_sym > 0 and n_err > 0
    # injection at two budgets, must obey both
    for budget in (6000, 1500):
        out, err, ms = run("inject.py", {**base, "source": "compact"}, {"D037_BUDGET_CHARS": str(budget)})
        assert not err, err; times.append(ms)
        ctx = check_inject(out, budget, f"{arm}@{budget}")
    # non-compact SessionStart must inject nothing
    out, _, _ = run("inject.py", {**base, "source": "resume"}); assert json.loads(out) == {}
    results[arm] = dict(receipts=n_r, symbols=n_sym, errors=n_err, max_hook_ms=round(max(times), 1),
                        inject_chars_6000=len(ctx) if False else None)
    results[arm]["sample"] = ctx.splitlines()[2:7]
# B and C must converge to the same store from the same calls (write path is the only difference)
cB = sqlite3.connect("/tmp/d037_B/.d037/index.sqlite"); cC = sqlite3.connect("/tmp/d037_C/.d037/index.sqlite")
q = "SELECT key,kind,degree,last_outcome FROM nodes ORDER BY key"
assert cB.execute(q).fetchall() == cC.execute(q).fetchall(), "B and C stores diverge"
print(json.dumps(results, indent=1)); print("ALL CHECKS PASSED; B≡C store parity OK")
