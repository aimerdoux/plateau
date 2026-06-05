# How to transcript the video (yt-dlp)

**Target:** *Bioelectricity, Morphogenesis, and Two-Headed Worms | Michael Levin*
— <https://youtu.be/t6EFV2gSSmg> (id `t6EFV2gSSmg`).

The tool is **[yt-dlp](https://github.com/yt-dlp/yt-dlp)** — a feature-rich, free,
command-line audio/video downloader that also pulls subtitle/caption tracks. It is the
right pick because YouTube auto-generates captions for almost every video, and yt-dlp
can fetch *just* the caption track (`--skip-download`) without ever downloading the
video, then we flatten it to clean text. No paid API, no browser extension.

## TL;DR

```bash
pip install -U yt-dlp
python research/levin-bioelectricity/scripts/get_transcript.py \
    "https://youtu.be/t6EFV2gSSmg" \
    --out research/levin-bioelectricity/transcript --keep-timestamps
# → transcript/t6EFV2gSSmg.vtt   (raw timed captions)
# → transcript/t6EFV2gSSmg.txt   (clean, de-duplicated, [HH:MM:SS] per line)
```

The wrapper exists because raw auto-caption VTT repeats every line 2–3× (the
rolling-caption effect); `get_transcript.py` collapses those duplicates and strips the
inline word-timing tags, which a naive `grep`/`sed` pipeline does not.

## The three caption paths, in order of preference

| # | Source | Command flag | Quality |
|---|--------|--------------|---------|
| 1 | **Human / uploader captions** | `--write-subs` | Best — real punctuation, speaker intent |
| 2 | **YouTube auto-captions (ASR)** | `--write-auto-subs` | Good — no punctuation/casing, occasional ASR errors |
| 3 | **Local Whisper on the audio** | `yt-dlp -f bestaudio -x` → `whisper` | Best ASR, needs GPU/time; use when 1 & 2 are absent |

`get_transcript.py` requests **1, falling back to 2 automatically** (`--write-subs
--write-auto-subs`, preferring a manual track if both land).

### Plain yt-dlp, no wrapper

```bash
# list what caption tracks exist
yt-dlp --list-subs --skip-download "https://youtu.be/t6EFV2gSSmg"

# grab English (manual or auto) as VTT, no video
yt-dlp --skip-download --write-subs --write-auto-subs \
       --sub-langs "en.*,en" --sub-format vtt \
       -o "%(id)s.%(ext)s" "https://youtu.be/t6EFV2gSSmg"
```

### Whisper fallback (when no captions exist at all)

```bash
yt-dlp -f bestaudio -x --audio-format mp3 -o audio.mp3 "https://youtu.be/t6EFV2gSSmg"
pip install -U openai-whisper        # or faster-whisper
whisper audio.mp3 --model small.en --output_format txt
```

## Known blocker in this environment (and the fix)

This was tested from the Claude Code remote container. **yt-dlp is installed and works,
but YouTube bot-gates the datacenter IP:**

```
WARNING: [youtube] Unable to download webpage: HTTP Error 429: Too Many Requests
ERROR:   [youtube] Sign in to confirm you're not a bot. Use --cookies-from-browser ...
```

Also note this environment's network egress runs through a **TLS-inspecting proxy**
(self-signed cert in the chain), so add `--insecure` (passes `--no-check-certificates`)
when running here. The bot gate is the harder blocker and is *not* a yt-dlp bug — it is
IP reputation. Three ways through:

1. **Run it locally** (recommended). On your own machine / normal IP the TL;DR command
   just works. This is the intended workflow: transcribe locally, commit the `.txt`.
2. **Pass cookies** from a logged-in browser when you must run server-side:
   `--cookies-from-browser chrome` (or `firefox`). The wrapper forwards this flag.
3. **Use a transcript mirror** (e.g. a "youtube transcript" web tool) and paste the
   text into `transcript/t6EFV2gSSmg.txt` by hand — lowest-tech fallback.

Whichever path you use, **commit the resulting `transcript/t6EFV2gSSmg.txt`** so the
roadmap in [`README.md`](README.md) can quote exact timestamps and the claims stay
recompute-checkable — the same discipline the rest of this repo holds itself to.
