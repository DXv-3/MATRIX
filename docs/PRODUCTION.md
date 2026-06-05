# MATRIX Production Guide

## One-command setup

```bash
cd ~/MATRIX
chmod +x scripts/*.sh
./scripts/production-setup.sh
```

This will:

- Install dependencies (including RAW support)
- Create `~/.matrix/` data + quarantine + backups
- Generate `.env` with `MATRIX_ENV=production`, scan roots, and API token
- Run `matrix init` and `matrix doctor --fix`

Save the printed **API token** — required for Web UI and API.

## Daily operations

| Task | Command |
|------|---------|
| Full scan + dedup | `./scripts/run-pipeline.sh` |
| Catalog backup | `./scripts/backup-catalog.sh` or `matrix backup` |
| Health check | `curl -s http://127.0.0.1:8765/api/health` |
| Config validation | `matrix doctor` |
| Review duplicates | `matrix review` (or Web UI) |

## Run as a service (macOS)

```bash
./scripts/install-launchd.sh
```

Loads `com.matrix.archive` — API at http://127.0.0.1:8765/

Logs: `~/.matrix/launchd.stdout.log`

## Security checklist

- [x] API bound to `127.0.0.1` by default (`MATRIX_BIND_PUBLIC=0`)
- [x] `MATRIX_API_TOKEN` required in production
- [x] Scan paths validated; system dirs blocked
- [x] Previews only under `MATRIX_SCAN_ROOTS`
- [x] Quarantine moves only under `MATRIX_QUARANTINE`
- [x] No hard deletes

For remote access, use `deploy/nginx-matrix.conf` with TLS — do not expose port 8765 directly.

## Docker production

```bash
cp .env.example .env   # or use production-setup output
export MATRIX_ARCHIVE_PATH=/path/to/photos
docker compose -f docker-compose.prod.yml up -d --build
```

## Environment reference

See `.env.example` for all variables.

## Troubleshooting

```bash
matrix doctor --fix
tail -f ~/.matrix/matrix.log
```