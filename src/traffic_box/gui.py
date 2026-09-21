"""GTK4 GUI launcher for Traffic-Box profiles."""

import json
import os
import signal
import subprocess
import threading
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import GLib, Gtk  # noqa: E402

from traffic_box.sub import get_profiles_dir, update_subscription


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
    found = sorted(
        (p for p in profiles_dir.glob("*.json") if is_singbox_config(p)),
        key=lambda p: p.name,
    )
    return found


class App(Gtk.Application):
    def __init__(self):
        super().__init__(application_id="ir.nexim.traffic_box")
        self.proc = None
        self.paths = []

    def do_activate(self):
        self.paths = get_profile_paths()

        win = Gtk.ApplicationWindow(application=self, title="Traffic Box — Smart Routing Launcher")
        win.set_default_size(600, 460)
        win.connect("close-request", self.on_close)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        box.set_margin_top(14)
        box.set_margin_bottom(14)
        box.set_margin_start(14)
        box.set_margin_end(14)
        win.set_child(box)

        # Top Control Row
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        box.append(row)

        self.combo = Gtk.DropDown.new_from_strings([p.name for p in self.paths] or ["(no profiles found)"])
        self.combo.set_hexpand(True)
        row.append(self.combo)

        self.update_btn = Gtk.Button(label="Update Sub")
        self.update_btn.connect("clicked", self.on_update_clicked)
        row.append(self.update_btn)

        self.button = Gtk.Button(label="Start")
        self.button.add_css_class("suggested-action")
        self.button.connect("clicked", self.on_toggle)
        row.append(self.button)

        # Status Label
        self.status = Gtk.Label(label="Status: Stopped", xalign=0)
        self.status.add_css_class("dim-label")
        box.append(self.status)

        # Log View
        self.buffer = Gtk.TextBuffer()
        view = Gtk.TextView(buffer=self.buffer, editable=False, monospace=True)
        scroll = Gtk.ScrolledWindow(child=view, vexpand=True)
        box.append(scroll)

        if not self.paths:
            self.button.set_sensitive(False)
            self.log(f"No profiles in {get_profiles_dir()}. Click 'Update Sub' to fetch profiles.")

        win.present()

    def log(self, line: str):
        end = self.buffer.get_end_iter()
        self.buffer.insert(end, line.rstrip() + "\n")

    def refresh_profiles(self):
        self.paths = get_profile_paths()
        strings = [p.name for p in self.paths] or ["(no profiles found)"]
        self.combo.set_model(Gtk.StringList.new(strings))
        self.button.set_sensitive(bool(self.paths))

    def on_update_clicked(self, _button):
        self.update_btn.set_sensitive(False)
        self.log("--- Updating subscription & rebuilding routing profiles...")

        def run_update():
            def log_callback(msg):
                GLib.idle_add(self.log, msg)

            try:
                update_subscription(log_fn=log_callback)
            except Exception as e:
                GLib.idle_add(self.log, f"Error updating subscription: {e}")
            finally:
                GLib.idle_add(self.update_btn.set_sensitive, True)
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
            return
        path = self.paths[idx]
        self.log(f"--- Starting profile: {path.name}")
        self.proc = subprocess.Popen(
            ["pkexec", "sing-box", "run", "-c", str(path), "-D", str(get_profiles_dir())],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        self.set_running(True, path.name)
        threading.Thread(target=self.pump, args=(self.proc,), daemon=True).start()

    def pump(self, proc):
        for line in proc.stdout:
            GLib.idle_add(self.log, line)
        code = proc.wait()
        GLib.idle_add(self.log, f"--- Process exited ({code})")
        GLib.idle_add(self.set_running, False, None)

    def stop(self):
        self.log("--- Stopping sing-box...")
        helper = "/usr/local/bin/singbox-stop"
        stopper = [helper] if os.path.exists(helper) else ["pkill", "-TERM", "-x", "sing-box"]
        subprocess.run(["pkexec", *stopper], check=False)
        try:
            self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.proc.send_signal(signal.SIGTERM)

    def set_running(self, running: bool, name: str | None):
        self.button.set_label("Stop" if running else "Start")
        self.button.remove_css_class("suggested-action" if running else "destructive-action")
        self.button.add_css_class("destructive-action" if running else "suggested-action")
        self.combo.set_sensitive(not running)
        self.update_btn.set_sensitive(not running)
        self.status.set_label(f"Status: Running — {name}" if running else "Status: Stopped")

    def on_close(self, _win):
        if self.proc and self.proc.poll() is None:
            self.stop()
        return False


def main():
    App().run(None)


if __name__ == "__main__":
    main()
