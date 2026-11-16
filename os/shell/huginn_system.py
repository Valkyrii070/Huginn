"""What the top bar and the control centre show and change, for real: the battery (UPower), the network
(NetworkManager), Bluetooth (BlueZ), the screen's brightness and the sound (Huginn's session daemon), Do Not Disturb,
night light (KWin), the notifications that came, and which app is in front.

Which app is in front: Huginn's own compositor tells the shell over D-Bus (org.huginn.Shell.Active); under KWin a small
KWin script (/usr/share/kwin/scripts/huginnactive) does. Things done to windows (bring an app forward, minimise, close)
are asked of Huginn's compositor (org.huginn.Compositor.ActivateApp, WindowAction), or of KWin through its scripting
interface, one tiny script at a time.

All of it is D-Bus through Gio; nothing here blocks the screen for long (every call has a short timeout).
"""
import json
import os
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path

from gi.repository import Gio, GLib
from PySide6.QtCore import Property, QObject, QTimer, Signal, Slot

# KWin script: the window list for the shell (the same as huginnactive's main.js, for a shell started after KWin)
WINDOWS_JS = """var lastWindows = "";
function spaceOf(w) {
    if (w.onAllDesktops || !w.desktops || w.desktops.length === 0) return -1;
    return workspace.desktops.indexOf(w.desktops[0]);
}
function reportWindows() {
    var rows = [];
    var all = workspace.windowList();
    for (var i = 0; i < all.length; i++) {
        var w = all[i];
        if (!w.normalWindow || w.skipTaskbar) continue;
        var g = w.frameGeometry;
        rows.push({ id: String(w.internalId), app: w.desktopFileName || w.resourceClass || "", cls: w.resourceClass || "",
                    title: w.caption, minimised: w.minimized, active: w === workspace.activeWindow, space: spaceOf(w), pid: w.pid, full: w.fullScreen,
                    x: g.x, y: g.y, w: g.width, h: g.height });
    }
    var spaces = [];
    for (var j = 0; j < workspace.desktops.length; j++) spaces.push(workspace.desktops[j].name);
    callDBus("org.huginn.Shell", "/org/huginn/Shell", "org.huginn.Shell", "Windows",
             JSON.stringify({ current: workspace.desktops.indexOf(workspace.currentDesktop), spaces: spaces, windows: rows }));
}"""

SHELL_XML = """<node><interface name="org.huginn.Shell">
  <method name="Active"><arg type="s" name="caption" direction="in"/><arg type="s" name="app" direction="in"/>
    <arg type="s" name="desktop" direction="in"/><arg type="b" name="maximized" direction="in"/></method>
  <method name="Activated"><arg type="s" name="app" direction="in"/><arg type="b" name="found" direction="in"/></method>
  <method name="ToggleLauncher"/>
  <method name="Launcher"><arg type="s" name="what" direction="in"/></method>
  <method name="Search"><arg type="s" name="text" direction="in"/></method>
  <method name="Screenshot"><arg type="s" name="what" direction="in"/></method>
  <method name="Windows"><arg type="s" name="json" direction="in"/></method>
  <method name="Key"><arg type="s" name="what" direction="in"/></method>
  <method name="Tour"/>
  <method name="Overview"><arg type="s" name="json" direction="in"/></method>
  <method name="SnapPreview"><arg type="s" name="json" direction="in"/></method>
  <method name="SnapAssist"><arg type="s" name="json" direction="in"/></method>
  <method name="Switcher"><arg type="s" name="json" direction="in"/></method>
  <method name="Snap"><arg type="s" name="layout" direction="in"/></method>
  <method name="AppMenu"/>
</interface></node>"""
HISTORY = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share") / "huginn" / "notifications.jsonl"
SEEN_NOTES = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local/state") / "huginn" / "notifications-seen"
BUSY_FLAG = Path(os.environ.get("XDG_RUNTIME_DIR") or "/tmp") / "huginn-busy-screen"



def QProcess_start(app: str) -> None:
    """One of Huginn's own apps."""
    from PySide6.QtCore import QProcess
    here = Path(__file__).resolve().parent
    for d in (Path("/usr/share/huginn-apps"), here.parent / "apps"):
        if (d / "huginn_app.py").exists():
            QProcess.startDetached("python3", [str(d / "huginn_app.py"), app])
            return


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
    windowsChanged = Signal()
    menusChanged = Signal()
    sceneChanged = Signal()                                # the Overview, snapping, Alt+Tab (Huginn's compositor)
    launcherWanted = Signal()                              # Super on its own (KWin asks)
    searchWanted = Signal(str)                             # Meta+Space: Search everything
    keyWanted = Signal(str)                                # a key for the shell: "today" (Meta+T)…
    tourWanted = Signal()                                  # Huginn's menu: Take the tour again
    shellMenuAction = Signal(str)                          # a menu item the shell itself does (about, aboutApp, appWindows, pin)

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
        self._windows = []                                 # every window (the dock, the Overview): see _read_windows
        self._spaces = {"current": 0, "names": ["Main"]}
        self._menus = {}                                   # the app in front's menus (the top bar's one menu)
        self._overview, self._snap_preview, self._snap_assist, self._switcher = {}, {}, {}, {}
        self._menu_bus = ""
        self._bt_path = ""
        self._pending = {}                                 # dock clicks waiting for KWin to say if a window was there
        self.sb = self.yb = None
        self._power = {"sleep": True, "restart": True, "shutdown": True}
        self.lastPower = ""                                 # (tests) the last power action asked for
        self._shooting = False
        if demo:
            self._battery = {"present": True, "percent": 82, "charging": False}
            self._network = {"wifiDevice": True, "wifiOn": True, "kind": "wifi", "name": "Home", "signal": 78, "wifiName": "Home", "wired": False, "wiredName": ""}
            self._bt = {"present": True, "on": True}
            self._levels = {"brightness": 0.68, "volume": 0.42, "muted": False}
            self._night = {"available": True, "on": False}
            self._notes = [{"app": "Software Update", "summary": "Updates are ready", "body": "3 updates, including Huginn 1.4.", "ago": "2 min"}]
            demo_windows = [("1", "huginn-files", "Documents › Travel", False, False), ("2", "huginn-files", "Pictures › Iceland", False, True),
                            ("3", "huginn-files", "Downloads", True, False), ("4", "huginn-writer", "Iceland trip plan", False, False)]
            self._windows = [{"id": i, "appId": a, "name": "", "title": t, "minimised": m, "active": act, "space": 0}
                             for i, a, t, m, act in demo_windows]
            QTimer.singleShot(0, self._name_windows)
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
        from PySide6.QtGui import QGuiApplication
        if QGuiApplication.instance():
            app = QGuiApplication.instance()
            app.primaryScreenChanged.connect(lambda *_: self.primaryScreenChanged.emit())
            app.screenAdded.connect(lambda *_: self.primaryScreenChanged.emit())
            app.screenRemoved.connect(lambda *_: QTimer.singleShot(0, self.primaryScreenChanged.emit))
        self._pump = QTimer(self, interval=40, timeout=lambda: GLib.MainContext.default().iteration(False))
        if not qt_runs_glib():
            self._pump.start()
        from PySide6.QtCore import QFileSystemWatcher
        HISTORY.parent.mkdir(parents=True, exist_ok=True)
        self._notes_watch = QFileSystemWatcher([str(HISTORY.parent)], self)        # a notification came: the dot, the Control Centre
        self._notes_watch.directoryChanged.connect(lambda *_: self._later(self._reread_notes))
        self._notes_watch.fileChanged.connect(lambda *_: self._later(self._reread_notes))
        if HISTORY.exists():
            self._notes_watch.addPath(str(HISTORY))
        self._slow = QTimer(self, interval=20000, timeout=self.refresh)        # the Wi‑Fi signal, and anything missed
        self._slow.start()
        QTimer.singleShot(800, self.refresh)
        QTimer.singleShot(1500, self._read_power)
        QTimer.singleShot(1200, self._ask_kwin)            # KWin's own script reports changes; this asks for the start
        QTimer.singleShot(1300, self._ask_windows)

    def _ask_kwin(self):
        """When the shell (re)starts after KWin, ask once which window is in front."""
        if not self.sb or not self._kwin_running():
            return
        self.kwin("""var w = workspace.activeWindow; var full = false;
if (w && w.fullScreen) full = true;
else if (w) { var a = workspace.clientArea(KWin.MaximizeArea, w); full = w.frameGeometry.width >= a.width - 2 && w.frameGeometry.height >= a.height - 2; }
if (!w || w.normalWindow || w.dialog)
    callDBus("org.huginn.Shell", "/org/huginn/Shell", "org.huginn.Shell", "Active", w ? w.caption : "", w ? w.resourceClass : "", w ? w.desktopFileName : "", full);""")

    def _ask_windows(self):
        """The window list, once at the start (afterwards the compositor or KWin's script tells us of changes)."""
        if not self.sb:
            return
        if self._own_compositor():
            got = self._compositor("Windows", None, "(s)")
            if got:
                self._read_windows(got[0])
        elif self._kwin_running():
            self.kwin(WINDOWS_JS + "\nreportWindows();")

    def _read_windows(self, text: str) -> None:
        try:
            data = json.loads(text or "{}")
        except ValueError:
            return
        if isinstance(data, list):                         # an older compositor: just the windows
            data = {"windows": data}
        rows = []
        for w in data.get("windows", []):
            app_id = w.get("app", "")
            rows.append({"id": str(w.get("id", "")), "appId": app_id, "pid": int(w.get("pid", 0) or 0), "name": self._app_name(app_id) or self._app_name(w.get("cls", "")),
                         "title": w.get("title", ""), "minimised": bool(w.get("minimised")), "active": bool(w.get("active") or w.get("focused")),
                         "space": int(w.get("space", 0)), "full": bool(w.get("full")), "x": w.get("x", 0), "y": w.get("y", 0), "w": w.get("w", 0), "h": w.get("h", 0)})
        self._windows = rows
        self._spaces = {"current": int(data.get("current", 0)), "names": list(data.get("spaces") or ["Main"])}
        self.windowsChanged.emit()

    def _name_windows(self):
        for w in self._windows:
            w["name"] = self._app_name(w["appId"]) or w["name"]
        self.windowsChanged.emit()

    @Slot(str, str)
    def windowDo(self, wid: str, action: str) -> None:
        """Something done to one window, by its id in the list: activate, minimise, close, toggle (hide it if it's
        in front, else bring it forward), maximise."""
        own = action.startswith(("snap:", "space:"))           # Huginn's compositor only (KWin: snapFront / spaceDo)
        if action not in ("activate", "minimise", "close", "toggle", "maximise") and not own or not wid:
            return
        if own and (self._demo or not self.sb or not self._own_compositor()):
            return
        if self._demo or not self.sb:
            for w in self._windows:
                if w["id"] == wid:
                    if action == "close":
                        self._windows.remove(w)
                        break
                    hide = action == "minimise" or (action == "toggle" and w["active"] and not w["minimised"])
                    for o in self._windows:
                        o["active"] = False
                    w["minimised"] = hide
                    w["active"] = not hide
                    break
            self.windowsChanged.emit()
            return
        if self._own_compositor():
            self._compositor("WindowDo", GLib.Variant("(ss)", (wid, action)), None)
            return
        do = {"activate": "w.minimized = false; workspace.activeWindow = w;",
              "minimise": "w.minimized = true;",
              "close": "w.closeWindow();",
              "toggle": "if (w === workspace.activeWindow && !w.minimized) w.minimized = true; else { w.minimized = false; workspace.activeWindow = w; }",
              "maximise": "w.minimized = false; workspace.activeWindow = w; w.setMaximize(true, true);"}[action]
        self.kwin(f"""var all = workspace.windowList();
for (var i = 0; i < all.length; i++) {{ var w = all[i]; if (String(w.internalId) === {json.dumps(wid)}) {{ {do} break; }} }}""")

    # ------------------------------------------------------------------ the app in front's menus
    def _huginn_menus(self) -> dict:
        """With nothing in front, the name in the bar is Huginn: the desktop's own menu."""
        def it(label, act, keys=""):
            return {"label": label, "id": act, "keys": keys, "enabled": True}
        return {"app": "Huginn", "key": "huginn", "groups": [],
                "top": [it("About Huginn OS", "shell:about"), it("Settings…", "shell:settings", "Ctrl+,")],
                "middle": [it("Change wallpaper…", "shell:wallpaper"), it("Desktop & Dock settings…", "shell:desktop"), it("Show the desktop", "shell:showDesktop", "Super+D"),
                           {"sep": True}, it("Help", "shell:help", "F1"), it("Take the tour again", "shell:tour")],
                "bottom": []}

    def _basic_menus(self, name: str) -> dict:
        """An app that doesn't share its menus: the same basics as every other app's, so the menu is never empty."""
        def it(label, act, keys="", on=True):
            return {"label": label, "id": act, "keys": keys, "enabled": on}
        return {"app": name, "key": "", "groups": [],
                "top": [it(f"About {name}", "shell:aboutApp"), it(f"{name} Settings…", "", "Ctrl+,", False)],
                "middle": [it("Show all its windows", "shell:appWindows"), it("Keep in the dock", "shell:pin")],
                "bottom": [it("Minimise", "shell:minimise"), it("Close window", "shell:close", "Ctrl+W"), it(f"Quit {name}", "shell:quit", "Ctrl+Q")]}

    def _front_window(self):
        """The window whose app is in the bar (the shell's own panels can have the keyboard meanwhile)."""
        front = next((w for w in self._windows if w.get("active") and not w.get("minimised")), None)
        if front is None and self._active.get("appId"):
            mine = [w for w in self._windows if not w.get("minimised") and w.get("appId", "").lower() == self._active["appId"].lower()]
            front = mine[-1] if mine else None
        return front

    @Slot()
    def loadMenus(self) -> None:
        name = self._active.get("name") or ""
        front = self._front_window()
        if not name or front is None and not self._demo:
            self._menu_bus = ""
            self._menus = self._huginn_menus()
            self.menusChanged.emit()
            return
        self._menus = self._basic_menus(name)
        self._menu_bus = ""
        self.menusChanged.emit()
        pid = (front or {}).get("pid", 0)
        if self._demo or not self.sb or not pid:
            return
        bus = f"org.huginn.App.p{pid}"

        def got(conn, res):
            try:
                text = conn.call_finish(res).unpack()[0]
                data = json.loads(text)
            except (GLib.Error, ValueError):
                return
            if data.get("groups") is not None:
                data.setdefault("middle", [])
                self._menus = data
                self._menu_bus = bus
                self.menusChanged.emit()
        self.sb.call(bus, "/org/huginn/App", "org.huginn.App", "Menus", None, GLib.VariantType("(s)"),
                     Gio.DBusCallFlags.NO_AUTO_START, 1500, None, got)

    @Slot(str)
    def menuTrigger(self, act: str) -> None:
        if not act:
            return
        if act.startswith("shell:"):
            what = act[6:]
            front = self._front_window()
            if what == "minimise":
                self.windowAction("minimise")
            elif what == "close":
                self.windowAction("close")
            elif what == "quit" and front:
                for w in [w for w in self._windows if w.get("name") == front.get("name")]:
                    self.windowDo(w["id"], "close")
            elif what in ("settings", "wallpaper", "desktop"):
                self.openSettings({"settings": "", "wallpaper": "appearance", "desktop": "desktop"}[what])
            elif what == "help":
                QProcess_start("help")
            elif what == "tour":
                self.tourWanted.emit()
            elif what == "showDesktop":
                for w in self._windows:
                    if not w.get("minimised"):
                        self.windowDo(w["id"], "minimise")
            else:
                self.shellMenuAction.emit(what)
            return
        if self._menu_bus and self.sb:
            self.sb.call(self._menu_bus, "/org/huginn/App", "org.huginn.App", "Trigger", GLib.Variant("(s)", (act,)), None,
                         Gio.DBusCallFlags.NO_AUTO_START, 1500, None, None)

    # ------------------------------------------------------------------ the Overview, spaces, snapping
    @Slot(str)
    def overviewDo(self, action: str) -> None:
        """The Overview: toggle, close, activate:ID, dim:ID,ID… (KWin: its own Overview, for toggle)."""
        if self._demo or not self.sb:
            return
        if self._own_compositor():
            self._compositor("OverviewDo", GLib.Variant("(s)", (action,)), None)
        elif self._kwin_running() and action in ("toggle", "open"):
            try:
                self.sb.call_sync("org.kde.kglobalaccel", "/component/kwin", "org.kde.kglobalaccel.Component", "invokeShortcut",
                                  GLib.Variant("(s)", ("Overview",)), None, 0, 1500, None)
            except GLib.Error:
                pass

    @Slot(str)
    def spaceDo(self, action: str) -> None:
        """Spaces: switch:N, add, remove:N, rename:N:name, move:ID:N, reorder:A:B."""
        if self._demo or not self.sb:
            return
        if self._own_compositor():
            self._compositor("SpaceDo", GLib.Variant("(s)", (action,)), None)
            return
        parts = action.split(":", 2)
        what, a, b = (parts + ["", "", ""])[:3]
        js = {"switch": f"var d = workspace.desktops[{int(a or 0)}]; if (d) workspace.currentDesktop = d;",
              "add": "workspace.createDesktop(workspace.desktops.length, 'Space ' + (workspace.desktops.length + 1));",
              "remove": f"var d = workspace.desktops[{int(a or 0)}]; if (d && workspace.desktops.length > 1) workspace.removeDesktop(d);",
              "rename": f"var d = workspace.desktops[{int(a or 0) if a.isdigit() else 0}]; if (d) d.name = {json.dumps(b)};",
              "move": f"var d = workspace.desktops[{int(b or 0) if b.isdigit() else 0}]; var all = workspace.windowList();"
                      f" for (var i = 0; i < all.length; i++) if (String(all[i].internalId) === {json.dumps(a)} && d) all[i].desktops = [d];"}.get(what)
        if js:
            self.kwin(js + "\n" + WINDOWS_JS + "\nreportWindows();")

    @Slot(str)
    def dockLayout(self, text: str) -> None:
        """Where the dock's tiles are (windows hide into them) and how: for Huginn's compositor."""
        if self._demo or not self.sb or not self._own_compositor():
            return
        self._compositor("DockLayout", GLib.Variant("(s)", (text,)), None)

    @Slot(str)
    def snapFront(self, layout: str) -> None:
        """The window in front, snapped: left, right, max, top-left…, left-third, right-two-thirds… (its fill button)."""
        front = self._front_window()
        if not front or self._demo or not self.sb:
            return
        if self._own_compositor():
            self.windowDo(front["id"], "snap:" + layout)
            return
        part = {"left": (0, 0, .5, 1), "right": (.5, 0, .5, 1), "max": (0, 0, 1, 1), "top-left": (0, 0, .5, .5), "top-right": (.5, 0, .5, .5),
                "bottom-left": (0, .5, .5, .5), "bottom-right": (.5, .5, .5, .5), "left-third": (0, 0, 1 / 3, 1), "right-third": (2 / 3, 0, 1 / 3, 1),
                "left-two-thirds": (0, 0, 2 / 3, 1), "right-two-thirds": (1 / 3, 0, 2 / 3, 1)}.get(layout)
        if part:
            x, y, w, h = part
            self.kwin(f"""var all = workspace.windowList();
for (var i = 0; i < all.length; i++) {{ var win = all[i]; if (String(win.internalId) !== {json.dumps(front['id'])}) continue;
  var a = workspace.clientArea(KWin.MaximizeArea, win), g = 8;
  win.frameGeometry = {{ x: a.x + g + (a.width - 2 * g) * {x} + ({x} > 0 ? g / 2 : 0), y: a.y + g + (a.height - 2 * g) * {y} + ({y} > 0 ? g / 2 : 0),
                        width: (a.width - 2 * g) * {w} - ({w} < 1 ? g / 2 : 0), height: (a.height - 2 * g) * {h} - ({h} < 1 ? g / 2 : 0) }}; }}""")

    @Slot()
    def assistDone(self) -> None:
        self._snap_assist = {}
        self.sceneChanged.emit()

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
        out = {"wifiDevice": False, "wifiOn": bool(self._get(self.yb, nm, base, nm, "WirelessEnabled", False)), "kind": "none", "name": "", "signal": 0,
               "wifiName": "", "wired": False, "wiredName": ""}
        devices = self._get(self.yb, nm, base, nm, "Devices", []) or []

        def active_id(d):
            """The connection a device is using (each device's own, not only the one the internet goes through)."""
            ac = self._get(self.yb, nm, d, nm + ".Device", "ActiveConnection", "/")
            if not ac or ac == "/" or self._get(self.yb, nm, ac, nm + ".Connection.Active", "State", 0) != 2:   # 2: activated
                return ""
            return self._get(self.yb, nm, ac, nm + ".Connection.Active", "Id", "") or ""
        for d in devices:
            kind = self._get(self.yb, nm, d, nm + ".Device", "DeviceType", 0)
            if kind == 2:
                out["wifiDevice"] = True
                out["wifiName"] = out["wifiName"] or active_id(d)
                ap = self._get(self.yb, nm, d, nm + ".Device.Wireless", "ActiveAccessPoint", "/")
                if ap and ap != "/":
                    out["signal"] = int(self._get(self.yb, nm, ap, nm + ".AccessPoint", "Strength", 0) or 0)
            elif kind == 1:
                name = active_id(d)
                if name:
                    out["wired"], out["wiredName"] = True, out["wiredName"] or name
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
        """What came, grouped by app (the newest of each, and how many more), newest app first."""
        try:
            lines = HISTORY.read_text(encoding="utf-8").splitlines()[-60:]
        except OSError:
            return []
        out, at = [], {}
        for line in reversed(lines):
            try:
                n = json.loads(line)
            except ValueError:
                continue
            app = n.get("app", "")
            if app in at:
                out[at[app]]["more"] += 1
                continue
            if len(out) >= 6:
                continue
            ago = max(0, int(time.time()) - int(n.get("at", 0)))
            text = "now" if ago < 60 else f"{ago // 60} min" if ago < 3600 else f"{ago // 3600} h" if ago < 86400 else f"{ago // 86400} d"
            at[app] = len(out)
            out.append({"app": app, "summary": n.get("summary", ""), "body": n.get("body", ""), "ago": text, "at": int(n.get("at", 0)), "more": 0,
                        "icon": n.get("icon", "")})
        return out

    def _reread_notes(self) -> None:
        if HISTORY.exists() and str(HISTORY) not in self._notes_watch.files():
            self._notes_watch.addPath(str(HISTORY))
        notes = self._read_notes()
        if notes != self._notes:
            self._notes = notes
            self.changed.emit()

    def _waiting(self) -> bool:
        """Notifications came since the Control Centre was last opened: a dot by the status icons."""
        try:
            seen = float(SEEN_NOTES.read_text(encoding="utf-8") or 0)
        except (OSError, ValueError):
            seen = 0
        return any(n.get("at", 0) > seen for n in self._notes)

    @Slot()
    def notesSeen(self) -> None:
        try:
            SEEN_NOTES.parent.mkdir(parents=True, exist_ok=True)
            SEEN_NOTES.write_text(str(time.time()), encoding="utf-8")
        except OSError:
            pass
        self.changed.emit()

    @Slot(bool)
    def setBusyScreen(self, busy: bool) -> None:
        """Something has the whole screen, or it's being shared: notifications wait quietly (calls and alarms don't)."""
        try:
            if busy:
                BUSY_FLAG.write_text("1", encoding="utf-8")
            elif BUSY_FLAG.exists():
                BUSY_FLAG.unlink()
        except OSError:
            pass

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

    # ------------------------------------------------------------------ power (the start menu's bottom row)
    def _read_power(self) -> None:
        """Which of Sleep / Restart / Shut Down logind will do here ("na" means the machine can't, e.g. sleep in a VM)."""
        if not self.yb:
            return
        caps = {}
        for key, method in (("sleep", "CanSuspend"), ("restart", "CanReboot"), ("shutdown", "CanPowerOff")):
            try:
                v = self.yb.call_sync("org.freedesktop.login1", "/org/freedesktop/login1", "org.freedesktop.login1.Manager", method,
                                      None, GLib.VariantType("(s)"), 0, 1500, None).unpack()[0]
                caps[key] = v != "na"
            except GLib.Error:
                caps[key] = True
        if caps != self._power:
            self._power = caps
            self.changed.emit()

    @Slot(str)
    def screenshot(self, what: str) -> None:
        """screen: the whole screen into Pictures › Screenshots at once (with a banner); choose: the Screenshot app."""
        if self._demo:
            return
        apps = "/usr/share/huginn-apps"
        if what == "choose":
            subprocess.Popen(["python3", f"{apps}/huginn_app.py", "screenshot"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             start_new_session=True)
            return
        if self._shooting:
            return
        self._shooting = True

        def run():
            try:
                subprocess.run(["python3", f"{apps}/huginn_capture.py", "--save"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60)
            except (OSError, subprocess.TimeoutExpired):
                pass
            self._shooting = False
        threading.Thread(target=run, daemon=True).start()

    @Slot(str)
    def power(self, what: str) -> None:
        """lock, sleep, restart, shutdown or signout. The session daemon does it (it locks before sleeping); without
        it, logind directly."""
        if what not in ("lock", "sleep", "restart", "shutdown", "signout"):
            return
        self.lastPower = what
        if self._demo:
            print(f"huginn-shell: power: {what} (preview: nothing happens)", file=__import__("sys").stderr)
            return

        def fallback(conn, res):
            try:
                conn.call_finish(res)
            except GLib.Error:
                self._power_direct(what)
        if self.sb:
            self.sb.call("org.huginn.Session", "/org/huginn/Session", "org.huginn.Session", "Do", GLib.Variant("(s)", (what,)),
                         None, 0, 3000, None, fallback)
        else:
            self._power_direct(what)

    def _power_direct(self, what: str) -> None:
        if what == "lock":
            cmd = ["loginctl", "lock-session"]
        elif what == "signout":
            cmd = ["loginctl", "terminate-session", os.environ.get("XDG_SESSION_ID", "")]
        else:
            cmd = ["systemctl", {"sleep": "suspend", "restart": "reboot", "shutdown": "poweroff"}[what]]
        if shutil.which(cmd[0]):
            subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)

    @Slot(str)
    def openSettings(self, page: str) -> None:
        if not self._demo:
            subprocess.Popen(["python3", "/usr/share/huginn-apps/huginn_app.py", "settings"] + (["--page", page] if page else []),
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)

    # ------------------------------------------------------------------ the app in front (KWin)
    def _shell_call(self, conn, sender, path, iface, method, params, inv):
        if method in ("ToggleLauncher", "Launcher"):            # Super (KWin)
            self.launcherWanted.emit()
            inv.return_value(None)
            return
        if method == "Search":                                   # Meta+Space (KWin's script)
            self.searchWanted.emit(params.unpack()[0])
            inv.return_value(None)
            return
        if method == "Screenshot":                               # Print and Meta+Shift+S (KWin's script)
            inv.return_value(None)
            self.screenshot(params.unpack()[0])
            return
        if method == "Active":
            caption, resource, desktop, maximized = params.unpack()
            app = self._app_name(desktop or resource)
            self._active = {"name": app or caption, "appId": desktop or resource, "caption": caption, "maximized": bool(maximized)}
            self.activeChanged.emit()
        elif method == "Key":
            self.keyWanted.emit(params.unpack()[0])
        elif method == "Tour":                                   # Welcome in the apps, Help, Huginn's menu
            self.tourWanted.emit()
        elif method == "Snap":                                   # an app's fill button: the window in front, snapped
            layout = params.unpack()[0]
            QTimer.singleShot(0, lambda: self.snapFront(layout))
        elif method in ("Overview", "SnapPreview", "SnapAssist", "Switcher"):
            text = params.unpack()[0]
            try:
                data = json.loads(text) if text else {}
            except ValueError:
                data = {}
            if method == "Overview":
                self._overview = data
            elif method == "SnapPreview":
                self._snap_preview = data
            elif method == "SnapAssist":
                self._snap_assist = data
            else:
                self._switcher = data
            self.sceneChanged.emit()
        elif method == "AppMenu":                                # Alt on its own (KWin)
            self.keyWanted.emit("menu")
        elif method == "Windows":
            self._read_windows(params.unpack()[0])
        elif method == "Activated":
            key, found = params.unpack()
            command = self._pending.pop(key, "")
            if not found and command and self._apps is not None:
                self._apps.launch(command)                   # no window of it after all: start it (it hands over if running)
        inv.return_value(None)

    def _kwin_running(self) -> bool:
        return self._has_name("org.kde.KWin")

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

    def _own_compositor(self) -> bool:
        """Huginn's own compositor (org.huginn.Compositor with ActivateApp) is running this session."""
        return self._has_name("org.huginn.Compositor")

    def _has_name(self, name: str) -> bool:
        try:
            return bool(self.sb.call_sync("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus", "NameHasOwner",
                                          GLib.Variant("(s)", (name,)), GLib.VariantType("(b)"), 0, 1000, None).unpack()[0])
        except GLib.Error:
            return False

    def _compositor(self, method: str, args: GLib.Variant | None, reply: str | None):
        """A call to Huginn's own compositor; None when it can't be made."""
        try:
            out = self.sb.call_sync("org.huginn.Compositor", "/org/huginn/Compositor", "org.huginn.Compositor", method, args,
                                    GLib.VariantType(reply) if reply else None, 0, 2000, None)
            return out.unpack() if reply else ()
        except GLib.Error:
            return None

    @Slot("QVariantMap", result=bool)
    def activateApp(self, app: dict) -> bool:
        """A running app's window comes forward (un-minimised) instead of the app starting again. Huginn's own
        compositor answers at once; KWin answers through Activated. With no window of it there, the app is started
        after all."""
        ids = [i.lower() for i in (app.get("wm", ""), app.get("id", "")) if i]
        if not ids or self._demo or not self.sb:
            return False
        if self._apps is None or app.get("name") not in self._apps.running:
            return False
        if self._own_compositor():
            found = self._compositor("ActivateApp", GLib.Variant("(s)", (" ".join(ids),)), "(b)")
            return bool(found and found[0])
        if not self._kwin_running():
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
        """The app menu in the top bar: minimise or close the window in front."""
        if action not in ("minimise", "close") or self._demo or not self.sb:
            return
        if self._own_compositor():
            self._compositor("WindowAction", GLib.Variant("(s)", (action,)), None)
            return
        js = {"minimise": "if (workspace.activeWindow) workspace.activeWindow.minimized = true;",
              "close": "if (workspace.activeWindow) workspace.activeWindow.closeWindow();"}.get(action)
        self.kwin(js)

    battery = Property("QVariantMap", lambda self: self._battery, notify=changed)
    network = Property("QVariantMap", lambda self: self._network, notify=changed)
    bluetooth = Property("QVariantMap", lambda self: self._bt, notify=changed)
    levels = Property("QVariantMap", lambda self: self._levels, notify=changed)
    dnd = Property(bool, lambda self: self._dnd, notify=changed)
    nightLight = Property("QVariantMap", lambda self: self._night, notify=changed)
    notifications = Property("QVariantList", lambda self: self._notes, notify=changed)
    waiting = Property(bool, lambda self: self._waiting(), notify=changed)
    active = Property("QVariantMap", lambda self: self._active, notify=activeChanged)
    windows = Property("QVariantList", lambda self: self._windows, notify=windowsChanged)
    menus = Property("QVariantMap", lambda self: self._menus, notify=menusChanged)
    overview = Property("QVariantMap", lambda self: self._overview, notify=sceneChanged)
    snapPreview = Property("QVariantMap", lambda self: self._snap_preview, notify=sceneChanged)
    snapAssist = Property("QVariantMap", lambda self: self._snap_assist, notify=sceneChanged)
    switcher = Property("QVariantMap", lambda self: self._switcher, notify=sceneChanged)
    ownCompositor = Property(bool, lambda self: bool(self.sb) and self._own_compositor(), constant=True)
    spaces = Property("QVariantMap", lambda self: self._spaces, notify=windowsChanged)
    powerCaps = Property("QVariantMap", lambda self: self._power, notify=changed)

    def _primary(self) -> str:
        from PySide6.QtGui import QGuiApplication
        screen = QGuiApplication.primaryScreen() if QGuiApplication.instance() else None
        return screen.name() if screen else ""
    primaryScreenChanged = Signal()
    primaryScreen = Property(str, _primary, notify=primaryScreenChanged)

    def _screens(self) -> list:
        """The screens as QScreen objects (QML's own Qt.application.screens are a different type, which layer-shell
        surfaces can't be given), for one wallpaper per screen."""
        from PySide6.QtGui import QGuiApplication
        return list(QGuiApplication.screens()) if QGuiApplication.instance() else []
    screenList = Property("QVariantList", _screens, notify=primaryScreenChanged)
