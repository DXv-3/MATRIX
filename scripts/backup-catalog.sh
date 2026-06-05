#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
source .venv/bin/activate
[[ -f .env ]] && set -a && source .env && set +a
matrix backup
echo "Backups in ${MATRIX_DATA_DIR:-$HOME/.matrix}/backups/"