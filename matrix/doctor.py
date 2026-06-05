from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

from matrix.config import catalog_db, data_dir, quarantine_dir, scan_roots
from matrix.db import Database
from matrix.settings import load_env, settings


def run_doctor(fix: bool = False) -> dict:
    load_env()
    cfg = settings()
    report: dict = {
        "environment": cfg.env,
        "production": cfg.production,
        "checks": [],
        "errors": [],
        "warnings": [],
    }

    def check(name: str, ok: bool, detail: str, *, warning: bool = False) -> None:
        report["checks"].append({"name": name, "ok": ok, "detail": detail})
        if not ok:
            (report["warnings"] if warning else report["errors"]).append(f"{name}: {detail}")

    # Python deps
    for mod in ("fastapi", "uvicorn", "imagehash", "PIL", "watchdog"):
        try:
            __import__(mod if mod != "PIL" else "PIL")
            check(f"import:{mod}", True, "ok")
        except ImportError:
            check(f"import:{mod}", False, f"missing {mod}")

    try:
        import rawpy  # noqa: F401

        check("import:rawpy", True, "RAW support enabled")
    except ImportError:
        check("import:rawpy", True, "optional — pip install -e '.[raw]'", warning=True)

    data_dir().mkdir(parents=True, exist_ok=True)
    check("data_dir", data_dir().is_dir(), str(data_dir()))

    db = Database()
    db.init_schema()
    check("catalog_db", catalog_db().is_file(), str(catalog_db()))

    roots = scan_roots()
    if roots:
        for r in roots:
            check(f"scan_root:{r.name}", r.is_dir(), str(r))
    else:
        check("scan_roots", False, "MATRIX_SCAN_ROOTS empty")

    q = quarantine_dir()
    if fix and not q.exists():
        q.mkdir(parents=True, exist_ok=True)
    check("quarantine", q.is_dir(), str(q))

    if cfg.production:
        for err in cfg.validate_production():
            check("production_rule", False, err)
    else:
        if not cfg.api_token:
            report["warnings"].append("MATRIX_API_TOKEN unset (ok for development)")

    venv = shutil.which("python3")
    check("python", bool(venv), venv or "not found")

    report["ok"] = len(report["errors"]) == 0
    return report


def print_doctor_report(report: dict) -> int:
    print(json.dumps(report, indent=2))
    if report["warnings"]:
        print("\nWarnings:", file=sys.stderr)
        for w in report["warnings"]:
            print(f"  - {w}", file=sys.stderr)
    if not report["ok"]:
        print("\nErrors:", file=sys.stderr)
        for e in report["errors"]:
            print(f"  - {e}", file=sys.stderr)
        return 1
    print("\nAll production checks passed.")
    return 0