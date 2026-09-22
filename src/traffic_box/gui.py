"""Modern Libadwaita / GTK4 GUI launcher for Traffic-Box profiles with Latency & Ping testing."""

import concurrent.futures
import json
import os
import re
import signal
import socket
import subprocess
import threading
import time
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk, Pango  # noqa: E402

from traffic_box.sub import (
    DEFAULT_SUB_URL,
    get_profiles_dir,
    get_sub_url_file,
    update_subscription,
)

CUSTOM_CSS = """
/* Traffic Box Modern Theme Styling */
.main-window {
    background: @window_bg_color;
}

.hero-card {
    background: alpha(@card_bg_color, 0.85);
    border-radius: 16px;
    border: 1px solid alpha(@borders, 0.6);
    padding: 16px;
}

.status-dot {
    min-width: 12px;
    min-height: 12px;
    border-radius: 50%;
    margin-right: 6px;
}

.status-dot.disconnected {
    background-color: #888888;
    box-shadow: 0 0 0 2px alpha(#888888, 0.2);
}

.status-dot.connected {
    background-color: #2ec27e;
    box-shadow: 0 0 8px 2px alpha(#2ec27e, 0.4);
}

.status-dot.working {
    background-color: #e5a50a;
    box-shadow: 0 0 8px 2px alpha(#e5a50a, 0.4);
}

.status-title {
    font-size: 1.15rem;
    font-weight: 700;
}

.status-subtitle {
    font-size: 0.85rem;
    opacity: 0.75;
}

.uptime-label {
    font-family: monospace;
    font-size: 0.95rem;
    font-weight: 600;
    padding: 4px 10px;
    border-radius: 8px;
    background: alpha(@window_bg_color, 0.8);
    border: 1px solid alpha(@borders, 0.4);
}

.hero-toggle-btn {
    font-size: 1.05rem;
    font-weight: bold;
    padding: 10px 24px;
    border-radius: 12px;
}

.pill-badge {
    font-size: 0.75rem;
    font-weight: 600;
    padding: 3px 8px;
    border-radius: 10px;
    background: alpha(@accent_color, 0.15);
    color: @accent_color;
    border: 1px solid alpha(@accent_color, 0.3);
}

/* Latency Badge Styles */
.latency-badge {
    font-size: 0.8rem;
    font-weight: 700;
    font-family: monospace;
    padding: 4px 10px;
    border-radius: 8px;
    margin-start: 4px;
}

.latency-good {
    background: alpha(#2ec27e, 0.2);
    color: #2ec27e;
    border: 1px solid alpha(#2ec27e, 0.4);
}

.latency-medium {
    background: alpha(#e5a50a, 0.2);
    color: #e5a50a;
    border: 1px solid alpha(#e5a50a, 0.4);
}

.latency-bad {
    background: alpha(#e66100, 0.2);
    color: #e66100;
    border: 1px solid alpha(#e66100, 0.4);
}

.latency-timeout {
    background: alpha(#e01b24, 0.2);
    color: #e01b24;
    border: 1px solid alpha(#e01b24, 0.4);
}

.log-terminal {
    font-family: "JetBrains Mono", "Fira Code", "Cascadia Code", "Source Code Pro", monospace;
    font-size: 0.82rem;
    background-color: #12151a;
    color: #e6edf3;
    padding: 12px;
    border-radius: 12px;
    border: 1px solid alpha(#ffffff, 0.08);
}

.log-tag-info {
    color: #58a6ff;
    font-weight: 600;
}

.log-tag-warn {
    color: #d29922;
    font-weight: 600;
}

.log-tag-error {
    color: #f85149;
    font-weight: 700;
}

.log-tag-system {
    color: #a371f7;
    font-weight: 600;
}

.log-tag-success {
    color: #3fb950;
    font-weight: 600;
}

.sub-entry-box {
    background: alpha(@card_bg_color, 0.6);
    border-radius: 12px;
    padding: 10px 14px;
    border: 1px solid alpha(@borders, 0.4);
}
"""


def is_singbox_config(path: Path) -> bool:
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return False
    if not isinstance(data, dict) or "outbounds" not in data:
        return False
    return "loglevel" not in data.get("log", {})


def get_profile_paths() -> list[Path]:
    profiles_dir = get_profiles_dir()
    return sorted(
        (p for p in profiles_dir.glob("*.json") if is_singbox_config(p)),
        key=lambda p: p.name,
    )


def tcp_ping(host: str, port: int, timeout: float = 2.5) -> int | None:
    """Measure TCP handshake round-trip time in milliseconds."""
    try:
        t0 = time.perf_counter()
        s = socket.create_connection((host, int(port)), timeout=timeout)
        t1 = time.perf_counter()
        s.close()
        return round((t1 - t0) * 1000)
    except Exception:
        return None


def get_profile_server_info(path: Path) -> tuple[str, int] | None:
    try:
        data = json.loads(path.read_text())
        for ob in data.get("outbounds", []):
            if ob.get("server") and ob.get("server_port"):
                return ob["server"], int(ob["server_port"])
    except Exception:
        pass
    return None


class TrafficBoxWindow(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="Traffic Box")
        self.set_default_size(780, 720)
        self.set_size_request(580, 540)

        self.proc: subprocess.Popen | None = None
        self.paths: list[Path] = []
        self.ping_results: dict[str, int | None] = {}
        self.connected_time: float | None = None
        self.timer_source_id = None
        self.auto_scroll = True

        self.setup_ui()
        self.refresh_profiles()
        self.load_saved_sub_url()

    def setup_ui(self):
        self.add_css_class("main-window")

        # Main Toast Overlay for floating notifications
        self.toast_overlay = Adw.ToastOverlay()
        self.set_content(self.toast_overlay)

        # Outer Box
        root_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.toast_overlay.set_child(root_box)

        # Header Bar
        header = Adw.HeaderBar()
        root_box.append(header)

        title_widget = Adw.WindowTitle(
            title="Traffic Box",
            subtitle="Transparent Smart Routing & Subscription Manager",
        )
        header.set_title_widget(title_widget)

        # Header End Controls: Ping All, Refresh, Settings
        ping_all_btn = Gtk.Button(
            icon_name="network-transmit-receive-symbolic",
            tooltip_text="Test Latency / Ping All Nodes",
        )
        ping_all_btn.connect("clicked", lambda _: self.on_ping_all_clicked())
        header.pack_end(ping_all_btn)

        refresh_btn = Gtk.Button(
            icon_name="view-refresh-symbolic",
            tooltip_text="Reload Profiles from Disk",
        )
        refresh_btn.connect("clicked", lambda _: self.refresh_profiles(show_toast=True))
        header.pack_end(refresh_btn)

        self.sub_settings_btn = Gtk.Button(
            icon_name="preferences-system-symbolic",
            tooltip_text="Subscription URL Settings",
        )
        self.sub_settings_btn.connect("clicked", self.toggle_sub_panel)
        header.pack_end(self.sub_settings_btn)

        # Main Content Scroller
        scrolled = Gtk.ScrolledWindow(vexpand=True, hexpand=True)
        root_box.append(scrolled)

        clamp = Adw.Clamp(maximum_size=820, tightening_threshold=600)
        scrolled.set_child(clamp)

        content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        content_box.set_margin_top(14)
        content_box.set_margin_bottom(14)
        content_box.set_margin_start(16)
        content_box.set_margin_end(16)
        clamp.set_child(content_box)

        # 1. HERO CONNECTION STATUS CARD
        content_box.append(self.build_hero_card())

        # 2. SUBSCRIPTION CONFIG COLLAPSIBLE PANEL
        self.sub_panel = self.build_sub_panel()
        content_box.append(self.sub_panel)

        # 3. PROFILE SELECTION & ACTIONS CARD
        content_box.append(self.build_profile_card())

        # 4. LOGS & DIAGNOSTICS CARD
        content_box.append(self.build_logs_card())

        self.connect("close-request", self.on_close)

    def build_hero_card(self) -> Gtk.Widget:
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        card.add_css_class("hero-card")

        top_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        top_row.set_valign(Gtk.Align.CENTER)
        card.append(top_row)

        # Status Icon/Dot & Labels
        status_info = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        status_info.set_hexpand(True)
        status_info.set_valign(Gtk.Align.CENTER)
        top_row.append(status_info)

        self.status_dot = Gtk.Box()
        self.status_dot.add_css_class("status-dot")
        self.status_dot.add_css_class("disconnected")
        self.status_dot.set_valign(Gtk.Align.CENTER)
        status_info.append(self.status_dot)

        text_vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        status_info.append(text_vbox)

        self.status_title = Gtk.Label(label="Disconnected", xalign=0)
        self.status_title.add_css_class("status-title")
        text_vbox.append(self.status_title)

        self.status_subtitle = Gtk.Label(label="Select a profile and press Connect", xalign=0)
        self.status_subtitle.add_css_class("status-subtitle")
        text_vbox.append(self.status_subtitle)

        # Live Uptime Counter
        self.uptime_label = Gtk.Label(label="00:00:00")
        self.uptime_label.add_css_class("uptime-label")
        self.uptime_label.set_visible(False)
        top_row.append(self.uptime_label)

        # Hero Action Button (Connect / Disconnect)
        self.hero_btn = Gtk.Button(label="Connect")
        self.hero_btn.add_css_class("suggested-action")
        self.hero_btn.add_css_class("hero-toggle-btn")
        self.hero_btn.connect("clicked", self.on_toggle)
        top_row.append(self.hero_btn)

        # Feature badges row
        badges_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        badges_row.set_margin_top(4)
        card.append(badges_row)

        tun_badge = Gtk.Label(label="TUN: sing-tun")
        tun_badge.add_css_class("pill-badge")
        badges_row.append(tun_badge)

        bypass_badge = Gtk.Label(label="Bypass: Iran Domains (.ir)")
        bypass_badge.add_css_class("pill-badge")
        badges_row.append(bypass_badge)

        dns_badge = Gtk.Label(label="DNS: Hijack & Zero-Leak")
        dns_badge.add_css_class("pill-badge")
        badges_row.append(dns_badge)

        self.hero_ping_badge = Gtk.Label(label="Ping: --")
        self.hero_ping_badge.add_css_class("pill-badge")
        self.hero_ping_badge.set_visible(False)
        badges_row.append(self.hero_ping_badge)

        return card

    def build_sub_panel(self) -> Gtk.Widget:
        expander = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        expander.add_css_class("sub-entry-box")
        expander.set_visible(False)

        lbl_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        expander.append(lbl_row)

        sub_title = Gtk.Label(label="Subscription URL", xalign=0)
        sub_title.add_css_class("heading")
        lbl_row.append(sub_title)

        entry_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        expander.append(entry_row)

        self.sub_entry = Gtk.Entry()
        self.sub_entry.set_placeholder_text("https://domain.com/sub/...")
        self.sub_entry.set_hexpand(True)
        entry_row.append(self.sub_entry)

        save_btn = Gtk.Button(label="Save URL")
        save_btn.connect("clicked", self.on_save_sub_url)
        entry_row.append(save_btn)

        return expander

    def build_profile_card(self) -> Gtk.Widget:
        group = Adw.PreferencesGroup(title="Profile & Latency")

        # Row 1: Profile Selector + Single Ping Button + Latency Badge
        self.profile_row = Adw.ActionRow(
            title="Active Routing Profile",
            subtitle="Choose a single node or 00-auto for automatic latency failover",
        )
        group.add(self.profile_row)

        # Selected Node Latency Badge
        self.selected_latency_badge = Gtk.Label(label="")
        self.selected_latency_badge.add_css_class("latency-badge")
        self.selected_latency_badge.set_valign(Gtk.Align.CENTER)
        self.selected_latency_badge.set_visible(False)
        self.profile_row.add_suffix(self.selected_latency_badge)

        # Single Node Ping Button
        self.single_ping_btn = Gtk.Button(
            icon_name="network-transmit-receive-symbolic",
            tooltip_text="Ping Selected Profile",
        )
        self.single_ping_btn.set_valign(Gtk.Align.CENTER)
        self.single_ping_btn.connect("clicked", lambda _: self.on_ping_selected_clicked())
        self.profile_row.add_suffix(self.single_ping_btn)

        # Dropdown
        self.combo = Gtk.DropDown.new_from_strings(["(loading profiles...)"])
        self.combo.set_valign(Gtk.Align.CENTER)
        self.combo.connect("notify::selected", self.on_profile_changed)
        self.profile_row.add_suffix(self.combo)

        # Row 2: Batch Actions (Ping All & Update Sub)
        self.action_row = Adw.ActionRow(
            title="Subscription & Batch Testing",
            subtitle="Test latency across all endpoints or sync latest subscription configs",
        )
        group.add(self.action_row)

        self.ping_all_spinner = Gtk.Spinner()
        self.ping_all_spinner.set_valign(Gtk.Align.CENTER)
        self.action_row.add_suffix(self.ping_all_spinner)

        self.ping_all_btn = Gtk.Button(label="⚡ Ping All")
        self.ping_all_btn.set_valign(Gtk.Align.CENTER)
        self.ping_all_btn.set_tooltip_text("Measure latency for all profiles concurrently")
        self.ping_all_btn.connect("clicked", lambda _: self.on_ping_all_clicked())
        self.action_row.add_suffix(self.ping_all_btn)

        self.sub_spinner = Gtk.Spinner()
        self.sub_spinner.set_valign(Gtk.Align.CENTER)
        self.action_row.add_suffix(self.sub_spinner)

        self.update_sub_btn = Gtk.Button(label="Update Sub")
        self.update_sub_btn.set_valign(Gtk.Align.CENTER)
        self.update_sub_btn.connect("clicked", self.on_update_clicked)
        self.action_row.add_suffix(self.update_sub_btn)

        return group

    def build_logs_card(self) -> Gtk.Widget:
        group = Adw.PreferencesGroup(title="Live Diagnostics & Logs")

        # Controls row above logs
        ctrl_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        ctrl_row.set_margin_bottom(6)
        group.add(ctrl_row)

        log_count_lbl = Gtk.Label(label="Console Stream", xalign=0)
        log_count_lbl.add_css_class("dim-label")
        log_count_lbl.set_hexpand(True)
        ctrl_row.append(log_count_lbl)

        # Auto-scroll Toggle
        scroll_btn = Gtk.ToggleButton(
            icon_name="go-bottom-symbolic",
            tooltip_text="Auto-scroll to latest log",
            active=True,
        )
        scroll_btn.connect("toggled", lambda b: setattr(self, "auto_scroll", b.get_active()))
        ctrl_row.append(scroll_btn)

        # Copy Logs Button
        copy_btn = Gtk.Button(
            icon_name="edit-copy-symbolic",
            tooltip_text="Copy Logs to Clipboard",
        )
        copy_btn.connect("clicked", self.on_copy_logs)
        ctrl_row.append(copy_btn)

        # Clear Logs Button
        clear_btn = Gtk.Button(
            icon_name="edit-clear-symbolic",
            tooltip_text="Clear Console Logs",
        )
        clear_btn.connect("clicked", self.on_clear_logs)
        ctrl_row.append(clear_btn)

        # Text View for Logs
        self.buffer = Gtk.TextBuffer()
        self.setup_log_tags()

        self.view = Gtk.TextView(
            buffer=self.buffer,
            editable=False,
            monospace=True,
            wrap_mode=Gtk.WrapMode.WORD_CHAR,
        )
        self.view.add_css_class("log-terminal")

        self.log_scroller = Gtk.ScrolledWindow(child=self.view)
        self.log_scroller.set_min_content_height(240)
        self.log_scroller.set_vexpand(True)
        group.add(self.log_scroller)

        return group

    def setup_log_tags(self):
        tag_table = self.buffer.get_tag_table()

        info_tag = Gtk.TextTag.new("info")
        info_tag.set_property("foreground", "#58a6ff")
        tag_table.add(info_tag)

        warn_tag = Gtk.TextTag.new("warn")
        warn_tag.set_property("foreground", "#d29922")
        tag_table.add(warn_tag)

        error_tag = Gtk.TextTag.new("error")
        error_tag.set_property("foreground", "#f85149")
        error_tag.set_property("weight", Pango.Weight.BOLD)
        tag_table.add(error_tag)

        system_tag = Gtk.TextTag.new("system")
        system_tag.set_property("foreground", "#a371f7")
        system_tag.set_property("weight", Pango.Weight.BOLD)
        tag_table.add(system_tag)

        success_tag = Gtk.TextTag.new("success")
        success_tag.set_property("foreground", "#3fb950")
        tag_table.add(success_tag)

    def log(self, line: str):
        line = line.rstrip()
        if not line:
            return

        end = self.buffer.get_end_iter()
        tag = None

        lower = line.lower()
        if line.startswith("---") or "[system]" in lower or "⚡" in line:
            tag = "system"
        elif "error" in lower or "fatal" in lower or "failed" in lower or "timeout" in lower:
            tag = "error"
        elif "warn" in lower:
            tag = "warn"
        elif "success" in lower or "saved:" in lower or "ok:" in lower:
            tag = "success"
        elif "info" in lower or line.startswith("  •") or "ping" in lower:
            tag = "info"

        start_offset = end.get_offset()
        self.buffer.insert(end, line + "\n")

        if tag:
            start_iter = self.buffer.get_iter_at_offset(start_offset)
            end_iter = self.buffer.get_end_iter()
            self.buffer.apply_tag_by_name(tag, start_iter, end_iter)

        if self.auto_scroll:
            adj = self.log_scroller.get_vadjustment()
            GLib.idle_add(lambda: adj.set_value(adj.get_upper() - adj.get_page_size()))

    def show_toast(self, message: str, timeout: int = 3):
        toast = Adw.Toast.new(message)
        toast.set_timeout(timeout)
        self.toast_overlay.add_toast(toast)

    def toggle_sub_panel(self, _btn):
        visible = not self.sub_panel.get_visible()
        self.sub_panel.set_visible(visible)

    def load_saved_sub_url(self):
        f = get_sub_url_file()
        url = f.read_text().strip() if f.exists() else DEFAULT_SUB_URL
        self.sub_entry.set_text(url)

    def on_save_sub_url(self, _btn):
        url = self.sub_entry.get_text().strip()
        if not url:
            self.show_toast("Please enter a valid URL")
            return
        get_sub_url_file().write_text(url)
        self.show_toast("Subscription URL saved")
        self.sub_panel.set_visible(False)

    def refresh_profiles(self, show_toast: bool = False):
        self.paths = get_profile_paths()
        labels = []
        for p in self.paths:
            ping = self.ping_results.get(p.name)
            ping_str = f" [{ping}ms]" if ping is not None else (" [Timeout]" if p.name in self.ping_results else "")
            
            if p.name == "00-auto.json":
                labels.append(f"⚡ 00-auto (Auto Latency Failover){ping_str}")
            else:
                clean = re.sub(r"^\d+-", "", p.stem)
                labels.append(f"🌐 {clean} ({p.name}){ping_str}")

        if not labels:
            labels = ["(No profiles found — Click 'Update Sub')"]

        current_idx = self.combo.get_selected()
        self.combo.set_model(Gtk.StringList.new(labels))
        if current_idx < len(labels):
            self.combo.set_selected(current_idx)

        has_profiles = bool(self.paths)
        self.hero_btn.set_sensitive(has_profiles)
        self.single_ping_btn.set_sensitive(has_profiles)
        self.ping_all_btn.set_sensitive(has_profiles)

        node_count = len(self.paths)
        self.action_row.set_subtitle(
            f"{node_count} profile(s) ready in {get_profiles_dir().name}/"
            if has_profiles
            else "No profiles found. Update subscription to generate configs."
        )

        self.update_selected_latency_badge()

        if show_toast:
            self.show_toast(f"Refreshed: {node_count} profiles found")

    def update_selected_latency_badge(self):
        idx = self.combo.get_selected()
        if idx >= len(self.paths):
            self.selected_latency_badge.set_visible(False)
            return

        path = self.paths[idx]
        ping = self.ping_results.get(path.name)

        self.selected_latency_badge.remove_css_class("latency-good")
        self.selected_latency_badge.remove_css_class("latency-medium")
        self.selected_latency_badge.remove_css_class("latency-bad")
        self.selected_latency_badge.remove_css_class("latency-timeout")

        if ping is not None:
            self.selected_latency_badge.set_label(f"⚡ {ping} ms")
            if ping < 150:
                self.selected_latency_badge.add_css_class("latency-good")
            elif ping < 350:
                self.selected_latency_badge.add_css_class("latency-medium")
            else:
                self.selected_latency_badge.add_css_class("latency-bad")
            self.selected_latency_badge.set_visible(True)
        elif path.name in self.ping_results:
            self.selected_latency_badge.set_label("❌ Timeout")
            self.selected_latency_badge.add_css_class("latency-timeout")
            self.selected_latency_badge.set_visible(True)
        else:
            self.selected_latency_badge.set_visible(False)

    def on_profile_changed(self, combo, _param):
        idx = combo.get_selected()
        if idx < len(self.paths):
            p = self.paths[idx]
            if not self.proc:
                self.status_subtitle.set_label(f"Ready to launch: {p.name}")
            self.update_selected_latency_badge()

    # --- PING IMPLEMENTATION ---
    def ping_single_profile(self, path: Path) -> int | None:
        info = get_profile_server_info(path)
        if not info:
            # For 00-auto.json, test gstatic directly or check first outbound
            try:
                data = json.loads(path.read_text())
                for ob in data.get("outbounds", []):
                    if ob.get("server") and ob.get("server_port"):
                        res = tcp_ping(ob["server"], ob["server_port"])
                        if res is not None:
                            return res
            except Exception:
                pass
            return None
        host, port = info
        return tcp_ping(host, port)

    def on_ping_selected_clicked(self):
        idx = self.combo.get_selected()
        if idx >= len(self.paths):
            return
        path = self.paths[idx]

        self.single_ping_btn.set_sensitive(False)
        self.log(f"⚡ Pinging selected profile: {path.name}...")

        def run_ping():
            res = self.ping_single_profile(path)
            self.ping_results[path.name] = res
            msg = f"{path.name} -> {res} ms" if res is not None else f"{path.name} -> Timeout"
            GLib.idle_add(self.log, f"⚡ Ping result: {msg}")
            GLib.idle_add(self.show_toast, f"Ping: {res}ms" if res is not None else "Ping: Timeout")
            GLib.idle_add(self.refresh_profiles)
            GLib.idle_add(self.single_ping_btn.set_sensitive, True)

        threading.Thread(target=run_ping, daemon=True).start()

    def on_ping_all_clicked(self):
        if not self.paths:
            self.show_toast("No profiles to ping")
            return

        self.ping_all_btn.set_sensitive(False)
        self.single_ping_btn.set_sensitive(False)
        self.ping_all_spinner.start()
        self.log(f"⚡ Starting concurrent latency test for {len(self.paths)} profiles...")

        def run_all_pings():
            results = {}
            with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
                future_to_path = {executor.submit(self.ping_single_profile, p): p for p in self.paths}
                for future in concurrent.futures.as_completed(future_to_path):
                    p = future_to_path[future]
                    try:
                        lat = future.result()
                    except Exception:
                        lat = None
                    results[p.name] = lat
                    tag = f"✅ {lat}ms" if lat is not None else "❌ Timeout"
                    GLib.idle_add(self.log, f"  • {p.name}: {tag}")

            self.ping_results = results

            # Find fastest working profile
            valid_pings = {k: v for k, v in results.items() if v is not None}
            if valid_pings:
                fastest = min(valid_pings.items(), key=lambda x: x[1])
                summary = f"Fastest: {fastest[0]} ({fastest[1]}ms) — {len(valid_pings)}/{len(self.paths)} reachable"
            else:
                summary = f"0/{len(self.paths)} reachable"

            GLib.idle_add(self.log, f"⚡ Ping complete: {summary}")
            GLib.idle_add(self.show_toast, summary)
            GLib.idle_add(self.refresh_profiles)
            GLib.idle_add(self.ping_all_spinner.stop)
            GLib.idle_add(self.ping_all_btn.set_sensitive, True)
            GLib.idle_add(self.single_ping_btn.set_sensitive, True)

        threading.Thread(target=run_all_pings, daemon=True).start()

    def on_update_clicked(self, _button):
        url = self.sub_entry.get_text().strip() or None
        self.update_sub_btn.set_sensitive(False)
        self.sub_spinner.start()
        self.log("--- Updating subscription & building sing-box profiles...")

        def run_update():
            def log_callback(msg):
                GLib.idle_add(self.log, msg)

            try:
                paths = update_subscription(url=url, log_fn=log_callback)
                GLib.idle_add(self.show_toast, f"Updated: {len(paths)} profiles built")
            except Exception as e:
                GLib.idle_add(self.log, f"Error updating subscription: {e}")
                GLib.idle_add(self.show_toast, f"Update failed: {e}")
            finally:
                GLib.idle_add(self.sub_spinner.stop)
                GLib.idle_add(self.update_sub_btn.set_sensitive, True)
                GLib.idle_add(self.refresh_profiles)

        threading.Thread(target=run_update, daemon=True).start()

    def on_toggle(self, _button):
        if self.proc and self.proc.poll() is None:
            self.stop()
        else:
            self.start()

    def start(self):
        idx = self.combo.get_selected()
        if idx >= len(self.paths):
            self.show_toast("Please select a profile first")
            return
        path = self.paths[idx]
        self.log(f"--- Starting profile: {path.name}")

        self.set_ui_state("connecting", path.name)

        try:
            self.proc = subprocess.Popen(
                ["pkexec", "sing-box", "run", "-c", str(path), "-D", str(get_profiles_dir())],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            self.connected_time = time.time()
            self.start_timer()
            self.set_ui_state("connected", path.name)
            self.show_toast(f"Connected to {path.name}")
            threading.Thread(target=self.pump_output, args=(self.proc,), daemon=True).start()
        except Exception as e:
            self.log(f"--- Execution error: {e}")
            self.set_ui_state("disconnected", None)
            self.show_toast(f"Failed to start: {e}")

    def pump_output(self, proc):
        for line in proc.stdout:
            GLib.idle_add(self.log, line)
        code = proc.wait()
        GLib.idle_add(self.log, f"--- sing-box process exited (code: {code})")
        GLib.idle_add(self.set_ui_state, "disconnected", None)

    def stop(self):
        self.log("--- Stopping sing-box...")
        helper = "/usr/local/bin/singbox-stop"
        stopper = [helper] if os.path.exists(helper) else ["pkill", "-TERM", "-x", "sing-box"]
        subprocess.run(["pkexec", *stopper], check=False)
        if self.proc:
            try:
                self.proc.wait(timeout=4)
            except subprocess.TimeoutExpired:
                self.proc.send_signal(signal.SIGTERM)
        self.set_ui_state("disconnected", None)
        self.show_toast("sing-box stopped")

    def set_ui_state(self, state: str, profile_name: str | None):
        self.status_dot.remove_css_class("disconnected")
        self.status_dot.remove_css_class("connected")
        self.status_dot.remove_css_class("working")

        if state == "connected":
            self.status_dot.add_css_class("connected")
            self.status_title.set_label("Connected & Routing")
            self.status_subtitle.set_label(f"Active Profile: {profile_name}")
            self.hero_btn.set_label("Disconnect")
            self.hero_btn.remove_css_class("suggested-action")
            self.hero_btn.add_css_class("destructive-action")
            self.combo.set_sensitive(False)
            self.single_ping_btn.set_sensitive(False)
            self.ping_all_btn.set_sensitive(False)
            self.update_sub_btn.set_sensitive(False)
            self.uptime_label.set_visible(True)
        elif state == "connecting":
            self.status_dot.add_css_class("working")
            self.status_title.set_label("Connecting...")
            self.status_subtitle.set_label(f"Launching {profile_name}")
            self.hero_btn.set_sensitive(False)
        else:  # disconnected
            self.stop_timer()
            self.status_dot.add_css_class("disconnected")
            self.status_title.set_label("Disconnected")
            self.status_subtitle.set_label("Select a profile and click Connect")
            self.hero_btn.set_label("Connect")
            self.hero_btn.remove_css_class("destructive-action")
            self.hero_btn.add_css_class("suggested-action")
            self.hero_btn.set_sensitive(bool(self.paths))
            self.combo.set_sensitive(True)
            self.single_ping_btn.set_sensitive(bool(self.paths))
            self.ping_all_btn.set_sensitive(bool(self.paths))
            self.update_sub_btn.set_sensitive(True)
            self.uptime_label.set_visible(False)
            self.uptime_label.set_label("00:00:00")

    def start_timer(self):
        if self.timer_source_id:
            GLib.source_remove(self.timer_source_id)

        def update():
            if self.connected_time:
                elapsed = int(time.time() - self.connected_time)
                h = elapsed // 3600
                m = (elapsed % 3600) // 60
                s = elapsed % 60
                self.uptime_label.set_label(f"{h:02d}:{m:02d}:{s:02d}")
            return True

        self.timer_source_id = GLib.timeout_add_seconds(1, update)

    def stop_timer(self):
        if self.timer_source_id:
            GLib.source_remove(self.timer_source_id)
            self.timer_source_id = None
        self.connected_time = None

    def on_copy_logs(self, _btn):
        start = self.buffer.get_start_iter()
        end = self.buffer.get_end_iter()
        text = self.buffer.get_text(start, end, True)
        if text:
            display = Gtk.Widget.get_display(self)
            clipboard = display.get_clipboard()
            clipboard.set(text)
            self.show_toast("Logs copied to clipboard")

    def on_clear_logs(self, _btn):
        self.buffer.set_text("")
        self.show_toast("Logs cleared")

    def on_close(self, _win):
        if self.proc and self.proc.poll() is None:
            self.stop()
        return False


class TrafficBoxApp(Adw.Application):
    def __init__(self):
        super().__init__(application_id="ir.nexim.traffic_box")

    def do_startup(self):
        Adw.Application.do_startup(self)
        self.load_css()

    def do_activate(self):
        win = self.props.active_window
        if not win:
            win = TrafficBoxWindow(self)
        win.present()

    def load_css(self):
        provider = Gtk.CssProvider()
        provider.load_from_data(CUSTOM_CSS.encode("utf-8"))
        from gi.repository import Gdk

        default_display = Gdk.Display.get_default()
        if default_display:
            Gtk.StyleContext.add_provider_for_display(
                default_display,
                provider,
                Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
            )


def main():
    TrafficBoxApp().run(None)


if __name__ == "__main__":
    main()
