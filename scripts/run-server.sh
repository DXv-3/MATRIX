#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
source .venv/bin/activate
[[ -f .env ]] && set -a && source .env && set +a
[[ -f "$HOME/.matrix/.env" ]] && set -a && source "$HOME/.matrix/.env" && set +a
exec python -m uvicorn matrix.api:app --host "${MATRIX_API_HOST:-127.0.0.1}" --port "${MATRIX_API_PORT:-8765}"