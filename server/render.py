"""Render text/images to 1-bpp bitmaps for mono panels (ePaper / RLCD)."""

from __future__ import annotations

import io
from pathlib import Path
from typing import Tuple

from PIL import Image, ImageDraw, ImageFont, ImageOps

# Default panel (Waveshare 3.97" ePaper)
WIDTH = 800
HEIGHT = 480
BYTES = WIDTH * HEIGHT // 8

FONT_CANDIDATES = [
    Path(__file__).resolve().parent / "fonts" / "NotoSansSC-Regular.otf",
    Path(__file__).resolve().parent / "fonts" / "wqy-microhei.ttc",
    Path(__file__).resolve().parent / "fonts" / "NotoSansCJKsc-Regular.otf",
    Path(__file__).resolve().parent / "fonts" / "STHeiti-Light.ttc",
    Path("/usr/share/fonts/google-noto-cjk/NotoSansCJK-Regular.ttc"),
    Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
    Path("/usr/share/fonts/truetype/wqy/wqy-microhei.ttc"),
    Path("/usr/share/fonts/wqy-microhei/wqy-microhei.ttc"),
    Path("/System/Library/Fonts/PingFang.ttc"),
    Path("/System/Library/Fonts/STHeiti Light.ttc"),
]


def find_font() -> Path:
    for p in FONT_CANDIDATES:
        if p.exists():
            return p
    raise FileNotFoundError(
        "No CJK font found. Put NotoSansSC-Regular.otf in server/fonts/"
    )


def load_font(size: int) -> ImageFont.FreeTypeFont:
    path = find_font()
    try:
        return ImageFont.truetype(str(path), size=size, index=0)
    except OSError:
        return ImageFont.truetype(str(path), size=size)


def wrap_text(draw: ImageDraw.ImageDraw, text: str, font, max_width: int) -> list[str]:
    if not text:
        return []
    lines: list[str] = []
    for paragraph in text.replace("\r\n", "\n").split("\n"):
        if not paragraph:
            lines.append("")
            continue
        current = ""
        for ch in paragraph:
            trial = current + ch
            if draw.textlength(trial, font=font) <= max_width:
                current = trial
            else:
                if current:
                    lines.append(current)
                current = ch
        if current:
            lines.append(current)
    return lines


def image_to_gx_bitmap(img: Image.Image, width: int, height: int) -> bytes:
    """Pack to GxEPD2-style mono bitmap: 1=white, 0=black, MSB left."""
    bw = img.convert("L")
    bw = ImageOps.autocontrast(bw)
    bw = bw.point(lambda x: 255 if x >= 160 else 0, mode="1")
    if bw.size != (width, height):
        bw = bw.resize((width, height), Image.Resampling.LANCZOS).convert("1")
    return bw.tobytes()


def render_text_card(
    title: str, body: str, width: int = WIDTH, height: int = HEIGHT
) -> bytes:
    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)

    # Scale typography roughly with panel height
    title_size = max(22, height // 11)
    body_size = max(18, height // 15)
    header_h = max(48, height // 7)
    title_font = load_font(title_size)
    body_font = load_font(body_size)

    draw.rectangle((0, 0, width, header_h), fill="black")
    header = (title or "消息").strip() or "消息"
    draw.text((20, max(8, (header_h - title_size) // 2)), header[:40], font=title_font, fill="white")

    lines = wrap_text(draw, body or "", body_font, width - 40)
    y = header_h + 24
    line_h = body_size + 12
    for line in lines:
        if y > height - 28:
            draw.text((20, height - 28), "…", font=body_font, fill="black")
            break
        draw.text((20, y), line, font=body_font, fill="black")
        y += line_h

    return image_to_gx_bitmap(img, width, height)


def render_uploaded_image(
    data: bytes,
    fit: str = "contain",
    width: int = WIDTH,
    height: int = HEIGHT,
) -> bytes:
    src = Image.open(io.BytesIO(data)).convert("RGB")
    canvas = Image.new("RGB", (width, height), "white")

    if fit == "cover":
        scale = max(width / src.width, height / src.height)
    else:
        scale = min(width / src.width, height / src.height)

    new_w = max(1, int(src.width * scale))
    new_h = max(1, int(src.height * scale))
    resized = src.resize((new_w, new_h), Image.Resampling.LANCZOS)
    x = (width - new_w) // 2
    y = (height - new_h) // 2
    canvas.paste(resized, (x, y))
    return image_to_gx_bitmap(canvas, width, height)


MAX_BITMAP_W = 800
MAX_BITMAP_H = 480


def _check_bitmap_dims(width: int, height: int) -> None:
    if (
        width < 8
        or height < 1
        or width > MAX_BITMAP_W
        or height > MAX_BITMAP_H
        or (width % 8) != 0
    ):
        raise ValueError(
            "width must be a multiple of 8 in 8..800; height must be 1..480"
        )


def decode_named_bitmap(
    payload: bytes,
    *,
    encoding: str,
    width: int | None,
    height: int | None,
) -> Tuple[bytes, int, int]:
    """Return Gx MONO_HLSB bytes plus pixel size.

    encoding=gx: payload is already packed (1=white, 0=black, MSB left).
    encoding=png: payload is a PNG; converted without letterboxing.
    """
    enc = (encoding or "gx").strip().lower()
    if enc == "png":
        img = Image.open(io.BytesIO(payload))
        img.load()
        w = int(width or img.width)
        h = int(height or img.height)
        _check_bitmap_dims(w, h)
        return image_to_gx_bitmap(img, w, h), w, h
    if enc != "gx":
        raise ValueError("encoding must be gx or png")
    if width is None or height is None:
        raise ValueError("gx encoding requires width and height")
    w, h = int(width), int(height)
    _check_bitmap_dims(w, h)
    need = w * h // 8
    if len(payload) != need:
        raise ValueError(f"gx bitmap is {len(payload)} bytes, expected {need}")
    return payload, w, h


def save_bitmap(path: Path, data: bytes) -> Tuple[int, int]:
    n = len(data)
    known = {
        800 * 480 // 8: (800, 480),
        400 * 300 // 8: (400, 300),
    }
    if n not in known:
        raise ValueError(f"unsupported bitmap size {n} bytes")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return known[n]
