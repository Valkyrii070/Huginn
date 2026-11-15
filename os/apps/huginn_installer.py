"""Huginn OS's installer: the app on the live system that puts Huginn OS on a computer. It asks, in order: the
language, the keyboard (with a place to try it), the network (optional), the disk and how to use it (erase it, the
free space beside another system, or partitions you choose; encryption on top), you (name, user name, computer
name, password, signing in by yourself), the time zone, and then shows everything once more before anything is
touched. Installing runs huginn_install_engine.py as root through pkexec (on the live system a polkit rule lets the
live user do that without a password); the plan, passwords included, goes to it on stdin and never to a file.

Everything about the computer is read without root: disks and partitions from lsblk and /sys, firmware from
/sys/firmware/efi, Wi‑Fi from NetworkManager (nmcli). `--demo` makes up a computer, for screenshots and tests.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import threading
from pathlib import Path

from PySide6.QtCore import Property, QObject, QProcess, QTimer, Signal, Slot

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import huginn_install_engine as engine                       # noqa: E402  (the plan's checks and names are shared)

ENGINE = "/usr/libexec/huginn-install-engine"
MIN_BYTES = 20 * 10 ** 9                                    # Huginn OS wants about 20 GB
GIB = 1 << 30
SECTOR = 512
STEPS = ["welcome", "keyboard", "network", "disk", "you", "time", "ready"]

LANGUAGES = ["en_US", "en_GB", "de_DE", "fr_FR", "es_ES", "es_MX", "it_IT", "pt_BR", "pt_PT", "nl_NL", "sv_SE", "nb_NO",
             "da_DK", "fi_FI", "is_IS", "pl_PL", "cs_CZ", "uk_UA", "ru_RU", "tr_TR", "el_GR", "ar_SA", "he_IL", "hi_IN",
             "ja_JP", "ko_KR", "zh_CN", "zh_TW", "id_ID", "vi_VN", "th_TH", "en_CA", "fr_CA", "en_AU"]
# the keyboard and time zone a language most likely means
GUESS = {"en_US": ("us", "America/New_York"), "en_GB": ("gb", "Europe/London"), "de_DE": ("de", "Europe/Berlin"),
         "fr_FR": ("fr", "Europe/Paris"), "es_ES": ("es", "Europe/Madrid"), "es_MX": ("latam", "America/Mexico_City"),
         "it_IT": ("it", "Europe/Rome"), "pt_BR": ("br", "America/Sao_Paulo"), "pt_PT": ("pt", "Europe/Lisbon"),
         "nl_NL": ("nl", "Europe/Amsterdam"), "sv_SE": ("se", "Europe/Stockholm"), "nb_NO": ("no", "Europe/Oslo"),
         "da_DK": ("dk", "Europe/Copenhagen"), "fi_FI": ("fi", "Europe/Helsinki"), "is_IS": ("is", "Atlantic/Reykjavik"),
         "pl_PL": ("pl", "Europe/Warsaw"), "cs_CZ": ("cz", "Europe/Prague"), "uk_UA": ("ua", "Europe/Kyiv"),
         "ru_RU": ("ru", "Europe/Moscow"), "tr_TR": ("tr", "Europe/Istanbul"), "el_GR": ("gr", "Europe/Athens"),
         "ar_SA": ("ara", "Asia/Riyadh"), "he_IL": ("il", "Asia/Jerusalem"), "hi_IN": ("in", "Asia/Kolkata"),
         "ja_JP": ("jp", "Asia/Tokyo"), "ko_KR": ("kr", "Asia/Seoul"), "zh_CN": ("cn", "Asia/Shanghai"),
         "zh_TW": ("tw", "Asia/Taipei"), "id_ID": ("id", "Asia/Jakarta"), "vi_VN": ("vn", "Asia/Ho_Chi_Minh"),
         "th_TH": ("th", "Asia/Bangkok"), "en_CA": ("us", "America/Toronto"), "fr_CA": ("ca", "America/Toronto"),
         "en_AU": ("us", "Australia/Sydney")}


# shown while it installs: what's waiting on the other side
SLIDES = [("browser", "Huginn", "The browser at the heart of it all. Private by default: trackers stop at the door."),
          ("mail", "Mail", "Your accounts in one calm inbox. Sign-ins stay locked in the Passwords vault."),
          ("easel", "Easel", "Paint, retouch and design, with layers, masks and type along a path."),
          ("clips", "Clips", "Cut films from several cameras at once, with titles that follow what moves."),
          ("tempo", "Tempo", "Make music: instruments, drums, takes and a full mixer."),
          ("code", "Code", "Write, run and test your code, with Git built in."),
          ("writer", "Huginn Office", "Writer, Sheets and Slides, for documents that open anywhere."),
          ("photos", "Photos", "Every picture, sorted by when and where, edited without losing the original."),
          ("passwords", "Passwords", "One vault for the browser, Mail and Messages, under one master password.")]
ICON_DIRS = [Path("/usr/share/icons/hicolor/256x256/apps"), HERE.parent / "config/overlay/usr/share/icons/hicolor/256x256/apps"]


def slides() -> list:
    from PySide6.QtCore import QUrl
    out = []
    for icon, name, line in SLIDES:
        f = next((d / f"huginn-{icon}.png" for d in ICON_DIRS if (d / f"huginn-{icon}.png").is_file()), None)
        out.append({"name": name, "line": line, "icon": QUrl.fromLocalFile(str(f)).toString() if f else ""})
    return out


def run(argv: list, stdin: str = None, timeout: float = 20) -> tuple:
    try:
        r = subprocess.run(argv, input=stdin, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout, r.stderr
    except (OSError, subprocess.SubprocessError) as err:
        return 127, "", str(err)


def size_text(n: int) -> str:
    gb = n / 10 ** 9
    return f"{gb / 1000:.1f} TB" if gb >= 1000 else f"{gb:.0f} GB" if gb >= 10 else f"{gb:.1f} GB"


def guess_system(part: dict) -> str:
    """What a partition probably holds, in words: 'Windows', 'Linux', 'EFI' … (os-prober needs root; this doesn't)."""
    fs, ptype, label = (part.get("fstype") or ""), (part.get("parttype") or "").lower(), (part.get("label") or "")
    if ptype == "c12a7328-f81f-11d2-ba4b-00a0c93ec93b" or ptype == "0xef":
        return "EFI"
    if ptype == "e3c9e316-0b5c-4db8-817d-f92df00215ae":
        return "Microsoft reserved"
    if ptype == "de94bba4-06d1-4d40-a16a-bfd50179d6ac":
        return "Windows recovery"
    if fs == "ntfs" or fs == "bitlocker":
        return "Windows" if "recovery" not in label.lower() else "Windows recovery"
    if fs in ("ext4", "ext3", "btrfs", "xfs", "f2fs"):
        return "Linux"
    if fs == "crypto_LUKS":
        return "Locked (LUKS)"
    if fs == "swap":
        return "Swap"
    if fs in ("vfat", "exfat"):
        return "FAT"
    if fs == "apfs" or fs == "hfsplus":
        return "macOS"
    return fs or "Empty"


def live_disk() -> str:
    """The disk the live system itself is running from (never offered)."""
    code, out, _ = run(["findmnt", "-n", "-o", "SOURCE", "/cdrom"])
    src = out.strip()
    if code or not src:
        return ""
    code, out, _ = run(["lsblk", "-n", "-o", "PKNAME", src])
    return "/dev/" + out.strip().splitlines()[0] if code == 0 and out.strip() else src


def free_spans(disk_name: str, disk_sectors: int, parts: list) -> list:
    """Unused stretches of a disk, from /sys (no root needed): [(start sector, sectors)], each at least 1 GiB,
    aligned to 1 MiB, keeping clear of the partition table at both ends."""
    used = sorted((p["start"], p["start"] + p["sectors"]) for p in parts)
    spans, at = [], 2048
    end = disk_sectors - 34                                   # GPT keeps a copy of itself at the end
    for a, b in used + [(end, end)]:
        if a > at:
            start = (at + 2047) // 2048 * 2048
            if a - start >= GIB // SECTOR:
                spans.append((start, a - start))
        at = max(at, b)
    return spans


def read_disks() -> list:
    code, out, _ = run(["lsblk", "-J", "-b", "-o", "NAME,PATH,SIZE,TYPE,MODEL,TRAN,RM,RO,PTTYPE,FSTYPE,LABEL,PARTTYPE,PARTLABEL,MOUNTPOINTS"])
    if code:
        return []
    skip = live_disk()
    disks = []
    for d in json.loads(out).get("blockdevices", []):
        if d.get("type") != "disk" or d.get("ro") in (True, "1") or d["path"] == skip or int(d.get("size") or 0) < 8 * 10 ** 9:
            continue
        if re.match(r"(loop|sr|zram|ram|fd)", d["name"]):
            continue
        parts = []
        for c in d.get("children") or []:
            try:
                start = int(Path(f"/sys/class/block/{c['name']}/start").read_text())
                sectors = int(Path(f"/sys/class/block/{c['name']}/size").read_text())
            except (OSError, ValueError):
                start, sectors = 0, int(c.get("size") or 0) // SECTOR
            parts.append({"path": c["path"], "name": c["name"], "size": int(c.get("size") or 0), "sizeText": size_text(int(c.get("size") or 0)),
                          "fstype": c.get("fstype") or "", "label": c.get("label") or c.get("partlabel") or "",
                          "parttype": c.get("parttype") or "", "start": start, "sectors": sectors,
                          "mounted": any(m for m in (c.get("mountpoints") or []) if m)})
        for p in parts:
            p["holds"] = guess_system(p)
        size = int(d.get("size") or 0)
        try:
            disk_sectors = int(Path(f"/sys/class/block/{d['name']}/size").read_text())
        except (OSError, ValueError):
            disk_sectors = size // SECTOR
        free = free_spans(d["name"], disk_sectors, parts)
        disks.append(disk_view(d["path"], (d.get("model") or "").strip(), d.get("tran") or "", d.get("rm") in (True, "1"), size, parts, free))
    return disks


def disk_view(path: str, model: str, tran: str, removable: bool, size: int, parts: list, free: list) -> dict:
    systems = sorted({p["holds"] for p in parts if p["holds"] in ("Windows", "Linux", "macOS")})
    best = max(free, key=lambda s: s[1]) if free else None
    kind = {"nvme": "NVMe drive", "sata": "SATA drive", "usb": "USB drive", "mmc": "Memory card", "virtio": "Virtual disk"}.get(tran, "Disk")
    return {"path": path, "model": model or kind, "kind": kind, "removable": removable, "size": size, "sizeText": size_text(size),
            "parts": parts, "systems": systems, "big": size >= MIN_BYTES,
            "freeStart": best[0] if best else 0, "freeBytes": best[1] * SECTOR if best else 0, "freeText": size_text(best[1] * SECTOR) if best else "",
            "hasEsp": any(p["holds"] == "EFI" for p in parts), "mounted": any(p["mounted"] for p in parts),
            "bar": [{"label": p["label"] or p["holds"], "holds": p["holds"], "share": p["size"] / size if size else 0, "sizeText": p["sizeText"], "free": False} for p in parts]
                   + ([{"label": "Free space", "holds": "Free", "share": best[1] * SECTOR / size, "sizeText": size_text(best[1] * SECTOR), "free": True}] if best else [])}


def demo_disks() -> list:
    w = [{"path": "/dev/nvme0n1p1", "name": "nvme0n1p1", "size": 272629760, "fstype": "vfat", "label": "SYSTEM", "parttype": "c12a7328-f81f-11d2-ba4b-00a0c93ec93b", "start": 2048, "sectors": 532480, "mounted": False},
         {"path": "/dev/nvme0n1p2", "name": "nvme0n1p2", "size": 16777216, "fstype": "", "label": "", "parttype": "e3c9e316-0b5c-4db8-817d-f92df00215ae", "start": 534528, "sectors": 32768, "mounted": False},
         {"path": "/dev/nvme0n1p3", "name": "nvme0n1p3", "size": 299 * 10 ** 9, "fstype": "ntfs", "label": "Windows", "parttype": "ebd0a0a2-b9e5-4433-87c0-68b6b72699c7", "start": 567296, "sectors": 299 * 10 ** 9 // 512, "mounted": False},
         {"path": "/dev/nvme0n1p4", "name": "nvme0n1p4", "size": 1 * 10 ** 9, "fstype": "ntfs", "label": "Recovery", "parttype": "de94bba4-06d1-4d40-a16a-bfd50179d6ac", "start": 584529000, "sectors": 1953125, "mounted": False}]
    for p in w:
        p["sizeText"] = size_text(p["size"]); p["holds"] = guess_system(p)
    free = [(586483712, (512 * 10 ** 9 - 586483712 * 512) // 512 - 34)]
    usb = [{"path": "/dev/sda1", "name": "sda1", "size": 64 * 10 ** 9, "fstype": "exfat", "label": "PHOTOS", "parttype": "0x7", "start": 2048, "sectors": 125000000, "mounted": False}]
    for p in usb:
        p["sizeText"] = size_text(p["size"]); p["holds"] = guess_system(p)
    return [disk_view("/dev/nvme0n1", "Samsung SSD 980 PRO", "nvme", False, 512 * 10 ** 9, w, free),
            disk_view("/dev/sda", "SanDisk Extreme", "usb", True, 64 * 10 ** 9, usb, [])]


def read_wifi() -> dict:
    if not shutil.which("nmcli"):
        return {"available": False, "networks": [], "wired": False, "connected": ""}
    _, devs, _ = run(["nmcli", "-t", "-f", "TYPE,STATE,CONNECTION", "device"])
    wired = any(line.startswith("ethernet:connected") for line in devs.splitlines())
    if not any(line.startswith("wifi:") for line in devs.splitlines()):          # no Wi‑Fi adapter at all
        return {"available": False, "networks": [], "wired": wired, "connected": ""}
    connected = next((line.split(":", 2)[2] for line in devs.splitlines() if line.startswith("wifi:connected")), "")
    _, scan, _ = run(["nmcli", "-t", "-f", "IN-USE,SSID,SIGNAL,SECURITY", "device", "wifi", "list", "--rescan", "auto"], timeout=25)
    best = {}
    for line in scan.splitlines():
        f = re.split(r"(?<!\\):", line)
        if len(f) < 4 or not f[1]:
            continue
        ssid = f[1].replace("\\:", ":")
        sig = int(f[2]) if f[2].isdigit() else 0
        if ssid not in best or sig > best[ssid]["signal"]:
            best[ssid] = {"ssid": ssid, "signal": sig, "secure": f[3] not in ("", "--"), "inUse": f[0] == "*"}
    return {"available": True, "networks": sorted(best.values(), key=lambda n: (not n["inUse"], -n["signal"])), "wired": wired, "connected": connected}


def locale_label(code: str) -> str:
    from PySide6.QtCore import QLocale
    q = QLocale(code)
    lang = q.nativeLanguageName() or code
    region = q.nativeTerritoryName() if hasattr(q, "nativeTerritoryName") else q.nativeCountryName()
    return f"{lang[:1].upper()}{lang[1:]} ({region})" if region else lang


def zone_list() -> list:
    try:
        import zoneinfo
        names = sorted(z for z in zoneinfo.available_timezones() if "/" in z and not z.startswith(("Etc/", "SystemV/", "US/", "posix/", "right/")))
    except Exception:                                       # noqa: BLE001
        names = ["UTC"]
    return [{"id": z, "city": z.rsplit("/", 1)[-1].replace("_", " "), "region": z.split("/", 1)[0].replace("_", " ")} for z in names]


def xkb_list() -> list:
    out, inside = [], False
    try:
        for line in Path("/usr/share/X11/xkb/rules/evdev.lst").read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("!"):
                inside = line.strip() == "! layout"
                continue
            if inside and line.strip():
                code, _, label = line.strip().partition(" ")
                out.append({"id": code, "label": label.strip()})
    except OSError:
        out = [{"id": c, "label": n} for c, n in (("us", "English (US)"), ("gb", "English (UK)"), ("de", "German"), ("fr", "French"),
                                                 ("es", "Spanish"), ("no", "Norwegian"), ("se", "Swedish"), ("jp", "Japanese"))]
    return sorted(out, key=lambda l: l["label"].lower())


def chassis() -> str:
    try:
        kind = int(Path("/sys/class/dmi/id/chassis_type").read_text().strip())
    except (OSError, ValueError):
        return "pc"
    return "laptop" if kind in (8, 9, 10, 14, 30, 31, 32) else "pc"


class Installer(QObject):
    changed = Signal()
    _wifiRead = Signal(object)                       # from the thread that asks NetworkManager (a scan takes seconds)
    _wifiJoined = Signal(str, int, str)
    progressed = Signal()
    said = Signal(str, bool)

    def __init__(self, demo: bool = False):
        super().__init__()
        self._demo = demo
        self._step = 0
        self._langs = sorted(({"id": c, "label": locale_label(c)} for c in LANGUAGES), key=lambda l: l["label"].lower())
        self._lang = "en_US"
        self._layouts = xkb_list()
        self._layout = "us"
        self._zones = zone_list()
        self._zone = self._guess_zone()
        self._wifi = {"available": True, "networks": [], "wired": False, "connected": ""}
        self._disks = demo_disks() if demo else read_disks()
        self._disk = next((d["path"] for d in self._disks if d["big"] and not d["removable"]), self._disks[0]["path"] if self._disks else "")
        self._mode = "erase"
        self._root = ""
        self._efi = ""
        self._format_efi = False
        self._encrypt = False
        self._passphrase = ""
        self._you = {"realName": "", "name": "", "hostname": "", "password": "", "again": "", "autologin": False, "hostTouched": False, "nameTouched": False}
        self._firmware = "uefi" if (demo or Path("/sys/firmware/efi").is_dir()) else "bios"
        self._state = "setup"                               # setup → installing → done | error
        self._fraction = 0.0
        self._label = ""
        self._note = ""
        self._error = ""
        self._log = []
        self._proc = None
        self._demo_timer = None
        self._wifi_busy = False
        self._wifiRead.connect(self._got_wifi)
        self._wifiJoined.connect(self._joined)
        if demo:
            self._wifi = {"available": True, "wired": False, "connected": "",
                          "networks": [{"ssid": "Valhalla", "signal": 92, "secure": True, "inUse": False}, {"ssid": "Bifrost-5G", "signal": 74, "secure": True, "inUse": False},
                                       {"ssid": "Library guest", "signal": 41, "secure": False, "inUse": False}]}

    # ------------------------------------------------------------------ where we are
    step = Property(int, lambda self: self._step, notify=changed)
    steps = Property("QVariantList", lambda self: [{"id": s, "label": l} for s, l in zip(STEPS, ["Welcome", "Keyboard", "Network", "Disk", "You", "Time Zone", "Ready"])], constant=True)
    state = Property(str, lambda self: self._state, notify=changed)
    slides = Property("QVariantList", lambda self: slides(), constant=True)
    demo = Property(bool, lambda self: self._demo, constant=True)

    @Slot()
    def next(self) -> None:
        problem = self.problem
        if problem:
            self.said.emit(problem, True)
            return
        if self._step < len(STEPS) - 1:
            self._step += 1
            if STEPS[self._step] == "network" and not self._demo:
                QTimer.singleShot(0, self.refreshWifi)
            self.changed.emit()

    @Slot()
    def back(self) -> None:
        if self._step > 0 and self._state == "setup":
            self._step -= 1
            self.changed.emit()

    @Slot(int)
    def goTo(self, i: int) -> None:
        if 0 <= i < self._step and self._state == "setup":
            self._step = i
            self.changed.emit()

    def _problem(self) -> str:
        s = STEPS[self._step]
        if s == "disk":
            d = self.chosenDisk
            if not d:
                return "There's no disk to put Huginn OS on."
            if self._mode == "erase" and not d.get("big"):
                return f"Huginn OS needs about {size_text(MIN_BYTES)}; this disk has {d.get('sizeText')}."
            if self._mode == "erase" and d.get("mounted"):
                return "Something on this disk is in use. Close it (or eject it in Files) first."
            if self._mode == "free" and d.get("freeBytes", 0) < MIN_BYTES:
                return f"The free space on this disk is {d.get('freeText') or 'none'}; Huginn OS needs about {size_text(MIN_BYTES)}."
            if self._mode == "manual":
                if not self._root:
                    return "Choose the partition for Huginn OS."
                if self._firmware == "uefi" and not self._efi:
                    return "Choose the EFI system partition."
                if self._root == self._efi:
                    return "Huginn OS and the EFI partition can't be the same partition."
            if self._encrypt:
                if len(self._passphrase) < 8:
                    return "The disk password needs 8 characters at least."
                if self._mode == "manual":
                    return "To encrypt, let the installer make the partitions (erase the disk, or use its free space)."
        if s == "you":
            u = self._you
            if not u["realName"].strip():
                return "What's your name?"
            if not engine.good_username(u["name"]):
                return "The user name can have small letters, digits, - and _, and must start with a letter."
            if not u["password"]:
                return "Choose a password."
            if u["password"] != u["again"]:
                return "The two passwords aren't the same."
        return ""

    problem = Property(str, _problem, notify=changed)

    # ------------------------------------------------------------------ language, keyboard, time zone
    languages = Property("QVariantList", lambda self: self._langs, constant=True)
    language = Property(str, lambda self: self._lang, notify=changed)
    layouts = Property("QVariantList", lambda self: self._layouts, constant=True)
    layout = Property(str, lambda self: self._layout, notify=changed)
    layoutLabel = Property(str, lambda self: next((l["label"] for l in self._layouts if l["id"] == self._layout), self._layout), notify=changed)
    languageLabel = Property(str, lambda self: next((l["label"] for l in self._langs if l["id"] == self._lang), self._lang), notify=changed)
    zones = Property("QVariantList", lambda self: self._zones, constant=True)
    zone = Property(str, lambda self: self._zone, notify=changed)
    zoneLabel = Property(str, lambda self: self._zone.rsplit("/", 1)[-1].replace("_", " ") + " (" + self._zone.split("/", 1)[0] + ")" if "/" in self._zone else self._zone, notify=changed)

    def _guess_zone(self) -> str:
        try:
            return os.path.realpath("/etc/localtime").split("zoneinfo/", 1)[1]
        except (IndexError, OSError):
            return "UTC"

    @Slot(str)
    def setLanguage(self, code: str) -> None:
        if code not in LANGUAGES:
            return
        self._lang = code
        lay, zone = GUESS.get(code, ("us", "UTC"))
        if any(l["id"] == lay for l in self._layouts):
            self.setLayout(lay)
        self._zone = zone
        self.changed.emit()

    @Slot(str)
    def setLayout(self, lay: str) -> None:
        if not re.fullmatch(r"[a-z]{2,8}", lay or ""):
            return
        self._layout = lay
        self.changed.emit()
        if not self._demo:                                  # try it right away, in the live session
            rc = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "kxkbrc"
            try:
                rc.parent.mkdir(parents=True, exist_ok=True)
                rc.write_text(f"[Layout]\nLayoutList={lay}\nUse=true\nResetOldOptions=true\n", encoding="utf-8")
                run(["dbus-send", "--session", "--type=signal", "/Layouts", "org.kde.keyboard.reloadConfig"], timeout=5)
            except OSError:
                pass
            if shutil.which("setxkbmap") and os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
                run(["setxkbmap", lay], timeout=5)

    @Slot(str)
    def setZone(self, zone: str) -> None:
        if any(z["id"] == zone for z in self._zones):
            self._zone = zone
            self.changed.emit()

    # ------------------------------------------------------------------ network
    wifi = Property("QVariantMap", lambda self: self._wifi, notify=changed)

    @Slot()
    def refreshWifi(self) -> None:
        if self._demo or self._wifi_busy:
            return
        self._wifi_busy = True
        threading.Thread(target=lambda: self._wifiRead.emit(read_wifi()), daemon=True).start()

    def _got_wifi(self, wifi: dict) -> None:
        self._wifi_busy = False
        self._wifi = wifi
        self.changed.emit()

    def _joined(self, ssid: str, code: int, message: str) -> None:
        self.said.emit(f"Connected to {ssid}." if code == 0 else "That didn't connect: " + message, code != 0)
        self.refreshWifi()

    @Slot(str, str)
    def connectWifi(self, ssid: str, password: str) -> None:
        if self._demo:
            self._wifi = dict(self._wifi, connected=ssid, networks=[dict(n, inUse=n["ssid"] == ssid) for n in self._wifi["networks"]])
            self.changed.emit()
            self.said.emit(f"Connected to {ssid}.", False)
            return
        argv = ["nmcli", "--wait", "25", "device", "wifi", "connect", ssid] + (["password", password] if password else [])

        def join():
            code, out, err = run(argv, timeout=40)
            self._wifiJoined.emit(ssid, code, ((err or out).strip().splitlines() or ["no reason given"])[-1])
        threading.Thread(target=join, daemon=True).start()

    # ------------------------------------------------------------------ the disk
    disks = Property("QVariantList", lambda self: self._disks, notify=changed)
    disk = Property(str, lambda self: self._disk, notify=changed)
    mode = Property(str, lambda self: self._mode, notify=changed)
    firmware = Property(str, lambda self: self._firmware, notify=changed)
    encrypt = Property(bool, lambda self: self._encrypt, notify=changed)
    root = Property(str, lambda self: self._root, notify=changed)
    efi = Property(str, lambda self: self._efi, notify=changed)
    chosenDisk = Property("QVariantMap", lambda self: next((d for d in self._disks if d["path"] == self._disk), {}), notify=changed)

    @Slot()
    def refreshDisks(self) -> None:
        if not self._demo:
            self._disks = read_disks()
        if not any(d["path"] == self._disk for d in self._disks):
            self._disk = self._disks[0]["path"] if self._disks else ""
        self.changed.emit()

    @Slot(str)
    def setDisk(self, path: str) -> None:
        if any(d["path"] == path for d in self._disks):
            self._disk, self._root, self._efi = path, "", ""
            d = self.chosenDisk
            if self._mode == "free" and not d.get("freeBytes"):
                self._mode = "erase"
            self.changed.emit()

    @Slot(str)
    def setMode(self, mode: str) -> None:
        if mode in ("erase", "free", "manual"):
            self._mode = mode
            if mode == "manual":
                self._encrypt = False
                esp = next((p["path"] for p in self.chosenDisk.get("parts", []) if p["holds"] == "EFI"), "")
                self._efi = self._efi or esp
            self.changed.emit()

    @Slot(str)
    def setRoot(self, path: str) -> None:
        self._root = path
        self.changed.emit()

    @Slot(str)
    def setEfi(self, path: str) -> None:
        self._efi = path
        self.changed.emit()

    @Slot(bool, str)
    def setEncrypt(self, on: bool, passphrase: str) -> None:
        self._encrypt, self._passphrase = bool(on) and self._mode != "manual", passphrase
        self.changed.emit()

    # ------------------------------------------------------------------ you
    you = Property("QVariantMap", lambda self: {k: v for k, v in self._you.items() if k not in ("password", "again")}
                   | {"hasPassword": bool(self._you["password"]), "same": self._you["password"] == self._you["again"],
                      "strength": strength(self._you["password"])}, notify=changed)

    @Slot(str, str)
    def setYou(self, key: str, value: str) -> None:
        u = self._you
        if key == "realName":
            u["realName"] = value[:80]
            first = re.sub(r"[^a-z0-9]", "", ascii_name((value.strip().split() or [""])[0].lower()))
            if not u["nameTouched"]:
                u["name"] = (first if first[:1].isalpha() else "") [:32]
            if not u["hostTouched"]:
                u["hostname"] = f"{first or 'huginn'}-{chassis()}"
        elif key == "name":
            u["name"], u["nameTouched"] = value.strip().lower()[:32], True
        elif key == "hostname":
            u["hostname"], u["hostTouched"] = value[:63], True
        elif key in ("password", "again"):
            u[key] = value
        elif key == "autologin":
            u["autologin"] = value == "true"
        self.changed.emit()

    # ------------------------------------------------------------------ the plan, and installing it
    def _plan(self) -> dict:
        d = self.chosenDisk
        u = self._you
        p = {"mode": self._mode, "disk": self._disk, "firmware": self._firmware, "encrypt": self._encrypt, "passphrase": self._passphrase if self._encrypt else "",
             "hostname": engine.good_hostname(u["hostname"] or (u["name"] + "-" + chassis())),
             "user": {"name": u["name"], "realName": u["realName"].strip(), "password": u["password"], "autologin": u["autologin"]},
             "timezone": self._zone, "locale": self._lang + ".UTF-8", "keyboard": {"layout": self._layout, "variant": ""}}
        if self._mode == "free":
            p["freeStart"] = d.get("freeStart", 0)
        if self._mode == "manual":
            p.update(root=self._root, efi=self._efi, formatEfi=self._format_efi)
        return p

    def _summary(self) -> list:
        d, u = self.chosenDisk, self._you
        where = {"erase": f"Erase {d.get('model', '')} ({d.get('sizeText', '')}) and put Huginn OS on all of it",
                 "free": f"Put Huginn OS in the {d.get('freeText', '')} of free space on {d.get('model', '')}" + (f", beside {' and '.join(d.get('systems'))}" if d.get("systems") else ""),
                 "manual": f"Put Huginn OS on {self._root} (it will be formatted)" + (f", starting from {self._efi}" if self._efi else "")}[self._mode]
        rows = [{"label": "Disk", "value": where, "warn": self._mode == "erase"},
                {"label": "Encryption", "value": "On: the disk asks for its password when the computer starts" if self._encrypt else "Off"},
                {"label": "You", "value": f"{u['realName'].strip()} ({u['name']})" + (", signing in by yourself" if u["autologin"] else "")},
                {"label": "Computer name", "value": engine.good_hostname(u["hostname"])},
                {"label": "Language", "value": self.languageLabel},
                {"label": "Keyboard", "value": self.layoutLabel},
                {"label": "Time zone", "value": self.zoneLabel}]
        return rows

    summary = Property("QVariantList", _summary, notify=changed)
    fraction = Property(float, lambda self: self._fraction, notify=progressed)
    label = Property(str, lambda self: self._label, notify=progressed)
    note = Property(str, lambda self: self._note, notify=progressed)
    error = Property(str, lambda self: self._error, notify=changed)
    log = Property(str, lambda self: "\n".join(self._log[-400:]), notify=progressed)

    @Slot()
    def install(self) -> None:
        if self._state == "installing":
            return
        plan = self._plan()
        problems = engine.check_plan(plan)
        if problems:
            self.said.emit(" ".join(problems), True)
            return
        self._state, self._fraction, self._label, self._error, self._log = "installing", 0.0, "Starting", "", []
        self.changed.emit(); self.progressed.emit()
        if self._demo:
            self._demo_install()
            return
        self._proc = QProcess(self)
        self._proc.setProgram("pkexec")
        self._proc.setArguments([ENGINE])
        self._proc.readyReadStandardOutput.connect(self._read)
        self._proc.readyReadStandardError.connect(lambda: self._log.extend(bytes(self._proc.readAllStandardError()).decode(errors="replace").splitlines()))
        self._proc.finished.connect(self._ended)
        self._buf = b""
        self._proc.start()
        self._proc.write(json.dumps(plan).encode())        # the plan, passwords included, only ever goes down this pipe
        self._proc.closeWriteChannel()
        self._you["password"] = self._you["again"] = ""
        self._passphrase = ""

    def _read(self) -> None:
        self._buf += bytes(self._proc.readAllStandardOutput())
        while b"\n" in self._buf:
            line, self._buf = self._buf.split(b"\n", 1)
            self._take(line.decode(errors="replace"))

    def _take(self, line: str) -> None:
        try:
            msg = json.loads(line)
        except ValueError:
            self._log.append(line)
            self.progressed.emit()
            return
        if "fraction" in msg:
            self._fraction, self._label, self._note = msg["fraction"], msg.get("label", ""), msg.get("note", "")
            self._log.append(f"{msg.get('label', '')} {msg.get('note', '')}".strip())
        elif msg.get("done"):
            self._state, self._fraction = "done", 1.0
            self.changed.emit()
        elif "error" in msg:
            self._state, self._error = "error", msg["error"]
            self._log.extend((msg.get("log") or "").splitlines())
            self.changed.emit()
        self.progressed.emit()

    def _ended(self, code: int, _status) -> None:
        if self._state == "installing":                     # it stopped without saying why (pkexec refused, a crash)
            self._state = "error"
            self._error = "The installer couldn't get permission to change the disks." if code in (126, 127) else f"The installer stopped (code {code})."
            self.changed.emit()

    def _demo_install(self) -> None:
        self._demo_t = 0

        def tick():
            self._demo_t += 1
            f = min(1.0, self._demo_t / 60)
            base = 0.0
            for k, label, w in engine.WEIGHTS:
                if f <= base + w:
                    self._label = label
                    break
                base += w
            self._fraction = f
            self._note = f"{int((f - 0.07) / 0.68 * 100)}%" if 0.07 < f < 0.75 else ""
            self._log.append(f"{self._label} {self._note}".strip())
            self.progressed.emit()
            if f >= 1.0:
                self._demo_timer.stop()
                self._state = "done"
                self.changed.emit()
        self._demo_timer = QTimer(self, interval=80, timeout=tick)
        self._demo_timer.start()

    @Slot()
    def retry(self) -> None:
        if self._state == "error":
            self._state, self._step = "setup", STEPS.index("ready")
            self.changed.emit()

    @Slot()
    def restart(self) -> None:
        if self._demo:
            self.said.emit("(Demo: this would restart the computer.)", False)
            return
        run(["systemctl", "reboot"], timeout=10)

    @Slot(result=str)
    def saveLog(self) -> str:
        path = Path.home() / "huginn-installer.log"
        try:
            path.write_text("\n".join(self._log) + "\n", encoding="utf-8")
            return str(path)
        except OSError:
            return ""


def ascii_name(text: str) -> str:
    """Hélène → helene, Bjørn → bjorn, Æsa → aesa: a name as plain letters, for a user name."""
    import unicodedata
    for a, b in (("æ", "ae"), ("ø", "o"), ("ß", "ss"), ("þ", "th"), ("ð", "d"), ("œ", "oe")):
        text = text.replace(a, b)
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))


def strength(pw: str) -> int:
    """0 (none) … 4 (strong): length and variety, roughly."""
    if not pw:
        return 0
    kinds = sum(bool(re.search(p, pw)) for p in (r"[a-z]", r"[A-Z]", r"\d", r"[^A-Za-z0-9]"))
    score = (len(pw) >= 8) + (len(pw) >= 12) + (len(pw) >= 16) + (kinds >= 3)
    return max(1, min(4, score))
