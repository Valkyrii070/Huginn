"""Search everything (Super+Space): apps, files, Settings pages, sums and units, Huginn's open tabs, then the web.

Everything is looked up on this computer: nothing you type leaves it unless you choose "Search the web".
    files     a list of the names under your home folder (hidden folders and caches skipped), built in the background
              when the shell starts and kept fresh every ten minutes; searching it is a quick scan of that list
    settings  the pages of Settings, with the words people use for them
    answers   sums (+ − × ÷ ^ %, brackets), "15% of 80", units (km mi m ft cm in kg lb °C °F l gal) and "C to F"
    resume    "pick up where you left off": the newest files in the shared recent list, and paused music (MPRIS)
"""
import ast
import json
import operator
import os
import re
import shlex
import threading
import time
from pathlib import Path

from PySide6.QtCore import Property, QObject, QProcess, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices

HERE = Path(__file__).resolve().parent
for _apps in (Path("/usr/share/huginn-apps"), HERE.parent / "apps"):         # huginn_recent lives with the apps
    if (_apps / "huginn_recent.py").exists() and str(_apps) not in __import__("sys").path:
        __import__("sys").path.append(str(_apps))
        break
SETTINGS_QML = (Path("/usr/share/huginn-apps/qml/SettingsApp.qml"), HERE.parent / "apps" / "qml" / "SettingsApp.qml")
STATE = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local/state") / "huginn"
SKIP_DIRS = {"node_modules", "__pycache__", "site-packages", "venv", ".venv", "snap", "build", "dist", "target"}
MAX_FILES = 150000
# The words people use for each Settings page, beside its own title and description.
SETTINGS_WORDS = {
    "appearance": "dark light mode theme realm wallpaper background colour color accent transparency",
    "desktop": "dock top bar menu clock date battery percentage hide today stacks downloads snap overview spaces workspaces motion", "notifications": "do not disturb quiet alerts banners",
    "network": "wifi wi-fi wireless ethernet internet vpn hotspot proxy", "bluetooth": "headphones earbuds pair speaker mouse",
    "accounts": "google microsoft nextcloud imap sign in online", "displays": "screen monitor resolution scale night light brightness refresh hz",
    "sound": "volume speakers microphone mic audio output input", "power": "battery sleep suspend energy lid",
    "input": "keyboard mouse touchpad trackpad layout typing shortcuts", "time": "date clock timezone time zone ntp",
    "language": "region locale format numbers currency", "users": "account password login picture avatar",
    "defaults": "default apps browser mail open with startup", "privacy": "security firewall permissions camera location history lock",
    "updates": "update upgrade software version", "about": "system computer version hardware storage memory",
    "accessibility": "zoom contrast motion large text screen reader"}


def settings_pages() -> list:
    """Settings' own list of pages (read from its QML, so it never drifts): [{id, label, sub, glyph}]."""
    for path in SETTINGS_QML:
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        pages = []
        for m in re.finditer(r'\{\s*id:\s*"([a-z-]+)",\s*label:\s*"([^"]+)",\s*glyph:\s*"([a-z]+)"[^}]*?sub:\s*"([^"]*)"', text):
            pages.append({"id": m.group(1), "label": m.group(2), "glyph": m.group(3), "sub": m.group(4)})
        if pages:
            return pages
    return []


# ---------------------------------------------------------------- answers
OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv, ast.Pow: operator.pow,
       ast.Mod: operator.mod, ast.FloorDiv: operator.floordiv}


def _eval(node):
    if isinstance(node, ast.Expression):
        return _eval(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in OPS:
        a, b = _eval(node.left), _eval(node.right)
        if isinstance(node.op, ast.Pow) and abs(b) > 100:
            raise ValueError("too big")
        return OPS[type(node.op)](a, b)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
        v = _eval(node.operand)
        return -v if isinstance(node.op, ast.USub) else v
    raise ValueError("not a sum")


def plain(v: float) -> str:
    return str(int(round(v))) if abs(v - round(v)) < 1e-9 and abs(v) < 1e15 else f"{v:.10f}".rstrip("0").rstrip(".")


def nice(v: float) -> str:
    if abs(v - round(v)) < 1e-9 and abs(v) < 1e15:
        return f"{int(round(v)):,}"
    return f"{v:,.6f}".rstrip("0").rstrip(".")


UNITS = {"km": ("length", 1000), "m": ("length", 1), "cm": ("length", 0.01), "mm": ("length", 0.001), "mi": ("length", 1609.344),
         "mile": ("length", 1609.344), "miles": ("length", 1609.344), "ft": ("length", 0.3048), "feet": ("length", 0.3048),
         "in": ("length", 0.0254), "inch": ("length", 0.0254), "inches": ("length", 0.0254), "yd": ("length", 0.9144),
         "kg": ("mass", 1), "g": ("mass", 0.001), "lb": ("mass", 0.45359237), "lbs": ("mass", 0.45359237), "oz": ("mass", 0.028349523),
         "l": ("volume", 1), "ml": ("volume", 0.001), "gal": ("volume", 3.785411784), "gallons": ("volume", 3.785411784)}


def answer(text: str) -> dict:
    """{"value", "detail", "copy"} for a sum or a conversion; {} for anything else."""
    q = text.strip().lower().replace("×", "*").replace("÷", "/").replace("−", "-").replace(",", "")
    if not q:
        return {}
    m = re.fullmatch(r"(-?[\d.]+)\s*°?\s*([cf])\s*(?:to|in)\s*°?\s*([cf])", q)
    if m:
        v, a, b = float(m.group(1)), m.group(2), m.group(3)
        out = v * 9 / 5 + 32 if (a, b) == ("c", "f") else (v - 32) * 5 / 9 if (a, b) == ("f", "c") else v
        return {"value": f"{nice(round(out, 2))} °{b.upper()}", "detail": f"{nice(v)} °{a.upper()}", "copy": plain(round(out, 2))}
    m = re.fullmatch(r"(-?[\d.]+)\s*([a-z]+)\s*(?:to|in)\s*([a-z]+)", q)
    if m and m.group(2) in UNITS and m.group(3) in UNITS and UNITS[m.group(2)][0] == UNITS[m.group(3)][0]:
        v = float(m.group(1)) * UNITS[m.group(2)][1] / UNITS[m.group(3)][1]
        return {"value": f"{nice(round(v, 4))} {m.group(3)}", "detail": f"{nice(float(m.group(1)))} {m.group(2)}", "copy": plain(round(v, 4))}
    m = re.fullmatch(r"([\d.]+)\s*%\s*of\s*([\d.]+)", q)
    if m:
        v = float(m.group(1)) / 100 * float(m.group(2))
        return {"value": nice(round(v, 6)), "detail": f"{m.group(1)}% of {m.group(2)}", "copy": plain(round(v, 6))}
    if not re.search(r"\d", q) or not re.fullmatch(r"[\d\s.+\-*/^()%]+", q) or not re.search(r"[+\-*/^%]", q.strip("-")):
        return {}
    expr = re.sub(r"([\d.]+)\s*%", r"(\1/100)", q).replace("^", "**")
    # "84.60 * 15%" means 15% of 84.60; "84.60 + 15%" means 84.60 and 15% more
    expr = re.sub(r"([\d.]+)\s*([+\-])\s*\(([\d.]+)/100\)", r"(\1\2\1*\3/100)", expr)
    try:
        v = _eval(ast.parse(expr, mode="eval"))
    except (SyntaxError, ValueError, ZeroDivisionError, OverflowError, TypeError, RecursionError):
        return {}
    if isinstance(v, complex):
        return {}
    return {"value": "= " + nice(round(v, 10)), "detail": text.strip(), "copy": plain(round(v, 10))}


# ---------------------------------------------------------------- files
class FileIndex:
    """The names of the files under your home folder, for searching by name."""

    def __init__(self):
        self.paths = []
        self.ready = False
        self._lock = threading.Lock()

    def build(self) -> None:
        home = Path.home()
        found = []
        for top, dirs, files in os.walk(home):
            dirs[:] = [d for d in dirs if not d.startswith(".") and d not in SKIP_DIRS]
            for f in files:
                if not f.startswith("."):
                    found.append(os.path.join(top, f))
            if len(found) > MAX_FILES:
                break
        with self._lock:
            self.paths = found
            self.ready = True

    def find(self, q: str, limit: int = 8) -> list:
        words = [w for w in q.lower().split() if w]
        if not words:
            return []
        with self._lock:
            paths = list(self.paths)
        hits = []
        for p in paths:
            name = os.path.basename(p).lower()
            if all(w in name for w in words):
                starts = name.startswith(words[0])
                try:
                    stamp = os.path.getmtime(p)
                except OSError:
                    continue
                hits.append((0 if starts else 1, -stamp, p))
                if len(hits) > 400:
                    break
        hits.sort()
        return [p for _, _, p in hits[:limit]]


def file_row(path: str) -> dict:
    import huginn_recent
    try:
        stamp = os.path.getmtime(path)
    except OSError:
        stamp = time.time()
    row = huginn_recent._row(path, stamp)
    kind = (row["mime"] or "").split("/")[0]
    row["kind"] = {"image": "image", "audio": "music", "video": "video", "text": "doc"}.get(kind, "doc")
    row["url"] = QUrl.fromLocalFile(path).toString()
    return row


class Search(QObject):
    """The data behind Search everything (qml/Search.qml)."""
    changed = Signal()
    _found = Signal(str, "QVariantList")

    def __init__(self, apps, tabs, demo: bool):
        super().__init__()
        self._apps, self._tabs, self._demo = apps, tabs, demo
        self._text = ""
        self._files = []
        self._answer = {}
        self._settings = []
        self._resume = []
        self._pages = settings_pages()
        self._index = FileIndex()
        self._found.connect(self._got_files)
        if not demo:
            threading.Thread(target=self._index.build, daemon=True).start()
            self._refresh = QTimer(self, interval=600000, timeout=lambda: threading.Thread(target=self._index.build, daemon=True).start())
            self._refresh.start()
        try:
            self._seen = json.loads((STATE / "search.json").read_text(encoding="utf-8")).get("opened", 0)
        except (OSError, ValueError, AttributeError):
            self._seen = 0

    # what QML reads
    text = Property(str, lambda self: self._text, notify=changed)
    files = Property("QVariantList", lambda self: self._files, notify=changed)
    answer = Property("QVariantMap", lambda self: self._answer, notify=changed)
    settings = Property("QVariantList", lambda self: self._settings, notify=changed)
    resume = Property("QVariantList", lambda self: self._resume, notify=changed)
    privacyNote = Property(bool, lambda self: self._seen < 4, notify=changed)    # said the first few times only

    @Slot()
    def opened(self) -> None:
        """Search was just opened: fresh "pick up where you left off"."""
        self._seen += 1
        if not self._demo:
            try:
                STATE.mkdir(parents=True, exist_ok=True)
                (STATE / "search.json").write_text(json.dumps({"opened": self._seen}), encoding="utf-8")
            except OSError:
                pass
        self._resume = self._read_resume()
        self.changed.emit()

    def _read_resume(self) -> list:
        if self._demo:
            return [{"kind": "file", "name": "Iceland trip plan.odt", "sub": "Documents › Travel · 1:12 AM", "path": "", "app": "Writer"},
                    {"kind": "music", "name": "Paused · Northbound", "sub": "Music · Late drive", "player": ""}]
        out = []
        import huginn_recent
        for r in huginn_recent.latest(2):
            out.append({"kind": "file", "name": r["name"], "sub": f"{r['where']} · {r['when']}", "path": r["path"], "app": ""})
        out += self._paused_players()
        return out[:3]

    def _paused_players(self) -> list:
        try:
            from gi.repository import Gio, GLib
            bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
            names = bus.call_sync("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus", "ListNames", None,
                                  GLib.VariantType("(as)"), 0, 1000, None).unpack()[0]
            out = []
            for n in [n for n in names if n.startswith("org.mpris.MediaPlayer2.")][:4]:
                def get(prop):
                    return bus.call_sync(n, "/org/mpris/MediaPlayer2", "org.freedesktop.DBus.Properties", "Get",
                                         GLib.Variant("(ss)", ("org.mpris.MediaPlayer2.Player", prop)), GLib.VariantType("(v)"), 0, 800, None).unpack()[0]
                if get("PlaybackStatus") != "Paused":
                    continue
                meta = get("Metadata") or {}
                title = meta.get("xesam:title") or "Something you were listening to"
                artist = ", ".join(meta.get("xesam:artist") or [])
                out.append({"kind": "music", "name": f"Paused · {title}", "sub": artist or n.split(".")[-1].title(), "player": n})
            return out[:1]
        except Exception:                                  # noqa: BLE001  (no bus, no players: nothing to resume)
            return []

    @Slot(str)
    def find(self, text: str) -> None:
        self._text = text
        q = text.strip().lower()
        self._answer = answer(text) if q else {}
        self._settings = self._find_settings(q) if q else []
        self._files = []
        self.changed.emit()
        if not q:
            return
        if self._demo:
            if "iceland".startswith(q[:3]):
                self._files = [{"name": "Iceland trip plan.odt", "where": "Home › Documents › Travel", "when": "1:12 AM", "path": "", "kind": "doc", "url": ""},
                               {"name": "Iceland packing list.ods", "where": "Home › Documents › Travel", "when": "yesterday", "path": "", "kind": "doc", "url": ""}]
                self.changed.emit()
            return

        def look(t=text):
            paths = self._index.find(t)
            self._found.emit(t, [file_row(p) for p in paths])
        threading.Thread(target=look, daemon=True).start()

    def _got_files(self, text: str, rows: list) -> None:
        if text == self._text:                             # (an answer for something typed since is dropped)
            self._files = rows
            self.changed.emit()

    def _find_settings(self, q: str) -> list:
        out = []
        for p in self._pages:
            words = re.split(r"[\s,.&‑-]+", f"{p['label']} {p['sub']} {SETTINGS_WORDS.get(p['id'], '')}".lower())
            if p["label"].lower().startswith(q):
                out.insert(0, p)
            elif all(any(w.startswith(part) for w in words) for part in q.split()):
                out.append(p)
        return out[:4]

    # what the results do
    @Slot(str)
    def openFile(self, path: str) -> None:
        if path and not self._demo:
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    @Slot(str)
    def reveal(self, path: str) -> None:
        if path and not self._demo:
            QProcess.startDetached("python3", ["/usr/share/huginn-apps/huginn_app.py", "files", str(Path(path).parent)])

    @Slot(str)
    def openSetting(self, page: str) -> None:
        if not self._demo:
            QProcess.startDetached("python3", ["/usr/share/huginn-apps/huginn_app.py", "settings", "--page", page])

    @Slot(str)
    def web(self, text: str) -> None:
        """Only here does anything leave the computer: Huginn opens your search engine with what you typed."""
        browser = next((a for a in self._apps.all if a["name"] == "Huginn"), None)
        if self._demo or not browser or not text.strip():
            return
        try:
            argv = [p for p in shlex.split(browser.get("execRaw") or browser["exec"]) if not re.fullmatch(r"%[a-zA-Z]", p)]
        except ValueError:
            return
        QProcess.startDetached(argv[0], argv[1:] + [text.strip()])

    @Slot(str)
    def resumePlayer(self, player: str) -> None:
        if not player or self._demo:
            return
        try:
            from gi.repository import Gio
            bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
            bus.call(player, "/org/mpris/MediaPlayer2", "org.mpris.MediaPlayer2.Player", "Play", None, None, 0, 2000, None, None)
        except Exception:                                  # noqa: BLE001
            pass

    @Slot(str)
    def copy(self, text: str) -> None:
        from PySide6.QtGui import QGuiApplication
        QGuiApplication.clipboard().setText(text)
