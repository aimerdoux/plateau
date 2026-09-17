"""plateau.bridge — the receipt graph: what a session actually touched.

Every tool call becomes a receipt (`common.record`); receipts fold into a small graph
of nodes (files, symbols, errors, tests, commands, searches, read facts, decisions) and
edges between them. At SessionStart the graph is scored against the task at hand and a
budget-bounded slice is injected back as `<plateau_index>` — data, never instructions.

This is a sibling of `plateau.signal` (the SIGNAL/THOUGHT gate), not a replacement: a
receipt about a file is exactly a `Measurement(kind="file_hash", ...)` by construction
(see `common.measurements`). Nothing about the core gate changes here.

Public modules: `common` (store + classify + record), `config` (BridgeConfig / bridge.toml
resolution), `query` (selector v2 — scoring, selection, rendering), `receipt` / `snapshot`
/ `inject` / `lookup` (the four hook entry points), `handoff` (session handoff blocks).
"""

from __future__ import annotations
