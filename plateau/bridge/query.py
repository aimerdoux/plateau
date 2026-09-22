"""plateau.bridge.query — Selector v2: query-aware, budget-bounded ranking over the bridge store.

Owner: A2 (selector-v2). This module is intentionally self-contained: it never imports
``plateau.bridge.common`` at module import time (that module is developed concurrently),
and it reads receipts-per-turn straight out of the ``receipts``/``turns`` tables of an
already-open sqlite3 connection (store schema v1; see docs/harness-0.3/PLAN.md). ``cfg``
is duck-typed — any object exposing ``.selector`` (dict) works, so tests can pass a plain
``types.SimpleNamespace`` instead of a real ``plateau.bridge.config.BridgeConfig``.

Pipeline: score_nodes() ranks every node in the store for a query; select() turns that
ranking into a budget-bounded list of lines, honouring stickiness (nodes shown at the
previous compaction stay shown unless invalidated) and the "bridge quota" (a floor on how
many chosen lines must predate the previous compaction, so old-but-still-relevant facts
are not starved out by a flood of very recent activity); render_line()/render() turn the
chosen nodes into the text that actually gets injected.
"""

from __future__ import annotations

import json
import math
import re
import sqlite3
from typing import Any, Dict, Iterable, List, Optional, Set

# Identifier-split tokenizer, shared with the D-037 rung this selector supersedes: splits
# camelCase/PascalCase/snake_case/dotted/slashed strings into lowercase word-ish tokens.
_TOK_RE = re.compile(r"[A-Za-z][a-z]+|[A-Z]+(?![a-z])|\d+")
_TOK_SEP_RE = re.compile(r"[_./\\-]")

# Fallbacks used only when the store has nothing to compute a real value from.
DEFAULT_RECEIPTS_PER_TURN = 30.0
DEFAULT_TAU = 90.0
DEFAULT_KIND_WEIGHT = 0.5

# select() knows budget_chars must cover head + lines + the closing "</tag>", but it is not
# given the tag itself. Reserve conservatively for the longest tag this repo actually emits
# (public "plateau_index", legacy "d037_index") plus headroom, so we never under-reserve.
_KNOWN_TAGS = ("plateau_index", "d037_index")
_CLOSE_TAG_RESERVE = max(len("</" + t + ">") for t in _KNOWN_TAGS) + 8


def toks(s: str) -> Set[str]:
    """Identifier-split lowercase tokens, len > 1."""
    normalized = _TOK_SEP_RE.sub(" ", s or "")
    return {t.lower() for t in _TOK_RE.findall(normalized) if len(t) > 1}


def _receipts_per_turn(conn: sqlite3.Connection, session_id: str) -> float:
    """receipts / max(turns, 1); default 30.0 when there are no turns.

    Computed locally from the receipts/turns tables (never via plateau.bridge.common,
    which this module must not import at module import time).
    """
    turns = conn.execute(
        "SELECT COUNT(*) FROM turns WHERE session_id = ?", (session_id,)
    ).fetchone()[0]
    if not turns:
        return DEFAULT_RECEIPTS_PER_TURN
    receipts = conn.execute(
        "SELECT COUNT(*) FROM receipts WHERE session_id = ?", (session_id,)
    ).fetchone()[0]
    return receipts / max(turns, 1)


def _prev_compaction_rid(conn: sqlite3.Connection, session_id: str) -> Optional[int]:
    """The "older than the previous compaction" boundary, defined in exactly one place:
    plateau.bridge.common.prev_compaction_rid. Imported lazily, INSIDE this function
    rather than at module level, because this module must not import
    plateau.bridge.common at import time (see module docstring) -- by the time this
    function actually runs, common.py is fully loaded, so there is no cycle."""
    from . import common as _common
    return _common.prev_compaction_rid(conn, session_id)


def score_nodes(conn: sqlite3.Connection, query: str, cfg: Any, session_id: str) -> List[Dict[str, Any]]:
    """Rank every node in the store for `query`.

    tau = cfg.selector["tau_turns"] * receipts_per_turn(conn, session_id)  (falls back to
    DEFAULT_TAU when that would be <= 0, e.g. turns recorded but no receipts yet).
    struct = W[kind] * (0.6*exp(-(last - last_rid)/tau) + 0.4*log1p(min(degree, degree_cap)))
    lex    = BM25-lite (IDF-only) over toks(key) | toks(detail), squashed to [0,1) via x/(1+x)
    score  = struct + 2*lex, when cfg.selector["lexical"]; else struct alone.
    A kind whose weight is exactly 0 is left out of the ranking altogether.
    """
    weights = cfg.selector["weights"]
    degree_cap = cfg.selector["degree_cap"]
    lexical_on = bool(cfg.selector["lexical"])

    tau = cfg.selector["tau_turns"] * _receipts_per_turn(conn, session_id)
    if tau <= 0:
        tau = DEFAULT_TAU

    last = conn.execute("SELECT COALESCE(MAX(id), 0) FROM receipts").fetchone()[0]
    prev_rid_at = _prev_compaction_rid(conn, session_id)

    rows = conn.execute(
        "SELECT key, kind, first_rid, last_rid, degree, last_outcome, last_detail FROM nodes"
    ).fetchall()

    q = toks(query)
    docs = []
    df: Dict[str, int] = {}
    for key, _kind, _first_rid, _last_rid, _degree, _outcome, detail in rows:
        d = toks(key) | toks(detail)
        docs.append(d)
        for t in d:
            df[t] = df.get(t, 0) + 1
    n_docs = max(len(rows), 1)

    out: List[Dict[str, Any]] = []
    for (key, kind, first_rid, last_rid, degree, outcome, detail), d in zip(rows, docs):
        if weights.get(kind, DEFAULT_KIND_WEIGHT) == 0:
            # 0.4.3: an explicit 0 weight opts a kind out of the index entirely (the
            # default config does this for `tool`: "mcp__x__y → ok ×58" lines carry no
            # fact, and no injected receipt id was ever cited back -- 0 of 17,661 calls).
            continue
        recency = math.exp(-(last - last_rid) / tau)
        capped_degree = min(degree, degree_cap)
        struct = weights.get(kind, DEFAULT_KIND_WEIGHT) * (
            0.6 * recency + 0.4 * math.log1p(capped_degree)
        )
        hit = bool(q & d)
        lex = 0.0
        if q and hit:
            raw = sum(math.log(1 + n_docs / df[t]) for t in (q & d))
            lex = raw / (1 + raw)  # squash to [0,1)
        score = struct + (2.0 * lex if lexical_on else 0.0)
        older = prev_rid_at is not None and last_rid <= prev_rid_at
        out.append(
            {
                "key": key,
                "kind": kind,
                "first_rid": first_rid,
                "last_rid": last_rid,
                "degree": degree,
                "outcome": outcome or "",
                "detail": detail or "",
                "score": score,
                "lexical_hit": hit,
                "older_than_prev_compaction": older,
            }
        )
    out.sort(key=lambda n: n["score"], reverse=True)
    return out


def render_line(n: Dict[str, Any]) -> str:
    """Render one node as: [r<last_rid>] <kind> <key> -> <outcome> (<detail<=60>) x<degree>,
    with a trailing " *" (rendered as a star) when lexical_hit is set, then " ◉" when
    `carried` is set (the continuum brought it across the compaction; both markers keep
    that order). No trailing newline."""
    detail = (n.get("detail") or "")[:60]
    line = "[r{}] {} {} → {}".format(n["last_rid"], n["kind"], n["key"], n["outcome"])
    if detail:
        line += " ({})".format(detail)
    line += " ×{}".format(n["degree"])
    if n.get("lexical_hit"):
        line += " ★"
    if n.get("carried"):
        line += " ◉"
    return line


def render(lines: List[Dict[str, Any]], head: str, tag: str) -> str:
    """head + lines + "</" + tag + ">"; each line is render_line(n) + "\\n"."""
    body = "".join(render_line(n) + "\n" for n in lines)
    return head + body + "</" + tag + ">"


def select(
    scored: List[Dict[str, Any]],
    budget_chars: int,
    cfg: Any,
    *,
    head: str,
    sticky_keys: List[str],
    edited_since: Set[str],
    resolved_errors: Set[str],
    carried_keys: Iterable[str] = (),
) -> List[Dict[str, Any]]:
    """Turn a score_nodes() ranking into a budget-bounded selection.

    0) carried: keys from `carried_keys` that are present in `scored` are included first,
       in score order, as copies marked `carried=True` -- they are ancestry the current
       request descends from (plateau.bridge.carry), not an open problem, so neither
       `edited_since` nor `resolved_errors` applies to them; the input dicts are never
       mutated.
    1) sticky: keys from `sticky_keys` that are still present in `scored` are re-included,
       unless a file key is in `edited_since` or an error key is in `resolved_errors`.
    2) quota: at least round(bridge_quota * n_lines) of the chosen lines are
       older_than_prev_compaction, when enough such nodes exist (n_lines = however many
       lines a plain score-ordered fill would have produced under this budget).
    3) fill the rest by score.
    Never exceeds budget_chars, counting head, every rendered line (+1 for its newline),
    and a reserved allowance for the closing tag.
    """
    bridge_quota = cfg.selector["bridge_quota"]
    by_key = {n["key"]: n for n in scored}
    ranked = sorted(scored, key=lambda n: n["score"], reverse=True)

    reserve = len(head) + _CLOSE_TAG_RESERVE

    def fits(used: int, n: Dict[str, Any]) -> bool:
        return used + len(render_line(n)) + 1 <= budget_chars

    chosen: List[Dict[str, Any]] = []
    chosen_keys: Set[str] = set()
    used = reserve

    # --- 0) carried --------------------------------------------------------------
    carried_nodes = []
    seen = set()
    for k in carried_keys:
        if k in seen:
            continue
        n = by_key.get(k)
        if n is None:
            continue
        carried_nodes.append(dict(n, carried=True))
        seen.add(k)
    carried_nodes.sort(key=lambda n: n["score"], reverse=True)
    for n in carried_nodes:
        if not fits(used, n):
            continue  # a smaller, lower-scored carried line might still fit
        chosen.append(n)
        chosen_keys.add(n["key"])
        used += len(render_line(n)) + 1

    # --- 1) sticky ---------------------------------------------------------------
    sticky_survivors = []
    seen = set()
    for k in sticky_keys:
        if k in seen or k in chosen_keys:
            continue
        n = by_key.get(k)
        if n is None:
            continue
        if n["kind"] == "file" and k in edited_since:
            continue
        if n["kind"] == "error" and k in resolved_errors:
            continue
        sticky_survivors.append(n)
        seen.add(k)
    sticky_survivors.sort(key=lambda n: n["score"], reverse=True)

    for n in sticky_survivors:
        if not fits(used, n):
            continue  # a smaller, lower-scored sticky line might still fit
        chosen.append(n)
        chosen_keys.add(n["key"])
        used += len(render_line(n)) + 1

    rest = [n for n in ranked if n["key"] not in chosen_keys]

    # --- estimate n_lines via a plain score-ordered fill (no quota bias) ---------
    dry_used = used
    dry_count = len(chosen)
    for n in rest:
        if dry_used + len(render_line(n)) + 1 > budget_chars:
            break
        dry_used += len(render_line(n)) + 1
        dry_count += 1
    target_n = dry_count

    # --- 2) quota ------------------------------------------------------------------
    required_older = round(bridge_quota * target_n)
    have_older = sum(1 for n in chosen if n["older_than_prev_compaction"])
    need = max(0, required_older - have_older)
    if need:
        older_pool = [n for n in rest if n["older_than_prev_compaction"]]
        added = 0
        for n in older_pool:
            if added >= need:
                break
            if not fits(used, n):
                continue  # a smaller, lower-scoring older node might still fit later
            chosen.append(n)
            chosen_keys.add(n["key"])
            used += len(render_line(n)) + 1
            added += 1
        rest = [n for n in rest if n["key"] not in chosen_keys]

    # --- 3) fill by score ------------------------------------------------------------
    for n in rest:
        if not fits(used, n):
            break
        chosen.append(n)
        chosen_keys.add(n["key"])
        used += len(render_line(n)) + 1

    return chosen


def last_user_prompt(transcript_path: str) -> str:
    """The last human-authored prompt text in a Claude Code transcript JSONL.

    Skips "user" turns whose content is tool-result feedback (a list whose first block is
    `{"type": "tool_result", ...}`); those are the model's own tool output relayed back on
    the user side of the transcript, not something a person typed. Returns "" if the file
    is missing/unreadable or no genuine prompt is found; never raises. Claude Code appends
    the JSONL while this hook reads it, so the tail may end inside a multibyte sequence:
    undecodable bytes are replaced, and that half line then fails to parse like any other
    garbage line instead of aborting the whole injection.
    """
    last = ""
    try:
        with open(transcript_path, "r", encoding="utf-8", errors="replace") as f:
            for raw_line in f:
                raw_line = raw_line.strip()
                if not raw_line:
                    continue
                try:
                    entry = json.loads(raw_line)
                except ValueError:
                    continue
                if not isinstance(entry, dict) or entry.get("type") != "user":
                    continue
                message = entry.get("message") or {}
                content = message.get("content")
                candidate = ""
                if isinstance(content, str):
                    candidate = content.strip()
                elif isinstance(content, list):
                    if content and isinstance(content[0], dict) and content[0].get("type") == "tool_result":
                        continue
                    parts = []
                    for block in content:
                        if isinstance(block, dict):
                            if block.get("type") == "tool_result":
                                continue
                            text = block.get("text")
                            if text:
                                parts.append(str(text))
                        elif isinstance(block, str):
                            parts.append(block)
                    candidate = " ".join(parts).strip()
                if candidate:
                    last = candidate
    except OSError:
        return ""
    return last


def sticky_keys(conn: sqlite3.Connection, session_id: str) -> List[str]:
    """Keys of the latest injection row for this session (JSON list; [] if none/empty)."""
    row = conn.execute(
        "SELECT keys FROM injections WHERE session_id = ? ORDER BY id DESC LIMIT 1",
        (session_id,),
    ).fetchone()
    if not row or not row[0]:
        return []
    try:
        keys = json.loads(row[0])
    except (ValueError, TypeError):
        return []
    if not isinstance(keys, list):
        return []
    return [str(k) for k in keys]


def edited_since(conn: sqlite3.Connection, session_id: str, rid: int) -> Set[str]:
    """File keys (receipt `target`) edited (kind='file', outcome='edit') after receipt `rid`."""
    rows = conn.execute(
        "SELECT DISTINCT target FROM receipts"
        " WHERE session_id = ? AND kind = 'file' AND outcome = 'edit' AND id > ?",
        (session_id, rid),
    ).fetchall()
    return {r[0] for r in rows}


def resolved_errors(conn: sqlite3.Connection, session_id: str, rid: int) -> Set[str]:
    """Error node keys whose originating target later (id > rid) passed a test/command.

    An error node's originating target is the `src` of its "fails_with" edge (written by
    common.record() the way d037_common.record() did: edges(target, "fails_with", error, rid)).
    """
    error_rows = conn.execute(
        "SELECT key FROM nodes WHERE kind = 'error' AND session_id = ?", (session_id,)
    ).fetchall()
    resolved: Set[str] = set()
    for (error_key,) in error_rows:
        targets = conn.execute(
            "SELECT DISTINCT src FROM edges WHERE rel = 'fails_with' AND dst = ?",
            (error_key,),
        ).fetchall()
        for (target,) in targets:
            passed = conn.execute(
                "SELECT 1 FROM receipts"
                " WHERE session_id = ? AND target = ? AND kind IN ('test', 'command')"
                "   AND outcome = 'pass' AND id > ? LIMIT 1",
                (session_id, target, rid),
            ).fetchone()
            if passed:
                resolved.add(error_key)
                break
    return resolved
