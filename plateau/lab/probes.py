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

Every `claude -p` this module spawns for GRADING goes through `run_probe(cmd, env)`, a
blocking helper; the actual fork this hook fires off, though, goes through `spawn_probe`
(see "new in this module" below) — a SEPARATE, fully-detached process, because the Stop
hook that calls `maybe()` has a 10s timeout and a real `claude -p --resume ... --fork-
session` probe routinely takes much longer than that. Nothing in this module (or its
test suite) invokes a subprocess any other way. `env` is always
`plateau.bridge.common.child_env()` (S4-A2) so the forked probe session never inherits
this process's own Claude-Code session identity.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import time
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

PROBES_DIR_REL = os.path.join(".plateau", "probes")

PROBE_PREFIX = "Answer with just the fact, no explanation, no tool calls: "

# Every tool disallowed: a shadow probe must never touch the filesystem or spend a turn
# doing anything but answering from context. Mirrors the shape of
# `experiments/d038/run_task.py`'s `PROBE_DISALLOWED` (sealed reference; not imported).
PROBE_DISALLOWED_TOOLS = (
    "Bash,Read,Edit,Write,MultiEdit,NotebookEdit,Grep,Glob,Task,Agent,"
    "WebSearch,WebFetch,TodoWrite,LSP"
)


def run_probe(cmd: List[str], env: Dict[str, str]) -> str:
    """BLOCKING: run the `claude -p ...` probe fork to completion and return its
    stdout. Only ever called from inside the ALREADY-DETACHED finalizer process
    (`_finalize_spec`, spawned by `spawn_probe`) -- never from `maybe()` itself, which
    runs inside the Stop hook's own 10s-timeout process and must return immediately.
    `env` is always `plateau.bridge.common.child_env()`'s result — see the module
    docstring."""
    proc = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=120)
    return proc.stdout or ""


def spawn_probe(cmd: List[str], env: Dict[str, str], stdout_path: str, stderr_path: str) -> Any:
    """The seam `maybe()` uses to fire off the finalizer (`_finalize_spec`, run as
    `python3 -m plateau.lab.probes --run-spec <path>`) as a FULLY DETACHED child
    (`start_new_session=True`, its own process group, stdin closed) so the Stop hook's
    10s timeout is never at risk even though a real `claude -p --fork-session` probe
    can take much longer than that — the finalizer keeps running under init/its own
    session leader after this process (and the Stop hook that called it) has already
    exited. stdout/stderr land in files under `.plateau/probes/` for observability
    (docs/harness-0.3/PLAN-step4.md's task: "poll for ... the probe output files").
    Tests monkeypatch THIS function (never `subprocess` itself) to a stub that records
    the call and spawns nothing, so a test run never spends a real token. Returns the
    `subprocess.Popen` handle; `maybe()` never waits on it."""
    stdout_f = open(stdout_path, "wb")
    stderr_f = open(stderr_path, "wb")
    try:
        return subprocess.Popen(
            cmd, env=env, stdin=subprocess.DEVNULL, stdout=stdout_f, stderr=stderr_f,
            start_new_session=True, close_fds=True,
        )
    finally:
        # The child already holds its own dup'd copies of these fds by the time Popen()
        # returns; closing the parent's copies here is the ordinary daemonizing pattern
        # (and avoids leaking fds in the Stop-hook process for however long it lives on).
        stdout_f.close()
        stderr_f.close()


def _finalize_spec(spec_path: str) -> None:
    """The finalizer (docs/harness-0.3/PLAN-step4.md item 7: "a small finalizer ...
    must record the graded result in the ledger"): runs entirely inside the DETACHED
    process `spawn_probe` started. Reads the small JSON spec `maybe()` wrote, blocks on
    the real probe fork via `run_probe` (safe here — this process has no Stop-hook
    timeout of its own), grades the answer, writes the `probes` ledger row, and leaves
    a status JSON file (`.plateau/probes/<...>.json`) recording the verdict and the
    fork's own `session_id` (a DIFFERENT session id from the main one, since the probe
    ran with `--fork-session`) for anything polling the filesystem rather than the
    ledger. Never raises past this function -- errors are logged, not propagated (there
    is no hook waiting on this process's exit code)."""
    try:
        with open(spec_path, encoding="utf-8") as f:
            spec = json.load(f)
    except Exception:
        return
    root = spec.get("root", "")
    try:
        raw = run_probe(spec["cmd"], dict(os.environ))
        answer = _extract_answer(raw)
        verdict = grade(spec["expected"], answer)

        fork_session_id: Optional[str] = None
        try:
            envelope = json.loads(raw.strip())
            if isinstance(envelope, dict):
                fork_session_id = envelope.get("session_id")
        except Exception:
            pass

        lconn = ledger_mod.db(root)
        try:
            ledger_mod.record_probe(
                lconn, spec["session_id"], spec["turn"], spec["cls"], spec["kind"],
                spec["lag_tokens"], spec["compactions_crossed"], verdict, spec["q_hash"],
            )
        finally:
            lconn.close()

        status = {
            "session_id": spec["session_id"], "fork_session_id": fork_session_id,
            "turn": spec["turn"], "cls": spec["cls"], "kind": spec["kind"],
            "verdict": verdict, "answer": answer, "expected": spec["expected"],
            "q_hash": spec["q_hash"], "done": True,
        }
        status_path = spec.get("status_path")
        if status_path:
            with open(status_path, "w", encoding="utf-8") as f:
                json.dump(status, f, indent=2)
        try:
            common.log(root, "probe q={} verdict={} fork={}".format(
                spec["q_hash"], verdict, fork_session_id))
        except Exception:
            pass
    except Exception as e:
        try:
            common.log(root, "probe ERROR {!r}".format(e))
        except Exception:
            pass


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
        finally:
            lconn.close()

        lag_tokens = scanned["pos"] - fact["last_pos"]
        compactions_crossed = scanned["compactions"] - fact["last_comp"]
        q_hash = _q_hash(fact["q"])
        cmd = [
            "claude", "-p", PROBE_PREFIX + fact["q"],
            "--resume", session_id, "--fork-session",
            "--disallowedTools", PROBE_DISALLOWED_TOOLS,
            "--output-format", "json",
        ]

        # Never block here (this runs inside the Stop hook's own 10s-timeout process):
        # write a small JSON spec for the finalizer and spawn it fully detached (see
        # `spawn_probe`/`_finalize_spec` above) -- it runs `cmd`, grades the answer, and
        # writes the `probes` ledger row itself, on its own time.
        probes_dir = os.path.join(root, PROBES_DIR_REL)
        os.makedirs(probes_dir, exist_ok=True)
        base = "{:.6f}_{}".format(time.time(), q_hash).replace(".", "_")
        stdout_path = os.path.join(probes_dir, base + ".out")
        stderr_path = os.path.join(probes_dir, base + ".err")
        status_path = os.path.join(probes_dir, base + ".json")
        spec_path = os.path.join(probes_dir, base + ".spec.json")

        spec = {
            "root": root, "session_id": session_id, "turn": turn_n,
            "cls": fact["cls"], "kind": fact["kind"], "expected": fact["expected"],
            "lag_tokens": lag_tokens, "compactions_crossed": compactions_crossed,
            "q_hash": q_hash, "cmd": cmd, "status_path": status_path,
        }
        with open(spec_path, "w", encoding="utf-8") as f:
            json.dump(spec, f)

        finalize_cmd = [sys.executable, "-m", "plateau.lab.probes", "--run-spec", spec_path]
        proc = spawn_probe(finalize_cmd, common.child_env(), stdout_path, stderr_path)
        try:
            common.log(root, "probe spawn q={} kind={}".format(q_hash, fact["kind"]))
        except Exception:
            pass
        return {
            "session_id": session_id, "turn": turn_n, "cls": fact["cls"], "kind": fact["kind"],
            "lag_tokens": lag_tokens, "compactions_crossed": compactions_crossed,
            "q_hash": q_hash, "spawned": True, "pid": getattr(proc, "pid", None),
            "spec_path": spec_path, "status_path": status_path,
        }
    except Exception as e:
        try:
            common.log(common.root(payload or {}), f"probe ERROR {e!r}")
        except Exception:
            pass
        return None


def main(argv: Optional[List[str]] = None) -> None:
    """Two shapes:

    `python3 -m plateau.lab.probes --run-spec <path>` — the finalizer's own entry
    point, invoked by `spawn_probe` as a fully detached subprocess (see `_finalize_spec`
    above); never reads stdin, never touches the hook payload.

    Anything else (including no args): the optional direct hook-shaped entry point
    (the Stop hook is expected to call `plateau.bridge.lift`, which calls `maybe()`
    itself, per PLAN-step4.md — see the module docstring) — reads the hook payload from
    stdin and the resolved `plateau.bridge.config.BridgeConfig` for its root, for
    parity with every other `plateau.bridge.*`/`plateau.lab.*` hook-shaped module.
    Prints nothing; never raises."""
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] == "--run-spec" and len(argv) > 1:
        _finalize_spec(argv[1])
        return

    from ..bridge import config as bridge_config
    payload = common.read_payload()
    root = common.root(payload)
    try:
        cfg = bridge_config.load(root, payload.get("session_id", ""))
    except Exception:
        cfg = None
    maybe(payload, cfg)


if __name__ == "__main__":
    main()
