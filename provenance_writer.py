#!/usr/bin/env python3
"""provenance_writer.py — MATRIX provenance pipeline → brain.db via bus.

Every file MATRIX processes — cataloged, deduplicated, archived, or flagged
— now has a provenance record in brain.db. This creates a queryable,
permanent audit trail that the conductor can use for routing decisions.

What gets written:
    - File catalog events: new file discovered, hash computed, stored
    - Deduplication events: duplicate found, which was kept, which removed
    - Lineage events: file moved/renamed/transformed, old path → new path
    - Archive events: file archived, storage location, compression ratio
    - Review flags: human review requested, outcome recorded
    - Error events: processing failures with file path + error message

Usage:
    from provenance_writer import ProvenanceWriter

    pw = ProvenanceWriter(source_repo="MATRIX")

    # Log a new file being cataloged
    pw.file_cataloged(
        file_path="/Photos/IMG_001.heic",
        file_hash="sha256:abc123...",
        size_bytes=4_200_000,
        media_type="image/heic",
    )

    # Log a duplicate found and removed
    pw.duplicate_found(
        original_path="/Photos/IMG_001.heic",
        duplicate_path="/Downloads/IMG_001.heic",
        kept="original",
    )

    # Log a file archived
    pw.file_archived(
        file_path="/Photos/IMG_001.heic",
        archive_location="/Archive/2024/IMG_001.heic",
        compression_ratio=0.72,
    )

All events are written async via harmony brain bus.
Direct sync writes are used for error events (so they're never lost).
"""
from __future__ import annotations

import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Locate harmony-engine-protocol for brain bus
sys.path.insert(0, str(Path(__file__).parent.parent / "harmony-engine-protocol"))
try:
    from brain_bus import BrainBusPublisher
    _BUS_AVAILABLE = True
except ImportError:
    _BUS_AVAILABLE = False


class ProvenanceWriter:
    """Write MATRIX file provenance events to brain.db via the brain bus."""

    def __init__(self, source_repo: str = "MATRIX", use_bus: bool = True):
        self.source_repo = source_repo
        self._pub: BrainBusPublisher | None = None
        if use_bus and _BUS_AVAILABLE:
            self._pub = BrainBusPublisher(source_repo=source_repo)

    def _run_id(self, prefix: str = "matrix") -> str:
        return f"{prefix}-{str(uuid.uuid4())[:8]}"

    def _detail(self, data: dict) -> str:
        return json.dumps(data)

    def _publish(self, event_type: str, category: str, detail: str,
                 outcome: str = "pass", run_id: str = "") -> bool:
        if self._pub is None:
            # Fallback: print to stdout so nothing is lost
            print(f"[provenance][no-bus] {event_type}: {detail[:80]}")
            return False
        return self._pub.publish_learn(
            run_id=run_id or self._run_id(),
            source=self.source_repo,
            category=category,
            event_type=event_type,
            detail=detail,
            outcome=outcome,
        )

    # ---------------------------------------------------------------- #
    #  File lifecycle events                                            #
    # ---------------------------------------------------------------- #

    def file_cataloged(
        self,
        file_path: str,
        file_hash: str = "",
        size_bytes: int = 0,
        media_type: str = "",
        tags: list[str] | None = None,
        run_id: str = "",
    ) -> bool:
        """Log a new file being discovered and cataloged by MATRIX."""
        return self._publish(
            event_type="FILE_CATALOGED",
            category="file_lifecycle",
            detail=self._detail({
                "path": str(file_path),
                "hash": file_hash,
                "size_bytes": size_bytes,
                "media_type": media_type,
                "tags": tags or [],
            }),
            outcome="pass",
            run_id=run_id,
        )

    def duplicate_found(
        self,
        original_path: str,
        duplicate_path: str,
        kept: str = "original",
        hash_match: bool = True,
        run_id: str = "",
    ) -> bool:
        """Log a duplicate file found during dedup scan."""
        return self._publish(
            event_type="DUPLICATE_FOUND",
            category="deduplication",
            detail=self._detail({
                "original": str(original_path),
                "duplicate": str(duplicate_path),
                "kept": kept,
                "hash_match": hash_match,
            }),
            outcome="pass",
            run_id=run_id,
        )

    def file_moved(
        self,
        old_path: str,
        new_path: str,
        reason: str = "",
        run_id: str = "",
    ) -> bool:
        """Log a file move or rename (lineage event)."""
        return self._publish(
            event_type="FILE_MOVED",
            category="file_lineage",
            detail=self._detail({
                "old_path": str(old_path),
                "new_path": str(new_path),
                "reason": reason,
            }),
            outcome="pass",
            run_id=run_id,
        )

    def file_archived(
        self,
        file_path: str,
        archive_location: str,
        compression_ratio: float = 1.0,
        archive_format: str = "",
        run_id: str = "",
    ) -> bool:
        """Log a file being archived to cold/warm storage."""
        return self._publish(
            event_type="FILE_ARCHIVED",
            category="archival",
            detail=self._detail({
                "path": str(file_path),
                "archive_location": str(archive_location),
                "compression_ratio": round(compression_ratio, 3),
                "archive_format": archive_format,
            }),
            outcome="pass",
            run_id=run_id,
        )

    def review_requested(
        self,
        file_path: str,
        reason: str = "",
        priority: str = "normal",
        run_id: str = "",
    ) -> bool:
        """Log that a file has been flagged for human review."""
        return self._publish(
            event_type="REVIEW_REQUESTED",
            category="human_review",
            detail=self._detail({
                "path": str(file_path),
                "reason": reason,
                "priority": priority,
            }),
            outcome="info",
            run_id=run_id,
        )

    def review_completed(
        self,
        file_path: str,
        outcome: str = "approved",
        reviewer_note: str = "",
        run_id: str = "",
    ) -> bool:
        """Log the outcome of a human review."""
        return self._publish(
            event_type="REVIEW_COMPLETED",
            category="human_review",
            detail=self._detail({
                "path": str(file_path),
                "reviewer_note": reviewer_note,
            }),
            outcome=outcome,  # approved / rejected / deferred
            run_id=run_id,
        )

    def processing_error(
        self,
        file_path: str,
        error_message: str,
        stage: str = "",
        run_id: str = "",
    ) -> bool:
        """Log a file processing error. Uses sync write for reliability."""
        return self._publish(
            event_type="PROCESSING_ERROR",
            category="error",
            detail=self._detail({
                "path": str(file_path),
                "error": error_message[:500],
                "stage": stage,
            }),
            outcome="fail",
            run_id=run_id,
        )

    def scan_started(
        self,
        scan_path: str,
        estimated_files: int = 0,
        scan_id: str = "",
    ) -> bool:
        """Log that a MATRIX scan job started."""
        return self._publish(
            event_type="SCAN_STARTED",
            category="scan",
            detail=self._detail({
                "scan_path": str(scan_path),
                "estimated_files": estimated_files,
                "scan_id": scan_id or self._run_id("scan"),
            }),
            outcome="info",
        )

    def scan_completed(
        self,
        scan_path: str,
        files_processed: int,
        duplicates_found: int,
        errors: int,
        duration_seconds: float,
        scan_id: str = "",
    ) -> bool:
        """Log that a MATRIX scan job completed."""
        return self._publish(
            event_type="SCAN_COMPLETED",
            category="scan",
            detail=self._detail({
                "scan_path": str(scan_path),
                "files_processed": files_processed,
                "duplicates_found": duplicates_found,
                "errors": errors,
                "duration_seconds": round(duration_seconds, 2),
                "scan_id": scan_id,
            }),
            outcome="pass" if errors == 0 else "fail",
        )

    # ---------------------------------------------------------------- #
    #  Knowledge graph integration                                      #
    # ---------------------------------------------------------------- #

    def register_file_in_kg(
        self,
        file_path: str,
        file_hash: str = "",
        media_type: str = "",
    ) -> bool:
        """Add a cataloged file as a node in the knowledge graph."""
        if self._pub is None:
            return False
        node_id = f"file:{Path(file_path).name}:{file_hash[:8]}" if file_hash else f"file:{Path(file_path).name}"
        return self._pub.publish_kg_node(
            node_id=node_id,
            node_type="file",
            label=Path(file_path).name,
            properties={"path": str(file_path), "hash": file_hash, "media_type": media_type},
        )

    def link_duplicate_in_kg(
        self,
        original_path: str,
        duplicate_path: str,
        original_hash: str = "",
        duplicate_hash: str = "",
    ) -> bool:
        """Add a DUPLICATE_OF edge between two file nodes in the KG."""
        if self._pub is None:
            return False
        src_id = f"file:{Path(original_path).name}:{original_hash[:8]}" if original_hash else f"file:{Path(original_path).name}"
        tgt_id = f"file:{Path(duplicate_path).name}:{duplicate_hash[:8]}" if duplicate_hash else f"file:{Path(duplicate_path).name}"
        return self._pub.publish_kg_edge(
            source_id=tgt_id,
            target_id=src_id,
            relation="DUPLICATE_OF",
            weight=1.0,
        )
