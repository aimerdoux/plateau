# Plateau

**Bounded, predictable context for long-horizon agents — with no recall penalty.** Carry
a small, re-grounded signal across steps instead of replaying the whole transcript.
Context stays flat as the task grows, and a stored fact stays one short line away.

![recall accuracy vs fact-distance: Plateau flat at 100%, full-history at ~18x the tokens](demo/recall_vs_distance3.png)

*Measured, pure-recall task (18 queries, random values, shuffled layout): Plateau answers
**18/18 correctly at every distance** while carrying a bounded ~120-token signal;
full-history answers 15/18 while carrying a transcript that climbs to ~2,138 tokens (~18×).
Honest verdict below — the head-to-head recall comparison came out **UNSCORABLE**, and we
say why rather than dress it up.*

## The paper

The mechanism is formalized in **[*The Integrator: A Free-Energy Filtering Account of
Compressed-State Continuity in Long-Running Agents*](paper/the-integrator-2026-06-02.pdf)** — a
theory-and-methods preprint that casts the loop as a recursive Bayesian filter (predict =
reasoning, update = the gate) plus a compression projection Π, with the demos below as its prior
results (C3/C4/C6) and a pre-registered forward program. It is a **draft**: every figure is
reconciled to the sealed artifacts in [`PAPER_RECONCILIATION.md`](PAPER_RECONCILIATION.md). The
account is functional and **silent on phenomenality** by construction.

## The idea

A long-running agent's scarcest resource is its context window. The naive loop carries the
full transcript forward, so context grows every step until the window fills and the agent
degrades. Plateau replaces *carry everything* with *carry a small re-grounded signal*:

- At each step you **emit** a compact `RelationalState` — `open_goals`, `stance`,
  `lessons`, `pointers`, and gated `verified_facts`.
- At the next step you **inflate** that signal instead of the transcript, and **ground**
  it: every carried fact is re-checked against the live environment; anything reality no
  longer supports is dropped as **stale**.

The catch that keeps a bounded context *honest*: a fact may enter the signal only if it
passes **the gate** — backed by a `Measurement` that re-verifies right now. A model's own
assertion is never a measurement. Bounded context is cheap; the gate is what stops it from
filling with confident fabrications.

This measures **context efficiency** and **recall** — nothing about understanding,
coherence, or any inner state.

## Quickstart

```bash
pip install -e .
python examples/bare_loop.py        # the whole loop in plain Python, no agent framework
```

## What we can and cannot claim (read this)

Every demo is pre-registered, sealed write-once before scoring, and scored by a locked rule —
including where it denies us a win. Full per-demo breakdown: [`demo/FINDINGS.md`](demo/FINDINGS.md).

**Proven, decisive — bounded context on real code (C6).** On a strictly serial ≥5-layer feature
built on this repo, the full-history arm's context climbed **365 → 37,405 tokens** over six
dependent steps (slope ~6,860), while Plateau stayed bounded **508 → 1,075** (slope ~103, **≈1.5%**
of full-history) — and **both arms reached PASS** (32 / 36 tests, zero rework): completion parity.
Sealed write-once, recompute PASS. [verdict](demo/verdict6b.json) · [readout](demo/demo6b_readout.md).
The same bound shows on every demo: full-history climbs toward the ceiling while Plateau stays flat
(~120 vs ~2,138 tokens on the recall task below).

**Strong — no recall penalty.** On the clean recall task (random values, shuffled layout),
Plateau answered **18/18 correctly at every distance** (demo3) on ~18× less context —
matched-or-beat full-history (100% vs 83%).

**Honest negative — we did NOT prove a recall *advantage* over full-history.** That was the
result we went looking for, and we did not get it:
- *demo2* (recall, but with sequential values + a sorted file): **NULL (near-miss).**
  Full-history degraded (far recall 0.50) but Plateau missed its own pre-registered 0.70
  far-recall floor by one query — and two of those misses were a layout artifact (grabbing
  a salient top-of-file line). [prereg](demo/demo2_prereg.md) · [verdict](demo/verdict2.json) · [readout](demo/demo2_readout.md)
- *demo3* (same task with the confounds removed and a bigger far bin): **UNSCORABLE.**
  Once values were random and positions shuffled, the full-history model recalled facts
  *well* even from a ~2,000-token transcript (far recall 0.80), degrading only 0.20 — below
  our pre-registered 0.25 anti-rig margin. The chain didn't bury facts deeply enough to
  *score* the comparison, so we don't claim one. [prereg](demo/demo3_prereg.md) · [verdict](demo/verdict3.json) · [readout](demo/demo3_readout.md)

So the defensible claim is **bounded context at no recall cost**, not "better recall than
full-history." A decisive recall-advantage win would need much longer contexts than are
economical to run here. We publish the UNSCORABLE/NULL rather than lengthen the chain until
the baseline breaks.

(An earlier arithmetic demo — [demo1](demo/demo_prereg.md), [chart](demo/context_per_step.png) —
showed the same token bound but had its completion axis confounded by arithmetic; that is
why the recall-only demos exist.)

See [`examples/continuum_story.md`](examples/continuum_story.md) for how this project's
discipline **killed its own headline hypothesis** and **caught its own fabricated "PASS"** —
the reason these receipts are worth reading. Integrity model: [`INTEGRITY.md`](INTEGRITY.md).

## Claude Code plugin

`adapters/claude_code/` is an installable **Claude Code plugin** (`.claude-plugin/plugin.json`,
a `plateau` skill, `hooks/hooks.json`, and slash commands). Enable it and the step boundary is
auto-wired: `UserPromptSubmit` inflates + re-grounds the carried signal and **injects it as
`additionalContext`** (the model sees the bounded signal, not the full transcript); `Stop` gates
queued facts and persists the bounded `.plateau/signal.json`. Commands: `/plateau:status`,
`/plateau:gate`. All decision logic stays in the zero-dep core — the adapter is only step-boundary
I/O. See [`adapters/claude_code/`](adapters/claude_code/).

**Install in a fresh Claude Code session:**

```bash
pip install git+https://github.com/aimerdoux/plateau.git    # the core (so the hook can import plateau)
```
```
/plugin marketplace add aimerdoux/plateau
/plugin install plateau@plateau
```

The hooks and `/plateau:*` commands activate automatically. The carried signal persists to
`.plateau/signal.json` in the project. (The hook runs `python3`; install the core into the
same interpreter Claude Code's hooks use.)

## The condensation limit (stated plainly)

Plateau does not claim flat-forever recall. Its signal is bounded, so it can hold only so
much; past the point where more distinct facts must be live than the signal carries, recall
must fall and real context has to be added back. Plateau bounds and re-grounds context; it
does not abolish the need for context.

## Layout

```
plateau/        core: signal (gate), continuum (emit/inflate/ground), metrics, integrity
examples/       bare_loop.py (host-free proof) + the continuum story
demo/           pre-registered demos (recall + real-code C6), sealed raw, verdicts, FINDINGS.md
adapters/       claude_code/ — installable Claude Code plugin (plugin.json, skill, hooks, commands)
paper/          The Integrator — theory-and-methods preprint (draft)
tests/          28 tests (26 core + 2 adapter), core has zero third-party deps
```

## License

Apache-2.0. See [LICENSE](LICENSE).
