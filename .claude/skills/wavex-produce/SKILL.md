---
name: wavex-produce
description: "Produce stage of the WaveX factory: convert influencer stills into short video clips at the cheapest rate. Watch-folder pipeline — you export images from Higgsfield (unlimited) into inbox/, this turns each into a clip via fal.ai image-to-video (Wan / Seedance, ~$0.21-0.29/clip) into outbox/. Model is swappable via env (Wan, Seedance, Kling). Use when the user wants to 'make videos from images', 'render the clips', 'run the produce stage', or batch-convert a folder of stills to video for AI-influencer/UGC content."
version: 1.0.0
tags: ["video", "image-to-video", "fal", "wan", "seedance", "wavex", "ugc"]
platforms: ["linux", "macos"]
metadata:
  openclaw:
    emoji: "🏭"
    requires:
      bins: ["python3"]
---

# WaveX Produce (image → video)

The cheapest scalable path to influencer clips, decided in the WaveX cost
analysis: **Higgsfield (unlimited) stills → fal.ai Wan/Seedance image-to-video**.
~$0.21–0.29 per clip vs Kling's $0.35–0.70 and Eromify's ~$0.82, and fully
scriptable.

## Why this shape
Higgsfield's unlimited image generation is **UI-only** (no free API), so images
come in **manually**: you batch-export stills from Higgsfield into `inbox/`.
Video is the only paid leg, on the cheapest decent i2v model.

## One-time setup
```bash
python3 -m pip install --user fal-client
export FAL_KEY="...your fal.ai key..."
```
Optional model/quality overrides:
```bash
export WAVEX_VIDEO_MODEL="fal-ai/wan/v2.2-a14b/image-to-video"   # default
# export WAVEX_VIDEO_MODEL="fal-ai/bytedance/seedance/v1/pro/image-to-video"
export WAVEX_VIDEO_RESOLUTION="720p"
export WAVEX_VIDEO_DURATION="5"
export WAVEX_MOTION_PROMPT="subtle natural motion, gentle push-in, 9:16"
```

## Folder layout
```
wavex_runs/<persona>/
  inbox/        <- drop exported Higgsfield stills here (png/jpg/webp)
    shot01.png
    shot01.txt  <- (optional) per-image motion prompt; else default is used
  outbox/       <- generated shot01.mp4 lands here
  .processed.json   <- state; processed images are skipped
```

## Run
```bash
# process whatever is in inbox/ once, then exit
python3 .claude/skills/wavex-produce/scripts/img2vid.py --root wavex_runs/persona1 --once

# keep watching the folder (local machine)
python3 .claude/skills/wavex-produce/scripts/img2vid.py --root wavex_runs/persona1 --watch --interval 20

# validate file discovery without spending anything
python3 .claude/skills/wavex-produce/scripts/img2vid.py --root wavex_runs/persona1 --once --dry-run
```

## Where this fits in the factory
```
discover ─► wavex-spec-extractor (spec + image-gen prompts)
                     │
        you generate stills in Higgsfield from those prompts
                     │
                     ▼
              wavex-produce  (this skill: stills -> clips)
                     │
                     ▼
   assemble: stitch clips + TTS voiceover + word-pop captions
   (use the `remotion-best-practices` skill for code-driven assembly,
    and `text-to-speech` for the VO)
```

## Agent guidance
- To produce from a spec: read `runs/<id>/spec.json`, take each
  `recreation_brief.image_gen_prompts` entry, and tell the user to generate that
  still in Higgsfield (image-first, no video credits). When they drop the stills
  in `inbox/`, optionally write a matching `<name>.txt` motion prompt derived
  from the spec's `shot_list` motion notes, then run `--once`.
- Cost check before a big batch: `count(inbox) × ~$0.25`. Confirm with the user
  if it exceeds their stated budget.
- Keep it backend-agnostic: switch `WAVEX_VIDEO_MODEL` to compare Wan vs Seedance
  vs Kling without code changes.
