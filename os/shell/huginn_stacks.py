"""Stacks in the dock: Downloads, and any folder dragged onto the dock's end.

Each stack shows its newest files as a little pile (the top card is a download still arriving, filling up); clicked,
it opens as a list (or a grid) of its files: name, size, where it came from (the browser's `user.xdg.origin.url`, or
the app that saved it) and when. A file that lands in Downloads flies into the pile from the window in front.

Settings (~/.config/huginn-shell/stacks.json): the folders, sort ("date", "name", "kind"), view ("list", "grid") and
"clear30" (downloads older than 30 days go to the Bin; off unless turned on).
"""
from __future__ import annotations

import json
import mimetypes
import os
import shutil
import time
from pathlib import Path
from urllib.parse import urlparse

from PySide6.QtCore import Property, QFileSystemWatcher, QMimeData, QObject, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QGuiApplication

PARTS = (".part", ".crdownload", ".download", ".partial")
CONFIG = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "huginn-shell" / "stacks.json"
KINDS = {
    "image": {"png", "jpg", "jpeg", "gif", "webp", "heic", "bmp", "svg", "tif", "tiff", "avif"},
    "document": {"odt", "docx", "doc", "rtf", "txt", "md", "pdf", "epub"},
    "sheet": {"ods", "xlsx", "xls", "csv"},
    "slides": {"odp", "pptx", "ppt", "key"},
    "audio": {"mp3", "flac", "ogg", "opus", "wav", "m4a", "aac"},
    "video": {"mp4", "mkv", "webm", "mov", "avi"},
    "archive": {"zip", "tar", "gz", "xz", "bz2", "7z", "rar", "zst", "tgz"},
    "disc": {"iso", "img"},
    "package": {"deb", "flatpak", "flatpakref", "appimage", "snap"},
}
# the app whose badge sits on a file's page
KIND_APP = {"image": "photos", "document": "writer", "sheet": "sheets", "slides": "slides", "audio": "music", "video": "video",
            "archive": "files", "disc": "files", "package": "store", "pdf": "writer", "other": "files"}
APP_NAMES = {"huginn-mail": "Mail", "huginn-messages": "Messages", "huginn-screenshot": "Screenshot", "huginn-capture": "Screenshot",
             "huginn": "Huginn", "firefox": "Firefox", "chromium": "Chromium"}


def kind_of(name: str) -> str:
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if ext == "pdf":
        return "pdf"
    return next((k for k, exts in KINDS.items() if ext in exts), "other")


def human_size(n: int) -> str:
    for unit in ("bytes", "KB", "MB", "GB", "TB"):
        if n < 1000 or unit == "TB":
            return f"{n} {unit}" if unit == "bytes" else f"{n:.1f} {unit}".replace(".0 ", " ")
        n /= 1000
    return ""


def human_when(t: float, now: float | None = None) -> str:
    now = now or time.time()
    d = max(0, now - t)
    if d < 60:
        return "now"
    if d < 3600:
        return f"{int(d // 60)} min"
    if d < 86400 and time.localtime(t).tm_yday == time.localtime(now).tm_yday:
        return f"{int(d // 3600)} h"
    if d < 2 * 86400:
        return "yesterday"
    if d < 7 * 86400:
        return time.strftime("%A", time.localtime(t))
    return time.strftime("%b %-d", time.localtime(t))


def origin_of(path: Path) -> str:
    """Where a file came from: the site a browser saved it from, or the app that put it there."""
    for attr in ("user.xdg.origin.url", "user.xdg.referrer.url"):
        try:
            url = os.getxattr(path, attr).decode("utf-8", "replace")
            host = urlparse(url).hostname or ""
            if host:
                return host[4:] if host.startswith("www.") else host
        except (OSError, AttributeError):
            pass
    try:
        app = os.getxattr(path, "user.huginn.app").decode("utf-8", "replace")
        return APP_NAMES.get(app, app)
    except (OSError, AttributeError):
        return ""


class Stacks(QObject):
    changed = Signal()
    landed = Signal(str, str, str)          # a file arrived: the stack's folder, the file, its kind (the dock flies it in)

    def __init__(self, demo: bool = False, icon=None):
        super().__init__()
        self._demo = demo
        self._icon = icon or (lambda key: "")
        self._cfg = {"folders": [str(Path.home() / "Downloads")], "sort": "date", "view": "list", "clear30": False}
        self._stacks: list = []
        self._known: dict = {}               # folder -> names already seen (a new one is a landing)
        if demo:
            self._stacks = [self._demo_stack()]
            return
        try:
            saved = json.loads(CONFIG.read_text(encoding="utf-8"))
            self._cfg.update({k: v for k, v in saved.items() if k in self._cfg})
        except (OSError, ValueError):
            pass
        self._watch = QFileSystemWatcher(self)
        self._watch.directoryChanged.connect(lambda _: self._soon.start())
        try:
            CONFIG.parent.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        self._cfg_watch = QFileSystemWatcher([str(CONFIG.parent)] if CONFIG.parent.is_dir() else [], self)   # Settings › Desktop & Dock
        self._cfg_watch.directoryChanged.connect(lambda _: self._reload_cfg())
        self._soon = QTimer(self, singleShot=True, interval=250, timeout=self.refresh)
        self._tick = QTimer(self, interval=1500, timeout=self._tick_downloads)     # downloads growing: sizes
        self._tick.start()
        self._daily = QTimer(self, interval=6 * 3600 * 1000, timeout=self._clear_old)
        self._daily.start()
        QTimer.singleShot(5000, self._clear_old)
        self.refresh(first=True)

    # ------------------------------------------------------------------ reading
    def _demo_stack(self) -> dict:
        now = time.time()
        files = [("huginn-os-0.2.iso", 2_100_000_000, now - 5, "", True), ("Iceland trip plan.odt", 1_200_000, now - 120, "Mail", False),
                 ("Aurora over Þingvellir.jpg", 4_800_000, now - 3600, "unsplash.com", False), ("Budget 2027.ods", 86_000, now - 90000, "Mail", False)]
        items = [{"name": n, "path": "", "url": "", "bytes": b, "badgeUrl": self._icon(KIND_APP[kind_of(n)]), "size": human_size(b) if not p else f"{human_size(b)} of 3.2 GB", "when": human_when(t, now),
                  "time": t, "from": f, "kind": kind_of(n), "mime": mimetypes.guess_type(n)[0] or "", "badge": KIND_APP[kind_of(n)], "partial": p, "progress": 0.66 if p else 1.0, "thumb": ""}
                 for n, b, t, f, p in files]
        return {"folder": str(Path.home() / "Downloads"), "name": "Downloads", "downloads": True, "items": items, "count": len(items),
                "busy": True}

    def _read(self, folder: str) -> dict:
        path = Path(folder)
        items = []
        try:
            entries = [e for e in os.scandir(path) if not e.name.startswith(".")]
        except OSError:
            entries = []
        now = time.time()
        for e in entries:
            try:
                st = e.stat()
            except OSError:
                continue
            partial = e.name.endswith(PARTS)
            name = e.name
            for suffix in PARTS:
                if partial and name.endswith(suffix):
                    name = name[: -len(suffix)]
            if partial and name.endswith(".crdownload"):
                name = name[: -len(".crdownload")]
            kind = "folder" if e.is_dir() else kind_of(name)
            total = 0
            try:
                total = int(os.getxattr(e.path, "user.huginn.total")) if partial else 0
            except (OSError, ValueError, AttributeError):
                pass
            items.append({"name": name, "path": e.path, "url": QUrl.fromLocalFile(e.path).toString(), "bytes": st.st_size,
                          "size": ("" if kind == "folder" else human_size(st.st_size)) + (f" of {human_size(total)}" if total else ""),
                          "when": human_when(st.st_mtime, now), "time": st.st_mtime, "from": origin_of(Path(e.path)) if not partial else "",
                          "kind": kind, "mime": "inode/directory" if kind == "folder" else (mimetypes.guess_type(name)[0] or ""), "badge": KIND_APP.get(kind, "files"), "badgeUrl": self._icon(KIND_APP.get(kind, "files")), "partial": partial,
                          "progress": min(1.0, st.st_size / total) if total else (-1.0 if partial else 1.0),
                          "thumb": QUrl.fromLocalFile(e.path).toString() if kind == "image" and not partial and st.st_size < 40_000_000 else ""})
        sort = self._cfg.get("sort", "date")
        if sort == "name":
            items.sort(key=lambda i: (not i["partial"], i["name"].lower()))
        elif sort == "kind":
            items.sort(key=lambda i: (not i["partial"], i["kind"], -i["time"]))
        else:
            items.sort(key=lambda i: (not i["partial"], -i["time"]))
        downloads = path == Path.home() / "Downloads"
        return {"folder": folder, "name": "Downloads" if downloads else path.name, "downloads": downloads, "items": items[:60],
                "count": len(items), "busy": any(i["partial"] for i in items)}

    @Slot()
    def refresh(self, first: bool = False) -> None:
        if self._demo:
            return
        stacks = []
        for folder in self._cfg["folders"]:
            if not Path(folder).is_dir():
                if Path(folder) == Path.home() / "Downloads":
                    Path(folder).mkdir(parents=True, exist_ok=True)
                else:
                    continue
            if folder not in self._watch.directories():
                self._watch.addPath(folder)
            st = self._read(folder)
            names = {i["name"] for i in st["items"] if not i["partial"]}
            seen = self._known.get(folder)
            if seen is not None and not first:
                for i in st["items"]:
                    if not i["partial"] and i["name"] not in seen and time.time() - i["time"] < 120:
                        self.landed.emit(folder, i["name"], i["kind"])
                        break
            self._known[folder] = names
            stacks.append(st)
        self._stacks = stacks
        self.changed.emit()

    def _tick_downloads(self) -> None:
        if any(s["busy"] for s in self._stacks):
            self.refresh()

    def _reload_cfg(self) -> None:
        try:
            saved = json.loads(CONFIG.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        new = dict(self._cfg)
        new.update({k: v for k, v in saved.items() if k in self._cfg})
        if new != self._cfg:
            self._cfg = new
            self.refresh()

    def _save(self) -> None:
        try:
            CONFIG.parent.mkdir(parents=True, exist_ok=True)
            CONFIG.write_text(json.dumps(self._cfg, indent=1), encoding="utf-8")
        except OSError:
            pass

    def _clear_old(self) -> None:
        """Clear out: downloads older than 30 days go to the Bin (only if turned on)."""
        if self._demo or not self._cfg.get("clear30"):
            return
        from gi.repository import Gio
        cutoff = time.time() - 30 * 86400
        folder = Path.home() / "Downloads"
        for e in os.scandir(folder) if folder.is_dir() else []:
            try:
                if e.stat().st_mtime < cutoff and not e.name.startswith("."):
                    Gio.File.new_for_path(e.path).trash(None)
            except Exception:  # noqa: BLE001 — a file that won't go stays
                pass
        self.refresh()

    # ------------------------------------------------------------------ what the dock does
    @Slot(str)
    def open(self, path: str) -> None:
        if path and not self._demo:
            from PySide6.QtGui import QDesktopServices
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    @Slot(str)
    def showInFiles(self, path: str) -> None:
        if not path or self._demo:
            return
        from PySide6.QtCore import QProcess
        target = path if os.path.isdir(path) else str(Path(path).parent)
        here = Path(__file__).resolve().parent
        files_app = next((p for p in (here.parent / "apps" / "huginn_app.py", Path("/usr/share/huginn-apps/huginn_app.py")) if p.exists()), None)
        if files_app:
            QProcess.startDetached("python3", [str(files_app), "files", target])
        else:
            QProcess.startDetached("xdg-open", [target])

    @Slot(str)
    def copy(self, path: str) -> None:
        data = QMimeData()
        data.setUrls([QUrl.fromLocalFile(path)])
        data.setData("x-special/gnome-copied-files", f"copy\n{QUrl.fromLocalFile(path).toString()}".encode())
        QGuiApplication.clipboard().setMimeData(data)

    @Slot(str, str, result=bool)
    def moveTo(self, path: str, where: str) -> bool:
        """Move to one of the home folders (Desktop, Documents, Pictures…) or any folder path."""
        dest = Path(where) if os.path.isabs(where) else Path.home() / where
        if self._demo or not path or not dest.is_dir():
            return False
        try:
            shutil.move(path, str(dest / Path(path).name))
        except OSError:
            return False
        self.refresh()
        return True

    @Slot(str, str, result=bool)
    def rename(self, path: str, new: str) -> bool:
        new = new.strip()
        if self._demo or not path or not new or "/" in new:
            return False
        target = Path(path).with_name(new)
        if target.exists():
            return False
        try:
            os.rename(path, target)
        except OSError:
            return False
        self.refresh()
        return True

    @Slot(str)
    def trash(self, path: str) -> None:
        if self._demo or not path:
            return
        from gi.repository import Gio
        try:
            Gio.File.new_for_path(path).trash(None)
        except Exception:  # noqa: BLE001
            pass
        self.refresh()

    @Slot(str, "QVariantList")
    def dropInto(self, folder: str, urls: list) -> None:
        """Files dropped on a stack's tile go into its folder."""
        if self._demo:
            return
        for u in urls:
            src = QUrl(u).toLocalFile() if not isinstance(u, QUrl) else u.toLocalFile()
            if not src or not os.path.exists(src) or Path(src).parent == Path(folder):
                continue
            try:
                shutil.move(src, os.path.join(folder, Path(src).name))
            except OSError:
                pass
        self.refresh()

    @Slot(str, result=bool)
    def addFolder(self, url: str) -> bool:
        """A folder dragged onto the dock's end becomes a stack."""
        folder = QUrl(url).toLocalFile() if "://" in url else url
        if not folder or not os.path.isdir(folder) or folder in self._cfg["folders"]:
            return False
        self._cfg["folders"].append(folder)
        self._save()
        self.refresh()
        return True

    @Slot(str)
    def removeFolder(self, folder: str) -> None:
        if folder in self._cfg["folders"] and Path(folder) != Path.home() / "Downloads":
            self._cfg["folders"].remove(folder)
            self._save()
            self.refresh()

    @Slot(str, str)
    def setOption(self, key: str, value: str) -> None:
        if key in ("sort", "view") or key == "clear30":
            self._cfg[key] = value == "true" if key == "clear30" else value
            self._save()
            self.refresh()
            if key == "clear30" and self._cfg[key]:
                self._clear_old()

    stacks = Property("QVariantList", lambda self: self._stacks, notify=changed)
    options = Property("QVariantMap", lambda self: {k: self._cfg[k] for k in ("sort", "view", "clear30")}, notify=changed)
