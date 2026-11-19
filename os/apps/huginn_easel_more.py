"""Easel, round four: the parts that don't need a window. Layer styles (shadows, glows, outlines, overlays),
the structure of layer groups, smart objects and their filters, the effect brushes (dodge, burn, sponge,
soften, sharpen, smudge) and liquify."""
import json
import math

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QTransform

try:
    import cv2
except ImportError:                                           # the outlines are made with blurs instead
    cv2 = None

FMT = QImage.Format.Format_ARGB32_Premultiplied


def _arr(img: QImage) -> np.ndarray:
    """A premultiplied ARGB32 image as rows × columns × (B, G, R, A) floats 0..1, a copy."""
    img = img.convertToFormat(FMT)
    w, h = img.width(), img.height()
    a = np.frombuffer(img.constBits(), np.uint8, count=img.bytesPerLine() * h).reshape(h, img.bytesPerLine())[:, :w * 4]
    return a.reshape(h, w, 4).astype(np.float32) / 255.0


def _img(a: np.ndarray) -> QImage:
    h, w = a.shape[:2]
    data = np.ascontiguousarray(np.clip(a * 255.0 + 0.5, 0, 255).astype(np.uint8))
    return QImage(data.data, w, h, w * 4, FMT).copy()


def _rgb(colour: str) -> np.ndarray:
    c = QColor(colour or "#000000")
    return np.array([c.blueF(), c.greenF(), c.redF()], np.float32)


# ------------------------------------------------------------------ blurs and outlines
def box_blur(a: np.ndarray, r: int, axis: int) -> np.ndarray:
    """A running mean 2r + 1 wide along one axis (edges repeated)."""
    if r < 1:
        return a
    pad = [(0, 0)] * a.ndim
    pad[axis] = (r + 1, r)
    c = np.cumsum(np.pad(a, pad, mode="edge"), axis=axis, dtype=np.float64)
    n = a.shape[axis]
    hi = np.take(c, np.arange(2 * r + 1, 2 * r + 1 + n), axis=axis)
    lo = np.take(c, np.arange(0, n), axis=axis)
    return ((hi - lo) / (2 * r + 1)).astype(np.float32)


def blur(a: np.ndarray, sigma: float) -> np.ndarray:
    """Very nearly a Gaussian: three box blurs each way."""
    if sigma < 0.4:
        return a
    if cv2 is not None:
        k = int(sigma * 3) * 2 + 1
        return cv2.GaussianBlur(a, (k, k), sigma, borderType=cv2.BORDER_REPLICATE)
    r = max(1, int(round(math.sqrt(12 * sigma * sigma / 3 + 1) / 2)))
    out = a
    for _ in range(3):
        out = box_blur(box_blur(out, r, 0), r, 1)
    return out


def distance_outside(alpha: np.ndarray) -> np.ndarray:
    """How far each pixel is from the shape (0 inside), in pixels."""
    inside = (alpha >= 0.5).astype(np.uint8)
    if cv2 is not None:
        return cv2.distanceTransform(1 - inside, cv2.DIST_L2, 5).astype(np.float32)
    d = np.where(inside > 0, 0.0, 1e6).astype(np.float32)                    # chamfer distance, two passes
    for y in range(d.shape[0]):
        if y:
            d[y] = np.minimum(d[y], d[y - 1] + 1)
    for y in range(d.shape[0] - 2, -1, -1):
        d[y] = np.minimum(d[y], d[y + 1] + 1)
    for x in range(1, d.shape[1]):
        d[:, x] = np.minimum(d[:, x], d[:, x - 1] + 1)
    for x in range(d.shape[1] - 2, -1, -1):
        d[:, x] = np.minimum(d[:, x], d[:, x + 1] + 1)
    return d


def distance_inside(alpha: np.ndarray) -> np.ndarray:
    return distance_outside(1.0 - alpha)


def _shift(a: np.ndarray, dx: float, dy: float) -> np.ndarray:
    """Moved by whole pixels (what goes off the edge is lost; what comes in is empty)."""
    dx, dy = int(round(dx)), int(round(dy))
    out = np.zeros_like(a)
    h, w = a.shape[:2]
    ys, yd = (slice(0, h - dy), slice(dy, h)) if dy >= 0 else (slice(-dy, h), slice(0, h + dy))
    xs, xd = (slice(0, w - dx), slice(dx, w)) if dx >= 0 else (slice(-dx, w), slice(0, w + dx))
    if (ys.stop or h) > (ys.start or 0) and (xs.stop or w) > (xs.start or 0):
        out[yd, xd] = a[ys, xs]
    return out


# ------------------------------------------------------------------ layer styles
STYLES = {
    "shadow": {"name": "Drop shadow", "on": False, "colour": "#000000", "opacity": 0.55, "angle": 120.0, "distance": 12.0, "size": 14.0, "spread": 0.0},
    "glow": {"name": "Outer glow", "on": False, "colour": "#FFE48A", "opacity": 0.75, "size": 18.0, "spread": 0.1},
    "stroke": {"name": "Outline", "on": False, "colour": "#14171C", "opacity": 1.0, "width": 4.0, "where": "outside"},
    "inner": {"name": "Inner shadow", "on": False, "colour": "#000000", "opacity": 0.5, "angle": 120.0, "distance": 6.0, "size": 8.0},
    "overlay": {"name": "Colour overlay", "on": False, "colour": "#E5484D", "opacity": 1.0},
}


def style_of(layer: dict, key: str) -> dict:
    out = {k: v for k, v in STYLES[key].items() if k != "name"}
    out.update((layer.get("fx") or {}).get(key) or {})
    return out


def has_fx(layer: dict) -> bool:
    return any(((layer.get("fx") or {}).get(k) or {}).get("on") for k in STYLES)


def _flat(alpha: np.ndarray, colour: str, opacity: float) -> np.ndarray:
    """A plain colour with this coverage, premultiplied."""
    a = np.clip(alpha * opacity, 0, 1)[..., None]
    return np.concatenate([_rgb(colour)[None, None, :] * a, a], axis=2)


def _over(top: np.ndarray, under: np.ndarray) -> np.ndarray:
    return top + under * (1.0 - top[..., 3:4])


def _atop(top: np.ndarray, base: np.ndarray) -> np.ndarray:
    """top drawn only where base is, base's coverage kept."""
    ab = base[..., 3:4]
    return top * ab + base * (1.0 - top[..., 3:4])


def render_fx(img: QImage, layer: dict) -> QImage:
    """A layer's picture with its styles: shadow, glow and an outside outline under it; the colour overlay, inner
    shadow and an inside outline on it (only where it is)."""
    if not has_fx(layer):
        return img
    base = _arr(img)
    alpha = base[..., 3]
    out = base
    under = np.zeros_like(base)
    s = style_of(layer, "shadow")
    if s["on"]:
        a = alpha
        if s["spread"] > 0:
            a = np.clip(blur(alpha, max(0.5, s["size"] * s["spread"])) * (1 + 4 * s["spread"]), 0, 1)
        ang = math.radians(s["angle"])
        a = _shift(a, -math.cos(ang) * s["distance"], math.sin(ang) * s["distance"])     # the light comes from the angle
        under = _over(under, _flat(blur(a, s["size"] / 2), s["colour"], s["opacity"]))
    g = style_of(layer, "glow")
    if g["on"]:
        a = np.clip(blur(alpha, g["size"] / 2) * (1 + 6 * g["spread"]), 0, 1)
        under = _over(_flat(a, g["colour"], g["opacity"]), under)
    st = style_of(layer, "stroke")
    w = max(0.0, float(st["width"]))
    if st["on"] and w > 0 and st["where"] in ("outside", "centre"):
        reach = w if st["where"] == "outside" else w / 2
        a = np.clip(reach + 1.0 - distance_outside(alpha), 0, 1)              # distances are between pixel centres; the edge is half a pixel in
        a = np.maximum(a, alpha) if st["where"] == "outside" else a
        under = _over(_flat(a, st["colour"], st["opacity"]), under)
    o = style_of(layer, "overlay")
    if o["on"]:
        out = _atop(_flat(np.ones_like(alpha), o["colour"], o["opacity"]), out)
    n = style_of(layer, "inner")
    if n["on"]:
        ang = math.radians(n["angle"])
        hole = 1.0 - _shift(alpha, -math.cos(ang) * n["distance"], math.sin(ang) * n["distance"])   # beyond the edge counts as outside
        a = blur(hole, n["size"] / 2)
        out = _atop(_flat(a, n["colour"], n["opacity"]), out)
    if st["on"] and w > 0 and st["where"] in ("inside", "centre"):
        reach = w if st["where"] == "inside" else w / 2
        a = np.clip(reach + 1.0 - distance_inside(alpha), 0, 1)
        out = _atop(_flat(a, st["colour"], st["opacity"]), out)
    return _img(_over(out, under))


# ------------------------------------------------------------------ layer groups (in a flat list, bottom first)
def ancestors(layers: list, layer: dict) -> list:
    """The groups a layer is in, innermost first."""
    by_id = {l["id"]: l for l in layers}
    out, g = [], layer.get("group")
    while g and g in by_id and len(out) < 64:
        out.append(g)
        g = by_id[g].get("group")
    return out


def tree(layers: list) -> list:
    """The layers as nested lists: a layer, or ("group", header, [what's inside]), bottom first. Membership comes
    from each layer's "group"; order from where they are in the list (a group's place is its header's)."""
    by_id = {l["id"]: l for l in layers}
    kids = {}
    for l in layers:
        g = l.get("group")
        kids.setdefault(g if g in by_id and by_id[g]["kind"] == "group" else None, []).append(l)

    def build(gid, seen):
        out = []
        for l in kids.get(gid, []):
            if l["kind"] == "group":
                if l["id"] in seen:
                    continue
                out.append(("group", l, build(l["id"], seen | {l["id"]})))
            else:
                out.append(l)
        return out
    return build(None, frozenset())


def flatten_tree(items: list) -> list:
    out = []
    for it in items:
        if isinstance(it, tuple):
            out += flatten_tree(it[2])
            out.append(it[1])
        else:
            out.append(it)
    return out


def normalize(layers: list) -> list:
    """The list put back in order: each group's insides just below its header, together."""
    by_id = {l["id"]: l for l in layers}
    for l in layers:                                          # a layer in a group that's gone is in no group
        if l.get("group") and (l["group"] not in by_id or by_id[l["group"]]["kind"] != "group"):
            l["group"] = None
    return flatten_tree(tree(layers))


def span(layers: list, gid: str) -> tuple:
    """(first, header) indices: a group's insides are layers[first:header]."""
    k = next((i for i, l in enumerate(layers) if l["id"] == gid), -1)
    if k < 0:
        return -1, -1
    first = k
    while first > 0 and gid in ancestors(layers, layers[first - 1]):
        first -= 1
    return first, k


def depth(layers: list, layer: dict) -> int:
    return len(ancestors(layers, layer))


# ------------------------------------------------------------------ smart objects
def smart_place(src: QImage, box_x: float, box_y: float) -> dict:
    return {"cx": box_x + src.width() / 2, "cy": box_y + src.height() / 2, "sx": 1.0, "sy": 1.0, "rot": 0.0, "flipx": False, "flipy": False}


def place_matrix(place: dict, w: int, h: int) -> QTransform:
    return (QTransform().translate(place["cx"], place["cy"]).rotate(place.get("rot", 0))
            .scale(place["sx"] * (-1 if place.get("flipx") else 1), place["sy"] * (-1 if place.get("flipy") else 1)).translate(-w / 2, -h / 2))


def smart_render(layer: dict, w: int, h: int, filter_array=None) -> QImage:
    """A smart object as it shows: its original, placed (every transform drawn from the original), then its
    filters in order."""
    src = layer["source"]
    out = QImage(w, h, FMT)
    out.fill(Qt.GlobalColor.transparent)
    p = QPainter(out)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setTransform(place_matrix(layer["place"], src.width(), src.height()))
    p.drawImage(0, 0, src)
    p.end()
    filters = [f for f in layer.get("sfilters") or [] if f.get("on", True)]
    if filters and filter_array is not None:
        from huginn_easel import array_to_image, image_to_array
        arr = image_to_array(out)
        for f in filters:
            arr = filter_array(arr, f["name"], float(f.get("amount", 0.4)))
        out = array_to_image(arr)
    return out


# ------------------------------------------------------------------ the effect brushes
def _luma(bgr: np.ndarray) -> np.ndarray:
    return bgr[..., 2] * 0.2126 + bgr[..., 1] * 0.7152 + bgr[..., 0] * 0.0722


def effect_of(base: QImage, tool: str, strength: float, rng: str = "mid") -> QImage:
    """What the effect brushes paint toward: the whole layer brightened (dodge), darkened (burn), its colour
    taken away (sponge), softened or sharpened. rng: shadows, mid or highlights, as Photoshop's range."""
    a = _arr(base)
    alpha = a[..., 3:4]
    col = np.where(alpha > 1e-4, a[..., :3] / np.maximum(alpha, 1e-4), 0.0)             # straight colour
    k = max(0.0, min(1.0, strength))
    if tool in ("dodge", "burn"):
        lum = _luma(col)[..., None]
        weight = {"shadows": (1 - lum) ** 2, "highlights": lum ** 2}.get(rng, 1 - (2 * lum - 1) ** 2) * 0.8 + 0.2
        if tool == "dodge":
            col = col + (1 - col) * k * weight
        else:
            col = col * (1 - k * weight)
    elif tool == "sponge":
        lum = _luma(col)[..., None]
        col = col + (lum - col) * k
    elif tool == "soften":
        b = blur(a, 1.0 + 6 * k)
        return _img(b)
    elif tool == "sharpen":
        b = blur(a, 1.5)
        s = np.clip(a + (a - b) * (0.6 + 2.4 * k), 0, None)
        s[..., :3] = np.minimum(s[..., :3], s[..., 3:4])
        s[..., 3] = a[..., 3]
        return _img(s)
    col = np.clip(col, 0, 1)
    return _img(np.concatenate([col * alpha, alpha], axis=2))


def blend_by(base: QImage, effect: QImage, cover: QImage, selection: QImage = None) -> QImage:
    """base where the stroke didn't reach, the effect where it did, in between at its edges (coverage is the
    stroke's alpha, times the selection's)."""
    b, e, c = _arr(base), _arr(effect), _arr(cover)[..., 3:4]
    if selection is not None:
        c = c * _arr(selection)[..., 3:4]
    return _img(b + (e - b) * c)


def soft_spot(r: float, hardness: float) -> np.ndarray:
    """A round brush's strength, 1 in the middle to 0 at the edge, (2r + 1)² pixels."""
    n = int(math.ceil(r))
    yy, xx = np.mgrid[-n:n + 1, -n:n + 1].astype(np.float32)
    d = np.sqrt(xx * xx + yy * yy) / max(0.5, r)
    h = max(0.0, min(0.95, hardness))
    return np.clip((1 - d) / max(1e-3, 1 - h), 0, 1) ** 1.5


def smudge_dab(arr: np.ndarray, carried, x: float, y: float, spot: np.ndarray, strength: float, sel: np.ndarray = None):
    """Smudge at (x, y): the paint carried from the last dab is laid down here (as strongly as `strength` and the
    spot say), and what's here then is carried on. -> what's carried now."""
    n = spot.shape[0] // 2
    xi, yi = int(round(x)), int(round(y))
    h, w = arr.shape[:2]
    y0, y1, x0, x1 = yi - n, yi + n + 1, xi - n, xi + n + 1
    cy0, cy1, cx0, cx1 = max(0, y0), min(h, y1), max(0, x0), min(w, x1)
    if cy0 >= cy1 or cx0 >= cx1:
        return carried
    patch = arr[cy0:cy1, cx0:cx1]
    m = spot[cy0 - y0:cy1 - y0, cx0 - x0:cx1 - x0, None] * strength
    if sel is not None:
        m = m * sel[cy0:cy1, cx0:cx1, None]
    if carried is None or carried.shape != (2 * n + 1, 2 * n + 1, 4):
        full = np.zeros((2 * n + 1, 2 * n + 1, 4), np.float32)
        full[cy0 - y0:cy1 - y0, cx0 - x0:cx1 - x0] = patch
        return full
    c = carried[cy0 - y0:cy1 - y0, cx0 - x0:cx1 - x0]
    patch[...] = patch + (c - patch) * m
    out = carried.copy()
    out[cy0 - y0:cy1 - y0, cx0 - x0:cx1 - x0] = patch
    return out


# ------------------------------------------------------------------ liquify
LIQUIFY = {"push": "Push", "bloat": "Bloat", "pucker": "Pucker", "twirl": "Twirl", "restore": "Restore"}


def liquify_step(dx: np.ndarray, dy: np.ndarray, mode: str, cx: float, cy: float, vx: float, vy: float, r: float, k: float) -> tuple:
    """Change the displacement field in the brush's circle. The picture shows, at each pixel p, what the
    original had at p - D(p). -> the box changed (x0, y0, x1, y1)."""
    h, w = dx.shape
    n = int(math.ceil(r))
    x0, x1, y0, y1 = max(0, int(cx) - n), min(w, int(cx) + n + 2), max(0, int(cy) - n), min(h, int(cy) + n + 2)
    if x0 >= x1 or y0 >= y1:
        return None
    yy, xx = np.mgrid[y0:y1, x0:x1].astype(np.float32)
    rx, ry = xx - cx, yy - cy
    d2 = (rx * rx + ry * ry) / (r * r)
    f = np.clip(1 - d2, 0, 1) ** 2 * k
    sx, sy = dx[y0:y1, x0:x1], dy[y0:y1, x0:x1]
    if mode == "push":
        # what was a step back along the stroke comes here: the field at p - v·f, plus v·f
        bx, by = _bilinear_field(dx, xx - vx * f, yy - vy * f), _bilinear_field(dy, xx - vx * f, yy - vy * f)
        sx[...], sy[...] = bx + vx * f, by + vy * f
    elif mode in ("bloat", "pucker"):
        s = (0.06 if mode == "bloat" else -0.06) * f
        sx += rx * s
        sy += ry * s
    elif mode == "twirl":
        a = 0.05 * f
        sx += -ry * a
        sy += rx * a
    elif mode == "restore":
        sx *= (1 - 0.35 * f)
        sy *= (1 - 0.35 * f)
    return x0, y0, x1, y1


def _bilinear_field(f: np.ndarray, xs: np.ndarray, ys: np.ndarray) -> np.ndarray:
    h, w = f.shape
    xs = np.clip(xs, 0, w - 1.001)
    ys = np.clip(ys, 0, h - 1.001)
    x0, y0 = xs.astype(np.int32), ys.astype(np.int32)
    tx, ty = xs - x0, ys - y0
    return (f[y0, x0] * (1 - tx) * (1 - ty) + f[y0, x0 + 1] * tx * (1 - ty) + f[y0 + 1, x0] * (1 - tx) * ty + f[y0 + 1, x0 + 1] * tx * ty)


def warp_region(src: np.ndarray, dx: np.ndarray, dy: np.ndarray, box: tuple, out: np.ndarray) -> None:
    """out[box] = the original sampled at p - D(p), smoothly (bilinear); outside the picture is empty."""
    x0, y0, x1, y1 = box
    yy, xx = np.mgrid[y0:y1, x0:x1].astype(np.float32)
    sx, sy = xx - dx[y0:y1, x0:x1], yy - dy[y0:y1, x0:x1]
    h, w = src.shape[:2]
    inside = (sx >= 0) & (sx <= w - 1) & (sy >= 0) & (sy <= h - 1)
    sx, sy = np.clip(sx, 0, w - 1.001), np.clip(sy, 0, h - 1.001)
    ix, iy = sx.astype(np.int32), sy.astype(np.int32)
    tx, ty = (sx - ix)[..., None], (sy - iy)[..., None]
    v = (src[iy, ix] * (1 - tx) * (1 - ty) + src[iy, ix + 1] * tx * (1 - ty) + src[iy + 1, ix] * (1 - tx) * ty + src[iy + 1, ix + 1] * tx * ty)
    out[y0:y1, x0:x1] = np.where(inside[..., None], v, 0.0)


# ------------------------------------------------------------------ guides and snapping
def snap_value(v: float, targets: list, within: float) -> tuple:
    """The nearest target within reach: (value, snapped?)."""
    best = min(targets, key=lambda t: abs(t - v), default=None)
    if best is not None and abs(best - v) <= within:
        return best, True
    return v, False


def snap_box(x: float, y: float, w: float, h: float, xs: list, ys: list, within: float) -> tuple:
    """Move a box so its nearest edge or middle lands on a guide (or the canvas's edges and middle): -> (dx, dy)."""
    def one(lo, size, targets):
        best = None
        for edge in (lo, lo + size / 2, lo + size):
            t, ok = snap_value(edge, targets, within)
            if ok and (best is None or abs(t - edge) < abs(best)):
                best = t - edge
        return best or 0.0
    return one(x, w, xs), one(y, h, ys)


def dumps(o) -> str:
    return json.dumps(o, sort_keys=True)
