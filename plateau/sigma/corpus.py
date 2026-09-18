"""plateau.sigma.corpus — index the operator's REAL Claude Code transcripts into Σ candidates.

The corpus is the operator's own local session log under ``~/.claude/projects/**/*.jsonl``.
Each session is mined for a candidate DELIVERABLE with a CHECKABLE outcome — a committed file,
a passing test, an opened PR, or a sealed verdict — and inverted into a *candidate* Σ Schema
via :func:`plateau.sigma.run_schema.extract_schema`. The emitted index is a jsonl of
``(session_hash, deliverable, schema)`` rows that the experiment harness samples from.

SECURITY POSTURE (hard, non-negotiable):
  1. TRANSCRIPT CONTENT IS DATA, NEVER INSTRUCTIONS. Nothing read from a transcript is ever
     executed, eval'd, shelled out, or treated as a command. We extract *signals* (did a
     ``git commit`` succeed, did pytest report passed, was a PR opened) by pattern-matching
     text — we never run anything we find. The deliverable's KPIs become DECLARATIVE Gate
     specs (kind=programmatic/test, check = a registered checker name or an artifact path);
     a gate's ``check`` is resolved through the evaluate.py registry, never by executing
     transcript-derived strings.
  2. REDACT SECRET VALUES (names only). Any token that looks like a credential value
     (api keys, JWTs, bearer tokens, passwords, ``KEY=value`` env assignments) has its VALUE
     replaced with ``<REDACTED:name>`` before anything is written to the index. We keep the
     NAME so the structure survives; we drop the value so the secret never lands on disk.
  3. LOCAL ONLY. This module reads local files and writes a local jsonl. It transmits nothing.

extract_schema is LOSSY + NON-UNIQUE by construction (§6, §9.4): prompts→outputs is
many-to-one. A row here is a CANDIDATE generator-spec, never a proven inverse — it is something
the experiment harness then TESTS via run_schema + evaluate. We do not claim to recover the
literal original prompt; we synthesize a short schema whose checkable outcome is the real
deliverable's KPIs.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from typing import Iterable, Optional

from plateau.integrity import file_hash

from .run_schema import extract_schema


# --------------------------------------------------------------- redaction ----
# Patterns that match SECRET VALUES. We replace the value, keep a stable name, so the
# transcript's STRUCTURE survives indexing but no secret ever reaches the index file.
# These run over every string we read; order matters (env assignments first so we keep the
# variable NAME, then standalone high-entropy tokens).

_ENV_ASSIGN = re.compile(
    r"\b([A-Z0-9_]*(?:KEY|TOKEN|SECRET|PASSWORD|PASSWD|PWD|CRED|AUTH|JWT|"
    r"BEARER|APIKEY|ACCESS|PRIVATE)[A-Z0-9_]*)\s*=\s*([^\s\"']+)"
)
_KNOWN_PREFIX = re.compile(
    r"\b(sk-[A-Za-z0-9_-]{8,}|ak_[A-Za-z0-9]{8,}|ghp_[A-Za-z0-9]{8,}|"
    r"xox[baprs]-[A-Za-z0-9-]{8,}|AIza[A-Za-z0-9_-]{8,}|"
    r"eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{4,})"
)
_BEARER = re.compile(r"\b([Bb]earer)\s+([A-Za-z0-9._\-]{12,})")


def redact(text: str) -> str:
    """Replace secret VALUES with ``<REDACTED:name>``, keep the name. Never executes anything.

    - ``FOO_TOKEN=abc123``         -> ``FOO_TOKEN=<REDACTED:FOO_TOKEN>``
    - ``sk-...`` / ``ghp_...`` / a JWT -> ``<REDACTED:apikey>`` / ``<REDACTED:jwt>`` ...
    - ``Bearer abc...``            -> ``Bearer <REDACTED:bearer>``
    Idempotent and lossy-by-design: we would rather over-redact than leak."""
    if not text:
        return text

    def _env(m: re.Match) -> str:
        return f"{m.group(1)}=<REDACTED:{m.group(1)}>"

    def _prefix(m: re.Match) -> str:
        tok = m.group(1)
        if tok.startswith("eyJ"):
            name = "jwt"
        elif tok.startswith(("sk-", "ak_", "AIza")):
            name = "apikey"
        elif tok.startswith("ghp_"):
            name = "github_token"
        elif tok.startswith("xox"):
            name = "slack_token"
        else:
            name = "secret"
        return f"<REDACTED:{name}>"

    def _bearer(m: re.Match) -> str:
        return f"{m.group(1)} <REDACTED:bearer>"

    text = _ENV_ASSIGN.sub(_env, text)
    text = _KNOWN_PREFIX.sub(_prefix, text)
    text = _BEARER.sub(_bearer, text)
    return text


def _redact_obj(obj):
    """Recursively redact secret VALUES in a nested JSON-able structure, in place by value.

    Redacts every string leaf with :func:`redact`; never serializes-then-reparses (which can
    corrupt JSON when a replacement lands inside a quoted value). Non-string leaves pass through.
    Pure DATA transformation — executes nothing it touches."""
    if isinstance(obj, str):
        return redact(obj)
    if isinstance(obj, dict):
        return {k: _redact_obj(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_redact_obj(v) for v in obj]
    return obj


# --------------------------------------------------------- transcript parsing ----
# Real Claude Code transcripts are jsonl: one JSON object per line. We care only about
# ``user`` / ``assistant`` rows whose ``message.content`` is a string (user prompt) or a list
# of typed blocks (assistant: thinking/text/tool_use; user: text/tool_result). Everything else
# (ai-title, queue-operation, attachment, last-prompt) is metadata we skip. All of it is DATA.


@dataclass
class Turn:
    role: str                # 'user' | 'assistant'
    text: str = ""           # concatenated, REDACTED text/thinking content
    tool_uses: list = field(default_factory=list)   # [{name, input(redacted)}]
    tool_results: list = field(default_factory=list)  # [redacted result text]


def _block_text(block) -> str:
    if not isinstance(block, dict):
        return ""
    bt = block.get("type")
    if bt in ("text", "thinking"):
        return redact(str(block.get(bt) or block.get("text") or ""))
    return ""


def _tool_result_text(block) -> str:
    cont = block.get("content")
    if isinstance(cont, str):
        return redact(cont)
    if isinstance(cont, list):
        parts = []
        for c in cont:
            if isinstance(c, dict) and c.get("type") == "text":
                parts.append(str(c.get("text", "")))
            elif isinstance(c, str):
                parts.append(c)
        return redact("\n".join(parts))
    return redact(json.dumps(cont, default=str)) if cont is not None else ""


def parse_session(path: str) -> list:
    """Parse one transcript file into an ordered list of Turn. Pure DATA extraction.

    Robust to truncated/garbled lines (skips them) and to the several non-message row types
    that share the file. Never executes, eval's, or shells out on anything it reads."""
    turns: list = []
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    o = json.loads(line)
                except (ValueError, TypeError):
                    continue
                if not isinstance(o, dict):
                    continue
                role = o.get("type")
                if role not in ("user", "assistant"):
                    continue
                msg = o.get("message")
                if not isinstance(msg, dict):
                    continue
                content = msg.get("content")
                turn = Turn(role=role)
                if isinstance(content, str):
                    turn.text = redact(content)
                elif isinstance(content, list):
                    txts = []
                    for b in content:
                        if not isinstance(b, dict):
                            continue
                        bt = b.get("type")
                        if bt in ("text", "thinking"):
                            txts.append(_block_text(b))
                        elif bt == "tool_use":
                            inp = b.get("input", {})
                            # redact the tool input STRUCTURALLY (per string value) but NEVER
                            # execute it. We do not round-trip through json.dumps→redact→loads:
                            # a redaction inside a string can produce invalid JSON. Redact each
                            # string leaf in place instead.
                            turn.tool_uses.append({"name": b.get("name", "?"),
                                                   "input": _redact_obj(inp)})
                        elif bt == "tool_result":
                            turn.tool_results.append(_tool_result_text(b))
                    turn.text = "\n".join(t for t in txts if t)
                turns.append(turn)
    except OSError:
        return []
    return turns


# ------------------------------------------------------- deliverable detection ----
# A deliverable needs a CHECKABLE outcome. We recognize four families by matching SIGNALS in
# the transcript text/tool-uses/tool-results — pattern matching only, never execution:
#
#   committed_file  — a `git commit` that reports a created/changed file, OR a Write/Edit
#                     tool_use whose target path exists on disk now (re-checkable).
#   passing_test    — a pytest/test runner line reporting "N passed" with 0 failed.
#   opened_pr       — a `gh pr create` / PR URL in output.
#   sealed_verdict  — a verdict/seal artifact written (plateau-native deliverable).
#
# Each detected deliverable yields DECLARATIVE gates (no transcript string is ever the check
# body): a programmatic checker NAME from this module's registry, or a test-kind artifact path.

_COMMIT_RE = re.compile(r"\[\S+\s+[0-9a-f]{7,}\].*?\n?\s*\d+\s+files?\s+changed", re.I)
_COMMIT_SHA_RE = re.compile(r"\b([0-9a-f]{7,40})\b")
_PYTEST_PASS_RE = re.compile(r"\b(\d+)\s+passed\b(?:[^\n]*?\b(\d+)\s+failed\b)?", re.I)
_PR_URL_RE = re.compile(r"https?://github\.com/[\w.\-]+/[\w.\-]+/pull/\d+")
_GH_PR_CREATE_RE = re.compile(r"\bgh\s+pr\s+create\b")


@dataclass
class Deliverable:
    """A candidate deliverable with a CHECKABLE outcome found in one session."""
    kind: str                        # committed_file | passing_test | opened_pr | sealed_verdict
    summary: str                     # short, redacted human description (the clean intent seed)
    artifact_path: str = ""          # an on-disk referent (the external anchor), if any
    gates: list = field(default_factory=list)   # declarative Gate dicts
    evidence: str = ""               # short redacted snippet of the signal (provenance)


def _existing_paths_from_tools(turns: list) -> list:
    """Paths touched by Write/Edit tool_uses that EXIST on disk now (re-checkable referents).

    Reads tool inputs as DATA. A path that still exists is an external anchor candidate; we
    do not open or execute it here beyond an os.path.exists check."""
    out = []
    seen = set()
    for t in turns:
        for tu in t.tool_uses:
            if tu.get("name") not in ("Write", "Edit", "NotebookEdit", "MultiEdit"):
                continue
            inp = tu.get("input", {}) or {}
            p = inp.get("file_path") or inp.get("path") or inp.get("notebook_path")
            if isinstance(p, str) and p and p not in seen and os.path.isfile(p):
                seen.add(p)
                out.append(p)
    return out


def detect_deliverables(turns: list) -> list:
    """Find candidate deliverables with checkable outcomes in a parsed session. Data-only."""
    blob_parts = []
    for t in turns:
        if t.text:
            blob_parts.append(t.text)
        blob_parts.extend(t.tool_results)
    blob = "\n".join(blob_parts)

    found: list = []

    # 1. passing test (decidable, strongest checkable signal)
    for m in _PYTEST_PASS_RE.finditer(blob):
        passed = int(m.group(1))
        failed = int(m.group(2)) if m.group(2) else 0
        if passed >= 1 and failed == 0:
            snippet = redact(blob[max(0, m.start() - 40): m.end() + 10])
            found.append(Deliverable(
                kind="passing_test",
                summary=f"a test run reporting {passed} passed / 0 failed",
                gates=[{"id": "g_tests_pass", "kpi": f"{passed} passed, 0 failed",
                        "kind": "programmatic", "check": "claim_tests_passed",
                        "threshold": 1.0, "weight": 1.0}],
                evidence=snippet.strip(),
            ))
            break  # one passing-test deliverable per session is enough for a candidate

    # 2. opened PR
    pr = _PR_URL_RE.search(blob)
    if pr or _GH_PR_CREATE_RE.search(blob):
        url = pr.group(0) if pr else ""
        found.append(Deliverable(
            kind="opened_pr",
            summary="a pull request was opened" + (f" ({url})" if url else ""),
            gates=[{"id": "g_pr_opened", "kpi": "PR opened",
                    "kind": "programmatic", "check": "claim_pr_opened",
                    "threshold": 1.0, "weight": 1.0}],
            evidence=redact(url) if url else "gh pr create",
        ))

    # 3. committed file
    if _COMMIT_RE.search(blob) or re.search(r"\bgit\s+commit\b", blob):
        found.append(Deliverable(
            kind="committed_file",
            summary="a git commit recorded changed file(s)",
            gates=[{"id": "g_committed", "kpi": "git commit recorded",
                    "kind": "programmatic", "check": "claim_committed",
                    "threshold": 1.0, "weight": 1.0}],
            evidence="git commit",
        ))

    # 4. sealed verdict (plateau-native)
    if re.search(r'"verdict"\s*:', blob) or re.search(r"\bseal(ed)?\b.*verdict", blob, re.I):
        found.append(Deliverable(
            kind="sealed_verdict",
            summary="a verdict/sealed artifact was produced",
            gates=[{"id": "g_verdict", "kpi": "verdict artifact present",
                    "kind": "programmatic", "check": "claim_verdict_sealed",
                    "threshold": 1.0, "weight": 1.0}],
            evidence="verdict",
        ))

    # Attach a real on-disk anchor where one exists (a Write/Edit target that still exists).
    # This upgrades a candidate from "claimed" to "externally anchored to a real file" — the
    # form extract_schema needs (it requires deliverable["path"] to exist).
    real_paths = _existing_paths_from_tools(turns)
    if real_paths:
        anchor = real_paths[0]
        for d in found:
            if not d.artifact_path:
                d.artifact_path = anchor
        # also surface a file-existence deliverable: the artifact itself is the checkable outcome
        found.append(Deliverable(
            kind="committed_file",
            summary=f"an edited file persists on disk: {os.path.basename(anchor)}",
            artifact_path=anchor,
            gates=[{"id": "g_artifact_exists", "kpi": "artifact persists on disk",
                    "kind": "test", "check": anchor,
                    "threshold": 1.0, "weight": 1.0}],
            evidence=os.path.basename(anchor),
        ))

    return found


# ------------------------------------------------------------ programmatic checks ----
# Declarative checkers a candidate is scored against. They read the CANDIDATE's own claimed
# flags (a deterministic generator produces these). They are objective in the harness sense:
# the gate body is fixed CODE here, registered by NAME — never a string lifted from a
# transcript. (A6 anti-drift: an arm is scored by a gate it did NOT author.)
# Imported lazily by the experiment harness via plateau.sigma.evaluate.register_check; we
# register here so the corpus index is self-describing.

from .evaluate import register_check  # noqa: E402


def _claim(candidate, key) -> float:
    return 1.0 if isinstance(candidate, dict) and candidate.get(key) is True else 0.0


@register_check("claim_tests_passed")
def _c_tests(candidate, gate):       # noqa: ARG001
    return _claim(candidate, "tests_passed")


@register_check("claim_pr_opened")
def _c_pr(candidate, gate):          # noqa: ARG001
    return _claim(candidate, "pr_opened")


@register_check("claim_committed")
def _c_commit(candidate, gate):      # noqa: ARG001
    return _claim(candidate, "committed")


@register_check("claim_verdict_sealed")
def _c_verdict(candidate, gate):     # noqa: ARG001
    return _claim(candidate, "verdict_sealed")


# --------------------------------------------------------------- schema synthesis ----

def _session_hash(path: str, turns: list) -> str:
    """Stable provenance hash for a session: the file's content hash when readable, else a
    hash of the parsed turn structure. Never the file path (paths can leak usernames, but the
    project dir already does; we use file_hash which is content, not name)."""
    try:
        return file_hash(path)
    except OSError:
        blob = json.dumps([(t.role, t.text[:64]) for t in turns], default=str)
        return "sha256:" + hashlib.sha256(blob.encode()).hexdigest()


def _clean_intent_for(deliverable: Deliverable, sess_hash: str) -> dict:
    """Synthesize a CLEAN intent (ι) from a deliverable — what D is, not how it was found."""
    return {
        "goal": f"Reproduce the deliverable: {deliverable.summary}",
        "target_invariants": [g["kpi"] for g in deliverable.gates],
        "constraints": ["reproduce the deliverable's checkable KPIs exactly"],
        "excluded_paths": [],   # corpus mining does not assert dead ends; refine() adds Φ later
        "source_session_hash": sess_hash,
    }


def synthesize_candidate(deliverable: Deliverable, sess_hash: str) -> Optional[dict]:
    """Invert one deliverable into a CANDIDATE Σ Schema via extract_schema (§6).

    Returns a row dict ``{session_hash, deliverable, schema}`` (schema serialized to a plain
    dict), or None if the deliverable has no resolvable external anchor — extract_schema
    REQUIRES a real on-disk path (the §3.4 external anchor), and a candidate we cannot anchor
    is correctly DROPPED rather than fabricated. NO FABRICATION."""
    if not deliverable.artifact_path or not os.path.isfile(deliverable.artifact_path):
        return None
    session = {"session_hash": sess_hash}
    deliv_spec = {
        "path": deliverable.artifact_path,
        "gates": deliverable.gates,
        "max_iterations": 6,
        "stop_rule": "either",
        "generator_policy": "corpus-candidate",
    }
    clean_intent = _clean_intent_for(deliverable, sess_hash)
    try:
        schema = extract_schema(session, deliv_spec, clean_intent)
    except (ValueError, FileNotFoundError, KeyError):
        return None   # anchor failed to resolve / gate spec invalid → drop, do not fabricate
    return {
        "session_hash": sess_hash,
        "deliverable": {
            "kind": deliverable.kind,
            "summary": deliverable.summary,
            "artifact_path": deliverable.artifact_path,
            "gates": deliverable.gates,
            "evidence": deliverable.evidence,
        },
        "schema": _schema_to_dict(schema),
    }


def _schema_to_dict(schema) -> dict:
    """Serialize a Schema to a plain JSON-able dict for the index (carriers preserved)."""
    iv = schema.intent
    v = schema.verifier
    g = schema.loop
    return {
        "intent": {
            "goal": iv.goal,
            "target_invariants": list(iv.target_invariants),
            "constraints": list(iv.constraints),
            "excluded_paths": list(iv.excluded_paths),
            "source_session_hash": iv.source_session_hash,
        },
        "verifier": {
            "gates": [{"id": ga.id, "kpi": ga.kpi, "kind": ga.kind, "check": ga.check,
                       "threshold": ga.threshold, "weight": ga.weight} for ga in v.gates],
            "external_anchor": v.external_anchor,
            "frozen_hash": v.frozen_hash,
        },
        "loop": {
            "generator_policy": g.generator_policy,
            "max_iterations": g.max_iterations,
            "stop_rule": g.stop_rule,
            "state_handle": g.state_handle,
            "fossil_write": g.fossil_write,
        },
    }


# ------------------------------------------------------------------ the indexer ----

DEFAULT_CORPUS_ROOT = os.path.expanduser("~/.claude/projects")


def iter_transcripts(root: str = DEFAULT_CORPUS_ROOT) -> Iterable[str]:
    """Yield every ``*.jsonl`` under root. Local filesystem only; transmits nothing."""
    for dirpath, _dirs, files in os.walk(root):
        for name in files:
            if name.endswith(".jsonl"):
                yield os.path.join(dirpath, name)


@dataclass
class IndexStats:
    files_scanned: int = 0
    sessions_with_deliverable: int = 0
    candidate_schemas: int = 0
    rows: list = field(default_factory=list)


def index_corpus(root: str = DEFAULT_CORPUS_ROOT, *, out_path: Optional[str] = None,
                 limit: Optional[int] = None) -> IndexStats:
    """Walk the corpus, mine deliverables, synthesize candidate Σ schemas, emit a jsonl index.

    Each output row is ``{session_hash, deliverable, schema}`` and is fully REDACTED. Rows whose
    deliverable has no resolvable external anchor are dropped (NO FABRICATION). Returns
    IndexStats with the rows in-memory too (so callers/tests don't have to re-read the file).

    `limit` caps files scanned (keeps the deterministic test fast); None scans the whole tree."""
    stats = IndexStats()
    writer = open(out_path, "w", encoding="utf-8") if out_path else None
    try:
        for i, path in enumerate(iter_transcripts(root)):
            if limit is not None and i >= limit:
                break
            stats.files_scanned += 1
            turns = parse_session(path)
            if not turns:
                continue
            deliverables = detect_deliverables(turns)
            if not deliverables:
                continue
            sess_hash = _session_hash(path, turns)
            session_emitted = False
            for d in deliverables:
                row = synthesize_candidate(d, sess_hash)
                if row is None:
                    continue
                stats.candidate_schemas += 1
                stats.rows.append(row)
                if writer:
                    writer.write(json.dumps(row, sort_keys=True) + "\n")
                session_emitted = True
            if session_emitted:
                stats.sessions_with_deliverable += 1
    finally:
        if writer:
            writer.close()
    return stats
