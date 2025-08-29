#!/bin/bash

# VPN+RDP Manager Direct Installer
# For Linux Mint 22.1 and Ubuntu 24.04

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}VPN+RDP Manager Installer${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# Check if running as root
if [ "$EUID" -ne 0 ]; then 
   echo -e "${RED}This installer must be run as root (use sudo)${NC}"
   exit 1
fi

# Function to detect Ubuntu base version
get_ubuntu_codename() {
    if [ -f /etc/os-release ]; then
        . /etc/os-release
        
        # For Linux Mint, map to Ubuntu base
        if [[ "$NAME" == *"Linux Mint"* ]]; then
            case "$VERSION_ID" in
                "22"|"22."*) echo "noble" ;;  # Ubuntu 24.04
                "21"|"21."*) echo "jammy" ;;  # Ubuntu 22.04
                "20"|"20."*) echo "focal" ;;  # Ubuntu 20.04
                *) echo "noble" ;;  # Default to latest
            esac
        # For Ubuntu, use the codename directly
        elif [[ "$NAME" == *"Ubuntu"* ]]; then
            echo "${VERSION_CODENAME:-noble}"
        else
            echo "noble"  # Default
        fi
    else
        echo "noble"  # Default
    fi
}

# Step 1: Install basic dependencies
echo -e "${YELLOW}Installing basic dependencies...${NC}"
apt-get update
apt-get install -y \
    python3 \
    python3-gi \
    python3-gi-cairo \
    gir1.2-gtk-3.0 \
    curl \
    gpg \
    apt-transport-https \
    python3-keyring \
    python3-secretstorage \
    gnome-keyring

# Step 2: Install FreeRDP
echo -e "${YELLOW}Installing FreeRDP...${NC}"
apt-get install -y freerdp2-x11 || apt-get install -y freerdp3-x11 || apt-get install -y freerdp-x11

# Step 3: Install VPN clients
echo -e "${YELLOW}Installing VPN clients...${NC}"

# Install WireGuard (usually available in standard repos)
echo "Installing WireGuard..."
apt-get install -y wireguard || {
    echo -e "${YELLOW}WireGuard installation failed or not available${NC}"
}

# Setup OpenVPN3 repository
echo -e "${YELLOW}Setting up OpenVPN3 repository...${NC}"

DIST_CODENAME=$(get_ubuntu_codename)
ARCH=$(dpkg --print-architecture)

echo "Detected distribution: $DIST_CODENAME ($ARCH)"

# Create keyrings directory
mkdir -p /etc/apt/keyrings

# Download OpenVPN repository key
echo "Downloading OpenVPN repository key..."
curl -fsSL https://packages.openvpn.net/packages-repo.gpg -o /etc/apt/keyrings/openvpn.asc 2>/dev/null || \
curl -fsSL https://swupdate.openvpn.net/repos/openvpn-repo-pkg-key.pub -o /etc/apt/keyrings/openvpn.asc 2>/dev/null || \
{
    echo -e "${YELLOW}Warning: Could not download OpenVPN repository key${NC}"
    echo "OpenVPN3 may need to be installed manually later"
}

# Add OpenVPN3 repository
if [ -f /etc/apt/keyrings/openvpn.asc ]; then
    echo "deb [arch=${ARCH} signed-by=/etc/apt/keyrings/openvpn.asc] https://packages.openvpn.net/openvpn3/debian ${DIST_CODENAME} main" > /etc/apt/sources.list.d/openvpn3.list
    
    echo "Updating package lists..."
    apt-get update
    
    # Install OpenVPN3
    echo -e "${YELLOW}Installing OpenVPN3...${NC}"
    apt-get install -y openvpn3 || {
        echo -e "${YELLOW}OpenVPN3 installation failed${NC}"
        echo "OpenVPN3 may need to be installed manually"
    }
else
    echo -e "${YELLOW}Could not setup OpenVPN3 repository${NC}"
fi

# Step 4: Install VPN+RDP Manager
echo -e "${YELLOW}Installing VPN+RDP Manager...${NC}"

# Create directories
mkdir -p /usr/local/bin
mkdir -p /usr/share/applications
mkdir -p /usr/share/doc/vpnrdp

# Copy main application
cp vpnrdp.py /usr/local/bin/vpnrdp
chmod 755 /usr/local/bin/vpnrdp

# Create desktop entry
cat > /usr/share/applications/vpnrdp.desktop << EOF
[Desktop Entry]
Version=1.0
Type=Application
Name=VPN+RDP Manager
Comment=Connect to VPN then RDP with one click
Exec=/usr/local/bin/vpnrdp
Icon=network-workgroup
Terminal=false
Categories=Network;RemoteAccess;
Keywords=vpn;rdp;remote;desktop;openvpn;freerdp;
StartupNotify=true
EOF

# Copy documentation
cp README.md /usr/share/doc/vpnrdp/ 2>/dev/null || true

# Create config directory for the user who ran sudo
if [ -n "$SUDO_USER" ]; then
    USER_HOME=$(getent passwd $SUDO_USER | cut -d: -f6)
    mkdir -p $USER_HOME/.config/vpnrdp
    chown -R $SUDO_USER:$SUDO_USER $USER_HOME/.config/vpnrdp
fi

# Update desktop database
update-desktop-database 2>/dev/null || true

# Final checks
echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}Installation Complete!${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""

# Check what was installed
if command -v wg >/dev/null 2>&1 && command -v wg-quick >/dev/null 2>&1; then
    echo -e "${GREEN}✓${NC} WireGuard is installed"
else
    echo -e "${YELLOW}⚠${NC} WireGuard is not installed. To install manually:"
    echo "    sudo apt update && sudo apt install wireguard"
fi

if command -v openvpn3 >/dev/null 2>&1; then
    echo -e "${GREEN}✓${NC} OpenVPN3 is installed"
else
    echo -e "${YELLOW}⚠${NC} OpenVPN3 is not installed. To install manually:"
    echo "    Follow instructions at: https://openvpn.net/cloud-docs/openvpn-3-client-for-linux/"
fi

if command -v xfreerdp >/dev/null 2>&1 || command -v xfreerdp3 >/dev/null 2>&1; then
    echo -e "${GREEN}✓${NC} FreeRDP is installed"
else
    echo -e "${YELLOW}⚠${NC} FreeRDP is not installed"
fi

if [ -f /usr/local/bin/vpnrdp ]; then
    echo -e "${GREEN}✓${NC} VPN+RDP Manager is installed"
else
    echo -e "${RED}✗${NC} VPN+RDP Manager installation failed"
fi

echo ""
echo "Next steps:"
echo "1. Import your VPN configurations:"
echo "   For OpenVPN3:"
echo "     openvpn3 config-import --config /path/to/your/config.ovpn"
echo "   For WireGuard:"
echo "     Copy your .conf files to ~/.config/wireguard/ or /etc/wireguard/"
echo ""
echo "2. Launch VPN+RDP Manager:"
echo "   - From your application menu, or"
echo "   - Run 'vpnrdp' in a terminal"
echo ""
echo "3. Create connection profiles for your VPN+RDP combinations"
echo "   - Choose between OpenVPN3 and WireGuard for each connection"
echo ""