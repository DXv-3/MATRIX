#!/usr/bin/env python3
"""matrix_brain_hooks.py — Drop-in hooks to add brain integration to MATRIX.

Import this module at the top of any MATRIX pipeline stage to get
transparent brain logging with zero changes to existing MATRIX code.

Hook usage pattern:
    from matrix_brain_hooks import hooks

    # At start of scan:
    hooks.on_scan_start(scan_path, estimated_files=len(file_list))

    # For each file:
    hooks.on_file_cataloged(path, hash=h, size_bytes=size)
    hooks.on_duplicate(original, duplicate, kept="original")
    hooks.on_file_archived(path, archive_path)
    hooks.on_error(path, str(e), stage="hash_compute")

    # At end:
    hooks.on_scan_complete(scan_path, files, dupes, errors, duration)

All hooks are no-ops if brain bus is unavailable.
All hooks are non-blocking (async bus writes).
"""
from __future__ import annotations

import time
from pathlib import Path

try:
    from provenance_writer import ProvenanceWriter
    _pw = ProvenanceWriter(source_repo="MATRIX")
except ImportError:
    _pw = None


class _MatrixBrainHooks:
    """Zero-overhead hook container.

    Every method is safe to call regardless of whether brain bus is available.
    Failures are silently ignored — MATRIX pipeline must never be interrupted
    by brain logging.
    """

    def on_scan_start(self, scan_path: str, estimated_files: int = 0, scan_id: str = "") -> None:
        try:
            _pw and _pw.scan_started(scan_path, estimated_files, scan_id)
        except Exception:
            pass

    def on_scan_complete(
        self, scan_path: str, files_processed: int, duplicates_found: int,
        errors: int, duration_seconds: float, scan_id: str = ""
    ) -> None:
        try:
            _pw and _pw.scan_completed(
                scan_path, files_processed, duplicates_found,
                errors, duration_seconds, scan_id
            )
        except Exception:
            pass

    def on_file_cataloged(
        self, file_path: str, file_hash: str = "", size_bytes: int = 0,
        media_type: str = "", tags: list[str] | None = None
    ) -> None:
        try:
            _pw and _pw.file_cataloged(file_path, file_hash, size_bytes, media_type, tags)
            # Register in KG (for cross-repo querying)
            _pw and _pw.register_file_in_kg(file_path, file_hash, media_type)
        except Exception:
            pass

    def on_duplicate(
        self, original_path: str, duplicate_path: str,
        kept: str = "original", hash_match: bool = True,
        original_hash: str = "", duplicate_hash: str = ""
    ) -> None:
        try:
            _pw and _pw.duplicate_found(original_path, duplicate_path, kept, hash_match)
            _pw and _pw.link_duplicate_in_kg(original_path, duplicate_path, original_hash, duplicate_hash)
        except Exception:
            pass

    def on_file_moved(self, old_path: str, new_path: str, reason: str = "") -> None:
        try:
            _pw and _pw.file_moved(old_path, new_path, reason)
        except Exception:
            pass

    def on_file_archived(
        self, file_path: str, archive_location: str,
        compression_ratio: float = 1.0, archive_format: str = ""
    ) -> None:
        try:
            _pw and _pw.file_archived(file_path, archive_location, compression_ratio, archive_format)
        except Exception:
            pass

    def on_review_needed(self, file_path: str, reason: str = "", priority: str = "normal") -> None:
        try:
            _pw and _pw.review_requested(file_path, reason, priority)
        except Exception:
            pass

    def on_review_done(self, file_path: str, outcome: str = "approved", note: str = "") -> None:
        try:
            _pw and _pw.review_completed(file_path, outcome, note)
        except Exception:
            pass

    def on_error(self, file_path: str, error_message: str, stage: str = "") -> None:
        try:
            _pw and _pw.processing_error(file_path, error_message, stage)
        except Exception:
            pass


# Singleton hooks instance — import and use directly
hooks = _MatrixBrainHooks()
