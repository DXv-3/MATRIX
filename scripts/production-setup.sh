#!/usr/bin/env bash
# MATRIX production bootstrap — run once on your Mac
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

# shellcheck source=ensure-venv.sh
source "$ROOT/scripts/ensure-venv.sh"
ensure_matrix_venv

echo "==> MATRIX production setup"
if [[ ! -d .venv ]]; then
  echo "    (New Mac after AirDrop? ./scripts/friend-setup.sh does the same thing.)"
fi
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip wheel
pip install -e ".[raw,dev]"

DATA="$HOME/.matrix"
mkdir -p "$DATA/backups" "$DATA/quarantine"

# Discover scan roots
ROOTS=""
for candidate in \
  "$HOME/Pictures" \
  "$HOME/Desktop/04_ARCHIVE" \
  "$HOME/Photos" \
  "/Volumes/Photos" \
  "/Volumes/Archive"; do
  if [[ -d "$candidate" ]]; then
    if [[ -n "$ROOTS" ]]; then
      ROOTS="${ROOTS}:"
    fi
    ROOTS="${ROOTS}${candidate}"
  fi
done

if [[ -z "$ROOTS" ]]; then
  echo "WARNING: No archive folders found. Edit MATRIX_SCAN_ROOTS in .env"
  ROOTS="$HOME/Pictures"
fi

TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"

if [[ -f .env ]]; then
  echo "Keeping existing .env (delete to regenerate)"
else
  cat > .env << EOF
# MATRIX production configuration — generated $(date -u +%Y-%m-%dT%H:%M:%SZ)
MATRIX_ENV=production
MATRIX_DATA_DIR=$DATA
MATRIX_QUARANTINE=$DATA/quarantine
MATRIX_SCAN_ROOTS=$ROOTS
MATRIX_API_HOST=127.0.0.1
MATRIX_API_PORT=8765
MATRIX_API_TOKEN=$TOKEN
MATRIX_LOG_LEVEL=INFO
MATRIX_LOG_FILE=$DATA/matrix.log
MATRIX_SCAN_WORKERS=8
MATRIX_PHASH_MAX_DISTANCE=10
MATRIX_BIND_PUBLIC=0
EOF
  echo "Created .env with API token (save this token securely):"
  echo "$TOKEN"
fi

cp -n .env "$DATA/.env" 2>/dev/null || cp .env "$DATA/.env"

matrix init
matrix doctor --fix

echo ""
echo "Production setup complete."
echo "  1. matrix doctor"
echo "  2. matrix pipeline --root \"\${FIRST_SCAN_ROOT}\""
echo "  3. matrix serve   OR: ./scripts/install-launchd.sh"
echo "  4. Open http://127.0.0.1:8765/ and paste API token when prompted"