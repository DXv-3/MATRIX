#!/usr/bin/env bash
# First-time setup on a new Mac (after AirDrop, zip, or git clone).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "==> MATRIX friend setup"
echo "    Folder: $ROOT"

if [[ ! -f "$ROOT/pyproject.toml" ]]; then
  echo "ERROR: Not a MATRIX project (pyproject.toml missing)."
  echo "You may have copied only part of the folder. Need the full MATRIX directory."
  exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "ERROR: python3 not found."
  echo "Install Python 3.11+ from https://www.python.org/downloads/ or: brew install python@3.12"
  exit 1
fi

PYVER="$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
PYMAJOR="$(echo "$PYVER" | cut -d. -f1)"
PYMINOR="$(echo "$PYVER" | cut -d. -f2)"
if [[ "$PYMAJOR" -lt 3 ]] || [[ "$PYMAJOR" -eq 3 && "$PYMINOR" -lt 11 ]]; then
  echo "ERROR: Python $PYVER found; MATRIX needs Python 3.11 or newer."
  exit 1
fi

# shellcheck source=ensure-venv.sh
source "$ROOT/scripts/ensure-venv.sh"
ensure_matrix_venv

echo "==> Creating virtualenv and installing dependencies (may take a few minutes)…"
python3 -m venv .venv
# shellcheck source=/dev/null
source .venv/bin/activate
pip install -U pip wheel
pip install -e ".[raw]"

DATA="$HOME/.matrix"
mkdir -p "$DATA/backups" "$DATA/quarantine"

# Fresh config for this machine (do not reuse another user's scan roots blindly)
if [[ -f .env ]] && grep -q "MATRIX_API_TOKEN=" .env 2>/dev/null; then
  echo "==> Keeping existing .env in project folder"
else
  ROOTS=""
  for candidate in "$HOME/Pictures" "$HOME/Desktop" "$HOME/Downloads" "$HOME/Photos"; do
    if [[ -d "$candidate" ]]; then
      [[ -n "$ROOTS" ]] && ROOTS="${ROOTS}:"
      ROOTS="${ROOTS}${candidate}"
    fi
  done
  [[ -z "$ROOTS" ]] && ROOTS="$HOME/Pictures"

  TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
  cat > .env << EOF
# MATRIX — generated on this Mac by friend-setup.sh
MATRIX_ENV=production
MATRIX_DATA_DIR=$DATA
MATRIX_QUARANTINE=$DATA/quarantine
MATRIX_SCAN_ROOTS=$ROOTS
MATRIX_API_HOST=127.0.0.1
MATRIX_API_PORT=8765
MATRIX_API_TOKEN=$TOKEN
MATRIX_LOG_LEVEL=INFO
MATRIX_LOG_FILE=$DATA/matrix.log
MATRIX_SCAN_WORKERS=4
MATRIX_PHASH_MAX_DISTANCE=10
MATRIX_BIND_PUBLIC=0
EOF
  echo ""
  echo "==> Created .env with a new API token for THIS computer:"
  echo "    $TOKEN"
fi

cp -f .env "$DATA/.env" 2>/dev/null || true

chmod +x setup.sh scripts/*.sh 2>/dev/null || true
chmod +x "Start MATRIX.command" 2>/dev/null || true

matrix init
matrix doctor --fix

echo ""
echo "=============================================="
echo "  Setup complete on $(whoami)@$(hostname -s)"
echo "=============================================="
echo ""
echo "Start MATRIX:"
echo "  • Double-click:  $ROOT/Start MATRIX.command"
echo "  • Or Terminal:"
echo "      cd \"$ROOT\""
echo "      source .venv/bin/activate"
echo "      matrix app"
echo ""
echo "Web UI:  http://127.0.0.1:8765/"
echo "Token:   grep MATRIX_API_TOKEN \"$ROOT/.env\""
echo ""
echo "Index photos (pick a folder on THIS Mac):"
echo "  matrix scan --root \"\$HOME/Pictures\""
echo "  matrix dedup"
echo "  matrix ui"
echo ""