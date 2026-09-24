#!/bin/bash
# Build the first-party macOS menu bar app (single command, zero deps).
#   scripts/build_macos_app.sh [output-dir]
# Produces <output-dir>/gpumaid-bar.app — LSUIElement (menu bar only).
set -euo pipefail
cd "$(dirname "$0")/.."

command -v swiftc >/dev/null || { echo "swiftc not found: install Xcode Command Line Tools (xcode-select --install)" >&2; exit 1; }

OUT_DIR="${1:-build}"
BIN="$(mktemp -d)/gpumaid-bar"
swiftc -O desktop/macos/gpumaid-bar.swift -o "$BIN"

APP="$OUT_DIR/gpumaid-bar.app"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS"
cp "$BIN" "$APP/Contents/MacOS/gpumaid-bar"
cat > "$APP/Contents/Info.plist" <<'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>gpu-maid</string>
  <key>CFBundleDisplayName</key><string>gpu-maid bar</string>
  <key>CFBundleIdentifier</key><string>com.guttostudio.gpumaid-bar</string>
  <key>CFBundleExecutable</key><string>gpumaid-bar</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>0.1.0</string>
  <key>LSUIElement</key><true/>
  <key>NSHighResolutionCapable</key><true/>
  <key>NSAppTransportSecurity</key>
  <dict>
    <!-- the agent URL is user-configured and typically plain HTTP on a
         LAN / tailnet (Tailscale's CGNAT range is not "local" to ATS),
         so the bar needs a full ATS exemption -->
    <key>NSAllowsArbitraryLoads</key><true/>
  </dict>
</dict>
</plist>
EOF
codesign --force -s - "$APP" 2>/dev/null || true
echo "built: $APP"
echo "run:   open $APP"
