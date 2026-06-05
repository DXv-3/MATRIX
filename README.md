# MATRIX

**Standalone** photo archive intelligence for film + digital libraries (100k+ assets).

All layers ship in one install — pick CLI, terminal UI, browser, API, file watcher, or macOS app.

## Architecture (all layers)

```text
                         ┌─────────────────────────────────┐
                         │         YOU / OPERATOR           │
                         └───────────────┬─────────────────┘
                                         │
     ┌───────────┬───────────┬───────────┼───────────┬───────────┐
     ▼           ▼           ▼           ▼           ▼           ▼
┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐
│  CLI    │ │ Rich    │ │  Web    │ │ FastAPI │ │ Watcher │ │ macOS   │
│ matrix  │ │  TUI    │ │   UI    │ │  REST   │ │ drop    │ │  .app   │
│ scan…   │ │ review  │ │  :8765  │ │ + SSE   │ │ folder  │ │ Dock    │
└────┬────┘ └────┬────┘ └────┬────┘ └────┬────┘ └────┬────┘ └────┬────┘
     │           │           │           │           │           │
     └───────────┴───────────┴─────┬─────┴───────────┴───────────┘
                                   ▼
                    ┌──────────────────────────────┐
                    │      SERVICES (orchestration) │
                    │  scan · dedup · lineage ·     │
                    │  approve · report · previews  │
                    └──────────────┬───────────────┘
                                   ▼
          ┌────────────┬───────────┴───────────┬────────────┐
          ▼            ▼                       ▼            ▼
     scanner.py   dedup_engine.py    lineage_resolver.py  hasher.py
          │            │                       │            │
          └────────────┴───────────┬───────────┴────────────┘
                                   ▼
                        ~/.matrix/catalog.db
                        ~/.matrix/quarantine/
```

| Layer | Command / URL | Purpose |
|-------|----------------|---------|
| **1. Engine** | (internal) | SHA256, pHash, grouping, film lineage |
| **2. CLI** | `matrix scan`, `dedup`, `report` | Scriptable automation |
| **3. TUI** | `matrix review` | Terminal duplicate review |
| **4. API** | `matrix serve` → `/api/*` | Integrations, headless ops |
| **5. Web UI** | `matrix ui` or http://127.0.0.1:8765 | Dashboard, review, lineage browser |
| **6. Watcher** | `matrix watch --root PATH` | Auto-index new drops |
| **7. macOS app** | `matrix app --install` | `MATRIX.app` in Applications |
| **8. Docker** | `docker compose up` | ARM64 server + volumes |

## Production (recommended)

```bash
./scripts/production-setup.sh   # creates .env, token, ~/.matrix
matrix doctor
./scripts/run-pipeline.sh       # scan + dedup + backup
./scripts/install-launchd.sh    # always-on API on :8765
```

Full guide: [docs/PRODUCTION.md](docs/PRODUCTION.md)

## Quickstart (5 steps)

```bash
cd ~/MATRIX
chmod +x setup.sh scripts/build-macos-app.sh
./setup.sh
source .venv/bin/activate

# Edit .env — set MATRIX_SCAN_ROOTS
matrix scan --root /path/to/archive
matrix dedup
matrix ui          # opens browser dashboard
matrix review      # terminal review (optional)
```

## Layer commands

```bash
# CLI
matrix init | scan | dedup | lineage | report

# TUI
matrix review
matrix review --execute   # quarantine (never hard delete)

# API + Web
matrix serve              # foreground server + UI at /
matrix ui                 # background server + open browser
matrix stop

# Watcher
matrix watch --root /Volumes/Photos

# macOS app bundle
matrix app --install      # builds ~/Applications/MATRIX.app
open -a MATRIX            # or: matrix app
```

## Web UI tabs

- **Dashboard** — stats, dedup shortcut, live SSE log
- **Scan** — scan-only or full pipeline
- **Review** — pending groups, previews, Keep / Delete / Skip / Manual
- **Lineage** — Roll + Frame variant chains
- **Assets** — catalog table with thumbnails

## API reference

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/` | Web UI |
| GET | `/health` | Liveness + layer list |
| GET | `/api/report` | Stats |
| GET | `/api/assets` | Paginated catalog |
| GET | `/api/assets/{id}/preview` | Thumbnail |
| GET | `/api/groups/pending` | Review queue |
| GET | `/api/lineage` | Film groups |
| GET | `/api/events` | SSE live log |
| POST | `/api/scan` | Index folder |
| POST | `/api/dedup` | Group duplicates |
| POST | `/api/pipeline` | Scan + dedup |
| POST | `/api/approve` | Review decision |

Legacy aliases: `/scan`, `/dedup`, `/groups`, `/approve`, `/report`.

## Supported formats

CR3, CR2, ARW, NEF, DNG, TIFF, PSD, JPEG, HEIC, MP4 (video: SHA256; pHash when decodable).

RAW pHash: `pip install -e ".[raw]"` (rawpy).

## Schema

- `schema.sql` — full catalog
- `docs/ERD.txt` — ASCII diagram
- `examples/group_map.json` — export example

## Docker (Mac M1 / arm64)

```bash
export MATRIX_ARCHIVE_PATH=/Volumes/YourPhotos
docker compose up --build
# UI: http://127.0.0.1:8765/
```

## Safety

- **No auto-delete** anywhere
- PSD/TIFF not auto-marked duplicate of RAW parent
- XMP sidecar → derivative, not duplicate
- Human review (Web or TUI) before quarantine moves