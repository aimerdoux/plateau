"""Generate `demo/context_growth.gif` from the SEALED demo6b series.

The animated line is read straight from the write-once completion files
(`demo/raw6b/arm*_completion.json` → each step's `context_tokens`); nothing is
hand-drawn or invented. Pure Pillow, no matplotlib. Re-run after any re-seal:

    python demo/make_context_gif.py
"""
from __future__ import annotations

import json
import os

from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # plateau/


def ctx(arm: str) -> list[int]:
    c = json.load(open(os.path.join(ROOT, "demo", "raw6b", f"{arm}_completion.json")))
    return [s["context_tokens"] for s in c["steps"]]


FULL = ctx("arm1_fullhistory")     # [365, 1494, 3753, 8568, 18186, 37405]
PLAT = ctx("arm2_efficiency")      # [508, 707, 788, 856, 941, 1075]
N = len(FULL)

W, H = 960, 560
PAD_L, PAD_R, PAD_T, PAD_B = 96, 56, 96, 72
PW, PH = W - PAD_L - PAD_R, H - PAD_T - PAD_B
YMAX = 40000
RED, GREEN, GRID, INK, SUB = (229, 72, 77), (48, 163, 108), (233, 233, 236), (28, 28, 32), (108, 108, 120)


def font(sz: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    cands = (
        ["/System/Library/Fonts/Supplemental/Arial Bold.ttf", "/System/Library/Fonts/HelveticaNeue.ttc"]
        if bold else
        ["/System/Library/Fonts/Supplemental/Arial.ttf", "/System/Library/Fonts/Helvetica.ttc"]
    ) + ["/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/Library/Fonts/Arial.ttf"]
    for p in cands:
        try:
            return ImageFont.truetype(p, sz)
        except Exception:
            pass
    return ImageFont.load_default()


def xy(step: int, val: int) -> tuple[float, float]:
    x = PAD_L + (step - 1) / (N - 1) * PW
    y = PAD_T + PH - min(val, YMAX) / YMAX * PH
    return x, y


def frame(k: int) -> Image.Image:
    img = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(img)
    for i in range(6):
        v = YMAX * i // 5
        y = PAD_T + PH - v / YMAX * PH
        d.line([(PAD_L, y), (PAD_L + PW, y)], fill=GRID, width=1)
        d.text((PAD_L - 14, y), f"{v // 1000}k" if v else "0", font=font(20), fill=SUB, anchor="rm")
    for s in range(1, N + 1):
        x, _ = xy(s, 0)
        d.text((x, PAD_T + PH + 12), f"step {s}", font=font(18), fill=SUB, anchor="mt")
    d.text((PAD_L, 32), "Context per step — a real 6-step dependent build (sealed: demo6b)",
           font=font(25, True), fill=INK, anchor="lm")
    d.text((PAD_L, 62), "full transcript replayed   vs   Plateau's bounded re-grounded signal",
           font=font(18), fill=SUB, anchor="lm")

    def line(series: list[int], color: tuple[int, int, int]) -> None:
        pts = [xy(s, series[s - 1]) for s in range(1, k + 1)]
        if len(pts) >= 2:
            d.line(pts, fill=color, width=5, joint="curve")
        for p in pts:
            d.ellipse([p[0] - 5, p[1] - 5, p[0] + 5, p[1] + 5], fill=color)

    line(FULL, RED)
    line(PLAT, GREEN)
    fx, fy = xy(k, FULL[k - 1])
    px, py = xy(k, PLAT[k - 1])
    if k == N:  # endpoints sit at the right edge — label to the LEFT so nothing clips
        d.text((fx - 12, fy), f"{FULL[k - 1]:,}", font=font(20, True), fill=RED, anchor="rm")
        d.text((px - 12, py + 18), f"{PLAT[k - 1]:,}", font=font(20, True), fill=GREEN, anchor="rm")
    else:
        d.text((fx + 10, fy), f"{FULL[k - 1]:,}", font=font(20, True), fill=RED, anchor="lm")
        d.text((px + 10, py + 18), f"{PLAT[k - 1]:,}", font=font(20, True), fill=GREEN, anchor="lm")

    d.rectangle([PAD_L, H - 30, PAD_L + 18, H - 16], fill=RED)
    d.text((PAD_L + 26, H - 23), "full history", font=font(18), fill=INK, anchor="lm")
    d.rectangle([PAD_L + 180, H - 30, PAD_L + 198, H - 16], fill=GREEN)
    d.text((PAD_L + 206, H - 23), "Plateau", font=font(18), fill=INK, anchor="lm")
    if k == N:  # punchline in the empty bottom-right, clear of the subtitle
        d.text((W - PAD_R, H - 23), "66× lower slope · both PASS, zero rework",
               font=font(18, True), fill=GREEN, anchor="rm")
    return img


def main() -> None:
    frames = [frame(k) for k in range(1, N + 1)]
    out = os.path.join(ROOT, "demo", "context_growth.gif")
    # long final hold on the punchline (no duplicate frames to survive GIF optimize)
    frames[0].save(out, save_all=True, append_images=frames[1:],
                   duration=[800, 800, 800, 800, 900, 3000], loop=0, optimize=True)
    print(f"wrote {os.path.relpath(out, ROOT)} — {len(frames)} frames; "
          f"full {FULL[0]}→{FULL[-1]}, plateau {PLAT[0]}→{PLAT[-1]}")


if __name__ == "__main__":
    main()
