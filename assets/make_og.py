"""Generate `assets/social-preview.png` — the GitHub social-preview / OG card (1280×640).

The mini-chart is read from the SEALED demo6b completion files (same source as the README
GIF); nothing is hand-typed. Upload the result via GitHub → Settings → Social preview.

    python assets/make_og.py
"""
from __future__ import annotations

import json
import os

from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def ctx(arm: str) -> list[int]:
    c = json.load(open(os.path.join(ROOT, "demo", "raw6b", f"{arm}_completion.json")))
    return [s["context_tokens"] for s in c["steps"]]


FULL = ctx("arm1_fullhistory")
PLAT = ctx("arm2_efficiency")
N = len(FULL)
W, H, YMAX = 1280, 640, 40000
INK, SUB, RED, GREEN, CHIP = (22, 22, 26), (112, 112, 124), (229, 72, 77), (48, 163, 108), (243, 244, 246)


def font(sz: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    for p in (["/System/Library/Fonts/Supplemental/Arial Bold.ttf"] if bold
              else ["/System/Library/Fonts/Supplemental/Arial.ttf"]) + \
             ["/System/Library/Fonts/Helvetica.ttc", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]:
        try:
            return ImageFont.truetype(p, sz)
        except Exception:
            pass
    return ImageFont.load_default()


def main() -> None:
    img = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, 12, H], fill=GREEN)
    d.text((64, 78), "Plateau", font=font(98, True), fill=INK)
    d.text((68, 196), "Bounded context for long-horizon agents.", font=font(33, True), fill=INK)
    d.text((68, 244), "Carry a small re-grounded signal — not the whole transcript.", font=font(25), fill=SUB)
    x, y = 68, 330
    for c in ["66× lower context slope", "cheaper, not smarter", "nulls published", "recompute-verifiable"]:
        w = d.textlength(c, font=font(23)) + 38
        if x + w > 720:
            x, y = 68, y + 62
        d.rounded_rectangle([x, y, x + w, y + 48], radius=11, fill=CHIP)
        d.text((x + 19, y + 24), c, font=font(23), fill=INK, anchor="lm")
        x += w + 14
    d.text((68, H - 62), "github.com/aimerdoux/plateau    ·    Apache-2.0    ·    zero core deps",
           font=font(23), fill=SUB)

    cx0, cy0, cw, ch = 792, 158, 396, 322
    for i in range(5):
        yy = cy0 + ch - i / 4 * ch
        d.line([(cx0, yy), (cx0 + cw, yy)], fill=(236, 236, 240), width=1)

    def pt(s: int, v: int) -> tuple[float, float]:
        return (cx0 + (s - 1) / (N - 1) * cw, cy0 + ch - min(v, YMAX) / YMAX * ch)

    d.line([pt(s, FULL[s - 1]) for s in range(1, N + 1)], fill=RED, width=6, joint="curve")
    d.line([pt(s, PLAT[s - 1]) for s in range(1, N + 1)], fill=GREEN, width=6, joint="curve")
    d.text((cx0, cy0 - 32), "context per step — full history vs Plateau (sealed demo6b)", font=font(18), fill=SUB)
    d.text((pt(N, FULL[-1])[0] - 8, pt(N, FULL[-1])[1] + 4), f"{FULL[-1]:,}", font=font(21, True), fill=RED, anchor="rm")
    d.text((pt(N, PLAT[-1])[0] - 8, pt(N, PLAT[-1])[1] - 2), f"{PLAT[-1]:,}", font=font(21, True), fill=GREEN, anchor="rm")

    out = os.path.join(ROOT, "assets", "social-preview.png")
    img.save(out)
    print(f"wrote {os.path.relpath(out, ROOT)} — {img.size}")


if __name__ == "__main__":
    main()
