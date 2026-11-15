"""What the top bar and the control centre show and change, for real: the battery (UPower), the network
(NetworkManager), Bluetooth (BlueZ), the screen's brightness and the sound (Huginn's session daemon), Do Not Disturb,
night light (KWin), the notifications that came, and which app is in front.

Which app is in front: under Huginn's compositor the compositor knows; under KWin a small KWin script
(/usr/share/kwin/scripts/huginnactive) tells the shell over D-Bus (org.huginn.Shell.Active). The shell asks KWin to do
things to windows (bring an app forward, minimise, close) through KWin's scripting interface, one tiny script at a time.

All of it is D-Bus through Gio; nothing here blocks the screen for long (every call has a short timeout).
"""
import json
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from gi.repository import Gio, GLib
from PySide6.QtCore import Property, QObject, QTimer, Signal, Slot

SHELL_XML = """<node><interface name="org.huginn.Shell">
  <method name="Active"><arg type="s" name="caption" direction="in"/><arg type="s" name="app" direction="in"/>
    <arg type="s" name="desktop" direction="in"/><arg type="b" name="maximized" direction="in"/></method>
  <method name="Activated"><arg type="s" name="app" direction="in"/><arg type="b" name="found" direction="in"/></method>
</interface></node>"""
HISTORY = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share") / "huginn" / "notifications.jsonl"



def qt_runs_glib() -> bool:
    """Ubuntu's Qt runs GLib's loop itself, and GLib's sources (D-Bus) are served with Qt's events. Turning GLib's
    loop by hand from a Qt timer as well would run Qt's events inside Qt's events: a window drawn in the middle of
    drawing another, which can leave a surface waiting forever for its compositor."""
    from PySide6.QtCore import QAbstractEventDispatcher
    d = QAbstractEventDispatcher.instance()
    return d is not None and "Glib" in d.metaObject().className()

def _js(text: str) -> str:
    return json.dumps(text)


class System(QObject):
    changed = Signal()
    activeChanged = Signal()

    def __init__(self, demo: bool, apps=None):
        super().__init__()
        self._demo = demo
        self._apps = apps
        self._battery = {"present": False, "percent": 0, "charging": False}
        self._network = {"wifiDevice": False, "wifiOn": False, "kind": "none", "name": "", "signal": 0}
        self._bt = {"present": False, "on": False}
        self._levels = {"brightness": -1.0, "volume": 0.0, "muted": False}
        self._dnd = False
        self._night = {"available": False, "on": False}
        self._notes = []
        self._active = {"name": "", "appId": "", "caption": "", "maximized": False}
        self._bt_path = ""
        self._pending = {}                                 # dock clicks waiting for KWin to say if a window was there
        self.sb = self.yb = None
        if demo:
            self._battery = {"present": True, "percent": 82, "charging": False}
            self._network = {"wifiDevice": True, "wifiOn": True, "kind": "wifi", "name": "Home", "signal": 78}
            self._bt = {"present": True, "on": True}
            self._levels = {"brightness": 0.68, "volume": 0.42, "muted": False}
            self._night = {"available": True, "on": False}
            self._notes = [{"app": "Software Update", "summary": "Updates are ready", "body": "3 updates, including Huginn 1.4.", "ago": "2 min"}]
            return
        try:
            self.sb = Gio.bus_get_sync(Gio.BusType.SESSION, None)
            node = Gio.DBusNodeInfo.new_for_xml(SHELL_XML)
            self.sb.register_object("/org/huginn/Shell", node.interfaces[0], self._shell_call, None, None)
            Gio.bus_own_name_on_connection(self.sb, "org.huginn.Shell", Gio.BusNameOwnerFlags.REPLACE | Gio.BusNameOwnerFlags.ALLOW_REPLACEMENT, None, None)
        except GLib.Error:
            self.sb = None
        try:
            self.yb = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
        except GLib.Error:
            self.yb = None
        if self.yb:
            self.yb.signal_subscribe("org.freedesktop.UPower", "org.freedesktop.DBus.Properties", "PropertiesChanged",
                                     "/org/freedesktop/UPower/devices/DisplayDevice", None, Gio.DBusSignalFlags.NONE, lambda *a: self._later(self._read_battery))
            self.yb.signal_subscribe("org.freedesktop.NetworkManager", "org.freedesktop.DBus.Properties", "PropertiesChanged",
                                     "/org/freedesktop/NetworkManager", None, Gio.DBusSignalFlags.NONE, lambda *a: self._later(self._read_network))
            self.yb.signal_subscribe("org.bluez", "org.freedesktop.DBus.Properties", "PropertiesChanged", None, None,
                                     Gio.DBusSignalFlags.NONE, lambda *a: self._later(self._read_bluetooth))
        self._pump = QTimer(self, interval=40, timeout=lambda: GLib.MainContext.default().iteration(False))
        if not qt_runs_glib():
            self._pump.start()
        self._slow = QTimer(self, interval=20000, timeout=self.refresh)        # the Wi‑Fi signal, and anything missed
        self._slow.start()
        QTimer.singleShot(800, self.refresh)
        QTimer.singleShot(1200, self._ask_kwin)            # KWin's own script reports changes; this asks for the start

    def _ask_kwin(self):
        """When the shell (re)starts after KWin, ask once which window is in front."""
        if not self.sb or not self._kwin_running():
            return
        self.kwin("""var w = workspace.activeWindow; var full = false;
if (w && w.fullScreen) full = true;
else if (w) { var a = workspace.clientArea(KWin.MaximizeArea, w); full = w.frameGeometry.width >= a.width - 2 && w.frameGeometry.height >= a.height - 2; }
if (!w || w.normalWindow || w.dialog)
    callDBus("org.huginn.Shell", "/org/huginn/Shell", "org.huginn.Shell", "Active", w ? w.caption : "", w ? w.resourceClass : "", w ? w.desktopFileName : "", full);""")

    def _later(self, fn):
        QTimer.singleShot(150, fn)

    # ------------------------------------------------------------------ reading
    def _get(self, bus, name, path, iface, prop, default=None):
        try:
            v = bus.call_sync(name, path, "org.freedesktop.DBus.Properties", "Get", GLib.Variant("(ss)", (iface, prop)),
                              GLib.VariantType("(v)"), 0, 1500, None)
            return v.unpack()[0]
        except (GLib.Error, AttributeError):
            return default

    @Slot()
    def refresh(self) -> None:
        if self._demo:
            return
        self._read_battery()
        self._read_network()
        self._read_bluetooth()
        self._read_night()
        self.changed.emit()

    def _read_battery(self) -> None:
        if not self.yb:
            return
        dev = "/org/freedesktop/UPower/devices/DisplayDevice"
        kind = self._get(self.yb, "org.freedesktop.UPower", dev, "org.freedesktop.UPower.Device", "Type", 0)
        present = bool(self._get(self.yb, "org.freedesktop.UPower", dev, "org.freedesktop.UPower.Device", "IsPresent", False)) and kind == 2
        pct = self._get(self.yb, "org.freedesktop.UPower", dev, "org.freedesktop.UPower.Device", "Percentage", 0.0) or 0.0
        state = self._get(self.yb, "org.freedesktop.UPower", dev, "org.freedesktop.UPower.Device", "State", 0)
        self._battery = {"present": present, "percent": int(round(pct)), "charging": state in (1, 4)}
        self.changed.emit()

    def _read_network(self) -> None:
        if not self.yb:
            return
        nm, base = "org.freedesktop.NetworkManager", "/org/freedesktop/NetworkManager"
        out = {"wifiDevice": False, "wifiOn": bool(self._get(self.yb, nm, base, nm, "WirelessEnabled", False)), "kind": "none", "name": "", "signal": 0}
        devices = self._get(self.yb, nm, base, nm, "Devices", []) or []
        for d in devices:
            if self._get(self.yb, nm, d, nm + ".Device", "DeviceType", 0) == 2:
                out["wifiDevice"] = True
                ap = self._get(self.yb, nm, d, nm + ".Device.Wireless", "ActiveAccessPoint", "/")
                if ap and ap != "/":
                    out["signal"] = int(self._get(self.yb, nm, ap, nm + ".AccessPoint", "Strength", 0) or 0)
        primary = self._get(self.yb, nm, base, nm, "PrimaryConnection", "/")
        if primary and primary != "/":
            kind = self._get(self.yb, nm, primary, nm + ".Connection.Active", "Type", "") or ""
            out["name"] = self._get(self.yb, nm, primary, nm + ".Connection.Active", "Id", "") or ""
            out["kind"] = "wifi" if "wireless" in kind else "wired" if "ethernet" in kind else "vpn" if kind in ("vpn", "wireguard") else "other"
        self._network = out
        self.changed.emit()

    def _read_bluetooth(self) -> None:
        if not self.yb:
            return
        try:
            got = self.yb.call_sync("org.bluez", "/", "org.freedesktop.DBus.ObjectManager", "GetManagedObjects", None,
                                    GLib.VariantType("(a{oa{sa{sv}}})"), 0, 1500, None).unpack()[0]
        except GLib.Error:
            got = {}
        self._bt_path = next((p for p, ifs in got.items() if "org.bluez.Adapter1" in ifs), "")
        on = bool(got[self._bt_path]["org.bluez.Adapter1"].get("Powered", False)) if self._bt_path else False
        self._bt = {"present": bool(self._bt_path), "on": on}
        self.changed.emit()

    def _read_night(self) -> None:
        if not self.sb:
            return
        running = self._get(self.sb, "org.kde.KWin", "/org/kde/KWin/NightLight", "org.kde.KWin.NightLight", "available", None)
        if running is None:
            self._night = {"available": False, "on": False}
            return
        on = bool(self._get(self.sb, "org.kde.KWin", "/org/kde/KWin/NightLight", "org.kde.KWin.NightLight", "enabled", False))
        self._night = {"available": bool(running) and bool(shutil.which("kwriteconfig6")), "on": on}

    @Slot()
    def refreshPanel(self) -> None:
        """When the control centre opens: the sliders, Do Not Disturb and the notifications as they are now."""
        if self._demo:
            return
        if self.sb:
            try:
                b, v, m = self.sb.call_sync("org.huginn.Session", "/org/huginn/Session", "org.huginn.Session", "Levels", None,
                                            GLib.VariantType("(ddb)"), 0, 2000, None).unpack()
                self._levels = {"brightness": b, "volume": v, "muted": m}
            except GLib.Error:
                pass
            self._dnd = bool(self._get(self.sb, "org.huginn.Session", "/org/huginn/Session", "org.huginn.Session", "DoNotDisturb", False))
        self._notes = self._read_notes()
        self.refresh()

    @staticmethod
    def _read_notes() -> list:
        try:
            lines = HISTORY.read_text(encoding="utf-8").splitlines()[-30:]
        except OSError:
            return []
        out = []
        for line in reversed(lines):
            try:
                n = json.loads(line)
            except ValueError:
                continue
            ago = max(0, int(time.time()) - int(n.get("at", 0)))
            text = "now" if ago < 60 else f"{ago // 60} min" if ago < 3600 else f"{ago // 3600} h" if ago < 86400 else f"{ago // 86400} d"
            out.append({"app": n.get("app", ""), "summary": n.get("summary", ""), "body": n.get("body", ""), "ago": text})
            if len(out) >= 6:
                break
        return out

    # ------------------------------------------------------------------ changing
    def _set(self, bus, name, path, iface, prop, value) -> None:
        if bus:
            bus.call(name, path, "org.freedesktop.DBus.Properties", "Set", GLib.Variant("(ssv)", (iface, prop, value)),
                     None, 0, 3000, None, lambda *a: self._later(self.refresh))

    @Slot(bool)
    def setWifi(self, on: bool) -> None:
        self._network = dict(self._network, wifiOn=on)
        self.changed.emit()
        if not self._demo:
            self._set(self.yb, "org.freedesktop.NetworkManager", "/org/freedesktop/NetworkManager", "org.freedesktop.NetworkManager",
                      "WirelessEnabled", GLib.Variant("b", on))

    @Slot(bool)
    def setBluetooth(self, on: bool) -> None:
        self._bt = dict(self._bt, on=on)
        self.changed.emit()
        if not self._demo and self._bt_path:
            self._set(self.yb, "org.bluez", self._bt_path, "org.bluez.Adapter1", "Powered", GLib.Variant("b", on))

    def _session(self, method, args=None):
        if self.sb:
            self.sb.call("org.huginn.Session", "/org/huginn/Session", "org.huginn.Session", method, args, None, 0, 3000, None, None)

    @Slot(float)
    def setBrightness(self, level: float) -> None:
        self._levels = dict(self._levels, brightness=level)
        self.changed.emit()
        if not self._demo:
            self._session("SetBrightness", GLib.Variant("(d)", (level,)))

    @Slot(float)
    def setVolume(self, level: float) -> None:
        self._levels = dict(self._levels, volume=level, muted=False)
        self.changed.emit()
        if not self._demo:
            self._session("SetVolume", GLib.Variant("(d)", (level,)))

    @Slot(bool)
    def setMuted(self, muted: bool) -> None:
        self._levels = dict(self._levels, muted=muted)
        self.changed.emit()
        if not self._demo:
            self._session("SetMuted", GLib.Variant("(b)", (muted,)))

    @Slot(bool)
    def setDnd(self, on: bool) -> None:
        self._dnd = on
        self.changed.emit()
        if not self._demo:
            self._session("SetDoNotDisturb", GLib.Variant("(b)", (on,)))

    @Slot(bool)
    def setNightLight(self, on: bool) -> None:
        self._night = dict(self._night, on=on)
        self.changed.emit()
        if self._demo or not shutil.which("kwriteconfig6"):
            return
        subprocess.run(["kwriteconfig6", "--file", "kwinrc", "--group", "NightColor", "--key", "Active", "true" if on else "false"], check=False)
        if self.sb:
            self.sb.call("org.kde.KWin", "/KWin", "org.kde.KWin", "reconfigure", None, None, 0, 3000, None, None)

    @Slot()
    def clearNotifications(self) -> None:
        self._notes = []
        self.changed.emit()
        if not self._demo:
            self._session("ClearNotifications")

    @Slot(str)
    def openSettings(self, page: str) -> None:
        if not self._demo:
            subprocess.Popen(["python3", "/usr/share/huginn-apps/huginn_app.py", "settings"] + (["--page", page] if page else []),
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)

    # ------------------------------------------------------------------ the app in front (KWin)
    def _shell_call(self, conn, sender, path, iface, method, params, inv):
        if method == "Active":
            caption, resource, desktop, maximized = params.unpack()
            app = self._app_name(desktop or resource)
            self._active = {"name": app or caption, "appId": desktop or resource, "caption": caption, "maximized": bool(maximized)}
            self.activeChanged.emit()
        elif method == "Activated":
            key, found = params.unpack()
            command = self._pending.pop(key, "")
            if not found and command and self._apps is not None:
                self._apps.launch(command)                   # no window of it after all: start it (it hands over if running)
        inv.return_value(None)

    def _kwin_running(self) -> bool:
        try:
            return bool(self.sb.call_sync("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus", "NameHasOwner",
                                          GLib.Variant("(s)", ("org.kde.KWin",)), GLib.VariantType("(b)"), 0, 1000, None).unpack()[0])
        except GLib.Error:
            return False

    def _app_name(self, app_id: str) -> str:
        low = (app_id or "").lower()
        if not low or self._apps is None:
            return ""
        found = next((a for a in self._apps.all if low in (a.get("wm", "").lower(), a.get("id", "").lower())), None)
        return found["name"] if found else ""

    def kwin(self, script: str) -> bool:
        """Runs a few lines of KWin script (window actions). False where KWin isn't the compositor."""
        if self._demo or not self.sb:
            return False
        folder = Path(os.environ.get("XDG_RUNTIME_DIR") or tempfile.gettempdir())
        fd, path = tempfile.mkstemp(prefix="huginn-kwin-", suffix=".js", dir=folder)
        with os.fdopen(fd, "w") as f:
            f.write(script)
        name = "huginn" + Path(path).stem.replace("-", "")
        try:
            sid = self.sb.call_sync("org.kde.KWin", "/Scripting", "org.kde.kwin.Scripting", "loadScript", GLib.Variant("(ss)", (path, name)),
                                    GLib.VariantType("(i)"), 0, 2000, None).unpack()[0]
            self.sb.call_sync("org.kde.KWin", f"/Scripting/Script{sid}", "org.kde.kwin.Script", "run", None, None, 0, 2000, None)
        except GLib.Error:
            os.unlink(path)
            return False

        def tidy():
            try:
                self.sb.call_sync("org.kde.KWin", "/Scripting", "org.kde.kwin.Scripting", "unloadScript", GLib.Variant("(s)", (name,)), None, 0, 2000, None)
            except GLib.Error:
                pass
            try:
                os.unlink(path)
            except OSError:
                pass
        QTimer.singleShot(3000, tidy)
        return True

    @Slot("QVariantMap", result=bool)
    def activateApp(self, app: dict) -> bool:
        """KWin session: a running app's window comes forward (un-minimised) instead of the app starting again. KWin
        answers through Activated; with no window of it there, the app is started after all."""
        ids = [i.lower() for i in (app.get("wm", ""), app.get("id", "")) if i]
        if not ids or self._demo or not self.sb or not self._kwin_running():
            return False
        if self._apps is None or app.get("name") not in self._apps.running:
            return False
        self._pending[ids[0]] = app.get("exec", "")
        return self.kwin(f"""var ids = {json.dumps(ids)};
var best = null;
workspace.stackingOrder.forEach(function (w) {{
    var id = (w.desktopFileName || w.resourceClass || "").toLowerCase();
    if (w.normalWindow && ids.indexOf(id) >= 0) best = w;
}});
if (best) {{ best.minimized = false; workspace.activeWindow = best; }}
callDBus("org.huginn.Shell", "/org/huginn/Shell", "org.huginn.Shell", "Activated", ids[0], best !== null);""")

    @Slot(str)
    def windowAction(self, action: str) -> None:
        """The app menu in the top bar (KWin session): minimise or close the window in front."""
        js = {"minimise": "if (workspace.activeWindow) workspace.activeWindow.minimized = true;",
              "close": "if (workspace.activeWindow) workspace.activeWindow.closeWindow();"}.get(action)
        if js:
            self.kwin(js)

    battery = Property("QVariantMap", lambda self: self._battery, notify=changed)
    network = Property("QVariantMap", lambda self: self._network, notify=changed)
    bluetooth = Property("QVariantMap", lambda self: self._bt, notify=changed)
    levels = Property("QVariantMap", lambda self: self._levels, notify=changed)
    dnd = Property(bool, lambda self: self._dnd, notify=changed)
    nightLight = Property("QVariantMap", lambda self: self._night, notify=changed)
    notifications = Property("QVariantList", lambda self: self._notes, notify=changed)
    active = Property("QVariantMap", lambda self: self._active, notify=activeChanged)
