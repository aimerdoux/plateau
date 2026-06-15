---
name: wavex-spec-extractor
description: "Reverse-engineer any short-form video from its URL into a full production spec. Given Instagram Reel / TikTok / YouTube Short / YouTube URLs, downloads the media, transcribes the voiceover + subtitles, extracts keyframes, then analyzes them into a structured spec: format archetype, visual style, color grade, shot list, on-screen text, effects, voiceover tone, product/brand, hook breakdown, and a recreation brief with image-generation prompts. Built for the WaveX content factory (image-first: no video-gen credits required). Use when the user pastes a video URL and wants the 'spec', 'breakdown', 'how was this made', 'recreate this', or wants to feed reference videos into the content pipeline."
version: 1.0.0
tags: ["video", "spec", "reverse-engineering", "content", "wavex", "image-gen"]
platforms: ["linux", "macos"]
metadata:
  openclaw:
    emoji: "🎬"
    requires:
      bins: ["python3"]
---

# WaveX Spec Extractor

Turns a reference video URL into a **complete, reproducible production spec** so
the WaveX factory can recreate the format with our own product and assets. Runs
fully local — `yt-dlp` for download, `faster-whisper` for audio, PyAV for frames.
No Higgsfield/video-gen credits needed; output is **image-generation prompts**
plus assembly notes (we have unlimited image creation).

## Dependencies (one-time)

```bash
python3 -m pip install --user yt-dlp faster-whisper av
```
`faster-whisper` skill must be installed alongside this one (it is, in
`.claude/skills/faster-whisper/`).

## How to run

### Step 1 — deterministic extraction (the script)

```bash
python3 .claude/skills/wavex-spec-extractor/scripts/extract.py \
  "<video-url>" [<more urls>...] --out runs/
```

For each URL it creates `runs/<id>/` containing:
- `metadata.json` — title, author, duration, views/likes, hashtags, description
- `audio.m4a` + `*.txt` (voiceover) + `*.srt` (subtitles, with timing)
- `frames/kf_*.jpg` — ~14 scene-representative keyframes
- `spec.json` — scaffold with metadata/audio filled, creative fields = TODO

If a download fails with an SSL error, that's the sandbox proxy — the script
already passes `--no-check-certificate`.

### Step 2 — creative analysis (you, the agent)

1. **Read every keyframe** in `runs/<id>/frames/` (use the Read tool — vision).
2. **Read** the voiceover `.txt` and the `.srt` (subtitle wording + timing reveal
   pacing).
3. Fill in `creative_spec_TODO` in `spec.json` with concrete observations:

| Field | What to capture |
|-------|-----------------|
| `format_archetype` | One of the WaveX format taxonomy (see below) |
| `visual_style` | e.g. "handheld UGC, natural light, 35mm look" |
| `color_grade` | palette, contrast, warm/cool, film emulation |
| `shot_list` | ordered shots with timestamp, framing, subject, motion |
| `on_screen_text_style` | font feel, position, size, animation |
| `subtitle_style` | karaoke/word-pop? color, outline, placement |
| `effects_transitions` | zoom punches, whip pans, glitch, speed ramps |
| `voiceover_tone` | energy, accent, pace, scripted vs casual |
| `music_sound` | genre, trending-audio?, sfx hits |
| `pacing_cuts_per_sec` | estimate from keyframe density + subtitle timing |
| `product_or_brand` | what's being sold + how it's placed |
| `hook_breakdown` | first 3s: visual + verbal hook, why it stops the scroll |
| `recreation_brief.image_gen_prompts` | one detailed prompt per key shot, ready for our image generator |
| `recreation_brief.assembly_notes` | shot order, durations, text overlays, transitions, where the VO/subtitles go |

4. Write the completed `spec.json` back and give the user a short readable summary.

## Format taxonomy (short-form archetypes)

Use these labels for `format_archetype` (from the WaveX reference set):
`yapping / green-screen / talking-head / interview / man-on-the-street /
text-over-broll / split-screen / clone / triple-clone / video-reaction /
ranking / listicle / object-lesson / play-pause-reaction / top-down /
carousel / whiteboard / ask-me-anything / hyper-cinematic / aspect-ratio-change`.

## Image-first recreation (WaveX constraint)

Because we're out of Higgsfield video credits but have **unlimited image
creation**, every `recreation_brief` must be buildable from stills:
- Prefer archetypes that read as image sequences: `text-over-broll`, `ranking`,
  `listicle`, `carousel`, `top-down`, `object-lesson`, `hyper-cinematic`.
- For each shot, emit a still prompt (subject, framing, lens, light, palette,
  mood, aspect ratio 9:16).
- In `assembly_notes`, specify the cheap motion layer: Ken Burns/pan-zoom on
  stills, hard cuts on the beat, word-pop subtitles, and the VO from our TTS
  skill (`text-to-speech`). Note where a 1–2s generated video clip *would* go if
  credits return, but never require it.

## Batch / pipeline use

Pass multiple URLs at once to build a reference library:
```bash
python3 .../extract.py "url1" "url2" "url3" --out runs/
```
Then analyze each `spec.json`, and (optionally) use `content-planner` /
`video-content-analyzer` to cluster the winning patterns into a shoot list.
