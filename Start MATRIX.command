#!/bin/bash
# Double-click this file (in the MATRIX folder) to install-if-needed and open the Web UI.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

if [[ ! -f "$ROOT/pyproject.toml" ]]; then
  osascript -e 'display alert "MATRIX folder is incomplete" message "This folder is missing pyproject.toml. Re-download the full MATRIX zip or AirDrop the whole project folder again."'
  exit 1
fi

# shellcheck source=scripts/ensure-venv.sh
source "$ROOT/scripts/ensure-venv.sh" 2>/dev/null || true
ensure_matrix_venv 2>/dev/null || [[ ! -d "$ROOT/.venv" ]] || rm -rf "$ROOT/.venv"

if [[ ! -x "$ROOT/.venv/bin/matrix" ]]; then
  osascript -e 'display notification "First-time setup (2–5 min)…" with title "MATRIX"'
  bash "$ROOT/scripts/friend-setup.sh" || {
    osascript -e 'display alert "MATRIX setup failed" message "Open Terminal, cd to this MATRIX folder, and run: ./scripts/friend-setup.sh"'
    read -p "Press Enter to close…"
    exit 1
  }
fi

source "$ROOT/.venv/bin/activate"
set -a
[[ -f "$ROOT/.env" ]] && source "$ROOT/.env"
set +a

matrix app 2>> "$HOME/.matrix/launcher.err.log" || {
  echo "Failed to start. Try in Terminal:"
  echo "  cd \"$ROOT\""
  echo "  source .venv/bin/activate && matrix app"
  read -p "Press Enter to close…"
  exit 1
}

echo ""
echo "Web UI: http://127.0.0.1:8765/"
echo "API token is in: $ROOT/.env  (MATRIX_API_TOKEN)"
read -p "Press Enter to close…"