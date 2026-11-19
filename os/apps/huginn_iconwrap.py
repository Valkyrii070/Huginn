"""Other apps' icons in Huginn's glass: every installed app's icon on the same smoked-glass tile as Huginn's own.

    python3 huginn_iconwrap.py --user      wrap every app this user can open whose icon isn't wrapped yet
    python3 huginn_iconwrap.py --system    the same, for everyone (the image's build, as root)
    python3 huginn_iconwrap.py --sheet F   also write a picture F of every wrapped icon (to look at)

An app's own icon is found where it put it (hicolor in every data folder, Flatpak's exports, Breeze, pixmaps) and
put on Huginn's tile (scripts/make-icons.py draws the same tile for Huginn's apps): an icon that is already a
square tile of its own (it fills its square, corners and all) is cut to Huginn's squircle and takes its glass edges;
any other shape (a circle, a logo) sits on the smoked glass, brought to the same size as Huginn's pictures, with a
soft shadow, and the glass glows in the icon's own main colour. Nothing is redrawn or traced: it's the app's icon.

The results go in the Huginn icon theme's wrapped/apps folder (the user's ~/.local/share/icons/Huginn, or
/usr/share/icons/Huginn for --system), named as the .desktop file asks for its icon, so every program that asks
the theme for that icon gets the wrapped one; an icon given as a file path is wrapped as app-<desktop id>.
The shell runs --user when it finds apps it hasn't seen (huginn_shell.Apps), so a new app has its tile in seconds.
"""
from __future__ import annotations

import configparser
import hashlib
import json
import math
import os
import sys
from pathlib import Path

HOME = Path.home()
DATA_HOME = Path(os.environ.get("XDG_DATA_HOME") or HOME / ".local/share")
DATA_DIRS = [Path(d) for d in os.environ.get("XDG_DATA_DIRS", "/usr/local/share:/usr/share").split(":") if d]
FLATPAK = [DATA_HOME / "flatpak/exports/share", Path("/var/lib/flatpak/exports/share")]
USER_OUT = DATA_HOME / "icons/Huginn/wrapped/apps"
SYSTEM_OUT = Path("/usr/share/icons/Huginn/wrapped/apps")
SIZE = 256
SIZES = ("512x512", "256x256", "192x192", "128x128", "96x96", "72x72", "64x64", "48x48", "32x32")


def bases() -> list:
    out = []
    for b in [DATA_HOME] + FLATPAK + DATA_DIRS + [Path("/usr/share")]:
        if b not in out:
            out.append(b)
    return out


def wrapped_dirs() -> list:
    """Where wrapped icons may be, the user's first."""
    return [USER_OUT, Path("/usr/local/share/icons/Huginn/wrapped/apps"), SYSTEM_OUT]


def wrapped_name(icon: str, desktop_id: str) -> str:
    """The name a wrapped icon is kept under: the icon's own name, or app-<desktop id> for an icon given as a path."""
    if not icon:
        return ""
    return f"app-{desktop_id}" if os.path.isabs(icon) else icon


def find_wrapped(icon: str, desktop_id: str) -> str:
    name = wrapped_name(icon, desktop_id)
    if not name or name.startswith("huginn-"):
        return ""
    for d in wrapped_dirs():
        f = d / f"{name}.png"
        if f.is_file():
            return str(f)
    return ""


def find_icon(name: str) -> str:
    """The app's own icon file: a path as given, else the biggest in hicolor (scalable first), Breeze, or pixmaps."""
    if os.path.isabs(name):
        return name if os.path.isfile(name) else ""
    for theme in ("hicolor", "breeze"):
        for b in bases():
            root = b / "icons" / theme
            if not root.is_dir():
                continue
            for f in (root / "scalable/apps" / f"{name}.svg", root / "scalable/apps" / f"{name}.svgz",
                      root / "apps/64" / f"{name}.svg", root / "apps/48" / f"{name}.svg"):
                if f.is_file():
                    return str(f)
            for s in SIZES:
                f = root / s / "apps" / f"{name}.png"
                if f.is_file():
                    return str(f)
    for b in bases():
        for ext in (".svg", ".png", ".xpm"):
            f = b / "pixmaps" / f"{name}{ext}"
            if f.is_file():
                return str(f)
    return ""


def apps() -> list:
    """(desktop id, icon) for every app a person can open."""
    seen, out = set(), []
    for b in bases():
        folder = b / "applications"
        for path in sorted(folder.glob("*.desktop")) if folder.is_dir() else []:
            if path.name in seen:
                continue
            seen.add(path.name)
            parser = configparser.ConfigParser(interpolation=None, strict=False)
            try:
                parser.read(path, encoding="utf-8")
                entry = parser["Desktop Entry"]
            except (configparser.Error, KeyError, UnicodeDecodeError):
                continue
            icon = entry.get("Icon", "").strip()
            if entry.get("Type") != "Application" or entry.get("NoDisplay", "false").lower() == "true" or not icon or icon.startswith("huginn"):
                continue
            out.append((path.stem, icon))
    return out


# ------------------------------------------------------------------------------------------------ the glass
def squircle(x: float, y: float, w: float, h: float, n: float = 5.0, steps: int = 96) -> list:
    cx, cy, a, b = x + w / 2, y + h / 2, w / 2, h / 2
    pts = []
    for i in range(steps):
        t = 2 * math.pi * i / steps
        c, s = math.cos(t), math.sin(t)
        pts.append((cx + a * math.copysign(abs(c) ** (2 / n), c), cy + b * math.copysign(abs(s) ** (2 / n), s)))
    return pts


def _d(pts) -> str:
    return "M" + " L".join(f"{x:.1f} {y:.1f}" for x, y in pts) + "Z"


TILE_PTS, INNER_PTS = squircle(14, 14, 228, 228), squircle(16.5, 16.5, 223, 223)
TILE, INNER = _d(TILE_PTS), _d(INNER_PTS)


def mix(a: str, b: str, t: float) -> str:
    pa, pb = (int(a[i:i + 2], 16) for i in (1, 3, 5)), (int(b[i:i + 2], 16) for i in (1, 3, 5))
    return "#" + "".join(f"{round(x + (y - x) * t):02X}" for x, y in zip(pa, pb))


def glass(bright: str, part: str, smoke: bool = True) -> str:
    """Huginn's tile (as make-icons.py draws it), in two parts: "under" the picture (its shadow, the smoked glass,
    the colour's glow, the sheen) and "over" it (the rim, the lit top edge and darker foot, the line of light along
    the bottom). Without smoke, "under" is only the shadow (an icon that fills the tile is the glass's colour)."""
    defs = (f'<linearGradient id="tile" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#2B3038"/><stop offset="1" stop-color="#121519"/></linearGradient>'
            f'<radialGradient id="glow" cx=".5" cy="1.04" r=".72"><stop offset="0" stop-color="{bright}" stop-opacity=".42"/><stop offset="1" stop-color="{bright}" stop-opacity="0"/></radialGradient>'
            f'<linearGradient id="sheen" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#fff" stop-opacity=".14"/><stop offset=".42" stop-color="#fff" stop-opacity="0"/></linearGradient>'
            f'<radialGradient id="spec" cx=".38" cy="0" r=".6"><stop offset="0" stop-color="#fff" stop-opacity=".16"/><stop offset="1" stop-color="#fff" stop-opacity="0"/></radialGradient>'
            f'<linearGradient id="rim" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#fff" stop-opacity=".30"/><stop offset=".55" stop-color="#fff" stop-opacity=".06"/><stop offset="1" stop-color="{bright}" stop-opacity=".75"/></linearGradient>'
            f'<linearGradient id="hi" gradientUnits="userSpaceOnUse" x1="0" y1="14" x2="0" y2="80"><stop offset="0" stop-color="#fff" stop-opacity=".55"/><stop offset="1" stop-color="#fff" stop-opacity="0"/></linearGradient>'
            f'<linearGradient id="lo" gradientUnits="userSpaceOnUse" x1="0" y1="180" x2="0" y2="242"><stop offset="0" stop-color="#000" stop-opacity="0"/><stop offset="1" stop-color="#000" stop-opacity=".55"/></linearGradient>'
            f'<filter id="drop" x="-20%" y="-20%" width="140%" height="150%"><feGaussianBlur stdDeviation="6"/><feOffset dy="6"/></filter>'
            f'<filter id="soft" x="-40%" y="-40%" width="180%" height="180%"><feGaussianBlur stdDeviation="4"/></filter>'
            f'<clipPath id="inside"><path d="{TILE}"/></clipPath>'
            f'<linearGradient id="ring" gradientUnits="userSpaceOnUse" x1="14" y1="0" x2="242" y2="0"><stop offset=".08" stop-color="{bright}" stop-opacity="0"/>'
            f'<stop offset=".5" stop-color="{mix(bright, "#FFFFFF", 0.35)}"/><stop offset=".92" stop-color="{bright}" stop-opacity="0"/></linearGradient>'
            f'<clipPath id="low"><rect x="0" y="196" width="256" height="60"/></clipPath>')
    if part == "under":
        body = f'<path d="{TILE}" fill="#000" opacity=".5" filter="url(#drop)"/>'
        if smoke:
            body += f'<path d="{TILE}" fill="url(#tile)"/><path d="{TILE}" fill="url(#spec)"/><path d="{TILE}" fill="url(#glow)"/><path d="{TILE}" fill="url(#sheen)"/>'
    else:
        body = (('' if smoke else f'<path d="{TILE}" fill="url(#sheen)"/>')
                + f'<path d="{TILE}" fill="none" stroke="url(#rim)" stroke-width="3"/>'
                f'<g clip-path="url(#inside)"><path d="{INNER}" fill="none" stroke="url(#hi)" stroke-width="5"/><path d="{INNER}" fill="none" stroke="url(#lo)" stroke-width="6"/></g>'
                f'<g clip-path="url(#low)"><path d="{TILE}" fill="none" stroke="url(#ring)" stroke-width="9" filter="url(#soft)" opacity=".9"/>'
                f'<path d="{TILE}" fill="none" stroke="url(#ring)" stroke-width="3.5"/></g>')
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256" width="256" height="256"><defs>{defs}</defs>{body}</svg>'


# ------------------------------------------------------------------------------------------------ wrapping one
def load(path: str):
    from PySide6.QtCore import QByteArray, QRectF, Qt
    from PySide6.QtGui import QImage, QPainter
    img = QImage(SIZE, SIZE, QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    if path.endswith((".svg", ".svgz")):
        from PySide6.QtSvg import QSvgRenderer
        r = QSvgRenderer(path)
        if not r.isValid():
            return None
        size = r.defaultSize()
        w, h = max(1, size.width()), max(1, size.height())
        k = SIZE / max(w, h)
        p = QPainter(img)
        p.setRenderHint(QPainter.Antialiasing)
        r.render(p, QRectF((SIZE - w * k) / 2, (SIZE - h * k) / 2, w * k, h * k))
        p.end()
        return img
    src = QImage(path)
    if src.isNull():
        return None
    src = src.convertToFormat(QImage.Format_ARGB32_Premultiplied).scaled(SIZE, SIZE, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    p = QPainter(img)
    p.drawImage((SIZE - src.width()) // 2, (SIZE - src.height()) // 2, src)
    p.end()
    return img


def _array(img):
    import numpy as np
    from PySide6.QtGui import QImage
    img = img.convertToFormat(QImage.Format_ARGB32)                    # straight alpha, B G R A in memory
    a = np.frombuffer(img.constBits(), np.uint8, img.sizeInBytes()).reshape(img.height(), img.bytesPerLine() // 4, 4)[:, :img.width()]
    return a.astype(np.float32) / 255.0


def look_at(img) -> dict:
    """What the icon is like: its box, whether it fills that box as a tile of its own would, and its main colour."""
    import numpy as np
    a = _array(img)
    alpha = a[..., 3]
    ys, xs = np.nonzero(alpha > 0.5)
    if len(xs) == 0:
        return {}
    x0, x1, y0, y1 = xs.min(), xs.max() + 1, ys.min(), ys.max() + 1
    w, h = x1 - x0, y1 - y0
    cover = float((alpha[y0:y1, x0:x1] > 0.5).mean())
    corner = float(alpha[y0 + int(h * 0.1), x0 + int(w * 0.1)])        # a rounded square's corner area is filled; a circle's isn't
    tile = cover > 0.88 and min(w, h) > SIZE * 0.72 and abs(w - h) < SIZE * 0.08 and corner > 0.5
    # the main colour: the most colourful pixels, weighted by how colourful they are
    rgb = a[..., [2, 1, 0]]
    mx, mn = rgb.max(axis=2), rgb.min(axis=2)
    sat = np.where(alpha > 0.5, (mx - mn) * mx, 0)
    if sat.sum() > 50:
        c = (rgb * sat[..., None]).sum(axis=(0, 1)) / sat.sum()
    else:
        c = np.array([0.55, 0.62, 0.72])                               # a grey icon: Huginn's quiet steel
    c = c / max(0.35, float(c.max())) * 0.95                            # bright enough to glow
    colour = "#" + "".join(f"{int(max(0, min(1, v)) * 255):02X}" for v in c)
    return {"box": (int(x0), int(y0), int(w), int(h)), "ink": float(alpha.sum()), "tile": tile, "colour": colour}


def wrap(img):
    """The icon on Huginn's glass, as a 256-pixel picture."""
    import cv2
    import numpy as np
    from PySide6.QtCore import QByteArray, QPointF, QRectF, Qt
    from PySide6.QtGui import QImage, QPainter, QPainterPath, QPolygonF
    from PySide6.QtSvg import QSvgRenderer
    info = look_at(img)
    if not info:
        return None
    out = QImage(SIZE, SIZE, QImage.Format_ARGB32_Premultiplied)
    out.fill(Qt.transparent)
    p = QPainter(out)
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.SmoothPixmapTransform)
    under = QSvgRenderer(QByteArray(glass(info["colour"], "under", smoke=not info["tile"]).encode()))
    over = QSvgRenderer(QByteArray(glass(info["colour"], "over", smoke=not info["tile"]).encode()))
    under.render(p, QRectF(0, 0, SIZE, SIZE))
    x0, y0, w, h = info["box"]
    if info["tile"]:
        # already a tile: it becomes Huginn's, cut to the squircle and filling it
        path = QPainterPath()
        path.addPolygon(QPolygonF([QPointF(x, y) for x, y in TILE_PTS]))
        path.closeSubpath()
        p.setClipPath(path)
        p.drawImage(QRectF(14, 14, 228, 228), img, QRectF(x0, y0, w, h))
        p.setClipping(False)
    else:
        # anything else sits on the glass, as big as Huginn's own pictures look (make-icons.py, fit())
        size = (math.sqrt(info["ink"]) + math.sqrt(w * h)) / 2
        k = min(max(140.0 / size, 0.6), 1.6, 168.0 / max(w, h))
        tw, th = w * k, h * k
        tx, ty = (SIZE - tw) / 2, (SIZE - th) / 2
        a = _array(img)[..., 3]
        crop = cv2.resize(a[y0:y0 + h, x0:x0 + w], (max(1, int(tw)), max(1, int(th))), interpolation=cv2.INTER_AREA)
        shadow = np.zeros((SIZE, SIZE), np.float32)
        sx, sy = int(tx), int(ty + 5)
        shadow[sy:sy + crop.shape[0], sx:sx + crop.shape[1]] = crop[:SIZE - sy, :SIZE - sx]
        shadow = cv2.GaussianBlur(shadow, (0, 0), 5) * 0.5
        sh = np.zeros((SIZE, SIZE, 4), np.uint8)
        sh[..., 3] = (shadow * 255).astype(np.uint8)
        simg = QImage(sh.data, SIZE, SIZE, SIZE * 4, QImage.Format_ARGB32).copy()
        p.drawImage(0, 0, simg)
        p.drawImage(QRectF(tx, ty, tw, th), img, QRectF(x0, y0, w, h))
    over.render(p, QRectF(0, 0, SIZE, SIZE))
    p.end()
    return out


# ------------------------------------------------------------------------------------------------ all of them
def run(out: Path, quiet: bool = False, sheet: str = "") -> int:
    """Wrap every app whose icon isn't wrapped yet (or whose own icon changed since). Returns how many were made."""
    from PySide6.QtGui import QGuiApplication
    app = QGuiApplication.instance() or QGuiApplication(["iconwrap", "-platform", "offscreen"])   # noqa: F841
    out.mkdir(parents=True, exist_ok=True)
    stamps_file = out / ".sources.json"
    try:
        stamps = json.loads(stamps_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        stamps = {}
    made, pictures = 0, []
    for desktop_id, icon in apps():
        name = wrapped_name(icon, desktop_id)
        source = find_icon(icon)
        if not name or not source:
            continue
        try:
            st = os.stat(source)
        except OSError:
            continue
        stamp = hashlib.sha1(f"{source}:{st.st_mtime_ns}:{st.st_size}:2".encode()).hexdigest()[:16]
        target = out / f"{name}.png"
        elsewhere = next((d / f"{name}.png" for d in wrapped_dirs() if d != out and (d / f"{name}.png").is_file()), None)
        if (target.is_file() and stamps.get(name) == stamp) or (elsewhere is not None and out == USER_OUT and not target.exists()):
            if sheet:
                pictures.append(str(target if target.is_file() else elsewhere))
            continue
        img = load(source)
        done = wrap(img) if img is not None else None
        if done is None:
            continue
        part = out / f".{name}.part.png"
        if done.save(str(part)):
            os.replace(part, target)
            stamps[name] = stamp
            made += 1
            pictures.append(str(target))
            if not quiet:
                print(f"wrapped {name}  ({desktop_id}, from {source})")
    try:
        part = stamps_file.with_name(".sources.json.part")
        part.write_text(json.dumps(stamps, indent=1), encoding="utf-8")
        os.replace(part, stamps_file)
    except OSError:
        pass
    if sheet and pictures:
        from PySide6.QtGui import QImage, QPainter
        cols = 8
        rows = -(-len(pictures) // cols)
        s = QImage(cols * 140 + 20, rows * 140 + 20, QImage.Format_RGB32)
        s.fill(0x15181C)
        p = QPainter(s)
        for i, f in enumerate(pictures):
            p.drawImage(20 + (i % cols) * 140, 20 + (i // cols) * 140, QImage(f).scaled(120, 120))
        p.end()
        s.save(sheet)
    return made


if __name__ == "__main__":
    quiet = "--quiet" in sys.argv
    sheet = sys.argv[sys.argv.index("--sheet") + 1] if "--sheet" in sys.argv else ""
    where = SYSTEM_OUT if "--system" in sys.argv else USER_OUT
    n = run(where, quiet, sheet)
    if not quiet:
        print(f"{n} icons wrapped into {where}")
