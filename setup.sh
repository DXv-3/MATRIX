#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

# shellcheck source=scripts/ensure-venv.sh
source "$ROOT/scripts/ensure-venv.sh"
ensure_matrix_venv

echo "==> MATRIX setup"
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip wheel
pip install -e ".[raw]"

if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "Created .env from .env.example — edit MATRIX_SCAN_ROOTS before scanning."
fi

mkdir -p "${MATRIX_DATA_DIR:-$HOME/.matrix}"

matrix init
echo ""
echo "Standalone app ready. Commands:"
echo "  matrix scan --root /path/to/photos"
echo "  matrix dedup"
echo "  matrix review          # dry-run (default)"
echo "  matrix review --execute  # move to quarantine"
echo "  matrix report"
echo "  matrix serve       # API + Web UI"
echo "  matrix ui          # background server + browser"
echo "  matrix app --install  # macOS MATRIX.app"