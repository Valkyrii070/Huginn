"""The rest of Huginn's portal backend, beside the file chooser (huginn_portal.py runs them all in one process).

    Prompt   Access: "Allow <app> to …?" — asked by the portal for cameras, screenshots, the background and more.
             AppChooser: "Open <file> with" — which app opens a file or a link.
    Shot     Screenshot: a picture of the screen for an app; when the app lets you choose, the screen holds still and
             you drag the part to share (or take it all).
             PickColor: the screen holds still with a magnifier; click the colour the app wants.

The picture comes from Huginn's compositor (org.huginn.Compositor.Capture) in the preview session, and from KWin
through KDE's portal backend in the main session (KWin only hands pictures to programs it knows; KDE's backend is one).
"""
import os
import shutil
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

from gi.repository import Gio, GLib
from PySide6.QtCore import Property, QObject, QUrl, Signal, Slot
from PySide6.QtGui import QColor, QGuiApplication, QImage

SUCCESS, CANCELLED, OTHER = 0, 1, 2
CACHE = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "huginn" / "screenshots"
RUNTIME = Path(os.environ.get("XDG_RUNTIME_DIR") or "/tmp") / "huginn-portal"


def app_info(app_id: str):
    if not app_id:
        return None
    try:
        return Gio.DesktopAppInfo.new(app_id if app_id.endswith(".desktop") else app_id + ".desktop")
    except TypeError:
        return None


def app_name(app_id: str) -> str:
    """What to call the app that's asking: its name, or a tidy form of its id; "" for an app with no id."""
    info = app_info(app_id)
    if info:
        return info.get_display_name()
    return app_id.rsplit(".", 1)[-1].replace("-", " ").replace("_", " ").title() if app_id else ""


def app_row(app_id: str) -> dict:
    """An app as the Open With list shows it: its name, its picture (Huginn's own, or the icon theme's)."""
    from huginn_shell import APP_GLYPHS, app_key, own_icon
    info = app_info(app_id)
    name = info.get_display_name() if info else app_name(app_id)
    command = info.get_commandline() or "" if info else ""
    key = app_key(command.replace("%U", "").replace("%u", "").replace("%F", "").replace("%f", "").strip())
    image = own_icon("browser" if name == "Huginn" else key if key in APP_GLYPHS else "")
    if not image and info and info.get_icon():
        icon = info.get_icon()
        names = icon.get_names() if hasattr(icon, "get_names") else []
        if names:
            image = "image://sysicon/" + names[0]
        elif hasattr(icon, "get_file") and icon.get_file():
            image = icon.get_file().get_uri()
    return {"id": app_id, "name": name, "image": image, "glyph": "" if image else "apps",
            "about": (info.get_description() or "") if info else ""}


class Prompt(QObject):
    """Access and Open With: one card, a question and its answers."""
    changed = Signal()
    finished = Signal(int, "QVariantMap")

    def __init__(self):
        super().__init__()
        self._kind = ""                         # "", "access", "apps"
        self._app = self._title = self._subtitle = self._body = self._icon = ""
        self._grant, self._deny = "Allow", "Don't Allow"
        self._choices = []
        self._apps, self._chosen, self._file = [], "", ""

    def ask_access(self, app_id: str, title: str, subtitle: str, body: str, options: dict) -> None:
        self._kind, self._app = "access", app_id
        self._title, self._subtitle, self._body = title, subtitle, body
        self._grant = (options.get("grant_label") or "Allow").replace("_", "")
        self._deny = (options.get("deny_label") or "Don't Allow").replace("_", "")
        self._icon = options.get("icon") or ""
        self._choices = [{"id": cid, "label": label, "options": [{"id": a, "label": b} for a, b in opts],
                          "value": value or ("false" if not opts else opts[0][0])} for cid, label, opts, value in options.get("choices") or []]
        self.changed.emit()

    def ask_apps(self, app_id: str, choices: list, options: dict) -> None:
        self._kind, self._app = "apps", app_id
        self._apps = [app_row(c) for c in dict.fromkeys(choices)]
        last = options.get("last_choice") or ""
        self._chosen = last if last in choices else (choices[0] if choices else "")
        uri, name = options.get("uri") or "", options.get("filename") or ""
        self._file = name or (os.path.basename(QUrl(uri).toLocalFile()) if uri.startswith("file:") else uri)
        self._title = f"Open “{self._file}” with" if self._file else "Open with"
        ctype = options.get("content_type") or ""
        self._subtitle = Gio.content_type_get_description(ctype) if ctype else ""
        self.changed.emit()

    def update_apps(self, choices: list) -> None:
        if self._kind == "apps":
            known = {a["id"] for a in self._apps}
            self._apps += [app_row(c) for c in choices if c not in known]
            self.changed.emit()

    def _finish(self, code: int, results: dict) -> None:
        self._kind = ""
        self.changed.emit()
        self.finished.emit(code, results)

    @Slot(str, str)
    def setChoice(self, cid: str, value: str) -> None:
        for c in self._choices:
            if c["id"] == cid:
                c["value"] = value
        self.changed.emit()

    @Slot(str)
    def choose(self, app_id: str) -> None:
        self._chosen = app_id
        self.changed.emit()

    @Slot(bool)
    def answer(self, yes: bool) -> None:
        if self._kind == "access":
            self._finish(SUCCESS if yes else CANCELLED, {"choices": GLib.Variant("a(ss)", [(c["id"], c["value"]) for c in self._choices])})
        elif self._kind == "apps":
            if yes and self._chosen:
                self._finish(SUCCESS, {"choice": GLib.Variant("s", self._chosen)})
            else:
                self._finish(CANCELLED, {})

    @Slot()
    def cancel(self) -> None:
        if self._kind:
            self._finish(CANCELLED, {})

    kind = Property(str, lambda self: self._kind, notify=changed)
    active = Property(bool, lambda self: self._kind != "", notify=changed)
    app = Property(str, lambda self: app_name(self._app), notify=changed)
    title = Property(str, lambda self: self._title, notify=changed)
    subtitle = Property(str, lambda self: self._subtitle, notify=changed)
    body = Property(str, lambda self: self._body, notify=changed)
    icon = Property(str, lambda self: self._icon, notify=changed)
    grantLabel = Property(str, lambda self: self._grant, notify=changed)
    denyLabel = Property(str, lambda self: self._deny, notify=changed)
    choices = Property("QVariantList", lambda self: self._choices, notify=changed)
    apps = Property("QVariantList", lambda self: self._apps, notify=changed)
    chosen = Property(str, lambda self: self._chosen, notify=changed)


def capture(bus) -> tuple:
    """A picture of the whole screen right now: (path, problem). Runs off the main thread."""
    RUNTIME.mkdir(parents=True, exist_ok=True)

    def has(name):
        try:
            return bus.call_sync("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus", "NameHasOwner",
                                 GLib.Variant("(s)", (name,)), GLib.VariantType("(b)"), 0, 2000, None).unpack()[0]
        except GLib.Error:
            return False
    if has("org.huginn.Compositor"):
        try:
            path = bus.call_sync("org.huginn.Compositor", "/org/huginn/Compositor", "org.huginn.Compositor", "Capture", None,
                                 GLib.VariantType("(s)"), 0, 10000, None).unpack()[0]
            return (path, "") if path else ("", "The compositor couldn't take the picture.")
        except GLib.Error as err:
            return "", err.message
    if has("org.kde.KWin"):
        # KDE's backend takes it through KWin and saves it in Pictures (and fails when there's no Pictures folder);
        # it moves to our own folder at once.
        pictures = GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_PICTURES) or str(Path.home() / "Pictures")
        Path(pictures).mkdir(parents=True, exist_ok=True)
        handle = f"/org/freedesktop/portal/desktop/request/huginn/shot{int(time.time() * 1000)}"
        try:
            code, results = bus.call_sync("org.freedesktop.impl.portal.desktop.kde", "/org/freedesktop/portal/desktop",
                                          "org.freedesktop.impl.portal.Screenshot", "Screenshot",
                                          GLib.Variant("(ossa{sv})", (handle, "", "", {"interactive": GLib.Variant("b", False), "modal": GLib.Variant("b", False)})),
                                          GLib.VariantType("(ua{sv})"), 0, 60000, None).unpack()   # (slow when drawing with the CPU)
        except GLib.Error as err:
            return "", err.message
        made = QUrl(results.get("uri", "")).toLocalFile() if code == 0 else ""
        if not made or not os.path.isfile(made):
            return "", "KWin didn't give a picture."
        dest = RUNTIME / f"screen-{int(time.time() * 1000)}.png"
        try:
            shutil.move(made, dest)
        except OSError:
            return made, ""
        return str(dest), ""
    return "", "x11"                                     # tests and X11: the main thread grabs it


class Shot(QObject):
    """Screenshot and PickColor: the screen held still, an area dragged or a colour clicked."""
    changed = Signal()
    finished = Signal(int, "QVariantMap")
    _got = Signal(str, str)

    def __init__(self, bus=None):
        super().__init__()
        self._bus = bus
        self._kind = ""                         # "", "shot", "colour"
        self._app = ""
        self._interactive = False
        self._image = ""                        # the frozen screen, while it shows
        self._picture = None
        self._got.connect(self._captured)

    def ask(self, kind: str, app_id: str, options: dict) -> None:
        self._kind, self._app, self._image, self._picture = kind, app_id, "", None
        self._interactive = kind == "colour" or bool(options.get("interactive", False))
        if self._bus is None:
            self._got.emit(*self._grab())
            return
        threading.Thread(target=lambda: self._got.emit(*capture(self._bus)), daemon=True).start()

    @staticmethod
    def _grab() -> tuple:
        screen = QGuiApplication.primaryScreen()
        shot = screen.grabWindow(0) if screen else None
        RUNTIME.mkdir(parents=True, exist_ok=True)
        dest = RUNTIME / f"screen-{int(time.time() * 1000)}.png"
        if shot is None or shot.isNull() or not shot.save(str(dest)):
            return "", "The screen couldn't be captured."
        return str(dest), ""

    def _captured(self, path: str, problem: str) -> None:
        if problem == "x11":
            path, problem = self._grab()
        if not path:
            print("huginn-portal: screenshot:", problem, file=sys.stderr, flush=True)
            self._finish(OTHER, {})
            return
        if not self._interactive:
            self._deliver(QImage(path), path)
            return
        self._image = QUrl.fromLocalFile(path).toString()
        self._picture = QImage(path)
        self.changed.emit()

    def _deliver(self, image: QImage, source: str = "") -> None:
        CACHE.mkdir(parents=True, exist_ok=True)
        for old in CACHE.glob("*.png"):                                   # the portal's copies don't pile up
            try:
                if time.time() - old.stat().st_mtime > 2 * 86400:
                    old.unlink()
            except OSError:
                pass
        stem = f"Screenshot {datetime.now().strftime('%Y-%m-%d %H.%M.%S')}"
        dest, n = CACHE / f"{stem}.png", 2
        while dest.exists():
            dest, n = CACHE / f"{stem} ({n}).png", n + 1
        if image.isNull() or not image.save(str(dest)):
            self._finish(OTHER, {})
            return
        if source.startswith(str(RUNTIME)):
            try:
                os.unlink(source)
            except OSError:
                pass
        self._finish(SUCCESS, {"uri": GLib.Variant("s", QUrl.fromLocalFile(str(dest)).toString(QUrl.ComponentFormattingOption.FullyEncoded))})

    def _finish(self, code: int, results: dict) -> None:
        if self._image:
            try:
                os.unlink(QUrl(self._image).toLocalFile())
            except OSError:
                pass
        self._kind, self._image, self._picture = "", "", None
        self.changed.emit()
        self.finished.emit(code, results)

    @Slot(float, float, float, float)
    def share(self, x: float, y: float, w: float, h: float) -> None:
        """The part to share, as fractions of the screen (w = 0: all of it)."""
        if self._kind != "shot" or self._picture is None:
            return
        pic = self._picture
        if w > 0 and h > 0:
            r = [round(x * pic.width()), round(y * pic.height()), round(w * pic.width()), round(h * pic.height())]
            pic = pic.copy(r[0], r[1], max(1, r[2]), max(1, r[3]))
        self._deliver(pic)

    @Slot(float, float, result=str)
    def colourAt(self, x: float, y: float) -> str:
        """The colour at a point (fractions of the screen), as #RRGGBB."""
        if self._picture is None:
            return ""
        px = min(self._picture.width() - 1, max(0, int(x * self._picture.width())))
        py = min(self._picture.height() - 1, max(0, int(y * self._picture.height())))
        return QColor(self._picture.pixel(px, py)).name()

    @Slot(float, float)
    def pick(self, x: float, y: float) -> None:
        if self._kind != "colour" or self._picture is None:
            return
        c = QColor(self.colourAt(x, y))
        self._finish(SUCCESS, {"color": GLib.Variant("(ddd)", (c.redF(), c.greenF(), c.blueF()))})

    @Slot()
    def cancel(self) -> None:
        if self._kind:
            self._finish(CANCELLED, {})

    kind = Property(str, lambda self: self._kind, notify=changed)
    showing = Property(bool, lambda self: self._image != "", notify=changed)
    image = Property(str, lambda self: self._image, notify=changed)
    app = Property(str, lambda self: app_name(self._app), notify=changed)
    imageWidth = Property(int, lambda self: self._picture.width() if self._picture else 0, notify=changed)
    imageHeight = Property(int, lambda self: self._picture.height() if self._picture else 0, notify=changed)
