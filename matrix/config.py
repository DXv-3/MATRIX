from __future__ import annotations

import os
from pathlib import Path


def data_dir() -> Path:
    return Path(os.environ.get("MATRIX_DATA_DIR", Path.home() / ".matrix")).expanduser()


def catalog_db() -> Path:
    return data_dir() / "catalog.db"


def quarantine_dir() -> Path:
    return Path(
        os.environ.get("MATRIX_QUARANTINE", data_dir() / "quarantine")
    ).expanduser()


def scan_roots() -> list[Path]:
    raw = os.environ.get("MATRIX_SCAN_ROOTS", "")
    if raw.strip():
        return [Path(p).expanduser() for p in raw.split(os.pathsep) if p.strip()]
    return []


PHASH_HAMMING_MAX = int(os.environ.get("MATRIX_PHASH_MAX_DISTANCE", "10"))
SUPPORTED_EXTENSIONS = {
    ".cr3",
    ".cr2",
    ".arw",
    ".nef",
    ".dng",
    ".tif",
    ".tiff",
    ".psd",
    ".jpg",
    ".jpeg",
    ".heic",
    ".heif",
    ".mp4",
    ".png",
}

RAW_EXTENSIONS = {".cr3", ".cr2", ".arw", ".nef", ".dng"}
XMP_SUFFIX = ".xmp"