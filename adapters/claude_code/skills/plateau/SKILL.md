---
name: plateau
description: Bounded, predictable context for long Claude Code sessions — carry a small re-grounded signal across steps instead of letting context grow unbounded. Use on long-horizon coding sessions where the transcript would otherwise climb toward the context ceiling.
---

# Plateau — bounded context for Claude Code

Long coding sessions accumulate context until the window fills and the agent degrades.
Plateau keeps a small, re-grounded **signal** — goals, stance, lessons, pointers, and
*gated* facts — and inflates it at each step instead of replaying the whole transcript.
Context stays flat. A fact only enters the signal if it passes the gate (a Measurement
that re-verifies against the repo now), so the bounded context can't fill with stale or
fabricated claims.

This adapter is **thin**: it does I/O at the step boundary and delegates every decision
(inflate, ground, gate, emit) to the `plateau` core package.

## Install (plugin)

The core package must be importable, then the plugin auto-wires the step boundary:

```bash
pip install plateau          # when published; until then: pip install -e <path-to>/plateau
```

Enable this plugin in Claude Code. Its `hooks/hooks.json` then auto-installs:

- **`UserPromptSubmit` → `hook.py pre --cc`** — inflates the persisted signal, re-grounds it
  against the current repo, and **injects the carried self-state into the step as
  `additionalContext`** (so the model sees the bounded signal instead of the full transcript).
  Facts reality no longer supports are dropped as **stale** and flagged.
- **`Stop` → `hook.py post --cc`** — gates any facts queued in `.plateau/pending_facts.json`,
  folds the admitted ones into the signal, and persists the bounded blob to
  `.plateau/signal.json`. Only facts whose Measurement re-verifies are admitted.

The carried signal lives at `.plateau/signal.json` in the project root (keep it in or out of
version control, as you prefer — it is just the bounded signal blob).

## Slash commands

- **`/plateau:status`** — show the current carried self-state and anything dropped as stale.
- **`/plateau:gate`** — gate facts this session produced into the bounded signal and persist.

## Proposing a fact (the gate)

A proposed fact is `{claim, source, value, kind?}`. `kind` defaults to `file_hash`: `source`
is a repo-relative path and `value` is its expected `sha256:` hash. The gate admits the fact
only if hashing `source` right now equals `value`. **"The model said so" is never admitted** —
that is the whole point.

```json
[{"claim": "build passes", "source": "build.ok", "value": "sha256:<hash>"}]
```

## Manual / dry use (no plugin)

```bash
python adapters/claude_code/hook.py pre     # see carried state + stale (plain JSON)
python adapters/claude_code/hook.py post    # gate .plateau/pending_facts.json + persist
```

## Honest scope

Plateau bounds context and keeps only re-grounded state. It does **not** guarantee the agent
uses the carried state perfectly — that depends on the model. The measured claim (see `demo/`)
is the context bound itself: full-history context climbs toward the ceiling; Plateau stays flat
(C6: ~6,840 tok/step vs ~103 tok/step at completion parity, on real multi-module code). It
measures context **efficiency and recall** — nothing about understanding or any inner state.
