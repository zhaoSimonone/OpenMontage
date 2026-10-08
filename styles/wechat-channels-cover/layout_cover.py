#!/usr/bin/env python3
"""WeChat Channels cover compositor.

Local cute Chinese fonts on a food-hero photo. Never bake title glyphs
into the image model. Defaults match the approved 粉蒸排骨 golden cover:

- 9:16 1080x1920, title_y=390, labels_y=1528 (inside 3:4 crop y=240-1680)
- 4:5 1080x1350, title_y=200, labels_y=1210
- bouncing puffy 站酷快乐体 title, left-aligned washi labels
"""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

ROOT = Path(__file__).resolve().parent
FONT_DIR = ROOT / "fonts"
KUAI = str(FONT_DIR / "ZCOOLKuaiLe-Regular.ttf")

PINK_DEEP = (255, 64, 106)
RED = (232, 46, 74)
BROWN = (102, 48, 24)
CREAM = (255, 250, 236)
WHITE = (255, 255, 255)
PEACH = (255, 186, 164)
LEMON = (255, 236, 150)

# WeChat Channels profile thumb ≈ 3:4 center-crop of 9:16.
WECHAT_CROP_TOP_9X16 = 240
WECHAT_CROP_BOTTOM_9X16 = 1680


def font(path: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(path, size)


def puffy_text(
    text: str,
    fnt: ImageFont.FreeTypeFont,
    fill: tuple[int, int, int],
    stroke: int = 14,
    rim: tuple[int, int, int] = WHITE,
    outer: tuple[int, int, int] | None = (255, 92, 132),
    shadow: bool = True,
) -> Image.Image:
    dummy = ImageDraw.Draw(Image.new("RGBA", (8, 8)))
    extra = stroke + 8
    box = dummy.textbbox((0, 0), text, font=fnt, stroke_width=extra)
    w, h = box[2] - box[0] + 20, box[3] - box[1] + 22
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    xy = (10 - box[0], 8 - box[1])
    if shadow:
        d.text(
            (xy[0] + 5, xy[1] + 8),
            text,
            font=fnt,
            fill=(80, 30, 30, 70),
            stroke_width=extra,
            stroke_fill=(80, 30, 30, 70),
        )
    if outer is not None:
        d.text(xy, text, font=fnt, fill=outer + (255,), stroke_width=stroke + 8, stroke_fill=outer + (255,))
    d.text(xy, text, font=fnt, fill=fill + (255,), stroke_width=stroke, stroke_fill=rim + (255,))
    bbox = img.getbbox()
    return img.crop(bbox) if bbox else img


def bounce_word(
    text: str,
    size: int,
    fills: list[tuple[int, int, int]],
    stroke: int,
    path: str = KUAI,
    gap: int = -18,
) -> Image.Image:
    rots = [-8, 7, -6, 9, -4, 6]
    lifts = [8, 22, 0, 18, 6, 16]
    parts = []
    fnt = font(path, size)
    for i, ch in enumerate(text):
        im = puffy_text(ch, fnt, fills[i % len(fills)], stroke=stroke)
        im = im.rotate(rots[i % len(rots)], resample=Image.Resampling.BICUBIC, expand=True)
        parts.append((im, lifts[i % len(lifts)]))
    width = sum(im.width + gap for im, _ in parts) - gap + 8
    height = max(im.height + lift for im, lift in parts) + 12
    canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    x = 0
    for im, lift in parts:
        canvas.alpha_composite(im, (x, lift))
        x += im.width + gap
    return canvas


def tape(text: str, fnt: ImageFont.FreeTypeFont, fill, fg=BROWN, tilt: float = -4) -> Image.Image:
    dummy = ImageDraw.Draw(Image.new("RGBA", (8, 8)))
    box = dummy.textbbox((0, 0), text, font=fnt)
    tw, th = box[2] - box[0], box[3] - box[1]
    w, h = tw + 46, th + 28
    img = Image.new("RGBA", (w + 8, h + 10), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.polygon([(6, 8), (w + 2, 4), (w - 2, h + 2), (2, h - 2)], fill=(80, 30, 40, 50))
    d.polygon([(2, 4), (w - 2, 1), (w - 6, h - 4), (0, h - 6)], fill=fill + (235,))
    d.text(((w - tw) / 2 - 2, (h - th) / 2 - 2), text, font=fnt, fill=fg + (255,))
    return img.rotate(tilt, resample=Image.Resampling.BICUBIC, expand=True)


def fitted_title(text: str, max_width: int, start_size: int, font_path: str = KUAI) -> Image.Image:
    fills = [BROWN, RED, BROWN, PINK_DEEP]
    for size in range(start_size, 96, -4):
        stroke = max(16, size // 9)
        gap = -max(28, size // 7)
        title = bounce_word(text, size, fills, stroke=stroke, path=font_path, gap=gap)
        if title.width <= max_width:
            print(f"title size={size} {title.size}")
            return title
    return bounce_word(text, 100, fills, stroke=14, path=font_path, gap=-24)


def wechat_crop_box(width: int, height: int) -> tuple[int, int, int, int]:
    crop_h = int(round(width * 4 / 3))
    top = max(0, (height - crop_h) // 2)
    return 0, top, width, top + crop_h


def just_now_badge(font_path: str, scale: float = 1.0) -> Image.Image:
    fnt = font(font_path, max(22, int(28 * scale)))
    text = "刚刚"
    dummy = ImageDraw.Draw(Image.new("RGBA", (8, 8)))
    box = dummy.textbbox((0, 0), text, font=fnt)
    tw, th = box[2] - box[0], box[3] - box[1]
    w, h = tw + 28, th + 16
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((0, 0, w - 1, h - 1), radius=h // 3, fill=(40, 40, 40, 170))
    d.text((14 - box[0], 7 - box[1]), text, font=fnt, fill=WHITE + (255,))
    return img


def compose(
    photo: Image.Image,
    title_text: str,
    labels: list[str],
    width: int,
    height: int,
    font_path: str = KUAI,
) -> Image.Image:
    tall = height == 1920
    fitted = ImageOps.fit(
        photo.convert("RGB"),
        (width, height),
        method=Image.Resampling.LANCZOS,
        centering=(0.5, 0.42 if tall else 0.46),
    )
    im = fitted.convert("RGBA")
    title = fitted_title(title_text, width - 56, 228 if tall else 196, font_path=font_path)
    title_y = 390 if tall else 200
    im.alpha_composite(title, ((width - title.width) // 2, title_y))
    print(f"{width}x{height} title_y={title_y} title={title.size}")

    x = 36 if tall else 28
    y = 1528 if tall else 1210
    tilts = [-6, 4, -3]
    fills = [CREAM, LEMON, PEACH]
    fnt = font(font_path, 44 if tall else 38)
    for i, label in enumerate(labels[:3]):
        chip = tape(label, fnt, fills[i % 3], BROWN, tilts[i % 3])
        im.alpha_composite(chip, (x, y))
        x += chip.width + 16
    return im.convert("RGB")


def save_wechat_sim(cover: Image.Image, out_dir: Path, font_path: str) -> None:
    left, top, right, bottom = wechat_crop_box(*cover.size)
    crop = cover.crop((left, top, right, bottom))
    thumb = crop.resize((398, 520), Image.Resampling.LANCZOS).convert("RGBA")
    thumb.alpha_composite(just_now_badge(font_path, 0.72), (10, 12))
    path = out_dir / "wechat_thumb_sim.jpg"
    thumb.convert("RGB").save(path, quality=96, subsampling=0)
    print(path, f"source_crop=y{top}-{bottom}")

    overlay = cover.convert("RGBA")
    d = ImageDraw.Draw(overlay)
    d.rectangle((left, top, right - 1, bottom - 1), outline=(255, 70, 90, 255), width=8)
    path2 = out_dir / "wechat_crop_overlay.jpg"
    overlay.convert("RGB").save(path2, quality=92, subsampling=0)
    print(path2)


def main() -> None:
    parser = argparse.ArgumentParser(description="Compose WeChat Channels covers from a food-hero photo.")
    parser.add_argument("--photo", required=True, help="Hero photo path (no baked-in title glyphs)")
    parser.add_argument("--title", required=True, help="Chinese title, e.g. 粉蒸排骨")
    parser.add_argument("--labels", default="", help="Comma-separated washi labels, e.g. 炒酱,腌透,裹粉")
    parser.add_argument("--out-dir", required=True, help="Output directory")
    parser.add_argument("--font", default=KUAI, help="TTF for bouncing title + labels")
    parser.add_argument("--stem", default="封面_可爱风", help="Filename stem")
    args = parser.parse_args()

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    photo = Image.open(args.photo).convert("RGB")
    labels = [part.strip() for part in args.labels.split(",") if part.strip()]
    if len(labels) > 3:
        labels = labels[:3]

    specs = [
        (1080, 1920, f"{args.stem}_9比16.jpg"),
        (1080, 1350, f"{args.stem}_4比5.jpg"),
    ]
    for w, h, name in specs:
        im = compose(photo, args.title, labels, w, h, font_path=args.font)
        path = out / name
        im.save(path, quality=96, subsampling=0)
        if h == 1920:
            im.save(out / f"{args.stem}_9比16.png")
            save_wechat_sim(im, out, args.font)
        print(path, im.size)


if __name__ == "__main__":
    main()
