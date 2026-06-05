from __future__ import annotations

import threading
import time
from pathlib import Path

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from matrix.config import SUPPORTED_EXTENSIONS, XMP_SUFFIX
from matrix.db import Database
from matrix.events import bus
from matrix.scanner import scan_file

DEBOUNCE_SEC = 1.5


class MatrixWatchHandler(FileSystemEventHandler):
    def __init__(self, db: Database, scan_root: Path) -> None:
        self.db = db
        self.scan_root = scan_root.resolve()
        self._pending: dict[str, float] = {}
        self._lock = threading.Lock()
        self._timer: threading.Timer | None = None

    def _schedule(self, path: str) -> None:
        with self._lock:
            self._pending[path] = time.time()
            if self._timer:
                self._timer.cancel()
            self._timer = threading.Timer(DEBOUNCE_SEC, self._flush)
            self._timer.daemon = True
            self._timer.start()

    def _flush(self) -> None:
        with self._lock:
            paths = list(self._pending.keys())
            self._pending.clear()
        for p in paths:
            self._index(Path(p))

    def _index(self, path: Path) -> None:
        if path.suffix.lower() not in SUPPORTED_EXTENSIONS and path.suffix.lower() != XMP_SUFFIX:
            return
        try:
            scan_file(self.db, path, scan_root=self.scan_root)
            bus.publish("watch.indexed", {"path": str(path)})
            print(f"[matrix] indexed: {path}")
        except Exception as exc:
            bus.publish("watch.error", {"path": str(path), "error": str(exc)})
            print(f"[matrix] skip {path}: {exc}")

    def on_created(self, event) -> None:
        if event.is_directory:
            return
        self._schedule(event.src_path)

    def on_modified(self, event) -> None:
        if event.is_directory:
            return
        self._schedule(event.src_path)


def run_watcher(root: Path) -> None:
    db = Database()
    db.init_schema()
    handler = MatrixWatchHandler(db, root)
    observer = Observer()
    observer.schedule(handler, str(root.resolve()), recursive=True)
    observer.start()
    bus.publish("watch.start", {"root": str(root)})
    print(f"[matrix] watching {root} (debounce {DEBOUNCE_SEC}s, Ctrl+C to stop)")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
        bus.publish("watch.stop", {"root": str(root)})
    observer.join()