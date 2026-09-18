#!/usr/bin/env python3
"""plateau.lab.promote — the promotion rule and `plateau learn` (docs/harness-0.3/
PLAN-step4.md "`plateau learn` and promotion").

The four constants immediately below are the WHOLE promotion policy. They are read by
`decide()` and nothing else in this module computes a threshold of its own; changing
what counts as "good enough to promote" means changing exactly these four numbers, in a
commit a human writes and reviews (see `.github/CODEOWNERS`, which lists this file for
`@aimerdoux`, and `.github/workflows/guardrails.yml`, which stops an automated PR from
touching it). Do not parameterize these from a config file, an environment variable, or
a CLI flag — that would let an automated `plateau learn` run change its own bar.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import subprocess
import sys
from typing import Any, Dict, List, Optional, Set, Tuple

from ..bridge import common as bridge_common
from . import ledger as ledger_mod
from . import model

try:
    import tomllib as _tomllib  # Python >= 3.11
except ImportError:  # pragma: no cover - exercised on 3.9/3.10
    _tomllib = None  # type: ignore[assignment]
from ..bridge import _toml

# --- the promotion rule (constants only a human commit changes) ----------------------

MIN_SESSIONS = 20      # per arm (incumbent AND canary), before `decide()` will judge at all
PI_GAIN = 0.15          # canary's presence_far_lag must exceed incumbent's by at least this
REDERIV_TOL = 0.05      # canary's rederivations/turn may regress by at most this fraction
TOKENS_TOL = 0.05       # canary's tokens/turn may regress by at most this fraction
RETIRE_AFTER = 60       # canary sessions without meeting the bar above -> "retire"


def decide(incumbent_stats: Dict[str, Any], canary_stats: Dict[str, Any]) -> str:
    """`"promote"` | `"keep"` | `"retire"`.

    Each stats dict (as `_arm_stats()` below builds them, and as a synthetic test dict
    must shape itself) carries:

        sessions            -- int, ledger session count for this arm (main agent only)
        rederivations_per_turn -- float, mean re-derivations/turn over the arm's sessions
        tokens_per_turn     -- float, mean (tokens_in + tokens_out)/turn
        presence_far_lag    -- float in [0, 1], or None if not enough far-lag probe data
                                to estimate it (compactions_crossed >= 2; see
                                `_arm_stats`'s docstring for exactly how it is fit)

    Logic:
      1. Either arm below `MIN_SESSIONS` -> not enough data to judge yet: `"retire"` if
         the canary has nonetheless run past `RETIRE_AFTER` sessions (a canary that
         cannot even accumulate `MIN_SESSIONS` in `RETIRE_AFTER` tries is not going
         anywhere), else `"keep"`.
      2. Both arms have enough data. Promote iff ALL of:
           - `presence_far_lag` is known for both arms, and the canary's exceeds the
             incumbent's by >= `PI_GAIN`;
           - the canary's `rederivations_per_turn` is no more than `REDERIV_TOL` worse
             (relatively) than the incumbent's;
           - the canary's `tokens_per_turn` is no more than `TOKENS_TOL` worse
             (relatively) than the incumbent's.
      3. Otherwise: `"retire"` once the canary has run `RETIRE_AFTER` sessions without
         clearing the bar, else `"keep"` (still worth collecting more data).
    """
    inc_n = int(incumbent_stats.get("sessions") or 0)
    can_n = int(canary_stats.get("sessions") or 0)

    if inc_n < MIN_SESSIONS or can_n < MIN_SESSIONS:
        return "retire" if can_n >= RETIRE_AFTER else "keep"

    promoted = False
    inc_pi = incumbent_stats.get("presence_far_lag")
    can_pi = canary_stats.get("presence_far_lag")
    if inc_pi is not None and can_pi is not None and (can_pi - inc_pi) >= PI_GAIN:
        if _within_tolerance(
            incumbent_stats.get("rederivations_per_turn"), canary_stats.get("rederivations_per_turn"), REDERIV_TOL
        ) and _within_tolerance(
            incumbent_stats.get("tokens_per_turn"), canary_stats.get("tokens_per_turn"), TOKENS_TOL
        ):
            promoted = True

    if promoted:
        return "promote"
    return "retire" if can_n >= RETIRE_AFTER else "keep"


def _within_tolerance(incumbent_value: Optional[float], canary_value: Optional[float], tol: float) -> bool:
    """True if `canary_value` is not worse (higher) than `incumbent_value` by more than
    the relative fraction `tol` — an improvement (canary lower) always passes. Unknown
    values are treated conservatively (fail) EXCEPT when the incumbent value is exactly
    0: a zero incumbent has nothing to regress relative to, so any canary value passes."""
    if incumbent_value is None or canary_value is None:
        return False
    if incumbent_value == 0:
        return True
    regression = (canary_value - incumbent_value) / incumbent_value
    return regression <= tol


# --- leak test -------------------------------------------------------------------------

_LEAK_COLUMN_TAGS = ("path", "symbol", "target", "key")


def body_leaks(body: str, ledger_conn: sqlite3.Connection) -> List[str]:
    """Every distinct string value in `ledger_conn` whose COLUMN NAME looks like it
    could carry a real filesystem path, code symbol, or receipt target (name contains
    "path", "symbol", "target", or "key", case-insensitive) that occurs verbatim as a
    substring of `body`. Introspects the connection's schema (`sqlite_master` +
    `PRAGMA table_info`) rather than hardcoding `.plateau/ledger.sqlite`'s own column
    names (`rederivations.path`, `sessions.handoff_path`), so the same check also works
    against a synthetic test connection or another store (e.g. the bridge receipt
    store's `receipts.target` / `nodes.key`) a caller passes it —
    docs/harness-0.3/PLAN-step4.md names the leak surface generically ("every string
    from the ledger's path/symbol/target columns"), not by exact schema position. Only
    matching-named columns are scanned: a numeric aggregate or an unrelated free-text
    column (e.g. `verdict`) is never a source of "leaked" strings, or nearly any body
    would fail the check on some short unrelated word. Values shorter than 3 characters
    are skipped (too likely to false-positive inside ordinary prose). `learn_main`
    refuses to write a body this returns anything non-empty for."""
    leaked: Set[str] = set()
    if not body:
        return []
    tables = [r[0] for r in ledger_conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()]
    for table in tables:
        cols = ledger_conn.execute(f"PRAGMA table_info({table})").fetchall()
        wanted = [c[1] for c in cols if any(tag in c[1].lower() for tag in _LEAK_COLUMN_TAGS)]
        for col in wanted:
            try:
                rows = ledger_conn.execute(
                    f"SELECT DISTINCT {col} FROM {table} WHERE {col} IS NOT NULL"
                ).fetchall()
            except sqlite3.Error:
                continue
            for (val,) in rows:
                if isinstance(val, str) and len(val) >= 3 and val in body:
                    leaked.add(val)
    return sorted(leaked)


# --- arm stats from the ledger ---------------------------------------------------------

_LAG_BUCKET_BOUNDS = (20_000, 60_000)  # same frozen boundaries as plateau.lab.fit/ledger
GRADE = {"exact": 1.0, "fuzzy": 0.5, "wrong": 0.0}
FAR_LAG_COMPACTIONS = 2  # "far-lag presence (>= 2 compactions crossed)" -- PLAN-step4.md


def _lag_bucket(lag_tokens: Optional[int]) -> int:
    lag_tokens = lag_tokens or 0
    if lag_tokens < _LAG_BUCKET_BOUNDS[0]:
        return 0
    if lag_tokens < _LAG_BUCKET_BOUNDS[1]:
        return 1
    return 2


def _mean(xs: List[Optional[float]]) -> Optional[float]:
    xs = [x for x in xs if x is not None]
    return (sum(xs) / len(xs)) if xs else None


def _mean_grade(rows: List[sqlite3.Row]) -> Optional[float]:
    grades = [GRADE[r["verdict"]] for r in rows if r["verdict"] in GRADE]
    return _mean(grades)


def _turn_counts(root: str, session_ids: List[str]) -> Dict[str, int]:
    store_path = os.path.join(root, bridge_common.DB_REL)
    if not session_ids or not os.path.isfile(store_path):
        return {}
    conn = bridge_common.db(root)
    try:
        return {
            sid: conn.execute("SELECT COUNT(*) FROM turns WHERE session_id=?", (sid,)).fetchone()[0]
            for sid in session_ids
        }
    finally:
        conn.close()


def _arm_stats(root: str, bridge_version: Optional[str]) -> Dict[str, Any]:
    """One arm's stats dict for `decide()` (see its docstring), computed from EVERY
    main-agent ledger session recorded under `bridge_version` -- incumbent and canary
    are told apart purely by this field (an operator setting up a canary must give
    `bridge.canary.toml` a `version` distinct from the incumbent `bridge.toml`'s, or
    their sessions collapse into one arm here; this module cannot detect that setup
    mistake on its own). `rederivations_per_turn`/`tokens_per_turn` are the per-session
    mean over ALL of the arm's sessions. `presence_far_lag` uses the SAME holdout split
    `plateau.lab.fit` does, but collapsed to the single "far lag" bucket
    (`compactions_crossed >= FAR_LAG_COMPACTIONS`) the promotion rule cares about: alpha
    from lag-bucket-0 grades across all of the arm's probes, `lambda` from its HOLDOUT
    probes' far-lag grades (native, unassisted recall), `pi` from its NON-holdout
    probes' far-lag grades via `plateau.lab.model.presence`."""
    empty = {"sessions": 0, "rederivations_per_turn": None, "tokens_per_turn": None, "presence_far_lag": None}
    if not bridge_version:
        return empty
    ledger_path = os.path.join(root, ledger_mod.LEDGER_REL)
    if not os.path.isfile(ledger_path):
        return empty

    conn = ledger_mod.db(root)
    conn.row_factory = sqlite3.Row
    try:
        sessions = conn.execute(
            "SELECT * FROM sessions WHERE agent='main' AND bridge_version=?", (bridge_version,)
        ).fetchall()
        session_ids = [r["session_id"] for r in sessions]
        probes: List[sqlite3.Row] = []
        if session_ids:
            qmarks = ",".join("?" for _ in session_ids)
            probes = conn.execute(
                f"SELECT * FROM probes WHERE session_id IN ({qmarks})", session_ids
            ).fetchall()
    finally:
        conn.close()

    if not sessions:
        return empty

    turn_counts = _turn_counts(root, session_ids)

    def per_session_mean(values_of) -> Optional[float]:
        return _mean(
            [values_of(r) / max(turn_counts.get(r["session_id"], 0), 1) for r in sessions]
        )

    rederiv_per_turn = per_session_mean(lambda r: r["rederivations"])
    tokens_per_turn = per_session_mean(lambda r: r["tokens_in"] + r["tokens_out"])

    holdout_ids = {r["session_id"] for r in sessions if (r["holdouts"] or 0) > 0}
    holdout_probes = [p for p in probes if p["session_id"] in holdout_ids]
    nonholdout_probes = [p for p in probes if p["session_id"] not in holdout_ids]

    presence_far: Optional[float] = None
    alpha = _mean_grade([p for p in probes if _lag_bucket(p["lag_tokens"]) == 0])
    if alpha:
        r_native_far = _mean_grade(
            [p for p in holdout_probes if (p["compactions_crossed"] or 0) >= FAR_LAG_COMPACTIONS]
        )
        r_bridge_far = _mean_grade(
            [p for p in nonholdout_probes if (p["compactions_crossed"] or 0) >= FAR_LAG_COMPACTIONS]
        )
        if r_native_far is not None and r_bridge_far is not None:
            lam_far = model.loss(alpha, r_native_far)
            presence_far = model.presence(alpha, lam_far, r_bridge_far)

    return {
        "sessions": len(sessions),
        "rederivations_per_turn": rederiv_per_turn,
        "tokens_per_turn": tokens_per_turn,
        "presence_far_lag": presence_far,
    }


# --- bridge.toml / bridge.canary.toml (version field only) ---------------------------

def _loads(text: str) -> Dict[str, Any]:
    if _tomllib is not None:
        try:
            return _tomllib.loads(text)
        except Exception:
            pass
    return _toml.loads(text)


def _read_version(path: str) -> Optional[str]:
    if not os.path.isfile(path):
        return None
    with open(path, "rb") as f:
        raw = f.read()
    cfg = _loads(raw.decode("utf-8"))
    v = cfg.get("version")
    return str(v) if v is not None else None


def _bump_minor(version: str) -> str:
    """`"2.0"` -> `"2.1"`; `"2.1.3"` -> `"2.2.0"`; anything not dotted-numeric-ish gets
    `"-promoted"` appended rather than raising (a canary's `version` string is free-form
    by nature -- see PLAN.md "Config": `version` is just `the toml's version key)."""
    parts = version.split(".")
    nums: List[Optional[int]] = []
    for p in parts:
        try:
            nums.append(int(p))
        except ValueError:
            nums.append(None)
    if len(nums) >= 2 and nums[0] is not None and nums[1] is not None:
        nums[1] += 1
        for i in range(2, len(nums)):
            nums[i] = 0
        return ".".join(str(n) for n in nums)
    if len(nums) == 1 and nums[0] is not None:
        return f"{nums[0]}.1"
    return version + "-promoted"


def _promote_canary(root: str, incumbent_version: str) -> Tuple[str, str]:
    """Write `bridge.canary.toml`'s content, with its `version` field replaced by the
    minor-bumped incumbent version, over `bridge.toml`; remove the canary file. Returns
    `(new_version, incumbent_path)`. Only the top-level `version = "..."` line is
    rewritten (a targeted substitution, not a general TOML re-serialization — every
    other key/table in the canary file is carried over byte-for-byte)."""
    incumbent_path = os.path.join(root, "bridge.toml")
    canary_path = os.path.join(root, "bridge.canary.toml")
    with open(canary_path, "rb") as f:
        raw = f.read()
    text = raw.decode("utf-8")
    new_version = _bump_minor(incumbent_version)
    new_text, n = re.subn(r'(?m)^version\s*=\s*"[^"]*"', f'version = "{new_version}"', text, count=1)
    if n == 0:
        new_text = f'version = "{new_version}"\n' + text
    with open(incumbent_path, "w", encoding="utf-8") as f:
        f.write(new_text)
    os.remove(canary_path)
    return new_version, incumbent_path


# --- PR body -----------------------------------------------------------------------

def _ledger_slice_hash(root: str, versions: List[str]) -> str:
    """sha256 of a canonical, deterministic JSON slice of `.plateau/ledger.sqlite`'s
    `sessions` rows for the arms under review — a proof that a specific private ledger
    state backed this decision, without the PR body containing any of that ledger's own
    strings (checked separately by `body_leaks`)."""
    ledger_path = os.path.join(root, ledger_mod.LEDGER_REL)
    if not os.path.isfile(ledger_path) or not versions:
        return hashlib.sha256(b"").hexdigest()
    conn = ledger_mod.db(root)
    conn.row_factory = sqlite3.Row
    try:
        qmarks = ",".join("?" for _ in versions)
        rows = conn.execute(
            f"SELECT session_id, agent_id, model_id, bridge_version, receipts, compactions, "
            f"injections_n, injections_chars, holdouts, rederivations, tokens_in, tokens_out, "
            f"cost_usd FROM sessions WHERE agent='main' AND bridge_version IN ({qmarks}) "
            f"ORDER BY session_id",
            versions,
        ).fetchall()
    finally:
        conn.close()
    slice_json = json.dumps([dict(r) for r in rows], sort_keys=True, default=str)
    return hashlib.sha256(slice_json.encode("utf-8")).hexdigest()


def _fmt(v: Any) -> str:
    if v is None:
        return "-"
    if isinstance(v, float):
        return f"{v:.4f}"
    return str(v)


def build_pr_body(
    new_version: str,
    incumbent_version: str,
    canary_version: str,
    incumbent_stats: Dict[str, Any],
    canary_stats: Dict[str, Any],
    ledger_slice_sha256: str,
) -> str:
    """The PR body `learn_main` writes to `proposals/promote-<version>.md`: aggregates
    only (session counts, means, margins, bucket tables) plus the private ledger
    slice's sha256 -- never a raw path, symbol, or session id (`body_leaks` is the
    enforcement of that; this function just avoids putting any there in the first
    place)."""
    pi_inc = incumbent_stats.get("presence_far_lag")
    pi_can = canary_stats.get("presence_far_lag")
    pi_gain = (pi_can - pi_inc) if (pi_inc is not None and pi_can is not None) else None

    lines = [
        f"# Promote {incumbent_version} -> {new_version}",
        "",
        f"Incumbent sessions: {incumbent_stats.get('sessions', 0)}    "
        f"Canary sessions: {canary_stats.get('sessions', 0)}",
        "",
        "| metric | incumbent | canary | margin |",
        "|---|---|---|---|",
        f"| presence (far lag, >= {FAR_LAG_COMPACTIONS} compactions crossed) "
        f"| {_fmt(pi_inc)} | {_fmt(pi_can)} | {_fmt(pi_gain)} (>= {PI_GAIN} required) |",
        f"| re-derivations / turn | {_fmt(incumbent_stats.get('rederivations_per_turn'))} "
        f"| {_fmt(canary_stats.get('rederivations_per_turn'))} "
        f"| tolerance {REDERIV_TOL} |",
        f"| tokens / turn | {_fmt(incumbent_stats.get('tokens_per_turn'))} "
        f"| {_fmt(canary_stats.get('tokens_per_turn'))} "
        f"| tolerance {TOKENS_TOL} |",
        "",
        f"Rule: `MIN_SESSIONS={MIN_SESSIONS}`, `PI_GAIN={PI_GAIN}`, "
        f"`REDERIV_TOL={REDERIV_TOL}`, `TOKENS_TOL={TOKENS_TOL}` "
        f"(`plateau/lab/promote.py`, changed only by a human commit).",
        "",
        f"Private ledger slice sha256: `{ledger_slice_sha256}`",
        "",
    ]
    return "\n".join(lines)


# --- `plateau learn` -----------------------------------------------------------------

def _open_pr(root: str, new_version: str, body_path: str) -> int:
    """`gh pr create` for the promotion, with `git`'s own `child_env()` scrubbing
    applied to the spawn (S4-A2: any process this package spawns should not inherit a
    Claude-Code-session identity it has no business carrying, `gh` included)."""
    branch = f"plateau/learn-{new_version}"
    env = bridge_common.child_env()
    try:
        subprocess.run(["git", "checkout", "-b", branch], cwd=root, env=env, check=True)
        subprocess.run(["git", "add", "bridge.toml", body_path], cwd=root, env=env, check=True)
        subprocess.run(
            ["git", "commit", "-m", f"plateau learn: promote to {new_version}"],
            cwd=root, env=env, check=True,
        )
        subprocess.run(["git", "push", "-u", "origin", branch], cwd=root, env=env, check=True)
        subprocess.run(
            [
                "gh", "pr", "create",
                "--title", f"plateau learn: promote bridge to {new_version}",
                "--body-file", body_path,
            ],
            cwd=root, env=env, check=True,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"plateau learn: --open-pr failed: {exc!r}", file=sys.stderr)
        return 1
    return 0


def learn_main(argv: Optional[List[str]] = None) -> int:
    """`plateau learn [--open-pr]`: compare the incumbent (`bridge.toml`) and canary
    (`bridge.canary.toml`) arms via `decide()`; on `"promote"`, write the canary's
    content over `bridge.toml` with a minor-bumped `version`, remove the canary file,
    and write the PR body to `proposals/promote-<version>.md` (aggregates + a ledger
    slice hash only — `body_leaks` refuses anything that leaks a raw ledger string). A
    PR is opened through `gh` only with `--open-pr`; by default this only writes the
    body. `"keep"`/`"retire"` print the arms' stats and do nothing else — this module
    never mutates `bridge.toml`/`bridge.canary.toml` on those outcomes."""
    argv = sys.argv[1:] if argv is None else argv
    ap = argparse.ArgumentParser(prog="plateau learn")
    ap.add_argument("--open-pr", action="store_true")
    ap.add_argument("--root", default=None)
    args = ap.parse_args(argv)

    root = args.root or bridge_common.root({})
    canary_path = os.path.join(root, "bridge.canary.toml")
    if not os.path.isfile(canary_path):
        print("plateau learn: no bridge.canary.toml -- nothing to evaluate")
        return 0

    incumbent_version = _read_version(os.path.join(root, "bridge.toml"))
    canary_version = _read_version(canary_path)
    if not incumbent_version or not canary_version:
        print("plateau learn: could not read `version` from bridge.toml / bridge.canary.toml", file=sys.stderr)
        return 1

    incumbent_stats = _arm_stats(root, incumbent_version)
    canary_stats = _arm_stats(root, canary_version)
    outcome = decide(incumbent_stats, canary_stats)

    print(f"plateau learn: incumbent={incumbent_version} ({incumbent_stats['sessions']} sessions)  "
          f"canary={canary_version} ({canary_stats['sessions']} sessions)  -> {outcome}")
    print(f"  presence_far_lag: incumbent={_fmt(incumbent_stats['presence_far_lag'])} "
          f"canary={_fmt(canary_stats['presence_far_lag'])}")
    print(f"  rederivations/turn: incumbent={_fmt(incumbent_stats['rederivations_per_turn'])} "
          f"canary={_fmt(canary_stats['rederivations_per_turn'])}")
    print(f"  tokens/turn: incumbent={_fmt(incumbent_stats['tokens_per_turn'])} "
          f"canary={_fmt(canary_stats['tokens_per_turn'])}")

    if outcome != "promote":
        return 0

    new_version, incumbent_path = _promote_canary(root, incumbent_version)
    ledger_slice_sha256 = _ledger_slice_hash(root, [incumbent_version, canary_version])
    body = build_pr_body(
        new_version, incumbent_version, canary_version, incumbent_stats, canary_stats, ledger_slice_sha256
    )

    ledger_path = os.path.join(root, ledger_mod.LEDGER_REL)
    if os.path.isfile(ledger_path):
        lconn = ledger_mod.db(root)
        try:
            leaks = body_leaks(body, lconn)
        finally:
            lconn.close()
        if leaks:
            print(
                "plateau learn: refusing to write proposals/promote-{}.md -- body leaks "
                "private ledger string(s): {}".format(new_version, ", ".join(leaks[:5])),
                file=sys.stderr,
            )
            return 1

    proposals_dir = os.path.join(root, "proposals")
    os.makedirs(proposals_dir, exist_ok=True)
    body_path = os.path.join(proposals_dir, f"promote-{new_version}.md")
    with open(body_path, "w", encoding="utf-8") as f:
        f.write(body)
    print(f"plateau learn: promoted -- {incumbent_path} updated to version {new_version}; "
          f"body written to {body_path}")

    if args.open_pr:
        return _open_pr(root, new_version, body_path)
    return 0


if __name__ == "__main__":
    sys.exit(learn_main())
