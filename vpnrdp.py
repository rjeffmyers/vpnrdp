#!/usr/bin/env python3

"""
VPN+RDP Combined GUI - Connect to VPN then RDP with one click
Copyright (c) 2024

MIT License
"""

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, GLib, Gdk
try:
    gi.require_version('AyatanaAppIndicator3', '0.1')
    from gi.repository import AyatanaAppIndicator3 as AppIndicator3
    APPINDICATOR_AVAILABLE = True
except (ImportError, ValueError):
    try:
        gi.require_version('AppIndicator3', '0.1')
        from gi.repository import AppIndicator3
        APPINDICATOR_AVAILABLE = True
    except (ImportError, ValueError):
        AppIndicator3 = None
        APPINDICATOR_AVAILABLE = False
import subprocess
import threading
import os
import shutil
import json
import time
import signal
import re
import sys
from collections import deque


def suppress_appindicator_deprecation_warning(log_domain, log_level, message):
    """Hide the known libayatana-appindicator deprecation warning."""
    if "libayatana-appindicator is deprecated" in message:
        return
    print(f"{log_domain}: {message}", file=sys.stderr)


def detect_os():
    """Detect the local OS family and package manager."""
    info = {
        "id": "",
        "name": "Linux",
        "id_like": "",
        "family": "unknown",
        "package_manager": "unknown"
    }

    try:
        with open("/etc/os-release", "r") as os_release:
            for line in os_release:
                if "=" not in line:
                    continue
                key, value = line.rstrip().split("=", 1)
                value = value.strip('"')
                if key == "ID":
                    info["id"] = value.lower()
                elif key == "NAME":
                    info["name"] = value
                elif key == "ID_LIKE":
                    info["id_like"] = value.lower()
    except OSError:
        pass

    os_tokens = {info["id"], *info["id_like"].split()}
    if os_tokens & {"arch", "cachyos", "manjaro", "endeavouros"} or shutil.which("pacman"):
        info["family"] = "arch"
        info["package_manager"] = "pacman"
    elif os_tokens & {"debian", "ubuntu", "linuxmint"} or shutil.which("apt"):
        info["family"] = "debian"
        info["package_manager"] = "apt"

    return info


OS_INFO = detect_os()


PACKAGE_MAP = {
    "networkmanager_openvpn": {
        "arch": ["networkmanager-openvpn"],
        "debian": ["network-manager-openvpn", "network-manager-openvpn-gnome"]
    },
    "openvpn3": {
        "arch": ["openvpn3"],
        "debian": ["openvpn3"]
    },
    "wireguard": {
        "arch": ["wireguard-tools"],
        "debian": ["wireguard"]
    },
    "freerdp": {
        "arch": ["freerdp"],
        "debian": ["freerdp2-x11"]
    },
    "gtk": {
        "arch": ["python-gobject", "gtk3"],
        "debian": ["python3-gi", "python3-gi-cairo", "gir1.2-gtk-3.0"]
    },
    "keyring": {
        "arch": ["python-keyring", "python-secretstorage", "kwallet"],
        "debian": ["python3-keyring", "python3-secretstorage", "gnome-keyring"]
    },
    "ayatana": {
        "arch": ["libayatana-appindicator"],
        "debian": ["gir1.2-ayatanaappindicator3-0.1"]
    }
}


def package_install_command(package_key):
    """Return a package install command for the detected OS."""
    packages = PACKAGE_MAP.get(package_key, {})
    family_packages = packages.get(OS_INFO["family"])
    if not family_packages:
        return "Install with your distribution package manager"
    if OS_INFO["package_manager"] == "pacman":
        return f"sudo pacman -S --needed {' '.join(family_packages)}"
    if OS_INFO["package_manager"] == "apt":
        return f"sudo apt update && sudo apt install {' '.join(family_packages)}"
    return "Install with your distribution package manager"

# Check if keyring module is available
try:
    import keyring
    backend = keyring.get_keyring()
    backend_name = backend.__class__.__name__.lower()
    
    if 'kde' in backend_name or 'kwallet' in backend_name:
        try:
            from keyring.backends import SecretService
            keyring.set_keyring(SecretService.Keyring())
            KEYRING_AVAILABLE = True
        except:
            KEYRING_AVAILABLE = False
    else:
        KEYRING_AVAILABLE = True
except ImportError:
    KEYRING_AVAILABLE = False
except Exception:
    KEYRING_AVAILABLE = False

class VPNRDPManager(Gtk.Window):
    def __init__(self):
        Gtk.Window.__init__(self, title="VPN+RDP Manager")
        self.set_border_width(20)
        self.set_default_size(600, 500)
        
        # Main vertical box
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.add(vbox)
        
        # Toolbar
        toolbar = Gtk.Toolbar()
        toolbar.set_style(Gtk.ToolbarStyle.BOTH_HORIZ)
        vbox.pack_start(toolbar, False, False, 0)
        
        # New connection button
        new_button = Gtk.ToolButton()
        new_button.set_label("New Connection")
        new_button.set_icon_name("list-add")
        new_button.set_tooltip_text("Create a new VPN+RDP connection profile")
        new_button.set_is_important(True)
        toolbar.insert(new_button, 0)
        new_button.connect("clicked", self.new_connection)
        
        # Edit connection button
        edit_button = Gtk.ToolButton()
        edit_button.set_label("Edit")
        edit_button.set_icon_name("document-edit")
        edit_button.set_tooltip_text("Edit selected connection")
        toolbar.insert(edit_button, 1)
        edit_button.connect("clicked", self.edit_connection)
        
        # Delete connection button
        delete_button = Gtk.ToolButton()
        delete_button.set_label("Delete")
        delete_button.set_icon_name("edit-delete")
        delete_button.set_tooltip_text("Delete selected connection")
        toolbar.insert(delete_button, 2)
        delete_button.connect("clicked", self.delete_connection)
        
        # Separator
        separator = Gtk.SeparatorToolItem()
        separator.set_expand(True)
        separator.set_draw(False)
        toolbar.insert(separator, 3)
        
        # Tools button
        tools_button = Gtk.ToolButton()
        tools_button.set_label("Tools")
        tools_button.set_icon_name("applications-system")
        tools_button.set_tooltip_text("Installation helpers and utilities")
        toolbar.insert(tools_button, 4)
        
        # Create tools menu
        tools_menu = Gtk.Menu()

        # Install NetworkManager OpenVPN menu item
        nm_item = Gtk.MenuItem(label="Install NetworkManager OpenVPN...")
        nm_item.connect("activate", self.show_networkmanager_openvpn_install)
        tools_menu.append(nm_item)
        
        # Install WireGuard menu item
        wg_item = Gtk.MenuItem(label="Install WireGuard...")
        wg_item.connect("activate", self.show_wireguard_install)
        tools_menu.append(wg_item)
        
        # Install OpenVPN3 menu item
        ovpn_item = Gtk.MenuItem(label="Install OpenVPN3...")
        ovpn_item.connect("activate", self.show_openvpn3_install)
        tools_menu.append(ovpn_item)
        
        # Separator
        tools_menu.append(Gtk.SeparatorMenuItem())
        
        # Import WireGuard config
        import_wg_item = Gtk.MenuItem(label="Import WireGuard Config...")
        import_wg_item.connect("activate", self.import_wireguard_config)
        tools_menu.append(import_wg_item)
        
        # Connect tools button to show menu
        def show_tools_menu(widget):
            tools_menu.show_all()
            tools_menu.popup_at_widget(widget, Gdk.Gravity.SOUTH_WEST, Gdk.Gravity.NORTH_WEST, None)
        
        tools_button.connect("clicked", show_tools_menu)
        
        # Help button
        help_button = Gtk.ToolButton()
        help_button.set_label("Help")
        help_button.set_icon_name("help-about")
        toolbar.insert(help_button, 5)
        help_button.connect("clicked", self.show_about)
        
        # Title
        title_label = Gtk.Label()
        title_label.set_markup("<b><big>VPN + RDP Connection Manager</big></b>")
        vbox.pack_start(title_label, False, False, 0)
        
        # Separator
        vbox.pack_start(Gtk.Separator(), False, False, 0)
        
        # Create notebook for connections and traffic chart
        self.main_notebook = Gtk.Notebook()
        vbox.pack_start(self.main_notebook, True, True, 0)
        
        # Tab 1: Saved Connections
        conn_frame = Gtk.Frame()
        conn_frame.set_border_width(10)
        
        # Scrolled window for connections
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        conn_frame.add(scrolled)
        
        # List store for connections
        self.liststore = Gtk.ListStore(str, str, str, str, str, str)  # Name, Type, VPN Config, RDP Host, Username, Status
        
        # Tree view
        self.treeview = Gtk.TreeView(model=self.liststore)
        scrolled.add(self.treeview)
        
        # Columns
        renderer = Gtk.CellRendererText()
        column = Gtk.TreeViewColumn("Connection Name", renderer, text=0)
        column.set_resizable(True)
        column.set_min_width(150)
        self.treeview.append_column(column)
        
        column = Gtk.TreeViewColumn("Type", renderer, text=1)
        column.set_resizable(True)
        self.treeview.append_column(column)
        
        column = Gtk.TreeViewColumn("VPN Config", renderer, text=2)
        column.set_resizable(True)
        self.treeview.append_column(column)
        
        column = Gtk.TreeViewColumn("RDP Host", renderer, text=3)
        column.set_resizable(True)
        self.treeview.append_column(column)
        
        column = Gtk.TreeViewColumn("RDP User", renderer, text=4)
        column.set_resizable(True)
        self.treeview.append_column(column)
        
        # Status column with color
        status_renderer = Gtk.CellRendererText()
        column = Gtk.TreeViewColumn("Status", status_renderer, text=5)
        column.set_cell_data_func(status_renderer, self.status_cell_data_func)
        self.treeview.append_column(column)
        
        # Double-click to connect
        self.treeview.connect("row-activated", self.on_row_activated)
        
        # Add Connections tab to notebook
        self.main_notebook.append_page(conn_frame, Gtk.Label(label="Connections"))
        
        # Tab 2: Traffic Chart
        chart_container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        chart_container.set_border_width(10)
        
        # Chart info label
        chart_info = Gtk.Label()
        chart_info.set_markup("<b>VPN Traffic Monitor</b>")
        chart_container.pack_start(chart_info, False, False, 0)
        
        # Create drawing area for chart
        self.chart_area = Gtk.DrawingArea()
        self.chart_area.set_size_request(600, 300)
        self.chart_area.connect("draw", self.on_chart_draw)
        
        # Put drawing area in a frame for visibility
        chart_frame = Gtk.Frame()
        chart_frame.add(self.chart_area)
        chart_container.pack_start(chart_frame, True, True, 0)
        
        # Legend for chart
        legend_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=20)
        legend_box.set_halign(Gtk.Align.CENTER)
        
        # Bytes In legend
        in_label = Gtk.Label()
        in_label.set_markup("<span color='#4CAF50'>●</span> Bytes In")
        legend_box.pack_start(in_label, False, False, 0)
        
        # Bytes Out legend
        out_label = Gtk.Label()
        out_label.set_markup("<span color='#2196F3'>●</span> Bytes Out")
        legend_box.pack_start(out_label, False, False, 0)
        
        # Current values display
        self.chart_stats_label = Gtk.Label()
        self.chart_stats_label.set_markup("<small>No active VPN connection</small>")
        legend_box.pack_start(self.chart_stats_label, False, False, 10)
        
        chart_container.pack_start(legend_box, False, False, 0)
        
        # Connection selector for chart
        conn_selector_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        conn_selector_label = Gtk.Label(label="Monitor connection:")
        conn_selector_box.pack_start(conn_selector_label, False, False, 0)
        
        self.chart_connection_combo = Gtk.ComboBoxText()
        self.chart_connection_combo.append_text("Auto (Active Connection)")
        self.chart_connection_combo.set_active(0)
        self.chart_connection_combo.connect("changed", self.on_chart_connection_changed)
        conn_selector_box.pack_start(self.chart_connection_combo, False, False, 0)
        
        chart_container.pack_start(conn_selector_box, False, False, 0)
        
        # Add Traffic Chart tab to notebook
        self.main_notebook.append_page(chart_container, Gtk.Label(label="Traffic Monitor"))
        
        # Initialize chart data
        self.chart_data_points = 60  # Number of data points to show
        self.bytes_in_history = deque([0] * self.chart_data_points, maxlen=self.chart_data_points)
        self.bytes_out_history = deque([0] * self.chart_data_points, maxlen=self.chart_data_points)
        self.last_bytes_in = {}  # Per connection
        self.last_bytes_out = {}  # Per connection
        self.chart_max_value = 1000  # Initial max value for Y-axis
        self.monitored_connection = None  # Which connection to monitor
        
        # Control buttons
        button_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        button_box.set_border_width(10)
        vbox.pack_start(button_box, False, False, 0)
        
        # Connect button
        self.connect_button = Gtk.Button(label="Connect")
        self.connect_button.connect("clicked", self.connect_selected)
        button_box.pack_start(self.connect_button, True, True, 0)
        
        # Disconnect button
        self.disconnect_button = Gtk.Button(label="Disconnect")
        self.disconnect_button.connect("clicked", self.disconnect_selected)
        self.disconnect_button.set_sensitive(False)
        button_box.pack_start(self.disconnect_button, True, True, 0)
        
        # Status bar
        self.statusbar = Gtk.Statusbar()
        vbox.pack_start(self.statusbar, False, False, 0)
        self.status_context = self.statusbar.get_context_id("status")
        
        # Initialize
        self.config_file = os.path.expanduser("~/.config/vpnrdp/connections.json")
        self.connections = self.load_connections()
        self.active_connections = {}  # Track active VPN sessions and RDP processes
        self.current_vpn_session = None
        self.current_rdp_process = None
        
        # Load connections into list
        self.refresh_connection_list()
        
        # Check dependencies
        self.check_dependencies()
        
        # Update status
        self.update_status("Ready")
        
        # Start status monitor
        GLib.timeout_add_seconds(2, self.monitor_connections)
        
        # Start traffic monitor
        GLib.timeout_add_seconds(2, self.update_traffic_chart)
        
        # Initialize system tray
        self.init_system_tray()
        
        # Connect window delete event to minimize to tray
        self.connect("delete-event", self.on_delete_event)
    
    def init_system_tray(self):
        """Initialize the system tray icon and menu"""
        self.tray_backend = None
        self.indicator = None
        self.status_icon = None
        self.tray_menu = self.create_tray_menu()

        if APPINDICATOR_AVAILABLE:
            GLib.log_set_handler(
                "libayatana-appindicator",
                GLib.LogLevelFlags.LEVEL_WARNING,
                suppress_appindicator_deprecation_warning
            )
            self.indicator = AppIndicator3.Indicator.new(
                "vpnrdp-manager",
                "network-vpn",
                AppIndicator3.IndicatorCategory.APPLICATION_STATUS
            )
            self.indicator.set_status(AppIndicator3.IndicatorStatus.ACTIVE)
            self.indicator.set_menu(self.tray_menu)
            self.tray_backend = "appindicator"
            return

        try:
            self.status_icon = Gtk.StatusIcon.new_from_icon_name("network-vpn")
            self.status_icon.set_tooltip_text("VPN+RDP Manager")
            self.status_icon.set_visible(True)
            self.status_icon.connect("activate", self.toggle_window_visibility)
            self.status_icon.connect("popup-menu", self.on_status_icon_popup_menu)
            self.tray_backend = "statusicon"
            self.update_status("Ready (legacy tray icon)")
        except Exception as e:
            self.status_icon = None
            self.update_status(f"Ready (tray unavailable: {e})")
    
    def create_tray_menu(self):
        """Create the system tray menu"""
        menu = Gtk.Menu()
        
        # Show/Hide window item
        show_item = Gtk.MenuItem(label="Show/Hide Window")
        show_item.connect("activate", self.toggle_window_visibility)
        menu.append(show_item)
        
        # Separator
        separator = Gtk.SeparatorMenuItem()
        menu.append(separator)
        
        # Exit item
        exit_item = Gtk.MenuItem(label="Exit")
        exit_item.connect("activate", self.on_exit)
        menu.append(exit_item)
        
        menu.show_all()
        return menu

    def on_status_icon_popup_menu(self, icon, button, activate_time):
        """Show the legacy Gtk.StatusIcon context menu."""
        self.tray_menu.popup(None, None, None, None, button, activate_time)
    
    def toggle_window_visibility(self, widget):
        """Toggle window visibility when tray icon is clicked"""
        if self.get_visible():
            self.hide()
        else:
            self.show()
            self.present()  # Bring window to front
    
    def on_delete_event(self, widget, event):
        """Minimize to tray when available; otherwise quit visibly."""
        if self.tray_backend:
            self.hide()
            self.update_status("Hidden to system tray")
            return True

        self.on_exit(widget)
        return True
    
    def on_exit(self, widget):
        """Handle exit with confirmation if connections are active"""
        # Check for active connections
        active_conns = []
        for name, info in self.active_connections.items():
            if info.get("status") in ["Connected", "Connecting..."]:
                active_conns.append(name)
        
        if active_conns:
            # Show warning dialog
            dialog = Gtk.MessageDialog(
                parent=self,
                flags=Gtk.DialogFlags.MODAL,
                type=Gtk.MessageType.WARNING,
                buttons=Gtk.ButtonsType.YES_NO,
                message_format="Active Connections Warning"
            )
            dialog.format_secondary_text(
                f"The following connections are active:\n\n{', '.join(active_conns)}\n\n"
                "Exiting will close all connections. Do you want to continue?"
            )
            
            response = dialog.run()
            dialog.destroy()
            
            if response != Gtk.ResponseType.YES:
                return
            
            # Disconnect all active connections
            for name in active_conns:
                self.disconnect(name)
        
        # Exit the application
        Gtk.main_quit()
    
    def status_cell_data_func(self, column, cell, model, iter, data):
        """Color code the status column"""
        status = model.get_value(iter, 5)
        if status == "Connected":
            cell.set_property("foreground", "green")
        elif status == "Connecting...":
            cell.set_property("foreground", "orange")
        elif status == "Disconnected":
            cell.set_property("foreground", "gray")
        else:
            cell.set_property("foreground", "red")
    
    def check_dependencies(self):
        """Check if required programs are installed"""
        missing = []
        optional_missing = []
        
        # Check for at least one VPN solution
        has_vpn = False
        if shutil.which("nmcli"):
            has_vpn = True
        else:
            optional_missing.append("NetworkManager")

        if shutil.which("openvpn3"):
            has_vpn = True
        else:
            optional_missing.append("OpenVPN3")
            
        if shutil.which("wg") and shutil.which("wg-quick"):
            has_vpn = True
        else:
            optional_missing.append("WireGuard")
        
        if not has_vpn:
            missing.append("VPN client (NetworkManager, OpenVPN3, or WireGuard)")
        
        if not shutil.which("xfreerdp") and not shutil.which("xfreerdp3"):
            missing.append("FreeRDP")
        
        if missing:
            dialog = Gtk.MessageDialog(
                transient_for=self,
                flags=0,
                message_type=Gtk.MessageType.WARNING,
                buttons=Gtk.ButtonsType.OK,
                text="Missing Required Dependencies"
            )
            dialog.format_secondary_text(
                f"The following required programs are not installed:\n{', '.join(missing)}\n\n"
                f"Detected OS: {OS_INFO['name']} ({OS_INFO['family']})\n\n"
                "Please install at least one VPN client:\n"
                f"• NetworkManager OpenVPN: {package_install_command('networkmanager_openvpn')}\n"
                f"• OpenVPN3: {package_install_command('openvpn3')}\n"
                f"• WireGuard: {package_install_command('wireguard')}\n"
                f"• FreeRDP: {package_install_command('freerdp')}"
            )
            dialog.run()
            dialog.destroy()
        elif optional_missing:
            # Show optional dependencies info in status bar
            self.update_status(f"Optional: {', '.join(optional_missing)} not installed")
    
    def load_connections(self):
        """Load saved connections from file"""
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r') as f:
                    return json.load(f)
            except:
                pass
        return {}
    
    def save_connections(self):
        """Save connections to file"""
        os.makedirs(os.path.dirname(self.config_file), exist_ok=True)
        with open(self.config_file, 'w') as f:
            json.dump(self.connections, f, indent=2)
        os.chmod(self.config_file, 0o600)
    
    def refresh_connection_list(self):
        """Refresh the connection list display"""
        self.liststore.clear()
        for name, conn in self.connections.items():
            status = self.active_connections.get(name, {}).get("status", "Disconnected")
            conn_type = conn.get("connection_mode", "VPN+RDP")  # Default to VPN+RDP for existing connections
            
            # Format display values based on connection type
            vpn_config = ""
            rdp_host = ""
            rdp_username = ""
            
            if conn_type in ["VPN+RDP", "VPN Only"]:
                vpn_config = os.path.basename(conn.get("vpn_config", ""))
            if conn_type in ["VPN+RDP", "RDP Only"]:
                rdp_host = conn.get("rdp_host", "")
                rdp_username = conn.get("rdp_username", "")
            
            self.liststore.append([
                name,
                conn_type,
                vpn_config,
                rdp_host,
                rdp_username,
                status
            ])
    
    def new_connection(self, widget):
        """Create a new connection profile"""
        dialog = ConnectionDialog(self, None, self.connections)
        response = dialog.run()
        
        if response == Gtk.ResponseType.OK:
            conn_data = dialog.get_connection_data()
            if conn_data:
                name = conn_data["name"]
                self.connections[name] = conn_data
                self.save_connections()
                self.refresh_connection_list()
                self.update_status(f"Created connection: {name}")
        
        dialog.destroy()
    
    def edit_connection(self, widget):
        """Edit selected connection"""
        selection = self.treeview.get_selection()
        model, iter = selection.get_selected()
        
        if iter:
            name = model.get_value(iter, 0)
            if name in self.connections:
                dialog = ConnectionDialog(self, self.connections[name], self.connections)
                response = dialog.run()
                
                if response == Gtk.ResponseType.OK:
                    conn_data = dialog.get_connection_data()
                    if conn_data:
                        # If name changed, remove old entry
                        if conn_data["name"] != name:
                            del self.connections[name]
                        
                        self.connections[conn_data["name"]] = conn_data
                        self.save_connections()
                        self.refresh_connection_list()
                        self.update_status(f"Updated connection: {conn_data['name']}")
                
                dialog.destroy()
    
    def delete_connection(self, widget):
        """Delete selected connection"""
        selection = self.treeview.get_selection()
        model, iter = selection.get_selected()
        
        if iter:
            name = model.get_value(iter, 0)
            
            dialog = Gtk.MessageDialog(
                transient_for=self,
                flags=0,
                message_type=Gtk.MessageType.QUESTION,
                buttons=Gtk.ButtonsType.YES_NO,
                text=f"Delete connection '{name}'?"
            )
            dialog.format_secondary_text("This action cannot be undone.")
            
            response = dialog.run()
            dialog.destroy()
            
            if response == Gtk.ResponseType.YES:
                if name in self.connections:
                    del self.connections[name]
                    self.save_connections()
                    self.refresh_connection_list()
                    self.update_status(f"Deleted connection: {name}")
    
    def on_row_activated(self, treeview, path, column):
        """Handle double-click on connection"""
        self.connect_selected(None)
    
    def connect_selected(self, widget):
        """Connect to selected VPN+RDP"""
        selection = self.treeview.get_selection()
        model, iter = selection.get_selected()
        
        if iter:
            name = model.get_value(iter, 0)
            if name in self.connections:
                self.connect_to(name)
    
    def connect_to(self, name):
        """Connect to a specific connection profile"""
        if name not in self.connections:
            return
        
        # Check if already connecting or connected
        if name in self.active_connections:
            status = self.active_connections[name].get("status", "")
            if status in ["Connecting...", "Connected", "VPN Connected"]:
                return  # Already connecting or connected
        
        conn = self.connections[name]
        
        # Disable connect button to prevent multiple clicks
        self.connect_button.set_sensitive(False)
        
        # Update status
        self.update_connection_status(name, "Connecting...")
        self.update_status(f"Connecting to {name}...")
        
        # Show connecting dialog
        self.show_connecting_dialog(name, conn)
    
    def show_connecting_dialog(self, name, conn):
        """Show a dialog while connecting"""
        conn = dict(conn)
        if not self.collect_connection_passwords(name, conn):
            self.update_connection_status(name, "Canceled")
            self.update_status("Connection canceled")
            self.connect_button.set_sensitive(True)
            return

        dialog = Gtk.Dialog(
            title=f"Connecting to {name}",
            transient_for=self,
            modal=True
        )
        dialog.set_default_size(400, 200)
        dialog.set_resizable(False)
        
        # Add cancel button
        dialog.add_button("Cancel", Gtk.ResponseType.CANCEL)
        
        content = dialog.get_content_area()
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=20)
        vbox.set_border_width(20)
        content.add(vbox)
        
        # Connection name label
        name_label = Gtk.Label()
        name_label.set_markup(f"<b><big>Connecting to {name}</big></b>")
        vbox.pack_start(name_label, False, False, 0)
        
        # Status label
        status_label = Gtk.Label(label="Establishing VPN connection...")
        vbox.pack_start(status_label, False, False, 0)
        
        # Progress bar
        progress_bar = Gtk.ProgressBar()
        progress_bar.set_show_text(False)
        vbox.pack_start(progress_bar, False, False, 0)
        
        # Spinner
        spinner = Gtk.Spinner()
        spinner.start()
        vbox.pack_start(spinner, True, True, 0)
        
        # Details expander
        expander = Gtk.Expander(label="Details")
        vbox.pack_start(expander, False, False, 0)
        
        details_text = Gtk.TextView()
        details_text.set_editable(False)
        details_text.set_wrap_mode(Gtk.WrapMode.WORD)
        details_buffer = details_text.get_buffer()
        
        # Build details based on connection mode
        connection_mode = conn.get("connection_mode", "VPN+RDP")
        details = f"Connection Type: {connection_mode}\n"
        if connection_mode in ["VPN+RDP", "VPN Only"]:
            details += f"VPN Config: {conn.get('vpn_config', 'N/A')}\n"
        if connection_mode in ["VPN+RDP", "RDP Only"]:
            details += f"RDP Host: {conn.get('rdp_host', 'N/A')}"
        details_buffer.set_text(details)
        
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_min_content_height(100)
        scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scrolled.add(details_text)
        expander.add(scrolled)
        
        dialog.show_all()
        
        # Store references for updates
        self.connecting_dialog = dialog
        self.connecting_status_label = status_label
        self.connecting_progress = progress_bar
        self.connecting_canceled = False
        self.connecting_thread_done = False
        
        # Start connection in background thread
        thread = threading.Thread(target=self.connection_worker_with_dialog, args=(name, conn, dialog))
        thread.daemon = True
        thread.start()
        
        # Handle dialog response
        response = dialog.run()
        if response == Gtk.ResponseType.CANCEL:
            self.connecting_canceled = True
            # Disconnect if connection was established
            if name in self.active_connections:
                self.disconnect(name)
            self.update_connection_status(name, "Canceled")
            self.update_status("Connection canceled")
            self.connect_button.set_sensitive(True)  # Re-enable connect button
        elif response != Gtk.ResponseType.OK:
            # Connection failed or dialog closed
            self.connect_button.set_sensitive(True)  # Re-enable connect button

        self.connecting_canceled = True
        
        dialog.destroy()
        self.connecting_dialog = None

    def collect_connection_passwords(self, name, conn):
        """Prompt for passwords on the GTK main thread before worker startup."""
        connection_mode = conn.get("connection_mode", "VPN+RDP")
        vpn_type = conn.get("vpn_type", "OpenVPN3")

        if connection_mode in ["VPN+RDP", "VPN Only"] and vpn_type == "OpenVPN3":
            vpn_password = self.get_password(name, "vpn")
            if not vpn_password:
                return False
            conn["_vpn_password"] = vpn_password

        if connection_mode in ["VPN+RDP", "RDP Only"]:
            rdp_password = self.get_password(name, "rdp")
            if not rdp_password:
                return False
            conn["_rdp_password"] = rdp_password

        return True

    def safe_dialog_response(self, dialog, response):
        """Respond to a dialog only if it has not been canceled/destroyed."""
        if self.connecting_canceled or self.connecting_dialog is not dialog:
            return False
        dialog.response(response)
        return False

    def safe_set_connecting_status(self, dialog, message):
        """Update connecting status only while the dialog is current."""
        if self.connecting_canceled or self.connecting_dialog is not dialog:
            return False
        self.connecting_status_label.set_text(message)
        return False

    def safe_set_connecting_progress(self, dialog, fraction):
        """Update connecting progress only while the dialog is current."""
        if self.connecting_canceled or self.connecting_dialog is not dialog:
            return False
        self.connecting_progress.set_fraction(fraction)
        return False
    
    def connection_worker_with_dialog(self, name, conn, dialog):
        """Worker thread for establishing connection with dialog updates"""
        try:
            connection_mode = conn.get("connection_mode", "VPN+RDP")
            
            # Handle VPN-only connections
            if connection_mode == "VPN Only":
                GLib.idle_add(self.safe_set_connecting_status, dialog, "Establishing VPN connection...")
                GLib.idle_add(self.safe_set_connecting_progress, dialog, 0.5)
                
                if self.connecting_canceled:
                    return
                
                # Connect to VPN
                vpn_success = self.connect_vpn(name, conn)
                
                if vpn_success:
                    GLib.idle_add(self.safe_set_connecting_status, dialog, "VPN connection established successfully!")
                    GLib.idle_add(self.safe_set_connecting_progress, dialog, 1.0)
                    GLib.idle_add(self.update_connection_status, name, "VPN Connected")
                    GLib.idle_add(self.update_status, f"VPN connected: {name}")
                    GLib.idle_add(self.update_buttons, True)
                    time.sleep(1)
                    GLib.idle_add(self.safe_dialog_response, dialog, Gtk.ResponseType.OK)
                else:
                    GLib.idle_add(self.safe_set_connecting_status, dialog, "VPN connection failed!")
                    GLib.idle_add(self.update_connection_status, name, "VPN Failed")
                    GLib.idle_add(self.update_status, f"VPN connection failed for {name}")
                    GLib.idle_add(self.update_buttons, False)
                    time.sleep(2)
                    GLib.idle_add(self.safe_dialog_response, dialog, Gtk.ResponseType.CLOSE)
                return
            
            # Handle RDP-only connections
            elif connection_mode == "RDP Only":
                GLib.idle_add(self.safe_set_connecting_status, dialog, "Establishing RDP connection...")
                GLib.idle_add(self.safe_set_connecting_progress, dialog, 0.5)
                
                if self.connecting_canceled:
                    return
                
                # Connect to RDP directly
                rdp_success = self.connect_rdp(name, conn)
                
                if rdp_success:
                    GLib.idle_add(self.safe_set_connecting_status, dialog, "RDP connection established successfully!")
                    GLib.idle_add(self.safe_set_connecting_progress, dialog, 1.0)
                    GLib.idle_add(self.update_connection_status, name, "RDP Connected")
                    GLib.idle_add(self.update_status, f"RDP connected: {name}")
                    GLib.idle_add(self.update_buttons, True)
                    time.sleep(1)
                    GLib.idle_add(self.safe_dialog_response, dialog, Gtk.ResponseType.OK)
                else:
                    GLib.idle_add(self.safe_set_connecting_status, dialog, "RDP connection failed!")
                    GLib.idle_add(self.update_connection_status, name, "RDP Failed")
                    GLib.idle_add(self.update_status, f"RDP connection failed for {name}")
                    GLib.idle_add(self.update_buttons, False)
                    time.sleep(2)
                    GLib.idle_add(self.safe_dialog_response, dialog, Gtk.ResponseType.CLOSE)
                return
            
            # Handle VPN+RDP connections (default)
            else:
                # Update dialog: Connecting to VPN
                GLib.idle_add(self.safe_set_connecting_status, dialog, "Establishing VPN connection...")
                GLib.idle_add(self.safe_set_connecting_progress, dialog, 0.25)
                
                if self.connecting_canceled:
                    return
                
                # Connect to VPN
                vpn_success = self.connect_vpn(name, conn)
                
                if not vpn_success:
                    GLib.idle_add(self.safe_set_connecting_status, dialog, "VPN connection failed!")
                    GLib.idle_add(self.update_connection_status, name, "VPN Failed")
                    GLib.idle_add(self.update_status, f"VPN connection failed for {name}")
                    GLib.idle_add(self.update_buttons, False)
                    time.sleep(2)  # Show error briefly
                    GLib.idle_add(self.safe_dialog_response, dialog, Gtk.ResponseType.CLOSE)
                    return
                
                if self.connecting_canceled:
                    self.disconnect_vpn(name)
                    return
                
                # Update dialog: VPN connected, connecting to RDP
                GLib.idle_add(self.safe_set_connecting_status, dialog, "VPN connected! Establishing RDP connection...")
                GLib.idle_add(self.safe_set_connecting_progress, dialog, 0.75)
                
                # Wait for VPN to stabilize
                time.sleep(3)
                
                if self.connecting_canceled:
                    self.disconnect_vpn(name)
                    return
                
                # Connect to RDP
                rdp_success = self.connect_rdp(name, conn)
                
                if rdp_success:
                    GLib.idle_add(self.safe_set_connecting_status, dialog, "Connection established successfully!")
                    GLib.idle_add(self.safe_set_connecting_progress, dialog, 1.0)
                    GLib.idle_add(self.update_connection_status, name, "Connected")
                    GLib.idle_add(self.update_status, f"Connected to {name}")
                    GLib.idle_add(self.update_buttons, True)
                    time.sleep(1)  # Show success briefly
                    GLib.idle_add(self.safe_dialog_response, dialog, Gtk.ResponseType.OK)
                else:
                    # RDP failed, disconnect VPN
                    GLib.idle_add(self.safe_set_connecting_status, dialog, "RDP connection failed!")
                    self.disconnect_vpn(name)
                    GLib.idle_add(self.update_connection_status, name, "RDP Failed")
                    GLib.idle_add(self.update_status, f"RDP connection failed for {name}")
                    GLib.idle_add(self.update_buttons, False)
                    time.sleep(2)  # Show error briefly
                    GLib.idle_add(self.safe_dialog_response, dialog, Gtk.ResponseType.CLOSE)
        
        except Exception as e:
            GLib.idle_add(self.safe_set_connecting_status, dialog, f"Error: {str(e)}")
            GLib.idle_add(self.update_connection_status, name, "Error")
            GLib.idle_add(self.update_status, f"Error connecting to {name}: {str(e)}")
            GLib.idle_add(self.update_buttons, False)
            time.sleep(2)  # Show error briefly
            GLib.idle_add(self.safe_dialog_response, dialog, Gtk.ResponseType.CLOSE)
    
    def connection_worker(self, name, conn):
        """Worker thread for establishing connection"""
        try:
            # First, connect to VPN
            vpn_success = self.connect_vpn(name, conn)
            
            if vpn_success:
                # Wait a moment for VPN to stabilize
                time.sleep(3)
                
                # Then connect to RDP
                rdp_success = self.connect_rdp(name, conn)
                
                if rdp_success:
                    GLib.idle_add(self.update_connection_status, name, "Connected")
                    GLib.idle_add(self.update_status, f"Connected to {name}")
                    GLib.idle_add(self.update_buttons, True)
                else:
                    # RDP failed, disconnect VPN
                    self.disconnect_vpn(name)
                    GLib.idle_add(self.update_connection_status, name, "RDP Failed")
                    GLib.idle_add(self.update_status, f"RDP connection failed for {name}")
                    GLib.idle_add(self.update_buttons, False)
            else:
                GLib.idle_add(self.update_connection_status, name, "VPN Failed")
                GLib.idle_add(self.update_status, f"VPN connection failed for {name}")
                GLib.idle_add(self.update_buttons, False)
        
        except Exception as e:
            GLib.idle_add(self.update_connection_status, name, "Error")
            GLib.idle_add(self.update_status, f"Error connecting to {name}: {str(e)}")
            GLib.idle_add(self.update_buttons, False)
    
    def connect_vpn(self, name, conn):
        """Connect to VPN"""
        vpn_type = conn.get("vpn_type", "OpenVPN3")
        vpn_config = conn.get("vpn_config")
        
        if not vpn_config:
            return False
        
        if vpn_type == "OpenVPN3":
            return self.connect_openvpn3(name, conn)
        elif vpn_type == "NetworkManager":
            return self.connect_networkmanager(name, conn)
        elif vpn_type == "WireGuard":
            return self.connect_wireguard(name, conn)
        else:
            return False

    def connect_networkmanager(self, name, conn):
        """Connect using an existing NetworkManager VPN profile."""
        vpn_config = conn.get("vpn_config")

        if not vpn_config:
            return False

        try:
            result = subprocess.run(
                ["nmcli", "connection", "up", "id", vpn_config],
                capture_output=True,
                text=True,
                timeout=45
            )

            if result.returncode == 0 or self.is_networkmanager_connection_active(vpn_config):
                self.active_connections[name] = {
                    "vpn_type": "NetworkManager",
                    "vpn_config": vpn_config,
                    "status": "VPN Connected"
                }
                return True

            print(f"NetworkManager connection failed: {result.stderr.strip() or result.stdout.strip()}")
            return False

        except Exception as e:
            print(f"NetworkManager connection error: {e}")
            return False

    def is_networkmanager_connection_active(self, connection_name):
        """Return True if NetworkManager reports the connection as active."""
        try:
            result = subprocess.run(
                ["nmcli", "-t", "--escape", "no", "-f", "NAME", "connection", "show", "--active"],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode != 0:
                return False
            return connection_name in result.stdout.splitlines()
        except Exception:
            return False
    
    def connect_openvpn3(self, name, conn):
        """Connect using OpenVPN3"""
        vpn_config = conn.get("vpn_config")
        vpn_username = conn.get("vpn_username")
        vpn_password = conn.get("_vpn_password")
        
        if not vpn_config or not os.path.exists(vpn_config):
            return False
        if vpn_password is None:
            print("OpenVPN3 password was not collected before worker startup")
            return False
        
        try:
            # Start VPN session
            cmd = ["openvpn3", "session-start", "--config", vpn_config]
            
            proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            
            # Provide credentials
            stdout, stderr = proc.communicate(
                input=f"{vpn_username}\n{vpn_password}\n",
                timeout=30
            )
            
            if proc.returncode == 0:
                # Extract session path
                for line in stdout.split('\n'):
                    if 'Session path:' in line:
                        session_path = line.split('Session path:')[1].strip()
                        self.active_connections[name] = {
                            "vpn_type": "OpenVPN3",
                            "vpn_session": session_path,
                            "status": "VPN Connected"
                        }
                        return True
                
                # Try alternative format
                if '/net/openvpn/v3/sessions/' in stdout:
                    matches = re.findall(r'/net/openvpn/v3/sessions/[a-f0-9s]+', stdout)
                    if matches:
                        self.active_connections[name] = {
                            "vpn_type": "OpenVPN3",
                            "vpn_session": matches[0],
                            "status": "VPN Connected"
                        }
                        return True
            
            return False
        
        except Exception as e:
            print(f"OpenVPN3 connection error: {e}")
            return False
    
    def connect_wireguard(self, name, conn):
        """Connect using WireGuard"""
        vpn_config = conn.get("vpn_config")
        
        if not vpn_config:
            return False
        
        # Handle sudo prefix for system configs
        needs_sudo = vpn_config.startswith("sudo:")
        if needs_sudo:
            vpn_config = vpn_config[5:]  # Remove "sudo:" prefix
        
        if not os.path.exists(vpn_config):
            print(f"WireGuard config not found: {vpn_config}")
            return False
        
        try:
            # Extract interface name from config file name
            config_name = os.path.basename(vpn_config)
            if config_name.endswith('.conf'):
                interface_name = config_name[:-5]  # Remove .conf extension
            else:
                interface_name = "wg0"
            
            # Start WireGuard connection
            if needs_sudo or not os.access(vpn_config, os.R_OK):
                # Need sudo for system configs
                cmd = ["sudo", "wg-quick", "up", vpn_config]
            else:
                cmd = ["wg-quick", "up", vpn_config]
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=10
            )
            
            if result.returncode == 0 or "already exists" in result.stderr:
                # Connection successful or already connected
                self.active_connections[name] = {
                    "vpn_type": "WireGuard",
                    "vpn_interface": interface_name,
                    "vpn_config": vpn_config,
                    "needs_sudo": needs_sudo,
                    "status": "VPN Connected"
                }
                return True
            
            print(f"WireGuard connection failed: {result.stderr}")
            return False
        
        except Exception as e:
            print(f"WireGuard connection error: {e}")
            return False
    
    def connect_rdp(self, name, conn):
        """Connect to RDP"""
        rdp_host = conn.get("rdp_host")
        rdp_username = conn.get("rdp_username")
        rdp_domain = conn.get("rdp_domain", "")
        rdp_password = conn.get("_rdp_password")
        
        if not rdp_host:
            return False
        if rdp_password is None:
            print("RDP password was not collected before worker startup")
            return False
        
        # Find xfreerdp command
        freerdp_cmd = None
        if shutil.which("xfreerdp3"):
            freerdp_cmd = "xfreerdp3"
        elif shutil.which("xfreerdp"):
            freerdp_cmd = "xfreerdp"
        
        if not freerdp_cmd:
            return False
        
        try:
            # Build RDP command
            cmd = [freerdp_cmd]
            cmd.append(f"/v:{rdp_host}")
            
            if rdp_domain:
                cmd.append(f"/u:{rdp_username}")
                cmd.append(f"/d:{rdp_domain}")
            else:
                cmd.append(f"/u:{rdp_username}")
            
            cmd.append(f"/p:{rdp_password}")
            
            # Display options
            if conn.get("rdp_fullscreen", True):
                cmd.append("/f")
            else:
                resolution = conn.get("rdp_resolution", "1920x1080")
                cmd.append(f"/size:{resolution}")
            
            # Multi-monitor support
            if conn.get("multimon", False):
                cmd.append("/multimon")
                
                # Specific monitors if selected
                selected_monitors = conn.get("selected_monitors", [])
                if selected_monitors:
                    monitors_str = ",".join(str(m) for m in selected_monitors)
                    cmd.extend([f"/monitors:{monitors_str}"])
            
            # Performance flags
            if conn.get("disable_fonts", True):
                cmd.append("+fonts")
            if conn.get("disable_wallpaper", True):
                cmd.append("-wallpaper")
            if conn.get("disable_themes", True):
                cmd.append("-themes")
            if conn.get("disable_aero", True):
                cmd.append("+aero")
            if conn.get("disable_drag", False):
                cmd.append("-window-drag")
            
            # Audio settings
            audio_mode = conn.get("audio_mode", "local")
            if audio_mode == "local":
                cmd.append("/sound")
            elif audio_mode == "remote":
                cmd.append("/audio-mode:1")
            elif audio_mode == "disabled":
                cmd.append("/audio-mode:2")
            
            # Clipboard
            if conn.get("clipboard", True):
                cmd.append("+clipboard")
            
            # Drive redirection
            if conn.get("redirect_drives", False):
                home_dir = os.path.expanduser("~")
                cmd.extend([f"/drive:home,{home_dir}"])
            
            # Certificate acceptance
            cmd.append("/cert:ignore")
            
            # Network level authentication
            if conn.get("nla", True):
                cmd.append("/sec:nla")
            else:
                cmd.append("/sec:rdp")
            
            # Compression
            if conn.get("compression", True):
                cmd.append("+compression")
            
            # Start RDP process
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            
            # Check if it started successfully
            time.sleep(2)
            if proc.poll() is None:
                # Process is running
                if name in self.active_connections:
                    self.active_connections[name]["rdp_process"] = proc
                    self.active_connections[name]["status"] = "Connected"
                else:
                    self.active_connections[name] = {
                        "rdp_process": proc,
                        "status": "Connected"
                    }
                return True
            
            return False
        
        except Exception as e:
            print(f"RDP connection error: {e}")
            return False
    
    def disconnect_selected(self, widget):
        """Disconnect selected connection"""
        selection = self.treeview.get_selection()
        model, iter = selection.get_selected()
        
        if iter:
            name = model.get_value(iter, 0)
            self.disconnect(name)
    
    def disconnect(self, name):
        """Disconnect a specific connection"""
        if name not in self.active_connections:
            return
        
        self.update_status(f"Disconnecting {name}...")
        
        # Get connection mode
        conn = self.connections.get(name, {})
        connection_mode = conn.get("connection_mode", "VPN+RDP")
        
        # Disconnect RDP if applicable
        if connection_mode in ["VPN+RDP", "RDP Only"]:
            if "rdp_process" in self.active_connections[name]:
                try:
                    proc = self.active_connections[name]["rdp_process"]
                    proc.terminate()
                    proc.wait(timeout=5)
                except:
                    try:
                        proc.kill()
                    except:
                        pass
        
        # Disconnect VPN if applicable
        if connection_mode in ["VPN+RDP", "VPN Only"]:
            self.disconnect_vpn(name)
        
        # Clean up
        if name in self.active_connections:
            del self.active_connections[name]
        
        self.update_connection_status(name, "Disconnected")
        self.update_status(f"Disconnected from {name}")
        self.update_buttons(False)
    
    def disconnect_vpn(self, name):
        """Disconnect VPN session"""
        if name in self.active_connections:
            conn_info = self.active_connections[name]
            vpn_type = conn_info.get("vpn_type", "OpenVPN3")
            
            if vpn_type == "OpenVPN3":
                session = conn_info.get("vpn_session")
                if session:
                    try:
                        subprocess.run(
                            ["openvpn3", "session-manage", "--session-path", session, "--disconnect"],
                            capture_output=True,
                            timeout=5
                        )
                    except:
                        pass

            elif vpn_type == "NetworkManager":
                vpn_config = conn_info.get("vpn_config")
                if vpn_config:
                    try:
                        subprocess.run(
                            ["nmcli", "connection", "down", "id", vpn_config],
                            capture_output=True,
                            timeout=10
                        )
                    except:
                        pass
            
            elif vpn_type == "WireGuard":
                vpn_config = conn_info.get("vpn_config")
                needs_sudo = conn_info.get("needs_sudo", False)
                
                if vpn_config:
                    try:
                        if needs_sudo:
                            cmd = ["sudo", "wg-quick", "down", vpn_config]
                        else:
                            cmd = ["wg-quick", "down", vpn_config]
                        
                        subprocess.run(cmd, capture_output=True, timeout=5)
                    except:
                        pass
    
    def monitor_connections(self):
        """Monitor active connections"""
        for name in list(self.active_connections.keys()):
            conn_info = self.active_connections[name]

            if conn_info.get("vpn_type") == "NetworkManager":
                vpn_config = conn_info.get("vpn_config")
                if vpn_config and not self.is_networkmanager_connection_active(vpn_config):
                    self.disconnect(name)
                    continue
            
            # Check RDP process
            if "rdp_process" in conn_info:
                proc = conn_info["rdp_process"]
                if proc.poll() is not None:
                    # RDP has closed
                    self.disconnect(name)
        
        return True  # Continue monitoring
    
    def update_connection_status(self, name, status):
        """Update status for a specific connection in the list"""
        for row in self.liststore:
            if row[0] == name:
                row[5] = status
                break
    
    def update_status(self, message):
        """Update status bar"""
        self.statusbar.pop(self.status_context)
        self.statusbar.push(self.status_context, message)
    
    def update_buttons(self, connected):
        """Update button states"""
        self.connect_button.set_sensitive(not connected)
        self.disconnect_button.set_sensitive(connected)
    
    def get_password(self, name, service_type):
        """Get password from keyring or prompt"""
        key = f"vpnrdp_{name}_{service_type}"
        
        if KEYRING_AVAILABLE:
            try:
                password = keyring.get_password("vpnrdp", key)
                if password:
                    return password
            except:
                pass
        
        # Prompt for password
        dialog = Gtk.Dialog(
            title=f"Enter {service_type.upper()} Password",
            transient_for=self,
            modal=True
        )
        dialog.add_buttons(
            Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
            Gtk.STOCK_OK, Gtk.ResponseType.OK
        )
        
        dialog.set_default_size(400, 150)
        
        content = dialog.get_content_area()
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        vbox.set_border_width(10)
        content.add(vbox)
        
        label = Gtk.Label(label=f"Enter {service_type.upper()} password for {name}:")
        vbox.pack_start(label, False, False, 0)
        
        entry = Gtk.Entry()
        entry.set_visibility(False)
        entry.set_input_purpose(Gtk.InputPurpose.PASSWORD)
        vbox.pack_start(entry, False, False, 0)
        
        save_check = Gtk.CheckButton(label="Save password")
        save_check.set_active(KEYRING_AVAILABLE)
        vbox.pack_start(save_check, False, False, 0)
        
        dialog.show_all()
        entry.grab_focus()
        
        response = dialog.run()
        password = entry.get_text()
        save = save_check.get_active()
        dialog.destroy()
        
        if response == Gtk.ResponseType.OK and password:
            if save and KEYRING_AVAILABLE:
                try:
                    keyring.set_password("vpnrdp", key, password)
                except:
                    pass
            return password
        
        return None
    
    def on_chart_connection_changed(self, widget):
        """Handle chart connection selection change"""
        text = widget.get_active_text()
        if text == "Auto (Active Connection)":
            self.monitored_connection = None
        else:
            self.monitored_connection = text
    
    def on_chart_draw(self, widget, cr):
        """Draw the traffic chart"""
        allocation = widget.get_allocation()
        width = allocation.width
        height = allocation.height
        
        # Ensure we have valid dimensions
        if width <= 0 or height <= 0:
            return False
        
        # Background - white
        cr.set_source_rgb(1.0, 1.0, 1.0)
        cr.rectangle(0, 0, width, height)
        cr.fill()
        
        # Draw grid
        cr.set_source_rgba(0.8, 0.8, 0.8, 0.5)
        cr.set_line_width(0.5)
        
        # Horizontal grid lines (5 lines)
        for i in range(5):
            y = int(height * i / 4)
            cr.move_to(0, y)
            cr.line_to(width, y)
        cr.stroke()
        
        # Vertical grid lines (every 10 data points)
        grid_spacing = 10
        for i in range(0, self.chart_data_points + 1, grid_spacing):
            x = int(width * i / self.chart_data_points)
            cr.move_to(x, 0)
            cr.line_to(x, height)
        cr.stroke()
        
        # Draw axes
        cr.set_source_rgb(0.3, 0.3, 0.3)
        cr.set_line_width(1.5)
        cr.move_to(0, height - 1)
        cr.line_to(width, height - 1)
        cr.move_to(1, 0)
        cr.line_to(1, height)
        cr.stroke()
        
        # Draw data if we have any
        if self.chart_max_value > 0 and len(self.bytes_in_history) > 1:
            # Calculate point spacing
            point_spacing = width / max(1, (self.chart_data_points - 1))
            
            # Draw filled area for bytes out (blue)
            cr.set_source_rgba(0.13, 0.59, 0.95, 0.3)  # Semi-transparent blue
            cr.move_to(0, height)
            for i, value in enumerate(self.bytes_out_history):
                x = i * point_spacing
                y = height - (value / self.chart_max_value * height * 0.85)  # Use 85% of height
                cr.line_to(x, y)
            cr.line_to(width, height)
            cr.close_path()
            cr.fill()
            
            # Draw line for bytes out (blue)
            cr.set_source_rgb(0.13, 0.59, 0.95)  # #2196F3
            cr.set_line_width(2)
            for i, value in enumerate(self.bytes_out_history):
                x = i * point_spacing
                y = height - (value / self.chart_max_value * height * 0.85)
                if i == 0:
                    cr.move_to(x, y)
                else:
                    cr.line_to(x, y)
            cr.stroke()
            
            # Draw filled area for bytes in (green)
            cr.set_source_rgba(0.30, 0.69, 0.31, 0.3)  # Semi-transparent green
            cr.move_to(0, height)
            for i, value in enumerate(self.bytes_in_history):
                x = i * point_spacing
                y = height - (value / self.chart_max_value * height * 0.85)
                cr.line_to(x, y)
            cr.line_to(width, height)
            cr.close_path()
            cr.fill()
            
            # Draw line for bytes in (green)
            cr.set_source_rgb(0.30, 0.69, 0.31)  # #4CAF50
            cr.set_line_width(2)
            for i, value in enumerate(self.bytes_in_history):
                x = i * point_spacing
                y = height - (value / self.chart_max_value * height * 0.85)
                if i == 0:
                    cr.move_to(x, y)
                else:
                    cr.line_to(x, y)
            cr.stroke()
        else:
            # No data - show message
            cr.set_source_rgb(0.5, 0.5, 0.5)
            cr.select_font_face("Sans", 0, 0)
            cr.set_font_size(14)
            text = "Waiting for traffic data..."
            text_extents = cr.text_extents(text)
            x = (width - text_extents.width) / 2
            y = height / 2
            cr.move_to(x, y)
            cr.show_text(text)
        
        # Draw border
        cr.set_source_rgb(0.7, 0.7, 0.7)
        cr.set_line_width(1)
        cr.rectangle(0.5, 0.5, width - 1, height - 1)
        cr.stroke()
        
        return False
    
    def update_traffic_chart(self):
        """Update traffic chart data"""
        try:
            # Determine which connection to monitor
            active_connection = None
            if self.monitored_connection:
                # Monitor specific connection
                if self.monitored_connection in self.active_connections:
                    active_connection = self.monitored_connection
            else:
                # Auto mode - find first active connection
                for name, info in self.active_connections.items():
                    if info.get("status") == "Connected" and "vpn_session" in info:
                        active_connection = name
                        break
            
            if active_connection:
                # Get VPN statistics
                conn_info = self.active_connections[active_connection]
                if conn_info.get("vpn_type") == "WireGuard" or conn_info.get("vpn_session"):
                    self.get_vpn_stats(active_connection, conn_info)
            else:
                # No active connection - add zero data points
                self.bytes_in_history.append(0)
                self.bytes_out_history.append(0)
                self.chart_stats_label.set_markup("<small>No active VPN connection</small>")
                self.chart_area.queue_draw()
        except Exception as e:
            print(f"Error updating traffic chart: {e}")
        
        return True  # Continue monitoring
    
    def get_vpn_stats(self, connection_name, session_info):
        """Get VPN statistics for a session"""
        if not isinstance(session_info, dict):
            # Legacy support for direct session path
            session_info = {"vpn_type": "OpenVPN3", "vpn_session": session_info}
        
        vpn_type = session_info.get("vpn_type", "OpenVPN3")
        
        if vpn_type == "OpenVPN3":
            session_path = session_info.get("vpn_session")
            if not session_path:
                return
            
            try:
                result = subprocess.run(
                    ["openvpn3", "session-stats", "--session-path", session_path],
                    capture_output=True,
                    text=True,
                    timeout=5
                )
                
                if result.returncode == 0:
                    bytes_in_value = 0
                    bytes_out_value = 0
                    
                    # Parse statistics
                    for line in result.stdout.split('\n'):
                        # Look for BYTES_IN but not TUN_BYTES_IN
                        if 'BYTES_IN' in line and not line.strip().startswith('TUN_'):
                            try:
                                if '.' in line:
                                    value_str = line.split('.')[-1].strip()
                                    bytes_in_value = int(value_str)
                            except:
                                pass
                        # Look for BYTES_OUT but not TUN_BYTES_OUT
                        elif 'BYTES_OUT' in line and not line.strip().startswith('TUN_'):
                            try:
                                if '.' in line:
                                    value_str = line.split('.')[-1].strip()
                                    bytes_out_value = int(value_str)
                            except:
                                pass
                    
                    # Update chart data
                    self.update_chart_data(connection_name, bytes_in_value, bytes_out_value)
            except Exception as e:
                print(f"Error getting OpenVPN3 stats: {e}")
        
        elif vpn_type == "WireGuard":
            interface_name = session_info.get("vpn_interface", "wg0")
            needs_sudo = session_info.get("needs_sudo", False)
            
            try:
                # Get WireGuard statistics
                if needs_sudo:
                    cmd = ["sudo", "wg", "show", interface_name, "transfer"]
                else:
                    cmd = ["wg", "show", interface_name, "transfer"]
                
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=5
                )
                
                if result.returncode == 0:
                    bytes_in_value = 0
                    bytes_out_value = 0
                    
                    # Parse WireGuard output format:
                    # peer_key<tab>received_bytes<tab>sent_bytes
                    for line in result.stdout.strip().split('\n'):
                        if line:
                            parts = line.split('\t')
                            if len(parts) >= 3:
                                try:
                                    # WireGuard shows received and sent per peer
                                    # We sum all peers for total traffic
                                    bytes_in_value += int(parts[1])
                                    bytes_out_value += int(parts[2])
                                except:
                                    pass
                    
                    # Update chart data
                    self.update_chart_data(connection_name, bytes_in_value, bytes_out_value)
            except Exception as e:
                print(f"Error getting WireGuard stats: {e}")
    
    def update_chart_data(self, connection_name, bytes_in, bytes_out):
        """Update chart with new traffic data"""
        # Get last values for this connection
        last_in = self.last_bytes_in.get(connection_name, 0)
        last_out = self.last_bytes_out.get(connection_name, 0)
        
        # Calculate rates (bytes per update interval)
        if last_in > 0 and bytes_in > last_in:
            in_rate = bytes_in - last_in
        else:
            in_rate = 0
        
        if last_out > 0 and bytes_out > last_out:
            out_rate = bytes_out - last_out
        else:
            out_rate = 0
        
        # Add to history
        self.bytes_in_history.append(in_rate)
        self.bytes_out_history.append(out_rate)
        
        # Update last values
        self.last_bytes_in[connection_name] = bytes_in
        self.last_bytes_out[connection_name] = bytes_out
        
        # Update max value for scaling
        max_rate = max(max(self.bytes_in_history), max(self.bytes_out_history))
        if max_rate > 0:
            # Add some padding to the max value
            self.chart_max_value = max_rate * 1.2
        
        # Update stats label
        in_total_mb = bytes_in / (1024 * 1024) if bytes_in > 0 else 0
        out_total_mb = bytes_out / (1024 * 1024) if bytes_out > 0 else 0
        in_rate_kb = in_rate / 1024 if in_rate > 0 else 0
        out_rate_kb = out_rate / 1024 if out_rate > 0 else 0
        
        self.chart_stats_label.set_markup(
            f"<small>{connection_name} - Total: In {in_total_mb:.1f}MB / Out {out_total_mb:.1f}MB | "
            f"Rate: In {in_rate_kb:.1f}KB/s / Out {out_rate_kb:.1f}KB/s</small>"
        )
        
        # Update connection selector if needed
        self.update_chart_connection_list()
        
        # Redraw chart
        self.chart_area.queue_draw()
    
    def update_chart_connection_list(self):
        """Update the connection selector for the chart"""
        # Get current selection
        current = self.chart_connection_combo.get_active_text()
        
        # Get list of active connections
        active_connections = []
        for name, info in self.active_connections.items():
            if info.get("status") == "Connected":
                active_connections.append(name)
        
        # Check if we need to update the list
        current_items = []
        model = self.chart_connection_combo.get_model()
        for row in model:
            if row[0] != "Auto (Active Connection)":
                current_items.append(row[0])
        
        if set(current_items) != set(active_connections):
            # Update the list
            self.chart_connection_combo.remove_all()
            self.chart_connection_combo.append_text("Auto (Active Connection)")
            for conn in active_connections:
                self.chart_connection_combo.append_text(conn)
            
            # Restore selection
            if current == "Auto (Active Connection)" or current not in active_connections:
                self.chart_connection_combo.set_active(0)
            else:
                # Find and select the current connection
                for i, row in enumerate(self.chart_connection_combo.get_model()):
                    if row[0] == current:
                        self.chart_connection_combo.set_active(i)
                        break
    
    def show_wireguard_install(self, widget):
        """Show WireGuard installation dialog"""
        install_command = package_install_command("wireguard")
        dialog = Gtk.MessageDialog(
            transient_for=self,
            flags=0,
            message_type=Gtk.MessageType.INFO,
            buttons=Gtk.ButtonsType.OK_CANCEL,
            text="Install WireGuard"
        )
        dialog.format_secondary_text(
            "WireGuard is a modern, fast VPN protocol.\n\n"
            "To install WireGuard, run:\n"
            f"{install_command}\n\n"
            "Click OK to copy the command to clipboard."
        )
        
        response = dialog.run()
        dialog.destroy()
        
        if response == Gtk.ResponseType.OK:
            clipboard = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
            clipboard.set_text(install_command, -1)
            self.update_status("WireGuard install command copied to clipboard")

    def show_networkmanager_openvpn_install(self, widget):
        """Show NetworkManager OpenVPN installation dialog"""
        install_command = package_install_command("networkmanager_openvpn")
        dialog = Gtk.MessageDialog(
            transient_for=self,
            flags=0,
            message_type=Gtk.MessageType.INFO,
            buttons=Gtk.ButtonsType.OK_CANCEL,
            text="Install NetworkManager OpenVPN"
        )
        dialog.format_secondary_text(
            f"Detected OS: {OS_INFO['name']} ({OS_INFO['family']})\n\n"
            "This backend uses VPN profiles already configured in KDE/NetworkManager.\n\n"
            "To install NetworkManager OpenVPN support, run:\n"
            f"{install_command}\n\n"
            "Click OK to copy the command to clipboard."
        )

        response = dialog.run()
        dialog.destroy()

        if response == Gtk.ResponseType.OK:
            clipboard = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
            clipboard.set_text(install_command, -1)
            self.update_status("NetworkManager OpenVPN install command copied to clipboard")
    
    def show_openvpn3_install(self, widget):
        """Show OpenVPN3 installation dialog"""
        install_command = package_install_command("openvpn3")
        dialog = Gtk.MessageDialog(
            transient_for=self,
            flags=0,
            message_type=Gtk.MessageType.INFO,
            buttons=Gtk.ButtonsType.OK_CANCEL,
            text="Install OpenVPN3"
        )
        dialog.format_secondary_text(
            f"Detected OS: {OS_INFO['name']} ({OS_INFO['family']})\n\n"
            "OpenVPN3 may require an additional repository or AUR package depending on your distribution.\n\n"
            "Suggested install command:\n"
            f"{install_command}\n\n"
            "For detailed instructions, visit:\n"
            "https://openvpn.net/cloud-docs/openvpn-3-client-for-linux/\n\n"
            "Click OK to copy the suggested command to clipboard."
        )
        
        response = dialog.run()
        dialog.destroy()
        
        if response == Gtk.ResponseType.OK:
            clipboard = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
            clipboard.set_text(install_command, -1)
            self.update_status("OpenVPN3 install command copied to clipboard")
    
    def import_wireguard_config(self, widget):
        """Import WireGuard configuration file"""
        dialog = Gtk.FileChooserDialog(
            title="Import WireGuard Configuration",
            parent=self,
            action=Gtk.FileChooserAction.OPEN
        )
        dialog.add_buttons(
            Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
            "Import", Gtk.ResponseType.OK
        )
        
        # Add file filters
        filter_conf = Gtk.FileFilter()
        filter_conf.set_name("WireGuard configs (*.conf)")
        filter_conf.add_pattern("*.conf")
        dialog.add_filter(filter_conf)
        
        filter_all = Gtk.FileFilter()
        filter_all.set_name("All files")
        filter_all.add_pattern("*")
        dialog.add_filter(filter_all)
        
        response = dialog.run()
        
        if response == Gtk.ResponseType.OK:
            source_file = dialog.get_filename()
            filename = os.path.basename(source_file)
            
            # Ask where to save it
            location_dialog = Gtk.MessageDialog(
                transient_for=self,
                flags=0,
                message_type=Gtk.MessageType.QUESTION,
                buttons=Gtk.ButtonsType.NONE,
                text="Where to save WireGuard config?"
            )
            location_dialog.format_secondary_text(
                f"Config file: {filename}\n\n"
                "Choose location:"
            )
            
            location_dialog.add_button("User Directory\n(~/.config/wireguard)", 1)
            location_dialog.add_button("System Directory\n(/etc/wireguard - requires sudo)", 2)
            location_dialog.add_button("Cancel", Gtk.ResponseType.CANCEL)
            
            location_response = location_dialog.run()
            location_dialog.destroy()
            
            if location_response == 1:
                # User directory
                dest_dir = os.path.expanduser("~/.config/wireguard")
                os.makedirs(dest_dir, exist_ok=True)
                dest_file = os.path.join(dest_dir, filename)
                
                try:
                    shutil.copy2(source_file, dest_file)
                    os.chmod(dest_file, 0o600)  # Secure permissions
                    self.show_info(f"WireGuard config imported to:\n{dest_file}")
                except Exception as e:
                    self.show_error(f"Failed to import config: {str(e)}")
            
            elif location_response == 2:
                # System directory (requires sudo)
                dest_file = f"/etc/wireguard/{filename}"
                
                try:
                    # Use sudo to copy
                    result = subprocess.run(
                        ["sudo", "cp", source_file, dest_file],
                        capture_output=True,
                        text=True
                    )
                    
                    if result.returncode == 0:
                        # Set permissions
                        subprocess.run(["sudo", "chmod", "600", dest_file])
                        self.show_info(f"WireGuard config imported to:\n{dest_file}")
                    else:
                        self.show_error(f"Failed to import config:\n{result.stderr}")
                except Exception as e:
                    self.show_error(f"Failed to import config: {str(e)}")
        
        dialog.destroy()
    
    def show_info(self, message):
        """Show info dialog"""
        dialog = Gtk.MessageDialog(
            transient_for=self,
            flags=0,
            message_type=Gtk.MessageType.INFO,
            buttons=Gtk.ButtonsType.OK,
            text=message
        )
        dialog.run()
        dialog.destroy()
    
    def show_error(self, message):
        """Show error dialog"""
        dialog = Gtk.MessageDialog(
            transient_for=self,
            flags=0,
            message_type=Gtk.MessageType.ERROR,
            buttons=Gtk.ButtonsType.OK,
            text=message
        )
        dialog.run()
        dialog.destroy()
    
    def show_about(self, widget):
        """Show about dialog"""
        dialog = Gtk.AboutDialog()
        dialog.set_transient_for(self)
        dialog.set_program_name("VPN+RDP Manager")
        dialog.set_version("1.0")
        dialog.set_comments("Combined VPN and RDP connection manager\n\nConnect to VPN then RDP with one click")
        dialog.set_authors(["VPN+RDP Manager Contributors"])
        dialog.set_license_type(Gtk.License.MIT_X11)
        dialog.run()
        dialog.destroy()


class ConnectionDialog(Gtk.Dialog):
    """Dialog for creating/editing connection profiles"""
    
    def __init__(self, parent, connection_data, existing_connections):
        if connection_data:
            title = "Edit Connection"
        else:
            title = "New Connection"
        
        Gtk.Dialog.__init__(self, title=title, transient_for=parent)
        self.add_buttons(
            Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
            Gtk.STOCK_SAVE, Gtk.ResponseType.OK
        )
        
        self.set_default_size(600, 800)
        self.connection_data = connection_data or {}
        self.existing_connections = existing_connections
        
        content = self.get_content_area()
        
        # Create notebook for tabs
        notebook = Gtk.Notebook()
        content.pack_start(notebook, True, True, 0)
        
        # Tab 1: Basic Settings
        basic_scrolled = Gtk.ScrolledWindow()
        basic_scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        vbox.set_border_width(10)
        basic_scrolled.add(vbox)
        
        # Connection name
        name_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        vbox.pack_start(name_box, False, False, 0)
        
        label = Gtk.Label(label="Connection Name:")
        label.set_size_request(150, -1)
        label.set_xalign(0)
        name_box.pack_start(label, False, False, 0)
        
        self.name_entry = Gtk.Entry()
        self.name_entry.set_text(self.connection_data.get("name", ""))
        name_box.pack_start(self.name_entry, True, True, 0)
        
        # Connection Mode selection
        mode_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        vbox.pack_start(mode_box, False, False, 0)
        
        label = Gtk.Label(label="Connection Mode:")
        label.set_size_request(150, -1)
        label.set_xalign(0)
        mode_box.pack_start(label, False, False, 0)
        
        self.connection_mode_combo = Gtk.ComboBoxText()
        self.connection_mode_combo.append_text("VPN+RDP")
        self.connection_mode_combo.append_text("VPN Only")
        self.connection_mode_combo.append_text("RDP Only")
        
        # Set default or existing value
        current_mode = self.connection_data.get("connection_mode", "VPN+RDP")
        mode_index = {"VPN+RDP": 0, "VPN Only": 1, "RDP Only": 2}.get(current_mode, 0)
        self.connection_mode_combo.set_active(mode_index)
        
        self.connection_mode_combo.connect("changed", self.on_connection_mode_changed)
        mode_box.pack_start(self.connection_mode_combo, True, True, 0)
        
        # VPN Settings Frame
        self.vpn_frame = Gtk.Frame(label="VPN Settings")
        vbox.pack_start(self.vpn_frame, False, False, 0)
        
        vpn_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        vpn_box.set_border_width(10)
        self.vpn_frame.add(vpn_box)
        
        # VPN Type selection
        type_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        vpn_box.pack_start(type_box, False, False, 0)
        
        label = Gtk.Label(label="VPN Type:")
        label.set_size_request(150, -1)
        label.set_xalign(0)
        type_box.pack_start(label, False, False, 0)
        
        self.vpn_type_combo = Gtk.ComboBoxText()
        vpn_types = []
        if OS_INFO["family"] == "arch":
            vpn_types = ["NetworkManager", "WireGuard", "OpenVPN3"]
        else:
            vpn_types = ["OpenVPN3", "NetworkManager", "WireGuard"]

        for vpn_type in vpn_types:
            if vpn_type == "NetworkManager" and shutil.which("nmcli"):
                self.vpn_type_combo.append_text(vpn_type)
            elif vpn_type == "OpenVPN3" and shutil.which("openvpn3"):
                self.vpn_type_combo.append_text(vpn_type)
            elif vpn_type == "WireGuard" and shutil.which("wg") and shutil.which("wg-quick"):
                self.vpn_type_combo.append_text(vpn_type)
        
        type_box.pack_start(self.vpn_type_combo, True, True, 0)
        
        # Don't connect the signal yet - we'll do it after setting up everything
        
        # VPN Config file
        config_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        vpn_box.pack_start(config_box, False, False, 0)
        
        label = Gtk.Label(label="VPN Config:")
        label.set_size_request(150, -1)
        label.set_xalign(0)
        config_box.pack_start(label, False, False, 0)
        
        # Use ComboBoxText with entry for manual input
        self.vpn_config_combo = Gtk.ComboBoxText.new_with_entry()
        self.vpn_config_entry = self.vpn_config_combo.get_child()  # Get the entry widget
        self.vpn_config_entry.set_placeholder_text("Select or enter VPN profile/config")
        config_box.pack_start(self.vpn_config_combo, True, True, 0)
        
        # Browse button for config file
        self.browse_config_button = Gtk.Button(label="Browse...")
        self.browse_config_button.connect("clicked", self.browse_vpn_config)
        config_box.pack_start(self.browse_config_button, False, False, 0)
        
        # VPN Username (mainly for OpenVPN3)
        self.username_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        vpn_box.pack_start(self.username_box, False, False, 0)
        
        label = Gtk.Label(label="VPN Username:")
        label.set_size_request(150, -1)
        label.set_xalign(0)
        self.username_box.pack_start(label, False, False, 0)
        
        self.vpn_username_entry = Gtk.Entry()
        self.vpn_username_entry.set_placeholder_text("Required for some OpenVPN3 profiles")
        self.vpn_username_entry.set_text(self.connection_data.get("vpn_username", ""))
        self.username_box.pack_start(self.vpn_username_entry, True, True, 0)
        
        # Set initial sensitivity based on VPN type
        current_vpn_type = self.connection_data.get("vpn_type", "")
        if current_vpn_type in ["NetworkManager", "WireGuard"]:
            self.vpn_username_entry.set_sensitive(False)
        
        # RDP Settings Frame
        self.rdp_frame = Gtk.Frame(label="RDP Settings")
        vbox.pack_start(self.rdp_frame, False, False, 0)
        
        rdp_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        rdp_box.set_border_width(10)
        self.rdp_frame.add(rdp_box)
        
        # RDP Host
        host_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        rdp_box.pack_start(host_box, False, False, 0)
        
        label = Gtk.Label(label="RDP Host:")
        label.set_size_request(150, -1)
        label.set_xalign(0)
        host_box.pack_start(label, False, False, 0)
        
        self.rdp_host_entry = Gtk.Entry()
        self.rdp_host_entry.set_placeholder_text("hostname or IP address")
        self.rdp_host_entry.set_text(self.connection_data.get("rdp_host", ""))
        host_box.pack_start(self.rdp_host_entry, True, True, 0)
        
        # RDP Username
        rdp_user_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        rdp_box.pack_start(rdp_user_box, False, False, 0)
        
        label = Gtk.Label(label="RDP Username:")
        label.set_size_request(150, -1)
        label.set_xalign(0)
        rdp_user_box.pack_start(label, False, False, 0)
        
        self.rdp_username_entry = Gtk.Entry()
        self.rdp_username_entry.set_text(self.connection_data.get("rdp_username", ""))
        rdp_user_box.pack_start(self.rdp_username_entry, True, True, 0)
        
        # RDP Domain
        domain_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        rdp_box.pack_start(domain_box, False, False, 0)
        
        label = Gtk.Label(label="RDP Domain:")
        label.set_size_request(150, -1)
        label.set_xalign(0)
        domain_box.pack_start(label, False, False, 0)
        
        self.rdp_domain_entry = Gtk.Entry()
        self.rdp_domain_entry.set_placeholder_text("(optional)")
        self.rdp_domain_entry.set_text(self.connection_data.get("rdp_domain", ""))
        domain_box.pack_start(self.rdp_domain_entry, True, True, 0)
        
        # Add Basic tab to notebook
        notebook.append_page(basic_scrolled, Gtk.Label(label="Basic"))
        
        # Tab 2: Advanced Settings
        advanced_scrolled = Gtk.ScrolledWindow()
        advanced_scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        
        advanced_vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        advanced_vbox.set_border_width(10)
        advanced_scrolled.add(advanced_vbox)
        
        # Display Settings Frame
        display_frame = Gtk.Frame(label="Display Settings")
        advanced_vbox.pack_start(display_frame, False, False, 0)
        
        display_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        display_box.set_border_width(10)
        display_frame.add(display_box)
        
        # Fullscreen checkbox
        self.fullscreen_check = Gtk.CheckButton(label="Fullscreen mode")
        self.fullscreen_check.set_active(self.connection_data.get("rdp_fullscreen", True))
        display_box.pack_start(self.fullscreen_check, False, False, 0)
        
        # Resolution
        res_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        display_box.pack_start(res_box, False, False, 0)
        
        label = Gtk.Label(label="Resolution:")
        label.set_size_request(150, -1)
        label.set_xalign(0)
        res_box.pack_start(label, False, False, 0)
        
        self.resolution_combo = Gtk.ComboBoxText()
        resolutions = ["1920x1080", "1680x1050", "1600x900", "1440x900", 
                       "1366x768", "1280x1024", "1280x720", "1024x768"]
        for res in resolutions:
            self.resolution_combo.append_text(res)
        
        current_res = self.connection_data.get("rdp_resolution", "1920x1080")
        if current_res in resolutions:
            self.resolution_combo.set_active(resolutions.index(current_res))
        else:
            self.resolution_combo.set_active(0)
        
        res_box.pack_start(self.resolution_combo, True, True, 0)
        
        # Multi-monitor settings
        self.multimon_check = Gtk.CheckButton(label="Use multiple monitors")
        self.multimon_check.set_active(self.connection_data.get("multimon", False))
        display_box.pack_start(self.multimon_check, False, False, 0)
        
        # Monitor selection
        monitor_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        display_box.pack_start(monitor_box, False, False, 0)
        
        monitor_label = Gtk.Label(label="Monitors:")
        monitor_label.set_size_request(150, -1)
        monitor_label.set_xalign(0)
        monitor_box.pack_start(monitor_label, False, False, 0)
        
        self.monitor_entry = Gtk.Entry()
        self.monitor_entry.set_placeholder_text("e.g., 0,1 (leave empty for all)")
        selected_monitors = self.connection_data.get("selected_monitors", [])
        if selected_monitors:
            self.monitor_entry.set_text(",".join(str(m) for m in selected_monitors))
        monitor_box.pack_start(self.monitor_entry, True, True, 0)
        
        identify_btn = Gtk.Button(label="Identify")
        identify_btn.connect("clicked", self.identify_monitors)
        monitor_box.pack_start(identify_btn, False, False, 0)
        
        # Performance Frame
        perf_frame = Gtk.Frame(label="Performance Settings")
        advanced_vbox.pack_start(perf_frame, False, False, 0)
        
        perf_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        perf_box.set_border_width(10)
        perf_frame.add(perf_box)
        
        self.disable_fonts_check = Gtk.CheckButton(label="Disable font smoothing")
        self.disable_fonts_check.set_active(self.connection_data.get("disable_fonts", True))
        perf_box.pack_start(self.disable_fonts_check, False, False, 0)
        
        self.disable_wallpaper_check = Gtk.CheckButton(label="Disable wallpaper")
        self.disable_wallpaper_check.set_active(self.connection_data.get("disable_wallpaper", True))
        perf_box.pack_start(self.disable_wallpaper_check, False, False, 0)
        
        self.disable_themes_check = Gtk.CheckButton(label="Disable themes")
        self.disable_themes_check.set_active(self.connection_data.get("disable_themes", True))
        perf_box.pack_start(self.disable_themes_check, False, False, 0)
        
        self.disable_aero_check = Gtk.CheckButton(label="Disable desktop composition")
        self.disable_aero_check.set_active(self.connection_data.get("disable_aero", True))
        perf_box.pack_start(self.disable_aero_check, False, False, 0)
        
        self.disable_drag_check = Gtk.CheckButton(label="Disable full window drag")
        self.disable_drag_check.set_active(self.connection_data.get("disable_drag", True))
        perf_box.pack_start(self.disable_drag_check, False, False, 0)
        
        self.compression_check = Gtk.CheckButton(label="Enable compression")
        self.compression_check.set_active(self.connection_data.get("compression", True))
        perf_box.pack_start(self.compression_check, False, False, 0)
        
        # Audio Frame
        audio_frame = Gtk.Frame(label="Audio Settings")
        advanced_vbox.pack_start(audio_frame, False, False, 0)
        
        audio_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        audio_box.set_border_width(10)
        audio_frame.add(audio_box)
        
        self.audio_local_radio = Gtk.RadioButton.new_with_label_from_widget(None, "Play on this computer")
        self.audio_local_radio.set_active(self.connection_data.get("audio_mode", "local") == "local")
        audio_box.pack_start(self.audio_local_radio, False, False, 0)
        
        self.audio_remote_radio = Gtk.RadioButton.new_with_label_from_widget(self.audio_local_radio, "Play on remote computer")
        self.audio_remote_radio.set_active(self.connection_data.get("audio_mode", "local") == "remote")
        audio_box.pack_start(self.audio_remote_radio, False, False, 0)
        
        self.audio_disabled_radio = Gtk.RadioButton.new_with_label_from_widget(self.audio_local_radio, "Do not play")
        self.audio_disabled_radio.set_active(self.connection_data.get("audio_mode", "local") == "disabled")
        audio_box.pack_start(self.audio_disabled_radio, False, False, 0)
        
        # Local Resources Frame
        resources_frame = Gtk.Frame(label="Local Resources")
        advanced_vbox.pack_start(resources_frame, False, False, 0)
        
        resources_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        resources_box.set_border_width(10)
        resources_frame.add(resources_box)
        
        self.clipboard_check = Gtk.CheckButton(label="Clipboard")
        self.clipboard_check.set_active(self.connection_data.get("clipboard", True))
        resources_box.pack_start(self.clipboard_check, False, False, 0)
        
        self.drives_check = Gtk.CheckButton(label="Share home directory")
        self.drives_check.set_active(self.connection_data.get("redirect_drives", False))
        resources_box.pack_start(self.drives_check, False, False, 0)
        
        # Security Frame
        security_frame = Gtk.Frame(label="Security Settings")
        advanced_vbox.pack_start(security_frame, False, False, 0)
        
        security_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        security_box.set_border_width(10)
        security_frame.add(security_box)
        
        self.nla_check = Gtk.CheckButton(label="Network Level Authentication (NLA)")
        self.nla_check.set_active(self.connection_data.get("nla", True))
        security_box.pack_start(self.nla_check, False, False, 0)
        
        # Add Advanced tab to notebook
        notebook.append_page(advanced_scrolled, Gtk.Label(label="Advanced"))
        
        # Initialize VPN type and configs if editing
        if connection_data:
            # Set VPN type first
            current_vpn_type = connection_data.get("vpn_type", "")
            if current_vpn_type:
                # Try to find and set the current VPN type
                model = self.vpn_type_combo.get_model()
                for i in range(len(model)):
                    if model[i][0] == current_vpn_type:
                        self.vpn_type_combo.set_active(i)
                        break
                else:
                    # If not found, set first available
                    if len(model) > 0:
                        self.vpn_type_combo.set_active(0)
            else:
                # No saved type, set first available
                if self.vpn_type_combo.get_model():
                    self.vpn_type_combo.set_active(0)
            
            # Load configs for the selected VPN type
            self.load_vpn_configs()
            
            # Set current VPN config if editing
            if "vpn_config" in connection_data:
                vpn_config = connection_data["vpn_config"]
                # Always set the text in the entry field
                self.vpn_config_entry.set_text(vpn_config)
                # Then try to find and set the matching config in the combo
                model = self.vpn_config_combo.get_model()
                for i, row in enumerate(model):
                    if row[0] == vpn_config:
                        self.vpn_config_combo.set_active(i)
                        break
        else:
            # New connection - set defaults
            if self.vpn_type_combo.get_model():
                self.vpn_type_combo.set_active(0)
            self.load_vpn_configs()
        
        # Now connect the change signal
        self.vpn_type_combo.connect("changed", self.on_vpn_type_changed)
        
        self.show_all()
        # Apply initial visibility based on connection mode
        self.on_connection_mode_changed(None)
    
    def on_vpn_type_changed(self, widget):
        """Handle VPN type selection change"""
        self.load_vpn_configs()
        
        # Show/hide username field based on VPN type
        vpn_type = self.vpn_type_combo.get_active_text()
        if hasattr(self, 'vpn_username_entry'):
            # NetworkManager and WireGuard handle credentials outside this field.
            self.vpn_username_entry.set_sensitive(vpn_type == "OpenVPN3")
        if hasattr(self, 'browse_config_button'):
            self.browse_config_button.set_sensitive(vpn_type != "NetworkManager")
    
    def on_connection_mode_changed(self, widget):
        """Handle connection mode selection change"""
        mode = self.connection_mode_combo.get_active_text()
        
        if not mode:
            return
        
        # Show/hide frames based on mode
        if mode == "VPN+RDP":
            self.vpn_frame.show()
            self.rdp_frame.show()
        elif mode == "VPN Only":
            self.vpn_frame.show()
            self.rdp_frame.hide()
        elif mode == "RDP Only":
            self.vpn_frame.hide()
            self.rdp_frame.show()
    
    def browse_vpn_config(self, widget):
        """Browse for VPN configuration file"""
        vpn_type = self.vpn_type_combo.get_active_text()

        if vpn_type == "NetworkManager":
            self.show_info("NetworkManager VPN profiles are selected from the list. You can also type an existing profile name.")
            return
        
        dialog = Gtk.FileChooserDialog(
            title=f"Select {vpn_type} Configuration",
            parent=self.get_toplevel(),
            action=Gtk.FileChooserAction.OPEN
        )
        dialog.add_buttons(
            Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
            Gtk.STOCK_OPEN, Gtk.ResponseType.OK
        )
        
        # Add file filters based on VPN type
        if vpn_type == "WireGuard":
            filter_conf = Gtk.FileFilter()
            filter_conf.set_name("WireGuard configs (*.conf)")
            filter_conf.add_pattern("*.conf")
            dialog.add_filter(filter_conf)
            
            # Set default folder
            if os.path.exists("/etc/wireguard"):
                dialog.set_current_folder("/etc/wireguard")
            elif os.path.exists(os.path.expanduser("~/.config/wireguard")):
                dialog.set_current_folder(os.path.expanduser("~/.config/wireguard"))
        elif vpn_type == "OpenVPN3":
            filter_ovpn = Gtk.FileFilter()
            filter_ovpn.set_name("OpenVPN configs (*.ovpn)")
            filter_ovpn.add_pattern("*.ovpn")
            dialog.add_filter(filter_ovpn)
        
        filter_all = Gtk.FileFilter()
        filter_all.set_name("All files")
        filter_all.add_pattern("*")
        dialog.add_filter(filter_all)
        
        response = dialog.run()
        if response == Gtk.ResponseType.OK:
            config_path = dialog.get_filename()
            self.vpn_config_entry.set_text(config_path)
        
        dialog.destroy()
    
    def load_vpn_configs(self):
        """Load available VPN configurations based on selected type"""
        # Clear existing items
        self.vpn_config_combo.remove_all()
        
        vpn_type = self.vpn_type_combo.get_active_text()
        
        if not vpn_type:
            return
        
        if vpn_type == "NetworkManager":
            try:
                result = subprocess.run(
                    ["nmcli", "-t", "--escape", "no", "-f", "NAME,TYPE", "connection", "show"],
                    capture_output=True,
                    text=True,
                    timeout=5
                )

                if result.returncode == 0:
                    configs_found = []
                    for line in result.stdout.splitlines():
                        if ":" not in line:
                            continue
                        name, conn_type = line.rsplit(":", 1)
                        if conn_type in ["vpn", "wireguard"]:
                            configs_found.append(name)

                    for config in sorted(configs_found):
                        self.vpn_config_combo.append_text(config)
            except:
                pass

        elif vpn_type == "OpenVPN3":
            try:
                result = subprocess.run(
                    ["openvpn3", "configs-list"],
                    capture_output=True,
                    text=True,
                    timeout=5
                )
                
                if result.returncode == 0:
                    lines = result.stdout.strip().split('\n')
                    for line in lines[2:]:  # Skip header
                        if line.strip() and not line.startswith('-'):
                            parts = line.split()
                            if len(parts) >= 1:
                                config_path = parts[0]
                                self.vpn_config_combo.append_text(config_path)
            except:
                pass
        
        elif vpn_type == "WireGuard":
            # Load WireGuard configs from common locations
            wg_dirs = [
                "/etc/wireguard",
                os.path.expanduser("~/.config/wireguard"),
                os.path.expanduser("~/wireguard")
            ]
            
            configs_found = []
            for wg_dir in wg_dirs:
                if os.path.exists(wg_dir):
                    try:
                        for file in os.listdir(wg_dir):
                            if file.endswith('.conf'):
                                config_path = os.path.join(wg_dir, file)
                                # Check if readable
                                if os.access(config_path, os.R_OK):
                                    configs_found.append(config_path)
                                else:
                                    # Try with sudo access notation
                                    configs_found.append(f"sudo:{config_path}")
                    except:
                        pass
            
            # Add found configs to combo
            for config in sorted(configs_found):
                self.vpn_config_combo.append_text(config)
        
        # Restore previous selection if it exists
        if self.connection_data and "vpn_config" in self.connection_data:
            vpn_config = self.connection_data["vpn_config"]
            # Set the text in the entry field
            self.vpn_config_entry.set_text(vpn_config)
    
    def get_connection_data(self):
        """Get the connection data from the dialog"""
        name = self.name_entry.get_text().strip()
        
        if not name:
            self.show_error("Please enter a connection name")
            return None
        
        # Check for duplicate names
        if self.connection_data.get("name") != name and name in self.existing_connections:
            self.show_error("A connection with this name already exists")
            return None
        
        # Get connection mode
        connection_mode = self.connection_mode_combo.get_active_text()
        
        # Validate based on connection mode
        if connection_mode in ["VPN+RDP", "VPN Only"]:
            # Get VPN config from the entry field
            vpn_config = self.vpn_config_entry.get_text().strip()
            if not vpn_config:
                self.show_error("Please select or enter a VPN configuration")
                return None
        else:
            vpn_config = ""
        
        if connection_mode in ["VPN+RDP", "RDP Only"]:
            rdp_host = self.rdp_host_entry.get_text().strip()
            if not rdp_host:
                self.show_error("Please enter an RDP host")
                return None
        else:
            rdp_host = ""
        
        # Parse monitor selection
        selected_monitors = []
        monitor_text = self.monitor_entry.get_text().strip()
        if monitor_text:
            try:
                selected_monitors = [int(m.strip()) for m in monitor_text.split(",")]
            except:
                pass
        
        # Determine audio mode
        audio_mode = "local"
        if self.audio_remote_radio.get_active():
            audio_mode = "remote"
        elif self.audio_disabled_radio.get_active():
            audio_mode = "disabled"
        
        return {
            "name": name,
            "connection_mode": connection_mode,
            "vpn_type": self.vpn_type_combo.get_active_text() if connection_mode != "RDP Only" else "",
            "vpn_config": vpn_config,
            "vpn_username": self.vpn_username_entry.get_text().strip() if connection_mode != "RDP Only" else "",
            "rdp_host": rdp_host,
            "rdp_username": self.rdp_username_entry.get_text().strip() if connection_mode != "VPN Only" else "",
            "rdp_domain": self.rdp_domain_entry.get_text().strip() if connection_mode != "VPN Only" else "",
            "rdp_fullscreen": self.fullscreen_check.get_active(),
            "rdp_resolution": self.resolution_combo.get_active_text(),
            "multimon": self.multimon_check.get_active(),
            "selected_monitors": selected_monitors,
            "disable_fonts": self.disable_fonts_check.get_active(),
            "disable_wallpaper": self.disable_wallpaper_check.get_active(),
            "disable_themes": self.disable_themes_check.get_active(),
            "disable_aero": self.disable_aero_check.get_active(),
            "disable_drag": self.disable_drag_check.get_active(),
            "compression": self.compression_check.get_active(),
            "audio_mode": audio_mode,
            "clipboard": self.clipboard_check.get_active(),
            "redirect_drives": self.drives_check.get_active(),
            "nla": self.nla_check.get_active()
        }
    
    def identify_monitors(self, widget=None):
        """Show a numbered overlay on each monitor."""
        try:
            display = Gdk.Display.get_default()
            if display is None:
                self.show_error("Could not get display information")
                return

            n_monitors = display.get_n_monitors()
            if n_monitors == 0:
                self.show_info("No monitors detected")
                return

            # Create identification windows
            id_windows = []

            for index in range(n_monitors):
                monitor = display.get_monitor(index)
                geo = monitor.get_geometry()
                name = monitor.get_model() or f"Output {index}"

                window = Gtk.Window()
                window.set_title(f"Monitor {index}")
                window.set_decorated(False)
                window.set_keep_above(True)

                screen = window.get_screen()
                rgba_visual = screen.get_rgba_visual()
                transparent = rgba_visual is not None and screen.is_composited()
                if transparent:
                    window.set_visual(rgba_visual)
                    window.set_app_paintable(True)

                badge = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
                badge.set_border_width(30)
                badge.set_halign(Gtk.Align.CENTER)
                badge.set_valign(Gtk.Align.CENTER)
                badge.get_style_context().add_class("badge")
                window.add(badge)

                css_provider = Gtk.CssProvider()
                window_bg = b"rgba(0,0,0,0)" if transparent else b"#2196F3"
                css_provider.load_from_data(b"""
                    window {
                        background-color: %s;
                    }
                    box.badge {
                        background-color: rgba(33, 150, 243, 0.92);
                        border-radius: 28px;
                        padding: 24px 56px;
                    }
                    box.badge label {
                        color: white;
                        font-size: 120px;
                        font-weight: bold;
                    }
                    box.badge label.info {
                        font-size: 24px;
                        font-weight: normal;
                    }
                """ % window_bg)

                style_context = window.get_style_context()
                style_context.add_provider(css_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
                badge.get_style_context().add_provider(css_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

                # Monitor number
                number_label = Gtk.Label(label=str(index))
                badge.pack_start(number_label, True, True, 0)

                # Monitor info
                info_label = Gtk.Label(label=f"{name}\n{geo.width}x{geo.height}")
                info_label.get_style_context().add_class("info")
                badge.pack_start(info_label, False, False, 0)

                # Close instruction
                close_label = Gtk.Label(label="Press ESC or click to close")
                close_label.get_style_context().add_class("info")
                badge.pack_start(close_label, False, False, 0)

                # Connect events
                window.connect("button-press-event", lambda w, e: w.destroy())
                window.connect("key-press-event", lambda w, e: w.destroy() if e.keyval == Gdk.KEY_Escape else None)

                window.show_all()
                window.fullscreen_on_monitor(window.get_screen(), index)
                id_windows.append(window)

            # Auto-close after 5 seconds
            def close_all():
                for w in id_windows:
                    if w.get_visible():
                        w.destroy()
                return False

            GLib.timeout_add_seconds(5, close_all)

        except Exception as e:
            self.show_error(f"Error identifying monitors: {str(e)}")
    
    def show_info(self, message):
        """Show info dialog"""
        dialog = Gtk.MessageDialog(
            transient_for=self,
            flags=0,
            message_type=Gtk.MessageType.INFO,
            buttons=Gtk.ButtonsType.OK,
            text=message
        )
        dialog.run()
        dialog.destroy()
    
    def show_error(self, message):
        """Show error dialog"""
        dialog = Gtk.MessageDialog(
            transient_for=self,
            flags=0,
            message_type=Gtk.MessageType.ERROR,
            buttons=Gtk.ButtonsType.OK,
            text=message
        )
        dialog.run()
        dialog.destroy()


if __name__ == "__main__":
    win = VPNRDPManager()
    win.show_all()
    Gtk.main()
