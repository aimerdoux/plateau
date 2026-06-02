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
(inflate, ground, gate, emit) to the `plateau` core package. See the repo root for the
core and `demo/` for the measured context-bounding result.

## What it does

- **Pre-step** (`hook.py pre`): inflates the persisted signal and re-grounds it against
  the current repo. Prints the carried self-state to surface into the next step, and
  flags any facts that went **stale** (reality moved, so they were dropped — not trusted).
- **Post-step** (`hook.py post`): gates newly proposed facts. Only facts whose
  Measurement re-verifies are admitted to the signal; the rest are dropped and reported.
  The updated, bounded signal is persisted to `.plateau/signal.json`.

## Install

```bash
pip install -e .            # from the repo root (installs the plateau core)
```

## Use it manually

```bash
# at the start of a step: see what's carried, and what went stale
python adapters/claude_code/hook.py pre

# propose facts this step produced (each must be re-verifiable), then gate + persist:
#   .plateau/pending_facts.json = [{"claim":"build passes","source":"build.ok","value":"<sha256>"}]
python adapters/claude_code/hook.py post
```

A proposed fact is `{claim, source, value, kind?}`. `kind` defaults to `file_hash`:
`source` is a path (relative to the repo) and `value` is its expected `sha256:` hash.
The gate admits the fact only if hashing `source` right now equals `value`. "The model
said so" is never admitted — that is the whole point.

## Wire into Claude Code hooks (optional)

Point a session/step hook at `hook.py pre` (to surface carried state) and `hook.py post`
(to gate + persist). Keep the project's `.plateau/` directory out of version control or
in it, as you prefer — it is just the carried signal blob.

## Honest scope

Plateau bounds context and keeps only re-grounded state. It does **not** guarantee the
agent uses the carried state perfectly — that depends on the model. The measured claim
(see `demo/`) is the context bound itself: full-history context climbs toward the
ceiling; Plateau stays flat. Completion parity in the demo was confounded by a noisy
toy task and is reported honestly there as not-a-clean-win.
