#!/usr/bin/env python3
"""Render assets/og.jpg, the 1200x630 link-preview image. Run once; re-run if the logos change."""
import urllib.request
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).parent
FONTS = HERE / ".fonts"
SRC = {"Bangers.ttf": "https://raw.githubusercontent.com/google/fonts/main/ofl/bangers/Bangers-Regular.ttf",
       "Barlow-ExtraBold.ttf": "https://raw.githubusercontent.com/google/fonts/main/ofl/barlow/Barlow-ExtraBold.ttf"}
INK, PAPER, YELLOW = (20, 20, 20), (255, 253, 245), (255, 214, 10)
W, H, S = 1200, 630, 2  # drawn at 2x, downsampled for clean edges


def font(name, size):
    FONTS.mkdir(exist_ok=True)
    path = FONTS / name
    if not path.exists():
        urllib.request.urlretrieve(SRC[name], path)
    return ImageFont.truetype(str(path), size * S)


def round_logo(key, d):
    img = Image.open(HERE / f"assets/logo-{key}.jpg").convert("RGBA").resize((d, d), Image.LANCZOS)
    mask = Image.new("L", (d, d), 0)
    ImageDraw.Draw(mask).ellipse([d * 0.03, d * 0.03, d * 0.97, d * 0.97], fill=255)
    img.putalpha(mask)
    return img


def main():
    im = Image.new("RGB", (W * S, H * S), YELLOW)
    dr = ImageDraw.Draw(im)
    for y in range(0, H * S, 24):  # halftone dots
        for x in range(0, W * S, 24):
            dr.ellipse([x, y, x + 4, y + 4], fill=(230, 192, 9))

    title = font("Bangers.ttf", 132)
    text = "Who survives?"
    tw = dr.textlength(text, font=title)
    tx, ty = (W * S - tw) / 2, 52 * S
    dr.text((tx + 7 * S, ty + 7 * S), text, font=title, fill=PAPER)
    dr.text((tx, ty), text, font=title, fill=INK)

    d = 270 * S
    gap = 46 * S
    x0 = (W * S - (3 * d + 2 * gap)) // 2
    y0 = 222 * S
    for i, key in enumerate(("science", "history", "nature")):
        x = x0 + i * (d + gap)
        dr.ellipse([x + 9 * S, y0 + 9 * S, x + d + 9 * S, y0 + d + 9 * S], fill=INK)  # printed offset
        logo = round_logo(key, d)
        im.paste(logo, (x, y0), logo)
        dr.ellipse([x + d * 0.03, y0 + d * 0.03, x + d * 0.97, y0 + d * 0.97], outline=INK, width=5 * S)

    sub = font("Barlow-ExtraBold.ttf", 34)
    line = "nerdscienceofficial.com"
    sw = dr.textlength(line, font=sub)
    bx, by, pad = (W * S - sw) / 2, 548 * S, 16 * S
    dr.rectangle([bx - pad, by - 8 * S, bx + sw + pad, by + 46 * S], fill=INK)
    dr.text((bx, by), line, font=sub, fill=YELLOW)

    im.resize((W, H), Image.LANCZOS).convert("RGB").save(HERE / "assets/og.jpg", quality=86, optimize=True)
    print("Wrote assets/og.jpg")


if __name__ == "__main__":
    main()
