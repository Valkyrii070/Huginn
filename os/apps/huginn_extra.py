#!/usr/bin/env python3
"""More Huginn apps: Phone, Print & Scan, Maps, Podcasts, Books, Translate.

Each is a thin, honest front for something the system already does well (KDE Connect, CUPS, SANE, OpenStreetMap,
podcast feeds, EPUB files, Argos Translate). Where the thing underneath isn't installed or isn't reachable, the app
says so in plain words instead of pretending.
"""
import datetime as dt
import html
import json
import os
import re
import shutil
import subprocess
import threading
import time
import urllib.parse
import urllib.request
import uuid
import zipfile
from pathlib import Path

from PySide6.QtCore import Property, QObject, QStandardPaths, QTimer, QUrl, Signal, Slot

DATA_HOME = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share") / "huginn"
CACHE_HOME = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "huginn"
AGENT = "Huginn/1.0 (desktop app; https://github.com/Valkyrii070/Huginn)"


def run(args: list, timeout: float = 15, feed: str = None) -> tuple:
    """Run a system tool. Returns (exit code, what it printed); 127 when the tool isn't installed."""
    try:
        done = subprocess.run(args, capture_output=True, text=True, timeout=timeout, input=feed, stdin=None if feed is not None else subprocess.DEVNULL)
        return done.returncode, (done.stdout or "") + (done.stderr or "")
    except FileNotFoundError:
        return 127, ""
    except subprocess.TimeoutExpired:
        return 124, "It took too long to answer."
    except OSError as err:
        return 126, str(err)


def fetch(url: str, timeout: float = 20, limit: int = 8_000_000) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": AGENT, "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=timeout) as reply:
        return reply.read(limit)


def plain_net_error(err: Exception) -> str:
    text = str(getattr(err, "reason", err))
    if "Name or service" in text or "resolution" in text or "unreachable" in text:
        return "This computer seems to be offline."
    if "timed out" in text:
        return "The server took too long to answer."
    return f"Couldn't reach it: {text}"[:160]


def size_words(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit in ("B", "KB") else f"{n:.1f} {unit}"
        n /= 1024
    return ""


def recent(suffixes: tuple = (), most: int = 14) -> list:
    """Files you've lately touched in Documents, Downloads, Pictures and the Desktop, newest first."""
    out = []
    for name in ("Documents", "Downloads", "Pictures", "Desktop"):
        folder = Path.home() / name
        try:
            for entry in os.scandir(folder):
                if entry.is_file() and not entry.name.startswith(".") and (not suffixes or entry.name.lower().endswith(suffixes)):
                    st = entry.stat()
                    out.append((st.st_mtime, {"name": entry.name, "path": entry.path, "where": name, "size": size_words(st.st_size)}))
        except OSError:
            continue
    return [row for _stamp, row in sorted(out, key=lambda x: -x[0])[:most]]


class Worker(QObject):
    """Things that take a moment run off the screen's thread; the answer comes back on it."""
    _back = Signal(object)

    def __init__(self):
        super().__init__()
        self._back.connect(lambda fn: fn())

    def bg(self, work, then=None) -> None:
        def go():
            try:
                result = work()
            except Exception as err:                               # every failure becomes a result the screen can show
                result = err
            if then:
                self._back.emit(lambda: then(result))
        threading.Thread(target=go, daemon=True).start()


# =================================================================================================== Phone
class Phone(Worker):
    """Your phone, through KDE Connect: send files and the clipboard both ways, ring it, see its battery.
    The phone needs the KDE Connect app and the same network; pairing is confirmed on the phone."""
    changed = Signal()
    said = Signal(str, bool)
    TOOL = "kdeconnect-cli"

    def __init__(self, demo: bool = False, target=None):
        super().__init__()
        self._demo, self._devices, self._picked, self._busy = demo, [], "", False
        self._ready = demo or shutil.which(self.TOOL) is not None
        self._waiting = self._paths(target)
        if demo:
            self._devices = [{"id": "a1", "name": "Astrid's Pixel", "paired": True, "here": True, "battery": 82, "charging": False},
                             {"id": "b2", "name": "Old tablet", "paired": True, "here": False, "battery": -1, "charging": False},
                             {"id": "c3", "name": "Sam's phone", "paired": False, "here": True, "battery": -1, "charging": False}]
            self._picked = "a1"
            return
        self._tick = QTimer(self)
        self._tick.setInterval(5000)
        self._tick.timeout.connect(self.refresh)
        self._tick.start()
        self.refresh()

    @staticmethod
    def _paths(target) -> list:
        text = str(target or "")
        if text.startswith("["):
            try:
                return [p for p in json.loads(text) if isinstance(p, str) and os.path.isfile(p)]
            except ValueError:
                return []
        return [text] if text and os.path.isfile(text) else []

    @staticmethod
    def read_list(text: str) -> list:
        """`kdeconnect-cli -l` prints "- Name: id (paired and reachable)" per device."""
        out = []
        for line in text.splitlines():
            m = re.match(r"^\s*-\s+(.*?):\s+([A-Za-z0-9_\-]{6,})\s+\(([^)]*)\)\s*$", line)
            if m:
                state = m.group(3).lower()
                out.append({"id": m.group(2), "name": m.group(1), "paired": "paired" in state and "unpaired" not in state, "here": "reachable" in state and "unreachable" not in state,
                            "battery": -1, "charging": False})
        return out

    def _battery(self, ident: str) -> tuple:
        def ask(what):
            code, out = run(["gdbus", "call", "--session", "--dest", "org.kde.kdeconnect", "--object-path", f"/modules/kdeconnect/devices/{ident}/battery",
                             "--method", "org.freedesktop.DBus.Properties.Get", "org.kde.kdeconnect.device.battery", what], 4)
            return out if code == 0 else ""
        level = re.search(r"<(?:int32 )?(-?\d+)>", ask("charge"))
        return (int(level.group(1)) if level else -1), "true" in ask("isCharging")

    @Slot()
    def refresh(self) -> None:
        if self._demo or not self._ready or self._busy:
            return
        self._busy = True

        def work():
            code, out = run([self.TOOL, "-l"], 8)
            devices = self.read_list(out) if code == 0 else []
            for d in devices:
                if d["paired"] and d["here"]:
                    d["battery"], d["charging"] = self._battery(d["id"])
            return devices

        def then(devices):
            self._busy = False
            if isinstance(devices, Exception):
                return
            if devices != self._devices:
                self._devices = devices
                if not any(d["id"] == self._picked for d in devices):
                    best = sorted(devices, key=lambda d: (not (d["paired"] and d["here"]), not d["here"]))
                    self._picked = best[0]["id"] if best else ""
                self.changed.emit()
        self.bg(work, then)

    ready = Property(bool, lambda self: self._ready, constant=True)
    devices = Property("QVariantList", lambda self: self._devices, notify=changed)
    picked = Property(str, lambda self: self._picked, notify=changed)
    waiting = Property("QVariantList", lambda self: [{"name": Path(p).name, "path": p} for p in self._waiting], notify=changed)     # handed over by Files, to send

    @Property("QVariantMap", notify=changed)
    def device(self):
        return next((d for d in self._devices if d["id"] == self._picked), {})

    @Property("QVariantList", notify=changed)
    def choices(self):
        return recent() if not self._demo else [{"name": "holiday.jpg", "path": "", "where": "Pictures", "size": "2.1 MB"}, {"name": "tickets.pdf", "path": "", "where": "Downloads", "size": "340 KB"}]

    @Slot(str)
    def pick(self, ident: str) -> None:
        self._picked = ident
        self.changed.emit()

    def _act(self, args: list, good: str, ident: str = None) -> None:
        ident = ident or self._picked
        if self._demo or not ident:
            self.said.emit("This is the preview: nothing is sent." if self._demo else "Choose a device first.", self._demo is False)
            return

        def then(result):
            code, out = result if not isinstance(result, Exception) else (1, str(result))
            self.said.emit(good if code == 0 else (out.strip().splitlines() or ["That didn't work."])[-1][:160], code != 0)
            self.refresh()
        self.bg(lambda: run([self.TOOL, "-d", ident] + args, 20), then)

    @Slot(str)
    def pair(self, ident: str) -> None:
        self._act(["--pair"], "Asked to pair. Accept it on the phone.", ident)

    @Slot(str)
    def unpair(self, ident: str) -> None:
        self._act(["--unpair"], "Unpaired.", ident)

    @Slot()
    def ring(self) -> None:
        self._act(["--ring"], "Ringing it.")

    @Slot()
    def ping(self) -> None:
        self._act(["--ping-msg", "Hello from Huginn"], "Sent a ping.")

    @Slot()
    def sendClipboard(self) -> None:
        self._act(["--send-clipboard"], "Clipboard sent to the phone.")

    @Slot(str)
    def sendText(self, text: str) -> None:
        """Send a note or a web address. A web address opens on the phone; other words arrive as text to copy."""
        text = text.strip()
        if not text:
            return
        link = re.fullmatch(r"https?://\S+", text) is not None
        self._act(["--share", text] if link else ["--share-text", text[:4000]], "The link is opening on the phone." if link else "Sent to the phone.")

    @Slot("QVariantList")
    def sendFiles(self, paths) -> None:
        files = [QUrl(str(p)).toLocalFile() if str(p).startswith("file:") else str(p) for p in paths]
        files = [f for f in files if os.path.isfile(f)]
        ident = self._picked
        if self._demo or not ident or not files:
            self.said.emit("This is the preview: nothing is sent." if self._demo else "Choose a device and a file first.", not self._demo)
            return

        def work():
            for f in files:
                code, out = run([self.TOOL, "-d", ident, "--share", f], 60)
                if code != 0:
                    return f"“{Path(f).name}” didn't go: " + ((out.strip().splitlines() or ["no reason given"])[-1][:120])
            return ""

        def then(why):
            self._waiting = [] if not why else self._waiting
            self.said.emit(str(why) if why else (f"Sent “{Path(files[0]).name}”." if len(files) == 1 else f"Sent {len(files)} files."), bool(why))
            self.changed.emit()
        self.bg(work, then)

    @Slot()
    def sendWaiting(self) -> None:
        self.sendFiles(list(self._waiting))

    @Slot()
    def dropWaiting(self) -> None:
        self._waiting = []
        self.changed.emit()


# ============================================================================================ Print & Scan
class PrintScan(Worker):
    """Printers (through CUPS) and scanners (through SANE). Printers on the network that need no driver appear by
    themselves; nothing here needs an administrator password."""
    changed = Signal()
    said = Signal(str, bool)

    def __init__(self, demo: bool = False, target=None):
        super().__init__()
        self._demo, self._printers, self._jobs, self._scanners, self._pages = demo, [], [], [], []
        self._looking, self._scanning, self._busy = False, False, False
        self._file = str(target) if target and Path(str(target)).is_file() else ""
        self._has_print, self._has_scan = demo or shutil.which("lpstat") is not None, demo or shutil.which("scanimage") is not None
        self._tmp = CACHE_HOME / "scans"
        if demo:
            self._printers = [{"name": "Office_LaserJet", "label": "Office LaserJet", "state": "Ready", "ok": True, "default": True},
                              {"name": "Canon_TS3300", "label": "Canon TS3300", "state": "Paused", "ok": False, "default": False}]
            self._jobs = [{"id": "Office_LaserJet-41", "printer": "Office LaserJet", "size": "212 KB", "when": "09:12"}]
            self._scanners = [{"id": "demo", "name": "Canon TS3300 flatbed"}]
            return
        shutil.rmtree(self._tmp, ignore_errors=True)
        self._tick = QTimer(self)
        self._tick.setInterval(6000)
        self._tick.timeout.connect(self.refresh)
        self._tick.start()
        self.refresh()
        self.findScanners()

    # ---- reading what the system says
    @staticmethod
    def read_printers(dests: str, states: str, default: str) -> list:
        chosen = (re.search(r"destination:\s*(\S+)", default) or [None, ""])[1]
        state = {}
        for line in states.splitlines():
            m = re.match(r"printer (\S+) (is idle|now printing|disabled|is not accepting)?(.*)", line)
            if m:
                rest = (m.group(2) or "") + m.group(3)
                state[m.group(1)] = ("Printing", True) if "now printing" in rest else ("Paused", False) if "disabled" in rest else ("Ready", True)
        names = [n.strip() for n in dests.splitlines() if n.strip() and " " not in n.strip()] or list(state)
        return [{"name": n, "label": n.replace("_", " "), "state": state.get(n, ("Ready", True))[0], "ok": state.get(n, ("", True))[1], "default": n == chosen} for n in names]

    @staticmethod
    def read_jobs(text: str) -> list:
        out = []
        for line in text.splitlines():
            m = re.match(r"(\S+)-(\d+)\s+(\S+)\s+(\d+)\s+(.*)", line)
            if m:
                clock = re.search(r"(\d\d:\d\d)", m.group(5))
                out.append({"id": f"{m.group(1)}-{m.group(2)}", "printer": m.group(1).replace("_", " "), "size": size_words(int(m.group(4))), "when": clock.group(1) if clock else ""})
        return out

    @staticmethod
    def read_scanners(text: str) -> list:
        out = []
        for m in re.finditer(r"device `([^']+)' is an? (.+)", text):
            name = re.sub(r"\s+", " ", m.group(2)).strip()
            if not m.group(1).startswith(("v4l:", "test:")):       # webcams aren't scanners
                out.append({"id": m.group(1), "name": name[0].upper() + name[1:]})
        return out

    @Slot()
    def refresh(self) -> None:
        if self._demo or not self._has_print or self._busy:
            return
        self._busy = True

        def work():
            return self.read_printers(run(["lpstat", "-e"], 8)[1], run(["lpstat", "-p"], 8)[1], run(["lpstat", "-d"], 8)[1]), self.read_jobs(run(["lpstat", "-o"], 8)[1])

        def then(result):
            self._busy = False
            if not isinstance(result, Exception) and (result[0], result[1]) != (self._printers, self._jobs):
                self._printers, self._jobs = result
                self.changed.emit()
        self.bg(work, then)

    @Slot()
    def findScanners(self) -> None:
        if self._demo or not self._has_scan or self._looking:
            return
        self._looking = True
        self.changed.emit()

        def then(result):
            self._looking = False
            self._scanners = self.read_scanners(result[1]) if not isinstance(result, Exception) else []
            self.changed.emit()
        self.bg(lambda: run(["scanimage", "-L"], 40), then)

    hasPrint = Property(bool, lambda self: self._has_print, constant=True)
    hasScan = Property(bool, lambda self: self._has_scan, constant=True)
    printers = Property("QVariantList", lambda self: self._printers, notify=changed)
    jobs = Property("QVariantList", lambda self: self._jobs, notify=changed)
    scanners = Property("QVariantList", lambda self: self._scanners, notify=changed)
    looking = Property(bool, lambda self: self._looking, notify=changed)
    scanning = Property(bool, lambda self: self._scanning, notify=changed)
    file = Property(str, lambda self: self._file, notify=changed)
    fileName = Property(str, lambda self: Path(self._file).name if self._file else "", notify=changed)
    pages = Property("QVariantList", lambda self: [{"url": QUrl.fromLocalFile(p).toString(), "path": p} for p in self._pages], notify=changed)

    @Property("QVariantList", notify=changed)
    def choices(self):
        if self._demo:
            return [{"name": "Boarding pass.pdf", "path": "", "where": "Downloads", "size": "88 KB"}, {"name": "Lease.pdf", "path": "", "where": "Documents", "size": "1.2 MB"}]
        return recent((".pdf", ".png", ".jpg", ".jpeg", ".txt", ".ps", ".gif", ".tif", ".tiff", ".bmp"))

    # ---- printing
    @Slot(str)
    def choose(self, path: str) -> None:
        path = QUrl(path).toLocalFile() if path.startswith("file:") else path
        self._file = path if Path(path).is_file() else ""
        self.changed.emit()

    @Slot(str, int, bool, str)
    def printFile(self, printer: str, copies: int, two_sided: bool, pages: str) -> None:
        self.printWith(printer, {"copies": copies, "twoSided": two_sided, "pages": pages})

    PAPERS = {"": "", "a4": "A4", "letter": "Letter", "legal": "Legal", "a5": "A5", "photo": "4x6"}

    @Slot(str, "QVariantMap")
    def printWith(self, printer: str, how) -> None:
        """Print the chosen file. `how` may hold copies, twoSided, pages, paper (a4, letter, legal, a5, photo),
        grey (no colour ink), fit (shrink or grow to fill the page), landscape."""
        pages, copies, two_sided = str(how.get("pages", "")).replace(" ", ""), int(how.get("copies") or 1), bool(how.get("twoSided"))
        extra = []
        if self.PAPERS.get(str(how.get("paper", ""))):
            extra += ["-o", "media=" + self.PAPERS[str(how["paper"])]]
        if how.get("grey"):
            extra += ["-o", "print-color-mode=monochrome"]
        if how.get("fit"):
            extra += ["-o", "fit-to-page"]
        if how.get("landscape"):
            extra += ["-o", "orientation-requested=4"]
        if self._demo or not self._file:
            self.said.emit("This is the preview: nothing is printed." if self._demo else "Choose what to print first.", not self._demo)
            return
        if pages and not re.fullmatch(r"\d+(-\d+)?(,\d+(-\d+)?)*", pages):
            self.said.emit("Write pages like 1-3 or 2,5,8.", True)
            return
        if not any(p["name"] == printer for p in self._printers):
            self.said.emit("Choose a printer first.", True)
            return
        args = ["lp", "-d", printer, "-n", str(max(1, min(99, copies)))] + (["-o", "sides=two-sided-long-edge"] if two_sided else ["-o", "sides=one-sided"]) + extra + (["-P", pages] if pages else [])
        name = Path(self._file).name

        def then(result):
            code, out = result if not isinstance(result, Exception) else (1, str(result))
            self.said.emit(f"“{name}” is on its way to the printer." if code == 0 else (out.strip().splitlines() or ["The printer didn't take it."])[-1][:160], code != 0)
            self.refresh()
        self.bg(lambda: run(args + ["--", self._file], 30), then)

    @Slot(str)
    def cancel(self, job: str) -> None:
        if not self._demo and re.fullmatch(r"[\w.\-]+-\d+", job):
            self.bg(lambda: run(["cancel", job], 10), lambda _r: self.refresh())

    @Slot(str)
    def makeDefault(self, printer: str) -> None:
        if not self._demo and any(p["name"] == printer for p in self._printers):
            self.bg(lambda: run(["lpoptions", "-d", printer], 10), lambda _r: self.refresh())

    # ---- scanning
    @Slot(str, bool, int)
    def scan(self, device: str, colour: bool, dpi: int) -> None:
        if self._demo or self._scanning or not any(s["id"] == device for s in self._scanners):
            if self._demo:
                self.said.emit("This is the preview: nothing is scanned.", False)
            return
        self._scanning = True
        self.changed.emit()
        self._tmp.mkdir(parents=True, exist_ok=True)
        target = self._tmp / f"page-{uuid.uuid4().hex[:8]}.png"
        args = ["scanimage", "-d", device, "--format=png", "--mode", "Color" if colour else "Gray", "--resolution", str(dpi if dpi in (75, 150, 300, 600) else 300), "-o", str(target)]

        def then(result):
            self._scanning = False
            code, out = result if not isinstance(result, Exception) else (1, str(result))
            if code == 0 and target.exists() and target.stat().st_size > 0:
                self._pages.append(str(target))
            else:
                target.unlink(missing_ok=True)
                why = (out.strip().splitlines() or ["The scanner didn't answer."])[-1]
                self.said.emit("The scanner is busy or switched off." if "busy" in why.lower() or "invalid argument" in why.lower() else why[:160], True)
            self.changed.emit()
        self.bg(lambda: run(args, 180), then)

    @Slot(int)
    def dropPage(self, index: int) -> None:
        if 0 <= index < len(self._pages):
            Path(self._pages.pop(index)).unlink(missing_ok=True)
            self.changed.emit()

    @staticmethod
    def write_pdf(images: list, target: Path) -> None:
        """Each scanned page becomes one PDF page of its true size, so it prints at the size of the original."""
        from PySide6.QtCore import QMarginsF, QSizeF
        from PySide6.QtGui import QImage, QPageLayout, QPageSize, QPainter, QPdfWriter
        writer = QPdfWriter(str(target))
        writer.setResolution(300)
        painter = None
        for path in images:
            img = QImage(path)
            if img.isNull():
                continue
            dpi = img.dotsPerMeterX() / 39.37 if img.dotsPerMeterX() > 0 else 300
            size = QPageSize(QSizeF(img.width() / dpi * 72, img.height() / dpi * 72), QPageSize.Unit.Point)
            writer.setPageLayout(QPageLayout(size, QPageLayout.Orientation.Portrait, QMarginsF(0, 0, 0, 0)))
            if painter is None:
                painter = QPainter(writer)
            else:
                writer.newPage()
            painter.drawImage(painter.viewport(), img)
        if painter is None:
            raise OSError("There was nothing to put in the PDF.")
        painter.end()

    @Slot(str, result=str)
    def savePdf(self, name: str) -> str:
        """Keep the scanned pages as one PDF in Documents/Scans. Returns where it went ("" when it couldn't)."""
        if not self._pages:
            return ""
        folder = Path(QStandardPaths.writableLocation(QStandardPaths.DocumentsLocation) or Path.home() / "Documents") / "Scans"
        stem = re.sub(r'[/\\\0]', "_", name).strip().strip(".") or "Scan " + dt.datetime.now().strftime("%Y-%m-%d %H.%M")
        try:
            folder.mkdir(parents=True, exist_ok=True)
            target, n = folder / f"{stem}.pdf", 1
            while target.exists():
                n += 1
                target = folder / f"{stem} {n}.pdf"
            self.write_pdf(self._pages, target)
        except OSError as err:
            self.said.emit(f"Couldn't save the scan: {err.strerror or err}", True)
            return ""
        for page in self._pages:
            Path(page).unlink(missing_ok=True)
        self._pages = []
        self.said.emit(f"Saved “{target.name}” in Documents, Scans.", False)
        self.changed.emit()
        return str(target)

    @Slot(str)
    def mail(self, path: str) -> None:
        if path and Path(path).is_file():
            subprocess.Popen([os.sys.executable, str(Path(__file__).with_name("huginn_app.py")), "mail", "mailto:?attach=" + urllib.parse.quote(path, safe="")], start_new_session=True,
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


# ==================================================================================================== Maps
MAP_SERVERS = {"search": "https://nominatim.openstreetmap.org", "tiles": "https://tile.openstreetmap.org/",
               "driving": "https://routing.openstreetmap.de/routed-car", "cycling": "https://routing.openstreetmap.de/routed-bike", "walking": "https://routing.openstreetmap.de/routed-foot"}


def map_servers() -> dict:
    """Where maps, search and directions come from. /etc/huginn/maps.json or ~/.config/huginn/maps.json can point
    any of them at your own server (the public ones are run by volunteers and ask for light use)."""
    out = dict(MAP_SERVERS)
    for file in (Path("/etc/huginn/maps.json"), Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "huginn" / "maps.json"):
        try:
            mine = json.loads(file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for key in out:
            if isinstance(mine, dict) and isinstance(mine.get(key), str) and mine[key].startswith(("https://", "http://localhost", "http://127.0.0.1")):
                out[key] = mine[key]
    return out


def distance_words(metres: float, miles: bool = False) -> str:
    if miles:
        feet = metres * 3.28084
        return f"{round(feet / 50) * 50:.0f} ft" if feet < 1000 else f"{metres / 1609.344:.1f} mi"
    return f"{round(metres / 10) * 10:.0f} m" if metres < 1000 else f"{metres / 1000:.1f} km"


def time_words(seconds: float) -> str:
    minutes = max(1, round(seconds / 60))
    return f"{minutes} min" if minutes < 60 else f"{minutes // 60} h" + (f" {minutes % 60} min" if minutes % 60 else "")


def step_words(step: dict) -> str:
    """One turn of a route, as a sentence."""
    move, road = step.get("maneuver") or {}, step.get("name") or ""
    kind, way = move.get("type", ""), (move.get("modifier") or "").replace("sharp ", "sharply ").replace("slight ", "slightly ")
    onto = f" onto {road}" if road else ""
    if kind == "depart":
        return "Set off" + (f" along {road}" if road else "")
    if kind == "arrive":
        return "You're there"
    if kind in ("roundabout", "rotary"):
        n = move.get("exit")
        return (f"At the roundabout, take exit {n}" if n else "Go round the roundabout") + onto
    if kind in ("merge", "on ramp"):
        return "Join" + (f" {road}" if road else " the road ahead")
    if kind == "off ramp":
        return "Take the exit" + onto
    if kind == "fork":
        return f"Keep {way or 'ahead'} at the fork" + onto
    if kind in ("new name", "continue") or way == "straight":
        return "Carry on" + (f" along {road}" if road else "")
    if way == "uturn":
        return "Turn around" + onto
    return (f"Turn {way}" if way else "Carry on") + onto


class Maps(Worker):
    """Places and directions from OpenStreetMap. Huginn never works out where you are: you say where from and where to."""
    changed = Signal()
    said = Signal(str, bool)
    moved = Signal(float, float, float)                            # the map should look here: lat, lon, zoom

    def __init__(self, demo: bool = False, target=None):
        super().__init__()
        self._demo, self._servers, self._results, self._route, self._busy = demo, map_servers(), [], {}, False
        self._from, self._to, self._mode = {}, {}, "driving"
        self._file = DATA_HOME / "maps.json"
        try:
            saved = json.loads(self._file.read_text(encoding="utf-8")) if not demo else {}
        except (OSError, ValueError):
            saved = {}
        self._saved = [p for p in saved.get("places", []) if isinstance(p, dict) and "lat" in p and "lon" in p and p.get("name")]
        self._miles, self._view = bool(saved.get("miles")), saved.get("view") if isinstance(saved.get("view"), list) and len(saved.get("view")) == 3 else [51.5, -0.12, 4.5]
        self._start = str(target or "")
        if demo:
            self._saved = [{"name": "Home", "detail": "Holton, Michigan", "lat": 43.41, "lon": -86.08}, {"name": "Lakeside Vets", "detail": "Muskegon", "lat": 43.23, "lon": -86.25}]
            self._from, self._to = self._saved[0], self._saved[1]
            self._route = {"distance": "31.4 km", "time": "28 min", "line": [], "steps": [{"text": "Set off along Holton Road", "far": "9.2 km"}, {"text": "Turn right onto M-120", "far": "14 km"},
                                                                                      {"text": "At the roundabout, take exit 2 onto Whitehall Road", "far": "7.6 km"}, {"text": "You're there", "far": ""}]}

    tileHost = Property(str, lambda self: self._servers["tiles"], constant=True)
    results = Property("QVariantList", lambda self: self._results, notify=changed)
    saved = Property("QVariantList", lambda self: self._saved, notify=changed)
    route = Property("QVariantMap", lambda self: self._route, notify=changed)
    origin = Property("QVariantMap", lambda self: self._from, notify=changed)
    goal = Property("QVariantMap", lambda self: self._to, notify=changed)
    mode = Property(str, lambda self: self._mode, notify=changed)
    busy = Property(bool, lambda self: self._busy, notify=changed)
    miles = Property(bool, lambda self: self._miles, notify=changed)
    view = Property("QVariantList", lambda self: self._view, constant=True)
    startWith = Property(str, lambda self: self._start, constant=True)

    def _keep(self) -> None:
        if self._demo:
            return
        try:
            self._file.parent.mkdir(parents=True, exist_ok=True)
            self._file.write_text(json.dumps({"places": self._saved, "miles": self._miles, "view": self._view}), encoding="utf-8")
        except OSError:
            pass

    @staticmethod
    def read_geo(text: str):
        """A "geo:" address from another app, or "lat, lon" typed in. Returns (lat, lon, label) or None."""
        m = re.match(r"^\s*(?:geo:)?\s*(-?\d{1,2}(?:\.\d+)?)\s*,\s*(-?\d{1,3}(?:\.\d+)?)(?:[;?](.*))?\s*$", text, re.I)
        if not m or not (-90 <= float(m.group(1)) <= 90 and -180 <= float(m.group(2)) <= 180):
            return None
        label = urllib.parse.parse_qs(m.group(3) or "").get("q", [""])[0]
        label = re.sub(r"^-?[\d.]+,-?[\d.]+\(?|\)$", "", label).strip()
        return float(m.group(1)), float(m.group(2)), label

    @Slot(str)
    def search(self, text: str) -> None:
        text = " ".join(text.split())
        if not text or self._demo:
            self._results = []
            self.changed.emit()
            return
        geo = self.read_geo(text)
        if geo or text.lower().startswith("geo:"):
            if geo:
                self._results = [{"name": geo[2] or f"{geo[0]:.5f}, {geo[1]:.5f}", "detail": "A point on the map", "lat": geo[0], "lon": geo[1]}]
                self.moved.emit(geo[0], geo[1], 15)
            self.changed.emit()
            return
        self._busy = True
        self.changed.emit()
        url = self._servers["search"] + "/search?" + urllib.parse.urlencode({"format": "jsonv2", "q": text[:200], "limit": 8})

        def then(result):
            self._busy = False
            if isinstance(result, Exception):
                self._results = []
                self.said.emit(plain_net_error(result), True)
            else:
                self._results = self.read_places(result)
                if not self._results:
                    self.said.emit("Nothing by that name. Try adding the town or country.", False)
                else:
                    self.moved.emit(self._results[0]["lat"], self._results[0]["lon"], 14)
            self.changed.emit()
        self.bg(lambda: json.loads(fetch(url, 20, 2_000_000).decode("utf-8")), then)

    @staticmethod
    def read_places(rows) -> list:
        out = []
        for r in rows if isinstance(rows, list) else []:
            try:
                whole = str(r.get("display_name", ""))
                name = str(r.get("name") or whole.split(",")[0]).strip()
                out.append({"name": name[:120], "detail": whole[len(name):].lstrip(", ")[:160] if whole.startswith(name) else whole[:160], "lat": float(r["lat"]), "lon": float(r["lon"])})
            except (KeyError, TypeError, ValueError):
                continue
        return out

    @Slot("QVariantMap")
    def show(self, place) -> None:
        self.moved.emit(float(place["lat"]), float(place["lon"]), 15)

    @Slot("QVariantMap")
    def keep(self, place) -> None:
        if not any(abs(p["lat"] - place["lat"]) < 1e-5 and abs(p["lon"] - place["lon"]) < 1e-5 for p in self._saved):
            self._saved.append({k: place[k] for k in ("name", "detail", "lat", "lon")})
            self._keep()
            self.said.emit(f"Kept “{place['name']}”.", False)
            self.changed.emit()

    @Slot(int)
    def forget(self, index: int) -> None:
        if 0 <= index < len(self._saved):
            self._saved.pop(index)
            self._keep()
            self.changed.emit()

    @Slot(float, float, float)
    def looked(self, lat: float, lon: float, zoom: float) -> None:
        """Remember where the map was left, for next time."""
        self._view = [round(lat, 5), round(lon, 5), round(zoom, 2)]
        self._keep()

    @Slot()
    def flipUnits(self) -> None:
        self._miles = not self._miles
        self._keep()
        if self._from and self._to:
            self.directions()
        self.changed.emit()

    @Slot(str, "QVariantMap")
    def setEnd(self, which: str, place) -> None:
        """Choose where the trip starts ("from") or ends ("to")."""
        spot = {k: place[k] for k in ("name", "detail", "lat", "lon")} if place and "lat" in place else {}
        if which == "from":
            self._from = spot
        else:
            self._to = spot
        self._route = {}
        self.changed.emit()
        if self._from and self._to:
            self.directions()

    @Slot(str)
    def setMode(self, mode: str) -> None:
        if mode in ("driving", "cycling", "walking"):
            self._mode = mode
            self.changed.emit()
            if self._from and self._to:
                self.directions()

    @Slot()
    def swap(self) -> None:
        self._from, self._to, self._route = self._to, self._from, {}
        self.changed.emit()
        if self._from and self._to:
            self.directions()

    def read_route(self, data: dict) -> dict:
        routes = data.get("routes") if isinstance(data, dict) else None
        if not routes:
            return {}
        r = routes[0]
        steps = [{"text": step_words(s), "far": distance_words(s.get("distance", 0), self._miles) if s.get("distance", 0) >= 10 else ""}
                 for leg in r.get("legs", []) for s in leg.get("steps", [])]
        line = [[float(lat), float(lon)] for lon, lat in (r.get("geometry") or {}).get("coordinates", [])][:20000]
        return {"distance": distance_words(r.get("distance", 0), self._miles), "time": time_words(r.get("duration", 0)), "line": line, "steps": steps[:400]}

    @Slot()
    def directions(self) -> None:
        if self._demo or not (self._from and self._to):
            return
        a, b, mode = self._from, self._to, self._mode
        url = f"{self._servers[mode]}/route/v1/driving/{a['lon']:.6f},{a['lat']:.6f};{b['lon']:.6f},{b['lat']:.6f}?overview=full&geometries=geojson&steps=true"
        self._busy = True
        self.changed.emit()

        def then(result):
            self._busy = False
            if (a, b, mode) != (self._from, self._to, self._mode):
                return                                             # you changed your mind while it was thinking
            if isinstance(result, Exception):
                self._route = {}
                gone = getattr(result, "code", 0) in (400, 404)
                self.said.emit("There's no way between those two by " + {"driving": "car", "cycling": "bike", "walking": "foot"}[mode] + "." if gone else plain_net_error(result), True)
            else:
                self._route = self.read_route(result)
                if not self._route:
                    self.said.emit("No route came back for those two places.", True)
            self.changed.emit()
        self.bg(lambda: json.loads(fetch(url, 30, 30_000_000).decode("utf-8")), then)

    @Slot()
    def clearRoute(self) -> None:
        self._from, self._to, self._route = {}, {}, {}
        self.changed.emit()


# ================================================================================================ Podcasts
def strip_tags(text: str, most: int = 600) -> str:
    text = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", text or "")
    text = re.sub(r"(?i)<br\s*/?>|</p>", "\n", text)
    return re.sub(r"[ \t]+", " ", html.unescape(re.sub(r"<[^>]+>", "", text))).strip()[:most]


def read_feed(raw: bytes) -> dict:
    """A podcast feed (RSS) as {title, author, image, episodes: [{id, title, date, stamp, url, length, about}]}."""
    if b"<!ENTITY" in raw[:200_000] or b"<!entity" in raw[:200_000]:
        raise ValueError("That feed uses a trick this app won't follow.")
    import email.utils
    import xml.etree.ElementTree as ET
    root = ET.fromstring(raw)
    channel = root.find("channel")
    if channel is None:
        raise ValueError("That address isn't a podcast feed.")
    it = "{http://www.itunes.com/dtds/podcast-1.0.dtd}"
    text = lambda node, tag: (node.findtext(tag) or "").strip()      # noqa: E731
    image = (channel.find(it + "image").get("href", "") if channel.find(it + "image") is not None else "") or text(channel, "image/url")
    episodes = []
    for item in channel.findall("item")[:300]:
        sound = item.find("enclosure")
        url = (sound.get("url", "") if sound is not None else "").strip()
        if not url.startswith(("https://", "http://")):
            continue
        try:
            stamp = email.utils.parsedate_to_datetime(text(item, "pubDate")).timestamp()
        except (TypeError, ValueError):
            stamp = 0
        length = text(item, it + "duration")
        if length.isdigit():
            length = time_words(int(length))
        elif re.fullmatch(r"(\d+:)?\d+:\d\d", length):
            parts = [int(x) for x in length.split(":")]
            length = time_words(sum(x * 60 ** i for i, x in enumerate(reversed(parts))))
        else:
            length = ""
        episodes.append({"id": text(item, "guid") or url, "title": text(item, "title")[:200] or "Untitled", "stamp": stamp, "url": url, "length": length,
                         "date": dt.datetime.fromtimestamp(stamp).strftime("%-d %b %Y") if stamp else "", "about": strip_tags(text(item, "description") or text(item, it + "summary"))})
    episodes.sort(key=lambda e: -e["stamp"])
    return {"title": text(channel, "title")[:160] or "Untitled show", "author": (text(channel, it + "author") or text(channel, "managingEditor"))[:120],
            "image": image if image.startswith("https://") else "", "about": strip_tags(text(channel, "description"), 400), "episodes": episodes}


class Podcasts(Worker):
    """Shows you follow. Finding one asks Apple's public podcast directory (only the words you type are sent);
    after that the app talks to each show's own feed and nobody else."""
    changed = Signal()
    said = Signal(str, bool)
    DIRECTORY = "https://itunes.apple.com/search"

    def __init__(self, demo: bool = False, target=None):
        super().__init__()
        self._demo, self._file, self._found, self._busy, self._show, self._now = demo, DATA_HOME / "podcasts.json", [], False, "", {}
        self._fetching = set()
        if demo:
            eps = [{"id": f"e{i}", "title": t, "date": d, "stamp": 9 - i, "url": "", "length": ln, "about": a} for i, (t, d, ln, a) in enumerate([
                ("Why small distros matter", "11 Nov 2026", "42 min", "A talk with the people behind three one-person Linux distributions."), ("The shape of a desktop", "4 Nov 2026", "38 min", "Docks, bars and islands."),
                ("Privacy by default", "28 Oct 2026", "51 min", "What a browser should refuse to do.")])]
            self._shows = [{"id": "s1", "title": "Open Desk", "author": "Open Desk Radio", "feed": "", "image": "", "about": "Weekly conversations about free desktops.", "episodes": eps, "played": {"e2": True}, "spot": {"e0": 760}},
                           {"id": "s2", "title": "Night Signals", "author": "R. Halvorsen", "feed": "", "image": "", "about": "", "episodes": [], "played": {}, "spot": {}}]
            self._show, self._now = "s1", dict(eps[0], show="Open Desk", showId="s1")
            return
        try:
            data = json.loads(self._file.read_text(encoding="utf-8"))
            self._shows = [s for s in data.get("shows", []) if isinstance(s, dict) and s.get("id") and s.get("feed")]
        except (OSError, ValueError, AttributeError):
            self._shows = []
        self._show = self._shows[0]["id"] if self._shows else ""
        QTimer.singleShot(0, self.refreshAll)

    def _keep(self) -> None:
        if self._demo:
            return
        try:
            self._file.parent.mkdir(parents=True, exist_ok=True)
            part = self._file.with_name(".podcasts.json.saving")
            part.write_text(json.dumps({"shows": self._shows}), encoding="utf-8")
            os.replace(part, self._file)
        except OSError as err:
            self.said.emit(f"Couldn't save your shows: {err.strerror or err}", True)

    def _prefs(self) -> dict:
        try:
            return json.loads((DATA_HOME / "podcasts-prefs.json").read_text(encoding="utf-8")) if not self._demo else {}
        except (OSError, ValueError):
            return {}

    speed = Property(float, lambda self: float(self._prefs().get("speed", 1.0)), notify=changed)

    @Slot(float)
    def setSpeed(self, speed: float) -> None:
        if not self._demo and speed in (0.8, 1.0, 1.2, 1.5, 2.0):
            try:
                DATA_HOME.mkdir(parents=True, exist_ok=True)
                (DATA_HOME / "podcasts-prefs.json").write_text(json.dumps({"speed": speed}), encoding="utf-8")
            except OSError:
                pass
        self.changed.emit()

    def _kept_path(self, show: dict, episode: dict) -> Path:
        clean = lambda t: " ".join(re.sub(r'[/\\\0:*?"<>|]+', " ", t).split()).strip(".")[:80] or "Untitled"      # noqa: E731
        kind = Path(urllib.parse.urlsplit(episode["url"]).path).suffix.lower()
        return Path.home() / "Podcasts" / clean(show["title"]) / (clean(episode["title"]) + (kind if kind in (".mp3", ".m4a", ".ogg", ".opus", ".aac", ".wav", ".mp4") else ".mp3"))

    @Slot(str)
    def keep(self, episode: str) -> None:
        """Fetch an episode into Podcasts in your home folder, so it plays with no network."""
        s = self._one()
        e = next((x for x in s.get("episodes", []) if x["id"] == episode), None)
        if self._demo or not e or episode in self._fetching:
            return
        target = self._kept_path(s, e)
        self._fetching.add(episode)
        self.changed.emit()

        def work():
            target.parent.mkdir(parents=True, exist_ok=True)
            part = target.with_name("." + target.name + ".part")
            req = urllib.request.Request(e["url"], headers={"User-Agent": AGENT})
            try:
                with urllib.request.urlopen(req, timeout=40) as reply, open(part, "wb") as out:
                    total = 0
                    while True:
                        block = reply.read(262144)
                        if not block:
                            break
                        total += len(block)
                        if total > 1_500_000_000:
                            raise OSError("That episode is too large to keep.")
                        out.write(block)
                if total < 1000:
                    raise OSError("The show's server sent nothing.")
                os.replace(part, target)
            finally:
                part.unlink(missing_ok=True)
            return target

        def then(result):
            self._fetching.discard(episode)
            if isinstance(result, Exception):
                mine = str(result).startswith(("That episode", "The show's"))
                self.said.emit(str(result) if mine else plain_net_error(result), True)
            else:
                self.said.emit(f"Kept “{e['title']}” in Podcasts.", False)
            self.changed.emit()
        self.bg(work, then)

    @Slot(str)
    def unkeep(self, episode: str) -> None:
        s = self._one()
        e = next((x for x in s.get("episodes", []) if x["id"] == episode), None)
        if e and not self._demo:
            self._kept_path(s, e).unlink(missing_ok=True)
            self.changed.emit()

    shows = Property("QVariantList", lambda self: [{"id": s["id"], "title": s["title"], "author": s.get("author", ""), "image": s.get("image", ""),
                                                    "fresh": sum(1 for e in s.get("episodes", [])[:30] if not s.get("played", {}).get(e["id"]))} for s in self._shows], notify=changed)
    show = Property(str, lambda self: self._show, notify=changed)
    found = Property("QVariantList", lambda self: self._found, notify=changed)
    busy = Property(bool, lambda self: self._busy, notify=changed)
    now = Property("QVariantMap", lambda self: self._now, notify=changed)

    def _one(self, ident: str = None) -> dict:
        return next((s for s in self._shows if s["id"] == (ident or self._show)), {})

    @Property("QVariantMap", notify=changed)
    def current(self):
        s = self._one()
        return {"id": s.get("id", ""), "title": s.get("title", ""), "author": s.get("author", ""), "image": s.get("image", ""), "about": s.get("about", "")}

    @Property("QVariantList", notify=changed)
    def episodes(self):
        s = self._one()
        kept = (lambda e: self._kept_path(s, e).exists()) if not self._demo and s else (lambda e: False)
        return [dict(e, played=bool(s.get("played", {}).get(e["id"])), spot=int(s.get("spot", {}).get(e["id"], 0)), kept=kept(e), fetching=e["id"] in self._fetching)
                for e in s.get("episodes", [])[:200]]

    @Slot(str)
    def choose(self, ident: str) -> None:
        self._show = ident
        self.changed.emit()

    @Slot(str)
    def find(self, text: str) -> None:
        text = " ".join(text.split())
        if self._demo or not text:
            self._found = []
            self.changed.emit()
            return
        if re.match(r"https?://", text):
            self.follow(text)
            return
        self._busy = True
        self.changed.emit()
        url = self.DIRECTORY + "?" + urllib.parse.urlencode({"media": "podcast", "limit": 12, "term": text[:100]})

        def then(result):
            self._busy = False
            if isinstance(result, Exception):
                self._found = []
                self.said.emit(plain_net_error(result), True)
            else:
                self._found = [{"title": str(r.get("collectionName", ""))[:160], "author": str(r.get("artistName", ""))[:120], "feed": r["feedUrl"], "image": str(r.get("artworkUrl100", ""))}
                               for r in result.get("results", []) if isinstance(r, dict) and str(r.get("feedUrl", "")).startswith("https://")]
                if not self._found:
                    self.said.emit("No show by that name. You can also paste a feed address.", False)
            self.changed.emit()
        self.bg(lambda: json.loads(fetch(url, 20, 2_000_000).decode("utf-8")), then)

    @Slot(str)
    def follow(self, feed: str) -> None:
        feed = feed.strip()
        if self._demo or not re.match(r"https?://", feed):
            return
        if any(s["feed"] == feed for s in self._shows):
            self.said.emit("You already follow that one.", False)
            return
        self._busy = True
        self.changed.emit()

        def then(result):
            self._busy = False
            if isinstance(result, Exception):
                self.said.emit(str(result) if isinstance(result, ValueError) else "That address isn't a podcast feed." if "syntax" in str(result) or "token" in str(result) else plain_net_error(result), True)
            else:
                show = dict(result, id=uuid.uuid4().hex[:10], feed=feed, played={}, spot={})
                self._shows.append(show)
                self._show, self._found = show["id"], []
                self._keep()
                self.said.emit(f"Following “{show['title']}”.", False)
            self.changed.emit()
        self.bg(lambda: read_feed(fetch(feed, 30)), then)

    @Slot(str)
    def unfollow(self, ident: str) -> None:
        self._shows = [s for s in self._shows if s["id"] != ident]
        if self._show == ident:
            self._show = self._shows[0]["id"] if self._shows else ""
        self._keep()
        self.changed.emit()

    @Slot()
    def refreshAll(self) -> None:
        if self._demo or self._busy or not self._shows:
            return
        self._busy = True
        self.changed.emit()
        feeds = [(s["id"], s["feed"]) for s in self._shows]

        def work():
            out = {}
            for ident, feed in feeds:
                try:
                    out[ident] = read_feed(fetch(feed, 25))
                except Exception:                                  # one show's server being down shouldn't stop the rest
                    continue
            return out

        def then(result):
            self._busy = False
            new = 0
            for s in self._shows:
                fresh = result.get(s["id"]) if isinstance(result, dict) else None
                if fresh:
                    have = {e["id"] for e in s.get("episodes", [])}
                    new += sum(1 for e in fresh["episodes"] if e["id"] not in have) if have else 0
                    s.update(title=fresh["title"], author=fresh["author"], image=fresh["image"], about=fresh["about"], episodes=fresh["episodes"])
            self._keep()
            if new:
                self.said.emit("1 new episode." if new == 1 else f"{new} new episodes.", False)
            self.changed.emit()
        self.bg(work, then)

    @Slot(str)
    def play(self, episode: str) -> None:
        s = self._one()
        e = next((x for x in s.get("episodes", []) if x["id"] == episode), None)
        if e:
            local = self._kept_path(s, e) if not self._demo else None
            self._now = dict(e, show=s["title"], showId=s["id"], image=s.get("image", ""), spot=int(s.get("spot", {}).get(e["id"], 0)),
                             url=QUrl.fromLocalFile(str(local)).toString() if local is not None and local.exists() else e["url"])
            self.changed.emit()

    @Slot(float, float)
    def heard(self, seconds: float, of: float) -> None:
        """The player reports how far in it is, every few seconds: that's where it picks up next time."""
        s = self._one(self._now.get("showId"))
        if not s or not self._now:
            return
        ident = self._now["id"]
        if of > 0 and seconds >= of - 20:
            s.setdefault("played", {})[ident] = True
            s.setdefault("spot", {}).pop(ident, None)
        elif seconds > 5:
            s.setdefault("spot", {})[ident] = int(seconds)
        self._keep()
        self.changed.emit()

    @Slot(str)
    def togglePlayed(self, episode: str) -> None:
        s = self._one()
        if s:
            played = s.setdefault("played", {})
            if played.pop(episode, None) is None:
                played[episode] = True
                s.setdefault("spot", {}).pop(episode, None)
            self._keep()
            self.changed.emit()


# =================================================================================================== Books
KEEP_TAGS = {"p", "br", "h1", "h2", "h3", "h4", "i", "em", "b", "strong", "blockquote", "ul", "ol", "li", "sup", "sub", "hr", "u", "pre", "code"}


def chapter_title(markup: str) -> str:
    m = re.search(r"(?is)<h[1-3][^>]*>(.*?)</h[1-3]>", markup) or re.search(r"(?is)<title[^>]*>(.*?)</title>", markup)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", m.group(1)))).strip()[:120] if m else ""


def tidy_chapter(markup: str, picture=None) -> str:
    """A chapter of an ebook cut down to plain structure: headings, paragraphs, emphasis, lists. Scripts, styles,
    pictures and links to anywhere are dropped, so opening a book can't fetch anything or run anything."""
    body = re.search(r"(?is)<body[^>]*>(.*)</body>", markup)
    text = body.group(1) if body else markup
    text = re.sub(r"(?is)<(script|style|head|iframe|object|math|nav)\b.*?</\1\s*>", " ", text)
    if not picture:
        text = re.sub(r"(?is)<svg\b.*?</svg\s*>", " ", text)
    text = re.sub(r"(?is)<!--.*?-->", "", text)
    text = re.sub(r"(?is)<(div|section|article|aside|figure|figcaption|header|footer|tr|td|th|table|dd|dt|dl)\b[^>]*>", "<p>", text)
    text = re.sub(r"(?is)</(div|section|article|aside|figure|figcaption|header|footer|tr|td|th|table|dd|dt|dl)\s*>", "</p>", text)

    def tag(m):
        name = m.group(2).lower()
        if name in ("img", "image") and picture and not m.group(1):       # only pictures from inside the book, copied out by `picture`
            src = re.search(r"""(?:src|xlink:href|href)\s*=\s*["']([^"']+)["']""", m.group(0), re.I)
            shown = picture(html.unescape(src.group(1))) if src else ""
            return f'<p align="center">{shown}</p>' if shown else ""
        return f"<{m.group(1)}{name}>" if name in KEEP_TAGS else ""
    text = re.sub(r"(?is)<svg\b[^>]*>(.*?)</svg\s*>", lambda m: " ".join(re.findall(r"(?is)<image\b[^>]*>", m.group(1))), text) if picture else text
    text = re.sub(r"<(/?)([A-Za-z][A-Za-z0-9]*)\b[^>]*?/?>", tag, text)
    text = re.sub(r"(<p>\s*)+", "<p>", re.sub(r"(</p>\s*)+", "</p>", text))
    return re.sub(r"<p>\s*</p>", "", text).strip()


def read_epub(path: Path) -> dict:
    """What a .epub holds: {title, author, chapters: [{name, title}], cover: member name or ""}. Nothing is unpacked."""
    import posixpath
    import xml.etree.ElementTree as ET
    with zipfile.ZipFile(path) as z:
        box = z.read("META-INF/container.xml")[:100_000]
        if b"<!ENTITY" in box:
            raise ValueError("bad book")
        opf_name = ET.fromstring(box).find(".//{*}rootfile").get("full-path")
        raw = z.read(opf_name)[:5_000_000]
        if b"<!ENTITY" in raw:
            raise ValueError("bad book")
        opf, base = ET.fromstring(raw), posixpath.dirname(opf_name)
        find = lambda tag: (opf.findtext(".//{http://purl.org/dc/elements/1.1/}" + tag) or "").strip()      # noqa: E731
        items = {i.get("id"): i for i in opf.findall(".//{*}manifest/{*}item")}
        full = lambda href: posixpath.normpath(posixpath.join(base, urllib.parse.unquote(href.split("#")[0])))      # noqa: E731
        names = set(z.namelist())
        chapters = []
        for ref in opf.findall(".//{*}spine/{*}itemref"):
            item = items.get(ref.get("idref"))
            if item is not None and "html" in (item.get("media-type") or "") and full(item.get("href", "")) in names:
                chapters.append({"name": full(item.get("href")), "title": ""})
        cover = ""
        meta = next((m.get("content") for m in opf.findall(".//{*}metadata/{*}meta") if m.get("name") == "cover"), None)
        for item in items.values():
            if "cover-image" in (item.get("properties") or "") or item.get("id") == meta:
                if (item.get("media-type") or "").startswith("image/") and full(item.get("href", "")) in names:
                    cover = full(item.get("href"))
                    break
    return {"title": find("title")[:200] or path.stem, "author": find("creator")[:120], "chapters": chapters[:2000], "cover": cover}


class Books(Worker):
    """Ebooks (EPUB) from your Books folder, read in a clean column, picked up where you left off."""
    changed = Signal()
    said = Signal(str, bool)
    opened = Signal()

    def __init__(self, demo: bool = False, target=None):
        super().__init__()
        self._demo, self._folder, self._file = demo, Path.home() / "Books", DATA_HOME / "books.json"
        self._books, self._open, self._chapter, self._text, self._info = [], "", 0, "", {}
        try:
            self._state = json.loads(self._file.read_text(encoding="utf-8")) if not demo else {}
        except (OSError, ValueError):
            self._state = {}
        if not isinstance(self._state, dict):
            self._state = {}
        if demo:
            self._books = [{"path": f"d{i}", "title": t, "author": a, "cover": "", "progress": p} for i, (t, a, p) in enumerate(
                [("The Raven's Road", "I. Halvorsen", 0.42), ("A Field Guide to Small Computers", "S. Okafor", 0.0), ("Letters from the North", "A. Lindqvist", 1.0), ("Notes on Glass", "V. Nordahl", 0.13)])]
            return
        self.rescan()
        if target and Path(str(target)).suffix.lower() == ".epub" and Path(str(target)).is_file():
            QTimer.singleShot(0, lambda: self.open(str(target)))

    def _keep(self) -> None:
        if self._demo:
            return
        try:
            self._file.parent.mkdir(parents=True, exist_ok=True)
            self._file.write_text(json.dumps(self._state), encoding="utf-8")
        except OSError:
            pass

    def _cover(self, path: Path, member: str) -> str:
        """The cover picture, copied out once into the cache so the screen can show it."""
        if not member:
            return ""
        import hashlib
        out = CACHE_HOME / "covers" / (hashlib.sha1(str(path).encode()).hexdigest()[:16] + Path(member).suffix.lower()[:5])
        try:
            if not out.exists() or out.stat().st_mtime < path.stat().st_mtime:
                out.parent.mkdir(parents=True, exist_ok=True)
                with zipfile.ZipFile(path) as z:
                    if z.getinfo(member).file_size > 12_000_000:
                        return ""
                    out.write_bytes(z.read(member))
            return QUrl.fromLocalFile(str(out)).toString()
        except (OSError, KeyError, zipfile.BadZipFile):
            return ""

    @Slot()
    def rescan(self) -> None:
        if self._demo:
            return
        found = []
        for folder in (self._folder, Path.home() / "Downloads", Path.home() / "Documents"):
            try:
                found += [p for p in folder.iterdir() if p.suffix.lower() == ".epub" and p.is_file() and not p.name.startswith(".")]
            except OSError:
                continue
        books = []
        for path in found[:500]:
            try:
                info = read_epub(path)
            except Exception:                                      # a damaged book is simply left out of the shelf
                continue
            seen = self._state.get(str(path), {})
            total = max(1, len(info["chapters"]))
            done = 1.0 if seen.get("done") else min(0.99, (seen.get("chapter", 0) + seen.get("at", 0)) / total) if seen else 0.0
            books.append({"path": str(path), "title": info["title"], "author": info["author"], "cover": self._cover(path, info["cover"]), "progress": round(done, 3), "last": seen.get("when", 0)})
        self._books = sorted(books, key=lambda b: (-b["last"], b["title"].lower()))
        self.changed.emit()

    books = Property("QVariantList", lambda self: self._books, notify=changed)
    folder = Property(str, lambda self: str(self._folder), constant=True)
    reading = Property(str, lambda self: self._open, notify=changed)
    title = Property(str, lambda self: self._info.get("title", ""), notify=changed)
    author = Property(str, lambda self: self._info.get("author", ""), notify=changed)
    chapter = Property(int, lambda self: self._chapter, notify=changed)
    chapters = Property(int, lambda self: len(self._info.get("chapters", [])), notify=changed)
    text = Property(str, lambda self: self._text, notify=opened)
    startAt = Property(float, lambda self: float(self._state.get(self._open, {}).get("at", 0)) if self._state.get(self._open, {}).get("chapter", 0) == self._chapter else 0.0, notify=opened)
    size = Property(int, lambda self: int(self._state.get("size", 18)), notify=changed)
    paper = Property(str, lambda self: str(self._state.get("paper", "theme")), notify=changed)

    @Slot(str)
    def open(self, path: str) -> None:
        if self._demo:
            self.said.emit("This is the preview: the shelf is a sample.", False)
            return
        try:
            self._info = read_epub(Path(path))
            if not self._info["chapters"]:
                raise ValueError("empty")
            with zipfile.ZipFile(path) as z:                       # the contents list: each part's own heading
                for c in self._info["chapters"][:600]:
                    with z.open(c["name"]) as part:
                        c["title"] = chapter_title(part.read(40_000).decode("utf-8", "replace"))
        except Exception:
            self.said.emit("That book can't be opened: it's damaged, or locked by its seller (DRM).", True)
            return
        self._open = path
        self._load(min(int(self._state.get(path, {}).get("chapter", 0)), len(self._info["chapters"]) - 1))

    def _picture(self, z, chapter: str):
        """Returns the function that copies one of the book's own pictures into the cache and gives the tag showing it."""
        import hashlib
        import posixpath
        from PySide6.QtGui import QImageReader
        folder = CACHE_HOME / "books" / hashlib.sha1(self._open.encode()).hexdigest()[:16]
        names = set(z.namelist())

        def picture(src: str) -> str:
            if re.match(r"(?i)[a-z][a-z0-9+.-]*:", src):                # http:, data:, file: … nothing from outside the book
                return ""
            member = posixpath.normpath(posixpath.join(posixpath.dirname(chapter), urllib.parse.unquote(src.split("#")[0])))
            kind = Path(member).suffix.lower()
            if member not in names or kind not in (".png", ".jpg", ".jpeg", ".gif", ".webp") or z.getinfo(member).file_size > 12_000_000:
                return ""
            out = folder / (hashlib.sha1(member.encode()).hexdigest()[:16] + kind)
            try:
                if not out.exists():
                    folder.mkdir(parents=True, exist_ok=True)
                    out.write_bytes(z.read(member))
                size = QImageReader(str(out)).size()
            except OSError:
                return ""
            if not size.isValid() or size.width() < 2:
                return ""
            wide = min(size.width(), 640)
            return f'<img src="{QUrl.fromLocalFile(str(out)).toString()}" width="{wide}" height="{int(size.height() * wide / size.width())}">'
        return picture

    @Property("QVariantList", notify=changed)
    def contents(self):
        return [{"index": i, "title": c.get("title") or f"Part {i + 1}"} for i, c in enumerate(self._info.get("chapters", []))]

    @Slot(int)
    def goTo(self, index: int) -> None:
        if self._open and 0 <= index < len(self._info["chapters"]):
            self._state.setdefault(self._open, {}).update(chapter=index, at=0, when=time.time())
            self._load(index)
            self._keep()

    def _load(self, index: int) -> None:
        try:
            with zipfile.ZipFile(self._open) as z:
                member = self._info["chapters"][index]["name"]
                if z.getinfo(member).file_size > 8_000_000:
                    raise ValueError("too big")
                raw = z.read(member)
                self._text = tidy_chapter(raw.decode("utf-8", "replace"), self._picture(z, member)) or "<p> </p>"
        except Exception:
            self._text = "<p><i>This part of the book couldn't be read.</i></p>"
        if False:
            pass
        self._chapter = index
        self.changed.emit()
        self.opened.emit()

    @Slot(int)
    def turn(self, by: int) -> None:
        if not self._open:
            return
        to = self._chapter + by
        if 0 <= to < len(self._info["chapters"]):
            self._state.setdefault(self._open, {}).update(chapter=to, at=0, when=time.time())
            self._load(to)
            self._keep()
        elif to >= len(self._info["chapters"]):
            self._state.setdefault(self._open, {}).update(done=True, when=time.time())
            self._keep()
            self.said.emit("That was the last page.", False)

    @Slot(float)
    def at(self, fraction: float) -> None:
        """How far down the chapter you've read (0 to 1), so the book reopens at the same place."""
        if self._open:
            self._state.setdefault(self._open, {}).update(chapter=self._chapter, at=round(max(0.0, min(1.0, fraction)), 4), when=time.time())
            self._keep()

    @Slot()
    def close(self) -> None:
        self._open, self._text, self._info = "", "", {}
        self.rescan()
        self.changed.emit()

    @Slot(int)
    def setSize(self, size: int) -> None:
        self._state["size"] = max(12, min(34, size))
        self._keep()
        self.changed.emit()

    @Slot(str)
    def setPaper(self, paper: str) -> None:
        self._state["paper"] = paper if paper in ("theme", "sepia", "white", "black") else "theme"
        self._keep()
        self.changed.emit()


# =============================================================================================== Translate
class ArgosEngine:
    """Argos Translate: translation that runs wholly on this computer, with a language pack per pair of languages."""

    def __init__(self):
        import argostranslate.package as package        # noqa: F401  (raises ImportError when it isn't installed)
        import argostranslate.translate as translate
        self._package, self._translate = package, translate

    def pairs(self) -> list:
        """Installed pairs as [(from code, from name, to code, to name)]."""
        out = []
        for lang in self._translate.get_installed_languages():
            for t in getattr(lang, "translations_from", []) or []:
                out.append((lang.code, lang.name, t.to_lang.code, t.to_lang.name))
        return out

    def translate(self, text: str, a: str, b: str) -> str:
        return self._translate.translate(text, a, b)

    def available(self) -> list:
        self._package.update_package_index()
        return [(p.from_code, p.from_name, p.to_code, p.to_name) for p in self._package.get_available_packages()]

    def install(self, a: str, b: str) -> None:
        pack = next(p for p in self._package.get_available_packages() if p.from_code == a and p.to_code == b)
        self._package.install_from_path(pack.download())

    def install_file(self, path: str) -> None:
        """A language pack you already have as a file (.argosmodel), for a computer that can't fetch one."""
        self._package.install_from_path(path)


class Translate(Worker):
    """Translate text without it leaving the computer. Language packs are fetched once each (that fetch is the only
    time the network is used); after that it works offline."""
    changed = Signal()
    said = Signal(str, bool)

    def __init__(self, demo: bool = False, target=None, engine=None):
        super().__init__()
        self._demo, self._engine, self._pairs, self._offered = demo, engine, [], []
        self._a, self._b, self._out, self._busy, self._fetching, self._count = "", "", "", False, "", 0
        self._file = DATA_HOME / "translate.json"
        self._doc = str(target) if target and Path(str(target)).suffix.lower() in (".txt", ".md", ".text") and Path(str(target)).is_file() else ""
        try:
            kept = json.loads(self._file.read_text(encoding="utf-8")) if not demo else {}
        except (OSError, ValueError):
            kept = {}
        self._keep_history = bool(kept.get("keep", True)) if isinstance(kept, dict) else True
        self._history = [h for h in kept.get("history", []) if isinstance(h, dict) and h.get("from") and h.get("to")][:30] if isinstance(kept, dict) else []
        if demo:
            self._history = [{"from": "Good morning. The coffee is ready.", "to": "God morgen. Kaffen er klar.", "a": "en", "b": "nb", "pair": "English → Norwegian"},
                             {"from": "Where is the station?", "to": "¿Dónde está la estación?", "a": "en", "b": "es", "pair": "English → Spanish"}]
            self._pairs = [("en", "English", "es", "Spanish"), ("es", "Spanish", "en", "English"), ("en", "English", "nb", "Norwegian"), ("en", "English", "fr", "French")]
            self._a, self._b, self._out = "en", "nb", "God morgen. Kaffen er klar, og snøen har lagt seg over fjorden."
            return
        if engine is None:
            try:
                self._engine = ArgosEngine()
            except Exception:                                      # not installed (or half-installed): the screen explains
                self._engine = None
        self._reload()

    def _reload(self) -> None:
        try:
            self._pairs = sorted(set(self._engine.pairs()), key=lambda p: (p[1], p[3])) if self._engine else []
        except Exception:
            self._pairs = []
        froms = [p[0] for p in self._pairs]
        if self._a not in froms:
            self._a = "en" if "en" in froms else (froms[0] if froms else "")
        tos = [p[2] for p in self._pairs if p[0] == self._a]
        if self._b not in tos:
            self._b = tos[0] if tos else ""
        self.changed.emit()

    def _save(self) -> None:
        if self._demo:
            return
        try:
            self._file.parent.mkdir(parents=True, exist_ok=True)
            self._file.write_text(json.dumps({"keep": self._keep_history, "history": self._history if self._keep_history else []}), encoding="utf-8")
            os.chmod(self._file, 0o600)
        except OSError:
            pass

    def _name(self, code: str) -> str:
        return next((n for a, an, b, bn in self._pairs for c, n in ((a, an), (b, bn)) if c == code), code)

    history = Property("QVariantList", lambda self: self._history, notify=changed)
    keepHistory = Property(bool, lambda self: self._keep_history, notify=changed)
    document = Property(str, lambda self: Path(self._doc).name if self._doc else "", notify=changed)      # a text file opened to be translated
    localPacks = Property("QVariantList", lambda self: recent((".argosmodel",)) if not self._demo else [], notify=changed)

    @Slot(bool)
    def setKeepHistory(self, on: bool) -> None:
        self._keep_history = bool(on)
        if not on:
            self._history = []
        self._save()
        self.changed.emit()

    @Slot()
    def clearHistory(self) -> None:
        self._history = []
        self._save()
        self.changed.emit()

    @Slot()
    def dropDocument(self) -> None:
        self._doc = ""
        self.changed.emit()

    @Slot()
    def translateDocument(self) -> None:
        """Translate the opened text file, paragraph by paragraph, into a new file beside it. The original is untouched."""
        if self._demo or not self._doc or self._engine is None or not self._a or not self._b or self._busy:
            return
        source, a, b = Path(self._doc), self._a, self._b
        try:
            if source.stat().st_size > 2_000_000:
                raise OSError("too big")
            text = source.read_text(encoding="utf-8", errors="replace")
        except OSError:
            self.said.emit("That file is too large or can't be read. Text files up to 2 MB work.", True)
            return
        target = source.with_name(f"{source.stem} ({self._name(b)}){source.suffix}")
        n = 2
        while target.exists():
            target = source.with_name(f"{source.stem} ({self._name(b)} {n}){source.suffix}")
            n += 1
        self._busy = True
        self.changed.emit()

        def work():
            out = []
            for block in re.split(r"(\n\s*\n)", text):               # blank lines between paragraphs are kept as they were
                out.append(block if not block.strip() else self._engine.translate(block, a, b))
            target.write_text("".join(out), encoding="utf-8")
            return target

        def then(result):
            self._busy = False
            if isinstance(result, Exception):
                self.said.emit(f"Couldn't translate the file: {str(result)[:120]}", True)
            else:
                self._doc = ""
                self.said.emit(f"Saved “{result.name}” beside the original.", False)
            self.changed.emit()
        self.bg(work, then)

    @Slot(str)
    def addPackFile(self, path: str) -> None:
        if self._demo or self._engine is None or self._fetching or not Path(path).is_file():
            return
        self._fetching = "file"
        self.changed.emit()

        def then(result):
            self._fetching = ""
            if isinstance(result, Exception):
                self.said.emit("That file isn't a language pack this translator can use.", True)
            else:
                self.said.emit("Installed from the file.", False)
                self._reload()
            self.changed.emit()
        self.bg(lambda: self._engine.install_file(path), then)

    ready = Property(bool, lambda self: self._demo or self._engine is not None, constant=True)
    hasPacks = Property(bool, lambda self: bool(self._pairs), notify=changed)
    source = Property(str, lambda self: self._a, notify=changed)
    target = Property(str, lambda self: self._b, notify=changed)
    result = Property(str, lambda self: self._out, notify=changed)
    busy = Property(bool, lambda self: self._busy, notify=changed)
    fetching = Property(str, lambda self: self._fetching, notify=changed)
    offered = Property("QVariantList", lambda self: self._offered, notify=changed)

    @Property("QVariantList", notify=changed)
    def sources(self):
        seen = {}
        for a, an, _b, _bn in self._pairs:
            seen[a] = an
        return [{"code": c, "name": n} for c, n in sorted(seen.items(), key=lambda x: x[1])]

    @Property("QVariantList", notify=changed)
    def targets(self):
        return [{"code": b, "name": bn} for a, _an, b, bn in self._pairs if a == self._a]

    @Property("QVariantList", notify=changed)
    def packs(self):
        return [{"from": an, "to": bn} for _a, an, _b, bn in self._pairs]

    @Slot(str)
    def setSource(self, code: str) -> None:
        self._a = code
        self._reload()

    @Slot(str)
    def setTarget(self, code: str) -> None:
        self._b = code
        self.changed.emit()

    @Slot(result=bool)
    def swap(self) -> bool:
        """Turn the pair round, if the pack for the other direction is here."""
        if any(p[0] == self._b and p[2] == self._a for p in self._pairs):
            self._a, self._b = self._b, self._a
            self.changed.emit()
            return True
        self.said.emit("The pack for the other direction isn't installed.", False)
        return False

    @Slot(str)
    def translate(self, text: str) -> None:
        text = text.strip()
        if self._demo:
            return
        if not text or not self._a or not self._b or self._engine is None:
            self._out = ""
            self.changed.emit()
            return
        if len(text) > 20_000:
            self.said.emit("That's a lot at once. Translate it a few pages at a time.", True)
            return
        self._count += 1
        mine, a, b = self._count, self._a, self._b
        self._busy = True
        self.changed.emit()

        def then(result):
            if mine != self._count:
                return                                             # something newer was asked for meanwhile
            self._busy = False
            if isinstance(result, Exception):
                self._out = ""
                self.said.emit(f"Couldn't translate that: {str(result)[:120]}", True)
            else:
                self._out = str(result)
                if self._keep_history and len(text) >= 3 and self._out and (not self._history or self._history[0]["from"] != text or self._history[0]["b"] != b):
                    grown = self._history and self._history[0]["b"] == b and text.startswith(self._history[0]["from"])       # still typing the same thing
                    entry = {"from": text[:2000], "to": self._out[:4000], "a": a, "b": b, "pair": f"{self._name(a)} → {self._name(b)}"}
                    self._history = ([entry] + self._history[1 if grown else 0:])[:30]
                    self._save()
            self.changed.emit()
        self.bg(lambda: self._engine.translate(text, a, b), then)

    @Slot()
    def lookForPacks(self) -> None:
        if self._demo or self._engine is None or self._fetching:
            return
        self._fetching = "list"
        self.changed.emit()

        def then(result):
            self._fetching = ""
            if isinstance(result, Exception):
                self.said.emit(plain_net_error(result), True)
            else:
                have = {(p[0], p[2]) for p in self._pairs}
                self._offered = [{"a": a, "from": an, "b": b, "to": bn} for a, an, b, bn in sorted(result, key=lambda p: (p[1], p[3])) if (a, b) not in have]
            self.changed.emit()
        self.bg(self._engine.available, then)

    @Slot(str, str)
    def getPack(self, a: str, b: str) -> None:
        if self._demo or self._engine is None or self._fetching:
            return
        self._fetching = f"{a}>{b}"
        self.changed.emit()

        def then(result):
            self._fetching = ""
            if isinstance(result, Exception):
                self.said.emit("That pack didn't arrive: " + plain_net_error(result), True)
            else:
                self._offered = [o for o in self._offered if (o["a"], o["b"]) != (a, b)]
                self.said.emit("Installed. It works offline from now on.", False)
                self._reload()
            self.changed.emit()
        self.bg(lambda: self._engine.install(a, b), then)


def make(app: str, demo: bool, target):
    return globals()[{"phone": "Phone", "print": "PrintScan", "maps": "Maps", "podcasts": "Podcasts", "books": "Books", "translate": "Translate"}[app]](demo, target)
