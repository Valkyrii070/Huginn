#!/usr/bin/env python3
"""Huginn's lock screen, under Huginn's own compositor.

The compositor starts this when the session locks (Super+L, the lid, going to sleep, the screen-off timer), connected
through a socket made just for it (WAYLAND_SOCKET), and while the session is locked it draws nothing else and sends the
keyboard and mouse nowhere else. One full-screen overlay per screen: the lock itself (the same Lock.qml as the KWin
session's) on the main one, black on the others. The password is checked through PAM (huginn_pam.py, as the person,
never root). Once it's right and the lock has faded away, this exits with 0, and that is what unlocks the session.
Anything else (a crash, being killed) and the compositor starts it again: a broken lock screen never unlocks.

    huginn_locker.py                      under the compositor (it passes the connection)
    HUGINN_LOCKER=/path/to/this ...       the compositor runs this copy instead of the installed one (for development)
"""
import json
import os
import sys
import threading
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "wayland")
os.environ.pop("QT_WAYLAND_SHELL_INTEGRATION", None)

from PySide6.QtCore import Property, QObject, QTimer, QUrl, Signal, Slot  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402
from PySide6.QtQml import QQmlApplicationEngine  # noqa: E402

HERE = Path(__file__).resolve().parent
for apps in (Path("/usr/share/huginn-apps"), HERE.parent / "apps"):
    if (apps / "huginn_pam.py").exists():
        sys.path.insert(0, str(apps))
        break
LOCK_PATHS = (Path("/usr/share/huginn-os/lock/Lock.qml"), HERE.parent / "config/overlay/usr/share/huginn-os/lock/Lock.qml")
LIVE_PATHS = (Path("/usr/share/huginn-os/live"), HERE.parent / "config/overlay/usr/share/huginn-os/live")


def person() -> dict:
    """The signed-in person's name, login and picture, as the lock screen shows them."""
    import pwd
    try:
        pw = pwd.getpwuid(os.getuid())
        name, login, home = (pw.pw_gecos or "").split(",")[0].strip(), pw.pw_name, Path(pw.pw_dir)
    except KeyError:
        name, login, home = "", os.environ.get("USER", ""), Path.home()
    face = next((f for f in (home / ".face.icon", home / ".face") if f.is_file()), None)
    return {"name": name or login, "login": login, "face": QUrl.fromLocalFile(str(face)).toString() if face else ""}


def realm() -> str:
    """The realm (colours) the shell's settings have; the lock wears it too."""
    config = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    try:
        value = json.loads((config / "huginn-shell" / "settings.json").read_text(encoding="utf-8")).get("realm", "")
    except (OSError, ValueError, AttributeError):
        value = ""
    return value if isinstance(value, str) and value.isalpha() else "aurora"


def live_dir() -> str:
    for d in LIVE_PATHS:
        if (d / "LiveWallpaper.qml").exists():
            return QUrl.fromLocalFile(str(d) + "/").toString()
    return ""


class Locker(QObject):
    unlockAnswer = Signal(bool, str)
    screensChanged = Signal()
    _checked = Signal(bool, str)

    def __init__(self, app: QGuiApplication):
        super().__init__()
        self._app = app
        self._checking = False
        self._me = person()
        self._checked.connect(self._answer)
        app.screenAdded.connect(lambda *_: self.screensChanged.emit())
        app.screenRemoved.connect(lambda *_: self.screensChanged.emit())

    @Slot(str)
    def unlock(self, password: str) -> None:
        """Checks the password away from the screen's thread (a wrong one takes PAM a couple of seconds)."""
        if self._checking:
            return
        self._checking = True
        login = self._me["login"]

        def check():
            try:
                import huginn_pam
                ok, message = huginn_pam.check(login, password)
            except Exception as err:                       # noqa: BLE001 - say what's wrong rather than hang
                ok, message = False, f"Can't check the password: {err}"
            self._checked.emit(ok, message)
        threading.Thread(target=check, daemon=True).start()

    def _answer(self, ok: bool, message: str) -> None:
        self._checking = False
        self.unlockAnswer.emit(ok, "" if ok else message)
        if ok:                                             # the lock's fade ends it; a timer makes sure it does
            QTimer.singleShot(2000, self.unlocked)

    @Slot()
    def unlocked(self) -> None:
        """Right password and faded away: leaving with 0 unlocks the session."""
        self._app.exit(0)

    @Slot()
    def suspend(self) -> None:
        from gi.repository import Gio, GLib
        try:
            bus = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
            bus.call("org.freedesktop.login1", "/org/freedesktop/login1", "org.freedesktop.login1.Manager", "Suspend",
                     GLib.Variant("(b)", (True,)), None, 0, 5000, None, None)
        except GLib.Error:
            pass

    def _screens(self) -> list:
        primary = self._app.primaryScreen()
        rest = [s for s in self._app.screens() if s is not primary]
        return ([primary] if primary else []) + rest

    screens = Property("QVariantList", _screens, notify=screensChanged)
    lockUi = Property(str, lambda self: QUrl.fromLocalFile(str(next((p for p in LOCK_PATHS if p.exists()), LOCK_PATHS[0]))).toString(), constant=True)
    me = Property("QVariantMap", lambda self: self._me, constant=True)
    realm = Property(str, lambda self: realm(), constant=True)
    liveDir = Property(str, lambda self: live_dir(), constant=True)
    # The installation drive's session: its account has no password, so an empty one unlocks (PAM agrees: nullok).
    live = Property(bool, lambda self: os.path.exists("/cdrom/casper/filesystem.squashfs"), constant=True)


def main() -> int:
    app = QGuiApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)             # a screen unplugged mustn't end the lock
    locker = Locker(app)
    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty("LockHost", locker)
    engine.load(QUrl.fromLocalFile(str(HERE / "qml" / "Locker.qml")))
    if not engine.rootObjects():
        return 2                                         # not 0: the compositor tries again, the session stays locked
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
