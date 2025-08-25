# VPN+RDP Manager

A combined VPN and RDP connection manager for Linux that allows you to connect to a VPN and then RDP with a single click.

## Features

- **One-Click Connection**: Save VPN+RDP connection profiles and connect with a single click
- **Connection Profiles**: Store multiple connection configurations with different VPN and RDP settings
- **Secure Password Storage**: Passwords can be stored securely using the system keyring
- **Status Monitoring**: Real-time status display for each connection
- **GUI Management**: Easy-to-use GTK+ interface for managing connections

## Requirements

- Python 3 with GTK+ bindings
- OpenVPN3 (`sudo apt install openvpn3`)
- FreeRDP (`sudo apt install freerdp2-x11`)
- Python keyring (optional, for secure password storage)

## Installation

1. Make sure you have the required dependencies:
```bash
sudo apt update
sudo apt install python3-gi python3-gi-cairo gir1.2-gtk-3.0
sudo apt install openvpn3 freerdp2-x11
# Optional for secure password storage:
sudo apt install python3-keyring python3-secretstorage gnome-keyring
```

2. Make the script executable:
```bash
chmod +x vpnrdp.py
```

3. Install the desktop entry (optional):
```bash
cp vpnrdp.desktop ~/.local/share/applications/
```

## Usage

1. **Launch the application**:
   - Run `./vpnrdp.py` from terminal, or
   - Launch from your application menu if you installed the desktop entry

2. **Create a new connection profile**:
   - Click "New Connection" button
   - Enter a name for your connection
   - Select your VPN configuration (must be already imported in OpenVPN3)
   - Enter VPN username
   - Enter RDP host, username, and optional domain
   - Configure display settings (fullscreen, resolution)
   - Click Save

3. **Connect**:
   - Select a connection from the list
   - Click "Connect" or double-click the connection
   - Enter VPN password when prompted (optionally save it)
   - Enter RDP password when prompted (optionally save it)
   - The app will connect to VPN first, then automatically launch RDP

4. **Disconnect**:
   - Select the active connection
   - Click "Disconnect"
   - This will close RDP and disconnect the VPN

## How It Works

1. When you click connect, the app first establishes a VPN connection using OpenVPN3
2. Once the VPN is connected, it automatically launches an RDP session using FreeRDP
3. The connection status is monitored in real-time
4. When you disconnect or close RDP, the VPN is also disconnected automatically

## Connection Profile Storage

- Connection profiles are stored in `~/.config/vpnrdp/connections.json`
- Passwords can be stored in the system keyring (if available) or prompted each time

## Importing VPN Configurations

Before using this app, you need to import your VPN configurations into OpenVPN3:

```bash
openvpn3 config-import --config /path/to/your/config.ovpn
```

You can then select the imported configuration when creating a connection profile.

## Troubleshooting

- **Missing Dependencies**: The app will warn you if OpenVPN3 or FreeRDP are not installed
- **VPN Connection Failed**: Check your VPN credentials and ensure the VPN config is properly imported
- **RDP Connection Failed**: Verify the RDP host is accessible from the VPN network
- **Password Storage Issues**: Install python3-keyring for secure password storage

## Security Notes

- Passwords are stored in the system keyring when available (recommended)
- Connection profiles are stored with restricted permissions (600)
- RDP passwords are passed via command line (be aware of process listing risks)

## License

MIT License# vpnrdp
