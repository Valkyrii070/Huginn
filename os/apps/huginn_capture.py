"""A picture of the screen from KWin, through huginn-grab (native/huginn-grab.c).

KWin hands screen pictures only to programs a .desktop file names (X-KDE-DBUS-Restricted-Interfaces), checked by the
program's own executable, so Huginn's Python can't ask itself: the small native helper is named
(/usr/share/applications/huginn-grab.desktop) and this reads what it writes.

    kwin_grab(out_png)            every screen, as one PNG: ("", "") on success, else ("", the reason)
    save_screenshot()             Print: a PNG in Pictures › Screenshots, and a notification
"""
import os
import subprocess
import tempfile
import time
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
HELPERS = (Path("/usr/libexec/huginn/huginn-grab"), HERE.parent / "native" / "huginn-grab")
LOG = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "huginn" / "screenshot.log"


def helper() -> str:
    return next((str(p) for p in HELPERS if os.access(p, os.X_OK)), "")


def note(line: str) -> None:
    """Why a picture failed, for anyone who looks (and for the next round of testing)."""
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a", encoding="utf-8") as fh:
            fh.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} {line}\n")
    except OSError:
        pass


def raw_to_png(raw: str, out_png: str) -> str:
    """huginn-grab's file (a header line, then the pixels) as a PNG: '' on success, else the reason."""
    from PySide6.QtGui import QImage
    try:
        data = Path(raw).read_bytes()
    except OSError as err:
        return str(err)
    head, _, pixels = data.partition(b"\n")
    bits = head.split()
    if len(bits) != 5 or bits[0] != b"HUGINNRAW":
        return "the picture couldn't be read"
    w, h, stride, fmt = (int(b) for b in bits[1:])
    if len(pixels) < stride * h:
        return "the picture arrived cut short"
    image = QImage(pixels, w, h, stride, QImage.Format(fmt)).copy()     # copy: the bytes go away after this
    if image.isNull():
        return "the picture couldn't be read"
    return "" if image.save(out_png, "PNG") else "the picture couldn't be saved"


def kwin_grab(out_png: str, screen: str = "") -> str:
    """The screen through KWin: '' when out_png was written, else why not."""
    prog = helper()
    if not prog:
        return "huginn-grab isn't installed"
    fd, raw = tempfile.mkstemp(prefix="huginn-grab-", suffix=".raw", dir=os.environ.get("XDG_RUNTIME_DIR") or None)
    os.close(fd)
    try:
        r = subprocess.run([prog, raw] + ([screen] if screen else []), capture_output=True, text=True, timeout=30)
        if r.returncode != 0:
            why = (r.stderr.strip().splitlines() or ["KWin didn't answer"])[-1]
            note(f"huginn-grab: {why}")
            return why
        why = raw_to_png(raw, out_png)
        if why:
            note(f"huginn-grab: {why}")
        return why
    except (OSError, subprocess.TimeoutExpired) as err:
        note(f"huginn-grab: {err}")
        return str(err)
    finally:
        try:
            os.unlink(raw)
        except OSError:
            pass


def pictures_dir() -> Path:
    try:
        from gi.repository import GLib
        got = GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_PICTURES)
        if got:
            return Path(got)
    except (ImportError, ValueError):
        pass
    return Path.home() / "Pictures"


def next_path() -> Path:
    folder = pictures_dir() / "Screenshots"
    folder.mkdir(parents=True, exist_ok=True)
    stem = f"Screenshot {datetime.now():%Y-%m-%d at %H.%M.%S}"
    path, n = folder / f"{stem}.png", 2
    while path.exists():                                   # two in the same second
        path, n = folder / f"{stem} ({n}).png", n + 1
    return path


def notify(summary: str, body: str, image: str = "") -> None:
    try:
        from gi.repository import Gio, GLib
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        hints = {"image-path": GLib.Variant("s", image)} if image else {}
        bus.call_sync("org.freedesktop.Notifications", "/org/freedesktop/Notifications", "org.freedesktop.Notifications", "Notify",
                      GLib.Variant("(susssasa{sv}i)", ("Screenshot", 0, "huginn-screenshot", summary, body, [], hints, 6000)),
                      None, 0, 3000, None)
    except Exception:                                      # noqa: BLE001  (a picture without a banner is still a picture)
        pass


def save_screenshot() -> str:
    """Print in the KWin session: the whole screen into Pictures › Screenshots. Returns the path, or ''."""
    path = next_path()
    why = kwin_grab(str(path))
    if why:
        notify("No screenshot was taken", f"{why[:1].upper()}{why[1:]}.")
        return ""
    notify("Screenshot saved", f"In Pictures › Screenshots as “{path.name}”.", str(path))
    return str(path)


if __name__ == "__main__":
    import sys
    t = time.time()
    if len(sys.argv) > 1 and sys.argv[1] == "--save":
        print(save_screenshot() or "failed")
    else:
        out = sys.argv[1] if len(sys.argv) > 1 else "/tmp/huginn-grab.png"
        print(kwin_grab(out) or f"ok {out} in {time.time() - t:.2f}s")
