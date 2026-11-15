#!/usr/bin/env python3
"""Builds Huginn OS's live wallpapers: each realm's scene (shaders/live/<realm>.frag, with common.glsl before it and
main.glsl after) compiled by Qt's shader baker (qsb) into config/overlay/usr/share/huginn-os/live/<realm>.frag.qsb, then a
still of each painted on the graphics card (an X server with OpenGL is needed: Xvfb with Mesa will do) at the moment
LiveWallpaper.qml starts from, into stills/<realm>.jpg. The stills stand in where there is no graphics card, show in
Settings, and are the boot screen's backdrop (make-plymouth.py).

    scripts/make-live-wallpapers.py [--size 2560x1600] [--only aurora]
"""
import argparse, os, shutil, subprocess, sys, tempfile, time
from pathlib import Path

KIT = Path(__file__).resolve().parent.parent
SRC = KIT / "shaders" / "live"
OUT = KIT / "config" / "overlay" / "usr" / "share" / "huginn-os" / "live"
REALMS = ["aurora", "bifrost", "muspelheim", "niflheim"]


def qsb() -> str:
    for name in ("qsb", "pyside6-qsb", "/usr/lib/qt6/bin/qsb"):
        if shutil.which(name):
            return shutil.which(name)
    sys.exit("make-live-wallpapers: Qt's qsb isn't here (qt6-shader-baker, or pip install PySide6)")


def build(realm: str) -> Path:
    with tempfile.TemporaryDirectory() as tmp:
        frag = Path(tmp) / f"{realm}.frag"
        frag.write_text((SRC / "common.glsl").read_text() + "\n" + (SRC / f"{realm}.frag").read_text() + "\n" + (SRC / "main.glsl").read_text())
        out = OUT / f"{realm}.frag.qsb"
        r = subprocess.run([qsb(), "--glsl", "100 es,120,150", "--hlsl", "50", "--msl", "12", "-o", str(out), str(frag)], capture_output=True, text=True)
        if r.returncode:
            sys.exit(f"{realm}: {r.stderr or r.stdout}")
    return out


STILL_QML = """import QtQuick
Item { width: %d; height: %d
    LiveWallpaper { id: lw; anchors.fill: parent; realm: "%s"; moving: false } }
"""


def stills(realms: list, size: tuple) -> None:
    display = os.environ.get("DISPLAY")
    xvfb = None
    if not display:
        display = ":87"
        xvfb = subprocess.Popen(["Xvfb", display, "-screen", "0", f"{size[0] + 16}x{size[1] + 16}x24"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(1)
    (OUT / "stills").mkdir(parents=True, exist_ok=True)
    try:
        for realm in realms:
            qml = OUT / f".still-{realm}.qml"
            qml.write_text(STILL_QML % (size[0], size[1], realm))
            code = ("import sys\nfrom PySide6.QtCore import QUrl, QTimer\nfrom PySide6.QtGui import QGuiApplication\nfrom PySide6.QtQuick import QQuickView\n"
                    "app = QGuiApplication(sys.argv); v = QQuickView(); v.setSource(QUrl.fromLocalFile(sys.argv[1])); v.show()\n"
                    "lw = v.rootObject().childItems()[0]\n"
                    "def go():\n    assert lw.property('gpu'), 'no graphics card: the still would only be the old still'\n"
                    "    v.grabWindow().save(sys.argv[2], quality=90); app.quit()\n"
                    "QTimer.singleShot(2500, go); app.exec()\n")
            env = dict(os.environ, DISPLAY=display, QT_QPA_PLATFORM="xcb")
            r = subprocess.run([sys.executable, "-c", code, str(qml), str(OUT / "stills" / f"{realm}.jpg")], env=env, capture_output=True, text=True, timeout=180)
            qml.unlink()
            if r.returncode:
                sys.exit(f"{realm} still: {r.stderr[-800:]}")
            print(f"  {realm}: stills/{realm}.jpg ({(OUT / 'stills' / f'{realm}.jpg').stat().st_size // 1024} KB)")
    finally:
        if xvfb:
            xvfb.terminate()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--size", default="2560x1600")
    ap.add_argument("--only", default="")
    ap.add_argument("--no-stills", action="store_true")
    a = ap.parse_args()
    realms = [a.only] if a.only else REALMS
    for realm in realms:
        print(f"  {realm}: {build(realm).relative_to(KIT)}")
    if not a.no_stills:
        w, h = (int(x) for x in a.size.split("x"))
        stills(realms, (w, h))
    return 0


if __name__ == "__main__":
    sys.exit(main())
