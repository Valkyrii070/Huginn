"""The Welcome tour, run by the shell: two full-screen pages (Welcome; Make it yours), then the island that welcomed
you walks you round the desktop — the dock, the top bar, the app's own menu, windows and spaces — with a line of
light from it to each part. Once, at the first sign-in (Welcome in the apps and Help play it again).

After a big update, the same island shows only what's new (WHAT_IS_NEW below, by version), the first time you sign
in after it.

Tour also lets the tour's full-screen surface take clicks only where its island is (setMask), so you can try things
on the real desktop while it's showing.
"""
from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import Property, QObject, QRect, Signal, Slot
from PySide6.QtGui import QRegion

CONFIG = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "huginn-shell"
WELCOMED = CONFIG / "welcomed"
SEEN = CONFIG / "seen-version"
VERSION_FILES = (Path("/usr/share/huginn-os/version"), Path(__file__).resolve().parent.parent / "config/overlay/usr/share/huginn-os/version")

# What's new, by version: the steps the island shows after updating to it (each points at a part, like the tour's).
WHAT_IS_NEW = {
    "0.3": [
        {"target": "date", "title": "Today", "words": "Click the date for your month, the weather and what's coming. Type to add an event or a reminder.",
         "try": "click the date", "done": "That's Today", "check": "today"},
        {"target": "name", "title": "Every app's own menu", "words": "The app's name in the bar opens its menu: its settings at the top, then every command, which you can search.",
         "try": "click the app's name", "done": "That's its menu", "check": "menu"},
        {"target": "dock", "title": "Your downloads, in a pile", "words": "Downloads sit at the end of the dock. Drag any folder there to keep it handy too.",
         "try": "", "done": "", "check": ""},
    ],
}


def version() -> str:
    for f in VERSION_FILES:
        try:
            return f.read_text(encoding="utf-8").strip()
        except OSError:
            continue
    return ""


def newer(a: str, b: str) -> bool:
    def parts(v):
        return [int(p) if p.isdigit() else 0 for p in (v or "0").split(".")]
    return parts(a) > parts(b)


class Tour(QObject):
    changed = Signal()

    def __init__(self, demo: bool = False):
        super().__init__()
        self._demo = demo
        self._version = version()
        self._due = ""
        if not demo:
            seen = ""
            try:
                seen = SEEN.read_text(encoding="utf-8").strip()
            except OSError:
                pass
            if not WELCOMED.exists():
                self._due = "first"
            elif self._version and newer(self._version, seen) and WHAT_IS_NEW.get(self._version):
                self._due = "whatsnew"

    def _due_get(self) -> str:
        return self._due

    def _new_steps(self) -> list:
        return WHAT_IS_NEW.get(self._version, [])

    @Slot(str)
    def finished(self, kind: str) -> None:
        """The tour (or what's new) was shown: it doesn't come back by itself."""
        self._due = ""
        if self._demo:
            self.changed.emit()
            return
        try:
            CONFIG.mkdir(parents=True, exist_ok=True)
            WELCOMED.touch()
            if self._version:
                SEEN.write_text(self._version, encoding="utf-8")
        except OSError:
            pass
        self.changed.emit()

    @Slot(QObject, int, int, int, int)
    def setMask(self, window, x: int, y: int, w: int, h: int) -> None:
        """Only this part of the tour's surface takes clicks (w <= 0: all of it)."""
        if window is None:
            return
        if os.environ.get("HUGINN_DEBUG_TOUR"):
            print("tour mask", type(window).__name__, x, y, w, h, flush=True)
        if w <= 0 or h <= 0:
            window.setMask(QRegion())
        else:
            window.setMask(QRegion(QRect(x, y, w, h)))

    due = Property(str, _due_get, notify=changed)
    whatsNew = Property("QVariantList", _new_steps, notify=changed)
    live = Property(bool, lambda self: os.path.exists("/cdrom/casper/filesystem.squashfs"), constant=True)
    osVersion = Property(str, lambda self: self._version, constant=True)
