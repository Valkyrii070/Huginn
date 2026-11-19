"""Huginn OS's desktop portal backend: the windows every app's questions to the desktop come through.

Apps ask xdg-desktop-portal (org.freedesktop.portal.*) for a file, a screenshot, a colour, permission or an app to
open something with; on Huginn OS the portal hands the asking to this backend (huginn-portals.conf), which answers
with Huginn's own windows:

    Open and Save   the places down the side, the folder as a list or as pictures, a path to click back along,
                    search, filters, a preview, and for saving a name with New Folder and a question before
                    anything is replaced (here, the Chooser)
    Screenshot      the screen held still: drag the part to share, or take it all (huginn_portal_ask.Shot)
    PickColor       the screen held still with a magnifier; click the colour
    Access          "Allow <app> to …?" with the app's own choices (huginn_portal_ask.Prompt)
    Open With       the apps that can open a file or a link, the last one used already picked

Settings (dark or light, accent, contrast) are answered by huginn_portal_settings.py, which stays running; screen
sharing stays KDE's (PipeWire). Qt apps reach the portal through KDE's integration (PLASMA_INTEGRATION_USE_PORTAL),
GTK apps through GTK_USE_PORTAL / GDK_DEBUG=portals, Flatpak and Snap apps always.

    python3 huginn_portal.py                 the backend (D-Bus activated as org.freedesktop.impl.portal.desktop.huginn)
    python3 huginn_portal.py --demo [what]   one window on its own: open, save, access, apps, shot or colour
"""
import argparse
import fnmatch
import json
import os
import re
import sys
import time
from pathlib import Path
from urllib.parse import quote, unquote

HERE = Path(__file__).resolve().parent
for shell_dir in (HERE.parent / "shell", Path("/usr/share/huginn-shell")):
    if (shell_dir / "huginn_shell.py").exists():
        sys.path.insert(0, str(shell_dir))
        break

from gi.repository import Gio, GLib  # noqa: E402
from PySide6.QtCore import Property, QMimeDatabase, QObject, QTimer, QUrl, Signal, Slot  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402
from PySide6.QtQml import QQmlApplicationEngine  # noqa: E402

from huginn_portal_ask import Prompt, Shot  # noqa: E402

BUS_NAME = "org.freedesktop.impl.portal.desktop.huginn"
OBJECT = "/org/freedesktop/portal/desktop"
XML = """<node>
<interface name="org.freedesktop.impl.portal.FileChooser">
  <method name="OpenFile"><arg type="o" name="handle" direction="in"/><arg type="s" name="app_id" direction="in"/><arg type="s" name="parent_window" direction="in"/>
    <arg type="s" name="title" direction="in"/><arg type="a{sv}" name="options" direction="in"/><arg type="u" direction="out"/><arg type="a{sv}" direction="out"/></method>
  <method name="SaveFile"><arg type="o" name="handle" direction="in"/><arg type="s" name="app_id" direction="in"/><arg type="s" name="parent_window" direction="in"/>
    <arg type="s" name="title" direction="in"/><arg type="a{sv}" name="options" direction="in"/><arg type="u" direction="out"/><arg type="a{sv}" direction="out"/></method>
  <method name="SaveFiles"><arg type="o" name="handle" direction="in"/><arg type="s" name="app_id" direction="in"/><arg type="s" name="parent_window" direction="in"/>
    <arg type="s" name="title" direction="in"/><arg type="a{sv}" name="options" direction="in"/><arg type="u" direction="out"/><arg type="a{sv}" direction="out"/></method>
  <property name="version" type="u" access="read"/>
</interface>
<interface name="org.freedesktop.impl.portal.Screenshot">
  <method name="Screenshot"><arg type="o" name="handle" direction="in"/><arg type="s" name="app_id" direction="in"/><arg type="s" name="parent_window" direction="in"/>
    <arg type="a{sv}" name="options" direction="in"/><arg type="u" direction="out"/><arg type="a{sv}" direction="out"/></method>
  <method name="PickColor"><arg type="o" name="handle" direction="in"/><arg type="s" name="app_id" direction="in"/><arg type="s" name="parent_window" direction="in"/>
    <arg type="a{sv}" name="options" direction="in"/><arg type="u" direction="out"/><arg type="a{sv}" direction="out"/></method>
  <property name="version" type="u" access="read"/>
</interface>
<interface name="org.freedesktop.impl.portal.Access">
  <method name="AccessDialog"><arg type="o" name="handle" direction="in"/><arg type="s" name="app_id" direction="in"/><arg type="s" name="parent_window" direction="in"/>
    <arg type="s" name="title" direction="in"/><arg type="s" name="subtitle" direction="in"/><arg type="s" name="body" direction="in"/>
    <arg type="a{sv}" name="options" direction="in"/><arg type="u" direction="out"/><arg type="a{sv}" direction="out"/></method>
</interface>
<interface name="org.freedesktop.impl.portal.AppChooser">
  <method name="ChooseApplication"><arg type="o" name="handle" direction="in"/><arg type="s" name="app_id" direction="in"/><arg type="s" name="parent_window" direction="in"/>
    <arg type="as" name="choices" direction="in"/><arg type="a{sv}" name="options" direction="in"/><arg type="u" direction="out"/><arg type="a{sv}" direction="out"/></method>
  <method name="UpdateChoices"><arg type="o" name="handle" direction="in"/><arg type="as" name="choices" direction="in"/></method>
  <property name="version" type="u" access="read"/>
</interface>
</node>"""
VERSIONS = {"org.freedesktop.impl.portal.FileChooser": 4, "org.freedesktop.impl.portal.Screenshot": 2,
            "org.freedesktop.impl.portal.AppChooser": 2}
REQUEST_XML = """<node><interface name="org.freedesktop.impl.portal.Request"><method name="Close"/></interface></node>"""
SUCCESS, CANCELLED = 0, 1
MEMORY = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "huginn" / "file-chooser.json"
IMAGE = (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".svg", ".avif", ".heic", ".tif", ".tiff")
MIMES = QMimeDatabase()



def qt_runs_glib() -> bool:
    """Ubuntu's Qt runs GLib's loop itself, and GLib's sources (D-Bus) are served with Qt's events. Turning GLib's
    loop by hand from a Qt timer as well would run Qt's events inside Qt's events: a window drawn in the middle of
    drawing another, which can leave a surface waiting forever for its compositor."""
    from PySide6.QtCore import QAbstractEventDispatcher
    d = QAbstractEventDispatcher.instance()
    return d is not None and "Glib" in d.metaObject().className()

def bytes_path(v) -> str:
    """The portal's paths come as NUL-terminated byte strings."""
    if not v:
        return ""
    raw = bytes(v)
    return raw.rstrip(b"\0").decode("utf-8", "surrogateescape")


def uri(path: str) -> str:
    return "file://" + quote(path)


def size_text(n: int) -> str:
    for unit in ("bytes", "KB", "MB", "GB", "TB"):
        if n < 1000 or unit == "TB":
            return f"{n} {unit}" if unit == "bytes" else f"{n:.1f} {unit}".replace(".0 ", " ")
        n /= 1000
    return ""


def when_text(t: float) -> str:
    now = time.time()
    lt = time.localtime(t)
    if now - t < 86400 and time.localtime(now).tm_yday == lt.tm_yday:
        return "Today " + time.strftime("%H:%M", lt)
    if now - t < 2 * 86400:
        return "Yesterday " + time.strftime("%H:%M", lt)
    return time.strftime("%-d %b %Y" if lt.tm_year != time.localtime(now).tm_year else "%-d %b %H:%M", lt)


def kind_of(path: Path, is_dir: bool) -> tuple:
    """(glyph, words) for a row: a folder, a picture, a song…"""
    if is_dir:
        return "folder", "Folder"
    mime = MIMES.mimeTypeForFile(str(path), QMimeDatabase.MatchExtension)
    name = mime.name()
    glyph = ("image" if name.startswith("image/") else "music" if name.startswith("audio/") else "video" if name.startswith("video/")
             else "doc" if name.startswith("text/") or "document" in name or name in ("application/pdf", "application/rtf") else "file")
    return glyph, mime.comment() or "File"


def places() -> list:
    home = Path.home()
    rows = [{"name": "Home", "path": str(home), "glyph": "home"}]
    for name, glyph, key in (("Desktop", "desktop", "DESKTOP"), ("Documents", "doc", "DOCUMENTS"), ("Downloads", "download", "DOWNLOAD"),
                             ("Pictures", "image", "PICTURES"), ("Music", "music", "MUSIC"), ("Videos", "video", "VIDEOS")):
        p = xdg_dir(key) or home / name
        if p.is_dir() and p != home:
            rows.append({"name": p.name if p.name != name and p.parent != home else name, "path": str(p), "glyph": glyph})
    return rows


def xdg_dir(key: str):
    try:
        text = (Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "user-dirs.dirs").read_text(encoding="utf-8")
    except OSError:
        return None
    m = re.search(rf'^XDG_{key}_DIR="([^"]+)"', text, re.M)
    return Path(m.group(1).replace("$HOME", str(Path.home()))) if m else None


def drives() -> list:
    """Mounted drives a person would call a drive: USB sticks, SD cards, other disks (mounted under /media or /run/media)."""
    out = []
    try:
        lines = Path("/proc/self/mounts").read_text().splitlines()
    except OSError:
        return out
    for line in lines:
        parts = line.split()
        if len(parts) < 3:
            continue
        where = parts[1].replace("\\040", " ")
        if where.startswith(("/media/", "/run/media/")) and os.path.isdir(where):
            out.append({"name": os.path.basename(where) or where, "path": where, "glyph": "disc"})
    return out


def matches(name: str, patterns: list) -> bool:
    """A filter's patterns: globs (type 0, case-insensitive) and MIME types (type 1)."""
    if not patterns:
        return True
    lower = name.lower()
    for kind, pat in patterns:
        if kind == 0 and fnmatch.fnmatch(lower, pat.lower()):
            return True
        if kind == 1:
            mime = MIMES.mimeTypeForFile(name, QMimeDatabase.MatchExtension)
            if mime.inherits(pat) or (pat.endswith("/*") and mime.name().startswith(pat[:-1])):
                return True
    return False


def recent_files(limit: int = 40) -> list:
    """Recently used files, from the freedesktop list every toolkit keeps (~/.local/share/recently-used.xbel)."""
    path = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share") / "recently-used.xbel"
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    found = []
    for href, modified in re.findall(r'<bookmark href="file://([^"]+)"[^>]*?modified="([^"]+)"', text):
        p = unquote(href)
        if os.path.isfile(p):
            found.append((modified, p))
    seen, out = set(), []
    for _m, p in sorted(found, reverse=True):
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out[:limit]


class Chooser(QObject):
    """One question at a time: what's asked, the folder being looked at, and the answer."""
    changed = Signal()
    listed = Signal()
    finished = Signal(int, "QVariantMap")

    def __init__(self):
        super().__init__()
        self._active = False
        self._mode = "open"                   # open, save, saveFiles
        self._title = ""
        self._accept = ""
        self._multiple = False
        self._directory = False
        self._filters = []                    # [{"name", "patterns": [(type, pattern)]}]
        self._filter = 0
        self._choices = []                    # [{"id", "label", "options": [{"id","label"}], "value"}]
        self._name = ""
        self._folder = str(Path.home())
        self._back, self._fwd = [], []
        self._rows = []
        self._hidden = False
        self._query = ""
        self._sort = "name"
        self._recent = False
        self._grid = False
        self._files = []                      # SaveFiles: the names to save
        self._app = ""
        try:
            self._memory = json.loads(MEMORY.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self._memory = {}
        self._grid = bool(self._memory.get("grid", False))
        self._sort = self._memory.get("sort", "name") if self._memory.get("sort") in ("name", "date", "size", "kind") else "name"
        self._hidden = bool(self._memory.get("hidden", False))

    def remember(self, **what) -> None:
        self._memory.update(what)
        try:
            MEMORY.parent.mkdir(parents=True, exist_ok=True)
            tmp = MEMORY.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._memory, indent=1), encoding="utf-8")
            tmp.replace(MEMORY)
        except OSError:
            pass

    # ------------------------------------------------------------------ the question
    def ask(self, mode: str, app_id: str, title: str, options: dict) -> None:
        self._mode = mode
        self._app = app_id
        self._multiple = bool(options.get("multiple", False))
        self._directory = bool(options.get("directory", False))
        default = {"open": "Open", "save": "Save", "saveFiles": "Save"}[mode]
        self._title = title or ("Choose a Folder" if self._directory else {"open": "Open", "save": "Save", "saveFiles": "Save Files"}[mode])
        self._accept = (options.get("accept_label") or default).replace("_", "")
        self._filters = [{"name": n, "patterns": [(int(k), str(p)) for k, p in pats]} for n, pats in (options.get("filters") or [])]
        current = options.get("current_filter")
        self._filter = 0
        if current:
            for i, f in enumerate(self._filters):
                if f["name"] == current[0]:
                    self._filter = i
                    break
            else:
                self._filters.insert(0, {"name": current[0], "patterns": [(int(k), str(p)) for k, p in current[1]]})
        self._choices = []
        for cid, label, opts, value in options.get("choices") or []:
            self._choices.append({"id": cid, "label": label, "options": [{"id": a, "label": b} for a, b in opts], "value": value or ("false" if not opts else opts[0][0])})
        folder = bytes_path(options.get("current_folder"))
        current_file = bytes_path(options.get("current_file"))
        if current_file:
            folder = folder or str(Path(current_file).parent)
        self._name = options.get("current_name") or (Path(current_file).name if current_file else "")
        self._files = [bytes_path(f) for f in options.get("files") or []]
        self._back, self._fwd = [], []
        self._query, self._recent = "", False
        last = (self._memory.get("folders") or {}).get(app_id or "-", "")
        start = next((f for f in (folder, last) if f and os.path.isdir(f)), str(Path.home()))
        self._active = True
        self.go(start, remember=False)
        self.changed.emit()

    def finish(self, code: int, results: dict) -> None:
        self._active = False
        if code == SUCCESS and not self._recent:
            folders = dict(self._memory.get("folders") or {})
            folders[self._app or "-"] = self._folder
            self.remember(folders=dict(list(folders.items())[-60:]))
        self.changed.emit()
        self.finished.emit(code, results)

    # ------------------------------------------------------------------ the folder
    def go(self, folder: str, remember: bool = True) -> None:
        folder = os.path.expanduser(folder)
        if not os.path.isdir(folder):
            return
        folder = os.path.abspath(folder)
        if remember and folder != self._folder:
            self._back.append(self._folder)
            self._fwd = []
        self._folder = folder
        self._recent = False
        self._query = ""
        self.refresh()

    @Slot(str)
    def open(self, folder: str) -> None:
        self.go(folder)

    @Slot()
    def showRecent(self) -> None:
        self._recent = True
        self._query = ""
        self.refresh()

    @Slot()
    def back(self) -> None:
        if self._back:
            self._fwd.append(self._folder)
            self._folder = self._back.pop()
            self._recent = False
            self.refresh()

    @Slot()
    def forward(self) -> None:
        if self._fwd:
            self._back.append(self._folder)
            self._folder = self._fwd.pop()
            self._recent = False
            self.refresh()

    @Slot()
    def up(self) -> None:
        parent = os.path.dirname(self._folder.rstrip("/")) or "/"
        if parent != self._folder:
            self.go(parent)

    @Slot()
    def refresh(self) -> None:
        rows = []
        pats = self._filters[self._filter]["patterns"] if self._filters and not self._directory else []
        entries = []
        if self._recent:
            for p in recent_files():
                try:
                    st = os.stat(p)
                except OSError:
                    continue
                entries.append((os.path.basename(p), p, False, st))
        else:
            try:
                with os.scandir(self._folder) as it:
                    for e in it:
                        try:
                            is_dir = e.is_dir()
                            st = e.stat()
                        except OSError:
                            continue
                        entries.append((e.name, e.path, is_dir, st))
            except OSError:
                entries = []
        q = self._query.lower()
        for name, path, is_dir, st in entries:
            if name.startswith(".") and not self._hidden:
                continue
            if q and q not in name.lower():
                continue
            if not is_dir and (self._directory or not matches(name, pats)):
                continue
            glyph, kind = kind_of(Path(path), is_dir)
            rows.append({"name": name, "path": path, "dir": is_dir, "size": 0 if is_dir else st.st_size,
                         "sizeText": "" if is_dir else size_text(st.st_size), "when": when_text(st.st_mtime), "mtime": st.st_mtime,
                         "glyph": glyph, "kind": kind, "url": uri(path),
                         "picture": QUrl.fromLocalFile(path).toString() if not is_dir and name.lower().endswith(IMAGE) else ""})
        key = {"name": lambda r: r["name"].lower(), "date": lambda r: -r["mtime"], "size": lambda r: -r["size"], "kind": lambda r: (r["kind"], r["name"].lower())}[self._sort]
        if self._recent:
            key = lambda r: -r["mtime"]            # noqa: E731
        rows.sort(key=key)
        rows.sort(key=lambda r: not r["dir"])         # folders first, keeping the order within each
        self._rows = rows
        self.listed.emit()
        self.changed.emit()

    @Slot(str)
    def search(self, text: str) -> None:
        self._query = text
        self.refresh()

    @Slot(str)
    def sortBy(self, key: str) -> None:
        if key in ("name", "date", "size", "kind"):
            self._sort = key
            self.remember(sort=key)
            self.refresh()

    @Slot(bool)
    def showHidden(self, on: bool) -> None:
        self._hidden = on
        self.remember(hidden=on)
        self.refresh()

    @Slot(int)
    def setFilter(self, i: int) -> None:
        if 0 <= i < len(self._filters):
            self._filter = i
            if self._mode == "save" and self._name:
                self._name = self.with_extension(self._name)
            self.refresh()

    def with_extension(self, name: str) -> str:
        """Saving with a filter like "*.png": the name follows it (photo.jpg → photo.png)."""
        pats = self._filters[self._filter]["patterns"] if self._filters else []
        glob = next((p for k, p in pats if k == 0 and re.fullmatch(r"\*\.[A-Za-z0-9]+", p)), "")
        if not glob or matches(name, pats):
            return name
        return re.sub(r"\.[A-Za-z0-9]{1,5}$", "", name) + glob[1:]

    @Slot(bool)
    def setGrid(self, on: bool) -> None:
        self._grid = on
        self.remember(grid=on)
        self.changed.emit()

    @Slot(str, str)
    def setChoice(self, cid: str, value: str) -> None:
        for c in self._choices:
            if c["id"] == cid:
                c["value"] = value
        self.changed.emit()

    @Slot(str)
    def setName(self, name: str) -> None:
        self._name = name

    @Slot(str, result=str)
    def newFolder(self, name: str) -> str:
        """Makes a folder here; returns "" or what went wrong."""
        name = (name or "").strip()
        if not name or "/" in name:
            return "A folder's name can't be empty or have a /."
        try:
            os.mkdir(os.path.join(self._folder, name))
        except FileExistsError:
            return f"There's already something called “{name}” here."
        except OSError as err:
            return f"Can't make it here: {err.strerror}."
        self.refresh()
        return ""

    # ------------------------------------------------------------------ answering
    def _results(self, uris: list) -> dict:
        out = {"uris": GLib.Variant("as", uris), "choices": GLib.Variant("a(ss)", [(c["id"], c["value"]) for c in self._choices]),
               "writable": GLib.Variant("b", True)}
        if self._filters:
            f = self._filters[self._filter]
            out["current_filter"] = GLib.Variant("(sa(us))", (f["name"], [(k, p) for k, p in f["patterns"]]))
        return out

    @Slot("QVariantList")
    def accept(self, paths: list) -> None:
        """Open: the files (or folders) chosen; with nothing chosen and a folder wanted, the folder being looked at."""
        paths = [p for p in paths if p]
        if self._directory and not paths:
            paths = [self._folder]
        if not paths:
            return
        files = [p for p in paths if self._directory or not os.path.isdir(p)]
        if len(paths) == 1 and os.path.isdir(paths[0]) and not self._directory:
            self.go(paths[0])
            return
        if not self._multiple:
            files = files[:1]
        if files:
            self.finish(SUCCESS, self._results([uri(p) for p in files]))

    @Slot(str, result=str)
    def save(self, name: str) -> str:
        """Save: "" when it's done; "exists" when it needs to ask about replacing; or what's wrong with the name."""
        name = (name or "").strip()
        if not name:
            return "Give it a name."
        if name.startswith(("/", "~")):                    # a whole path typed in: go there, keep its name
            target = os.path.expanduser(name)
            if os.path.isdir(target):
                self.go(target)
                return "folder"
            self.go(os.path.dirname(target))
            name = os.path.basename(target)
            self._name = name
        if "/" in name:
            return "A name can't have a / in it."
        path = os.path.join(self._folder, name)
        if os.path.isdir(path):
            self.go(path)
            return "folder"
        if os.path.exists(path):
            return "exists"
        self.finish(SUCCESS, self._results([uri(path)]))
        return ""

    @Slot(str)
    def replace(self, name: str) -> None:
        self.finish(SUCCESS, self._results([uri(os.path.join(self._folder, name.strip()))]))

    @Slot()
    def saveHere(self) -> None:
        """SaveFiles: the folder being looked at, with each file's name in it."""
        self.finish(SUCCESS, self._results([uri(os.path.join(self._folder, os.path.basename(f))) for f in self._files]))

    @Slot()
    def cancel(self) -> None:
        if self._active:
            self.finish(CANCELLED, {})

    # ------------------------------------------------------------------ for the window
    active = Property(bool, lambda self: self._active, notify=changed)
    mode = Property(str, lambda self: self._mode, notify=changed)
    title = Property(str, lambda self: self._title, notify=changed)
    acceptLabel = Property(str, lambda self: self._accept, notify=changed)
    multiple = Property(bool, lambda self: self._multiple, notify=changed)
    directory = Property(bool, lambda self: self._directory, notify=changed)
    folder = Property(str, lambda self: self._folder, notify=changed)
    folderName = Property(str, lambda self: "Recent" if self._recent else (os.path.basename(self._folder) or "/"), notify=changed)
    crumbs = Property("QVariantList", lambda self: [] if self._recent else self._crumbs(), notify=changed)
    rows = Property("QVariantList", lambda self: self._rows, notify=listed)
    filters = Property("QVariantList", lambda self: [f["name"] for f in self._filters], notify=changed)
    filterIndex = Property(int, lambda self: self._filter, notify=changed)
    choices = Property("QVariantList", lambda self: self._choices, notify=changed)
    name = Property(str, lambda self: self._name, notify=changed)
    places = Property("QVariantList", lambda self: places(), notify=changed)
    drives = Property("QVariantList", lambda self: drives(), notify=changed)
    canBack = Property(bool, lambda self: bool(self._back), notify=changed)
    canForward = Property(bool, lambda self: bool(self._fwd), notify=changed)
    hidden = Property(bool, lambda self: self._hidden, notify=changed)
    grid = Property(bool, lambda self: self._grid, notify=changed)
    sort = Property(str, lambda self: self._sort, notify=changed)
    recent = Property(bool, lambda self: self._recent, notify=changed)
    query = Property(str, lambda self: self._query, notify=changed)
    files = Property("QVariantList", lambda self: [os.path.basename(f) for f in self._files], notify=changed)
    app = Property(str, lambda self: self._app, notify=changed)

    def _crumbs(self) -> list:
        home = str(Path.home())
        parts, out = [], []
        path = self._folder
        if path == home or path.startswith(home + "/"):
            out.append({"name": "Home", "path": home})
            rest = path[len(home):].strip("/")
            parts, base = (rest.split("/") if rest else []), home
        else:
            out.append({"name": "Computer", "path": "/"})
            parts, base = path.strip("/").split("/") if path != "/" else [], ""
        for p in parts:
            base = base + "/" + p
            out.append({"name": p, "path": base})
        return out


class Portal:
    """The D-Bus side: one question at a time (a file, an app, a yes or no, a picture); another one waits its turn."""

    def __init__(self, chooser: Chooser, conn, prompt=None, shot=None):
        self.helpers = {"files": chooser, "prompt": prompt, "shot": shot}
        self.conn = conn
        self.queue = []
        self.current = None
        self.request_reg = None
        node = Gio.DBusNodeInfo.new_for_xml(XML)
        for iface in node.interfaces:
            conn.register_object(OBJECT, iface, self._call, self._get, None)
        for helper in self.helpers.values():
            if helper is not None:
                helper.finished.connect(self._done)

    def _get(self, conn, sender, path, iface, prop):
        return GLib.Variant("u", VERSIONS.get(iface, 1)) if prop == "version" else None

    def _call(self, conn, sender, path, iface, method, params, inv):
        args = params.unpack()
        if method in ("OpenFile", "SaveFile", "SaveFiles"):
            handle, app_id, _parent, title, options = args
            mode = {"OpenFile": "open", "SaveFile": "save", "SaveFiles": "saveFiles"}[method]
            job = ("files", lambda: self.helpers["files"].ask(mode, app_id, title, options))
        elif method in ("Screenshot", "PickColor") and self.helpers["shot"]:
            handle, app_id, _parent, options = args
            kind = "shot" if method == "Screenshot" else "colour"
            job = ("shot", lambda: self.helpers["shot"].ask(kind, app_id, options))
        elif method == "AccessDialog" and self.helpers["prompt"]:
            handle, app_id, _parent, title, subtitle, body, options = args
            job = ("prompt", lambda: self.helpers["prompt"].ask_access(app_id, title, subtitle, body, options))
        elif method == "ChooseApplication" and self.helpers["prompt"]:
            handle, app_id, _parent, choices, options = args
            job = ("prompt", lambda: self.helpers["prompt"].ask_apps(app_id, choices, options))
        elif method == "UpdateChoices" and self.helpers["prompt"]:
            handle, choices = args
            if self.current and self.current[1] == handle:
                self.helpers["prompt"].update_apps(choices)
            inv.return_value(None)
            return
        else:
            inv.return_dbus_error("org.freedesktop.DBus.Error.UnknownMethod", method)
            return
        self.queue.append((inv, handle, job))
        if self.current is None:
            self._next()

    def _next(self) -> None:
        if not self.queue:
            return
        self.current = self.queue.pop(0)
        _inv, handle, (helper, start) = self.current
        try:                                           # the portal may close the request (the app gave up)
            node = Gio.DBusNodeInfo.new_for_xml(REQUEST_XML)
            self.request_reg = self.conn.register_object(handle, node.interfaces[0],
                                                         lambda *a: (a[-1].return_value(None), self.helpers[helper].cancel()), None, None)
        except GLib.Error:
            self.request_reg = None
        start()

    def _done(self, code: int, results: dict) -> None:
        if self.current is None:
            return
        inv = self.current[0]
        self.current = None
        if self.request_reg:
            self.conn.unregister_object(self.request_reg)
            self.request_reg = None
        inv.return_value(GLib.Variant("(ua{sv})", (code, results)))
        QTimer.singleShot(0, self._next)


def wait_for_display(limit: float = 120.0) -> None:
    """Until there's a screen to open windows on (the compositor's Wayland socket, or X11 in tests), keep answering
    D-Bus: a question that comes meanwhile is held, and its window opens once the screen is there."""
    if os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
        return
    runtime = Path(os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}")
    name = os.environ.get("WAYLAND_DISPLAY") or "wayland-0"
    socket_path = Path(name) if name.startswith("/") else runtime / name
    loop = GLib.MainLoop()
    end = time.monotonic() + limit

    def check():
        if socket_path.exists() or time.monotonic() > end:
            loop.quit()
            return False
        return True
    if not socket_path.exists():
        GLib.timeout_add(250, check)
        loop.run()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--demo", nargs="?", const="open", choices=("open", "save", "access", "apps", "shot", "colour"),
                    help="show one of the windows on its own (open, save, access, apps, shot, colour)")
    ap.add_argument("--save", action="store_true", help="the same as --demo save")
    args = ap.parse_args()
    if args.save:
        args.demo = "save"
    chooser, prompt = Chooser(), Prompt()
    shot = Shot(None)
    portal = None
    if not args.demo:
        # D-Bus activated, and the portal waits on us: answer to the name first, open a window connection after. (The
        # portal gives up on a backend that takes too long to appear, and then has no Open and Save windows at all.
        # It is started with the session, often before the compositor is listening, so the window side waits for it.)
        conn = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        shot = Shot(conn)
        portal = Portal(chooser, conn, prompt, shot)
        got = conn.call_sync("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus", "RequestName",
                             GLib.Variant("(su)", (BUS_NAME, 4)), GLib.VariantType("(u)"), 0, 5000, None)
        if got.unpack()[0] not in (1, 4):                  # someone else is already the file chooser
            return 0
        wait_for_display()
    app = QGuiApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setDesktopFileName("huginn-files-chooser")          # Files' colour, but not mistaken for the Files app
    if portal is not None:
        idle = QTimer(interval=600000)                   # leaves after ten quiet minutes; the portal starts it again
        idle.timeout.connect(lambda: app.quit() if portal.current is None and not portal.queue else None)
        idle.start()
    pump = QTimer(interval=30)
    pump.timeout.connect(lambda: GLib.MainContext.default().iteration(False))
    if not qt_runs_glib():
        pump.start()
    ui = {}

    def load() -> None:
        from huginn_shell import SysIcon, make_theme
        tokens, settings, theme = make_theme(False, False, "", persist=False, app="files")
        engine = QQmlApplicationEngine()
        engine.addImageProvider("sysicon", SysIcon())
        ctx = engine.rootContext()
        ctx.setContextProperty("Theme", theme)
        ctx.setContextProperty("Chooser", chooser)
        ctx.setContextProperty("Prompt", prompt)
        ctx.setContextProperty("Shot", shot)
        for page in ("FileChooser.qml", "PortalPrompt.qml", "PortalShot.qml"):
            engine.load(QUrl.fromLocalFile(str(HERE / "qml" / page)))
        ui.update(engine=engine, theme=theme, settings=settings)
        if len(engine.rootObjects()) < 3:
            app.exit(1)
            return
        if args.demo:
            def said(code, res):
                print(code, {k: v.unpack() if hasattr(v, "unpack") else v for k, v in res.items()}, flush=True)
                app.quit()
            for helper in (chooser, prompt, shot):
                helper.finished.connect(said)
            if args.demo in ("open", "save"):
                opts = {"filters": [("Pictures", [(1, "image/*")]), ("Everything", [(0, "*")])], "multiple": True}
                if args.demo == "save":
                    opts = {"current_name": "Untitled.txt", "filters": [("Text", [(0, "*.txt")]), ("Markdown", [(0, "*.md")])]}
                chooser.ask(args.demo, "", "", opts)
            elif args.demo == "access":
                prompt.ask_access("org.example.Camera", "Allow Camera to Use the Camera?", "Camera wants to see you.",
                                  "You can change this at any time in Settings › Privacy.",
                                  {"grant_label": "Allow", "deny_label": "Deny", "icon": "camera",
                                   "choices": [("remember", "Remember this for Camera", [], "true")]})
            elif args.demo == "apps":
                ids = [a.stem for a in sorted(Path("/usr/share/applications").glob("huginn-*.desktop"))][:5] or ["huginn-documents"]
                prompt.ask_apps("", ids, {"filename": "Holiday plan.pdf", "content_type": "application/pdf", "last_choice": ids[0]})
            else:
                shot.ask(args.demo, "", {"interactive": True})
    QTimer.singleShot(0, load)
    code = app.exec()
    ui.pop("engine", None)          # the QML goes before the Python objects it binds to
    return code


if __name__ == "__main__":
    sys.exit(main())
