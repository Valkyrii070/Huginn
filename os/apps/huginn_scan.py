"""Scan: documents from a scanner or from photos, cleaned up and made into PDFs you can search.

    scanners        SANE (`scanimage`): flatbeds and document feeders, colour, grey or black and white, any resolution
    photos          a photo of a page: Scan finds the paper's four corners and straightens it (perspective)
    clean-up        Document (white paper, black ink, shadows gone), Grey, Colour (even light), or the photo as it is
    reading text    Tesseract: the PDF gets a hidden layer of text, so it can be searched and copied; or just the text
    saving          a PDF in Documents/Scans (A4, Letter or the page's own size), or pictures

A document is a folder of pages: each page keeps its original picture and what was done to it (corners, turn,
clean-up), so nothing is lost and anything can be redone.
"""
import json
import os
import re
import shutil
import subprocess
import threading
import time
import uuid
from pathlib import Path

import numpy as np
from PySide6.QtCore import (Property, QMarginsF, QObject, QPointF, QProcess, QRectF, QSizeF, QStandardPaths, QTimer, QUrl, Qt, Signal,
                            Slot)
from PySide6.QtGui import QImage, QPageLayout, QPageSize, QPainter, QPdfWriter, QPolygonF, QTransform
from PySide6.QtQuick import QQuickImageProvider

try:
    import cv2
except ImportError:                                          # corners are still found, a simpler way
    cv2 = None

DATA = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share") / "huginn" / "scan"
FMT = QImage.Format.Format_RGB888
MODES = [("document", "Document"), ("grey", "Grey"), ("colour", "Colour"), ("photo", "As it is")]
PAPERS = {"a4": ("A4", QPageSize.PageSizeId.A4), "letter": ("Letter", QPageSize.PageSizeId.Letter), "page": ("Page's own size", None)}
IMAGES = (".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff", ".bmp", ".heic", ".pnm", ".pgm", ".ppm")


# ------------------------------------------------------------------------------------------- pictures and numbers
def to_array(img: QImage) -> np.ndarray:
    img = img.convertToFormat(FMT)
    w, h, bpl = img.width(), img.height(), img.bytesPerLine()
    return np.frombuffer(img.constBits(), np.uint8, count=bpl * h).reshape(h, bpl)[:, :w * 3].reshape(h, w, 3).copy()


def to_image(a: np.ndarray) -> QImage:
    a = np.ascontiguousarray(a.astype(np.uint8))
    if a.ndim == 2:
        a = np.ascontiguousarray(np.repeat(a[..., None], 3, axis=2))
    h, w = a.shape[:2]
    return QImage(a.data, w, h, w * 3, FMT).copy()


def luma(a: np.ndarray) -> np.ndarray:
    return a[..., 0] * 0.299 + a[..., 1] * 0.587 + a[..., 2] * 0.114


def box_blur(g: np.ndarray, r: int) -> np.ndarray:
    """A fast box blur of a 2-D array (summed-area table), radius r."""
    if r < 1:
        return g.astype(np.float32)
    p = np.pad(g.astype(np.float64), r + 1, mode="edge")
    s = p.cumsum(0).cumsum(1)
    k = 2 * r + 1
    out = s[k:, k:] - s[:-k, k:] - s[k:, :-k] + s[:-k, :-k]
    h, w = g.shape
    return (out[:h, :w] / (k * k)).astype(np.float32)


def stretch(c: np.ndarray, lo: float = 1, hi: float = 99) -> np.ndarray:
    a, b = np.percentile(c, lo), np.percentile(c, hi)
    return np.clip((c - a) * (255.0 / max(1.0, b - a)), 0, 255)


def background(g: np.ndarray) -> np.ndarray:
    """The paper's own brightness everywhere (the light falling on it), without the ink: a blur of a small copy where
    dark marks are first lifted to their surroundings."""
    h, w = g.shape
    f = max(1, int(max(h, w) / 400))
    small = g[::f, ::f].astype(np.float32)
    lifted = np.maximum(small, box_blur(small, 3))           # thin ink disappears
    for _ in range(2):
        lifted = np.maximum(lifted, box_blur(lifted, 6))
    bg = box_blur(lifted, max(4, int(max(small.shape) / 40)))
    yi = np.minimum((np.arange(h) / f).astype(int), bg.shape[0] - 1)
    xi = np.minimum((np.arange(w) / f).astype(int), bg.shape[1] - 1)
    return bg[yi][:, xi]


def enhance(a: np.ndarray, mode: str) -> np.ndarray:
    """Clean a straightened page: Document (white paper, crisp ink, shadows gone), Grey, Colour (even light), or as it is."""
    if mode == "photo":
        return a
    if mode == "colour":
        g = luma(a)
        bg = np.maximum(background(g), 1)
        lit = a.astype(np.float32) * (np.percentile(bg, 95) / bg)[..., None]       # even out the light
        out = np.stack([stretch(lit[..., i], 0.5, 99.5) for i in range(3)], axis=2)
        return out.astype(np.uint8)
    g = luma(a)
    if mode == "grey":
        bg = np.maximum(background(g), 1)
        return stretch(g * (np.percentile(bg, 95) / bg), 0.5, 99.5).astype(np.uint8)
    # document: divide out the paper, then a curve that sends paper to white and ink to black
    bg = np.maximum(background(g), 1)
    n = np.clip(g / bg, 0, 1.2)
    out = np.clip((n - 0.45) / (0.88 - 0.45), 0, 1) ** 1.6
    return (out * 255).astype(np.uint8)


def order_corners(pts) -> list:
    """Four points as top-left, top-right, bottom-right, bottom-left."""
    pts = np.asarray(pts, dtype=np.float64).reshape(4, 2)
    s, d = pts.sum(1), pts[:, 0] - pts[:, 1]
    return [pts[np.argmin(s)].tolist(), pts[np.argmax(d)].tolist(), pts[np.argmax(s)].tolist(), pts[np.argmin(d)].tolist()]


def find_page(a: np.ndarray) -> list:
    """The paper's four corners in a photo (as fractions of the width and height), or the whole picture when no page
    stands out. Works on a small copy: the paper is the large bright area that differs from its surroundings."""
    h, w = a.shape[:2]
    f = max(1, int(max(h, w) / 640))
    small = a[::f, ::f]
    sh, sw = small.shape[:2]
    whole = [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]]
    quad = None
    if cv2 is not None:
        g = cv2.GaussianBlur(cv2.cvtColor(np.ascontiguousarray(small), cv2.COLOR_RGB2GRAY), (5, 5), 0)
        edges = cv2.dilate(cv2.Canny(g, 40, 120), np.ones((3, 3), np.uint8))
        contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
        for c in sorted(contours, key=cv2.contourArea, reverse=True)[:8]:
            peri = cv2.arcLength(c, True)
            approx = cv2.approxPolyDP(c, 0.02 * peri, True)
            if len(approx) == 4 and cv2.isContourConvex(approx) and cv2.contourArea(approx) > 0.15 * sh * sw:
                quad = order_corners(approx.reshape(4, 2))
                break
    if quad is None:                                          # bright paper against a darker background
        g = luma(small)
        t = otsu(g)
        mask = g > t
        if 0.12 < mask.mean() < 0.97:
            ys, xs = np.nonzero(mask)
            pts = np.stack([xs, ys], 1).astype(np.float64)
            s, d = pts.sum(1), pts[:, 0] - pts[:, 1]
            quad = [pts[np.argmin(s)].tolist(), pts[np.argmax(d)].tolist(), pts[np.argmax(s)].tolist(), pts[np.argmin(d)].tolist()]
    if quad is None:
        return whole
    cx, cy = sum(q[0] for q in quad) / 4, sum(q[1] for q in quad) / 4
    quad = [[x + (cx - x) * 0.006, y + (cy - y) * 0.006] for x, y in quad]       # just inside the paper's edge, so no table shows
    return [[round(max(0.0, min(1.0, x / max(1, sw - 1))), 4), round(max(0.0, min(1.0, y / max(1, sh - 1))), 4)] for x, y in quad]


def otsu(g: np.ndarray) -> float:
    hist, edges = np.histogram(g, bins=256, range=(0, 256))
    p = hist / max(1, hist.sum())
    omega, mu = np.cumsum(p), np.cumsum(p * np.arange(256))
    between = (mu[-1] * omega - mu) ** 2 / np.maximum(omega * (1 - omega), 1e-12)
    return float(np.argmax(between))


def straighten(img: QImage, corners: list) -> QImage:
    """The paper inside `corners` (fractions) as a flat rectangle, its size taken from the paper's own edges."""
    w, h = img.width(), img.height()
    pts = [QPointF(x * (w - 1), y * (h - 1)) for x, y in corners]
    if all(abs(a - b) < 1e-4 for (a, b) in zip([c for p in corners for c in p], [0, 0, 1, 0, 1, 1, 0, 1])):
        return img.convertToFormat(FMT)
    dist = lambda p, q: ((p.x() - q.x()) ** 2 + (p.y() - q.y()) ** 2) ** 0.5
    out_w = int(max(dist(pts[0], pts[1]), dist(pts[3], pts[2])))
    out_h = int(max(dist(pts[0], pts[3]), dist(pts[1], pts[2])))
    out_w, out_h = max(16, out_w), max(16, out_h)
    tr = QTransform()
    if not QTransform.quadToQuad(QPolygonF(pts), QPolygonF([QPointF(0, 0), QPointF(out_w, 0), QPointF(out_w, out_h), QPointF(0, out_h)]), tr):
        return img.convertToFormat(FMT)
    out = QImage(out_w, out_h, FMT)
    out.fill(Qt.GlobalColor.white)
    p = QPainter(out)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    p.setTransform(tr)
    p.drawImage(0, 0, img)
    p.end()
    return out


def process(original: QImage, page: dict, limit: int = 0) -> QImage:
    """A page as it will be saved: straightened, turned, cleaned up. `limit` makes a smaller copy first (previews)."""
    img = original
    if limit and max(img.width(), img.height()) > limit:
        img = img.scaled(limit, limit, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
    img = straighten(img, page.get("corners") or [[0, 0], [1, 0], [1, 1], [0, 1]])
    turn = int(page.get("turn", 0)) % 360
    if turn:
        img = img.transformed(QTransform().rotate(turn), Qt.TransformationMode.SmoothTransformation)
    return to_image(enhance(to_array(img), page.get("mode", "document")))


# ------------------------------------------------------------------------------------------- scanners (SANE)
def list_scanners() -> list:
    if not shutil.which("scanimage"):
        return []
    try:
        out = subprocess.run(["scanimage", "-f", "%d\t%v\t%m\t%t%n"], capture_output=True, text=True, timeout=40).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    found = []
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) >= 4 and parts[0]:
            name = " ".join(x for x in (parts[1], parts[2]) if x and x.lower() not in ("noname", "unknown")) or parts[0]
            found.append({"id": parts[0], "name": name, "kind": parts[3]})
    return found


def parse_options(text: str) -> dict:
    """What `scanimage -d <device> -A` says the scanner can do: modes, resolutions and sources (flatbed, feeder)."""
    out = {"modes": [], "resolutions": [], "sources": []}
    for line in text.splitlines():
        m = re.match(r"\s+--(mode|resolution|source)\s+(.+?)\s+\[(.*?)\]", line)
        if not m:
            continue
        key, values, _now = m.groups()
        if key == "resolution":
            rng = re.match(r"(\d+)\.\.(\d+)", values)
            if rng:
                lo, hi = int(rng.group(1)), int(rng.group(2))
                out["resolutions"] = [r for r in (75, 150, 200, 300, 600, 1200) if lo <= r <= hi] or [lo]
            else:
                out["resolutions"] = [int(v) for v in re.findall(r"\d+", values.replace("dpi", ""))]
        else:
            out[key + "s"] = [v.strip() for v in values.split("|") if v.strip()]
    return out


def scanner_options(device: str) -> dict:
    try:
        out = subprocess.run(["scanimage", "-d", device, "-A"], capture_output=True, text=True, timeout=40).stdout
    except (OSError, subprocess.SubprocessError):
        out = ""
    return parse_options(out)


def scan_command(device: str, mode: str, dpi: int, source: str, target: str, batch: bool) -> list:
    args = ["scanimage", "-d", device, "--format=png", "-p"]
    if mode:
        args += ["--mode", mode]
    if dpi:
        args += ["--resolution", str(dpi)]
    if source:
        args += ["--source", source]
    if batch:
        args += [f"--batch={target}", "--batch-start=1"]
    else:
        args += ["-o", target]
    return args


# ------------------------------------------------------------------------------------------- reading text (Tesseract)
def ocr_languages() -> list:
    if not shutil.which("tesseract"):
        return []
    try:
        out = subprocess.run(["tesseract", "--list-langs"], capture_output=True, text=True, timeout=20).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    return [l.strip() for l in out.splitlines()[1:] if l.strip() and l.strip() != "osd"]


def read_text(path: str, lang: str = "eng") -> str:
    try:
        r = subprocess.run(["tesseract", path, "stdout", "-l", lang or "eng", "--psm", "3"], capture_output=True, text=True, timeout=180)
    except (OSError, subprocess.SubprocessError):
        return ""
    return r.stdout.strip()


def searchable_pdf(images: list, target: str, lang: str = "eng") -> bool:
    """One PDF from page pictures, each with Tesseract's hidden text over it."""
    work = Path(target).with_suffix("")
    listing = work.with_name(work.name + ".pages.txt")
    listing.write_text("\n".join(images) + "\n", encoding="utf-8")
    try:
        r = subprocess.run(["tesseract", str(listing), str(work), "-l", lang or "eng", "pdf"], capture_output=True, timeout=600)
    except (OSError, subprocess.SubprocessError):
        return False
    finally:
        listing.unlink(missing_ok=True)
    return r.returncode == 0 and Path(str(work) + ".pdf").is_file()


def plain_pdf(images: list, target: str, paper: str, dpis: list) -> None:
    """A PDF of the pages as pictures, each fitted to the paper (or at its own size)."""
    writer = QPdfWriter(target)
    writer.setTitle(Path(target).stem)
    writer.setCreator("Huginn Scan")
    writer.setResolution(300)
    painter = None
    for k, path in enumerate(images):
        img = QImage(path)
        dpi = dpis[k] if k < len(dpis) else 300
        if PAPERS.get(paper, PAPERS["a4"])[1] is not None:
            size = QPageSize(PAPERS[paper][1])
            if img.width() > img.height():
                layout = QPageLayout(size, QPageLayout.Orientation.Landscape, QMarginsF(0, 0, 0, 0))
            else:
                layout = QPageLayout(size, QPageLayout.Orientation.Portrait, QMarginsF(0, 0, 0, 0))
        else:
            inches = QSizeF(img.width() / dpi, img.height() / dpi)
            layout = QPageLayout(QPageSize(inches, QPageSize.Unit.Inch, "Scan"), QPageLayout.Orientation.Portrait, QMarginsF(0, 0, 0, 0))
        writer.setPageLayout(layout)
        if painter is None:
            painter = QPainter(writer)
        else:
            writer.newPage()
        area = QRectF(painter.viewport())
        s = min(area.width() / img.width(), area.height() / img.height())
        w, h = img.width() * s, img.height() * s
        painter.drawImage(QRectF(area.x() + (area.width() - w) / 2, area.y() + (area.height() - h) / 2, w, h), img)
    if painter is not None:
        painter.end()


def free_name(folder: Path, base: str, ext: str) -> Path:
    base = re.sub(r"[\\/:*?\"<>|]+", " ", base).strip() or "Scan"
    out, n = folder / f"{base}{ext}", 2
    while out.exists():
        out, n = folder / f"{base} {n}{ext}", n + 1
    return out


# ------------------------------------------------------------------------------------------- the app's backend
class Scan(QObject):
    changed = Signal()
    pageChanged = Signal()                                    # pictures of pages changed (the strip and the big page)
    said = Signal(str, bool)
    _back = Signal(object)

    def __init__(self, demo: bool = False):
        super().__init__()
        self._back.connect(lambda fn: fn())
        self._demo = demo
        self._doc = {"name": time.strftime("Scan %-d %b %Y"), "pages": []}
        self._folder = DATA / "current"
        self._at = -1
        self._scanners, self._scanner, self._opts = [], "", {"modes": [], "resolutions": [], "sources": []}
        self._choice = {"mode": "Color", "dpi": 300, "source": "", "clean": "document", "paper": "a4", "lang": "eng", "searchable": True}
        self._busy, self._share, self._proc = "", 0.0, None
        self._version = 0
        self._cache = {}
        self._langs = []
        self._recent = []
        if demo:
            self._demo_fill()
        else:
            self._load()
            QTimer.singleShot(0, self.refresh)
            threading.Thread(target=lambda: self._back.emit(lambda: self._set_langs(ocr_languages())), daemon=True).start()
        self._find_recent()

    # ---- keeping the document between runs
    def _load(self) -> None:
        try:
            self._doc = json.loads((self._folder / "document.json").read_text(encoding="utf-8"))
            self._doc["pages"] = [p for p in self._doc.get("pages", []) if (self._folder / p["file"]).is_file()]
            self._at = 0 if self._doc["pages"] else -1
        except (OSError, ValueError, KeyError):
            pass

    def _keep(self) -> None:
        self._version += 1
        self._cache.clear()
        if not self._demo:
            try:
                self._folder.mkdir(parents=True, exist_ok=True)
                (self._folder / "document.json").write_text(json.dumps(self._doc), encoding="utf-8")
            except OSError:
                pass
        self.changed.emit()
        self.pageChanged.emit()

    def _set_langs(self, langs: list) -> None:
        self._langs = langs
        if langs and self._choice["lang"] not in langs:
            self._choice["lang"] = "eng" if "eng" in langs else langs[0]
        self.changed.emit()

    def _demo_fill(self) -> None:
        DATA.mkdir(parents=True, exist_ok=True)
        self._folder = Path(os.environ.get("XDG_RUNTIME_DIR") or "/tmp") / f"huginn-scan-demo-{os.getpid()}"
        self._folder.mkdir(parents=True, exist_ok=True)
        self._doc = {"name": "Lease agreement", "pages": []}
        for k, (title, tilt) in enumerate((("Tenancy Agreement", 0.06), ("Schedule of Rent", -0.04), ("Signatures", 0.02))):
            img = demo_photo(title, k, tilt)
            name = f"p{k}.png"
            img.save(str(self._folder / name))
            self._doc["pages"].append({"id": f"d{k}", "file": name, "corners": find_page(to_array(img)), "turn": 0, "mode": "document", "dpi": 300, "text": ""})
        self._at = 0
        self._scanners = [{"id": "escl:https://192.168.1.40:443", "name": "Brother MFC-L2750DW", "kind": "flatbed scanner"},
                          {"id": "test:0", "name": "Office copier (feeder)", "kind": "virtual device"}]
        self._scanner = self._scanners[0]["id"]
        self._opts = {"modes": ["Color", "Gray", "Lineart"], "resolutions": [150, 300, 600], "sources": ["Flatbed", "ADF", "ADF Duplex"]}
        self._choice["source"] = "Flatbed"
        self._langs = ["eng", "deu", "fra", "spa", "nor"]

    def _find_recent(self) -> None:
        folder = self._scans_folder()
        try:
            files = sorted(folder.glob("*.pdf"), key=lambda q: -q.stat().st_mtime)[:12]
        except OSError:
            files = []
        self._recent = [{"path": str(q), "name": q.stem, "when": time.strftime("%-d %b, %H:%M", time.localtime(q.stat().st_mtime)),
                         "size": f"{max(1, q.stat().st_size // 1024)} KB"} for q in files]
        if self._demo:
            self._recent = [{"path": "/demo/Insurance.pdf", "name": "Car insurance", "when": "12 Nov, 09:14", "size": "412 KB"},
                            {"path": "/demo/Receipt.pdf", "name": "Receipt, bike repair", "when": "8 Nov, 17:02", "size": "96 KB"},
                            {"path": "/demo/School.pdf", "name": "School form", "when": "3 Nov, 08:30", "size": "230 KB"}]

    def _scans_folder(self) -> Path:
        return Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation) or Path.home() / "Documents") / "Scans"

    # ---- what QML sees
    def _page_views(self) -> list:
        return [{"id": p["id"], "index": i, "mode": p.get("mode", "document"), "turn": p.get("turn", 0), "corners": p.get("corners"),
                 "hasText": bool(p.get("text")), "src": f"image://scan/{p['id']}/{self._version}"} for i, p in enumerate(self._doc["pages"])]

    pages = Property("QVariantList", _page_views, notify=changed)
    current = Property(int, lambda self: self._at, notify=changed)
    name = Property(str, lambda self: self._doc.get("name", ""), notify=changed)
    scanners = Property("QVariantList", lambda self: self._scanners, notify=changed)
    scanner = Property(str, lambda self: self._scanner, notify=changed)
    options = Property("QVariantMap", lambda self: self._opts, notify=changed)
    choice = Property("QVariantMap", lambda self: dict(self._choice), notify=changed)
    busy = Property(str, lambda self: self._busy, notify=changed)
    share = Property(float, lambda self: self._share, notify=changed)
    languages = Property("QVariantList", lambda self: self._langs, notify=changed)
    canRead = Property(bool, lambda self: bool(self._langs), notify=changed)
    recent = Property("QVariantList", lambda self: self._recent, notify=changed)
    modes = Property("QVariantList", lambda self: [{"id": i, "name": n} for i, n in MODES], constant=True)
    papers = Property("QVariantList", lambda self: [{"id": k, "name": v[0]} for k, v in PAPERS.items()], constant=True)

    @Property("QVariantMap", notify=changed)
    def page(self):
        if not 0 <= self._at < len(self._doc["pages"]):
            return {}
        p = self._doc["pages"][self._at]
        img = self.original(self._at)
        return {"id": p["id"], "corners": p.get("corners"), "mode": p.get("mode", "document"), "turn": p.get("turn", 0), "text": p.get("text", ""),
                "width": img.width(), "height": img.height(), "original": f"image://scan/{p['id']}/{self._version}/original"}

    def original(self, i: int) -> QImage:
        p = self._doc["pages"][i]
        key = ("orig", p["id"])
        if key not in self._cache:
            self._cache[key] = QImage(str(self._folder / p["file"]))
        return self._cache[key]

    def finished(self, i: int, limit: int = 0) -> QImage:
        p = self._doc["pages"][i]
        key = ("done", p["id"], limit)
        if key not in self._cache:
            self._cache[key] = process(self.original(i), p, limit)
        return self._cache[key]

    def _index_of(self, pid: str) -> int:
        return next((i for i, p in enumerate(self._doc["pages"]) if p["id"] == pid), -1)

    # ---- scanners
    @Slot()
    def refresh(self) -> None:
        if self._demo:
            return
        self._busy = "Looking for scanners…"
        self.changed.emit()

        def found(devs):
            self._scanners = devs
            if devs and self._scanner not in [d["id"] for d in devs]:
                self.chooseScanner(devs[0]["id"])
            self._busy = ""
            self.changed.emit()
        threading.Thread(target=lambda: (lambda d: self._back.emit(lambda: found(d)))(list_scanners()), daemon=True).start()

    @Slot(str)
    def chooseScanner(self, device: str) -> None:
        self._scanner = device
        self.changed.emit()
        if self._demo:
            return

        def got(opts):
            self._opts = opts
            if opts["modes"]:
                self._choice["mode"] = next((m for m in ("Color", "Colour", "color") if m in opts["modes"]), opts["modes"][0])
            if opts["resolutions"]:
                self._choice["dpi"] = min(opts["resolutions"], key=lambda r: abs(r - 300))
            self._choice["source"] = opts["sources"][0] if opts["sources"] else ""
            self.changed.emit()
        threading.Thread(target=lambda: (lambda o: self._back.emit(lambda: got(o)))(scanner_options(device)), daemon=True).start()

    @Slot(str, "QVariant")
    def setChoice(self, key: str, value) -> None:
        value = value.toVariant() if hasattr(value, "toVariant") else value
        if key in self._choice:
            self._choice[key] = int(value) if key == "dpi" else value
            self.changed.emit()

    @Slot()
    def scan(self) -> None:
        """Scan with the chosen scanner: one page from the glass, or every page in the feeder."""
        if self._busy:
            return
        if self._demo:
            self._add_image(demo_photo("Page " + str(len(self._doc["pages"]) + 1), len(self._doc["pages"]), 0.0, flat=True), from_scanner=True)
            return
        if not self._scanner:
            self.said.emit("No scanner was found. Is it on, and connected?", True)
            return
        work = self._folder / "incoming"
        shutil.rmtree(work, ignore_errors=True)
        work.mkdir(parents=True, exist_ok=True)
        batch = "adf" in self._choice["source"].lower() or "feeder" in self._choice["source"].lower()
        target = str(work / ("page%03d.png" if batch else "page001.png"))
        args = scan_command(self._scanner, self._choice["mode"], self._choice["dpi"], self._choice["source"], target, batch)
        proc = QProcess(self)
        proc.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self._proc, self._busy, self._share = proc, "Scanning…", 0.0
        log = []

        def read():
            text = bytes(proc.readAll()).decode(errors="replace")
            log.append(text)
            got = re.findall(r"Progress:\s*([\d.]+)%", text)
            if got:
                self._share = min(0.99, float(got[-1]) / 100)
                self.changed.emit()

        def done(code, _status):
            self._proc, self._busy = None, ""
            files = sorted(work.glob("page*.png"))
            for f in files:
                img = QImage(str(f))
                if not img.isNull():
                    self._add_image(img, from_scanner=True, quiet=True)
            if files:
                self.said.emit(f"{len(files)} page{'s' if len(files) != 1 else ''} scanned", False)
            elif code != 0:
                last = [l for l in "".join(log).splitlines() if l.strip() and "Progress" not in l][-1:] or ["the scanner stopped"]
                self.said.emit("Couldn't scan: " + last[0].replace("scanimage: ", "")[:160], True)
            self.changed.emit()
        proc.readyRead.connect(read)
        proc.finished.connect(done)
        proc.start(args[0], args[1:])
        self.changed.emit()

    @Slot()
    def stop(self) -> None:
        if self._proc is not None:
            self._proc.kill()

    # ---- pages from photos and files
    def _add_image(self, img: QImage, from_scanner: bool = False, quiet: bool = False) -> None:
        self._folder.mkdir(parents=True, exist_ok=True)
        pid = uuid.uuid4().hex[:10]
        name = f"{pid}.png"
        img.save(str(self._folder / name))
        corners = [[0, 0], [1, 0], [1, 1], [0, 1]] if from_scanner else find_page(to_array(img))
        dpi = int(self._choice["dpi"]) if from_scanner else max(150, int(max(img.width(), img.height()) / 11.69))
        mode = {"Gray": "grey", "Grey": "grey", "Lineart": "document"}.get(self._choice["mode"], self._choice["clean"]) if from_scanner else self._choice["clean"]
        self._doc["pages"].append({"id": pid, "file": name, "corners": corners, "turn": 0, "mode": mode, "dpi": dpi, "text": ""})
        self._at = len(self._doc["pages"]) - 1
        self._keep()
        if not quiet and not from_scanner:
            self.said.emit("Found the page's edges and straightened it. Drag the corners if they're off.", False)

    @Slot("QVariantList")
    def addFiles(self, urls: list) -> None:
        n = 0
        for u in urls:
            path = QUrl(str(u)).toLocalFile() if str(u).startswith("file:") else str(u)
            if Path(path).is_dir():
                files = sorted(q for q in Path(path).iterdir() if q.suffix.lower() in IMAGES)
            else:
                files = [Path(path)]
            for f in files:
                img = QImage(str(f))
                if img.isNull():
                    continue
                if max(img.width(), img.height()) > 5000:
                    img = img.scaled(5000, 5000, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                self._add_image(img, quiet=True)
                n += 1
        if n:
            self.said.emit(f"{n} page{'s' if n != 1 else ''} added. The edges were found and straightened; drag the corners if they're off.", False)
        else:
            self.said.emit("Those aren't pictures Scan can read.", True)

    @Slot(result="QVariantList")
    def photoChoices(self) -> list:
        found = []
        for base in (Path.home() / "Pictures", Path.home() / "Downloads", Path.home() / "Pictures" / "Camera", Path.home() / "Desktop"):
            if base.is_dir():
                found += [q for q in base.iterdir() if q.suffix.lower() in IMAGES]
        found.sort(key=lambda q: -q.stat().st_mtime)
        return [{"path": str(q), "name": q.name, "url": QUrl.fromLocalFile(str(q)).toString()} for q in found[:24]]

    # ---- editing pages
    @Slot(int)
    def select(self, i: int) -> None:
        if 0 <= i < len(self._doc["pages"]):
            self._at = i
            self.changed.emit()

    @Slot(int, int)
    def move(self, i: int, to: int) -> None:
        pages = self._doc["pages"]
        if 0 <= i < len(pages) and 0 <= to < len(pages) and i != to:
            pages.insert(to, pages.pop(i))
            self._at = to
            self._keep()

    @Slot(int)
    def remove(self, i: int) -> None:
        if 0 <= i < len(self._doc["pages"]):
            p = self._doc["pages"].pop(i)
            if not self._demo:
                (self._folder / p["file"]).unlink(missing_ok=True)
            self._at = min(self._at, len(self._doc["pages"]) - 1)
            self._keep()

    @Slot(int, int)
    def turn(self, i: int, degrees: int) -> None:
        if 0 <= i < len(self._doc["pages"]):
            p = self._doc["pages"][i]
            p["turn"] = (int(p.get("turn", 0)) + degrees) % 360
            self._keep()

    @Slot(int, str)
    def setMode(self, i: int, mode: str) -> None:
        if mode in dict(MODES):
            targets = range(len(self._doc["pages"])) if i < 0 else [i]
            for k in targets:
                self._doc["pages"][k]["mode"] = mode
            self._choice["clean"] = mode
            self._keep()

    @Slot(int, "QVariantList")
    def setCorners(self, i: int, corners: list) -> None:
        if 0 <= i < len(self._doc["pages"]):
            c = [[round(max(0.0, min(1.0, float(x))), 4), round(max(0.0, min(1.0, float(y))), 4)] for x, y in (corners.toVariant() if hasattr(corners, "toVariant") else corners)]
            if len(c) == 4:
                self._doc["pages"][i]["corners"] = order_corners(c)
                self._keep()

    @Slot(int)
    def findEdges(self, i: int) -> None:
        if 0 <= i < len(self._doc["pages"]):
            self._doc["pages"][i]["corners"] = find_page(to_array(self.original(i)))
            self._keep()

    @Slot(int)
    def wholePicture(self, i: int) -> None:
        if 0 <= i < len(self._doc["pages"]):
            self._doc["pages"][i]["corners"] = [[0, 0], [1, 0], [1, 1], [0, 1]]
            self._keep()

    @Slot(str)
    def rename(self, name: str) -> None:
        self._doc["name"] = name.strip() or self._doc["name"]
        self._keep()

    @Slot()
    def startOver(self) -> None:
        if not self._demo:
            for p in self._doc["pages"]:
                (self._folder / p["file"]).unlink(missing_ok=True)
        self._doc = {"name": time.strftime("Scan %-d %b %Y"), "pages": []}
        self._at = -1
        self._keep()

    # ---- reading the text
    @Slot(int)
    def readPage(self, i: int) -> None:
        """Read the words on one page (or all, with -1) and keep them with the page."""
        if not self._langs:
            self.said.emit("Reading text needs Tesseract.", True)
            return
        if self._busy:
            return
        todo = list(range(len(self._doc["pages"]))) if i < 0 else [i]
        if self._demo:
            for k in todo:
                self._doc["pages"][k]["text"] = DEMO_TEXT[k % len(DEMO_TEXT)]
            self._keep()
            return
        work = self._folder / "read"
        work.mkdir(parents=True, exist_ok=True)
        jobs = []
        for k in todo:
            f = work / f"{self._doc['pages'][k]['id']}.png"
            self.finished(k).save(str(f))
            jobs.append((self._doc["pages"][k]["id"], str(f)))
        self._busy, self._share = "Reading the text…", 0.0
        self.changed.emit()
        lang = self._choice["lang"]

        def work_fn():
            out = {}
            for n, (pid, f) in enumerate(jobs):
                out[pid] = read_text(f, lang)
                share = (n + 1) / len(jobs)
                self._back.emit(lambda s=share: (setattr(self, "_share", s), self.changed.emit()))
            self._back.emit(lambda: self._took_text(out))
        threading.Thread(target=work_fn, daemon=True).start()

    def _took_text(self, out: dict) -> None:
        self._busy = ""
        for p in self._doc["pages"]:
            if p["id"] in out:
                p["text"] = out[p["id"]]
        words = sum(len(t.split()) for t in out.values())
        self.said.emit(f"Read {words} word{'s' if words != 1 else ''}." if words else "No words were found on that page.", not words)
        self._keep()

    # ---- saving
    @Slot(result=str)
    def savePdf(self) -> str:
        """The document as a PDF in Documents/Scans: searchable when Tesseract is there and that's chosen. Gives the path."""
        if not self._doc["pages"] or self._busy:
            return ""
        folder = self._scans_folder()
        folder.mkdir(parents=True, exist_ok=True)
        target = free_name(folder, self._doc["name"], ".pdf")
        if self._demo:
            self.said.emit(f"Saved {target.name} in Documents/Scans", False)
            return str(target)
        work = self._folder / "out"
        shutil.rmtree(work, ignore_errors=True)
        work.mkdir(parents=True, exist_ok=True)
        files, dpis = [], []
        for k, p in enumerate(self._doc["pages"]):
            f = work / f"{k:03d}.png"
            img = self.finished(k)
            img.setDotsPerMeterX(int(p.get("dpi", 300) / 0.0254))
            img.setDotsPerMeterY(int(p.get("dpi", 300) / 0.0254))
            img.save(str(f))
            files.append(str(f))
            dpis.append(int(p.get("dpi", 300)))
        searchable = self._choice["searchable"] and bool(self._langs)
        self._busy, self._share = "Making the PDF…", 0.0
        self.changed.emit()
        lang, paper = self._choice["lang"], self._choice["paper"]

        def work_fn():
            ok = False
            if searchable:
                ok = searchable_pdf(files, str(target), lang)
            self._back.emit(lambda: self._saved(target, files, dpis, paper, ok, searchable))
        threading.Thread(target=work_fn, daemon=True).start()
        return str(target)

    def _saved(self, target: Path, files: list, dpis: list, paper: str, ok: bool, searchable: bool) -> None:
        if not ok:
            plain_pdf(files, str(target), paper, dpis)        # on the GUI thread: QPdfWriter draws with fonts
        self._busy = ""
        self._find_recent()
        if target.is_file():
            self.said.emit(f"Saved {target.name} in Documents/Scans" + (", with its text to search" if ok else ""), False)
        else:
            self.said.emit("Couldn't make the PDF.", True)
        self.changed.emit()

    @Slot(result=str)
    def saveImages(self) -> str:
        folder = free_name(self._scans_folder(), self._doc["name"], "")
        if self._demo:
            return str(folder)
        folder.mkdir(parents=True, exist_ok=True)
        for k in range(len(self._doc["pages"])):
            self.finished(k).save(str(folder / f"Page {k + 1}.jpg"), "JPG", 90)
        self.said.emit(f"Saved {len(self._doc['pages'])} pictures in Documents/Scans/{folder.name}", False)
        return str(folder)

    @Slot(result=str)
    def allText(self) -> str:
        return "\n\n".join(p.get("text", "") for p in self._doc["pages"] if p.get("text"))

    @Slot(str)
    def open(self, path: str) -> None:
        if not self._demo and Path(path).exists():
            QProcess.startDetached("xdg-open", [path])

    @Slot()
    def showFolder(self) -> None:
        if not self._demo:
            QProcess.startDetached("xdg-open", [str(self._scans_folder())])


class ScanImages(QQuickImageProvider):
    """image://scan/<page>/<version>[/original]: a page as it'll be saved (or as it came), sized for the screen."""

    def __init__(self, scan: Scan):
        super().__init__(QQuickImageProvider.ImageType.Image)
        self.scan = scan

    def requestImage(self, ident, size, requested):
        parts = ident.split("/")
        i = self.scan._index_of(parts[0])
        if i < 0:
            img = QImage(4, 4, FMT)
            img.fill(Qt.GlobalColor.white)
        elif len(parts) > 2 and parts[2] == "original":
            img = self.scan.original(i)
            if max(img.width(), img.height()) > 1600:
                img = img.scaled(1600, 1600, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        else:
            big = requested.isValid() and max(requested.width(), requested.height()) > 400
            img = self.scan.finished(i, 1800 if big else 600)
        if size is not None:
            size.setWidth(img.width())
            size.setHeight(img.height())
        return img


# ------------------------------------------------------------------------------------------- the demo's photos
DEMO_TEXT = ["TENANCY AGREEMENT\nThis agreement is made on 1 November 2026 between the landlord and the tenant for the flat at Storgata 12, Tromsø.",
             "SCHEDULE OF RENT\nMonthly rent: 11 400 kr, due on the first day of each month.\nDeposit: 34 200 kr.",
             "SIGNATURES\nLandlord ______________   Tenant ______________"]


def demo_photo(title: str, k: int, tilt: float, flat: bool = False) -> QImage:
    """A photo of a page lying on a wooden table, slightly turned: for the demo and for tests."""
    from PySide6.QtGui import QColor, QFont, QLinearGradient, QPen
    W, H = (1240, 1754) if flat else (1500, 2000)
    img = QImage(W, H, FMT)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    if flat:
        img.fill(QColor("#FDFDFB"))
        page = QPolygonF([QPointF(0, 0), QPointF(W, 0), QPointF(W, H), QPointF(0, H)])
    else:
        g = QLinearGradient(0, 0, W, H)
        g.setColorAt(0, QColor("#6B4A32"))
        g.setColorAt(1, QColor("#3E2A1C"))
        p.fillRect(0, 0, W, H, g)
        cx, cy = W / 2, H / 2
        pw, ph = 1050, 1480
        pts = [(-pw / 2, -ph / 2), (pw / 2, -ph / 2), (pw / 2 + 40, ph / 2), (-pw / 2 - 30, ph / 2)]
        import math
        c, s = math.cos(tilt), math.sin(tilt)
        page = QPolygonF([QPointF(cx + x * c - y * s, cy + x * s + y * c) for x, y in pts])
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 90))
        p.drawPolygon(page.translated(14, 18))
    shade = QLinearGradient(0, 0, W, 0)
    shade.setColorAt(0, QColor("#F4F1EA"))
    shade.setColorAt(1, QColor("#D9D4C8") if not flat else QColor("#F4F1EA"))
    p.setBrush(shade)
    p.setPen(Qt.PenStyle.NoPen)
    p.drawPolygon(page)
    # words on the page, in its own frame
    tr = QTransform()
    QTransform.quadToQuad(QPolygonF([QPointF(0, 0), QPointF(1050, 0), QPointF(1050, 1480), QPointF(0, 1480)]), page, tr)
    p.setTransform(tr)
    p.setPen(QPen(QColor("#1B1B1F")))
    f = QFont("Inter")
    f.setPixelSize(54)
    f.setBold(True)
    p.setFont(f)
    p.drawText(QRectF(90, 90, 870, 90), title)
    f.setPixelSize(28)
    f.setBold(False)
    p.setFont(f)
    words = ("This agreement sets out the rent, the deposit and the rules for the flat. The tenant keeps it clean and tidy and "
             "tells the landlord about repairs. Either side can end it with three months' notice in writing. ") * 3
    p.drawText(QRectF(90, 220, 870, 900), Qt.TextFlag.TextWordWrap, words)
    p.setPen(QPen(QColor("#3A3A40"), 2))
    for r in range(4):
        p.drawLine(QPointF(90, 1180 + r * 60), QPointF(960, 1180 + r * 60))
    p.end()
    return img
