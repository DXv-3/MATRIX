from __future__ import annotations

import platform
import subprocess

from matrix.db import Database
from matrix.services import asset_path_allowed


def reveal_asset_in_finder(db: Database, asset_id: int) -> dict:
    if platform.system() != "Darwin":
        raise RuntimeError("Show in Finder is only available on macOS")
    path = asset_path_allowed(db, asset_id)
    if not path:
        raise FileNotFoundError("asset not found or path is not readable")
    subprocess.run(["open", "-R", str(path)], check=True)
    return {"asset_id": asset_id, "path": str(path)}