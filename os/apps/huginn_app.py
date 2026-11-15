#!/usr/bin/env python3
"""Huginn OS apps: one host, twenty apps that share the shell's theme, settings and component kit.

  huginn_app.py <app> [file or folder to open]
  apps: files calendar mail settings monitor store video music notes photos documents calculator clock terminal
        screenshot archives welcome writer sheets slides
  options:  --dark | --light   --realm NAME   --demo (sample content)   --shot out.png (render and exit)

Each app is a QML file in qml/ plus a small backend class here.
"""
import argparse
import calendar as cal
import datetime as dt
import json
import os
import shutil
import signal
import subprocess
import shlex
import sys
import threading
import time
import re
import uuid
from pathlib import Path
from urllib.parse import quote, unquote

HERE = Path(__file__).resolve().parent
for shell_dir in (HERE.parent / "shell", Path("/usr/share/huginn-shell")):
    if (shell_dir / "huginn_shell.py").is_file():
        sys.path.insert(0, str(shell_dir))
        break

from PySide6.QtCore import Property, QFileSystemWatcher, QMimeData, QMimeDatabase, QObject, QSize, QStandardPaths, Qt, QTimer, QUrl, Signal, Slot  # noqa: E402
from PySide6.QtGui import (QColor, QDesktopServices, QFont, QGuiApplication, QImage, QImageReader, QPainter,  # noqa: E402
                           QPainterPath, QSyntaxHighlighter, QTextCharFormat)
from PySide6.QtQml import QQmlApplicationEngine  # noqa: E402
from PySide6.QtQuick import QQuickImageProvider, QQuickWindow  # noqa: E402,F401

from huginn_shell import make_theme  # noqa: E402

DATA_HOME = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share") / "huginn"
AUDIO = {".mp3", ".flac", ".ogg", ".opus", ".m4a", ".wav", ".aac"}
VIDEO = {".mp4", ".mkv", ".webm", ".mov", ".avi", ".m4v"}
IMAGES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp"}
DOCS = {".pdf", ".txt", ".md", ".odt", ".docx", ".ods", ".xlsx", ".odp", ".pptx", ".csv"}


def human_size(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit in ("B", "KB") else f"{n:.1f} {unit}"
        n /= 1024
    return ""


def file_kind(path: Path) -> str:
    if path.is_dir():
        return "folder"
    ext = path.suffix.lower()
    return ("image" if ext in IMAGES else "music" if ext in AUDIO else "video" if ext in VIDEO
            else "doc" if ext in DOCS else "file")


# ------------------------------------------------------------------------------------------------ Trash
# The freedesktop.org Trash layout, so Files' Trash view, Restore and any other file manager all agree.
def trash_home() -> Path:
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share") / "Trash"


def mount_of(path: Path) -> Path:
    """The top folder of the drive this path is on."""
    path = Path(os.path.abspath(path))
    while path.parent != path and not os.path.ismount(path):
        path = path.parent
    return path


def _uid() -> int:
    return os.getuid() if hasattr(os, "getuid") else 0


def move_to_trash(path: str) -> None:
    """Move a file or folder to the trash (never deletes outright). Raises OSError."""
    src = Path(os.path.abspath(path))
    if not os.path.lexists(src):
        raise FileNotFoundError(2, "It is no longer there", str(src))
    home = trash_home()
    (home / "files").mkdir(parents=True, exist_ok=True)
    (home / "info").mkdir(parents=True, exist_ok=True)
    bin_dir, top = home, None
    if os.lstat(src).st_dev != os.stat(home).st_dev:       # on another drive: use that drive's own trash, so nothing is copied
        try:
            top = mount_of(src.parent)
            bin_dir = top / f".Trash-{_uid()}"
            (bin_dir / "files").mkdir(parents=True, exist_ok=True, mode=0o700)
            (bin_dir / "info").mkdir(parents=True, exist_ok=True, mode=0o700)
        except OSError:
            bin_dir, top = home, None
    n = 1
    while True:
        name = src.name if n == 1 else f"{src.stem} {n}{src.suffix}"
        note = bin_dir / "info" / f"{name}.trashinfo"
        if not os.path.lexists(bin_dir / "files" / name):
            try:
                fd = os.open(note, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                break
            except FileExistsError:
                pass
        n += 1
    where = str(src) if top is None else os.path.relpath(src, top)
    with os.fdopen(fd, "w", encoding="utf-8") as out:
        out.write(f"[Trash Info]\nPath={quote(where)}\nDeletionDate={dt.datetime.now().strftime('%Y-%m-%dT%H:%M:%S')}\n")
    try:
        try:
            os.rename(src, bin_dir / "files" / name)
        except OSError:
            shutil.move(str(src), str(bin_dir / "files" / name))
    except Exception:
        note.unlink(missing_ok=True)
        raise


def trash_bins() -> list:
    """Every trash this user has: [(folder, top of its drive or None for the home one)]."""
    bins, seen = [(trash_home(), None)], set()
    try:
        with open("/proc/self/mounts", encoding="utf-8", errors="replace") as mounts:
            tops = [line.split()[1].replace("\\040", " ") for line in mounts if len(line.split()) > 1]
    except OSError:
        tops = []
    for top in tops:
        if top.startswith(("/media/", "/run/media/", "/mnt/")) and top not in seen:
            seen.add(top)
            spot = Path(top) / f".Trash-{_uid()}"
            if spot.is_dir():
                bins.append((spot, Path(top)))
    return bins


def trash_items() -> list:
    """What is in the trash: [{item, note, name, origin, when}], newest first."""
    rows = []
    for bin_dir, top in trash_bins():
        try:
            names = os.listdir(bin_dir / "files")
        except OSError:
            continue
        for name in names:
            item, note = bin_dir / "files" / name, bin_dir / "info" / f"{name}.trashinfo"
            origin, when = "", 0.0
            try:
                for line in note.read_text(encoding="utf-8", errors="replace").splitlines():
                    if line.startswith("Path="):
                        origin = unquote(line[5:].strip())
                        if origin and not os.path.isabs(origin):
                            origin = str((top or Path.home()) / origin)
                    elif line.startswith("DeletionDate="):
                        try:
                            when = dt.datetime.strptime(line[13:].strip()[:19], "%Y-%m-%dT%H:%M:%S").timestamp()
                        except ValueError:
                            pass
            except OSError:
                pass
            if not when:
                try:
                    when = os.lstat(item).st_mtime
                except OSError:
                    continue
            rows.append({"item": item, "note": note, "name": Path(origin).name if origin else name, "origin": origin, "when": when})
    return sorted(rows, key=lambda r: -r["when"])


def _rm(path) -> None:
    """Delete for good: a file, a link, or a whole folder (links inside are not followed)."""
    if os.path.isdir(path) and not os.path.islink(path):
        shutil.rmtree(path)
    else:
        os.unlink(path)


def free_name(folder: Path, name: str, tag: str = "") -> Path:
    """A name not taken in `folder`: "a.txt" → "a copy.txt" → "a copy 2.txt" (or "a 2.txt" with no tag)."""
    stem, suffix = (name, "") if (folder / name).is_dir() or name.startswith(".") and name.count(".") == 1 else (Path(name).stem, Path(name).suffix)
    n = 1
    while True:
        extra = (tag if n == 1 else f"{tag} {n}") if tag else ("" if n == 1 else f" {n}")
        target = folder / f"{stem}{extra}{suffix}"
        if not os.path.lexists(target):
            return target
        n += 1


def natural(text: str) -> list:
    """Sort key that puts "File 2" before "File 10"."""
    return [(0, int(part), "") if part.isdigit() else (1, 0, part) for part in re.split(r"(\d+)", text.lower()) if part]


KIND_NAMES = {"folder": "Folder", "image": "Picture", "music": "Audio", "video": "Video", "doc": "Document", "file": "File"}
TRASH = "trash:"
FIND_LIMIT = 500
THUMBED = IMAGES | VIDEO | {".pdf"}
MAX_TABS = 12
READ_INSIDE = {".pdf", ".docx", ".odt", ".xlsx", ".ods", ".pptx", ".odp"}
NET_SCHEMES = ("smb", "sftp", "ssh", "ftp", "ftps", "dav", "davs", "nfs", "afp")
LIVE_MOUNTS = ("/", "/boot", "/boot/efi", "/cdrom", "/rofs")


# ----------------------------------------------------------------------------------------------- Files
class Files(QObject):
    changed = Signal()
    failed = Signal(str)        # something went wrong, in plain words
    said = Signal(str)          # something worth a line: "3 items moved to the Trash"
    clipChanged = Signal()
    jobChanged = Signal()
    drivesChanged = Signal()
    undoChanged = Signal()
    _finished = Signal(str, str, bool)
    _found = Signal(int)

    def __init__(self, start: Path, persist: bool = True):
        super().__init__()
        self._start_pick = ""
        if start.is_file():                                      # opened on a file: show its folder with it selected
            self._start_pick, start = str(start), start.parent
        self._path, self._back, self._forward = start, [], []
        self._in_trash = False
        self._find, self._hits, self._finding, self._find_run = "", [], False, 0
        self._undo, self._undo_note, self._redo = None, "", None
        self._trash_n = None
        self._inside, self._notes = False, {}
        self._tabs, self._tab = [None], 0                        # the open tab's state is live; the others wait in here
        self._gvfs = Path(os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{_uid()}") / "gvfs"
        self._net_proc, self._net_wait, self._net_reply = None, threading.Event(), None
        self.changed.connect(self._changed_first)
        self._found.connect(self._on_found)
        self._scanned.connect(self.drivesChanged)
        self._watch = QFileSystemWatcher(self)
        self._settle = QTimer(self)
        self._settle.setSingleShot(True)
        self._settle.setInterval(350)
        self._settle.timeout.connect(self._seen_change)
        self._watch.directoryChanged.connect(lambda _p: self._settle.start())
        self._prefs_file = DATA_HOME / "files.json" if persist else None
        prefs = {}
        if self._prefs_file:
            try:
                prefs = json.loads(self._prefs_file.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                prefs = {}
        self._hidden = bool(prefs.get("hidden", False))
        self._grid = bool(prefs.get("grid", True))
        self._sort = prefs.get("sort") if prefs.get("sort") in ("name", "date", "size", "kind") else "name"
        self._down = bool(prefs.get("down", False))
        self._servers = [str(a) for a in prefs.get("servers", []) if isinstance(a, str)][:6]
        self._pins = [str(a) for a in prefs.get("pins", []) if isinstance(a, str)][:12]
        self._nearby, self._scanning = [], False
        self._clip, self._cut = [], False
        self._busy, self._job_text, self._progress, self._stop, self._worker = False, "", 0.0, False, None
        self._drives = []
        self._finished.connect(self._after_job)
        board = QGuiApplication.clipboard() if QGuiApplication.instance() else None
        if board:
            board.dataChanged.connect(self.clipChanged)
        self.refreshDrives()
        self._watch_here()

    def _changed_first(self) -> None:
        self._trash_n = None

    def _watch_here(self) -> None:
        """Watch the folder being shown, so what other apps do in it shows up by itself."""
        old = self._watch.directories()
        if old:
            self._watch.removePaths(old)
        if self._in_trash:
            self._watch.addPath(str(trash_home() / "files"))
        elif not self._find:
            self._watch.addPath(str(self._path))

    def _seen_change(self) -> None:
        if self._busy:
            self._settle.start()                                  # our own job is writing here: wait until it ends
        else:
            self.changed.emit()

    def _keep(self) -> None:
        if not self._prefs_file:
            return
        try:
            self._prefs_file.parent.mkdir(parents=True, exist_ok=True)
            self._prefs_file.write_text(json.dumps({"hidden": self._hidden, "grid": self._grid, "sort": self._sort, "down": self._down, "servers": self._servers, "pins": self._pins}), encoding="utf-8")
        except OSError:
            pass

    def _std(self, which) -> str:
        return QStandardPaths.writableLocation(which)

    @Property("QVariantList", constant=True)
    def places(self):
        sp = QStandardPaths
        rows = [("Home", "home", str(Path.home())), ("Desktop", "desktop", self._std(sp.DesktopLocation)),
                ("Documents", "doc", self._std(sp.DocumentsLocation)), ("Downloads", "download", self._std(sp.DownloadLocation)),
                ("Pictures", "image", self._std(sp.PicturesLocation)), ("Music", "music", self._std(sp.MusicLocation)),
                ("Videos", "video", self._std(sp.MoviesLocation))]
        return [{"name": n, "icon": i, "path": p} for n, i, p in rows if p]

    path = Property(str, lambda self: TRASH if self._in_trash else str(self._path), notify=changed)
    name = Property(str, lambda self: "Trash" if self._in_trash else self._label(self._path), notify=changed)
    startPick = Property(str, lambda self: self._start_pick, constant=True)
    finding = Property(str, lambda self: self._find, notify=changed)            # what a search through subfolders is for, or ""
    stillFinding = Property(bool, lambda self: self._finding, notify=changed)

    @Property(str, notify=changed)
    def free(self):
        if self._in_trash:
            return ""
        try:
            return human_size(shutil.disk_usage(self._path).free) + " free"
        except OSError:
            return ""
    inTrash = Property(bool, lambda self: self._in_trash, notify=changed)
    canBack = Property(bool, lambda self: bool(self._back), notify=changed)
    canForward = Property(bool, lambda self: bool(self._forward), notify=changed)
    canUp = Property(bool, lambda self: not self._in_trash and self._path.parent not in (self._path, self._gvfs), notify=changed)
    showHidden = Property(bool, lambda self: self._hidden, notify=changed)
    grid = Property(bool, lambda self: self._grid, notify=changed)
    sortBy = Property(str, lambda self: self._sort, notify=changed)
    sortDown = Property(bool, lambda self: self._down, notify=changed)
    canWrite = Property(bool, lambda self: not self._in_trash and not self._find and os.access(self._path, os.W_OK), notify=changed)

    @Property("QVariantList", notify=changed)
    def crumbs(self):
        if self._in_trash:
            return [{"name": "Trash", "path": TRASH}]
        home, parts, out = Path.home(), [], []
        p = self._path
        while True:
            parts.append(p)
            if p == home or p.parent == p or p.parent == self._gvfs:      # a network place starts at its own top
                break
            p = p.parent
        for p in reversed(parts):
            out.append({"name": self._label(p), "path": str(p)})
        return out

    def _label(self, p: Path) -> str:
        """What a folder is called in the path, on a tab and in the title."""
        return "Home" if p == Path.home() else self._net_name(p.name) if p.parent == self._gvfs else (p.name or "/")

    @staticmethod
    def _day(stamp: float) -> str:
        return dt.datetime.fromtimestamp(stamp).strftime("%b %-d, %Y" if os.name != "nt" else "%b %d, %Y")

    def _row(self, shown: str, real: Path, st, stamp: float, origin: str = "") -> dict:
        is_dir = real.is_dir() and not (self._in_trash and real.is_symlink())
        kind = "folder" if is_dir else file_kind(Path(shown))
        return {"name": shown, "path": str(real), "dir": is_dir, "kind": kind, "bytes": 0 if is_dir else st.st_size,
                "size": "" if is_dir else human_size(st.st_size), "stamp": stamp, "modified": self._day(stamp),
                "from": origin, "link": real.is_symlink(),
                "thumb": not is_dir and Path(shown).suffix.lower() in THUMBED}

    @Property("QVariantList", notify=changed)
    def entries(self):
        rows = []
        if self._in_trash:
            for it in trash_items():
                try:
                    st = os.lstat(it["item"])
                except OSError:
                    continue
                where = str(Path(it["origin"]).parent) if it["origin"] else ""
                home = str(Path.home())
                rows.append(self._row(it["name"], it["item"], st, it["when"], "Home" + where[len(home):] if where.startswith(home) else where))
        elif self._find:
            for hit in list(self._hits):
                try:
                    st = hit.stat()
                except OSError:
                    continue
                inside = os.path.relpath(hit.parent, self._path)
                row = self._row(hit.name, hit, st, st.st_mtime, "Here" if inside == "." else inside)
                row["line"] = self._notes.get(str(hit), "")
                rows.append(row)
        else:
            try:
                children = list(self._path.iterdir())
            except OSError as err:
                self.failed.emit(f"Can't open this folder: {err.strerror or err}")
                return rows
            for child in children:
                if child.name.startswith(".") and not self._hidden:
                    continue
                try:
                    st = child.stat()
                except OSError:
                    try:
                        st = child.lstat()                       # a link that points nowhere still shows
                    except OSError:
                        continue
                rows.append(self._row(child.name, child, st, st.st_mtime))
        keys = {"name": lambda r: natural(r["name"]), "date": lambda r: r["stamp"], "size": lambda r: r["bytes"],
                "kind": lambda r: (r["kind"], Path(r["name"]).suffix.lower())}
        rows.sort(key=lambda r: natural(r["name"]))
        if self._sort != "name" or self._down:
            rows.sort(key=keys[self._sort], reverse=self._down)
        rows.sort(key=lambda r: not r["dir"])                    # folders first, always
        return rows

    @Property(int, notify=changed)
    def trashCount(self):
        if self._trash_n is None:
            self._trash_n = len(trash_items())
        return self._trash_n

    # ------------------------------------------------------------------ moving around
    def _go(self, target, remember: bool = True) -> None:
        if target != TRASH and not Path(target).is_dir():
            self.failed.emit("That folder no longer exists.")
            return
        here = TRASH if self._in_trash else self._path
        if remember and target != here:
            self._back.append(here)
            self._forward.clear()
        self._in_trash = target == TRASH
        if not self._in_trash:
            self._path = Path(target)
        self._find, self._hits, self._finding = "", [], False
        self._find_run += 1
        self._watch_here()
        self.changed.emit()

    @Slot(str)
    def open(self, path: str) -> None:
        if path == TRASH:
            self._go(TRASH)
            return
        target = Path(path)
        if self._in_trash:
            self.said.emit("Put it back to open it.")
        elif target.is_dir():
            self._go(target)
        elif not QDesktopServices.openUrl(QUrl.fromLocalFile(str(target))):
            self.failed.emit("No app is set up to open this kind of file.")

    @Slot()
    def back(self) -> None:
        if self._back:
            self._forward.append(TRASH if self._in_trash else self._path)
            self._go(self._back.pop(), remember=False)

    @Slot()
    def forward(self) -> None:
        if self._forward:
            self._back.append(TRASH if self._in_trash else self._path)
            self._go(self._forward.pop(), remember=False)

    @Slot()
    def up(self) -> None:
        if not self._in_trash and self._path.parent != self._gvfs:
            self._go(self._path.parent)

    @Slot()
    def refresh(self) -> None:
        self.changed.emit()

    @Slot()
    def toggleHidden(self) -> None:
        self._hidden = not self._hidden
        self._keep()
        self.changed.emit()

    @Slot()
    def toggleGrid(self) -> None:
        self._grid = not self._grid
        self._keep()
        self.changed.emit()

    @Slot(str)
    def sort(self, by: str) -> None:
        """Sort by name, date, size or kind; asking for the same one again turns it round."""
        if by not in ("name", "date", "size", "kind"):
            return
        self._down = (not self._down) if by == self._sort else by in ("date", "size")    # newest and biggest first
        self._sort = by
        self._keep()
        self.changed.emit()

    # ------------------------------------------------------------------ tabs: several folders in one window
    def _state(self) -> dict:
        return {"path": self._path, "back": self._back, "forward": self._forward, "trash": self._in_trash}

    @Property("QVariantList", notify=changed)
    def tabs(self):
        out = []
        for i, st in enumerate(self._tabs):
            st = self._state() if i == self._tab else st
            out.append({"name": "Trash" if st["trash"] else self._label(st["path"]),
                        "path": TRASH if st["trash"] else str(st["path"])})
        return out

    tab = Property(int, lambda self: self._tab, notify=changed)

    def _show_tab(self, index: int) -> None:
        st = self._tabs[index]
        self._tab, self._tabs[index] = index, None
        self._path, self._back, self._forward, self._in_trash = st["path"], st["back"], st["forward"], st["trash"]
        if not self._in_trash and not self._path.is_dir():       # its folder went away while it was in the background
            self._path, self._back, self._forward = Path.home(), [], []
        self._find, self._hits, self._finding = "", [], False
        self._find_run += 1
        self._watch_here()
        self.changed.emit()

    @Slot(str)
    def newTab(self, path: str) -> None:
        """Open a folder in a new tab ("" for the one being shown)."""
        if len(self._tabs) >= MAX_TABS:
            self.failed.emit(f"{MAX_TABS} tabs is the most one window holds.")
            return
        target = Path(path) if path and path != TRASH and Path(path).is_dir() else self._path
        self._tabs[self._tab] = self._state()
        self._tabs.insert(self._tab + 1, {"path": target, "back": [], "forward": [], "trash": path == TRASH})
        self._show_tab(self._tab + 1)

    @Slot(int)
    def selectTab(self, index: int) -> None:
        if 0 <= index < len(self._tabs) and index != self._tab:
            self._tabs[self._tab] = self._state()
            self._show_tab(index)

    @Slot(int)
    def stepTab(self, by: int) -> None:
        if len(self._tabs) > 1:
            self.selectTab((self._tab + by) % len(self._tabs))

    @Slot(int)
    def closeTab(self, index: int) -> None:
        if not 0 <= index < len(self._tabs) or len(self._tabs) == 1:
            return
        if index == self._tab:
            self._tabs.pop(index)
            self._show_tab(min(index, len(self._tabs) - 1))
        else:
            self._tabs.pop(index)
            if index < self._tab:
                self._tab -= 1
            self.changed.emit()

    def _all_paths_leave(self, root: str) -> None:
        """A drive or server is going away: no tab may be left looking at it."""
        root = root.rstrip("/") + "/"
        for i, st in enumerate(self._tabs):
            if st and (str(st["path"]) + "/").startswith(root):
                self._tabs[i] = {"path": Path.home(), "back": [], "forward": [], "trash": st["trash"]}
        self._back = [p for p in self._back if p == TRASH or not (str(p) + "/").startswith(root)]
        self._forward = [p for p in self._forward if p == TRASH or not (str(p) + "/").startswith(root)]
        if (str(self._path) + "/").startswith(root):
            if self._in_trash:
                self._path = Path.home()
            else:
                self._go(Path.home(), remember=False)

    # ------------------------------------------------------------------ network places (shared folders, servers)
    servers = Property("QVariantList", lambda self: list(self._servers), notify=drivesChanged)     # addresses used before; never passwords
    netAsk = Signal("QVariantMap")                               # the server wants a name and password, or an answer

    @staticmethod
    def tidy_address(text: str) -> str:
        """What someone types → an address: \\\\nas\\films and //nas/films become smb://nas/films. "" if it isn't one."""
        text = text.strip().replace("\\", "/")
        if text.startswith("//") and len(text) > 2:
            text = "smb:" + text
        scheme, sep, rest = text.partition("://")
        if not sep or scheme.lower() not in NET_SCHEMES or not rest.strip("/") or any(c in text for c in " \n\t"):
            return ""
        return ("sftp" if scheme.lower() == "ssh" else scheme.lower()) + "://" + rest

    @staticmethod
    def _net_name(folder: str) -> str:
        """gvfs names its mounts "smb-share:server=nas,share=films": make that "films on nas"."""
        kind, _, rest = folder.partition(":")
        bits = dict(b.split("=", 1) for b in rest.split(",") if "=" in b)
        host = unquote(bits.get("host") or bits.get("server") or "")
        share = unquote(bits.get("share") or "")
        if kind == "smb-share" and share:
            return f"{share} on {host}"
        return host or folder

    def _net_mounts(self) -> list:
        try:
            names = sorted(os.listdir(self._gvfs))
        except OSError:
            return []
        return [{"dev": str(self._gvfs / n), "name": self._net_name(n), "path": str(self._gvfs / n), "mounted": True,
                 "locked": False, "lock": "", "net": True} for n in names if ":" in n]

    def _net_env(self) -> dict:
        return dict(os.environ, LC_ALL="C", LANGUAGE="C")

    @Slot(str)
    def connectTo(self, text: str) -> None:
        """Connect to a shared folder or server and open it. If it wants a name, password or an answer, netAsk says so
        and the connection waits for netAnswer. A password goes straight down a pipe to the system and is not kept."""
        address = self.tidy_address(text)
        if not address:
            self.failed.emit("That isn't an address Files knows. Try smb://computer/folder or sftp://server.")
            return
        if self._busy:
            return
        if not shutil.which("gio"):
            self.failed.emit("Network places need the system's sharing parts (gvfs), which aren't installed.")
            return
        self._net_wait.clear()
        self._net_reply = None

        def ask(what: dict):
            self._net_reply = None
            self._net_wait.clear()
            self.netAsk.emit(what)
            while not self._net_wait.wait(0.2):
                if self._stop:
                    return None
            return self._net_reply

        def work():
            try:
                proc = subprocess.Popen(["gio", "mount", address], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                        env=self._net_env())
            except OSError as err:
                return "", f"Couldn't connect: {err.strerror or err}", False
            self._net_proc = proc
            said, given, tries = b"", {}, 0

            def send(line: str) -> None:
                proc.stdin.write(line.encode() + b"\n")
                proc.stdin.flush()
            try:
                while True:
                    ch = proc.stdout.read(1)
                    if not ch:
                        break
                    said += ch
                    tail = said.rsplit(b"\n", 1)[-1].decode("utf-8", "replace")
                    prompt = re.match(r"^(User|Domain|Password|Choice)\b[^:]*: $", tail)
                    if not prompt:
                        continue
                    kind = prompt.group(1)
                    before = said.decode("utf-8", "replace").rsplit("\n", 1)[0].strip()
                    said = b""
                    if kind == "Choice":
                        lines = before.splitlines()
                        choices = [m.group(1) for m in (re.match(r"^\[\d+\] (.*)$", ln.strip()) for ln in lines) if m]
                        reply = ask({"kind": "choice", "address": address, "choices": choices,
                                     "message": "\n".join(ln for ln in lines if not re.match(r"^\[\d+\] ", ln.strip())).strip()})
                        if reply is None:
                            raise InterruptedError
                        send(str(int(reply.get("choice", 0)) + 1))
                        continue
                    if kind == "Password" and "password" in given:
                        send(given.pop("password"))                # the one typed beside the name, used once
                        continue
                    if kind == "Domain":
                        send(given.pop("domain", ""))              # an empty line takes the server's own default
                        continue
                    default = re.search(r"\[(.*)\]", tail)
                    reply = ask({"kind": "login", "address": address, "needUser": kind == "User", "user": default.group(1) if default else "",
                                 "again": tries > 0})
                    if reply is None:
                        raise InterruptedError
                    tries += 1
                    user, domain = str(reply.get("user", "")), ""
                    if "\\" in user:                               # WORKGROUP\name
                        domain, user = user.split("\\", 1)
                    if kind == "User":
                        given = {"password": str(reply.get("password", "")), "domain": domain}
                        send(user)
                    else:
                        send(str(reply.get("password", "")))
                code = proc.wait(timeout=30)
            except InterruptedError:
                proc.kill()
                return "", "", False
            except (OSError, subprocess.SubprocessError) as err:
                proc.kill()
                return "", f"Couldn't connect: {getattr(err, 'strerror', None) or err}", False
            finally:
                self._net_proc = None
                given.clear()
            out = said.decode("utf-8", "replace").strip()
            if code != 0 and "already mounted" not in out.lower():
                low = out.lower()
                why = "the name or password wasn't accepted." if "denied" in low or "password" in low or "authentication" in low \
                    else "there is no computer at that address." if "resolve" in low or "no route" in low or "refused" in low or "timed out" in low or "not found" in low \
                    else "this kind of address isn't set up on this computer." if "not supported" in low \
                    else (out.splitlines()[-1].split(": ", 1)[-1] if out else "it didn't answer.")
                return "", f"Couldn't connect: {why}", False
            code, info = self._sh(["gio", "info", address], 20)
            where = next((ln.split(":", 1)[1].strip() for ln in info.splitlines() if ln.strip().startswith("local path:")), "")
            self._net_done = (address, where)
            return "", "", False
        self._net_done = None
        self._start(f"Connecting to {address.split('://', 1)[1].split('/')[0]}", work)

    @Slot("QVariantMap")
    def netAnswer(self, reply) -> None:
        self._net_reply = dict(reply)
        self._net_wait.set()

    @Slot()
    def netCancel(self) -> None:
        self._stop = True

    def _net_arrived(self) -> None:
        address, where = self._net_done
        self._net_done = None
        self._servers = ([address] + [a for a in self._servers if a != address])[:6]
        self._keep()
        self.refreshDrives()
        self.drivesChanged.emit()
        if where and Path(where).is_dir():
            self._go(Path(where))
        else:
            self.failed.emit("Connected, but this computer can't show it as a folder (gvfs-fuse isn't running).")

    @Slot(str)
    def forgetServer(self, address: str) -> None:
        self._servers = [a for a in self._servers if a != address]
        self._keep()
        self.drivesChanged.emit()

    @Slot(str, result=str)
    def goTo(self, text: str) -> str:
        """Go to a folder typed in by hand ("~/Music", "/media"). A file's path shows its folder. Returns "" or why not."""
        text = text.strip()
        if text.startswith("file://"):
            text = QUrl(text).toLocalFile()
        if not text:
            return "Type a folder's path."
        if self.tidy_address(text):
            self.connectTo(text)
            return ""
        if "://" in text or text.startswith("\\\\"):
            return "That isn't an address Files knows. Try smb://computer/folder or sftp://server."
        target = Path(os.path.expanduser(text))
        if not target.is_absolute():
            target = self._path / target
        target = Path(os.path.normpath(target))
        if target.is_dir():
            if not os.access(target, os.R_OK | os.X_OK):
                return "You aren't allowed to open that folder."
            self._go(target)
            return ""
        if os.path.lexists(target):
            self._go(target.parent)
            return ""
        return "There is no folder with that path."

    @Slot(str)
    def showIn(self, path: str) -> None:
        """Open the folder a search result or a trashed thing's original lives in."""
        parent = Path(path).parent
        if parent.is_dir():
            self._go(parent)

    @Slot()
    def openTerminal(self) -> None:
        if self._in_trash:
            return
        try:
            subprocess.Popen([sys.executable, str(HERE / "huginn_app.py"), "terminal", str(self._path)], start_new_session=True)
        except OSError as err:
            self.failed.emit(f"Couldn't open Terminal: {err.strerror or err}")

    # ------------------------------------------------------------------ searching through subfolders
    findsInside = Property(bool, lambda self: self._inside, notify=changed)

    @staticmethod
    def _line_with(path: str, want: str) -> str:
        """The first line of a text file that contains `want` ("12: the line"), or ""."""
        try:
            if os.path.getsize(path) > 2 * 1024 * 1024:
                return ""
            with open(path, "rb") as f:
                head = f.read(4096)
                if b"\0" in head:
                    return ""                                      # not text
                data = head + f.read()
        except OSError:
            return ""
        text = data.decode("utf-8", errors="replace")
        at = text.lower().find(want)
        if at < 0:
            return ""
        start, end = text.rfind("\n", 0, at) + 1, text.find("\n", at)
        line = text[start:end if end >= 0 else len(text)].strip()
        if len(line) > 90:
            cut = max(0, at - start - 30)
            line = ("…" if cut else "") + line[cut:cut + 90] + "…"
        return f"{text.count(chr(10), 0, at) + 1}: {line}"

    @staticmethod
    def _snip(text: str, at: int, want: str) -> str:
        start, end = max(0, at - 30), min(len(text), at + len(want) + 50)
        return ("…" if start else "") + " ".join(text[start:end].split()) + ("…" if end < len(text) else "")

    @classmethod
    def _doc_with(cls, path: str, want: str) -> str:
        """Where a PDF or an office file mentions `want` ("page 3: …the words…"), or ""."""
        suffix = os.path.splitext(path)[1].lower()
        try:
            if os.path.getsize(path) > 40 * 1024 * 1024:
                return ""
            if suffix == ".pdf":
                from PySide6.QtPdf import QPdfDocument
                doc = QPdfDocument(None)
                try:
                    if doc.load(path) != QPdfDocument.Error.None_:
                        return ""
                    for page in range(min(doc.pageCount(), 300)):
                        text = doc.getAllText(page).text()
                        at = text.lower().find(want)
                        if at >= 0:
                            return f"page {page + 1}: {cls._snip(text, at, want)}"
                finally:
                    doc.close()
                return ""
            import html
            import zipfile
            with zipfile.ZipFile(path) as z:
                names = z.namelist()
                if suffix in (".odt", ".ods", ".odp"):
                    parts = [("", "content.xml")]
                elif suffix == ".docx":
                    parts = [("", "word/document.xml")]
                elif suffix == ".xlsx":
                    parts = [("", "xl/sharedStrings.xml")]
                else:                                              # .pptx: one part per slide, in order
                    slides = sorted((n for n in names if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)), key=lambda n: int(re.findall(r"\d+", n)[-1]))
                    parts = [(f"slide {i + 1}: ", n) for i, n in enumerate(slides)]
                for label, member in parts:
                    if member not in names or z.getinfo(member).file_size > 30 * 1024 * 1024:
                        continue
                    text = html.unescape(re.sub(r"<[^>]+>", " ", z.read(member).decode("utf-8", "replace")))
                    at = text.lower().find(want)
                    if at >= 0:
                        return label + cls._snip(text, at, want)
        except Exception:                                          # a damaged or locked file is simply not a match
            return ""
        return ""

    @Slot(str, bool)
    def find(self, text: str, inside: bool = False) -> None:
        """Look for names containing `text` in this folder and every folder inside it; with `inside`, also for text
        files that contain it. "" goes back to the folder."""
        text = text.strip()
        self._inside = bool(inside) and bool(text)
        self._find_run += 1
        run = self._find_run
        if self._in_trash or not text:
            if self._find:
                self._find, self._hits, self._finding = "", [], False
                self._watch_here()
                self.changed.emit()
            return
        self._find, self._hits, self._finding, self._notes = text, [], True, {}
        self._watch_here()
        self.changed.emit()
        root, want, hidden, deep = self._path, text.lower(), self._hidden, self._inside
        notes = self._notes

        def look():
            hits, last, seen = [], time.monotonic(), 0
            for folder, dirs, files in os.walk(root):
                if run != self._find_run:
                    return
                if not hidden:
                    dirs[:] = [d for d in dirs if not d.startswith(".")]
                for name in dirs + files:
                    if want in name.lower() and (hidden or not name.startswith(".")):
                        hits.append(Path(folder) / name)
                if deep:
                    for name in files:
                        if run != self._find_run or len(hits) >= FIND_LIMIT:
                            break
                        if name.startswith(".") and not hidden:
                            continue
                        suffix = os.path.splitext(name)[1].lower()
                        if suffix in TEXT_SUFFIXES or suffix in (".csv", ".log", "") or suffix in READ_INSIDE:
                            full = os.path.join(folder, name)
                            line = self._doc_with(full, want) if suffix in READ_INSIDE else self._line_with(full, want)
                            if line:
                                notes[full] = line
                                if want not in name.lower():
                                    hits.append(Path(full))
                if len(hits) >= FIND_LIMIT:
                    break
                if len(hits) != seen and time.monotonic() - last > 0.25:
                    seen, last = len(hits), time.monotonic()
                    self._hits = hits[:]
                    self._found.emit(run)
            if run == self._find_run:
                self._hits = hits[:FIND_LIMIT]
                self._finding = False
                self._found.emit(run)
        self._finder = threading.Thread(target=look, daemon=True)
        self._finder.start()

    def _on_found(self, run: int) -> None:
        if run == self._find_run:
            self.changed.emit()

    foundTooMany = Property(bool, lambda self: bool(self._find) and len(self._hits) >= FIND_LIMIT, notify=changed)

    def wait_find(self) -> None:
        """For tests."""
        if getattr(self, "_finder", None):
            self._finder.join()

    # ------------------------------------------------------------------ opening with another app
    @staticmethod
    def _app_dirs() -> list:
        data = [os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local/share")]
        data += (os.environ.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share").split(":")
        return [Path(d) / "applications" for d in data if d] + [Path("/var/lib/flatpak/exports/share/applications")]

    @staticmethod
    def _read_entry(file: Path) -> dict:
        out, on = {}, False
        try:
            for line in file.read_text(encoding="utf-8", errors="replace").splitlines():
                line = line.strip()
                if line.startswith("["):
                    on = line == "[Desktop Entry]"
                elif on and "=" in line and not line.startswith("#"):
                    key, value = line.split("=", 1)
                    out.setdefault(key.strip(), value.strip())
        except OSError:
            pass
        return out

    def _kinds(self, path: str) -> list:
        """The file's type, then the wider types it also is (a Python file is also plain text)."""
        base = QMimeDatabase()
        kind = base.mimeTypeForFile(path)
        return [kind.name()] + [a for a in kind.allAncestors() if a != "application/octet-stream"]

    @staticmethod
    def _apps_file() -> Path:
        return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "mimeapps.list"

    def _default_for(self, kind: str) -> str:
        for file in [self._apps_file(), Path("/etc/xdg/mimeapps.list")]:
            on = False
            try:
                for line in file.read_text(encoding="utf-8", errors="replace").splitlines():
                    line = line.strip()
                    if line.startswith("["):
                        on = line == "[Default Applications]"
                    elif on and line.startswith(kind + "="):
                        return line.split("=", 1)[1].split(";")[0].strip()
            except OSError:
                pass
        return ""

    @Slot(str, result="QVariantList")
    def appsFor(self, path: str):
        """Apps that say they open this kind of file: [{id, name, usual}], the usual one first."""
        kinds = self._kinds(path)
        usual = next((d for d in (self._default_for(k) for k in kinds) if d), "")
        found = {}
        for folder in self._app_dirs():
            try:
                files = sorted(folder.glob("*.desktop"))
            except OSError:
                continue
            for file in files:
                if file.name in found:
                    continue                                       # an earlier folder (the user's own) wins
                entry = self._read_entry(file)
                if entry.get("Type", "Application") != "Application" or entry.get("NoDisplay") == "true" and file.name != usual \
                        or entry.get("Hidden") == "true" or not entry.get("Exec"):
                    found[file.name] = None
                    continue
                handles = [m for m in entry.get("MimeType", "").split(";") if m]
                rank = next((i for i, k in enumerate(kinds) if k in handles), None)
                found[file.name] = None if rank is None else {"id": file.name, "name": entry.get("Name", file.stem), "usual": file.name == usual,
                                                               "rank": rank, "file": str(file)}
        rows = [r for r in found.values() if r]
        rows.sort(key=lambda r: (not r["usual"], r["rank"], r["name"].lower()))
        return rows

    @Slot(str, str, bool)
    def openWith(self, path: str, app_id: str, always: bool) -> None:
        row = next((r for r in self.appsFor(path) if r["id"] == app_id), None)
        if not row:
            self.failed.emit("That app is no longer installed.")
            return
        entry = self._read_entry(Path(row["file"]))
        try:
            words, used = [], False
            for word in shlex.split(entry["Exec"]):
                if word in ("%f", "%F"):
                    words.append(path)
                    used = True
                elif word in ("%u", "%U"):
                    words.append(QUrl.fromLocalFile(path).toString())
                    used = True
                elif word.startswith("%") and len(word) == 2:
                    continue                                       # %i, %c, %k: nothing Files needs to fill in
                else:
                    words.append(word.replace("%%", "%"))
            if not used:
                words.append(path)
            self._launch(words)
        except (OSError, ValueError, KeyError) as err:
            self.failed.emit(f"Couldn't open it with {row['name']}: {getattr(err, 'strerror', None) or err}")
            return
        if always:
            problem = self._set_default(self._kinds(path)[0], app_id)
            if problem:
                self.failed.emit(problem)
            else:
                self.said.emit(f"{row['name']} now opens files like this.")

    def _launch(self, words: list) -> None:
        subprocess.Popen(words, start_new_session=True, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def _set_default(self, kind: str, app_id: str) -> str:
        """Record the choice in the user's own mimeapps.list, leaving everything else in it alone."""
        file = self._apps_file()
        try:
            lines = file.read_text(encoding="utf-8").splitlines() if file.exists() else []
        except OSError as err:
            return f"Couldn't remember that choice: {err.strerror or err}"
        out, section, done = [], "", False
        for line in lines:
            bare = line.strip()
            if bare.startswith("["):
                if section == "[Default Applications]" and not done:
                    while out and not out[-1].strip():
                        out.pop()
                    out += [f"{kind}={app_id}", ""]
                    done = True
                section = bare
            elif section == "[Default Applications]" and bare.startswith(kind + "="):
                if not done:
                    out.append(f"{kind}={app_id}")
                    done = True
                continue
            out.append(line)
        if not done:
            if section != "[Default Applications]":
                out += ([""] if out and out[-1].strip() else []) + ["[Default Applications]"]
            out.append(f"{kind}={app_id}")
        try:
            file.parent.mkdir(parents=True, exist_ok=True)
            part = file.parent / ".mimeapps.list.saving"
            part.write_text("\n".join(out).rstrip("\n") + "\n", encoding="utf-8")
            os.replace(part, file)
        except OSError as err:
            return f"Couldn't remember that choice: {err.strerror or err}"
        return ""

    # ------------------------------------------------------------------ undo: one step back
    canUndo = Property(bool, lambda self: self._undo is not None, notify=undoChanged)
    undoText = Property(str, lambda self: self._undo[0] if self._undo else "", notify=undoChanged)

    undoNote = Property(str, lambda self: self._undo_note if self._undo else "", notify=undoChanged)   # the line Undo belongs beside

    canRedo = Property(bool, lambda self: self._redo is not None, notify=undoChanged)
    redoText = Property(str, lambda self: self._redo[0] if self._redo else "", notify=undoChanged)

    def _remember(self, text, kind, data, note: str = "", redo=None) -> None:
        self._undo = (text, kind, data) if kind else None
        self._undo_note = note
        self._redo = redo                                         # anything new you do ends what could be redone
        self.undoChanged.emit()

    def _swap_names(self, pairs) -> str:
        """Rename many at once, [(from, to)], by way of spare names so that swapping "1" and "2" works. All or nothing."""
        for src, target in pairs:
            if not os.path.lexists(src):
                return f"“{Path(src).name}” is no longer there."
        taken = {src for src, _t in pairs}
        for _src, target in pairs:
            if os.path.lexists(target) and target not in taken:
                return f"“{Path(target).name}” is already here."
        done = []                                                 # (where it is now, where it was), newest last
        try:
            spares = []
            for i, (src, _target) in enumerate(pairs):
                spare = str(Path(src).parent / f".huginn-renaming-{os.getpid()}-{i}")
                os.rename(src, spare)
                done.append((spare, src))
                spares.append(spare)
            for spare, (_src, target) in zip(spares, pairs):
                os.rename(spare, target)
                done.append((target, spare))
        except OSError as err:
            for now, was in reversed(done):                        # walk it all back, last step first
                try:
                    os.rename(now, was)
                except OSError:
                    pass
            return f"Couldn't rename them: {err.strerror or err}"
        return ""

    @Slot("QVariantList", str, result=str)
    def renameMany(self, paths, base: str) -> str:
        """Give several things one name and a number each, in the order given: "Holiday 1.jpg", "Holiday 2.jpg".
        Each keeps its own ending. Returns "" when done, or why not."""
        base = base.strip()
        if self._in_trash:
            return "Put them back before renaming them."
        if not base:
            return "A name can't be empty."
        if "/" in base or "\0" in base or base in (".", ".."):
            return "A name can't contain a slash."
        pairs = []
        for n, p in enumerate(paths, 1):
            src = Path(str(p))
            ending = "" if src.is_dir() and not src.is_symlink() else src.suffix
            pairs.append((str(src), str(src.parent / f"{base} {n}{ending}")))
        if len({t for _s, t in pairs}) != len(pairs) or any(len(Path(t).name.encode()) > 255 for _s, t in pairs):
            return "Those names would clash or be too long."
        pairs = [(a, b) for a, b in pairs if a != b]
        problem = self._swap_names(pairs)
        if problem:
            return problem
        if self._find:
            new = dict(pairs)
            self._hits = [Path(new.get(str(hit), str(hit))) for hit in self._hits]
        self._remember(f"Undo Rename of {len(pairs)}", "renames", pairs, f"{len(pairs)} items renamed.")
        self.changed.emit()
        self.said.emit(f"{len(pairs)} items renamed.")
        return ""

    @Slot()
    def redo(self) -> None:
        """Do again what Undo just took back."""
        if not self._redo or self._busy:
            return
        _text, kind, data = self._redo
        self._redo = None
        self.undoChanged.emit()
        problem, count = "", 0
        if kind == "rename":
            problem = self.rename(data[0], Path(data[1]).name)
            count = 0 if problem else 1
        elif kind == "renames":
            problem = self._swap_names(data)
            if not problem:
                count = len(data)
                self._remember(f"Undo Rename of {count}", "renames", data)
        elif kind == "trash":
            gone = []
            for origin in data:
                try:
                    move_to_trash(origin)
                    gone.append(origin)
                except OSError as err:
                    problem = problem or f"Couldn't move “{Path(origin).name}” to the Trash: {err.strerror or err}"
            count = len(gone)
            if gone:
                self._remember("Undo Move to Trash", "trash", gone)
        elif kind == "move":
            again = []
            for was, now in data:
                try:
                    if os.path.lexists(now):
                        problem = problem or f"“{Path(now).name}” is taken there now, so it stays."
                    else:
                        shutil.move(was, now)
                        again.append((was, now))
                except OSError as err:
                    problem = problem or f"Couldn't move “{Path(was).name}”: {err.strerror or err}"
            count = len(again)
            if again:
                self._remember("Undo Move", "move", again)
        elif kind == "copy":                                       # the copies are waiting in the Trash
            back = []
            for it in trash_items():
                if it["origin"] in data and not os.path.lexists(it["origin"]):
                    try:
                        os.rename(it["item"], it["origin"])
                        it["note"].unlink(missing_ok=True)
                        back.append(it["origin"])
                        data = [d for d in data if d != it["origin"]]
                    except OSError as err:
                        problem = problem or f"Couldn't bring “{it['name']}” back: {err.strerror or err}"
            count = len(back)
            if back:
                self._remember("Undo Copy", "copy", back)
        elif kind == "made":
            path, is_dir = data
            try:
                if is_dir:
                    os.mkdir(path)
                else:
                    with open(path, "x", encoding="utf-8"):
                        pass
                count = 1
                self._remember("Undo New Folder" if is_dir else "Undo New File", "made", path)
            except OSError as err:
                problem = f"Couldn't make it again: {err.strerror or err}"
        self.changed.emit()
        if problem:
            self.failed.emit(problem)
        elif count:
            self.said.emit("Done again.")

    @Slot()
    def undo(self) -> None:
        """Take back the last rename, move, copy, new folder or move to the Trash."""
        if not self._undo or self._busy:
            return
        _text, kind, data = self._undo
        self._remember("", "", None)
        problem, count, redo = "", 0, None
        if kind == "rename":
            old, new = data
            if os.path.lexists(old):
                problem = f"“{Path(old).name}” is taken again, so the rename stays."
            else:
                try:
                    os.rename(new, old)
                    count = 1
                    redo = ("Redo Rename", "rename", (old, new))
                except OSError as err:
                    problem = f"Couldn't undo the rename: {err.strerror or err}"
        elif kind == "renames":
            problem = self._swap_names([(new, old) for old, new in data])
            if not problem:
                count = len(data)
                redo = (f"Redo Rename of {count}", "renames", data)
        elif kind == "trash":
            back = []
            for it in trash_items():
                if it["origin"] in data and not os.path.lexists(it["origin"]):
                    try:
                        Path(it["origin"]).parent.mkdir(parents=True, exist_ok=True)
                        os.rename(it["item"], it["origin"])
                        it["note"].unlink(missing_ok=True)
                        data.remove(it["origin"])
                        back.append(it["origin"])
                        count += 1
                    except OSError as err:
                        problem = problem or f"Couldn't put “{it['name']}” back: {err.strerror or err}"
            redo = ("Redo Move to Trash", "trash", back) if back else None
        elif kind == "move":
            back = []
            for was, now in data:
                try:
                    if os.path.lexists(was):
                        problem = problem or f"“{Path(was).name}” is taken where it came from, so it stays."
                    else:
                        shutil.move(now, was)
                        back.append((was, now))
                        count += 1
                except OSError as err:
                    problem = problem or f"Couldn't move “{Path(now).name}” back: {err.strerror or err}"
            redo = ("Redo Move", "move", back) if back else None
        elif kind == "copy":                                       # the copies go to the Trash, so even this can be taken back
            binned = []
            for made in data:
                if os.path.lexists(made):
                    try:
                        move_to_trash(made)
                        binned.append(made)
                        count += 1
                    except OSError as err:
                        problem = problem or f"Couldn't remove “{Path(made).name}”: {err.strerror or err}"
            redo = ("Redo Copy", "copy", binned) if binned else None
        elif kind == "made":
            try:
                is_dir = os.path.isdir(data)
                if is_dir:
                    os.rmdir(data)                                 # only if it is still empty
                elif os.path.getsize(data) == 0:
                    os.unlink(data)
                else:
                    raise OSError
                count = 1
                redo = ("Redo New Folder" if is_dir else "Redo New File", "made", (data, is_dir))
            except OSError:
                problem = "It has things in it now, so it stays."
        if redo:
            self._redo = redo
            self.undoChanged.emit()
        self.changed.emit()
        if problem:
            self.failed.emit(problem)
        elif count:
            self.said.emit("Undone.")

    # ------------------------------------------------------------------ making and naming
    @Slot(result=str)
    def newFolder(self) -> str:
        if self._in_trash or self._find:
            return ""
        target = free_name(self._path, "New Folder")
        try:
            target.mkdir()
        except OSError as err:
            self.failed.emit(f"Couldn't create the folder: {err.strerror or err}")
            return ""
        self._remember("Undo New Folder", "made", str(target))
        self.changed.emit()
        return str(target)

    @Slot(result=str)
    def newTextFile(self) -> str:
        if self._in_trash or self._find:
            return ""
        target = free_name(self._path, "New Text File.txt")
        try:
            with open(target, "x", encoding="utf-8"):
                pass
        except OSError as err:
            self.failed.emit(f"Couldn't create the file: {err.strerror or err}")
            return ""
        self._remember("Undo New File", "made", str(target))
        self.changed.emit()
        return str(target)

    @Slot(str, str, result=str)
    def rename(self, path: str, new: str) -> str:
        """Rename in place. Returns "" when done, or why not."""
        src, new = Path(path), new.strip()
        if self._in_trash:
            return "Put it back before renaming it."
        if new == src.name:
            return ""
        if not new:
            return "A name can't be empty."
        if "/" in new or "\0" in new:
            return "A name can't contain a slash."
        if new in (".", ".."):
            return "That name is taken by the system."
        if len(new.encode("utf-8")) > 255:
            return "That name is too long."
        target = src.parent / new
        same_file = os.path.lexists(target) and new.lower() == src.name.lower() and os.path.samefile(src, target)
        if os.path.lexists(target) and not same_file:
            return f"“{new}” is already here."
        try:
            os.rename(src, target)
        except OSError as err:
            return f"Couldn't rename it: {err.strerror or err}"
        if self._find:
            self._hits = [target if h == src else h for h in self._hits]
        self._remember("Undo Rename", "rename", (str(src), str(target)))
        self.changed.emit()
        return ""

    # ------------------------------------------------------------------ copy, cut and paste
    def _board(self):
        return QGuiApplication.clipboard() if QGuiApplication.instance() else None

    def _clip_now(self) -> tuple:
        """What is waiting to be pasted: ([paths], cut?). Files copied in another app count too."""
        board = self._board()
        try:
            data = board.mimeData() if board else None
            if data is not None and data.hasUrls():
                paths = [u.toLocalFile() for u in data.urls() if u.isLocalFile()]
                cut = bytes(data.data("application/x-kde-cutselection")).strip() == b"1" \
                    or bytes(data.data("x-special/gnome-copied-files")).startswith(b"cut")
                return [p for p in paths if os.path.lexists(p)], cut
        except RuntimeError:
            pass
        return [p for p in self._clip if os.path.lexists(p)], self._cut

    def _hold(self, paths, cut: bool) -> None:
        self._clip, self._cut = [str(p) for p in paths if os.path.lexists(str(p))], cut
        board = self._board()
        if board and self._clip:
            data = QMimeData()
            data.setUrls([QUrl.fromLocalFile(p) for p in self._clip])
            listing = "\n".join(QUrl.fromLocalFile(p).toString() for p in self._clip)
            data.setData("x-special/gnome-copied-files", (("cut\n" if cut else "copy\n") + listing).encode())
            data.setData("application/x-kde-cutselection", b"1" if cut else b"0")
            data.setText("\n".join(self._clip))
            board.setMimeData(data)
        self.clipChanged.emit()

    @Slot("QVariantList")
    def copy(self, paths) -> None:
        if not self._in_trash:
            self._hold(paths, False)

    @Slot("QVariantList")
    def cut(self, paths) -> None:
        if not self._in_trash:
            self._hold(paths, True)

    @Slot()
    def forget(self) -> None:
        """Drop what was copied or cut."""
        self._clip, self._cut = [], False
        board = self._board()
        if board and board.mimeData() is not None and board.mimeData().hasUrls():
            board.clear()
        self.clipChanged.emit()

    clipCount = Property(int, lambda self: len(self._clip_now()[0]), notify=clipChanged)
    clipCut = Property(bool, lambda self: self._clip_now()[1], notify=clipChanged)

    @Property("QVariantList", notify=clipChanged)
    def cutPaths(self):
        paths, cut = self._clip_now()
        return paths if cut else []

    def _inside_itself(self, sources, dest: Path = None) -> str:
        here = Path(os.path.realpath(dest or self._path))
        for src in sources:
            real = Path(os.path.realpath(src))
            if os.path.isdir(src) and not os.path.islink(src) and (real == here or real in here.parents):
                return f"“{Path(src).name}” can't go inside itself."
        return ""

    @Slot(result="QVariantList")
    def pasteClashes(self):
        """Names already here that a paste would run into (a copy made beside its original doesn't count)."""
        paths, _cut = self._clip_now()
        return [Path(p).name for p in paths if Path(p).parent != self._path and os.path.lexists(self._path / Path(p).name)]

    @Slot(str)
    def paste(self, mode: str) -> None:
        """Paste here. mode decides a name that's already here: "keep" both, "replace", or "skip"."""
        paths, cut = self._clip_now()
        if self._in_trash or self._find or not paths or self._busy:
            return
        problem = self._inside_itself(paths)
        if problem:
            self.failed.emit(problem)
            return
        self._transfer([Path(p) for p in paths], self._path, cut, mode if mode in ("keep", "replace", "skip") else "keep", from_clip=True)

    # dropping: onto a folder, a place, a drive, the Trash, or the open folder (from another app too)
    @staticmethod
    def _as_paths(things) -> list:
        out = []
        for t in things:
            t = str(t.toString() if hasattr(t, "toString") else t)
            t = QUrl(t).toLocalFile() if t.startswith("file:") else t
            if t and os.path.lexists(t):
                out.append(os.path.normpath(t))
        return out

    @Slot("QVariantList", result="QVariantList")
    def urls(self, paths):
        """file:// addresses for dragging things out to other apps."""
        return [QUrl.fromLocalFile(str(p)).toString(QUrl.ComponentFormattingOption.FullyEncoded) for p in paths]

    @Slot("QVariantList", str, result=bool)
    def dropMoves(self, things, dest: str) -> bool:
        """Would a plain drop move (same drive) or copy (another drive)? Holding Ctrl always copies."""
        paths = self._as_paths(things)
        try:
            return dest == TRASH or all(os.lstat(p).st_dev == os.stat(dest).st_dev for p in paths)
        except OSError:
            return False

    @Slot("QVariantList", str, result="QVariantList")
    def dropClashes(self, things, dest: str):
        if dest == TRASH:
            return []
        return [Path(p).name for p in self._as_paths(things) if Path(p).parent != Path(dest) and os.path.lexists(Path(dest) / Path(p).name)]

    @Slot("QVariantList", str, bool, str)
    def drop(self, things, dest: str, copy: bool, mode: str) -> None:
        paths = self._as_paths(things)
        if not paths or self._busy:
            return
        if dest == TRASH:
            self.trash(paths)
            return
        target = Path(dest)
        if not target.is_dir():
            self.failed.emit("That folder no longer exists.")
            return
        if not os.access(target, os.W_OK):
            self.failed.emit(f"You aren't allowed to put things in “{target.name or '/'}”.")
            return
        if not copy and all(Path(p).parent == target for p in paths):
            return                                                 # dropped back where it came from
        problem = self._inside_itself(paths, target)
        if problem:
            self.failed.emit(problem)
            return
        self._transfer([Path(p) for p in paths], target, not copy, mode if mode in ("keep", "replace", "skip") else "keep")

    @Slot("QVariantList", result=bool)
    def anyFolders(self, paths) -> bool:
        return any(os.path.isdir(str(p)) for p in paths)

    @Slot("QVariantList")
    def sendToPhone(self, paths) -> None:
        """Open Phone with these files ready to send to the paired phone."""
        files = [str(p) for p in paths if os.path.isfile(str(p))]
        if files:
            subprocess.Popen([sys.executable, str(HERE / "huginn_app.py"), "phone", json.dumps(files)], start_new_session=True,
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    @Slot(str)
    def translateFile(self, path: str) -> None:
        if os.path.isfile(path):
            subprocess.Popen([sys.executable, str(HERE / "huginn_app.py"), "translate", path], start_new_session=True,
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    @Slot(str)
    def printFile(self, path: str) -> None:
        if os.path.isfile(path):
            subprocess.Popen([sys.executable, str(HERE / "huginn_app.py"), "print", path], start_new_session=True,
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    @Slot("QVariantList")
    def sendByMail(self, paths) -> None:
        """Start a message in Mail with these files attached (Mail shows the list; nothing is sent from here)."""
        send_by_mail(paths)

    @Slot("QVariantList")
    def compress(self, paths) -> None:
        """Pack the selection into one .zip beside it."""
        sources = [Path(str(p)) for p in paths if os.path.lexists(str(p))]
        if not sources or self._busy or self._in_trash:
            return
        folder = sources[0].parent
        target = free_name(folder, (sources[0].stem if len(sources) == 1 and not sources[0].is_dir() else sources[0].name if len(sources) == 1 else "Archive") + ".zip")
        if not os.access(folder, os.W_OK):
            self.failed.emit("You aren't allowed to save here.")
            return

        def work():
            import zipfile
            part = folder / f".{target.name}.huginn-part"
            total = max(1, sum(self._weigh(s) for s in sources))
            done = 0
            try:
                with zipfile.ZipFile(part, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as z:
                    for src in sources:
                        members = [src]
                        if src.is_dir() and not src.is_symlink():
                            members += [Path(r) / n for r, ds, fs in os.walk(src) for n in sorted(ds) + sorted(fs)]
                        for m in members:
                            if self._stop:
                                raise InterruptedError
                            if m.is_symlink() or not (m.is_dir() or m.is_file()):
                                continue                           # links and devices are left out
                            z.write(m, os.path.relpath(m, folder))
                            done += 1 if m.is_dir() else os.lstat(m).st_size + 1
                            self._progress = min(1.0, done / total)
                            self.jobChanged.emit()
                os.replace(part, target)
            except InterruptedError:
                part.unlink(missing_ok=True)
                return "", "", False
            except (OSError, zipfile.LargeZipFile, ValueError) as err:
                part.unlink(missing_ok=True)
                return "", f"Couldn't make the archive: {getattr(err, 'strerror', None) or err}", False
            return f"Made “{target.name}”.", "", False
        self._start("Compressing", work)

    @Slot("QVariantList")
    def duplicate(self, paths) -> None:
        if not self._in_trash and not self._busy and paths:
            self._transfer([Path(str(p)) for p in paths], self._path, False, "keep")

    # the long jobs run off the window's thread, so the app never freezes and Stop always works
    busy = Property(bool, lambda self: self._busy, notify=jobChanged)
    jobText = Property(str, lambda self: self._job_text, notify=jobChanged)
    progress = Property(float, lambda self: self._progress, notify=jobChanged)

    @Slot()
    def stop(self) -> None:
        self._stop = True
        proc = self._net_proc
        if proc:
            try:
                proc.kill()
            except OSError:
                pass

    def _start(self, text: str, work) -> None:
        self._busy, self._job_text, self._progress, self._stop = True, text, 0.0, False
        self.jobChanged.emit()

        def run():
            good, bad, clear = "", "", False
            try:
                good, bad, clear = work()
            except Exception as err:                              # a job must always end, whatever happened
                bad = f"It stopped: {getattr(err, 'strerror', None) or err}"
            self._finished.emit(good, bad, clear)
        self._worker = threading.Thread(target=run, daemon=True)
        self._worker.start()

    def _after_job(self, good: str, bad: str, clear: bool) -> None:
        self._busy, self._job_text = False, ""
        self.jobChanged.emit()
        pending, self._pending_undo = getattr(self, "_pending_undo", None), None
        if pending:
            self._remember(*pending)
        if clear:
            self.forget()
        if getattr(self, "_net_done", None):
            self._net_arrived()
        self.changed.emit()
        if bad:
            self.failed.emit(bad)
        elif good:
            self.said.emit(good)

    def wait(self) -> None:
        """For tests: let the running job finish."""
        if self._worker:
            self._worker.join()

    @staticmethod
    def _weigh(path: Path) -> int:
        try:
            if path.is_symlink() or not path.is_dir():
                return os.lstat(path).st_size + 1
            total = 1
            for root, _dirs, files in os.walk(path):
                for f in files:
                    try:
                        total += os.lstat(os.path.join(root, f)).st_size + 1
                    except OSError:
                        pass
            return total
        except OSError:
            return 1

    def _transfer(self, sources, dest: Path, move: bool, mode: str, from_clip: bool = False) -> None:
        verb = "Moving" if move else "Copying"
        state = {"done": 0, "total": 1, "last": 0.0}
        moved_pairs, copied = [], []

        def tick(n: int) -> None:
            state["done"] += n
            now = time.monotonic()
            if now - state["last"] > 0.1:
                state["last"] = now
                self._progress = min(1.0, state["done"] / state["total"])
                self.jobChanged.emit()

        def copy_file(src: Path, target: Path) -> None:
            if target.is_dir() and not target.is_symlink():
                raise IsADirectoryError(21, "a folder with that name is in the way", str(target))
            part = target.parent / f".{target.name}.huginn-part"
            try:
                with open(src, "rb") as fin, open(part, "wb") as fout:
                    while True:
                        if self._stop:
                            raise InterruptedError
                        block = fin.read(1024 * 1024)
                        if not block:
                            break
                        fout.write(block)
                        tick(len(block))
                shutil.copystat(src, part, follow_symlinks=True)
                os.replace(part, target)
                tick(1)
            except BaseException:
                try:
                    os.unlink(part)
                except OSError:
                    pass
                raise

        def copy_any(src: Path, target: Path) -> None:
            if self._stop:
                raise InterruptedError
            if src.is_symlink():
                if target.is_dir() and not target.is_symlink():
                    raise IsADirectoryError(21, "a folder with that name is in the way", str(target))
                if os.path.lexists(target):
                    _rm(target)
                os.symlink(os.readlink(src), target)
                tick(1)
            elif src.is_dir():
                if os.path.lexists(target) and not target.is_dir():
                    _rm(target)
                target.mkdir(exist_ok=True)
                for child in sorted(os.listdir(src)):
                    copy_any(src / child, target / child)          # an existing folder is merged into, never emptied
                try:
                    shutil.copystat(src, target)
                except OSError:
                    pass
                tick(1)
            elif src.is_file():
                copy_file(src, target)
            else:
                raise OSError(22, "it isn't a file that can be copied", str(src))

        def work():
            state["total"] = max(1, sum(self._weigh(s) for s in sources))
            count, errors, stopped = 0, [], False
            for src in sources:
                target = dest / src.name
                try:
                    if src.parent == dest:
                        if move:
                            continue                               # cut and pasted where it already is
                        target = free_name(dest, src.name, " copy")
                    elif os.path.lexists(target):
                        if mode == "skip":
                            continue
                        if mode == "keep":
                            target = free_name(dest, src.name)
                    if move:
                        moved = False
                        fresh = not os.path.lexists(target)
                        if fresh or (not src.is_dir() and not (target.is_dir() and not target.is_symlink())):
                            try:
                                os.replace(src, target)
                                moved = True
                                tick(self._weigh(target))
                            except OSError:
                                moved = False                      # another drive: copy it over, then remove the original
                        if not moved:
                            copy_any(src, target)
                            _rm(src)
                        if fresh:
                            moved_pairs.append((str(src), str(target)))       # only a move that replaced nothing can be undone
                    else:
                        fresh = not os.path.lexists(target)
                        copy_any(src, target)
                        if fresh:
                            copied.append(str(target))
                    count += 1
                except InterruptedError:
                    stopped = True
                    break
                except OSError as err:
                    errors.append(f"“{src.name}”: {err.strerror or err}")
            word = "moved" if move else "copied"
            good = f"{count} item{'' if count == 1 else 's'} {word}" + (" before you stopped it." if stopped else ".") if count or stopped else ""
            bad = ""
            if errors:
                bad = f"Couldn't {'move' if move else 'copy'} {errors[0]}" + (f", and {len(errors) - 1} more" if len(errors) > 1 else "")
            self._pending_undo = ("Undo Move", "move", moved_pairs, good) if moved_pairs else \
                ("Undo Copy", "copy", copied, good) if copied and not move else None
            return good, bad, from_clip and move and not errors and not stopped
        self._start(f"{verb} {len(sources)} item{'' if len(sources) == 1 else 's'}", work)

    # ------------------------------------------------------------------ the Trash
    @Slot("QVariantList")
    def trash(self, paths) -> None:
        """Move to the Trash (never deletes outright)."""
        if self._in_trash:
            return
        if isinstance(paths, str):
            paths = [paths]
        count, problem, gone = 0, "", []
        for path in paths:
            try:
                move_to_trash(str(path))
                gone.append(os.path.abspath(str(path)))
                count += 1
            except OSError as err:
                problem = problem or f"Couldn't move “{Path(str(path)).name}” to the Trash: {err.strerror or err}"
        if gone:
            self._remember("Undo Move to Trash", "trash", gone, f"{count} item{'' if count == 1 else 's'} moved to the Trash.")
        if self._find:
            self._hits = [h for h in self._hits if str(h) not in gone]
        self.changed.emit()
        if problem:
            self.failed.emit(problem)
        elif count:
            self.said.emit(f"{count} item{'' if count == 1 else 's'} moved to the Trash.")

    def _trashed(self, paths) -> list:
        want = {str(p) for p in paths}
        return [it for it in trash_items() if str(it["item"]) in want]

    @Slot("QVariantList")
    def restore(self, paths) -> None:
        """Put things back where they were deleted from; a name taken since gets "(restored)" added."""
        count, problem = 0, ""
        for it in self._trashed(paths):
            origin = Path(it["origin"]) if it["origin"] else Path.home() / it["name"]
            try:
                origin.parent.mkdir(parents=True, exist_ok=True)
                target = origin if not os.path.lexists(origin) else free_name(origin.parent, origin.name, " (restored)")
                try:
                    os.rename(it["item"], target)
                except OSError:
                    shutil.move(str(it["item"]), str(target))
                it["note"].unlink(missing_ok=True)
                count += 1
            except OSError as err:
                problem = problem or f"Couldn't put “{it['name']}” back: {err.strerror or err}"
        self.changed.emit()
        if problem:
            self.failed.emit(problem)
        elif count:
            self.said.emit(f"{count} item{'' if count == 1 else 's'} put back.")

    def _destroy(self, items, text: str) -> None:
        def work():
            errors, count = [], 0
            for n, it in enumerate(items):
                if self._stop:
                    break
                try:
                    _rm(it["item"])
                    it["note"].unlink(missing_ok=True)
                    count += 1
                except OSError as err:
                    errors.append(f"“{it['name']}”: {err.strerror or err}")
                self._progress = (n + 1) / max(1, len(items))
                self.jobChanged.emit()
            bad = f"Couldn't delete {errors[0]}" + (f", and {len(errors) - 1} more" if len(errors) > 1 else "") if errors else ""
            return (f"{count} item{'' if count == 1 else 's'} deleted for good." if count else ""), bad, False
        if items and not self._busy:
            self._start(text, work)

    @Slot("QVariantList")
    def deleteForever(self, paths) -> None:
        """Only for things already in the Trash."""
        self._destroy(self._trashed(paths), "Deleting")

    @Slot()
    def emptyTrash(self) -> None:
        self._destroy(trash_items(), "Emptying the Trash")

    # ------------------------------------------------------------------ who may open and change a thing
    @Slot(str, result="QVariantMap")
    def access(self, path: str):
        """How one file or folder is shared, in plain terms; `mine` says whether you may change that."""
        try:
            st = os.stat(path)
        except OSError:
            return {}
        import stat as S
        mode, is_dir = st.st_mode, S.S_ISDIR(st.st_mode)
        try:
            import pwd
            owner = pwd.getpwuid(st.st_uid).pw_name
        except (ImportError, KeyError):
            owner = str(st.st_uid)
        return {"mine": st.st_uid == _uid() and not self._in_trash and not os.path.islink(path), "owner": owner, "dir": is_dir,
                "others": "change" if mode & S.S_IWOTH else "open" if mode & S.S_IROTH else "none",
                "locked": not mode & S.S_IWUSR, "run": bool(mode & S.S_IXUSR) and not is_dir}

    @Slot(str, str, bool, bool, result=str)
    def setAccess(self, path: str, others: str, locked: bool, run: bool) -> str:
        """others: "none", "open" or "change" (for everyone else on this computer); locked: nobody, you included, can
        change it; run: it may be started as a program (files only). Returns "" or why not."""
        import stat as S
        try:
            st = os.stat(path)
            if st.st_uid != _uid() or os.path.islink(path):
                return "Only its owner can change this."
            is_dir = S.S_ISDIR(st.st_mode)
            enter = is_dir or run
            mode = S.S_IRUSR | (0 if locked else S.S_IWUSR) | (S.S_IXUSR if enter else 0)
            if others in ("open", "change"):
                mode |= S.S_IRGRP | S.S_IROTH | ((S.S_IXGRP | S.S_IXOTH) if enter else 0)
            if others == "change" and not locked:
                mode |= S.S_IWGRP | S.S_IWOTH
            os.chmod(path, mode)
        except OSError as err:
            return f"Couldn't change it: {err.strerror or err}"
        self.changed.emit()
        return ""

    # ------------------------------------------------------------------ pinned folders
    def _pin_rows(self) -> list:
        return [{"name": self._label(Path(p)), "path": p, "where": self._where(Path(p).parent)} for p in self._pins]

    pins = Property("QVariantList", lambda self: self._pin_rows(), notify=drivesChanged)
    pinned = Property(bool, lambda self: not self._in_trash and str(self._path) in self._pins, notify=changed)

    @Slot(str)
    def togglePin(self, path: str) -> None:
        """Pin a folder ("" for the open one) so it is one click away in Go to a Folder, or unpin it."""
        path = path or str(self._path)
        if path in self._pins:
            self._pins.remove(path)
        elif Path(path).is_dir() and len(self._pins) < 12:
            self._pins.append(path)
            self.said.emit(f"“{self._label(Path(path))}” is pinned. Ctrl+L shows your pins.")
        self._keep()
        self.drivesChanged.emit()
        self.changed.emit()

    # ------------------------------------------------------------------ a quick look (Space)
    @Slot(str, result="QVariantMap")
    def peek(self, path: str):
        """What to show for a quick look: a picture (pictures, videos, PDFs), the start of a text file, or just the facts."""
        p = Path(path)
        shown = next((it["name"] for it in self._trashed([p])), p.name) if self._in_trash else p.name
        suffix = Path(shown).suffix.lower()
        try:
            st = p.stat()
        except OSError:
            return {}
        out = {"name": shown, "kind": "facts", "text": "", "source": "", "facts": human_size(st.st_size) + " · " + self._time(st.st_mtime)}
        if p.is_dir():
            try:
                n = len(os.listdir(p))
                out["facts"] = f"{n} item{'' if n == 1 else 's'} · " + self._time(st.st_mtime)
            except OSError:
                pass
        elif suffix in THUMBED:
            out["kind"] = "picture"
            out["source"] = "image://filethumb/" + quote(str(p), safe="") + f"?{st.st_mtime_ns}&big"
        elif suffix in TEXT_SUFFIXES or suffix in (".csv", ".log", "") and st.st_size < TEXT_LIMIT:
            try:
                with open(p, "rb") as f:
                    data = f.read(24000)
                if b"\0" not in data:
                    text = data.decode("utf-8", errors="replace")
                    out["kind"] = "text"
                    out["text"] = text + ("\n…" if st.st_size > len(data) else "")
            except OSError:
                pass
        return out

    # ------------------------------------------------------------------ computers nearby that share folders
    nearby = Property("QVariantList", lambda self: list(self._nearby), notify=drivesChanged)
    scanning = Property(bool, lambda self: self._scanning, notify=drivesChanged)
    _scanned = Signal()

    @Slot()
    def scanNetwork(self) -> None:
        """Ask the local network who is sharing (Bonjour/mDNS, the way printers are found). Windows PCs that only
        announce themselves the old way won't show; their address can still be typed."""
        if self._scanning:
            return
        if not shutil.which("avahi-browse"):
            return
        self._scanning = True
        self.drivesChanged.emit()
        kinds = {"_smb._tcp": ("smb", "Shared folders"), "_sftp-ssh._tcp": ("sftp", "Files over SSH"), "_afpovertcp._tcp": ("afp", "Mac sharing"),
                 "_webdav._tcp": ("dav", "WebDAV"), "_webdavs._tcp": ("davs", "WebDAV"), "_nfs._tcp": ("nfs", "NFS"), "_ftp._tcp": ("ftp", "FTP")}

        def look():
            found = {}
            for service, (scheme, label) in kinds.items():
                code, out = self._sh(["avahi-browse", "-rtpk", service], 8)
                for line in out.splitlines() if code == 0 else []:
                    bits = line.split(";")
                    if len(bits) < 9 or bits[0] != "=":
                        continue
                    name = re.sub(r"\\(\d{3})", lambda m: chr(int(m.group(1))), bits[3])
                    host, port = bits[6], bits[8]
                    usual = {"smb": "445", "sftp": "22", "afp": "548", "dav": "80", "davs": "443", "nfs": "2049", "ftp": "21"}[scheme]
                    address = f"{scheme}://{host}" + ("" if port == usual else f":{port}") + "/"
                    found.setdefault(address, {"name": name, "address": address, "kind": label, "share": scheme == "smb"})
            self._nearby = sorted(found.values(), key=lambda r: (r["name"].lower(), r["kind"]))
            self._scanning = False
            self._scanned.emit()
        self._scanner = threading.Thread(target=look, daemon=True)
        self._scanner.start()

    # ------------------------------------------------------------------ details
    @Slot("QVariantList", result="QVariantMap")
    def details(self, paths):
        """What the Details sheet shows for one thing or several."""
        paths = [Path(str(p)) for p in paths] or ([] if self._in_trash else [self._path])
        if not paths:
            return {}
        files = folders = total = 0
        capped, deadline = False, time.monotonic() + 0.6
        for p in paths:
            try:
                if p.is_dir() and not p.is_symlink():
                    folders += 1
                    for root, dirs, names in os.walk(p):
                        files += len(names)
                        folders += len(dirs)
                        for n in names:
                            try:
                                total += os.lstat(os.path.join(root, n)).st_size
                            except OSError:
                                pass
                        if time.monotonic() > deadline:
                            capped = True
                            break
                else:
                    files += 1
                    total += os.lstat(p).st_size
            except OSError:
                pass
        size = ("more than " if capped else "") + human_size(total)
        one = paths[0]
        if len(paths) > 1:
            return {"title": f"{len(paths)} items", "icon": "file", "rows": [["Size", size], ["Contains", self._contains(files, folders)], ["Where", self._where(one.parent)]]}
        trashed = self._trashed([one]) if self._in_trash else []
        shown = trashed[0]["name"] if trashed else ("Home" if one == Path.home() else one.name or "/")
        is_dir = one.is_dir() and not one.is_symlink()
        kind = "folder" if is_dir else file_kind(Path(shown))
        suffix = Path(shown).suffix[1:].upper()
        rows = [["Kind", "Link to " + os.readlink(one) if one.is_symlink() else KIND_NAMES[kind] + (f" ({suffix})" if suffix and not is_dir else "")],
                ["Size", size]]
        if is_dir:
            rows.append(["Contains", ("more than " if capped else "") + self._contains(files, folders - 1)])
        if trashed:
            rows += [["Deleted from", self._where(Path(trashed[0]["origin"]).parent) if trashed[0]["origin"] else "Unknown"], ["Deleted", self._time(trashed[0]["when"])]]
        else:
            rows.append(["Where", self._where(one.parent)])
            try:
                st = one.lstat()
                rows.append(["Changed", self._time(st.st_mtime)])
                can_read, can_write = os.access(one, os.R_OK), os.access(one, os.W_OK)
                rows.append(["You can", "Open and change it" if can_read and can_write else "Open it, not change it" if can_read else "Not open it"])
            except OSError:
                pass
            if is_dir and os.path.ismount(one) or one == self._path:
                try:
                    use = shutil.disk_usage(one)
                    rows.append(["Free space", f"{human_size(use.free)} of {human_size(use.total)}"])
                except OSError:
                    pass
        return {"title": shown, "icon": kind, "rows": rows}

    @staticmethod
    def _contains(files: int, folders: int) -> str:
        bits = ([f"{files} file{'' if files == 1 else 's'}"] if files else []) + ([f"{folders} folder{'' if folders == 1 else 's'}"] if folders else [])
        return ", ".join(bits) or "Nothing"

    @staticmethod
    def _where(folder: Path) -> str:
        home, text = str(Path.home()), str(folder)
        return "Home" + text[len(home):] if text == home or text.startswith(home + "/") else text

    @staticmethod
    def _time(stamp: float) -> str:
        return dt.datetime.fromtimestamp(stamp).strftime("%b %-d, %Y at %H:%M" if os.name != "nt" else "%b %d, %Y at %H:%M")

    # ------------------------------------------------------------------ drives you plug in
    def _sh(self, args, timeout: int = 30, feed: str = None) -> tuple:
        try:
            done = subprocess.run(args, capture_output=True, text=True, timeout=timeout, input=feed)
            return done.returncode, (done.stdout or "") + (done.stderr or "")
        except (OSError, subprocess.SubprocessError) as err:
            return 1, str(err)

    def _read_drives(self) -> list:
        code, out = self._sh(["lsblk", "-J", "-p", "-o", "NAME,LABEL,SIZE,MOUNTPOINT,RM,HOTPLUG,FSTYPE,TYPE"], 8)
        rows = []
        try:
            tree = json.loads(out)["blockdevices"] if code == 0 else []
        except (ValueError, KeyError, TypeError):
            tree = []

        def yes(v) -> bool:
            return v in (True, 1, "1", "true")

        def walk(node, removable, lock="", size=""):
            removable = removable or yes(node.get("rm")) or yes(node.get("hotplug"))
            kids = node.get("children") or []
            spot, fs, dev = node.get("mountpoint") or "", node.get("fstype") or "", node.get("name") or ""
            size = node.get("size") or size
            usable = fs and fs not in ("swap", "crypto_LUKS", "LVM2_member", "linux_raid_member", "squashfs")
            system = spot in LIVE_MOUNTS or spot.startswith(("/run/live", "/usr/lib/live", "/boot/", "/snap/", "/var/"))
            if removable and fs == "crypto_LUKS" and not kids:      # locked: needs its password before it can be opened
                rows.append({"dev": dev, "name": node.get("label") or f"{size} Locked Drive".strip(), "path": "", "mounted": False,
                             "locked": True, "lock": "", "net": False})
            elif removable and usable and not system and not kids and node.get("type") in ("part", "disk", "rom", "crypt"):
                rows.append({"dev": dev, "name": node.get("label") or f"{size} Drive".strip(), "path": spot, "mounted": bool(spot),
                             "locked": False, "lock": lock, "net": False})
            for kid in kids:
                walk(kid, removable, dev if fs == "crypto_LUKS" else lock, size)
        for node in tree:
            walk(node, False)
        return rows

    drives = Property("QVariantList", lambda self: self._drives, notify=drivesChanged)

    @Slot()
    def refreshDrives(self) -> None:
        rows = self._read_drives() + self._net_mounts()
        if rows != self._drives:
            pulled = [d["path"] for d in self._drives if d["mounted"] and d["path"] and not Path(d["path"]).is_dir()]
            self._drives = rows
            self.drivesChanged.emit()
            for root in pulled:                                   # a drive was pulled out: no tab stays on it
                self._all_paths_leave(root)

    @Slot(str)
    def openDrive(self, dev: str) -> None:
        drive = next((d for d in self._drives if d["dev"] == dev), None)
        if not drive or drive["locked"]:
            return                                                 # a locked drive is opened with unlock()
        if not drive["mounted"]:
            code, out = self._sh(["udisksctl", "mount", "-b", dev, "--no-user-interaction"])
            self.refreshDrives()
            drive = next((d for d in self._drives if d["dev"] == dev), None)
            if code != 0 or not drive or not drive["mounted"]:
                self.failed.emit("Couldn't open that drive. " + ("It may be damaged or use a format Huginn can't read." if code else ""))
                return
        self._go(Path(drive["path"]))

    @Slot(str, str, result=str)
    def unlock(self, dev: str, phrase: str) -> str:
        """Open a locked (encrypted) drive with its password. The password goes straight to the system's disk service
        and is not kept or written anywhere. Returns "" when the drive is open, or why not."""
        drive = next((d for d in self._drives if d["dev"] == dev and d["locked"]), None)
        if not drive:
            return "That drive is no longer plugged in."
        if not phrase:
            return "Type the drive's password."
        code, out = self._sh(["udisksctl", "unlock", "-b", dev, "--key-file", "/dev/stdin", "--no-user-interaction"], 60, feed=phrase)
        self.refreshDrives()
        inner = next((d for d in self._drives if d["lock"] == dev), None)
        if code != 0 or not inner:
            low = out.lower()
            return "That password didn't open it." if "passphrase" in low or "no key available" in low or "failed to activate" in low \
                else "Couldn't unlock the drive."
        self.openDrive(inner["dev"])
        return ""

    @Slot(str)
    def eject(self, dev: str) -> None:
        drive = next((d for d in self._drives if d["dev"] == dev), None)
        if not drive or not drive["mounted"] or self._busy:
            return
        self._all_paths_leave(drive["path"])
        name = drive["name"]

        def work():
            if drive.get("net"):
                code, out = self._sh(["gio", "mount", "-u", drive["path"]], 60)
                return ("", f"Couldn't disconnect from “{name}”" + (": something on it is still open." if "busy" in out.lower() else "."), False) \
                    if code != 0 else (f"Disconnected from “{name}”.", "", False)
            code, out = self._sh(["udisksctl", "unmount", "-b", dev, "--no-user-interaction"], 120)
            if code != 0:
                busy = "busy" in out.lower()
                return "", f"Couldn't eject “{name}”" + (": something on it is still open." if busy else "."), False
            if drive["lock"]:
                self._sh(["udisksctl", "lock", "-b", drive["lock"], "--no-user-interaction"], 30)
            return f"“{name}” is safe to unplug.", "", False
        self._start(("Disconnecting from" if drive.get("net") else "Ejecting") + f" “{name}”", work)


# -------------------------------------------------------------------------------------------- Calendar
def send_by_mail(paths=(), subject: str = "", body: str = "", event: dict = None) -> None:
    """Start a message in Mail (or hand it to the Mail that's open) with these files attached. Nothing is sent from here."""
    from urllib.parse import quote
    parts = ["attach=" + quote(str(p), safe="") for p in paths if os.path.isfile(str(p))]
    if subject:
        parts.append("subject=" + quote(subject[:200], safe=""))
    if body:
        parts.append("body=" + quote(body[:60_000], safe=""))
    if event:
        parts.append("x-huginn-event=" + quote(json.dumps(event), safe=""))
    subprocess.Popen([sys.executable, str(HERE / "huginn_app.py"), "mail", "mailto:?" + "&".join(parts)], start_new_session=True,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


class Calendar(QObject):
    changed = Signal()

    def __init__(self, demo: bool, target: Path = None):
        super().__init__()
        self._file = DATA_HOME / "calendar.json"
        self._demo = demo
        today = dt.date.today()
        self._year, self._month, self._selected = today.year, today.month, today
        self._events = self._sample(today) if demo else self._load()
        self._gone, self._notice, self._seen = set(), "", self._stamp()
        if not demo:
            self._watch = QTimer(self)                             # another window (or Mail handing over an invitation) may add events
            self._watch.setInterval(4000)
            self._watch.timeout.connect(self._absorb)
            self._watch.start()
            if target is not None and target.suffix.lower() in (".ics", ".ical", ".ifb", ".vcs"):
                self.importFile(str(target))

    def _stamp(self):
        try:
            st = self._file.stat()
            return st.st_mtime_ns, st.st_size
        except OSError:
            return None

    def _reminders(self) -> list:
        """What the Reminders app holds (read again only when its file changes)."""
        if self._demo:
            return []
        file = DATA_HOME / "reminders.json"
        try:
            stamp = file.stat().st_mtime_ns
        except OSError:
            return []
        if getattr(self, "_rem", (None, []))[0] != stamp:
            try:
                items = json.loads(file.read_text(encoding="utf-8")).get("items", [])
                self._rem = (stamp, [r for r in items if isinstance(r, dict) and r.get("id") and isinstance(r.get("title"), str)])
            except (OSError, ValueError, AttributeError):
                self._rem = (stamp, [])
            QTimer.singleShot(0, self.changed.emit)
        return self._rem[1]

    def _absorb(self) -> None:
        """Take in what another window wrote, keeping what this one removed."""
        self._reminders()
        if self._stamp() == self._seen:
            return
        self._seen = self._stamp()
        mine = {e["id"] for e in self._events}
        fresh = [e for e in self._load() if e["id"] not in mine and e["id"] not in self._gone]
        if fresh:
            self._events.extend(fresh)
            self.changed.emit()

    notice = Property(str, lambda self: self._notice, notify=changed)

    @staticmethod
    def read_ics(text: str) -> list:
        """The events in a calendar file, as this app keeps them. Times are shown in this computer's time zone.
        Repeats come across: daily, weekly, monthly, yearly, with end date, count, weekdays, skipped days, "the last
        Friday of the month", "the 15th and the last day", "the fourth Thursday of November". The few patterns beyond
        those (picking the n-th of a set, by week number) come in once, on their first day. A file that cancels
        starts with a {"cancel": True} marker; a changed single day of a series carries "series" and "instead_of"."""
        import hashlib
        lines = []
        for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
            if raw[:1] in (" ", "\t") and lines:
                lines[-1] += raw[1:]                               # a long line folded over
            else:
                lines.append(raw)
        def local_day(stamp: str, params: list) -> str:
            """The day, in this computer's time zone, that a date or a moment in a calendar file falls on."""
            m = re.match(r"(\d{4})(\d\d)(\d\d)(?:T(\d\d)(\d\d)\d*(Z)?)?", stamp.strip())
            if not m:
                return ""
            try:
                if m.group(4) is None:
                    return dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3))).isoformat()
                when = dt.datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4)), int(m.group(5)))
                zone = next((p.split("=", 1)[1].strip('"') for p in params if p.upper().startswith("TZID=")), "")
                if m.group(6):
                    when = when.replace(tzinfo=dt.timezone.utc).astimezone()
                elif zone:
                    try:
                        from zoneinfo import ZoneInfo
                        when = when.replace(tzinfo=ZoneInfo(zone)).astimezone()
                    except Exception:
                        pass
                return when.date().isoformat()
            except ValueError:
                return ""

        out, cur = [], None
        for line in lines:
            head, _, value = line.partition(":")
            name, *params = head.split(";")
            name = name.upper()
            if name == "BEGIN" and value.upper() == "VEVENT":
                cur = {}
            elif name == "METHOD" and cur is None and value.strip().upper() == "CANCEL":
                out.append({"cancel": True})
            elif name == "END" and value.upper() == "VEVENT" and cur is not None:
                if cur.get("date") and cur.get("title"):
                    skipped = cur.pop("skipped", [])
                    if cur.get("repeat") and skipped:
                        cur["repeat"]["skip"] = sorted(set(skipped))
                    key = cur.pop("uid", "") or cur["title"] + cur["date"] + cur["time"]
                    cur["id"] = "ics-" + hashlib.sha1(key.encode("utf-8")).hexdigest()[:20]
                    if cur.get("instead_of"):                      # one day of a series, moved or renamed
                        cur["series"], cur["id"] = cur["id"], cur["id"] + "-" + cur["instead_of"]
                        cur.pop("repeat", None)
                    out.append(cur)
                cur = None
            elif cur is None:
                continue
            elif name == "SUMMARY":
                cur["title"] = re.sub(r"\\([\\;,])", r"\1", value.replace("\\n", " ").replace("\\N", " ")).strip()[:200]
            elif name == "UID":
                cur["uid"] = value.strip()
            elif name == "RRULE":
                parts = dict(p.split("=", 1) for p in value.upper().split(";") if "=" in p)
                freq = parts.get("FREQ", "").lower()
                names = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"]
                by = [re.fullmatch(r"([+-]?\d)?(MO|TU|WE|TH|FR|SA|SU)", d) for d in parts.get("BYDAY", "").split(",") if d]
                known = set(parts) <= {"FREQ", "INTERVAL", "COUNT", "UNTIL", "BYDAY", "BYMONTHDAY", "BYMONTH", "WKST"}
                if freq in Calendar.REPEATS and known and all(by):
                    rule = {"freq": freq, "interval": int(parts["INTERVAL"]) if parts.get("INTERVAL", "").isdigit() else 1}
                    if parts.get("COUNT", "").isdigit():
                        rule["count"] = int(parts["COUNT"])
                    if local_day(parts.get("UNTIL", ""), []):
                        rule["until"] = local_day(parts["UNTIL"], [])
                    ordinal = [m for m in by if m.group(1)]
                    if freq in ("weekly", "daily") and by and not ordinal:
                        rule["days"] = sorted(names.index(m.group(2)) for m in by)
                    elif freq in ("monthly", "yearly") and by:
                        rule["nth"] = [[int(m.group(1)), names.index(m.group(2))] for m in ordinal] or [[n, names.index(m.group(2))] for m in by for n in (1, 2, 3, 4, 5)]
                    if freq == "monthly" and not by and re.fullmatch(r"-?\d+(,-?\d+)*", parts.get("BYMONTHDAY", "")):
                        rule["monthdays"] = [int(d) for d in parts["BYMONTHDAY"].split(",") if -31 <= int(d) <= 31 and int(d)]
                    if freq == "yearly" and re.fullmatch(r"\d+(,\d+)*", parts.get("BYMONTH", "")):
                        rule["months"] = [int(x) for x in parts["BYMONTH"].split(",") if 1 <= int(x) <= 12]
                    odd = (freq in ("weekly", "daily") and ordinal) or (freq == "yearly" and parts.get("BYMONTHDAY")) or (freq != "yearly" and parts.get("BYMONTH")) or (freq != "monthly" and parts.get("BYMONTHDAY"))
                    if not odd:
                        cur["repeat"] = rule
            elif name == "RECURRENCE-ID" and local_day(value, params):
                cur["instead_of"] = local_day(value, params)
            elif name == "EXDATE":
                cur.setdefault("skipped", []).extend(local_day(d, params) for d in value.split(",") if local_day(d, params))
            elif name == "DTSTART":
                zone = next((p.split("=", 1)[1] for p in params if p.upper().startswith("TZID=")), "")
                m = re.fullmatch(r"(\d{4})(\d\d)(\d\d)(?:T(\d\d)(\d\d)(\d\d)?(Z)?)?", value.strip())
                if not m:
                    continue
                try:
                    if m.group(4) is None:
                        cur["date"], cur["time"] = dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3))).isoformat(), ""
                        continue
                    when = dt.datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4)), int(m.group(5)))
                    if m.group(7):
                        when = when.replace(tzinfo=dt.timezone.utc).astimezone()
                    elif zone:
                        try:
                            from zoneinfo import ZoneInfo
                            when = when.replace(tzinfo=ZoneInfo(zone.strip('"'))).astimezone()
                        except Exception:                          # a zone name this computer doesn't know: keep the clock time as written
                            pass
                    cur["date"], cur["time"] = when.date().isoformat(), when.strftime("%H:%M")
                except ValueError:
                    continue
        return out

    @Slot(str)
    def importFile(self, path: str) -> None:
        try:
            raw = Path(path).read_bytes()[:5_000_000]
            found = self.read_ics(raw.decode("utf-8", "replace"))
        except OSError as err:
            self._notice = f"Couldn't read that calendar file: {err.strerror or err}"
            self.changed.emit()
            return
        cancel = bool(found) and found[0].get("cancel") is True
        found = [e for e in found if "id" in e]
        by_id = {e["id"]: e for e in self._events}
        fresh, changed, removed = [], [], []
        for e in found:
            series, day = e.pop("series", None), e.pop("instead_of", None)
            if cancel:
                if day and series in by_id and by_id[series].get("repeat"):          # one day of a series called off
                    rule = by_id[series]["repeat"]
                    rule["skip"] = sorted(set(rule.get("skip") or []) | {day})
                    removed.append(e)
                if e["id"] in by_id:
                    self._events = [x for x in self._events if x["id"] != e["id"]]
                    self._gone.add(e["id"])
                    removed.append(e)
                continue
            if day and series in by_id and by_id[series].get("repeat"):               # that day moves: the series skips it
                rule = by_id[series]["repeat"]
                rule["skip"] = sorted(set(rule.get("skip") or []) | {day})
            old = by_id.get(e["id"])
            if old is None:
                self._events.append(e)
                by_id[e["id"]] = e
                fresh.append(e)
            else:
                kept = (old.get("repeat") or {}).get("skip")
                new = dict(e)
                if kept and new.get("repeat"):
                    new["repeat"]["skip"] = sorted(set(kept) | set(new["repeat"].get("skip") or []))
                if any(old.get(k) != new.get(k) for k in ("title", "date", "time", "repeat")):
                    old.update(title=new["title"], date=new["date"], time=new["time"])
                    old.pop("repeat", None)
                    if new.get("repeat"):
                        old["repeat"] = new["repeat"]
                    changed.append(old)
        if fresh or changed or removed:
            self._save()
        shown = (fresh or changed or [e for e in found if e["id"] in by_id] or found)
        if shown and not cancel:
            first = dt.date.fromisoformat(shown[0]["date"])
            self._selected, self._year, self._month = first, first.year, first.month
        name = lambda rows: f"“{rows[0]['title']}”" if len(rows) == 1 else f"{len(rows)} events"      # noqa: E731
        if cancel:
            self._notice = f"Removed {name(removed)}: the organiser cancelled." if removed else "That cancellation is for something that isn't in your calendar."
        elif not found:
            self._notice = "That file has no events in it."
        elif fresh or changed:
            self._notice = " ".join(x for x in (f"Added {name(fresh)}." if fresh else "", f"Updated {name(changed)} to match." if changed else "") if x)
        else:
            self._notice = f"{name(found)} {'is' if len(found) == 1 else 'are'} already in your calendar."
        self.changed.emit()

    @Slot()
    def clearNotice(self) -> None:
        self._notice = ""
        self.changed.emit()

    @staticmethod
    def _sample(today: dt.date) -> list:
        first = today.replace(day=1)
        rows = [(2, "09:30", "Design review"), (2, "14:00", "Dentist"), (6, "", "Release notes due"),
                (today.day - 1, "10:00", "Build ISO 0.1"), (today.day - 1, "16:30", "Call with Sam"),
                (15, "19:00", "Dinner"), (21, "", "Day off"), (24, "11:00", "Hardware test")]
        return [{"id": str(i), "date": (first + dt.timedelta(days=max(0, d))).isoformat(), "time": t, "title": n}
                for i, (d, t, n) in enumerate(rows)]

    def _load(self) -> list:
        try:
            data = json.loads(self._file.read_text(encoding="utf-8"))
            return [e for e in data if isinstance(e, dict) and {"id", "date", "title"} <= e.keys()]
        except (OSError, ValueError):
            return []

    def _save(self) -> None:
        if self._demo:
            return
        try:
            self._file.parent.mkdir(parents=True, exist_ok=True)
            self._seen = None
            self._absorb()                                         # never write over what another window added meanwhile
            part = self._file.with_name(".calendar.json.saving")
            part.write_text(json.dumps(self._events, indent=1), encoding="utf-8")
            os.replace(part, self._file)
            self._seen = self._stamp()
        except OSError as err:
            print(f"Could not save the calendar: {err}", file=sys.stderr)

    REPEATS = {"daily": "every day", "weekly": "every week", "monthly": "every month", "yearly": "every year"}

    _counted = {}                                                  # for "N times" rules: the days they land on, worked out once

    @staticmethod
    def _hits(start: dt.date, rule: dict, day: dt.date) -> bool:
        """Would the pattern land on this day, leaving aside its end, its count and skipped days?"""
        every, freq = max(1, int(rule.get("interval") or 1)), rule["freq"]
        days = sorted(set(d for d in (rule.get("days") or []) if 0 <= d <= 6))
        last = cal.monthrange(day.year, day.month)[1]
        nth_ok = any(day.weekday() == wd and ((day.day - 1) // 7 + 1 == n if n > 0 else (last - day.day) // 7 + 1 == -n) for n, wd in (rule.get("nth") or []))
        if freq == "daily":
            return (day - start).days % every == 0 and (not days or day.weekday() in days)
        if freq == "weekly":
            weeks = ((day - dt.timedelta(days=day.weekday())) - (start - dt.timedelta(days=start.weekday()))).days // 7
            return weeks % every == 0 and day.weekday() in (days or [start.weekday()])
        if freq == "monthly":
            if ((day.year - start.year) * 12 + day.month - start.month) % every:
                return False
            if rule.get("nth"):
                return nth_ok
            if rule.get("monthdays"):
                return any(day.day == (d if d > 0 else last + 1 + d) for d in rule["monthdays"])
            return day.day == start.day                            # a 31st skips the short months
        if (day.year - start.year) % every or day.month not in (rule.get("months") or [start.month]):
            return False
        return nth_ok if rule.get("nth") else day.day == start.day

    @staticmethod
    def _falls_on(e: dict, day: dt.date) -> bool:
        """Does this event happen on this day? Covers events that repeat."""
        rule = e.get("repeat")
        iso = day.isoformat()
        if not rule or rule.get("freq") not in Calendar.REPEATS:
            return e["date"] == iso
        if iso < e["date"] or iso in (rule.get("skip") or ()) or (rule.get("until") and iso > rule["until"]):
            return False
        start = dt.date.fromisoformat(e["date"])
        if not Calendar._hits(start, rule, day):
            return False
        if rule.get("count"):
            key = json.dumps([e["date"], {k: v for k, v in rule.items() if k != "skip"}], sort_keys=True)
            landed = Calendar._counted.get(key)
            if landed is None:
                landed, at, want = set(), start, min(int(rule["count"]), 3000)
                for _ in range(366 * 60):                          # look at most sixty years ahead
                    if len(landed) >= want:
                        break
                    if Calendar._hits(start, rule, at):
                        landed.add(at.isoformat())
                    at += dt.timedelta(days=1)
                if len(Calendar._counted) > 400:
                    Calendar._counted.clear()
                Calendar._counted[key] = landed
            return iso in landed
        return True

    @staticmethod
    def repeat_words(rule: dict) -> str:
        if not rule or rule.get("freq") not in Calendar.REPEATS:
            return ""
        every, freq = max(1, int(rule.get("interval") or 1)), rule["freq"]
        if freq == "daily" and sorted(rule.get("days") or []) == [0, 1, 2, 3, 4] and every == 1:
            return "every weekday"
        unit = {"daily": "day", "weekly": "week", "monthly": "month", "yearly": "year"}[freq]
        words = f"every {unit}" if every == 1 else f"every other {unit}" if every == 2 else f"every {every} {unit}s"
        if rule.get("nth"):
            place = {1: "first", 2: "second", 3: "third", 4: "fourth", 5: "fifth", -1: "last", -2: "second-to-last"}
            words += ", on the " + " and ".join(f"{place.get(n, str(n))} {cal.day_name[wd]}" for n, wd in rule["nth"][:3])
        elif rule.get("monthdays") == [-1]:
            words += ", on its last day"
        elif freq in ("weekly", "daily") and len(rule.get("days") or []) > 1:
            words += ", " + " ".join(cal.day_abbr[d] for d in sorted(rule["days"]))
        return words

    def _on(self, day: dt.date) -> list:
        iso = day.isoformat()
        rows = [dict(e, date=iso, repeats=self.repeat_words(e.get("repeat"))) for e in self._events if self._falls_on(e, day)]
        rows += [{"id": "rem-" + r["id"], "date": iso, "time": r.get("time", ""), "title": r["title"], "repeats": "a reminder", "reminder": True}
                 for r in self._reminders() if r.get("due") == iso and not r.get("done")]
        return sorted(rows, key=lambda e: e.get("time") or "")

    title = Property(str, lambda self: f"{cal.month_name[self._month]} {self._year}", notify=changed)
    selected = Property(str, lambda self: self._selected.isoformat(), notify=changed)
    selectedLabel = Property(str, lambda self: self._selected.strftime("%A, %B ") + str(self._selected.day), notify=changed)
    weekdays = Property("QVariantList", lambda self: [cal.day_abbr[i] for i in range(7)], constant=True)

    @Property("QVariantList", notify=changed)
    def days(self):
        today, out = dt.date.today(), []
        for day in cal.Calendar(firstweekday=0).itermonthdates(self._year, self._month):
            out.append({"date": day.isoformat(), "day": day.day, "inMonth": day.month == self._month,
                        "today": day == today, "selected": day == self._selected, "events": self._on(day)})
        return out

    @Property("QVariantList", notify=changed)
    def agenda(self):
        return self._on(self._selected)

    @Property("QVariantList", notify=changed)
    def upcoming(self):
        rows, day = [], dt.date.today()
        last = max([day.isoformat()] + [e["date"] for e in self._events])
        for _ in range(400):                                       # the next six things, looking up to about a year ahead
            if len(rows) >= 6 or (day.isoformat() > last and not any(e.get("repeat") for e in self._events)):
                break
            rows.extend(self._on(day))
            day += dt.timedelta(days=1)
        rows = rows[:6]
        return [dict(e, when=dt.date.fromisoformat(e["date"]).strftime("%a %b ") + str(dt.date.fromisoformat(e["date"]).day)) for e in rows]

    # ---- the week that holds the selected day
    def _week_start(self) -> dt.date:
        return self._selected - dt.timedelta(days=self._selected.weekday())

    @Property(str, notify=changed)
    def weekTitle(self):
        a = self._week_start()
        b = a + dt.timedelta(days=6)
        left = f"{cal.month_abbr[a.month]} {a.day}" + (f", {a.year}" if a.year != b.year else "")
        right = (f"{cal.month_abbr[b.month]} " if b.month != a.month else "") + f"{b.day}, {b.year}"
        return f"{left} – {right}"

    def _span(self) -> tuple[int, int]:
        """First and last hour the week view shows: 7 to 21, wider when an event falls outside."""
        first, last = 7, 21
        start = self._week_start()
        for i in range(7):
            for e in self._on(start + dt.timedelta(days=i)):
                if e.get("time"):
                    hour = int(e["time"][:2])
                    first, last = min(first, hour), max(last, min(24, hour + 1))
        return first, last

    @Property("QVariantList", notify=changed)
    def weekHours(self):
        first, last = self._span()
        return [f"{h:02d}:00" for h in range(first, last)]

    @Property("QVariantList", notify=changed)
    def week(self):
        """Seven days. A timed event has `at` and `length` as fractions of the lane (events have no end, so one hour)."""
        today, start = dt.date.today(), self._week_start()
        first, last = self._span()
        total = (last - first) * 60
        out = []
        for i in range(7):
            day = start + dt.timedelta(days=i)
            timed, all_day = [], []
            for e in self._on(day):
                if e.get("time"):
                    minutes = int(e["time"][:2]) * 60 + int(e["time"][3:5]) - first * 60
                    timed.append(dict(e, at=minutes / total, length=min(60, total - minutes) / total))
                else:
                    all_day.append(e)
            for k, e in enumerate(timed):                      # events that overlap share the lane side by side
                clash = [x for x in timed if x["at"] < e["at"] + e["length"] and e["at"] < x["at"] + x["length"]]
                e["cols"], e["col"] = len(clash), clash.index(e)
            out.append({"date": day.isoformat(), "label": cal.day_abbr[day.weekday()], "day": day.day, "today": day == today,
                        "selected": day == self._selected, "timed": timed, "allDay": all_day})
        return out

    @Slot(int)
    def stepWeek(self, weeks: int) -> None:
        self._selected += dt.timedelta(days=7 * weeks)
        self._year, self._month = self._selected.year, self._selected.month
        self.changed.emit()

    @Slot(int)
    def step(self, months: int) -> None:
        m = self._month - 1 + months
        self._year, self._month = self._year + m // 12, m % 12 + 1
        self.changed.emit()

    @Slot()
    def today(self) -> None:
        t = dt.date.today()
        self._year, self._month, self._selected = t.year, t.month, t
        self.changed.emit()

    @Slot(str)
    def select(self, iso: str) -> None:
        self._selected = dt.date.fromisoformat(iso)
        self._year, self._month = self._selected.year, self._selected.month
        self.changed.emit()

    @Slot(str, str)
    def add(self, title: str, time_text: str) -> None:
        self.addRepeating(title, time_text, "")

    @Slot(str)
    def invite(self, event_id: str) -> None:
        """Start a message in Mail that carries this event as an invitation; you add the people there."""
        e = next((x for x in self._events if x["id"] == event_id), None)
        if e is None:
            return
        if not e["id"].startswith("ics-"):
            when = dt.date.fromisoformat(e["date"]).strftime("%A %-d %B %Y") + (f" at {e['time']}" if e.get("time") else "")
            send_by_mail([], "Invitation: " + e["title"], f"You're invited to “{e['title']}” on {when}." + (f" It repeats {self.repeat_words(e.get('repeat'))}." if e.get("repeat") else ""),
                         {"uid": e["id"] + "@huginn", "title": e["title"], "date": e["date"], "time": e.get("time", ""), "repeat": e.get("repeat") or {}})
        else:
            self._notice = "That event came from someone else's invitation, so it's theirs to send out."
            self.changed.emit()

    @Slot(str, str)
    def skip(self, event_id: str, iso: str) -> None:
        """Take one day out of an event that repeats."""
        for e in self._events:
            if e["id"] == event_id and e.get("repeat"):
                e["repeat"]["skip"] = sorted(set(e["repeat"].get("skip") or []) | {iso})
        self._save()
        self.changed.emit()

    @Slot(str, str, str)
    def addRepeating(self, title: str, time_text: str, freq: str) -> None:
        title, time_text = title.strip(), time_text.strip()
        if not title:
            return
        try:
            time_text = dt.datetime.strptime(time_text, "%H:%M").strftime("%H:%M") if time_text else ""
        except ValueError:
            time_text = ""
        event = {"id": uuid.uuid4().hex, "date": self._selected.isoformat(), "time": time_text, "title": title}
        if freq == "weekdays":
            event["repeat"] = {"freq": "daily", "interval": 1, "days": [0, 1, 2, 3, 4]}
        elif freq in self.REPEATS:
            event["repeat"] = {"freq": freq, "interval": 1}
        self._events.append(event)
        self._save()
        self.changed.emit()

    @Slot(str)
    def remove(self, event_id: str) -> None:
        self._events = [e for e in self._events if e["id"] != event_id]
        self._gone.add(event_id)
        self._save()
        self.changed.emit()


# ------------------------------------------------------------------------------------------------ Mail
# ----------------------------------------------------------------------------------------------- Notes
NOTE_MARK = __import__("re").compile(r"^(\s*)(#{1,2} |- \[([ xX])\] |[-*] )")


class NoteStyler(QSyntaxHighlighter):
    """Shows a note's simple marks as you type, without changing the file: the first line and lines that start with
    "# " are headings, "- [ ] " is something to tick off ("- [x] " is done), "- " is a list."""

    def __init__(self, document, accent: str, dim: str):
        super().__init__(document)
        self.accent, self.dim = QColor(accent), QColor(dim)

    def highlightBlock(self, text: str) -> None:
        found = NOTE_MARK.match(text)
        mark = found.group(2) if found else ""
        start = len(found.group(1)) if found else 0
        size = 0
        if mark.startswith("#") or self.currentBlock().blockNumber() == 0:
            size = 17 if mark == "## " else 22
            head = QTextCharFormat()
            head.setFontPixelSize(size) if hasattr(head, "setFontPixelSize") else head.setFontPointSize(size * 0.75)
            head.setFontWeight(QFont.Weight.DemiBold)
            self.setFormat(0, len(text), head)
        if not mark:
            return
        sign = QTextCharFormat()
        sign.setForeground(self.dim if mark.startswith("#") else self.accent)
        if size:
            sign.setFontPointSize(size * 0.75)
        if "[" in mark:
            sign.setFontFamilies(["JetBrains Mono", "monospace"])
            sign.setFontWeight(QFont.Weight.Bold)
        self.setFormat(start, len(mark), sign)
        if found.group(3) in ("x", "X"):                 # done: struck through and quiet
            done = QTextCharFormat()
            done.setForeground(self.dim)
            done.setFontStrikeOut(True)
            self.setFormat(start + len(mark), len(text) - start - len(mark), done)


class Notes(QObject):
    """Plain-text and Markdown notes, one file each, in Documents/Notes. Saves by itself as you type."""
    changed = Signal()
    textLoaded = Signal()
    failed = Signal(str)

    def __init__(self, target: Path = None):
        super().__init__()
        docs = QStandardPaths.writableLocation(QStandardPaths.DocumentsLocation) or str(Path.home() / "Documents")
        self._folder = Path(docs) / "Notes"
        self._path, self._text, self._dirty, self._extra = None, "", False, None
        self._saver = QTimer(self)
        self._saver.setSingleShot(True)
        self._saver.setInterval(700)
        self._saver.timeout.connect(self.save)
        if target and target.is_file():
            self._extra = target                       # a file opened from elsewhere (Files, the command line)
            self.open(str(target))
        else:
            first = self._files()
            if first:
                self.open(str(first[0]))

    def _files(self) -> list:
        rows = [p for p in self._folder.glob("*") if p.suffix.lower() in (".md", ".txt") and p.is_file()] if self._folder.is_dir() else []
        if self._extra and self._extra not in rows:
            rows.append(self._extra)
        return sorted(rows, key=lambda p: p.stat().st_mtime, reverse=True)

    @Slot(str, result=str)
    def remind(self, line: str) -> str:
        """Turn a line of the note into a reminder (it understands "tomorrow 9am" in the line). Returns what to say."""
        import huginn_reminders
        text = NOTE_MARK.sub("", line).strip() or (self._path.stem if self._path else "")
        if not text:
            return "Put the cursor on a line with some words first."
        title, due, at = huginn_reminders.parse_when(text)
        huginn_reminders.add_reminder(title or text, due, at, f"From the note “{self._path.stem}”." if self._path else "")
        return "Added to Reminders" + (f" for {huginn_reminders.when_words(due, at)}." if due else ".")

    @Slot()
    def sendByMail(self) -> None:
        """The note as the words of a message; its first line becomes the subject."""
        lines = self._text.strip().splitlines()
        title = NOTE_MARK.sub("", lines[0]).strip() if lines else ""
        send_by_mail([], title or (self._path.stem if self._path else "Note"), self._text.strip())

    @staticmethod
    def _title(text: str, fallback: str) -> str:
        for line in text.splitlines():
            line = line.strip().lstrip("#").strip()
            if line:
                return line[:80]
        return fallback

    @Property("QVariantList", notify=changed)
    def notes(self):
        out = []
        for p in self._files():
            try:
                text = self._text if p == self._path else p.read_text(encoding="utf-8", errors="replace")[:400]
                stamp = dt.datetime.fromtimestamp(p.stat().st_mtime)
            except OSError:
                continue
            lines = [NOTE_MARK.sub(lambda m: "✓ " if m.group(3) in ("x", "X") else ("○ " if m.group(3) == " " else ""), ln.strip()) for ln in text.splitlines() if ln.strip()]
            when = stamp.strftime("%H:%M") if stamp.date() == dt.date.today() else stamp.strftime("%b ") + str(stamp.day)
            out.append({"path": str(p), "title": self._title(text, p.stem), "preview": lines[1][:90] if len(lines) > 1 else "No more text", "when": when})
        return out

    current = Property(str, lambda self: str(self._path) if self._path else "", notify=changed)
    text = Property(str, lambda self: self._text, notify=textLoaded)
    fileName = Property(str, lambda self: self._path.name if self._path else "", notify=changed)
    saved = Property(bool, lambda self: not self._dirty, notify=changed)
    words = Property(int, lambda self: sum(len(NOTE_MARK.sub("", ln).split()) for ln in self._text.splitlines()), notify=changed)

    @Property(str, notify=changed)
    def checks(self):
        """'2 of 3 done' when the note has things to tick off, otherwise nothing."""
        boxes = [m.group(3) for m in (NOTE_MARK.match(ln) for ln in self._text.splitlines()) if m and m.group(3)]
        return f"{sum(b != ' ' for b in boxes)} of {len(boxes)} done" if boxes else ""

    @Slot(QObject, str, str)
    def style(self, quick_document, accent: str, dim: str) -> None:
        """Called by the editor: draw this note's marks in the theme's colours."""
        old = getattr(self, "_styler", None)
        if old is not None:
            old.setDocument(None)
        self._styler = NoteStyler(quick_document.textDocument(), accent, dim)

    @Slot(str)
    def open(self, path: str) -> None:
        self.save()
        try:
            self._text = Path(path).read_text(encoding="utf-8", errors="replace")
        except OSError as err:
            self.failed.emit(f"Couldn't open that note: {err.strerror or err}")
            return
        self._path, self._dirty = Path(path), False
        self.textLoaded.emit()
        self.changed.emit()

    @Slot(str)
    def edit(self, text: str) -> None:
        if text == self._text or self._path is None:
            return
        self._text, self._dirty = text, True
        self._saver.start()
        self.changed.emit()

    @Slot()
    def save(self) -> None:
        if not self._dirty or self._path is None:
            return
        try:
            tmp = self._path.with_name(self._path.name + ".saving")
            tmp.write_text(self._text, encoding="utf-8")
            os.replace(tmp, self._path)                 # never leaves a half-written note behind
            self._dirty = False
        except OSError as err:
            self.failed.emit(f"Couldn't save: {err.strerror or err}")
        self.changed.emit()

    @Slot()
    def create(self) -> None:
        self.save()
        try:
            self._folder.mkdir(parents=True, exist_ok=True)
            n, path = 1, self._folder / "Untitled.md"
            while path.exists():
                n += 1
                path = self._folder / f"Untitled {n}.md"
            path.write_text("", encoding="utf-8")
        except OSError as err:
            self.failed.emit(f"Couldn't create a note: {err.strerror or err}")
            return
        self.open(str(path))

    @Slot(str)
    def trash(self, path: str) -> None:
        if self._path and str(self._path) == path:
            self._saver.stop()
            self._path, self._text, self._dirty = None, "", False
        try:
            move_to_trash(path)
        except (OSError, subprocess.SubprocessError) as err:
            self.failed.emit(f"Couldn't move the note to the trash: {err}")
        if self._extra and str(self._extra) == path:
            self._extra = None
        rest = self._files()
        if self._path is None and rest:
            self.open(str(rest[0]))
        self.textLoaded.emit()
        self.changed.emit()


# ---------------------------------------------------------------------------------------------- Photos
class Photos(QObject):
    """Pictures from the Pictures folder, newest first, with rotate and move-to-trash."""
    changed = Signal()
    failed = Signal(str)

    def __init__(self, target: Path = None):
        super().__init__()
        pics = QStandardPaths.writableLocation(QStandardPaths.PicturesLocation) or str(Path.home() / "Pictures")
        self._folder = target.parent if target and target.is_file() else (target if target and target.is_dir() else Path(pics))
        self._first, self._stamp = str(target) if target and target.is_file() else "", 0
        self._file = DATA_HOME / "photos.json"            # which pictures are favourites, and the edits made to pictures
        try:
            self._favs = set(json.loads(self._file.read_text(encoding="utf-8")).get("favourites", []))
        except (OSError, ValueError, AttributeError):
            self._favs = set()
        self._edits, self._session, self._version, self._saving = {}, None, 0, False
        self._call.connect(lambda fn: fn())
        try:
            import huginn_photoedit
            self._pe = huginn_photoedit
            self._edits = huginn_photoedit.load_edits(self._file)
        except ImportError:                                # numpy or Pillow missing: Photos still shows pictures
            self._pe = None
        self._items = self._scan()

    def _scan(self) -> list:
        rows = []
        if self._folder.is_dir():
            for root, dirs, files in os.walk(self._folder):
                dirs[:] = [d for d in dirs if not d.startswith(".")]
                for name in files:
                    p = Path(root, name)
                    if p.suffix.lower() in IMAGES:
                        try:
                            rows.append((p.stat().st_mtime, p))
                        except OSError:
                            pass
                if len(rows) > 4000:
                    break
        rows.sort(reverse=True)
        return [{"path": str(p), "url": QUrl.fromLocalFile(str(p)).toString(), "name": p.name, "fav": str(p) in self._favs, "edited": str(p) in getattr(self, "_edits", {}),
                 "album": self._album(p), "day": dt.datetime.fromtimestamp(m).strftime("%B %Y")} for m, p in rows]

    def _album(self, picture: Path) -> str:
        """An album is a folder inside Pictures: the first folder on the way to the picture ('' when it is loose)."""
        try:
            parts = picture.parent.relative_to(self._folder).parts
        except ValueError:
            return ""
        return parts[0] if parts else ""

    @Slot(str)
    def sendByMail(self, path: str) -> None:
        send_by_mail([path])

    @Property("QVariantList", notify=changed)
    def albums(self):
        """Each album once: its name, how many pictures, and its newest picture as the cover."""
        seen = {}
        for it in self._items:
            if it["album"]:
                entry = seen.setdefault(it["album"], {"name": it["album"], "count": 0, "cover": it["path"]})
                entry["count"] += 1
        return sorted(seen.values(), key=lambda a: a["name"].lower())

    favourites = Property(int, lambda self: sum(1 for it in self._items if it["fav"]), notify=changed)

    @Slot(str)
    def toggleFavourite(self, path: str) -> None:
        self._favs.symmetric_difference_update({path})
        self._items = [dict(it, fav=it["path"] in self._favs) for it in self._items]
        self._keep()
        self.changed.emit()

    def _keep(self) -> None:
        try:
            self._file.parent.mkdir(parents=True, exist_ok=True)
            self._file.write_text(json.dumps({"favourites": sorted(self._favs), "edits": self._edits}, indent=1), encoding="utf-8")
        except OSError as err:
            self.failed.emit(f"Couldn't save your favourites: {err.strerror or err}")

    items = Property("QVariantList", lambda self: self._items, notify=changed)
    folder = Property(str, lambda self: str(self._folder), constant=True)
    stamp = Property(int, lambda self: self._stamp, notify=changed)      # bumps when a file changes, to refresh pictures
    first = Property(int, lambda self: next((i for i, it in enumerate(self._items) if it["path"] == self._first), -1), constant=True)

    @Slot(str, result="QVariantList")
    def info(self, path: str) -> list:
        from PySide6.QtGui import QImageReader
        try:
            st = Path(path).stat()
        except OSError:
            return []
        size = QImageReader(path).size()
        return [{"name": "Name", "value": Path(path).name}, {"name": "Size", "value": f"{size.width()} × {size.height()}" if size.isValid() else ""},
                {"name": "File size", "value": human_size(st.st_size)}, {"name": "Changed", "value": dt.datetime.fromtimestamp(st.st_mtime).strftime("%b %d, %Y %H:%M")},
                {"name": "Folder", "value": str(Path(path).parent)}]

    @Slot(str, int)
    def rotate(self, path: str, degrees: int) -> None:
        """Turn the picture and save it in place (PNG, JPEG, WebP and BMP)."""
        from PySide6.QtGui import QImage, QTransform
        if Path(path).suffix.lower() not in (".png", ".jpg", ".jpeg", ".webp", ".bmp"):
            self.failed.emit("This kind of picture can't be rotated yet.")
            return
        image = QImage(path)
        if image.isNull() or not image.transformed(QTransform().rotate(degrees)).save(path, quality=95):
            self.failed.emit("The picture couldn't be saved after rotating.")
            return
        self._stamp += 1
        self.changed.emit()

    # ------------------------------------------------------------------ editing (huginn_photoedit does the work)
    editReady = Signal()
    canEdit = Property(bool, lambda self: self._pe is not None, constant=True)
    editing = Property(bool, lambda self: self._session is not None, notify=editReady)
    editVersion = Property(int, lambda self: self._version, notify=editReady)
    saving = Property(bool, lambda self: self._saving, notify=editReady)
    edit = Property("QVariantMap", lambda self: dict(self._session.edit) if self._session else {}, notify=editReady)
    canUndo = Property(bool, lambda self: bool(self._session and self._session.history), notify=editReady)
    canRedo = Property(bool, lambda self: bool(self._session and self._session.future), notify=editReady)
    hasOriginal = Property(bool, lambda self: bool(self._session and self._pe.original_of(self._session.path).exists()), notify=editReady)
    shapeAspect = Property(float, lambda self: (lambda w, h: w / h if h else 1.0)(*self._session.shape_size()) if self._session else 1.0, notify=editReady)
    filters = Property("QVariantList", lambda self: [{"id": k, "name": v} for k, v in (self._pe.FILTER_NAMES.items() if self._pe else [])], constant=True)

    @Slot(str)
    def beginEdit(self, path: str) -> None:
        if self._pe is None:
            self.failed.emit("Editing needs numpy and Pillow (python3-numpy, python3-pil).")
            return
        if Path(path).suffix.lower() not in self._pe.EDITABLE:
            self.failed.emit("This kind of picture can't be edited. JPEG, PNG, WebP, TIFF and BMP can.")
            return

        def work():
            try:
                session = self._pe.Session(path, self._edits.get(path))
            except (OSError, ValueError) as err:
                self._back_call(lambda why=str(err): self.failed.emit(f"Couldn't open the picture for editing: {why}"))
                return
            self._back_call(lambda: self._started(session))
        threading.Thread(target=work, daemon=True).start()

    _call = Signal(object)                                 # work finished in another thread comes back through here

    def _back_call(self, fn) -> None:
        self._call.emit(fn)

    def _started(self, session) -> None:
        self._session = session
        self._version += 1
        self.editReady.emit()

    def _touched(self) -> None:
        self._version += 1
        self.editReady.emit()

    @Slot(str, float)
    def setEdit(self, key: str, value: float) -> None:
        if self._session and key in self._pe.SLIDERS:
            self._session.change(**{key: value})
            self._touched()

    @Slot()
    def markEdit(self) -> None:
        """A drag is starting: everything it changes undoes as one step."""
        if self._session:
            self._session.mark()

    @Slot(str, float)
    def dragEdit(self, key: str, value: float) -> None:
        if self._session and key in self._pe.SLIDERS:
            self._session.change(record=False, **{key: value})
            self._touched()

    @Slot(float, float, float, float)
    def dragCrop(self, x: float, y: float, w: float, h: float) -> None:
        if self._session:
            self._session.change(record=False, crop=[x, y, w, h])
            self._touched()

    @Slot(float, float, float, float)
    def setCrop(self, x: float, y: float, w: float, h: float) -> None:
        if self._session:
            self._session.change(crop=[x, y, w, h])
            self._touched()

    @Slot(str)
    def setRatio(self, ratio: str) -> None:
        """Choose a shape for the crop: the biggest frame of that shape, in the middle."""
        if not self._session or ratio not in self._pe.RATIOS:
            return
        want = self._pe.RATIOS[ratio]
        sw, sh = self._session.shape_size()
        aspect = sw / sh if sh else 1.0
        if want < 0:
            want = (self._session.size[0] / self._session.size[1]) if self._session.edit["turns"] % 2 == 0 else (self._session.size[1] / self._session.size[0])
        if want == 0:
            self._session.change(ratio=ratio)
        else:
            w, h = (1.0, aspect / want) if want > aspect else (want / aspect, 1.0)
            self._session.change(ratio=ratio, crop=[(1 - w) / 2, (1 - h) / 2, w, h])
        self._touched()

    @Slot(str)
    def setFilter(self, name: str) -> None:
        if self._session and name in self._pe.FILTERS:
            self._session.change(filter=name, amount=1.0)
            self._touched()

    @Slot()
    def turnEdit(self) -> None:
        if self._session:
            e = self._session.edit
            x, y, w, h = e["crop"]
            self._session.change(turns=(e["turns"] + 1) % 4, crop=[1 - y - h, x, h, w])       # the frame turns with it
            self._touched()

    @Slot()
    def flipEdit(self) -> None:
        if self._session:
            e = self._session.edit
            x, y, w, h = e["crop"]
            self._session.change(flip=not e["flip"], crop=[1 - x - w, y, w, h])
            self._touched()

    @Slot()
    def autoEdit(self) -> None:
        if self._session:
            self._session.change(**self._pe.auto_enhance(self._session.small))
            self._touched()

    @Slot(str)
    def resetEdit(self, part: str) -> None:
        """part: "light", "colour", "detail", "crop", or "all"."""
        if not self._session:
            return
        b = self._pe.blank()
        keys = {"light": ("exposure", "brightness", "contrast", "highlights", "shadows", "blacks"), "colour": ("saturation", "vibrance", "warmth", "tint"),
                "detail": ("sharpen", "vignette", "grain", "fade"), "crop": ("crop", "turns", "flip", "straighten", "ratio")}.get(part, tuple(b))
        self._session.change(**{k: b[k] for k in keys})
        self._touched()

    @Slot()
    def undoEdit(self) -> None:
        if self._session and self._session.undo():
            self._touched()

    @Slot()
    def redoEdit(self) -> None:
        if self._session and self._session.redo():
            self._touched()

    @Slot()
    def cancelEdit(self) -> None:
        self._session = None
        self.editReady.emit()

    @Slot(bool)
    def finishEdit(self, copy: bool) -> None:
        """Done: write the edited picture (over the file, its original kept aside; or as a new copy beside it)."""
        if not self._session or self._saving:
            return
        session, edit = self._session, dict(self._session.edit)
        path = session.path
        target = str(free_name(Path(path).parent, Path(path).name, " edited")) if copy else ""
        self._saving = True
        self.editReady.emit()

        def work():
            try:
                if self._pe.is_blank(edit) and not copy:
                    done = self._pe.revert(path) and path
                else:
                    done = self._pe.save_edit(path, edit, target)
                self._back_call(lambda: self._finished(path, edit, done, copy))
            except (OSError, ValueError) as err:
                self._back_call(lambda why=str(err): self._save_failed(why))
        threading.Thread(target=work, daemon=True).start()

    def _save_failed(self, why: str) -> None:
        self._saving = False
        self.editReady.emit()
        self.failed.emit(f"The picture couldn't be saved: {why}")

    def _finished(self, path: str, edit: dict, written, copy: bool) -> None:
        self._saving = False
        self._session = None
        if not copy:
            if self._pe.is_blank(edit):
                self._edits.pop(path, None)
            else:
                self._edits[path] = edit
        self._keep()
        self._items = self._scan()
        self._stamp += 1
        self.editReady.emit()
        self.changed.emit()
        if copy and written:
            self.failed.emit(f"Saved as “{Path(written).name}”; the original is unchanged.")

    @Slot()
    def revertOriginal(self) -> None:
        """Throw away every edit ever made to the picture being edited, back to the file as it first came."""
        if not self._session:
            return
        path = self._session.path
        try:
            self._pe.revert(path)
        except OSError as err:
            self.failed.emit(f"Couldn't put the original back: {err}")
            return
        self._edits.pop(path, None)
        self._keep()
        self._session = None
        self._items = self._scan()
        self._stamp += 1
        self.editReady.emit()
        self.changed.emit()

    @Slot(str)
    def trash(self, path: str) -> None:
        try:
            move_to_trash(path)
        except (OSError, subprocess.SubprocessError) as err:
            self.failed.emit(f"Couldn't move the picture to the trash: {err}")
            return
        self._items = [it for it in self._items if it["path"] != path]
        if path in self._favs:
            self._favs.discard(path)
            self._keep()
        self.changed.emit()


# ------------------------------------------------------------------------------------------- Documents
# Plain files Documents opens for editing, and what each language's comments, strings and key words look like.
LANGUAGES = {
    "Python": ((".py", ".pyw"), "#", "and as assert async await break class continue def del elif else except finally for from global if import in is lambda nonlocal not or pass raise return try while with yield None True False self"),
    "Shell": ((".sh", ".bash", ".zsh", ".profile", ".bashrc"), "#", "if then else elif fi for while until do done case esac in function return exit export local readonly set unset echo cd source"),
    "JSON": ((".json", ".hsheet", ".hslides"), "", "true false null"),
    "Settings": ((".conf", ".ini", ".cfg", ".toml", ".desktop", ".service", ".list", ".env", ".properties"), "#", "true false yes no on off"),
    "YAML": ((".yml", ".yaml"), "#", "true false null yes no on off"),
    "Markdown": ((".md", ".markdown"), "", ""),
    "JavaScript": ((".js", ".mjs", ".ts", ".qml", ".jsx", ".tsx"), "//", "async await break case catch class const continue default delete do else export extends finally for function if import in instanceof let new of return static super switch this throw try typeof var void while yield true false null undefined property signal readonly required"),
    "C": ((".c", ".h", ".cpp", ".hpp", ".cc", ".rs", ".go", ".java", ".cs"), "//", "auto bool break case char class const continue default do double else enum extern false float for fn func goto if impl import inline int let long match mut namespace new nullptr package private protected pub public return short signed sizeof static struct switch template this true typedef union unsigned use using var virtual void volatile while"),
    "Web": ((".html", ".htm", ".xml", ".svg", ".css"), "", ""),
    "Text": ((".txt", ".text", ".log", ".csv", ".tsv", ".rst", ".tex", ".sql", ".lua", ".rb", ".pl", ".php", ".gitignore", ".diff", ".patch"), "", ""),
}
TEXT_SUFFIXES = {suffix for suffixes, _, _ in LANGUAGES.values() for suffix in suffixes}
TEXT_LIMIT = 4 * 1024 * 1024        # larger than this is not opened for editing


class CodeStyler(QSyntaxHighlighter):
    """Colours comments, quoted text, numbers and a language's key words, one line at a time."""
    WORD = __import__("re").compile(r"[A-Za-z_][A-Za-z0-9_]*|\d+(?:\.\d+)?")

    def __init__(self, document, language: str, colours: dict):
        super().__init__(document)
        _, self.comment, words = LANGUAGES.get(language, ((), "", ""))
        self.words = set(words.split())
        self.fmt = {}
        for name, colour in colours.items():
            f = QTextCharFormat()
            f.setForeground(QColor(colour))
            self.fmt[name] = f
        self.fmt["key"].setFontWeight(QFont.Weight.DemiBold)
        self.markdown = language == "Markdown"

    def highlightBlock(self, text: str) -> None:
        if self.markdown:
            if text.startswith("#"):
                self.setFormat(0, len(text), self.fmt["key"])
            elif text.lstrip().startswith(("- ", "* ", "> ")):
                self.setFormat(0, len(text) - len(text.lstrip()) + 1, self.fmt["key"])
            return
        i, n = 0, len(text)
        while i < n:
            ch = text[i]
            if self.comment and text.startswith(self.comment, i) and (self.comment != "#" or i == 0 or text[i - 1] in " \t;"):
                self.setFormat(i, n - i, self.fmt["comment"])
                return
            if ch in "\"'":
                j = i + 1
                while j < n and text[j] != ch:
                    j += 2 if text[j] == "\\" else 1
                self.setFormat(i, min(j + 1, n) - i, self.fmt["string"])
                i = j + 1
                continue
            found = self.WORD.match(text, i)
            if found:
                word = found.group()
                if word[0].isdigit():
                    self.setFormat(i, len(word), self.fmt["number"])
                elif word in self.words:
                    self.setFormat(i, len(word), self.fmt["key"])
                i = found.end()
                continue
            i += 1


class Documents(QObject):
    """Everything you open that isn't a Writer document: it reads PDFs, and it opens plain text and code for editing.
    A text file is saved only when you say so, in the encoding and with the line endings it came with."""
    changed = Signal()
    failed = Signal(str)
    textLoaded = Signal()

    def __init__(self, target: Path = None):
        super().__init__()
        self._current, self._kind = "", ""
        self._text = self._saved = ""
        self._encoding, self._bom, self._crlf, self._mtime, self._read_only, self._why = "utf-8", False, False, 0.0, False, ""
        self._extra = str(target) if target and target.is_file() else ""
        self._scan()
        first = self._extra or next((f["path"] for f in self._files if f["kind"] == "pdf"), "") or (self._files[0]["path"] if self._files else "")
        if first:
            self.open(first)

    def _scan(self) -> None:
        rows = []
        for which in (QStandardPaths.DocumentsLocation, QStandardPaths.DownloadLocation):
            folder = Path(QStandardPaths.writableLocation(which) or "")
            if folder.is_dir():
                for p in folder.rglob("*"):
                    if p.suffix.lower() == ".pdf" and not any(part.startswith(".") for part in p.parts):
                        try:
                            if p.is_file():
                                rows.append((p.stat().st_mtime, p))
                        except OSError:
                            pass
                    if len(rows) > 500:
                        break
        if self._extra and Path(self._extra) not in [p for _, p in rows]:
            rows.append((time.time(), Path(self._extra)))
        if self._current and Path(self._current) not in [p for _, p in rows]:
            rows.append((time.time(), Path(self._current)))
        rows.sort(reverse=True)
        self._files = [{"path": str(p), "name": p.stem if p.suffix.lower() == ".pdf" else p.name, "kind": "pdf" if p.suffix.lower() == ".pdf" else "text"} for _, p in rows]

    files = Property("QVariantList", lambda self: self._files, notify=changed)
    current = Property(str, lambda self: self._current, notify=changed)
    kind = Property(str, lambda self: self._kind, notify=changed)                 # "pdf", "text", "other" (can't be shown) or ""
    currentUrl = Property(str, lambda self: QUrl.fromLocalFile(self._current).toString() if self._kind == "pdf" else "", notify=changed)
    title = Property(str, lambda self: (Path(self._current).stem if self._kind == "pdf" else Path(self._current).name) if self._current else "Documents", notify=changed)
    text = Property(str, lambda self: self._text, notify=textLoaded)
    edited = Property(bool, lambda self: self._kind == "text" and self._text != self._saved, notify=changed)
    readOnly = Property(bool, lambda self: self._read_only, notify=changed)
    why = Property(str, lambda self: self._why, notify=changed)                   # why it can't be changed or shown
    encoding = Property(str, lambda self: {"utf-8": "UTF-8", "latin-1": "Latin-1"}[self._encoding] + (" with CRLF" if self._crlf else ""), notify=changed)

    @Slot()
    def sendByMail(self) -> None:
        if self._current:
            send_by_mail([self._current])

    @Property(str, notify=changed)
    def language(self):
        if self._kind != "text":
            return ""
        name = Path(self._current).name.lower()
        for language, (suffixes, _, _) in LANGUAGES.items():
            if name.endswith(suffixes):
                return language
        first = self._saved.split("\n", 1)[0]
        return "Python" if first.startswith("#!") and "python" in first else "Shell" if first.startswith("#!") else "Text"

    @Slot(str)
    def open(self, path: str) -> None:
        """Open a file. Anything unsaved in the file in front is dropped: the window asks first."""
        source = Path(path)
        self._current, self._text, self._saved, self._read_only, self._why = path, "", "", False, ""
        self._encoding, self._bom, self._crlf = "utf-8", False, False
        try:
            with open(source, "rb") as f:
                head = f.read(8192)
            if head.startswith(b"%PDF") or source.suffix.lower() == ".pdf":
                self._kind = "pdf"
            elif b"\0" in head:
                self._kind, self._why = "other", "This isn't a text file or a PDF, so Documents can't show it."
            elif source.stat().st_size > TEXT_LIMIT:
                self._kind, self._why = "other", f"This file is {human_size(source.stat().st_size)}. Documents opens text files up to {human_size(TEXT_LIMIT)}."
            elif not os.environ.get("HUGINN_DOCUMENTS_EDITS_TEXT"):      # text and code live in Code now
                import sys
                from PySide6.QtCore import QProcess
                QProcess.startDetached(sys.executable, [str(Path(__file__).resolve()), "code", str(source)])
                self._kind, self._why = "other", f"“{source.name}” opened in Code, Huginn's code editor."
            else:
                data = source.read_bytes()
                self._bom = data.startswith(b"\xef\xbb\xbf")
                try:
                    text = data[3 if self._bom else 0:].decode("utf-8")
                except UnicodeDecodeError:
                    text, self._encoding = data.decode("latin-1"), "latin-1"      # every byte has a letter, so saving puts the same bytes back
                self._crlf = "\r\n" in text
                self._text = self._saved = text.replace("\r\n", "\n") if self._crlf else text
                self._mtime, self._kind = source.stat().st_mtime, "text"
                if not os.access(source, os.W_OK):
                    self._read_only, self._why = True, "You don't have permission to change this file, so it is read only."
        except OSError as err:
            self._kind, self._why = "other", f"Couldn't open “{source.name}”: {err.strerror or err}"
        if path not in [f["path"] for f in self._files]:
            self._scan()
        self.changed.emit()
        self.textLoaded.emit()

    @Slot(str)
    def edit(self, text: str) -> None:
        was = self.edited
        self._text = text
        if self.edited != was:
            self.changed.emit()

    @Slot(bool, result=str)
    def save(self, force: bool = False) -> str:
        """Returns "" when saved, "changed" when the file was altered by something else since it was opened (ask, then
        call again with force), or "failed" (the reason goes out through `failed`)."""
        if self._kind != "text" or self._read_only:
            return "failed"
        target = Path(os.path.realpath(self._current))            # through a link, to the file itself
        try:
            if not force and target.exists() and abs(target.stat().st_mtime - self._mtime) > 0.001:
                return "changed"
            text = self._text.replace("\n", "\r\n") if self._crlf else self._text
            try:
                data = (b"\xef\xbb\xbf" if self._bom else b"") + text.encode(self._encoding)
            except UnicodeEncodeError:                            # a letter Latin-1 doesn't have was typed: the file becomes UTF-8
                self._encoding = "utf-8"
                data = text.encode("utf-8")
            tmp = target.with_name(f".{target.name}.saving")
            try:                                                  # write beside it, then swap: a crash can't leave half a file
                tmp.write_bytes(data)
                if target.exists():
                    shutil.copymode(target, tmp)
                os.replace(tmp, target)
            except PermissionError:                               # the folder can't be written but the file can
                try:
                    tmp.unlink(missing_ok=True)
                except OSError:
                    pass
                with open(target, "wb") as f:
                    f.write(data)
            self._saved, self._mtime = self._text, target.stat().st_mtime
        except OSError as err:
            self.failed.emit(f"Couldn't save: {err.strerror or err}")
            return "failed"
        self.changed.emit()
        return ""

    @Slot()
    def revert(self) -> None:
        self.open(self._current)

    @Slot()
    def newText(self) -> None:
        folder = Path(QStandardPaths.writableLocation(QStandardPaths.DocumentsLocation) or Path.home() / "Documents")
        try:
            folder.mkdir(parents=True, exist_ok=True)
            path, n = folder / "Untitled.txt", 1
            while path.exists():
                n += 1
                path = folder / f"Untitled {n}.txt"
            path.write_text("", encoding="utf-8")
        except OSError as err:
            self.failed.emit(f"Couldn't create a file: {err.strerror or err}")
            return
        self._scan()
        self.open(str(path))

    @Slot(QObject, "QVariantMap")
    def style(self, quick_document, colours) -> None:
        """Called by the editor: colour this file as its language, in the theme's colours."""
        old = getattr(self, "_styler", None)
        if old is not None:
            old.setDocument(None)
        self._styler = CodeStyler(quick_document.textDocument(), self.language, dict(colours)) if self._kind == "text" else None


# ------------------------------------------------------------------------------------------ Calculator
class Calculator(QObject):
    """Exact decimal arithmetic (no 0.1 + 0.2 surprises). Understands + − × ÷, brackets and %."""
    changed = Signal()

    def __init__(self):
        super().__init__()
        self._history = []

    history = Property("QVariantList", lambda self: self._history, notify=changed)

    @staticmethod
    def _eval(text: str):
        import ast
        from decimal import Decimal, DivisionByZero, InvalidOperation, getcontext
        getcontext().prec = 28
        text = text.replace("×", "*").replace("÷", "/").replace("−", "-").replace(",", "").replace("%", "/100")
        if not text.strip() or len(text) > 200:
            raise ValueError("empty")

        def walk(node):
            if isinstance(node, ast.Expression):
                return walk(node.body)
            if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
                return Decimal(str(node.value))
            if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
                value = walk(node.operand)
                return -value if isinstance(node.op, ast.USub) else value
            if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div)):
                a, b = walk(node.left), walk(node.right)
                return a + b if isinstance(node.op, ast.Add) else a - b if isinstance(node.op, ast.Sub) else a * b if isinstance(node.op, ast.Mult) else a / b
            raise ValueError("unsupported")
        try:
            return walk(ast.parse(text, mode="eval"))
        except (DivisionByZero, ZeroDivisionError):
            raise ZeroDivisionError
        except (SyntaxError, InvalidOperation, RecursionError, MemoryError):
            raise ValueError("bad")

    @staticmethod
    def _show(value) -> str:
        from decimal import Decimal
        if value == value.to_integral_value() and abs(value) < Decimal("1e15"):
            return f"{int(value):,}"
        if abs(value) >= Decimal("1e15") or (value != 0 and abs(value) < Decimal("1e-9")):
            return f"{value:.8E}"
        text = f"{value:,.10f}".rstrip("0").rstrip(".")
        return text or "0"

    @Slot(str, result=str)
    def preview(self, text: str) -> str:
        try:
            return self._show(self._eval(text))
        except (ValueError, ZeroDivisionError):
            return ""

    @Slot(str, result=str)
    def solve(self, text: str) -> str:
        try:
            result = self._show(self._eval(text))
        except ZeroDivisionError:
            return "Can't divide by zero"
        except ValueError:
            return "Not a complete sum"
        self._history = ([{"sum": text, "result": result}] + self._history)[:30]
        self.changed.emit()
        return result


# ----------------------------------------------------------------------------------------------- Clock
class Clock(QObject):
    """World clock data; the stopwatch and timer live in the QML."""
    changed = Signal()
    CITIES = [("Reykjavík", "Atlantic/Reykjavik"), ("London", "Europe/London"), ("New York", "America/New_York"),
              ("Los Angeles", "America/Los_Angeles"), ("Tokyo", "Asia/Tokyo"), ("Sydney", "Australia/Sydney")]

    @Slot(result="QVariantList")
    def world(self) -> list:
        try:
            from zoneinfo import ZoneInfo
        except ImportError:
            return []
        here, out = dt.datetime.now().astimezone(), []
        for city, zone in self.CITIES:
            try:
                there = here.astimezone(ZoneInfo(zone))
            except Exception:       # zone data missing on this system
                continue
            hours = (there.utcoffset() - here.utcoffset()).total_seconds() / 3600
            day = "Today" if there.date() == here.date() else ("Tomorrow" if there.date() > here.date() else "Yesterday")
            gap = "Same time" if hours == 0 else f"{abs(hours):g} h {'ahead' if hours > 0 else 'behind'}"
            out.append({"city": city, "time": there.strftime("%H:%M"), "note": f"{day} · {gap}", "night": there.hour < 6 or there.hour >= 20})
        return out


# -------------------------------------------------------------------------------------------- Terminal
class Shell(QObject):
    """One terminal tab: runs your shell on a pseudo-terminal and draws what it prints.
    The screen logic is the `pyte` library (a VT100/xterm emulator); this class connects it to the shell and to QML."""
    changed = Signal()
    closed = Signal()

    ANSI = {"black": "#1E2227", "red": "#FF5F57", "green": "#43D9B8", "brown": "#FFB340", "blue": "#7CC4FF", "magenta": "#A995FF",
            "cyan": "#3DD6B5", "white": "#DCE1E6", "brightblack": "#5C646D", "brightred": "#FF8C82", "brightgreen": "#7CEBD2",
            "brightbrown": "#FFD080", "brightblue": "#A9D8FF", "brightmagenta": "#C9BCFF", "brightcyan": "#8BEBD8", "brightwhite": "#FFFFFF"}
    LIGHT = {"black": "#101317", "red": "#D93A3F", "green": "#0A8071", "brown": "#C46A00", "blue": "#2361AE", "magenta": "#563AD1",
             "cyan": "#0A8071", "white": "#464D57", "brightblack": "#6E767F", "brightwhite": "#101317"}

    def __init__(self, settings, start: Path = None, run: list = None):
        super().__init__()
        self._settings, self._fd, self._pid, self._title = settings, -1, 0, "Terminal"
        self._run = [a for a in (run or []) if a != "--"]
        self._cols, self._rows, self._lines, self._ok = 100, 30, [], True
        try:
            import pyte
            self._pyte = pyte
        except ImportError:
            self._ok = False
            return
        self._screen = pyte.HistoryScreen(self._cols, self._rows, history=3000, ratio=0.5)
        self._stream = pyte.ByteStream(self._screen)
        self._paint = QTimer(self)
        self._paint.setSingleShot(True)
        self._paint.setInterval(16)
        self._paint.timeout.connect(self._render)
        settings.changed.connect(self._render)
        self._spawn(start)

    def _spawn(self, start) -> None:
        import pty
        shell = os.environ.get("SHELL") or "/bin/bash"
        self._pid, self._fd = pty.fork()
        if self._pid == 0:                                # the child becomes the shell
            try:
                os.chdir(str(start) if start and start.is_dir() else str(Path.home()))
            except OSError:
                pass
            os.environ.update({"TERM": "xterm-256color", "COLORTERM": "truecolor", "TERM_PROGRAM": "huginn-terminal"})
            argv = [shell]
            if self._run:                                 # a command to run (x-terminal-emulator -e …): one string goes to the shell
                argv = ["/bin/sh", "-c", self._run[0]] if len(self._run) == 1 and " " in self._run[0] else self._run
            try:
                os.execvp(argv[0], argv)
            finally:
                os._exit(1)
        from PySide6.QtCore import QSocketNotifier
        self._notifier = QSocketNotifier(self._fd, QSocketNotifier.Read, self)
        self._notifier.activated.connect(self._read)
        self._resize()

    def _resize(self) -> None:
        import fcntl
        import struct
        import termios
        if self._fd >= 0:
            fcntl.ioctl(self._fd, termios.TIOCSWINSZ, struct.pack("HHHH", self._rows, self._cols, 0, 0))

    def _read(self) -> None:
        try:
            data = os.read(self._fd, 65536)
        except OSError:
            data = b""
        if not data:                                      # the shell exited
            self._notifier.setEnabled(False)
            self.closed.emit()
            return
        self._stream.feed(data)
        if self._screen.title:
            self._title = self._screen.title
        if not self._paint.isActive():
            self._paint.start()

    def _colour(self, name: str, fallback: str) -> str:
        if name == "default":
            return fallback
        if len(name) == 6 and all(c in "0123456789abcdefABCDEF" for c in name):
            return "#" + name
        table = self.ANSI if self._settings.dark else {**self.ANSI, **self.LIGHT}
        return table.get(name, fallback)

    def _line(self, row: dict, cursor: int = -1) -> str:
        """One screen row as rich text: runs of equal style become one <span>."""
        import html
        fg0, out, run, style = ("#ECEFF3" if self._settings.dark else "#101317"), [], [], None

        def flush():
            if run:
                text = html.escape("".join(run)).replace(" ", "&nbsp;")
                out.append(f'<span style="{style}">{text}</span>' if style else text)
                run.clear()
        last = max(row.keys(), default=-1)
        for x in range(max(last, cursor) + 1):
            ch = row.get(x) if x in row else None
            data = ch.data if ch else " "
            fg = self._colour(ch.fg, fg0) if ch else fg0
            bg = self._colour(ch.bg, "") if ch else ""
            if ch and ch.reverse:
                fg, bg = (bg or ("#15181C" if self._settings.dark else "#FFFFFF")), fg
            if x == cursor:
                fg, bg = ("#15181C" if self._settings.dark else "#FFFFFF"), ("#43D9B8" if self._settings.dark else "#0A8071")
            css = (f"color:{fg};" if fg != fg0 else "") + (f"background-color:{bg};" if bg else "") + ("font-weight:bold;" if ch and ch.bold else "") \
                + ("font-style:italic;" if ch and ch.italics else "") + ("text-decoration:underline;" if ch and ch.underscore else "")
            if css != style:
                flush()
                style = css
            run.append(data or " ")
        flush()
        return "".join(out) or "&nbsp;"

    def _render(self) -> None:
        scr = self._screen
        history = [self._line(row) for row in scr.history.top]
        cursor = scr.cursor
        live = [self._line(scr.buffer[y], cursor.x if (y == cursor.y and not cursor.hidden) else -1) for y in range(scr.lines)]
        self._lines = history + live
        self.changed.emit()

    @Property(str, constant=True)
    def font(self):
        """The theme's monospace font if installed, otherwise the system's fixed-width font (never a proportional one)."""
        from PySide6.QtGui import QFontDatabase
        wanted = "JetBrains Mono"
        return wanted if wanted in QFontDatabase.families() else QFontDatabase.systemFont(QFontDatabase.FixedFont).family()

    available = Property(bool, lambda self: self._ok, constant=True)
    lines = Property("QVariantList", lambda self: self._lines, notify=changed)
    title = Property(str, lambda self: self._title, notify=changed)
    size = Property(str, lambda self: f"{self._cols} × {self._rows}", notify=changed)

    @Slot(int, int)
    def fit(self, cols: int, rows: int) -> None:
        cols, rows = max(20, min(400, cols)), max(5, min(200, rows))
        if not self._ok or (cols, rows) == (self._cols, self._rows):
            return
        self._cols, self._rows = cols, rows
        self._screen.resize(rows, cols)
        self._resize()
        self._render()

    def _send(self, data: bytes) -> None:
        if self._fd >= 0 and data:
            try:
                os.write(self._fd, data)
            except OSError:
                pass

    @Slot(int, int, str)
    def key(self, key: int, modifiers: int, text: str) -> None:
        from PySide6.QtCore import Qt
        ctrl = bool(modifiers & Qt.ControlModifier.value)
        special = {Qt.Key_Return.value: b"\r", Qt.Key_Enter.value: b"\r", Qt.Key_Backspace.value: b"\x7f", Qt.Key_Tab.value: b"\t",
                   Qt.Key_Escape.value: b"\x1b", Qt.Key_Up.value: b"\x1b[A", Qt.Key_Down.value: b"\x1b[B", Qt.Key_Right.value: b"\x1b[C",
                   Qt.Key_Left.value: b"\x1b[D", Qt.Key_Home.value: b"\x1b[H", Qt.Key_End.value: b"\x1b[F", Qt.Key_Delete.value: b"\x1b[3~",
                   Qt.Key_PageUp.value: b"\x1b[5~", Qt.Key_PageDown.value: b"\x1b[6~", Qt.Key_Backtab.value: b"\x1b[Z"}
        if key in special:
            self._send(special[key])
        elif ctrl and Qt.Key_A.value <= key <= Qt.Key_Z.value:
            self._send(bytes([key - Qt.Key_A.value + 1]))
        elif text:
            self._send(text.encode("utf-8"))

    @Slot()
    def paste(self) -> None:
        text = QGuiApplication.clipboard().text()
        if text:
            self._send(text.replace("\r\n", "\r").replace("\n", "\r").encode("utf-8"))

    @Slot()
    def copyAll(self) -> None:
        scr = self._screen
        rows = ["".join(row[x].data for x in range(scr.columns)).rstrip() for row in list(scr.history.top) + [scr.buffer[y] for y in range(scr.lines)]]
        QGuiApplication.clipboard().setText("\n".join(rows).rstrip() + "\n")

    def stop(self) -> None:
        if self._pid > 0:
            try:
                os.kill(self._pid, signal.SIGHUP)
            except OSError:
                pass


class Terminal(QObject):
    """The Terminal app: one Shell per tab. QML talks to this; it passes everything on to the tab in front."""
    changed = Signal()
    closed = Signal()          # the last tab's shell ended: the window closes

    def __init__(self, settings, start: Path = None, run: list = None):
        super().__init__()
        self._settings, self._tabs, self._at, self._size = settings, [], 0, (100, 30)
        self._open(start, run)

    def _open(self, start, run: list = None) -> None:
        tab = Shell(self._settings, start, run)
        tab.fit(*self._size)
        tab.changed.connect(lambda t=tab: self.changed.emit() if t is self._now() else self._names())
        tab.closed.connect(lambda t=tab: self._ended(t))
        self._tabs.append(tab)
        self._at = len(self._tabs) - 1
        self._seen = self._labels()
        self.changed.emit()

    def _now(self) -> "Shell":
        return self._tabs[self._at]

    def _labels(self) -> list:
        return [t.title for t in self._tabs]

    def _names(self) -> None:
        """A tab behind the front one printed something: redraw only if its name changed."""
        if self._labels() != self._seen:
            self._seen = self._labels()
            self.changed.emit()

    def _ended(self, tab) -> None:
        if tab not in self._tabs:
            return
        i = self._tabs.index(tab)
        self._tabs.remove(tab)
        tab.stop()
        tab.deleteLater()
        if not self._tabs:
            self.closed.emit()
            return
        self._at = min(self._at if i > self._at else max(0, self._at - 1) if i < self._at else i, len(self._tabs) - 1)
        self._seen = self._labels()
        self.changed.emit()

    def _folder(self):
        """Where the front tab's shell is, so a new tab opens beside it."""
        try:
            return Path(os.readlink(f"/proc/{self._now()._pid}/cwd"))
        except OSError:
            return None

    font = Property(str, lambda self: self._now().font, constant=True)
    available = Property(bool, lambda self: self._now()._ok, constant=True)
    lines = Property("QVariantList", lambda self: self._now()._lines, notify=changed)
    title = Property(str, lambda self: self._now().title, notify=changed)
    size = Property(str, lambda self: self._now().size, notify=changed)
    current = Property(int, lambda self: self._at, notify=changed)

    @Property("QVariantList", notify=changed)
    def tabs(self):
        out = []
        for t in self._tabs:
            name = t.title.rsplit(":", 1)[-1].strip() or t.title       # "you@pc: ~/Projects" -> "~/Projects"
            out.append(name if len(name) <= 22 else "…" + name[-21:])
        return out

    @Slot()
    def newTab(self) -> None:
        if self._now()._ok and len(self._tabs) < 12:
            self._open(self._folder())

    @Slot(int)
    def select(self, index: int) -> None:
        if 0 <= index < len(self._tabs) and index != self._at:
            self._at = index
            self._now()._render()
            self.changed.emit()

    @Slot(int)
    def step(self, by: int) -> None:
        self.select((self._at + by) % len(self._tabs))

    @Slot(int)
    def closeTab(self, index: int) -> None:
        if 0 <= index < len(self._tabs):
            self._ended(self._tabs[index])

    @Slot(int, int)
    def fit(self, cols: int, rows: int) -> None:
        self._size = (cols, rows)
        for t in self._tabs:
            t.fit(cols, rows)
        self.changed.emit()

    @Slot(int, int, str)
    def key(self, key: int, modifiers: int, text: str) -> None:
        self._now().key(key, modifiers, text)

    @Slot()
    def paste(self) -> None:
        self._now().paste()

    @Slot()
    def copyAll(self) -> None:
        self._now().copyAll()

    def stop(self) -> None:
        for t in self._tabs:
            t.stop()


# ------------------------------------------------------------------------------------------ Screenshot
class Capture(QObject):
    """Screenshot: take a picture of the screen, mark it up, save or copy it.
    On Wayland the picture is taken by the desktop portal (the only permitted way); elsewhere Qt grabs the screen."""
    changed = Signal()
    failed = Signal(str)

    def __init__(self, sample: str = ""):
        super().__init__()
        self._image, self._saved, self._busy = sample, "", False
        self._framing, self._frame_next, self._cuts = False, False, 0
        self._tmp = Path(os.environ.get("XDG_RUNTIME_DIR") or "/tmp") / f"huginn-capture-{os.getpid()}.png"
        self._rec, self._rec_state, self._rec_path, self._rec_since = None, "", "", 0.0      # "", "asking", "on", "ending"
        self._rec_line.connect(self._rec_said)

    # ---------------------------------------------------------------- recording the screen as video
    _rec_line = Signal(str)
    recorded = Signal(str)                                         # a recording was finished: where it is
    recording = Property(str, lambda self: self._rec_state, notify=changed)
    recordedFor = Property(int, lambda self: int(time.time() - self._rec_since) if self._rec_state == "on" else 0, notify=changed)

    @Slot(bool)
    def record(self, sound: bool = True) -> None:
        """Start a video of the screen. The desktop asks which screen or window; nothing is recorded before you pick."""
        if self._rec_state:
            return
        import shutil as sh
        folder = Path(QStandardPaths.writableLocation(QStandardPaths.MoviesLocation) or Path.home() / "Videos") / "Screen Recordings"
        kind = ".mp4" if sh.which("gst-inspect-1.0") and subprocess.run(["gst-inspect-1.0", "x264enc"], capture_output=True).returncode == 0 else ".webm"
        stem, n = dt.datetime.now().strftime("Screen Recording %Y-%m-%d %H.%M.%S"), 1
        while (folder / (stem + ("" if n == 1 else f" {n}") + kind)).exists():      # never the name of a recording that's already there
            n += 1
        self._rec_path = str(folder / (stem + ("" if n == 1 else f" {n}") + kind))
        tool = os.environ.get("HUGINN_SCREENCAST") or str(HERE / "huginn_screencast.py")
        try:
            folder.mkdir(parents=True, exist_ok=True)
            self._rec = subprocess.Popen([sys.executable, tool, self._rec_path] + ([] if sound else ["--no-sound"]), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        except OSError as err:
            self.failed.emit(f"Couldn't start recording: {err.strerror or err}")
            return
        self._rec_state = "asking"
        self.changed.emit()
        proc = self._rec

        def listen():
            for line in proc.stdout:
                self._rec_line.emit(line.strip())
            proc.wait()
            self._rec_line.emit(f"EXIT {proc.returncode}")
        threading.Thread(target=listen, daemon=True).start()

    def _rec_said(self, line: str) -> None:
        if line == "STARTED":
            self._rec_state, self._rec_since = "on", time.time()
        elif line.startswith("ERROR:"):
            self._rec_problem = line[6:].strip()
        elif line.startswith("NOTE:"):
            self.failed.emit(line[5:].strip())
        elif line.startswith("EXIT"):
            was, problem = self._rec_state, getattr(self, "_rec_problem", "")
            self._rec, self._rec_state, self._rec_problem = None, "", ""
            path = Path(self._rec_path)
            if was in ("on", "ending") and path.exists() and path.stat().st_size > 1000:
                self.recorded.emit(str(path))
            else:
                path.unlink(missing_ok=True) if path.exists() else None
                self.failed.emit(problem or "The recording didn't start.")
        self.changed.emit()

    @Slot()
    def stopRecording(self) -> None:
        if self._rec is not None and self._rec_state in ("on", "asking"):
            self._rec_state = "ending"
            try:
                self._rec.send_signal(signal.SIGINT)
            except OSError:
                pass
            self.changed.emit()

    image = Property(str, lambda self: QUrl.fromLocalFile(self._image).toString() if self._image else "", notify=changed)
    saved = Property(str, lambda self: self._saved, notify=changed)
    busy = Property(bool, lambda self: self._busy, notify=changed)
    framing = Property(bool, lambda self: self._framing, notify=changed)   # the screen is frozen, waiting for you to drag a frame

    @Property("QVariantList", notify=changed)
    def pixels(self):
        """The captured picture's size, so the frame can say how big the cut will be."""
        size = QImageReader(self._image).size() if self._image else QSize()
        return [size.width(), size.height()] if size.isValid() else [0, 0]

    @Slot(int)
    def frame(self, delay: int) -> None:
        """Freeze the whole screen, then let the person drag a frame over it (see crop)."""
        self._frame_next = True
        self.take(False, delay)

    @Slot(float, float, float, float)
    def crop(self, x: float, y: float, w: float, h: float) -> None:
        """Keep only the framed part. The frame comes as fractions of the picture, so it works at any scale."""
        picture = QImage(self._image)
        if picture.isNull():
            self._framing = False
            self._done("", "The picture couldn't be opened to cut it.")
            return
        left, top = round(max(0.0, min(1.0, x)) * picture.width()), round(max(0.0, min(1.0, y)) * picture.height())
        wide = max(1, min(picture.width() - left, round(w * picture.width())))
        tall = max(1, min(picture.height() - top, round(h * picture.height())))
        self._cuts += 1
        out = self._tmp.with_name(f"{self._tmp.stem}-{self._cuts}.png")     # a new name, so the old picture isn't shown from memory
        self._framing = False
        if picture.copy(left, top, wide, tall).save(str(out)):
            self._done(str(out))
        else:
            self._done("", "The cut picture couldn't be saved.")

    @Property(str, constant=True)
    def folder(self):
        pics = QStandardPaths.writableLocation(QStandardPaths.PicturesLocation) or str(Path.home() / "Pictures")
        return str(Path(pics) / "Screenshots")

    @Slot(result=str)
    def nextPath(self) -> str:
        folder = Path(self.folder)
        folder.mkdir(parents=True, exist_ok=True)
        return str(folder / dt.datetime.now().strftime("Screenshot %Y-%m-%d at %H.%M.%S.png"))

    @Slot(bool, int)
    def take(self, choose: bool, delay: int) -> None:
        """choose=False: the whole screen. choose=True: the desktop asks which window or area."""
        self._busy = True
        self.changed.emit()
        QTimer.singleShot(max(0, delay) * 1000 + 250, lambda: self._grab(choose))

    def _grab(self, choose: bool) -> None:
        if os.environ.get("WAYLAND_DISPLAY"):
            if self._portal(choose):
                return
        screen = QGuiApplication.primaryScreen()
        shot = screen.grabWindow(0) if screen else None
        if shot is None or shot.isNull() or not shot.save(str(self._tmp)):
            self._done("", "The screen couldn't be captured on this system.")
        else:
            self._done(str(self._tmp))

    def _portal(self, choose: bool) -> bool:
        try:
            from PySide6.QtDBus import QDBusConnection, QDBusInterface, QDBusMessage
        except ImportError:
            return False
        bus = QDBusConnection.sessionBus()
        iface = QDBusInterface("org.freedesktop.portal.Desktop", "/org/freedesktop/portal/desktop", "org.freedesktop.portal.Screenshot", bus)
        if not iface.isValid():
            return False
        token = f"huginn{uuid.uuid4().hex[:8]}"
        sender = bus.baseService().lstrip(":").replace(".", "_")
        path = f"/org/freedesktop/portal/desktop/request/{sender}/{token}"
        bus.connect("org.freedesktop.portal.Desktop", path, "org.freedesktop.portal.Request", "Response", self, "1portalReply(QDBusMessage)")
        reply = iface.call("Screenshot", "", {"handle_token": token, "interactive": choose, "modal": False})
        if reply.type() == QDBusMessage.ErrorMessage:
            return False
        return True

    @Slot("QDBusMessage")
    def portalReply(self, message) -> None:
        args = message.arguments()
        uri = args[1].get("uri", "") if len(args) > 1 and args[0] == 0 and isinstance(args[1], dict) else ""
        self._done(QUrl(uri).toLocalFile() if uri else "", "" if uri else "No screenshot was taken.")

    def _done(self, path: str, problem: str = "") -> None:
        self._busy = False
        if path:
            self._image, self._saved = path, ""
            self._framing, self._frame_next = self._frame_next, False
        else:
            self._framing = self._frame_next = False
            if problem:
                self.failed.emit(problem)
        self.changed.emit()

    @Slot(str)
    def wasSaved(self, path: str) -> None:
        self._saved = path
        self.changed.emit()

    @Slot(str)
    def copy(self, path: str) -> None:
        from PySide6.QtGui import QImage
        image = QImage(path)
        if image.isNull():
            self.failed.emit("The picture couldn't be copied.")
        else:
            QGuiApplication.clipboard().setImage(image)

    @Slot()
    def discard(self) -> None:
        self._image, self._saved, self._framing = "", "", False
        self.changed.emit()

    @Slot(str)
    def reveal(self, path: str) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(path).parent)))


# -------------------------------------------------------------------------------------------- Archives
ARCHIVE_SUFFIXES = (".zip", ".tar", ".tgz", ".gz", ".xz", ".bz2", ".zst", ".7z", ".rar", ".cab", ".cpio", ".xar", ".lha", ".lzh", ".iso")


def bsdtar_list(path: str) -> list:
    """What's in an archive Python can't read itself (7z, RAR, ISO, CAB, cpio…), through libarchive's bsdtar:
    [{"full", "dir", "bytes", "when"}]. Raises OSError if it can't be read."""
    r = subprocess.run(["bsdtar", "-tvf", path], capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        raise OSError(r.stderr.strip().splitlines()[-1] if r.stderr.strip() else "not an archive")
    out = []
    for line in r.stdout.splitlines():                      # -rw-r--r--  0 user group  1234 Jan  1 12:00 name
        bits = line.split(None, 8)
        if len(bits) < 9:
            continue
        mode, size, name = bits[0], bits[4], bits[8]
        if " -> " in name and mode.startswith("l"):
            name = name.split(" -> ")[0]
        when = " ".join(bits[5:8])
        out.append({"full": name.rstrip("/"), "dir": mode.startswith("d"), "bytes": int(size) if size.isdigit() else 0, "when": when})
    return out


class Archives(QObject):
    """Look inside archives and unpack them: zip and tar here, 7z, RAR, ISO, CAB, cpio and the rest through libarchive.
    Unpacking refuses entries that try to escape the folder."""
    changed = Signal()
    failed = Signal(str)

    def __init__(self, target: Path = None):
        super().__init__()
        self._path, self._members, self._inside, self._note, self._last = None, [], "", "", ""
        if target and target.is_file():
            self.open(str(target))

    @Property("QVariantList", constant=True)
    def nearby(self):
        rows = []
        for which in (QStandardPaths.DownloadLocation, QStandardPaths.DocumentsLocation):
            folder = Path(QStandardPaths.writableLocation(which) or "")
            if folder.is_dir():
                for p in sorted(folder.iterdir()):
                    if p.is_file() and (p.suffix.lower() in ARCHIVE_SUFFIXES or ".tar." in p.name.lower()):
                        rows.append({"name": p.name, "path": str(p), "size": human_size(p.stat().st_size)})
        return rows[:40]

    name = Property(str, lambda self: self._path.name if self._path else "", notify=changed)
    isOpen = Property(bool, lambda self: self._path is not None, notify=changed)
    inside = Property(str, lambda self: self._inside, notify=changed)
    note = Property(str, lambda self: self._note, notify=changed)
    lastFolder = Property(str, lambda self: self._last, notify=changed)
    summary = Property(str, lambda self: (f"{sum(1 for m in self._members if not m['dir'])} files, "
                                          f"{human_size(sum(m['bytes'] for m in self._members))} unpacked") if self._path else "", notify=changed)

    @Slot(str)
    def open(self, path: str) -> None:
        import tarfile
        import zipfile
        members = []
        try:
            if zipfile.is_zipfile(path):
                with zipfile.ZipFile(path) as z:
                    for i in z.infolist():
                        members.append({"full": i.filename.rstrip("/"), "dir": i.is_dir(), "bytes": i.file_size, "when": "%04d-%02d-%02d" % i.date_time[:3]})
            elif tarfile.is_tarfile(path):
                with tarfile.open(path) as t:
                    for i in t:
                        members.append({"full": i.name.rstrip("/"), "dir": i.isdir(), "bytes": i.size if i.isfile() else 0,
                                        "when": dt.date.fromtimestamp(i.mtime).isoformat()})
            elif shutil.which("bsdtar"):
                try:
                    members = bsdtar_list(path)
                except (OSError, subprocess.SubprocessError):
                    self.failed.emit("This file isn't an archive Huginn can open.")
                    return
            else:
                self.failed.emit("This file isn't an archive Huginn can open (zip and tar are supported).")
                return
        except (OSError, zipfile.BadZipFile, tarfile.TarError, EOFError) as err:
            self.failed.emit(f"The archive is damaged or unreadable: {err}")
            return
        for m in members:
            m["raw"], m["full"] = m["full"], m["full"][2:] if m["full"].startswith("./") else m["full"]
        members = [m for m in members if m["full"] not in ("", ".")]
        self._path, self._members, self._inside, self._note = Path(path), members, "", ""
        self.changed.emit()

    @Property("QVariantList", notify=changed)
    def entries(self):
        prefix, seen, rows = (self._inside + "/" if self._inside else ""), set(), []
        for m in self._members:
            if not m["full"].startswith(prefix) or m["full"] == self._inside:
                continue
            rest = m["full"][len(prefix):]
            head, _, tail = rest.partition("/")
            if head in seen or not head:
                continue
            seen.add(head)
            is_dir = bool(tail) or m["dir"]
            rows.append({"name": head, "full": prefix + head, "dir": is_dir, "size": "" if is_dir else human_size(m["bytes"]),
                         "when": "" if is_dir else m["when"], "kind": "folder" if is_dir else file_kind(Path(head))})
        return sorted(rows, key=lambda r: (not r["dir"], r["name"].lower()))

    @Property("QVariantList", notify=changed)
    def crumbs(self):
        parts, out = [p for p in self._inside.split("/") if p], [{"name": self._path.name if self._path else "", "full": ""}]
        for i, part in enumerate(parts):
            out.append({"name": part, "full": "/".join(parts[:i + 1])})
        return out

    @Slot(str)
    def enter(self, full: str) -> None:
        self._inside = full
        self.changed.emit()

    @Slot()
    def close(self) -> None:
        self._path, self._members, self._inside, self._note = None, [], "", ""
        self.changed.emit()

    @Slot(str)
    def extract(self, only: str) -> None:
        """Unpack everything (only="") or one file or folder, into a new folder beside the archive."""
        import tarfile
        import zipfile
        if self._path is None:
            return
        stem = self._path.name
        for ext in (".tar.gz", ".tar.xz", ".tar.bz2", ".tar.zst", ".tgz", ".zip", ".tar", ".7z", ".rar", ".cab", ".cpio", ".xar", ".lha", ".lzh", ".iso"):
            if stem.lower().endswith(ext):
                stem = stem[:-len(ext)]
                break
        dest, n = self._path.parent / stem, 1
        while dest.exists():
            n += 1
            dest = self._path.parent / f"{stem} {n}"
        def wanted(name: str) -> bool:
            name = name[2:] if name.startswith("./") else name
            return not only or name == only or name.startswith(only + "/")
        try:
            dest.mkdir(parents=True)
            root, count = dest.resolve(), 0
            if zipfile.is_zipfile(self._path):
                with zipfile.ZipFile(self._path) as z:
                    for info in z.infolist():
                        if not wanted(info.filename.rstrip("/")):
                            continue
                        target = (root / info.filename).resolve()
                        if root != target and root not in target.parents:
                            raise OSError(f"“{info.filename}” points outside the folder")
                        z.extract(info, root)
                        count += not info.is_dir()
            elif tarfile.is_tarfile(self._path):
                with tarfile.open(self._path) as t:
                    picked = [m for m in t if wanted(m.name.rstrip("/"))]
                    t.extractall(root, members=picked, filter="data")      # "data" blocks escapes, devices and odd permissions
                    count = sum(1 for m in picked if m.isfile())
            else:                                             # libarchive: it refuses absolute paths and ".." by itself
                names = [m["raw"] for m in self._members if wanted(m["raw"])]
                if any(n.startswith("/") or ".." in Path(n).parts for n in names):
                    raise OSError("an entry points outside the folder")
                cmd = ["bsdtar", "-xf", str(self._path), "-C", str(root), "--no-same-owner", "--no-same-permissions"]
                if only:
                    cmd += ["--", *[n for n in names]]
                r = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
                if r.returncode != 0:
                    raise OSError((r.stderr.strip().splitlines() or ["couldn't unpack"])[-1])
                count = sum(1 for q in root.rglob("*") if q.is_file())
        except (OSError, zipfile.BadZipFile, tarfile.TarError) as err:
            shutil.rmtree(dest, ignore_errors=True)
            self.failed.emit(f"Unpacking stopped and nothing was kept: {err}")
            return
        self._note, self._last = f"Unpacked {count} file{'s' if count != 1 else ''} into “{dest.name}”", str(dest)
        self.changed.emit()

    @Slot()
    def showFolder(self) -> None:
        if self._last:
            QDesktopServices.openUrl(QUrl.fromLocalFile(self._last))


# --------------------------------------------------------------------------------------------- Monitor
class Monitor(QObject):
    """System Monitor: processor, memory, swap, network and disk activity plus the process list, all read
    from /proc. Refreshes every two seconds; each graph keeps the last two minutes."""
    changed = Signal()
    failed = Signal(str)
    POINTS = 60

    def __init__(self):
        super().__init__()
        zero = [0.0] * self.POINTS
        self._rows, self._prev, self._prev_io = [], {}, {}
        self._prev_total = self._prev_idle = 0
        self._cpu, self._cpu_hist = 0.0, list(zero)
        self._mem = {"used": 0, "total": 0, "swap_used": 0, "swap_total": 0}
        self._net = {"down": 0.0, "up": 0.0, "rx": 0, "tx": 0}
        self._disk = {"read": 0.0, "write": 0.0, "rd": 0, "wr": 0}
        self._hist = {"down": list(zero), "up": list(zero), "read": list(zero), "write": list(zero)}
        self._stamp = 0.0
        self._page = os.sysconf("SC_PAGE_SIZE") if hasattr(os, "sysconf") else 4096
        self._ticks = os.sysconf("SC_CLK_TCK") if hasattr(os, "sysconf") else 100
        self._supported = Path("/proc/stat").is_file()
        self.refresh()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh)
        self._timer.start(2000)

    supported = Property(bool, lambda self: self._supported, constant=True)
    rows = Property("QVariantList", lambda self: self._rows, notify=changed)
    cores = Property(int, lambda self: os.cpu_count() or 1, constant=True)
    cpu = Property(float, lambda self: self._cpu, notify=changed)
    cpuHistory = Property("QVariantList", lambda self: self._cpu_hist, notify=changed)
    memory = Property(float, lambda self: self._mem["used"] / self._mem["total"] if self._mem["total"] else 0.0, notify=changed)
    memoryLabel = Property(str, lambda self: f"{human_size(self._mem['used'])} of {human_size(self._mem['total'])}", notify=changed)
    swap = Property(float, lambda self: self._mem["swap_used"] / self._mem["swap_total"] if self._mem["swap_total"] else 0.0, notify=changed)
    swapLabel = Property(str, lambda self: (f"{human_size(self._mem['swap_used'])} of {human_size(self._mem['swap_total'])}"
                                            if self._mem["swap_total"] else "Not set up"), notify=changed)
    downLabel = Property(str, lambda self: human_size(self._net["down"]) + "/s", notify=changed)
    upLabel = Property(str, lambda self: human_size(self._net["up"]) + "/s", notify=changed)
    receivedLabel = Property(str, lambda self: human_size(self._net["rx"]), notify=changed)
    sentLabel = Property(str, lambda self: human_size(self._net["tx"]), notify=changed)
    readLabel = Property(str, lambda self: human_size(self._disk["read"]) + "/s", notify=changed)
    writeLabel = Property(str, lambda self: human_size(self._disk["write"]) + "/s", notify=changed)
    downHistory = Property("QVariantList", lambda self: self._hist["down"], notify=changed)
    upHistory = Property("QVariantList", lambda self: self._hist["up"], notify=changed)
    readHistory = Property("QVariantList", lambda self: self._hist["read"], notify=changed)
    writeHistory = Property("QVariantList", lambda self: self._hist["write"], notify=changed)
    summary = Property(str, lambda self: f"{sum(1 for r in self._rows if r['mine'])} of yours, {len(self._rows)} in all", notify=changed)

    @staticmethod
    def _network() -> tuple:
        rx = tx = 0
        for line in Path("/proc/net/dev").read_text().splitlines()[2:]:
            name, _, data = line.partition(":")
            cols = data.split()
            if name.strip() != "lo" and len(cols) >= 9:
                rx, tx = rx + int(cols[0]), tx + int(cols[8])
        return rx, tx

    @staticmethod
    def _disks() -> tuple:
        try:
            whole = {d.name for d in os.scandir("/sys/block") if not d.name.startswith(("loop", "ram", "zram"))}
        except OSError:
            whole = set()
        rd = wr = 0
        for line in Path("/proc/diskstats").read_text().splitlines():
            cols = line.split()
            if len(cols) >= 10 and cols[2] in whole:
                rd, wr = rd + int(cols[5]) * 512, wr + int(cols[9]) * 512
        return rd, wr

    def _push(self, key: str, value: float) -> None:
        self._hist[key] = self._hist[key][1:] + [value]

    @Slot()
    def refresh(self) -> None:
        if not self._supported:
            return
        now = time.monotonic()
        span = now - self._stamp if self._stamp else 0.0
        try:
            fields = [int(x) for x in Path("/proc/stat").read_text().splitlines()[0].split()[1:]]
            total, idle = sum(fields), fields[3] + (fields[4] if len(fields) > 4 else 0)
            mem = {line.split(":")[0]: int(line.split()[1]) * 1024 for line in Path("/proc/meminfo").read_text().splitlines() if ":" in line}
        except (OSError, ValueError, IndexError):
            return
        d_total = total - self._prev_total
        if self._prev_total and d_total > 0:
            self._cpu = max(0.0, min(1.0, 1 - (idle - self._prev_idle) / d_total))
        self._cpu_hist = self._cpu_hist[1:] + [self._cpu]
        self._mem = {"total": mem.get("MemTotal", 0), "used": mem.get("MemTotal", 0) - mem.get("MemAvailable", 0),
                     "swap_total": mem.get("SwapTotal", 0), "swap_used": mem.get("SwapTotal", 0) - mem.get("SwapFree", 0)}
        for store, reader, keys in ((self._net, self._network, ("rx", "tx", "down", "up")), (self._disk, self._disks, ("rd", "wr", "read", "write"))):
            try:
                a, b = reader()
            except (OSError, ValueError):
                continue
            if span > 0 and store[keys[0]]:
                store[keys[2]], store[keys[3]] = max(0.0, (a - store[keys[0]]) / span), max(0.0, (b - store[keys[1]]) / span)
            store[keys[0]], store[keys[1]] = a, b
            self._push(keys[2], store[keys[2]])
            self._push(keys[3], store[keys[3]])

        rows, seen, seen_io = [], {}, {}
        me = os.getuid()
        for entry in os.scandir("/proc"):
            if not entry.name.isdigit():
                continue
            try:
                stat = Path(entry.path, "stat").read_text()
                name = stat[stat.index("(") + 1:stat.rindex(")")]
                rest = stat[stat.rindex(")") + 2:].split()
                used, rss, uid = int(rest[11]) + int(rest[12]), int(rest[21]) * self._page, entry.stat().st_uid
            except (OSError, ValueError, IndexError):
                continue
            pid = int(entry.name)
            seen[pid] = used
            if rss == 0:
                continue                                                  # kernel threads
            share = (used - self._prev.get(pid, used)) / d_total * (os.cpu_count() or 1) if d_total > 0 else 0.0
            disk = -1.0                                                   # -1: not readable (someone else's program)
            try:
                io = dict(line.split(": ") for line in Path(entry.path, "io").read_text().splitlines())
                moved = int(io["read_bytes"]) + int(io["write_bytes"])
                seen_io[pid] = moved
                disk = max(0.0, (moved - self._prev_io.get(pid, moved)) / span) if span > 0 else 0.0
            except (OSError, ValueError, KeyError):
                pass
            rows.append({"pid": pid, "name": name, "cpu": round(max(0.0, share) * 100, 1), "memory": rss,
                         "memoryLabel": human_size(rss), "disk": disk, "diskLabel": "" if disk < 0 else human_size(disk) + "/s",
                         "mine": uid == me, "paused": rest[0] == "T"})
        self._prev, self._prev_io, self._prev_total, self._prev_idle, self._stamp = seen, seen_io, total, idle, now
        self._rows = rows
        self.changed.emit()

    def _signal(self, pid: int, sig: int) -> None:
        try:
            os.kill(pid, sig)
        except ProcessLookupError:
            pass
        except PermissionError:
            self.failed.emit("That program belongs to the system, so it can't be changed from here.")
        QTimer.singleShot(400, self.refresh)

    @Slot(int)
    def end(self, pid: int) -> None:
        """Ask the program to close (it may save first)."""
        self._signal(pid, signal.SIGTERM)

    @Slot(int)
    def force(self, pid: int) -> None:
        """Stop it at once, for a program that ignores End."""
        self._signal(pid, signal.SIGKILL)

    @Slot(int)
    def pause(self, pid: int) -> None:
        self._signal(pid, signal.SIGSTOP)

    @Slot(int)
    def resume(self, pid: int) -> None:
        self._signal(pid, signal.SIGCONT)

    @Slot(int, result="QVariantList")
    def details(self, pid: int) -> list:
        base, out = Path("/proc", str(pid)), []
        try:
            stat = (base / "stat").read_text()
            rest = stat[stat.rindex(")") + 2:].split()
            boot = time.time() - float(Path("/proc/uptime").read_text().split()[0])
            started = dt.datetime.fromtimestamp(boot + int(rest[19]) / self._ticks).strftime("%b %d, %H:%M")
            out += [("Process number", str(pid)), ("Started", started), ("Threads", rest[17]),
                    ("State", "Paused" if rest[0] == "T" else "Running")]
            try:
                import pwd
                out.append(("Owner", pwd.getpwuid(base.stat().st_uid).pw_name))
            except (ImportError, KeyError):
                pass
            try:
                out.append(("Program file", os.readlink(base / "exe")))
            except OSError:
                pass
            command = (base / "cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace").strip()
            if command:
                out.append(("Started as", command[:300]))
        except (OSError, ValueError, IndexError):
            return [{"name": "Status", "value": "This program has already closed."}]
        return [{"name": k, "value": v} for k, v in out]

    @Slot(int)
    def showLocation(self, pid: int) -> None:
        try:
            folder = str(Path(os.readlink(f"/proc/{pid}/exe")).parent)
        except OSError:
            self.failed.emit("The location of that program can't be read.")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(folder))


# --------------------------------------------------------------------------------------- Music + Video
class Library(QObject):
    """Media files in a folder (Music or Videos by default), newest-first for video, by name for music."""
    changed = Signal()

    def __init__(self, kinds: set, folder: Path, demo: bool, first: str = ""):
        super().__init__()
        self._kinds, self._folder, self._first = kinds, folder, first
        self._items = self._sample() if demo else self._scan()

    def _sample(self) -> list:
        if self._kinds is VIDEO:
            names = [("Fjord at dawn", "4:12"), ("Shell preview walkthrough", "2:40"), ("Northern lights timelapse", "7:05"), ("Raven study", "1:18")]
            return [{"title": t, "artist": "", "album": "", "length": d, "url": "", "path": ""} for t, d in names]
        rows = [("Glacier Mouth", "Halda", "Low Sun", "3:48"), ("Kelp Forest", "Halda", "Low Sun", "4:21"), ("Low Sun", "Halda", "Low Sun", "5:02"),
                ("Paper Boats", "Nine Lanterns", "Harbour Songs", "3:15"), ("Salt Road", "Nine Lanterns", "Harbour Songs", "4:40"),
                ("Tin Roof Rain", "Mara Quill", "Small Hours", "2:58"), ("Small Hours", "Mara Quill", "Small Hours", "3:36"),
                ("Lighthouse Keeper", "Mara Quill", "Small Hours", "4:09")]
        return [{"title": t, "artist": a, "album": al, "length": d, "url": "", "path": ""} for t, a, al, d in rows]

    def _scan(self) -> list:
        rows = []
        if self._first and Path(self._first).is_file():
            p = Path(self._first)
            rows.append({"title": p.stem, "artist": "", "album": p.parent.name, "length": "", "url": QUrl.fromLocalFile(str(p)).toString(), "path": str(p)})
        if self._folder.is_dir():
            for root, dirs, files in os.walk(self._folder):
                dirs[:] = sorted(d for d in dirs if not d.startswith("."))
                for name in sorted(files):
                    p = Path(root, name)
                    if p.suffix.lower() in self._kinds and str(p) != self._first:
                        artist, _, title = p.stem.partition(" - ")
                        rows.append({"title": title or p.stem, "artist": artist if title else "", "album": p.parent.name,
                                     "length": "", "url": QUrl.fromLocalFile(str(p)).toString(), "path": str(p)})
                if len(rows) > 5000:
                    break
        return rows

    items = Property("QVariantList", lambda self: self._items, notify=changed)
    folder = Property(str, lambda self: str(self._folder), constant=True)

    @Property("QVariantList", notify=changed)
    def albums(self):
        seen = {}
        for it in self._items:
            seen.setdefault(it["album"] or "Unknown album", it["artist"])
        return [{"name": k, "artist": v} for k, v in seen.items()]


# ----------------------------------------------------------------------------------------------- Store
CATEGORY_MAP = {"Network": "Internet", "Office": "Work", "Graphics": "Create", "Game": "Games", "AudioVideo": "Media",
                "Audio": "Media", "Video": "Media", "Development": "Develop", "Education": "Learn", "Science": "Learn",
                "Utility": "Utilities", "System": "Utilities"}
CATEGORIES = [("Discover", "star"), ("Internet", "wifi"), ("Work", "doc"), ("Create", "palette"), ("Media", "music"),
              ("Games", "apps"), ("Develop", "cpu"), ("Learn", "info"), ("Utilities", "gear")]
SAMPLE_APPS = [
    ("org.libreoffice.LibreOffice", "LibreOffice", "Documents, spreadsheets and slides", "Work", "The Document Foundation", True, False, "1.3 GB"),
    ("org.gimp.GIMP", "GIMP", "Edit photos and paint", "Create", "The GIMP team", True, False, "410 MB"),
    ("org.inkscape.Inkscape", "Inkscape", "Draw logos, icons and diagrams", "Create", "Inkscape Project", True, True, "350 MB"),
    ("org.kde.krita", "Krita", "Digital painting, from sketch to finish", "Create", "KDE", True, False, "520 MB"),
    ("org.blender.Blender", "Blender", "3D modelling, animation and video editing", "Create", "Blender Foundation", True, False, "1.1 GB"),
    ("org.videolan.VLC", "VLC", "Plays almost any video or audio file", "Media", "VideoLAN", True, False, "190 MB"),
    ("org.audacityteam.Audacity", "Audacity", "Record and edit sound", "Media", "Audacity Team", True, False, "120 MB"),
    ("org.signal.Signal", "Signal", "Private messages and calls", "Internet", "Signal Foundation", False, True, "480 MB"),
    ("org.mozilla.Thunderbird", "Thunderbird", "Email, calendar and contacts", "Internet", "Mozilla", True, False, "260 MB"),
    ("org.kde.kdenlive", "Kdenlive", "Edit video on a timeline", "Media", "KDE", True, False, "600 MB"),
    ("com.vscodium.codium", "VSCodium", "A code editor without the tracking", "Develop", "VSCodium", False, False, "390 MB"),
    ("net.ankiweb.Anki", "Anki", "Remember anything with flashcards", "Learn", "Ankitects", True, False, "310 MB"),
]


class Store(QObject):
    """App Store: finds, installs, opens and removes apps. Apps come from Flathub through the `flatpak` tool;
    the catalogue is read from Flatpak's own app list on this computer, so browsing needs no network."""
    changed = Signal()
    failed = Signal(str)
    _loaded = Signal(dict)

    def __init__(self, demo: bool):
        super().__init__()
        self._demo, self._flatpak = demo, shutil.which("flatpak")
        self._apps, self._category, self._query, self._current = {}, "Discover", "", ""
        self._busy, self._progress, self._ready = "", "", False
        self._process = None
        self._loaded.connect(self._adopt)
        self._web = self._sample_web() if demo else self._scan_web()
        if demo:
            self._adopt({i: {"id": i, "name": n, "summary": s, "category": c, "developer": d, "verified": v, "installed": inst,
                             "size": size, "version": "", "license": "", "icon": "", "web": False, "open": True, "released": "",
                             "shots": [{"url": "", "caption": c} for c in ("Main window", "Working on a project", "Preferences")],
                             "description": s + ". This is sample text shown while previewing the store without a catalogue."}
                         for i, n, s, c, d, v, inst, size in SAMPLE_APPS})
        elif self._flatpak:
            import threading
            threading.Thread(target=self._read_catalogue, daemon=True).start()
        else:
            self._ready = True

    # -- web apps installed from Huginn ----------------------------------------------------------------
    WEB_KEY = "X-Huginn-WebApp"      # Huginn's "Install as app" writes a .desktop file carrying this key

    @staticmethod
    def _web_dir() -> Path:
        return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share") / "applications"

    @staticmethod
    def _web_entry(app_id: str, name: str, url: str, command: str) -> dict:
        return {"id": app_id, "name": name, "summary": url or "Web app", "category": "Web apps", "developer": "Installed from Huginn",
                "verified": False, "installed": True, "web": True, "size": "", "version": "", "license": "", "icon": "", "open": False, "released": "", "shots": [],
                "exec": command, "description": "A website you installed as an app from Huginn. Removing it takes it out of the launcher and dock; "
                                                "the website itself and your account there are not affected."}

    def _sample_web(self) -> dict:
        rows = [("Calendar", "calendar.example"), ("News", "news.example")]
        return {f"web:{n}": self._web_entry(f"web:{n}", n, u, "") for n, u in rows}

    def _scan_web(self) -> dict:
        import configparser
        found = {}
        folder = self._web_dir()
        for path in sorted(folder.glob("*.desktop")) if folder.is_dir() else []:
            parser = configparser.ConfigParser(interpolation=None, strict=False)
            try:
                parser.read(path, encoding="utf-8")
                entry = parser["Desktop Entry"]
            except (configparser.Error, KeyError, UnicodeDecodeError):
                continue
            if entry.get(self.WEB_KEY, "false").lower() == "true":
                app_id = f"web:{path}"
                found[app_id] = self._web_entry(app_id, entry.get("Name", path.stem), entry.get("X-Huginn-Url", ""), entry.get("Exec", ""))
        return found

    def _everything(self) -> dict:
        return {**self._apps, **self._web}

    # -- catalogue ---------------------------------------------------------------------------------
    def _installed_ids(self) -> set:
        try:
            out = subprocess.run([self._flatpak, "list", "--app", "--columns=application"], capture_output=True, text=True, timeout=30).stdout
            return {line.strip() for line in out.splitlines() if "." in line}
        except (OSError, subprocess.SubprocessError):
            return set()

    def ensure_flathub(self) -> None:
        """Flathub is added while the image is built; if that build had no network, the store adds it for this person
        (no administrator needed) and fetches its catalogue, the first time it's opened online."""
        try:
            remotes = subprocess.run([self._flatpak, "remotes", "--columns=name"], capture_output=True, text=True, timeout=20).stdout.split()
            if "flathub" in remotes:
                return
            if subprocess.run([self._flatpak, "remote-add", "--user", "--if-not-exists", "flathub", "https://dl.flathub.org/repo/flathub.flatpakrepo"],
                              capture_output=True, timeout=60).returncode == 0:
                subprocess.run([self._flatpak, "update", "--user", "--appstream", "-y", "flathub"], capture_output=True, timeout=600)
        except (OSError, subprocess.SubprocessError):
            pass

    def _read_catalogue(self) -> None:
        """Parse Flathub's AppStream file that flatpak keeps on disk. Runs off the main thread."""
        import gzip
        import xml.etree.ElementTree as ET
        self.ensure_flathub()
        apps, installed = {}, self._installed_ids()
        roots = [Path("/var/lib/flatpak"), Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share") / "flatpak"]
        for root in roots:
            base = root / "appstream" / "flathub" / os.uname().machine / "active"
            source = base / "appstream.xml.gz"
            if not source.is_file():
                continue
            try:
                with gzip.open(source, "rb") as handle:
                    for _, node in ET.iterparse(handle):
                        if node.tag != "component":
                            continue
                        if node.get("type") in ("desktop-application", "desktop"):
                            bundle = node.findtext("bundle") or ""
                            app_id = bundle.split("/")[1] if bundle.count("/") >= 3 else (node.findtext("id") or "")
                            name = next((n.text for n in node.findall("name") if len(n.attrib) == 0), None)
                            if app_id and name and app_id not in apps:
                                cats = [c.text for c in node.findall("categories/category")]
                                desc = node.find("description")
                                icon = next((i.text for i in node.findall("icon") if i.get("type") == "cached" and i.get("width") == "128"), "")
                                icon_file = base / "icons" / "128x128" / icon if icon else None
                                verified = any(v.get("key") == "flathub::verification::verified" and v.text == "true" for v in node.findall("custom/value"))
                                release = node.find("releases/release")
                                shots = []
                                for shot in node.findall("screenshots/screenshot"):
                                    images = shot.findall("image")
                                    source = next((i.text for i in images if i.get("type") == "source"), None) or (images[0].text if images else None)
                                    if source and source.startswith("https://"):
                                        caption = next((c.text or "" for c in shot.findall("caption") if len(c.attrib) == 0), "")
                                        shots.append({"url": source, "caption": caption})
                                released = ""
                                if release is not None and (release.get("timestamp") or "").isdigit():
                                    released = dt.datetime.fromtimestamp(int(release.get("timestamp"))).strftime("%b %Y")
                                licence = node.findtext("project_license") or ""
                                apps[app_id] = {
                                    "id": app_id, "name": name,
                                    "summary": next((n.text or "" for n in node.findall("summary") if len(n.attrib) == 0), ""),
                                    "description": " ".join("".join(p.itertext()).strip() for p in desc.iter("p"))[:1200] if desc is not None else "",
                                    "category": next((CATEGORY_MAP[c] for c in cats if c in CATEGORY_MAP), "Utilities"),
                                    "developer": node.findtext("developer/name") or node.findtext("developer_name") or "",
                                    "verified": verified, "installed": app_id in installed, "size": "", "web": False,
                                    "version": release.get("version", "") if release is not None else "",
                                    "license": licence, "open": bool(licence) and "proprietary" not in licence.lower(),
                                    "shots": shots[:8], "released": released,
                                    "icon": QUrl.fromLocalFile(str(icon_file)).toString() if icon_file and icon_file.is_file() else ""}
                        node.clear()
            except (OSError, ET.ParseError, EOFError) as err:
                print(f"Could not read the app catalogue: {err}", file=sys.stderr)
        # Download sizes come from flatpak's own summary of the remote (already on disk; no network).
        try:
            out = subprocess.run([self._flatpak, "remote-ls", "--app", "--cached", "--columns=application,download-size", "flathub"],
                                 capture_output=True, text=True, timeout=60).stdout
            for line in out.splitlines():
                app_id, _, size = line.partition("\t")
                if app_id in apps and size.strip():
                    apps[app_id]["size"] = size.strip().replace("\u00a0", " ")
        except (OSError, subprocess.SubprocessError):
            pass
        self._loaded.emit(apps)

    def _adopt(self, apps: dict) -> None:
        self._apps, self._ready = apps, True
        self.changed.emit()

    # -- what the pages show -----------------------------------------------------------------------
    available = Property(bool, lambda self: bool(self._flatpak) or self._demo or bool(self._web), notify=changed)
    catalogue = Property(bool, lambda self: bool(self._flatpak) or self._demo, constant=True)
    ready = Property(bool, lambda self: self._ready, notify=changed)
    category = Property(str, lambda self: self._category, notify=changed)
    busy = Property(str, lambda self: self._busy, notify=changed)
    progress = Property(str, lambda self: self._progress, notify=changed)
    count = Property(int, lambda self: len(self._apps), notify=changed)
    categories = Property("QVariantList", lambda self: [{"name": n, "icon": i} for n, i in CATEGORIES], constant=True)
    current = Property("QVariantMap", lambda self: self._everything().get(self._current, {}), notify=changed)

    @Property("QVariantList", notify=changed)
    def apps(self):
        q = self._query.lower()
        if q:
            rows = [a for a in self._everything().values() if q in a["name"].lower() or q in a["summary"].lower()]
        elif self._category == "Installed":
            rows = [a for a in self._everything().values() if a["installed"]]
        else:
            rows = [a for a in self._apps.values() if self._category == "Discover" or a["category"] == self._category]
        # Verified apps first, then by name; cap the page so a 3,000-app catalogue stays quick.
        return sorted(rows, key=lambda a: (not a["verified"], a.get("web", False), a["name"].lower()))[:120]

    @Property("QVariantMap", notify=changed)
    def featured(self):
        """One app for the top of Discover: a verified app with pictures, changing each day."""
        pool = sorted((a for a in self._apps.values() if a["verified"] and a.get("shots")), key=lambda a: a["id"])
        return pool[dt.date.today().toordinal() % len(pool)] if pool else {}

    @Property("QVariantList", notify=changed)
    def fresh(self):
        """Recently updated verified apps, for a second shelf on Discover."""
        rows = [a for a in self._apps.values() if a["verified"]]
        return sorted(rows, key=lambda a: a["name"].lower(), reverse=True)[:6]

    @Property(int, notify=changed)
    def installedCount(self):
        return sum(1 for a in self._everything().values() if a["installed"])

    @Slot(str)
    def setCategory(self, name: str) -> None:
        self._category, self._current = name, ""
        self.changed.emit()

    @Slot(str)
    def setQuery(self, text: str) -> None:
        self._query, self._current = text.strip(), ""
        self.changed.emit()

    @Slot(str, result="QVariantMap")
    def info(self, app_id: str):
        """One app's entry from the catalogue (its name and icon), or {} if the catalogue doesn't know it."""
        return self._everything().get(app_id, {})

    @Slot(str)
    def show(self, app_id: str) -> None:
        self._current = app_id
        self.changed.emit()

    # -- actions -----------------------------------------------------------------------------------
    def _run(self, app_id: str, verb: str, args: list) -> None:
        if self._busy:
            self.failed.emit("One thing at a time: wait for the current install or removal to finish.")
            return
        if self._demo or not self._flatpak:
            self._apps[app_id]["installed"] = verb == "install"
            self.changed.emit()
            return
        from PySide6.QtCore import QProcess
        self._busy, self._progress = app_id, "Starting…"
        self.changed.emit()
        proc = QProcess(self)
        proc.setProcessChannelMode(QProcess.MergedChannels)

        def output():
            text = bytes(proc.readAll()).decode(errors="replace").strip().splitlines()
            if text:
                self._progress = text[-1][:90]
                self.changed.emit()

        def done(code, _status):
            ok = code == 0
            if ok:
                self._apps[app_id]["installed"] = verb == "install"
            else:
                self.failed.emit(f"Couldn't {'install' if verb == 'install' else 'remove'} {self._apps[app_id]['name']}. {self._progress}")
            self._busy, self._progress, self._process = "", "", None
            self.changed.emit()

        proc.readyRead.connect(output)
        proc.finished.connect(done)
        self._process = proc
        proc.start(self._flatpak, args)

    @Slot(str)
    def install(self, app_id: str) -> None:
        self._run(app_id, "install", ["install", "-y", "--noninteractive", "flathub", app_id])

    @Slot(str)
    def remove(self, app_id: str) -> None:
        if app_id in self._web:
            if not self._demo:
                try:
                    Path(app_id[len("web:"):]).unlink()
                except FileNotFoundError:
                    pass
                except OSError as err:
                    self.failed.emit(f"Couldn't remove {self._web[app_id]['name']}: {err.strerror or err}")
                    return
            del self._web[app_id]
            self._current = ""
            self.changed.emit()
            return
        self._run(app_id, "remove", ["uninstall", "-y", "--noninteractive", app_id])

    @Slot(str)
    def launch(self, app_id: str) -> None:
        if self._demo:
            return
        if app_id in self._web:
            import shlex
            parts = [p for p in shlex.split(self._web[app_id]["exec"]) if not p.startswith("%")]
            if parts:
                subprocess.Popen(parts, start_new_session=True)
        elif self._flatpak:
            subprocess.Popen([self._flatpak, "run", app_id], start_new_session=True)


# ------------------------------------------------------------------------------------------- Settings
class System(QObject):
    """Read-only facts for Settings > About."""

    @Property("QVariantList", constant=True)
    def about(self):
        info = {}
        try:
            for line in Path("/etc/os-release").read_text().splitlines():
                key, _, value = line.partition("=")
                info[key] = value.strip('"')
        except OSError:
            pass
        mem = ""
        try:
            mem = human_size(int(Path("/proc/meminfo").read_text().split()[1]) * 1024)
        except (OSError, ValueError, IndexError):
            pass
        uname = os.uname() if hasattr(os, "uname") else None
        disk = shutil.disk_usage(Path.home())
        rows = [("System", info.get("PRETTY_NAME", sys.platform)), ("Kernel", uname.release if uname else ""),
                ("Computer name", uname.nodename if uname else ""), ("Processor cores", str(os.cpu_count() or "")),
                ("Memory", mem), ("Storage", f"{human_size(disk.free)} free of {human_size(disk.total)}")]
        return [{"name": k, "value": v} for k, v in rows if v]


APPS = {"files": ("Files", "Files.qml"), "calendar": ("Calendar", "Calendar.qml"), "mail": ("Mail", "Mail.qml"),
        "settings": ("Settings", "SettingsApp.qml"), "monitor": ("System Monitor", "Monitor.qml"),
        "store": ("App Store", "Store.qml"), "video": ("Media Player", "Video.qml"), "music": ("Music", "Music.qml"),
        "notes": ("Notes", "Notes.qml"), "photos": ("Photos", "Photos.qml"), "documents": ("Documents", "Documents.qml"),
        "calculator": ("Calculator", "Calculator.qml"), "clock": ("Clock", "Clock.qml"), "terminal": ("Terminal", "Terminal.qml"),
        "screenshot": ("Screenshot", "Screenshot.qml"), "archives": ("Archives", "Archives.qml"), "welcome": ("Welcome", "Welcome.qml"),
        "writer": ("Writer", "Writer.qml"), "sheets": ("Sheets", "Sheets.qml"), "slides": ("Slides", "Slides.qml"),
        "passwords": ("Passwords", "Passwords.qml"), "contacts": ("Contacts", "Contacts.qml"), "weather": ("Weather", "Weather.qml"),
        "backup": ("Backup", "Backup.qml"), "disks": ("Disks", "Disks.qml"), "camera": ("Camera", "Camera.qml"),
        "recorder": ("Voice Recorder", "Recorder.qml"),
        "reminders": ("Reminders", "Reminders.qml"), "phone": ("Phone", "Phone.qml"), "print": ("Print & Scan", "PrintScan.qml"), "maps": ("Maps", "Maps.qml"), "podcasts": ("Podcasts", "Podcasts.qml"), "books": ("Books", "Books.qml"), "translate": ("Translate", "Translate.qml"), "games": ("Games", "Games.qml"),
        "authenticator": ("Authenticator", "Authenticator.qml"), "feeds": ("Feeds", "Feeds.qml"), "money": ("Money", "Money.qml"), "shortcuts": ("Shortcuts", "Shortcuts.qml"), "clips": ("Clips", "Clips.qml"), "privacy": ("Privacy Report", "Privacy.qml"), "messages": ("Messages", "Messages.qml"), "characters": ("Characters", "Characters.qml"), "fonts": ("Fonts", "Fonts.qml"), "sharing": ("Screen Sharing", "Sharing.qml"), "help": ("Help", "Help.qml"), "code": ("Code", "Code.qml"),
        "easel": ("Easel", "Easel.qml"), "scan": ("Scan", "Scan.qml"), "machines": ("Machines", "Machines.qml"), "tempo": ("Tempo", "Tempo.qml"),
        "installer": ("Install Huginn OS", "Installer.qml")}


class FileThumb(QQuickImageProvider):
    """image://filethumb/<path>?<stamp>: a small rounded picture of an image file for Files, made off the window's
    thread and kept in ~/.cache/huginn/thumbs so a folder of photos opens at once the second time."""
    W, H, R = 128, 108, 22

    def __init__(self):
        super().__init__(QQuickImageProvider.ImageType.Image, QQuickImageProvider.Flag.ForceAsynchronousImageLoading)
        self._cache = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "huginn" / "thumbs"
        self._last = ("", None)
        try:                                                     # keep the cache from growing for ever: past 5000, drop the oldest half
            kept = sorted(self._cache.glob("*.png"), key=lambda f: f.stat().st_mtime)
            for old in kept[:len(kept) // 2] if len(kept) > 5000 else []:
                old.unlink(missing_ok=True)
        except OSError:
            pass

    def requestImage(self, ident, size, requested):
        import hashlib
        from urllib.parse import unquote
        big = ident.endswith("&big")                             # the Space-bar preview: the whole picture, large, not kept
        name = ident.rsplit("?", 1)[0]
        path = name if os.path.exists(name) else unquote(name)
        none = QImage(1, 1, QImage.Format.Format_ARGB32_Premultiplied)      # "no picture": Files shows the icon instead
        none.fill(Qt.GlobalColor.transparent)
        try:
            st = os.stat(path)
        except OSError:
            return none
        kept = self._cache / (hashlib.sha1(f"{path}|{st.st_mtime_ns}|{st.st_size}".encode()).hexdigest() + ".png")
        if big and self._last[0] == kept.name:
            return self._last[1]                                   # Qt asks twice when the preview opens; don't decode twice
        if kept.exists() and not big:
            saved = QImage(str(kept))
            if not saved.isNull():
                return saved
        suffix = os.path.splitext(path)[1].lower()
        if suffix == ".pdf":
            picture = self._pdf(path, 1100 if big else self.W * 2)
        elif suffix in VIDEO:
            picture = self._video(path, 960 if big else self.W * 2)
        elif big:
            reader = QImageReader(path)
            reader.setAutoTransform(True)
            full = reader.size()
            if not full.isValid() or full.width() * full.height() > 120_000_000:
                return none
            if full.width() > 1400 or full.height() > 1000:
                reader.setScaledSize(full.scaled(QSize(1400, 1000), Qt.AspectRatioMode.KeepAspectRatio))
            picture = reader.read()
        else:
            reader = QImageReader(path)
            reader.setAutoTransform(True)
            full = reader.size()
            if not full.isValid() or full.width() * full.height() > 120_000_000:  # not a picture, or too big to be worth it
                return none
            reader.setScaledSize(full.scaled(QSize(self.W * 2, self.H * 2), Qt.AspectRatioMode.KeepAspectRatioByExpanding))
            picture = reader.read()
        if picture is None or picture.isNull():
            return none
        if big:
            self._last = (kept.name, picture)
            return picture
        out = QImage(self.W, self.H, QImage.Format.Format_ARGB32_Premultiplied)
        out.fill(Qt.GlobalColor.transparent)
        picture = picture.scaled(self.W, self.H, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
        painter = QPainter(out)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        shape = QPainterPath()
        shape.addRoundedRect(0, 0, self.W, self.H, self.R, self.R)
        painter.setClipPath(shape)
        painter.drawImage((self.W - picture.width()) // 2, 0 if suffix == ".pdf" else (self.H - picture.height()) // 2, picture)
        if suffix in VIDEO:                                       # a small play mark, so a video isn't taken for a photo
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(0, 0, 0, 150))
            painter.drawEllipse(self.W - 40, self.H - 40, 30, 30)
            mark = QPainterPath()
            mark.moveTo(self.W - 29, self.H - 32)
            mark.lineTo(self.W - 29, self.H - 18)
            mark.lineTo(self.W - 17, self.H - 25)
            mark.closeSubpath()
            painter.setBrush(QColor(255, 255, 255, 235))
            painter.drawPath(mark)
        painter.end()
        try:
            self._cache.mkdir(parents=True, exist_ok=True)
            out.save(str(kept), "PNG")
        except OSError:
            pass
        return out


    def _pdf(self, path: str, width: int):
        """The first page, on white."""
        try:
            from PySide6.QtPdf import QPdfDocument
        except ImportError:
            return None
        doc = QPdfDocument(None)
        try:
            if doc.load(path) != QPdfDocument.Error.None_ or doc.pageCount() < 1:
                return None
            page = doc.pagePointSize(0)
            if page.width() <= 0 or page.height() <= 0:
                return None
            scale = width / page.width()
            shot = doc.render(0, QSize(int(page.width() * scale), int(page.height() * scale)))
        finally:
            doc.close()
        if shot.isNull():
            return None
        paper = QImage(shot.size(), QImage.Format.Format_RGB32)
        paper.fill(Qt.GlobalColor.white)
        painter = QPainter(paper)
        painter.drawImage(0, 0, shot)
        painter.end()
        return paper

    def _video(self, path: str, width: int):
        """One frame a few seconds in (the very start is so often black), by way of ffmpeg."""
        tool = shutil.which("ffmpeg")
        if not tool:
            return None
        for at in ("3", "0"):
            try:
                done = subprocess.run([tool, "-v", "error", "-nostdin", "-ss", at, "-i", path, "-frames:v", "1", "-vf", f"scale={width}:-2",
                                       "-f", "image2pipe", "-vcodec", "png", "-"], capture_output=True, timeout=20)
            except (OSError, subprocess.SubprocessError):
                return None
            if done.returncode == 0 and done.stdout:
                frame = QImage.fromData(done.stdout, "PNG")
                if not frame.isNull():
                    return frame
        return None


class EditView(QQuickImageProvider):
    """image://photoedit/view/<version>/<crop 0 or 1> and image://photoedit/filter/<name>/<version>: the picture being
    edited, as it looks with the edit so far (worked out on a smaller copy)."""

    def __init__(self, photos):
        super().__init__(QQuickImageProvider.ImageType.Image)
        self.photos = photos

    def requestImage(self, ident, size, requested):
        session = self.photos._session
        if session is None:
            return QImage(1, 1, QImage.Format.Format_ARGB32)
        parts = ident.split("/")
        try:
            pic = session.filter_thumb(parts[1]) if parts[0] == "filter" else session.plain() if parts[-1] == "orig" else session.preview(crop=parts[-1] != "0")
        except Exception:                                          # noqa: BLE001  (a picture mid-change: show nothing rather than fall over)
            return QImage(1, 1, QImage.Format.Format_ARGB32)
        pic = pic.convert("RGBA")
        data = pic.tobytes("raw", "RGBA")
        image = QImage(data, pic.width, pic.height, pic.width * 4, QImage.Format.Format_RGBA8888).copy()
        if size is not None:
            size.setWidth(image.width())
            size.setHeight(image.height())
        return image


class RoundThumb(QQuickImageProvider):
    """image://roundthumb/<path>: a picture for the Photos wall, cropped to 4:3 and cut to rounded corners here.
    Doing it in the picture, not with a shader, means it looks the same whichever way the desktop draws."""
    W, H, R = 420, 315, 19

    def __init__(self):
        super().__init__(QQuickImageProvider.ImageType.Image)

    def requestImage(self, ident, size, requested):
        from urllib.parse import unquote
        name = ident.rsplit("?", 1)[0]                   # "?<stamp>" only makes the address new after a rotate
        path = name if os.path.exists(name) else unquote(name)
        reader = QImageReader(path)
        reader.setAutoTransform(True)
        full = reader.size()
        if full.isValid():                               # decode small: these are thumbnails
            reader.setScaledSize(full.scaled(QSize(self.W * 2, self.H * 2), Qt.AspectRatioMode.KeepAspectRatioByExpanding))
        picture = reader.read()
        out = QImage(self.W, self.H, QImage.Format.Format_ARGB32_Premultiplied)
        out.fill(Qt.GlobalColor.transparent)
        if picture.isNull():
            return out
        picture = picture.scaled(self.W, self.H, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
        painter = QPainter(out)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        shape = QPainterPath()
        shape.addRoundedRect(0, 0, self.W, self.H, self.R, self.R)
        painter.setClipPath(shape)
        painter.drawImage((self.W - picture.width()) // 2, (self.H - picture.height()) // 2, picture)
        painter.end()
        return out


def apply_ui_scale() -> None:
    """Accessibility's "Make everything bigger": Qt scales the whole window (text, controls, pictures) when it starts."""
    if os.environ.get("QT_SCALE_FACTOR"):
        return
    try:
        saved = json.loads((Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "huginn-shell" / "settings.json").read_text(encoding="utf-8"))
        scale = float(saved.get("uiScale", "1"))
    except (OSError, ValueError, TypeError, AttributeError):
        return
    if 1.0 < scale <= 2.0:
        os.environ["QT_SCALE_FACTOR"] = f"{scale:g}"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("app", choices=sorted(APPS))
    ap.add_argument("target", nargs="?", default="", help="a folder (files) or a media file (video, music) to open")
    ap.add_argument("--demo", action="store_true")
    ap.add_argument("--shot", metavar="PNG")
    ap.add_argument("--page", default="", help="settings, clock, welcome: page to open")
    ap.add_argument("--background", action="store_true", help="mail: start with no window, to watch the inbox")
    ap.add_argument("--first-run", action="store_true", help="welcome: show only if it has never been shown")
    ap.add_argument("--realm", default="")
    ap.add_argument("--run", nargs=argparse.REMAINDER, default=None, help="terminal: run this command instead of the shell (x-terminal-emulator -e)")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--dark", action="store_true")
    mode.add_argument("--light", action="store_true")
    args = ap.parse_args()

    title, qml = APPS[args.app]
    welcomed = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "huginn-shell" / "welcomed"
    if args.app == "welcome" and args.first_run:
        if welcomed.exists():
            return 0                                     # the tour shows itself once
        try:
            welcomed.parent.mkdir(parents=True, exist_ok=True)
            welcomed.touch()
        except OSError:
            pass
    apply_ui_scale()
    app = QGuiApplication(sys.argv[:1])
    app.setApplicationName(title)
    app.setDesktopFileName(f"huginn-{args.app}")
    tokens, settings, theme = make_theme(args.dark, args.light, args.realm, persist=not args.shot, app=args.app)   # each app: its own colour

    sp = QStandardPaths
    target = Path(args.target).expanduser() if args.target else None
    if args.app == "files":
        backend = Files(target if target and target.exists() else Path.home(), persist=not (args.shot or args.demo))
    elif args.app == "calendar":
        backend = Calendar(args.demo, target)
    elif args.app == "mail":
        import huginn_mail
        backend = huginn_mail.Mail(args.demo, None, args.target or "")
        if args.background and not (backend.hasAccount and backend.stayOn):
            backend.stop()
            return 0
        if not (args.demo or args.shot) and not backend.listen(show=not args.background):
            backend.stop()                                         # Mail is already open: it has the link now
            return 0
        app.setQuitOnLastWindowClosed(False)                       # closing the window can leave Mail watching the inbox
        app.aboutToQuit.connect(backend.stop)
    elif args.app == "monitor":
        backend = Monitor()
    elif args.app == "store":
        backend = Store(args.demo)
    elif args.app == "music":
        backend = Library(AUDIO, Path(sp.writableLocation(sp.MusicLocation) or Path.home() / "Music"), args.demo, str(target or ""))
    elif args.app == "video":
        backend = Library(VIDEO, Path(sp.writableLocation(sp.MoviesLocation) or Path.home() / "Videos"), args.demo, str(target or ""))
    elif args.app == "notes":
        backend = Notes(target)
    elif args.app == "photos":
        backend = Photos(target)
    elif args.app == "documents":
        backend = Documents(target)
    elif args.app == "calculator":
        backend = Calculator()
    elif args.app == "clock":
        backend = Clock()
    elif args.app == "terminal":
        backend = Terminal(settings, target, args.run)
        app.aboutToQuit.connect(backend.stop)
    elif args.app == "screenshot":
        backend = Capture(str(target) if target and target.is_file() else "")
        backend._framing = args.page == "frame" and bool(backend._image)      # for previews: start with the frame up
    elif args.app == "archives":
        backend = Archives(target)
    elif args.app in ("passwords", "contacts", "weather", "backup", "disks", "camera", "recorder"):
        import huginn_more
        backend = {"passwords": lambda: huginn_more.Vault(None, args.demo),
                   "contacts": lambda: huginn_more.Contacts(args.demo), "weather": lambda: huginn_more.Weather(args.demo),
                   "backup": lambda: huginn_more.Backup(args.demo), "disks": lambda: huginn_more.Disks(args.demo),
                   "camera": lambda: huginn_more.Shelf("camera", args.demo), "recorder": lambda: huginn_more.Shelf("recorder", args.demo)}[args.app]()
        if args.app == "contacts" and target and target.is_file():
            QTimer.singleShot(0, lambda: backend.importFile(str(target)))      # opened on a .vcf: bring its people in
    elif args.app == "reminders":
        import huginn_reminders
        backend = huginn_reminders.Reminders(args.demo)
    elif args.app in ("phone", "print", "maps", "podcasts", "books", "translate"):
        import huginn_extra
        backend = huginn_extra.make(args.app, args.demo, args.target if args.app in ("phone", "maps") else target)
    elif args.app == "games":
        import huginn_games
        backend = huginn_games.Games(args.demo, target)
        app.aboutToQuit.connect(backend.leaving)
    elif args.app == "feeds":
        import huginn_feeds
        backend = huginn_feeds.Feeds(args.demo, args.target)
    elif args.app == "money":
        import huginn_money
        backend = huginn_money.Money(args.demo, target)
    elif args.app == "shortcuts":
        import huginn_shortcuts
        backend = huginn_shortcuts.Shortcuts(args.demo)
    elif args.app == "clips":
        import huginn_clips
        clips_frames = huginn_clips.FrameProvider()
        backend = huginn_clips.Clips(args.demo, target, provider=clips_frames)
        app.aboutToQuit.connect(backend.leaving)
    elif args.app == "privacy":
        import huginn_privacy
        backend = huginn_privacy.Privacy(args.demo)
    elif args.app == "messages":
        import huginn_messages
        if args.background and not args.demo and not ((huginn_messages.HOME / "signed-in").exists() and huginn_messages.Messages.stay_wanted()):
            return 0                                               # nothing to keep an eye on
        backend = huginn_messages.Messages(args.demo)
        if not (args.demo or args.shot) and not backend.listen(show=not args.background):
            return 0                                               # Messages was already running: it came forward
        app.setQuitOnLastWindowClosed(args.demo or bool(args.shot) or not backend.stayOn)
        app.aboutToQuit.connect(backend.stop)
    elif args.app == "characters":
        import huginn_chars
        backend = huginn_chars.Characters(args.demo)
    elif args.app == "fonts":
        import huginn_fonts
        backend = huginn_fonts.Fonts(args.demo, str(target or ""))
    elif args.app == "sharing":
        import huginn_sharing
        backend = huginn_sharing.Sharing(args.demo)
        app.aboutToQuit.connect(backend.leaving)
    elif args.app == "help":
        import huginn_help
        backend = huginn_help.Help(args.demo, args.target or "")
    elif args.app == "code":
        import huginn_code
        backend = huginn_code.Code(args.demo, str(target or ""), shell_class=Shell, settings=settings, trash=move_to_trash)
        if not (args.demo or args.shot) and not backend.listen(str(target or "")):
            return 0                                               # Code was already open: the file went to it
        app.aboutToQuit.connect(backend.leaving)
    elif args.app == "easel":
        import huginn_easel_ui
        from PySide6.QtQml import qmlRegisterType
        qmlRegisterType(huginn_easel_ui.EaselView, "Huginn.Easel", 1, 0, "EaselView")
        backend = huginn_easel_ui.Easel(args.demo, str(target or ""))
    elif args.app == "installer":
        import huginn_installer
        backend = huginn_installer.Installer(args.demo)
    elif args.app == "tempo":
        import huginn_tempo
        backend = huginn_tempo.Tempo(args.demo)
        app.aboutToQuit.connect(backend.leaving)
        if target is not None and not args.demo:                   # a song folder, a MIDI file or a sound to bring in
            if target.is_dir() and target.suffix == ".tempo":
                backend.openProject(str(target))
            elif target.is_file():
                backend.importFiles([str(target)])
    elif args.app == "machines":
        import huginn_machines
        from PySide6.QtQml import qmlRegisterType
        qmlRegisterType(huginn_machines.Screen, "Huginn.Machines", 1, 0, "MachineScreen")
        backend = huginn_machines.Machines(args.demo)
        app.aboutToQuit.connect(backend.leaving)          # running machines are saved, to carry on next time
    elif args.app == "scan":
        import huginn_scan
        backend = huginn_scan.Scan(args.demo)
    elif args.app == "settings":
        import huginn_settings
        backend = huginn_settings.SystemSettings(args.demo, settings)
    elif args.app == "authenticator":
        import huginn_auth
        backend = huginn_auth.Authenticator(None, args.demo)
    elif args.app in ("writer", "sheets", "slides"):
        import huginn_office
        backend = {"writer": huginn_office.Writer, "sheets": huginn_office.Sheets, "slides": huginn_office.Slides}[args.app](target)
    else:
        backend = System()                               # settings and welcome

    engine = QQmlApplicationEngine()
    ctx = engine.rootContext()
    ctx.setContextProperty("Theme", theme)
    ctx.setContextProperty("Settings", settings)
    ctx.setContextProperty("Backend", backend)
    ctx.setContextProperty("demo", args.demo)
    ctx.setContextProperty("startPage", args.page)
    ctx.setContextProperty("startHidden", bool(args.background))
    logo = next((str(f) for f in (Path("/usr/share/icons/hicolor/256x256/apps/huginn-os.png"), HERE.parent / "config/overlay/usr/share/icons/hicolor/256x256/apps/huginn-os.png") if f.is_file()), "")
    ctx.setContextProperty("osLogo", QUrl.fromLocalFile(logo).toString() if logo else "")
    if args.app == "photos":
        engine.addImageProvider("roundthumb", RoundThumb())
        engine.addImageProvider("photoedit", EditView(backend))
    if args.app == "files":
        engine.addImageProvider("filethumb", FileThumb())
    if args.app == "clips":
        engine.addImageProvider("clips", clips_frames)
    if args.app == "easel":
        engine.addImageProvider("easel", huginn_easel_ui.EaselThumbs(backend))
    if args.app == "code":
        engine.addImageProvider("minimap", huginn_code.MinimapProvider(backend))
    if args.app == "scan":
        engine.addImageProvider("scan", huginn_scan.ScanImages(backend))
    if args.app in ("settings", "store"):
        from huginn_shell import SysIcon
        engine.addImageProvider("sysicon", SysIcon())
        import huginn_updates
        updates = huginn_updates.Updates(args.demo, settings)
        ctx.setContextProperty("Updates", updates)
        if args.app == "settings":
            import huginn_accounts
            accounts = huginn_accounts.Accounts(args.demo)
            ctx.setContextProperty("Accounts", accounts)
        updates.said.connect(lambda msg, bad: backend.said.emit(msg, bad) if hasattr(backend, "said") else None)
    engine.load(QUrl.fromLocalFile(str(HERE / "qml" / qml)))
    if not engine.rootObjects():
        return 1
    if args.shot:
        window = engine.rootObjects()[0]

        def grab():
            window.grabWindow().save(args.shot)
            app.quit()
        QTimer.singleShot(4800 if args.app == "monitor" else int(os.environ.get("HUGINN_SHOT_DELAY", "900")), grab)
    code = app.exec()
    del engine
    return code


if __name__ == "__main__":
    sys.exit(main())
