#!/usr/bin/env python3
"""get_transcript.py — fetch a YouTube transcript to clean, timestamped text.

Zero-dependency wrapper around yt-dlp (the only external requirement). It pulls the
best available captions — manual subs if present, else auto-generated — as a VTT
track, then flattens that VTT into (a) raw VTT and (b) de-duplicated plain text with
optional timestamps.

Why a script and not a one-liner: YouTube's VTT auto-captions repeat each line two or
three times (the rolling-caption effect). Naively `grep -v` of the cue headers leaves a
transcript that is 2–3× too long and unreadable. This collapses the rolling duplicates.

USAGE
    python get_transcript.py "https://youtu.be/t6EFV2gSSmg" --out ./out
    python get_transcript.py VIDEO_ID --lang en --keep-timestamps

NETWORK NOTE (read TRANSCRIPTION.md): from a datacenter / CI IP, YouTube frequently
bot-gates the request ("Sign in to confirm you're not a bot", HTTP 429). When that
happens, run this on your own machine, or pass cookies with --cookies-from-browser.
The bot gate is YouTube's, not yt-dlp's — the tool and this script are correct; the IP
reputation is the blocker.
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import tempfile


def video_id(url_or_id: str) -> str:
    """Accept a bare id, a youtu.be link, or a watch?v= link."""
    m = re.search(r"(?:v=|youtu\.be/|/shorts/)([A-Za-z0-9_-]{11})", url_or_id)
    return m.group(1) if m else url_or_id.strip()


def run_ytdlp(vid: str, lang: str, workdir: str, cookies_from: str | None,
              insecure: bool) -> str:
    """Download the caption track to VTT and return its path (raises on failure)."""
    out_tmpl = os.path.join(workdir, "%(id)s.%(ext)s")
    cmd = [
        "yt-dlp", "--skip-download",
        "--write-subs", "--write-auto-subs",      # manual first, else auto
        "--sub-langs", f"{lang}.*,{lang}",          # en, en-US, en-orig, ...
        "--sub-format", "vtt",
        "-o", out_tmpl,
        f"https://www.youtube.com/watch?v={vid}",
    ]
    if cookies_from:
        cmd += ["--cookies-from-browser", cookies_from]
    if insecure:
        cmd += ["--no-check-certificates"]         # TLS-inspecting proxy only
    print("·", " ".join(cmd), file=sys.stderr)
    subprocess.run(cmd, check=True)
    vtts = [f for f in os.listdir(workdir) if f.startswith(vid) and f.endswith(".vtt")]
    if not vtts:
        raise FileNotFoundError(
            "no .vtt produced — captions may be absent, or the IP was bot-gated "
            "(see TRANSCRIPTION.md; try --cookies-from-browser chrome)")
    # Prefer a manual track (no 'auto' marker) if both exist.
    vtts.sort(key=lambda f: ("auto" in f, f))
    return os.path.join(workdir, vtts[0])


_TS = re.compile(r"^(\d{2}:\d{2}:\d{2})\.\d{3}\s+-->")
_TAG = re.compile(r"<[^>]+>")           # inline <c> / <00:00:00.000> word timings


def vtt_to_text(vtt_path: str, keep_timestamps: bool) -> str:
    """Collapse rolling-caption VTT into clean, de-duplicated lines."""
    out: list[str] = []
    last = None
    cur_ts = ""
    with open(vtt_path, encoding="utf-8") as f:
        for raw in f:
            line = raw.rstrip("\n")
            ts = _TS.match(line)
            if ts:
                cur_ts = ts.group(1)
                continue
            if not line or line in ("WEBVTT",) or line.startswith(("Kind:", "Language:")):
                continue
            if line.isdigit():           # cue index
                continue
            text = _TAG.sub("", line).strip()
            if not text or text == last:
                continue
            last = text
            out.append(f"[{cur_ts}] {text}" if keep_timestamps else text)
    return "\n".join(out) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("url", help="YouTube URL or 11-char video id")
    ap.add_argument("--out", default=".", help="output directory (default: cwd)")
    ap.add_argument("--lang", default="en", help="caption language prefix (default: en)")
    ap.add_argument("--keep-timestamps", action="store_true",
                    help="prefix each line with [HH:MM:SS]")
    ap.add_argument("--cookies-from-browser", dest="cookies",
                    help="e.g. chrome / firefox — needed when the IP is bot-gated")
    ap.add_argument("--insecure", action="store_true",
                    help="pass --no-check-certificates (TLS-inspecting proxy)")
    args = ap.parse_args()

    vid = video_id(args.url)
    os.makedirs(args.out, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        try:
            vtt = run_ytdlp(vid, args.lang, tmp, args.cookies, args.insecure)
        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            print(f"FAILED: {e}", file=sys.stderr)
            return 1
        vtt_dst = os.path.join(args.out, f"{vid}.vtt")
        with open(vtt) as src, open(vtt_dst, "w") as dst:
            dst.write(src.read())
        txt = vtt_to_text(vtt, args.keep_timestamps)
    txt_dst = os.path.join(args.out, f"{vid}.txt")
    with open(txt_dst, "w", encoding="utf-8") as f:
        f.write(txt)
    print(f"wrote {vtt_dst}\nwrote {txt_dst}  ({txt.count(chr(10))} lines)",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
