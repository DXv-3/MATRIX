#!/usr/bin/env bash
# Nightly or manual full pipeline: scan + dedup + lineage + backup
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
source .venv/bin/activate
[[ -f .env ]] && set -a && source .env && set +a

ROOT_PATH="${1:-}"
if [[ -z "$ROOT_PATH" ]]; then
  ROOT_PATH="${MATRIX_SCAN_ROOTS%%:*}"
fi
echo "Pipeline root: $ROOT_PATH"
matrix pipeline --root "$ROOT_PATH" --workers "${MATRIX_SCAN_WORKERS:-8}"
matrix backup
matrix report