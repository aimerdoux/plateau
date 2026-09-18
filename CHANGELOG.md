# Changelog

All notable changes to Plateau are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.4.0] — Unreleased

The continuum (`docs/toy/continuum-toy.html`): a context window holds the last few requests,
and a compaction evicts the rest. The toy's claim is that what should cross a compaction is
not "everything old" but exactly the knowledge the current request descends from -- walk
the arrows back from the request's own calls, keep the facts, errors, and decisions on that
path. 0.4 gives the receipt store that second arrow (`because`: the reason the assistant
stated before a tool call, lifted from its own text) and the carry rule over it, and wires
the rule into the `compact` injection. The sealed D-037/D-038 instruments are untouched:
the legacy path never lifts and never carries.

### Added

- **The `because` arrow** (`plateau/bridge/common.py`, `lift.py`, `receipt.py`) --
  `receipts.tool_use_id` (the PostToolUse payload's id, so a call's receipt can be found
  again from the transcript's `tool_use` block), a `reasons` table (`rid`, `session_id`,
  `tool_use_id`, `text`), `common.KNOWLEDGE_KINDS` (`read`, `decided`, `error`, `symbol`:
  what an arrow may start from and what the continuum carries), `common.record_reason` /
  `common._link_because` (the reason row plus a `(key, "because", r<rid>, rid)` edge from
  every earlier knowledge node sharing at least `REASON_MIN_OVERLAP` non-stopword tokens
  with the reason -- the selector's own overlap, pointed at the call instead of the
  prompt), `lift.reasons_from_transcript` / `lift.lift_reasons` (pairs each `tool_use`
  with the `text` blocks before it in the same `message.id`, never a `thinking` block;
  idempotent per receipt), and the `reason session=<id> n=<k>` hook-log line at `Stop`.
- **`plateau.bridge.carry`** -- the toy's `compute()` transliterated: the pure rule
  (`Node`, `Carry`, `cutoff`, `ancestors`, `carry`) over any node map and edge list,
  asserted verbatim against the exported fixture, and the store adapter
  (`turn_of_rid`, `graph_from_store`, `carry_from_store`) that builds the graph from the
  whole store as one session sees it -- its own receipts dated by `turns.rid_at`, the
  knowledge they produced at the turn of the first receipt that did, its decisions at the
  turn whose `Stop` lifted them, the open turn as the current request, and everything
  another session did at turn 0: walkable ancestry, never `now`, never inside the window.
- **Compaction carry** (`plateau/bridge/inject.py`, `query.py`) -- on `compact`, the hook
  lifts the open turn's reasons from the transcript, asks `carry_from_store(...,
  window=0)` -- nothing stays: a Claude Code compaction summarizes the open turn's own
  earlier calls too, so what they produced is evicted like a previous turn's -- and
  passes the carried keys as `select(carried_keys=...)`; carried lines
  are rendered with a trailing `◉` ahead of sticky, quota, and fill, budget permitting
  (a carried line that does not fit is skipped, never squeezed in), and the log line
  gains a ` carried=<m>` suffix counting the carried lines that made it. A lift that raises is rolled back, so a reasons row
  never lands without its arrows. `[continuum] carry` in `bridge.toml` (and
  `bridge.default.toml`, kept byte-identical) is the kill switch; `bridge.toml` is now
  version `2.1`, so 2.0 and 2.1 injections stay distinguishable in the ledger.
- **The continuum toy** (`docs/toy/continuum-toy.html`) and its exported fixture
  (`tests/fixtures/continuum_toy.json`: 21 nodes, 24 edges, the expected answer for every
  request in both arms).
- Tests, as pytest collects them: `tests/test_reason.py` (14), `tests/test_carry.py`
  (30, the pure rule against the fixture, both arms at every request),
  `tests/test_carry_store.py` (40, the toy session replayed through the real store API),
  `tests/test_continuum_inject.py` (20, the hook as a subprocess), and one
  `last_user_prompt` case in `tests/test_selector.py`.

### Changed

- `common.record_decision` now draws `because` edges from the knowledge nodes a decision
  descends from (the toy's `f1 -> d1`).
- `query.select()` takes a keyword-only `carried_keys`; `render_line()` appends ` ◉` after
  the ` ★` lexical marker. Without `carried_keys` both are unchanged.
- The `<plateau_index>` head legend reads `★ = matches current prompt, ◉ = this request
  descends from it.` on a compaction that ran the carry step; every other block keeps
  the 0.3 head byte-for-byte, and the `<d037_index>` legacy head is unchanged.
- `query.last_user_prompt`, `lift.reasons_from_transcript` and the Stop hook's
  `lift._last_assistant_text_blocks` decode the transcript with `errors="replace"`: a
  tail cut inside a multibyte sequence (Claude Code appends the JSONL while the hook
  reads it) is skipped like any garbage line instead of raising `UnicodeDecodeError` out
  of the hook -- `inject` injecting nothing, or `Stop` losing the last message's
  `DECISION:`/`FACT:` lines for good and lifting no reasons that turn.
- `bridge.toml` / `bridge.default.toml`: `version = "2.1"`, new `[continuum]` table;
  `BridgeConfig` gains `continuum`.

### Findings

- Replaying the toy session through the real store reproduces 9 of its 18 `because`
  arrows (`tests/test_carry_store.py::test_store_reproduces_exactly_these_toy_because_edges`).
  The 9 it cannot draw are structural: the store has no request node, `_link_because`
  starts an edge only at a knowledge node (no action-to-action "verify the edit"
  arrow), and a decision lifted at `Stop` cannot be the cause of the same-turn call that
  applied it. So at request 5 the store carries nothing where the toy carries one node,
  the error `e1` (`test_request_5_honest_store_value_vs_toy`).
- Reasons are only lifted at `Stop`, so a compaction taken mid-turn would see the open
  turn's calls with no arrow at all and carry nothing
  (`test_open_turn_before_its_stop_has_no_reasons`); this is why `inject` lifts the open
  turn's reasons itself before it carries (`tests/test_continuum_inject.py`).
- The toy's window keeps the current request visible, so a window of one request
  leaves knowledge the open turn produced itself out of `carried` even when the open
  turn descends from it (a read three calls ago, acted on now). A real compaction
  summarizes the open turn as well, which is why the hook asks with `window=0` (the
  cutoff past the turn, so the ancestry is carried in full;
  `test_same_turn_ancestry_is_carried_because_a_compaction_evicts_the_open_turn_too`).
- `plateau absorb` is unchanged: it matches the inject log line by its 0.3 prefix and
  reads only the columns it always did, so the ` carried=<m>` suffix, the `reasons`
  table and the `because` edges are not yet emitted as primitives (`--check` still
  passes over a 2.1 store; nothing is absorbed from the continuum either).
- A decision recorded mid-turn before any receipt of that turn is indistinguishable from
  one recorded at the previous `Stop` and is placed there: its cursor is the previous
  boundary and no later Stop precedes it (documented on `carry.graph_from_store`; the
  placement rule itself is pinned by
  `test_decision_at_the_stop_of_an_empty_turn_lands_in_that_turn` and
  `test_decision_in_the_open_turn_after_a_receipt_stays_in_the_open_turn`).

## [0.3.0] — 2026-09-18

The harness refactor (`docs/harness-0.3/PLAN.md`): the sealed D-037 Ω hook bundle becomes
a public `plateau.bridge` package with its own selector, provenance-tracked config, and
session handoff blocks, plus a `plateau.lab` recall/loss/presence model and a `plateau`
CLI. `d037_hooks/` keeps running byte-for-byte as a thin shim over the new package — the
sealed D-037/D-038 instruments are never edited and never change behavior.

### Added

- **`plateau.bridge` package** — the receipt store and its hook entry points, ported from
  the sealed D-037 Ω bundle (`d037_hooks/` at git tag `d037-hooks-sealed`, commit
  `a342094`) into `plateau/bridge/{common,config,query,receipt,snapshot,inject,lookup,
  handoff}.py` over a schema-v1 sqlite store (`receipts`, `nodes`, `edges`, `compactions`,
  `injections`, `decisions`, `turns`, `meta`; WAL mode, stdlib `sqlite3` only).
  `common.classify()` keeps the D-037 classification rules verbatim and adds "read facts"
  (signatures / config keys / grep hits lifted from Read/Grep results) and Stop-time
  decisions as new node kinds.
- **Selector v2** (`plateau/bridge/query.py`) — query-aware, budget-bounded node
  selection: a structural score (recency scaled by a receipts-per-turn-derived `tau`,
  degree, per-kind weight) blended with a BM25-lite lexical match against the last user
  prompt at compaction; stickiness across compactions; a "bridge quota" floor that
  reserves budget for nodes older than the previous compaction so a burst of recent
  activity cannot starve out still-relevant older facts.
- **Config with provenance** (`plateau/bridge/config.py`, `_toml.py`, `bridge.toml`) —
  `BridgeConfig` resolution order is packaged defaults ← `~/.plateau/bridge.toml` ← root
  `bridge.toml` (or a deterministically-bucketed `bridge.canary.toml`) ←
  `.plateau/config.toml [bridge] enabled`; every receipt and injection row now records
  which file won (`role`: incumbent/canary/off) and its sha256, not just its version
  string. A dependency-free fallback TOML parser (`_toml.py`) covers the exact subset
  `bridge.toml` and `.plateau/config.toml` use, for Python 3.9/3.10 (no `tomllib`).
- **Handoff block v1** (`plateau/bridge/handoff.py`) — a `<plateau_handoff v=1>` text
  block (and its JSON form) summarizing a session's git identity, store cursor, last
  injection, last snapshot, open errors/failing tests, and recent decisions, with ready
  `lookup`/`resume` commands for whoever (or whichever agent) picks the session back up.
  Reads the store directly via `sqlite3` against the schema-v1 table/column names,
  independent of `plateau.bridge.common`, so it degrades to all-zero/`none` fields
  instead of failing when no store exists yet.
- **`plateau.lab.model`** — the recall/loss/presence decay model as six pure, dependency-
  free functions (`recall`, `auc`, `presence`, `loss`, `break_even_chars`,
  `crossover_lag`), and root `model.toml`, seeded from D-038 run 1
  (`experiments/d038/results.json`, sealed): arm A ("none") `recall_by_comp` 0.933 /
  0.462 / 0.333, `lambda_by_lag` 0.0 / 0.31 / 0.66, AUC 0.618, 142 rederivations, 143 676
  tokens/turn; arm C ("d037-omega-6000") `recall_by_comp` 0.95 / 0.917 / 0.059,
  `pi_by_comp` 0.96 / 0.0, AUC 0.744, 105 rederivations, 109 215 tokens/turn. Arm A has no
  receipt store, so its `receipts_per_turn` is recorded as 0 with an explanatory comment,
  not measured as zero.
- **`plateau` CLI** (`plateau/cli.py`; `[project.scripts] plateau = "plateau.cli:main"`)
  — `lookup`, `handoff`, `version`, and `doctor` (spins up a scratch git repo, drives
  `receipt`/`snapshot`/`inject` through it as subprocesses against synthetic hook
  payloads, and checks that a receipt is recorded, a snapshot file is written, the
  injection stays under budget, and a handoff block renders — printing PASS/FAIL per
  check, SKIP while the bridge package is mid-edit). `init`, `resume`, `report`, `fit`,
  `propose`, `learn`, and `sync` are registered so the full command surface exists, and
  each prints `not implemented in 0.3.0-step2` (exit 2) until a later step fills it in.
- **Legacy shims** — every hook in `d037_hooks/` (except `test_hooks.py`,
  `settings.*.json`, `CLAUDE.md.snippet`, `launch_toy.sh`) is now a thin re-export of its
  `plateau.bridge` twin, pointed at the old `.d037/` paths and the `<d037_index>` tag via
  env overrides the new modules honor (`PLATEAU_DB_REL`, `PLATEAU_LOG_REL`,
  `PLATEAU_LEGACY_TAG`) — so the sealed D-037/D-038 instruments keep running unchanged
  and `python3 d037_hooks/test_hooks.py` still prints
  `ALL CHECKS PASSED; B≡C store parity OK`.
- **Claude Code adapter wiring, `init`/`resume`, decided-fact lifter** — the plugin's
  `hooks.json` now wires all nine hook modes (`SessionStart` `parent`+`inject`,
  `UserPromptSubmit` `pre`, `PostToolUse` `receipt`, `PreCompact` `snapshot`, `Stop`
  `post`+`lift`+`handoff --print`, `SessionEnd` `ledger`+`handoff --write`,
  `SubagentStop` `handoff --write --agent subagent`). `plateau init [--global]` writes
  the same table into `.claude/settings.json` (idempotent merge, foreign entries kept,
  one `.plateau.bak` backup, `--uninstall` removes only our entries) and `plateau
  init --global` also seeds `~/.plateau/bridge.toml`. `plateau resume <session_id>
  [prompt]` starts a fresh `claude -p` whose `SessionStart(startup)` injection is
  prefixed with the stored handoff block, so the shared store's receipt ids continue
  rather than restart. `plateau/bridge/lift.py` lifts `DECISION:`/`FACT:` lines from the
  last assistant message at Stop into `decisions`/`decided` rows, deduped per session.
  Subagent handoffs write to `.plateau/handoff/<session_id>.subagent-<agent_id>.json` so
  `SessionEnd` never clobbers one.
- **One install story** — `parent`/`pre`/`post` moved out of the adapter into
  `plateau.hooks.signal`, so `adapters/claude_code/hook.py` and `plateau hook <mode>`
  are two entry points over one implementation for all nine modes, byte-for-byte
  identical hook JSON either way.
- **Session identity on every spawn** — every process Plateau spawns (`plateau resume`,
  the shadow-probe fork, `plateau.agency.driver.spawn_agent`, `plateau propose`) goes
  through `plateau.bridge.common.child_env()`, which strips the inherited
  `CLAUDECODE`/`CLAUDE_CODE_SESSION_ID`/`CLAUDE_CODE_REMOTE_SESSION_ID`/
  `CLAUDE_AUTOCOMPACT_PCT_OVERRIDE` so the child always gets a fresh session id. Ledger
  rows, handoff files, and holdout hashes key on `(session_id, agent_id)`, with the main
  agent's `agent_id` the empty string; shadow probes run for the main agent only.
- **`plateau.lab`** — a shadow-probe/ledger/fit/promote/propose lab layered on top of
  the bridge, off by default (`[lab] shadow_probes = false`; spends tokens once on):
  `ledger.py` upserts one `sessions` row per session plus `probes`/`rederivations` rows
  at `SessionEnd`, reading the store, the transcript, and `.plateau/hooks.log`;
  `probes.py` runs a shadow probe from the Stop hook every `shadow_probe_every_turns`
  turns on a `--fork-session` child (never in the main session) and grades it
  exact/fuzzy/wrong; `fit.py` implements `plateau report`/`plateau fit` (refits α, λ,
  π into `model.toml` cells only where sessions ≥ 5, never deleting existing cells);
  `promote.py` implements `plateau learn` and the promotion rule (`MIN_SESSIONS = 20`,
  `PI_GAIN = 0.15`, `REDERIV_TOL`/`TOKENS_TOL = 0.05`, `RETIRE_AFTER = 60`,
  `decide(...) -> "promote"|"keep"|"retire"`), writes PR bodies containing only
  aggregates, and refuses to write one that `body_leaks` flags; `propose.py` implements
  `plateau propose` (builds a prompt from `report --json`, runs a `claude -p` proposal
  turn, writes `proposals/<date>.md`) but is **never executed in this step** — it is
  exercised only against a stubbed runner, so step 4 spends zero dollars on live
  `claude -p` calls.
- **Private ring** (`plateau/ring.py`) — `plateau sync` clones/pulls a git-or-path
  remote named in `.plateau/config.toml` (off, printing `private ring: off`, when the
  remote or its token env var is unset), pushes the session ledger and a curated
  layer (`files`, `fixes`, `decisions`, `procedures` tables) under a per-repo key, and
  `ring.curate()` promotes a receipt shape that repeats 3× into a named procedure and
  demotes entries unused over the last 10 sessions. `plateau/bridge/config.default.toml`
  is the packaged `.plateau/config.toml` template (`[bridge] enabled`, `[lab]
  shadow_probes`, `[private_ring] remote`/`key`).
- **`plateau doctor` (full)** (`plateau/doctor.py`) — drives one fake `PostToolUse`,
  `PreCompact`, `SessionStart(compact)`, and `Stop` through the hooks the project's or
  global `settings.json` actually installs (falling back to the package modules
  directly), and additionally checks the ledger is writable, config resolves, and
  reports private-ring status; PASS/FAIL/SKIP per check, exit 1 on any FAIL.
- **Guardrails** — `.github/CODEOWNERS` requires a human (`@aimerdoux`) on
  `plateau/lab/model.py`, `plateau/lab/fit.py`, `plateau/lab/promote.py`,
  `experiments/`, and `docs/harness-0.3/PLAN*.md`; `.github/workflows/guardrails.yml`
  fails a PR that touches those paths when its author login ends `[bot]` or its head
  branch starts `plateau/learn-`, as an independent required-status-check backstop to
  branch-protection settings.
- **Single owner for `plateau/cli.py`** — every lab/ring/doctor subcommand
  (`report`, `fit`, `propose`, `learn`, `sync`, `doctor`) is a thin `importlib`
  delegation from `cli.py` to its module's entry point, with a `not available` message
  on `ImportError`, so the CLI never depends on landing order across owners.

### Notes

- **D-037 erratum**, carried forward unedited from the sealed record
  (`experiments/d037/D-037.md`): "Bash was denied under headless acceptEdits; no pytest
  ran and arm C's lookup path never executed. File-based recall result unaffected." This
  refactor moves where that bundle's code lives; it does not revisit D-037's own
  conclusion (online loop unsupported on that chain — λ̂ = 0 in 3/3 runs, no arm lost a
  k−3 fact).

## Docs-only pass, shipped in [0.3.0]

Docs-only pass — no core or agency logic changed. Adopts the polish of a strong
per-payload-compression README (crisp tagline, badges, time-boxed quickstart sections, an
ASCII parent→orchestrator→worker diagram, a "Compared to" table, progressive `<details>`
disclosure) while keeping every Plateau integrity guardrail — and never adopting a claim the
sealed artifacts don't support.

### Added

- **Metacognition (faithfulness) result** added to README's validated set: a recursive self-reliability
  estimate `R̂` tracks *actual* reliability under induced corruption — **CALIBRATED** via the gate-output
  proxy (sealed, recompute PASS) and reproduced at the endpoints on a 5-dispatch live-agent pilot. Honest
  scope: a calibration result, **Proposition-1 aggregate-only**, **silent on phenomenality** (calibration
  ≠ awareness). Sealed in the parent tree at `reports/continuum/metacog/` + `metacog_kl_v2/`.
- **`BENCHMARKS.md`** — the live `wavex-os` agency run plus the sealed demos, with **every number
  sourced** to its artifact (`AGENCY_RUN_REPORT.md` §-by-§, `FLEET_REPORT.md`, sealed verdicts).
  Headline run figures: parent **0 compactions**, **76,030** signal tokens vs **40.39M** worker
  tokens bypassed (**≈531:1**, observed this run), peak single-step cache_read **7,294,973** tok,
  **4** orchestrators, **3** PRs **emitted and never merged**; the 19-agent fleet beneath it ran
  **500 issues / 439 done / 2,499 heartbeat runs** (live-API counts, not the brief's estimates).
- **`plateau/agency/bench_summary.py`** — a read-only script (`python -m plateau.agency.bench_summary`)
  that prints the sourced run metrics verbatim from the sealed reports. It recomputes nothing and
  labels the two modelled estimates (the ~202 hypothetical inline compactions and the USD cost) as
  estimates.

### Changed

- **`README.md`** rewritten for parity-of-polish: ASCII wordmark + truthful pillar subhead, honest
  badges only (License / Python 3.9+ / tests 71 passing / zero core deps — **no** PyPI/codecov/social
  badges, which aren't earned yet), time-boxed "30-second idea" / "60-second quickstart" headers, an
  ASCII three-tier architecture diagram, a **Proof** section led by the wavex-os run, a "When to use ·
  when to skip" table, and a "Compared to" table that **concedes** per-payload compressors' strength
  and frames them as complementary (run a compressor *inside* a Plateau worker). Dense cycle/install
  detail collapsed into `<details>` blocks.

### Integrity guardrails (explicitly held)

- The 3 wavex-os PRs are described as **emitted, never merged** — never "merged to main" (the agency
  is code-enforced not to merge/force-push/push to `main`; that is a selling point).
- Fleet counts use the **live-API-authoritative** values (439 done / 2,499 runs); the run brief's
  round estimates (~441 / ~2,482) are noted, not published as fact.
- The footprint law `O(agents+resumes)` is stated as a **design property corroborated** by 0
  compactions — **not** a swept-`N` live experiment; the 531:1 ratio is labelled **observed for this
  one run**, not a guaranteed constant.
- No recall/capability advantage claimed (demo2/demo3/demo4 nulls retained); no "compresses better
  than Headroom" claim; no "docs online / on PyPI" claim until those artifacts exist; the clean-machine
  install `[VERIFY]` marker is retained.

## [0.2.0] — 2026-06-03

The release that adds the **agency layer** on top of the bounded-context core: a
parent → orchestrator → worker delegation hierarchy that keeps a *parent* agent's
context flat across an arbitrarily long mission, proven on a live run.

### Added

- **`plateau.agency` subpackage** — the external bounded-context QA driver, folded into
  the core. The orchestrator is a plain Python process whose only memory is `signal.json`,
  so it does not grow; each step spawns a fresh `claude -p` worker that sees only the
  carried signal plus one subtask. Console entry point: **`plateau-agency`**
  (`plateau.agency.driver:main`). It **reuses the core** rather than duplicating it —
  facts bind via `plateau.signal.Measurement(kind="file_hash").reverify()` and
  `plateau.integrity.file_hash`, not a private hasher.
- **Three prose layer contracts** shipped with the package:
  - **`PARENT_AGENT_MANUAL.md`** — usable verbatim as a parent system prompt; turns a
    one-line operator mission into N background orchestrators and holds the parent's
    footprint at O(A + R), independent of internal step count N.
  - **`ORCHESTRATOR_PROMPT.md`** — the bounded loop: pick one, spawn one worker, gate,
    meter to disk, shed; return to the parent EXACTLY ONCE.
  - **`BACKGROUND_AGENCY.md`** — the worker contract (fresh per unit, one-line return,
    detail to disk, then discarded).
- **Gate re-verify** in `plateau.agency.gate`: a fact is admitted only after a real
  re-ground — `file_hash` sha256 binds to file *content* (the core `Measurement`), and
  command gates capture an `exit_code` / normalized `test_result` in a hashed
  `result.json`. The agent's word is never "done."
- **CHANGELOG.md** (this file).

### Changed

- **Bounded control loop** in `plateau.orchestrator`: `serve_forever` drives the
  never-returning loop and `should_continue` is the single bounded stop-decision, so the
  loop is provably flat (see `context_proven_bounded`) instead of growing per step.
- **Packaging** — the wheel now ships the agency `*.md` contracts (including
  `PARENT_AGENT_MANUAL.md`) and the example override configs under `plateau/agency/configs/`,
  via explicit `[tool.hatch.build.targets.wheel].artifacts` (neither `*.md` nor `*.json`
  is auto-included by hatchling).

### Validated

- **Live `wavex-os` case study** — the agency drove a real bounded QA-hardening run:
  **4 bounded orchestrators** (`connectors`, `fleet-observe`, `fleet-launch`, `onboarding`),
  a **live 19-agent sonnet fleet** of ephemeral workers beneath them, and **3 PRs**
  emitted in `write` mode and never merged by the agency
  ([wavex-os #44](https://github.com/aimerdoux/wavex-os/pull/44),
  [#45](https://github.com/aimerdoux/wavex-os/pull/45),
  [#46](https://github.com/aimerdoux/wavex-os/pull/46)). **The parent never compacted.**
  Full report: `/Users/geniex/wavex-os/.plateau-agency/reports/AGENCY_RUN_REPORT.pdf`.

## [0.1.0] — 2026-06-02

Initial release of the bounded-context core.

### Added

- **Core** (`plateau`, zero third-party dependencies): `signal` (the gate — a fact enters
  the carried signal only when backed by a re-verifying `Measurement`), `continuum`
  (emit / inflate / ground), `metrics` (arm curves, slope, decision rules), and `integrity`
  (`file_hash`).
- **`examples/bare_loop.py`** — the whole bounded loop in plain Python, no agent framework.
- **Claude Code plugin** under `adapters/claude_code/` — `plugin.json`, a `plateau` skill,
  hooks, and the `/plateau:status | gate | run` commands.
- Pre-registered, sealed demos under `demo/` (recall + real-code efficiency) with
  recompute-verifiable verdicts; results in `RESULTS.md`.

[0.4.0]: https://github.com/aimerdoux/plateau/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/aimerdoux/plateau/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/aimerdoux/plateau/releases/tag/v0.2.0
[0.1.0]: https://github.com/aimerdoux/plateau/releases/tag/v0.1.0
