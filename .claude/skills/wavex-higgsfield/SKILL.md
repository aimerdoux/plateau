---
name: wavex-higgsfield
description: "Fully automate Higgsfield image generation via the vercel-labs/agent-browser CLI — no manual exporting. Drives the Higgsfield web UI to generate stills from spec prompts and download them into a wavex-produce inbox/, so the whole influencer pipeline (spec -> images -> video) runs hands-off. Use when the user wants to 'auto-generate the Higgsfield images', 'run the image stage automatically', or 'drive Higgsfield with the browser agent'."
version: 1.0.0
tags: ["browser-automation", "agent-browser", "higgsfield", "wavex", "image-gen"]
allowed-tools: Bash(agent-browser:*), Bash(npx agent-browser:*), Bash(python3:*)
metadata:
  openclaw:
    emoji: "🤖"
    requires:
      bins: ["agent-browser", "python3"]
---

# WaveX Higgsfield (automated image stage)

Removes the only manual step in the factory: instead of exporting stills by hand,
this drives Higgsfield's web UI with **agent-browser** to generate each shot from
the spec's prompts and saves them straight into a `wavex-produce` `inbox/`.

```
spec.json ──prep_queue.py──► queue.jsonl ──agent-browser──► inbox/*.png ──wavex-produce──► outbox/*.mp4
```

## Requirements (the two secrets only you can provide)

A browser must run somewhere that can reach Higgsfield, **and** be logged into
your Higgsfield account. Pick one of:

**A. Cloud browser (recommended — fully hands-off, runs anywhere incl. this sandbox)**
```bash
export BROWSERBASE_API_KEY=bb_...        # or KERNEL_API_KEY / BROWSERLESS_API_KEY
npm i -g agent-browser
```
Then every command below takes `--provider browserbase`.

**B. Local Chrome (simplest — run on your own machine where you're logged in)**
```bash
npm i -g agent-browser && agent-browser install
```
Uses real Chrome with your profile; no cloud key needed.

> ⚠️ This sandbox has **no browser and a TLS-proxied network**, so option A with a
> provider key is required to run it from here. Option B is for running on your
> own machine.

### Higgsfield auth (once)
On a machine where you can log in:
```bash
agent-browser auth save higgsfield --url https://higgsfield.ai/login   # interactive
agent-browser state save ./higgsfield-auth.json                        # cookies+localStorage
```
Hand me `higgsfield-auth.json` (or set the vault) and every run uses
`--state ./higgsfield-auth.json`. Heads-up: automating your own paid account
may bump Higgsfield's ToS — it's your call; this only uses your own session.

## Run

### 1. Build the queue from a spec
```bash
python3 .claude/skills/wavex-higgsfield/scripts/prep_queue.py \
  --spec runs/<id>/spec.json --root wavex_runs/<persona>
```

### 2. Agent drives Higgsfield (snapshot-and-act loop)
For each `pending` row in `wavex_runs/<persona>/queue.jsonl`, the agent runs:
```bash
AB="agent-browser --provider browserbase --state ./higgsfield-auth.json"
$AB open https://higgsfield.ai/create/image      # or the image-gen route
$AB snapshot                                       # read live refs (don't hardcode)
$AB find placeholder "Describe" fill "<prompt>"    # adapt to the real input from snapshot
$AB find text "Generate" click
$AB wait --text "Download" --timeout 180           # wait for the result
$AB snapshot                                        # locate the new image element
$AB download @eN wavex_runs/<persona>/inbox/shotNN.png   # or right-click/save flow
```
Use `screenshot --annotate` if a control is an unlabeled icon. After each save,
mark the row `done` in `queue.jsonl`. **Refs go stale after every action — always
re-snapshot.** Selectors above are placeholders; resolve them from the live
snapshot on the first shot, then reuse the pattern.

### 3. Produce video (auto-chains)
```bash
python3 .claude/skills/wavex-produce/scripts/img2vid.py --root wavex_runs/<persona> --once
```
Motion sidecars were already written by `prep_queue.py` from the spec's shot list.

## Full hands-off one-shot
Once the two secrets exist, the agent runs prep_queue → the agent-browser loop →
img2vid back-to-back, turning a single reference URL into finished clips with zero
manual steps.

## Troubleshooting
- **Cloudflare / captcha on login:** use a cloud provider with stealth + your saved
  `state.json` so you never hit the login wall mid-run.
- **`Chrome not found` / CDN cert error:** you're trying local mode without a
  browser — switch to a provider (`--provider ...`).
- **Element not found:** re-`snapshot`; the UI likely re-rendered. Prefer
  `find role/text/placeholder` over raw `@eN` across navigations.
