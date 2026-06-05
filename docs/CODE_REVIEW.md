# MATRIX Code Review — Jun 2026

## Summary

Review covered engine, DB layer, API, scanner, dedup, quarantine, events, and web UI integration. Critical bugs were fixed, security hardened, and visual dedup optimized for 100k+ assets.

---

## 1. Bug Detection & Resolution

| Issue | Root cause | Fix |
|-------|------------|-----|
| **Exact dedup dropped valid members** | `skip_ids` removed arbitrary cluster members instead of building connected components | Union-find per SHA256 cluster; only non-derivative pairs link |
| **Re-running dedup duplicated groups** | No cleanup before INSERT into `duplicate_groups` | `clear_group_types()` before EXACT/VISUAL/DERIVATIVE/LINEAGE rebuild |
| **XMP parent_id inverted (historical)** | Redundant UPDATE after upsert with correct parent | Removed wrong UPDATE; upsert sets `parent_id` on insert |
| **Lineage `COALESCE(parent_id, ?)`** | Never updated parent chain on re-run | Set `parent_id=?` explicitly in lineage pass |
| **SQLite write races** | New connection per call, default journal | WAL + `busy_timeout` + `threading.Lock` on transactions |
| **SSE from watcher thread** | `asyncio.Queue.put_nowait` from non-async thread | Thread-safe `EventBus` with lock around subscriber list |
| **Preview allowed any catalog path** | Fallback returned paths outside scan roots | Require `path_under_allowed_roots()` — no bypass |
| **Daemon stale PID** | Non-numeric or dead PID blocked restart | Validate PID file; fail if process exits on start |
| **Lineage used `parent_id`** | Film hierarchy collided with XMP derivative dedup | Lineage uses `lineage_group_id` only; derivative uses XMP parents only |
| **False DERIVATIVE groups** | Any `parent_id` triggered derivative pass | `mark_derivative_groups` limited to XMP sidecar parents |

---

## 2. Security & Hardening

- **`matrix/security.py`**: `resolve_directory()`, blocked system prefixes (`/etc`, `/usr`, `~/.ssh`), max file sizes for hash/XMP.
- **API**: Optional `MATRIX_API_TOKEN` Bearer auth; security headers (`nosniff`, `DENY` frame); Pydantic bounds on `workers`, `limit`, `group_id`.
- **Scan paths**: Reject `..` segments; resolve before walk; `followlinks=False` in `os.walk`.
- **Quarantine**: Source must match catalog row; destination forced under `MATRIX_QUARANTINE`.
- **Previews**: Only files under configured scan roots + data/quarantine dirs.

---

## 3. Performance Optimization

| Area | Before | After | Impact |
|------|--------|-------|--------|
| Visual dedup | O(n²) global on all phashes | O(n²) **per 6-char bucket** | ~10⁴× fewer comparisons at 100k scale |
| Scanner | `pool.map` | `as_completed` + capped workers (1–32) | Better thread utilization |
| File stat | `stat()` called 2–3× per file | Once per file in upsert | Fewer syscalls |
| XMP hash | `read_bytes()` whole file | Streamed SHA256, 32 MiB cap | Memory-safe large sidecars |
| DB | DELETE journal implied | WAL + NORMAL sync | Concurrent scan writes |

---

## 4. Code Quality & Maintainability

- Centralized orchestration in `services.py` (API + CLI share validation).
- Removed dead async stub in `api.pipeline`.
- Removed duplicate `re.IGNORECASE` flags on compiled regexes.
- `dedup_engine._assign_group()` DRY for EXACT/VISUAL/DERIVATIVE.
- Typed validation errors: `PathValidationError`.

---

## 5. Refactoring Decisions

1. **`clear_group_types()`** — Idempotent dedup/lineage runs; safe to re-run pipeline.
2. **Union-find clustering** — Correct transitive duplicates (A≈B, B≈C ⇒ one group).
3. **Phash bucketing** — Scales to large archives without external index service.
4. **Transaction wrapper** — Single pattern for all writes; easier to add batch inserts later.

---

## Configuration (new)

```bash
MATRIX_API_TOKEN=secret          # optional API auth
MATRIX_MAX_HASH_BYTES=536870912  # 512 MiB cap per file hash
MATRIX_MAX_XMP_BYTES=33554432    # 32 MiB XMP cap
```