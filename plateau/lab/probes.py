#!/usr/bin/env python3
"""plateau.lab.probes — shadow probes: ask the session, on a disposable fork, whether a
fact the receipt store already knows it discovered is still recoverable from context.

`scan()`, `choose()`, and the two bucket functions below are copied from
`experiments/d038/probes.py` (sealed; never imported — copied, then generalised: this
module drops that experiment's `mandated`-prompt leak filter's task-specific bits and
keeps everything else byte-identical in BEHAVIOUR, per docs/harness-0.3/PLAN-step4.md
"Shadow probes": "Generalize `experiments/d038/probes.py` (copy, then edit; the sealed
file stays)"). `maybe()` is the new entry point a Stop hook calls once per turn; it is a
no-op almost every time it runs — only every `lab.shadow_probe_every_turns` turns, for
the MAIN agent only (PLAN-step4.md: "Never in the main session" was this module's
predecessor's rule inverted for D-038's arm layout; here the rule is the mirror image —
a shadow probe never contaminates a SUBAGENT's isolated context by running one from
inside it, hence main-agent-only), and only when `.plateau/config.toml` sets
`[lab] shadow_probes = true` (default off: "it spends tokens"). Grading is fully
deterministic (`grade()`) — no `claude -p` judge, unlike D-038's blind LLM judge.

Every `claude -p` this module spawns goes through `run_probe(cmd, env)`, a seam tests
monkeypatch; nothing else in this module (or its test suite) invokes a subprocess
directly. `env` is always `plateau.bridge.common.child_env()` (S4-A2) so the forked
probe session never inherits this process's own Claude-Code session identity.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from typing import Any, Dict, List, Optional

from ..bridge import common
from . import ledger as ledger_mod

# --- copied verbatim (behaviour) from experiments/d038/probes.py (sealed reference) ----
# See that file for the original comments; only the docstring above and this banner are
# new. Do not "clean up" divergences from the sealed file without re-reading its
# docstring: PLAN-step4.md requires scan()/choose() to keep the SAME behaviour.

CLASSES = ("read", "exec", "decided")
CODE_EXT = (".py", ".mjs", ".js", ".ts", ".tsx", ".cjs")
SIG_RE = re.compile(r"^\s*(?:export\s+)?(?:async\s+)?(?:def|function)\s+([A-Za-z_$][\w$]*)\s*\(([^)]*)\)", re.M)
ARROW_RE = re.compile(r"^\s*(?:export\s+)?const\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?\(([^)]*)\)\s*=>", re.M)
ENV_RE = re.compile(r"process\.env\.([A-Z][A-Z0-9_]+)|os\.environ(?:\.get\(|\[)\s*['\"]([A-Z][A-Z0-9_]+)['\"]")
ERR_RE = re.compile(r"^.*(?:\bError\b|\bException\b|Traceback|ENOENT|EACCES|npm ERR!|\bFAILED\b|^not ok).*$", re.M)
ERR_STRICT_RE = re.compile(r"^(?:\S*Error\b.*|Traceback.*|npm ERR!.*|FAILED .*|not ok .*|.*\bError: .*)$", re.M)
PYTEST_FAIL_RE = re.compile(r"^FAILED\s+(\S+)", re.M)
NODE_FAIL_RE = re.compile(r"^not ok \d+ - (.+)$", re.M)
COUNT_RE = re.compile(r"(\d+) (passed|failed|vulnerabilit(?:y|ies))|^# (pass|fail) (\d+)$", re.M)
DEF_RE = re.compile(r"^[ \t]*(?:export\s+)?(?:default\s+)?(?:async\s+)?(class|function|def)\s+([A-Za-z_$][\w$]*)"
                    r"|^[ \t]*(?:export\s+)?(const|let)\s+([A-Za-z_$][\w$]*)\s*=|^([A-Z][A-Z0-9_]{2,})\s*=", re.M)
WORD = {"class": "class", "function": "function", "def": "function", "const": "constant", "let": "variable", "": "module-level constant"}
LAG_BUCKETS = ((0, 20_000), (20_000, 60_000), (60_000, float("inf")))


def lag_bucket(t):
    return next(i for i, (lo, hi) in enumerate(LAG_BUCKETS) if lo <= t < hi)


def comp_bucket(n):
    return min(n, 2)


def _rel(p, root):
    return os.path.relpath(p, root) if root and p.startswith(root) else p


def _short(s, n=140):
    s = (s or "").strip()
    return s if len(s) <= n else s[:n] + "…"


def _facts_read(res, tin, root):
    f = (res.get("file") or {}) if isinstance(res, dict) else {}
    path = f.get("filePath") or tin.get("file_path") or ""
    text = f.get("content") or ""
    rel = _rel(path, root)
    out = []
    if not path.endswith(CODE_EXT) or not text:
        return out
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
    pat = tin.get("pattern", "")
    lines = []
    if isinstance(res, dict):
        c = res.get("content") or ""
        lines = [l for l in str(c).splitlines() if re.match(r"^[^:\s]+:\d+:", l)]
    if not lines:
        return []
    first = lines[0]
    m = re.match(r"^([^:]+):(\d+):", first)
    rel = _rel(m.group(1), root)
    return [dict(cls="read", kind="grep_hit", key=("read", "grep", pat), file=rel,
                 q=f"Your earlier search for the pattern `{pat}` found its first match in which file and on which line? Answer `file:line`.",
                 expected=f"{rel}:{m.group(2)}")]


def _facts_bash(res, tin):
    cmd = _short(tin.get("command", ""), 100)
    out = []
    if isinstance(res, str):
        if "requires approval" in res or "denied" in res.lower():
            out.append(dict(cls="exec", kind="denied", key=("exec", "denied", cmd), file="",
                            q=f"What was the outcome when you ran `{cmd}`: did it run, or was it blocked? One line.", expected="blocked: command requires approval (not run)"))
        return out
    if not isinstance(res, dict):
        return out
    so, se = str(res.get("stdout") or ""), str(res.get("stderr") or "")
    for m in PYTEST_FAIL_RE.finditer(so + "\n" + se):
        out.append(dict(cls="exec", kind="failed_test", key=("exec", "failed_test", cmd), file="",
                        q=f"When you ran `{cmd}`, which test failed? Give the test name as printed.", expected=m.group(1)))
        break
    for m in NODE_FAIL_RE.finditer(so + "\n" + se):
        out.append(dict(cls="exec", kind="failed_test", key=("exec", "failed_test", cmd), file="",
                        q=f"When you ran `{cmd}`, which test failed? Give the test name as printed.", expected=m.group(1)))
        break
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
    line = text[start:].split("\n")[0]
    if word in ("constant", "variable", "module-level constant"):
        m = re.search(r"=\s*(.+?)\s*;?\s*$", line)
        return ("with value `" + _short(m.group(1), 60) + "`") if m else ""
    if word == "class":
        m = re.search(r"(?:extends|\()\s*([A-Za-z_$][\w$.]*)", line)
        if m:
            return "that extends `" + m.group(1) + "`"
    for l in text[start:].split("\n")[1:]:
        if l.strip():
            return "whose first body line is `" + _short(l.strip(), 60) + "`"
    return ""


def _facts_edit(res, tin, root, tool):
    out = []
    if not isinstance(res, dict):
        return out
    path = res.get("filePath") or tin.get("file_path") or ""
    rel = _rel(path, root)
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
        g = m.groups()
        word = WORD[g[0] or g[2] or ""]
        name = g[1] or g[3] or g[4]
        if not name or name in old_names or len(name) < 3:
            continue
        anchor = _anchor(new, m.start(), word)
        if not anchor or name in anchor:
            continue
        out.append(dict(cls="decided", kind="name", key=("decided", "name", rel, name), file=rel,
                        q=f"In `{rel}` you added a new {word} {anchor}. What did you name it?", expected=name))
    return out


def scan(tp, root=None, mandated=""):
    """Return {'facts': [...], 'pos': cumulative new tokens, 'compactions': n, 'lines': n}.
    See `experiments/d038/probes.py::scan` (sealed reference) for the full contract;
    behaviour is unchanged here."""
    facts = {}
    order = []
    pending = {}
    seen_ids = set()
    cum = 0
    comp = 0
    n = 0
    with open(tp) as fh:
        for i, l in enumerate(fh, 1):
            n = i
            try:
                j = json.loads(l)
            except Exception:
                continue
            t = j.get("type")
            m = j.get("message") or {}
            c = m.get("content")
            if t == "system" and j.get("subtype") == "compact_boundary":
                comp += 1
                continue
            if t == "assistant":
                u = m.get("usage")
                if u and m.get("id") not in seen_ids:
                    seen_ids.add(m.get("id"))
                    cum += u.get("input_tokens", 0) + u.get("cache_creation_input_tokens", 0) + u.get("output_tokens", 0)
                for b in (c or []) if isinstance(c, list) else []:
                    if b.get("type") == "tool_use":
                        pending[b["id"]] = (b.get("name"), b.get("input") or {})
                continue
            if t == "user" and isinstance(c, list) and c and c[0].get("type") == "tool_result":
                tool, tin = pending.pop(c[0].get("tool_use_id"), (None, {}))
                res = j.get("toolUseResult")
                found = []
                if tool == "Read":
                    found = _facts_read(res, tin, root)
                elif tool == "Grep":
                    found = _facts_grep(res, tin, root)
                elif tool == "Bash":
                    found = _facts_bash(res, tin)
                elif tool in ("Edit", "Write", "MultiEdit"):
                    found = _facts_edit(res, tin, root, tool)
                for f in found:
                    k = f["key"]
                    if mandated and f["expected"] and re.search(r"(?<![\w/.\-])" + re.escape(f["expected"]) + r"(?![\w/.\-])", mandated):
                        continue
                    if k in facts:
                        facts[k].update(last_line=i, last_pos=cum, last_comp=comp)
                        continue
                    f.update(id=f"f{len(order)+1:03d}", first_line=i, pos=cum, comp=comp, last_line=i, last_pos=cum, last_comp=comp,
                             target_bucket=len(order) % 3)
                    f["key"] = "|".join(map(str, k))
                    facts[k] = f
                    order.append(k)
    return {"facts": [facts[k] for k in order], "pos": cum, "compactions": comp, "lines": n}


def choose(facts, probed, cur_pos, cur_comp, n, counts=None, final=False):
    """Pick up to `n` unprobed facts that have reached their target lag bucket (any
    fact when `final`), filling the least-populated (lag bucket, class) cell first,
    oldest first. See `experiments/d038/probes.py::choose` (sealed reference);
    behaviour unchanged here."""
    counts = counts if counts is not None else {}
    cands = [f for f in facts if f["id"] not in probed and (final or lag_bucket(cur_pos - f["last_pos"]) >= f["target_bucket"])]
    picked = []
    while cands and len(picked) < n:
        def score(f):
            lb = lag_bucket(cur_pos - f["last_pos"])
            return (counts.get((lb, f["cls"]), 0), sum(v for (b, _), v in counts.items() if b == lb), f["last_pos"])
        f = min(cands, key=score)
        cands.remove(f)
        picked.append(f)
        lb = lag_bucket(cur_pos - f["last_pos"])
        counts[(lb, f["cls"])] = counts.get((lb, f["cls"]), 0) + 1
    return picked


# --- new in this module (PLAN-step4.md "Shadow probes") -------------------------------

PROBE_PREFIX = "Answer with just the fact, no explanation, no tool calls: "

# Every tool disallowed: a shadow probe must never touch the filesystem or spend a turn
# doing anything but answering from context. Mirrors the shape of
# `experiments/d038/run_task.py`'s `PROBE_DISALLOWED` (sealed reference; not imported).
PROBE_DISALLOWED_TOOLS = (
    "Bash,Read,Edit,Write,MultiEdit,NotebookEdit,Grep,Glob,Task,Agent,"
    "WebSearch,WebFetch,TodoWrite,LSP"
)


def run_probe(cmd: List[str], env: Dict[str, str]) -> str:
    """Actually spawn the `claude -p ...` probe fork and return its stdout. This is the
    ONLY place this module ever starts a subprocess; tests monkeypatch this function
    (never `subprocess` itself) so no test run ever spends real tokens. `env` is always
    `plateau.bridge.common.child_env()`'s result — see the module docstring."""
    proc = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=120)
    return proc.stdout or ""


def _normalize(s: Optional[str]) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


_FILE_LINE_RE = re.compile(r"([^\s:]+):(\d+)\s*$")


def grade(expected: str, answer: str) -> str:
    """Deterministic grading (PLAN-step4.md "Shadow probes"): `exact` on normalized
    equality; `fuzzy` on token overlap >= 0.6 (relative to the expected answer's own
    tokens) OR a `file:line` answer within one line of the expected `file:line`;
    `wrong` otherwise."""
    expected = expected or ""
    exp_n = _normalize(expected)
    ans_n = _normalize(answer)
    if exp_n and exp_n == ans_n:
        return "exact"

    m_exp = _FILE_LINE_RE.search(expected.strip())
    if m_exp:
        m_ans = _FILE_LINE_RE.search((answer or "").strip())
        if m_ans and m_ans.group(1) == m_exp.group(1) and abs(int(m_ans.group(2)) - int(m_exp.group(2))) <= 1:
            return "fuzzy"

    exp_tokens = set(re.findall(r"[a-z0-9_]+", exp_n))
    if exp_tokens:
        ans_tokens = set(re.findall(r"[a-z0-9_]+", ans_n))
        overlap = len(exp_tokens & ans_tokens) / len(exp_tokens)
        if overlap >= 0.6:
            return "fuzzy"
    return "wrong"


def _extract_answer(raw_stdout: str) -> str:
    """The probe fork's answer text out of its `--output-format json` envelope, or the
    raw stdout verbatim if it is not JSON (a stub runner in tests may return plain
    text)."""
    if not raw_stdout:
        return ""
    try:
        envelope = json.loads(raw_stdout.strip())
    except Exception:
        return raw_stdout
    if isinstance(envelope, dict):
        return str(envelope.get("result") or envelope.get("text") or "")
    return raw_stdout


def _q_hash(q: str) -> str:
    return hashlib.sha256((q or "").encode("utf-8")).hexdigest()[:16]


def _shadow_probes_enabled(root: str) -> bool:
    """`.plateau/config.toml`'s `[lab] shadow_probes` flag (default false: "it spends
    tokens" — PLAN-step4.md). Lives in `.plateau/config.toml`, not `bridge.toml`, so it
    is NOT part of `plateau.bridge.config.BridgeConfig.lab` (that dataclass only ever
    merges `bridge.toml`-family files); this reads the same `.plateau/config.toml` file
    `plateau.bridge.config.load` already reads for its `[bridge] enabled` flag,
    directly, mirroring `plateau.bridge.handoff`'s pattern of being its own small
    reader rather than reaching into another owner's module for one field."""
    path = os.path.join(root, ".plateau", "config.toml")
    if not os.path.isfile(path):
        return False
    try:
        with open(path, "rb") as f:
            raw = f.read()
        text = raw.decode("utf-8")
    except OSError:
        return False
    try:
        import tomllib as _tomllib  # Python >= 3.11
        cfg = _tomllib.loads(text)
    except ImportError:
        from ..bridge import _toml
        try:
            cfg = _toml.loads(text)
        except Exception:
            return False
    except Exception:
        return False
    lab = cfg.get("lab") if isinstance(cfg, dict) else None
    return bool(isinstance(lab, dict) and lab.get("shadow_probes") is True)


def _turn_count(conn, session_id: str) -> int:
    return conn.execute("SELECT COUNT(*) FROM turns WHERE session_id=?", (session_id,)).fetchone()[0]


def _already_probed_hashes(conn, session_id: str) -> set:
    rows = conn.execute("SELECT DISTINCT q_hash FROM probes WHERE session_id=?", (session_id,)).fetchall()
    return {r[0] for r in rows}


def maybe(payload: Dict[str, Any], cfg: Any) -> Optional[Dict[str, Any]]:
    """Called from the Stop hook once per turn. A no-op unless ALL of: this is the
    MAIN agent (never a subagent — a shadow probe forks the MAIN session), shadow
    probes are turned on for this project, the turn count (from the store's `turns`
    table) is a positive multiple of `cfg.lab.get("shadow_probe_every_turns", 4)`, the
    transcript has an unprobed fact ready at this lag, and the fork actually runs.
    Returns the probe row dict it wrote to the ledger's `probes` table, or `None` when
    it did nothing — this never raises (a probe is a diagnostic, never something that
    should break a session)."""
    try:
        payload = payload or {}
        agent = common.agent_of(payload)
        if agent != "main":
            return None
        root = common.root(payload)
        if not _shadow_probes_enabled(root):
            return None

        session_id = payload.get("session_id", "")
        transcript_path = payload.get("transcript_path", "")
        if not session_id or not transcript_path or not os.path.isfile(transcript_path):
            return None

        every_n = int((getattr(cfg, "lab", None) or {}).get("shadow_probe_every_turns", 4) or 4)
        if every_n <= 0:
            return None

        store_conn = common.db(root)
        try:
            turn_n = _turn_count(store_conn, session_id)
        finally:
            store_conn.close()
        if turn_n <= 0 or turn_n % every_n != 0:
            return None

        scanned = scan(transcript_path, root)
        facts = scanned["facts"]
        if not facts:
            return None

        lconn = ledger_mod.db(root)
        try:
            probed_hashes = _already_probed_hashes(lconn, session_id)
            probed_ids = {f["id"] for f in facts if _q_hash(f["q"]) in probed_hashes}
            picked = choose(facts, probed_ids, scanned["pos"], scanned["compactions"], 1)
            if not picked:
                return None
            fact = picked[0]

            cmd = [
                "claude", "-p", PROBE_PREFIX + fact["q"],
                "--resume", session_id, "--fork-session",
                "--disallowedTools", PROBE_DISALLOWED_TOOLS,
                "--output-format", "json",
            ]
            raw = run_probe(cmd, common.child_env())
            answer = _extract_answer(raw)
            verdict = grade(fact["expected"], answer)

            lag_tokens = scanned["pos"] - fact["last_pos"]
            compactions_crossed = scanned["compactions"] - fact["last_comp"]
            q_hash = _q_hash(fact["q"])
            ledger_mod.record_probe(
                lconn, session_id, turn_n, fact["cls"], fact["kind"],
                lag_tokens, compactions_crossed, verdict, q_hash,
            )
            return {
                "session_id": session_id, "turn": turn_n, "cls": fact["cls"], "kind": fact["kind"],
                "lag_tokens": lag_tokens, "compactions_crossed": compactions_crossed,
                "verdict": verdict, "q_hash": q_hash,
            }
        finally:
            lconn.close()
    except Exception as e:
        try:
            common.log(common.root(payload or {}), f"probe ERROR {e!r}")
        except Exception:
            pass
        return None


def main(argv: Optional[List[str]] = None) -> None:
    """Optional direct entry point (the Stop hook is expected to call `maybe()`
    itself, per PLAN-step4.md — see the module docstring); reads the hook payload from
    stdin and the resolved `plateau.bridge.config.BridgeConfig` for its root, for
    parity with every other `plateau.bridge.*`/`plateau.lab.*` hook-shaped module.
    Prints nothing; never raises."""
    from ..bridge import config as bridge_config
    _ = sys.argv[1:] if argv is None else argv  # accepted for parity; unused (see docstring)
    payload = common.read_payload()
    root = common.root(payload)
    try:
        cfg = bridge_config.load(root, payload.get("session_id", ""))
    except Exception:
        cfg = None
    maybe(payload, cfg)


if __name__ == "__main__":
    main()
