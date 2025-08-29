#!/bin/bash

# VPN+RDP Manager Debian Package Builder
# For Linux Mint 22.1 and Ubuntu 24.04

set -e

# Package information
PACKAGE_NAME="vpnrdp"
VERSION="1.0.0"
ARCH="all"
MAINTAINER="VPN+RDP Manager Contributors"
DESCRIPTION="Combined VPN (OpenVPN3/WireGuard) and RDP connection manager with one-click connect"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}VPN+RDP Manager Debian Package Builder${NC}"
echo -e "${GREEN}Version: ${VERSION}${NC}"
echo -e "${GREEN}========================================${NC}"

# Check if running as root
if [ "$EUID" -eq 0 ]; then 
   echo -e "${RED}Please do not run this script as root${NC}"
   exit 1
fi

# Clean up any previous build
echo -e "${YELLOW}Cleaning up previous builds...${NC}"
rm -rf debian-build
rm -f ${PACKAGE_NAME}_${VERSION}_${ARCH}.deb

# Create debian package structure
echo -e "${YELLOW}Creating package structure...${NC}"
mkdir -p debian-build/DEBIAN
mkdir -p debian-build/usr/bin
mkdir -p debian-build/usr/share/applications
mkdir -p debian-build/usr/share/doc/${PACKAGE_NAME}
mkdir -p debian-build/usr/share/icons/hicolor/48x48/apps
mkdir -p debian-build/usr/share/icons/hicolor/scalable/apps
mkdir -p debian-build/etc/apt/sources.list.d
mkdir -p debian-build/etc/apt/keyrings

# Copy the main application
echo -e "${YELLOW}Copying application files...${NC}"
cp vpnrdp.py debian-build/usr/bin/vpnrdp
chmod 755 debian-build/usr/bin/vpnrdp

# Create desktop entry
echo -e "${YELLOW}Creating desktop entry...${NC}"
cat > debian-build/usr/share/applications/vpnrdp.desktop << EOF
[Desktop Entry]
Version=1.0
Type=Application
Name=VPN+RDP Manager
Comment=Connect to VPN then RDP with one click
Exec=/usr/bin/vpnrdp
Icon=network-workgroup
Terminal=false
Categories=Network;RemoteAccess;
Keywords=vpn;rdp;remote;desktop;openvpn;freerdp;
StartupNotify=true
EOF

# Copy documentation
echo -e "${YELLOW}Copying documentation...${NC}"
cp README.md debian-build/usr/share/doc/${PACKAGE_NAME}/
cat > debian-build/usr/share/doc/${PACKAGE_NAME}/copyright << EOF
Format: https://www.debian.org/doc/packaging-manuals/copyright-format/1.0/
Upstream-Name: vpnrdp
Source: https://github.com/vpnrdp/vpnrdp

Files: *
Copyright: 2024 VPN+RDP Manager Contributors
License: MIT
 Permission is hereby granted, free of charge, to any person obtaining a copy
 of this software and associated documentation files (the "Software"), to deal
 in the Software without restriction, including without limitation the rights
 to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
 copies of the Software, and to permit persons to whom the Software is
 furnished to do so, subject to the following conditions:
 .
 The above copyright notice and this permission notice shall be included in all
 copies or substantial portions of the Software.
 .
 THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
 IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
 FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
 AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
 LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
 OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
 SOFTWARE.
EOF

# Create changelog
cat > debian-build/usr/share/doc/${PACKAGE_NAME}/changelog << EOF
vpnrdp (${VERSION}) stable; urgency=medium

  * Initial release
  * Combined VPN and RDP connection manager
  * One-click connect to VPN then RDP
  * Advanced RDP options support
  * Real-time traffic monitoring
  * Secure password storage with keyring support

 -- ${MAINTAINER}  $(date -R)
EOF
gzip -9 debian-build/usr/share/doc/${PACKAGE_NAME}/changelog

# Create control file
echo -e "${YELLOW}Creating control file...${NC}"
cat > debian-build/DEBIAN/control << EOF
Package: ${PACKAGE_NAME}
Version: ${VERSION}
Section: net
Priority: optional
Architecture: ${ARCH}
Depends: python3 (>= 3.10), 
         python3-gi,
         python3-gi-cairo,
         gir1.2-gtk-3.0,
         freerdp2-x11 | freerdp3-x11 | freerdp-x11,
         python3-keyring,
         python3-secretstorage,
         gnome-keyring,
         curl,
         gpg,
         apt-transport-https
Recommends: openvpn3, wireguard
Suggests: wireguard-tools
Maintainer: ${MAINTAINER}
Description: ${DESCRIPTION}
 VPN+RDP Manager is a combined VPN and RDP connection manager for Linux
 that allows you to save connection profiles and connect to both VPN
 and RDP with a single click.
 .
 Features:
  - Support for both OpenVPN3 and WireGuard VPN protocols
  - One-click connection to VPN then RDP
  - Save multiple connection profiles with different VPN types
  - Advanced RDP options (multi-monitor, audio, performance settings)
  - Real-time VPN traffic monitoring with charts for both protocols
  - Secure password storage using system keyring
  - Connection status tracking
  - Built-in VPN config import tools
Homepage: https://github.com/vpnrdp/vpnrdp
EOF

# Create postinst script for OpenVPN3 repository setup
echo -e "${YELLOW}Creating post-installation script...${NC}"
cat > debian-build/DEBIAN/postinst << 'EOF'
#!/bin/bash
set -e

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

# Function to setup OpenVPN3 repository
setup_openvpn3_repo() {
    echo "Setting up OpenVPN3 repository..."
    
    # Detect distribution
    DIST_CODENAME=$(get_ubuntu_codename)
    ARCH=$(dpkg --print-architecture)
    
    # Create keyrings directory if it doesn't exist
    mkdir -p /etc/apt/keyrings
    
    # Download and install OpenVPN repository key
    echo "Downloading OpenVPN repository key..."
    if command -v curl >/dev/null 2>&1; then
        curl -fsSL https://packages.openvpn.net/packages-repo.gpg -o /etc/apt/keyrings/openvpn.asc 2>/dev/null || \
        curl -fsSL https://swupdate.openvpn.net/repos/openvpn-repo-pkg-key.pub -o /etc/apt/keyrings/openvpn.asc 2>/dev/null || \
        echo "Warning: Could not download OpenVPN repository key"
    elif command -v wget >/dev/null 2>&1; then
        wget -qO /etc/apt/keyrings/openvpn.asc https://packages.openvpn.net/packages-repo.gpg 2>/dev/null || \
        wget -qO /etc/apt/keyrings/openvpn.asc https://swupdate.openvpn.net/repos/openvpn-repo-pkg-key.pub 2>/dev/null || \
        echo "Warning: Could not download OpenVPN repository key"
    fi
    
    # Add OpenVPN3 repository if key was downloaded successfully
    if [ -f /etc/apt/keyrings/openvpn.asc ]; then
        echo "deb [arch=${ARCH} signed-by=/etc/apt/keyrings/openvpn.asc] https://packages.openvpn.net/openvpn3/debian ${DIST_CODENAME} main" > /etc/apt/sources.list.d/openvpn3.list
        
        echo "Updating package lists..."
        apt-get update || true
        
        # Try to install OpenVPN3 if not already installed
        if ! command -v openvpn3 >/dev/null 2>&1; then
            echo "Installing OpenVPN3..."
            apt-get install -y openvpn3 || echo "Note: OpenVPN3 installation failed. You may need to install it manually."
        fi
    else
        echo "Note: Could not set up OpenVPN3 repository. You may need to install OpenVPN3 manually."
    fi
}

# Main post-installation tasks
case "$1" in
    configure)
        # Check and install VPN clients
        # Install WireGuard if not present
        if ! command -v wg >/dev/null 2>&1 || ! command -v wg-quick >/dev/null 2>&1; then
            echo "Installing WireGuard..."
            apt-get install -y wireguard || echo "Note: WireGuard installation failed. You may need to install it manually."
        else
            echo "WireGuard is already installed."
        fi
        
        # Only setup OpenVPN3 repo if openvpn3 is not installed
        if ! command -v openvpn3 >/dev/null 2>&1; then
            setup_openvpn3_repo
        else
            echo "OpenVPN3 is already installed."
        fi
        
        # Create config directory with proper permissions
        mkdir -p /home/$SUDO_USER/.config/vpnrdp 2>/dev/null || true
        if [ -n "$SUDO_USER" ]; then
            chown -R $SUDO_USER:$SUDO_USER /home/$SUDO_USER/.config/vpnrdp 2>/dev/null || true
        fi
        
        echo ""
        echo "=========================================="
        echo "VPN+RDP Manager has been installed!"
        echo "=========================================="
        echo ""
        echo "You can launch it from your application menu"
        echo "or by running 'vpnrdp' in a terminal."
        echo ""
        
        # Check what VPN clients are available
        if ! command -v wg >/dev/null 2>&1 || ! command -v wg-quick >/dev/null 2>&1; then
            echo "NOTE: WireGuard is not installed. To install it manually, run:"
            echo "  sudo apt update && sudo apt install wireguard"
            echo ""
        fi
        
        if ! command -v openvpn3 >/dev/null 2>&1; then
            echo "NOTE: OpenVPN3 is not installed. To install it manually, run:"
            echo "  sudo apt update && sudo apt install openvpn3"
            echo ""
        fi
        
        echo "Before using VPN+RDP Manager:"
        echo "1. Import your VPN configurations:"
        echo "   For OpenVPN3:"
        echo "     openvpn3 config-import --config /path/to/your/config.ovpn"
        echo "   For WireGuard:"
        echo "     Copy your .conf files to ~/.config/wireguard/ or /etc/wireguard/"
        echo ""
        echo "2. Launch VPN+RDP Manager and create connection profiles"
        echo "   - Choose between OpenVPN3 and WireGuard for each connection"
        echo ""
        ;;
    
    abort-upgrade|abort-remove|abort-deconfigure)
        ;;
    
    *)
        echo "postinst called with unknown argument: $1" >&2
        exit 1
        ;;
esac

exit 0
EOF
chmod 755 debian-build/DEBIAN/postinst

# Create prerm script to clean up
echo -e "${YELLOW}Creating pre-removal script...${NC}"
cat > debian-build/DEBIAN/prerm << 'EOF'
#!/bin/bash
set -e

case "$1" in
    remove|purge)
        # Kill any running instances
        pkill -f "python.*vpnrdp" 2>/dev/null || true
        ;;
    
    upgrade|deconfigure)
        ;;
    
    *)
        echo "prerm called with unknown argument: $1" >&2
        exit 1
        ;;
esac

exit 0
EOF
chmod 755 debian-build/DEBIAN/prerm

# Create postrm script for cleanup
echo -e "${YELLOW}Creating post-removal script...${NC}"
cat > debian-build/DEBIAN/postrm << 'EOF'
#!/bin/bash
set -e

case "$1" in
    purge)
        # Remove OpenVPN3 repository if no other packages need it
        if [ -f /etc/apt/sources.list.d/openvpn3.list ]; then
            if ! dpkg -l | grep -q "openvpn3"; then
                rm -f /etc/apt/sources.list.d/openvpn3.list
                rm -f /etc/apt/keyrings/openvpn.asc
                apt-get update || true
            fi
        fi
        ;;
    
    remove|upgrade|failed-upgrade|abort-install|abort-upgrade|disappear)
        ;;
    
    *)
        echo "postrm called with unknown argument: $1" >&2
        exit 1
        ;;
esac

exit 0
EOF
chmod 755 debian-build/DEBIAN/postrm

# Calculate installed size
INSTALLED_SIZE=$(du -sk debian-build | cut -f1)
sed -i "s/^Architecture: ${ARCH}$/Architecture: ${ARCH}\nInstalled-Size: ${INSTALLED_SIZE}/" debian-build/DEBIAN/control

# Build the package
echo -e "${YELLOW}Building debian package...${NC}"
dpkg-deb --build debian-build ${PACKAGE_NAME}_${VERSION}_${ARCH}.deb

# Clean up build directory
echo -e "${YELLOW}Cleaning up...${NC}"
rm -rf debian-build

# Final message
if [ -f ${PACKAGE_NAME}_${VERSION}_${ARCH}.deb ]; then
    echo -e "${GREEN}========================================${NC}"
    echo -e "${GREEN}Package built successfully!${NC}"
    echo -e "${GREEN}Package: ${PACKAGE_NAME}_${VERSION}_${ARCH}.deb${NC}"
    echo -e "${GREEN}========================================${NC}"
    echo ""
    echo "To install the package, run:"
    echo "  sudo dpkg -i ${PACKAGE_NAME}_${VERSION}_${ARCH}.deb"
    echo "  sudo apt-get install -f  # To resolve any missing dependencies"
    echo ""
    echo "Or install with apt to automatically handle dependencies:"
    echo "  sudo apt install ./${PACKAGE_NAME}_${VERSION}_${ARCH}.deb"
else
    echo -e "${RED}Package build failed!${NC}"
    exit 1
fi