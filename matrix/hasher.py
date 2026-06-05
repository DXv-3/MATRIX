from __future__ import annotations

import hashlib
import mimetypes
from dataclasses import dataclass
from pathlib import Path

from matrix.config import RAW_EXTENSIONS, SUPPORTED_EXTENSIONS
from matrix.security import MAX_HASH_BYTES, safe_file_size

try:
    import imagehash
    from PIL import Image
except ImportError as exc:  # pragma: no cover
    raise RuntimeError("imagehash and Pillow are required") from exc

try:
    import rawpy

    HAS_RAWPY = True
except ImportError:
    HAS_RAWPY = False


@dataclass
class HashResult:
    sha256: str
    phash: str | None
    width: int | None
    height: int | None
    file_type: str
    mime_type: str | None


def classify_file(path: Path) -> str:
    ext = path.suffix.lower()
    if ext in RAW_EXTENSIONS:
        return "RAW"
    if ext in {".tif", ".tiff"}:
        return "TIFF"
    if ext in {".jpg", ".jpeg"}:
        return "JPEG"
    if ext == ".psd":
        return "PSD"
    if ext == ".dng":
        return "DNG"
    if ext in {".heic", ".heif"}:
        return "HEIC"
    if ext == ".mp4":
        return "MP4"
    return "OTHER"


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    safe_file_size(path, MAX_HASH_BYTES)
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            block = f.read(chunk_size)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def _pil_from_raw(path: Path) -> Image.Image | None:
    if not HAS_RAWPY or path.suffix.lower() not in RAW_EXTENSIONS:
        return None
    try:
        with rawpy.imread(str(path)) as raw:
            rgb = raw.postprocess(use_camera_wb=True, output_bps=8)
        return Image.fromarray(rgb)
    except Exception:
        return None


def _open_image(path: Path) -> Image.Image | None:
    ext = path.suffix.lower()
    if ext == ".mp4":
        return None
    if ext in RAW_EXTENSIONS:
        return _pil_from_raw(path)
    try:
        with Image.open(path) as im:
            return im.convert("RGB")
    except Exception:
        return None


def compute_phash(path: Path) -> tuple[str | None, int | None, int | None]:
    img = _open_image(path)
    if img is None:
        return None, None, None
    try:
        h = imagehash.phash(img)
        return str(h), img.width, img.height
    finally:
        img.close()


def hash_file(path: Path) -> HashResult:
    ext = path.suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise ValueError(f"Unsupported extension: {path}")

    sha = sha256_file(path)
    phash_val, w, h = compute_phash(path)
    ft = classify_file(path)
    mime, _ = mimetypes.guess_type(str(path))

    return HashResult(
        sha256=sha,
        phash=phash_val,
        width=w,
        height=h,
        file_type=ft,
        mime_type=mime,
    )


def hamming_distance(hex_a: str, hex_b: str) -> int:
    try:
        return imagehash.hex_to_hash(hex_a) - imagehash.hex_to_hash(hex_b)
    except Exception:
        return 999