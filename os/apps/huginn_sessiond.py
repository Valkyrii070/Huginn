"""Huginn OS's session daemon: the background services Plasma used to provide, in one small process.

    Notifications   the session's notification server (org.freedesktop.Notifications): banners at the top right,
                    actions, replacing, Do Not Disturb and per-app choices from Settings › Notifications.
    Keys            volume, microphone, brightness, keyboard light, media and power keys, with an on-screen level.
                    In the KWin session they're registered with KWin's shortcut service (kglobalaccel); Huginn's
                    own compositor sends them over D-Bus instead (org.huginn.Session.Key).
    Power           Settings › Battery & Power carried out: dim, screen off, lock and sleep when idle (on battery or
                    plugged in), the lid, the power button (it asks), low and critical battery. Apps that ask the
                    screen to stay on (videos, calls) are listened to: org.freedesktop.PowerManagement.Inhibit, KDE's
                    PolicyAgent (which the screen locker and the portal forward to), and logind's idle inhibitors.
    Wi‑Fi           a NetworkManager secret agent: when a network needs its password, Huginn asks for it.
    Bluetooth       a BlueZ pairing agent: confirm the code on both devices, or type a PIN.

Everything is on D-Bus through Gio; the windows (banners, the level, the questions) are QML. In the KWin session
they're layer-shell surfaces; under Huginn's compositor they're ordinary windows that it places itself.

    python3 huginn_sessiond.py            the daemon (started by huginn-session-apps)
    python3 huginn_sessiond.py --demo     its windows with made-up content, for a look
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
for shell_dir in (HERE.parent / "shell", Path("/usr/share/huginn-shell")):
    if (shell_dir / "huginn_shell.py").exists():
        sys.path.insert(0, str(shell_dir))
        break

from gi.repository import Gio, GLib  # noqa: E402
from PySide6.QtCore import Property, QFileSystemWatcher, QObject, QTimer, QUrl, Qt, Signal, Slot  # noqa: E402
from PySide6.QtGui import QGuiApplication, QIcon, QImage  # noqa: E402
from PySide6.QtQml import QQmlApplicationEngine  # noqa: E402

CONFIG = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
DATA = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share")
RUNTIME = Path(os.environ.get("XDG_RUNTIME_DIR") or "/tmp")
POWER_FILE = CONFIG / "huginn" / "power.json"
NOTIFY_FILE = CONFIG / "huginn-shell" / "notifications.json"
SYSFS = Path(os.environ.get("HUGINN_SYSFS") or "/sys/class")      # tests point this at a pretend /sys/class
TESTING = os.environ.get("HUGINN_SESSIOND_TEST") == "1"          # tests may answer questions over D-Bus
HISTORY = DATA / "huginn" / "notifications.jsonl"
# The installation drive's session: its account has no password, so nothing locks it by itself (asking still does).
LIVE = os.path.exists("/cdrom/casper/filesystem.squashfs")

POWER_DEFAULTS = {"ac": {"screenOff": 600, "sleep": 900}, "battery": {"screenOff": 300, "sleep": 600},
                  "lid": "1", "button": "16", "lockOnScreenOff": True, "low": 10, "critical": 5, "criticalAction": "2"}
# Settings stores PowerDevil's numbers, so files written before still mean the same
ACTIONS = {"0": "nothing", "1": "sleep", "2": "hibernate", "8": "shutdown", "16": "ask", "32": "lock", "64": "screenOff"}



def qt_runs_glib() -> bool:
    """Ubuntu's Qt runs GLib's loop itself, and GLib's sources (D-Bus) are served with Qt's events. Turning GLib's
    loop by hand from a Qt timer as well would run Qt's events inside Qt's events: a window drawn in the middle of
    drawing another, which can leave a surface waiting forever for its compositor."""
    from PySide6.QtCore import QAbstractEventDispatcher
    d = QAbstractEventDispatcher.instance()
    return d is not None and "Glib" in d.metaObject().className()

def power_settings() -> dict:
    try:
        saved = json.loads(POWER_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        saved = {}
    out = json.loads(json.dumps(POWER_DEFAULTS))
    for k, v in saved.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k].update(v)
        else:
            out[k] = v
    return out


def action_of(code) -> str:
    code = str(code)
    return ACTIONS.get(code, code if code in ACTIONS.values() else "nothing")


def run(argv: list, timeout: float = 5) -> tuple:
    try:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout
    except (OSError, subprocess.SubprocessError):
        return 127, ""


# ================================================================================================ D-Bus helpers
class Bus:
    """A Gio connection with a few conveniences: call, export, own a name, follow signals."""

    def __init__(self, kind):
        self.conn = Gio.bus_get_sync(kind, None) if not isinstance(kind, Gio.DBusConnection) else kind
        self.exported = []
        self.subs = []

    def call(self, name, path, iface, method, args=None, reply=None, timeout=4000, fds=None):
        try:
            if fds is not None:
                res, fdl = self.conn.call_with_unix_fd_list_sync(name, path, iface, method, args, GLib.VariantType(reply) if reply else None,
                                                                 Gio.DBusCallFlags.NONE, timeout, None, None)
                return res.unpack() if res else None, fdl
            res = self.conn.call_sync(name, path, iface, method, args, GLib.VariantType(reply) if reply else None, Gio.DBusCallFlags.NONE, timeout, None)
            return res.unpack() if res is not None else None
        except GLib.Error:
            return (None, None) if fds is not None else None

    def fire(self, name, path, iface, method, args=None, timeout=120000):
        """Call and don't wait (logind may stop to ask for a password first)."""
        self.conn.call(name, path, iface, method, args, None, Gio.DBusCallFlags.ALLOW_INTERACTIVE_AUTHORIZATION, timeout, None, None)

    def get(self, name, path, iface, prop, default=None):
        got = self.call(name, path, "org.freedesktop.DBus.Properties", "Get", GLib.Variant("(ss)", (iface, prop)), "(v)")
        return got[0] if got else default

    def export(self, path, xml, handler):
        node = Gio.DBusNodeInfo.new_for_xml(xml)
        for iface in node.interfaces:
            def call(conn, sender, p, i, method, params, inv, _h=handler):
                try:
                    out = _h(method, params.unpack(), inv, sender, i)
                except Exception as err:                      # noqa: BLE001  (an answer, never a hang)
                    inv.return_dbus_error("org.huginn.Session.Error", str(err))
                    return
                if out is not Ellipsis:                        # Ellipsis: the handler answers later itself
                    inv.return_value(out)
            self.exported.append(self.conn.register_object(path, iface, call, None, None))

    def own(self, name, replace=True):
        flags = Gio.BusNameOwnerFlags.ALLOW_REPLACEMENT | (Gio.BusNameOwnerFlags.REPLACE if replace else Gio.BusNameOwnerFlags.NONE)
        return Gio.bus_own_name_on_connection(self.conn, name, flags, None, None)

    def signal(self, path, iface, name, args):
        try:
            self.conn.emit_signal(None, path, iface, name, args)
        except GLib.Error:
            pass

    def follow(self, sender, iface, member, path, callback):
        self.subs.append(self.conn.signal_subscribe(sender, iface, member, path, None, Gio.DBusSignalFlags.NONE,
                                                    lambda c, s, p, i, m, params: callback(s, p, params.unpack())))

    def has(self, name) -> bool:
        got = self.call("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus", "NameHasOwner", GLib.Variant("(s)", (name,)), "(b)")
        return bool(got and got[0])


NOTIFY_XML = """<node><interface name="org.freedesktop.Notifications">
  <method name="GetCapabilities"><arg type="as" direction="out"/></method>
  <method name="Notify"><arg type="s" name="app_name" direction="in"/><arg type="u" name="replaces_id" direction="in"/>
    <arg type="s" name="app_icon" direction="in"/><arg type="s" name="summary" direction="in"/><arg type="s" name="body" direction="in"/>
    <arg type="as" name="actions" direction="in"/><arg type="a{sv}" name="hints" direction="in"/><arg type="i" name="expire_timeout" direction="in"/>
    <arg type="u" direction="out"/></method>
  <method name="CloseNotification"><arg type="u" name="id" direction="in"/></method>
  <method name="GetServerInformation"><arg type="s" direction="out"/><arg type="s" direction="out"/><arg type="s" direction="out"/><arg type="s" direction="out"/></method>
  <signal name="NotificationClosed"><arg type="u"/><arg type="u"/></signal>
  <signal name="ActionInvoked"><arg type="u"/><arg type="s"/></signal>
  <signal name="ActivationToken"><arg type="u"/><arg type="s"/></signal>
</interface></node>"""

SESSION_XML = """<node><interface name="org.huginn.Session">
  <method name="Key"><arg type="s" name="name" direction="in"/></method>
  <method name="Shown"><arg type="s" direction="out"/></method>
  <method name="Notifications"><arg type="s" direction="out"/></method>
  <method name="ClearNotifications"/>
  <method name="Reload"/>
  <method name="Levels"><arg type="d" name="brightness" direction="out"/><arg type="d" name="volume" direction="out"/><arg type="b" name="muted" direction="out"/></method>
  <method name="SetBrightness"><arg type="d" name="level" direction="in"/></method>
  <method name="SetVolume"><arg type="d" name="level" direction="in"/></method>
  <method name="SetMuted"><arg type="b" name="muted" direction="in"/></method>
  <method name="SetDoNotDisturb"><arg type="b" name="on" direction="in"/></method>
  <method name="Do"><arg type="s" name="action" direction="in"/></method>
  <method name="Answer"><arg type="s" name="key" direction="in"/><arg type="s" name="text" direction="in"/><arg type="s" name="identity" direction="in"/></method>
  <property name="DoNotDisturb" type="b" access="read"/>
</interface></node>"""

INHIBIT_XML = """<node><interface name="org.freedesktop.PowerManagement.Inhibit">
  <method name="Inhibit"><arg type="s" name="application" direction="in"/><arg type="s" name="reason" direction="in"/><arg type="u" direction="out"/></method>
  <method name="UnInhibit"><arg type="u" name="cookie" direction="in"/></method>
  <method name="HasInhibit"><arg type="b" direction="out"/></method>
  <signal name="HasInhibitChanged"><arg type="b"/></signal>
</interface></node>"""

POLICY_XML = """<node><interface name="org.kde.Solid.PowerManagement.PolicyAgent">
  <method name="AddInhibition"><arg type="u" name="types" direction="in"/><arg type="s" name="appName" direction="in"/>
    <arg type="s" name="reason" direction="in"/><arg type="u" direction="out"/></method>
  <method name="ReleaseInhibition"><arg type="u" name="cookie" direction="in"/></method>
  <method name="HasInhibition"><arg type="u" name="types" direction="in"/><arg type="b" direction="out"/></method>
</interface></node>"""

NM_AGENT_XML = """<node><interface name="org.freedesktop.NetworkManager.SecretAgent">
  <method name="GetSecrets"><arg type="a{sa{sv}}" name="connection" direction="in"/><arg type="o" name="connection_path" direction="in"/>
    <arg type="s" name="setting_name" direction="in"/><arg type="as" name="hints" direction="in"/><arg type="u" name="flags" direction="in"/>
    <arg type="a{sa{sv}}" direction="out"/></method>
  <method name="CancelGetSecrets"><arg type="o" name="connection_path" direction="in"/><arg type="s" name="setting_name" direction="in"/></method>
  <method name="SaveSecrets"><arg type="a{sa{sv}}" name="connection" direction="in"/><arg type="o" name="connection_path" direction="in"/></method>
  <method name="DeleteSecrets"><arg type="a{sa{sv}}" name="connection" direction="in"/><arg type="o" name="connection_path" direction="in"/></method>
</interface></node>"""

BT_AGENT_XML = """<node><interface name="org.bluez.Agent1">
  <method name="Release"/>
  <method name="RequestPinCode"><arg type="o" name="device" direction="in"/><arg type="s" direction="out"/></method>
  <method name="DisplayPinCode"><arg type="o" name="device" direction="in"/><arg type="s" name="pincode" direction="in"/></method>
  <method name="RequestPasskey"><arg type="o" name="device" direction="in"/><arg type="u" direction="out"/></method>
  <method name="DisplayPasskey"><arg type="o" name="device" direction="in"/><arg type="u" name="passkey" direction="in"/><arg type="q" name="entered" direction="in"/></method>
  <method name="RequestConfirmation"><arg type="o" name="device" direction="in"/><arg type="u" name="passkey" direction="in"/></method>
  <method name="RequestAuthorization"><arg type="o" name="device" direction="in"/></method>
  <method name="AuthorizeService"><arg type="o" name="device" direction="in"/><arg type="s" name="uuid" direction="in"/></method>
  <method name="Cancel"/>
</interface></node>"""

NM_NO_SECRETS = "org.freedesktop.NetworkManager.SecretAgent.NoSecrets"
NM_CANCELLED = "org.freedesktop.NetworkManager.SecretAgent.UserCanceled"
BT_REJECTED, BT_CANCELED = "org.bluez.Error.Rejected", "org.bluez.Error.Canceled"
KEY_NAMES = {   # our name → (Qt key, what it's called in KWin's shortcut list)
    "volumeUp": ("Key_VolumeUp", "Volume up"), "volumeDown": ("Key_VolumeDown", "Volume down"), "volumeMute": ("Key_VolumeMute", "Mute"),
    "micMute": ("Key_MicMute", "Mute the microphone"), "brightnessUp": ("Key_MonBrightnessUp", "Brighter screen"),
    "brightnessDown": ("Key_MonBrightnessDown", "Dimmer screen"), "keyboardLightUp": ("Key_KeyboardBrightnessUp", "Brighter keyboard"),
    "keyboardLightDown": ("Key_KeyboardBrightnessDown", "Dimmer keyboard"), "keyboardLight": ("Key_KeyboardLightOnOff", "Keyboard light on or off"),
    "power": ("Key_PowerOff", "Power button"), "sleep": ("Key_Sleep", "Sleep"), "suspend": ("Key_Suspend", "Sleep (suspend key)"),
    "playPause": ("Key_MediaTogglePlayPause", "Play or pause"), "play": ("Key_MediaPlay", "Play"), "pause": ("Key_MediaPause", "Pause"),
    "next": ("Key_MediaNext", "Next track"), "previous": ("Key_MediaPrevious", "Previous track"), "stop": ("Key_MediaStop", "Stop")}


# ================================================================================================ notifications
def strip_markup(text: str) -> str:
    """The body's simple markup (<b>, <i>, <a>, &amp;) as plain text: banners show text, not HTML."""
    text = re.sub(r"<br\s*/?>", "\n", text or "", flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    for a, b in (("&lt;", "<"), ("&gt;", ">"), ("&quot;", '"'), ("&apos;", "'"), ("&#39;", "'"), ("&amp;", "&")):
        text = text.replace(a, b)
    return text.strip()


def icon_url(name: str, cache: Path) -> str:
    """A URL QML can show for an icon given as a path, a file:// URL or a themed icon name."""
    if not name:
        return ""
    if name.startswith("file://"):
        return name
    if name.startswith("/"):
        return QUrl.fromLocalFile(name).toString() if os.path.isfile(name) else ""
    for folder in ("/usr/share/icons/hicolor/256x256/apps", "/usr/share/icons/hicolor/128x128/apps", "/usr/share/icons/hicolor/scalable/apps",
                   str(HERE.parent / "config/overlay/usr/share/icons/hicolor/256x256/apps"), "/usr/share/pixmaps"):
        for ext in (".png", ".svg"):
            f = Path(folder) / (name + ext)
            if f.is_file():
                return QUrl.fromLocalFile(str(f)).toString()
    if QIcon.hasThemeIcon(name):
        out = cache / f"icon-{re.sub(r'[^A-Za-z0-9_.-]', '_', name)}.png"
        if not out.exists():
            QIcon.fromTheme(name).pixmap(96, 96).save(str(out))
        return QUrl.fromLocalFile(str(out)).toString()
    return ""


def image_data(v, cache: Path, key: str) -> str:
    """The image-data hint (width, height, rowstride, has alpha, bits, channels, bytes) saved as a PNG."""
    try:
        w, h, stride, alpha, _bits, _ch, data = v
        img = QImage(bytes(data), w, h, stride, QImage.Format_RGBA8888 if alpha else QImage.Format_RGB888).copy()
        out = cache / f"image-{key}.png"
        img.save(str(out))
        return QUrl.fromLocalFile(str(out)).toString()
    except (TypeError, ValueError):
        return ""


class Notifications(QObject):
    changed = Signal()

    def __init__(self, bus: Bus, demo: bool = False):
        super().__init__()
        self.bus, self._demo = bus, demo
        self._next = 1
        self._shown = []                      # banners on screen: dicts
        self._timers = {}
        self._cache = RUNTIME / "huginn-notifications"
        self._cache.mkdir(parents=True, exist_ok=True)
        self._prefs = {}
        self._load_prefs()
        if bus:
            bus.export("/org/freedesktop/Notifications", NOTIFY_XML, self._call)
            bus.own("org.freedesktop.Notifications")

    def _load_prefs(self) -> None:
        try:
            self._prefs = json.loads(NOTIFY_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self._prefs = {}

    def quiet(self) -> bool:
        """Do Not Disturb: switched on, or the scheduled hours (Settings › Notifications)."""
        p = self._prefs
        if p.get("dnd"):
            return True
        if p.get("focus"):
            now = time.strftime("%H:%M")
            a, b = p.get("from", "22:00"), p.get("to", "07:00")
            return (a <= now < b) if a < b else (now >= a or now < b)
        return False

    def set_quiet(self, on: bool) -> None:
        """Do Not Disturb on or off from the control centre: the same switch as Settings › Notifications."""
        self._prefs["dnd"] = on
        try:
            NOTIFY_FILE.parent.mkdir(parents=True, exist_ok=True)
            part = NOTIFY_FILE.with_suffix(".saving")
            part.write_text(json.dumps(self._prefs, indent=1), encoding="utf-8")
            part.replace(NOTIFY_FILE)
        except OSError:
            pass

    def _app_prefs(self, app: str, entry: str) -> dict:
        per = self._prefs.get("apps") or {}
        for key in (entry, "huginn-" + app.lower(), app.lower()):
            if key and key in per:
                return per[key]
        return {}

    def _call(self, method, args, inv, sender, iface):
        if method == "GetCapabilities":
            return GLib.Variant("(as)", (["body", "actions", "icon-static", "persistence", "body-hyperlinks"],))
        if method == "GetServerInformation":
            return GLib.Variant("(ssss)", ("Huginn", "Huginn OS", "0.1", "1.2"))
        if method == "CloseNotification":
            self.close(args[0], 3)
            return None
        if method == "Notify":
            return GLib.Variant("(u)", (self.notify(*args, sender=sender),))
        return None

    def notify(self, app, replaces, icon, summary, body, actions, hints, timeout, sender="") -> int:
        nid = replaces if replaces and any(n["id"] == replaces for n in self._shown) else self._next
        if nid == self._next:
            self._next += 1
        entry = str(hints.get("desktop-entry", "")) if hints else ""
        urgency = int(hints.get("urgency", 1)) if hints else 1
        mine = self._app_prefs(app, entry)
        img = ""
        if hints:
            for k in ("image-data", "image_data", "icon_data"):
                if k in hints:
                    img = image_data(hints[k], self._cache, str(nid))
                    break
            if not img:
                img = icon_url(str(hints.get("image-path") or hints.get("image_path") or ""), self._cache)
        item = {"id": nid, "app": app or "", "icon": img or icon_url(icon, self._cache) or icon_url(entry, self._cache),
                "summary": summary or app or "", "body": strip_markup(body), "urgency": urgency, "time": time.strftime("%H:%M"),
                "actions": [{"key": actions[i], "label": actions[i + 1] or "Open"} for i in range(0, len(actions) - 1, 2) if actions[i] != "default"],
                "hasDefault": "default" in actions[0::2], "resident": bool(hints.get("resident")) if hints else False,
                "sender": sender}
        self._remember(item)
        if mine.get("allow") is False:
            return nid
        if (self.quiet() and urgency < 2) or mine.get("banner") is False:
            return nid                                        # kept in the history, not shown
        self._shown = [n for n in self._shown if n["id"] != nid]
        self._shown.insert(0, item)
        if len(self._shown) > 4:                              # four at most; the oldest steps aside
            for old in self._shown[4:]:
                self._expire(old["id"])
        wait = 0 if urgency >= 2 else (timeout if timeout > 0 else 6500)
        self._arm(nid, wait)
        self.changed.emit()
        return nid

    def _arm(self, nid: int, wait: int) -> None:
        t = self._timers.pop(nid, None)
        if t:
            t.stop()
        if wait > 0:
            t = QTimer(self, singleShot=True, interval=wait)
            t.timeout.connect(lambda n=nid: self.close(n, 1))
            t.start()
            self._timers[nid] = t

    def _expire(self, nid):
        self.close(nid, 1)

    def _remember(self, item: dict) -> None:
        if self._demo:
            return
        try:
            HISTORY.parent.mkdir(parents=True, exist_ok=True)
            lines = HISTORY.read_text(encoding="utf-8").splitlines()[-99:] if HISTORY.exists() else []
            lines.append(json.dumps({k: item[k] for k in ("app", "summary", "body", "time", "icon")} | {"at": int(time.time())}))
            HISTORY.write_text("\n".join(lines) + "\n", encoding="utf-8")
        except OSError:
            pass

    def close(self, nid: int, reason: int) -> None:
        t = self._timers.pop(nid, None)
        if t:
            t.stop()
        if any(n["id"] == nid for n in self._shown):
            self._shown = [n for n in self._shown if n["id"] != nid]
            self.changed.emit()
        if self.bus:
            self.bus.signal("/org/freedesktop/Notifications", "org.freedesktop.Notifications", "NotificationClosed", GLib.Variant("(uu)", (nid, reason)))

    shown = Property("QVariantList", lambda self: self._shown, notify=changed)

    @Slot(int, str)
    def invoke(self, nid: int, key: str) -> None:
        item = next((n for n in self._shown if n["id"] == nid), None)
        if self.bus:
            self.bus.signal("/org/freedesktop/Notifications", "org.freedesktop.Notifications", "ActionInvoked", GLib.Variant("(us)", (nid, key)))
        if item and not item.get("resident"):
            self.close(nid, 2)

    @Slot(int)
    def dismiss(self, nid: int) -> None:
        self.close(nid, 2)

    @Slot(int, bool)
    def hold(self, nid: int, held: bool) -> None:
        """The pointer is on a banner: it waits; when it leaves, it gives the reader a moment more."""
        item = next((n for n in self._shown if n["id"] == nid), None)
        if not item or item["urgency"] >= 2:
            return
        if held:
            t = self._timers.pop(nid, None)
            if t:
                t.stop()
        else:
            self._arm(nid, 3000)

    def history(self) -> str:
        try:
            return HISTORY.read_text(encoding="utf-8")
        except OSError:
            return ""


# ================================================================================================ levels: volume, brightness
def volume_get() -> tuple:
    code, out = run(["wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@"])
    m = re.search(r"Volume:\s*([\d.]+)", out)
    if code == 0 and m:
        return float(m.group(1)), "[MUTED]" in out
    code, out = run(["pactl", "get-sink-volume", "@DEFAULT_SINK@"])
    m = re.search(r"(\d+)%", out)
    _, muted = run(["pactl", "get-sink-mute", "@DEFAULT_SINK@"])
    return (int(m.group(1)) / 100 if m else 0.0), "yes" in muted


def volume_change(step: float) -> None:
    if shutil.which("wpctl"):
        run(["wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "0"])
        run(["wpctl", "set-volume", "-l", "1.0", "@DEFAULT_AUDIO_SINK@", f"{abs(step) * 100:.0f}%{'+' if step > 0 else '-'}"])
    else:
        run(["pactl", "set-sink-mute", "@DEFAULT_SINK@", "0"])
        run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{'+' if step > 0 else '-'}{abs(step) * 100:.0f}%"])


def volume_set(level: float) -> None:
    level = max(0.0, min(1.0, level))
    if shutil.which("wpctl"):
        run(["wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "0"])
        run(["wpctl", "set-volume", "-l", "1.0", "@DEFAULT_AUDIO_SINK@", f"{level:.2f}"])
    else:
        run(["pactl", "set-sink-mute", "@DEFAULT_SINK@", "0"])
        run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{round(level * 100)}%"])


def volume_mute(muted: bool) -> None:
    if shutil.which("wpctl"):
        run(["wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "1" if muted else "0"])
    else:
        run(["pactl", "set-sink-mute", "@DEFAULT_SINK@", "1" if muted else "0"])


def mute_toggle(source: bool = False) -> bool:
    if shutil.which("wpctl"):
        target = "@DEFAULT_AUDIO_SOURCE@" if source else "@DEFAULT_AUDIO_SINK@"
        run(["wpctl", "set-mute", target, "toggle"])
        _, out = run(["wpctl", "get-volume", target])
        return "[MUTED]" in out
    if source:
        run(["pactl", "set-source-mute", "@DEFAULT_SOURCE@", "toggle"])
        return "yes" in run(["pactl", "get-source-mute", "@DEFAULT_SOURCE@"])[1]
    run(["pactl", "set-sink-mute", "@DEFAULT_SINK@", "toggle"])
    return "yes" in run(["pactl", "get-sink-mute", "@DEFAULT_SINK@"])[1]


class Light:
    """A backlight (/sys/class/backlight) or the keyboard's (/sys/class/leds/*kbd_backlight*), changed through
    logind (no root needed for the person at the seat), or straight through sysfs where that's writable."""

    def __init__(self, bus: Bus, keyboard: bool = False, root: Path = SYSFS):
        self.bus = bus
        self.subsystem = "leds" if keyboard else "backlight"
        self.dev = None
        folder = root / self.subsystem
        found = sorted(folder.glob("*kbd_backlight*") if keyboard else folder.glob("*")) if folder.is_dir() else []
        rank = {"firmware": 0, "platform": 1, "raw": 2}
        if not keyboard:
            found.sort(key=lambda d: rank.get((d / "type").read_text().strip() if (d / "type").exists() else "raw", 3))
        self.dev = found[0] if found else None
        self.saved = None

    def ok(self) -> bool:
        return self.dev is not None

    def max(self) -> int:
        try:
            return max(1, int((self.dev / "max_brightness").read_text()))
        except (OSError, ValueError, TypeError):
            return 1

    def now(self) -> int:
        try:
            return int((self.dev / "brightness").read_text())
        except (OSError, ValueError, TypeError):
            return 0

    def set(self, value: int) -> None:
        if not self.dev:
            return
        value = max(0, min(self.max(), int(value)))
        done = self.bus and self.bus.call("org.freedesktop.login1", "/org/freedesktop/login1/session/auto", "org.freedesktop.login1.Session",
                                           "SetBrightness", GLib.Variant("(ssu)", (self.subsystem, self.dev.name, value)), timeout=2000) is not None
        if not done:
            try:
                (self.dev / "brightness").write_text(str(value))
            except OSError:
                pass

    def fraction(self) -> float:
        return self.now() / self.max() if self.dev else 0.0

    def step(self, delta: float, floor: int = 1) -> float:
        """Up or down by a share of the range (a screen never goes fully dark from the keys)."""
        m = self.max()
        if m <= 10:                                           # few steps (keyboard lights): one at a time
            self.set(self.now() + (1 if delta > 0 else -1))
        else:
            self.set(max(floor if self.subsystem == "backlight" else 0, round(self.now() + delta * m)))
        return self.fraction()


# ================================================================================================ the session
class Session(QObject):
    """Keys, power, the agents and the windows' state, in one object the QML reads."""
    osdChanged = Signal()
    promptChanged = Signal()

    def __init__(self, session_bus: Bus, system_bus: Bus, notes: Notifications, demo: bool = False):
        super().__init__()
        self.sb, self.yb, self.notes, self._demo = session_bus, system_bus, notes, demo
        self._osd = {"kind": "", "level": 0.0, "muted": False, "text": ""}
        self._osd_timer = QTimer(self, singleShot=True, interval=1400, timeout=self._osd_hide)
        self._prompts = []                   # questions waiting: the first is shown
        self.screen = Light(system_bus)
        self.keyboard = Light(system_bus, keyboard=True)
        self.power = power_settings()
        self._stage = ""                     # "", "dim", "off", "slept"
        self._dimmed_from = None
        self._inhibits = {}                  # cookie → (sender, app, reason, types)
        self._cookie = 1
        self._lid_fd = self._key_fd = None
        self._battery_warned = ""
        self._compositor = False
        watcher = QFileSystemWatcher(self)
        for f in (POWER_FILE, NOTIFY_FILE):
            f.parent.mkdir(parents=True, exist_ok=True)
            watcher.addPath(str(f.parent))
        watcher.directoryChanged.connect(self.reload)
        self._watcher = watcher
        if demo:
            return
        if session_bus:
            session_bus.export("/org/huginn/Session", SESSION_XML, self._session_call)
            session_bus.own("org.huginn.Session")
            session_bus.export("/org/freedesktop/PowerManagement/Inhibit", INHIBIT_XML, self._inhibit_call)
            session_bus.own("org.freedesktop.PowerManagement.Inhibit", replace=False)
            session_bus.export("/org/kde/Solid/PowerManagement/PolicyAgent", POLICY_XML, self._policy_call)
            session_bus.own("org.kde.Solid.PowerManagement.PolicyAgent", replace=False)
            session_bus.follow("org.freedesktop.DBus", "org.freedesktop.DBus", "NameOwnerChanged", "/org/freedesktop/DBus", self._owner_changed)
            self._compositor = session_bus.has("org.huginn.Compositor")
            if not self._compositor:
                QTimer.singleShot(1500, self.register_keys)
        if system_bus:
            system_bus.export("/org/freedesktop/NetworkManager/SecretAgent", NM_AGENT_XML, self._nm_call)
            system_bus.export("/org/huginn/bluetooth/agent", BT_AGENT_XML, self._bt_call)
            system_bus.follow("org.freedesktop.UPower", "org.freedesktop.DBus.Properties", "PropertiesChanged", None, lambda *a: self.check_battery())
            system_bus.follow("org.freedesktop.UPower", "org.freedesktop.DBus.Properties", "PropertiesChanged", "/org/freedesktop/UPower", self._upower_changed)
            system_bus.follow("org.freedesktop.DBus", "org.freedesktop.DBus", "NameOwnerChanged", "/org/freedesktop/DBus", self._system_owner)
            QTimer.singleShot(500, self.register_agents)
            QTimer.singleShot(800, self.take_inhibitors)
        self._idle = QTimer(self, interval=2000, timeout=self.tick)
        self._idle.start()
        self._battery = QTimer(self, interval=60000, timeout=self.check_battery)
        self._battery.start()
        QTimer.singleShot(3000, self.check_battery)

    # ---------------------------------------------------------------- settings
    @Slot()
    def reload(self, *_):
        self.power = power_settings()
        self.notes._load_prefs()
        self.take_inhibitors()

    def _session_call(self, method, args, inv, sender, iface):
        if method == "Key":
            self.key(args[0])
            return None
        if method == "Notifications":
            return GLib.Variant("(s)", (self.notes.history(),))
        if method == "Shown":                                 # what's on screen now: banners, the level, a question
            return GLib.Variant("(s)", (json.dumps({"banners": self.notes._shown, "osd": self._osd, "prompt": self.prompt}),))
        if method == "Answer" and TESTING:                    # tests only: answer the question on screen
            if self._prompts:
                self.answer(self._prompts[0][0]["uid"], args[0], args[1], args[2])
            return None
        if method == "Levels":                                # the control centre's sliders (-1: no screen light here)
            level, muted = volume_get()
            return GLib.Variant("(ddb)", (self.screen.fraction() if self.screen.ok() else -1.0, float(level), bool(muted)))
        if method == "SetBrightness":
            if self.screen.ok():
                self._dimmed_from = None
                self.screen.set(max(1, round(float(args[0]) * self.screen.max())))
            return None
        if method == "SetVolume":
            volume_set(float(args[0]))
            return None
        if method == "SetMuted":
            volume_mute(bool(args[0]))
            return None
        if method == "SetDoNotDisturb":
            self.notes.set_quiet(bool(args[0]))
            return None
        if method == "Do":                                    # the start menu's power row: someone at the computer asked
            if args[0] in ("lock", "sleep", "hibernate", "restart", "shutdown", "signout"):
                self.do(args[0], interactive=True)
            return None
        if method == "ClearNotifications":
            try:
                HISTORY.unlink()
            except OSError:
                pass
            return None
        if method == "Reload":
            self.reload()
            return None
        if method == "Get":
            return GLib.Variant("(v)", (GLib.Variant("b", self.notes.quiet()),))
        return None

    # ---------------------------------------------------------------- keys
    def register_keys(self) -> None:
        """Ask KWin's shortcut service for the hardware keys (as Plasma's own services did)."""
        if not self.sb:
            return
        comp = ["huginn-session", "", "Huginn OS", ""]
        for name, (qt_key, label) in KEY_NAMES.items():
            key = getattr(Qt.Key, qt_key, None)
            if key is None:
                continue
            action = [comp[0], name, comp[2], label]
            self.sb.call("org.kde.kglobalaccel", "/kglobalaccel", "org.kde.KGlobalAccel", "doRegister", GLib.Variant("(as)", (action,)))
            for flags in (1, 2):                              # IsDefault, then SetPresent (a person's own choice wins)
                self.sb.call("org.kde.kglobalaccel", "/kglobalaccel", "org.kde.KGlobalAccel", "setShortcut",
                             GLib.Variant("(asaiu)", (action, [int(key.value) if hasattr(key, "value") else int(key)], flags)), "(ai)")
        self.sb.follow("org.kde.kglobalaccel", "org.kde.kglobalaccel.Component", "globalShortcutPressed", None,
                       lambda s, p, a: self.key(a[1]) if a and a[0] == "huginn-session" else None)

    @Slot(str)
    def key(self, name: str) -> None:
        if name in ("volumeUp", "volumeDown"):
            volume_change(0.05 if name == "volumeUp" else -0.05)
            level, muted = volume_get()
            self.osd("volume", level, muted)
        elif name == "volumeMute":
            muted = mute_toggle()
            self.osd("volume", volume_get()[0], muted)
        elif name == "micMute":
            muted = mute_toggle(source=True)
            self.osd("mic", 0.0 if muted else 1.0, muted, "Microphone off" if muted else "Microphone on")
        elif name in ("brightnessUp", "brightnessDown") and self.screen.ok():
            self._dimmed_from = None
            self.osd("brightness", self.screen.step(0.05 if name == "brightnessUp" else -0.05))
        elif name in ("keyboardLightUp", "keyboardLightDown", "keyboardLight") and self.keyboard.ok():
            if name == "keyboardLight":
                self.keyboard.set(0 if self.keyboard.now() else self.keyboard.max())
                level = self.keyboard.fraction()
            else:
                level = self.keyboard.step(0.34 if name.endswith("Up") else -0.34)
            self.osd("keyboard", level)
        elif name == "power":
            self.power_button()
        elif name in ("sleep", "suspend"):
            self.do("sleep")
        elif name in ("playPause", "play", "pause", "next", "previous", "stop"):
            self.media(name)

    def osd(self, kind: str, level: float, muted: bool = False, text: str = "") -> None:
        self._osd = {"kind": kind, "level": max(0.0, min(1.0, level)), "muted": muted, "text": text}
        self._osd_timer.start()
        self.osdChanged.emit()

    def _osd_hide(self) -> None:
        self._osd = dict(self._osd, kind="")
        self.osdChanged.emit()

    osdState = Property("QVariantMap", lambda self: self._osd, notify=osdChanged)

    def media(self, what: str) -> None:
        # The dock's live island first: the keys work on whatever is playing there (two players: the one it shows).
        if what in ("playPause", "play", "pause", "next", "previous"):
            handled = self.sb.call("org.huginn.Live", "/org/huginn/Live", "org.huginn.Live", "Media", GLib.Variant("(s)", (what,)), "(b)", 1000)
            if handled and handled[0]:
                return
        names = (self.sb.call("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus", "ListNames", None, "(as)") or ([],))[0]
        players = [n for n in names if n.startswith("org.mpris.MediaPlayer2.")]
        if not players:
            return
        playing = [p for p in players if self.sb.get(p, "/org/mpris/MediaPlayer2", "org.mpris.MediaPlayer2.Player", "PlaybackStatus") == "Playing"]
        target = (playing or players)[0]
        method = {"playPause": "PlayPause", "play": "Play", "pause": "Pause", "next": "Next", "previous": "Previous", "stop": "Stop"}[what]
        self.sb.call(target, "/org/mpris/MediaPlayer2", "org.mpris.MediaPlayer2.Player", method)

    # ---------------------------------------------------------------- power: idle
    def on_battery(self) -> bool:
        return bool(self.yb and self.yb.get("org.freedesktop.UPower", "/org/freedesktop/UPower", "org.freedesktop.UPower", "OnBattery", False))

    def idle_ms(self) -> int:
        """How long nobody has touched the computer: from Huginn's compositor, or KWin's screen locker."""
        if not self.sb:
            return 0
        if self._compositor:
            got = self.sb.call("org.huginn.Compositor", "/org/huginn/Compositor", "org.huginn.Compositor", "IdleTime", None, "(t)", timeout=1000)
        else:
            got = self.sb.call("org.freedesktop.ScreenSaver", "/ScreenSaver", "org.freedesktop.ScreenSaver", "GetSessionIdleTime", None, "(u)", timeout=1000)
        return int(got[0]) if got else 0

    def inhibited(self, what: str) -> bool:
        """Whether an app asked to keep the screen on (what="screen") or the computer awake (what="sleep")."""
        if self._demo:
            return False
        wants = 4 if what == "screen" else 1
        if any(types & wants for _s, _a, _r, types in self._inhibits.values()):
            return True
        got = self.yb and self.yb.call("org.freedesktop.login1", "/org/freedesktop/login1", "org.freedesktop.login1.Manager", "ListInhibitors", None,
                                       "(a(ssssuu))", timeout=1000)
        for w, _who, _why, mode, uid, _pid in (got[0] if got else []):
            if mode == "block" and uid == os.getuid() and ("idle" in w.split(":") or (what == "sleep" and "sleep" in w.split(":"))):
                return True
        return False

    def tick(self) -> None:
        source = "battery" if self.on_battery() else "ac"
        rules = self.power.get(source) or {}
        off, sleep = int(rules.get("screenOff") or 0), int(rules.get("sleep") or 0)
        idle = self.idle_ms() / 1000.0
        if idle < 3:
            if self._stage:
                self.wake_up()
            return
        if sleep > 0 and idle >= sleep and self._stage != "slept" and not self.inhibited("sleep"):
            self._stage = "slept"
            self.do("sleep")
        elif off > 0 and idle >= off and self._stage in ("", "dim") and not self.inhibited("screen"):
            self._stage = "off"
            if self.power.get("lockOnScreenOff", True) and not LIVE:
                self.lock()
            self.screen_off(True)
        elif off > 0 and idle >= max(15, off - 30) and self._stage == "" and not self.inhibited("screen") and self.screen.ok():
            self._stage = "dim"
            self._dimmed_from = self.screen.now()
            self.screen.set(max(1, round(self._dimmed_from * 0.3)))

    def wake_up(self) -> None:
        if self._stage == "off":
            self.screen_off(False)
        if self._dimmed_from is not None:
            self.screen.set(self._dimmed_from)
            self._dimmed_from = None
        self._stage = ""

    def screen_off(self, off: bool) -> None:
        if self._compositor:
            self.sb.call("org.huginn.Compositor", "/org/huginn/Compositor", "org.huginn.Compositor", "Blank", GLib.Variant("(b)", (off,)))
        elif off and shutil.which("kscreen-doctor"):
            run(["kscreen-doctor", "--dpms", "off"])        # any key or movement turns it back on (KWin does that)

    def lock(self) -> None:
        if not self.sb:
            return
        if self._compositor:
            self.sb.call("org.huginn.Compositor", "/org/huginn/Compositor", "org.huginn.Compositor", "Lock")
        else:
            self.sb.call("org.freedesktop.ScreenSaver", "/ScreenSaver", "org.freedesktop.ScreenSaver", "Lock")

    def do(self, what: str, interactive: bool = False) -> None:
        """Carry out an action by its name: sleep, hibernate, shutdown, restart, signout, lock, screenOff, nothing.
        interactive: a person asked (the start menu), so logind may ask for a password if it needs one."""
        if what == "signout" and self.yb:
            self.yb.fire("org.freedesktop.login1", "/org/freedesktop/login1/session/auto", "org.freedesktop.login1.Session", "Terminate")
            return
        if what == "lock":
            self.lock()
        elif what == "screenOff":
            self.screen_off(True)
            self._stage = "off"
        elif what in ("sleep", "hibernate", "shutdown", "restart") and self.yb:
            if what in ("sleep", "hibernate") and not LIVE:
                self.lock()
            method = {"sleep": "Suspend", "hibernate": "Hibernate", "shutdown": "PowerOff", "restart": "Reboot"}[what]
            if what == "hibernate":
                can = self.yb.call("org.freedesktop.login1", "/org/freedesktop/login1", "org.freedesktop.login1.Manager", "CanHibernate", None, "(s)")
                if not can or can[0] != "yes":
                    method = "Suspend"
            if interactive:
                self.yb.fire("org.freedesktop.login1", "/org/freedesktop/login1", "org.freedesktop.login1.Manager", method, GLib.Variant("(b)", (True,)))
            else:
                self.yb.call("org.freedesktop.login1", "/org/freedesktop/login1", "org.freedesktop.login1.Manager", method, GLib.Variant("(b)", (False,)))

    # ---------------------------------------------------------------- power: the lid and the button
    def take_inhibitors(self) -> None:
        """logind does the lid and the power button itself unless someone holds them: Huginn holds each one whose
        setting isn't what logind would do anyway."""
        if not self.yb or self._demo:
            return
        want_lid = action_of(self.power.get("lid")) != "sleep"
        want_key = action_of(self.power.get("button")) != "shutdown"
        self._lid_fd = self._hold("handle-lid-switch", want_lid, self._lid_fd, "Closing the lid does what Settings says")
        self._key_fd = self._hold("handle-power-key", want_key, self._key_fd, "The power button asks first")

    def _hold(self, what: str, want: bool, fd, why: str):
        if not want:
            if fd is not None:
                try:
                    os.close(fd)
                except OSError:
                    pass
            return None
        if fd is not None:
            return fd
        got, fdl = self.yb.call("org.freedesktop.login1", "/org/freedesktop/login1", "org.freedesktop.login1.Manager", "Inhibit",
                                GLib.Variant("(ssss)", (what, "Huginn OS", why, "block")), "(h)", fds=True)
        if got and fdl:
            return fdl.get(got[0])
        return None

    def _upower_changed(self, sender, path, args):
        changed = args[1] if len(args) > 1 else {}
        if "LidIsClosed" in changed and self._lid_fd is not None:
            if changed["LidIsClosed"]:
                self.do(action_of(self.power.get("lid")))
            else:
                self.wake_up()
        if "OnBattery" in changed:
            self.check_battery()

    def power_button(self) -> None:
        act = action_of(self.power.get("button"))
        if act == "ask":
            self.ask({"kind": "power", "title": "Turn off the computer?", "detail": "It turns off by itself in a minute.", "countdown": 60,
                      "buttons": [{"key": "cancel", "label": "Cancel"}, {"key": "sleep", "label": "Sleep"}, {"key": "restart", "label": "Restart"},
                                  {"key": "shutdown", "label": "Shut Down", "primary": True}], "timeoutKey": "shutdown"},
                     lambda key, text: self.do(key) if key in ("sleep", "restart", "shutdown") else None)
        else:
            self.do(act)

    # ---------------------------------------------------------------- power: the battery
    def check_battery(self) -> None:
        if not self.yb or self._demo:
            return
        dev = "/org/freedesktop/UPower/devices/DisplayDevice"
        present = self.yb.get("org.freedesktop.UPower", dev, "org.freedesktop.UPower.Device", "IsPresent", False)
        if not present or not self.on_battery():
            self._battery_warned = ""
            return
        pct = float(self.yb.get("org.freedesktop.UPower", dev, "org.freedesktop.UPower.Device", "Percentage", 100.0) or 100)
        left = int(self.yb.get("org.freedesktop.UPower", dev, "org.freedesktop.UPower.Device", "TimeToEmpty", 0) or 0)
        mins = f" (about {left // 60} minutes)" if left >= 120 else ""
        if pct <= int(self.power.get("critical", 5)) and self._battery_warned != "critical":
            self._battery_warned = "critical"
            act = action_of(self.power.get("criticalAction", "2"))
            if act in ("sleep", "hibernate", "shutdown"):
                word = {"sleep": "go to sleep", "hibernate": "hibernate", "shutdown": "shut down"}[act]
                self.ask({"kind": "battery", "title": "The battery is almost empty", "detail": f"{pct:.0f}% left. Plug in the charger, or the computer will {word} in a minute to keep your work safe.",
                          "countdown": 60, "buttons": [{"key": "cancel", "label": "Not Now"}, {"key": act, "label": word.capitalize() + " Now", "primary": True}],
                          "timeoutKey": act, "cancelWhen": "charging"},
                         lambda key, text: self.do(key) if key == act and self.on_battery() else None)
        elif pct <= int(self.power.get("low", 10)) and not self._battery_warned:
            self._battery_warned = "low"
            self.notes.notify("Battery", 0, "battery-caution", "The battery is low", f"{pct:.0f}% left{mins}. Plug in the charger soon.",
                              [], {"urgency": 2}, -1)

    # ---------------------------------------------------------------- apps keeping the screen on
    def _add_inhibit(self, sender, app, reason, types) -> int:
        cookie = self._cookie
        self._cookie += 1
        self._inhibits[cookie] = (sender, app, reason, types)
        return cookie

    def _inhibit_call(self, method, args, inv, sender, iface):
        if method == "Inhibit":
            return GLib.Variant("(u)", (self._add_inhibit(sender, args[0], args[1], 1 | 4),))
        if method == "UnInhibit":
            self._inhibits.pop(args[0], None)
            return None
        if method == "HasInhibit":
            return GLib.Variant("(b)", (bool(self._inhibits),))
        return None

    def _policy_call(self, method, args, inv, sender, iface):
        if method == "AddInhibition":
            return GLib.Variant("(u)", (self._add_inhibit(sender, args[1], args[2], int(args[0])),))
        if method == "ReleaseInhibition":
            self._inhibits.pop(args[0], None)
            return None
        if method == "HasInhibition":
            return GLib.Variant("(b)", (any(t & int(args[0]) for _s, _a, _r, t in self._inhibits.values()),))
        return None

    def _owner_changed(self, sender, path, args):
        name, _old, new = args
        if not new and name.startswith(":"):                 # an app that left takes its requests with it
            self._inhibits = {c: v for c, v in self._inhibits.items() if v[0] != name}
        if name == "org.huginn.Compositor":
            self._compositor = bool(new)
        if name == "org.kde.kglobalaccel" and new and not self._compositor:
            QTimer.singleShot(500, self.register_keys)

    def _system_owner(self, sender, path, args):
        name, _old, new = args
        if new and name in ("org.freedesktop.NetworkManager", "org.bluez"):
            QTimer.singleShot(1000, self.register_agents)

    # ---------------------------------------------------------------- Wi‑Fi and Bluetooth agents
    def register_agents(self) -> None:
        if not self.yb:
            return
        self.yb.call("org.freedesktop.NetworkManager", "/org/freedesktop/NetworkManager/AgentManager", "org.freedesktop.NetworkManager.AgentManager",
                     "RegisterWithCapabilities", GLib.Variant("(su)", ("org.huginn.SecretAgent", 0)))
        if self.yb.call("org.bluez", "/org/bluez", "org.bluez.AgentManager1", "RegisterAgent",
                        GLib.Variant("(os)", ("/org/huginn/bluetooth/agent", "KeyboardDisplay"))) is not None:
            self.yb.call("org.bluez", "/org/bluez", "org.bluez.AgentManager1", "RequestDefaultAgent", GLib.Variant("(o)", ("/org/huginn/bluetooth/agent",)))

    def _nm_call(self, method, args, inv, sender, iface):
        if method == "GetSecrets":
            connection, path, setting, hints, flags = args
            if not flags & 0x1:                               # not allowed to ask anyone: nothing to give
                inv.return_dbus_error(NM_NO_SECRETS, "Huginn only answers by asking")
                return Ellipsis
            conn = connection.get("connection", {})
            wifi = connection.get("802-11-wireless", {})
            ssid = bytes(wifi.get("ssid", b"")).decode("utf-8", "replace") if wifi.get("ssid") else conn.get("id", "the network")
            enterprise = setting == "802-1x"
            again = bool(flags & 0x2)
            self.ask({"kind": "wifi", "title": f"Password for “{ssid}”" if not enterprise else f"Sign in to “{ssid}”",
                      "detail": ("That password didn't work. Try again." if again else "This network needs a password to join."),
                      "field": "password", "identity": enterprise, "tag": str(path),
                      "buttons": [{"key": "cancel", "label": "Cancel"}, {"key": "join", "label": "Join", "primary": True}]},
                     lambda key, text, ident="": self._nm_answer(inv, setting, key, text, ident, enterprise))
            return Ellipsis
        if method == "CancelGetSecrets":
            self.cancel_prompt(str(args[0]))
            return None
        return None                                           # SaveSecrets, DeleteSecrets: NetworkManager keeps them itself

    def _nm_answer(self, inv, setting, key, text, ident, enterprise):
        if key != "join" or not text:
            inv.return_dbus_error(NM_CANCELLED, "Cancelled")
            return
        if enterprise:
            secrets = {"802-1x": {"password": GLib.Variant("s", text)} | ({"identity": GLib.Variant("s", ident)} if ident else {})}
        else:
            secrets = {"802-11-wireless-security": {"psk": GLib.Variant("s", text)}}
        inv.return_value(GLib.Variant("(a{sa{sv}})", (secrets,)))

    def _device_name(self, path: str) -> str:
        return self.yb.get("org.bluez", path, "org.bluez.Device1", "Alias", "") or self.yb.get("org.bluez", path, "org.bluez.Device1", "Name", "") or "A device"

    def _bt_call(self, method, args, inv, sender, iface):
        if method in ("Release", "Cancel"):
            self.cancel_prompt("bluetooth")
            return None
        name = self._device_name(args[0]) if args else ""
        if method == "RequestConfirmation":
            code = f"{args[1]:06d}"
            self.ask({"kind": "bluetooth", "title": f"Pair with {name}?", "detail": "Check that it shows this code too.", "code": code, "tag": "bluetooth",
                      "buttons": [{"key": "cancel", "label": "Cancel"}, {"key": "pair", "label": "Pair", "primary": True}]},
                     lambda key, text: inv.return_value(None) if key == "pair" else inv.return_dbus_error(BT_REJECTED, "Not paired"))
            return Ellipsis
        if method in ("RequestPinCode", "RequestPasskey"):
            numeric = method == "RequestPasskey"
            self.ask({"kind": "bluetooth", "title": f"Pair with {name}", "detail": "Type the code shown on it, or the one in its instructions (often 0000).",
                      "field": "number" if numeric else "pin", "tag": "bluetooth",
                      "buttons": [{"key": "cancel", "label": "Cancel"}, {"key": "pair", "label": "Pair", "primary": True}]},
                     lambda key, text: self._bt_code(inv, key, text, numeric))
            return Ellipsis
        if method in ("DisplayPinCode", "DisplayPasskey"):
            code = args[1] if method == "DisplayPinCode" else f"{args[1]:06d}"
            self.ask({"kind": "bluetooth", "title": f"Type this code on {name}", "detail": "Then press Enter on it.", "code": code, "tag": "bluetooth",
                      "buttons": [{"key": "cancel", "label": "Done"}]}, lambda key, text: None)
            return None
        if method == "RequestAuthorization":
            self.ask({"kind": "bluetooth", "title": f"Let {name} connect?", "detail": "It wants to pair without a code.", "tag": "bluetooth",
                      "buttons": [{"key": "cancel", "label": "Don't Allow"}, {"key": "allow", "label": "Allow", "primary": True}]},
                     lambda key, text: inv.return_value(None) if key == "allow" else inv.return_dbus_error(BT_REJECTED, "Not allowed"))
            return Ellipsis
        if method == "AuthorizeService":
            paired = self.yb.get("org.bluez", args[0], "org.bluez.Device1", "Paired", False)
            trusted = self.yb.get("org.bluez", args[0], "org.bluez.Device1", "Trusted", False)
            if paired or trusted:
                return None
            inv.return_dbus_error(BT_REJECTED, "Pair first")
            return Ellipsis
        return None

    def _bt_code(self, inv, key, text, numeric):
        if key != "pair" or not text.strip():
            inv.return_dbus_error(BT_CANCELED, "Cancelled")
        elif numeric:
            try:
                inv.return_value(GLib.Variant("(u)", (int(text.strip()),)))
            except ValueError:
                inv.return_dbus_error(BT_REJECTED, "Not a number")
        else:
            inv.return_value(GLib.Variant("(s)", (text.strip(),)))

    # ---------------------------------------------------------------- questions (one at a time)
    def ask(self, prompt: dict, answer) -> None:
        prompt = dict(prompt, uid=f"{time.time():.6f}")
        self._prompts.append((prompt, answer))
        if len(self._prompts) == 1:
            self.promptChanged.emit()

    def cancel_prompt(self, tag: str) -> None:
        keep = []
        for p, ans in self._prompts:
            if p.get("tag") == tag:
                try:
                    ans("cancel", "")
                except Exception:                             # noqa: BLE001  (already answered)
                    pass
            else:
                keep.append((p, ans))
        if len(keep) != len(self._prompts):
            self._prompts = keep
            self.promptChanged.emit()

    prompt = Property("QVariantMap", lambda self: self._prompts[0][0] if self._prompts else {}, notify=promptChanged)

    @Slot(str, str, str, str)
    def answer(self, uid: str, key: str, text: str, identity: str = "") -> None:
        if not self._prompts or self._prompts[0][0]["uid"] != uid:
            return
        prompt, ans = self._prompts.pop(0)
        try:
            if prompt.get("identity"):
                ans(key, text, identity)
            else:
                ans(key, text)
        finally:
            self.promptChanged.emit()

    @Slot(result=bool)
    def charging(self) -> bool:
        return not self.on_battery()


# ================================================================================================ start
def has_layer_shell(engine) -> bool:
    for d in engine.importPathList():
        if (Path(d) / "org" / "kde" / "layershell").is_dir():
            return True
    return False


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--demo", action="store_true", help="the windows with made-up content, and no D-Bus")
    ap.add_argument("--plain", action="store_true", help="ordinary windows even where layer-shell exists")
    args = ap.parse_args()
    app = QGuiApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setDesktopFileName("huginn-sessiond")
    from huginn_shell import make_theme
    tokens, settings, theme = make_theme(False, False, "", persist=False)        # the person's light or dark, and realm
    sb = yb = None
    if not args.demo:
        try:
            sb = Bus(Gio.BusType.SESSION)
        except GLib.Error as err:
            print(f"huginn-sessiond: no session bus ({err.message})", file=sys.stderr)
            return 1
        try:
            yb = Bus(Gio.BusType.SYSTEM)
        except GLib.Error:
            yb = None
    notes = Notifications(sb, demo=args.demo)
    session = Session(sb, yb, notes, demo=args.demo)
    engine = QQmlApplicationEngine()
    ctx = engine.rootContext()
    ctx.setContextProperty("Theme", theme)
    ctx.setContextProperty("Notifier", notes)    # (not "Notes": QML takes capitalised names as types first)
    ctx.setContextProperty("Session", session)
    # Layer-shell on KWin; under Huginn's own compositor (HUGINN_COMPOSITOR=1) plain windows, which it places by title.
    ctx.setContextProperty("layerShell", has_layer_shell(engine) and not args.plain and os.environ.get("WAYLAND_DISPLAY", "") != ""
                           and os.environ.get("HUGINN_COMPOSITOR") != "1")
    engine.load(QUrl.fromLocalFile(str(HERE / "qml" / "SessionUi.qml")))
    if not engine.rootObjects():
        return 1
    if args.demo:
        QTimer.singleShot(300, lambda: notes.notify("Mail", 0, "huginn-mail", "Astrid Berg", "Tickets for Saturday — I got us two seats near the front.",
                                                    ["reply", "Reply", "default", ""], {}, 0))
        QTimer.singleShot(400, lambda: notes.notify("Software Update", 0, "huginn-settings", "Updates are ready", "3 updates, including Huginn 1.4.", [], {}, 0))
        QTimer.singleShot(500, lambda: session.osd("volume", 0.62))
    pump = QTimer(interval=50)                                # GLib's sources, where Qt doesn't run GLib's loop itself
    pump.timeout.connect(lambda: GLib.MainContext.default().iteration(False))
    if not qt_runs_glib():
        pump.start()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
