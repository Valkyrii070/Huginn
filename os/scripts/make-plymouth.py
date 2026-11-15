#!/usr/bin/env python3
"""Draw the pictures Huginn OS's boot screen (the Plymouth theme in config/overlay/usr/share/plymouth/themes/huginn)
uses: the backdrop (the realm's live wallpaper, as a soft dark still: run make-live-wallpapers.py first), the logo,
the progress line's track and its light, the glass pill the disk password is typed into, its bullets and a lock.
Run again after changing the logo, the realm colours or the scenes."""
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QGuiApplication, QImage, QLinearGradient, QPainter, QPainterPath, QPen, QRadialGradient
from PySide6.QtSvg import QSvgRenderer

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "config/overlay/usr/share/plymouth/themes/huginn"
GLOW_A, GLOW_B = QColor("#3DD6B5"), QColor("#7B61FF")


def canvas(w, h):
    img = QImage(w, h, QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    return img, p


def main() -> None:
    app = QGuiApplication(sys.argv)                            # noqa: F841  (QPainter text needs it)
    OUT.mkdir(parents=True, exist_ok=True)
    # the logo, as on the login screen and the launcher
    img, p = canvas(144, 144)
    QSvgRenderer(str(ROOT / "config/overlay/usr/share/icons/hicolor/scalable/apps/huginn-os.svg")).render(p, QRectF(0, 0, 144, 144))
    p.end(); img.save(str(OUT / "logo.png"))
    # the backdrop: the realm's scene, blurred and darkened, so the logo sits in the same world as the sign-in screen
    still = QImage(str(ROOT / "config/overlay/usr/share/huginn-os/live/stills/aurora.jpg"))
    if still.isNull():
        sys.exit("make-plymouth: no stills/aurora.jpg (run scripts/make-live-wallpapers.py first)")
    small = still.scaled(96, 60, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)          # a blur: down very small, then up
    soft = small.scaled(480, 300, Qt.IgnoreAspectRatio, Qt.SmoothTransformation).scaled(1280, 800, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
    img, p = canvas(1280, 800)
    p.drawImage(0, 0, soft)
    p.fillRect(0, 0, 1280, 800, QColor(0, 0, 0, 120))
    vig = QRadialGradient(640, 380, 820)
    vig.setColorAt(0.45, QColor(0, 0, 0, 0)); vig.setColorAt(1.0, QColor(0, 0, 0, 150))
    p.fillRect(0, 0, 1280, 800, vig)
    p.end(); img.convertToFormat(QImage.Format_RGB32).save(str(OUT / "backdrop.png"))
    # the progress line: its track, and its light in the realm's pair
    img, p = canvas(220, 4)
    path = QPainterPath(); path.addRoundedRect(QRectF(0, 0, 220, 4), 2, 2)
    p.fillPath(path, QColor(255, 255, 255, 46))
    p.end(); img.save(str(OUT / "track.png"))
    img, p = canvas(220, 4)
    g = QLinearGradient(0, 0, 220, 0); g.setColorAt(0, GLOW_A); g.setColorAt(1, GLOW_B)
    p.fillPath(path, g)
    p.end(); img.save(str(OUT / "fill.png"))
    # the glass pill for the disk password
    img, p = canvas(340, 48)
    path = QPainterPath(); path.addRoundedRect(QRectF(1, 1, 338, 46), 23, 23)
    p.fillPath(path, QColor(255, 255, 255, 30))
    p.setPen(QPen(QColor(255, 255, 255, 64), 1.2)); p.drawPath(path)
    p.end(); img.save(str(OUT / "pill.png"))
    img, p = canvas(12, 12)
    p.setBrush(QColor("#F5F7FA")); p.setPen(Qt.NoPen); p.drawEllipse(2, 2, 8, 8)
    p.end(); img.save(str(OUT / "bullet.png"))
    # a lock, as a line drawing like the sign-in screen's icons
    img, p = canvas(32, 32)
    pen = QPen(QColor(255, 255, 255, 170), 2.2); pen.setCapStyle(Qt.RoundCap)
    p.setPen(pen); p.setBrush(Qt.NoBrush)
    p.drawArc(QRectF(10, 5, 12, 14), 0, 180 * 16)
    p.drawLine(10, 12, 10, 15); p.drawLine(22, 12, 22, 15)
    lock = QPainterPath(); lock.addRoundedRect(QRectF(7, 14, 18, 13), 3.5, 3.5); p.drawPath(lock)
    p.end(); img.save(str(OUT / "lock.png"))
    for old in ("glow.png", "dot.png", "dot-on.png", "box.png"):
        (OUT / old).unlink(missing_ok=True)
    print("Boot screen pictures in", OUT)


if __name__ == "__main__":
    main()
