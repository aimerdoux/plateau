#!/usr/bin/env python3
"""D-038 probe extractor and context-position tracker. Reads a Claude Code transcript JSONL (live or sealed) and returns
facts the worker DISCOVERED (class read: from Read/Grep results; class exec: from Bash results) or DECIDED (class
decided: names it introduced via Edit/Write), each with a one-line question, the expected answer, the transcript line,
and the context position (cumulative new tokens) and compaction count at which the fact last entered the context.
Also the probe scheduler. Deterministic; stdlib only. Never asks anything itself."""
import json, re, os
CLASSES = ("read", "exec", "decided")
CODE_EXT = (".py", ".mjs", ".js", ".ts", ".tsx", ".cjs")
SIG_RE = re.compile(r"^\s*(?:export\s+)?(?:async\s+)?(?:def|function)\s+([A-Za-z_$][\w$]*)\s*\(([^)]*)\)", re.M)
ARROW_RE = re.compile(r"^\s*(?:export\s+)?const\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?\(([^)]*)\)\s*=>", re.M)
ENV_RE = re.compile(r"process\.env\.([A-Z][A-Z0-9_]+)|os\.environ(?:\.get\(|\[)\s*['\"]([A-Z][A-Z0-9_]+)['\"]")
ERR_RE = re.compile(r"^.*(?:\bError\b|\bException\b|Traceback|ENOENT|EACCES|npm ERR!|\bFAILED\b|^not ok).*$", re.M)   # stderr: loose
ERR_STRICT_RE = re.compile(r"^(?:\S*Error\b.*|Traceback.*|npm ERR!.*|FAILED .*|not ok .*|.*\bError: .*)$", re.M)             # stdout: strict
PYTEST_FAIL_RE = re.compile(r"^FAILED\s+(\S+)", re.M)
NODE_FAIL_RE = re.compile(r"^not ok \d+ - (.+)$", re.M)
COUNT_RE = re.compile(r"(\d+) (passed|failed|vulnerabilit(?:y|ies))|^# (pass|fail) (\d+)$", re.M)
DEF_RE = re.compile(r"^[ \t]*(?:export\s+)?(?:default\s+)?(?:async\s+)?(class|function|def)\s+([A-Za-z_$][\w$]*)"
                    r"|^[ \t]*(?:export\s+)?(const|let)\s+([A-Za-z_$][\w$]*)\s*=|^([A-Z][A-Z0-9_]{2,})\s*=", re.M)
WORD = {"class": "class", "function": "function", "def": "function", "const": "constant", "let": "variable", "": "module-level constant"}
LAG_BUCKETS = ((0, 20_000), (20_000, 60_000), (60_000, float("inf")))
def lag_bucket(t): return next(i for i, (lo, hi) in enumerate(LAG_BUCKETS) if lo <= t < hi)
def comp_bucket(n): return min(n, 2)
def _rel(p, root): return os.path.relpath(p, root) if root and p.startswith(root) else p
def _short(s, n=140): s = (s or "").strip(); return s if len(s) <= n else s[:n] + "…"

def _facts_read(res, tin, root):
    f = (res.get("file") or {}) if isinstance(res, dict) else {}
    path = f.get("filePath") or tin.get("file_path") or ""; text = f.get("content") or ""
    rel = _rel(path, root); out = []
    if not path.endswith(CODE_EXT) or not text: return out
    sigs = [(n, p) for n, p in SIG_RE.findall(text) + ARROW_RE.findall(text) if p.strip()]
    for n, p in sigs[:2]:
        out.append(dict(cls="read", kind="signature", key=("read", "signature", rel, n), file=rel,
                        q=f"In `{rel}`, what is the exact parameter list of `{n}`? Answer with the parentheses content only.",
                        expected=re.sub(r"\s+", " ", p.strip())))
    env = sorted({a or b for a, b in ENV_RE.findall(text)})
    if 1 <= len(env) <= 8:
        out.append(dict(cls="read", kind="env_keys", key=("read", "env", rel), file=rel,
                        q=f"Which environment variable names does `{rel}` read? List them, comma-separated.", expected=", ".join(env)))
    return out

def _facts_grep(res, tin, root):
    pat = tin.get("pattern", ""); lines = []
    if isinstance(res, dict):
        c = res.get("content") or ""; lines = [l for l in str(c).splitlines() if re.match(r"^[^:\s]+:\d+:", l)]
    if not lines: return []
    first = lines[0]; m = re.match(r"^([^:]+):(\d+):", first); rel = _rel(m.group(1), root)
    return [dict(cls="read", kind="grep_hit", key=("read", "grep", pat), file=rel,
                 q=f"Your earlier search for the pattern `{pat}` found its first match in which file and on which line? Answer `file:line`.",
                 expected=f"{rel}:{m.group(2)}")]

def _facts_bash(res, tin):
    cmd = _short(tin.get("command", ""), 100); out = []
    if isinstance(res, str):
        if "requires approval" in res or "denied" in res.lower():
            out.append(dict(cls="exec", kind="denied", key=("exec", "denied", cmd), file="",
                            q=f"What was the outcome when you ran `{cmd}`: did it run, or was it blocked? One line.", expected="blocked: command requires approval (not run)"))
        return out
    if not isinstance(res, dict): return out
    so, se = str(res.get("stdout") or ""), str(res.get("stderr") or "")
    for m in PYTEST_FAIL_RE.finditer(so + "\n" + se):
        out.append(dict(cls="exec", kind="failed_test", key=("exec", "failed_test", cmd), file="",
                        q=f"When you ran `{cmd}`, which test failed? Give the test name as printed.", expected=m.group(1))); break
    for m in NODE_FAIL_RE.finditer(so + "\n" + se):
        out.append(dict(cls="exec", kind="failed_test", key=("exec", "failed_test", cmd), file="",
                        q=f"When you ran `{cmd}`, which test failed? Give the test name as printed.", expected=m.group(1))); break
    cm = COUNT_RE.search(so + "\n" + se)
    if cm:
        n, what = (cm.group(1), cm.group(2)) if cm.group(1) else (cm.group(4), "tests " + cm.group(3))
        out.append(dict(cls="exec", kind="count", key=("exec", "count", cmd), file="",
                        q=f"When you ran `{cmd}`, how many `{what}` did its summary report? Answer with the number.", expected=n))
    em = ERR_RE.search(se) or ERR_STRICT_RE.search(so)
    if em and not cm:
        out.append(dict(cls="exec", kind="error_line", key=("exec", "error", cmd), file="",
                        q=f"When you ran `{cmd}`, what was the first error line in its output? Quote it as closely as you can.", expected=_short(em.group(0))))
    return out

def _anchor(text, start, word):
    """A non-leaking hint for a definition: a constant's value, a class's parent, else the first body line."""
    line = text[start:].split("\n")[0]
    if word in ("constant", "variable", "module-level constant"):
        m = re.search(r"=\s*(.+?)\s*;?\s*$", line); return ("with value `" + _short(m.group(1), 60) + "`") if m else ""
    if word == "class":
        m = re.search(r"(?:extends|\()\s*([A-Za-z_$][\w$.]*)", line)
        if m: return "that extends `" + m.group(1) + "`"
    for l in text[start:].split("\n")[1:]:
        if l.strip(): return "whose first body line is `" + _short(l.strip(), 60) + "`"
    return ""

def _facts_edit(res, tin, root, tool):
    out = []
    if not isinstance(res, dict): return out
    path = res.get("filePath") or tin.get("file_path") or ""; rel = _rel(path, root)
    if tool == "Write" and res.get("type") == "create":
        first = next((l.strip() for l in str(res.get("content") or "").splitlines() if l.strip()), "")
        if first and os.path.basename(rel) not in first and len(rel) < 120:
            out.append(dict(cls="decided", kind="new_file", key=("decided", "file", rel), file=rel,
                            q=f"You created a new file whose first non-empty line is `{_short(first, 80)}`. What is its path (relative to the worktree)?", expected=rel))
        new, old = str(res.get("content") or ""), ""
    else:
        new, old = str(res.get("newString") or tin.get("new_string") or ""), str(res.get("oldString") or tin.get("old_string") or "")
    old_names = {n for m in DEF_RE.finditer(old) for n in m.groups() if n and n not in ("class", "function", "def", "const", "let")}
    for m in DEF_RE.finditer(new):
        g = m.groups(); word = WORD[g[0] or g[2] or ""]; name = g[1] or g[3] or g[4]
        if not name or name in old_names or len(name) < 3: continue
        anchor = _anchor(new, m.start(), word)
        if not anchor or name in anchor: continue                  # the hint must not leak the answer
        out.append(dict(cls="decided", kind="name", key=("decided", "name", rel, name), file=rel,
                        q=f"In `{rel}` you added a new {word} {anchor}. What did you name it?", expected=name))
    return out

def scan(tp, root=None, mandated=""):
    """Return {'facts': [...], 'pos': cumulative new tokens, 'compactions': n, 'lines': n}. Facts are deduplicated by key;
    first_line/pos/comp record the first sighting, last_line/last_pos/last_comp the most recent (a re-read refreshes).
    `mandated` = the concatenated task prompts: a fact whose expected answer occurs there was dictated, not discovered."""
    facts = {}; order = []; pending = {}; seen_ids = set(); cum = 0; comp = 0; n = 0
    for i, l in enumerate(open(tp), 1):
        n = i
        try: j = json.loads(l)
        except Exception: continue
        t = j.get("type"); m = j.get("message") or {}; c = m.get("content")
        if t == "system" and j.get("subtype") == "compact_boundary": comp += 1; continue
        if t == "assistant":
            u = m.get("usage")
            if u and m.get("id") not in seen_ids:
                seen_ids.add(m.get("id")); cum += u.get("input_tokens", 0) + u.get("cache_creation_input_tokens", 0) + u.get("output_tokens", 0)
            for b in (c or []) if isinstance(c, list) else []:
                if b.get("type") == "tool_use": pending[b["id"]] = (b.get("name"), b.get("input") or {})
            continue
        if t == "user" and isinstance(c, list) and c and c[0].get("type") == "tool_result":
            tool, tin = pending.pop(c[0].get("tool_use_id"), (None, {})); res = j.get("toolUseResult")
            found = []
            if tool == "Read": found = _facts_read(res, tin, root)
            elif tool == "Grep": found = _facts_grep(res, tin, root)
            elif tool == "Bash": found = _facts_bash(res, tin)
            elif tool in ("Edit", "Write", "MultiEdit"): found = _facts_edit(res, tin, root, tool)
            for f in found:
                k = f["key"]
                if mandated and f["expected"] and re.search(r"(?<![\w/.\-])" + re.escape(f["expected"]) + r"(?![\w/.\-])", mandated): continue
                if k in facts: facts[k].update(last_line=i, last_pos=cum, last_comp=comp); continue
                f.update(id=f"f{len(order)+1:03d}", first_line=i, pos=cum, comp=comp, last_line=i, last_pos=cum, last_comp=comp,
                         target_bucket=len(order) % 3); f["key"] = "|".join(map(str, k))   # facts are held back until they reach their target lag bucket
                facts[k] = f; order.append(k)
    return {"facts": [facts[k] for k in order], "pos": cum, "compactions": comp, "lines": n}

def choose(facts, probed, cur_pos, cur_comp, n, counts=None, final=False):
    """Pick up to n unprobed facts that have reached their target lag bucket (any fact when final), filling the
    least-populated (lag bucket, class) cell first, oldest first. counts = {(lag_bucket, cls): probes so far}; updated in place."""
    counts = counts if counts is not None else {}
    cands = [f for f in facts if f["id"] not in probed and (final or lag_bucket(cur_pos - f["last_pos"]) >= f["target_bucket"])]
    picked = []
    while cands and len(picked) < n:
        def score(f):
            lb = lag_bucket(cur_pos - f["last_pos"]); return (counts.get((lb, f["cls"]), 0), sum(v for (b, _), v in counts.items() if b == lb), f["last_pos"])
        f = min(cands, key=score); cands.remove(f); picked.append(f)
        lb = lag_bucket(cur_pos - f["last_pos"]); counts[(lb, f["cls"])] = counts.get((lb, f["cls"]), 0) + 1
    return picked

if __name__ == "__main__":
    import sys
    r = scan(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
    print(json.dumps({"pos": r["pos"], "compactions": r["compactions"], "n_facts": len(r["facts"]),
                      "by_class": {c: sum(f["cls"] == c for f in r["facts"]) for c in CLASSES}}, indent=1))
    for f in r["facts"][:12]: print(f["id"], f["cls"], f["kind"], f["first_line"], f["pos"], "|", f["q"], "=>", f["expected"])
