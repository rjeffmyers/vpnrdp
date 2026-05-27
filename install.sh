#!/bin/bash

# VPN+RDP Manager Direct Installer
# Supports Arch/CachyOS and Debian/Ubuntu based distributions.

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}VPN+RDP Manager Installer${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

if [ "$EUID" -ne 0 ]; then
   echo -e "${RED}This installer must be run as root (use sudo)${NC}"
   exit 1
fi

detect_os_family() {
    local os_id=""
    local os_like=""

    if [ -f /etc/os-release ]; then
        . /etc/os-release
        os_id="${ID,,}"
        os_like="${ID_LIKE,,}"
    fi

    if [[ " $os_id $os_like " == *" arch "* ]] || [[ "$os_id" == "cachyos" ]] || command -v pacman >/dev/null 2>&1; then
        echo "arch"
    elif [[ " $os_id $os_like " == *" debian "* ]] || [[ " $os_id $os_like " == *" ubuntu "* ]] || command -v apt-get >/dev/null 2>&1; then
        echo "debian"
    else
        echo "unknown"
    fi
}

install_arch_dependencies() {
    echo -e "${YELLOW}Installing Arch/CachyOS dependencies...${NC}"
    pacman -Syu --needed --noconfirm \
        python \
        python-gobject \
        gtk3 \
        freerdp \
        networkmanager \
        networkmanager-openvpn \
        openvpn \
        wireguard-tools

    echo -e "${YELLOW}Installing optional Arch/CachyOS dependencies...${NC}"
    pacman -S --needed --noconfirm \
        python-keyring \
        python-secretstorage \
        kwallet \
        libayatana-appindicator || {
            echo -e "${YELLOW}Some optional packages failed to install; continuing with app install.${NC}"
        }
}

get_ubuntu_codename() {
    if [ -f /etc/os-release ]; then
        . /etc/os-release

        if [[ "$NAME" == *"Linux Mint"* ]]; then
            case "$VERSION_ID" in
                "22"|"22."*) echo "noble" ;;
                "21"|"21."*) echo "jammy" ;;
                "20"|"20."*) echo "focal" ;;
                *) echo "noble" ;;
            esac
        elif [[ "$NAME" == *"Ubuntu"* ]]; then
            echo "${VERSION_CODENAME:-noble}"
        else
            echo "noble"
        fi
    else
        echo "noble"
    fi
}

install_debian_dependencies() {
    echo -e "${YELLOW}Installing Debian/Ubuntu dependencies...${NC}"
    apt-get update
    apt-get install -y \
        python3 \
        python3-gi \
        python3-gi-cairo \
        gir1.2-gtk-3.0 \
        gir1.2-ayatanaappindicator3-0.1 \
        curl \
        gpg \
        apt-transport-https \
        python3-keyring \
        python3-secretstorage \
        gnome-keyring \
        network-manager-openvpn \
        wireguard || true

    echo -e "${YELLOW}Installing FreeRDP...${NC}"
    apt-get install -y freerdp2-x11 || apt-get install -y freerdp3-x11 || apt-get install -y freerdp-x11

    echo -e "${YELLOW}Setting up OpenVPN3 repository...${NC}"
    local dist_codename
    local arch
    dist_codename=$(get_ubuntu_codename)
    arch=$(dpkg --print-architecture)

    mkdir -p /etc/apt/keyrings
    curl -fsSL https://packages.openvpn.net/packages-repo.gpg -o /etc/apt/keyrings/openvpn.asc 2>/dev/null || \
    curl -fsSL https://swupdate.openvpn.net/repos/openvpn-repo-pkg-key.pub -o /etc/apt/keyrings/openvpn.asc 2>/dev/null || true

    if [ -f /etc/apt/keyrings/openvpn.asc ]; then
        echo "deb [arch=${arch} signed-by=/etc/apt/keyrings/openvpn.asc] https://packages.openvpn.net/openvpn3/debian ${dist_codename} main" > /etc/apt/sources.list.d/openvpn3.list
        apt-get update
        apt-get install -y openvpn3 || echo -e "${YELLOW}OpenVPN3 install failed; NetworkManager OpenVPN can still be used.${NC}"
    fi
}

OS_FAMILY=$(detect_os_family)
echo "Detected OS family: $OS_FAMILY"

case "$OS_FAMILY" in
    arch)
        install_arch_dependencies
        ;;
    debian)
        install_debian_dependencies
        ;;
    *)
        echo -e "${YELLOW}Unknown OS family. Skipping dependency installation.${NC}"
        echo "Install Python GTK bindings, FreeRDP, and a VPN backend manually."
        ;;
esac

echo -e "${YELLOW}Installing VPN+RDP Manager...${NC}"

mkdir -p /usr/local/bin
mkdir -p /usr/share/applications
mkdir -p /usr/share/doc/vpnrdp

cp vpnrdp.py /usr/local/bin/vpnrdp
chmod 755 /usr/local/bin/vpnrdp

install -m 644 vpnrdp.desktop /usr/share/applications/vpnrdp.desktop
sed -i 's|^Exec=.*|Exec=/usr/local/bin/vpnrdp|' /usr/share/applications/vpnrdp.desktop

cp README.md /usr/share/doc/vpnrdp/ 2>/dev/null || true

if [ -n "$SUDO_USER" ]; then
    USER_HOME=$(getent passwd "$SUDO_USER" | cut -d: -f6)
    mkdir -p "$USER_HOME/.config/vpnrdp"
    chown -R "$SUDO_USER:$SUDO_USER" "$USER_HOME/.config/vpnrdp"
fi

update-desktop-database 2>/dev/null || true

echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}Installation Complete!${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""

if command -v nmcli >/dev/null 2>&1; then
    echo -e "${GREEN}OK${NC} NetworkManager is installed"
else
    echo -e "${YELLOW}WARN${NC} NetworkManager is not installed"
fi

if command -v openvpn3 >/dev/null 2>&1; then
    echo -e "${GREEN}OK${NC} OpenVPN3 is installed"
else
    echo -e "${YELLOW}WARN${NC} OpenVPN3 is not installed; use NetworkManager OpenVPN on Arch/CachyOS"
fi

if command -v wg >/dev/null 2>&1 && command -v wg-quick >/dev/null 2>&1; then
    echo -e "${GREEN}OK${NC} WireGuard is installed"
else
    echo -e "${YELLOW}WARN${NC} WireGuard is not installed"
fi

if command -v xfreerdp >/dev/null 2>&1 || command -v xfreerdp3 >/dev/null 2>&1; then
    echo -e "${GREEN}OK${NC} FreeRDP is installed"
else
    echo -e "${YELLOW}WARN${NC} FreeRDP is not installed"
fi

echo ""
echo "Next steps:"
echo "1. On CachyOS/KDE, import or configure your OpenVPN profile in NetworkManager."
echo "2. Launch VPN+RDP Manager from the application menu or run 'vpnrdp'."
echo "3. Create a connection and choose NetworkManager as the VPN type."
echo ""
