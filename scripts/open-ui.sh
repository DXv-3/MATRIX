#!/usr/bin/env bash
# Open MATRIX Web UI in a specific browser.
# Usage:
#   ./scripts/open-ui.sh
#   ./scripts/open-ui.sh "Google Chrome"
#   ./scripts/open-ui.sh Firefox
#   MATRIX_BROWSER="Brave Browser" ./scripts/open-ui.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
source .venv/bin/activate
set -a && source .env && set +a

BROWSER="${1:-${MATRIX_BROWSER:-}}"
URL=$(python3 -c "
from matrix.macos_app import build_ui_url
from matrix.settings import settings
c = settings()
print(build_ui_url(c.api_host, c.api_port))
")

if [[ -n "$BROWSER" ]]; then
  open -a "$BROWSER" "$URL"
  echo "Opened in: $BROWSER"
else
  open "$URL"
  echo "Opened in default browser"
fi
echo "$URL"