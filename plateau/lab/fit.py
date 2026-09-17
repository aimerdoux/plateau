#!/usr/bin/env python3
"""plateau.lab.fit — refit the lab model from this repo's ledger and write the result
to `model.toml` (`plateau fit`, docs/harness-0.3/PLAN-step4.md "`plateau report`,
`plateau fit`").

For every `(model_id, bridge_version)` pair with at least 5 `.plateau/ledger.sqlite`
`sessions` rows (main agent only — S4-A2: compactions/injections/holdouts are main-agent
phenomena, and so is the holdout split below), this refits:

  * `alpha` — recall at lag bucket 0 (mean shadow-probe grade, `plateau.lab.ledger.GRADE`,
    over ALL of the pair's probes — holdout and non-holdout together — at lag bucket 0).
    At zero lag the model predicts `R = alpha` regardless of `pi` (`phi = 0`), so both
    arms estimate the same ceiling; pooling them uses the fuller sample.
  * `lambda_by_lag` — one `l<lag_bucket>` key per lag bucket (0/1/2) that has at least
    one HOLDOUT probe (a holdout compaction skips the injection, i.e. measures native,
    unassisted recall — D-038's arm-A reference): `plateau.lab.model.loss(alpha,
    r_native)`.
  * `pi_by_comp` — one `c<compactions_crossed>` key per distinct crossed value that has
    at least one NON-holdout probe (recall while the bridge is actually injecting):
    `plateau.lab.model.presence(alpha, lambda_by_lag[min(crossed, 2)], r_bridge)`. The
    lag-bucket index paired with a given `compactions_crossed` value is capped at 2 (only
    three lag buckets exist) — this mirrors how `plateau.lab.model.crossover_lag` already
    matches a `pi_by_lag`/`pi_by_comp` key against a `lambda_by_lag` key by their shared
    trailing digit, not by prefix letter. A crossed value whose matching lambda is
    missing or 0 yields no `pi_by_comp` key (`presence()` returns `None` for `lambda ==
    0`: undefined, not zero).
  * `recall_by_comp` (kept for `plateau report`'s residuals) — observed mean grade by
    `compactions_crossed`, preferring the pair's NON-holdout probes (recall under the
    bridge as actually configured) and falling back to its holdout probes only when it
    has no non-holdout probes at all (e.g. a `bridge_version` that never injects).
  * `receipts_per_turn` / `compactions_per_turn` / `tokens_per_turn` — per-session means
    over ALL of the pair's sessions (holdout and non-holdout together), turn counts read
    from the bridge receipt store's `turns` table.

A `model.toml` cell already present for a `(model_id, bridge_version)` pair that does
NOT reach 5 sessions this run is left untouched byte-for-byte — never deleted, never
re-dated (PLAN-step4.md: "never delete existing cells"). A pair that DOES reach 5
sessions replaces the existing cell with that same `(model_id, bridge_version)` identity
(if any), or is appended as a new one. `last_updated` is always `--date` — this module
never reads the wall clock (PLAN.md conventions: "no wall clock inside library code").
"""

from __future__ import annotations

import argparse
import os
import re
import sqlite3
import sys
from typing import Any, Dict, List, Optional, Tuple

from ..bridge import _toml
from ..bridge import common as bridge_common
from . import ledger as ledger_mod
from . import model

try:
    import tomllib as _tomllib  # Python >= 3.11
except ImportError:  # pragma: no cover - exercised on 3.9/3.10
    _tomllib = None  # type: ignore[assignment]

MODEL_TOML_REL = "model.toml"
MIN_SESSIONS = 5  # PLAN-step4.md: "write cells to model.toml only where sessions >= 5"

# Same three lag buckets `experiments/d038/probes.py::LAG_BUCKETS` and
# `plateau.lab.ledger._lag_bucket` use (sealed/frozen boundaries; duplicated here rather
# than imported, per this package's own convention of not depending on another owner's
# private helpers -- see plateau.lab.ledger's module docstring, "reimplemented here
# rather than imported").
_LAG_BUCKET_BOUNDS = (20_000, 60_000)
GRADE = {"exact": 1.0, "fuzzy": 0.5, "wrong": 0.0}

# The cell field order this module writes fresh cells in (matches root `model.toml`'s
# existing seed cells); untouched cells keep whatever key order they were parsed in.
_CELL_KEY_ORDER = [
    "model_id", "bridge_version", "run_id", "sessions", "alpha",
    "lambda_by_lag", "pi_by_comp", "recall_by_comp",
    "receipts_per_turn", "compactions_per_turn", "tokens_per_turn", "last_updated",
]


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


# --- ledger read -----------------------------------------------------------------------

def _fetch(root: str) -> Tuple[List[sqlite3.Row], List[sqlite3.Row]]:
    """`(sessions, probes)` rows from `.plateau/ledger.sqlite` — main agent only
    (`sessions.agent == 'main'`: compactions/injections/holdouts, and therefore the
    holdout split this module fits against, only ever exist for the main agent)."""
    ledger_path = os.path.join(root, ledger_mod.LEDGER_REL)
    if not os.path.isfile(ledger_path):
        return [], []
    conn = ledger_mod.db(root)
    conn.row_factory = sqlite3.Row
    try:
        sessions = conn.execute("SELECT * FROM sessions WHERE agent='main'").fetchall()
        probes = conn.execute("SELECT * FROM probes").fetchall()
    finally:
        conn.close()
    return sessions, probes


def _turn_counts(root: str, session_ids: List[str]) -> Dict[str, int]:
    store_path = os.path.join(root, bridge_common.DB_REL)
    if not session_ids or not os.path.isfile(store_path):
        return {}
    conn = bridge_common.db(root)
    try:
        return {
            sid: conn.execute(
                "SELECT COUNT(*) FROM turns WHERE session_id=?", (sid,)
            ).fetchone()[0]
            for sid in session_ids
        }
    finally:
        conn.close()


# --- fit -----------------------------------------------------------------------------

def compute_cells(root: str, date: str) -> List[Dict[str, Any]]:
    """One fresh cell per `(model_id, bridge_version)` pair with >= `MIN_SESSIONS`
    ledger sessions; see the module docstring for exactly what each field means and
    which bucket/arm it is fit from."""
    sessions, probes = _fetch(root)

    session_pair: Dict[str, Tuple[str, str]] = {}
    session_is_holdout: Dict[str, bool] = {}
    pair_sessions: Dict[Tuple[str, str], List[sqlite3.Row]] = {}
    for r in sessions:
        model_id, bridge_version = r["model_id"], r["bridge_version"]
        if not model_id or not bridge_version:
            continue  # a cell needs both keys; a session missing either can't seed one
        pair = (model_id, bridge_version)
        session_pair[r["session_id"]] = pair
        session_is_holdout[r["session_id"]] = (r["holdouts"] or 0) > 0
        pair_sessions.setdefault(pair, []).append(r)

    pair_probes_holdout: Dict[Tuple[str, str], List[sqlite3.Row]] = {}
    pair_probes_nonholdout: Dict[Tuple[str, str], List[sqlite3.Row]] = {}
    for p in probes:
        pair = session_pair.get(p["session_id"])
        if pair is None:
            continue
        bucket = (
            pair_probes_holdout if session_is_holdout.get(p["session_id"]) else pair_probes_nonholdout
        )
        bucket.setdefault(pair, []).append(p)

    cells: List[Dict[str, Any]] = []
    for pair, rows in pair_sessions.items():
        if len(rows) < MIN_SESSIONS:
            continue
        model_id, bridge_version = pair
        holdout_probes = pair_probes_holdout.get(pair, [])
        nonholdout_probes = pair_probes_nonholdout.get(pair, [])
        all_probes = holdout_probes + nonholdout_probes

        alpha = _mean_grade([p for p in all_probes if _lag_bucket(p["lag_tokens"]) == 0])
        if alpha is None:
            continue  # no lag-0 probes at all: nothing to anchor lambda/pi against

        lambda_by_lag: Dict[str, float] = {}
        for lag in (0, 1, 2):
            r_native = _mean_grade(
                [p for p in holdout_probes if _lag_bucket(p["lag_tokens"]) == lag]
            )
            if r_native is not None:
                lambda_by_lag[f"l{lag}"] = model.loss(alpha, r_native)

        crossed_values = sorted(
            {p["compactions_crossed"] for p in nonholdout_probes if p["compactions_crossed"] is not None}
        )
        pi_by_comp: Dict[str, float] = {}
        for c in crossed_values:
            r_bridge = _mean_grade([p for p in nonholdout_probes if p["compactions_crossed"] == c])
            if r_bridge is None:
                continue
            lam = lambda_by_lag.get(f"l{min(c, 2)}")
            if not lam:
                continue
            pi = model.presence(alpha, lam, r_bridge)
            if pi is not None:
                pi_by_comp[f"c{c}"] = pi

        recall_source = nonholdout_probes or holdout_probes
        recall_by_comp: Dict[str, float] = {}
        for c in sorted({p["compactions_crossed"] for p in recall_source if p["compactions_crossed"] is not None}):
            r = _mean_grade([p for p in recall_source if p["compactions_crossed"] == c])
            if r is not None:
                recall_by_comp[f"c{c}"] = r

        turn_counts = _turn_counts(root, [r["session_id"] for r in rows])

        def per_turn(field: str) -> Optional[float]:
            return _mean(
                [r[field] / max(turn_counts.get(r["session_id"], 0), 1) for r in rows]
            )

        cell: Dict[str, Any] = {
            "model_id": model_id,
            "bridge_version": bridge_version,
            "run_id": f"plateau fit {date}",
            "sessions": len(rows),
            "alpha": alpha,
        }
        if lambda_by_lag:
            cell["lambda_by_lag"] = lambda_by_lag
        if pi_by_comp:
            cell["pi_by_comp"] = pi_by_comp
        if recall_by_comp:
            cell["recall_by_comp"] = recall_by_comp
        cell["receipts_per_turn"] = per_turn("receipts") or 0
        cell["compactions_per_turn"] = per_turn("compactions") or 0
        tokens_per_turn = _mean(
            [
                (r["tokens_in"] + r["tokens_out"]) / max(turn_counts.get(r["session_id"], 0), 1)
                for r in rows
            ]
        )
        cell["tokens_per_turn"] = tokens_per_turn or 0
        cell["last_updated"] = date
        cells.append(cell)

    return cells


# --- model.toml read/write (the "small TOML writer for the [[cell]] shape") ----------

_CELL_MARKER_RE = re.compile(r"(?m)^\[\[cell\]\]\s*$")


def _split_header_and_blocks(text: str) -> Tuple[str, List[str]]:
    m = _CELL_MARKER_RE.search(text)
    if not m:
        return text, []
    header = text[: m.start()]
    blocks = _CELL_MARKER_RE.split(text[m.start():])[1:]
    return header, blocks


def load_cells(path: str) -> Tuple[str, List[Dict[str, Any]]]:
    """`(header_text, cells)` — `header_text` is everything before the first
    `[[cell]]` marker (the file's leading comment block), kept verbatim on write;
    `cells` are the parsed `[[cell]]` tables in file order, each a plain dict with keys
    in parse order. `tomllib` is used when available; the 3.9/3.10 fallback (`_toml`'s
    parser does not support array-of-tables — see its own docstring) instead splits the
    text on `[[cell]]` markers and parses each block as its own flat top-level document,
    which is lossless for `model.toml` specifically since no cell nests a `[section]`
    of its own."""
    if not os.path.isfile(path):
        return "", []
    with open(path, "rb") as f:
        raw = f.read()
    text = raw.decode("utf-8")
    header, blocks = _split_header_and_blocks(text)
    if _tomllib is not None:
        try:
            data = _tomllib.loads(text)
            cells = [dict(c) for c in (data.get("cell") or []) if isinstance(c, dict)]
            return header, cells
        except Exception:
            pass
    cells = []
    for block in blocks:
        try:
            cells.append(dict(_toml.loads(block)))
        except Exception:
            continue
    return header, cells


def _fmt_str(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _fmt_number(v: Any) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        if v == int(v) and abs(v) < 1e15:
            return f"{v:.1f}"
        s = f"{v:.6f}".rstrip("0")
        return s if not s.endswith(".") else s + "0"
    return str(v)


def _fmt_value(v: Any) -> str:
    if isinstance(v, dict):
        inner = ", ".join(f"{k} = {_fmt_value(v2)}" for k, v2 in v.items())
        return "{ " + inner + " }"
    if isinstance(v, str):
        return _fmt_str(v)
    if isinstance(v, list):
        return "[" + ", ".join(_fmt_value(x) for x in v) + "]"
    return _fmt_number(v)


def _dump_cell(cell: Dict[str, Any]) -> str:
    lines = ["[[cell]]"]
    for k, v in cell.items():
        lines.append(f"{k} = {_fmt_value(v)}")
    return "\n".join(lines)


def dump_document(header: str, cells: List[Dict[str, Any]]) -> str:
    """The full `model.toml` text: `header` verbatim, then one `[[cell]]` block per
    cell, in order, blank-line separated."""
    body = "\n\n".join(_dump_cell(c) for c in cells)
    header = header.rstrip("\n")
    if header.strip():
        return header + "\n\n" + body + "\n"
    return body + "\n"


def merge_cells(
    existing: List[Dict[str, Any]], fitted: List[Dict[str, Any]]
) -> Tuple[List[Dict[str, Any]], List[Tuple[str, str]]]:
    """`existing` with each `fitted` cell replacing the existing cell sharing its
    `(model_id, bridge_version)` identity, or appended when no such cell exists yet.
    Every OTHER existing cell is returned unchanged (never deleted, never reordered).
    Returns `(merged_cells, pairs_written)`."""
    out = list(existing)
    index_by_pair: Dict[Tuple[Any, Any], int] = {
        (c.get("model_id"), c.get("bridge_version")): i for i, c in enumerate(out)
    }
    written: List[Tuple[str, str]] = []
    for cell in fitted:
        pair = (cell["model_id"], cell["bridge_version"])
        if pair in index_by_pair:
            out[index_by_pair[pair]] = cell
        else:
            index_by_pair[pair] = len(out)
            out.append(cell)
        written.append(pair)
    return out, written


# --- `plateau fit` ---------------------------------------------------------------------

def main(argv: Optional[List[str]] = None) -> int:
    """`plateau fit --date YYYY-MM-DD`: refit `model.toml` from this repo's ledger (see
    the module docstring). `--date` is required — `last_updated` always comes from it,
    never from the wall clock (PLAN.md conventions)."""
    argv = sys.argv[1:] if argv is None else argv
    ap = argparse.ArgumentParser(prog="plateau fit")
    ap.add_argument("--date", required=True, help="last_updated stamp, e.g. 2026-09-17")
    ap.add_argument("--root", default=None, help="repo root (default: git toplevel of cwd)")
    args = ap.parse_args(argv)

    root = args.root or bridge_common.root({})
    fitted = compute_cells(root, args.date)
    if not fitted:
        print("plateau fit: no (model_id, bridge_version) pair has >= {} ledger sessions "
              "yet -- model.toml left unchanged".format(MIN_SESSIONS))
        return 0

    model_path = os.path.join(root, MODEL_TOML_REL)
    header, existing = load_cells(model_path)
    merged, written = merge_cells(existing, fitted)
    with open(model_path, "w", encoding="utf-8") as f:
        f.write(dump_document(header, merged))

    pairs = ", ".join(f"{m}/{b}" for m, b in written)
    print(f"plateau fit: wrote {len(written)} cell(s) to {model_path} ({pairs})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
