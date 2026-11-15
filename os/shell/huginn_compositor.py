"""Huginn's own compositor (the preview session): what the QML compositor (qml/Compositor.qml) can't do itself.

The scene is Qt Wayland Compositor in QML: apps' windows as glass islands with the shell (wallpaper, widgets, top
bar, dock, launcher, control centre) drawn around them in one picture. This half is the Python around it:

    keys        the hardware keys go to Huginn's session daemon (org.huginn.Session.Key); Super+L locks, Print takes
                a screenshot, Alt+Tab switches windows, Alt+F4 closes one, Super alone opens the launcher
    idle        how long since anyone touched the computer, for the session daemon's dim / screen off / sleep
    locking     the lock screen (the same one as the KWin session, /usr/share/huginn-os/lock/Lock.qml) with the password
                checked through PAM; logind's "lock the session" (loginctl lock-session, the lid) and going to sleep
                lock it too
    D-Bus       org.huginn.Compositor: IdleTime, Lock, Blank, Screenshot, Capture (for the portal), Locked
    services    once the compositor is up, the session's services start inside it (huginn-session-apps --services)

On a computer it runs inside cage (a kiosk compositor that owns the screen, keyboard and mouse) — huginn-session-
preview does that — and in tests in an ordinary window under X11 (--windowed).
"""
import os
import re
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

from gi.repository import Gio, GLib
from PySide6.QtCore import Property, QEvent, QObject, Qt, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QGuiApplication

HERE = Path(__file__).resolve().parent
for apps_dir in (HERE.parent / "apps", Path("/usr/share/huginn-apps")):
    if (apps_dir / "huginn_pam.py").exists():
        sys.path.insert(0, str(apps_dir))
        break

XML = """<node><interface name="org.huginn.Compositor">
  <method name="IdleTime"><arg type="t" direction="out"/></method>
  <method name="Lock"/>
  <method name="Blank"><arg type="b" name="off" direction="in"/></method>
  <method name="Screenshot"><arg type="s" direction="out"/></method>
  <method name="Capture"><arg type="s" direction="out"/></method>
  <method name="Locked"><arg type="b" direction="out"/></method>
  <method name="Windows"><arg type="s" direction="out"/></method>
</interface></node>"""
TESTING = os.environ.get("HUGINN_COMPOSITOR_TEST") == "1"         # tests only: Windows() describes the windows
# The hardware keys: Qt's name for the key → the session daemon's (huginn_sessiond.KEY_NAMES).
HARDWARE = {"Key_VolumeUp": "volumeUp", "Key_VolumeDown": "volumeDown", "Key_VolumeMute": "volumeMute", "Key_MicMute": "micMute",
            "Key_MonBrightnessUp": "brightnessUp", "Key_MonBrightnessDown": "brightnessDown",
            "Key_KeyboardBrightnessUp": "keyboardLightUp", "Key_KeyboardBrightnessDown": "keyboardLightDown",
            "Key_KeyboardLightOnOff": "keyboardLight", "Key_PowerOff": "power", "Key_Sleep": "sleep", "Key_Suspend": "suspend",
            "Key_MediaTogglePlayPause": "playPause", "Key_MediaPlay": "play", "Key_MediaPause": "pause",
            "Key_MediaNext": "next", "Key_MediaPrevious": "previous", "Key_MediaStop": "stop"}
HARDWARE = {int(getattr(Qt.Key, k).value): v for k, v in HARDWARE.items() if hasattr(Qt.Key, k)}
INPUT = {QEvent.KeyPress, QEvent.KeyRelease, QEvent.MouseMove, QEvent.MouseButtonPress, QEvent.MouseButtonRelease, QEvent.Wheel,
         QEvent.TouchBegin, QEvent.TouchUpdate, QEvent.TabletMove, QEvent.TabletPress}
LOCK_PATHS = (Path("/usr/share/huginn-os/lock/Lock.qml"), HERE.parent / "config/overlay/usr/share/huginn-os/lock/Lock.qml")



def qt_runs_glib() -> bool:
    """Ubuntu's Qt runs GLib's loop itself, and GLib's sources (D-Bus) are served with Qt's events. Turning GLib's
    loop by hand from a Qt timer as well would run Qt's events inside Qt's events: a window drawn in the middle of
    drawing another, which can leave a surface waiting forever for its compositor."""
    from PySide6.QtCore import QAbstractEventDispatcher
    d = QAbstractEventDispatcher.instance()
    return d is not None and "Glib" in d.metaObject().className()

def pictures_dir() -> Path:
    try:
        text = (Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "user-dirs.dirs").read_text(encoding="utf-8")
        m = re.search(r'^XDG_PICTURES_DIR="([^"]+)"', text, re.M)
        if m:
            return Path(m.group(1).replace("$HOME", str(Path.home())))
    except OSError:
        pass
    return Path.home() / "Pictures"


class Compositor(QObject):
    lockedChanged = Signal()
    blankChanged = Signal()
    switchStep = Signal(int)            # Alt+Tab: 1 forward, -1 back
    switchCommit = Signal()             # Alt let go: to the window picked
    switchCancel = Signal()
    closeActive = Signal()
    minimiseActive = Signal()
    maximiseActive = Signal()
    toggleLauncher = Signal()
    flash = Signal()                    # a screenshot was taken
    unlockAnswer = Signal(bool, str)
    screensChanged = Signal()
    frostChanged = Signal()
    _checked = Signal(bool, str)        # from the PAM thread

    def __init__(self, socket: str, windowed: bool, tokens: dict, apps, services: bool):
        super().__init__()
        self._socket = socket
        self._windowed = windowed
        self._tokens = tokens
        self._apps = apps
        self._services = services
        self._locked = False
        self._blank = False
        self._inhibited = False
        self._checking = False
        self._screen = None
        self._last = time.monotonic()
        self._switching = False
        self._super_alone = False
        self._session_path = ""
        self._report = "[]"
        self._screens = []                  # [{x, y, width, height, main}] in the scene's coordinates
        self._software = False              # drawn by the CPU (llvmpipe): no frosted glass
        self._x11 = None                    # xwayland-satellite: X11 apps as windows of their own
        self._display = ""
        self._checked.connect(self._answer)
        self.sb = self.yb = None
        try:
            self.sb = Gio.bus_get_sync(Gio.BusType.SESSION, None)
            node = Gio.DBusNodeInfo.new_for_xml(XML)
            self.sb.register_object("/org/huginn/Compositor", node.interfaces[0], self._call, None, None)
            Gio.bus_own_name_on_connection(self.sb, "org.huginn.Compositor", Gio.BusNameOwnerFlags.REPLACE, None, None)
        except GLib.Error as err:
            print(f"huginn-compositor: no session bus ({err.message})", file=sys.stderr)
        try:
            self.yb = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
            self._follow_logind()
        except GLib.Error:
            self.yb = None
        QGuiApplication.instance().installEventFilter(self)
        self._pump = QTimer(self, interval=30, timeout=lambda: GLib.MainContext.default().iteration(False))
        if not qt_runs_glib():
            self._pump.start()

    # ------------------------------------------------------------------ D-Bus
    def _call(self, conn, sender, path, iface, method, params, inv):
        if method == "IdleTime":
            inv.return_value(GLib.Variant("(t)", (self.idle_ms(),)))
        elif method == "Lock":
            self.lock()
            inv.return_value(None)
        elif method == "Blank":
            self.setBlank(params.unpack()[0])
            inv.return_value(None)
        elif method == "Screenshot":
            inv.return_value(GLib.Variant("(s)", (self.screenshot(),)))
        elif method == "Capture":
            inv.return_value(GLib.Variant("(s)", (self.capture(),)))
        elif method == "Locked":
            inv.return_value(GLib.Variant("(b)", (self._locked,)))
        elif method == "Windows" and TESTING:
            inv.return_value(GLib.Variant("(s)", (self._report,)))
        else:
            inv.return_dbus_error("org.freedesktop.DBus.Error.UnknownMethod", method)

    def _follow_logind(self) -> None:
        """loginctl lock-session (and anything else that asks logind) locks; so does going to sleep."""
        sid = os.environ.get("XDG_SESSION_ID", "")
        try:
            if sid:
                got = self.yb.call_sync("org.freedesktop.login1", "/org/freedesktop/login1", "org.freedesktop.login1.Manager", "GetSession",
                                        GLib.Variant("(s)", (sid,)), GLib.VariantType("(o)"), 0, 2000, None)
            else:
                got = self.yb.call_sync("org.freedesktop.login1", "/org/freedesktop/login1", "org.freedesktop.login1.Manager", "GetSessionByPID",
                                        GLib.Variant("(u)", (os.getpid(),)), GLib.VariantType("(o)"), 0, 2000, None)
            self._session_path = got.unpack()[0]
        except GLib.Error:
            self._session_path = ""
        if self._session_path:
            self.yb.signal_subscribe("org.freedesktop.login1", "org.freedesktop.login1.Session", "Lock", self._session_path, None,
                                     Gio.DBusSignalFlags.NONE, lambda *a: QTimer.singleShot(0, self.lock))
        self.yb.signal_subscribe("org.freedesktop.login1", "org.freedesktop.login1.Manager", "PrepareForSleep", "/org/freedesktop/login1", None,
                                 Gio.DBusSignalFlags.NONE, lambda c, s, p, i, m, args: QTimer.singleShot(0, self.lock) if args.unpack()[0] else None)

    def _locked_hint(self, on: bool) -> None:
        if self.yb and self._session_path:
            self.yb.call("org.freedesktop.login1", self._session_path, "org.freedesktop.login1.Session", "SetLockedHint",
                         GLib.Variant("(b)", (on,)), None, 0, 2000, None, None)

    def _key_to_session(self, name: str) -> None:
        if self.sb:
            self.sb.call("org.huginn.Session", "/org/huginn/Session", "org.huginn.Session", "Key", GLib.Variant("(s)", (name,)),
                         None, 0, 2000, None, None)

    # ------------------------------------------------------------------ input
    def eventFilter(self, obj, event) -> bool:
        kind = event.type()
        if kind not in INPUT:
            return False
        self._last = time.monotonic()
        if kind not in (QEvent.KeyPress, QEvent.KeyRelease) or obj is not self._screen:
            return False
        key, mods = event.key(), event.modifiers()
        if kind == QEvent.KeyRelease:
            if key == Qt.Key_Alt and self._switching:
                self._switching = False
                self.switchCommit.emit()
            if key in (Qt.Key_Meta, Qt.Key_Super_L, Qt.Key_Super_R) and self._super_alone and not self._locked:
                self._super_alone = False
                self.toggleLauncher.emit()
            return False
        self._super_alone = key in (Qt.Key_Meta, Qt.Key_Super_L, Qt.Key_Super_R) and not event.isAutoRepeat()
        if key in HARDWARE:                                          # volume, brightness, media… also on the lock screen
            if not event.isAutoRepeat() or key in (Qt.Key_VolumeUp, Qt.Key_VolumeDown, Qt.Key_MonBrightnessUp, Qt.Key_MonBrightnessDown):
                self._key_to_session(HARDWARE[key])
            return True
        if self._locked:
            return False
        meta = bool(mods & Qt.MetaModifier)
        alt = bool(mods & Qt.AltModifier)
        if key == Qt.Key_Print:
            self.screenshot()
            return True
        if meta and key == Qt.Key_L:
            self.lock()
            return True
        if alt and key in (Qt.Key_Tab, Qt.Key_Backtab):
            self._switching = True
            self.switchStep.emit(-1 if key == Qt.Key_Backtab or mods & Qt.ShiftModifier else 1)
            return True
        if self._switching and key == Qt.Key_Escape:
            self._switching = False
            self.switchCancel.emit()
            return True
        if alt and key == Qt.Key_F4:
            self.closeActive.emit()
            return True
        if meta and key == Qt.Key_Up:
            self.maximiseActive.emit()
            return True
        if meta and key == Qt.Key_Down:
            self.minimiseActive.emit()
            return True
        return False

    def idle_ms(self) -> int:
        if self._inhibited and not self._locked:
            return 0
        return int((time.monotonic() - self._last) * 1000)

    # ------------------------------------------------------------------ the lock
    @Slot()
    def lock(self) -> None:
        if not self._locked:
            self._locked = True
            self._switching = False
            self.lockedChanged.emit()
            self._locked_hint(True)

    @Slot(str)
    def unlock(self, password: str) -> None:
        """Checks the password through PAM away from the screen's thread (a wrong one takes PAM a couple of seconds)."""
        if self._checking:
            return
        self._checking = True
        user = os.environ.get("USER") or Path.home().name

        def check():
            try:
                import huginn_pam
                ok, message = huginn_pam.check(user, password)
            except Exception as err:                                   # noqa: BLE001 - a broken PAM must not lock you out silently
                ok, message = False, f"Can't check the password: {err}"
            self._checked.emit(ok, message)
        threading.Thread(target=check, daemon=True).start()

    def _answer(self, ok: bool, message: str) -> None:
        self._checking = False
        self.unlockAnswer.emit(ok, "" if ok else message)
        if ok:                                       # the lock's fade ends it; a real timer makes sure it does
            QTimer.singleShot(2000, lambda: self.unlocked() if self._locked else None)

    @Slot()
    def unlocked(self) -> None:
        """The lock has faded away."""
        self._locked = False
        self._last = time.monotonic()
        self.lockedChanged.emit()
        self._locked_hint(False)

    @Slot(bool)
    def setBlank(self, on: bool) -> None:
        if on != self._blank:
            self._blank = on
            self.blankChanged.emit()

    @Slot(bool)
    def setInhibited(self, on: bool) -> None:
        self._inhibited = on

    @Slot()
    def suspend(self) -> None:
        if self.yb:
            self.yb.call("org.freedesktop.login1", "/org/freedesktop/login1", "org.freedesktop.login1.Manager", "Suspend",
                         GLib.Variant("(b)", (True,)), None, 0, 5000, None, None)

    @Slot()
    def switchUser(self) -> None:
        subprocess.Popen(["dm-tool", "switch-to-greeter"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) if os.path.exists("/usr/bin/dm-tool") else None

    # ------------------------------------------------------------------ screenshots
    @Slot("QVariant")
    def setScreen(self, window) -> None:
        self._screen = window
        window.sceneGraphInitialized.connect(self._renderer, Qt.ConnectionType.DirectConnection)
        app = QGuiApplication.instance()
        app.screenAdded.connect(lambda *_: QTimer.singleShot(300, self._read_screens))
        app.screenRemoved.connect(lambda *_: QTimer.singleShot(300, self._read_screens))
        window.widthChanged.connect(lambda *_: QTimer.singleShot(0, self._read_screens))
        window.heightChanged.connect(lambda *_: QTimer.singleShot(0, self._read_screens))
        QTimer.singleShot(0, self._read_screens)
        QTimer.singleShot(0, self._started)

    def _renderer(self) -> None:
        """On the render thread, once: is the GPU drawing, or the CPU (llvmpipe, softpipe)? Frosted glass needs a GPU."""
        try:
            from PySide6.QtGui import QOpenGLContext
            ctx = QOpenGLContext.currentContext()
            name = ctx.functions().glGetString(0x1F01) if ctx else ""          # GL_RENDERER
            name = name.decode() if isinstance(name, bytes) else str(name or "")
        except Exception:                                  # noqa: BLE001 (another graphics API, or none)
            name = ""
        soft = any(w in name.lower() for w in ("llvmpipe", "softpipe", "software"))
        if soft != self._software:
            self._software = soft
            QTimer.singleShot(0, self.frostChanged.emit)

    def _read_screens(self) -> None:
        """The screens the scene spans. Under cage (-m extend) the compositor's one window covers every screen side by
        side; each screen is a QScreen, placed in the same layout. HUGINN_COMPOSITOR_SCREENS fakes them for tests."""
        win = self._screen
        if win is None:
            return
        W, H = win.width(), win.height()
        fake = os.environ.get("HUGINN_COMPOSITOR_SCREENS", "")
        rects = []
        if fake:
            for part in fake.split(";"):
                try:
                    x, y, w, h = (int(v) for v in part.split(","))
                    rects.append((x, y, w, h))
                except ValueError:
                    pass
        elif not self._windowed:
            screens = QGuiApplication.screens()
            if len(screens) > 1:
                left = min(sc.geometry().x() for sc in screens)
                top = min(sc.geometry().y() for sc in screens)
                rects = [(sc.geometry().x() - left, sc.geometry().y() - top, sc.geometry().width(), sc.geometry().height()) for sc in screens]
        rects = [r for r in rects if r[2] > 0 and r[3] > 0 and r[0] < W and r[1] < H] or [(0, 0, W, H)]
        primary = QGuiApplication.primaryScreen()
        main = 0
        if not fake and primary is not None and len(rects) > 1:
            pg = primary.geometry()
            main = next((i for i, sc in enumerate(QGuiApplication.screens()) if sc.geometry() == pg), 0)
        out = [{"x": x, "y": y, "width": w, "height": h, "main": i == main} for i, (x, y, w, h) in enumerate(rects)]
        if out != self._screens:
            self._screens = out
            if os.environ.get("HUGINN_DEBUG_SCREENS"):
                print("huginn-compositor: screens", out, flush=True)
            self.screensChanged.emit()

    def _start_x11(self) -> None:
        """X11 apps: xwayland-satellite gives each X window a window of its own here (Qt's compositor has no
        XWayland). It takes the first free display number and starts Xwayland when an X app first connects."""
        exe = next((p for p in ("/usr/libexec/huginn/xwayland-satellite", "/usr/bin/xwayland-satellite", "/usr/local/bin/xwayland-satellite")
                    if os.access(p, os.X_OK)), "")
        if not exe or os.environ.get("HUGINN_COMPOSITOR_X11") == "0":
            return
        n = next((n for n in range(1, 64) if not os.path.exists(f"/tmp/.X11-unix/X{n}") and not os.path.exists(f"/tmp/.X{n}-lock")), 0)
        if not n:
            return
        log = Path(os.environ.get("XDG_RUNTIME_DIR") or "/tmp") / "huginn-x11.log"
        try:
            self._x11 = subprocess.Popen([exe, f":{n}"], stdout=subprocess.DEVNULL, stderr=open(log, "w"))
        except OSError:
            return
        self._display = f":{n}"
        for _ in range(40):                                  # until it listens (a moment)
            if os.path.exists(f"/tmp/.X11-unix/X{n}"):
                break
            time.sleep(0.05)
        QGuiApplication.instance().aboutToQuit.connect(self._x11.terminate)

    @Slot(result=str)
    def screenshot(self) -> str:
        if self._screen is None:
            return ""
        image = self._screen.grabWindow()
        folder = pictures_dir() / "Screenshots"
        folder.mkdir(parents=True, exist_ok=True)
        stem = f"Screenshot {datetime.now().strftime('%Y-%m-%d %H.%M.%S')}"
        path, n = folder / f"{stem}.png", 2
        while path.exists():                                   # two in the same second
            path, n = folder / f"{stem} ({n}).png", n + 1
        if not image.save(str(path)):
            return ""
        self.flash.emit()
        if self.sb:
            self.sb.call("org.freedesktop.Notifications", "/org/freedesktop/Notifications", "org.freedesktop.Notifications", "Notify",
                         GLib.Variant("(susssasa{sv}i)", ("Screenshot", 0, "huginn-screenshot", "Screenshot saved",
                                                           f"In Pictures › Screenshots as “{path.name}”.", [],
                                                           {"image-path": GLib.Variant("s", str(path))}, 5000)), None, 0, 2000, None, None)
        return str(path)

    def capture(self) -> str:
        """The screen as it is, for the portal (an app asked for a screenshot or a colour): a file in the session's
        runtime folder, no flash and no notification. Nothing while the screen is locked."""
        if self._screen is None or self._locked:
            return ""
        folder = Path(os.environ.get("XDG_RUNTIME_DIR") or "/tmp") / "huginn-portal"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"screen-{int(time.time() * 1000)}.png"
        return str(path) if self._screen.grabWindow().save(str(path)) else ""

    # ------------------------------------------------------------------ apps
    @Slot(str, result="QVariantMap")
    def appFor(self, app_id: str) -> dict:
        """The installed app a window belongs to (by its Wayland app id): name, icon and its own colour."""
        low = (app_id or "").lower()
        found = next((a for a in self._apps.all if low and low in (a.get("wm", "").lower(), a.get("id", "").lower())), None)
        key = low[len("huginn-"):].split("-")[0] if low.startswith("huginn-") else ""      # huginn-files-chooser: Files' colour
        colours = (self._tokens.get("apps") or {}).get(key) or ["", ""]
        out = dict(found) if found else {"name": "" if key else app_id.rsplit(".", 1)[-1].replace("-", " ").title(), "image": "", "own": "", "glyph": ""}
        out["colour"] = colours[0] if isinstance(colours, list) else ""
        return out

    def _started(self) -> None:
        """The compositor is listening: its apps start inside it, never in the host."""
        os.environ["WAYLAND_DISPLAY"] = self._socket
        os.environ["QT_QPA_PLATFORM"] = "wayland"
        os.environ["GDK_BACKEND"] = "wayland"
        os.environ["HUGINN_COMPOSITOR"] = "1"
        os.environ.pop("DISPLAY", None)                     # X apps must never land in the host's X server
        self._start_x11()
        if self._display:
            os.environ["DISPLAY"] = self._display           # …but in ours, if it's there
        if self.sb:
            env = {k: os.environ[k] for k in ("WAYLAND_DISPLAY", "QT_QPA_PLATFORM", "GDK_BACKEND", "HUGINN_COMPOSITOR")}
            env["DISPLAY"] = self._display
            self.sb.call("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus", "UpdateActivationEnvironment",
                         GLib.Variant("(a{ss})", (env,)), None, 0, 2000, None, None)
        services = "/usr/libexec/huginn-session-apps"
        if self._services and os.access(services, os.X_OK):
            subprocess.Popen([services, "--services"])

    @Slot(str)
    def report(self, text: str) -> None:
        self._report = text

    testing = Property(bool, lambda self: TESTING, constant=True)
    socket = Property(str, lambda self: self._socket, constant=True)
    windowed = Property(bool, lambda self: self._windowed, constant=True)
    locked = Property(bool, lambda self: self._locked, notify=lockedChanged)
    blank = Property(bool, lambda self: self._blank, notify=blankChanged)
    lockUi = Property(str, lambda self: QUrl.fromLocalFile(str(next((p for p in LOCK_PATHS if p.exists()), LOCK_PATHS[0]))).toString(), constant=True)
    user = Property(str, lambda self: os.environ.get("USER") or Path.home().name, constant=True)
    screens = Property("QVariantList", lambda self: self._screens, notify=screensChanged)
    # Frosted glass behind the bar, dock and panels: a GPU draws it; the CPU (a VM, no driver) gets plain glass.
    frost = Property(bool, lambda self: os.environ.get("HUGINN_FROST") == "1" or (not self._software and os.environ.get("HUGINN_FROST") != "0"), notify=frostChanged)
