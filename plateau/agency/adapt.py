"""plateau.agency.adapt — the gap-analysis / recalibration layer of the control loop.

The control loop makes DONE a predicate. This module makes the loop ADAPTIVE: it closes the
predict -> observe -> gap -> recalibrate cycle so a plan is continuously re-grounded against
what execution actually reveals, and so surfaced blockers/errors are classified and given a
next action automatically instead of stalling for a human.

Three pieces, all pure-stdlib and file-backed (state lives on disk, like the rest of the loop):

  FORECAST   before a task runs, the parent records what it EXPECTS the gate to observe and
             the risk. Kept in FORECAST.md, keyed by task id — no PLAN row-grammar change.
  GAP        after a task runs, `analyze_gap` compares the forecast to the actual gate
             artifact and classifies: CONFIRMED (as predicted), DRIFT (passed, but not for
             the predicted reason), REFUTED (failed), or UNVERIFIED (not run yet).
  RECALIBRATE every DRIFT/REFUTED is appended to RECALIBRATE.md with a classified blocker and
             a smallest-unblocking action, so the parent adjusts the plan from ground truth
             rather than from its prior.

This is deliberately the same discipline as `plateau.signal`'s gate, one level up: a plan
step survives only while reality keeps agreeing with it — and when reality disagrees, the
disagreement itself becomes the next unit of work.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

# Blocker taxonomy (matches CONTROL_LOOP.md §6 B1). Each class carries pattern rules over the
# gate's output and a template for the smallest unblocking action, so a failed gate becomes an
# actionable, classified blocker WITHOUT a human reading the log first.
_BLOCKER_RULES = [
    ("PERMISSION", re.compile(
        r"permission denied|requires approval|not permitted|EACCES|forbidden|"
        r"\b401\b|\b403\b|unauthorized|dangerously-skip-permissions", re.I),
     "re-run the step with the needed permission/mode, or record it as an intentional "
     "exception; never weaken an auth check to pass a gate"),
    ("CAPABILITY", re.compile(
        r"command not found|not recognized|No module named|is not installed|"
        r"unsupported|cannot execute|no such command", re.I),
     "install or substitute the missing tool, or rewrite the gate to use one that exists here "
     "(preflight catches this before dispatch)"),
    ("EXTERNAL", re.compile(
        r"timed out|timeout|connection refused|ECONNREFUSED|rate limit|\b429\b|\b50[234]\b|"
        r"network is unreachable|temporarily unavailable", re.I),
     "retry with backoff; if it persists, block on the external dependency and note it — do "
     "not fake the result"),
    ("MISSING-INFO", re.compile(
        r"no such file|not found|ENOENT|undefined|cannot find|does not exist|"
        r"unknown option|missing required", re.I),
     "produce or locate the missing artifact/arg the gate needs; if it is an earlier task's "
     "deliverable, that task is not actually done — reopen it"),
]
_BLOCKER_DEFAULT = ("AMBIGUITY",
                    "the failure is not machine-classifiable; decide the safest reasonable "
                    "next action and log it — this is the one class that legitimately needs a "
                    "judgment call")

# Gap classes, ordinal by how far reality drifted from the plan.
CONFIRMED, DRIFT, REFUTED, UNVERIFIED = "CONFIRMED", "DRIFT", "REFUTED", "UNVERIFIED"
# A fourth outcome, distinct from both a pass and a drift: the gate PASSED, but its output
# cannot possibly settle whether the forecast happened. Calling that CONFIRMED hides a
# too-loose gate; calling it DRIFT floods a long run with false alarms. It is its own
# actionable state — make the claim checkable.
UNCHECKABLE = "UNCHECKABLE"

# Below this many characters a gate's output cannot plausibly contain a prose forecast's
# vocabulary, so token overlap is meaningless and DRIFT must not fire on absence alone.
_MIN_OBSERVABLE = 200
_EXPECT_RE = re.compile(r'expect:\s*"([^"]*)"', re.I)


def _explicit_expectation(forecast: str):
    """The literal string a forecast promises the gate output will contain, written
    `expect:"..."`. Returns None when the forecast makes no checkable promise — the caller
    then must NOT treat mere absence as drift."""
    m = _EXPECT_RE.search(forecast or "")
    return m.group(1).strip() if m else None
_DRIFT_MAGNITUDE = {CONFIRMED: 0, UNCHECKABLE: 1, DRIFT: 1, REFUTED: 2, UNVERIFIED: -1}


def classify_blocker(output: str) -> tuple:
    """Map a failed gate's output to (class, smallest_unblocking_action). Deterministic,
    first-match-wins over the ordered rules; AMBIGUITY is the fallthrough (a real decision)."""
    text = output or ""
    for name, pattern, action in _BLOCKER_RULES:
        if pattern.search(text):
            return name, action
    return _BLOCKER_DEFAULT


def parse_forecast(text: str) -> dict:
    """Parse FORECAST.md rows `T<n> | <expected observation / risk>` -> {id: prediction}.
    Lines that are not forecast rows (headers, prose) are ignored."""
    out = {}
    for line in (text or "").splitlines():
        # id = any identifier starting with a LETTER, matching control._ROW. This once
        # required a leading `T`, which silently dropped every forecast for a plan using
        # another prefix — and a missing forecast degrades to CONFIRMED, so the drift check
        # quietly stopped working rather than erroring.
        m = re.match(r"^\s*([A-Za-z][\w.-]*)\s*\|\s*(.+?)\s*$", line)
        if m:
            out[m.group(1)] = m.group(2)
    return out


@dataclass
class Gap:
    task: str
    klass: str                       # CONFIRMED | DRIFT | REFUTED | UNVERIFIED
    predicted: str = ""
    observed: str = ""
    magnitude: int = 0
    blocker: str = ""                # set only when REFUTED
    unblock: str = ""                # smallest unblocking action, when REFUTED
    note: str = ""

    def as_dict(self) -> dict:
        d = {"task": self.task, "class": self.klass, "magnitude": self.magnitude,
             "predicted": self.predicted, "observed": self.observed}
        if self.blocker:
            d["blocker"] = self.blocker
            d["unblock"] = self.unblock
        if self.note:
            d["note"] = self.note
        return d


def analyze_gap(task_id: str, forecast: str, artifact: dict | None) -> Gap:
    """Compare a task's FORECAST to its recorded gate ARTIFACT (from control.run_gate).

    - no artifact yet                       -> UNVERIFIED (not executed)
    - artifact exit_code == 0 (gate passed):
        * forecast given and borne out in the output   -> CONFIRMED
        * forecast given but NOT borne out             -> DRIFT (passed for a different reason;
                                                          the gate may be too loose, or the
                                                          prediction was wrong — worth a look)
        * no forecast                                  -> CONFIRMED (nothing to compare)
    - artifact exit_code != 0 (gate failed)  -> REFUTED, with a classified blocker + next action
    """
    if artifact is None:
        return Gap(task=task_id, klass=UNVERIFIED, predicted=forecast,
                   magnitude=_DRIFT_MAGNITUDE[UNVERIFIED], note="no gate artifact yet")
    observed = (artifact.get("output_tail") or "").strip()
    passed = artifact.get("exit_code") == 0
    if passed:
        expected = _explicit_expectation(forecast)
        if expected is not None:
            # An explicitly checkable expectation: DRIFT iff the named string is absent.
            if expected and expected.lower() not in observed.lower():
                return Gap(task=task_id, klass=DRIFT, predicted=forecast,
                           observed=observed[:200], magnitude=_DRIFT_MAGNITUDE[DRIFT],
                           note=f"gate passed but the expected observation {expected!r} is "
                                "absent — tighten the gate or correct the forecast")
            return Gap(task=task_id, klass=CONFIRMED, predicted=forecast,
                       observed=observed[:200], magnitude=_DRIFT_MAGNITUDE[CONFIRMED])
        if forecast and _forecast_borne_out(forecast, observed):
            return Gap(task=task_id, klass=CONFIRMED, predicted=forecast,
                       observed=observed[:200], magnitude=_DRIFT_MAGNITUDE[CONFIRMED])
        if forecast and len(observed) < _MIN_OBSERVABLE:
            # A terse gate output (e.g. "24 passed in 0.24s") carries almost no vocabulary,
            # so a prose forecast can never be found in it. This is NOT drift (we did not
            # observe a divergence) and NOT a clean pass (the gate did not prove the claim).
            return Gap(task=task_id, klass=UNCHECKABLE, predicted=forecast,
                       observed=observed[:200], magnitude=_DRIFT_MAGNITUDE[UNCHECKABLE],
                       note="gate passed but its output cannot settle the forecast — add "
                            'expect:"<literal>" to FORECAST.md, or tighten the gate so it '
                            "emits the evidence")
        if forecast and not _forecast_borne_out(forecast, observed):
            return Gap(task=task_id, klass=DRIFT, predicted=forecast, observed=observed[:200],
                       magnitude=_DRIFT_MAGNITUDE[DRIFT],
                       note="gate passed but the prediction was not observed — verify the gate "
                            "actually proves the claim, or update the forecast")
        return Gap(task=task_id, klass=CONFIRMED, predicted=forecast, observed=observed[:200],
                   magnitude=_DRIFT_MAGNITUDE[CONFIRMED])
    blocker, unblock = classify_blocker(observed)
    return Gap(task=task_id, klass=REFUTED, predicted=forecast, observed=observed[:200],
               magnitude=_DRIFT_MAGNITUDE[REFUTED], blocker=blocker, unblock=unblock,
               note="gate did not pass; treat as the next unit of work, not a stop")


def _forecast_borne_out(forecast: str, observed: str) -> bool:
    """Loose check that the prediction shows up in the observation. Token overlap keeps it
    robust to phrasing: if a third of the forecast's distinctive words appear in the gate
    output, call it borne out. (The gate's own EXPECT is the hard check; this only decides
    CONFIRMED vs DRIFT for the adaptive log.)"""
    fwords = {w for w in re.findall(r"[a-zA-Z0-9_]{4,}", forecast.lower())}
    if not fwords:
        return True
    owords = set(re.findall(r"[a-zA-Z0-9_]{4,}", observed.lower()))
    hit = len(fwords & owords)
    return hit >= max(1, len(fwords) // 3)


def analyze_plan(tasks, forecasts: dict, gates_dir: str) -> list:
    """Produce a Gap per task from the recorded gate artifacts in `gates_dir`. Reads only —
    it does NOT run gates (that is `control.verify_plan`); this is the cheap post-hoc read the
    parent does after a step, or a poller does mid-run."""
    gaps = []
    for t in tasks:
        art = None
        p = os.path.join(gates_dir, f"{t.id}.gate.json")
        if os.path.isfile(p):
            try:
                with open(p) as fh:
                    art = json.load(fh)
            except (OSError, ValueError):
                art = None
        gaps.append(analyze_gap(t.id, forecasts.get(t.id, ""), art))
    return gaps


def recalibration_entries(gaps: list) -> list:
    """The subset of gaps that DEMAND a plan adjustment: DRIFT and REFUTED. CONFIRMED needs
    nothing; UNVERIFIED just hasn't run yet."""
    return [g for g in gaps if g.klass in (DRIFT, REFUTED, UNCHECKABLE)]


def write_recalibration(control_dir: str, gaps: list, note: str = "") -> str:
    """Append a timestamped recalibration block to RECALIBRATE.md for every DRIFT/REFUTED gap,
    each with its classified blocker and smallest unblocking action. This is the ledger the
    parent reads to adjust the plan from ground truth. Returns the path (or '' if nothing to
    record)."""
    entries = recalibration_entries(gaps)
    if not entries:
        return ""
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    lines = [f"\n## {ts} — {len(entries)} gap(s){(' — ' + note) if note else ''}\n"]
    for g in entries:
        lines.append(f"- **{g.task} [{g.klass}]** predicted: {g.predicted or '(none)'}")
        lines.append(f"  - observed: {g.observed or '(none)'}")
        if g.blocker:
            lines.append(f"  - blocker: **{g.blocker}** → {g.unblock}")
        lines.append(f"  - action: adjust the plan — {'reopen/repair this task' if g.klass == REFUTED else 'tighten the gate or update the forecast'}, and log the change here.")
    os.makedirs(control_dir, exist_ok=True)
    path = os.path.join(control_dir, "RECALIBRATE.md")
    if not os.path.exists(path):
        with open(path, "w") as fh:
            fh.write("# RECALIBRATE — gap analysis: where execution diverged from the plan\n")
    with open(path, "a") as fh:
        fh.write("\n".join(lines) + "\n")
    return path


def summarize(gaps: list) -> dict:
    """One-line health read of a run's adaptivity: counts per class + total drift."""
    counts = {CONFIRMED: 0, UNCHECKABLE: 0, DRIFT: 0, REFUTED: 0, UNVERIFIED: 0}
    for g in gaps:
        counts[g.klass] = counts.get(g.klass, 0) + 1
    total_drift = sum(max(0, g.magnitude) for g in gaps)
    return {"counts": counts, "total_drift": total_drift,
            "needs_recalibration": counts[DRIFT] + counts[REFUTED] + counts[UNCHECKABLE]}
