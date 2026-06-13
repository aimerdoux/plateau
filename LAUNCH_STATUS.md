# LAUNCH_STATUS.md

Ops dashboard for the Plateau OSS launch. Updated each ops cycle.
Last cycle: 2026-06-13. All claims grounded in sealed demo artifacts.

---

## Shipped (automated / merged to main)

| item | status | notes |
|---|---|---|
| Core library (`plateau/`) | ✅ on main | stdlib-only, py3.9+ |
| Agency layer (`plateau/agency/`) | ✅ on main | prose contracts + driver |
| Tests (28 passing) | ✅ CI green | pytest 3.9 / 3.11 / 3.12 |
| CI workflow (`.github/workflows/ci.yml`) | ✅ green | badge is live, earned |
| Release workflow (`.github/workflows/release.yml`) | ✅ on main | PyPI OIDC trusted-publish on GitHub Release |
| Hero demo GIF (`demo/context_growth.gif`) | ✅ on main | animated context-per-step from sealed demo6b |
| Social-preview / OG card (`assets/social-preview.png`) | ✅ on main | generated from sealed demo6b completion series |
| Community infra (CONTRIBUTING, SECURITY, issue/PR templates) | ✅ on main | evidence-first policy documented |
| Sealed demo6b result (38 files, recompute PASS) | ✅ on main | EFFICIENCY=WIN, arm1 slope 6859.7, arm2 slope 103.0 |

## Not yet shipped (human-gated)

| item | blocker | payload below |
|---|---|---|
| PyPI first publish | maintainer one-time setup on pypi.org | § A |
| awesome-claude-code listing | human must submit the web form | § B |
| Show HN post | human must post | § C |
| X/Twitter announcement | human must post | § D |
| Reddit post (r/MachineLearning) | human must post | § E |

---

## § A — PyPI Trusted Publisher setup (one-time, maintainer)

**Do this once on pypi.org before cutting the first GitHub Release.**

1. Log in to pypi.org as `aimerdoux`.
2. Go to **Your projects → Add new project** (or, if the project name `plateau` is already
   reserved, go to its Manage page).
3. Under **Publishing → Trusted Publishers**, click **Add a new publisher**.
4. Fill in:
   - **PyPI project name:** `plateau`
   - **Owner:** `aimerdoux`
   - **Repository:** `plateau`
   - **Workflow name:** `release.yml`
   - **Environment name:** `pypi`
5. Save.
6. Back in GitHub, go to **Settings → Environments → pypi** and create that environment
   (no secrets needed — OIDC handles auth).
7. Now cut a GitHub Release tagged `v0.2.0` (title: "v0.2.0 — initial PyPI release").
   The `release.yml` workflow will fire automatically and publish the wheel + sdist.

**Verify:** `pip install plateau` should work within ~5 minutes of the release.

---

## § B — awesome-claude-code web-form submission

**Human action required.** Go to the awesome-claude-code repository's issue tracker or
contribution form and submit. Paste the text below exactly as your PR description or
issue body (the exact format varies by repo; adapt the markdown heading if needed).

```
### Submission

**Name:** plateau
**URL:** https://github.com/aimerdoux/plateau
**Category:** Context Management / Agent Infrastructure
**Description:** Bounded context for long-horizon LLM agents — emit a small re-grounded
signal instead of carrying full transcript history, keeping a parent agent's token footprint
flat as the task grows. Recompute-verifiable; null results published; cheaper, not smarter.

**Why it belongs:**
Plateau is an OSS library that directly addresses context explosion in multi-step Claude
Code agents. The sealed demo6b experiment (38 files, recompute-verifiable) shows arm1
(full-history) climbing 365→37,405 tok in 6 steps (slope 6,860 tok/step) while arm2
(Plateau-bounded) stays flat 508→1,075 tok (slope 103 tok/step ≈ 1.5% of arm1), with
both arms reaching PASS at completion parity.

pip install plateau
```

---

## § C — Show HN draft

**Title (max 80 chars):**
```
Show HN: Plateau – bounded context for long-horizon LLM agents (OSS, recompute-verifiable)
```

**Body:**
```
Plateau is a small Python library (stdlib-only core) that lets a parent agent carry a
bounded re-grounded signal instead of the full transcript history, so its context stays
flat as the task grows.

The headline result (demo6b, pre-registered, sealed, recompute-verifiable):
- arm1 (full-history): 365→37,405 tok over 6 steps — slope 6,860 tok/step
- arm2 (Plateau): 508→1,075 tok over 6 steps — slope 103 tok/step (≈1.5% of arm1)
- Both arms reach PASS (32–36/36 tests), 0 rework. Completion parity held.

The claim is efficiency, not intelligence. Plateau keeps context flat; it does not make the
agent smarter. The null results from demo1–demo3 are published alongside the wins.

To verify the experiment yourself:
  git clone https://github.com/aimerdoux/plateau
  DEMO6_RAW=demo/raw6b DEMO6_VERDICT=demo/verdict6b.json \
    python demo/recompute_demo6.py
  # → RECOMPUTE: PASS — chain+files verify, context_tokens re-derive, verdict reproduces

pip install plateau  (once PyPI trusted publisher is wired — see repo for status)

Feedback welcome, especially on the recompute harness and the demo design.
```

---

## § D — X/Twitter draft

```
Plateau: bounded context for long-horizon LLM agents.

arm1 (full-history): 365→37,405 tok over 6 steps
arm2 (Plateau): 508→1,075 tok — same task, same pass rate, 1.5% of the tokens

OSS, stdlib-only core, recompute-verifiable result.
Null results from earlier demos also published.

https://github.com/aimerdoux/plateau
```

---

## § E — Reddit draft (r/MachineLearning or r/LocalLLaMA)

**Title:**
```
Plateau: keeping LLM agent context flat over long tasks — OSS, sealed experiment, null results published
```

**Body:**
```
I've been working on a problem that comes up a lot in multi-step LLM agents: the context
window fills up as the transcript grows, even when most of it is stale. Plateau is a small
Python library (zero third-party deps in the core) that emits a bounded re-grounded signal
at each step instead of replaying the transcript.

**The sealed experiment (demo6b):**

The primary result is a 2-arm experiment on a real code task (a multi-module Python
verification chain, 36 tests):

| arm | step 1 | step 6 | slope (tok/step) | result |
|---|---|---|---|---|
| arm1: full-history | 365 tok | 37,405 tok | 6,860 | PASS |
| arm2: Plateau | 508 tok | 1,075 tok | 103 | PASS |

Both arms complete the task in 6 steps with 0 rework. The claim is efficiency, not accuracy.

The experiment is pre-registered (commit precedes data), sealed write-once, and
recompute-verifiable — the raw prompts, completions, and a manifest.jsonl are all in
the repo. You can reproduce the verdict from scratch:

```bash
git clone https://github.com/aimerdoux/plateau
DEMO6_RAW=demo/raw6b DEMO6_VERDICT=demo/verdict6b.json \
  python demo/recompute_demo6.py
# → RECOMPUTE: PASS
```

**Honest caveats published:**
- n=1 per arm. Absolute scale is modest (~37k peak).
- The earlier demo1–demo3 results include a NULL and an UNSCORABLE — those are also in the
  repo with their full readouts.
- Plateau keeps context flat. It does not improve reasoning or recall on its own.

GitHub: https://github.com/aimerdoux/plateau
pip install plateau (PyPI publish pending one-time trusted-publisher wiring)
```

---

## CI / integrity snapshot (2026-06-13)

- Main CI: **green** (run #6, conclusion: success, 2026-06-09)
- Sealed demo6b recompute: **PASS** (38 files, chain+files verify, context_tokens re-derive,
  harness4 pin intact, EFFICIENCY=WIN) — verified 2026-06-13
- Open issues: 0
- Open PRs (before this cycle): 1 (PR #10 stale draft from 2026-06-11; no file diff landed)
- Latest GitHub Release: none
- pyproject version: 0.2.0
- PyPI published version: not yet published
