#!/usr/bin/env python3
"""Render assets/og.jpg, the 1200x630 link-preview image. Run once; re-run if the logos change."""
import urllib.request
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

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
    # Top: the sharp strip of the NerdScience YouTube banner (characters + logo), full bleed.
    # Bottom: a dark-green caption band under the banner's yellow frame line.
    banner = Image.open(HERE / "assets/banner-science.jpg").convert("RGB")
    art = banner.crop((800, 428, 1640, 728))
    art_h = round(art.height * W * S / art.width)
    art = art.resize((W * S, art_h), Image.LANCZOS).filter(ImageFilter.UnsharpMask(2, 60, 2))

    im = Image.new("RGB", (W * S, H * S), (10, 52, 28))
    dr = ImageDraw.Draw(im)
    for y in range(art_h, H * S, 22):  # faint halftone in the caption band
        for x in range(0, W * S, 22):
            dr.ellipse([x, y, x + 4, y + 4], fill=(16, 66, 36))
    im.paste(art, (0, 0))
    dr.rectangle([0, art_h, W * S, art_h + 9 * S], fill=YELLOW)

    m = 44 * S
    band_top = art_h + 9 * S
    title = font("Bangers.ttf", 96)
    ty = band_top + 20 * S
    dr.text((m + 6 * S, ty + 6 * S), "Who survives?", font=title, fill=INK)
    dr.text((m, ty), "Who survives?", font=title, fill=YELLOW)
    sub = font("Barlow-ExtraBold.ttf", 30)
    dr.text((m + 2 * S, ty + 102 * S), "nerdscienceofficial.com", font=sub, fill=PAPER)

    d = 112 * S
    gap = 16 * S
    y0 = band_top + ((H * S - band_top) - d) // 2
    for i, key in enumerate(("nature", "history", "science")):  # right-aligned, science outermost
        x = W * S - m - d - i * (d + gap)
        dr.ellipse([x + 6 * S, y0 + 6 * S, x + d + 6 * S, y0 + d + 6 * S], fill=INK)
        logo = round_logo(key, d)
        im.paste(logo, (x, y0), logo)
        dr.ellipse([x + d * 0.03, y0 + d * 0.03, x + d * 0.97, y0 + d * 0.97], outline=INK, width=4 * S)

    im.resize((W, H), Image.LANCZOS).save(HERE / "assets/og.jpg", quality=88, optimize=True)
    print("Wrote assets/og.jpg")


if __name__ == "__main__":
    main()
