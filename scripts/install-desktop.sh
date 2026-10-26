#!/usr/bin/env bash
# Installs dogear as a user service (starts at login, restarts on failure) and adds a launcher
# to the application menu. Linux with systemd. Remove again with: scripts/install-desktop.sh --remove
set -euo pipefail
HERE="$(cd "$(dirname "$0")/.." && pwd)"
UNIT_DIR="$HOME/.config/systemd/user"
APP_DIR="$HOME/.local/share/applications"
ICON_DIR="$HOME/.local/share/icons/hicolor/scalable/apps"
PORT="${DOGEAR_PORT:-7870}"

if [[ "${1:-}" == "--remove" ]]; then
  systemctl --user disable --now dogear.service 2>/dev/null || true
  rm -f "$UNIT_DIR/dogear.service" "$APP_DIR/dogear.desktop" "$ICON_DIR/dogear.svg"
  systemctl --user daemon-reload
  echo "dogear service and launcher removed."
  exit 0
fi

command -v uv >/dev/null || { echo "uv is required (https://docs.astral.sh/uv/)"; exit 1; }
mkdir -p "$UNIT_DIR" "$APP_DIR" "$ICON_DIR"

cat > "$UNIT_DIR/dogear.service" <<EOF
[Unit]
Description=dogear coding agent
After=network.target

[Service]
WorkingDirectory=$HERE
ExecStart=$(command -v uv) run python -m dogear --port $PORT
Restart=on-failure
RestartSec=3

[Install]
WantedBy=default.target
EOF

cp "$HERE/web/logo.svg" "$ICON_DIR/dogear.svg"
cat > "$APP_DIR/dogear.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=dogear
Comment=Local coding agent with a live workspace
Exec=xdg-open http://127.0.0.1:$PORT
Icon=dogear
Terminal=false
Categories=Development;
EOF

systemctl --user daemon-reload
systemctl --user enable --now dogear.service
echo "dogear runs as a user service on http://127.0.0.1:$PORT and starts at login."
echo "Logs: journalctl --user -u dogear -f"
