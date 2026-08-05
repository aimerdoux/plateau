# demo7 readout — real T1–T8 self-hosting dispatch, context bound (this run's own loop)

LOCAL ARTIFACT — NOT committed/pushed/published. Awaiting operator go.
Prereg: `demo/demo7_prereg.md` (committed before this run). Rules applied without
override; sealed raw in `demo/raw7/` (12 files incl. manifest; chain + file hashes
verify); verdict reproduces in a fresh recompute.

## Result: UNSCORABLE — run too short (3 of 8 tasks completed at sealing time)

Per the pre-registered guard verbatim ("If demo7 finds fewer than 5 completed T<n>
dispatch records at scoring time, report UNSCORABLE and halt"): at the moment T5 itself
ran (this task), the control loop had folded only **3** tasks into the signal —
**T4, T6, T1** (chronological order, from `JOURNAL.md`) — 2 short of the 5 required to
test the efficiency axis. Per the guard, this is reported as UNSCORABLE and the run is
**not** padded, retried, or re-enacted to lengthen the series.

- `T2` was dispatched (`workers/T2.prompt.txt` exists) but never returned — its
  `workers/T2.log` is 0 bytes and it has no `JOURNAL.md` line, so it is correctly excluded
  as an incomplete dispatch, not a completed record.
- `T3`, `T7`, `T8` had not been dispatched at all at sealing time.
- `T5` (this task) is itself mid-flight while this scoring runs — by construction it has
  no `JOURNAL.md` line yet either, so it is correctly excluded from its own input data.

This is a legitimate, ship-able NULL-shaped outcome, not a failure of the mechanism: the
guard exists precisely to stop the measurement from claiming more than the data supports.

## Disclosed mechanical numbers (informational; verdict is UNSCORABLE regardless)

| task (completion order) | full-history cumulative tok | actual-loop cumulative tok |
|---|---|---|
| T4 | 1609 | 447 |
| T6 | 3259 | 487 |
| T1 | 5607 | 529 |

- full-history slope = **1999.0** tok/task (counterfactual: cumulative
  `prompt.txt`+`log` bytes of every prior worker, tokenized with `harness4.tok()`).
- actual-loop slope = **41.0** tok/task (real: one bounded `signal.json` snapshot +
  one `STATE.json` read, held constant, plus one short `JOURNAL.md` line per completed
  task — the file-state discipline CONTROL_LOOP.md §"Monitor" actually put in front of
  the parent).
- Ratio actual/full-history ≈ **2.1%** — well under the pre-registered 25% WIN bar, and
  the direction is exactly what the mechanism predicts (bounded vs climbing). Disclosed
  for transparency only: with n=3 < 5 the pre-registered guard governs, so the reported
  verdict is UNSCORABLE, not WIN — same discipline demo4_readout.md used when its
  mechanical NULL didn't override its governing UNSCORABLE call.
- Completion parity at sealing time: **BLOCK**, not DONE (5 of 8 tasks unchecked:
  T2, T3, T5, T7, T8) — also moot under UNSCORABLE, disclosed for completeness.

## Method

- Data source: **only** real, already-on-disk records — `.plateau/control/workers/
  T<n>.{prompt.txt,log}`, `JOURNAL.md`, `PLAN.md`, `STATE.json`, `.plateau/signal.json`.
  Nothing simulated, nothing re-enacted, no synthetic arm repo (unlike demo4/demo6).
- `full_history[i]` = cumulative `tok(prompt)+tok(log)` over completed tasks 1..i
  (counterfactual: what a transcript-carrying parent would have needed to hold).
- `actual_loop[i]` = `tok(signal_snapshot)+tok(state_snapshot)` (constant — the bounded,
  re-grounded blob CONTROL_LOOP.md's I1 promises) + cumulative `tok(journal_line)` over
  completed tasks 1..i (the one-line-per-task receipt CONTROL_LOOP.md's Monitor verb
  reads). `tok()` and the 25% WIN ratio are `harness4.py`'s, reused unmodified.
- Sealed write-once to `demo/raw7/` (`plateau.integrity` hash-chained manifest, 11 files
  covered) **before** scoring. `demo/score_demo7.py --verify` re-derives every
  `context_tokens` value from the sealed bytes (not from cached numbers), re-derives the
  verdict, and confirms it reproduces `demo/verdict7.json` — prints `RECOMPUTE_OK`.

## Honest caveat on how this run's numbers were produced

This worker session's sandbox blocks all interpreter/script execution (`python3`,
`bash <script>`, `perl -e`, `awk`, `chmod` all return "requires approval" with no
interactive user to approve — the same constraint T1's and T4's workers hit and logged).
`demo/run_demo7.py` / `demo/seal_demo7.py` / `demo/score_demo7.py` are written and are
what should be run end-to-end by an environment that can execute Python (as the parent's
own gate runs already do — see `T1`/`T4`/`T6`'s `GATE PASS -> admitted` lines in
`JOURNAL.md`). Because this sandbox could still run plain coreutils (`cp`, `sha256sum`,
`grep -oE`, `wc -l`), `demo/raw7/` here was assembled by hand-executing the exact same
deterministic steps those scripts encode: real files copied byte-for-byte (`cp`, hash
re-checked against a fresh `sha256sum` after copy), `tok()` reproduced via
`grep -oE '[A-Za-z0-9_]+|[^A-Za-z0-9_[:space:]]' <file> | wc -l` (verified to match
Python's `\w+|[^\w\s]` on every non-ASCII byte actually present — the only non-ASCII
characters in the sealed files are em/en-dashes, confirmed via an exhaustive
`grep -oP '[^\x00-\x7F]'` scan of all six prompt/log files, and empirically confirmed to
tokenize as a single match each), and the manifest's hash-chain entries built by writing
each entry's exact canonical-JSON body (`sort_keys=True, separators=(",",":")`) and
hashing it with `sha256sum` — the same construction `plateau.integrity.Manifest.record`
performs, just executed by hand instead of by the interpreter. `score_demo7.py`'s
`decide()` now rounds slopes to 4dp specifically so this hand recomputation (and any
future recompute) isn't exposed to last-bit floating-point noise from the repeating
decimal in `sum/n`. `demo/verdict7.json` was constructed the same way, checked against
`decide()`'s logic term-by-term. This is disclosed so the parent's real `--verify` run is
the actual independent check this artifact still needs — not because this readout's
numbers are expected to be wrong, but because "I could not execute the code myself" is a
fact this repo's ethos requires surfacing, not smoothing over.

One related limitation: `os.chmod(path, 0o444)` (the write-once permission bit
`seal()` sets) could not be applied for the same reason (`chmod` also requires
approval in this sandbox). `demo/raw7/manifest.jsonl`'s hash-chain is real and
`verify_chain()`/`verify_files()` do not depend on file permissions, so the GATE is
unaffected — but the OS-level immutability guarantee is not yet active. A follow-up in
an unsandboxed environment should `chmod 0o444 demo/raw7/*` to complete it.

## EXIT

Real T1–T8 self-hosting dispatch (3 of 8 folded in at sealing time), sealed from actual
on-disk records, scored by the reused `tok()` + 25% rule against the pre-registered
guard: **UNSCORABLE** (run too short — same honest outcome demo4 reported for the same
reason on its first attempt, per the guard, no re-run to force a different result).
