#!/usr/bin/env python3
"""plateau.ring — the private ring: a curated layer synced to an org-owned remote.

Owner C3 (docs/harness-0.3/PLAN-step4.md "Private ring"). Two things live here:

  * `.plateau/config.toml`'s `[private_ring]` table (`remote`, `key`) turns this on or
    off; the packaged template for that whole file is `plateau/bridge/config.default.toml`
    (this repo never carries a real `.plateau/config.toml` itself — see PLAN.md's ring
    table: "private (org)... never in this repo").
  * `curate(store_conn, curated_conn)`: folds a project's own receipt store
    (`plateau.bridge.common`, schema v1) into a small, portable `curated.sqlite` —
    files touched, fixes that resolved an error, decisions held, and receipt "shapes"
    (tool, kind, outcome) repeated often enough to be worth naming as a procedure —
    which is what actually gets pushed to the org-wide remote. `sync()` calls it once
    per run so `curated.sqlite` is always fresh right before it is published.

`plateau sync` (`sync_main`, wired by `plateau.cli` per S4-A4) is deliberately quiet
when the private ring is off: no remote configured, no key name configured, or the
named env var unset all print the single line `private ring: off` and exit 0 — this is
the common case (most checkouts of this repo have no org ring at all) and must never
look like an error.

Transport is plain `git`: the remote (a URL or, for tests, a local path — "path remotes
work without network") is cloned/fetched into a per-remote cache directory under
`~/.plateau/ring/<sha256(remote)>/`, and each calling project gets its own
sha256-keyed subdirectory there (`repo_key()`, derived from the project's own `origin`
remote, or its absolute path when it has none) so many projects can share one ring
remote without colliding. `key` names an env var holding a bearer token (never the
token itself, per PLAN-step4.md) that is folded into an `https://` remote URL only;
path and `ssh://`/`git@` remotes need no such rewriting and are used as-is.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
from typing import Any, Dict, List, Optional, Tuple

try:
    import tomllib as _tomllib  # Python >= 3.11
except ImportError:  # pragma: no cover - exercised on 3.9/3.10
    _tomllib = None  # type: ignore[assignment]

from .bridge import _toml

# --- .plateau/config.toml [private_ring] ---------------------------------------------


def _read_config_toml(root: str) -> Dict[str, Any]:
    """This project's `.plateau/config.toml`, parsed with `tomllib` when available and
    the bridge's own fallback parser otherwise (mirrors `plateau.lab.probes`'s own small
    reader of the same file — this module deliberately does not import
    `plateau.bridge.config`, whose `BridgeConfig` never carries `[private_ring]` at
    all). `{}` for a missing, unreadable, or unparseable file — never raises."""
    path = os.path.join(root, ".plateau", "config.toml")
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, "rb") as f:
            raw = f.read()
        text = raw.decode("utf-8")
    except OSError:
        return {}
    try:
        if _tomllib is not None:
            return _tomllib.loads(text)
        return _toml.loads(text)
    except Exception:
        return {}


def _private_ring_settings(root: str) -> Tuple[str, str]:
    """`(remote, key)` from `[private_ring]`, each `""` when the table, the file, or
    the individual key is missing."""
    cfg = _read_config_toml(root)
    section = cfg.get("private_ring") if isinstance(cfg, dict) else None
    if not isinstance(section, dict):
        return "", ""
    return str(section.get("remote") or ""), str(section.get("key") or "")


def status(root: str) -> str:
    """A one-line, human-readable private-ring status for `plateau doctor` — never
    prints the token's value, only whether its named env var is set."""
    remote, key_name = _private_ring_settings(root)
    if not remote:
        return "off (no remote configured)"
    if not key_name:
        return "off (no key configured)"
    if not os.environ.get(key_name):
        return "off (env {} not set)".format(key_name)
    return "on (remote configured, env {} set)".format(key_name)


# --- identity: which local cache dir, which subdirectory within it -------------------


def _origin_or_path(root: str) -> str:
    """This project's own `origin` remote URL, or its absolute path when it has none
    (a fresh repo, or no git repo at all) — the seed for `repo_key()`."""
    try:
        cp = subprocess.run(
            ["git", "remote", "get-url", "origin"], cwd=root,
            capture_output=True, text=True, timeout=5,
        )
        if cp.returncode == 0:
            out = cp.stdout.strip()
            if out:
                return out
    except (OSError, subprocess.SubprocessError):
        pass
    return os.path.abspath(root)


def repo_key(root: str) -> str:
    """sha256 hex of this project's own git identity — the subdirectory this project's
    `ledger.sqlite`/`curated.sqlite` live under inside the shared ring clone, so many
    projects can publish to the same ring remote without colliding."""
    return hashlib.sha256(_origin_or_path(root).encode("utf-8")).hexdigest()


def _ring_local_dir(remote: str) -> str:
    """`~/.plateau/ring/<sha256(remote)>/` — the local clone cache for one ring
    remote, shared by every project configured to use that same remote."""
    h = hashlib.sha256(remote.encode("utf-8")).hexdigest()
    return os.path.join(os.path.expanduser("~"), ".plateau", "ring", h)


# --- transport: plain git, path remotes work without network -------------------------


def _git(args: List[str], cwd: Optional[str] = None) -> Tuple[bool, str]:
    try:
        cp = subprocess.run(
            ["git"] + list(args), cwd=cwd, capture_output=True, text=True, timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return False, str(exc)
    return cp.returncode == 0, (cp.stdout or "") + (cp.stderr or "")


def _authed_remote(remote: str, token: str) -> str:
    """Fold `token` into an `https://` remote as `x-access-token:<token>@host/...`
    (GitHub-style); every other shape (a local path, `ssh://`, `git@host:...`, or an
    `https://` URL that already carries credentials) is returned unchanged — a path
    remote (what this module's own tests use) needs no rewriting at all."""
    if not token or "://" not in remote:
        return remote
    scheme, rest = remote.split("://", 1)
    if scheme != "https" or "@" in rest.split("/", 1)[0]:
        return remote
    return "{}://x-access-token:{}@{}".format(scheme, token, rest)


def _prepare_local_clone(remote: str, local_dir: str) -> None:
    """Clone/fetch `remote` into `local_dir`, landing on a local branch `main` (fast
    -forwarded from `origin/main` when the remote already has one). Never raises: a
    remote with no commits yet (a brand-new ring) fails the initial `clone`, in which
    case this starts a fresh local repo pointed at that remote instead — the first
    `_commit_and_push()` below is what actually seeds it."""
    if os.path.isdir(os.path.join(local_dir, ".git")):
        _git(["fetch", "--quiet", "origin"], cwd=local_dir)
    else:
        parent = os.path.dirname(local_dir) or os.path.expanduser("~")
        os.makedirs(parent, exist_ok=True)
        ok, _out = _git(["clone", "--quiet", remote, local_dir])
        if not ok:
            os.makedirs(local_dir, exist_ok=True)
            _git(["init", "--quiet", local_dir])
            _git(["remote", "add", "origin", remote], cwd=local_dir)
    _git(["checkout", "-B", "main"], cwd=local_dir)
    _git(["merge", "--ff-only", "origin/main"], cwd=local_dir)  # best-effort catch-up


def _commit_and_push(local_dir: str, rel_paths: List[str]) -> None:
    """Stage `rel_paths` (relative to `local_dir`) and push, only if something
    actually changed — an unmodified re-sync must never create an empty commit."""
    if not rel_paths:
        return
    _git(["add"] + rel_paths, cwd=local_dir)
    no_changes, _out = _git(["diff", "--cached", "--quiet"], cwd=local_dir)
    if no_changes:
        return
    _git(
        ["-c", "user.email=plateau@localhost", "-c", "user.name=plateau",
         "commit", "--quiet", "-m", "plateau sync"],
        cwd=local_dir,
    )
    _git(["push", "--quiet", "origin", "main"], cwd=local_dir)


_RING_FILES = ("ledger.sqlite", "curated.sqlite")


def sync(root: str) -> str:
    """Bring `<root>/.plateau/{ledger,curated}.sqlite` and the ring's own copy of them
    into agreement: pull down whichever of the two this checkout has never had locally
    (the "pull them on init" case in PLAN-step4.md), curate the local store into
    `curated.sqlite`, then push both up under this project's `repo_key()`. Returns a
    one-line human status; never raises — a git/network failure degrades to a
    best-effort no-op (the individual `_git` calls swallow their own errors), since
    `plateau sync` is a convenience command, never a hook that must not fail a turn."""
    remote, key_name = _private_ring_settings(root)
    if not remote or not key_name or not os.environ.get(key_name):
        return "private ring: off"

    token = os.environ.get(key_name, "")
    authed_remote = _authed_remote(remote, token)
    local_dir = _ring_local_dir(remote)
    _prepare_local_clone(authed_remote, local_dir)

    key = repo_key(root)
    ring_subdir = os.path.join(local_dir, key)
    os.makedirs(ring_subdir, exist_ok=True)

    plateau_dir = os.path.join(root, ".plateau")
    os.makedirs(plateau_dir, exist_ok=True)

    # Pull down whichever file this checkout has never had locally (fresh clone / new
    # machine): the ring's copy, when it exists, seeds the local one.
    for name in _RING_FILES:
        local_path = os.path.join(plateau_dir, name)
        ring_path = os.path.join(ring_subdir, name)
        if not os.path.isfile(local_path) and os.path.isfile(ring_path):
            shutil.copyfile(ring_path, local_path)

    _curate_local_store(root, plateau_dir)

    pushed: List[str] = []
    for name in _RING_FILES:
        local_path = os.path.join(plateau_dir, name)
        if os.path.isfile(local_path):
            shutil.copyfile(local_path, os.path.join(ring_subdir, name))
            pushed.append("/".join((key, name)))  # git wants forward slashes
    _commit_and_push(local_dir, pushed)

    return "private ring: synced {} file(s) via {}".format(len(pushed), local_dir)


def _curate_local_store(root: str, plateau_dir: str) -> None:
    """Refresh `curated.sqlite` from `index.sqlite` right before publishing — a nicety,
    never load-bearing for the transport above (any failure here is swallowed)."""
    store_path = os.path.join(plateau_dir, "index.sqlite")
    if not os.path.isfile(store_path):
        return
    try:
        from .bridge import common as bridge_common
        store_conn = bridge_common.db(root)
    except Exception:
        return
    try:
        curated_conn = curated_db(os.path.join(plateau_dir, "curated.sqlite"))
    except Exception:
        store_conn.close()
        return
    try:
        curate(store_conn, curated_conn)
    except Exception:
        pass
    finally:
        store_conn.close()
        curated_conn.close()


# --- curated.sqlite: schema + curate() -------------------------------------------------

_CURATED_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS files(
  path TEXT PRIMARY KEY, role TEXT, uses INTEGER DEFAULT 0, last_used INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS fixes(
  error TEXT PRIMARY KEY, fix TEXT, uses INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS decisions(
  text TEXT PRIMARY KEY, held INTEGER DEFAULT 0, uses INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS procedures(
  name TEXT PRIMARY KEY, receipt_shape TEXT, evidence_rids TEXT, uses INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY, v TEXT);
"""

# Constants (PLAN-step4.md "Private ring"): a receipt "shape" (tool, kind, outcome)
# repeated this many times or more is promoted to a named procedure; a `files` row
# left at `uses == 0` for this many curate() calls ("sessions" — the demotion clock
# lives in curated.sqlite's own `meta` table, one tick per call) is demoted.
PROCEDURE_MIN_REPEATS = 3
DEMOTE_AFTER_SESSIONS = 10
MAX_EVIDENCE_RIDS = 5


def curated_db(path: str) -> sqlite3.Connection:
    """Open (creating if needed) a `curated.sqlite` at `path` with the schema above."""
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    conn = sqlite3.connect(path, timeout=5)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.executescript(_CURATED_SCHEMA_SQL)
    conn.commit()
    return conn


def _bump_session_count(curated_conn: sqlite3.Connection) -> int:
    row = curated_conn.execute("SELECT v FROM meta WHERE k='session_count'").fetchone()
    n = (int(row[0]) if row and row[0] is not None else 0) + 1
    curated_conn.execute(
        "INSERT INTO meta(k, v) VALUES('session_count', ?) "
        "ON CONFLICT(k) DO UPDATE SET v=excluded.v",
        (str(n),),
    )
    return n


def _curate_files(store_conn: sqlite3.Connection, curated_conn: sqlite3.Connection, session_count: int) -> None:
    rows = store_conn.execute("SELECT key FROM nodes WHERE kind='file'").fetchall()
    for (path,) in rows:
        curated_conn.execute(
            "INSERT INTO files(path, role, uses, last_used) VALUES(?,?,1,?) "
            "ON CONFLICT(path) DO UPDATE SET uses=uses+1, last_used=excluded.last_used",
            (path, "file", session_count),
        )


def _curate_fixes(store_conn: sqlite3.Connection, curated_conn: sqlite3.Connection) -> None:
    """An error is "fixed" once its originating target later passed a test/command
    (the same notion `plateau.bridge.query.resolved_errors` and
    `plateau.bridge.handoff._open_errors` use); the fix text is that passing receipt's
    own detail (falling back to the target itself when the detail is empty)."""
    rows = store_conn.execute(
        "SELECT DISTINCT src, dst FROM edges WHERE rel='fails_with'"
    ).fetchall()
    for target, error_key in rows:
        passing = store_conn.execute(
            "SELECT detail FROM receipts WHERE target=? AND kind IN ('test','command') "
            "AND outcome='pass' ORDER BY id DESC LIMIT 1",
            (target,),
        ).fetchone()
        if not passing:
            continue
        fix_text = passing[0] or target
        curated_conn.execute(
            "INSERT INTO fixes(error, fix, uses) VALUES(?,?,1) "
            "ON CONFLICT(error) DO UPDATE SET fix=excluded.fix, uses=uses+1",
            (error_key, fix_text),
        )


def _curate_decisions(store_conn: sqlite3.Connection, curated_conn: sqlite3.Connection) -> None:
    rows = store_conn.execute("SELECT DISTINCT text FROM decisions").fetchall()
    for (text,) in rows:
        curated_conn.execute(
            "INSERT INTO decisions(text, held, uses) VALUES(?,1,1) "
            "ON CONFLICT(text) DO UPDATE SET uses=uses+1",
            (text,),
        )


def _curate_procedures(store_conn: sqlite3.Connection, curated_conn: sqlite3.Connection) -> None:
    """Promote a receipt "shape" — `(tool, kind, outcome)` — seen
    `>= PROCEDURE_MIN_REPEATS` times into a named `procedures` row, carrying up to
    `MAX_EVIDENCE_RIDS` of its most recent receipt ids as evidence."""
    rows = store_conn.execute(
        "SELECT tool, kind, outcome, GROUP_CONCAT(id) FROM receipts "
        "GROUP BY tool, kind, outcome HAVING COUNT(*) >= ?",
        (PROCEDURE_MIN_REPEATS,),
    ).fetchall()
    for tool, kind, outcome, ids_csv in rows:
        name = "{}:{}:{}".format(tool, kind, outcome)
        ids = [int(x) for x in (ids_csv or "").split(",") if x][-MAX_EVIDENCE_RIDS:]
        shape = json.dumps({"tool": tool, "kind": kind, "outcome": outcome})
        curated_conn.execute(
            "INSERT INTO procedures(name, receipt_shape, evidence_rids, uses) VALUES(?,?,?,1) "
            "ON CONFLICT(name) DO UPDATE SET receipt_shape=excluded.receipt_shape, "
            "evidence_rids=excluded.evidence_rids, uses=uses+1",
            (name, shape, json.dumps(ids)),
        )


def _demote_unused_files(curated_conn: sqlite3.Connection, session_count: int) -> None:
    curated_conn.execute(
        "DELETE FROM files WHERE uses = 0 AND (? - last_used) >= ?",
        (session_count, DEMOTE_AFTER_SESSIONS),
    )


def curate(store_conn: sqlite3.Connection, curated_conn: sqlite3.Connection) -> None:
    """Fold `store_conn` (a `plateau.bridge.common` receipt store, schema v1) into
    `curated_conn` (schema above). One call is one "session" tick for the demotion
    clock (tracked in `curated_conn`'s own `meta` table, so this never needs the
    caller to pass a session id or count):

      * every `file` node touches a `files` row (`uses += 1`, `last_used` = this tick);
      * every `(tool, kind, outcome)` receipt shape seen `>= 3` times overall is
        promoted to (or refreshed in) `procedures`;
      * every resolved error/decision is folded into `fixes`/`decisions`;
      * a `files` row still at `uses == 0` after `>= 10` ticks is demoted (deleted) —
        it was curated once, speculatively, and never used again.

    Commits `curated_conn` before returning; never touches `store_conn`."""
    session_count = _bump_session_count(curated_conn)
    _curate_files(store_conn, curated_conn, session_count)
    _curate_fixes(store_conn, curated_conn)
    _curate_decisions(store_conn, curated_conn)
    _curate_procedures(store_conn, curated_conn)
    _demote_unused_files(curated_conn, session_count)
    curated_conn.commit()


# --- CLI: `plateau sync` --------------------------------------------------------------


def _repo_root_git_toplevel_or_cwd() -> str:
    try:
        cp = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True, timeout=5,
        )
        if cp.returncode == 0:
            top = cp.stdout.strip()
            if top:
                return top
    except (OSError, subprocess.SubprocessError):
        pass
    return os.getcwd()


def sync_main(argv: Optional[List[str]] = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    ap = argparse.ArgumentParser(prog="plateau sync", add_help=True)
    ap.add_argument("--root", default=None, help=argparse.SUPPRESS)  # testing hook
    args = ap.parse_args(argv)
    root = args.root or _repo_root_git_toplevel_or_cwd()
    print(sync(root))
    return 0


if __name__ == "__main__":
    sys.exit(sync_main())
