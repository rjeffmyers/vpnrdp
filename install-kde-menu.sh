#!/bin/bash

# Install VPN+RDP Manager into the current user's KDE application menu.

set -e

APP_DIR="${HOME}/.local/share/vpnrdp"
BIN_DIR="${HOME}/.local/bin"
DESKTOP_DIR="${HOME}/.local/share/applications"
DESKTOP_FILE="${DESKTOP_DIR}/vpnrdp.desktop"
BIN_FILE="${BIN_DIR}/vpnrdp"

echo "Installing VPN+RDP Manager for user: ${USER}"

mkdir -p "${APP_DIR}" "${BIN_DIR}" "${DESKTOP_DIR}"

install -m 755 vpnrdp.py "${APP_DIR}/vpnrdp.py"
install -m 644 README.md "${APP_DIR}/README.md" 2>/dev/null || true

cat > "${BIN_FILE}" << EOF
#!/bin/sh
exec python "${APP_DIR}/vpnrdp.py" "\$@"
EOF
chmod 755 "${BIN_FILE}"

cat > "${DESKTOP_FILE}" << EOF
[Desktop Entry]
Version=1.0
Type=Application
Name=VPN+RDP Manager
Comment=Connect to VPN then RDP with one click
Exec=${BIN_FILE}
Icon=network-vpn
Terminal=false
Categories=Network;RemoteAccess;
Keywords=vpn;rdp;remote;desktop;openvpn;freerdp;
StartupNotify=true
EOF

chmod 644 "${DESKTOP_FILE}"

if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "${DESKTOP_DIR}" 2>/dev/null || true
fi

if command -v kbuildsycoca6 >/dev/null 2>&1; then
    kbuildsycoca6 --noincremental >/dev/null 2>&1 || true
elif command -v kbuildsycoca5 >/dev/null 2>&1; then
    kbuildsycoca5 --noincremental >/dev/null 2>&1 || true
fi

echo "Installed:"
echo "  ${BIN_FILE}"
echo "  ${DESKTOP_FILE}"
echo ""
echo "Open the KDE application launcher and search for: VPN+RDP Manager"
