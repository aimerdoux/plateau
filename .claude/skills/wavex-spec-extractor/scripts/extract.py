#!/usr/bin/env python3
"""
WaveX video-spec extractor — deterministic stage.

Given one or more video URLs (Instagram / TikTok / YouTube / Shorts), this:
  1. Pulls metadata (title, author, duration, stats, hashtags, description)
  2. Downloads the audio track and transcribes it (voiceover + SRT subtitles)
     using the locally-installed faster-whisper skill
  3. Downloads the video track and extracts representative keyframes (PyAV,
     no system ffmpeg required)
  4. Writes a spec scaffold JSON with everything machine-extractable filled in
     and the creative fields left as TODO for the agent's vision pass.

The agent then READS the keyframes and completes the creative spec
(style / format / effects / product / image-gen prompts) per SKILL.md.

Usage:
  python3 extract.py <url> [<url> ...] --out runs/
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

REPO_SKILLS = Path(__file__).resolve().parents[2]  # .claude/skills/
WHISPER = REPO_SKILLS / "faster-whisper" / "scripts" / "transcribe.py"
YTDLP = [sys.executable, "-m", "yt_dlp", "--no-check-certificate", "--no-playlist"]


def run(cmd, **kw):
    print(f"  $ {' '.join(str(c) for c in cmd)}", flush=True)
    return subprocess.run(cmd, **kw)


def slug(url):
    return url.rstrip("/").split("/")[-1].split("?")[0] or "video"


def metadata(url, d):
    p = run(YTDLP + ["--dump-single-json", "--skip-download", url],
            capture_output=True, text=True)
    if p.returncode != 0:
        print(f"  ! metadata failed: {p.stderr[-300:]}")
        return {}
    info = json.loads(p.stdout)
    keep = {k: info.get(k) for k in (
        "title", "uploader", "uploader_id", "channel", "duration",
        "view_count", "like_count", "comment_count", "repost_count",
        "description", "tags", "categories", "webpage_url", "upload_date",
        "resolution", "fps", "aspect_ratio")}
    (d / "metadata.json").write_text(json.dumps(info, indent=2)[:200000])
    return keep


def transcribe(url, d):
    audio = d / "audio.m4a"
    r = run(YTDLP + ["-f", "bestaudio", "-o", str(audio), url])
    if r.returncode != 0 or not audio.exists():
        # some hosts label the audio differently
        for f in d.glob("audio.*"):
            audio = f
            break
    if not audio.exists():
        return {"error": "audio download failed"}
    if not WHISPER.exists():
        return {"error": f"faster-whisper not found at {WHISPER}"}
    run([sys.executable, str(WHISPER), str(audio), "--model", "small",
         "-f", "srt,text", "-o", str(d), "--device", "cpu",
         "--compute-type", "int8", "-q"])
    out = {}
    for ext, key in (("txt", "voiceover"), ("srt", "subtitles_srt")):
        hits = list(d.glob(f"*.{ext}"))
        if hits:
            out[key] = hits[0].read_text(errors="ignore").strip()
    return out


def keyframes(url, d, cap=14):
    vid = d / "video.mp4"
    run(YTDLP + ["-f", "bestvideo[height<=1080]/best[height<=1080]/best",
                 "-o", str(d / "video.%(ext)s"), url])
    cands = list(d.glob("video.*"))
    if not cands:
        return []
    vid = cands[0]
    try:
        import av
    except ImportError:
        return [{"error": "PyAV not installed"}]
    fr = d / "frames"
    fr.mkdir(exist_ok=True)
    saved = []
    container = av.open(str(vid))
    stream = container.streams.video[0]
    stream.codec_context.skip_frame = "NONKEY"  # scene-representative keyframes
    tb = stream.time_base
    for frame in container.decode(stream):
        ts = round(float(frame.pts * tb), 2) if frame.pts is not None else 0.0
        saved.append((ts, frame))
    # even-sample down to cap
    if len(saved) > cap:
        step = len(saved) / cap
        saved = [saved[int(i * step)] for i in range(cap)]
    paths = []
    for i, (ts, frame) in enumerate(saved):
        p = fr / f"kf_{i:02d}_t{ts:g}s.jpg"
        frame.to_image().save(p, quality=85)
        paths.append(str(p))
    return paths


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("urls", nargs="+")
    ap.add_argument("--out", default="runs")
    args = ap.parse_args()
    root = Path(args.out)
    root.mkdir(parents=True, exist_ok=True)
    for url in args.urls:
        d = root / slug(url)
        d.mkdir(parents=True, exist_ok=True)
        print(f"\n=== {url} -> {d} ===")
        meta = metadata(url, d)
        tr = transcribe(url, d)
        frames = keyframes(url, d)
        spec = {
            "source_url": url,
            "metadata": meta,
            "audio": {k: v for k, v in tr.items() if k != "subtitles_srt"},
            "subtitles_srt_file": "see *.srt in run dir",
            "keyframes": frames,
            "creative_spec_TODO": {
                "_instruction": "Agent: READ each keyframe image and fill these in.",
                "format_archetype": None,
                "visual_style": None,
                "color_grade": None,
                "shot_list": [],
                "on_screen_text_style": None,
                "subtitle_style": None,
                "effects_transitions": [],
                "voiceover_tone": None,
                "music_sound": None,
                "pacing_cuts_per_sec": None,
                "product_or_brand": None,
                "hook_breakdown": None,
                "recreation_brief": {
                    "image_gen_prompts": [],
                    "assembly_notes": None,
                },
            },
        }
        (d / "spec.json").write_text(json.dumps(spec, indent=2))
        print(f"  -> wrote {d/'spec.json'}  ({len(frames)} keyframes)")
        print("  -> NEXT: agent reads frames/ and completes creative_spec_TODO")


if __name__ == "__main__":
    main()
