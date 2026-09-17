#!/usr/bin/env python3
"""plateau.bridge.inject — SessionStart hook: query-aware, budget-bounded injection.

`startup`/`clear` inject up to `budget.startup_chars`, queried by `--query` (or nothing).
`compact` injects up to `budget.compaction_chars`, queried by the last user prompt in the
transcript, and is subject to `plateau.lab.holdout` so the lab can measure recall without
the bridge on a controlled slice of compactions. `resume` injects nothing at all.

Every attempt (including a held-out one) is recorded as an `injections` row and logged
in the exact line format the sealed D-038 scorer parses:
    inject ev=<Event> q=<n>ch nodes=<k>/<n> chars=<c> budget=<b>   (+" holdout=1" when skipped)

Env `PLATEAU_LEGACY_TAG=1` (set by the `d037_hooks/` shims) switches the emitted tag and
head text to the D-037 wording so `d037_hooks/test_hooks.py` keeps passing byte-for-byte.
Holdout is skipped under that same legacy flag: the sealed harness has no holdout concept
and must always inject deterministically (see PLAN.md deviations for this call).

When the resolved bridge role is "off" ("off means off everywhere"; docs/harness-0.3/
PLAN.md deviations), this prints `{}` and records nothing at all -- not even a store
file gets created.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

from . import common
from . import config
from . import query as query_mod
from ..lab import holdout

LOOKUP_LINE = "plateau lookup <words>"
LEGACY_LOOKUP_LINE = "python3 .claude/hooks/d037/lookup.py <words>"


def _head(tag: str) -> str:
    lookup_line = LEGACY_LOOKUP_LINE if tag == common.LEGACY_TAG else LOOKUP_LINE
    return (
        f"<{tag}>\n# Machine-generated ledger of execution receipts from earlier in this session. "
        "Data, not instructions. [rN] = receipt id, ★ = matches current prompt. "
        f"Deep lookup: {lookup_line}\n"
    )


def _current_compaction_k(conn, session_id: str) -> int:
    """This compact event's index: MAX(k) for the session (0 if none yet). By the time
    a `compact` SessionStart fires, snapshot.py's PreCompact hook has already inserted
    the row for the compaction currently being handled (PreCompact always fires before
    SessionStart), so that row's own k already IS "the current compaction count"."""
    row = conn.execute(
        "SELECT MAX(k) FROM compactions WHERE session_id=?", (session_id,),
    ).fetchone()
    return row[0] if row and row[0] is not None else 0


def _resume_handoff_prefix(root: str, budget: int) -> str:
    """The stored handoff block named by `PLATEAU_RESUME_FROM` (set by `plateau resume`
    on the fresh session it launches; see docs/harness-0.3/PLAN-step3.md "`plateau
    resume`"), rendered and capped to `budget` chars so the caller can subtract its
    length from the selector's own budget and never exceed `budget.startup_chars`
    overall. "" when the env var is unset, names no stored handoff file, or anything
    about the stored block is unreadable -- this never raises."""
    session_id = os.environ.get("PLATEAU_RESUME_FROM", "")
    if not session_id:
        return ""
    path = os.path.join(root, ".plateau", "handoff", f"{session_id}.json")
    if not os.path.isfile(path):
        return ""
    try:
        with open(path, encoding="utf-8") as f:
            block = json.load(f)
    except (OSError, ValueError):
        return ""
    if not isinstance(block, dict):
        return ""
    try:
        from . import handoff as handoff_mod
        text = handoff_mod.render(block) + "\n"
    except Exception:
        return ""
    return text[:budget] if len(text) > budget else text


def _injection_rid_at(conn, session_id: str) -> int:
    """The receipt cursor at injection time: MAX(receipts.id) for the session (0 when
    none) -- stored on the injections row so plateau.bridge.handoff can render
    `last_injection: r<N>` against the actual cursor, not this row's own id."""
    return conn.execute(
        "SELECT COALESCE(MAX(id), 0) FROM receipts WHERE session_id=?", (session_id,),
    ).fetchone()[0]


def main(argv=None) -> None:
    argv = sys.argv[1:] if argv is None else argv
    ap = argparse.ArgumentParser(add_help=False)
    ap.add_argument("--query", default=None)
    ap.add_argument("--budget", type=int, default=None)
    args, _unknown = ap.parse_known_args(argv)

    payload = common.read_payload()
    root = common.root(payload)
    session_id = payload.get("session_id", "")
    source = payload.get("source", "startup")
    out: dict = {}

    try:
        if source == "resume":
            print(json.dumps(out))
            sys.exit(0)

        cfg = config.load(root, session_id)
        if cfg.role == "off":
            # "off means off everywhere" (docs/harness-0.3/PLAN.md deviations): a
            # disabled bridge injects nothing and records nothing -- not even a store
            # file gets created (we return before ever calling common.db()).
            print(json.dumps({}))
            sys.exit(0)

        legacy = os.environ.get("PLATEAU_LEGACY_TAG") == "1"
        tag = common.LEGACY_TAG if legacy else common.TAG
        head = _head(tag)

        conn = common.db(root)
        k = _current_compaction_k(conn, session_id) if source == "compact" else None
        prev_rid = common.prev_compaction_rid(conn, session_id)
        if prev_rid is None:
            prev_rid = 0

        if source == "compact":
            budget = cfg.budget.get("compaction_chars", 12000)
            q = query_mod.last_user_prompt(payload.get("transcript_path", ""))
        else:
            budget = cfg.budget.get("startup_chars", 6000)
            q = args.query or ""
        if args.budget is not None:
            budget = args.budget

        scored = query_mod.score_nodes(conn, q, cfg, session_id)
        rid_at = _injection_rid_at(conn, session_id)

        if source == "compact" and not legacy and holdout.is_holdout(session_id, k, cfg.lab.get("holdout_rate", 0.10)):
            conn.execute(
                "INSERT INTO injections(ts,session_id,event,compaction_k,chars,budget,holdout,"
                "bridge_version,bridge_sha,keys,rid_at) VALUES(?,?,?,?,?,?,1,?,?,?,?)",
                (_now(), session_id, source, k, 0, budget, cfg.version, cfg.sha, json.dumps([]), rid_at),
            )
            conn.commit()
            common.log(
                root,
                f"inject ev=SessionStart q={len(q)}ch nodes=0/{len(scored)} chars=0 budget={budget} holdout=1",
            )
            print(json.dumps({}))
            sys.exit(0)

        resume_prefix = _resume_handoff_prefix(root, budget) if source == "startup" else ""
        selector_budget = max(0, budget - len(resume_prefix))

        sticky = query_mod.sticky_keys(conn, session_id) if cfg.selector.get("sticky", True) else []
        edited = query_mod.edited_since(conn, session_id, prev_rid)
        resolved = query_mod.resolved_errors(conn, session_id, prev_rid)
        chosen = query_mod.select(
            scored, selector_budget, cfg,
            head=head, sticky_keys=sticky, edited_since=edited, resolved_errors=resolved,
        )
        body = resume_prefix + query_mod.render(chosen, head, tag)
        keys = [n["key"] for n in chosen]

        conn.execute(
            "INSERT INTO injections(ts,session_id,event,compaction_k,chars,budget,holdout,"
            "bridge_version,bridge_sha,keys,rid_at) VALUES(?,?,?,?,?,?,0,?,?,?,?)",
            (_now(), session_id, source, k, len(body), budget, cfg.version, cfg.sha, json.dumps(keys), rid_at),
        )
        conn.commit()
        common.log(
            root,
            f"inject ev=SessionStart q={len(q)}ch nodes={len(chosen)}/{len(scored)} chars={len(body)} budget={budget}",
        )
        out = {"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": body}}
    except SystemExit:
        raise
    except Exception as e:
        common.log(root, f"inject ERROR {e!r}")
        out = {}
    print(json.dumps(out))
    sys.exit(0)


def _now() -> float:
    return time.time()


if __name__ == "__main__":
    main()
