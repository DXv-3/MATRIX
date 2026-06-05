# MATRIX — Full LLM Handoff (zero prior context required)

**Last updated:** 2026-06-04  
**Version:** 1.2.0 (`matrix-archive` in `pyproject.toml`)  
**Primary machine (author):** macOS, user `vinnygilberti`, project at `/Users/vinnygilberti/MATRIX`  
**Runtime data:** `~/.matrix/` (NOT inside the repo; per-user catalog)

---

## 1. What MATRIX is

MATRIX is a **standalone production macOS-oriented app** for large photo/video archives (100k+ assets). It:

- **Catalogs** files (SHA256, perceptual hash, metadata, film lineage)
- **Groups duplicates** (exact SHA + visual pHash)
- **Resolves lineage** (Roll/Frame naming for film scans)
- **Human review** before any destructive action
- **Quarantines** rejected duplicates (moves files; **never hard-deletes**)

Delivery surfaces (all implemented):

| Layer | Entry |
|-------|--------|
| Engine | `scanner.py`, `hasher.py`, `dedup_engine.py`, `lineage_resolver.py` |
| CLI | `matrix` command via `matrix/main.py` |
| Rich TUI | `matrix review` |
| FastAPI | `matrix/api.py` on port **8765** |
| Web UI | `matrix/web/static/` (dashboard, scan, review, lineage, assets) |
| SSE | `/api/events` live log |
| Watcher | `matrix watch` |
| macOS app | `MATRIX.app` via `matrix app --install` |
| Docker | `docker-compose.yml`, `docker-compose.prod.yml` |

---

## 2. Repository layout (important paths only)

```
MATRIX/
├── pyproject.toml          # deps, matrix CLI entrypoint
├── schema.sql              # SQLite catalog schema
├── .env.example            # template (no secrets)
├── .env                    # gitignored; production config + API token (per machine)
├── setup.sh                # dev setup
├── Start MATRIX.command    # portable double-click launcher (uses script dir, not hardcoded user)
├── RUN_ON_NEW_MAC.sh       # one-shot: rm .venv + friend-setup + matrix app
├── HOW_TO_RUN.txt          # human instructions for AirDrop recipients
├── HANDOFF.md              # this file
├── matrix/
│   ├── main.py             # CLI argparse
│   ├── api.py              # FastAPI + auth middleware + static mount
│   ├── services.py         # orchestration (scan, dedup, approve, report, lists)
│   ├── db.py               # SQLite WAL + locking
│   ├── scanner.py, hasher.py, dedup_engine.py, lineage_resolver.py
│   ├── review_queue.py     # Rich TUI review (+ [f] Finder on macOS)
│   ├── quarantine_handler.py
│   ├── security.py         # path validation, blocked dirs, size limits
│   ├── preview.py          # Pillow thumbnails for API
│   ├── reveal.py           # macOS `open -R` for Show in Finder
│   ├── daemon.py           # background uvicorn via run-server.sh
│   ├── macos_app.py        # app launch, browser, MATRIX_BROWSER env
│   ├── macos_launcher.py   # MATRIX.app entry
│   ├── settings.py         # .env loading, production validation
│   ├── events.py           # thread-safe SSE bus
│   ├── doctor.py, backup.py, watcher.py, config.py, logging_config.py
│   └── web/static/
│       ├── index.html
│       ├── app.js          # Review UI, auth, previews, Finder buttons
│       └── style.css       # incl. .btn-delete-glow (gradient text only)
├── scripts/
│   ├── production-setup.sh # Vinny's Mac production bootstrap
│   ├── friend-setup.sh     # NEW Mac after AirDrop (deletes broken .venv)
│   ├── ensure-venv.sh      # detects venv pip shebang from another user → rm .venv
│   ├── package-for-friend.sh → Desktop/MATRIX-for-friend.zip (no .venv, no .env)
│   ├── run-server.sh, run-pipeline.sh, backup-catalog.sh
│   ├── build-macos-app.sh, install-launchd.sh, open-ui.sh
├── tests/                  # test_dedup, test_security, test_doctor (4 tests pass)
├── docs/PRODUCTION.md, CODE_REVIEW.md, ERD.txt
└── deploy/nginx-matrix.conf
```

**Do not AirDrop `.venv`** — virtualenv contains absolute paths to the source Mac’s Python (e.g. `/Users/vinnygilberti/MATRIX/.venv/bin/python3.14`). On another Mac this causes:

```
.venv/bin/pip: /Users/vinnygilberti/.../python3.14: bad interpreter
zsh: command not found: matrix
```

---

## 3. Data model & safety

- **Catalog DB:** `~/.matrix/catalog.db` (path from `MATRIX_DATA_DIR`)
- **Quarantine:** `~/.matrix/quarantine/` or `MATRIX_QUARANTINE`
- **Logs:** `~/.matrix/matrix.log`, `~/.matrix/server.log`, `~/.matrix/launcher.err.log`
- **Backups:** `~/.matrix/backups/`

**Safety rules (enforced in code):**

- No hard deletes; quarantine = move under quarantine root only
- PSD/TIFF not auto-marked duplicate of RAW parent
- XMP sidecars → derivative grouping, not duplicate of RAW
- Preview/reveal paths must be under scan roots + data/quarantine
- Production requires `MATRIX_API_TOKEN` (16+ chars)

---

## 4. Environment variables (`.env`)

| Variable | Purpose |
|----------|---------|
| `MATRIX_ENV` | `production` or development |
| `MATRIX_DATA_DIR` | Default `~/.matrix` |
| `MATRIX_SCAN_ROOTS` | `:`-separated archive directories |
| `MATRIX_QUARANTINE` | Quarantine folder |
| `MATRIX_API_HOST` | Default `127.0.0.1` |
| `MATRIX_API_PORT` | Default `8765` |
| `MATRIX_API_TOKEN` | Bearer + `?token=` for API/UI |
| `MATRIX_BIND_PUBLIC` | `1` to allow non-localhost (use with care) |
| `MATRIX_BROWSER` | macOS app name for `open -a` (Chrome, Firefox, Arc…) |
| `MATRIX_PHASH_MAX_DISTANCE` | Visual dup threshold (default 10) |
| `MATRIX_MAX_HASH_BYTES` | 512 MiB default |
| `MATRIX_MAX_XMP_BYTES` | 32 MiB default |

**API token** lives in project `.env` on each machine — **never commit or text multi-line setup**. For browser: `http://127.0.0.1:8765/?token=TOKEN` or paste when prompted (stored in `localStorage` as `matrix_token`).

---

## 5. CLI commands (complete list)

```bash
source .venv/bin/activate   # always after setup

matrix init
matrix doctor [--fix]
matrix backup [--dest PATH]
matrix scan [--root PATH] [--workers N]
matrix dedup
matrix lineage
matrix pipeline [--root PATH] [--workers N]
matrix review [--execute]    # --execute moves to quarantine
matrix report
matrix serve [--host] [--port]
matrix ui [--browser "Google Chrome"] [--host] [--port]
matrix app [--install] [--browser NAME]
matrix stop
matrix watch [--root PATH]
```

Production mode forces API bind to `127.0.0.1` unless `MATRIX_BIND_PUBLIC=1`.

---

## 6. API endpoints

| Method | Path | Notes |
|--------|------|-------|
| GET | `/`, `/health`, `/api/health` | UI / health |
| GET | `/api/report`, `/api/config` | Stats + scan roots |
| GET | `/api/assets`, `/api/assets/{id}` | Catalog |
| GET | `/api/assets/{id}/preview` | JPEG thumb; auth via Bearer or `?token=` |
| POST | `/api/assets/{id}/reveal` | macOS Finder `open -R` |
| GET | `/api/groups/pending` | Review queue |
| GET | `/api/lineage` | Lineage groups |
| GET | `/api/events` | SSE |
| POST | `/api/scan`, `/api/dedup`, `/api/pipeline` | Jobs |
| POST | `/api/approve` | `{ group_id, action, dry_run }` |

**Review actions:** `KEEP_ALL`, `DELETE_DUPLICATES`, `SKIP`, `MANUAL`

Auth middleware: all `/api/*` except `/api/health` require token when `MATRIX_API_TOKEN` set.

---

## 7. Web UI — current behavior (Review tab)

Built in `matrix/web/static/app.js` + `style.css`:

- **Pending duplicate groups** from `/api/groups/pending`
- Each member: **thumbnail** via `/api/assets/{id}/preview?token=...` (required in production — img tags don’t send Bearer headers)
- **Show in Finder** per member → POST `/api/assets/{id}/reveal`
- Actions: Keep all, **Delete duplicates**, Skip, Manual
- Dry-run toggle (default on) — no quarantine moves when checked
- **Delete duplicates button styling:** solid red `border` (no spinning ring); label span `.btn-delete-label` has **animated horizontal gradient text** only; `prefers-reduced-motion` falls back to solid red text

SSE connects with `?token=` on EventSource URL.

---

## 8. Critical bugs fixed (see `docs/CODE_REVIEW.md`)

- Exact dedup broken when lineage set `parent_id` → fixed union-find + lineage uses `lineage_group_id` only
- Re-run dedup duplicated groups → `clear_group_types()` before rebuild
- Cross-mac `.venv` → `ensure-venv.sh` + `friend-setup.sh` remove broken venv
- Preview path escape → `asset_path_allowed()` only under allowed roots
- Phash O(n²) → bucketed by 6-char prefix

**Tests:** `pytest tests/` → 4 passed.

---

## 9. Production setup (Vinny’s Mac)

```bash
cd ~/MATRIX
./scripts/production-setup.sh   # now calls ensure-venv.sh first
matrix doctor --fix
./scripts/run-pipeline.sh       # scan + dedup real archives
matrix app                      # or double-click Start MATRIX.command
```

Optional: `./scripts/install-launchd.sh` for always-on API.

**Installed app:** `/Applications/MATRIX.app` (duplicate in `~/Applications` was removed).

**Desktop launcher:** `~/Desktop/Open MATRIX.command` → delegates to `~/MATRIX/Start MATRIX.command`.

---

## 10. Sharing with another Mac (friend: Javier)

**What went wrong in real session:**

1. AirDropped folder **with Vinny’s `.venv`** → bad interpreter error
2. Ran `production-setup.sh` without deleting `.venv` first (older zip)
3. Texted multi-line Terminal commands → `zsh: = not found` from pasting `====` banner lines or broken `=` lines
4. Expected Vinny’s catalog (19 test assets) — catalog is in **Vinny’s** `~/.matrix/`, not in repo

**Correct handoff procedure:**

```bash
# On Vinny's Mac:
cd ~/MATRIX
./scripts/package-for-friend.sh
# AirDrop Desktop/MATRIX-for-friend.zip (excludes .venv and .env)
```

**On friend’s Mac:**

```bash
# Unzip → ~/Downloads/MATRIX (or ~/MATRIX)
cd ~/Downloads/MATRIX
bash RUN_ON_NEW_MAC.sh
# OR double-click "Start MATRIX.command"
# OR:
rm -rf .venv && ./scripts/friend-setup.sh && source .venv/bin/activate && matrix app
```

Friend gets **new** `MATRIX_API_TOKEN` in their `.env`. They must **scan their own photos**:

```bash
matrix scan --root "$HOME/Pictures"
matrix dedup
matrix ui
```

**Do not text multi-line shell commands** — use zip + double-click, or **one single-line** command.

Requires **Python 3.11+**.

---

## 11. Browser & remote access

- **Different browser:** `matrix ui --browser "Google Chrome"` or `MATRIX_BROWSER=Firefox` in `.env`
- **Manual:** open `http://127.0.0.1:8765/?token=TOKEN`
- **Remote/LAN:** `MATRIX_API_HOST=0.0.0.0`, `MATRIX_BIND_PUBLIC=1`, share LAN IP + token (trusted network only)
- **Internet:** use `deploy/nginx-matrix.conf` + TLS; do not expose :8765 publicly without auth

---

## 12. Related but separate work (conversation context)

**Track A — GitHub photo dedup report** (not in this repo):

- Skill: `~/.grok/skills/github-photo-dedup/SKILL.md`
- GitHub user **DXv-3** (not StudioVinny)
- ~845 repos merged; report delivered with ecosystem ranking (imagededup, dupeguru, czkawka, etc.)

**Track B — MATRIX** is the implementation the user wanted as a full standalone app; all 6 original spec steps + production hardening + UI polish were completed in this project.

---

## 13. Supported file types

CR3, CR2, ARW, NEF, DNG, TIFF, PSD, JPEG, HEIC, MP4. RAW pHash needs `pip install -e ".[raw]"` (rawpy). Preview returns 404 for `.mp4`, `.psd` (placeholder shown in UI).

---

## 14. Common troubleshooting

| Symptom | Fix |
|---------|-----|
| `bad interpreter` in pip | `rm -rf .venv && ./scripts/friend-setup.sh` |
| `matrix: command not found` | `source .venv/bin/activate` |
| `zsh: = not found` | Don’t paste decorative `===` lines; one command per paste |
| Blank review thumbnails | Token in preview URL; check `localStorage.matrix_token` |
| Empty review queue | Run `matrix dedup` after `matrix scan` |
| Port in use | `matrix stop` or `lsof -i :8765` |
| App “nothing happens” | Load `.env` on launch; check `~/.matrix/server.log` |

```bash
matrix doctor --fix
tail -f ~/.matrix/matrix.log
curl -s http://127.0.0.1:8765/api/health
```

---

## 15. Key design decisions for future agents

1. **Idempotent dedup:** always safe to re-run `matrix dedup` / pipeline
2. **Services layer** is single source of truth for API + CLI
3. **Auth on static API routes** but UI is same-origin; previews need query token
4. **Friend distribution** = zip without venv/env, not raw AirDrop of dev folder
5. **UI destructive action** = visually distinct (gradient label on delete) but still requires dry-run awareness
6. **Quarantine only** — product promise to user

---

## 16. Files changed in recent UI/session work

- `matrix/web/static/app.js` — `previewUrl()`, `revealInFinder()`, review member cards, delete button markup
- `matrix/web/static/style.css` — `.btn-delete-glow`, `.btn-delete-label`, member preview layout
- `matrix/api.py` — `POST /api/assets/{id}/reveal`
- `matrix/reveal.py` — new
- `matrix/review_queue.py` — Finder `[f]` in TUI
- `matrix/macos_app.py` — `MATRIX_BROWSER`, `build_ui_url`, token in URL
- `scripts/ensure-venv.sh`, `friend-setup.sh`, `package-for-friend.sh`, `RUN_ON_NEW_MAC.sh`, `Start MATRIX.command`
- `HOW_TO_RUN.txt` — friend instructions

---

## 17. What the next LLM should do if user continues

- **Run commands on machine** — user rules require executing, not only instructing
- **Don’t expose API tokens** in chat — read from `.env` locally if needed
- **Regenerate friend zip** after material changes: `./scripts/package-for-friend.sh`
- **Hard refresh browser** after static JS/CSS changes (Cmd+Shift+R)
- **Read** `docs/CODE_REVIEW.md` and `docs/PRODUCTION.md` for depth

---

## 18. Quick verification checklist

```bash
cd ~/MATRIX && source .venv/bin/activate
pytest tests/ -q
matrix doctor
curl -s http://127.0.0.1:8765/api/health
# Expect: status ok, version 1.2.0, assets count from catalog
```

---

*End of handoff — paste this entire document into a new LLM session to continue MATRIX work with full context.*