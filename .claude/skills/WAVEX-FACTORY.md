# WaveX Content Factory

A repeatable, mostly-local pipeline to **discover** what's going viral,
**reverse-engineer** the winners into reproducible specs, and **produce** our own
versions — image-first, because we're out of Higgsfield video credits but have
**unlimited image creation**.

## The four stages

```
  DISCOVER ─────► ANALYZE ─────► SPEC ─────► PRODUCE
  (trends +      (why it       (full        (images + VO +
   viral pulls)   works)        blueprint)   assembly)
```

### 1. DISCOVER — find viral videos & trending topics
| Skill | Use | Needs |
|-------|-----|-------|
| `google-trends-research` | rising queries, keyword momentum | — |
| `tiktok-research` | outlier TikToks in a niche + hook formulas | `APIFY_TOKEN` |
| `instagram-research` | top reels from tracked accounts | `APIFY_TOKEN` |
| `youtube-research` | outlier YouTube videos (TubeLab) | TubeLab API |
| `x-research` | trending tweets/threads | `APIFY_TOKEN` |
| `social-media-extractor` | generic IG/Meta public data | `APIFY_TOKEN` |
| `content-planner` | runs all of the above in parallel → playbook | the above |
| `competitive-ads-extractor` | live competitor ads: hooks/CTAs | — |
| `deep-research` | market/topic deep dives | — |

### 2. ANALYZE — why a specific video works
| Skill | Use | Needs |
|-------|-----|-------|
| `video-content-analyzer` | Gemini hook/structure breakdown | `GEMINI_API_KEY` |
| `wavex-spec-extractor` | **our** local breakdown (no API key) | — |

### 3. SPEC — full reproducible blueprint  ⭐ core
`wavex-spec-extractor` (custom, in this repo). Paste any Reel/TikTok/Short URL →
it downloads, transcribes voiceover + subtitles, extracts keyframes, and I read
the frames to produce a `spec.json`: format archetype, visual style, color
grade, shot list, on-screen text, effects, voiceover tone, product/brand, hook
breakdown, and a **recreation brief with image-gen prompts**. Runs fully local
(`yt-dlp` + `faster-whisper` + PyAV).

### 4. PRODUCE — build our version (image-first, now fully automated)
| Skill | Use |
|-------|-----|
| **`wavex-higgsfield`** 🤖 | drives Higgsfield's UI via **agent-browser** to auto-generate the stills from the spec's prompts into `inbox/` — no manual export. Needs a cloud-browser key (Browserbase/Kernel) + a saved Higgsfield session |
| **`wavex-produce`** ⭐ | watch-folder: stills in `inbox/` → fal.ai **Wan/Seedance** i2v clips in `outbox/` (~$0.25/clip) |
| `text-to-speech` (ElevenLabs) | voiceover from the rewritten script |
| `voice-dna-creator` | keep copy in the WaveX voice |
| `content-research-writer` | script + on-screen copy with citations |
| `remotion-best-practices` | assemble clips/stills→video in React (Ken Burns, cuts, subtitles) |

**Decided stack (cheapest scalable, image-first):** Higgsfield stills (manual
export, unlimited) → `wavex-produce` → fal.ai Wan/Seedance image-to-video. This
beat Eromify (~$0.82/clip) and "Kling direct" (~$0.35–0.70/clip) at **~$0.25/clip**
for ~1,000 clips/mo ≈ ~$250. Higgsfield's unlimited images are **UI-only** (no
free API), so the image leg stays manual; video is the only paid leg.
Needs `FAL_KEY`. Swap `WAVEX_VIDEO_MODEL` to compare Wan vs Seedance vs Kling.

## Quickstart

```bash
# one-time
python3 -m pip install --user yt-dlp faster-whisper av

# spec a single reference
python3 .claude/skills/wavex-spec-extractor/scripts/extract.py \
  "https://www.instagram.com/reel/XXXX/" --out runs/

# build a reference library
python3 .claude/skills/wavex-spec-extractor/scripts/extract.py \
  "url1" "url2" "url3" --out runs/
```
Then ask me to "complete the specs" — I read the keyframes and fill the creative
blueprint, then summarize the winning patterns.

## API keys to unlock full discovery
Set these in the environment (the research skills no-op without them):
- `APIFY_TOKEN` — TikTok / Instagram / X / social extractor
- `GEMINI_API_KEY` — `video-content-analyzer`
- `ELEVENLABS_API_KEY` — `text-to-speech`
- TubeLab key — `youtube-research`

The SPEC stage (`wavex-spec-extractor`) and `google-trends-research`,
`competitive-ads-extractor`, `deep-research` need **none** of these.
