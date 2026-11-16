"""Settings › Desktop & Dock: the parts of it the shell keeps in files of its own — the dock's stacks
(~/.config/huginn-shell/stacks.json) and Today (today.json). The shell watches both and follows changes."""
from __future__ import annotations

import json
import os
from pathlib import Path

from PySide6.QtCore import Property, QObject, Signal, Slot

CONFIG = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "huginn-shell"
STACKS, TODAY = CONFIG / "stacks.json", CONFIG / "today.json"
CITIES = ["Reykjavík", "London", "Paris", "Berlin", "New York", "Chicago", "Los Angeles", "Tokyo", "Sydney", "Singapore", "Dubai", "São Paulo"]


def _read(path: Path, default: dict) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return {**default, **data} if isinstance(data, dict) else dict(default)
    except (OSError, ValueError):
        return dict(default)


def _write(path: Path, data: dict) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        part = path.with_suffix(".saving")
        part.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
        part.replace(path)
    except OSError:
        pass


class DeskPrefs(QObject):
    changed = Signal()

    def __init__(self):
        super().__init__()
        self._stacks = _read(STACKS, {"folders": [str(Path.home() / "Downloads")], "sort": "date", "view": "list", "clear30": False})
        self._today = _read(TODAY, {"islands": {"month": True, "weather": True, "agenda": True, "clocks": True}, "clocks": ["Reykjavík", "New York", "Tokyo"]})

    def _fresh(self) -> None:   # the dock may have changed them meanwhile (a folder added); start from what's saved
        self._stacks = _read(STACKS, self._stacks)
        self._today = _read(TODAY, self._today)

    @Slot(str, str)
    def setStack(self, key: str, value: str) -> None:
        self._fresh()
        if key in ("sort", "view"):
            self._stacks[key] = value
        elif key == "clear30":
            self._stacks[key] = value == "true"
        _write(STACKS, self._stacks)
        self.changed.emit()

    @Slot(str, bool)
    def setIsland(self, name: str, on: bool) -> None:
        self._fresh()
        self._today.setdefault("islands", {})[name] = on
        _write(TODAY, self._today)
        self.changed.emit()

    @Slot(str, bool)
    def setClock(self, city: str, on: bool) -> None:
        self._fresh()
        clocks = [c for c in self._today.get("clocks", []) if c != city]
        if on:
            clocks.append(city)
        self._today["clocks"] = clocks[:4]
        _write(TODAY, self._today)
        self.changed.emit()

    stacks = Property("QVariantMap", lambda self: self._stacks, notify=changed)
    today = Property("QVariantMap", lambda self: self._today, notify=changed)
    cities = Property("QVariantList", lambda self: CITIES, constant=True)
