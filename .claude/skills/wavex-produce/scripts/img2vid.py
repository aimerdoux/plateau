#!/usr/bin/env python3
"""
WaveX produce stage — image -> video, watch-folder pipeline.

Workflow (image-first, cheapest path):
  1. You export stills from your Higgsfield (unlimited) UI into  inbox/
  2. (optional) drop a sidecar  <name>.txt  next to an image = motion prompt
  3. This converts each new image to a short clip via fal.ai (Wan / Seedance
     image-to-video — the cheapest decent i2v at ~$0.21-0.29/clip) into  outbox/
  4. Already-processed images are skipped (state in .processed.json)

Models are swappable via env so you are never locked to one vendor.

Env:
  FAL_KEY                 fal.ai key (required for real runs)
  WAVEX_VIDEO_MODEL       default: fal-ai/wan/v2.2-a14b/image-to-video
                          (e.g. fal-ai/bytedance/seedance/v1/pro/image-to-video)
  WAVEX_VIDEO_DURATION    default: 5
  WAVEX_VIDEO_RESOLUTION  default: 720p
  WAVEX_MOTION_PROMPT     default motion prompt when no sidecar .txt

Usage:
  python3 img2vid.py --root wavex_runs/persona1 --once
  python3 img2vid.py --root wavex_runs/persona1 --watch --interval 20
  python3 img2vid.py --root wavex_runs/persona1 --once --dry-run   # no API calls
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

IMG_EXT = {".png", ".jpg", ".jpeg", ".webp"}
DEFAULT_MODEL = os.environ.get(
    "WAVEX_VIDEO_MODEL", "fal-ai/wan/v2.2-a14b/image-to-video")
DEFAULT_PROMPT = os.environ.get(
    "WAVEX_MOTION_PROMPT",
    "subtle natural motion, gentle camera push-in, lifelike micro-movements, "
    "hair and fabric drift, cinematic, 9:16")


def build_args(model, image_url, prompt):
    """Per-model argument shaping for fal.ai i2v endpoints."""
    dur = os.environ.get("WAVEX_VIDEO_DURATION", "5")
    res = os.environ.get("WAVEX_VIDEO_RESOLUTION", "720p")
    a = {"image_url": image_url, "prompt": prompt}
    if "wan" in model:
        a.update({"resolution": res, "num_frames": 81})
    elif "seedance" in model:
        a.update({"resolution": res, "duration": dur})
    elif "kling" in model:
        a.update({"duration": dur})
    else:
        a.update({"duration": dur, "resolution": res})
    return a


def load_state(root):
    f = root / ".processed.json"
    return json.loads(f.read_text()) if f.exists() else {}


def save_state(root, state):
    (root / ".processed.json").write_text(json.dumps(state, indent=2))


def pending(root, state):
    inbox = root / "inbox"
    out = []
    for p in sorted(inbox.glob("*")):
        if p.suffix.lower() in IMG_EXT and p.name not in state:
            out.append(p)
    return out


def prompt_for(img):
    side = img.with_suffix(".txt")
    if side.exists():
        return side.read_text().strip()
    return DEFAULT_PROMPT


def convert_one(img, outbox, model, dry):
    prompt = prompt_for(img)
    dest = outbox / (img.stem + ".mp4")
    print(f"  - {img.name}  ->  {dest.name}")
    print(f"      prompt: {prompt[:80]}")
    if dry:
        print("      [dry-run] skipped API call")
        return {"status": "dry-run", "out": str(dest)}
    try:
        import fal_client
    except ImportError:
        print("      ! pip install --user fal-client", file=sys.stderr)
        return {"status": "error", "error": "fal-client missing"}
    if not os.environ.get("FAL_KEY"):
        return {"status": "error", "error": "FAL_KEY not set"}
    url = fal_client.upload_file(str(img))
    handler = fal_client.submit(model, arguments=build_args(model, url, prompt))
    result = handler.get()
    vid = (result.get("video") or {}).get("url") or result.get("url")
    if not vid:
        return {"status": "error", "error": f"no video in result: {result}"}
    import urllib.request
    urllib.request.urlretrieve(vid, dest)
    print(f"      ok -> {dest}")
    return {"status": "done", "out": str(dest), "src_video_url": vid}


def run_once(root, model, dry):
    root = Path(root)
    (root / "inbox").mkdir(parents=True, exist_ok=True)
    outbox = root / "outbox"
    outbox.mkdir(exist_ok=True)
    state = load_state(root)
    todo = pending(root, state)
    if not todo:
        print("  (nothing pending in inbox/)")
        return 0
    print(f"  {len(todo)} image(s) pending  [model={model}]")
    for img in todo:
        res = convert_one(img, outbox, model, dry)
        if res["status"] in ("done", "dry-run"):
            state[img.name] = res
            save_state(root, state)
    return len(todo)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True, help="run dir with inbox/ + outbox/")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--watch", action="store_true")
    ap.add_argument("--interval", type=int, default=20)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    if args.watch:
        print(f"watching {args.root}/inbox  (Ctrl-C to stop)")
        while True:
            run_once(args.root, args.model, args.dry_run)
            time.sleep(args.interval)
    else:
        run_once(args.root, args.model, args.dry_run)


if __name__ == "__main__":
    main()
