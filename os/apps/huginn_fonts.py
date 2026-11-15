"""Fonts: every typeface on the computer, shown in your own words. Try a font file before installing it, install it
for yourself with one click (a .zip from a font site works too), and remove the ones you installed.

Fonts you install go to ~/.local/share/fonts (only you, no password needed); fonts that came with the system are
shown but can't be removed from here."""
import hashlib
import json
import os
import shutil
import subprocess
import zipfile
from pathlib import Path

from PySide6.QtCore import Property, QObject, QTimer, Signal, Slot
from PySide6.QtGui import QFontDatabase, QGuiApplication

HOME = Path.home()
MINE = Path(os.environ.get("XDG_DATA_HOME") or HOME / ".local/share") / "fonts"
OLD_MINE = HOME / ".fonts"
STATE = Path(os.environ.get("XDG_DATA_HOME") or HOME / ".local/share") / "huginn" / "fonts.json"
FONT_EXT = (".ttf", ".otf", ".ttc", ".otc", ".woff", ".woff2", ".pfb")
PICK_EXT = FONT_EXT + (".zip",)
FORMATS = {"TrueType": "TrueType", "CFF": "OpenType (PostScript)", "Type 1": "Type 1", "PCF": "Bitmap", "BDF": "Bitmap"}
SAMPLES = ["The quick brown fox jumps over the lazy dog", "Sphinx of black quartz, judge my vow", "Huginn flies out over the world each morning",
           "0123456789 £$€¥ &?!@#%"]
WEIGHTS = {"thin": 100, "hairline": 100, "extralight": 200, "ultralight": 200, "light": 300, "book": 400, "regular": 400, "normal": 400,
           "medium": 500, "semibold": 600, "demibold": 600, "bold": 700, "extrabold": 800, "ultrabold": 800, "black": 900, "heavy": 900}


def mine(path: str) -> bool:
    p = os.path.realpath(path)
    return any(p.startswith(os.path.realpath(d) + os.sep) for d in (MINE, OLD_MINE))


def weight_of(style: str) -> int:
    s = style.lower().replace(" ", "").replace("-", "")
    for word in sorted(WEIGHTS, key=len, reverse=True):
        if word in s:
            return WEIGHTS[word]
    return 400


def style_order(style: str) -> tuple:
    s = style.lower()
    return (weight_of(style), "italic" in s or "oblique" in s, s)


def read_fc(text: str) -> list:
    """`fc-list --format '%{family[0]}\\t%{style[0]}\\t%{file}\\t%{spacing}\\t%{fontformat}\\n'` -> families."""
    fams = {}
    for line in text.splitlines():
        parts = line.split("\t")
        if len(parts) < 3 or not parts[0].strip() or not parts[2]:
            continue
        family, style, path = parts[0].strip(), (parts[1] or "Regular").strip(), parts[2]
        spacing, fmt = (parts[3] if len(parts) > 3 else ""), (parts[4] if len(parts) > 4 else "")
        f = fams.setdefault(family, {"name": family, "styles": [], "files": [], "mine": False, "mono": False, "format": FORMATS.get(fmt, fmt or "Font")})
        if style not in f["styles"]:
            f["styles"].append(style)
        if path not in f["files"]:
            f["files"].append(path)
        f["mine"] = f["mine"] or mine(path)
        f["mono"] = f["mono"] or spacing in ("100", "110")         # fontconfig: 100 mono, 110 charcell
    out = sorted(fams.values(), key=lambda f: f["name"].lower())
    for f in out:
        f["styles"].sort(key=style_order)
    return out


def list_fonts() -> list:
    try:
        text = subprocess.run(["fc-list", "--format", "%{family[0]}\t%{style[0]}\t%{file}\t%{spacing}\t%{fontformat}\n"],
                              capture_output=True, text=True, timeout=30).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    return [f for f in read_fc(text) if not f["name"].startswith(".")]


def family_of_file(path: str) -> list:
    """The family names inside a font file (empty when it isn't a font fontconfig can read)."""
    try:
        out = subprocess.run(["fc-query", "--format", "%{family[0]}\n", path], capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError):
        return []
    return sorted({x.strip() for x in out.stdout.splitlines() if x.strip()}) if out.returncode == 0 else []


def same_file(a: Path, b: Path) -> bool:
    try:
        if a.stat().st_size != b.stat().st_size:
            return False
        return hashlib.sha256(a.read_bytes()).digest() == hashlib.sha256(b.read_bytes()).digest()
    except OSError:
        return False


def unpack_zip(path: Path, into: Path) -> list:
    """Font files inside a .zip go into `into` (flattened, no paths from the archive are trusted). Returns them."""
    got = []
    with zipfile.ZipFile(path) as z:
        for info in z.infolist():
            name = Path(info.filename).name
            if info.is_dir() or "__MACOSX" in info.filename or name.startswith(".") or not name.lower().endswith(FONT_EXT):
                continue
            if info.file_size > 60 * 1024 * 1024:
                continue
            into.mkdir(parents=True, exist_ok=True)
            target = into / name
            with z.open(info) as src, open(target, "wb") as dst:
                shutil.copyfileobj(src, dst)
            got.append(target)
    return got


class Fonts(QObject):
    changed = Signal()
    said = Signal(str, bool)

    def __init__(self, demo: bool = False, target: str = ""):
        super().__init__()
        self._demo = demo
        self._fams = list_fonts()
        self._view, self._query, self._open = "all", "", ""
        self._sample, self._size = SAMPLES[0], 34
        self._starred, self._trying = [], None        # trying: {"name", "path", "families": [...], "loaded": [...]}
        self._busy = ""
        self._cache = None
        if demo:
            names = {f["name"] for f in self._fams}
            for f in self._fams:
                if f["name"] in ("Caladea", "Carlito", "GFS Baskerville"):
                    f["mine"] = True
            self._starred = [n for n in ("Inter", "DejaVu Serif") if n in names]
            self._open = "Inter" if "Inter" in names else (self._fams[0]["name"] if self._fams else "")
        else:
            try:
                self._starred = json.loads(STATE.read_text(encoding="utf-8")).get("starred", [])
            except (OSError, ValueError, AttributeError):
                pass
        if target:
            QTimer.singleShot(0, lambda: self.tryFile(target))

    def _keep(self) -> None:
        if not self._demo:
            try:
                STATE.parent.mkdir(parents=True, exist_ok=True)
                STATE.write_text(json.dumps({"starred": self._starred}), encoding="utf-8")
            except OSError:
                pass

    def _reload(self) -> None:
        self._fams = list_fonts()
        self.changed.emit()

    def _recache(self, then_say: str) -> None:
        """fc-cache in the background, then reload the list."""
        self._busy = "updating the font list"
        self.changed.emit()
        try:
            proc = subprocess.Popen(["fc-cache", "-f", str(MINE)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError:
            self._busy = ""
            self._reload()
            self.said.emit(then_say, False)
            return
        timer = QTimer(self)
        timer.setInterval(250)

        def check():
            if proc.poll() is None:
                return
            timer.stop()
            timer.deleteLater()
            self._busy = ""
            self._reload()
            self.said.emit(then_say, False)
        timer.timeout.connect(check)
        timer.start()

    # ---------------- what QML sees
    def _get_families(self) -> list:
        words = self._query.lower().split()
        rows = self._fams
        if self._view == "mine":
            rows = [f for f in rows if f["mine"]]
        elif self._view == "starred":
            rows = [f for f in rows if f["name"] in self._starred]
        elif self._view == "mono":
            rows = [f for f in rows if f["mono"]]
        if words:
            rows = [f for f in rows if all(w in f["name"].lower() for w in words)]
        return [{"name": f["name"], "styles": len(f["styles"]), "mine": f["mine"], "star": f["name"] in self._starred, "mono": f["mono"]} for f in rows]

    def _get_family(self) -> dict:
        f = next((x for x in self._fams if x["name"] == self._open), None)
        if not f:
            return {}
        styles = [{"name": s, "weight": weight_of(s), "italic": "italic" in s.lower() or "oblique" in s.lower()} for s in f["styles"]]
        return {"name": f["name"], "styles": styles, "files": len(f["files"]), "where": "Installed by you" if f["mine"] else "Came with the system",
                "mine": f["mine"], "star": f["name"] in self._starred, "format": f["format"], "mono": f["mono"]}

    def _get_counts(self) -> dict:
        return {"all": len(self._fams), "mine": sum(1 for f in self._fams if f["mine"]), "starred": sum(1 for f in self._fams if f["name"] in self._starred),
                "mono": sum(1 for f in self._fams if f["mono"])}

    families = Property("QVariantList", _get_families, notify=changed)
    family = Property("QVariantMap", _get_family, notify=changed)
    counts = Property("QVariantMap", _get_counts, notify=changed)
    view = Property(str, lambda self: self._view, notify=changed)
    sample = Property(str, lambda self: self._sample, notify=changed)
    size = Property(int, lambda self: self._size, notify=changed)
    busy = Property(str, lambda self: self._busy, notify=changed)
    trying = Property("QVariantMap", lambda self: dict(self._trying) if self._trying else {}, notify=changed)
    samples = Property("QStringList", lambda self: SAMPLES, constant=True)

    @Slot(str)
    def setView(self, v: str) -> None:
        self._view = v
        self.changed.emit()

    @Slot(str)
    def search(self, text: str) -> None:
        self._query = text.strip()
        self.changed.emit()

    @Slot(str)
    def open(self, name: str) -> None:
        self._open = name
        self.changed.emit()

    @Slot()
    def close(self) -> None:
        self._open = ""
        self.changed.emit()

    @Slot(str)
    def setSample(self, text: str) -> None:
        self._sample = text
        self.changed.emit()

    @Slot(int)
    def setSize(self, n: int) -> None:
        self._size = max(10, min(120, n))
        self.changed.emit()

    @Slot(str)
    def star(self, name: str) -> None:
        if name in self._starred:
            self._starred.remove(name)
        else:
            self._starred.append(name)
        self._keep()
        self.changed.emit()

    @Slot(str)
    def copyName(self, name: str) -> None:
        if QGuiApplication.instance():
            QGuiApplication.clipboard().setText(name)
            self.said.emit(f"Copied “{name}”", False)

    @Slot(result="QVariantList")
    def fileChoices(self) -> list:
        """Font files and font .zips in Downloads, Desktop and Documents, newest first."""
        found = []
        for folder in ("Downloads", "Desktop", "Documents"):
            base = HOME / folder
            if not base.is_dir():
                continue
            for root, dirs, files in os.walk(base):
                dirs[:] = [d for d in dirs if not d.startswith(".")]
                if root.count(os.sep) - str(base).count(os.sep) > 2:
                    dirs[:] = []
                for name in files:
                    if name.lower().endswith(PICK_EXT):
                        p = Path(root) / name
                        try:
                            found.append((p.stat().st_mtime, p))
                        except OSError:
                            pass
        found.sort(reverse=True)
        return [{"path": str(p), "name": p.name, "where": p.parent.name} for _, p in found[:60]]

    @Slot(str, result=str)
    def tryFile(self, path: str) -> str:
        """Load a font file (or the fonts in a .zip) just for this window, to look at before installing."""
        p = Path(path.replace("file://", "")).expanduser()
        if not p.is_file():
            return "That file isn't there any more."
        files = [p]
        if p.suffix.lower() == ".zip":
            scratch = Path(os.environ.get("XDG_RUNTIME_DIR") or "/tmp") / "huginn-fonts-try" / hashlib.sha1(str(p).encode()).hexdigest()[:10]
            shutil.rmtree(scratch, ignore_errors=True)
            try:
                files = unpack_zip(p, scratch)
            except (OSError, zipfile.BadZipFile):
                return "That .zip couldn't be opened."
            if not files:
                return "There are no fonts in that .zip."
        fams, loaded = [], []
        for f in files:
            fid = QFontDatabase.addApplicationFont(str(f))
            if fid >= 0:
                loaded.append(fid)
                for name in QFontDatabase.applicationFontFamilies(fid):
                    if name not in fams:
                        fams.append(name)
        if not fams:
            return "That doesn't look like a font."
        self._trying = {"name": p.name, "path": str(p), "families": fams, "family": fams[0], "files": len(files),
                        "installed": any(f["name"] in fams and f["mine"] for f in self._fams)}
        self.changed.emit()
        return ""

    @Slot()
    def stopTrying(self) -> None:
        self._trying = None
        self.changed.emit()

    @Slot(str, result=str)
    def install(self, path: str) -> str:
        """Copy a font (or a .zip's fonts) into ~/.local/share/fonts, then refresh fontconfig."""
        if self._demo:
            self.said.emit("Installed (demo)", False)
            self._trying = None
            self.changed.emit()
            return ""
        p = Path(path.replace("file://", "")).expanduser()
        if not p.is_file():
            return "That file isn't there any more."
        MINE.mkdir(parents=True, exist_ok=True)
        if p.suffix.lower() == ".zip":
            try:
                got = unpack_zip(p, MINE / p.stem)
            except (OSError, zipfile.BadZipFile):
                return "That .zip couldn't be opened."
            good = [g for g in got if family_of_file(str(g))]
            for g in got:
                if g not in good:
                    g.unlink(missing_ok=True)
            if not good:
                shutil.rmtree(MINE / p.stem, ignore_errors=True)
                return "There are no fonts in that .zip."
            names = sorted({n for g in good for n in family_of_file(str(g))})
        else:
            names = family_of_file(str(p))
            if not names:
                return "That doesn't look like a font."
            target = MINE / p.name
            if target.exists():
                if same_file(p, target):
                    return f"{names[0]} is already installed."
                target = MINE / f"{p.stem}-{hashlib.sha1(p.read_bytes()).hexdigest()[:6]}{p.suffix}"
            try:
                shutil.copy2(p, target)
            except OSError as e:
                return f"Couldn't copy it: {e.strerror}"
        self._trying = None
        self._open = names[0]
        self._recache(f"Installed {', '.join(names[:3])}" + (" and more" if len(names) > 3 else ""))
        return ""

    @Slot(str, result=str)
    def remove(self, name: str) -> str:
        f = next((x for x in self._fams if x["name"] == name), None)
        if not f or not f["mine"]:
            return "Only fonts you installed can be removed here."
        if self._demo:
            self.said.emit(f"Removed {name} (demo)", False)
            return ""
        for path in f["files"]:
            if mine(path):
                try:
                    os.unlink(path)
                except OSError:
                    pass
                parent = Path(path).parent
                while parent != MINE and mine(str(parent / "x")) and parent.is_dir() and not any(parent.iterdir()):
                    parent.rmdir()
                    parent = parent.parent
        if name in self._starred:
            self._starred.remove(name)
            self._keep()
        self._open = ""
        self._recache(f"Removed {name}. Apps that are open may keep it until they restart.")
        return ""
