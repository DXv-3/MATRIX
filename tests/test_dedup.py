from pathlib import Path

from matrix.db import Database
from matrix.dedup_engine import run_dedup, run_exact_dedup
from matrix.hasher import hash_file
from matrix.scanner import scan_file


def test_exact_duplicate_group(tmp_path: Path):
    db = Database(tmp_path / "catalog.db")
    db.init_schema()
    img_dir = tmp_path / "photos"
    img_dir.mkdir()
    from PIL import Image

    p1 = img_dir / "a.jpg"
    p2 = img_dir / "b.jpg"
    im = Image.new("RGB", (64, 64), color=(1, 2, 3))
    im.save(p1, "JPEG")
    im.save(p2, "JPEG")

    scan_file(db, p1, scan_root=img_dir)
    scan_file(db, p2, scan_root=img_dir)
    n = run_exact_dedup(db)
    assert n == 1
    rows = db.fetchall("SELECT duplicate_group_id FROM assets")
    assert rows[0]["duplicate_group_id"] == rows[1]["duplicate_group_id"]