#!/usr/bin/env python3

"""
VPN+RDP Combined GUI - Connect to VPN then RDP with one click
Copyright (c) 2024

MIT License
"""

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, GLib, Gdk
import subprocess
import threading
import os
import shutil
import json
import time
import signal
import re
from collections import deque

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
        
        # Help button
        help_button = Gtk.ToolButton()
        help_button.set_label("Help")
        help_button.set_icon_name("help-about")
        toolbar.insert(help_button, 4)
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
        self.liststore = Gtk.ListStore(str, str, str, str, str)  # Name, VPN Config, RDP Host, Username, Status
        
        # Tree view
        self.treeview = Gtk.TreeView(model=self.liststore)
        scrolled.add(self.treeview)
        
        # Columns
        renderer = Gtk.CellRendererText()
        column = Gtk.TreeViewColumn("Connection Name", renderer, text=0)
        column.set_resizable(True)
        column.set_min_width(150)
        self.treeview.append_column(column)
        
        column = Gtk.TreeViewColumn("VPN Config", renderer, text=1)
        column.set_resizable(True)
        self.treeview.append_column(column)
        
        column = Gtk.TreeViewColumn("RDP Host", renderer, text=2)
        column.set_resizable(True)
        self.treeview.append_column(column)
        
        column = Gtk.TreeViewColumn("RDP User", renderer, text=3)
        column.set_resizable(True)
        self.treeview.append_column(column)
        
        # Status column with color
        status_renderer = Gtk.CellRendererText()
        column = Gtk.TreeViewColumn("Status", status_renderer, text=4)
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
    
    def status_cell_data_func(self, column, cell, model, iter, data):
        """Color code the status column"""
        status = model.get_value(iter, 4)
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
        
        if not shutil.which("openvpn3"):
            missing.append("OpenVPN3")
        
        if not shutil.which("xfreerdp") and not shutil.which("xfreerdp3"):
            missing.append("FreeRDP")
        
        if missing:
            dialog = Gtk.MessageDialog(
                transient_for=self,
                flags=0,
                message_type=Gtk.MessageType.WARNING,
                buttons=Gtk.ButtonsType.OK,
                text="Missing Dependencies"
            )
            dialog.format_secondary_text(
                f"The following programs are not installed:\n{', '.join(missing)}\n\n"
                "Please install them for full functionality:\n"
                "• OpenVPN3: sudo apt install openvpn3\n"
                "• FreeRDP: sudo apt install freerdp2-x11"
            )
            dialog.run()
            dialog.destroy()
    
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
            self.liststore.append([
                name,
                os.path.basename(conn.get("vpn_config", "")),
                conn.get("rdp_host", ""),
                conn.get("rdp_username", ""),
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
        dialog = Gtk.Dialog(
            title=f"Connecting to {name}",
            parent=self,
            flags=Gtk.DialogFlags.MODAL
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
        details_buffer.set_text(f"VPN Config: {conn.get('vpn_config', 'N/A')}\nRDP Host: {conn.get('rdp_host', 'N/A')}")
        
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
        
        dialog.destroy()
        self.connecting_dialog = None
    
    def connection_worker_with_dialog(self, name, conn, dialog):
        """Worker thread for establishing connection with dialog updates"""
        try:
            # Update dialog: Connecting to VPN
            GLib.idle_add(self.connecting_status_label.set_text, "Establishing VPN connection...")
            GLib.idle_add(self.connecting_progress.set_fraction, 0.25)
            
            if self.connecting_canceled:
                return
            
            # Connect to VPN
            vpn_success = self.connect_vpn(name, conn)
            
            if not vpn_success:
                GLib.idle_add(self.connecting_status_label.set_text, "VPN connection failed!")
                GLib.idle_add(self.update_connection_status, name, "VPN Failed")
                GLib.idle_add(self.update_status, f"VPN connection failed for {name}")
                GLib.idle_add(self.update_buttons, False)
                time.sleep(2)  # Show error briefly
                GLib.idle_add(dialog.response, Gtk.ResponseType.CLOSE)
                return
            
            if self.connecting_canceled:
                self.disconnect_vpn(name)
                return
            
            # Update dialog: VPN connected, connecting to RDP
            GLib.idle_add(self.connecting_status_label.set_text, "VPN connected! Establishing RDP connection...")
            GLib.idle_add(self.connecting_progress.set_fraction, 0.75)
            
            # Wait for VPN to stabilize
            time.sleep(3)
            
            if self.connecting_canceled:
                self.disconnect_vpn(name)
                return
            
            # Connect to RDP
            rdp_success = self.connect_rdp(name, conn)
            
            if rdp_success:
                GLib.idle_add(self.connecting_status_label.set_text, "Connection established successfully!")
                GLib.idle_add(self.connecting_progress.set_fraction, 1.0)
                GLib.idle_add(self.update_connection_status, name, "Connected")
                GLib.idle_add(self.update_status, f"Connected to {name}")
                GLib.idle_add(self.update_buttons, True)
                time.sleep(1)  # Show success briefly
                GLib.idle_add(dialog.response, Gtk.ResponseType.OK)
            else:
                # RDP failed, disconnect VPN
                GLib.idle_add(self.connecting_status_label.set_text, "RDP connection failed!")
                self.disconnect_vpn(name)
                GLib.idle_add(self.update_connection_status, name, "RDP Failed")
                GLib.idle_add(self.update_status, f"RDP connection failed for {name}")
                GLib.idle_add(self.update_buttons, False)
                time.sleep(2)  # Show error briefly
                GLib.idle_add(dialog.response, Gtk.ResponseType.CLOSE)
        
        except Exception as e:
            GLib.idle_add(self.connecting_status_label.set_text, f"Error: {str(e)}")
            GLib.idle_add(self.update_connection_status, name, "Error")
            GLib.idle_add(self.update_status, f"Error connecting to {name}: {str(e)}")
            GLib.idle_add(self.update_buttons, False)
            time.sleep(2)  # Show error briefly
            GLib.idle_add(dialog.response, Gtk.ResponseType.CLOSE)
    
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
        vpn_config = conn.get("vpn_config")
        vpn_username = conn.get("vpn_username")
        vpn_password = self.get_password(name, "vpn")
        
        if not vpn_config or not os.path.exists(vpn_config):
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
                            "vpn_session": session_path,
                            "status": "VPN Connected"
                        }
                        return True
                
                # Try alternative format
                if '/net/openvpn/v3/sessions/' in stdout:
                    import re
                    matches = re.findall(r'/net/openvpn/v3/sessions/[a-f0-9s]+', stdout)
                    if matches:
                        self.active_connections[name] = {
                            "vpn_session": matches[0],
                            "status": "VPN Connected"
                        }
                        return True
            
            return False
        
        except Exception as e:
            print(f"VPN connection error: {e}")
            return False
    
    def connect_rdp(self, name, conn):
        """Connect to RDP"""
        rdp_host = conn.get("rdp_host")
        rdp_username = conn.get("rdp_username")
        rdp_domain = conn.get("rdp_domain", "")
        rdp_password = self.get_password(name, "rdp")
        
        if not rdp_host:
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
        
        # Disconnect RDP first
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
        
        # Then disconnect VPN
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
            session = self.active_connections[name].get("vpn_session")
            if session:
                try:
                    subprocess.run(
                        ["openvpn3", "session-manage", "--session-path", session, "--disconnect"],
                        capture_output=True,
                        timeout=5
                    )
                except:
                    pass
    
    def monitor_connections(self):
        """Monitor active connections"""
        for name in list(self.active_connections.keys()):
            conn_info = self.active_connections[name]
            
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
                row[4] = status
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
            parent=self,
            flags=0
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
                vpn_session = self.active_connections[active_connection].get("vpn_session")
                if vpn_session:
                    self.get_vpn_stats(active_connection, vpn_session)
            else:
                # No active connection - add zero data points
                self.bytes_in_history.append(0)
                self.bytes_out_history.append(0)
                self.chart_stats_label.set_markup("<small>No active VPN connection</small>")
                self.chart_area.queue_draw()
        except Exception as e:
            print(f"Error updating traffic chart: {e}")
        
        return True  # Continue monitoring
    
    def get_vpn_stats(self, connection_name, session_path):
        """Get VPN statistics for a session"""
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
            print(f"Error getting VPN stats: {e}")
    
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
        
        Gtk.Dialog.__init__(self, title=title, parent=parent, flags=0)
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
        
        # VPN Settings Frame
        vpn_frame = Gtk.Frame(label="VPN Settings")
        vbox.pack_start(vpn_frame, False, False, 0)
        
        vpn_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        vpn_box.set_border_width(10)
        vpn_frame.add(vpn_box)
        
        # VPN Config file
        config_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        vpn_box.pack_start(config_box, False, False, 0)
        
        label = Gtk.Label(label="VPN Config:")
        label.set_size_request(150, -1)
        label.set_xalign(0)
        config_box.pack_start(label, False, False, 0)
        
        self.vpn_config_combo = Gtk.ComboBoxText()
        self.load_vpn_configs()
        config_box.pack_start(self.vpn_config_combo, True, True, 0)
        
        # VPN Username
        username_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        vpn_box.pack_start(username_box, False, False, 0)
        
        label = Gtk.Label(label="VPN Username:")
        label.set_size_request(150, -1)
        label.set_xalign(0)
        username_box.pack_start(label, False, False, 0)
        
        self.vpn_username_entry = Gtk.Entry()
        self.vpn_username_entry.set_text(self.connection_data.get("vpn_username", ""))
        username_box.pack_start(self.vpn_username_entry, True, True, 0)
        
        # RDP Settings Frame
        rdp_frame = Gtk.Frame(label="RDP Settings")
        vbox.pack_start(rdp_frame, False, False, 0)
        
        rdp_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        rdp_box.set_border_width(10)
        rdp_frame.add(rdp_box)
        
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
        
        # Set current VPN config if editing
        if connection_data and "vpn_config" in connection_data:
            vpn_config = connection_data["vpn_config"]
            # Find and set the matching config
            model = self.vpn_config_combo.get_model()
            for i, row in enumerate(model):
                if row[0] == vpn_config:
                    self.vpn_config_combo.set_active(i)
                    break
        
        self.show_all()
    
    def load_vpn_configs(self):
        """Load available VPN configurations"""
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
        
        vpn_config = self.vpn_config_combo.get_active_text()
        if not vpn_config:
            self.show_error("Please select a VPN configuration")
            return None
        
        rdp_host = self.rdp_host_entry.get_text().strip()
        if not rdp_host:
            self.show_error("Please enter an RDP host")
            return None
        
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
            "vpn_config": vpn_config,
            "vpn_username": self.vpn_username_entry.get_text().strip(),
            "rdp_host": rdp_host,
            "rdp_username": self.rdp_username_entry.get_text().strip(),
            "rdp_domain": self.rdp_domain_entry.get_text().strip(),
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
    
    def identify_monitors(self, widget):
        """Show monitor identification windows"""
        try:
            # Get monitor information using xrandr
            result = subprocess.run(
                ["xrandr", "--query"],
                capture_output=True,
                text=True,
                timeout=5
            )
            
            if result.returncode != 0:
                self.show_error("Could not get monitor information")
                return
            
            # Parse xrandr output
            monitors = []
            monitor_index = 0
            
            for line in result.stdout.split('\n'):
                if ' connected' in line and not 'disconnected' in line:
                    # Extract monitor info
                    parts = line.split()
                    name = parts[0]
                    
                    # Find resolution and position
                    for part in parts:
                        match = re.match(r'(\d+)x(\d+)\+(\d+)\+(\d+)', part)
                        if match:
                            width = int(match.group(1))
                            height = int(match.group(2))
                            x = int(match.group(3))
                            y = int(match.group(4))
                            monitors.append({
                                'index': monitor_index,
                                'name': name,
                                'width': width,
                                'height': height,
                                'x': x,
                                'y': y
                            })
                            monitor_index += 1
                            break
            
            if not monitors:
                self.show_info("No monitors detected")
                return
            
            # Create identification windows
            id_windows = []
            
            for mon in monitors:
                window = Gtk.Window()
                window.set_title(f"Monitor {mon['index']}")
                window.set_decorated(False)
                window.set_keep_above(True)
                window.set_default_size(400, 300)
                
                # Position window on the monitor
                window.move(mon['x'] + (mon['width'] - 400) // 2,
                           mon['y'] + (mon['height'] - 300) // 2)
                
                # Create content
                vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
                vbox.set_border_width(20)
                window.add(vbox)
                
                # Add background color
                css_provider = Gtk.CssProvider()
                css_provider.load_from_data(b"""
                    window {
                        background-color: #2196F3;
                    }
                    label {
                        color: white;
                        font-size: 48px;
                        font-weight: bold;
                    }
                    label.info {
                        font-size: 18px;
                        font-weight: normal;
                    }
                """)
                
                style_context = window.get_style_context()
                style_context.add_provider(css_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
                
                # Monitor number
                number_label = Gtk.Label(label=str(mon['index']))
                number_label.get_style_context().add_class("number")
                vbox.pack_start(number_label, True, True, 0)
                
                # Monitor info
                info_label = Gtk.Label(label=f"{mon['name']}\n{mon['width']}x{mon['height']}")
                info_label.get_style_context().add_class("info")
                vbox.pack_start(info_label, False, False, 0)
                
                # Close instruction
                close_label = Gtk.Label(label="Press ESC or click to close")
                close_label.get_style_context().add_class("info")
                vbox.pack_start(close_label, False, False, 0)
                
                # Connect events
                window.connect("button-press-event", lambda w, e: w.destroy())
                window.connect("key-press-event", lambda w, e: w.destroy() if e.keyval == Gdk.KEY_Escape else None)
                
                window.show_all()
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
    win.connect("destroy", Gtk.main_quit)
    win.show_all()
    Gtk.main()