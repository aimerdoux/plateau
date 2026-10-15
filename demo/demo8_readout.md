# demo8 readout — control-loop A/B at completion parity

LOCAL ARTIFACT. Prereg: [`demo8_prereg.md`](demo8_prereg.md), committed at `e883108`
**before** the driver existed (`sha256:5ba4832775ec8f989c726966ffba86850150fa19fdfe9df6dbdcf32fd27e9be5`).
Rules applied without override. Raw sealed in `demo/raw8/` (21 files, hash-chained manifest);
verdict reproduces in a fresh process.

## Result: **WIN** — bounded context at completion parity

```
arm_fullhistory  tokens=[332, 828, 1205, 1600, 2178]  slope=+446.4  completed=5/5
arm_plateau      tokens=[425, 515,  446,  507,  583]  slope= +30.8  completed=5/5
```

- Bounded slope is **6.9%** of the control's — well under the pre-registered 25% bar.
- **Completion parity:** both arms passed all 5 parent-run gates.
- `RECOMPUTE_OK` — chain + file hashes verify, `prompt_tokens` re-derived from the sealed
  prompt bytes, verdict reproduces in a fresh process.

Both arms genuinely built the feature (independently verified in their worktrees, not taken
from a worker's word): `arm_plateau` 7 passing tests, `arm_fullhistory` 10, both with a
working `control resume` CLI.

The treatment arm carried a **real** signal — at T5 it held 4 gated facts (`T1..T4 done`),
4 carry lessons, goals, stance and pointers, in 583 tokens, while the control arm was
carrying 2178 tokens of transcript to do the same task.

## The honest limit that matters most

**Completion parity here is NOT evidence that the carried signal was necessary.** The
voided-then-preserved second collection (`demo/raw8_confounded/`) accidentally ran the
treatment arm with a completely **empty** signal — and it *also* scored 5/5. That
unplanned third arm is direct evidence that these five tasks are self-contained enough to be
completed with **no carried context at all**.

So demo8 establishes the **efficiency axis** cleanly (bounded vs climbing, at parity) and
says nothing about **necessity**. A task chain that genuinely requires carry — where a late
step fails without an early decision — is what would test that, and it is exactly the
`PARTIAL_FORGETS` case this prereg left live. It did not fire, because the chain never put
the bounded arm under memory pressure.

## Other limits

- **n=1 per arm.** One run, no seeds, 5 steps. Slopes from 5 points.
- **Bounded ≠ flat.** The treatment arm's slope is positive (+30.8 tok/step): the signal
  grows as facts accumulate. It is *bounded by design* (lessons capped, facts are one line
  each), not constant.
- **One model, one environment**, same worker timeout for both arms.
- The control arm's T4 worker took 239s vs the bounded arm's 34s on the same task. Suggestive
  of transcript-reading cost, but n=1 and not a pre-registered metric — **not a claim**.

## Every collection, disclosed

| run | disposition | why |
|---|---|---|
| 1 — `demo/raw8_void/` | **VOID**, no data | all 10 workers died <1.1s: `bypassPermissions` maps to `--dangerously-skip-permissions`, refused under root. Prompt content was never exercised. |
| 2 — `demo/raw8_confounded/` | **CONFOUNDED**, mechanically a WIN, not reported | treatment arm carried an EMPTY signal (fresh worktree, gitignored `signal.json`, driver never populated it) → a no-context arm, not a bounded-context arm. Its 5/5 became the necessity evidence above. |
| 3 — `demo/raw8/` | **REPORTED** | signal genuinely accumulated through the real gate; both arms 5/5. |

Re-running after 1 and 2 is consistent with the prereg's *"no re-runs to improve a number"*:
that guard stops p-hacking, and run 2 **already cleared the WIN bar** — fixing the treatment
arm could only cost the win. Both re-runs were because the treatment was never applied.

## Reproduce

```bash
python demo/score_demo8.py --verify     # RECOMPUTE_OK + the verdict
python -c "from plateau.integrity import Manifest as M; m=M('demo/raw8/manifest.jsonl'); \
print(m.verify_chain(), m.verify_files('demo/raw8'))"
```

## What this does and does not license

It licenses: *"on a 5-step serial coding chain, a bounded re-grounded signal held context
growth to 6.9% of a full-transcript loop while completing the same work."*

It does **not** license any claim about capability, understanding, or that the signal was
required. Nothing here is promoted into `README`/`RESULTS`/`BENCHMARKS` without operator go.
