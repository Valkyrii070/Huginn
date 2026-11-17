"""Huginn Easel's tools, its history, and the canvas you draw on (see huginn_easel for the document itself).

Every tool works in the document's own pixels: the canvas turns your pointer into those and hands it to Easel, which
keeps all the drawing logic here, in one place, where it can be tested without a screen.
"""
import json
import math
import os
import random
import threading
from pathlib import Path

import numpy as np
from PySide6.QtCore import Property, QEvent, QMimeData, QObject, QPointF, QRect, QRectF, Qt, QTimer, Signal, Slot
from PySide6.QtGui import (QBrush, QColor, QCursor, QFontDatabase, QGuiApplication, QImage, QPainter, QPainterPath, QPen, QPixmap,
                           QPolygonF, QLinearGradient, QRadialGradient, QTransform)
from PySide6.QtQuick import QQuickImageProvider, QQuickPaintedItem

import huginn_easel as ez
import huginn_easel_more as more

DATA_HOME = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share") / "huginn"
PREFS = DATA_HOME / "easel.json"
OPENABLE = (".easel", ".ora", ".psd", ".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff", ".gif", ".svg")
PRESETS = [("Screen", 1920, 1080), ("4K screen", 3840, 2160), ("Square post", 1080, 1080), ("Story", 1080, 1920), ("A4 at 300 dpi", 2480, 3508),
           ("Letter at 300 dpi", 2550, 3300), ("App icon", 1024, 1024), ("Banner", 1500, 500), ("Phone wallpaper", 1290, 2796)]
PIXEL_TOOLS = ["move", "transform", "select", "ellipsesel", "lasso", "wand", "brush", "eraser", "clone", "heal", "dodge", "smudge", "liquify", "fill", "gradient",
               "picker", "text", "crop", "hand", "zoom"]
VECTOR_TOOLS = ["pointer", "nodes", "pen", "rect", "ellipse", "line", "star", "text", "fill", "picker", "hand", "zoom"]
TOOL_NAMES = {"move": "Move", "select": "Rectangle selection", "ellipsesel": "Ellipse selection", "lasso": "Lasso", "wand": "Magic wand",
              "brush": "Brush", "eraser": "Eraser", "fill": "Fill", "gradient": "Gradient", "picker": "Colour picker", "text": "Text", "crop": "Crop",
              "hand": "Hand", "zoom": "Zoom", "pointer": "Select", "pen": "Pen", "rect": "Rectangle", "ellipse": "Ellipse", "line": "Line", "star": "Star",
              "transform": "Free transform", "clone": "Clone", "heal": "Heal", "nodes": "Edit points", "dodge": "Dodge and burn", "smudge": "Smudge",
              "liquify": "Liquify"}
SHIFT, ALT, CTRL = 1, 2, 4
HANDLES = ["tl", "t", "tr", "r", "br", "b", "bl", "l"]


def _hex(c: QColor) -> str:
    return c.name(QColor.NameFormat.HexArgb) if c.alpha() < 255 else c.name()


class Easel(QObject):
    changed = Signal()                      # layers, tools, settings: what the panels show
    painted = Signal()                      # the canvas needs drawing again
    said = Signal(str, bool)
    editText = Signal(str, float, float)    # the text shape to edit, and where (document pixels)
    _call = Signal(object)

    def __init__(self, demo: bool = False, target: str = ""):
        super().__init__()
        self._demo = demo
        self.doc = None
        self.tool, self.persona = "brush", "pixel"
        self.fg, self.bg = "#2B6CF0", "#FFFFFF"
        self.brush_key = "round"
        self.brush = dict(ez.BRUSHES["round"])
        self.pressure_mode = "size"                    # what a pen's pressure changes: size, opacity, both or off
        self._pressure = 1.0                           # the pen's pressure now (a mouse is always 1)
        self._stylus = False                           # a drawing tablet's pen has been seen
        self.busy = ""
        self._filled.connect(self._took_fill)
        self.opacity = 1.0                                       # the stroke's own opacity
        self.style = {"fill": "#5B8CFF", "stroke": "#14171C", "width": 0.0, "radius": 0.0, "points": 5, "inner": 0.5, "opacity": 1.0}
        self.text = {"font": "Inter", "size": 72, "weight": 700, "italic": False, "align": "left"}
        self.tolerance, self.contiguous, self.gradient_kind, self.gradient_clear = 0.12, True, "linear", False
        self.zoom = 1.0                                          # the view tells Easel, so handles and slack match the screen
        self._undo, self._redo = [], []
        self._drag = None
        self._live = None
        self._picked = []
        self._mask_edit = ""
        self._crop = None
        self._pen = None
        self._hover = None
        self._sel_path = QPainterPath()
        self._xform = None                                       # a free transform in progress
        self._clone_src, self._clone_off, self.heal_spot = None, None, True
        self._node_sel = None                                    # (shape id, subpath, node) being edited
        self.retouch, self.retouch_range, self.retouch_strength = "dodge", "mid", 0.35   # round four's brushes
        self.liquify_mode, self.liquify_strength, self.smudge_strength = "push", 0.7, 0.6
        self.snap, self.rulers, self._guide_live = True, False, None
        self._dabs = {}
        self._cursor = ""
        self._call.connect(lambda fn: fn())
        try:
            prefs = json.loads(PREFS.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            prefs = {}
        self._recent = [r for r in prefs.get("recent", []) if isinstance(r, str)][:12]
        self.fg, self.bg = prefs.get("fg", self.fg), prefs.get("bg", self.bg)
        self.snap, self.rulers = bool(prefs.get("snap", True)), bool(prefs.get("rulers", False))
        self._swatches = prefs.get("swatches") or ["#14171C", "#FFFFFF", "#E5484D", "#F76B15", "#FFC53D", "#30A46C", "#12A594", "#0090FF", "#3E63DD", "#8E4EC6", "#D6409F", "#8D8D8D"]
        if demo:
            self._demo_doc()
        elif target and Path(target).is_file():
            self.open(target)

    # ------------------------------------------------------------------ what the panels read
    hasDoc = Property(bool, lambda self: self.doc is not None, notify=changed)
    docName = Property(str, lambda self: (Path(self.doc.path).name if self.doc and self.doc.path else "Untitled") if self.doc else "", notify=changed)
    docW = Property(int, lambda self: self.doc.w if self.doc else 0, notify=changed)
    docH = Property(int, lambda self: self.doc.h if self.doc else 0, notify=changed)
    dirty = Property(bool, lambda self: bool(self._undo) and getattr(self, "_saved_at", None) is not self._undo[-1], notify=changed)
    toolName = Property(str, lambda self: self.tool, notify=changed)
    personaName = Property(str, lambda self: self.persona, notify=changed)
    tools = Property("QVariantList", lambda self: [{"id": t, "name": TOOL_NAMES[t]} for t in (PIXEL_TOOLS if self.persona == "pixel" else VECTOR_TOOLS)], notify=changed)
    fgColour = Property(str, lambda self: self.fg, notify=changed)
    bgColour = Property(str, lambda self: self.bg, notify=changed)
    swatches = Property("QVariantList", lambda self: self._swatches, notify=changed)
    brushes = Property("QVariantList", lambda self: [{"id": k, "name": v["name"]} for k, v in ez.BRUSHES.items()], constant=True)
    brushKey = Property(str, lambda self: self.brush_key, notify=changed)
    brushSize = Property(float, lambda self: self.brush["size"], notify=changed)
    brushHardness = Property(float, lambda self: self.brush["hardness"], notify=changed)
    brushFlow = Property(float, lambda self: self.brush["flow"], notify=changed)
    strokeOpacity = Property(float, lambda self: self.opacity, notify=changed)
    wandTolerance = Property(float, lambda self: self.tolerance, notify=changed)
    contiguousOn = Property(bool, lambda self: self.contiguous, notify=changed)
    gradientKind = Property(str, lambda self: self.gradient_kind, notify=changed)
    gradientClear = Property(bool, lambda self: self.gradient_clear, notify=changed)
    blends = Property("QVariantList", lambda self: [{"id": k, "name": n} for k, n in ez.BLEND_NAMES], constant=True)
    filters = Property("QVariantList", lambda self: [{"id": k, "name": n} for k, n in ez.FILTERS.items()], constant=True)
    adjustments = Property("QVariantList", lambda self: [{"id": k, "name": n} for k, n in ez.ADJUSTMENTS.items()], constant=True)
    presets = Property("QVariantList", lambda self: [{"name": n, "w": w, "h": h} for n, w, h in PRESETS], constant=True)
    recent = Property("QVariantList", lambda self: [{"path": r, "name": Path(r).name, "folder": str(Path(r).parent).replace(str(Path.home()), "~")} for r in self._recent if Path(r).exists()], notify=changed)
    canUndo = Property(bool, lambda self: bool(self._undo), notify=changed)
    canRedo = Property(bool, lambda self: bool(self._redo), notify=changed)
    steps = Property("QVariantList", lambda self: [name for name, _ in self._undo[-14:]], notify=changed)
    hasSelection = Property(bool, lambda self: bool(self.doc and self.doc.selection is not None), notify=changed)
    cropping = Property(bool, lambda self: self._crop is not None, notify=changed)
    penActive = Property(bool, lambda self: self._pen is not None, notify=changed)
    maskEditing = Property(bool, lambda self: bool(self._mask_edit), notify=changed)
    cursorText = Property(str, lambda self: self._cursor, notify=changed)
    shapeStyle = Property("QVariantMap", lambda self: dict(self.style), notify=changed)
    transforming = Property(bool, lambda self: self._xform is not None, notify=changed)
    healSpot = Property(bool, lambda self: self.heal_spot, notify=changed)
    cloneReady = Property(bool, lambda self: self._clone_src is not None, notify=changed)
    nodePicked = Property(bool, lambda self: self._node_sel is not None, notify=changed)

    @Property("QVariantMap", notify=changed)
    def transformInfo(self):
        x = self._xform
        if not x:
            return {}
        return {"w": round(abs(x["sx"]) * 100), "h": round(abs(x["sy"]) * 100), "angle": round(x["rot"] % 360, 1)}
    textStyle = Property("QVariantMap", lambda self: dict(self.text), notify=changed)

    @Property("QVariantList", constant=True)
    def fonts(self):
        fams = QFontDatabase.families()
        first = [f for f in ("Inter", "Noto Serif", "Noto Sans", "JetBrains Mono", "Noto Sans Mono") if f in fams]
        return first + [f for f in fams if f not in first and not f.startswith(".")][:300]

    @Property("QVariantList", notify=changed)
    def layers(self):
        if not self.doc:
            return []
        out = []
        layers = self.doc.layers
        for l in reversed(layers):                                # the panel lists the top layer first
            anc = more.ancestors(layers, l)
            if any(not self.doc.layer(g).get("open", True) for g in anc):
                continue                                          # inside a folded group
            out.append({"id": l["id"], "name": l["name"], "kind": l["kind"], "visible": l["visible"], "locked": l["locked"], "opacity": l["opacity"],
                        "blend": l["blend"], "hasMask": l.get("mask") is not None, "maskOn": l.get("maskOn", True), "active": l["id"] == self.doc.active,
                        "adjust": l.get("adjust", ""), "v": l.get("v", 0) + (sum(x.get("v", 0) for x in self._subtree(l)) if l["kind"] == "group" else 0),
                        "shapes": len(l.get("shapes", [])), "depth": len(anc), "open": l.get("open", True), "fx": more.has_fx(l),
                        "count": len(self._subtree(l)) - 1 if l["kind"] == "group" else 0, "filters": len(l.get("sfilters") or [])})
        return out

    @Property("QVariantMap", notify=changed)
    def activeLayer(self):
        if not self.doc:
            return {}
        l = self.doc.layer()
        params = dict(ez.ADJUST_DEFAULTS.get(l.get("adjust", ""), {}))
        params.update(l.get("params") or {})
        if l.get("adjust") == "curves":
            params["curves"] = dict(ez.ADJUST_DEFAULTS["curves"]["curves"], **((l.get("params") or {}).get("curves") or {}))
        return {"id": l["id"], "name": l["name"], "kind": l["kind"], "opacity": l["opacity"], "blend": l["blend"], "locked": l["locked"],
                "hasMask": l.get("mask") is not None, "adjust": l.get("adjust", ""), "params": params,
                "paramList": [{"id": k, "name": n} for k, n in ez.ADJUST_PARAMS.get(l.get("adjust", ""), [])],
                "fx": more.has_fx(l), "inGroup": bool(l.get("group")),
                "sfilters": [{"name": ez.FILTERS.get(f["name"], f["name"]), "on": f.get("on", True), "amount": f.get("amount", 0.4)} for f in l.get("sfilters") or []]}

    @Property("QVariantMap", notify=changed)
    def picked(self):
        """The shape (or shapes) picked with the Select tool: what the style bar shows and changes."""
        shapes = self._picked_shapes()
        if not shapes:
            return {"count": 0}
        s = shapes[-1]
        return {"count": len(shapes), "type": s["type"], "fill": s.get("fill", ""), "stroke": s.get("stroke", ""), "width": float(s.get("width", 0)),
                "opacity": float(s.get("opacity", 1)), "radius": float(s.get("radius", 0)), "points": int(s.get("points", 5)), "inner": float(s.get("inner", 0.5)),
                "text": s.get("text", ""), "font": s.get("font", ""), "size": float(s.get("size", 0)), "weight": int(s.get("weight", 400)), "rot": float(s.get("rot", 0)),
                "fill2": s.get("fill2", ""), "gangle": float(s.get("gangle", 90)), "gkind": s.get("gkind", "linear"),
                "along": bool(s.get("along")), "pathOffset": float(s.get("pathOffset", 0)),
                "canPath": len(shapes) == 2 and sorted(x["type"] == "text" for x in shapes) == [False, True]}

    def _picked_shapes(self) -> list:
        if not self.doc:
            return []
        out = []
        for l in self.doc.layers:
            for s in l.get("shapes", []):
                if s.get("id") in self._picked:
                    out.append(s)
        return out

    # ------------------------------------------------------------------ documents
    def _demo_doc(self) -> None:
        doc = ez.Document(1600, 1000, "#F4EFE6")
        bg = doc.layers[0]
        p = QPainter(bg["image"])
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        g = QLinearGradient(0, 0, 0, 1000)
        g.setColorAt(0, QColor("#FFD3A5"))
        g.setColorAt(0.55, QColor("#FD6585"))
        g.setColorAt(1, QColor("#3A1C71"))
        p.fillRect(0, 0, 1600, 1000, g)
        p.setBrush(QColor("#FFF4D6"))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QPointF(1120, 470), 170, 170)
        p.end()
        hills = ez.new_layer("pixel", "Hills", 1600, 1000)
        p = QPainter(hills["image"])
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        for colour_, pts in (("#5B2A86", [(0, 700), (300, 560), (650, 690), (1000, 520), (1350, 650), (1600, 580), (1600, 1000), (0, 1000)]),
                             ("#2E1A47", [(0, 820), (380, 700), (760, 840), (1180, 720), (1600, 830), (1600, 1000), (0, 1000)])):
            p.setBrush(QColor(colour_))
            p.drawPolygon(QPolygonF([QPointF(x, y) for x, y in pts]))
        p.end()
        doc.layers.append(hills)
        shapes = ez.new_layer("vector", "Title", 1600, 1000)
        shapes["shapes"] = [
            {"id": "s1", "type": "rect", "x": 110, "y": 120, "w": 620, "h": 250, "radius": 36, "fill": "#CCFFFFFF", "stroke": "", "width": 0, "opacity": 1},
            {"id": "s2", "type": "text", "x": 150, "y": 150, "text": "Huginn\nEasel", "font": "Inter", "size": 84, "weight": 800, "fill": "#2E1A47", "opacity": 1},
            {"id": "s3", "type": "star", "x": 600, "y": 160, "w": 90, "h": 90, "points": 5, "inner": 0.45, "fill": "#FD6585", "stroke": "#2E1A47", "width": 4, "opacity": 1},
            {"id": "s4", "type": "path", "subs": [{"nodes": [{"x": 820, "y": 300, "ox": 900, "oy": 180}, {"x": 1000, "y": 260, "ix": 950, "iy": 330, "ox": 1050, "oy": 200},
                                                            {"x": 1180, "y": 240, "ix": 1120, "iy": 160}], "closed": False}], "fill": "", "stroke": "#FFFFFF", "width": 8, "opacity": 0.9}]
        doc.layers.append(shapes)
        warm = ez.new_layer("adjust", "Warmth", 1600, 1000)
        warm["adjust"], warm["params"], warm["opacity"] = "warmth", {"warmth": 0.4}, 0.6
        doc.layers.append(warm)
        doc.active = hills["id"]
        doc.path = str(Path.home() / "Pictures" / "Evening.easel")
        self.doc = doc
        self._picked = ["s3"]

    def _remember(self, path: str) -> None:
        if not path:
            return
        self._recent = [path] + [r for r in self._recent if r != path][:11]
        self._save_prefs()

    def _save_prefs(self) -> None:
        if self._demo:
            return
        try:
            PREFS.parent.mkdir(parents=True, exist_ok=True)
            PREFS.write_text(json.dumps({"recent": self._recent, "fg": self.fg, "bg": self.bg, "swatches": self._swatches, "snap": self.snap,
                                         "rulers": self.rulers}, indent=1), encoding="utf-8")
        except OSError:
            pass

    def _fresh(self) -> None:
        self._undo, self._redo, self._picked, self._crop, self._pen, self._mask_edit, self._drag = [], [], [], None, None, "", None
        self._saved_at = None
        self._selection_changed()
        self.changed.emit()
        self.painted.emit()

    @Slot(int, int, str)
    def newDoc(self, w: int, h: int, background: str) -> None:
        w, h = max(1, min(int(w), 16384)), max(1, min(int(h), 16384))
        self.doc = ez.Document(w, h, None if background == "transparent" else (background or "#FFFFFF"))
        self._fresh()

    @Slot(str)
    def open(self, path: str) -> None:
        path = path.replace("file://", "")
        try:
            doc = ez.open_any(path)
        except (OSError, ValueError, KeyError, zipfile_error()) as err:
            self.said.emit(f"Couldn't open “{Path(path).name}”: {err}", True)
            return
        self.doc = doc
        self._fresh()
        if doc.path:
            self._remember(path)
        else:
            self._opened_from = path
            self._remember(path)

    @Slot(str, result="QVariantList")
    def browse(self, folder: str):
        """A folder's contents for the Open and Save sheets: folders first, then pictures Easel can open."""
        base = Path(folder.replace("file://", "") or str(Path.home() / "Pictures")).expanduser()
        out = []
        try:
            for p in sorted(base.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
                if p.name.startswith("."):
                    continue
                if p.is_dir() or p.suffix.lower() in OPENABLE:
                    out.append({"name": p.name, "path": str(p), "dir": p.is_dir()})
        except OSError:
            pass
        return out[:600]

    @Property(str, constant=True)
    def home(self):
        return str(Path.home())

    @Slot(result=str)
    def suggestedName(self):
        if self.doc and self.doc.path:
            return Path(self.doc.path).stem
        return Path(getattr(self, "_opened_from", "")).stem or "Untitled"

    @Slot(result=str)
    def suggestedFolder(self):
        if self.doc and self.doc.path:
            return str(Path(self.doc.path).parent)
        src = getattr(self, "_opened_from", "")
        return str(Path(src).parent) if src else str(Path.home() / "Pictures")

    @Slot(result=bool)
    def save(self) -> bool:
        if not self.doc:
            return False
        if not self.doc.path:
            return False                                            # the window asks where
        return self.saveAs(self.doc.path)

    @Slot(str, result=bool)
    def saveAs(self, path: str) -> bool:
        path = path.replace("file://", "")
        if not path.endswith(".easel"):
            path += ".easel"
        if self._demo:
            self.doc.path = path
            self.said.emit(f"Saved “{Path(path).name}”.", False)
            self.changed.emit()
            return True
        try:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            self.doc.save_easel(path)
        except OSError as err:
            self.said.emit(f"Couldn't save: {err.strerror or err}", True)
            return False
        self._saved_at = self._undo[-1] if self._undo else None
        self._remember(path)
        self.changed.emit()
        self.said.emit(f"Saved “{Path(path).name}”.", False)
        return True

    @Slot(str, int)
    def exportAs(self, path: str, quality: int) -> None:
        path = path.replace("file://", "")
        if Path(path).suffix.lower() not in (".png", ".jpg", ".jpeg", ".webp", ".svg", ".pdf", ".ora", ".psd", ".tif", ".tiff", ".bmp"):
            path += ".png"
        try:
            if path.lower().endswith(".ora"):
                self.doc.save_ora(path)
            else:
                self.doc.export(path, quality)
        except (OSError, ValueError) as err:
            self.said.emit(f"Couldn't export: {err}", True)
            return
        kind = Path(path).suffix.upper().lstrip(".")
        extra = (" Shapes stay shapes in it." if kind in ("SVG", "PDF") else " Krita and GIMP open it with its layers." if kind == "ORA"
                 else " Photoshop opens it with its layers (shapes and type as pictures)." if kind == "PSD" else "")
        self.said.emit(f"Exported “{Path(path).name}”.{extra}", False)

    @Slot()
    def closeDoc(self) -> None:
        self.doc = None
        self._fresh()

    # ------------------------------------------------------------------ history
    def _push(self, name: str) -> None:
        self._undo.append((name, self.doc.snapshot()))
        per = self.doc.w * self.doc.h * 4                             # roughly what one step keeps: one changed layer
        while len(self._undo) > 60 or (len(self._undo) * per > 900_000_000 and len(self._undo) > 8):
            self._undo.pop(0)
        self._redo.clear()

    @Slot()
    def undo(self) -> None:
        if not self._undo or not self.doc:
            return
        if self._pen is not None:
            self.finishPen()
        if self._xform is not None:
            self.cancelTransform()
            return
        name, snap = self._undo.pop()
        self._redo.append((name, self.doc.snapshot()))
        self.doc.restore(snap)
        self._after_history()

    @Slot()
    def redo(self) -> None:
        if not self._redo or not self.doc:
            return
        name, snap = self._redo.pop()
        self._undo.append((name, self.doc.snapshot()))
        self.doc.restore(snap)
        self._after_history()

    def _after_history(self) -> None:
        self._picked = [i for i in self._picked if any(s.get("id") == i for l in self.doc.layers for s in l.get("shapes", []))]
        self._crop, self._drag, self._live = None, None, None
        self._selection_changed()
        self.changed.emit()
        self.painted.emit()

    # ------------------------------------------------------------------ the canvas
    def render(self) -> QImage:
        if not self.doc:
            return QImage()
        return self.doc.composite(self._live)

    def overlay(self) -> dict:
        """What the canvas draws over the picture, in document pixels."""
        out = {"selection": self._sel_path, "boxes": [], "handles": None, "pen": None, "crop": self._crop, "line": None, "rect": None, "lasso": None,
               "brush": None, "nodes": []}
        d = self._drag or {}
        if d.get("kind") in ("select", "ellipsesel") and d.get("rect") is not None:
            out["rect"] = (d["kind"], d["rect"])
        if d.get("kind") == "lasso":
            out["lasso"] = d["points"]
        if d.get("kind") == "gradient" and d.get("end"):
            out["line"] = (d["start"], d["end"])
        if d.get("kind") == "rubber" and d.get("rect") is not None:
            out["rect"] = ("select", d["rect"])
        shapes = self._picked_shapes()
        for s in shapes:
            out["boxes"].append(ez.shape_bounds(s))
        if len(shapes) == 1 and self.tool == "pointer":
            out["handles"] = ez.shape_bounds(shapes[0])
        if self._pen is not None:
            out["pen"] = self._pen
            shape = self._pen_shape()
            if shape:
                out["nodes"] = shape["subs"][0]["nodes"]
        elif len(shapes) == 1 and shapes[0]["type"] == "path" and self.tool in ("pointer", "pen", "nodes"):
            out["nodes"] = [n for sub in shapes[0].get("subs", []) for n in sub["nodes"]]
        out["guides"] = [dict(g) for g in self.doc.guides] if self.doc else []
        out["guideLive"] = self._guide_live
        if self._hover is not None and self.tool in ("brush", "eraser", "clone", "heal", "dodge", "smudge", "liquify") and self.doc:
            out["brush"] = (self._hover, self.brush["size"])
        out["xform"] = self._xform_handles() if self._xform else None
        out["source"] = None
        if self.tool in ("clone", "heal") and self._clone_src is not None and not (self.tool == "heal" and self.heal_spot):
            if self._clone_off is not None and self._hover is not None:
                out["source"] = QPointF(self._hover.x() + self._clone_off[0], self._hover.y() + self._clone_off[1])
            else:
                out["source"] = self._clone_src
        out["nodesel"] = None
        if self._node_sel:
            nd = self._node_ref()
            if nd is not None:
                out["nodesel"] = QPointF(nd["x"], nd["y"])
        return out

    def _selection_changed(self) -> None:
        self._sel_path = self.doc.selection_path() if self.doc and self.doc.selection is not None else QPainterPath()

    # ------------------------------------------------------------------ settings the bars change
    @Slot(str)
    def setTool(self, tool: str) -> None:
        if tool not in TOOL_NAMES:
            return
        if self._pen is not None and tool != "pen":
            self.finishPen()
        if self._xform is not None and tool != "transform":
            self.applyTransform()
        if tool != "nodes":
            self._node_sel = None
        self.tool = tool
        self.changed.emit()
        self.painted.emit()

    @Slot(str)
    def setPersona(self, persona: str) -> None:
        if persona not in ("pixel", "vector") or persona == self.persona:
            return
        if self._pen is not None:
            self.finishPen()
        if self._xform is not None:
            self.applyTransform()
        self.persona = persona
        self.tool = "brush" if persona == "pixel" else "pointer"
        if self.doc and persona == "vector" and self.doc.layer()["kind"] != "vector":
            target = next((l for l in reversed(self.doc.layers) if l["kind"] == "vector"), None)
            if target:
                self.doc.active = target["id"]
        self.changed.emit()
        self.painted.emit()

    @Slot(str, str)
    def setColour(self, which: str, value: str) -> None:
        c = QColor(value)
        if not c.isValid():
            return
        value = _hex(c)
        if which == "fg":
            self.fg = value
        elif which == "bg":
            self.bg = value
        self._save_prefs()
        self.changed.emit()

    @Slot()
    def swapColours(self) -> None:
        self.fg, self.bg = self.bg, self.fg
        self.changed.emit()

    @Slot()
    def keepSwatch(self) -> None:
        if self.fg not in self._swatches:
            self._swatches = [self.fg] + self._swatches[:23]
            self._save_prefs()
            self.changed.emit()

    @Slot(str)
    def setBrushPreset(self, key: str) -> None:
        if key in ez.BRUSHES:
            self.brush_key, self.brush = key, dict(ez.BRUSHES[key])
            self.changed.emit()
            self.painted.emit()

    @Slot(str, float)
    def setBrush(self, key: str, value: float) -> None:
        if key == "size":
            self.brush["size"] = max(1.0, min(1000.0, value))
        elif key in ("hardness", "flow"):
            self.brush[key] = max(0.0 if key == "hardness" else 0.01, min(1.0, value))
        elif key == "opacity":
            self.opacity = max(0.01, min(1.0, value))
        elif key == "tolerance":
            self.tolerance = max(0.0, min(1.0, value))
        self.changed.emit()
        self.painted.emit()

    @Slot(float)
    def setPressure(self, p: float) -> None:
        """How hard the pen presses, 0..1 (from a drawing tablet). A mouse never calls this."""
        self._pressure = max(0.02, min(1.0, float(p)))
        if not self._stylus:
            self._stylus = True
            self.changed.emit()

    penSeen = Property(bool, lambda self: self._stylus, notify=changed)
    busyText = Property(str, lambda self: self.busy, notify=changed)
    pressureMode = Property(str, lambda self: self.pressure_mode, notify=changed)

    @Slot(str, "QVariant")
    def setOption(self, key: str, value) -> None:
        if key == "pressure" and value in ("size", "opacity", "both", "off"):
            self.pressure_mode = value
        elif key == "contiguous":
            self.contiguous = bool(value)
        elif key == "gradientKind" and value in ("linear", "radial"):
            self.gradient_kind = value
        elif key == "gradientClear":
            self.gradient_clear = bool(value)
        self.changed.emit()

    @Slot(str, "QVariant")
    def setStyle(self, key: str, value) -> None:
        """A shape setting: changes the picked shapes, and is what the next shape gets."""
        if key in ("fill", "stroke", "fill2"):
            value = "" if not value else _hex(QColor(value))
        elif key in ("width", "radius", "opacity", "inner", "rot", "gangle"):
            value = float(value)
        elif key == "gkind" and value not in ("linear", "radial"):
            return
        elif key == "points":
            value = max(3, int(value))
        if key != "rot":
            self.style[key] = value
        shapes = self._picked_shapes()
        if shapes:
            if not getattr(self, "_style_marked", False):
                self._push("Shape style")
            for s in shapes:
                if key in ("radius",) and s["type"] != "rect" or key in ("points", "inner") and s["type"] != "star":
                    continue
                s[key] = value
            self._touch_shapes(shapes)
        self.changed.emit()

    @Slot()
    def markStyle(self) -> None:
        """A slider for the picked shapes is starting to move: what it does undoes as one step."""
        if self._picked_shapes():
            self._push("Shape style")
            self._style_marked = True

    @Slot()
    def unmarkStyle(self) -> None:
        self._style_marked = False

    @Slot(str, "QVariant")
    def setTextStyle(self, key: str, value) -> None:
        if key not in self.text:
            return
        self.text[key] = value
        shapes = [s for s in self._picked_shapes() if s["type"] == "text"]
        if shapes:
            self._push("Text style")
            for s in shapes:
                s[key] = value
            self._touch_shapes(shapes)
        self.changed.emit()

    def _touch_shapes(self, shapes: list) -> None:
        ids = {s.get("id") for s in shapes}
        for l in self.doc.layers:
            if any(s.get("id") in ids for s in l.get("shapes", [])):
                self.doc.touch(l)
        self.painted.emit()

    # ------------------------------------------------------------------ layers
    def _insert(self, layer: dict, above: str = None) -> None:
        ref = self.doc.layer(above or self.doc.active)
        at = self.doc.index(ref["id"]) if ref else -1
        if ref is not None and ref["kind"] == "group" and ref.get("open", True) and above is None:
            layer["group"] = ref["id"]                                # a new layer on an open group goes in at its top
            at -= 1
        elif ref is not None:
            layer["group"] = ref.get("group")
        self.doc.layers.insert(at + 1 if at >= 0 else len(self.doc.layers), layer)
        self.doc.layers = more.normalize(self.doc.layers)
        self.doc.active = layer["id"]
        self.doc.touch()

    def _count(self, kind: str) -> int:
        return sum(1 for l in self.doc.layers if l["kind"] == kind) + 1

    @Slot(str)
    def addLayer(self, kind: str) -> None:
        if not self.doc or kind not in ("pixel", "vector"):
            return
        self._push("New layer")
        self._insert(ez.new_layer(kind, f"{'Layer' if kind == 'pixel' else 'Shapes'} {self._count(kind)}", self.doc.w, self.doc.h))
        self._refresh()

    @Slot(str)
    def addAdjustment(self, kind: str) -> None:
        if not self.doc or kind not in ez.ADJUSTMENTS:
            return
        self._push("New adjustment")
        layer = ez.new_layer("adjust", ez.ADJUSTMENTS[kind], self.doc.w, self.doc.h)
        layer["adjust"], layer["params"] = kind, dict(ez.ADJUST_DEFAULTS.get(kind, {}))
        if self.doc.selection is not None:
            layer["mask"] = QImage(self.doc.selection)
        self._insert(layer)
        self._refresh()

    @Slot(str, float)
    def setAdjust(self, key: str, value: float) -> None:
        l = self.doc.layer() if self.doc else None
        if not l or l["kind"] != "adjust":
            return
        l.setdefault("params", {})[key] = float(value)
        self.doc.touch(l)
        self._refresh()

    @Slot()
    def markLayer(self) -> None:
        """A layer slider is about to move (opacity, an adjustment): one undo step for the whole drag."""
        if self.doc:
            self._push("Layer change")

    @Slot(str)
    def selectLayer(self, ident: str) -> None:
        if self.doc and self.doc.index(ident) >= 0:
            if self._pen is not None:
                self.finishPen()
            self.doc.active = ident
            self._mask_edit = ""
            self._picked = []
            self.changed.emit()
            self.painted.emit()

    @Slot(str, str, "QVariant")
    def setLayer(self, ident: str, key: str, value) -> None:
        l = self.doc.layer(ident) if self.doc else None
        if not l or key not in ("name", "visible", "locked", "opacity", "blend", "maskOn"):
            return
        if key in ("name", "visible", "locked", "blend", "maskOn"):
            self._push("Layer change")
        if key == "opacity":
            value = max(0.0, min(1.0, float(value)))
        elif key == "blend" and value not in ez.BLENDS:
            return
        elif key == "name":
            value = str(value).strip()[:80] or l["name"]
        l[key] = value
        self.doc.touch(l)
        self._refresh()

    @Slot(str, int)
    def moveLayer(self, ident: str, delta: int) -> None:
        """delta +1 moves it up (toward the top of the stack), past the next layer or group beside it. At the top
        (or bottom) of a group it steps out of the group; onto an open group it steps in."""
        l = self.doc.layer(ident) if self.doc else None
        if not l or self.doc.index(ident) < 0:
            return
        sibs = self._siblings(l)
        k = next(i for i, x in enumerate(sibs) if x is l)
        items = self._subtree(l)
        if 0 <= k + delta < len(sibs):
            nb = sibs[k + delta]
            self._push("Move layer")
            if nb["kind"] == "group" and nb.get("open", True):    # into the open group next to it, at its near end
                inside = self._siblings_of_group(nb["id"])
                if inside:
                    (self._place_below if delta > 0 else self._place_above)(items, inside[0] if delta > 0 else inside[-1], nb["id"])
                else:
                    items[-1]["group"] = nb["id"]
                    self.doc.layers = more.normalize(self.doc.layers)
            else:
                (self._place_above if delta > 0 else self._place_below)(items, nb, l.get("group"))
        elif l.get("group"):                                       # out of the group, beside it
            g = self.doc.layer(l["group"])
            self._push("Move layer")
            (self._place_above if delta > 0 else self._place_below)(items, g, g.get("group"))
        else:
            return
        self.doc.touch()
        self._refresh()

    def _siblings_of_group(self, gid: str) -> list:
        return [x for x in self.doc.layers if x.get("group") == gid]

    @Slot(str, str)
    def dropLayer(self, ident: str, onto: str) -> None:
        """Drag a layer in the list onto another: it takes that one's place (in its group). Dropped on a group,
        it goes in at the top."""
        l, t = (self.doc.layer(ident), self.doc.layer(onto)) if self.doc else (None, None)
        if not l or not t or l is t or self.doc.index(ident) < 0 or self.doc.index(onto) < 0:
            return
        if l["kind"] == "group" and (t["id"] == l["id"] or l["id"] in more.ancestors(self.doc.layers, t)):
            return                                                 # not into itself
        self._push("Move layer")
        items = self._subtree(l)
        if t["kind"] == "group":
            inside = self._siblings_of_group(t["id"])
            if inside:
                self._place_above(items, inside[-1], t["id"])
            else:
                items[-1]["group"] = t["id"]
                self.doc.layers = more.normalize(self.doc.layers)
            t["open"] = True
        else:
            (self._place_above if self.doc.index(ident) < self.doc.index(onto) else self._place_below)(items, t, t.get("group"))
        self.doc.touch()
        self._refresh()

    @Slot()
    def duplicateLayer(self) -> None:
        if not self.doc:
            return
        self._push("Duplicate layer")
        src = self.doc.layer()
        items = self._subtree(src)
        ids = {x["id"]: os.urandom(5).hex() for x in items}
        dups = []
        for x in items:
            dup = ez.copy_layer(x)
            dup["id"] = ids[x["id"]]
            dup["group"] = ids.get(x.get("group"), x.get("group"))
            if dup.get("shapes"):
                for sh in dup["shapes"]:
                    sh["id"] = os.urandom(4).hex()
            dups.append(dup)
        dups[-1]["name"] = src["name"] + " copy"
        at = self.doc.index(items[-1]["id"])
        self.doc.layers[at + 1:at + 1] = dups
        self.doc.layers = more.normalize(self.doc.layers)
        self.doc.active = dups[-1]["id"]
        self.doc.touch()
        self._refresh()

    @Slot()
    def deleteLayer(self) -> None:
        if not self.doc or len(self.doc.layers) <= 1:
            self.said.emit("A picture needs at least one layer.", True)
            return
        items = self._subtree(self.doc.layer())
        if len(items) >= len(self.doc.layers):
            self.said.emit("A picture needs at least one layer.", True)
            return
        self._push("Delete layer" if len(items) == 1 else "Delete group")
        first = self.doc.index(items[0]["id"])
        gone = {x["id"] for x in items}
        self.doc.layers = [x for x in self.doc.layers if x["id"] not in gone]
        self.doc.active = self.doc.layers[max(0, min(first, len(self.doc.layers)) - 1)]["id"]
        self._picked = []
        self.doc.touch()
        self._refresh()

    def _rasterized(self, layer: dict) -> QImage:
        img = self.doc.layer_image(layer)
        return QImage(img) if img is not None else ez.new_image(self.doc.w, self.doc.h)

    @Slot()
    def rasterize(self) -> None:
        l = self.doc.layer() if self.doc else None
        if not l or l["kind"] not in ("vector", "smart", "group"):
            return
        if l["kind"] == "group":                                       # a group becomes one picture, as it shows
            self._push("Merge group")
            img = self.doc.group_image(dict(l, mask=None))
            gone = {x["id"] for x in self._subtree(l) if x is not l}
            self.doc.layers = [x for x in self.doc.layers if x["id"] not in gone]
            l.update(kind="pixel", image=QImage(img))
            l.pop("open", None)
            self.doc.touch(l)
            self._refresh()
            return
        if l["kind"] == "smart":
            self._push("Rasterise")
            img = self.doc.layer_image(dict(l, mask=None))
            for key in ("source", "place", "sfilters"):
                l.pop(key, None)
            l.update(kind="pixel", image=QImage(img))
            self.doc.touch(l)
            self._refresh()
            return
        self._push("Rasterise")
        img = self.doc.layer_image(dict(l, mask=None))
        l.update(kind="pixel", image=QImage(img))
        l.pop("shapes", None)
        self._picked = []
        self.doc.touch(l)
        self._refresh()

    @Slot()
    def mergeDown(self) -> None:
        if not self.doc:
            return
        i = self.doc.index(self.doc.active)
        if i <= 0:
            self.said.emit("There's no layer below to merge into.", True)
            return
        top, below = self.doc.layers[i], self.doc.layers[i - 1]
        if top["kind"] == "group":
            self.rasterize()
            return
        if top["kind"] == "adjust" or below["kind"] == "adjust":
            self.said.emit("Adjustment layers can't be merged; flatten the picture instead.", True)
            return
        if below["kind"] == "group" or below.get("group") != top.get("group"):
            self.said.emit("The layer below is in another group: move it next to the one to merge with.", True)
            return
        self._push("Merge down")
        base = QImage(self.doc.styled_image(below)) if below["visible"] else ez.new_image(self.doc.w, self.doc.h)
        if below.get("opacity", 1) < 1:
            faded = ez.new_image(self.doc.w, self.doc.h)
            p = QPainter(faded)
            p.setOpacity(below["opacity"])
            p.drawImage(0, 0, base)
            p.end()
            base = faded
        if top["visible"]:
            p = QPainter(base)
            p.setOpacity(top["opacity"])
            p.setCompositionMode(ez.BLENDS.get(top["blend"], ez.CM.CompositionMode_SourceOver))
            p.drawImage(0, 0, self.doc.styled_image(top))
            p.end()
        below.update(kind="pixel", image=base, mask=None, opacity=1.0, blend=below["blend"] if below["kind"] == "pixel" else "normal")
        for key in ("shapes", "source", "place", "sfilters", "fx"):
            below.pop(key, None)
        self.doc.layers.pop(i)
        self.doc.active = below["id"]
        self._picked = []
        self.doc.touch(below)
        self._refresh()

    @Slot()
    def flatten(self) -> None:
        if not self.doc:
            return
        self._push("Flatten")
        flat = ez.new_layer("pixel", "Background", self.doc.w, self.doc.h)
        flat["image"] = self.doc.composite()
        self.doc.layers = [flat]
        self.doc.active = flat["id"]
        self._picked = []
        self.doc.touch()
        self._refresh()

    @Slot(str)
    def addMask(self, how: str) -> None:
        """how: "reveal" (all white), "hide" (all black) or "selection" (white where chosen)."""
        l = self.doc.layer() if self.doc else None
        if not l or l["kind"] == "adjust" and l.get("mask") is not None:
            return
        self._push("Add mask")
        if how == "selection" and self.doc.selection is not None:
            l["mask"] = QImage(self.doc.selection)
        else:
            l["mask"] = ez.alpha_image(np.full((self.doc.h, self.doc.w), 255 if how != "hide" else 0, np.uint8))
        l["maskOn"] = True
        self._mask_edit = l["id"]
        self.doc.touch(l)
        self._refresh()

    @Slot()
    def deleteMask(self) -> None:
        l = self.doc.layer() if self.doc else None
        if l and l.get("mask") is not None:
            self._push("Delete mask")
            l["mask"] = None
            self._mask_edit = ""
            self.doc.touch(l)
            self._refresh()

    @Slot()
    def applyMask(self) -> None:
        l = self.doc.layer() if self.doc else None
        if not l or l.get("mask") is None or l["kind"] != "pixel":
            return
        self._push("Apply mask")
        l["image"] = self.doc.layer_image(l)
        l["mask"] = None
        self._mask_edit = ""
        self.doc.touch(l)
        self._refresh()

    @Slot(bool)
    def editMask(self, on: bool) -> None:
        l = self.doc.layer() if self.doc else None
        self._mask_edit = l["id"] if on and l and l.get("mask") is not None else ""
        if on and self.tool not in ("brush", "eraser", "fill", "gradient"):
            self.tool = "brush"
        self.changed.emit()

    def _refresh(self) -> None:
        self.changed.emit()
        self.painted.emit()

    # ------------------------------------------------------------------ the selection
    def _combine(self, alpha: np.ndarray, mods: int) -> None:
        """Make a new selection, or add to (Shift), take from (Alt) or keep the overlap with (both) the old one."""
        old = ez.alpha_of(self.doc.selection) if self.doc.selection is not None else None
        if old is not None and mods & SHIFT and mods & ALT:
            alpha = np.minimum(old, alpha)
        elif old is not None and mods & SHIFT:
            alpha = np.maximum(old, alpha)
        elif old is not None and mods & ALT:
            alpha = np.clip(old.astype(np.int16) - alpha, 0, 255).astype(np.uint8)
        elif mods & ALT:
            return
        self.doc.selection = ez.alpha_image(alpha) if alpha.any() else None
        self._selection_changed()

    def _shape_alpha(self, draw) -> np.ndarray:
        img = ez.new_image(self.doc.w, self.doc.h)
        p = QPainter(img)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#FFFFFF"))
        draw(p)
        p.end()
        return ez.alpha_of(img)

    @Slot()
    def selectAll(self) -> None:
        if self.doc:
            self._push("Select all")
            self.doc.selection = ez.alpha_image(np.full((self.doc.h, self.doc.w), 255, np.uint8))
            self._selection_changed()
            self._refresh()

    @Slot()
    def deselect(self) -> None:
        if self.doc and self.doc.selection is not None:
            self._push("Deselect")
            self.doc.selection = None
            self._selection_changed()
            self._refresh()

    @Slot()
    def invertSelection(self) -> None:
        if not self.doc:
            return
        self._push("Invert selection")
        a = 255 - self.doc.selection_alpha()
        self.doc.selection = ez.alpha_image(a) if a.any() else None
        self._selection_changed()
        self._refresh()

    @Slot(float)
    def feather(self, radius: float) -> None:
        if not self.doc or self.doc.selection is None:
            return
        from PIL import Image, ImageFilter
        self._push("Feather")
        a = Image.fromarray(self.doc.selection_alpha()).filter(ImageFilter.GaussianBlur(max(0.5, radius)))
        self.doc.selection = ez.alpha_image(np.asarray(a))
        self._selection_changed()
        self._refresh()

    @Slot(int)
    def growSelection(self, px: int) -> None:
        """Grow (or with a negative number, shrink) the selection by some pixels."""
        if not self.doc or self.doc.selection is None or not px:
            return
        from PIL import Image, ImageFilter
        self._push("Grow selection" if px > 0 else "Shrink selection")
        a = Image.fromarray(self.doc.selection_alpha())
        size = abs(px) * 2 + 1
        a = a.filter(ImageFilter.MaxFilter(min(size, 51)) if px > 0 else ImageFilter.MinFilter(min(size, 51)))
        arr = np.asarray(a)
        self.doc.selection = ez.alpha_image(arr) if arr.any() else None
        self._selection_changed()
        self._refresh()

    # ------------------------------------------------------------------ pixel targets
    def _target(self):
        """(layer, image to paint on, is it the mask). None when the active layer can't be painted."""
        l = self.doc.layer()
        if l["locked"]:
            self.said.emit(f"“{l['name']}” is locked.", True)
            return None
        if self._mask_edit == l["id"] and l.get("mask") is not None:
            return l, "mask"
        if l["kind"] == "pixel":
            return l, "image"
        if l["kind"] in ("group", "smart"):
            self.said.emit("Pick a layer in the group to paint on." if l["kind"] == "group" else
                           "A smart object keeps its original: rasterise it (Layer menu) to paint on it.", True)
        return None

    def _clip(self, img: QImage) -> QImage:
        """Keep only the part inside the selection."""
        if self.doc.selection is None:
            return img
        out = img.copy()
        p = QPainter(out)
        p.setCompositionMode(ez.CM.CompositionMode_DestinationIn)
        p.drawImage(0, 0, self.doc.selection)
        p.end()
        return out

    def _merge(self, base: QImage, stroke: QImage, erase: bool, opacity: float, mask_mode: bool = False) -> QImage:
        out = base.copy()
        p = QPainter(out)
        p.setOpacity(opacity)
        if mask_mode:                                                # on a mask, light colours show and dark ones hide
            erase = QColor(self.fg).lightness() < 128 if not erase else True
        p.setCompositionMode(ez.CM.CompositionMode_DestinationOut if erase else ez.CM.CompositionMode_SourceOver)
        p.drawImage(0, 0, self._clip(stroke))
        p.end()
        return out

    def _dab_image(self, erase: bool) -> QImage:
        c = QColor("#FFFFFF") if (erase or self._mask_edit) else QColor(self.fg)
        key = (round(self.brush["size"], 1), round(self.brush["hardness"], 2), c.rgba())
        img = self._dabs.get(key)
        if img is None:
            if len(self._dabs) > 40:
                self._dabs.clear()
            img = ez.dab(self.brush["size"], self.brush["hardness"], c)
            self._dabs[key] = img
        return img

    def _stamp(self, d: dict, x: float, y: float, pressure: float = None) -> None:
        img, size = d["dab"], self.brush["size"]
        p = d["painter"]
        scatter = self.brush.get("scatter", 0)
        jx = (random.random() - 0.5) * size * scatter * 2 if scatter else 0
        jy = (random.random() - 0.5) * size * scatter * 2 if scatter else 0
        pr = self._pressure if pressure is None else pressure
        mode = self.pressure_mode if self._stylus else "off"
        if mode != "off" and pr < 0.999:                     # a pen: lighter pressure, a smaller or fainter dab
            k = max(0.08, pr) if mode in ("size", "both") else 1.0
            a = max(0.05, pr) if mode in ("opacity", "both") else 1.0
            w, h = img.width() * k, img.height() * k
            p.save()
            p.setOpacity(p.opacity() * a)
            p.drawImage(QRectF(x + jx - w / 2, y + jy - h / 2, w, h), img)
            p.restore()
        else:
            p.drawImage(QPointF(x + jx - img.width() / 2, y + jy - img.height() / 2), img)
        r = size / 2 + size * scatter + 2
        d["box"] = d["box"].united(QRectF(x - r, y - r, r * 2, r * 2)) if d.get("box") else QRectF(x - r, y - r, r * 2, r * 2)

    def _stroke_to(self, d: dict, x: float, y: float) -> None:
        lx, ly = d["last"]
        step = max(0.5, self.brush["size"] * self.brush.get("spacing", 0.12))
        dist = math.hypot(x - lx, y - ly) + d.get("carry", 0)
        n = int(dist // step)
        if n <= 0:
            d["carry"] = dist
            return
        dx, dy = (x - lx), (y - ly)
        length = math.hypot(dx, dy) or 1
        start = step - d.get("carry", 0)
        p0, p1 = d.get("p_last", self._pressure), self._pressure
        for i in range(n):
            t = (start + i * step) / length
            self._stamp(d, lx + dx * t, ly + dy * t, p0 + (p1 - p0) * min(1.0, t))       # pressure eases along the line
        d["carry"] = dist - n * step
        d["last"] = (x, y)
        d["p_last"] = p1

    # ------------------------------------------------------------------ the pointer: press, move, release
    @Slot(float, float, int, int)
    def press(self, x: float, y: float, button: int, mods: int) -> None:
        if not self.doc:
            return
        tool = self.tool
        pt = QPointF(x, y)
        if button == 2 and tool in ("brush", "eraser", "fill", "gradient"):     # a right click picks the colour, like a dropper
            tool = "picker"
        handler = getattr(self, f"_press_{tool}", None)
        if handler:
            if tool in ("select", "ellipsesel", "rect", "ellipse", "line", "star", "crop", "gradient"):
                pt = self._snap_point(pt)
            handler(pt, mods)
        self.painted.emit()

    SNAPPING = ("select", "ellipsesel", "shape", "crop", "gradient")

    @Slot(float, float, int)
    def move(self, x: float, y: float, mods: int) -> None:
        if not self.doc or not self._drag:
            return
        handler = getattr(self, f"_move_{self._drag['kind']}", None)
        if handler:
            pt = QPointF(x, y)
            if self._drag["kind"] in self.SNAPPING:
                pt = self._snap_point(pt)
            handler(pt, mods)
            self.painted.emit()

    @Slot(float, float, int)
    def release(self, x: float, y: float, mods: int) -> None:
        if not self.doc or not self._drag:
            return
        handler = getattr(self, f"_release_{self._drag['kind']}", None)
        d = self._drag
        if handler:
            handler(QPointF(x, y), mods)
        if self._drag is d:
            self._drag = None
        if self._xform is None:                                      # a transform keeps showing until it's applied
            self._live = None
        self._refresh()

    @Slot(float, float)
    def hover(self, x: float, y: float) -> None:
        if not self.doc:
            return
        self._hover = QPointF(x, y) if x >= -9999 else None
        inside = 0 <= x < self.doc.w and 0 <= y < self.doc.h
        text = f"{int(x)}, {int(y)} px" if inside else ""
        if text != self._cursor:
            self._cursor = text
            self.changed.emit()
        if self.tool in ("brush", "eraser", "dodge", "smudge", "liquify"):
            self.painted.emit()

    @Slot(float, float)
    def doubleClick(self, x: float, y: float) -> None:
        if self._xform is not None:
            self.applyTransform()
            return
        if self.tool == "nodes" and self._node_sel is not None:
            self.toggleSmooth()
            return
        if self._pen is not None:
            self.finishPen()
            return
        if self.tool in ("pointer", "text"):
            hit = self._shape_at(QPointF(x, y))
            if hit and hit[1]["type"] == "text":
                self._picked = [hit[1]["id"]]
                self.editText.emit(hit[1]["text"], hit[1]["x"], hit[1]["y"])
                self._refresh()
        if self.tool == "crop" and self._crop is not None:
            self.applyCrop()

    # --- painting
    def _press_brush(self, pt: QPointF, mods: int, erase: bool = False) -> None:
        target = self._target()
        if target is None:
            l = self.doc.layer()
            if not l["locked"] and l["kind"] not in ("group", "smart"):
                self.said.emit("Brushes paint on pixel layers. Pick one, or add one with + in Layers.", True)
            return
        layer, which = target
        self._push("Eraser" if erase else "Brush")
        stroke = ez.new_image(self.doc.w, self.doc.h)
        painter = QPainter(stroke)
        painter.setOpacity(self.brush["flow"])
        d = {"kind": "brush", "layer": layer, "which": which, "stroke": stroke, "painter": painter, "erase": erase, "dab": self._dab_image(erase),
             "last": (pt.x(), pt.y()), "carry": 0.0}
        if mods & SHIFT and getattr(self, "_last_point", None):      # Shift: a straight line from the last stroke
            d["last"] = self._last_point
            self._stroke_to(d, pt.x(), pt.y())
        else:
            self._stamp(d, pt.x(), pt.y())
        self._drag = d
        mask_mode = which == "mask"
        self._live = (layer["id"], (lambda img, d=d: self._merge(img, d["stroke"], d["erase"], self.opacity, mask_mode))) if not mask_mode else None
        if mask_mode:
            self._live = (layer["id"], lambda img, d=d: img)

    def _press_eraser(self, pt: QPointF, mods: int) -> None:
        self._press_brush(pt, mods, erase=True)

    def _move_brush(self, pt: QPointF, mods: int) -> None:
        self._stroke_to(self._drag, pt.x(), pt.y())
        d = self._drag
        if d["which"] == "mask":                                       # show the mask as it is being painted
            d["layer"]["mask"] = self._merge(d.setdefault("mask0", d["layer"]["mask"]), d["stroke"], d["erase"], self.opacity, True)
            self.doc.touch(d["layer"])

    def _release_brush(self, pt: QPointF, mods: int) -> None:
        d = self._drag
        self._stroke_to(d, pt.x(), pt.y())
        d["painter"].end()
        layer = d["layer"]
        if d["which"] == "mask":
            layer["mask"] = self._merge(d.get("mask0", layer["mask"]), d["stroke"], d["erase"], self.opacity, True)
        else:
            layer["image"] = self._merge(layer["image"], d["stroke"], d["erase"], self.opacity)
        self._last_point = (pt.x(), pt.y())
        self.doc.touch(layer)

    # --- fill and gradient
    def _press_fill(self, pt: QPointF, mods: int) -> None:
        x, y = int(pt.x()), int(pt.y())
        if not (0 <= x < self.doc.w and 0 <= y < self.doc.h):
            return
        l = self.doc.layer()
        if l["kind"] == "vector" and not l["locked"]:                 # on shapes, the bucket paints the shape it lands on
            hit = self._shape_at(pt, l)
            if hit:
                self._push("Fill shape")
                key = "stroke" if mods & ALT else "fill"
                hit[1][key] = self.fg
                self.doc.touch(l)
                self._refresh()
            return
        target = self._target()
        if target is None:
            return
        layer, which = target
        self._push("Fill")
        base = layer[which]
        rgba = ez.image_to_array(base)
        ok = ez.similar(rgba, x, y, self.tolerance)
        region = ez.flood(ok, x, y) if self.contiguous else ok
        if self.doc.selection is not None:
            region &= self.doc.selection_alpha() > 127
        paint = ez.new_image(self.doc.w, self.doc.h, "#FFFFFF" if which == "mask" else self.fg)
        p = QPainter(paint)
        p.setCompositionMode(ez.CM.CompositionMode_DestinationIn)
        p.drawImage(0, 0, ez.alpha_image(region.astype(np.uint8) * 255))
        p.end()
        layer[which] = self._merge(base, paint, which == "mask" and QColor(self.fg).lightness() < 128, self.opacity, False)
        self.doc.touch(layer)
        self._refresh()

    def _gradient_image(self, a: QPointF, b: QPointF) -> QImage:
        img = ez.new_image(self.doc.w, self.doc.h)
        c0, c1 = QColor(self.fg), QColor(self.bg)
        if self.gradient_clear:
            c1 = QColor(self.fg)
            c1.setAlpha(0)
        if self.gradient_kind == "radial":
            g = QRadialGradient(a, max(1.0, math.hypot(b.x() - a.x(), b.y() - a.y())))
        else:
            g = QLinearGradient(a, b)
        g.setColorAt(0, c0)
        g.setColorAt(1, c1)
        p = QPainter(img)
        p.fillRect(0, 0, self.doc.w, self.doc.h, QBrush(g))
        p.end()
        return img

    def _press_gradient(self, pt: QPointF, mods: int) -> None:
        target = self._target()
        if target is None:
            return
        self._push("Gradient")
        self._drag = {"kind": "gradient", "start": pt, "end": None, "layer": target[0], "which": target[1]}

    def _move_gradient(self, pt: QPointF, mods: int) -> None:
        d = self._drag
        if mods & SHIFT:                                              # Shift: straight across, down or at 45°
            dx, dy = pt.x() - d["start"].x(), pt.y() - d["start"].y()
            ang = round(math.atan2(dy, dx) / (math.pi / 4)) * (math.pi / 4)
            r = math.hypot(dx, dy)
            pt = QPointF(d["start"].x() + r * math.cos(ang), d["start"].y() + r * math.sin(ang))
        d["end"] = pt
        grad = self._gradient_image(d["start"], pt)
        self._live = (d["layer"]["id"], lambda img, g=grad: self._merge(img, g, False, self.opacity))

    def _release_gradient(self, pt: QPointF, mods: int) -> None:
        d = self._drag
        if d.get("end") is None or math.hypot(d["end"].x() - d["start"].x(), d["end"].y() - d["start"].y()) < 2:
            self._undo.pop()
            return
        layer = d["layer"]
        grad = self._gradient_image(d["start"], d["end"])
        layer[d["which"]] = self._merge(layer[d["which"]], grad, False, self.opacity)
        self.doc.touch(layer)

    def _press_picker(self, pt: QPointF, mods: int) -> None:
        x, y = int(pt.x()), int(pt.y())
        if not (0 <= x < self.doc.w and 0 <= y < self.doc.h):
            return
        c = QColor(self.doc.composite().pixelColor(x, y))
        if c.alpha() == 0:
            return
        c.setAlpha(255)
        self.setColour("bg" if mods & ALT else "fg", c.name())
        picked = self._picked_shapes()
        if picked and self.persona == "vector":
            self.setStyle("fill", c.name())

    # --- choosing an area
    def _press_select(self, pt: QPointF, mods: int) -> None:
        self._drag = {"kind": self.tool if self.tool in ("select", "ellipsesel") else "select", "start": pt, "rect": None, "mods": mods}

    _press_ellipsesel = _press_select

    def _move_select(self, pt: QPointF, mods: int) -> None:
        d = self._drag
        s = d["start"]
        w, h = pt.x() - s.x(), pt.y() - s.y()
        if mods & SHIFT and not d["mods"] & SHIFT:                   # Shift while dragging: a square or circle
            m = max(abs(w), abs(h))
            w, h = math.copysign(m, w or 1), math.copysign(m, h or 1)
        d["rect"] = QRectF(s.x(), s.y(), w, h).normalized()

    _move_ellipsesel = _move_select

    def _release_select(self, pt: QPointF, mods: int) -> None:
        d = self._drag
        rect = d.get("rect")
        if rect is None or rect.width() < 2 or rect.height() < 2:
            if not d["mods"] & (SHIFT | ALT):
                self.deselect()
            return
        self._push("Select")
        ellipse = d["kind"] == "ellipsesel"
        alpha = self._shape_alpha(lambda p: p.drawEllipse(rect) if ellipse else p.fillRect(rect, QColor("#FFFFFF")))
        self._combine(alpha, d["mods"])

    _release_ellipsesel = _release_select

    def _press_lasso(self, pt: QPointF, mods: int) -> None:
        self._drag = {"kind": "lasso", "points": [pt], "mods": mods}

    def _move_lasso(self, pt: QPointF, mods: int) -> None:
        pts = self._drag["points"]
        if math.hypot(pt.x() - pts[-1].x(), pt.y() - pts[-1].y()) >= 1.5:
            pts.append(pt)

    def _release_lasso(self, pt: QPointF, mods: int) -> None:
        pts = self._drag["points"]
        if len(pts) < 3:
            return
        self._push("Lasso")
        poly = QPolygonF(pts)
        self._combine(self._shape_alpha(lambda p: p.drawPolygon(poly)), self._drag["mods"])

    def _press_wand(self, pt: QPointF, mods: int) -> None:
        x, y = int(pt.x()), int(pt.y())
        if not (0 <= x < self.doc.w and 0 <= y < self.doc.h):
            return
        l = self.doc.layer()
        source = l["image"] if l["kind"] == "pixel" else self.doc.composite()
        rgba = ez.image_to_array(source)
        ok = ez.similar(rgba, x, y, self.tolerance)
        region = ez.flood(ok, x, y) if self.contiguous else ok
        self._push("Magic wand")
        self._combine(region.astype(np.uint8) * 255, mods)
        self._refresh()

    # --- moving a layer (or what's selected on it)
    def _press_move(self, pt: QPointF, mods: int) -> None:
        l = self.doc.layer()
        if l["locked"] or l["kind"] == "adjust":
            return
        k = self.guide_at(pt.x(), pt.y(), 5 / max(0.05, self.zoom)) if self.doc.guides else -1
        if k >= 0:                                                    # the Move tool drags guides too
            self._drag = {"kind": "guide", "k": k, "axis": self.doc.guides[k]["axis"]}
            return
        self._push("Move")
        d = {"kind": "move", "start": pt, "dx": 0.0, "dy": 0.0, "layer": l, "box": self._content_box(l) if self.snap else None}
        if l["kind"] in ("group", "smart"):
            d["members"] = [x for x in self._subtree(l) if x["kind"] in ("pixel", "vector", "smart")]
            d["orig"] = {x["id"]: (QImage(x["image"]) if x["kind"] == "pixel" else json.loads(json.dumps(x.get("shapes") or x.get("place"))))
                         for x in d["members"]}
            self._drag = d
            return
        if l["kind"] == "pixel" and self.doc.selection is not None:   # lift what's selected off the layer
            sel = self.doc.selection
            floating = self._clip(l["image"])
            rest = l["image"].copy()
            p = QPainter(rest)
            p.setCompositionMode(ez.CM.CompositionMode_DestinationOut)
            p.drawImage(0, 0, sel)
            p.end()
            d.update(floating=floating, rest=rest, sel=QImage(sel))
        self._drag = d

    def _move_move(self, pt: QPointF, mods: int) -> None:
        d = self._drag
        d["dx"], d["dy"] = pt.x() - d["start"].x(), pt.y() - d["start"].y()
        if mods & SHIFT:
            if abs(d["dx"]) > abs(d["dy"]):
                d["dy"] = 0
            else:
                d["dx"] = 0
        elif d.get("box") is not None and "floating" not in d:
            d["dx"], d["dy"] = self._snap_box(d["box"], d["dx"], d["dy"])
        l = d["layer"]
        if "members" in d:                                            # a group (everything in it) or a smart object
            for x in d["members"]:
                o = d["orig"][x["id"]]
                if x["kind"] == "pixel":
                    out = ez.new_image(self.doc.w, self.doc.h)
                    p = QPainter(out)
                    p.drawImage(QPointF(d["dx"], d["dy"]), o)
                    p.end()
                    x["image"] = out
                elif x["kind"] == "smart":
                    x["place"] = dict(o, cx=o["cx"] + d["dx"], cy=o["cy"] + d["dy"])
                else:
                    x["shapes"] = json.loads(json.dumps(o))
                    for sh in x["shapes"]:
                        ez.move_shape(sh, d["dx"], d["dy"])
                self.doc.touch(x)
            return
        if l["kind"] == "pixel":
            self._live = (l["id"], lambda img, d=d: self._shifted(d))
        else:
            if "shapes0" not in d:
                d["shapes0"] = json.loads(json.dumps(l["shapes"]))
            l["shapes"] = json.loads(json.dumps(d["shapes0"]))
            for s in l["shapes"]:
                ez.move_shape(s, d["dx"], d["dy"])
            self.doc.touch(l)

    def _move_guide(self, pt: QPointF, mods: int) -> None:
        d = self._drag
        d["at"] = pt.x() if d["axis"] == "x" else pt.y()
        self.set_guide_live((d["axis"], d["at"], d["k"]))

    def _release_guide(self, pt: QPointF, mods: int) -> None:
        d = self._drag
        at = pt.x() if d["axis"] == "x" else pt.y()
        size = self.doc.w if d["axis"] == "x" else self.doc.h
        if at < -4 or at > size + 4:                                  # dragged off the picture: gone
            self.removeGuide(d["k"])
        elif "at" in d:
            self.moveGuide(d["k"], at)
        self._guide_live = None

    def _shifted(self, d: dict) -> QImage:
        l = d["layer"]
        out = (d["rest"] if "rest" in d else ez.new_image(self.doc.w, self.doc.h)).copy()
        p = QPainter(out)
        p.drawImage(QPointF(d["dx"], d["dy"]), d.get("floating", l["image"]))
        p.end()
        return out

    def _release_move(self, pt: QPointF, mods: int) -> None:
        d = self._drag
        if abs(d["dx"]) < 0.5 and abs(d["dy"]) < 0.5:
            self._undo.pop()
            return
        if "members" in d:
            for x in d["members"]:
                self.doc.touch(x)
            self.doc.touch(d["layer"])
            return
        l = d["layer"]
        if l["kind"] == "pixel":
            l["image"] = self._shifted(d)
            if "sel" in d:                                             # the selection travels with what it held
                moved = ez.new_image(self.doc.w, self.doc.h)
                p = QPainter(moved)
                p.drawImage(QPointF(d["dx"], d["dy"]), d["sel"])
                p.end()
                self.doc.selection = moved
                self._selection_changed()
        self.doc.touch(l)

    # --- cropping the canvas
    def _press_crop(self, pt: QPointF, mods: int) -> None:
        self._drag = {"kind": "crop", "start": pt}
        self._crop = QRectF(pt, pt)

    def _move_crop(self, pt: QPointF, mods: int) -> None:
        s = self._drag["start"]
        r = QRectF(s, pt).normalized()
        self._crop = r.intersected(QRectF(0, 0, self.doc.w, self.doc.h))

    def _release_crop(self, pt: QPointF, mods: int) -> None:
        if self._crop is None or self._crop.width() < 4 or self._crop.height() < 4:
            self._crop = None
        self.changed.emit()

    @Slot()
    def applyCrop(self) -> None:
        rect = self._crop
        if rect is None:
            if self.doc and self.doc.selection is not None:
                b = self.doc.selection_box()
                rect = QRectF(b)
            else:
                return
        self._crop = None
        self._resize_canvas(QRect(int(round(rect.x())), int(round(rect.y())), max(1, int(round(rect.width()))), max(1, int(round(rect.height())))), "Crop")

    @Slot()
    def cancelCrop(self) -> None:
        self._crop = None
        self._refresh()

    def _resize_canvas(self, rect: QRect, name: str) -> None:
        """Make the canvas this rectangle of the old one (it may reach outside it, to add room)."""
        self._push(name)
        w, h = rect.width(), rect.height()
        for l in self.doc.layers:
            for key in ("image", "mask"):
                img = l.get(key)
                if img is None:
                    continue
                out = ez.new_image(w, h, "#FFFFFF" if key == "mask" else None)
                p = QPainter(out)
                p.setCompositionMode(ez.CM.CompositionMode_Source)
                p.drawImage(-rect.x(), -rect.y(), img)
                p.end()
                l[key] = out
            for s in l.get("shapes", []):
                ez.move_shape(s, -rect.x(), -rect.y())
            if l.get("place"):
                l["place"]["cx"] -= rect.x()
                l["place"]["cy"] -= rect.y()
            l["v"] = l.get("v", 0) + 1
        for g in self.doc.guides:
            g["at"] -= rect.x() if g["axis"] == "x" else rect.y()
        self.doc.w, self.doc.h = w, h
        self.doc.selection = None
        self._selection_changed()
        self.doc.touch()
        self._refresh()

    @Slot(int, int, str)
    def canvasSize(self, w: int, h: int, anchor: str) -> None:
        """anchor: one of tl t tr l c r bl b br: where the old picture sits on the new canvas."""
        if not self.doc or w < 1 or h < 1:
            return
        ax = {"l": 0, "c": 0.5, "r": 1}[anchor[-1] if anchor[-1] in "lr" else "c"] if anchor != "c" else 0.5
        ay = {"t": 0, "b": 1}.get(anchor[0], 0.5) if anchor not in ("l", "r", "c") else 0.5
        x, y = int(round((self.doc.w - w) * ax)), int(round((self.doc.h - h) * ay))
        self._resize_canvas(QRect(x, y, int(w), int(h)), "Canvas size")

    @Slot(int, int)
    def imageSize(self, w: int, h: int) -> None:
        """Scale everything: pixels are resampled, shapes simply grow."""
        if not self.doc or w < 1 or h < 1:
            return
        self._push("Image size")
        sx, sy = w / self.doc.w, h / self.doc.h
        for l in self.doc.layers:
            for key in ("image", "mask"):
                if l.get(key) is not None:
                    l[key] = l[key].scaled(w, h, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
            for s in l.get("shapes", []):
                ez.scale_shape(s, QRectF(0, 0, self.doc.w, self.doc.h), QRectF(0, 0, w, h))
                if s.get("width"):
                    s["width"] = s["width"] * (sx + sy) / 2
            if l.get("place"):
                pl = l["place"]
                pl.update(cx=pl["cx"] * sx, cy=pl["cy"] * sy, sx=pl["sx"] * sx, sy=pl["sy"] * sy)
            l["v"] = l.get("v", 0) + 1
        for g in self.doc.guides:
            g["at"] *= sx if g["axis"] == "x" else sy
        self.doc.w, self.doc.h = int(w), int(h)
        self.doc.selection = None
        self._selection_changed()
        self.doc.touch()
        self._refresh()

    @Slot(str)
    def transformCanvas(self, how: str) -> None:
        """how: "cw", "ccw", "180", "fliph", "flipv"."""
        if not self.doc or how not in ("cw", "ccw", "180", "fliph", "flipv"):
            return
        self._push({"cw": "Rotate right", "ccw": "Rotate left", "180": "Rotate 180°", "fliph": "Flip across", "flipv": "Flip upside down"}[how])
        w, h = self.doc.w, self.doc.h
        t = {"cw": QTransform(0, 1, -1, 0, h, 0), "ccw": QTransform(0, -1, 1, 0, 0, w), "180": QTransform(-1, 0, 0, -1, w, h),
             "fliph": QTransform(-1, 0, 0, 1, w, 0), "flipv": QTransform(1, 0, 0, -1, 0, h)}[how]
        nw, nh = (h, w) if how in ("cw", "ccw") else (w, h)
        for l in self.doc.layers:
            for key in ("image", "mask"):
                if l.get(key) is not None:
                    out = ez.new_image(nw, nh)
                    p = QPainter(out)
                    p.setTransform(t)
                    p.drawImage(0, 0, l[key])
                    p.end()
                    l[key] = out
            new = []
            for s in l.get("shapes", []):
                path = ez.shape_path(s)
                mapped = t.map(path)
                keep = {k: s[k] for k in ("id", "fill", "stroke", "width", "opacity", "fill2") if k in s}
                if s["type"] == "text" and how in ("cw", "ccw", "180"):
                    c = t.map(path.boundingRect().center())
                    s2 = dict(s)
                    s2["rot"] = (s.get("rot", 0) + {"cw": 90, "ccw": -90, "180": 180}[how]) % 360
                    box = ez.raw_path(dict(s, rot=0)).boundingRect()
                    ez.move_shape(s2, c.x() - box.center().x(), c.y() - box.center().y())
                    new.append(s2)
                else:
                    new.append({**keep, "type": "path", "subs": ez.path_to_subs(mapped) if s["type"] != "line" else
                                [{"nodes": [{"x": t.map(QPointF(s["x1"], s["y1"])).x(), "y": t.map(QPointF(s["x1"], s["y1"])).y()},
                                            {"x": t.map(QPointF(s["x2"], s["y2"])).x(), "y": t.map(QPointF(s["x2"], s["y2"])).y()}], "closed": False}]})
            if "shapes" in l:
                l["shapes"] = new
            if l.get("place"):
                pl = l["place"]
                c = t.map(QPointF(pl["cx"], pl["cy"]))
                pl["cx"], pl["cy"] = c.x(), c.y()
                if how in ("cw", "ccw", "180"):
                    pl["rot"] = (pl.get("rot", 0) + {"cw": 90, "ccw": -90, "180": 180}[how]) % 360
                else:
                    pl["flipx" if how == "fliph" else "flipy"] = not pl.get("flipx" if how == "fliph" else "flipy")
                    pl["rot"] = -pl.get("rot", 0) % 360
            l["v"] = l.get("v", 0) + 1
        self.doc.guides = []
        self.doc.w, self.doc.h = nw, nh
        self.doc.selection = None
        self._selection_changed()
        self.doc.touch()
        self._refresh()

    @Slot()
    def trim(self) -> None:
        """Cut away the transparent edges."""
        if not self.doc:
            return
        a = ez.alpha_of(self.doc.composite())
        ys, xs = np.nonzero(a > 4)
        if not len(xs):
            return
        self._resize_canvas(QRect(int(xs.min()), int(ys.min()), int(xs.max() - xs.min() + 1), int(ys.max() - ys.min() + 1)), "Trim")

    # ------------------------------------------------------------------ editing what's selected
    @Slot()
    def fillSelection(self) -> None:
        target = self._target() if self.doc else None
        if target is None:
            return
        layer, which = target
        self._push("Fill")
        layer[which] = self._merge(layer[which], ez.new_image(self.doc.w, self.doc.h, "#FFFFFF" if which == "mask" else self.fg), False, self.opacity)
        self.doc.touch(layer)
        self._refresh()

    _filled = Signal(object)

    @Slot()
    def fillAware(self) -> None:
        """Fill the selection with what's around it (content-aware fill): a person, a wire or a blemish disappears and
        the background carries on through. Runs in the background; undo puts it back."""
        target = self._target() if self.doc else None
        if target is None or self.doc.selection is None:
            self.said.emit("Choose the part to fill first, on a pixel layer.", True)
            return
        layer, which = target
        if which == "mask":
            return
        hole = ez.alpha_of(self.doc.selection) > 96
        if not hole.any():
            return
        if hole.mean() > 0.6:
            self.said.emit("Choose a smaller part: the fill needs enough of the picture around it to learn from.", True)
            return
        rgba = ez.image_to_array(layer[which])
        self._push("Fill with surroundings")
        self.busy = "Filling from the surroundings…"
        self.changed.emit()
        lid = layer["id"]

        def work():
            try:
                out = ez.content_fill(rgba, hole)
            except Exception as err:                         # noqa: BLE001
                out = err
            self._filled.emit((lid, which, out))
        threading.Thread(target=work, daemon=True).start()

    def _took_fill(self, result) -> None:
        lid, which, out = result
        self.busy = ""
        if isinstance(out, Exception):
            self.said.emit(f"Couldn't fill it: {out}", True)
        else:
            layer = self.doc.layer(lid) if self.doc else None
            if layer is not None:
                layer[which] = ez.array_to_image(out)
                self.doc.touch(layer)
                self._refresh()
        self.changed.emit()
        self.painted.emit()

    @Slot()
    def textOnPath(self) -> None:
        """Pick some type and a line or shape: the type follows it."""
        picked = self._picked_shapes()
        texts = [s for s in picked if s["type"] == "text"]
        guides = [s for s in picked if s["type"] != "text"]
        if len(texts) != 1 or len(guides) != 1:
            self.said.emit("Pick one piece of type and one line or shape (Shift-click both).", True)
            return
        path = ez.shape_path(guides[0])
        pts = []
        for poly in path.toSubpathPolygons():
            pts += [[round(q.x(), 2), round(q.y(), 2)] for q in poly]
            break
        if len(pts) < 2:
            return
        self._push("Type on a path")
        texts[0]["along"] = pts
        texts[0].setdefault("pathOffset", 0.0)
        if guides[0].get("stroke") and float(guides[0].get("width") or 0) > 0:      # sit just clear of a drawn line
            texts[0].setdefault("pathLift", round(float(guides[0]["width"]) / 2 + 4, 1))
        self.doc.touch(self.doc.layer())
        self._refresh()
        self.changed.emit()

    @Slot()
    def textOffPath(self) -> None:
        picked = [s for s in self._picked_shapes() if s["type"] == "text" and s.get("along")]
        if not picked:
            return
        self._push("Type off its path")
        for s_ in picked:
            s_.pop("along", None)
        self.doc.touch(self.doc.layer())
        self._refresh()
        self.changed.emit()

    @Slot(float)
    def setPathOffset(self, v: float) -> None:
        picked = [s for s in self._picked_shapes() if s["type"] == "text" and s.get("along")]
        for s_ in picked:
            s_["pathOffset"] = max(0.0, min(1.0, float(v)))
        if picked:
            self.doc.touch(self.doc.layer())
            self._refresh()
            self.changed.emit()

    @Slot()
    def clearSelection(self) -> None:
        """Delete: rub out what's selected on a pixel layer, or the picked shapes."""
        if not self.doc:
            return
        if self._picked_shapes():
            self.deleteShapes()
            return
        target = self._target()
        if target is None or self.doc.selection is None:
            return
        layer, which = target
        self._push("Delete")
        layer[which] = self._merge(layer[which], ez.new_image(self.doc.w, self.doc.h, "#FFFFFF"), True, 1.0)
        self.doc.touch(layer)
        self._refresh()

    @Slot(bool)
    def layerFromSelection(self, cut: bool) -> None:
        l = self.doc.layer() if self.doc else None
        if not l or l["kind"] != "pixel" or self.doc.selection is None:
            self.said.emit("Choose part of a pixel layer first.", True)
            return
        self._push("Cut to new layer" if cut else "Copy to new layer")
        part = self._clip(l["image"])
        if cut:
            l["image"] = self._merge(l["image"], ez.new_image(self.doc.w, self.doc.h, "#FFFFFF"), True, 1.0)
            self.doc.touch(l)
        layer = ez.new_layer("pixel", f"Layer {self._count('pixel')}", self.doc.w, self.doc.h)
        layer["image"] = part
        self._insert(layer)
        self._refresh()

    @Slot(str, float)
    def applyFilter(self, name: str, amount: float) -> None:
        l = self.doc.layer() if self.doc else None
        if l and l["kind"] == "smart" and name in ez.FILTERS and not l["locked"]:
            self._push(ez.FILTERS[name])                               # a smart filter: kept, and can be changed or taken away
            l.setdefault("sfilters", []).append({"name": name, "amount": max(0.0, min(1.0, float(amount))), "on": True})
            self.doc.touch(l)
            self._refresh()
            return
        target = self._target() if self.doc else None
        if target is None or name not in ez.FILTERS:
            if self.doc and self.doc.layer()["kind"] == "vector":
                self.said.emit("Filters work on pixels. Rasterise the layer first (Layer menu).", True)
            return
        layer, which = target
        self._push(ez.FILTERS[name])
        rgba = ez.image_to_array(layer[which])
        out = ez.filter_array(rgba, name, max(0.0, min(1.0, amount)))
        if self.doc.selection is not None:                            # only inside the selection
            a = (self.doc.selection_alpha().astype(np.float32) / 255)[..., None]
            out = (rgba * (1 - a) + out * a + 0.5).astype(np.uint8)
        layer[which] = ez.array_to_image(out)
        self.doc.touch(layer)
        self._refresh()

    # ------------------------------------------------------------------ the clipboard
    @Slot(bool)
    def copy(self, cut: bool = False) -> None:
        if not self.doc:
            return
        shapes = self._picked_shapes()
        cb = QGuiApplication.clipboard()
        if shapes:
            data = QMimeData()
            data.setData("application/x-huginn-easel-shapes", json.dumps(shapes).encode())
            data.setText(f"{len(shapes)} shape{'s' if len(shapes) > 1 else ''} from Easel")
            cb.setMimeData(data)
            if cut:
                self.deleteShapes()
            return
        l = self.doc.layer()
        source = self.doc.layer_image(l) if l["kind"] != "adjust" else self.doc.composite()
        box = self.doc.selection_box()
        if box.isEmpty():
            return
        img = self._clip(source).copy(box)
        self._copied_at = (box.x(), box.y())
        cb.setImage(img)
        if cut and l["kind"] == "pixel" and self.doc.selection is not None:
            self.clearSelection()

    @Slot()
    def paste(self) -> None:
        if not self.doc:
            return
        cb = QGuiApplication.clipboard()
        data = cb.mimeData()
        if data is not None and data.hasFormat("application/x-huginn-easel-shapes"):
            try:
                shapes = json.loads(bytes(data.data("application/x-huginn-easel-shapes")).decode())
            except ValueError:
                return
            self._push("Paste")
            l = self.doc.layer()
            if l["kind"] != "vector":
                l = ez.new_layer("vector", f"Shapes {self._count('vector')}", self.doc.w, self.doc.h)
                self._insert(l)
            for s in shapes:
                s["id"] = os.urandom(4).hex()
                ez.move_shape(s, 20, 20)
                l["shapes"].append(s)
            self._picked = [s["id"] for s in shapes]
            self.doc.touch(l)
            self._refresh()
            return
        img = cb.image()
        if img.isNull():
            self.said.emit("There's no picture to paste.", True)
            return
        self._push("Paste")
        layer = ez.new_layer("pixel", "Pasted", self.doc.w, self.doc.h)
        x, y = getattr(self, "_copied_at", ((self.doc.w - img.width()) // 2, (self.doc.h - img.height()) // 2))
        p = QPainter(layer["image"])
        p.drawImage(int(x), int(y), img.convertToFormat(ez.FMT))
        p.end()
        self._insert(layer)
        self._copied_at = ((self.doc.w - img.width()) // 2, (self.doc.h - img.height()) // 2)
        self._refresh()

    # ------------------------------------------------------------------ shapes
    def _vector_target(self, name: str = "Shapes") -> dict:
        l = self.doc.layer()
        if l["kind"] == "vector" and not l["locked"]:
            return l
        layer = ez.new_layer("vector", f"{name} {self._count('vector')}", self.doc.w, self.doc.h)
        self._insert(layer)
        return layer

    def _shape_at(self, pt: QPointF, layer: dict = None):
        """The topmost shape under the pointer: (layer, shape) or None."""
        layers = [layer] if layer else [l for l in reversed(self.doc.layers) if l["kind"] == "vector" and l["visible"] and not l["locked"]]
        slack = 4 / max(0.05, self.zoom)
        for l in layers:
            for s in reversed(l.get("shapes", [])):
                if not s.get("hidden") and ez.hits(s, pt, slack):
                    return l, s
        return None

    def _new_shape(self, kind: str, pt: QPointF) -> dict:
        st = self.style
        s = {"id": os.urandom(4).hex(), "type": kind, "fill": st["fill"] if kind != "line" else "", "stroke": st["stroke"] if (st["width"] > 0 or kind == "line") else "",
             "width": st["width"] if kind != "line" else max(2.0, st["width"]), "opacity": st["opacity"]}
        if kind == "line":
            s.update(x1=pt.x(), y1=pt.y(), x2=pt.x(), y2=pt.y())
            if not s["stroke"]:
                s["stroke"] = st["fill"] or "#14171C"
        else:
            s.update(x=pt.x(), y=pt.y(), w=0, h=0)
        if kind == "rect":
            s["radius"] = st["radius"]
        if kind == "star":
            s.update(points=st["points"], inner=st["inner"])
        return s

    def _press_shape(self, pt: QPointF, mods: int) -> None:
        self._push(TOOL_NAMES[self.tool])
        layer = self._vector_target()
        s = self._new_shape(self.tool, pt)
        layer["shapes"].append(s)
        self._picked = [s["id"]]
        self._drag = {"kind": "shape", "start": pt, "shape": s, "layer": layer}

    _press_rect = _press_ellipse = _press_line = _press_star = _press_shape

    def _move_shape(self, pt: QPointF, mods: int) -> None:
        d = self._drag
        s, st = d["shape"], d["start"]
        w, h = pt.x() - st.x(), pt.y() - st.y()
        if s["type"] == "line":
            if mods & SHIFT:
                ang = round(math.atan2(h, w) / (math.pi / 4)) * (math.pi / 4)
                r = math.hypot(w, h)
                w, h = r * math.cos(ang), r * math.sin(ang)
            s["x2"], s["y2"] = st.x() + w, st.y() + h
        else:
            if mods & SHIFT:
                m = max(abs(w), abs(h))
                w, h = math.copysign(m, w or 1), math.copysign(m, h or 1)
            if mods & ALT:                                           # Alt: draw from the middle
                s.update(x=st.x() - abs(w), y=st.y() - abs(h), w=abs(w) * 2, h=abs(h) * 2)
            else:
                r = QRectF(st.x(), st.y(), w, h).normalized()
                s.update(x=r.x(), y=r.y(), w=r.width(), h=r.height())
        self.doc.touch(d["layer"])

    def _release_shape(self, pt: QPointF, mods: int) -> None:
        d = self._drag
        s = d["shape"]
        small = (math.hypot(s["x2"] - s["x1"], s["y2"] - s["y1"]) < 3) if s["type"] == "line" else (abs(s["w"]) < 3 and abs(s["h"]) < 3)
        if small:                                                    # a click: a shape of a sensible size, there
            size = 160 / max(0.2, self.zoom) ** 0.5
            if s["type"] == "line":
                s["x2"], s["y2"] = s["x1"] + size, s["y1"]
            else:
                s.update(w=size, h=size)
        self.doc.touch(d["layer"])

    def _press_pointer(self, pt: QPointF, mods: int) -> None:
        shapes = self._picked_shapes()
        slack = 7 / max(0.05, self.zoom)
        if len(shapes) == 1:                                         # a handle of the picked shape?
            box = ez.shape_bounds(shapes[0])
            for name, hp in self._handle_points(box, slack).items():
                if abs(pt.x() - hp.x()) <= slack and abs(pt.y() - hp.y()) <= slack:
                    self._push("Resize" if name != "rot" else "Rotate")
                    layer = next(l for l in self.doc.layers if shapes[0] in l.get("shapes", []))
                    self._drag = {"kind": "handle", "handle": name, "shape": shapes[0], "box": box, "orig": json.loads(json.dumps(shapes[0])),
                                  "layer": layer, "start": pt}
                    return
        hit = self._shape_at(pt)
        if hit:
            layer, s = hit
            if mods & SHIFT:
                self._picked = [i for i in self._picked if i != s["id"]] if s["id"] in self._picked else self._picked + [s["id"]]
            elif s["id"] not in self._picked:
                self._picked = [s["id"]]
            self.doc.active = layer["id"]
            self._push("Move shape")
            picked = self._picked_shapes()
            self._drag = {"kind": "drag", "start": pt, "orig": {x["id"]: json.loads(json.dumps(x)) for x in picked}, "moved": False}
            self.changed.emit()
            return
        if not mods & SHIFT:
            self._picked = []
        self._drag = {"kind": "rubber", "start": pt, "rect": None}
        self.changed.emit()

    def _handle_points(self, box: QRectF, slack: float) -> dict:
        c = box.center()
        pts = {"tl": box.topLeft(), "t": QPointF(c.x(), box.top()), "tr": box.topRight(), "r": QPointF(box.right(), c.y()),
               "br": box.bottomRight(), "b": QPointF(c.x(), box.bottom()), "bl": box.bottomLeft(), "l": QPointF(box.left(), c.y())}
        pts["rot"] = QPointF(c.x(), box.top() - 28 / max(0.05, self.zoom))
        return pts

    def _move_drag(self, pt: QPointF, mods: int) -> None:
        d = self._drag
        dx, dy = pt.x() - d["start"].x(), pt.y() - d["start"].y()
        if mods & SHIFT:
            if abs(dx) > abs(dy):
                dy = 0
            else:
                dx = 0
        if self.snap and not mods & SHIFT:
            if "box" not in d:
                boxes = [ez.shape_bounds(o) for o in d["orig"].values()]
                d["box"] = boxes[0] if boxes else None
                for b in boxes[1:]:
                    d["box"] = d["box"].united(b)
            dx, dy = self._snap_box(d["box"], dx, dy)
        d["moved"] = d["moved"] or abs(dx) + abs(dy) > 0.5
        for s in self._picked_shapes():
            o = d["orig"].get(s["id"])
            if o is None:
                continue
            s.clear()
            s.update(json.loads(json.dumps(o)))
            ez.move_shape(s, dx, dy)
        self._touch_shapes(self._picked_shapes())

    def _release_drag(self, pt: QPointF, mods: int) -> None:
        if not self._drag.get("moved"):
            self._undo.pop()

    def _move_handle(self, pt: QPointF, mods: int) -> None:
        d = self._drag
        s, box, h = d["shape"], d["box"], d["handle"]
        s.clear()
        s.update(json.loads(json.dumps(d["orig"])))
        if h == "rot":
            c = box.center()
            ang = math.degrees(math.atan2(pt.y() - c.y(), pt.x() - c.x())) + 90
            if mods & SHIFT:
                ang = round(ang / 15) * 15
            s["rot"] = (d["orig"].get("rot", 0) + ang) % 360 if s["type"] != "path" else ang % 360
            if s["type"] in ("path", "line"):                       # turn the points themselves
                s.pop("rot", None)
                t = QTransform().translate(c.x(), c.y()).rotate(ang).translate(-c.x(), -c.y())
                if s["type"] == "line":
                    a, b = t.map(QPointF(s["x1"], s["y1"])), t.map(QPointF(s["x2"], s["y2"]))
                    s.update(x1=a.x(), y1=a.y(), x2=b.x(), y2=b.y())
                else:
                    for sub in s["subs"]:
                        for nd in sub["nodes"]:
                            for kx, ky in (("x", "y"), ("ix", "iy"), ("ox", "oy")):
                                if kx in nd:
                                    q = t.map(QPointF(nd[kx], nd[ky]))
                                    nd[kx], nd[ky] = q.x(), q.y()
        else:
            l, t_, r, b = box.left(), box.top(), box.right(), box.bottom()
            if "l" in h:
                l = min(pt.x(), r - 1)
            if "r" in h:
                r = max(pt.x(), l + 1)
            if h.startswith("t"):
                t_ = min(pt.y(), b - 1)
            if h.startswith("b"):
                b = max(pt.y(), t_ + 1)
            if mods & SHIFT and len(h) == 2:                         # keep the shape's proportions
                k = max((r - l) / box.width(), (b - t_) / box.height())
                nw, nh = box.width() * k, box.height() * k
                if "l" in h:
                    l = r - nw
                else:
                    r = l + nw
                if h.startswith("t"):
                    t_ = b - nh
                else:
                    b = t_ + nh
            inner = ez.raw_path(dict(s, rot=0)).boundingRect()
            pad = (box.width() - inner.width()) / 2 if box.width() > inner.width() else 0
            ez.scale_shape(s, inner, QRectF(l + pad, t_ + pad, max(1, r - l - pad * 2), max(1, b - t_ - pad * 2)))
        self.doc.touch(d["layer"])
        self.changed.emit()

    def _release_handle(self, pt: QPointF, mods: int) -> None:
        pass

    def _move_rubber(self, pt: QPointF, mods: int) -> None:
        self._drag["rect"] = QRectF(self._drag["start"], pt).normalized()

    def _release_rubber(self, pt: QPointF, mods: int) -> None:
        r = self._drag.get("rect")
        if r is None or r.width() < 3 or r.height() < 3:
            return
        inside = [s["id"] for l in self.doc.layers if l["kind"] == "vector" and l["visible"] and not l["locked"] for s in l["shapes"] if r.contains(ez.shape_bounds(s))]
        self._picked = list(dict.fromkeys(self._picked + inside))

    @Slot()
    def deleteShapes(self) -> None:
        if not self._picked_shapes():
            return
        self._push("Delete shapes")
        for l in self.doc.layers:
            if "shapes" in l:
                before = len(l["shapes"])
                l["shapes"] = [s for s in l["shapes"] if s.get("id") not in self._picked]
                if len(l["shapes"]) != before:
                    self.doc.touch(l)
        self._picked = []
        self._refresh()

    @Slot(str)
    def arrange(self, how: str) -> None:
        """front, forward, backward, back: the picked shape's place among the shapes on its layer."""
        shapes = self._picked_shapes()
        if not shapes:
            return
        self._push("Arrange")
        for l in self.doc.layers:
            items = l.get("shapes")
            if not items:
                continue
            mine = [s for s in items if s.get("id") in self._picked]
            if not mine:
                continue
            rest = [s for s in items if s.get("id") not in self._picked]
            if how == "front":
                l["shapes"] = rest + mine
            elif how == "back":
                l["shapes"] = mine + rest
            else:
                for s in (mine if how == "backward" else reversed(mine)):
                    i = l["shapes"].index(s)
                    j = max(0, i - 1) if how == "backward" else min(len(l["shapes"]) - 1, i + 1)
                    l["shapes"].insert(j, l["shapes"].pop(i))
            self.doc.touch(l)
        self._refresh()

    @Slot(str)
    def align(self, edge: str) -> None:
        """left, hcenter, right, top, vcenter, bottom: to each other (2 or more) or to the canvas (one)."""
        shapes = self._picked_shapes()
        if not shapes:
            return
        self._push("Align")
        boxes = [ez.shape_bounds(s) for s in shapes]
        ref = QRectF(0, 0, self.doc.w, self.doc.h)
        if len(shapes) > 1:
            ref = boxes[0]
            for b in boxes[1:]:
                ref = ref.united(b)
        for s, b in zip(shapes, boxes):
            dx = {"left": ref.left() - b.left(), "hcenter": ref.center().x() - b.center().x(), "right": ref.right() - b.right()}.get(edge, 0)
            dy = {"top": ref.top() - b.top(), "vcenter": ref.center().y() - b.center().y(), "bottom": ref.bottom() - b.bottom()}.get(edge, 0)
            ez.move_shape(s, dx, dy)
        self._touch_shapes(shapes)
        self._refresh()

    @Slot(str)
    def combine(self, how: str) -> None:
        """union, subtract (the others from the bottom one), intersect, exclude: the picked shapes become one."""
        shapes = self._picked_shapes()
        if len(shapes) < 2:
            self.said.emit("Pick two or more shapes to combine (Shift-click adds to the picked ones).", True)
            return
        self._push({"union": "Unite", "subtract": "Subtract", "intersect": "Intersect", "exclude": "Exclude"}.get(how, "Combine"))
        layer = next(l for l in self.doc.layers if shapes[0] in l.get("shapes", []))
        order = [s for s in layer["shapes"] if s in shapes] + [s for s in shapes if s not in layer["shapes"]]
        result = ez.shape_path(order[0])
        for s in order[1:]:
            other = ez.shape_path(s)
            result = {"union": result.united, "subtract": result.subtracted, "intersect": result.intersected}.get(how, result.united)(other) if how != "exclude" \
                else result.united(other).subtracted(result.intersected(other))
        base = order[0]
        new = {"id": os.urandom(4).hex(), "type": "path", "subs": ez.path_to_subs(result.simplified()), "fill": base.get("fill", ""), "stroke": base.get("stroke", ""),
               "width": base.get("width", 0), "opacity": base.get("opacity", 1)}
        at = layer["shapes"].index(base)
        for l in self.doc.layers:
            if "shapes" in l:
                l["shapes"] = [s for s in l["shapes"] if s not in shapes]
                self.doc.touch(l)
        layer["shapes"].insert(min(at, len(layer["shapes"])), new)
        self._picked = [new["id"]]
        self._refresh()

    # --- the pen
    def _pen_shape(self):
        if self._pen is None:
            return None
        l = self.doc.layer(self._pen["layer"])
        return next((s for s in l.get("shapes", []) if s.get("id") == self._pen["id"]), None)

    def _press_pen(self, pt: QPointF, mods: int) -> None:
        shape = self._pen_shape()
        slack = 8 / max(0.05, self.zoom)
        if shape is None:
            self._push("Pen")
            layer = self._vector_target("Shapes")
            st = self.style
            shape = {"id": os.urandom(4).hex(), "type": "path", "subs": [{"nodes": [], "closed": False}], "fill": "", "stroke": st["stroke"] or "#14171C",
                     "width": max(2.0, st["width"]), "opacity": st["opacity"], "drawing": True}
            layer["shapes"].append(shape)
            self._pen = {"layer": layer["id"], "id": shape["id"]}
            self._picked = [shape["id"]]
        nodes = shape["subs"][0]["nodes"]
        if len(nodes) >= 2 and abs(pt.x() - nodes[0]["x"]) <= slack and abs(pt.y() - nodes[0]["y"]) <= slack:
            shape["subs"][0]["closed"] = True                        # back at the start: the shape closes
            if not shape.get("fill"):
                shape["fill"] = self.style["fill"]
            self.finishPen()
            return
        nodes.append({"x": pt.x(), "y": pt.y()})
        self._drag = {"kind": "pen", "node": nodes[-1], "start": pt}
        self.doc.touch(self.doc.layer(self._pen["layer"]))
        self.changed.emit()

    def _move_pen(self, pt: QPointF, mods: int) -> None:
        """Dragging after a click pulls out the curve's handles (mirrored either side of the point)."""
        nd = self._drag["node"]
        dx, dy = pt.x() - nd["x"], pt.y() - nd["y"]
        if math.hypot(dx, dy) < 1:
            return
        nd["ox"], nd["oy"] = nd["x"] + dx, nd["y"] + dy
        nd["ix"], nd["iy"] = nd["x"] - dx, nd["y"] - dy
        self.doc.touch(self.doc.layer(self._pen["layer"]))

    def _release_pen(self, pt: QPointF, mods: int) -> None:
        self._drag = None

    @Slot()
    def finishPen(self) -> None:
        shape = self._pen_shape()
        if shape is None:
            self._pen = None
            return
        shape.pop("drawing", None)
        layer = self.doc.layer(self._pen["layer"])
        if len(shape["subs"][0]["nodes"]) < 2:
            layer["shapes"] = [s for s in layer["shapes"] if s is not shape]
            self._picked = []
        self._pen = None
        self.doc.touch(layer)
        self._refresh()

    # --- text
    def _press_text(self, pt: QPointF, mods: int) -> None:
        hit = self._shape_at(pt)
        if hit and hit[1]["type"] == "text":
            self._picked = [hit[1]["id"]]
            self.doc.active = hit[0]["id"]
            self.editText.emit(hit[1]["text"], hit[1]["x"], hit[1]["y"])
            self._refresh()
            return
        self._push("Text")
        layer = self._vector_target("Text")
        s = {"id": os.urandom(4).hex(), "type": "text", "x": pt.x(), "y": pt.y(), "text": "", "fill": self.fg, "stroke": "", "width": 0, "opacity": 1.0, **self.text}
        layer["shapes"].append(s)
        self._picked = [s["id"]]
        self.doc.touch(layer)
        self._refresh()
        self.editText.emit("", pt.x(), pt.y())

    @Slot(str)
    def setText(self, text: str) -> None:
        shapes = [s for s in self._picked_shapes() if s["type"] == "text"]
        if shapes:
            shapes[-1]["text"] = text
            self._touch_shapes(shapes)

    @Slot()
    def doneText(self) -> None:
        """Leaving the text box: an empty text shape goes away."""
        for l in self.doc.layers if self.doc else []:
            if "shapes" in l:
                before = len(l["shapes"])
                l["shapes"] = [s for s in l["shapes"] if not (s["type"] == "text" and not s.get("text", "").strip())]
                if len(l["shapes"]) != before:
                    self._picked = [i for i in self._picked if any(s["id"] == i for s in l["shapes"])]
                    self.doc.touch(l)
        self._refresh()

    @Slot()
    def escape(self) -> None:
        if self._xform is not None:
            self.cancelTransform()
        elif self._node_sel is not None:
            self._node_sel = None
            self._refresh()
        elif self._pen is not None:
            self.finishPen()
        elif self._crop is not None:
            self.cancelCrop()
        elif self._picked:
            self._picked = []
            self._refresh()
        elif self.doc and self.doc.selection is not None:
            self.deselect()

    @Slot(float, float)
    def nudge(self, dx: float, dy: float) -> None:
        """Arrow keys: move the picked shapes (or the layer) a pixel; with Shift, ten."""
        if not self.doc:
            return
        shapes = self._picked_shapes()
        self._push("Nudge")
        if shapes:
            for s in shapes:
                ez.move_shape(s, dx, dy)
            self._touch_shapes(shapes)
        else:
            self._drag = None
            self._press_move(QPointF(0, 0), 0)
            if self._drag:
                self._undo.pop()
                self._drag["dx"], self._drag["dy"] = dx, dy
                self._release_move(QPointF(dx, dy), 0)
            self._drag = None
        self._refresh()

    # ------------------------------------------------------------------ free transform (pixels)
    def _xform_matrix(self, visual: bool = False) -> QTransform:
        x = self._xform
        t = QTransform().translate(x["cx"], x["cy"]).rotate(x["rot"])
        if visual:
            return t
        w, h = x["floating"].width(), x["floating"].height()
        return t.scale(x["sx"] * (-1 if x["flipx"] else 1), x["sy"] * (-1 if x["flipy"] else 1)).translate(-w / 2, -h / 2)

    def _xform_handles(self) -> dict:
        x = self._xform
        hw, hh = x["floating"].width() * x["sx"] / 2, x["floating"].height() * x["sy"] / 2
        t = self._xform_matrix(True)
        pts = {name: t.map(QPointF(sx * hw, sy * hh)) for name, sx, sy in
               (("tl", -1, -1), ("t", 0, -1), ("tr", 1, -1), ("r", 1, 0), ("br", 1, 1), ("b", 0, 1), ("bl", -1, 1), ("l", -1, 0))}
        pts["rot"] = t.map(QPointF(0, -hh - 28 / max(0.05, self.zoom)))
        return pts

    def _xform_image(self) -> QImage:
        x = self._xform
        out = x["rest"].copy()
        p = QPainter(out)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setTransform(self._xform_matrix())
        p.drawImage(0, 0, x["floating"])
        p.end()
        return out

    def _begin_transform(self) -> bool:
        l = self.doc.layer()
        if l["kind"] == "smart" and not l["locked"]:
            self._push("Transform")
            pl = l["place"]
            self._xform = {"layer": l, "floating": l["source"], "rest": ez.new_image(self.doc.w, self.doc.h), "smart": True, "sel": None,
                           "cx": pl["cx"], "cy": pl["cy"], "sx": pl["sx"], "sy": pl["sy"], "rot": pl.get("rot", 0.0),
                           "flipx": bool(pl.get("flipx")), "flipy": bool(pl.get("flipy"))}
            self._live = (l["id"], lambda img: self._xform_image())
            self.changed.emit()
            return True
        if l["kind"] != "pixel" or l["locked"]:
            self.said.emit("Free transform works on pixel layers; shapes have their own handles with Select.", True)
            return False
        sel = self.doc.selection
        floating = self._clip(l["image"]) if sel is not None else QImage(l["image"])
        a = ez.alpha_of(floating)
        ys, xs = np.nonzero(a > 0)
        if not len(xs):
            self.said.emit("There's nothing there to transform.", True)
            return False
        self._push("Transform")
        box = QRect(int(xs.min()), int(ys.min()), int(xs.max() - xs.min() + 1), int(ys.max() - ys.min() + 1))
        rest = l["image"].copy()
        p = QPainter(rest)
        p.setCompositionMode(ez.CM.CompositionMode_DestinationOut if sel is not None else ez.CM.CompositionMode_Clear)
        if sel is not None:
            p.drawImage(0, 0, sel)
        else:
            p.fillRect(rest.rect(), Qt.GlobalColor.transparent)
        p.end()
        self._xform = {"layer": l, "floating": floating.copy(box), "rest": rest, "cx": box.x() + box.width() / 2, "cy": box.y() + box.height() / 2,
                       "sx": 1.0, "sy": 1.0, "rot": 0.0, "flipx": False, "flipy": False, "sel": QImage(sel).copy(box) if sel is not None else None}
        self._live = (l["id"], lambda img: self._xform_image())
        self.changed.emit()
        return True

    @Slot()
    def startTransform(self) -> None:
        """Ctrl+T: free transform the active pixel layer (or what's selected on it)."""
        if not self.doc:
            return
        if self.tool != "transform":
            self.tool = "transform"
        if self._xform is None:
            self._begin_transform()
        self._refresh()

    @Slot()
    def applyTransform(self) -> None:
        x = self._xform
        if x is None:
            return
        if x.get("smart"):
            x["layer"]["place"] = {k: x[k] for k in ("cx", "cy", "sx", "sy", "rot", "flipx", "flipy")}
            self._xform, self._live = None, None
            self.doc.touch(x["layer"])
            self._refresh()
            return
        x["layer"]["image"] = self._xform_image()
        if x["sel"] is not None:                                     # the selection keeps its new shape too
            moved = ez.new_image(self.doc.w, self.doc.h)
            p = QPainter(moved)
            p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            p.setTransform(self._xform_matrix())
            p.drawImage(0, 0, x["sel"])
            p.end()
            self.doc.selection = moved
            self._selection_changed()
        self._xform, self._live = None, None
        self.doc.touch(x["layer"])
        self._refresh()

    @Slot()
    def cancelTransform(self) -> None:
        if self._xform is None:
            return
        self._xform, self._live = None, None
        if self._undo:
            _, snap = self._undo.pop()
            self.doc.restore(snap)
            self._selection_changed()
        self._refresh()

    @Slot(str)
    def flipTransform(self, axis: str) -> None:
        if self._xform is not None:
            self._xform["flipx" if axis == "x" else "flipy"] ^= True
            self._refresh()

    @Slot(float, float, float)
    def setTransform(self, wpercent: float, hpercent: float, angle: float) -> None:
        if self._xform is not None:
            self._xform.update(sx=max(0.01, wpercent / 100), sy=max(0.01, hpercent / 100), rot=angle % 360)
            self._refresh()

    def _press_transform(self, pt: QPointF, mods: int) -> None:
        if self._xform is None and not self._begin_transform():
            return
        x = self._xform
        slack = 8 / max(0.05, self.zoom)
        handles = self._xform_handles()
        which = next((n for n, hp in handles.items() if abs(pt.x() - hp.x()) <= slack and abs(pt.y() - hp.y()) <= slack), None)
        if which is None:
            poly = QPolygonF([handles[k] for k in ("tl", "tr", "br", "bl")])
            which = "move" if poly.containsPoint(pt, Qt.FillRule.OddEvenFill) else "rot"
        self._drag = {"kind": "xform", "what": which, "start": pt, "orig": {k: x[k] for k in ("cx", "cy", "sx", "sy", "rot")}}

    def _move_xform(self, pt: QPointF, mods: int) -> None:
        d, x = self._drag, self._xform
        o = d["orig"]
        w, h = x["floating"].width(), x["floating"].height()
        if d["what"] == "move":
            dx, dy = pt.x() - d["start"].x(), pt.y() - d["start"].y()
            if self.snap and not mods & SHIFT:
                bw, bh = abs(w * o["sx"]), abs(h * o["sy"])
                dx, dy = self._snap_box(QRectF(o["cx"] - bw / 2, o["cy"] - bh / 2, bw, bh), dx, dy)
            x["cx"], x["cy"] = o["cx"] + dx, o["cy"] + dy
        elif d["what"] == "rot":
            a0 = math.atan2(d["start"].y() - o["cy"], d["start"].x() - o["cx"])
            a1 = math.atan2(pt.y() - o["cy"], pt.x() - o["cx"])
            ang = o["rot"] + math.degrees(a1 - a0)
            x["rot"] = round(ang / 15) * 15 if mods & SHIFT else ang
        else:
            signs = {"tl": (-1, -1), "t": (0, -1), "tr": (1, -1), "r": (1, 0), "br": (1, 1), "b": (0, 1), "bl": (-1, 1), "l": (-1, 0)}[d["what"]]
            frame = QTransform().translate(o["cx"], o["cy"]).rotate(o["rot"])
            inv, _ = frame.inverted()
            lp = inv.map(pt)
            W0, H0 = w * o["sx"], h * o["sy"]
            centred = bool(mods & ALT)
            fixed = QPointF(0, 0) if centred else QPointF(-signs[0] * W0 / 2, -signs[1] * H0 / 2)
            k = 2 if centred else 1
            nw = max(1.0, (lp.x() - fixed.x()) * signs[0] * k) if signs[0] else W0
            nh = max(1.0, (lp.y() - fixed.y()) * signs[1] * k) if signs[1] else H0
            if signs[0] and signs[1] and not mods & SHIFT:           # corners keep the proportions (Shift lets go)
                f = max(nw / W0, nh / H0)
                nw, nh = W0 * f, H0 * f
            c = QPointF(0 if centred or not signs[0] else fixed.x() + signs[0] * nw / 2, 0 if centred or not signs[1] else fixed.y() + signs[1] * nh / 2)
            wc = frame.map(c)
            x.update(cx=wc.x(), cy=wc.y(), sx=nw / w, sy=nh / h)
        self.changed.emit()

    def _release_xform(self, pt: QPointF, mods: int) -> None:
        pass

    # ------------------------------------------------------------------ clone and heal
    @Slot(bool)
    def setHealSpot(self, on: bool) -> None:
        self.heal_spot = bool(on)
        self.changed.emit()

    def _press_clone(self, pt: QPointF, mods: int, heal: bool = False) -> None:
        if mods & ALT:
            self._clone_src, self._clone_off = pt, None
            self.said.emit("Copying from here. Now paint where it should go.", False)
            self._refresh()
            return
        spot = heal and self.heal_spot
        if self._clone_src is None and not spot:
            self.said.emit("Alt-click where to copy from first.", True)
            return
        target = self._target()
        if target is None:
            return
        layer, which = target
        self._push("Heal" if heal else "Clone")
        if spot:
            off = (self.brush["size"] * 1.6, 0.0)
        else:
            if self._clone_off is None:
                self._clone_off = (self._clone_src.x() - pt.x(), self._clone_src.y() - pt.y())
            off = self._clone_off
        stroke = ez.new_image(self.doc.w, self.doc.h)
        painter = QPainter(stroke)
        painter.setOpacity(self.brush["flow"])
        d = {"kind": "clone", "heal": heal, "spot": spot, "layer": layer, "which": which, "base": QImage(layer[which]), "off": off,
             "stroke": stroke, "painter": painter, "dab": self._dab_image(True), "last": (pt.x(), pt.y()), "carry": 0.0, "erase": False}
        self._stamp(d, pt.x(), pt.y())
        self._drag = d
        self._live = (layer["id"], lambda img, d=d: self._clone_result(d, False))

    def _press_heal(self, pt: QPointF, mods: int) -> None:
        self._press_clone(pt, mods, heal=True)

    def _move_clone(self, pt: QPointF, mods: int) -> None:
        self._stroke_to(self._drag, pt.x(), pt.y())

    def _shifted_base(self, d: dict, off) -> QImage:
        src = ez.new_image(self.doc.w, self.doc.h)
        p = QPainter(src)
        p.drawImage(QPointF(-off[0], -off[1]), d["base"])
        p.end()
        return src

    def _clone_result(self, d: dict, final: bool) -> QImage:
        off = d["off"]
        if final and d["spot"] and d.get("box") is not None:         # spot healing: find the best nearby patch to borrow
            box = d["box"]
            rgba = ez.image_to_array(d["base"])
            sx, sy = ez.best_spot_source(rgba, box.center().x(), box.center().y(), max(box.width(), box.height()))
            off = (sx - box.center().x(), sy - box.center().y())
        src = self._shifted_base(d, off)
        if final and d["heal"] and d.get("box") is not None:
            pad = int(self.brush["size"])
            r = d["box"].toAlignedRect().adjusted(-pad, -pad, pad, pad).intersected(QRect(0, 0, self.doc.w, self.doc.h))
            if r.width() > 2 and r.height() > 2:
                dst = ez.image_to_array(d["base"].copy(r)).astype(np.float32)
                sa = ez.image_to_array(src.copy(r)).astype(np.float32)
                healed = ez.heal_patch(dst, sa, self.brush["size"] / 3)
                healed[..., 3] = np.maximum(dst[..., 3], sa[..., 3])
                p = QPainter(src)
                p.setCompositionMode(ez.CM.CompositionMode_Source)
                p.drawImage(r.topLeft(), ez.array_to_image((healed + 0.5).astype(np.uint8)))
                p.end()
        p = QPainter(src)
        p.setCompositionMode(ez.CM.CompositionMode_DestinationIn)
        p.drawImage(0, 0, d["stroke"])
        p.end()
        return self._merge(d["base"] if final else d["base"], src, False, self.opacity)

    def _release_clone(self, pt: QPointF, mods: int) -> None:
        d = self._drag
        self._stroke_to(d, pt.x(), pt.y())
        d["painter"].end()
        d["layer"][d["which"]] = self._clone_result(d, True)
        self.doc.touch(d["layer"])

    # ------------------------------------------------------------------ editing points
    def _node_ref(self):
        if not self._node_sel:
            return None
        sid, si, ni = self._node_sel
        shape = next((s for l in self.doc.layers for s in l.get("shapes", []) if s.get("id") == sid), None)
        try:
            return shape["subs"][si]["nodes"][ni]
        except (TypeError, KeyError, IndexError):
            return None

    def _as_path(self, s: dict) -> bool:
        """Rectangles, ellipses, stars and lines become paths the first time their points are edited."""
        if s["type"] == "path":
            return True
        if s["type"] == "text":
            self.said.emit("Text is edited as text. To change its letters' shapes, use Arrange › Convert to Outlines first.", True)
            return False
        subs = ez.path_to_subs(ez.shape_path(s))
        if s["type"] == "line":
            subs = [{"nodes": [{"x": s["x1"], "y": s["y1"]}, {"x": s["x2"], "y": s["y2"]}], "closed": False}]
        for k in ("x", "y", "w", "h", "radius", "rot", "points", "inner", "x1", "y1", "x2", "y2"):
            s.pop(k, None)
        s.update(type="path", subs=subs)
        return True

    def _press_nodes(self, pt: QPointF, mods: int) -> None:
        slack = 7 / max(0.05, self.zoom)
        shapes = self._picked_shapes()
        s = shapes[0] if len(shapes) == 1 else None
        if s is not None and s["type"] == "path":
            for si, sub in enumerate(s["subs"]):                     # a handle first, then a point
                for ni, nd in enumerate(sub["nodes"]):
                    for side in ("i", "o"):
                        if f"{side}x" in nd and math.hypot(pt.x() - nd[f"{side}x"], pt.y() - nd[f"{side}y"]) <= slack:
                            self._push("Edit points")
                            self._node_sel = (s["id"], si, ni)
                            self._drag = {"kind": "nodehandle", "side": side, "shape": s, "start": pt}
                            return
            for si, sub in enumerate(s["subs"]):
                for ni, nd in enumerate(sub["nodes"]):
                    if math.hypot(pt.x() - nd["x"], pt.y() - nd["y"]) <= slack:
                        self._push("Edit points")
                        self._node_sel = (s["id"], si, ni)
                        self._drag = {"kind": "node", "shape": s, "start": pt, "orig": dict(nd)}
                        self.changed.emit()
                        return
            hit = self._segment_at(s, pt, slack)
            if hit is not None:                                      # a click on the line adds a point there
                self._push("Add point")
                si, ni, t = hit
                self._split(s, si, ni, t)
                self._node_sel = (s["id"], si, ni + 1)
                self._touch_shapes([s])
                self._refresh()
                return
        hit = self._shape_at(pt)
        if hit:
            if hit[1]["type"] != "path":
                self._push("Edit points")
                if not self._as_path(hit[1]):
                    self._undo.pop()
                    return
                self._touch_shapes([hit[1]])
            self._picked = [hit[1]["id"]]
            self.doc.active = hit[0]["id"]
            self._node_sel = None
        else:
            self._picked, self._node_sel = [], None
        self._refresh()

    def _segment_at(self, s: dict, pt: QPointF, slack: float):
        best = None
        for si, sub in enumerate(s["subs"]):
            nodes = sub["nodes"]
            pairs = list(range(len(nodes) - 1)) + ([len(nodes) - 1] if sub.get("closed") and len(nodes) > 1 else [])
            for ni in pairs:
                a, b = nodes[ni], nodes[(ni + 1) % len(nodes)]
                for k in range(1, 40):
                    t = k / 40
                    q = self._bez(a, b, t)
                    dist = math.hypot(q[0] - pt.x(), q[1] - pt.y())
                    if dist <= slack and (best is None or dist < best[0]):
                        best = (dist, si, ni, t)
        return best[1:] if best else None

    @staticmethod
    def _bez(a: dict, b: dict, t: float):
        p0 = (a["x"], a["y"])
        p1 = (a.get("ox", a["x"]), a.get("oy", a["y"]))
        p2 = (b.get("ix", b["x"]), b.get("iy", b["y"]))
        p3 = (b["x"], b["y"])
        u = 1 - t
        return tuple(u ** 3 * p0[i] + 3 * u * u * t * p1[i] + 3 * u * t * t * p2[i] + t ** 3 * p3[i] for i in (0, 1))

    def _split(self, s: dict, si: int, ni: int, t: float) -> None:
        """Split the curve after point ni at t (de Casteljau), so the shape doesn't change."""
        nodes = s["subs"][si]["nodes"]
        a, b = nodes[ni], nodes[(ni + 1) % len(nodes)]
        p0, p1 = (a["x"], a["y"]), (a.get("ox", a["x"]), a.get("oy", a["y"]))
        p2, p3 = (b.get("ix", b["x"]), b.get("iy", b["y"])), (b["x"], b["y"])

        def lerp(m, n):
            return (m[0] + (n[0] - m[0]) * t, m[1] + (n[1] - m[1]) * t)
        q0, q1, q2 = lerp(p0, p1), lerp(p1, p2), lerp(p2, p3)
        r0, r1 = lerp(q0, q1), lerp(q1, q2)
        m = lerp(r0, r1)
        curved = "ox" in a or "ix" in b
        new = {"x": m[0], "y": m[1]}
        if curved:
            a["ox"], a["oy"] = q0
            new.update(ix=r0[0], iy=r0[1], ox=r1[0], oy=r1[1])
            b["ix"], b["iy"] = q2
        nodes.insert(ni + 1, new)

    def _move_node(self, pt: QPointF, mods: int) -> None:
        d = self._drag
        nd, o = self._node_ref(), d["orig"]
        if nd is None:
            return
        dx, dy = pt.x() - d["start"].x(), pt.y() - d["start"].y()
        for kx, ky in (("x", "y"), ("ix", "iy"), ("ox", "oy")):
            if kx in o:
                nd[kx], nd[ky] = o[kx] + dx, o[ky] + dy
        self._touch_shapes([d["shape"]])

    def _move_nodehandle(self, pt: QPointF, mods: int) -> None:
        d = self._drag
        nd = self._node_ref()
        if nd is None:
            return
        side, other = d["side"], "o" if d["side"] == "i" else "i"
        nd[f"{side}x"], nd[f"{side}y"] = pt.x(), pt.y()
        if not mods & ALT and not nd.get("corner") and f"{other}x" in nd:   # smooth points keep their handles in line
            length = math.hypot(nd[f"{other}x"] - nd["x"], nd[f"{other}y"] - nd["y"])
            vx, vy = nd["x"] - pt.x(), nd["y"] - pt.y()
            n = math.hypot(vx, vy) or 1
            nd[f"{other}x"], nd[f"{other}y"] = nd["x"] + vx / n * length, nd["y"] + vy / n * length
        if mods & ALT:
            nd["corner"] = True
        self._touch_shapes([d["shape"]])

    def _release_node(self, pt: QPointF, mods: int) -> None:
        pass

    _release_nodehandle = _release_node

    @Slot()
    def deleteNode(self) -> None:
        if not self._node_sel:
            return
        sid, si, ni = self._node_sel
        s = next((x for x in self._picked_shapes() if x["id"] == sid), None)
        if s is None or len(s["subs"][si]["nodes"]) <= 2:
            self.said.emit("A path needs at least two points.", True)
            return
        self._push("Delete point")
        s["subs"][si]["nodes"].pop(ni)
        self._node_sel = None
        self._touch_shapes([s])
        self._refresh()

    @Slot()
    def toggleSmooth(self) -> None:
        """A smooth point gets handles in line; a corner point loses them."""
        nd = self._node_ref()
        if nd is None:
            return
        sid, si, ni = self._node_sel
        s = next(x for x in self._picked_shapes() if x["id"] == sid)
        self._push("Point type")
        if "ix" in nd or "ox" in nd:
            for k in ("ix", "iy", "ox", "oy", "corner"):
                nd.pop(k, None)
        else:
            nodes = s["subs"][si]["nodes"]
            prev, nxt = nodes[(ni - 1) % len(nodes)], nodes[(ni + 1) % len(nodes)]
            vx, vy = nxt["x"] - prev["x"], nxt["y"] - prev["y"]
            n = math.hypot(vx, vy) or 1
            k = min(math.hypot(nxt["x"] - nd["x"], nxt["y"] - nd["y"]), math.hypot(prev["x"] - nd["x"], prev["y"] - nd["y"])) / 3
            nd.update(ix=nd["x"] - vx / n * k, iy=nd["y"] - vy / n * k, ox=nd["x"] + vx / n * k, oy=nd["y"] + vy / n * k)
            nd.pop("corner", None)
        self._touch_shapes([s])
        self._refresh()

    @Slot()
    def outline(self) -> None:
        """Convert to Outlines: text (and any shape) becomes a path whose points can be edited."""
        shapes = self._picked_shapes()
        if not shapes:
            return
        self._push("Convert to outlines")
        for s in shapes:
            path = ez.shape_path(s)
            for k in [k for k in s if k not in ("id", "fill", "stroke", "width", "opacity", "fill2", "gangle", "gkind")]:
                s.pop(k)
            s.update(type="path", subs=ez.path_to_subs(path))
        self._touch_shapes(shapes)
        self._refresh()

    # ------------------------------------------------------------------ curves
    @Slot(str, "QVariantList")
    def setCurve(self, channel: str, points) -> None:
        """One channel's curve (rgb, r, g or b) on a Curves adjustment layer: points as [x, y], both 0..1."""
        l = self.doc.layer() if self.doc else None
        if not l or l.get("adjust") != "curves" or channel not in ("rgb", "r", "g", "b"):
            return
        pts = []
        for p in points:
            p = list(p) if not isinstance(p, dict) else [p.get("x", 0), p.get("y", 0)]
            pts.append([max(0.0, min(1.0, float(p[0]))), max(0.0, min(1.0, float(p[1])))])
        pts.sort()
        curves = l.setdefault("params", {}).setdefault("curves", dict(ez.ADJUST_DEFAULTS["curves"]["curves"]))
        curves[channel] = pts
        self.doc.touch(l)
        self._refresh()

    @Slot(str, result="QVariantList")
    def curveSamples(self, channel: str):
        """64 points along the curve, for drawing it."""
        l = self.doc.layer() if self.doc else None
        pts = ((l.get("params") or {}).get("curves") or ez.ADJUST_DEFAULTS["curves"]["curves"]).get(channel) if l else None
        lut = ez.curve_lut(pts or [[0, 0], [1, 1]])
        return [float(lut[int(i * 255 / 63)]) for i in range(64)]


    # ================================================================== round four
    # ------------------------------------------------------------------ layer groups
    def _siblings(self, layer: dict) -> list:
        g = layer.get("group")
        return [l for l in self.doc.layers if l.get("group") == g]

    def _subtree(self, layer: dict) -> list:
        """A layer, or a group with everything in it, in list order."""
        if layer["kind"] != "group":
            return [layer]
        a, b = more.span(self.doc.layers, layer["id"])
        return self.doc.layers[a:b + 1]

    def _place_above(self, items: list, ref: dict, group) -> None:
        """Take items out and put them just above ref (a layer, or a whole group), in `group`."""
        ids = {l["id"] for l in items}
        rest = [l for l in self.doc.layers if l["id"] not in ids]
        top = more.span(rest, ref["id"])[1] if ref["kind"] == "group" else next(i for i, l in enumerate(rest) if l["id"] == ref["id"])
        items[-1]["group"] = group
        self.doc.layers = more.normalize(rest[:top + 1] + items + rest[top + 1:])

    def _place_below(self, items: list, ref: dict, group) -> None:
        ids = {l["id"] for l in items}
        rest = [l for l in self.doc.layers if l["id"] not in ids]
        first = more.span(rest, ref["id"])[0] if ref["kind"] == "group" else next(i for i, l in enumerate(rest) if l["id"] == ref["id"])
        items[-1]["group"] = group
        self.doc.layers = more.normalize(rest[:first] + items + rest[first:])

    @Slot()
    def groupLayer(self) -> None:
        """Ctrl+G: put the active layer (or group) in a new group of its own, where it was."""
        if not self.doc:
            return
        l = self.doc.layer()
        self._push("Group")
        g = ez.new_layer("group", f"Group {self._count('group')}")
        g["group"] = l.get("group")
        items = self._subtree(l)
        at = self.doc.index(items[-1]["id"])
        self.doc.layers.insert(at + 1, g)
        l["group"] = g["id"]
        self.doc.layers = more.normalize(self.doc.layers)
        self.doc.active = g["id"]
        self.doc.touch()
        self._refresh()

    @Slot()
    def ungroup(self) -> None:
        """Ctrl+Shift+G: the group goes; what was in it stays where it was."""
        l = self.doc.layer() if self.doc else None
        if not l or l["kind"] != "group":
            return
        self._push("Ungroup")
        for x in self.doc.layers:
            if x.get("group") == l["id"]:
                x["group"] = l.get("group")
        kids = [x for x in self._subtree(l) if x is not l]
        self.doc.layers = more.normalize([x for x in self.doc.layers if x is not l])
        self.doc.active = kids[-1]["id"] if kids else self.doc.layers[-1]["id"]
        self.doc.touch()
        self._refresh()

    @Slot(str)
    def toggleOpen(self, ident: str) -> None:
        l = self.doc.layer(ident) if self.doc else None
        if l and l["kind"] == "group":
            l["open"] = not l.get("open", True)
            self.changed.emit()

    # ------------------------------------------------------------------ layer styles
    @Slot()
    def markFx(self) -> None:
        if self.doc:
            self._push("Layer style")

    @Slot(str, str, "QVariant")
    def setFx(self, key: str, prop: str, value) -> None:
        """One setting of one style of the active layer (call markFx first for one undo step per change)."""
        l = self.doc.layer() if self.doc else None
        if not l or key not in more.STYLES or l["kind"] == "adjust":
            return
        if hasattr(value, "toVariant"):
            value = value.toVariant()
        cur = more.STYLES[key]
        if prop not in cur or prop == "name":
            return
        if prop == "colour":
            value = _hex(QColor(value))
        elif prop == "on":
            value = bool(value)
        elif prop == "where":
            value = value if value in ("outside", "inside", "centre") else "outside"
        else:
            value = float(value)
        import time as _time
        mark = (l["id"], key, prop)
        last = getattr(self, "_fx_mark", None)
        if not last or last[0] != mark or _time.monotonic() - last[1] > 1.5 or prop in ("on", "where", "colour"):
            self._push("Layer style")                               # one undo step for a whole drag of one slider
        self._fx_mark = (mark, _time.monotonic())
        fx = l.setdefault("fx", {})
        st = fx.setdefault(key, {})
        st[prop] = value
        if prop != "on" and not st.get("on"):
            st["on"] = True                                     # changing a style's setting turns it on
        self.doc.touch(l)
        self._refresh()

    @Slot()
    def clearFx(self) -> None:
        l = self.doc.layer() if self.doc else None
        if l and l.get("fx"):
            self._push("Clear styles")
            l.pop("fx", None)
            self.doc.touch(l)
            self._refresh()

    @Property("QVariantMap", notify=changed)
    def styles(self):
        if not self.doc:
            return {}
        l = self.doc.layer()
        return {k: dict(more.style_of(l, k), name=v["name"]) for k, v in more.STYLES.items()}

    # ------------------------------------------------------------------ smart objects
    @Slot()
    def convertToSmart(self) -> None:
        """The active pixel or shape layer becomes a smart object: its pixels kept as they are, so it can be made
        smaller and bigger again, turned and filtered without losing anything."""
        l = self.doc.layer() if self.doc else None
        if not l or l["kind"] not in ("pixel", "vector"):
            self.said.emit("Pixel and shape layers can become smart objects.", True)
            return
        img = self.doc.layer_image(dict(l, mask=None))
        a = ez.alpha_of(img)
        ys, xs = np.nonzero(a > 0)
        if not len(xs):
            self.said.emit("There's nothing on that layer yet.", True)
            return
        self._push("Smart object")
        box = QRect(int(xs.min()), int(ys.min()), int(xs.max() - xs.min() + 1), int(ys.max() - ys.min() + 1))
        src = img.copy(box)
        l.pop("image", None)
        l.pop("shapes", None)
        l.update(kind="smart", source=src, place=more.smart_place(src, box.x(), box.y()), sfilters=[])
        self._picked = []
        self.doc.touch(l)
        self._refresh()

    @Slot(str)
    def placeFile(self, path: str) -> None:
        """Bring a picture in as a smart object, fitted inside the canvas."""
        if not self.doc:
            return
        img = QImage(path)
        if img.isNull():
            self.said.emit("That picture couldn't be read.", True)
            return
        img = img.convertToFormat(ez.FMT)
        self._push("Place")
        l = ez.new_layer("pixel", Path(path).stem, 1, 1)
        l.pop("image", None)
        k = min(1.0, self.doc.w * 0.8 / img.width(), self.doc.h * 0.8 / img.height())
        place = more.smart_place(img, (self.doc.w - img.width()) / 2, (self.doc.h - img.height()) / 2)
        place.update(sx=k, sy=k)
        l.update(kind="smart", source=img, place=place, sfilters=[])
        self._insert(l)
        self._refresh()

    @Slot(int)
    def toggleSmartFilter(self, k: int) -> None:
        l = self.doc.layer() if self.doc else None
        if l and l["kind"] == "smart" and 0 <= k < len(l.get("sfilters") or []):
            self._push("Smart filter")
            l["sfilters"][k]["on"] = not l["sfilters"][k].get("on", True)
            self.doc.touch(l)
            self._refresh()

    @Slot(int)
    def removeSmartFilter(self, k: int) -> None:
        l = self.doc.layer() if self.doc else None
        if l and l["kind"] == "smart" and 0 <= k < len(l.get("sfilters") or []):
            self._push("Remove filter")
            l["sfilters"].pop(k)
            self.doc.touch(l)
            self._refresh()

    @Slot(int, float)
    def setSmartFilter(self, k: int, amount: float) -> None:
        l = self.doc.layer() if self.doc else None
        if l and l["kind"] == "smart" and 0 <= k < len(l.get("sfilters") or []):
            l["sfilters"][k]["amount"] = max(0.0, min(1.0, float(amount)))
            self.doc.touch(l)
            self._refresh()

    # ------------------------------------------------------------------ the effect brushes and liquify
    @Slot(str, "QVariant")
    def setRetouch(self, key: str, value) -> None:
        if key == "mode" and value in ("dodge", "burn", "sponge", "soften", "sharpen"):
            self.retouch = value
        elif key == "range" and value in ("shadows", "mid", "highlights"):
            self.retouch_range = value
        elif key == "strength":
            self.retouch_strength = max(0.02, min(1.0, float(value)))
        elif key == "liquify" and value in more.LIQUIFY:
            self.liquify_mode = value
        elif key == "liquifyStrength":
            self.liquify_strength = max(0.05, min(1.0, float(value)))
        elif key == "smudge":
            self.smudge_strength = max(0.05, min(1.0, float(value)))
        self.changed.emit()

    def _pixels_target(self, what: str):
        target = self._target()
        if target is None or target[1] != "image":
            l = self.doc.layer()
            if not l["locked"] and l["kind"] not in ("group", "smart"):
                self.said.emit(f"The {what} works on pixel layers. Pick one (or rasterise this one).", True)
            return None
        return target[0]

    def _press_dodge(self, pt: QPointF, mods: int) -> None:
        layer = self._pixels_target(TOOL_NAMES["dodge"].lower())
        if layer is None:
            return
        self._push({"dodge": "Dodge", "burn": "Burn", "sponge": "Sponge", "soften": "Soften", "sharpen": "Sharpen"}[self.retouch])
        stroke = ez.new_image(self.doc.w, self.doc.h)
        painter = QPainter(stroke)
        painter.setOpacity(self.brush["flow"])
        base = layer["image"]
        effect = more.effect_of(base, self.retouch, self.retouch_strength, self.retouch_range)
        d = {"kind": "dodge", "layer": layer, "which": "image", "stroke": stroke, "painter": painter, "erase": False, "dab": self._dab_image(True),
             "last": (pt.x(), pt.y()), "carry": 0.0, "base": base, "effect": effect}
        self._stamp(d, pt.x(), pt.y())
        self._drag = d
        self._live = (layer["id"], lambda img, d=d: self._retouched(d))

    def _retouched(self, d: dict) -> QImage:
        out = d["base"].copy()
        top = d["effect"].copy()
        p = QPainter(top)
        p.setCompositionMode(ez.CM.CompositionMode_DestinationIn)
        p.drawImage(0, 0, self._clip(d["stroke"]))
        p.end()
        p = QPainter(out)
        p.setCompositionMode(ez.CM.CompositionMode_SourceAtop)
        p.drawImage(0, 0, top)
        p.end()
        return out

    def _move_dodge(self, pt: QPointF, mods: int) -> None:
        self._stroke_to(self._drag, pt.x(), pt.y())

    def _release_dodge(self, pt: QPointF, mods: int) -> None:
        d = self._drag
        self._stroke_to(d, pt.x(), pt.y())
        d["painter"].end()
        d["layer"]["image"] = more.blend_by(d["base"], d["effect"], d["stroke"], self.doc.selection)
        self.doc.touch(d["layer"])

    def _press_smudge(self, pt: QPointF, mods: int) -> None:
        layer = self._pixels_target("smudge brush")
        if layer is None:
            return
        self._push("Smudge")
        arr = more._arr(layer["image"])
        sel = (self.doc.selection_alpha().astype(np.float32) / 255) if self.doc.selection is not None else None
        d = {"kind": "smudge", "layer": layer, "arr": arr, "spot": more.soft_spot(self.brush["size"] / 2, self.brush["hardness"]), "carried": None,
             "last": (pt.x(), pt.y()), "sel": sel, "img": layer["image"]}
        d["carried"] = more.smudge_dab(arr, None, pt.x(), pt.y(), d["spot"], self.smudge_strength, sel)
        self._drag = d
        self._live = (layer["id"], lambda img, d=d: d["img"])

    def _move_smudge(self, pt: QPointF, mods: int) -> None:
        d = self._drag
        lx, ly = d["last"]
        step = max(1.0, self.brush["size"] * 0.08)
        dist = math.hypot(pt.x() - lx, pt.y() - ly)
        n = int(dist // step)
        for i in range(1, n + 1):
            t = i * step / dist
            d["carried"] = more.smudge_dab(d["arr"], d["carried"], lx + (pt.x() - lx) * t, ly + (pt.y() - ly) * t, d["spot"], self.smudge_strength, d["sel"])
        if n:
            d["last"] = (lx + (pt.x() - lx) * n * step / dist, ly + (pt.y() - ly) * n * step / dist)
            d["img"] = more._img(d["arr"])

    def _release_smudge(self, pt: QPointF, mods: int) -> None:
        self._move_smudge(pt, mods)
        d = self._drag
        d["layer"]["image"] = more._img(d["arr"])
        self.doc.touch(d["layer"])

    def _press_liquify(self, pt: QPointF, mods: int) -> None:
        layer = self._pixels_target("liquify brush")
        if layer is None:
            return
        self._push("Liquify")
        src = more._arr(layer["image"])
        lq = getattr(self, "_lq", None)
        if not lq or lq["layer"] is not layer or lq["shape"] != src.shape[:2] or lq.get("v") != layer.get("v"):
            lq = {"layer": layer, "src": src, "dx": np.zeros(src.shape[:2], np.float32), "dy": np.zeros(src.shape[:2], np.float32), "shape": src.shape[:2]}
            self._lq = lq                                           # strokes one after another warp the same original: restore can go all the way back
        d = {"kind": "liquify", "layer": layer, "lq": lq, "out": lq.get("out", src.copy()), "last": (pt.x(), pt.y()), "img": layer["image"],
             "sel": (self.doc.selection_alpha().astype(np.float32) / 255) if self.doc.selection is not None else None}
        self._drag = d
        self._liquify_at(d, pt.x(), pt.y(), 0.0, 0.0)
        self._live = (layer["id"], lambda img, d=d: d["img"])

    def _liquify_at(self, d: dict, x: float, y: float, vx: float, vy: float) -> None:
        lq = d["lq"]
        r = max(2.0, self.brush["size"] / 2)
        if self.liquify_mode == "push" and abs(vx) + abs(vy) < 1e-6:
            return
        box = more.liquify_step(lq["dx"], lq["dy"], self.liquify_mode, x, y, vx, vy, r, self.liquify_strength)
        if box is None:
            return
        x0, y0, x1, y1 = box                                       # what moved can pull from a little further
        pad = int(r)
        box = (max(0, x0 - pad), max(0, y0 - pad), min(lq["shape"][1], x1 + pad), min(lq["shape"][0], y1 + pad))
        more.warp_region(lq["src"], lq["dx"], lq["dy"], box, d["out"])
        if d["sel"] is not None:
            bx0, by0, bx1, by1 = box
            a = d["sel"][by0:by1, bx0:bx1, None]
            d["out"][by0:by1, bx0:bx1] = lq["src"][by0:by1, bx0:bx1] * (1 - a) + d["out"][by0:by1, bx0:bx1] * a

    def _move_liquify(self, pt: QPointF, mods: int) -> None:
        d = self._drag
        lx, ly = d["last"]
        step = max(1.0, self.brush["size"] * 0.1)
        dist = math.hypot(pt.x() - lx, pt.y() - ly)
        n = max(1, int(dist // step)) if self.liquify_mode == "push" else 1
        if self.liquify_mode == "push" and dist < 0.5:
            return
        for i in range(1, n + 1):
            t = i / n
            x, y = lx + (pt.x() - lx) * t, ly + (pt.y() - ly) * t
            self._liquify_at(d, x, y, (pt.x() - lx) / n, (pt.y() - ly) / n)
        d["last"] = (pt.x(), pt.y())
        d["img"] = more._img(d["out"])

    def _release_liquify(self, pt: QPointF, mods: int) -> None:
        d = self._drag
        if self.liquify_mode != "push":
            self._liquify_at(d, pt.x(), pt.y(), 0, 0)
        d["layer"]["image"] = more._img(d["out"])
        self.doc.touch(d["layer"])
        d["lq"]["out"], d["lq"]["v"] = d["out"], d["layer"].get("v")

    # ------------------------------------------------------------------ guides, rulers and snapping
    @Slot(str, float)
    def addGuide(self, axis: str, at: float) -> None:
        if not self.doc or axis not in ("x", "y"):
            return
        self._push("Guide")
        self.doc.guides.append({"axis": axis, "at": round(float(at), 1)})
        self._guide_live = None
        self._refresh()

    @Slot(int, float)
    def moveGuide(self, k: int, at: float) -> None:
        if self.doc and 0 <= k < len(self.doc.guides):
            self._push("Move guide")
            self.doc.guides[k]["at"] = round(float(at), 1)
            self._guide_live = None
            self._refresh()

    @Slot(int)
    def removeGuide(self, k: int) -> None:
        if self.doc and 0 <= k < len(self.doc.guides):
            self._push("Remove guide")
            self.doc.guides.pop(k)
            self._guide_live = None
            self._refresh()

    @Slot()
    def clearGuides(self) -> None:
        if self.doc and self.doc.guides:
            self._push("Clear guides")
            self.doc.guides = []
            self._refresh()

    def guide_at(self, x: float, y: float, slack: float) -> int:
        best, bd = -1, slack
        for k, g in enumerate(self.doc.guides if self.doc else []):
            d = abs((x if g["axis"] == "x" else y) - g["at"])
            if d <= bd:
                best, bd = k, d
        return best

    def set_guide_live(self, live) -> None:
        self._guide_live = live
        self.painted.emit()

    @Slot(bool)
    def setSnap(self, on: bool) -> None:
        self.snap = bool(on)
        self._save_prefs()
        self.changed.emit()

    rulersToggled = Signal()

    @Slot(bool)
    def setRulers(self, on: bool) -> None:
        self.rulers = bool(on)
        self._save_prefs()
        self.changed.emit()
        self.rulersToggled.emit()
        self.painted.emit()

    def _snap_targets(self) -> tuple:
        xs = [0.0, self.doc.w / 2, float(self.doc.w)] + [g["at"] for g in self.doc.guides if g["axis"] == "x"]
        ys = [0.0, self.doc.h / 2, float(self.doc.h)] + [g["at"] for g in self.doc.guides if g["axis"] == "y"]
        return xs, ys

    def _snap_point(self, pt: QPointF) -> QPointF:
        if not self.snap or not self.doc:
            return pt
        xs, ys = self._snap_targets()
        within = 7 / max(0.05, self.zoom)
        return QPointF(more.snap_value(pt.x(), xs, within)[0], more.snap_value(pt.y(), ys, within)[0])

    def _snap_box(self, box: QRectF, dx: float, dy: float) -> tuple:
        """A moving box's delta, nudged so an edge or its middle lands on a guide or the canvas's edges and middle."""
        if not self.snap or box is None or box.isEmpty():
            return dx, dy
        xs, ys = self._snap_targets()
        within = 7 / max(0.05, self.zoom)
        sx, sy = more.snap_box(box.x() + dx, box.y() + dy, box.width(), box.height(), xs, ys, within)
        return dx + sx, dy + sy

    def _content_box(self, layer: dict) -> QRectF:
        img = self.doc.layer_image(dict(layer, mask=None)) if layer["kind"] != "adjust" else None
        if img is None:
            return QRectF()
        a = ez.alpha_of(img)
        ys, xs = np.nonzero(a > 0)
        if not len(xs):
            return QRectF()
        return QRectF(float(xs.min()), float(ys.min()), float(xs.max() - xs.min() + 1), float(ys.max() - ys.min() + 1))

    guides = Property("QVariantList", lambda self: [dict(g) for g in self.doc.guides] if self.doc else [], notify=changed)
    snapOn = Property(bool, lambda self: self.snap, notify=changed)
    rulersOn = Property(bool, lambda self: self.rulers, notify=changed)
    retouchMode = Property(str, lambda self: self.retouch, notify=changed)
    retouchRange = Property(str, lambda self: self.retouch_range, notify=changed)
    retouchStrength = Property(float, lambda self: self.retouch_strength, notify=changed)
    liquifyMode = Property(str, lambda self: self.liquify_mode, notify=changed)
    liquifyStrength = Property(float, lambda self: self.liquify_strength, notify=changed)
    smudgeStrength = Property(float, lambda self: self.smudge_strength, notify=changed)
    liquifyModes = Property("QVariantList", lambda self: [[k, v] for k, v in more.LIQUIFY.items()], constant=True)


def zipfile_error():
    import zipfile
    return zipfile.BadZipFile


# ------------------------------------------------------------------------------------------- pictures for the panels
class EaselThumbs(QQuickImageProvider):
    """image://easel/layer/<id>/<version>: a small picture of one layer, for the Layers panel."""

    def __init__(self, easel: Easel):
        super().__init__(QQuickImageProvider.ImageType.Image)
        self.easel = easel

    def requestImage(self, ident, size, requested):
        doc = self.easel.doc
        parts = ident.split("/")
        side = 96
        out = QImage(side, side, ez.FMT)
        out.fill(Qt.GlobalColor.transparent)
        if doc is None or len(parts) < 2:
            return out
        layer = doc.layer(parts[1]) if parts[0] in ("layer", "mask") else None
        if layer is None or doc.index(parts[1]) < 0:
            return out
        if parts[0] == "mask" and layer.get("mask") is not None:
            img = ez.array_to_image(np.repeat(ez.alpha_of(layer["mask"])[..., None], 4, axis=2) | np.array([0, 0, 0, 255], np.uint8))
        elif layer["kind"] == "adjust":
            return out
        else:
            img = doc.layer_image(dict(layer, mask=None))
        thumb = img.scaled(side, side, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        p = QPainter(out)
        x, y = (side - thumb.width()) // 2, (side - thumb.height()) // 2
        tile = 8
        for ty in range(0, thumb.height(), tile):                    # a checkerboard where it's see-through
            for tx in range(0, thumb.width(), tile):
                p.fillRect(x + tx, y + ty, tile, tile, QColor("#DADDE3") if (tx // tile + ty // tile) % 2 else QColor("#F5F6F8"))
        p.drawImage(x, y, thumb)
        p.end()
        return out


# ------------------------------------------------------------------------------------------- the canvas
class EaselView(QQuickPaintedItem):
    """Draws the picture (zoomed and panned), the checkerboard behind it, and what tools show over it; turns the
    pointer into document pixels for Easel."""
    zoomChanged = Signal()
    backendChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._easel = None
        self._zoom, self._ox, self._oy = 1.0, 0.0, 0.0
        self._pads = (0.0, 0.0, 0.0, 0.0)                         # room the islands take: left, top, right, bottom
        self._img = QImage()
        self._fitted = False
        self._pan = None
        self._space = False
        self._ants = 0
        self.setAcceptedMouseButtons(Qt.MouseButton.LeftButton | Qt.MouseButton.RightButton | Qt.MouseButton.MiddleButton)
        self.setAcceptHoverEvents(True)
        self.setActiveFocusOnTab(True)
        self._tick = QTimer(self)
        self._tick.setInterval(160)
        self._tick.timeout.connect(self._march)
        self._tile = self._checker()
        self.widthChanged.connect(self._refit)
        self.heightChanged.connect(self._refit)

    @staticmethod
    def _checker() -> QPixmap:
        pm = QPixmap(16, 16)
        pm.fill(QColor("#F5F6F8"))
        p = QPainter(pm)
        p.fillRect(0, 0, 8, 8, QColor("#DADDE3"))
        p.fillRect(8, 8, 8, 8, QColor("#DADDE3"))
        p.end()
        return pm

    def _get_backend(self):
        return self._easel

    def _set_backend(self, easel):
        if easel is self._easel:
            return
        self._easel = easel
        if easel is not None:
            easel.painted.connect(self._repaint)
            easel.changed.connect(self._changed)
            easel.rulersToggled.connect(lambda: self.fit() if not getattr(self, "_user_zoom", False) else self.update())
        self._fitted = False
        self._repaint()
        self.backendChanged.emit()

    backend = Property(QObject, _get_backend, _set_backend, notify=backendChanged)

    @Slot(float, float, float, float)
    def setPads(self, left: float, top: float, right: float, bottom: float):
        """Where the islands sit, so fitting the picture keeps it clear of them."""
        if (left, top, right, bottom) != self._pads:
            self._pads = (left, top, right, bottom)
            if not getattr(self, "_user_zoom", False):
                self._fitted = False
                if not self._img.isNull():
                    self.fit()
    zoom = Property(float, lambda self: self._zoom, notify=zoomChanged)

    def _changed(self):
        doc = self._easel.doc if self._easel else None
        key = (id(doc), doc.w if doc else 0, doc.h if doc else 0)
        if key != getattr(self, "_doc_key", None):
            self._doc_key = key
            self._fitted = False
            self._repaint()
        if self._easel and self._easel.doc and self._easel.doc.selection is not None:
            if not self._tick.isActive():
                self._tick.start()
        else:
            self._tick.stop()

    def _march(self):
        self._ants = (self._ants + 1) % 8
        self.update()

    def _repaint(self):
        self._img = self._easel.render() if self._easel and self._easel.doc else QImage()
        if not self._fitted and not self._img.isNull():
            self.fit()
        self.update()

    def _refit(self):
        if not self._fitted_by_user():
            self._fitted = False
            if not self._img.isNull():
                self.fit()

    def _fitted_by_user(self) -> bool:
        return getattr(self, "_user_zoom", False)

    @Slot()
    def fit(self):
        if not self._easel or not self._easel.doc or self.width() < 10:
            return
        doc = self._easel.doc
        l, t, r, b = self._pads
        if self._easel.rulers:                                        # room for the rulers too
            l, t = l + self.RULER, t + self.RULER
        room_w, room_h = max(50, self.width() - l - r - 40), max(50, self.height() - t - b - 40)
        z = min(room_w / doc.w, room_h / doc.h, 1.0 if max(doc.w, doc.h) > 400 else 4.0)
        self._set_zoom(max(0.02, z), center=False)
        self._ox = l + 20 + (room_w - doc.w * self._zoom) / 2
        self._oy = t + 20 + (room_h - doc.h * self._zoom) / 2
        self.update()
        self._fitted = True
        self._user_zoom = False

    @Slot(float)
    def setZoom(self, z: float):
        self._user_zoom = True
        self._set_zoom(z, center=False, around=QPointF(self.width() / 2, self.height() / 2))

    @Slot()
    def actualSize(self):
        self.setZoom(1.0)

    def _set_zoom(self, z: float, center: bool = False, around: QPointF = None):
        z = max(0.02, min(64.0, z))
        doc = self._easel.doc
        if center:
            self._ox = (self.width() - doc.w * z) / 2
            self._oy = (self.height() - doc.h * z) / 2
        elif around is not None:
            dx, dy = (around.x() - self._ox) / self._zoom, (around.y() - self._oy) / self._zoom
            self._ox, self._oy = around.x() - dx * z, around.y() - dy * z
        self._zoom = z
        if self._easel:
            self._easel.zoom = z
        self.zoomChanged.emit()
        self.update()

    def _doc_point(self, pos) -> QPointF:
        return QPointF((pos.x() - self._ox) / self._zoom, (pos.y() - self._oy) / self._zoom)

    @Slot(bool)
    def setSpace(self, down: bool):
        self._space = down
        self.setCursor(QCursor(Qt.CursorShape.OpenHandCursor if down else self._tool_cursor()))

    def _tool_cursor(self):
        tool = self._easel.tool if self._easel else ""
        return {"hand": Qt.CursorShape.OpenHandCursor, "move": Qt.CursorShape.SizeAllCursor, "text": Qt.CursorShape.IBeamCursor,
                "pointer": Qt.CursorShape.ArrowCursor, "nodes": Qt.CursorShape.ArrowCursor, "transform": Qt.CursorShape.SizeAllCursor}.get(tool, Qt.CursorShape.CrossCursor)

    @staticmethod
    def _mods(event) -> int:
        m = event.modifiers()
        return (SHIFT if m & Qt.KeyboardModifier.ShiftModifier else 0) | (ALT if m & Qt.KeyboardModifier.AltModifier else 0) | (CTRL if m & Qt.KeyboardModifier.ControlModifier else 0)

    def event(self, ev):
        """A drawing tablet: its pressure goes to the brush; the pen draws like the mouse does."""
        t = ev.type()
        if t in (QEvent.Type.TabletPress, QEvent.Type.TabletMove, QEvent.Type.TabletRelease) and self._easel:
            self._easel.setPressure(ev.pressure() if t != QEvent.Type.TabletRelease else 1.0)
            pt = self._doc_point(ev.position())
            if t == QEvent.Type.TabletPress:
                self.forceActiveFocus()
                self._easel.press(pt.x(), pt.y(), 2 if ev.button() == Qt.MouseButton.RightButton else 1, self._mods(ev))
            elif t == QEvent.Type.TabletMove:
                self._easel.move(pt.x(), pt.y(), self._mods(ev))
                self._easel.hover(pt.x(), pt.y())
            else:
                self._easel.release(pt.x(), pt.y(), self._mods(ev))
            ev.accept()
            return True
        return super().event(ev)

    def mousePressEvent(self, event):
        self.forceActiveFocus()
        e = self._easel
        if not e or not e.doc:
            return
        tool = e.tool
        if event.button() == Qt.MouseButton.MiddleButton or self._space or tool == "hand":
            self._pan = (event.position(), self._ox, self._oy)
            self.setCursor(QCursor(Qt.CursorShape.ClosedHandCursor))
            return
        if tool == "zoom":
            self._user_zoom = True
            self._set_zoom(self._zoom * (0.5 if self._mods(event) & ALT or event.button() == Qt.MouseButton.RightButton else 2.0), around=event.position())
            return
        axis = self._in_ruler(event.position())
        if axis and event.button() == Qt.MouseButton.LeftButton:     # pull a guide out of the ruler
            self._ruler_drag = axis
            return
        pt = self._doc_point(event.position())
        button = 2 if event.button() == Qt.MouseButton.RightButton else 1
        e.press(pt.x(), pt.y(), button, self._mods(event))

    def mouseMoveEvent(self, event):
        if getattr(self, "_ruler_drag", ""):
            pt = self._doc_point(event.position())
            self._easel.set_guide_live((self._ruler_drag, pt.x() if self._ruler_drag == "x" else pt.y(), None))
            return
        if self._pan is not None:
            start, ox, oy = self._pan
            self._ox, self._oy = ox + event.position().x() - start.x(), oy + event.position().y() - start.y()
            self.update()
            return
        if self._easel:
            pt = self._doc_point(event.position())
            self._easel.move(pt.x(), pt.y(), self._mods(event))
            self._easel.hover(pt.x(), pt.y())

    def mouseReleaseEvent(self, event):
        if getattr(self, "_ruler_drag", ""):
            axis, self._ruler_drag = self._ruler_drag, ""
            if self._in_ruler(event.position()):
                self._easel.set_guide_live(None)                      # let go over the ruler: no guide
            else:
                pt = self._doc_point(event.position())
                self._easel.addGuide(axis, pt.x() if axis == "x" else pt.y())
            return
        if self._pan is not None:
            self._pan = None
            self.setCursor(QCursor(Qt.CursorShape.OpenHandCursor if self._space or (self._easel and self._easel.tool == "hand") else self._tool_cursor()))
            return
        if self._easel:
            pt = self._doc_point(event.position())
            self._easel.release(pt.x(), pt.y(), self._mods(event))

    def mouseDoubleClickEvent(self, event):
        if self._easel:
            pt = self._doc_point(event.position())
            self._easel.doubleClick(pt.x(), pt.y())

    def hoverMoveEvent(self, event):
        if self._easel:
            pt = self._doc_point(event.position())
            self._easel.hover(pt.x(), pt.y())
            self.setCursor(QCursor(Qt.CursorShape.OpenHandCursor if self._space else self._tool_cursor()))

    def hoverLeaveEvent(self, event):
        if self._easel:
            self._easel.hover(-1e6, -1e6)

    def wheelEvent(self, event):
        if not self._easel or not self._easel.doc:
            return
        d = event.angleDelta()
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self._user_zoom = True
            self._set_zoom(self._zoom * (1.15 if d.y() > 0 else 1 / 1.15), around=event.position())
        else:
            dx, dy = (d.y(), d.x()) if event.modifiers() & Qt.KeyboardModifier.ShiftModifier else (d.x(), d.y())
            self._ox += dx / 2
            self._oy += dy / 2
            self.update()

    KEYS = {Qt.Key.Key_B: "brush", Qt.Key.Key_E: "eraser", Qt.Key.Key_M: "select", Qt.Key.Key_L: "lasso", Qt.Key.Key_W: "wand", Qt.Key.Key_G: "gradient",
            Qt.Key.Key_K: "fill", Qt.Key.Key_I: "picker", Qt.Key.Key_T: "text", Qt.Key.Key_C: "crop", Qt.Key.Key_H: "hand", Qt.Key.Key_Z: "zoom",
            Qt.Key.Key_P: "pen", Qt.Key.Key_U: "rect", Qt.Key.Key_O: "ellipse", Qt.Key.Key_S: "clone", Qt.Key.Key_J: "heal", Qt.Key.Key_A: "nodes"}

    def keyPressEvent(self, event):
        """Single keys for tools (only while the canvas has the keyboard, so typing in a box is never taken)."""
        e = self._easel
        if not e or not e.doc or event.modifiers() & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.MetaModifier):
            event.ignore()
            return
        k = event.key()
        if k == Qt.Key.Key_Space and not event.isAutoRepeat():
            self.setSpace(True)
        elif k == Qt.Key.Key_V:
            e.setTool("move" if e.persona == "pixel" else "pointer")
        elif k in self.KEYS and self.KEYS[k] in (PIXEL_TOOLS if e.persona == "pixel" else VECTOR_TOOLS):
            e.setTool(self.KEYS[k])
        elif k == Qt.Key.Key_X:
            e.swapColours()
        elif k == Qt.Key.Key_D:
            e.setColour("fg", "#000000")
            e.setColour("bg", "#FFFFFF")
        elif k == Qt.Key.Key_BracketLeft:
            e.setBrush("size", e.brush["size"] / 1.25)
        elif k == Qt.Key.Key_BracketRight:
            e.setBrush("size", e.brush["size"] * 1.25)
        elif k in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            if e.tool == "nodes" and e.nodePicked:
                e.deleteNode()
            else:
                e.clearSelection()
        elif k == Qt.Key.Key_Escape:
            e.escape()
        elif k in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if e.transforming:
                e.applyTransform()
            elif e.penActive:
                e.finishPen()
            elif e.cropping:
                e.applyCrop()
        elif k in (Qt.Key.Key_Left, Qt.Key.Key_Right, Qt.Key.Key_Up, Qt.Key.Key_Down):
            step = 10 if event.modifiers() & Qt.KeyboardModifier.ShiftModifier else 1
            e.nudge({Qt.Key.Key_Left: -step, Qt.Key.Key_Right: step}.get(k, 0), {Qt.Key.Key_Up: -step, Qt.Key.Key_Down: step}.get(k, 0))
        elif Qt.Key.Key_0 <= k <= Qt.Key.Key_9 and e.tool in ("brush", "eraser"):
            n = k - Qt.Key.Key_0
            e.setBrush("opacity", 1.0 if n == 0 else n / 10)
        else:
            event.ignore()
            return
        event.accept()

    def keyReleaseEvent(self, event):
        if event.key() == Qt.Key.Key_Space and not event.isAutoRepeat():
            self.setSpace(False)
        event.ignore()

    # -------------------------------------------------------------- drawing
    def paint(self, p: QPainter):
        e = self._easel
        if not e or not e.doc or self._img.isNull():
            return
        doc = e.doc
        z = self._zoom
        target = QRectF(self._ox, self._oy, doc.w * z, doc.h * z)
        p.save()
        p.fillRect(target.adjusted(2, 4, 2, 4), QColor(0, 0, 0, 50))  # a soft shadow under the canvas
        p.setBrushOrigin(target.topLeft())
        p.fillRect(target, QBrush(self._tile))
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, z < 2)
        p.drawImage(target, self._img)
        p.restore()
        if z >= 10:                                                   # the pixel grid, close up
            p.save()
            p.setPen(QPen(QColor(128, 128, 128, 70), 0))
            vis = target.intersected(QRectF(0, 0, self.width(), self.height()))
            x0 = int((vis.left() - self._ox) / z)
            x1 = int((vis.right() - self._ox) / z) + 1
            y0 = int((vis.top() - self._oy) / z)
            y1 = int((vis.bottom() - self._oy) / z) + 1
            for x in range(x0, x1 + 1):
                p.drawLine(QPointF(self._ox + x * z, vis.top()), QPointF(self._ox + x * z, vis.bottom()))
            for y in range(y0, y1 + 1):
                p.drawLine(QPointF(vis.left(), self._oy + y * z), QPointF(vis.right(), self._oy + y * z))
            p.restore()
        ov = e.overlay()
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        t = QTransform().translate(self._ox, self._oy).scale(z, z)

        def ants(path: QPainterPath):
            mapped = t.map(path)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(QColor("#FFFFFF"), 1))
            p.drawPath(mapped)
            pen = QPen(QColor("#000000"), 1)
            pen.setDashPattern([4, 4])
            pen.setDashOffset(self._ants)
            p.setPen(pen)
            p.drawPath(mapped)
        if not ov["selection"].isEmpty():
            ants(ov["selection"])
        if ov["rect"] is not None:
            kind, r = ov["rect"]
            path = QPainterPath()
            path.addEllipse(r) if kind == "ellipsesel" else path.addRect(r)
            ants(path)
        if ov["lasso"]:
            path = QPainterPath()
            path.addPolygon(QPolygonF(ov["lasso"]))
            ants(path)
        if ov["line"] is not None:
            a, b = t.map(ov["line"][0]), t.map(ov["line"][1])
            p.setPen(QPen(QColor("#FFFFFF"), 3))
            p.drawLine(a, b)
            p.setPen(QPen(QColor("#2B6CF0"), 1.5))
            p.drawLine(a, b)
            for q in (a, b):
                p.setBrush(QColor("#FFFFFF"))
                p.drawEllipse(q, 4, 4)
        accent = QColor("#2B9DF0")
        for box in ov["boxes"]:
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(accent, 1))
            p.drawRect(t.mapRect(box))
        if ov["handles"] is not None and e.tool == "pointer":
            box = t.mapRect(ov["handles"])
            c = box.center()
            pts = [box.topLeft(), QPointF(c.x(), box.top()), box.topRight(), QPointF(box.right(), c.y()), box.bottomRight(),
                   QPointF(c.x(), box.bottom()), box.bottomLeft(), QPointF(box.left(), c.y())]
            p.setPen(QPen(accent, 1))
            p.drawLine(QPointF(c.x(), box.top()), QPointF(c.x(), box.top() - 28))
            p.setBrush(QColor("#FFFFFF"))
            for q in pts:
                p.drawRect(QRectF(q.x() - 4, q.y() - 4, 8, 8))
            p.drawEllipse(QPointF(c.x(), box.top() - 28), 5, 5)
        for nd in ov["nodes"]:
            q = t.map(QPointF(nd["x"], nd["y"]))
            p.setPen(QPen(accent, 1))
            for hx, hy in (("ix", "iy"), ("ox", "oy")):
                if hx in nd:
                    hq = t.map(QPointF(nd[hx], nd[hy]))
                    p.drawLine(q, hq)
                    p.setBrush(accent)
                    p.drawEllipse(hq, 3, 3)
            p.setBrush(QColor("#FFFFFF"))
            p.drawRect(QRectF(q.x() - 3.5, q.y() - 3.5, 7, 7))
        if ov["crop"] is not None:
            r = t.mapRect(ov["crop"])
            outside = QPainterPath()
            outside.addRect(QRectF(self._ox, self._oy, doc.w * z, doc.h * z))
            inner = QPainterPath()
            inner.addRect(r)
            p.fillPath(outside.subtracted(inner), QColor(0, 0, 0, 130))
            p.setPen(QPen(QColor("#FFFFFF"), 1.5))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(r)
            p.setPen(QPen(QColor(255, 255, 255, 90), 1))
            for i in (1, 2):
                p.drawLine(QPointF(r.left() + r.width() * i / 3, r.top()), QPointF(r.left() + r.width() * i / 3, r.bottom()))
                p.drawLine(QPointF(r.left(), r.top() + r.height() * i / 3), QPointF(r.right(), r.top() + r.height() * i / 3))
        if ov.get("xform"):
            hp = {k: t.map(v) for k, v in ov["xform"].items()}
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(accent, 1.5))
            p.drawPolygon(QPolygonF([hp[k] for k in ("tl", "tr", "br", "bl")]))
            p.drawLine(hp["t"], hp["rot"])
            p.setBrush(QColor("#FFFFFF"))
            for k in HANDLES:
                p.drawRect(QRectF(hp[k].x() - 4, hp[k].y() - 4, 8, 8))
            p.drawEllipse(hp["rot"], 5, 5)
        if ov.get("source") is not None:
            q = t.map(ov["source"])
            p.setBrush(Qt.BrushStyle.NoBrush)
            for col, w in ((QColor(0, 0, 0, 170), 3), (QColor("#FFFFFF"), 1.2)):
                p.setPen(QPen(col, w))
                p.drawLine(QPointF(q.x() - 9, q.y()), QPointF(q.x() + 9, q.y()))
                p.drawLine(QPointF(q.x(), q.y() - 9), QPointF(q.x(), q.y() + 9))
        if ov.get("nodesel") is not None:
            q = t.map(ov["nodesel"])
            p.setPen(QPen(accent, 1))
            p.setBrush(accent)
            p.drawRect(QRectF(q.x() - 4.5, q.y() - 4.5, 9, 9))
        if ov["brush"] is not None:
            pt, size = ov["brush"]
            q = t.map(pt)
            r = max(1.5, size * z / 2)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(QColor(0, 0, 0, 160), 1))
            p.drawEllipse(q, r, r)
            p.setPen(QPen(QColor(255, 255, 255, 200), 1))
            p.drawEllipse(q, r + 1, r + 1)
        self._paint_guides(p, ov, z)
        p.restore()
        if e.rulers:
            self._paint_rulers(p, z)

    RULER = 20

    def _paint_guides(self, p: QPainter, ov: dict, z: float) -> None:
        live = ov.get("guideLive")
        guides = [g for k, g in enumerate(ov.get("guides") or []) if not (live and live[2] == k)]
        if live:
            guides.append({"axis": live[0], "at": live[1], "live": True})
        for g in guides:
            pen = QPen(QColor("#00C8E8"), 1)
            if g.get("live"):
                pen.setDashPattern([5, 3])
            p.setPen(pen)
            left, top, right, bottom = self._pads                      # across the free area, not under the islands
            if g["axis"] == "x":
                x = self._ox + g["at"] * z
                p.drawLine(QPointF(x, top), QPointF(x, self.height() - bottom))
            else:
                y = self._oy + g["at"] * z
                p.drawLine(QPointF(left, y), QPointF(self.width() - right, y))

    def _ruler_step(self, z: float) -> float:
        for step in (1, 2, 5, 10, 25, 50, 100, 250, 500, 1000, 2500, 5000):
            if step * z >= 60:
                return step
        return 10000

    def _paint_rulers(self, p: QPainter, z: float) -> None:
        """Along the top and left of the canvas's free area (clear of the islands): pixels, numbered."""
        left, top, right, bottom = self._pads
        R = self.RULER
        p.save()
        dark = QColor(20, 22, 27, 215)
        p.fillRect(QRectF(left, top, self.width() - left - right, R), dark)
        p.fillRect(QRectF(left, top, R, self.height() - top - bottom), dark)
        step = self._ruler_step(z)
        f = p.font()
        f.setPixelSize(9)
        p.setFont(f)
        p.setPen(QPen(QColor(200, 205, 215), 1))
        x_from, x_to = (left + R - self._ox) / z, (self.width() - right - self._ox) / z
        k = math.floor(x_from / step) * step
        while k <= x_to:
            sx = self._ox + k * z
            if sx >= left + R:
                p.drawLine(QPointF(sx, top + R - 7), QPointF(sx, top + R))
                p.drawText(QPointF(sx + 3, top + 10), str(int(k)))
            for sub in range(1, 5):
                tx = sx + sub * step * z / 5
                if left + R <= tx <= self.width() - right:
                    p.drawLine(QPointF(tx, top + R - 3), QPointF(tx, top + R))
            k += step
        y_from, y_to = (top + R - self._oy) / z, (self.height() - bottom - self._oy) / z
        k = math.floor(y_from / step) * step
        while k <= y_to:
            sy = self._oy + k * z
            if sy >= top + R:
                p.drawLine(QPointF(left + R - 7, sy), QPointF(left + R, sy))
                p.save()
                p.translate(left + 10, sy + 3)
                p.rotate(90)
                p.drawText(QPointF(0, 0), str(int(k)))
                p.restore()
            for sub in range(1, 5):
                ty = sy + sub * step * z / 5
                if top + R <= ty <= self.height() - bottom:
                    p.drawLine(QPointF(left + R - 3, ty), QPointF(left + R, ty))
            k += step
        hv = self._easel._hover if self._easel else None
        if hv is not None:                                            # where the pointer is, on both rulers
            p.setPen(QPen(QColor("#00C8E8"), 1))
            p.drawLine(QPointF(self._ox + hv.x() * z, top), QPointF(self._ox + hv.x() * z, top + R))
            p.drawLine(QPointF(left, self._oy + hv.y() * z), QPointF(left + R, self._oy + hv.y() * z))
        p.restore()

    def _in_ruler(self, pos) -> str:
        """"y" over the top ruler (a guide across), "x" over the left one, "" elsewhere."""
        e = self._easel
        if not e or not e.rulers:
            return ""
        left, top, right, bottom = self._pads
        if top <= pos.y() < top + self.RULER and pos.x() >= left:
            return "y"
        if left <= pos.x() < left + self.RULER and pos.y() >= top:
            return "x"
        return ""
