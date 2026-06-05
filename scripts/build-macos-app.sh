#!/usr/bin/env bash
# Build MATRIX.app — macOS standalone launcher (opens Web UI + API server)
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DEST="${MATRIX_APP_DEST:-$HOME/Applications}"
APP="$DEST/MATRIX.app"
VENV="$ROOT/.venv/bin/python"

if [[ ! -x "$VENV" ]]; then
  echo "Run ./setup.sh first to create .venv"
  exit 1
fi

mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"

cat > "$APP/Contents/Info.plist" << 'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleExecutable</key>
  <string>matrix-launcher</string>
  <key>CFBundleIdentifier</key>
  <string>com.matrix.archive</string>
  <key>CFBundleName</key>
  <string>MATRIX</string>
  <key>CFBundleVersion</key>
  <string>1.0.0</string>
  <key>CFBundlePackageType</key>
  <string>APPL</string>
  <key>LSMinimumSystemVersion</key>
  <string>12.0</string>
  <key>NSHighResolutionCapable</key>
  <true/>
</dict>
</plist>
PLIST

cat > "$APP/Contents/MacOS/matrix-launcher" << LAUNCHER
#!/bin/bash
set -e
ROOT="$ROOT"
cd "\$ROOT"
if [[ -f "\$ROOT/.env" ]]; then
  set -a
  source "\$ROOT/.env"
  set +a
fi
export MATRIX_DATA_DIR="\${MATRIX_DATA_DIR:-\$HOME/.matrix}"
source "\$ROOT/.venv/bin/activate"
exec "\$ROOT/.venv/bin/python" -m matrix.macos_launcher
LAUNCHER

chmod +x "$APP/Contents/MacOS/matrix-launcher"

echo "Installed: $APP"
echo "Drag to Dock or open from Applications."