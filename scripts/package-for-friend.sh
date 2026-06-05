#!/usr/bin/env bash
# Build a zip you can AirDrop — no broken venv, no secrets from your machine.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
OUT="${1:-$HOME/Desktop/MATRIX-for-friend.zip}"

echo "==> Packaging MATRIX for sharing"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

rsync -a \
  --exclude '.venv' \
  --exclude '.env' \
  --exclude '__pycache__' \
  --exclude '*.pyc' \
  --exclude '.git' \
  --exclude '.DS_Store' \
  --exclude 'matrix_archive.egg-info' \
  --exclude '.pytest_cache' \
  "$ROOT/" "$TMP/MATRIX/"

chmod +x "$TMP/MATRIX/setup.sh" "$TMP/MATRIX/scripts/"*.sh "$TMP/MATRIX/Start MATRIX.command" 2>/dev/null || true

(
  cd "$TMP"
  zip -r "$OUT" MATRIX -x "*.DS_Store"
)

echo ""
echo "Created: $OUT"
echo "AirDrop or send this zip. Your friend should:"
echo "  1. Unzip to Downloads (or Desktop)"
echo "  2. Double-click  MATRIX/Start MATRIX.command"
echo "     — or in Terminal:  cd ~/Downloads/MATRIX && ./scripts/friend-setup.sh"
echo ""