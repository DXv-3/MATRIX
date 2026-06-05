#!/bin/bash
# One script to paste/run on a new Mac. No decorative lines — safe for Terminal.
set -euo pipefail
cd "${1:-$HOME/MATRIX}"
if [[ ! -f pyproject.toml ]]; then
  if [[ -f "$HOME/Downloads/MATRIX/pyproject.toml" ]]; then
    cd "$HOME/Downloads/MATRIX"
  else
    echo "Put the MATRIX folder in ~/MATRIX or ~/Downloads/MATRIX, then run:"
    echo "  bash RUN_ON_NEW_MAC.sh"
    exit 1
  fi
fi
rm -rf .venv
bash scripts/friend-setup.sh
source .venv/bin/activate
matrix app