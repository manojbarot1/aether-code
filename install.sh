#!/usr/bin/env bash
# ==============================================================================
# Aether Code — One-Click Installation & Setup Script
# https://github.com/manojbarot1/aether-code
# ==============================================================================

set -e

echo "🔮 Installing Aether Code..."

# Check Node.js version
if ! command -v node >/dev/null 2>&1; then
  echo "❌ Error: Node.js is required but not installed."
  echo "Please install Node.js 20+ (https://nodejs.org/) and retry."
  exit 1
fi

NODE_MAJOR=$(node -v | cut -d'.' -f1 | tr -d 'v')
if [ "$NODE_MAJOR" -lt 20 ]; then
  echo "⚠️ Warning: Node.js 20 or higher is recommended (detected $(node -v))."
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN_DIR="${HOME}/.local/bin"
DESKTOP_DIR="${HOME}/.local/share/applications"

# Make binary launcher executable
chmod +x "${SCRIPT_DIR}/bin/aether-code"
chmod +x "${SCRIPT_DIR}/bin/agy-gui" 2>/dev/null || true

# Symlink to ~/.local/bin if available in PATH
mkdir -p "$BIN_DIR"
ln -sf "${SCRIPT_DIR}/bin/aether-code" "${BIN_DIR}/aether-code"
ln -sf "${SCRIPT_DIR}/bin/aether-code" "${BIN_DIR}/agy-gui" 2>/dev/null || true

# Create Desktop Entry (Linux)
if [ -d "$DESKTOP_DIR" ] || [ -n "$XDG_DATA_HOME" ]; then
  mkdir -p "$DESKTOP_DIR"
  cat << EOF > "${DESKTOP_DIR}/aether-code.desktop"
[Desktop Entry]
Version=1.0
Type=Application
Name=Aether Code
GenericName=AI Agent Console
Comment=Unified AI Agent Development Console with Liquid Glass UI
Exec=${SCRIPT_DIR}/bin/aether-code
Icon=${SCRIPT_DIR}/public/assets/icon.svg
Terminal=false
Categories=Development;IDE;
StartupWMClass=AetherCode
EOF
  chmod +x "${DESKTOP_DIR}/aether-code.desktop"
  echo "✓ Desktop application launcher registered."
fi

# Optional: Systemd user service installation
if command -v systemctl >/dev/null 2>&1; then
  SYSTEMD_DIR="${HOME}/.config/systemd/user"
  mkdir -p "$SYSTEMD_DIR"
  cat << EOF > "${SYSTEMD_DIR}/aether-code.service"
[Unit]
Description=Aether Code Server
After=network.target

[Service]
Type=simple
WorkingDirectory=${SCRIPT_DIR}
ExecStart=$(which node) ${SCRIPT_DIR}/server.js
Restart=on-failure
RestartSec=3
Environment=NODE_ENV=production
Environment=PORT=4567

[Install]
WantedBy=default.target
EOF
  systemctl --user daemon-reload 2>/dev/null || true
  systemctl --user enable --now aether-code.service 2>/dev/null || true
  echo "✓ Background systemd service configured."
fi

echo ""
echo "✨ Installation complete! You can run Aether Code using:"
echo "   aether-code          # Launches app window or server"
echo "   npm start            # Or start local server on http://localhost:4567"
echo ""
