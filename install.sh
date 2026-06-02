#!/bin/bash

# VPN+RDP Manager Direct Installer
# Supports Arch/CachyOS and Debian/Ubuntu based distributions.

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

INSTALL_TARGET="/usr/local/bin/vpnrdp"
MODE="auto"   # auto | update | reinstall

usage() {
    cat <<EOF
Usage: sudo ./install.sh [OPTION]

  (no option)   Auto: fresh install runs dependency setup; if already
                installed, updates the app files only.
  --update      Update app files only, always skip dependency setup.
  --reinstall   Reinstall, always run dependency setup (incl. system update).
  -h, --help    Show this help.
EOF
}

while [ $# -gt 0 ]; do
    case "$1" in
        --update)    MODE="update" ;;
        --reinstall) MODE="reinstall" ;;
        -h|--help)   usage; exit 0 ;;
        *) echo -e "${RED}Unknown option: $1${NC}"; usage; exit 1 ;;
    esac
    shift
done

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}VPN+RDP Manager Installer${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

if [ "$EUID" -ne 0 ]; then
   echo -e "${RED}This installer must be run as root (use sudo)${NC}"
   exit 1
fi

# Detect an existing installation and decide whether to run dependency setup.
# Covers both the system install (this script) and the per-user KDE install
# (install-kde-menu.sh -> ~/.local/share/vpnrdp/vpnrdp.py).
ALREADY_INSTALLED=false
[ -f "$INSTALL_TARGET" ] && ALREADY_INSTALLED=true

USER_APP=""
if [ -n "$SUDO_USER" ]; then
    USER_HOME=$(getent passwd "$SUDO_USER" | cut -d: -f6)
    if [ -f "$USER_HOME/.local/share/vpnrdp/vpnrdp.py" ]; then
        USER_APP="$USER_HOME/.local/share/vpnrdp/vpnrdp.py"
        ALREADY_INSTALLED=true
    fi
fi

RUN_DEPS=true
case "$MODE" in
    reinstall) RUN_DEPS=true ;;
    update)    RUN_DEPS=false ;;
    auto)      if $ALREADY_INSTALLED; then RUN_DEPS=false; else RUN_DEPS=true; fi ;;
esac

if $ALREADY_INSTALLED; then
    echo -e "${YELLOW}Existing installation detected at ${INSTALL_TARGET} — updating application files.${NC}"
    if ! $RUN_DEPS; then
        echo -e "${YELLOW}Skipping dependency setup (run with --reinstall to force it).${NC}"
    fi
else
    echo -e "${GREEN}Performing a fresh installation.${NC}"
fi
echo ""

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

if $RUN_DEPS; then
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
fi

if $ALREADY_INSTALLED; then
    echo -e "${YELLOW}Updating VPN+RDP Manager...${NC}"
else
    echo -e "${YELLOW}Installing VPN+RDP Manager...${NC}"
fi

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

    # Also refresh a per-user KDE install (install-kde-menu.sh), which is what
    # the application menu launches via ~/.local/bin/vpnrdp.
    if [ -n "$USER_APP" ]; then
        echo -e "${YELLOW}Updating per-user install at ${USER_APP}${NC}"
        install -m 755 vpnrdp.py "$USER_APP"
        chown "$SUDO_USER:" "$USER_APP"
        install -m 644 README.md "$(dirname "$USER_APP")/README.md" 2>/dev/null \
            && chown "$SUDO_USER:" "$(dirname "$USER_APP")/README.md" || true
    fi
fi

update-desktop-database 2>/dev/null || true

echo ""
echo -e "${GREEN}========================================${NC}"
if $ALREADY_INSTALLED; then
    echo -e "${GREEN}Update Complete!${NC}"
else
    echo -e "${GREEN}Installation Complete!${NC}"
fi
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
