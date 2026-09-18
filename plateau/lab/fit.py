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
import json
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
    "lambda_by_lag", "pi_by_comp", "pi_raw_by_comp", "recall_by_comp",
    "receipts_per_turn", "tool_calls_per_turn", "compactions_per_turn",
    "tokens_per_turn", "last_updated",
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
        # Full precision (PLAN-absorb.md: a fitted number is not hand-rounded like the
        # old seed values were) -- `repr()` is the shortest decimal string that reads
        # back as this exact float, never a lossy fixed-decimal truncation.
        return repr(v)
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


# --- `plateau fit --from-primitives` (docs/harness-0.3/PLAN-absorb.md "CLI") --------
#
# Fits cells straight from `primitives/<source>/<run_id>/` directories (owner D1's
# `plateau.absorb` output) instead of this repo's own `.plateau/ledger.sqlite` --
# `compute_cells` above stays the ledger-backed path; this is the primitives-backed one,
# and `main()` picks between them on `--from-primitives`. An "experiment" source run
# (two arms, D-038-shaped) contributes one cell per arm with `sessions = 1`, `run_id`
# naming the absorbed run; the arm the run's own `arms` map calls "A" is treated as the
# native/no-bridge control (the fixed D-037/D-038 experimental convention -- see
# `experiments/d038/score.py`'s own `BETS` logic, which only ever compares "A" against
# the treatment arm) and gets `lambda_by_lag`; every other arm is the bridge under test
# and gets `pi_by_comp`/`pi_raw_by_comp`, computed against arm A's OWN compaction-bucket
# recall -- alpha_comp = arm A's `recall_by_comp["0"]`, lambda_c<n> = 1 - (arm A's
# recall_by_comp[n]) / alpha_comp -- never against arm A's `lambda_by_lag` (a
# LAG-bucket quantity keyed by a different index; mixing the two was a bug this comment
# replaces, see the "presence-estimator" note in docs/harness-0.3/PLAN-absorb.md's
# "Leak rule" section). Both the clamped `pi_by_comp` (for `plateau.lab.model.recall`'s
# equation) and the unclamped `pi_raw_by_comp` (a negative value there means the bridge
# arm recalled LESS than the native arm at that bucket -- eviction, not "no help"; see
# `plateau.lab.model`'s docstring) are written to the cell. Here the "native" reference
# is the paired control arm within the SAME run, not a holdout split, since a
# single experiment run has no holdout dimension of its own. An "adapter" source run
# only contributes a cell at `sessions >= MIN_SESSIONS` (PLAN-absorb.md: "sessions ...
# >= 5 for adapter cells"); with no per-session holdout flag recorded in the adapter
# primitives, that cell carries `alpha`/`recall_by_comp` only (no `lambda_by_lag`/
# `pi_by_comp` -- flagged in the returned notes, not silently omitted).


def _read_jsonl(path: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    if not os.path.isfile(path):
        return out
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


_EXPERIMENT_CODE_RE = re.compile(r"^([A-Za-z]+)(\d+)$")
_RUN_SUFFIX_RE = re.compile(r"^-run(\d+)$", re.IGNORECASE)


def _pretty_run_id(experiment: str, run_id: str) -> str:
    """A human-friendly `"D-038 run 1"`-style label for an `(experiment, run_id)` pair
    that follows this repo's sealed-experiment naming (`<code><digits>` experiment,
    `<code>-run<n>` run id -- see docs/harness-0.3/PLAN.md's D-037/D-038 references and
    model.toml's hand-typed seed run ids), e.g. `("d038", "d038-run1")` -> `"D-038 run
    1"`. Falls back to `"<experiment> <run_id>"` verbatim for any pair that doesn't fit
    that shape (a different naming convention, or a `plateau absorb --run-id` value
    that isn't `<experiment>-run<n>`), so absorbing a differently-named experiment still
    gets a readable label instead of an error."""
    m_code = _EXPERIMENT_CODE_RE.match(experiment or "")
    if m_code and run_id and run_id.lower().startswith((experiment or "").lower()):
        m_run = _RUN_SUFFIX_RE.match(run_id[len(experiment):])
        if m_run:
            return "{}-{} run {}".format(m_code.group(1).upper(), m_code.group(2), m_run.group(1))
    return "{} {}".format(experiment, run_id)


def _token_for_arm(arms: Dict[str, str], letter: str) -> Optional[str]:
    for tok, l in (arms or {}).items():
        if l == letter:
            return tok
    return None


def _iter_run_dirs(primitives_root: str):
    for dirpath, dirnames, filenames in os.walk(primitives_root):
        if "run.json" in filenames:
            yield dirpath
            dirnames[:] = []  # a run dir has no nested run dirs of its own


def _cells_from_experiment_run(
    run_dir: str, run_doc: Dict[str, Any], date: str, notes: List[str]
) -> List[Dict[str, Any]]:
    derived_path = os.path.join(run_dir, "derived.json")
    if not os.path.isfile(derived_path):
        notes.append("skipping {}: no derived.json (experiment source requires it)".format(run_dir))
        return []
    with open(derived_path, encoding="utf-8") as f:
        derived = json.load(f)

    arms = run_doc.get("arms") or {}
    arm_letters = sorted(set(arms.values()))
    if not arm_letters:
        notes.append("skipping {}: run.json has no arms".format(run_dir))
        return []
    native_letter = "A" if "A" in arm_letters else arm_letters[0]

    settings = run_doc.get("settings") or {}
    model_ids = settings.get("model_ids") or []
    model_id = model_ids[0] if model_ids else "unknown"
    bridge_version_run = settings.get("bridge_version") or "none"

    turns_by_token: Dict[str, List[Dict[str, Any]]] = {}
    for rec in _read_jsonl(os.path.join(run_dir, "turns.jsonl")):
        turns_by_token.setdefault(rec.get("token"), []).append(rec)

    recall_by_lag = derived.get("recall_by_lag") or {}
    recall_by_comp = derived.get("recall_by_comp") or {}
    tokens_per_turn = derived.get("tokens_per_turn") or {}

    native_rl = recall_by_lag.get(native_letter) or {}
    native_alpha = native_rl.get("0", native_rl.get(0))
    native_lambda: Dict[str, float] = {}
    if native_alpha:
        for lag_key, r in native_rl.items():
            if r is None:
                continue
            native_lambda[str(lag_key)] = model.loss(native_alpha, r)

    # Index-consistent presence (see plateau.lab.model's docstring on pi/lambda):
    # pi_c<n> compares the bridge arm's recall at COMPACTION bucket n against the
    # NATIVE arm's own recall at that SAME compaction bucket, both normalized by the
    # native arm's compaction-bucket-0 recall (alpha_comp). This is deliberately a
    # SEPARATE alpha/lambda pair from `native_alpha`/`native_lambda` above, which are
    # LAG-bucket quantities (native_lambda is keyed by lag index, feeds
    # `lambda_by_lag`) -- matching a comp-bucket bridge recall against a lag-bucket
    # lambda mixes two different indices and was the bug this comment replaces (see
    # docs/harness-0.3/PLAN-absorb.md, "Leak rule" section, presence-estimator note).
    native_rc = recall_by_comp.get(native_letter) or {}
    alpha_comp = native_rc.get("0", native_rc.get(0))
    native_lambda_comp: Dict[str, float] = {}
    if alpha_comp:
        for comp_key, r in native_rc.items():
            if r is None:
                continue
            native_lambda_comp[str(comp_key)] = model.loss(alpha_comp, r)

    out: List[Dict[str, Any]] = []
    for letter in arm_letters:
        rl = recall_by_lag.get(letter) or {}
        alpha = rl.get("0", rl.get(0))
        if alpha is None:
            notes.append("{} arm {}: no lag-0 recall, skipped".format(run_dir, letter))
            continue
        is_native = (letter == native_letter)
        cell: Dict[str, Any] = {
            "model_id": model_id,
            "bridge_version": "none" if is_native else bridge_version_run,
            "run_id": _pretty_run_id(run_doc.get("experiment", "?"), run_doc.get("run_id", "?")),
            "sessions": 1,
            "alpha": alpha,
        }
        if is_native:
            lambda_by_lag = {
                "l{}".format(lag_key): model.loss(alpha, r)
                for lag_key, r in rl.items() if r is not None
            }
            if lambda_by_lag:
                cell["lambda_by_lag"] = lambda_by_lag
        else:
            rc = recall_by_comp.get(letter) or {}
            pi_by_comp: Dict[str, float] = {}
            pi_raw_by_comp: Dict[str, float] = {}
            if alpha_comp:
                for comp_key, r_bridge in rc.items():
                    if r_bridge is None:
                        continue
                    idx = int(comp_key)
                    lam = native_lambda_comp.get(str(idx))
                    if not lam:
                        continue
                    pi_raw = model.presence_raw(alpha_comp, lam, r_bridge)
                    if pi_raw is None:
                        continue
                    pi_raw_by_comp["c{}".format(idx)] = pi_raw
                    pi_by_comp["c{}".format(idx)] = model.presence(alpha_comp, lam, r_bridge)
            if pi_by_comp:
                cell["pi_by_comp"] = pi_by_comp
            if pi_raw_by_comp:
                # unclamped twin, kept alongside the clamped one so a negative
                # presence (eviction -- see plateau.lab.model's docstring) is
                # reported, not silently floored away (PLAN-absorb.md: "do not hide
                # the finding").
                cell["pi_raw_by_comp"] = pi_raw_by_comp

        rc = recall_by_comp.get(letter) or {}
        if rc:
            cell["recall_by_comp"] = {
                "c{}".format(k): v for k, v in rc.items() if v is not None
            }

        token = _token_for_arm(arms, letter)
        turns = turns_by_token.get(token, [])
        tool_calls_per_turn = _mean(
            [sum((t.get("tools") or {}).values()) for t in turns]
        ) or 0
        if is_native:
            # The native arm ran with bridge_version "none": no receipt hook ever
            # fired for it, so there is no receipt store to count -- "receipts_per_turn"
            # would misname a plain tool-call tally as a receipts count for an arm that
            # never had receipts. Write the same recomputed number under its honest
            # name instead (PLAN-step4.md's model.toml note: "receipts_per_turn for arm
            # A is unknown (no receipt store in arm A)" -- this is that value, correctly
            # named, not the old hand-seeded placeholder 0).
            cell["tool_calls_per_turn"] = tool_calls_per_turn
        else:
            cell["receipts_per_turn"] = tool_calls_per_turn
        cell["compactions_per_turn"] = _mean(
            [t.get("compactions_in_turn") for t in turns]
        ) or 0
        cell["tokens_per_turn"] = tokens_per_turn.get(letter) or 0
        cell["last_updated"] = date
        # Traceable to the primitives this cell was fitted from (PLAN-absorb.md: every
        # `model.toml` cell a `plateau fit --from-primitives` run writes should point
        # back at the `primitives/<source>/<run_id>/` directory it came from).
        cell["source"] = run_dir
        out.append(cell)
    return out


def _cells_from_adapter_run(
    run_dir: str, run_doc: Dict[str, Any], date: str, notes: List[str]
) -> List[Dict[str, Any]]:
    sessions = run_doc.get("sessions", 0) or 0
    if sessions < MIN_SESSIONS:
        notes.append(
            "{}: adapter run has {} session(s), need >= {}; no cell written".format(
                run_dir, sessions, MIN_SESSIONS,
            )
        )
        return []

    settings = run_doc.get("settings") or {}
    model_ids = settings.get("model_ids") or []
    model_id = model_ids[0] if model_ids else "unknown"
    bridge_version = settings.get("bridge_version") or "none"

    probes = _read_jsonl(os.path.join(run_dir, "probes.jsonl"))
    turns = _read_jsonl(os.path.join(run_dir, "turns.jsonl"))

    def mean_grade(rows: List[Dict[str, Any]]) -> Optional[float]:
        xs = [GRADE[r["verdict"]] for r in rows if r.get("verdict") in GRADE]
        return (sum(xs) / len(xs)) if xs else None

    alpha = mean_grade([p for p in probes if p.get("lag_bucket") == 0])
    if alpha is None:
        notes.append("{}: no lag-0 probes; no cell written".format(run_dir))
        return []

    recall_by_comp: Dict[str, float] = {}
    for c in sorted({p.get("comp_bucket") for p in probes if p.get("comp_bucket") is not None}):
        r = mean_grade([p for p in probes if p.get("comp_bucket") == c])
        if r is not None:
            recall_by_comp["c{}".format(c)] = r

    cell: Dict[str, Any] = {
        "model_id": model_id, "bridge_version": bridge_version,
        "run_id": "adapter {}".format(run_doc.get("run_id", "?")),
        "sessions": sessions, "alpha": alpha,
    }
    if recall_by_comp:
        cell["recall_by_comp"] = recall_by_comp
    cell["receipts_per_turn"] = _mean(
        [sum((t.get("tools") or {}).values()) for t in turns]
    ) or 0
    cell["compactions_per_turn"] = _mean(
        [t.get("compactions_in_turn") for t in turns]
    ) or 0
    cell["tokens_per_turn"] = _mean(
        [
            (t.get("tokens_in") or 0) + (t.get("tokens_cache_create") or 0) + (t.get("tokens_out") or 0)
            for t in turns
        ]
    ) or 0
    cell["last_updated"] = date
    cell["source"] = run_dir
    notes.append(
        "{}: adapter cell fitted WITHOUT a holdout split (the adapter primitives carry "
        "no per-session holdout flag) -- alpha/recall_by_comp only, no lambda_by_lag/"
        "pi_by_comp.".format(run_dir)
    )
    return [cell]


def from_primitives(primitives_root: str, date: str) -> Tuple[List[Dict[str, Any]], List[str]]:
    """`(cells, notes)` fitted from every `primitives/<source>/<run_id>/run.json` found
    under `primitives_root` (see the section docstring above for exactly what each
    source contributes). `notes` carries skip reasons and documented approximations for
    the CLI to print -- never silently swallowed."""
    cells: List[Dict[str, Any]] = []
    notes: List[str] = []
    if not os.path.isdir(primitives_root):
        return cells, ["plateau fit --from-primitives: no such directory: {}".format(primitives_root)]

    for run_dir in sorted(_iter_run_dirs(primitives_root)):
        run_path = os.path.join(run_dir, "run.json")
        try:
            with open(run_path, encoding="utf-8") as f:
                run_doc = json.load(f)
        except (OSError, ValueError) as e:
            notes.append("skipping {}: run.json unreadable ({!r})".format(run_dir, e))
            continue

        source = run_doc.get("source")
        if source == "experiment":
            cells.extend(_cells_from_experiment_run(run_dir, run_doc, date, notes))
        elif source == "adapter":
            cells.extend(_cells_from_adapter_run(run_dir, run_doc, date, notes))
        else:
            notes.append("skipping {}: unknown run.json.source {!r}".format(run_dir, source))

    return cells, notes


# Identity/bookkeeping keys (never numbers to reconcile) plus administrative per-turn
# telemetry that a hand-typed seed legitimately rounded or omitted altogether --
# `tokens_per_turn` in particular was hand-seeded as a rounded integer (e.g. `143676`)
# while the recompute carries the exact float (`143675.588...`); a fresh cell adding a
# field the seed never had (`source`, `pi_raw_by_comp`, or arm A's `tool_calls_per_turn`
# replacing its old `receipts_per_turn` placeholder -- see `_cells_from_experiment_run`)
# is likewise not a disagreement to gate the write on. None of these bear on whether the
# recall/loss/presence MODEL (alpha, lambda_by_lag, pi_by_comp, recall_by_comp) itself
# reproduces the seed -- that is what this tolerance check exists to protect.
_COMPARE_SKIP_KEYS = (
    "run_id", "last_updated", "model_id", "bridge_version", "sessions",
    "source", "tokens_per_turn",
)


def compare_cells(existing: Dict[str, Any], new: Dict[str, Any], tol: float = 0.01) -> Tuple[bool, List[str]]:
    """`(within_tolerance, diffs)` for every SHARED numeric field of two cells sharing a
    `(model_id, bridge_version)` identity -- used to check a freshly-fitted cell against
    an already-seeded one (PLAN-absorb.md: "the existing seeded D-038 cells in
    model.toml must be reproduced by the recompute within 0.01 -- report the values
    side by side rather than editing them if they differ") without ever needing that
    seed's own derivation method reproduced exactly, only its numbers. A field present
    on only ONE side (the seed lacked it, or the fit no longer writes it) is not itself
    a disagreement -- there is nothing on the other side to compare it against -- so
    only keys (and, for dict-valued fields, sub-keys) present in BOTH cells are ever
    compared; this is what makes the fit able to add or rename a field (e.g. this run's
    `pi_raw_by_comp`, `source`, arm A's `tool_calls_per_turn`) without that alone
    tripping the tolerance check."""
    diffs: List[str] = []
    keys = (set(existing.keys()) & set(new.keys())) - set(_COMPARE_SKIP_KEYS)
    for k in sorted(keys):
        av, bv = existing.get(k), new.get(k)
        if isinstance(av, dict) or isinstance(bv, dict):
            av, bv = (av or {}), (bv or {})
            for kk in sorted(set(av) & set(bv)):
                a1, b1 = av.get(kk), bv.get(kk)
                if a1 is None or b1 is None:
                    continue
                if abs(a1 - b1) > tol:
                    diffs.append("{}.{}: existing={} new={} (|diff|={:.4f})".format(k, kk, a1, b1, abs(a1 - b1)))
        else:
            if av is None or bv is None:
                continue
            try:
                if abs(av - bv) > tol:
                    diffs.append("{}: existing={} new={} (|diff|={:.4f})".format(k, av, bv, abs(av - bv)))
            except TypeError:
                if av != bv:
                    diffs.append("{}: existing={} new={}".format(k, av, bv))
    return (len(diffs) == 0), diffs


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
    """`plateau fit --date YYYY-MM-DD [--from-primitives DIR]`: refit `model.toml`
    (see the module docstring). `--date` is required — `last_updated` always comes from
    it, never from the wall clock (PLAN.md conventions). `--from-primitives DIR`
    (docs/harness-0.3/PLAN-absorb.md "CLI") fits from `plateau.absorb` output instead of
    this repo's own ledger (`from_primitives`, above) -- and, for any fitted cell whose
    `(model_id, bridge_version)` already has a `model.toml` cell that is NOT itself a
    `plateau fit`/`plateau absorb` product (i.e. a hand-seeded reference cell such as
    the D-038 run-1 seed), compares the two within a 0.01 tolerance
    (`compare_cells`) rather than overwriting blind: within tolerance, the fresh cell is
    written as usual; out of tolerance, that ONE cell is left untouched and both sets of
    numbers are printed side by side (PLAN-absorb.md: "report the values side by side
    rather than editing them if they differ")."""
    argv = sys.argv[1:] if argv is None else argv
    ap = argparse.ArgumentParser(prog="plateau fit")
    ap.add_argument("--date", required=True, help="last_updated stamp, e.g. 2026-09-17")
    ap.add_argument("--root", default=None, help="repo root (default: git toplevel of cwd)")
    ap.add_argument("--from-primitives", default=None, metavar="DIR",
                     help="fit from primitives/ (plateau.absorb output) instead of this repo's ledger")
    args = ap.parse_args(argv)

    root = args.root or bridge_common.root({})

    if args.from_primitives:
        fitted, notes = from_primitives(args.from_primitives, args.date)
        for n in notes:
            print("plateau fit --from-primitives: {}".format(n))
    else:
        fitted = compute_cells(root, args.date)

    if not fitted:
        if not args.from_primitives:
            print("plateau fit: no (model_id, bridge_version) pair has >= {} ledger sessions "
                  "yet -- model.toml left unchanged".format(MIN_SESSIONS))
        return 0

    model_path = os.path.join(root, MODEL_TOML_REL)
    header, existing = load_cells(model_path)

    to_write = []
    for cell in fitted:
        pair = (cell["model_id"], cell["bridge_version"])
        existing_cell = next(
            (c for c in existing if (c.get("model_id"), c.get("bridge_version")) == pair), None,
        )
        is_seed = existing_cell is not None and not str(existing_cell.get("run_id", "")).startswith(
            ("plateau fit ", "adapter ")
        ) and existing_cell.get("run_id") != cell.get("run_id")
        if is_seed:
            ok, diffs = compare_cells(existing_cell, cell, tol=0.01)
            print("plateau fit: {}/{} vs existing seed {!r}: {}".format(
                pair[0], pair[1], existing_cell.get("run_id"),
                "within 0.01 tolerance" if ok else "OUT OF TOLERANCE -- left unchanged",
            ))
            for d in diffs:
                print("  {}".format(d))
            if not ok:
                continue
        to_write.append(cell)

    if not to_write:
        print("plateau fit: no cells written (nothing new, or all within-tolerance checks failed)")
        return 0

    merged, written = merge_cells(existing, to_write)
    with open(model_path, "w", encoding="utf-8") as f:
        f.write(dump_document(header, merged))

    pairs = ", ".join(f"{m}/{b}" for m, b in written)
    print(f"plateau fit: wrote {len(written)} cell(s) to {model_path} ({pairs})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
