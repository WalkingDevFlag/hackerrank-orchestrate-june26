from __future__ import annotations

import base64
import io
from pathlib import Path

from PIL import Image

from .config import SETTINGS


def _downscale(img: Image.Image, max_dim: int) -> Image.Image:
    w, h = img.size
    longest = max(w, h)
    if longest <= max_dim:
        return img
    scale = max_dim / float(longest)
    return img.resize((max(1, int(w * scale)), max(1, int(h * scale))), Image.LANCZOS)


def load_image_b64(path: Path) -> tuple[str, str]:
    with Image.open(path) as im:
        im = im.convert("RGB")
        im = _downscale(im, SETTINGS.max_image_dim)
        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=SETTINGS.jpeg_quality, optimize=True)
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return b64, "image/jpeg"


def load_claim_images(image_files: list[Path]) -> list[dict]:
    blocks = []
    for p in image_files:
        if not p.exists():
            continue
        b64, media_type = load_image_b64(p)
        blocks.append(
            {
                "type": "image",
                "source": {"type": "base64", "media_type": media_type, "data": b64},
            }
        )
    return blocks


def approx_image_tokens(image_files: list[Path]) -> int:
    total = 0
    for p in image_files:
        if not p.exists():
            continue
        try:
            with Image.open(p) as im:
                w, h = im.size
        except Exception:
            continue
        longest = max(w, h)
        if longest > SETTINGS.max_image_dim:
            scale = SETTINGS.max_image_dim / float(longest)
            w, h = int(w * scale), int(h * scale)
        total += int((w * h) / 750)
    return total
