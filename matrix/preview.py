from __future__ import annotations

import io
from pathlib import Path

from matrix.services import asset_path_allowed
from matrix.db import Database

try:
    from PIL import Image
except ImportError:
    Image = None  # type: ignore


PREVIEW_MAX = 480


def generate_preview(db: Database, asset_id: int) -> tuple[bytes, str] | None:
    if Image is None:
        return None
    path = asset_path_allowed(db, asset_id)
    if not path:
        return None
    ext = path.suffix.lower()
    if ext in {".mp4", ".psd"}:
        return None
    try:
        with Image.open(path) as im:
            im.thumbnail((PREVIEW_MAX, PREVIEW_MAX))
            buf = io.BytesIO()
            fmt = "JPEG"
            if im.mode in ("RGBA", "P"):
                im = im.convert("RGB")
            im.save(buf, format=fmt, quality=85)
            return buf.getvalue(), "image/jpeg"
    except Exception:
        return None