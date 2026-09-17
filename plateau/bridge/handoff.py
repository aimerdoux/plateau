#!/usr/bin/env python3
"""plateau.bridge.handoff — session handoff blocks (v1).

A handoff block is a small, self-contained snapshot of where a session's receipt graph
stands: git identity, store cursor, the last injection, the last snapshot, what is still
open (unresolved errors / failing tests), recent decisions, and two ready-to-paste
commands (`lookup`, `continue`) for whoever (or whichever agent) picks the session back
up. It is deliberately its OWN small reader of the store: `build()` talks to
`<root>/.plateau/index.sqlite` with `sqlite3` directly, using the schema v1 table and
column names in `docs/harness-0.3/PLAN.md` ("Store schema v1"), rather than importing
`plateau.bridge.common`. That keeps this module usable (falling back to zeroed counts
and `none` values) even when the store does not exist yet, and keeps it decoupled from
the rest of the bridge package's own development.

See `docs/harness-0.3/PLAN.md` "Handoff block v1" for the exact contract: the `build`/
`render`/`write`/`last`/`main` signatures, the store-schema-v1 field mapping, and the
literal `<plateau_handoff v=1>` text format `render()` must reproduce byte-for-byte.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import subprocess
import sys
from typing import Any, Dict, List, Optional, Tuple

from ..integrity import file_hash

# Where the store lives, relative to `root`. Handoff v1 has no legacy (`d037_hooks/`)
# counterpart and so — unlike `plateau.bridge.common.DB_REL` — takes no PLATEAU_DB_REL
# env override: it always reads the current, public `.plateau/` layout.
DB_REL = ".plateau/index.sqlite"
SCHEMA = 1  # the schema version this reader understands (see PLAN.md "Store schema v1")

_TOKEN_SPLIT_RE = re.compile(r"[/\\:._\-\s]+")


# --- git facts ----------------------------------------------------------------------

def _run_git(args: List[str], cwd: str) -> Optional[str]:
    """`git <args>` in `cwd`; stripped stdout on success, else None (never raises)."""
    try:
        proc = subprocess.run(
            ["git"] + list(args), cwd=cwd, capture_output=True, text=True, timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    out = proc.stdout.strip()
    return out or None


def _git_facts(root: str) -> Dict[str, Optional[str]]:
    """`repo` (the `origin` remote url, or `root` itself when there is none), `branch`,
    and a short `commit` sha — each `None` when `root` is not a git repo, and `commit`
    (or, rarely, `branch`) still `None` on a repo with no commits yet (unborn HEAD)."""
    if _run_git(["rev-parse", "--is-inside-work-tree"], root) != "true":
        return {"repo": None, "branch": None, "commit": None}
    remote = _run_git(["remote", "get-url", "origin"], root)
    branch = _run_git(["symbolic-ref", "--short", "HEAD"], root)
    if branch is None:
        branch = _run_git(["rev-parse", "--abbrev-ref", "HEAD"], root)
    commit = _run_git(["rev-parse", "--short", "HEAD"], root)
    return {"repo": remote or root, "branch": branch, "commit": commit}


# --- store access (schema v1, direct sqlite3 — see module docstring) ----------------

def _connect(root: str) -> Optional[sqlite3.Connection]:
    path = os.path.join(root, DB_REL)
    if not os.path.isfile(path):
        return None
    try:
        return sqlite3.connect(path, timeout=5)
    except sqlite3.Error:
        return None


def _first_token(key: str) -> str:
    """The first token of a node key, splitting on path/identifier separators (used
    only to seed the `lookup:` hint words — not a scoring tokenizer)."""
    for part in _TOKEN_SPLIT_RE.split(key or ""):
        if part:
            return part
    return key or ""


def _open_errors(conn: sqlite3.Connection, session_id: str) -> List[str]:
    """Error node keys with no LATER passing test/command on their originating target
    (mirrors `plateau.bridge.query.resolved_errors`'s notion of "resolved", reimplemented
    here directly so this module never imports the rest of the bridge package)."""
    open_keys: List[str] = []
    try:
        error_rows = conn.execute(
            "SELECT key, last_rid FROM nodes WHERE session_id=? AND kind='error'",
            (session_id,),
        ).fetchall()
    except sqlite3.Error:
        return open_keys
    for error_key, last_rid in error_rows:
        resolved = False
        try:
            targets = conn.execute(
                "SELECT DISTINCT src FROM edges WHERE rel='fails_with' AND dst=?",
                (error_key,),
            ).fetchall()
        except sqlite3.Error:
            targets = []
        for (target,) in targets:
            try:
                passed = conn.execute(
                    "SELECT 1 FROM receipts WHERE session_id=? AND target=? "
                    "AND kind IN ('test','command') AND outcome='pass' AND id>? LIMIT 1",
                    (session_id, target, last_rid),
                ).fetchone()
            except sqlite3.Error:
                passed = None
            if passed:
                resolved = True
                break
        if not resolved:
            open_keys.append(error_key)
    return open_keys


def build(
    root: str, session_id: str, agent: str = "main", parent: str = "", agent_id: str = "",
) -> Dict[str, Any]:
    """Assemble a handoff block for `session_id` from `<root>/.plateau/index.sqlite`
    (schema v1) and git. If the store does not exist yet, every count is 0 and every
    store-derived value is `None` (renders as `none`) — this never raises.

    `agent_id`, when given, is carried in the returned dict as an extra `agent_id` key
    that `render()` never prints (it is not part of the `<plateau_handoff v=1>` text
    format) — `write()` uses it alone to key a SUBAGENT write to a path that cannot
    collide with the main file's (S3-A1, docs/harness-0.3/PLAN-step3.md "Amendments
    after preflight run 1"). Round-trips through `json.dumps`/`json.loads` like every
    other field here."""
    facts = _git_facts(root)
    conn = _connect(root)

    bridge_version: Optional[str] = None
    bridge_sha: Optional[str] = None
    cursor: Optional[int] = None
    receipts_n = 0
    compactions_n = 0
    last_injection: Optional[Dict[str, Any]] = None
    snapshot_block: Dict[str, Optional[str]] = {"path": None, "sha256": None}
    open_block: Dict[str, List[str]] = {"errors": [], "tests": []}
    decisions_block: Dict[str, Any] = {"count": 0, "last": []}
    lookup_words: List[str] = []

    if conn is not None:
        try:
            row = conn.execute(
                "SELECT bridge_version, bridge_sha FROM receipts WHERE session_id=? "
                "ORDER BY id DESC LIMIT 1", (session_id,),
            ).fetchone()
            if row:
                bridge_version, bridge_sha = row[0], row[1]

            row = conn.execute(
                "SELECT MAX(id) FROM receipts WHERE session_id=?", (session_id,)
            ).fetchone()
            cursor = row[0] if row and row[0] is not None else None

            row = conn.execute(
                "SELECT COUNT(*) FROM receipts WHERE session_id=?", (session_id,)
            ).fetchone()
            receipts_n = row[0] if row and row[0] is not None else 0

            row = conn.execute(
                "SELECT COUNT(*) FROM compactions WHERE session_id=?", (session_id,)
            ).fetchone()
            compactions_n = row[0] if row and row[0] is not None else 0

            row = conn.execute(
                "SELECT id, chars, holdout, bridge_version, bridge_sha, rid_at FROM injections "
                "WHERE session_id=? ORDER BY id DESC LIMIT 1", (session_id,),
            ).fetchone()
            if row:
                inj_id, chars, holdout, inj_version, inj_sha, rid_at = row
                # `rid` is the receipt CURSOR at injection time (injections.rid_at),
                # not this row's own auto-increment id -- fall back to the id only for
                # a row written before rid_at existed (NULL there).
                cursor_rid = rid_at if rid_at is not None else inj_id
                last_injection = {"rid": cursor_rid, "chars": chars, "holdout": bool(holdout)}
                if bridge_version is None:
                    bridge_version, bridge_sha = inj_version, inj_sha

            row = conn.execute(
                "SELECT snapshot FROM compactions WHERE session_id=? ORDER BY k DESC LIMIT 1",
                (session_id,),
            ).fetchone()
            if row and row[0]:
                snap_path = row[0]
                snapshot_block["path"] = (
                    os.path.relpath(snap_path, root) if os.path.isabs(snap_path) else snap_path
                )
                try:
                    if os.path.isfile(snap_path):
                        snapshot_block["sha256"] = file_hash(snap_path)
                except OSError:
                    pass

            open_block["errors"] = _open_errors(conn, session_id)
            test_rows = conn.execute(
                "SELECT key FROM nodes WHERE session_id=? AND kind='test' AND last_outcome='fail'",
                (session_id,),
            ).fetchall()
            open_block["tests"] = [r[0] for r in test_rows]

            row = conn.execute(
                "SELECT COUNT(*) FROM decisions WHERE session_id=?", (session_id,)
            ).fetchone()
            decisions_block["count"] = row[0] if row and row[0] is not None else 0
            last_rows = conn.execute(
                "SELECT id FROM decisions WHERE session_id=? ORDER BY id DESC LIMIT 3",
                (session_id,),
            ).fetchall()
            decisions_block["last"] = [r[0] for r in last_rows]

            top_nodes = conn.execute(
                "SELECT key FROM nodes WHERE session_id=? ORDER BY degree DESC, last_rid DESC LIMIT 3",
                (session_id,),
            ).fetchall()
            lookup_words = [_first_token(r[0]) for r in top_nodes]
        except sqlite3.Error:
            pass
        finally:
            conn.close()

    lookup = "plateau lookup " + " ".join(lookup_words) if lookup_words else "plateau lookup"
    continue_cmd = "plateau resume {}".format(session_id) if session_id else None

    return {
        "repo": facts["repo"],
        "branch": facts["branch"],
        "commit": facts["commit"],
        "store": DB_REL,
        "schema": SCHEMA,
        "bridge_version": bridge_version,
        "bridge_sha": bridge_sha,
        "session": session_id or None,
        "parent": parent or None,
        "agent": agent,
        "agent_id": agent_id or None,
        "cursor": cursor,
        "receipts": receipts_n,
        "compactions": compactions_n,
        "last_injection": last_injection,
        "snapshot": snapshot_block,
        "open": open_block,
        "decisions": decisions_block,
        "lookup": lookup,
        "continue": continue_cmd,
    }


# --- rendering ------------------------------------------------------------------------

def _none(value: Any) -> str:
    return "none" if value is None else str(value)


def _short_sha(sha: Optional[str]) -> str:
    if not sha:
        return "none"
    return sha[:8]


def render(block: Dict[str, Any]) -> str:
    """Exactly the `<plateau_handoff v=1>` text format (PLAN.md "Handoff block v1"):
    one line per field, three spaces between same-line fields, no narrative. Missing
    values render as the literal `none`. `render(json.loads(json.dumps(build(...))))`
    equals `render(build(...))` — every value here is plain JSON-safe data."""
    lines = ["<plateau_handoff v=1>"]

    lines.append(
        "repo: {}   branch: {}   commit: {}".format(
            _none(block.get("repo")), _none(block.get("branch")), _none(block.get("commit"))
        )
    )

    sha_short = _short_sha(block.get("bridge_sha"))
    lines.append(
        "store: {}   schema: {}   bridge: {} ({})".format(
            block.get("store") or DB_REL, _none(block.get("schema")),
            _none(block.get("bridge_version")), sha_short,
        )
    )

    lines.append(
        "session: {}   parent: {}   agent: {}".format(
            _none(block.get("session")), _none(block.get("parent")), _none(block.get("agent"))
        )
    )

    cursor = block.get("cursor")
    cursor_text = "r{}".format(cursor) if cursor is not None else "none"
    lines.append(
        "cursor: {}   receipts: {}   compactions: {}".format(
            cursor_text, _none(block.get("receipts")), _none(block.get("compactions"))
        )
    )

    last_injection = block.get("last_injection")
    if last_injection:
        rid = last_injection.get("rid")
        rid_text = "r{}".format(rid) if rid is not None else "none"
        holdout = "yes" if last_injection.get("holdout") else "no"
        lines.append(
            "last_injection: {}, {} chars, holdout: {}".format(
                rid_text, _none(last_injection.get("chars")), holdout
            )
        )
    else:
        lines.append("last_injection: none")

    snapshot = block.get("snapshot") or {}
    snap_hash = snapshot.get("sha256")
    if snap_hash and ":" in snap_hash:
        snap_hash = snap_hash.split(":", 1)[1]
    lines.append("snapshot: {}   sha256: {}".format(_none(snapshot.get("path")), _none(snap_hash)))

    open_block = block.get("open") or {}
    errors = open_block.get("errors") or []
    tests = open_block.get("tests") or []
    lines.append(
        "open: {}, {}".format(
            ", ".join(errors) if errors else "none",
            ", ".join(tests) if tests else "none",
        )
    )

    decisions = block.get("decisions") or {}
    last_ids = decisions.get("last") or []
    last_text = ", ".join("d{}".format(i) for i in last_ids) if last_ids else "none"
    lines.append("decisions: {}, last: {}".format(_none(decisions.get("count", 0)), last_text))

    lines.append("lookup: {}".format(block.get("lookup") or "plateau lookup"))
    lines.append("continue: {}".format(_none(block.get("continue"))))

    lines.append("</plateau_handoff>")
    return "\n".join(lines)


_SUBAGENT_ID_SAFE_RE = re.compile(r"[^A-Za-z0-9_.-]+")


def _handoff_filename(block: Dict[str, Any]) -> str:
    """S3-A1 (docs/harness-0.3/PLAN-step3.md "Amendments after preflight run 1"): the
    main agent's handoff lands at `<session_id>.json`; a SUBAGENT's (block carries a
    non-empty `agent_id`) lands at `<session_id>.subagent-<agent_id>.json` instead --
    a DIFFERENT path from the main file's, so a later `SessionEnd` write for the same
    `session_id` (which Claude Code, per the preflight run, may hand the *same*
    `session_id` a subagent's own events carried) can never clobber a `SubagentStop`
    write, and vice versa, no matter which one lands second."""
    session_id = block.get("session") or "unknown"
    agent_id = block.get("agent_id")
    if agent_id:
        safe_id = _SUBAGENT_ID_SAFE_RE.sub("_", str(agent_id))
        return "{}.subagent-{}.json".format(session_id, safe_id)
    return "{}.json".format(session_id)


def write(root: str, block: Dict[str, Any]) -> str:
    """Write `block` as JSON under `.plateau/handoff/`; returns that path. See
    `_handoff_filename` for the main-vs-subagent path split (S3-A1)."""
    dir_path = os.path.join(root, ".plateau", "handoff")
    os.makedirs(dir_path, exist_ok=True)
    path = os.path.join(dir_path, _handoff_filename(block))
    with open(path, "w", encoding="utf-8") as f:
        json.dump(block, f, indent=2, sort_keys=True)
        f.write("\n")
    return path


def last(root: str) -> Optional[Dict[str, Any]]:
    """The most recently WRITTEN MAIN handoff block under `.plateau/handoff/` (S3-A1:
    `--last` PREFERS the main `<session_id>.json` file over any
    `<session_id>.subagent-<id>.json` file, even one written more recently -- a caller
    resuming a session almost always wants the parent's own view, not one particular
    subagent's); falls back to the newest subagent file only when no main file exists
    at all. None if the directory is missing/empty/unreadable."""
    dir_path = os.path.join(root, ".plateau", "handoff")
    if not os.path.isdir(dir_path):
        return None
    main_candidates: List[Tuple[float, str]] = []
    subagent_candidates: List[Tuple[float, str]] = []
    for name in os.listdir(dir_path):
        if not name.endswith(".json"):
            continue
        full = os.path.join(dir_path, name)
        try:
            mtime = os.path.getmtime(full)
        except OSError:
            continue
        bucket = subagent_candidates if ".subagent-" in name else main_candidates
        bucket.append((mtime, full))
    candidates = main_candidates or subagent_candidates
    if not candidates:
        return None
    candidates.sort(key=lambda pair: pair[0])
    newest_path = candidates[-1][1]
    try:
        with open(newest_path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


# --- CLI --------------------------------------------------------------------------

def _read_optional_payload() -> Dict[str, Any]:
    """The hook-style JSON payload on stdin, if any — never blocks on an interactive
    terminal, never raises. `{}` when there is none (`plateau handoff --print` run
    bare has no payload at all: this is entirely normal, not an error)."""
    try:
        if sys.stdin.isatty():
            return {}
        data = sys.stdin.read()
        if not data or not data.strip():
            return {}
        parsed = json.loads(data)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def _resolve_root() -> str:
    """`git rev-parse --show-toplevel` of the current directory, else the current
    directory itself."""
    cwd = os.getcwd()
    return _run_git(["rev-parse", "--show-toplevel"], cwd) or cwd


def _resolve_agent(explicit: Optional[str], payload: Dict[str, Any]) -> str:
    """The `--agent` CLI flag wins whenever it is more specific than the generic
    `subagent` marker that `hooks.json`'s static SubagentStop entry hard-codes (it
    cannot embed a runtime name); otherwise prefer whatever the hook payload itself
    identifies (`common.agent_of`), and fall back to the literal flag (or `main`)."""
    payload_agent = "main"
    try:
        from . import common as _common
        payload_agent = _common.agent_of(payload)
    except Exception:
        pass
    if explicit and explicit != "subagent":
        return explicit
    if payload_agent != "main":
        return payload_agent
    return explicit or payload_agent


def _resolve_parent(explicit: Optional[str], payload: Dict[str, Any], session_id: str) -> str:
    """The `--parent` CLI flag wins. Otherwise, for a SubagentStop-style payload
    (carries `agent_type` and/or `agent_id`), S3-A1 sets `parent` to this call's own
    `session_id` — Claude Code, per the preflight run, does not mint a distinct
    `session_id` for a subagent's own hook events, so the block's `session` and
    `parent` fields read the same value on purpose (that IS the payload's actual
    identity; a future Claude Code version handing subagents a truly distinct id would
    make this the subagent's *own* id and `session_id` its parent's, unchanged code).
    Otherwise `PLATEAU_RESUME_FROM` (set by `plateau resume` on the fresh session it
    launches) names the session this one continues."""
    if explicit:
        return explicit
    if payload.get("agent_type") or payload.get("agent_id"):
        return session_id or ""
    return os.environ.get("PLATEAU_RESUME_FROM", "") or str(payload.get("parent_session_id") or "")


def _resolve_agent_id(agent: str, payload: Dict[str, Any]) -> str:
    """The filename-safe id `write()` uses to key a subagent's handoff to a path that
    cannot collide with its parent's (S3-A1): empty for a main-agent write; otherwise
    `payload["agent_id"]` (the opaque per-instance id), falling back to `agent_type` /
    `agent_name` when a payload somehow lacks `agent_id` but is still identifiably a
    subagent (`agent` already resolved to `subagent:<name>` by `_resolve_agent`)."""
    if not agent.startswith("subagent:"):
        return ""
    return str(
        payload.get("agent_id") or payload.get("agent_type") or payload.get("agent_name") or ""
    ).strip()


def main(argv: Optional[List[str]] = None) -> None:
    argv = sys.argv[1:] if argv is None else argv
    ap = argparse.ArgumentParser(prog="plateau handoff")
    ap.add_argument("--print", action="store_true", dest="do_print")
    ap.add_argument("--write", action="store_true", dest="do_write")
    ap.add_argument("--last", action="store_true", dest="do_last")
    ap.add_argument("--agent", default=None)
    ap.add_argument("--parent", default=None)
    args = ap.parse_args(argv)

    root = _resolve_root()

    if args.do_last:
        block = last(root)
        print("(no handoff blocks written yet)" if block is None else render(block))
        return

    payload = _read_optional_payload()
    session_id = payload.get("session_id") or ""
    agent = _resolve_agent(args.agent, payload)
    parent = _resolve_parent(args.parent, payload, session_id)
    agent_id = _resolve_agent_id(agent, payload)
    block = build(root, session_id, agent=agent, parent=parent, agent_id=agent_id)

    wrote_path = write(root, block) if args.do_write else None

    if args.do_print:
        # Stop's hook contract (PLAN-step3.md "hooks.json (plugin)"): the handoff block
        # is the systemMessage, so it is the LAST thing shown in the turn.
        print(json.dumps({"systemMessage": render(block)}))
    elif wrote_path:
        print(wrote_path)
    else:
        print(render(block))


if __name__ == "__main__":
    main()
