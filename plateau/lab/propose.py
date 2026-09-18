#!/usr/bin/env python3
"""plateau.lab.propose — `plateau propose` (docs/harness-0.3/PLAN-step4.md
"`plateau propose`").

Builds a prompt from this repo's `plateau report --json` aggregates plus the formal
`plateau.lab.model` docstrings, and asks a disposable `claude -p` (every tool
disallowed — a hypothesis generator must never touch the filesystem or spend a turn
doing anything but reasoning over the numbers it was given) for at most 3 hypotheses,
each naming a discriminating change limited to a `bridge.toml` key or an edit to
`plateau/bridge/query.py`, with a bet probability and an estimated cost. Writes the
result to `proposals/<date>.md`.

ZERO SPEND (S4-A3): `run_claude()` is the ONLY place this module ever starts a
subprocess; every test in this repo monkeypatches it (never `subprocess` itself), so no
test run here ever spends a real token. This module's own docstring and this step's
implementer are both under the same instruction: never invoke it live.
"""

from __future__ import annotations

import argparse
import inspect
import json
import os
import subprocess
import sys
from typing import Any, Dict, List, Optional

from ..bridge import common as bridge_common
from . import ledger as ledger_mod
from . import model as model_mod

# Every tool disallowed -- mirrors `plateau.lab.probes.PROBE_DISALLOWED_TOOLS` (same
# shape, duplicated rather than imported: this module has no other dependency on
# `plateau.lab.probes`, and the two lists are free to diverge if either job's tool
# surface ever needs to).
ALL_TOOLS = (
    "Bash,Read,Edit,Write,MultiEdit,NotebookEdit,Grep,Glob,Task,Agent,"
    "WebSearch,WebFetch,TodoWrite,LSP"
)

_MODEL_FUNCTIONS = ("recall", "auc", "presence", "loss", "break_even_chars", "crossover_lag")


def _model_docstrings() -> str:
    """`plateau.lab.model`'s module docstring plus each of its six formal functions'
    docstrings — "the formal model docstrings" the prompt is built from
    (PLAN-step4.md)."""
    parts = [inspect.getdoc(model_mod) or ""]
    for name in _MODEL_FUNCTIONS:
        fn = getattr(model_mod, name, None)
        if fn is None:
            continue
        doc = inspect.getdoc(fn) or ""
        parts.append(f"### {name}\n\n{doc}")
    return "\n\n".join(p for p in parts if p)


def build_prompt(report_data: Dict[str, Any], model_docs: str) -> str:
    """The prompt sent to the disposable `claude -p` fork: this repo's `plateau report
    --json` (per-`bridge_version` ledger aggregates) plus `plateau.lab.model`'s formal
    docstrings, followed by explicit output constraints (PLAN-step4.md "`plateau
    propose`": at most 3 hypotheses, each with a discriminating change limited to a
    `bridge.toml` key or an edit to `plateau/bridge/query.py`, a bet probability, and a
    cost estimate)."""
    report_json = json.dumps(report_data, indent=2, sort_keys=True)
    return (
        "You are proposing discriminating experiments for the Plateau context bridge "
        "(a receipt-graph injected into a coding agent's context to reduce information "
        "re-derivation across compactions).\n\n"
        "Below is `plateau report --json` -- per-bridge_version aggregates from this "
        "repo's session ledger -- and the formal recall/loss/presence model this lab "
        "uses to interpret them.\n\n"
        "```json\n" + report_json + "\n```\n\n"
        "## Model (plateau.lab.model)\n\n" + model_docs + "\n\n"
        "---\n\n"
        "Propose AT MOST 3 hypotheses for why the numbers above look the way they do. "
        "For EACH hypothesis, give exactly these fields:\n\n"
        "  1. name -- a short label\n"
        "  2. observation -- the specific number(s) above it explains\n"
        "  3. change -- a DISCRIMINATING CHANGE that would test it. It must be EITHER:\n"
        "     (a) one `bridge.toml` key and its proposed new value, or\n"
        "     (b) one function in `plateau/bridge/query.py` and the change to make to it.\n"
        "     No other file may be named. No change may be proposed to "
        "`plateau/lab/model.py`, `plateau/lab/fit.py`, `plateau/lab/promote.py`, or "
        "anything under `experiments/` -- those are human-only.\n"
        "  4. bet -- your probability, 0 to 1, that the change moves the relevant "
        "metric in the predicted direction\n"
        "  5. cost -- an estimated number of sessions (or tokens) to run the experiment\n\n"
        "Answer in Markdown, numbered 1 to at most 3, with nothing else before or after."
    )


def run_claude(prompt: str, env: Dict[str, str]) -> str:
    """Spawn the disposable `claude -p <prompt> --disallowedTools <all> --output-format
    json` and return its raw stdout. The ONLY place this module ever starts a
    subprocess; tests monkeypatch this function (never `subprocess` itself). `env` is
    always `plateau.bridge.common.child_env()`'s result (S4-A2) so this fork never
    inherits the parent process's own Claude-Code session identity. Never invoked in
    this step (ZERO SPEND) except by a test's stub."""
    cmd = [
        "claude", "-p", prompt,
        "--disallowedTools", ALL_TOOLS,
        "--output-format", "json",
    ]
    proc = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=600)
    return proc.stdout or ""


def _extract_text(raw_stdout: str) -> str:
    """The response text out of `claude -p ... --output-format json`'s envelope (its
    `result`/`text` field), or the raw stdout verbatim if it is not JSON (a stub
    runner in tests may return plain Markdown directly). Mirrors
    `plateau.lab.probes._extract_answer`'s shape; duplicated rather than imported so
    this module carries no dependency on `plateau.lab.probes`."""
    if not raw_stdout:
        return ""
    try:
        envelope = json.loads(raw_stdout.strip())
    except Exception:
        return raw_stdout
    if isinstance(envelope, dict):
        return str(envelope.get("result") or envelope.get("text") or "")
    return raw_stdout


def render_proposal(text: str, date: str) -> str:
    """`proposals/<date>.md`'s content: a short header naming the constraint this
    proposal was generated under, then the model's response verbatim."""
    header = (
        f"# Proposal — {date}\n\n"
        "_Generated by `plateau propose` from `plateau report --json` and the "
        "`plateau.lab.model` docstrings. Each hypothesis's discriminating change is "
        "limited to a `bridge.toml` key or `plateau/bridge/query.py` "
        "(docs/harness-0.3/PLAN-step4.md)._\n\n"
    )
    return header + (text or "").strip() + "\n"


def main(argv: Optional[List[str]] = None) -> int:
    """`plateau propose --date YYYY-MM-DD`: builds the prompt, runs `run_claude()`,
    writes `proposals/<date>.md`. Never invoked live in this step (see module
    docstring)."""
    argv = sys.argv[1:] if argv is None else argv
    ap = argparse.ArgumentParser(prog="plateau propose")
    ap.add_argument("--date", required=True, help="output stamp, e.g. 2026-09-17 -> proposals/<date>.md")
    ap.add_argument("--root", default=None, help="repo root (default: git toplevel of cwd)")
    args = ap.parse_args(argv)

    root = args.root or bridge_common.root({})
    report_data = ledger_mod._report_data(root)
    prompt = build_prompt(report_data, _model_docstrings())

    raw = run_claude(prompt, bridge_common.child_env())
    text = _extract_text(raw)
    body = render_proposal(text, args.date)

    proposals_dir = os.path.join(root, "proposals")
    os.makedirs(proposals_dir, exist_ok=True)
    out_path = os.path.join(proposals_dir, f"{args.date}.md")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(body)

    print(f"plateau propose: wrote {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
