#!/usr/bin/env python3
"""plateau.absorb — private raw -> public primitives -> model.toml.

Implements `docs/harness-0.3/PLAN-absorb.md` (owner D1): distils a sealed experiment's
raw directory (or an adapter session's `.plateau/` store) into small, leak-checked JSONL
"primitives" under `primitives/<source>/<run_id>/`, from which `plateau.lab.fit.
from_primitives` recomputes `model.toml`. The raw/store stay private; primitives carry
only aggregate counts, buckets and the SHA-256 of every raw file they were distilled
from -- never a path, a symbol, a decision's text or a probe's question/answer text.

Two sources:

  * experiment (`--raw <dir|tar.gz> --run-id ID --experiment NAME --out DIR`): a D-038-
    shaped raw run (`<raw>/<run>/blind.json` + one dir per token, each with
    `manifest.json`, `probes.jsonl`, `judge.json`, `transcript/*.jsonl`). Reuses the
    exact turn/compaction/re-derivation definitions `experiments/d038/score.py` and
    `experiments/d038/probes.py` use (sealed references; reimplemented here rather than
    imported -- this package's established convention, see `plateau/lab/ledger.py`'s own
    docstring) so `derived.json` reproduces `results.json` bit for bit.
  * adapter (`--store <dir with index.sqlite, ledger.sqlite, handoff/, hooks.log,
    probes/> --run-id ID --out DIR`): a `plateau.bridge`/`plateau.lab` store, aggregated
    the same shape.

`--check <primitives dir>` re-runs the reproducible half of the leak check (the
structural code-fence/path-shaped-string rules) plus a schema/hash integrity check,
using only `hashes.json` and `run.json` -- never the raw, which by then may be gone or
simply not present (see `check_primitives`'s docstring for exactly what is and is not
re-verifiable without the raw).

Conventions as `docs/harness-0.3/PLAN.md`: Python >= 3.9, stdlib only, never touches
`experiments/` (read-only reference), never `git commit`/push.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
from typing import Any, Dict, List, Optional, Set, Tuple

CODE_EXT = (".py", ".mjs", ".js", ".ts", ".tsx", ".cjs")
LAG_BUCKET_BOUNDS = (20_000, 60_000)
GRADE = {"exact": 1.0, "fuzzy": 0.5, "wrong": 0.0}

_TEST_CMD_RE = re.compile(
    r"pytest|unittest|npm test|npm run test|cargo test|go test|node\s+--test|vitest|jest|mocha"
)
_COUNT_RE = re.compile(r"(\d+) (passed|failed|vulnerabilit(?:y|ies))|^# (pass|fail) (\d+)$", re.M)
_ERR_RE = re.compile(r"^(Traceback|.*Error\b.*|.*FAILED.*|.*Exception\b.*)$", re.M)

# --- fail-closed leak scan (PLAN-absorb.md "Leak rule") ------------------------------
CODE_FENCE = "```"
PATHLIKE_RE = re.compile(r"[\w.-]+/[\w.-]+\.(?:mjs|js|ts|py|md|json)")

# Tokens extracted from raw material for the forbidden set: maximal contiguous runs of
# identifier/path characters (dots, slashes and hyphens are kept WITH their neighbours,
# not split out -- "concierge-agent", "config.mjs" and "wavex-qa-bot-2026" each become
# ONE forbidden entry this way, which is both what a literal copy-paste leak would
# reproduce verbatim and safer than exploding every raw string into single dictionary
# words: this repo's own primitive schema legitimately uses short generic words as enum
# values ("read", "test", "file", "command", ...) that plausibly also occur, as their
# own free-standing (space- or punctuation-delimited) token, somewhere in a real raw
# tree's paths/commands/citations -- see the module docstring's cross-reference to the
# `_STOPWORDS` filter below for how those are told apart from an actual leak.
_TOKEN_RE = re.compile(r"[A-Za-z0-9_./-]{3,}")
_STOPWORDS = {
    "read", "edit", "write", "bash", "grep", "glob", "test", "tests", "exec", "file",
    "files", "kind", "tool", "tools", "turn", "turns", "true", "false", "none", "null",
    "command", "commands", "search", "decided", "symbol", "symbols", "error", "errors",
    "node", "main", "agent", "session", "sessions", "data", "json", "config", "count",
    "index", "name", "type", "value", "path", "paths", "pass", "fail", "passed",
    "failed", "done", "list", "dict", "str", "int", "float", "bool", "http", "https",
    # this repo's own probe-verdict enum -- a judge.json's `probes[].verdict` legitimately
    # uses these words too (see e.g. experiments/d038 judge output), and this repo's own
    # `probes.jsonl` primitive carries the same enum as a VALUE (never a leak by itself).
    "exact", "fuzzy", "wrong",
    # this package's/this host's own already-public naming -- picked up from a raw run's
    # OWN tooling paths (".claude/hooks/d037/...") and manifest fields (claude_version,
    # model_ids), never the private target's identity, and already public in this repo's
    # own model.toml / CHANGELOG.md (e.g. "d037-omega-6000", "claude-sonnet-5").
    "claude", "d037", "d038", "omega", "plateau",
}


def _keep_token(tok: str) -> bool:
    if len(tok) < 4:
        return False
    if tok.lower() in _STOPWORDS:
        return False
    return True


def _tokens_from_text(s: Optional[str]) -> Set[str]:
    out: Set[str] = set()
    if not s:
        return out
    s = str(s)
    for m in _TOKEN_RE.finditer(s):
        tok = m.group(0).strip("./-")
        if _keep_token(tok):
            out.add(tok)
    return out


def _tokens_from_json(obj: Any) -> Set[str]:
    out: Set[str] = set()
    if isinstance(obj, str):
        out |= _tokens_from_text(obj)
    elif isinstance(obj, dict):
        for v in obj.values():
            out |= _tokens_from_json(v)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            out |= _tokens_from_json(v)
    return out


# Long free-text narrative (a judge's prose "defects" paragraph, a shadow/D-038
# probe's TEMPLATED question text) is scanned more narrowly than a short structured
# string: pulling every >=4-char word out of a paragraph of ordinary English guarantees
# collisions with this repo's own short enum vocabulary (a probe's own "kind" -- e.g.
# probes.py's "signature"/"denied"/"error_line" -- or a judge verdict) and with pure
# coincidence (a probe id like "f010" recurring as four consecutive hex digits inside an
# unrelated sha256 prefix). Prose is instead scanned only for the SHAPES an actual leak
# would take: backtick-quoted spans (every raw probe/judge template quotes its
# identifying substitution in backticks), `path.ext[:line]`-shaped citations, ALL_CAPS
# env-var-style names, snake_case identifiers, and multi-segment hyphenated compounds
# (e.g. a literal leaked credential default) -- never a bare dictionary word.
_BACKTICK_RE = re.compile(r"`([^`]+)`")
_CITE_RE = re.compile(r"[\w./-]+\.(?:mjs|js|ts|tsx|cjs|py|md|json|sql|toml|yaml|yml)(?::\d+(?:-\d+)?)?")
_ALLCAPS_RE = re.compile(r"\b[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+\b")
_SNAKE_RE = re.compile(r"\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+\b")
_HYPHEN_COMPOUND_RE = re.compile(r"\b[A-Za-z0-9]+(?:-[A-Za-z0-9]+){2,}\b")


def _tokens_from_prose(text: Optional[str]) -> Set[str]:
    out: Set[str] = set()
    if not text:
        return out
    text = str(text)
    for m in _BACKTICK_RE.finditer(text):
        out |= _tokens_from_text(m.group(1))
    for rx in (_CITE_RE, _ALLCAPS_RE, _SNAKE_RE, _HYPHEN_COMPOUND_RE):
        for m in rx.finditer(text):
            tok = m.group(0)
            if _keep_token(tok):
                out.add(tok)
    return out


def _tokens_from_json_prose(obj: Any) -> Set[str]:
    """Like `_tokens_from_json`, but scans string leaves with `_tokens_from_prose`
    instead of whole-value `_tokens_from_text` -- for judge.json, whose "defects"/
    "item" fields are free-flowing narrative (see `_tokens_from_prose`'s docstring)."""
    out: Set[str] = set()
    if isinstance(obj, str):
        out |= _tokens_from_prose(obj)
    elif isinstance(obj, dict):
        for v in obj.values():
            out |= _tokens_from_json_prose(v)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            out |= _tokens_from_json_prose(v)
    return out


def _tokens_from_tree_paths(root_dir: str) -> Set[str]:
    """Every path segment (dir/file name) and every relpath under `root_dir`, tokenized
    -- "every path under snap/, work/ and the store" (PLAN-absorb.md "Leak rule")."""
    out: Set[str] = set()
    if not os.path.isdir(root_dir):
        return out
    for dirpath, dirnames, filenames in os.walk(root_dir):
        rel = os.path.relpath(dirpath, root_dir)
        if rel != ".":
            out |= _tokens_from_text(rel)
        for name in list(dirnames) + list(filenames):
            out |= _tokens_from_text(name)
    return out


def _scan_value_for_leaks(value: str, forbidden: Set[str]) -> List[str]:
    problems = []
    if CODE_FENCE in value:
        problems.append("code fence in value: {!r}".format(value[:80]))
    if PATHLIKE_RE.search(value):
        problems.append("path-shaped string in value: {!r}".format(value[:80]))
    for tok in forbidden:
        if tok and tok in value:
            problems.append("forbidden token {!r} found in value: {!r}".format(tok, value[:80]))
    return problems


def _scan_for_leaks(obj: Any, forbidden: Set[str], where: str = "$") -> List[str]:
    problems: List[str] = []
    if isinstance(obj, str):
        for p in _scan_value_for_leaks(obj, forbidden):
            problems.append("{}: {}".format(where, p))
    elif isinstance(obj, dict):
        for k, v in obj.items():
            problems.extend(_scan_for_leaks(v, forbidden, "{}.{}".format(where, k)))
    elif isinstance(obj, (list, tuple)):
        for i, v in enumerate(obj):
            problems.extend(_scan_for_leaks(v, forbidden, "{}[{}]".format(where, i)))
    return problems


# --- run-id naming rule (PLAN-absorb.md "Leak rule": a run id must not carry the
# target's own name -- the same failure mode as a primitive value leaking it, just in a
# field the leak SCAN never looks at, since `--run-id` is caller-supplied rather than
# derived from the raw/store) -----------------------------------------------------------

class ForbiddenRunId(ValueError):
    """Raised when `--run-id` echoes the raw/store's own forbidden vocabulary or the
    target repo's git remote name/URL; `main()` reports it and exits 2, the same as any
    other bad-argument `ValueError` this module raises."""


def _git_remote_tokens(path: str) -> Set[str]:
    """Tokens (lowercased, `_keep_token`-filtered) drawn from the git remote name(s)
    and URL(s) of the repo containing `path` -- the private target's own identity.
    Kept OUT of the primitive-scan `forbidden` set itself (a coincidental short
    substring match there against this repo's own vocabulary would be a false
    positive); used only to keep that identity out of a caller-supplied `--run-id`.
    Best-effort: returns an empty set when `path` is not inside a git working tree, has
    no remotes, or `git` itself is unavailable -- never raises."""
    tokens: Set[str] = set()
    try:
        top = subprocess.run(
            ["git", "-C", path, "rev-parse", "--show-toplevel"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, timeout=5,
        )
        if top.returncode != 0 or not top.stdout.strip():
            return tokens
        root = top.stdout.strip()
        remotes = subprocess.run(
            ["git", "-C", root, "remote"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, timeout=5,
        )
        names = remotes.stdout.split() if remotes.returncode == 0 else []
        for name in names or ["origin"]:
            urlres = subprocess.run(
                ["git", "-C", root, "remote", "get-url", name],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, timeout=5,
            )
            if urlres.returncode != 0:
                continue
            url = urlres.stdout.strip()
            for part in re.split(r"[^A-Za-z0-9]+", "{} {}".format(name, url)):
                part = part.strip().lower()
                if len(part) >= 4 and part not in _STOPWORDS:
                    tokens.add(part)
    except (OSError, subprocess.SubprocessError):
        return set()
    return tokens


def _check_run_id(run_id: str, forbidden: Set[str], remote_tokens: Set[str]) -> None:
    """Raises `ForbiddenRunId` when `run_id` matches the raw/store's own forbidden set
    (the same containment check the leak scan applies to primitive values) or contains
    a token from the target's git remote name/URL -- e.g. an adapter run id or
    primitives dir name that carries the target's own name."""
    rid_lower = (run_id or "").lower()
    for tok in forbidden:
        if tok and tok.lower() in rid_lower:
            raise ForbiddenRunId(
                "--run-id {!r} contains a forbidden token ({!r}) drawn from the "
                "raw/store being absorbed -- choose a run id that does not echo the "
                "target's own names.".format(run_id, tok)
            )
    for tok in remote_tokens:
        if tok in rid_lower:
            raise ForbiddenRunId(
                "--run-id {!r} contains a token ({!r}) from the target's git remote "
                "name/URL -- choose a run id that does not name the target.".format(run_id, tok)
            )


# --- small utilities -------------------------------------------------------------------

def _version() -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    pyproject_path = os.path.join(os.path.dirname(here), "pyproject.toml")
    try:
        with open(pyproject_path, encoding="utf-8") as f:
            in_project = False
            for raw_line in f:
                line = raw_line.strip()
                if line.startswith("["):
                    in_project = (line == "[project]")
                    continue
                if in_project and line.startswith("version"):
                    _, _, rhs = line.partition("=")
                    return rhs.strip().strip('"').strip("'")
    except OSError:
        pass
    return "0.0.0"


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _sha256_text(s: str) -> str:
    return _sha256_bytes(s.encode("utf-8"))


def _load_json(path: str) -> Any:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _write_json(path: str, obj: Any) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=1, sort_keys=True)
        f.write("\n")


def _write_jsonl(path: str, records: List[Dict[str, Any]]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, sort_keys=True))
            f.write("\n")


def _read_jsonl(path: str) -> List[Dict[str, Any]]:
    out = []
    if not os.path.isfile(path):
        return out
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def _lag_bucket(t: Optional[int]) -> int:
    t = t or 0
    if t < LAG_BUCKET_BOUNDS[0]:
        return 0
    if t < LAG_BUCKET_BOUNDS[1]:
        return 1
    return 2


def _comp_bucket(n: Optional[int]) -> int:
    return min(n or 0, 2)


def _mean(xs: List[Optional[float]]) -> Optional[float]:
    xs = [x for x in xs if x is not None]
    return (sum(xs) / len(xs)) if xs else None


def _hash_tree(root_dir: str) -> Tuple[int, str, Dict[str, str]]:
    """`(n_files, raw_sha256, {relpath: sha256})` for every regular file under
    `root_dir`. `raw_sha256` is the sha256 of the sorted `"<hash>  <relpath>"` lines
    (the same shape `experiments/d038/hash_raw.py`'s `raw_hashes.txt` uses -- a
    plain-hex sha256sum-style manifest, not a private-repo-specific convention)."""
    file_hashes: Dict[str, str] = {}
    for dirpath, _dirnames, filenames in os.walk(root_dir):
        for name in filenames:
            full = os.path.join(dirpath, name)
            rel = os.path.relpath(full, root_dir).replace(os.sep, "/")
            try:
                file_hashes[rel] = _sha256_file(full)
            except OSError:
                continue
    lines = sorted("{}  {}".format(h, rel) for rel, h in file_hashes.items())
    raw_sha256 = _sha256_text("\n".join(lines))
    return len(file_hashes), raw_sha256, file_hashes


def _write_hashes_json(out_dir: str, file_hashes: Dict[str, str]) -> Dict[str, Any]:
    """`hashes.json`: `{"raw_files": {sha256(relpath): sha256(file)}, "manifest_sha256":
    ...}` -- relpaths are themselves hashed so no raw file name ever appears in the
    public repo (PLAN-absorb.md "Primitive files"). `manifest_sha256` is the sha256 of
    the sorted `"<relpath_hash> <file_sha256>"` lines, letting `--check` detect
    tampering with `hashes.json` itself without needing the raw relpaths back."""
    raw_files = {_sha256_text(rel): h for rel, h in file_hashes.items()}
    manifest_sha256 = _sha256_text(
        "\n".join("{} {}".format(k, v) for k, v in sorted(raw_files.items()))
    )
    doc = {"raw_files": raw_files, "manifest_sha256": manifest_sha256}
    _write_json(os.path.join(out_dir, "hashes.json"), doc)
    return doc


def _extract_raw_arg(raw_arg: str, tmp_holder: List[str]) -> Tuple[str, Optional[str]]:
    """`(raw_dir, tarball_sha256)`. `raw_arg` is either a directory (used as-is, no
    tarball hash) or a `.tar.gz`/`.tgz` (extracted to a fresh temp dir, `raw/` inside
    used as the raw root -- PLAN-absorb.md: "the tarball ... must also be accepted via
    `--raw <tar.gz>` (extract to a temp dir; use `raw/` inside; record
    tarball_sha256)"). `tmp_holder` collects the temp dir path so the caller can clean
    it up afterwards."""
    if os.path.isdir(raw_arg):
        return raw_arg, None
    if not os.path.isfile(raw_arg):
        raise FileNotFoundError("--raw: no such directory or file: {}".format(raw_arg))
    tarball_sha256 = _sha256_file(raw_arg)
    tmp_dir = tempfile.mkdtemp(prefix="plateau-absorb-")
    tmp_holder.append(tmp_dir)
    with tarfile.open(raw_arg, "r:*") as tf:
        _safe_extractall(tf, tmp_dir)
    raw_dir = os.path.join(tmp_dir, "raw")
    if not os.path.isdir(raw_dir):
        # tolerate a tarball whose top level IS the raw tree (no leading raw/ dir)
        raw_dir = tmp_dir
    return raw_dir, tarball_sha256


def _safe_extractall(tf: "tarfile.TarFile", dest: str) -> None:
    dest_abs = os.path.abspath(dest)
    for member in tf.getmembers():
        member_path = os.path.abspath(os.path.join(dest, member.name))
        if not (member_path == dest_abs or member_path.startswith(dest_abs + os.sep)):
            raise ValueError("tarball member escapes destination: {}".format(member.name))
    tf.extractall(dest)  # noqa: S202 -- members already validated above


# --- experiment transcript scan (reimplements experiments/d038/score.py::turn_usage and
# experiments/d038/probes.py, sealed references, byte-identical algorithm) -------------

def _resp_text(res: Any) -> Tuple[str, Optional[int], Optional[bool]]:
    if res is None:
        return "", None, None
    if isinstance(res, str):
        return res, None, None
    if isinstance(res, dict):
        f = res.get("file")
        if isinstance(f, dict) and f.get("content") is not None:
            return str(f.get("content")), res.get("exitCode"), res.get("success")
        so = str(res.get("stdout") or "")
        se = str(res.get("stderr") or "")
        return so + ("\n" + se if se else ""), res.get("exitCode"), res.get("success")
    return str(res), None, None


def _new_turn_rec() -> Dict[str, Any]:
    return {
        "tools": {"Read": 0, "Edit": 0, "Write": 0, "Bash": 0, "Grep": 0, "Glob": 0, "other": 0},
        "reads_of_code": 0, "tests_run": 0, "tests_passed": 0, "tests_failed": 0,
        "has_test_counts": False, "errors_seen": 0, "api_calls": 0,
    }


def _tally_tool(rec: Dict[str, Any], name: str, tin: Dict[str, Any], res: Any,
                reads_out: List[Tuple[int, int, str]], cur: int, line: int) -> None:
    bucket = name if name in ("Read", "Edit", "Write", "Bash", "Grep", "Glob") else "other"
    rec["tools"][bucket] = rec["tools"].get(bucket, 0) + 1
    text, code, ok = _resp_text(res)
    if name in ("Read", "NotebookRead"):
        fp = tin.get("file_path") or tin.get("notebook_path") or ""
        if fp:
            reads_out.append((cur, line, fp))
        if fp.endswith(CODE_EXT):
            rec["reads_of_code"] += 1
    if name == "Bash":
        cmd = tin.get("command", "") or ""
        if _TEST_CMD_RE.search(cmd):
            rec["tests_run"] += 1
            m = _COUNT_RE.search(text)
            if m:
                n = int(m.group(1) or m.group(4) or 0)
                what = m.group(2) or m.group(3) or ""
                rec["has_test_counts"] = True
                if "pass" in what:
                    rec["tests_passed"] += n
                elif "fail" in what:
                    rec["tests_failed"] += n
        failed = (code not in (None, 0)) or (ok is False) or bool(re.search(r"\bFAILED\b|Traceback|\d+ failed", text))
        if failed and _ERR_RE.search(text):
            rec["errors_seen"] += 1


def _scan_experiment_transcript(tp: str, prompts: List[str]) -> Dict[str, Any]:
    """Replays one main-session transcript, tracking the same "current turn" (`cur`,
    matched by user-prompt prefix), compaction boundaries, and per-turn token usage
    `experiments/d038/score.py::turn_usage` does (sealed reference; reimplemented here
    byte-for-byte so `rederivations`/`tokens_per_turn` reproduce `results.json`), plus a
    per-turn tool tally this repo's `turns.jsonl` primitive additionally records."""
    cur = 0
    usage: Dict[int, List[int]] = {}          # cur -> [in, cache_create, cache_read, out]
    reads: List[Tuple[int, int, str]] = []     # (cur, line, full_path)
    comp: List[Tuple[int, int]] = []           # (cur, line)
    grand_cum = 0
    compactions_ctx: List[Dict[str, Any]] = []  # {cur, line, context_before, context_after}
    pending: Dict[str, Tuple[str, Dict[str, Any]]] = {}
    per_turn: Dict[int, Dict[str, Any]] = {}
    seen_msg_ids: Set[Any] = set()
    awaiting_after: Optional[int] = None  # index into compactions_ctx awaiting a context_after

    def turn(i: int) -> Dict[str, Any]:
        return per_turn.setdefault(i, _new_turn_rec())

    with open(tp, encoding="utf-8", errors="replace") as f:
        for i, raw_line in enumerate(f, 1):
            raw_line = raw_line.strip()
            if not raw_line:
                continue
            try:
                j = json.loads(raw_line)
            except Exception:
                continue
            t = j.get("type")
            m = j.get("message") or {}
            c = m.get("content")

            if t == "user":
                txt = c if isinstance(c, str) else " ".join(
                    b.get("text", "") for b in (c or []) if isinstance(b, dict) and b.get("type") == "text"
                )
                for k, p in enumerate(prompts, 1):
                    if txt.strip().startswith(p[:80]) and cur < k:
                        cur = k
                if isinstance(c, list) and c and isinstance(c[0], dict) and c[0].get("type") == "tool_result":
                    uid = c[0].get("tool_use_id")
                    name, tin = pending.pop(uid, (None, {}))
                    res = j.get("toolUseResult")
                    if name:
                        _tally_tool(turn(cur), name, tin, res, reads, cur, i)
                continue

            if t == "system" and j.get("subtype") == "compact_boundary":
                comp.append((cur, i))
                compactions_ctx.append({"cur": cur, "line": i, "context_before": grand_cum, "context_after": None})
                awaiting_after = len(compactions_ctx) - 1
                continue

            if t == "assistant":
                u = m.get("usage")
                mid = m.get("id")
                if u and mid not in seen_msg_ids:
                    seen_msg_ids.add(mid)
                    slot = usage.setdefault(cur, [0, 0, 0, 0])
                    inp = int(u.get("input_tokens", 0) or 0)
                    cc = int(u.get("cache_creation_input_tokens", 0) or 0)
                    cr = int(u.get("cache_read_input_tokens", 0) or 0)
                    out = int(u.get("output_tokens", 0) or 0)
                    slot[0] += inp
                    slot[1] += cc
                    slot[2] += cr
                    slot[3] += out
                    grand_cum += inp + cc + out
                    if awaiting_after is not None:
                        compactions_ctx[awaiting_after]["context_after"] = grand_cum
                        awaiting_after = None
                for b in (c or []) if isinstance(c, list) else []:
                    if isinstance(b, dict) and b.get("type") == "tool_use":
                        pending[b.get("id")] = (b.get("name"), b.get("input") or {})
                        turn(cur)["api_calls"] += 1
                continue

    return {"usage": usage, "comp": comp, "reads": reads, "per_turn": per_turn, "compactions_ctx": compactions_ctx}


def _rederivation_events(reads: List[Tuple[int, int, str]], comp: List[Tuple[int, int]],
                          target_name: str) -> List[Tuple[int, int, int, str]]:
    """`(line, turn, after_compaction_k, ext)` per re-derivation event -- the exact
    `experiments/d038/score.py::turn_usage` definition (sealed reference): a file under
    the target subtree read again after some compaction boundary it was already read
    before, with no OTHER boundary in between. `after_compaction_k` is that boundary's
    0-indexed position among this transcript's own compactions."""
    out: List[Tuple[int, int, int, str]] = []
    needle = "/" + target_name + "/"
    for k, (_comp_cur, ci) in enumerate(comp):
        before = {fp for (_c, li, fp) in reads if li < ci and needle in fp}
        for (rcur, li, fp) in reads:
            if li <= ci or fp not in before:
                continue
            if any(ci < cj < li for (_c, cj) in comp):
                continue
            out.append((li, rcur, k, os.path.splitext(fp)[1]))
    return out


def _prompts_from_turns_json(turns_doc: Dict[str, Any]) -> List[str]:
    footer = turns_doc.get("common_footer", "")
    out = []
    for epic in turns_doc.get("epics", []):
        for t in epic.get("turns", []):
            out.append("{}\n\n{}".format(t.get("prompt", ""), footer))
    return out


def _find_turns_json(token_dir: str) -> Optional[Dict[str, Any]]:
    p = os.path.join(token_dir, "judge_view", "turns.json")
    if os.path.isfile(p):
        return _load_json(p)
    return None


# --- experiment forbidden set ----------------------------------------------------------

def _forbidden_set_experiment(run_dir: str, token_dirs: Dict[str, str], manifest_by_token: Dict[str, Any],
                               judge_by_token: Dict[str, Any], probes_by_token: Dict[str, List[Dict[str, Any]]]) -> Set[str]:
    forbidden: Set[str] = set()
    for token, tdir in token_dirs.items():
        # every path under work/, judge_view/ and the store (.d037/.claude/.plateau
        # dirs all live under work/) -- PLAN-absorb.md "Leak rule".
        forbidden |= _tokens_from_tree_paths(os.path.join(tdir, "work"))
        forbidden |= _tokens_from_tree_paths(os.path.join(tdir, "judge_view"))
        # the D-037 receipt store, when this arm ran one: every receipt target, every
        # node key.
        store_path = os.path.join(tdir, "work", ".d037", "index.sqlite")
        if os.path.isfile(store_path):
            try:
                conn = sqlite3.connect(store_path)
                try:
                    for (target,) in conn.execute("SELECT DISTINCT target FROM receipts"):
                        forbidden |= _tokens_from_text(target)
                    for (key,) in conn.execute("SELECT DISTINCT key FROM nodes"):
                        forbidden |= _tokens_from_text(key)
                    for (det,) in conn.execute("SELECT DISTINCT last_detail FROM nodes"):
                        forbidden |= _tokens_from_text(det)
                finally:
                    conn.close()
            except sqlite3.Error:
                pass
        # every symbol/identifier in probe expected/q; every decision text (cls
        # "decided" probes carry the decided name/path as `expected`).
        for p in probes_by_token.get(token, []):
            forbidden |= _tokens_from_prose(p.get("q"))   # templated prose: backtick spans only
            forbidden |= _tokens_from_text(p.get("expected"))  # pure data, never templated
        # every judge citation (judge.json's "defects"/"item" fields are free-text
        # narrative -- see `_tokens_from_json_prose`'s docstring).
        judge = judge_by_token.get(token)
        if judge:
            forbidden |= _tokens_from_json_prose(judge)
        # the target's own basename ("Wavex/target file basename").
        target = (manifest_by_token.get(token) or {}).get("target") or {}
        subtree = target.get("subtree")
        if subtree:
            forbidden |= _tokens_from_text(os.path.basename(subtree))
            forbidden |= _tokens_from_text(subtree)
    return forbidden


def _target_name(manifest: Dict[str, Any]) -> str:
    subtree = (manifest.get("target") or {}).get("subtree") or ""
    return os.path.basename(subtree) or "target"


# --- experiment absorb -------------------------------------------------------------------

def absorb_experiment(raw_arg: str, run_id: str, experiment: str, out_dir: str) -> Dict[str, Any]:
    tmp_holders: List[str] = []
    try:
        raw_dir, tarball_sha256 = _extract_raw_arg(raw_arg, tmp_holders)
        run_subdirs = sorted(
            d for d in os.listdir(raw_dir)
            if os.path.isfile(os.path.join(raw_dir, d, "blind.json"))
        ) if os.path.isdir(raw_dir) else []
        if not run_subdirs:
            raise FileNotFoundError("no <run>/blind.json found under raw dir: {}".format(raw_dir))
        run_no = run_subdirs[0]
        run_root = os.path.join(raw_dir, run_no)
        blind = _load_json(os.path.join(run_root, "blind.json"))

        token_dirs = {tok: os.path.join(run_root, tok) for tok in blind}
        manifest_by_token = {tok: _load_json(os.path.join(d, "manifest.json")) for tok, d in token_dirs.items()}
        judge_by_token: Dict[str, Any] = {}
        for tok, d in token_dirs.items():
            jp = os.path.join(d, "judge.json")
            if os.path.isfile(jp):
                judge_by_token[tok] = _load_json(jp)
        raw_probes_by_token = {tok: _read_jsonl(os.path.join(d, "probes.jsonl")) for tok, d in token_dirs.items()}

        n_files, raw_sha256, file_hashes = _hash_tree(raw_dir)

        forbidden = _forbidden_set_experiment(
            run_root, token_dirs, manifest_by_token, judge_by_token, raw_probes_by_token,
        )
        # The run's own worktree tokens (blind.json's keys, e.g. "wt_85150c") are
        # legitimate primitive content by design -- `run.json`'s own `arms` map and
        # every JSONL row's `token` field publish them outright -- not a path/symbol/
        # decision the leak rule protects. They can still surface as a snake_case-
        # shaped standalone match inside a raw probe's absolute-path text (`/./raw/1/
        # wt_85150c/work/...` has `\b` word boundaries either side of the token even
        # though it's slash-embedded); discard them explicitly rather than let that
        # false-positive block every legitimate `token` value absorb itself writes.
        forbidden -= set(blind.keys())
        forbidden_digest = _sha256_text("\n".join(sorted(forbidden)))

        # Fail closed on the run id itself, same as any other caller-supplied value
        # that could carry the target's own name (PLAN-absorb.md "Leak rule").
        _check_run_id(run_id, forbidden, _git_remote_tokens(raw_dir))

        # --- per-arm scan (turns, rederivations, recall) ---
        turns_records: List[Dict[str, Any]] = []
        rederiv_records: List[Dict[str, Any]] = []
        probes_records: List[Dict[str, Any]] = []
        per_arm_summary: Dict[str, Dict[str, Any]] = {}

        for token, arm in blind.items():
            tdir = token_dirs[token]
            manifest = manifest_by_token[token]
            target_name = _target_name(manifest)
            turns_doc = _find_turns_json(tdir)
            prompts = _prompts_from_turns_json(turns_doc) if turns_doc else []

            main_session = manifest.get("main_session")
            tp = os.path.join(tdir, "transcript", "{}.jsonl".format(main_session)) if main_session else None
            if tp and os.path.isfile(tp) and prompts:
                scanned = _scan_experiment_transcript(tp, prompts)
            else:
                scanned = {"usage": {}, "comp": [], "reads": [], "per_turn": {}, "compactions_ctx": []}

            usage = scanned["usage"]
            comp = scanned["comp"]
            reads = scanned["reads"]
            per_turn = scanned["per_turn"]

            rederivs = _rederivation_events(reads, comp, target_name)
            agg: Dict[Tuple[int, int, str], int] = {}
            for line, rcur, k, ext in rederivs:
                key = (rcur, k, ext)
                agg[key] = agg.get(key, 0) + 1
            for (rcur, k, ext), count in sorted(agg.items()):
                rederiv_records.append({
                    "token": token, "turn": rcur, "after_compaction_k": k,
                    "ext": ext, "count": count,
                })

            for turn_meta in manifest.get("turns", []):
                i = turn_meta.get("i")
                rec = per_turn.get(i, _new_turn_rec())
                slot = usage.get(i, [0, 0, 0, 0])
                compactions_in_turn = sum(1 for (ccur, _li) in comp if ccur == i)
                turns_records.append({
                    "token": token, "i": i, "turn_id": turn_meta.get("id"),
                    "seconds": turn_meta.get("seconds"), "cost": turn_meta.get("cost"),
                    "api_calls": rec["api_calls"],
                    "tokens_in": slot[0], "tokens_cache_read": slot[2],
                    "tokens_cache_create": slot[1], "tokens_out": slot[3],
                    "compactions_in_turn": compactions_in_turn,
                    "tools": dict(rec["tools"]),
                    "reads_of_code": rec["reads_of_code"],
                    "tests_run": rec["tests_run"],
                    "tests_passed": rec["tests_passed"] if rec["has_test_counts"] else None,
                    "tests_failed": rec["tests_failed"] if rec["has_test_counts"] else None,
                    "errors_seen": rec["errors_seen"],
                })

            judge = judge_by_token.get(token)
            verdict_by_id = {p["id"]: p["verdict"] for p in (judge or {}).get("probes", [])} if judge else {}
            graded = []
            for p in raw_probes_by_token.get(token, []):
                verdict = verdict_by_id.get(p.get("id"))
                grade = GRADE.get(verdict)
                probes_records.append({
                    "token": token, "turn": p.get("turn"), "cls": p.get("cls"), "kind": p.get("kind"),
                    "lag_tokens": p.get("tokens_since"), "compactions_crossed": p.get("compactions_crossed"),
                    "lag_bucket": p.get("lag_bucket"), "comp_bucket": p.get("comp_bucket"),
                    "verdict": verdict,
                    "expected_len": len(p.get("expected") or ""), "answer_len": len(p.get("answer") or ""),
                    "q_hash": _sha256_text(p.get("q") or "")[:16],
                    "probe_contaminates": p.get("probe_contaminates"),
                })
                if grade is not None:
                    graded.append(dict(p, grade=grade, verdict=verdict))

            def recall(sel):
                xs = [g["grade"] for g in graded if sel(g)]
                return (sum(xs) / len(xs)) if xs else None

            by_lag = {b: recall(lambda g, b=b: g.get("lag_bucket") == b) for b in (0, 1, 2)}
            by_comp = {b: recall(lambda g, b=b: g.get("comp_bucket") == b) for b in (0, 1, 2)}
            far = recall(lambda g: g.get("lag_bucket") == 2 or g.get("comp_bucket", 0) >= 1)
            auc = None if any(by_lag.get(b) is None for b in (0, 1, 2)) else (by_lag[0] + 2 * by_lag[1] + by_lag[2]) / 4
            tokens_per_turn = _mean([
                (usage[k][0] + usage[k][1] + usage[k][3]) for k in usage if k >= 1
            ])

            per_arm_summary[arm] = {
                "token": token,
                "recall_by_lag": by_lag, "recall_by_comp": by_comp,
                "far_recall": far, "auc": auc,
                "rederivations": len(rederivs),
                "tokens_per_turn": tokens_per_turn,
            }

        # --- compactions.jsonl (best-effort: transcript usage fields only; a store's
        # own `.plateau/compactions` table is a per-agent event log with no per-line
        # token-context notion, so this is the one place the experiment and adapter
        # sources genuinely differ in what's measurable -- see module docstring).
        compactions_records: List[Dict[str, Any]] = []
        for token in blind:
            tdir = token_dirs[token]
            manifest = manifest_by_token[token]
            main_session = manifest.get("main_session")
            turns_doc = _find_turns_json(tdir)
            prompts = _prompts_from_turns_json(turns_doc) if turns_doc else []
            tp = os.path.join(tdir, "transcript", "{}.jsonl".format(main_session)) if main_session else None
            if tp and os.path.isfile(tp) and prompts:
                scanned = _scan_experiment_transcript(tp, prompts)
                for k, cx in enumerate(scanned["compactions_ctx"]):
                    compactions_records.append({
                        "token": token, "k": k, "turn": cx["cur"], "line": cx["line"],
                        "context_before": cx["context_before"], "context_after": cx["context_after"],
                    })

        # --- injections.jsonl: from the bridge arm's hooks.log (PLAN.md hook log format:
        # "inject ev=<Event> q=<n>ch nodes=<k>/<n> chars=<c> budget=<b>" [+ " holdout=1"])
        inject_re = re.compile(
            r"inject ev=(\S+) q=(\d+)ch nodes=(\d+)/(\d+) chars=(\d+) budget=(\d+)(?: holdout=(\d))?"
        )
        injections_records: List[Dict[str, Any]] = []
        for token, tdir in token_dirs.items():
            hooks_log = os.path.join(tdir, "hooks.log")
            if not os.path.isfile(hooks_log):
                continue
            with open(hooks_log, encoding="utf-8", errors="replace") as f:
                for line in f:
                    m = inject_re.search(line)
                    if not m:
                        continue
                    injections_records.append({
                        "token": token, "event": m.group(1), "compaction_k": None,
                        "chars": int(m.group(5)), "budget": int(m.group(6)),
                        "nodes": int(m.group(3)), "of_nodes": int(m.group(4)),
                        "holdout": int(m.group(7) or 0), "rid_at": None,
                    })

        # --- judge.json primitive ---
        judge_out: Dict[str, Any] = {}
        for token, arm in blind.items():
            judge = judge_by_token.get(token)
            if not judge:
                continue
            epics = {e: judge["epics"][e]["score"] for e in judge.get("epics", {})}
            judge_out[token] = {
                "epics": epics,
                "task_total": sum(epics.values()),
                "security_items_closed": len(judge.get("security_items_closed", [])),
                "runner_green": (judge.get("tests") or {}).get("runner_green"),
                "defects_len": len(judge.get("defects") or ""),
            }

        model_ids = sorted({
            m for man in manifest_by_token.values() for t in man.get("turns", []) for m in (t.get("models") or [])
        })
        first_manifest = manifest_by_token[sorted(manifest_by_token)[0]]
        bridge_version, bridge_sha = "none", None
        for man in manifest_by_token.values():
            hooks = man.get("hooks") or {}
            if hooks:
                bridge_sha = _sha256_text(json.dumps(sorted(hooks.items())))
                bridge_version = "d037-omega-{}".format(man.get("budget"))
                break

        run_doc = {
            "run_id": run_id, "source": "experiment", "experiment": experiment,
            "arms": dict(blind),
            "target": {
                "commit": first_manifest.get("target", {}).get("commit"),
                "tree": first_manifest.get("target", {}).get("tree"),
            },
            "settings": {
                "window": first_manifest.get("window"), "pct": first_manifest.get("pct"),
                "model_ids": model_ids, "cli_version": first_manifest.get("claude_version"),
                "bridge_version": bridge_version, "bridge_sha": bridge_sha,
            },
            "cost_usd": {
                "task": sum(m.get("task_cost_usd") or 0 for m in manifest_by_token.values()),
                "probe": sum(m.get("probe_cost_usd") or 0 for m in manifest_by_token.values()),
                "judge": sum((j.get("_cost_usd") or 0) for j in judge_by_token.values()),
            },
            "raw_files": n_files, "raw_sha256": raw_sha256, "tarball_sha256": tarball_sha256,
            "absorbed_by": "plateau {}".format(_version()),
            "forbidden_digest": forbidden_digest,
        }

        # --- write everything, then scan the whole primitives tree for leaks BEFORE
        # anything is left on disk that shouldn't be (fail closed: on a leak, remove the
        # partially-written out_dir and raise).
        if os.path.isdir(out_dir):
            shutil.rmtree(out_dir)
        os.makedirs(out_dir, exist_ok=True)
        _write_json(os.path.join(out_dir, "run.json"), run_doc)
        _write_jsonl(os.path.join(out_dir, "turns.jsonl"), turns_records)
        _write_jsonl(os.path.join(out_dir, "probes.jsonl"), probes_records)
        _write_jsonl(os.path.join(out_dir, "injections.jsonl"), injections_records)
        _write_jsonl(os.path.join(out_dir, "compactions.jsonl"), compactions_records)
        _write_jsonl(os.path.join(out_dir, "rederivations.jsonl"), rederiv_records)
        _write_json(os.path.join(out_dir, "judge.json"), judge_out)
        _write_json(os.path.join(out_dir, "payload_shapes.json"), {})
        _write_hashes_json(out_dir, file_hashes)

        problems = _scan_primitives_dir(out_dir, forbidden)
        if problems:
            shutil.rmtree(out_dir, ignore_errors=True)
            raise LeakDetected(problems)

        # --- derived.json + recompute-link assertion against results.json, if present
        derived = {
            "far_recall": {arm: s["far_recall"] for arm, s in per_arm_summary.items()},
            "auc": {arm: s["auc"] for arm, s in per_arm_summary.items()},
            "recall_by_lag": {arm: s["recall_by_lag"] for arm, s in per_arm_summary.items()},
            "recall_by_comp": {arm: s["recall_by_comp"] for arm, s in per_arm_summary.items()},
            "rederivations": {arm: s["rederivations"] for arm, s in per_arm_summary.items()},
            "tokens_per_turn": {arm: s["tokens_per_turn"] for arm, s in per_arm_summary.items()},
        }
        results_path = os.path.join(os.path.dirname(raw_dir), "results.json")
        checked_against = None
        if os.path.isfile(results_path):
            results = _load_json(results_path)
            checked_against = results_path
            _assert_matches_results(derived, results, run_no)
        _write_json(os.path.join(out_dir, "derived.json"), derived)

        return {
            "out_dir": out_dir, "run_doc": run_doc, "derived": derived,
            "checked_against": checked_against, "per_arm_summary": per_arm_summary,
        }
    finally:
        for d in tmp_holders:
            shutil.rmtree(d, ignore_errors=True)


class LeakDetected(RuntimeError):
    def __init__(self, problems: List[str]) -> None:
        super().__init__("leak check failed ({} problem(s)):\n{}".format(len(problems), "\n".join(problems[:20])))
        self.problems = problems


def _scan_primitives_dir(out_dir: str, forbidden: Set[str]) -> List[str]:
    problems: List[str] = []
    for name in sorted(os.listdir(out_dir)):
        if name in ("hashes.json",):
            continue  # hashed relpaths/sha256 hex by construction; nothing to leak
        path = os.path.join(out_dir, name)
        if not os.path.isfile(path):
            continue
        if name.endswith(".jsonl"):
            for i, rec in enumerate(_read_jsonl(path)):
                problems.extend(_scan_for_leaks(rec, forbidden, "{}[{}]".format(name, i)))
        elif name.endswith(".json"):
            try:
                doc = _load_json(path)
            except (OSError, ValueError):
                continue
            problems.extend(_scan_for_leaks(doc, forbidden, name))
    return problems


def _assert_matches_results(derived: Dict[str, Any], results: Dict[str, Any], run_no: str) -> None:
    """Equality assertion against `experiments/d038/results.json`'s `table` row for
    this run (PLAN-absorb.md "Recompute link"). A mismatch is an error, not a warning."""
    table = results.get("table") or []
    row = next((r for r in table if str(r.get("run")) == str(int(run_no))), None)
    if row is None:
        return
    problems = []

    def close(a, b, tol=1e-6):
        return a is not None and b is not None and abs(a - b) <= tol * max(1.0, abs(b))

    far_a = derived["far_recall"].get("A")
    if "far_recall_A" in row and not close(far_a, row["far_recall_A"]):
        problems.append("far_recall A: derived {} != results.json {}".format(far_a, row["far_recall_A"]))
    for arm in ("A", "C"):
        exp_auc = (row.get("auc") or {}).get(arm)
        got_auc = derived["auc"].get(arm)
        if exp_auc is not None and not close(got_auc, exp_auc):
            problems.append("auc {}: derived {} != results.json {}".format(arm, got_auc, exp_auc))
        exp_rd = (row.get("rederivations") or {}).get(arm)
        got_rd = derived["rederivations"].get(arm)
        if exp_rd is not None and got_rd != exp_rd:
            problems.append("rederivations {}: derived {} != results.json {}".format(arm, got_rd, exp_rd))
        exp_tpt = (row.get("tokens_per_turn") or {}).get(arm)
        got_tpt = derived["tokens_per_turn"].get(arm)
        if exp_tpt is not None and not close(got_tpt, exp_tpt):
            problems.append("tokens_per_turn {}: derived {} != results.json {}".format(arm, got_tpt, exp_tpt))
    if problems:
        raise RecomputeMismatch(problems)


class RecomputeMismatch(RuntimeError):
    def __init__(self, problems: List[str]) -> None:
        super().__init__("derived.json does not reproduce results.json:\n" + "\n".join(problems))
        self.problems = problems


# --- adapter absorb ----------------------------------------------------------------------

def _forbidden_set_adapter(store_dir: str) -> Set[str]:
    forbidden: Set[str] = set()
    forbidden |= _tokens_from_tree_paths(store_dir)  # snapshots/, handoff/, probes/ names

    index_path = os.path.join(store_dir, "index.sqlite")
    if os.path.isfile(index_path):
        conn = sqlite3.connect(index_path)
        try:
            for (target,) in conn.execute("SELECT DISTINCT target FROM receipts"):
                forbidden |= _tokens_from_text(target)
            for (detail,) in conn.execute("SELECT DISTINCT detail FROM receipts"):
                forbidden |= _tokens_from_text(detail)
            for (key,) in conn.execute("SELECT DISTINCT key FROM nodes"):
                forbidden |= _tokens_from_text(key)
            for (det,) in conn.execute("SELECT DISTINCT last_detail FROM nodes"):
                forbidden |= _tokens_from_prose(det)
            # a decision's `text` is free-flowing prose (unlike a node's last_detail,
            # it is never `_short()`-truncated -- see plateau.bridge.common.
            # record_decision), so it gets the same narrow, shape-based extraction as
            # judge.json's "defects" narrative (module docstring, `_tokens_from_prose`).
            for (text,) in conn.execute("SELECT DISTINCT text FROM decisions"):
                forbidden |= _tokens_from_prose(text)
            for (prov,) in conn.execute("SELECT DISTINCT provenance FROM decisions"):
                forbidden |= _tokens_from_text(prov)
        except sqlite3.Error:
            pass
        finally:
            conn.close()

    ledger_path = os.path.join(store_dir, "ledger.sqlite")
    # probes table carries no question/answer text (q_hash only) -- nothing to mine.

    handoff_dir = os.path.join(store_dir, "handoff")
    if os.path.isdir(handoff_dir):
        for name in os.listdir(handoff_dir):
            p = os.path.join(handoff_dir, name)
            try:
                forbidden |= _tokens_from_json(_load_json(p))
            except (OSError, ValueError):
                pass

    probes_dir = os.path.join(store_dir, "probes")
    _PROBE_TEXT_KEYS = ("expected", "answer", "cmd", "q")
    if os.path.isdir(probes_dir):
        for name in os.listdir(probes_dir):
            if not name.endswith(".json"):
                continue
            p = os.path.join(probes_dir, name)
            try:
                doc = _load_json(p)
            except (OSError, ValueError):
                continue
            if isinstance(doc, dict):
                # only the fields that actually carry question/expected/answer text or
                # the fork command line (PLAN-absorb.md: no path/symbol/decision/
                # question text) -- not "kind"/"cls"/"q_hash"/"verdict", which are this
                # repo's own enum/hash vocabulary and legitimately echoed verbatim into
                # `probes.jsonl` by design.
                for k in _PROBE_TEXT_KEYS:
                    forbidden |= _tokens_from_json(doc.get(k))

    # the store's own session ids are legitimate primitive content by design (every
    # JSONL row's `session` field publishes them outright) -- not a path/symbol/
    # decision the leak rule protects. Discard them explicitly, mirroring the
    # experiment side's worktree-token exclusion above.
    known_sessions: Set[str] = set()
    if os.path.isfile(index_path):
        conn = sqlite3.connect(index_path)
        try:
            for (sid,) in conn.execute("SELECT DISTINCT session_id FROM receipts"):
                if sid:
                    known_sessions.add(sid)
        except sqlite3.Error:
            pass
        finally:
            conn.close()
    if os.path.isfile(ledger_path):
        conn = sqlite3.connect(ledger_path)
        try:
            for (sid,) in conn.execute("SELECT DISTINCT session_id FROM sessions"):
                if sid:
                    known_sessions.add(sid)
        except sqlite3.Error:
            pass
        finally:
            conn.close()
    forbidden -= known_sessions

    return forbidden


def absorb_adapter(store_dir: str, run_id: str, out_dir: str) -> Dict[str, Any]:
    if not os.path.isdir(store_dir):
        raise FileNotFoundError("--store: no such directory: {}".format(store_dir))

    n_files, raw_sha256, file_hashes = _hash_tree(store_dir)
    forbidden = _forbidden_set_adapter(store_dir)
    forbidden_digest = _sha256_text("\n".join(sorted(forbidden)))

    # Fail closed on the run id itself, same as any other caller-supplied value that
    # could carry the target's own name (PLAN-absorb.md "Leak rule") -- this is exactly
    # the mistake `wavex-adapter-2026-09-17` made: the adapter run id and primitives
    # dir name carried the target's own name.
    _check_run_id(run_id, forbidden, _git_remote_tokens(store_dir))

    index_path = os.path.join(store_dir, "index.sqlite")
    ledger_path = os.path.join(store_dir, "ledger.sqlite")

    sessions_rows: List[sqlite3.Row] = []
    if os.path.isfile(ledger_path):
        lconn = sqlite3.connect(ledger_path)
        lconn.row_factory = sqlite3.Row
        try:
            sessions_rows = lconn.execute("SELECT * FROM sessions").fetchall()
            probes_rows = lconn.execute("SELECT * FROM probes").fetchall()
            rederiv_rows = lconn.execute("SELECT * FROM rederivations").fetchall()
        finally:
            lconn.close()
    else:
        probes_rows, rederiv_rows = [], []

    nodes_records: List[Dict[str, Any]] = []
    turns_records: List[Dict[str, Any]] = []
    compactions_records: List[Dict[str, Any]] = []
    injections_records: List[Dict[str, Any]] = []
    model_ids: Set[str] = set()

    if os.path.isfile(index_path):
        conn = sqlite3.connect(index_path)
        conn.row_factory = sqlite3.Row
        try:
            for row in conn.execute(
                "SELECT session_id, kind, COUNT(*) AS n, AVG(degree) AS mean_degree "
                "FROM nodes GROUP BY session_id, kind"
            ):
                nodes_records.append({
                    "session": row["session_id"], "kind": row["kind"],
                    "count": row["n"], "mean_degree": row["mean_degree"],
                })

            turn_boundaries = conn.execute(
                "SELECT session_id, n, rid_at FROM turns ORDER BY session_id, n"
            ).fetchall()
            by_session: Dict[str, List[sqlite3.Row]] = {}
            for r in turn_boundaries:
                by_session.setdefault(r["session_id"], []).append(r)
            for session_id, rows in by_session.items():
                prev_rid = 0
                for r in rows:
                    lo, hi = prev_rid, r["rid_at"]
                    tool_counts = {"Read": 0, "Edit": 0, "Write": 0, "Bash": 0, "Grep": 0, "Glob": 0, "other": 0}
                    for trow in conn.execute(
                        "SELECT tool, kind, outcome FROM receipts WHERE session_id=? AND id>? AND id<=?",
                        (session_id, lo, hi),
                    ):
                        tool_counts[trow["tool"]] = tool_counts.get(trow["tool"], 0) + 1 if trow["tool"] in tool_counts else tool_counts["other"] + 1
                    reads_of_code = conn.execute(
                        "SELECT COUNT(*) FROM nodes WHERE session_id=? AND kind='read' AND first_rid>? AND first_rid<=?",
                        (session_id, lo, hi),
                    ).fetchone()[0]
                    tests_run, tests_passed, tests_failed = 0, 0, 0
                    for trow in conn.execute(
                        "SELECT outcome FROM receipts WHERE session_id=? AND kind='test' AND id>? AND id<=?",
                        (session_id, lo, hi),
                    ):
                        tests_run += 1
                        if trow["outcome"] == "pass":
                            tests_passed += 1
                        elif trow["outcome"] == "fail":
                            tests_failed += 1
                    errors_seen = conn.execute(
                        "SELECT COUNT(*) FROM receipts WHERE session_id=? AND kind='error' AND id>? AND id<=?",
                        (session_id, lo, hi),
                    ).fetchone()[0]
                    turns_records.append({
                        "session": session_id, "i": r["n"], "turn_id": None,
                        "seconds": None, "cost": None, "api_calls": sum(tool_counts.values()),
                        # per-turn token usage is not attributable from the store alone
                        # (only session-level totals exist -- ledger.sessions.tokens_in/
                        # out); recorded as 0 rather than guessed. See absorb.py's
                        # module docstring / this run's report for this limitation.
                        "tokens_in": 0, "tokens_cache_read": 0, "tokens_cache_create": 0, "tokens_out": 0,
                        "compactions_in_turn": 0,
                        "tools": tool_counts, "reads_of_code": reads_of_code,
                        "tests_run": tests_run,
                        "tests_passed": tests_passed if tests_run else None,
                        "tests_failed": tests_failed if tests_run else None,
                        "errors_seen": errors_seen,
                    })
                    prev_rid = hi

            for row in conn.execute("SELECT session_id, k, rid_at FROM compactions"):
                turn_n = conn.execute(
                    "SELECT MAX(n) FROM turns WHERE session_id=? AND rid_at<=?",
                    (row["session_id"], row["rid_at"]),
                ).fetchone()[0]
                compactions_records.append({
                    "token": row["session_id"], "k": row["k"], "turn": turn_n,
                    "line": None, "context_before": None, "context_after": None,
                })

            for row in conn.execute(
                "SELECT session_id, event, compaction_k, chars, budget, holdout, keys, rid_at FROM injections"
            ):
                try:
                    n_nodes = len(json.loads(row["keys"])) if row["keys"] else 0
                except (TypeError, ValueError):
                    n_nodes = 0
                injections_records.append({
                    "token": row["session_id"], "event": row["event"],
                    "compaction_k": row["compaction_k"], "chars": row["chars"],
                    "budget": row["budget"], "nodes": n_nodes, "of_nodes": None,
                    "holdout": row["holdout"], "rid_at": row["rid_at"],
                })

            for (mid,) in conn.execute("SELECT DISTINCT bridge_version FROM receipts WHERE bridge_version IS NOT NULL"):
                pass  # bridge_version tracked in run.json settings, not model_ids
        finally:
            conn.close()

    for r in sessions_rows:
        if r["model_id"]:
            model_ids.add(r["model_id"])

    probes_records = []
    for p in probes_rows:
        probes_records.append({
            "session": p["session_id"], "turn": p["turn"], "cls": p["cls"], "kind": p["kind"],
            "lag_tokens": p["lag_tokens"], "compactions_crossed": p["compactions_crossed"],
            "lag_bucket": _lag_bucket(p["lag_tokens"]), "comp_bucket": _comp_bucket(p["compactions_crossed"]),
            "verdict": p["verdict"],
            "expected_len": None, "answer_len": None,  # not retained by the ledger (already sanitized upstream)
            "q_hash": p["q_hash"], "probe_contaminates": None,
        })

    rederiv_agg: Dict[Tuple[str, str], int] = {}
    for r in rederiv_rows:
        ext = os.path.splitext(r["path"] or "")[1]
        key = (r["session_id"], ext)
        rederiv_agg[key] = rederiv_agg.get(key, 0) + 1
    rederiv_records = [
        {"session": sid, "turn": None, "after_compaction_k": None, "ext": ext, "count": count}
        for (sid, ext), count in sorted(rederiv_agg.items())
    ]

    bridge_versions = sorted({r["bridge_version"] for r in sessions_rows if r["bridge_version"]})
    bridge_version = bridge_versions[0] if len(bridge_versions) == 1 else ("mixed" if len(bridge_versions) > 1 else "none")

    run_doc = {
        "run_id": run_id, "source": "adapter",
        "target": {"commit": None, "tree": None},
        "settings": {
            "window": None, "pct": None, "model_ids": sorted(model_ids),
            "cli_version": None, "bridge_version": bridge_version, "bridge_sha": None,
        },
        "cost_usd": {
            "task": sum(r["cost_usd"] or 0 for r in sessions_rows), "probe": 0.0, "judge": 0.0,
        },
        "raw_files": n_files, "raw_sha256": raw_sha256, "tarball_sha256": None,
        "absorbed_by": "plateau {}".format(_version()),
        "forbidden_digest": forbidden_digest,
        "sessions": len(sessions_rows),
    }

    if os.path.isdir(out_dir):
        shutil.rmtree(out_dir)
    os.makedirs(out_dir, exist_ok=True)
    _write_json(os.path.join(out_dir, "run.json"), run_doc)
    _write_jsonl(os.path.join(out_dir, "turns.jsonl"), turns_records)
    _write_jsonl(os.path.join(out_dir, "probes.jsonl"), probes_records)
    _write_jsonl(os.path.join(out_dir, "injections.jsonl"), injections_records)
    _write_jsonl(os.path.join(out_dir, "compactions.jsonl"), compactions_records)
    _write_jsonl(os.path.join(out_dir, "rederivations.jsonl"), rederiv_records)
    _write_jsonl(os.path.join(out_dir, "nodes.jsonl"), nodes_records)
    _write_json(os.path.join(out_dir, "payload_shapes.json"), {})
    _write_hashes_json(out_dir, file_hashes)

    problems = _scan_primitives_dir(out_dir, forbidden)
    if problems:
        shutil.rmtree(out_dir, ignore_errors=True)
        raise LeakDetected(problems)

    return {"out_dir": out_dir, "run_doc": run_doc}


# --- `plateau absorb --check` ------------------------------------------------------------

def check_primitives(primitives_dir: str) -> Tuple[bool, List[str]]:
    """Re-runs the reproducible half of the leak check plus a schema/hash integrity
    check, using only what a primitives dir carries on its own (PLAN-absorb.md:
    "`--check` re-runs this using `hashes.json` and the forbidden-set digest stored in
    `run.json` ... so the check is reproducible without the raw").

    What IS re-verifiable without the raw: the structural rules (a code fence, or a
    `/a/b.ext`-shaped string, in any primitive value) -- these never depended on the raw
    in the first place; and `hashes.json`'s own internal consistency (`manifest_sha256`
    recomputes from its `raw_files` dict) and `run.json` carrying a well-formed
    `forbidden_digest`. What is NOT re-verifiable without the raw: membership in the
    original specific-string forbidden set built from receipt targets/node keys/probe
    text/etc, since storing that set would itself be exactly the leak this whole
    mechanism exists to prevent -- `--check` only confirms `run.json` recorded one
    (`forbidden_digest` is a 64-hex-char sha256) at absorb time, not that it still holds
    (that guarantee comes from `absorb` refusing to write leaking primitives in the
    first place, and from `--check`'s own structural rescan)."""
    problems: List[str] = []
    run_path = os.path.join(primitives_dir, "run.json")
    hashes_path = os.path.join(primitives_dir, "hashes.json")
    if not os.path.isfile(run_path):
        return False, ["missing run.json"]
    try:
        run_doc = _load_json(run_path)
    except (OSError, ValueError) as e:
        return False, ["run.json unreadable: {!r}".format(e)]

    digest = run_doc.get("forbidden_digest")
    if not (isinstance(digest, str) and re.fullmatch(r"[0-9a-f]{64}", digest)):
        problems.append("run.json.forbidden_digest missing or not a sha256 hex digest")
    if run_doc.get("source") not in ("experiment", "adapter"):
        problems.append("run.json.source must be 'experiment' or 'adapter'")

    if not os.path.isfile(hashes_path):
        problems.append("missing hashes.json")
    else:
        try:
            hashes_doc = _load_json(hashes_path)
        except (OSError, ValueError) as e:
            problems.append("hashes.json unreadable: {!r}".format(e))
            hashes_doc = None
        if hashes_doc is not None:
            raw_files = hashes_doc.get("raw_files") or {}
            recomputed = _sha256_text(
                "\n".join("{} {}".format(k, v) for k, v in sorted(raw_files.items()))
            )
            if recomputed != hashes_doc.get("manifest_sha256"):
                problems.append("hashes.json.manifest_sha256 does not match its own raw_files (tampered or corrupt)")
            for relpath_hash in raw_files:
                if not re.fullmatch(r"[0-9a-f]{64}", relpath_hash):
                    problems.append("hashes.json.raw_files key is not a sha256 hex digest: {!r}".format(relpath_hash))
                    break

    # structural leak rescan (fully reproducible without the raw): empty forbidden set,
    # code-fence + pathlike-string rules only.
    problems.extend(_scan_primitives_dir(primitives_dir, forbidden=set()))

    return (len(problems) == 0), problems


# --- CLI -----------------------------------------------------------------------------

def _print_summary(kind: str, result: Dict[str, Any]) -> None:
    run_doc = result["run_doc"]
    print("plateau absorb: wrote {} ({} source, run_id={})".format(result["out_dir"], kind, run_doc["run_id"]))
    print("  raw_files={} raw_sha256={} tarball_sha256={}".format(
        run_doc["raw_files"], run_doc["raw_sha256"][:16] + "...", run_doc.get("tarball_sha256")))
    if "derived" in result:
        print("  derived.json: {}".format(json.dumps(result["derived"], sort_keys=True)))
        if result.get("checked_against"):
            print("  recompute-link OK against {}".format(result["checked_against"]))


def main(argv: Optional[List[str]] = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    ap = argparse.ArgumentParser(prog="plateau absorb")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--raw", help="experiment raw dir or .tar.gz")
    src.add_argument("--store", help="adapter store dir (.plateau layout)")
    src.add_argument("--check", metavar="DIR", help="re-check an already-absorbed primitives dir")
    ap.add_argument("--run-id", help="required with --raw/--store")
    ap.add_argument("--experiment", default="d038", help="experiment name (--raw only; default d038)")
    ap.add_argument("--out", help="output primitives dir (required with --raw/--store)")
    args = ap.parse_args(argv)

    if args.check:
        ok, problems = check_primitives(args.check)
        if ok:
            print("plateau absorb --check: PASS ({})".format(args.check))
            return 0
        print("plateau absorb --check: FAIL ({})".format(args.check), file=sys.stderr)
        for p in problems:
            print("  {}".format(p), file=sys.stderr)
        return 1

    if not args.run_id or not args.out:
        print("plateau absorb: --run-id and --out are required with --raw/--store", file=sys.stderr)
        return 2

    try:
        if args.raw:
            result = absorb_experiment(args.raw, args.run_id, args.experiment, args.out)
            _print_summary("experiment", result)
        else:
            result = absorb_adapter(args.store, args.run_id, args.out)
            _print_summary("adapter", result)
    except (LeakDetected, RecomputeMismatch) as e:
        print("plateau absorb: FAILED: {}".format(e), file=sys.stderr)
        return 1
    except (FileNotFoundError, ValueError) as e:
        print("plateau absorb: {}".format(e), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
