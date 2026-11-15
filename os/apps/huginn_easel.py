"""Huginn Easel: paint, retouch and draw. Pixel layers and vector layers live in one document.

The document
    A stack of layers, bottom first. Pixel layers hold a picture as big as the canvas; vector layers hold shapes
    (rectangles, ellipses, lines, stars, paths drawn with the pen, and text) that stay sharp at any size; adjustment
    layers change the look of everything below them without touching it. Any pixel or vector layer can have a mask
    (white shows, black hides), a blend mode and an opacity.

Files
    .easel        Easel's own: a zip with manifest.json, one PNG per pixel layer and mask, and a preview.
    .ora          OpenRaster, which Krita, GIMP and MyPaint read and write: layers, blend modes and opacity cross over.
    PNG, JPEG, WebP, TIFF, BMP open as one pixel layer; SVG opens as a picture (drawn sharp at the canvas size).
    Export        PNG, JPEG, WebP; SVG and PDF keep vector layers as vectors (pixel layers go in as pictures).

Qt's QPainter does the compositing (blend modes, masks, antialiased shapes); numpy and Pillow do the filters.
"""
import json
import math
import os
import time
import uuid
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np
from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QPointF, QRect, QRectF, QSize, QSizeF, Qt
from PySide6.QtGui import (QBrush, QColor, QFont, QImage, QLinearGradient, QPageSize, QPainter, QPainterPath, QPainterPathStroker,
                           QPdfWriter, QPen, QPolygonF, QRadialGradient, QRegion, QBitmap, QTransform)

FMT = QImage.Format.Format_ARGB32_Premultiplied
CM = QPainter.CompositionMode
BLENDS = {"normal": CM.CompositionMode_SourceOver, "multiply": CM.CompositionMode_Multiply, "screen": CM.CompositionMode_Screen,
          "overlay": CM.CompositionMode_Overlay, "darken": CM.CompositionMode_Darken, "lighten": CM.CompositionMode_Lighten,
          "dodge": CM.CompositionMode_ColorDodge, "burn": CM.CompositionMode_ColorBurn, "hard": CM.CompositionMode_HardLight,
          "soft": CM.CompositionMode_SoftLight, "difference": CM.CompositionMode_Difference, "exclusion": CM.CompositionMode_Exclusion,
          "add": CM.CompositionMode_Plus}
BLEND_NAMES = [("normal", "Normal"), ("multiply", "Multiply"), ("screen", "Screen"), ("overlay", "Overlay"), ("darken", "Darken"),
               ("lighten", "Lighten"), ("dodge", "Colour Dodge"), ("burn", "Colour Burn"), ("hard", "Hard Light"), ("soft", "Soft Light"),
               ("difference", "Difference"), ("exclusion", "Exclusion"), ("add", "Add")]
ORA_OPS = {"normal": "svg:src-over", "multiply": "svg:multiply", "screen": "svg:screen", "overlay": "svg:overlay", "darken": "svg:darken",
           "lighten": "svg:lighten", "dodge": "svg:color-dodge", "burn": "svg:color-burn", "hard": "svg:hard-light", "soft": "svg:soft-light",
           "difference": "svg:difference", "exclusion": "svg:exclusion", "add": "svg:plus"}
ADJUSTMENTS = {"light": "Brightness & Contrast", "curves": "Curves", "colour": "Hue & Saturation", "levels": "Levels", "bw": "Black & White",
               "invert": "Invert", "warmth": "Warmth", "posterize": "Posterize"}
PICTURES = (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff", ".gif")


def new_image(w: int, h: int, fill=None) -> QImage:
    img = QImage(max(1, int(w)), max(1, int(h)), FMT)
    img.fill(QColor(fill) if fill else Qt.GlobalColor.transparent)
    return img


def colour(text: str, fallback: str = "#000000") -> QColor:
    c = QColor(text or fallback)
    return c if c.isValid() else QColor(fallback)


def image_to_array(img: QImage) -> np.ndarray:
    """A QImage as an h×w×4 uint8 array in RGBA order (straight alpha)."""
    img = img.convertToFormat(QImage.Format.Format_RGBA8888)
    ptr = img.constBits()
    arr = np.frombuffer(ptr, np.uint8, img.sizeInBytes()).reshape(img.height(), img.bytesPerLine())[:, :img.width() * 4]
    return arr.reshape(img.height(), img.width(), 4).copy()


def array_to_image(arr: np.ndarray) -> QImage:
    arr = np.ascontiguousarray(arr.astype(np.uint8))
    h, w = arr.shape[:2]
    img = QImage(arr.data, w, h, w * 4, QImage.Format.Format_RGBA8888).copy()
    return img.convertToFormat(FMT)


def alpha_of(img: QImage) -> np.ndarray:
    return image_to_array(img)[..., 3]


def alpha_image(a: np.ndarray) -> QImage:
    """An image that is white, with this alpha (masks and selections are kept like this)."""
    h, w = a.shape
    rgba = np.empty((h, w, 4), np.uint8)
    rgba[..., :3] = 255
    rgba[..., 3] = a
    return array_to_image(rgba)


def png_bytes(img: QImage) -> bytes:
    data = QByteArray()
    buf = QBuffer(data)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    buf.close()
    return bytes(data)


def image_from_bytes(raw: bytes) -> QImage:
    img = QImage()
    img.loadFromData(raw)
    return img.convertToFormat(FMT) if not img.isNull() else img


# ------------------------------------------------------------------------------------------- vector shapes
def _node_path(subs: list) -> QPainterPath:
    path = QPainterPath()
    for sub in subs:
        nodes = sub.get("nodes") or []
        if not nodes:
            continue
        path.moveTo(nodes[0]["x"], nodes[0]["y"])
        pairs = list(zip(nodes, nodes[1:])) + ([(nodes[-1], nodes[0])] if sub.get("closed") and len(nodes) > 1 else [])
        for a, b in pairs:
            ax, ay = a.get("ox", a["x"]), a.get("oy", a["y"])
            bx, by = b.get("ix", b["x"]), b.get("iy", b["y"])
            if (ax, ay) == (a["x"], a["y"]) and (bx, by) == (b["x"], b["y"]):
                path.lineTo(b["x"], b["y"])
            else:
                path.cubicTo(ax, ay, bx, by, b["x"], b["y"])
        if sub.get("closed"):
            path.closeSubpath()
    return path


def text_font(s: dict) -> QFont:
    f = QFont(s.get("font") or "Inter")
    f.setPixelSize(max(1, int(s.get("size", 48))))
    f.setWeight(QFont.Weight(int(s.get("weight", 400))))
    f.setItalic(bool(s.get("italic")))
    return f


def raw_path(s: dict) -> QPainterPath:
    """A shape's outline before its turn."""
    t = s.get("type")
    path = QPainterPath()
    if t == "rect":
        r = max(0.0, min(float(s.get("radius", 0)), abs(s["w"]) / 2, abs(s["h"]) / 2))
        path.addRoundedRect(QRectF(s["x"], s["y"], s["w"], s["h"]).normalized(), r, r)
    elif t == "ellipse":
        path.addEllipse(QRectF(s["x"], s["y"], s["w"], s["h"]).normalized())
    elif t == "line":
        path.moveTo(s["x1"], s["y1"])
        path.lineTo(s["x2"], s["y2"])
    elif t == "star":
        rect = QRectF(s["x"], s["y"], s["w"], s["h"]).normalized()
        n, inner = max(3, int(s.get("points", 5))), float(s.get("inner", 0.5))
        cx, cy, rx, ry = rect.center().x(), rect.center().y(), rect.width() / 2, rect.height() / 2
        poly = QPolygonF()
        steps = n * 2 if inner < 0.999 else n
        for i in range(steps):
            k = 1.0 if (i % 2 == 0 or inner >= 0.999) else inner
            a = -math.pi / 2 + i * (2 * math.pi / steps)
            poly.append(QPointF(cx + rx * k * math.cos(a), cy + ry * k * math.sin(a)))
        path.addPolygon(poly)
        path.closeSubpath()
    elif t == "path":
        path = _node_path(s.get("subs") or [])
    elif t == "text" and s.get("along"):
        return text_along(s, text_font(s), s["along"])
    elif t == "text":
        f = text_font(s)
        from PySide6.QtGui import QFontMetricsF
        fm = QFontMetricsF(f)
        lines = (s.get("text") or "").split("\n")
        widths = [fm.horizontalAdvance(line) for line in lines]
        box = max(widths or [0])
        for i, line in enumerate(lines):
            dx = {"center": (box - widths[i]) / 2, "right": box - widths[i]}.get(s.get("align", "left"), 0)
            path.addText(s["x"] + dx, s["y"] + fm.ascent() + i * fm.lineSpacing(), f, line)
    return path


def shape_path(s: dict) -> QPainterPath:
    path = raw_path(s)
    rot = float(s.get("rot", 0))
    if rot:
        c = path.boundingRect().center()
        path = QTransform().translate(c.x(), c.y()).rotate(rot).translate(-c.x(), -c.y()).map(path)
    return path


def paint_shape(p: QPainter, s: dict) -> None:
    path = shape_path(s)
    p.save()
    p.setOpacity(p.opacity() * float(s.get("opacity", 1)))
    fill = s.get("fill", "")
    if fill and s.get("type") != "line":
        if s.get("fill2"):                                           # a gradient across the shape
            box = path.boundingRect()
            c = box.center()
            if s.get("gkind") == "radial":
                g = QRadialGradient(c, max(box.width(), box.height()) / 2)
            else:
                a = math.radians(float(s.get("gangle", 90)))
                r = (abs(box.width() * math.cos(a)) + abs(box.height() * math.sin(a))) / 2
                g = QLinearGradient(QPointF(c.x() - math.cos(a) * r, c.y() - math.sin(a) * r), QPointF(c.x() + math.cos(a) * r, c.y() + math.sin(a) * r))
            g.setColorAt(0, colour(fill))
            g.setColorAt(1, colour(s["fill2"]))
            p.fillPath(path, QBrush(g))
        else:
            p.fillPath(path, colour(fill))
    width = float(s.get("width", 0))
    if s.get("stroke") and width > 0:
        pen = QPen(colour(s["stroke"]), width)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        if s.get("dash"):
            pen.setDashPattern([3.0, 2.0])
        p.strokePath(path, pen)
    p.restore()


def shape_bounds(s: dict) -> QRectF:
    path = shape_path(s)
    box = path.boundingRect()
    w = float(s.get("width", 0)) if s.get("stroke") else 0
    return box.adjusted(-w / 2, -w / 2, w / 2, w / 2)


def hits(s: dict, pt: QPointF, slack: float = 4.0) -> bool:
    path = shape_path(s)
    if s.get("type") != "line" and s.get("fill") and path.contains(pt):
        return True
    stroker = QPainterPathStroker()
    stroker.setWidth(max(float(s.get("width", 0)), 1.0) + slack * 2)
    return stroker.createStroke(path).contains(pt) or (s.get("type") == "text" and path.boundingRect().contains(pt))


def path_to_subs(path: QPainterPath) -> list:
    """A QPainterPath (from combining shapes) as Easel's nodes: one list per subpath, with curve handles."""
    subs, nodes, i, n = [], [], 0, path.elementCount()
    while i < n:
        e = path.elementAt(i)
        if e.type == QPainterPath.ElementType.MoveToElement:
            if nodes:
                subs.append({"nodes": nodes, "closed": True})
            nodes = [{"x": e.x, "y": e.y}]
            i += 1
        elif e.type == QPainterPath.ElementType.LineToElement:
            nodes.append({"x": e.x, "y": e.y})
            i += 1
        elif e.type == QPainterPath.ElementType.CurveToElement and i + 2 < n:
            c1, c2, end = e, path.elementAt(i + 1), path.elementAt(i + 2)
            nodes[-1]["ox"], nodes[-1]["oy"] = c1.x, c1.y
            nodes.append({"x": end.x, "y": end.y, "ix": c2.x, "iy": c2.y})
            i += 3
        else:
            i += 1
    if nodes:
        subs.append({"nodes": nodes, "closed": True})
    for sub in subs:                                                 # a closed subpath repeats its first point last
        ns = sub["nodes"]
        if len(ns) > 2 and abs(ns[-1]["x"] - ns[0]["x"]) < 1e-6 and abs(ns[-1]["y"] - ns[0]["y"]) < 1e-6:
            last = ns.pop()
            if "ix" in last:
                ns[0]["ix"], ns[0]["iy"] = last["ix"], last["iy"]
    return subs


def move_shape(s: dict, dx: float, dy: float) -> None:
    t = s["type"]
    if t == "line":
        s["x1"] += dx
        s["y1"] += dy
        s["x2"] += dx
        s["y2"] += dy
    elif t == "path":
        for sub in s.get("subs", []):
            for nd in sub["nodes"]:
                for kx, ky in (("x", "y"), ("ix", "iy"), ("ox", "oy")):
                    if kx in nd:
                        nd[kx] += dx
                        nd[ky] += dy
    else:
        s["x"] += dx
        s["y"] += dy


def scale_shape(s: dict, box: QRectF, new: QRectF) -> None:
    """Fit a shape from one box into another (resizing with the handles)."""
    sx = new.width() / box.width() if box.width() else 1
    sy = new.height() / box.height() if box.height() else 1

    def mx(x):
        return new.x() + (x - box.x()) * sx

    def my(y):
        return new.y() + (y - box.y()) * sy
    t = s["type"]
    if t == "line":
        s["x1"], s["y1"], s["x2"], s["y2"] = mx(s["x1"]), my(s["y1"]), mx(s["x2"]), my(s["y2"])
    elif t == "path":
        for sub in s.get("subs", []):
            for nd in sub["nodes"]:
                for kx, ky in (("x", "y"), ("ix", "iy"), ("ox", "oy")):
                    if kx in nd:
                        nd[kx], nd[ky] = mx(nd[kx]), my(nd[ky])
    elif t == "text":
        s["x"], s["y"] = mx(s["x"]), my(s["y"])
        if s.get("along"):
            s["along"] = [[mx(x), my(y)] for x, y in s["along"]]
        s["size"] = max(4, float(s.get("size", 48)) * (sy if abs(sy - 1) > abs(sx - 1) else sx))
    else:
        x2, y2 = mx(s["x"] + s["w"]), my(s["y"] + s["h"])
        s["x"], s["y"] = mx(s["x"]), my(s["y"])
        s["w"], s["h"] = x2 - s["x"], y2 - s["y"]



# ------------------------------------------------------------------------------------------- filling a hole from its surroundings
def _box_sum(a: np.ndarray, r: int) -> np.ndarray:
    pad = np.pad(a.astype(np.float32), r + 1)
    c = pad.cumsum(0).cumsum(1)
    k = 2 * r + 1
    h, w = a.shape
    return (c[k:k + h, k:k + w] - c[:h, k:k + w] - c[k:k + h, :w] + c[:h, :w])


def _patch_offsets(r: int):
    dy, dx = np.mgrid[-r:r + 1, -r:r + 1]
    return dy.ravel(), dx.ravel()


def _ssd(img: np.ndarray, ty, tx, sy, sx, r: int) -> np.ndarray:
    h, w = img.shape[:2]
    dy, dx = _patch_offsets(r)
    a = img[np.clip(ty[:, None] + dy, 0, h - 1), np.clip(tx[:, None] + dx, 0, w - 1)]
    b = img[np.clip(sy[:, None] + dy, 0, h - 1), np.clip(sx[:, None] + dx, 0, w - 1)]
    d = a - b
    return (d * d).sum(axis=(1, 2))


def _diffuse(img: np.ndarray, hole: np.ndarray, rounds: int = 60) -> np.ndarray:
    """A first guess for the hole: its edges spread inwards."""
    out = img.copy()
    known = (~hole).astype(np.float32)
    for _ in range(rounds):
        s = np.stack([_box_sum(out[..., c] * known, 1) for c in range(3)], -1)
        n = _box_sum(known, 1)[..., None]
        fill = s / np.maximum(n, 1e-6)
        out[hole] = np.where(n[hole] > 0, fill[hole], out[hole])
        known = np.maximum(known, (n[..., 0] > 0).astype(np.float32))
    return out


def content_fill(rgb: np.ndarray, hole: np.ndarray, patch: int = 7, seed: int = 1) -> np.ndarray:
    """Fill the hole (True where to fill) with what's around it, texture and all: PatchMatch (Barnes et al.) inside
    an expectation-maximisation loop, coarse to fine over an image pyramid. Works on the hole's surroundings only."""
    hole = hole.astype(bool)
    if not hole.any():
        return rgb
    H, W = hole.shape
    ys, xs = np.nonzero(hole)
    m = max(int(np.ptp(ys)) + 1, int(np.ptp(xs)) + 1)
    margin = int(max(32, m * 1.6))
    Y0, Y1, X0, X1 = max(0, ys.min() - margin), min(H, ys.max() + margin + 1), max(0, xs.min() - margin), min(W, xs.max() + margin + 1)
    img0 = rgb[Y0:Y1, X0:X1, :3].astype(np.float32)
    hole0 = hole[Y0:Y1, X0:X1]
    r = patch // 2
    rng = np.random.default_rng(seed)
    # the pyramid
    levels = [(img0, hole0)]
    while min(levels[-1][0].shape[:2]) > 64 and levels[-1][1].sum() > 64:
        im, ho = levels[-1]
        h2, w2 = im.shape[0] // 2, im.shape[1] // 2
        im2 = im[:h2 * 2, :w2 * 2].reshape(h2, 2, w2, 2, 3).mean(axis=(1, 3))
        ho2 = ho[:h2 * 2, :w2 * 2].reshape(h2, 2, w2, 2).any(axis=(1, 3))
        levels.append((im2, ho2))
    levels.reverse()
    est, nnf = None, None
    for li, (im, ho) in enumerate(levels):
        h, w = ho.shape
        img = im.copy()
        if est is None:
            img = _diffuse(img, ho)
        else:                                                 # the coarser answer, made larger, as the start here
            up = np.repeat(np.repeat(est, 2, axis=0), 2, axis=1)
            up = np.pad(up, ((0, max(0, h - up.shape[0])), (0, max(0, w - up.shape[1])), (0, 0)), mode="edge")[:h, :w]
            img[ho] = up[ho]
        # sources: where a whole patch lies in known picture
        valid = (_box_sum(ho.astype(np.float32), r) == 0)
        valid[:r, :] = valid[-r:, :] = False
        valid[:, :r] = valid[:, -r:] = False
        vy, vx = np.nonzero(valid)
        if len(vy) == 0:
            return rgb
        ty, tx = np.nonzero(ho)
        n = len(ty)
        if nnf is None:
            k = rng.integers(0, len(vy), n)
            sy, sx = vy[k], vx[k]
        else:
            py, px = nnf
            sy = np.clip(py[np.minimum(ty // 2, py.shape[0] - 1), np.minimum(tx // 2, py.shape[1] - 1)] * 2 + ty % 2, 0, h - 1)
            sx = np.clip(px[np.minimum(ty // 2, px.shape[0] - 1), np.minimum(tx // 2, px.shape[1] - 1)] * 2 + tx % 2, 0, w - 1)
            bad = ~valid[sy, sx]
            k = rng.integers(0, len(vy), int(bad.sum()))
            sy[bad], sx[bad] = vy[k], vx[k]
        rounds = 3 if li < len(levels) - 1 else 2
        for _em in range(rounds):
            best = _ssd(img, ty, tx, sy, sx, r)
            mapy = np.full((h, w), -1, np.int64)
            mapx = np.full((h, w), -1, np.int64)
            for it in range(4):
                mapy[ty, tx], mapx[ty, tx] = sy, sx
                step = 1 if it % 2 == 0 else -1
                for oy, ox in ((0, step), (step, 0)):          # propagation: a neighbour's match, moved along
                    ny, nx = np.clip(ty - oy, 0, h - 1), np.clip(tx - ox, 0, w - 1)
                    cy, cx = mapy[ny, nx], mapx[ny, nx]
                    ok = cy >= 0
                    cy, cx = np.clip(cy + oy, 0, h - 1), np.clip(cx + ox, 0, w - 1)
                    ok &= valid[cy, cx]
                    if ok.any():
                        d = np.full(n, np.inf, np.float32)
                        d[ok] = _ssd(img, ty[ok], tx[ok], cy[ok], cx[ok], r)
                        better = d < best
                        sy[better], sx[better], best[better] = cy[better], cx[better], d[better]
                radius = max(h, w)
                while radius >= 1:                             # random search, nearer and nearer
                    cy = np.clip(sy + rng.integers(-radius, radius + 1, n), 0, h - 1)
                    cx = np.clip(sx + rng.integers(-radius, radius + 1, n), 0, w - 1)
                    ok = valid[cy, cx]
                    if ok.any():
                        d = np.full(n, np.inf, np.float32)
                        d[ok] = _ssd(img, ty[ok], tx[ok], cy[ok], cx[ok], r)
                        better = d < best
                        sy[better], sx[better], best[better] = cy[better], cx[better], d[better]
                    radius //= 2
            # voting: each hole pixel takes the average of what the patches over it say
            acc = np.zeros((h, w, 3), np.float32)
            cnt = np.zeros((h, w), np.float32)
            plain = np.zeros((h, w, 3), np.float32)
            many = np.zeros((h, w), np.float32)
            # good matches count for more; the scale has a floor, or a smooth picture (where most matches are
            # perfect) would give every imperfect one no say at all and leave pixels with nothing
            sigma = max(float(np.median(best)), 2.0 * (2 * r + 1) ** 2 * 3)
            wgt = np.exp(-np.minimum(best, 1e12) / (2 * sigma)).astype(np.float32)
            dy, dx = _patch_offsets(r)
            for oy, ox in zip(dy, dx):
                py, px = ty + oy, tx + ox
                ok = (py >= 0) & (py < h) & (px >= 0) & (px < w)
                py, px = py[ok], px[ok]
                qy, qx = np.clip(sy[ok] + oy, 0, h - 1), np.clip(sx[ok] + ox, 0, w - 1)
                vals = img[qy, qx]
                np.add.at(acc, (py, px), vals * wgt[ok][:, None])
                np.add.at(cnt, (py, px), wgt[ok])
                np.add.at(plain, (py, px), vals)
                np.add.at(many, (py, px), 1.0)
            filled = np.where((cnt > 1e-4)[..., None], acc / np.maximum(cnt, 1e-6)[..., None], plain / np.maximum(many, 1.0)[..., None])
            img[ho] = np.nan_to_num(filled[ho], nan=0.0)
        est = img
        py = np.zeros((h, w), np.int64)
        px = np.zeros((h, w), np.int64)
        py[ty, tx], px[ty, tx] = sy, sx
        nnf = (py, px)
    out = rgb.copy()
    region = out[Y0:Y1, X0:X1]
    region[..., :3][hole0] = np.clip(est[hole0], 0, 255).astype(rgb.dtype)
    out[Y0:Y1, X0:X1] = region
    return out


# ------------------------------------------------------------------------------------------- type along a path
def text_along(s: dict, f, points: list) -> QPainterPath:
    """Type that follows a line: each letter sits on the line at its place, turned to the line's direction."""
    from PySide6.QtGui import QFontMetricsF
    out = QPainterPath()
    if len(points) < 2:
        return out
    pts = np.array(points, np.float64)
    seg = np.hypot(np.diff(pts[:, 0]), np.diff(pts[:, 1]))
    cum = np.concatenate([[0], np.cumsum(seg)])
    total = cum[-1]
    fm = QFontMetricsF(f)
    text = (s.get("text") or "").replace("\\n", " ")
    adv = [fm.horizontalAdvance(ch) for ch in text]
    width = sum(adv)
    start = float(s.get("pathOffset", 0)) * max(0.0, total - width)
    if s.get("align") == "center":
        start = (total - width) / 2
    elif s.get("align") == "right":
        start = total - width
    lift = float(s.get("pathLift", 0))

    def point(d):
        d = max(0.0, min(total, d))
        k = int(np.searchsorted(cum, d, side="right") - 1)
        k = max(0, min(k, len(seg) - 1))
        t = (d - cum[k]) / max(1e-9, seg[k])
        return pts[k] + (pts[k + 1] - pts[k]) * t

    at = start
    for ch, a in zip(text, adv):
        mid = at + a / 2
        at += a
        if mid < 0 or mid > total or not ch.strip():
            continue
        x, y = point(mid)
        a0, a1 = point(mid - a / 2), point(mid + a / 2)      # the letter turns with the line across its own width,
        ang = math.degrees(math.atan2(a1[1] - a0[1], a1[0] - a0[0]))   # so bends don't jolt it
        glyph = QPainterPath()
        glyph.addText(-a / 2, -lift, f, ch)
        out.addPath(QTransform().translate(x, y).rotate(ang).map(glyph))
    return out


# ------------------------------------------------------------------------------------------- adjustment layers and filters
def hue_rotate(rgb: np.ndarray, degrees: float) -> np.ndarray:
    """Turn every colour round the colour wheel (in YIQ, which keeps brightness)."""
    a = math.radians(degrees)
    c, s = math.cos(a), math.sin(a)
    to_yiq = np.array([[0.299, 0.587, 0.114], [0.596, -0.274, -0.322], [0.211, -0.523, 0.312]], np.float32)
    rot = np.array([[1, 0, 0], [0, c, -s], [0, s, c]], np.float32)
    m = np.linalg.inv(to_yiq) @ rot @ to_yiq
    return rgb @ m.T.astype(np.float32)


def curve_lut(points: list) -> np.ndarray:
    """A 256-step table through the curve's points (x, y in 0..1), smooth and never overshooting (monotone cubic)."""
    pts = sorted((max(0.0, min(1.0, float(x))), max(0.0, min(1.0, float(y)))) for x, y in (points or []))
    if not pts:
        pts = [(0.0, 0.0), (1.0, 1.0)]
    if pts[0][0] > 0:                                               # past the end points the curve stays level
        pts.insert(0, (0.0, pts[0][1]))
    if pts[-1][0] < 1:
        pts.append((1.0, pts[-1][1]))
    xs = np.array([p[0] for p in pts])
    ys = np.array([p[1] for p in pts])
    keep = np.concatenate(([True], np.diff(xs) > 1e-6))
    xs, ys = xs[keep], ys[keep]
    t = np.linspace(0, 1, 256)
    if len(xs) < 2:
        return np.clip(t, 0, 1)
    h = np.diff(xs)
    d = np.diff(ys) / h
    m = np.zeros_like(xs)
    m[0], m[-1] = d[0], d[-1]
    for i in range(1, len(xs) - 1):                                 # Fritsch–Carlson slopes
        m[i] = 0 if d[i - 1] * d[i] <= 0 else 3 * (h[i - 1] + h[i]) / ((2 * h[i] + h[i - 1]) / d[i - 1] + (h[i] + 2 * h[i - 1]) / d[i])
    k = np.clip(np.searchsorted(xs, t) - 1, 0, len(xs) - 2)
    u = (t - xs[k]) / h[k]
    h00, h10, h01, h11 = 2 * u ** 3 - 3 * u ** 2 + 1, u ** 3 - 2 * u ** 2 + u, -2 * u ** 3 + 3 * u ** 2, u ** 3 - u ** 2
    out = h00 * ys[k] + h10 * h[k] * m[k] + h01 * ys[k + 1] + h11 * h[k] * m[k + 1]
    return np.clip(out, 0, 1)


def apply_curves(x: np.ndarray, curves: dict) -> np.ndarray:
    idx = np.clip((x * 255 + 0.5).astype(np.int32), 0, 255)
    if curves.get("rgb"):
        lut = curve_lut(curves["rgb"])
        x = lut[idx]
        idx = np.clip((x * 255 + 0.5).astype(np.int32), 0, 255)
    out = x.copy()
    for c, key in enumerate(("r", "g", "b")):
        if curves.get(key):
            out[..., c] = curve_lut(curves[key])[idx[..., c]]
    return out


def adjust_array(rgb: np.ndarray, kind: str, p: dict) -> np.ndarray:
    """One adjustment on float RGB (0..1). Parameters run from -1 to 1 unless said otherwise."""
    x = rgb
    if kind == "light":
        x = x + p.get("brightness", 0) * 0.35
        k = 1 + p.get("contrast", 0) * (0.9 if p.get("contrast", 0) > 0 else 0.7)
        x = (x - 0.5) * k + 0.5
    elif kind == "colour":
        if p.get("hue"):
            x = hue_rotate(x, p["hue"] * 180)
        lum = (x @ np.array([0.2126, 0.7152, 0.0722], np.float32))[..., None]
        x = lum + (x - lum) * (1 + p.get("saturation", 0))
        light = p.get("lightness", 0)
        if light:
            x = x + (1 - x) * light * 0.8 if light > 0 else x * (1 + light * 0.8)
    elif kind == "levels":
        lo, hi = p.get("black", 0.0), p.get("white", 1.0)                  # 0..1
        gamma = 2.0 ** (-p.get("gamma", 0.0) * 1.5)
        x = np.clip((x - lo) / max(1e-3, hi - lo), 0, 1) ** gamma
    elif kind == "bw":
        grey = (x @ np.array([0.3 + p.get("reds", 0) * 0.3, 0.59 + p.get("greens", 0) * 0.3, 0.11 + p.get("blues", 0) * 0.3], np.float32))[..., None]
        x = np.repeat(grey, 3, axis=2)
    elif kind == "invert":
        x = 1 - x
    elif kind == "curves":
        x = apply_curves(x, p.get("curves") or {})
    elif kind == "warmth":
        w = p.get("warmth", 0) * 0.15
        x = x * np.array([1 + w, 1, 1 - w], np.float32)
    elif kind == "posterize":
        n = max(2, int(2 + (p.get("levels", 0.3) + 1) * 7))
        x = np.round(x * (n - 1)) / (n - 1)
    return np.clip(x, 0, 1)


ADJUST_PARAMS = {"light": [("brightness", "Brightness"), ("contrast", "Contrast")], "colour": [("hue", "Hue"), ("saturation", "Saturation"), ("lightness", "Lightness")],
                 "levels": [("black", "Black point"), ("gamma", "Midtones"), ("white", "White point")], "bw": [("reds", "Reds"), ("greens", "Greens"), ("blues", "Blues")],
                 "invert": [], "warmth": [("warmth", "Warmth")], "posterize": [("levels", "Levels")], "curves": []}
ADJUST_DEFAULTS = {"levels": {"black": 0.0, "white": 1.0, "gamma": 0.0}, "posterize": {"levels": -0.4},
                   "curves": {"curves": {"rgb": [[0, 0], [0.25, 0.2], [0.75, 0.82], [1, 1]]}}}


def apply_adjust_image(below: QImage, kind: str, params: dict) -> QImage:
    arr = image_to_array(below).astype(np.float32) / 255.0
    rgb, a = arr[..., :3], arr[..., 3:4]
    safe = np.where(a > 0, rgb, 0)
    out = adjust_array(safe, kind, params)
    res = np.concatenate([out, a], axis=2)
    return array_to_image((res * 255 + 0.5).astype(np.uint8))


FILTERS = {"blur": "Blur", "sharpen": "Sharpen", "noise": "Add Noise", "pixelate": "Pixelate", "emboss": "Emboss", "edges": "Find Edges",
           "invert": "Invert", "desaturate": "Desaturate", "posterize": "Posterize", "autolevels": "Auto Levels", "motion": "Motion Blur"}


def filter_array(rgba: np.ndarray, name: str, amount: float) -> np.ndarray:
    """A filter on the whole of an RGBA picture (Pillow does the convolutions). amount is 0..1."""
    from PIL import Image, ImageFilter, ImageOps
    img = Image.fromarray(rgba, "RGBA")
    if name == "blur":
        img = img.filter(ImageFilter.GaussianBlur(radius=0.5 + amount * 30))
    elif name == "sharpen":
        img = img.filter(ImageFilter.UnsharpMask(radius=2 + amount * 3, percent=int(60 + amount * 240), threshold=2))
    elif name == "motion":
        n = max(3, int(3 + amount * 40)) | 1
        k = [0.0] * (n * n)
        for i in range(n):
            k[(n // 2) * n + i] = 1.0
        if n > 5:                                                    # Pillow's kernels stop at 5×5: blur sideways by shifting
            arr = np.asarray(img).astype(np.float32)
            acc = np.zeros_like(arr)
            for i in range(-(n // 2), n // 2 + 1):
                acc += np.roll(arr, i, axis=1)
            return np.clip(acc / n, 0, 255).astype(np.uint8)
        img = img.filter(ImageFilter.Kernel((n, n), k, scale=n))
    elif name == "noise":
        arr = np.asarray(img).astype(np.float32)
        noise = np.random.default_rng(int(time.time())).normal(0, 1, arr.shape[:2] + (1,)) * (4 + amount * 60)
        arr[..., :3] += noise
        return np.clip(arr, 0, 255).astype(np.uint8)
    elif name == "pixelate":
        side = max(2, int(2 + amount * 60))
        w, h = img.size
        img = img.resize((max(1, w // side), max(1, h // side)), Image.Resampling.BOX).resize((w, h), Image.Resampling.NEAREST)
    elif name == "emboss":
        a = img.getchannel("A")
        img = img.convert("RGB").filter(ImageFilter.EMBOSS).convert("RGBA")
        img.putalpha(a)
    elif name == "edges":
        a = img.getchannel("A")
        img = ImageOps.invert(img.convert("RGB").filter(ImageFilter.FIND_EDGES)).convert("RGBA")
        img.putalpha(a)
    elif name in ("invert", "desaturate", "posterize", "autolevels"):
        arr = np.asarray(img).astype(np.float32) / 255
        rgb = arr[..., :3]
        if name == "invert":
            rgb = 1 - rgb
        elif name == "desaturate":
            rgb = np.repeat((rgb @ np.array([0.3, 0.59, 0.11], np.float32))[..., None], 3, axis=2)
        elif name == "posterize":
            n = max(2, int(2 + (1 - amount) * 10))
            rgb = np.round(rgb * (n - 1)) / (n - 1)
        else:
            seen = rgb[arr[..., 3] > 0.05] if (arr[..., 3] > 0.05).any() else rgb.reshape(-1, 3)
            lo, hi = np.percentile(seen, 0.5, axis=0), np.percentile(seen, 99.5, axis=0)
            rgb = np.clip((rgb - lo) / np.maximum(1e-3, hi - lo), 0, 1)
        arr[..., :3] = rgb
        return (np.clip(arr, 0, 1) * 255 + 0.5).astype(np.uint8)
    return np.asarray(img).copy()


# ------------------------------------------------------------------------------------------- filling and choosing by colour
def flood(ok: np.ndarray, x: int, y: int) -> np.ndarray:
    """The connected part of `ok` (a h×w bool array) that holds (x, y): a scanline fill, row runs at a time."""
    h, w = ok.shape
    out = np.zeros_like(ok)
    if not (0 <= x < w and 0 <= y < h) or not ok[y, x]:
        return out
    stack = [(x, y)]
    while stack:
        x, y = stack.pop()
        if out[y, x] or not ok[y, x]:
            continue
        row = ok[y]
        left = row[:x + 1][::-1]
        l = x - (int(np.argmin(left)) if not left.all() else len(left)) + 1
        right = row[x:]
        r = x + (int(np.argmin(right)) if not right.all() else len(right)) - 1
        out[y, l:r + 1] = True
        for ny in (y - 1, y + 1):
            if 0 <= ny < h:
                seg = ok[ny, l:r + 1] & ~out[ny, l:r + 1]
                if seg.any():
                    d = np.diff(np.concatenate(([False], seg)).astype(np.int8))
                    for s0 in np.nonzero(d == 1)[0]:
                        stack.append((l + int(s0), ny))
    return out


def similar(rgba: np.ndarray, x: int, y: int, tolerance: float) -> np.ndarray:
    """Pixels close in colour (and transparency) to the one at (x, y). tolerance 0..1."""
    ref = rgba[y, x].astype(np.int16)
    diff = np.abs(rgba.astype(np.int16) - ref).max(axis=2)
    return diff <= int(tolerance * 255)


# ------------------------------------------------------------------------------------------- the document
def new_layer(kind: str, name: str, w: int = 0, h: int = 0, fill=None) -> dict:
    layer = {"id": uuid.uuid4().hex[:10], "name": name, "kind": kind, "visible": True, "locked": False, "opacity": 1.0, "blend": "normal",
             "mask": None, "maskOn": True, "v": 0}
    if kind == "pixel":
        layer["image"] = new_image(w, h, fill)
    elif kind == "vector":
        layer["shapes"] = []
    elif kind == "adjust":
        layer["adjust"] = "light"
        layer["params"] = {}
    return layer


def copy_layer(layer: dict) -> dict:
    """A copy that shares pictures until one side paints (QImage copies only when written to)."""
    out = dict(layer)
    if "image" in layer:
        out["image"] = QImage(layer["image"])
    if layer.get("mask") is not None:
        out["mask"] = QImage(layer["mask"])
    if "shapes" in layer:
        out["shapes"] = json.loads(json.dumps(layer["shapes"]))
    if "params" in layer:
        out["params"] = dict(layer["params"])
    return out


class Document:
    def __init__(self, w: int, h: int, background="#FFFFFF"):
        self.w, self.h = int(w), int(h)
        self.layers = []
        if background is not None:
            self.layers.append(new_layer("pixel", "Background", w, h, background))
        else:
            self.layers.append(new_layer("pixel", "Layer 1", w, h))
        self.active = self.layers[-1]["id"]
        self.selection = None                                   # an image whose alpha is how chosen each pixel is
        self.path = ""
        self.dpi = 72
        self.version = 0
        self._vector_cache = {}
        self._mask_cache = {}

    # -------------------------------------------------------------- finding layers
    def layer(self, ident: str = None) -> dict:
        ident = ident or self.active
        return next((l for l in self.layers if l["id"] == ident), self.layers[-1] if self.layers else None)

    def index(self, ident: str) -> int:
        return next((i for i, l in enumerate(self.layers) if l["id"] == ident), -1)

    def touch(self, layer: dict = None) -> None:
        self.version += 1
        if layer is not None:
            layer["v"] = layer.get("v", 0) + 1

    # -------------------------------------------------------------- drawing it all
    def layer_image(self, layer: dict, extra=None) -> QImage:
        """What one layer looks like on its own (vector layers are drawn here; their picture is kept until they change)."""
        if layer["kind"] == "pixel":
            img = layer["image"]
            if extra is not None:
                img = extra(img)
        elif layer["kind"] == "vector":
            key = (layer["id"], layer.get("v", 0), self.w, self.h)
            img = self._vector_cache.get(layer["id"])
            if img is None or img[0] != key or extra is not None:
                canvas = new_image(self.w, self.h)
                p = QPainter(canvas)
                p.setRenderHint(QPainter.RenderHint.Antialiasing)
                p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
                for s in layer["shapes"]:
                    if not s.get("hidden"):
                        paint_shape(p, s)
                p.end()
                if extra is not None:
                    return self._masked(layer, extra(canvas))
                self._vector_cache[layer["id"]] = (key, canvas)
                img = (key, canvas)
            img = img[1]
        else:
            return None
        return self._masked(layer, img)

    def _masked(self, layer: dict, img: QImage) -> QImage:
        if layer.get("mask") is None or not layer.get("maskOn", True):
            return img
        out = img.copy()
        p = QPainter(out)
        p.setCompositionMode(CM.CompositionMode_DestinationIn)
        p.drawImage(0, 0, layer["mask"])
        p.end()
        return out

    def composite(self, live=None, upto: int = None) -> QImage:
        """Every visible layer, bottom up. `live` = (layer id, function(image) → image) shows a stroke in progress."""
        out = new_image(self.w, self.h)
        for i, layer in enumerate(self.layers):
            if upto is not None and i >= upto:
                break
            if not layer["visible"]:
                continue
            extra = live[1] if live and live[0] == layer["id"] else None
            if layer["kind"] == "adjust":
                adjusted = apply_adjust_image(out, layer["adjust"], layer.get("params") or {})
                if layer.get("mask") is not None and layer.get("maskOn", True):
                    adjusted = self._masked(layer, adjusted)
                p = QPainter(out)
                p.setOpacity(layer["opacity"])
                p.drawImage(0, 0, adjusted)
                p.end()
                continue
            img = self.layer_image(layer, extra)
            p = QPainter(out)
            p.setOpacity(layer["opacity"])
            p.setCompositionMode(BLENDS.get(layer["blend"], CM.CompositionMode_SourceOver))
            p.drawImage(0, 0, img)
            p.end()
        return out

    def flattened(self, background=None) -> QImage:
        out = self.composite()
        if background:
            under = new_image(self.w, self.h, background)
            p = QPainter(under)
            p.drawImage(0, 0, out)
            p.end()
            return under
        return out

    # -------------------------------------------------------------- the whole document as data (for undo)
    def snapshot(self) -> dict:
        return {"w": self.w, "h": self.h, "layers": [copy_layer(l) for l in self.layers], "active": self.active,
                "selection": QImage(self.selection) if self.selection is not None else None}

    def restore(self, snap: dict) -> None:
        self.w, self.h = snap["w"], snap["h"]
        self.layers = [copy_layer(l) for l in snap["layers"]]
        for l in self.layers:
            l["v"] = l.get("v", 0) + 1000                        # vector pictures are drawn afresh
        self.active = snap["active"] if any(l["id"] == snap["active"] for l in self.layers) else self.layers[-1]["id"]
        self.selection = QImage(snap["selection"]) if snap["selection"] is not None else None
        self.touch()

    # -------------------------------------------------------------- the selection
    def selection_alpha(self) -> np.ndarray:
        if self.selection is None:
            return np.full((self.h, self.w), 255, np.uint8)
        return alpha_of(self.selection)

    def selection_box(self) -> QRect:
        if self.selection is None:
            return QRect(0, 0, self.w, self.h)
        a = alpha_of(self.selection)
        ys, xs = np.nonzero(a > 8)
        if not len(xs):
            return QRect()
        return QRect(int(xs.min()), int(ys.min()), int(xs.max() - xs.min() + 1), int(ys.max() - ys.min() + 1))

    def selection_path(self) -> QPainterPath:
        """The outline of the selection, for the marching ants."""
        if self.selection is None:
            return QPainterPath()
        a = alpha_of(self.selection) > 127
        if not a.any():
            return QPainterPath()
        packed = np.packbits(a, axis=1, bitorder="little")
        bpl = packed.shape[1]
        stride = (bpl + 3) // 4 * 4
        buf = np.zeros((self.h, stride), np.uint8)
        buf[:, :bpl] = packed
        mono = QImage(buf.tobytes(), self.w, self.h, stride, QImage.Format.Format_MonoLSB)
        mono.setColorTable([0xFF000000, 0xFFFFFFFF])
        region = QRegion(QBitmap.fromImage(mono.copy()))
        path = QPainterPath()
        path.addRegion(region)
        return path.simplified()

    # -------------------------------------------------------------- reading and writing
    def manifest(self) -> dict:
        out = {"format": "huginn-easel", "version": 1, "w": self.w, "h": self.h, "dpi": self.dpi, "active": self.active, "layers": []}
        for l in self.layers:
            entry = {k: l[k] for k in ("id", "name", "kind", "visible", "locked", "opacity", "blend", "maskOn")}
            if l["kind"] == "vector":
                entry["shapes"] = l["shapes"]
            if l["kind"] == "adjust":
                entry["adjust"], entry["params"] = l["adjust"], l.get("params") or {}
            entry["hasMask"] = l.get("mask") is not None
            out["layers"].append(entry)
        return out

    def save_easel(self, path: str) -> None:
        part = path + ".saving"
        with zipfile.ZipFile(part, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("mimetype", "application/x-huginn-easel", compress_type=zipfile.ZIP_STORED)
            z.writestr("manifest.json", json.dumps(self.manifest(), indent=1))
            for l in self.layers:
                if l["kind"] == "pixel":
                    z.writestr(f"layers/{l['id']}.png", png_bytes(l["image"]), compress_type=zipfile.ZIP_STORED)
                if l.get("mask") is not None:
                    z.writestr(f"masks/{l['id']}.png", png_bytes(l["mask"]), compress_type=zipfile.ZIP_STORED)
            thumb = self.flattened().scaled(512, 512, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            z.writestr("Thumbnails/thumbnail.png", png_bytes(thumb), compress_type=zipfile.ZIP_STORED)
        os.replace(part, path)
        self.path = path

    @classmethod
    def load_easel(cls, path: str) -> "Document":
        with zipfile.ZipFile(path) as z:
            m = json.loads(z.read("manifest.json"))
            if m.get("format") != "huginn-easel":
                raise ValueError("That isn't an Easel picture.")
            doc = cls(m["w"], m["h"], None)
            doc.layers, doc.dpi = [], int(m.get("dpi", 72))
            names = set(z.namelist())
            for e in m["layers"]:
                layer = new_layer(e["kind"], e.get("name", "Layer"), doc.w, doc.h)
                layer.update({k: e[k] for k in ("id", "visible", "locked", "opacity", "blend", "maskOn") if k in e})
                if e["kind"] == "pixel" and f"layers/{e['id']}.png" in names:
                    img = image_from_bytes(z.read(f"layers/{e['id']}.png"))
                    layer["image"] = img if img.size() == QSize(doc.w, doc.h) else _fit(img, doc.w, doc.h)
                if e["kind"] == "vector":
                    layer["shapes"] = e.get("shapes", [])
                if e["kind"] == "adjust":
                    layer["adjust"], layer["params"] = e.get("adjust", "light"), e.get("params", {})
                if e.get("hasMask") and f"masks/{e['id']}.png" in names:
                    layer["mask"] = image_from_bytes(z.read(f"masks/{e['id']}.png"))
                doc.layers.append(layer)
            if not doc.layers:
                doc.layers.append(new_layer("pixel", "Layer 1", doc.w, doc.h))
            doc.active = m.get("active") if any(l["id"] == m.get("active") for l in doc.layers) else doc.layers[-1]["id"]
        doc.path = path
        return doc

    def save_ora(self, path: str) -> None:
        """OpenRaster: vector layers go in as pictures (other programs can't edit Easel's shapes)."""
        part = path + ".saving"
        stack = ET.Element("image", {"w": str(self.w), "h": str(self.h), "version": "0.0.5"})
        top = ET.SubElement(stack, "stack")
        with zipfile.ZipFile(part, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("mimetype", "image/openraster", compress_type=zipfile.ZIP_STORED)
            for i, l in enumerate(reversed(self.layers)):           # OpenRaster lists the top layer first
                img = self.layer_image(l) if l["kind"] != "adjust" else None
                if img is None:
                    continue
                name = f"data/layer{i}.png"
                z.writestr(name, png_bytes(img), compress_type=zipfile.ZIP_STORED)
                ET.SubElement(top, "layer", {"name": l["name"], "src": name, "x": "0", "y": "0", "opacity": f"{l['opacity']:.3f}",
                                              "visibility": "visible" if l["visible"] else "hidden", "composite-op": ORA_OPS.get(l["blend"], "svg:src-over")})
            z.writestr("stack.xml", ET.tostring(stack, encoding="unicode"))
            flat = self.flattened()
            z.writestr("mergedimage.png", png_bytes(flat), compress_type=zipfile.ZIP_STORED)
            z.writestr("Thumbnails/thumbnail.png", png_bytes(flat.scaled(256, 256, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)),
                       compress_type=zipfile.ZIP_STORED)
        os.replace(part, path)

    @classmethod
    def load_ora(cls, path: str) -> "Document":
        ops = {v: k for k, v in ORA_OPS.items()}
        with zipfile.ZipFile(path) as z:
            root = ET.fromstring(z.read("stack.xml"))
            w, h = int(root.get("w")), int(root.get("h"))
            doc = cls(w, h, None)
            doc.layers = []

            def walk(stack, hidden=False):
                for el in stack:
                    if el.tag == "stack":
                        walk(el, hidden or el.get("visibility") == "hidden")
                    elif el.tag == "layer" and el.get("src", "").lower().endswith(".png"):
                        img = image_from_bytes(z.read(el.get("src")))
                        layer = new_layer("pixel", el.get("name", "Layer"), w, h)
                        p = QPainter(layer["image"])
                        p.drawImage(int(float(el.get("x", 0))), int(float(el.get("y", 0))), img)
                        p.end()
                        layer["opacity"] = float(el.get("opacity", 1))
                        layer["visible"] = el.get("visibility", "visible") != "hidden" and not hidden
                        layer["blend"] = ops.get(el.get("composite-op", "svg:src-over"), "normal")
                        doc.layers.insert(0, layer)
            walk(root.find("stack") if root.find("stack") is not None else root)
        if not doc.layers:
            doc.layers.append(new_layer("pixel", "Layer 1", w, h))
        doc.active = doc.layers[-1]["id"]
        return doc

    @classmethod
    def from_picture(cls, path: str) -> "Document":
        if path.lower().endswith(".svg"):
            from PySide6.QtSvg import QSvgRenderer
            r = QSvgRenderer(path)
            if not r.isValid():
                raise ValueError("That SVG couldn't be read.")
            size = r.defaultSize()
            w, h = max(1, size.width()), max(1, size.height())
            if max(w, h) < 1024:                                     # draw small drawings bigger, so they stay sharp
                k = 2048 / max(w, h)
                w, h = int(w * k), int(h * k)
            doc = cls(w, h, None)
            p = QPainter(doc.layers[0]["image"])
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            r.render(p, QRectF(0, 0, w, h))
            p.end()
            doc.layers[0]["name"] = Path(path).stem
            return doc
        from PySide6.QtGui import QImageReader
        reader = QImageReader(path)
        reader.setAutoTransform(True)
        img = reader.read()
        if img.isNull():
            raise ValueError(reader.errorString() or "That picture couldn't be read.")
        img = img.convertToFormat(FMT)
        doc = cls(img.width(), img.height(), None)
        doc.layers[0]["image"] = img
        doc.layers[0]["name"] = "Background"
        try:
            doc.dpi = round(img.dotsPerMeterX() * 0.0254) or 72
        except Exception:                                            # noqa: BLE001
            pass
        return doc

    def export(self, path: str, quality: int = 92, background: str = "") -> None:
        ext = Path(path).suffix.lower()
        if ext == ".svg":
            self.export_svg(path)
            return
        if ext == ".psd":
            write_psd(self, path)
            return
        if ext == ".pdf":
            self.export_pdf(path)
            return
        img = self.flattened(background or ("#FFFFFF" if ext in (".jpg", ".jpeg", ".bmp") else None))
        if ext in (".jpg", ".jpeg"):
            img = img.convertToFormat(QImage.Format.Format_RGB32)
        part = str(Path(path).with_name(f".{Path(path).name}.saving{ext}"))
        if not img.save(part, None, quality):
            raise OSError(f"Couldn't write {Path(path).name}.")
        os.replace(part, path)

    def _paint_vectors(self, p: QPainter) -> None:
        """Each layer in turn: shapes as shapes, pictures as pictures (for SVG and PDF)."""
        for layer in self.layers:
            if not layer["visible"] or layer["kind"] == "adjust":
                continue
            p.save()
            p.setOpacity(layer["opacity"])
            if layer["kind"] == "vector" and (layer.get("mask") is None or not layer.get("maskOn", True)) and layer["blend"] == "normal":
                p.setRenderHint(QPainter.RenderHint.Antialiasing)
                for s in layer["shapes"]:
                    if not s.get("hidden"):
                        paint_shape(p, s)
            else:
                p.drawImage(0, 0, self.layer_image(layer))
            p.restore()

    def export_svg(self, path: str) -> None:
        from PySide6.QtSvg import QSvgGenerator
        gen = QSvgGenerator()
        part = str(Path(path).with_name(f".{Path(path).name}.saving.svg"))
        gen.setFileName(part)
        gen.setSize(QSize(self.w, self.h))
        gen.setViewBox(QRect(0, 0, self.w, self.h))
        gen.setTitle(Path(path).stem)
        gen.setDescription("Made in Huginn Easel")
        p = QPainter(gen)
        self._paint_vectors(p)
        p.end()
        os.replace(part, path)

    def export_pdf(self, path: str) -> None:
        part = str(Path(path).with_name(f".{Path(path).name}.saving.pdf"))
        writer = QPdfWriter(part)
        writer.setResolution(72)
        writer.setPageSize(QPageSize(QSizeF(self.w, self.h), QPageSize.Unit.Point))
        from PySide6.QtGui import QPageLayout
        from PySide6.QtCore import QMarginsF
        writer.setPageMargins(QMarginsF(0, 0, 0, 0), QPageLayout.Unit.Point)
        writer.setCreator("Huginn Easel")
        p = QPainter(writer)
        self._paint_vectors(p)
        p.end()
        os.replace(part, path)


def _fit(img: QImage, w: int, h: int) -> QImage:
    out = new_image(w, h)
    p = QPainter(out)
    p.drawImage(0, 0, img)
    p.end()
    return out


def open_any(path: str) -> Document:
    low = path.lower()
    if low.endswith(".psd"):
        doc = read_psd(path)
        doc.path = ""
        return doc
    if low.endswith(".easel"):
        return Document.load_easel(path)
    if low.endswith(".ora"):
        doc = Document.load_ora(path)
        doc.path = ""
        return doc
    doc = Document.from_picture(path)
    doc.path = ""
    return doc


# ------------------------------------------------------------------------------------------- brushes
BRUSHES = {"round": {"name": "Round", "size": 24, "hardness": 0.8, "flow": 1.0, "spacing": 0.12, "scatter": 0.0},
           "soft": {"name": "Soft", "size": 60, "hardness": 0.0, "flow": 0.6, "spacing": 0.1, "scatter": 0.0},
           "pencil": {"name": "Pencil", "size": 3, "hardness": 1.0, "flow": 1.0, "spacing": 0.05, "scatter": 0.0},
           "ink": {"name": "Ink", "size": 8, "hardness": 0.95, "flow": 1.0, "spacing": 0.06, "scatter": 0.0},
           "airbrush": {"name": "Airbrush", "size": 120, "hardness": 0.0, "flow": 0.08, "spacing": 0.06, "scatter": 0.0},
           "chalk": {"name": "Chalk", "size": 30, "hardness": 0.6, "flow": 0.5, "spacing": 0.2, "scatter": 0.35},
           "marker": {"name": "Marker", "size": 40, "hardness": 0.9, "flow": 0.35, "spacing": 0.05, "scatter": 0.0}}


def dab(size: float, hardness: float, colour_: QColor) -> QImage:
    """One stamp of the brush: a disc, soft at the edge by (1 - hardness)."""
    side = max(1, int(math.ceil(size)) + 2)
    img = new_image(side, side)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    c = QColor(colour_)
    r = size / 2
    if hardness >= 0.98 or size <= 2:
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(c)
        p.drawEllipse(QPointF(side / 2, side / 2), r, r)
    else:
        g = QRadialGradient(QPointF(side / 2, side / 2), r)
        g.setColorAt(0, c)
        g.setColorAt(max(0.0, min(0.99, hardness)), c)
        edge = QColor(c)
        edge.setAlpha(0)
        g.setColorAt(1, edge)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(g))
        p.drawEllipse(QPointF(side / 2, side / 2), r, r)
    p.end()
    return img


# ------------------------------------------------------------------------------------------- healing
def heal_patch(dst: np.ndarray, src: np.ndarray, radius: float) -> np.ndarray:
    """Healing: the source's texture with the destination's colour and light. Both are float RGB(A) arrays of the
    same size; the detail is what's left after blurring, so it carries over and the tone underneath does not."""
    r = max(1, int(round(radius)))

    def box(a, axis):
        """A running mean along one axis (edges repeat), done with cumulative sums so it costs the same at any size."""
        pad = [(0, 0)] * a.ndim
        pad[axis] = (r + 1, r)
        c = np.cumsum(np.pad(a, pad, mode="edge"), axis=axis, dtype=np.float64)
        hi = np.take(c, np.arange(2 * r + 1, c.shape[axis]), axis=axis)
        lo = np.take(c, np.arange(0, c.shape[axis] - 2 * r - 1), axis=axis)
        return ((hi - lo) / (2 * r + 1)).astype(np.float32)

    def blur(a):                                                    # three box blurs are very nearly a Gaussian
        for _ in range(3):
            a = box(box(a, 0), 1)
        return a
    return np.clip(blur(dst) + (src - blur(src)), 0, 255)


def best_spot_source(rgba: np.ndarray, cx: float, cy: float, size: float) -> tuple:
    """For spot healing: the nearby patch, one or two brush widths away, that looks most like the area round the spot."""
    h, w = rgba.shape[:2]
    r = max(4, int(size * 0.75))
    ring = []
    for k in (1.6, 2.4):
        for i in range(8):
            a = i * math.pi / 4
            ring.append((cx + math.cos(a) * size * k, cy + math.sin(a) * size * k))
    x0, y0 = int(cx) - r, int(cy) - r

    def patch(x, y):
        xa, ya = int(x) - r, int(y) - r
        if xa < 0 or ya < 0 or xa + 2 * r >= w or ya + 2 * r >= h:
            return None
        return rgba[ya:ya + 2 * r, xa:xa + 2 * r, :3].astype(np.float32)
    here = patch(cx, cy)
    if here is None:
        return ring[0]
    yy, xx = np.mgrid[0:2 * r, 0:2 * r]
    edge = (np.hypot(xx - r, yy - r) > r * 0.7)[..., None]           # compare the edges: the middle is the blemish
    best, choice = None, ring[0]
    for x, y in ring:
        other = patch(x, y)
        if other is None:
            continue
        score = float((np.abs(other - here) * edge).mean() + other.std(axis=(0, 1)).mean() * 0.15)
        if best is None or score < best:
            best, choice = score, (x, y)
    del x0, y0
    return choice


# ------------------------------------------------------------------------------------------- Photoshop files
PSD_BLENDS = {"norm": "normal", "mul ": "multiply", "scrn": "screen", "over": "overlay", "dark": "darken", "lite": "lighten", "div ": "dodge",
              "idiv": "burn", "hLit": "hard", "sLit": "soft", "diff": "difference", "smud": "exclusion", "lddg": "add", "pass": "normal"}
PSD_KEYS = {v: k for k, v in PSD_BLENDS.items() if k != "pass"}


def _unpack_rle(data: bytes, pos: int, rows: int, width: int) -> tuple:
    """PackBits rows as Photoshop writes them: a table of row lengths, then the rows."""
    counts = np.frombuffer(data, ">u2", rows, pos).astype(int)
    pos += rows * 2
    out = np.zeros((rows, width), np.uint8)
    for y, n in enumerate(counts):
        row, i, end, x = data, pos, pos + n, 0
        line = bytearray()
        while i < end and len(line) < width:
            b = row[i]
            i += 1
            if b < 128:
                line += row[i:i + b + 1]
                i += b + 1
            elif b > 128:
                line += bytes([row[i]]) * (257 - b)
                i += 1
        out[y, :min(width, len(line))] = np.frombuffer(bytes(line[:width]), np.uint8)
        pos = end
    del x
    return out, pos


def _channel(data: bytes, pos: int, length: int, rows: int, width: int) -> np.ndarray:
    comp = int.from_bytes(data[pos:pos + 2], "big")
    body = pos + 2
    if rows <= 0 or width <= 0:
        return np.zeros((max(rows, 0), max(width, 0)), np.uint8)
    if comp == 0:
        return np.frombuffer(data, np.uint8, rows * width, body).reshape(rows, width).copy()
    if comp == 1:
        return _unpack_rle(data, body, rows, width)[0]
    raise ValueError("This Photoshop file packs its pictures in a way Easel can't read yet (ZIP compression).")


def read_psd(path: str) -> "Document":
    """Layers from a Photoshop file: 8-bit RGB or greyscale, with names, opacity, blend modes and visibility. Groups
    come in as their layers, one after another; text and smart objects come in as the pictures Photoshop saved."""
    data = Path(path).read_bytes()
    if data[:4] != b"8BPS" or int.from_bytes(data[4:6], "big") != 1:
        raise ValueError("That isn't a Photoshop file Easel can read (big PSB files aren't supported yet).")
    channels = int.from_bytes(data[12:14], "big")
    h, w = int.from_bytes(data[14:18], "big"), int.from_bytes(data[18:22], "big")
    depth, mode = int.from_bytes(data[22:24], "big"), int.from_bytes(data[24:26], "big")
    if depth != 8 or mode not in (1, 3):
        raise ValueError("Easel reads 8-bit RGB and greyscale Photoshop files; this one is " + ({16: "16-bit", 32: "32-bit"}.get(depth, f"{depth}-bit")) + " or another colour mode.")
    pos = 26
    pos += 4 + int.from_bytes(data[pos:pos + 4], "big")              # colour mode data
    pos += 4 + int.from_bytes(data[pos:pos + 4], "big")              # image resources
    lm_len = int.from_bytes(data[pos:pos + 4], "big")
    lm_end = pos + 4 + lm_len
    doc = Document(w, h, None)
    doc.layers = []
    if lm_len:
        li_len = int.from_bytes(data[pos + 4:pos + 8], "big")
        q = pos + 8
        if li_len:
            count = abs(int.from_bytes(data[q:q + 2], "big", signed=True))
            q += 2
            records = []
            for _ in range(count):
                top, left, bottom, right = (int.from_bytes(data[q + i * 4:q + i * 4 + 4], "big", signed=True) for i in range(4))
                q += 16
                nch = int.from_bytes(data[q:q + 2], "big")
                q += 2
                chans = []
                for _ in range(nch):
                    chans.append((int.from_bytes(data[q:q + 2], "big", signed=True), int.from_bytes(data[q + 2:q + 6], "big")))
                    q += 6
                key = data[q + 4:q + 8].decode("latin-1")
                opacity, flags = data[q + 8], data[q + 10]
                extra = int.from_bytes(data[q + 12:q + 16], "big")
                ex, ex_end = q + 16, q + 16 + extra
                ex += 4 + int.from_bytes(data[ex:ex + 4], "big")         # layer mask data
                ex += 4 + int.from_bytes(data[ex:ex + 4], "big")         # blending ranges
                n = data[ex]
                name = data[ex + 1:ex + 1 + n].decode("latin-1", "replace")
                ex += ((n + 1 + 3) // 4) * 4
                divider = 0
                while ex + 12 <= ex_end and data[ex:ex + 4] in (b"8BIM", b"8B64"):
                    k, ln = data[ex + 4:ex + 8], int.from_bytes(data[ex + 8:ex + 12], "big")
                    body = data[ex + 12:ex + 12 + ln]
                    if k == b"luni" and len(body) >= 4:
                        chars = int.from_bytes(body[:4], "big")
                        name = body[4:4 + chars * 2].decode("utf-16-be", "replace").rstrip("\x00")
                    elif k in (b"lsct", b"lsdk") and len(body) >= 4:
                        divider = int.from_bytes(body[:4], "big")
                    ex += 12 + ln + (ln % 2)
                records.append({"rect": (top, left, bottom, right), "chans": chans, "blend": PSD_BLENDS.get(key, "normal"), "opacity": opacity / 255,
                                "visible": not (flags & 2), "name": name or "Layer", "divider": divider})
                q = ex_end
            for rec in records:                                      # then each layer's pictures, channel by channel
                top, left, bottom, right = rec["rect"]
                rh, rw = bottom - top, right - left
                planes = {}
                for cid, length in rec["chans"]:
                    if cid in (0, 1, 2, -1) or (mode == 1 and cid == 0):
                        try:
                            planes[cid] = _channel(data, q, length, rh, rw) if cid != -2 else None
                        except ValueError:
                            raise
                    q += length
                if rec["divider"] in (1, 2, 3) or rh <= 0 or rw <= 0:
                    continue                                         # the start or end of a group, or an empty layer
                if mode == 1:
                    grey = planes.get(0, np.zeros((rh, rw), np.uint8))
                    rgba = np.dstack([grey, grey, grey, planes.get(-1, np.full((rh, rw), 255, np.uint8))])
                else:
                    rgba = np.dstack([planes.get(0, np.zeros((rh, rw), np.uint8)), planes.get(1, np.zeros((rh, rw), np.uint8)),
                                      planes.get(2, np.zeros((rh, rw), np.uint8)), planes.get(-1, np.full((rh, rw), 255, np.uint8))])
                layer = new_layer("pixel", rec["name"], w, h)
                p = QPainter(layer["image"])
                p.drawImage(left, top, array_to_image(rgba))
                p.end()
                layer.update(opacity=rec["opacity"], visible=rec["visible"], blend=rec["blend"])
                doc.layers.append(layer)
    if not doc.layers:                                               # no layers: the merged picture at the end of the file
        q = lm_end
        comp = int.from_bytes(data[q:q + 2], "big")
        q += 2
        planes = []
        if comp == 1:
            counts = np.frombuffer(data, ">u2", channels * h, q).astype(int)
            q += channels * h * 2
            for c in range(channels):
                plane = np.zeros((h, w), np.uint8)
                for y in range(h):
                    n = counts[c * h + y]
                    row = _unpack_rle(n.to_bytes(2, "big") + data[q:q + n], 0, 1, w)[0]
                    plane[y] = row[0]
                    q += n
                planes.append(plane)
        else:
            for c in range(channels):
                planes.append(np.frombuffer(data, np.uint8, w * h, q + c * w * h).reshape(h, w))
        if mode == 1:
            planes = [planes[0]] * 3 + planes[1:2]
        rgba = np.dstack(planes[:3] + [planes[3] if len(planes) > 3 else np.full((h, w), 255, np.uint8)])
        layer = new_layer("pixel", "Background", w, h)
        layer["image"] = array_to_image(rgba)
        doc.layers.append(layer)
    doc.active = doc.layers[-1]["id"]
    return doc


def write_psd(doc: "Document", path: str) -> None:
    """A Photoshop file with every pixel and vector layer as a layer (shapes and type become pictures, since only
    Photoshop's own text engine could keep them editable), plus the whole picture flattened for quick previews."""
    import struct
    out = bytearray(b"8BPS" + struct.pack(">H6xHIIHH", 1, 4, doc.h, doc.w, 8, 3))
    out += struct.pack(">I", 0)                                       # colour mode data
    res = b"8BIM" + struct.pack(">H", 1005) + b"\x00\x00" + struct.pack(">I", 16) + struct.pack(">IHHIHH", doc.dpi << 16, 1, 1, doc.dpi << 16, 1, 1)
    out += struct.pack(">I", len(res)) + res                          # the resolution, so print sizes come across
    layers = [l for l in doc.layers if l["kind"] != "adjust"]
    records, pictures = bytearray(), bytearray()
    for l in layers:
        img = doc.layer_image(l)
        rgba = image_to_array(img)
        ys, xs = np.nonzero(rgba[..., 3])
        if len(xs):
            top, left, bottom, right = int(ys.min()), int(xs.min()), int(ys.max()) + 1, int(xs.max()) + 1
        else:
            top = left = bottom = right = 0
        part = rgba[top:bottom, left:right]
        chans = []
        for cid, plane in ((-1, 3), (0, 0), (1, 1), (2, 2)):
            raw = part[..., plane].tobytes() if part.size else b""
            chans.append((cid, b"\x00\x00" + raw))
        name = l["name"].encode("latin-1", "replace")[:255]
        pascal = bytes([len(name)]) + name
        pascal += b"\x00" * ((4 - len(pascal) % 4) % 4)
        uni = l["name"].encode("utf-16-be")
        luni_body = struct.pack(">I", len(l["name"])) + uni
        luni_body += b"\x00" * (len(luni_body) % 2)
        luni = b"8BIM" + b"luni" + struct.pack(">I", len(luni_body)) + luni_body
        extra = struct.pack(">I", 0) + struct.pack(">I", 0) + pascal + luni
        records += struct.pack(">iiiiH", top, left, bottom, right, len(chans))
        for cid, body in chans:
            records += struct.pack(">hI", cid, len(body))
        records += b"8BIM" + PSD_KEYS.get(l["blend"], "norm").encode("latin-1") + bytes([int(round(l["opacity"] * 255)), 0, 0 if l["visible"] else 2, 0])
        records += struct.pack(">I", len(extra)) + extra
        for _, body in chans:
            pictures += body
    info = struct.pack(">h", len(layers)) + records + pictures
    if len(info) % 2:
        info += b"\x00"
    layer_info = struct.pack(">I", len(info)) + info
    out += struct.pack(">I", len(layer_info) + 4) + layer_info + struct.pack(">I", 0)
    flat = image_to_array(doc.flattened())
    out += struct.pack(">H", 0)
    for c in (0, 1, 2, 3):
        out += flat[..., c].tobytes()
    part = path + ".saving"
    Path(part).write_bytes(bytes(out))
    os.replace(part, path)
