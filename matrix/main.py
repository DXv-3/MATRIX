from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from matrix.settings import load_env, settings

load_env()

from matrix.config import catalog_db, data_dir, scan_roots  # noqa: E402
from matrix.db import Database  # noqa: E402
from matrix.dedup_engine import export_group_map_json, run_dedup  # noqa: E402
from matrix.lineage_resolver import run_lineage  # noqa: E402
from matrix.logging_config import setup_logging  # noqa: E402
from matrix.review_queue import run_review  # noqa: E402
from matrix.security import PathValidationError, resolve_directory  # noqa: E402
from matrix.services import run_full_pipeline, run_scan  # noqa: E402


def _db() -> Database:
    db = Database()
    db.init_schema()
    return db


def _production_exit() -> None:
    errs = settings().validate_production()
    if errs:
        for e in errs:
            print(e, file=sys.stderr)
        raise SystemExit(1)


def cmd_init(_: argparse.Namespace) -> int:
    setup_logging()
    db = _db()
    print(f"Catalog ready: {db.path}")
    print(f"Data dir: {data_dir()}")
    print(f"Environment: {settings().env}")
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    from matrix.doctor import print_doctor_report, run_doctor

    return print_doctor_report(run_doctor(fix=args.fix))


def cmd_backup(args: argparse.Namespace) -> int:
    from matrix.backup import backup_catalog

    dest = Path(args.dest) if args.dest else None
    out = backup_catalog(dest)
    print(json.dumps({"backup": str(out)}, indent=2))
    return 0


def cmd_scan(args: argparse.Namespace) -> int:
    setup_logging()
    db = _db()
    workers = max(1, min(args.workers, 32))
    try:
        if args.root:
            roots = [resolve_directory(args.root)]
        else:
            roots = scan_roots()
            if not roots:
                print("Set MATRIX_SCAN_ROOTS or pass --root /path/to/archive", file=sys.stderr)
                return 1
        for root in roots:
            stats = run_scan(db, root, workers=workers)
            print(json.dumps(stats, indent=2))
    except PathValidationError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


def cmd_dedup(_: argparse.Namespace) -> int:
    setup_logging()
    db = _db()
    stats = run_dedup(db)
    stats.update(run_lineage(db))
    out = data_dir() / "group_map.json"
    export_group_map_json(db, out)
    stats["group_map"] = str(out)
    print(json.dumps(stats, indent=2))
    return 0


def cmd_pipeline(args: argparse.Namespace) -> int:
    setup_logging()
    if settings().production:
        _production_exit()
    db = _db()
    try:
        root = args.root or (str(scan_roots()[0]) if scan_roots() else None)
        if not root:
            print("Pass --root or set MATRIX_SCAN_ROOTS", file=sys.stderr)
            return 1
        stats = run_full_pipeline(db, root, workers=max(1, min(args.workers, 32)))
        print(json.dumps(stats, indent=2))
    except PathValidationError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


def cmd_lineage(_: argparse.Namespace) -> int:
    db = _db()
    print(json.dumps(run_lineage(db), indent=2))
    return 0


def cmd_review(args: argparse.Namespace) -> int:
    db = _db()
    run_review(db, dry_run=not args.execute, execute=args.execute)
    return 0


def cmd_report(_: argparse.Namespace) -> int:
    from matrix.services import get_report

    print(json.dumps(get_report(_db()), indent=2))
    return 0


def _serve_host_port(args: argparse.Namespace) -> tuple[str, int]:
    cfg = settings()
    host = args.host or cfg.api_host
    port = args.port or cfg.api_port
    if cfg.production and not cfg.bind_public:
        host = "127.0.0.1"
    return host, port


def cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    setup_logging()
    if settings().production:
        _production_exit()
    host, port = _serve_host_port(args)
    print(f"Web UI: http://{host}:{port}/")
    uvicorn.run("matrix.api:app", host=host, port=port, reload=False, log_level="info")
    return 0


def cmd_ui(args: argparse.Namespace) -> int:
    import os

    from matrix.macos_app import open_matrix_app

    if settings().production:
        _production_exit()
    if args.browser:
        os.environ["MATRIX_BROWSER"] = args.browser
    host, port = _serve_host_port(args)
    print(open_matrix_app(host=host, port=port))
    print("Stop with: matrix stop")
    return 0


def cmd_app(args: argparse.Namespace) -> int:
    import os

    from matrix.macos_app import install_app_bundle, open_matrix_app

    if args.install:
        app = install_app_bundle(str(Path(__file__).resolve().parent.parent))
        print(f"Installed {app}")
        return 0
    if args.browser:
        os.environ["MATRIX_BROWSER"] = args.browser
    host, port = _serve_host_port(args)
    print(open_matrix_app(host=host, port=port))
    return 0


def cmd_stop(_: argparse.Namespace) -> int:
    from matrix.daemon import stop_server

    print("MATRIX server stopped." if stop_server() else "No running MATRIX server found.")
    return 0


def cmd_watch(args: argparse.Namespace) -> int:
    from matrix.watcher import run_watcher

    setup_logging()
    root = Path(args.root) if args.root else (scan_roots()[0] if scan_roots() else None)
    if not root:
        print("Pass --root or set MATRIX_SCAN_ROOTS", file=sys.stderr)
        return 1
    run_watcher(resolve_directory(str(root)))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="matrix",
        description="MATRIX — standalone photo archive intelligence",
    )
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("init", help="Initialize catalog database").set_defaults(func=cmd_init)

    doc = sub.add_parser("doctor", help="Validate production configuration")
    doc.add_argument("--fix", action="store_true", help="Create missing dirs")
    doc.set_defaults(func=cmd_doctor)

    bak = sub.add_parser("backup", help="Backup SQLite catalog")
    bak.add_argument("--dest", help="Backup directory")
    bak.set_defaults(func=cmd_backup)

    scan = sub.add_parser("scan", help="Scan archive and hash files")
    scan.add_argument("--root", help="Root directory to scan")
    scan.add_argument("--workers", type=int, default=settings().workers_default)
    scan.set_defaults(func=cmd_scan)

    pipe = sub.add_parser("pipeline", help="Scan + dedup + lineage (production batch)")
    pipe.add_argument("--root", help="Archive root")
    pipe.add_argument("--workers", type=int, default=settings().workers_default)
    pipe.set_defaults(func=cmd_pipeline)

    sub.add_parser("dedup", help="Run duplicate + lineage grouping").set_defaults(func=cmd_dedup)
    sub.add_parser("lineage", help="Resolve film roll/frame lineage").set_defaults(func=cmd_lineage)

    rev = sub.add_parser("review", help="Interactive Rich review queue")
    rev.add_argument("--execute", action="store_true", help="Move rejects to quarantine")
    rev.set_defaults(func=cmd_review)

    sub.add_parser("report", help="Summary stats").set_defaults(func=cmd_report)

    serve = sub.add_parser("serve", help="Start FastAPI + Web UI server")
    serve.add_argument("--host", default=None)
    serve.add_argument("--port", type=int, default=None)
    serve.set_defaults(func=cmd_serve)

    ui = sub.add_parser("ui", help="Background server + open Web UI")
    ui.add_argument("--host", default=None)
    ui.add_argument("--port", type=int, default=None)
    ui.add_argument("--browser", help="macOS browser name (Google Chrome, Firefox, …)")
    ui.set_defaults(func=cmd_ui)

    app_cmd = sub.add_parser("app", help="macOS MATRIX.app")
    app_cmd.add_argument("--install", action="store_true")
    app_cmd.add_argument("--host", default=None)
    app_cmd.add_argument("--port", type=int, default=None)
    app_cmd.add_argument(
        "--browser",
        help='macOS app name, e.g. "Google Chrome", Firefox, Arc, "Brave Browser"',
    )
    app_cmd.set_defaults(func=cmd_app)

    sub.add_parser("stop", help="Stop background server").set_defaults(func=cmd_stop)

    watch = sub.add_parser("watch", help="Watch folder for new files")
    watch.add_argument("--root", help="Directory to watch")
    watch.set_defaults(func=cmd_watch)

    return p


def app_entry() -> None:
    setup_logging()
    parser = build_parser()
    args = parser.parse_args()
    raise SystemExit(args.func(args))


if __name__ == "__main__":
    app_entry()