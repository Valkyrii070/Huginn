"""Machines: other operating systems in a window, on QEMU and KVM.

    a machine       a folder in ~/.local/share/huginn/machines: its settings (machine.json), its disk (disk.qcow2, which
                    only grows as it fills), its UEFI variables and TPM (for Windows 11), its pictures and snapshots
    making one      from an installer (.iso) in Downloads: Machines recognises Ubuntu, Fedora, Debian, Mint, Windows and
                    others and suggests memory, processors and disk size to match
    running it      qemu-system-x86_64 with KVM when the computer allows (TCG otherwise), controlled over QMP (pause,
                    resume, shut down, snapshots, changing the disc), shown in the window by Machines' own VNC client
                    over a private socket, so nothing listens on the network
    sharing         a folder of yours shows up inside Linux machines (9p, "hostshare"); the network is QEMU's own (NAT)

QMP: the QEMU Machine Protocol (JSON over a Unix socket). RFB: the protocol VNC speaks (version 3.8, raw and
CopyRect pictures, the DesktopSize change, keys as X keysyms, an absolute pointer through a USB tablet).
"""
import json
import os
import re
import shutil
import struct
import subprocess
import time
import uuid
from pathlib import Path

import numpy as np
from PySide6.QtCore import Property, QObject, QPointF, QProcess, QRectF, QTimer, QUrl, Qt, Signal, Slot
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtNetwork import QLocalSocket
from PySide6.QtQuick import QQuickPaintedItem

HOME_DIR = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share") / "huginn" / "machines"
RUN_DIR = Path(os.environ.get("XDG_RUNTIME_DIR") or "/tmp") / "huginn-machines"
OVMF_CODE = ["/usr/share/OVMF/OVMF_CODE_4M.ms.fd", "/usr/share/OVMF/OVMF_CODE_4M.fd", "/usr/share/OVMF/OVMF_CODE.fd"]
OVMF_VARS = ["/usr/share/OVMF/OVMF_VARS_4M.ms.fd", "/usr/share/OVMF/OVMF_VARS_4M.fd", "/usr/share/OVMF/OVMF_VARS.fd"]

# what Machines knows about systems people install: (match in the installer's name, name, kind, memory MB, processors, disk GB)
SYSTEMS = [("ubuntu", "Ubuntu", "linux", 4096, 2, 40), ("kubuntu", "Kubuntu", "linux", 4096, 2, 40), ("huginn", "Huginn OS", "linux", 4096, 2, 40),
           ("fedora", "Fedora", "linux", 4096, 2, 40), ("debian", "Debian", "linux", 2048, 2, 30), ("linuxmint", "Linux Mint", "linux", 4096, 2, 40),
           ("mint", "Linux Mint", "linux", 4096, 2, 40), ("pop-os", "Pop!_OS", "linux", 4096, 2, 40), ("archlinux", "Arch Linux", "linux", 2048, 2, 30),
           ("manjaro", "Manjaro", "linux", 4096, 2, 40), ("opensuse", "openSUSE", "linux", 4096, 2, 40), ("elementary", "elementary OS", "linux", 4096, 2, 40),
           ("alpine", "Alpine Linux", "linux", 1024, 1, 8), ("freebsd", "FreeBSD", "bsd", 2048, 2, 30),
           ("win11", "Windows 11", "windows", 8192, 4, 80), ("windows11", "Windows 11", "windows", 8192, 4, 80),
           ("win10", "Windows 10", "windows", 4096, 2, 64), ("windows10", "Windows 10", "windows", 4096, 2, 64), ("windows", "Windows", "windows", 8192, 4, 80)]


def recognise(iso: str) -> dict:
    """What an installer probably is, from its file name: name, kind and the settings that suit it."""
    low = Path(iso).name.lower()
    for key, name, kind, mem, cpus, disk in SYSTEMS:
        if key in low:
            version = re.search(r"(\d+(?:\.\d+)+)", low)
            if kind == "windows" and "11" not in name and "10" not in name:
                name = "Windows 11" if "11" in low else "Windows 10" if "10" in low else name
            return {"system": name + (f" {version.group(1)}" if version and kind != "windows" else ""), "kind": kind, "memory": mem, "cpus": cpus, "disk": disk}
    return {"system": Path(iso).stem or "Other", "kind": "other", "memory": 2048, "cpus": 2, "disk": 30}


def host_limits() -> dict:
    cpus = os.cpu_count() or 2
    try:
        mem = int(re.search(r"MemTotal:\s+(\d+)", Path("/proc/meminfo").read_text()).group(1)) // 1024
    except (OSError, AttributeError, ValueError):
        mem = 8192
    return {"cpus": cpus, "memory": mem, "kvm": os.access("/dev/kvm", os.R_OK | os.W_OK), "qemu": bool(shutil.which("qemu-system-x86_64")),
            "tpm": bool(shutil.which("swtpm")), "uefi": any(os.path.isfile(f) for f in OVMF_CODE), "home": str(Path.home())}


def first(paths: list) -> str:
    return next((p for p in paths if os.path.isfile(p)), "")


def qemu_command(m: dict, folder: Path, run: Path, kvm: bool, boot_cd: bool) -> list:
    """The qemu-system-x86_64 command line for a machine."""
    win = m.get("kind") == "windows"
    args = ["qemu-system-x86_64", "-name", f"{m['name'].replace(',', ',,')},process=huginn-vm-{m['id']}", "-machine", "q35,accel=" + ("kvm" if kvm else "tcg"),
            "-cpu", "host" if kvm else "max", "-m", str(int(m.get("memory", 2048))), "-smp", str(int(m.get("cpus", 2))),
            "-display", "none", "-vnc", f"unix:{run / 'vnc.sock'}", "-qmp", f"unix:{run / 'qmp.sock'},server=on,wait=off",
            "-device", "qemu-xhci,id=usb", "-device", "usb-tablet", "-rtc", "base=localtime" if win else "base=utc",
            "-device", "virtio-balloon-pci" if not win else "VGA", "-pidfile", str(run / "qemu.pid")]
    if m.get("firmware", "uefi") == "uefi" and first(OVMF_CODE):
        vars_ = folder / "vars.qcow2"                     # qcow2, so snapshots can include it
        args += ["-drive", f"if=pflash,format=raw,readonly=on,file={first(OVMF_CODE)}", "-drive", f"if=pflash,format=qcow2,file={vars_}"]
    disk = folder / "disk.qcow2"
    if disk.exists():
        if win:      # Windows has no virtio driver of its own: NVMe it knows
            args += ["-drive", f"file={disk},if=none,id=hd0,format=qcow2,discard=unmap", "-device", "nvme,drive=hd0,serial=huginn0,bootindex=1"]
        else:
            args += ["-drive", f"file={disk},if=none,id=hd0,format=qcow2,discard=unmap,cache=writeback", "-device", "virtio-blk-pci,drive=hd0,bootindex=1"]
    iso = m.get("iso", "")
    args += ["-drive", "id=cd0,if=none,media=cdrom,readonly=on" + (f",file={iso}" if iso and os.path.isfile(iso) else ""),
             "-device", f"ide-cd,drive=cd0,bus=ide.0{',bootindex=0' if boot_cd else ',bootindex=2'}"]
    if not win:
        args += ["-device", "virtio-vga"]
    net = m.get("network", "nat")
    if net != "none":
        args += ["-nic", "user,model=" + ("e1000e" if win else "virtio-net-pci")]
    else:
        args += ["-nic", "none"]
    share = m.get("share", "")
    if share and os.path.isdir(share) and not win:
        args += ["-virtfs", f"local,path={share},mount_tag=hostshare,security_model=mapped-xattr,id=hostshare"]
    if m.get("sound", True) and shutil.which("pw-cli"):
        args += ["-audiodev", "pipewire,id=snd0", "-device", "intel-hda", "-device", "hda-duplex,audiodev=snd0"]
    if m.get("tpm") and shutil.which("swtpm"):
        args += ["-chardev", f"socket,id=chrtpm,path={run / 'swtpm.sock'}", "-tpmdev", "emulator,id=tpm0,chardev=chrtpm", "-device", "tpm-tis,tpmdev=tpm0"]
    return args


# ------------------------------------------------------------------------------------------------- QMP
class Qmp(QObject):
    """QEMU's control socket: JSON commands, answers in order, events in between."""
    event = Signal(str, "QVariantMap")
    ready = Signal()
    gone = Signal()

    def __init__(self, path: str, parent=None):
        super().__init__(parent)
        self.path, self.buf, self.waiting, self.up = path, b"", [], False
        self.sock = QLocalSocket(self)
        self.sock.readyRead.connect(self._read)
        self.sock.disconnected.connect(self.gone.emit)
        self.tries = 0
        self.timer = QTimer(self, interval=150)
        self.timer.timeout.connect(self._try)
        self.timer.start()

    def _try(self) -> None:
        self.tries += 1
        if self.sock.state() == QLocalSocket.LocalSocketState.UnconnectedState and os.path.exists(self.path):
            self.sock.connectToServer(self.path)
        if self.sock.state() == QLocalSocket.LocalSocketState.ConnectedState or self.tries > 800:
            self.timer.stop()

    def _read(self) -> None:
        self.buf += bytes(self.sock.readAll())
        while b"\n" in self.buf:
            line, self.buf = self.buf.split(b"\n", 1)
            try:
                msg = json.loads(line)
            except ValueError:
                continue
            if "QMP" in msg:
                self._send({"execute": "qmp_capabilities"}, lambda r, e: (setattr(self, "up", True), self.ready.emit()))
            elif "event" in msg:
                self.event.emit(msg["event"], msg.get("data") or {})
            elif "return" in msg or "error" in msg:
                if self.waiting:
                    then = self.waiting.pop(0)
                    if then:
                        then(msg.get("return"), (msg.get("error") or {}).get("desc"))

    def _send(self, msg: dict, then=None) -> None:
        self.waiting.append(then)
        self.sock.write(json.dumps(msg).encode() + b"\n")
        self.sock.flush()

    def run(self, command: str, args: dict = None, then=None) -> None:
        if not self.up:
            if then:
                then(None, "not connected")
            return
        self._send({"execute": command, **({"arguments": args} if args else {})}, then)

    def hmp(self, line: str, then=None) -> None:
        self.run("human-monitor-command", {"command-line": line}, then)

    def close(self) -> None:
        self.timer.stop()
        self.sock.abort()


# ------------------------------------------------------------------------------------------------- RFB (VNC)
KEYSYMS = {Qt.Key.Key_Return: 0xFF0D, Qt.Key.Key_Enter: 0xFF8D, Qt.Key.Key_Backspace: 0xFF08, Qt.Key.Key_Tab: 0xFF09, Qt.Key.Key_Backtab: 0xFF09,
           Qt.Key.Key_Escape: 0xFF1B, Qt.Key.Key_Delete: 0xFFFF, Qt.Key.Key_Insert: 0xFF63, Qt.Key.Key_Home: 0xFF50, Qt.Key.Key_End: 0xFF57,
           Qt.Key.Key_Left: 0xFF51, Qt.Key.Key_Up: 0xFF52, Qt.Key.Key_Right: 0xFF53, Qt.Key.Key_Down: 0xFF54, Qt.Key.Key_PageUp: 0xFF55,
           Qt.Key.Key_PageDown: 0xFF56, Qt.Key.Key_Shift: 0xFFE1, Qt.Key.Key_Control: 0xFFE3, Qt.Key.Key_Alt: 0xFFE9, Qt.Key.Key_AltGr: 0xFE03,
           Qt.Key.Key_Meta: 0xFFEB, Qt.Key.Key_Super_L: 0xFFEB, Qt.Key.Key_Super_R: 0xFFEC, Qt.Key.Key_CapsLock: 0xFFE5, Qt.Key.Key_Menu: 0xFF67,
           Qt.Key.Key_Print: 0xFF61, Qt.Key.Key_ScrollLock: 0xFF14, Qt.Key.Key_Pause: 0xFF13, Qt.Key.Key_NumLock: 0xFF7F, Qt.Key.Key_Space: 0x20}
for _n in range(1, 13):
    KEYSYMS[getattr(Qt.Key, f"Key_F{_n}")] = 0xFFBD + _n


def keysym(key: int, text: str) -> int:
    """The X keysym for a key press: special keys from the table, letters and symbols from what they type."""
    try:
        k = Qt.Key(key)
    except ValueError:
        k = None
    if k in KEYSYMS:
        return KEYSYMS[k]
    if text and text.isprintable():
        c = ord(text[0])
        return c if c < 0x100 else 0x01000000 + c
    if Qt.Key.Key_A.value <= key <= Qt.Key.Key_Z.value:          # with Ctrl held, text is a control character
        return ord("a") + key - Qt.Key.Key_A.value
    if 0x20 <= key < 0x7F:
        return key
    return 0


class Rfb(QObject):
    """A VNC client for one machine's screen, over a Unix socket: the picture is kept in `image`."""
    frame = Signal(QRectF)          # a part of the picture changed
    resized = Signal()
    connectedChanged = Signal()
    bell = Signal()

    def __init__(self, path: str, parent=None):
        super().__init__(parent)
        self.path = path
        self.image = QImage(640, 400, QImage.Format.Format_RGB32)
        self.image.fill(QColor("#000000"))
        self.buf = bytearray()
        self.stage = "version"
        self.need = 12
        self.rects = 0
        self.rect = None
        self.sock = QLocalSocket(self)
        self.sock.readyRead.connect(self._read)
        self.sock.connected.connect(self._fresh)
        self.sock.disconnected.connect(self._lost)
        self._up = False
        self.closing = False
        self.buttons = 0
        self.tries = 0
        self.retry = QTimer(self, interval=200)
        self.retry.timeout.connect(self._try)
        self.retry.start()
        self.poll = QTimer(self, interval=33)                  # ask for changes ~30 times a second
        self.poll.timeout.connect(lambda: self._request(True))

    connected = Property(bool, lambda self: self._up, notify=connectedChanged)

    def _try(self) -> None:
        self.tries += 1
        if self.sock.state() == QLocalSocket.LocalSocketState.UnconnectedState and os.path.exists(self.path):
            self.sock.connectToServer(self.path)
        if self._up or self.tries > 900:
            self.retry.stop()

    def _fresh(self) -> None:
        """A new connection starts the conversation from the beginning."""
        self.buf, self.stage, self.rect, self.rects = bytearray(), "version", None, 0
        self.connectedChanged.emit()

    def _lost(self) -> None:
        """QEMU can close a connection made while it's still starting: try again, as long as the machine is there."""
        self._up = False
        self.poll.stop()
        self.connectedChanged.emit()
        if not self.closing and not self.retry.isActive():
            self.tries = max(0, self.tries - 50)
            self.retry.start()

    def _send(self, data: bytes) -> None:
        if self.sock.state() == QLocalSocket.LocalSocketState.ConnectedState:
            self.sock.write(data)
            self.sock.flush()

    def _request(self, incremental: bool) -> None:
        self._send(struct.pack(">BBHHHH", 3, 1 if incremental else 0, 0, 0, self.image.width(), self.image.height()))

    def _read(self) -> None:
        self.buf += bytes(self.sock.readAll())
        while True:
            if not self._step():
                break

    def _take(self, n: int):
        if len(self.buf) < n:
            return None
        out = bytes(self.buf[:n])
        del self.buf[:n]
        return out

    def _step(self) -> bool:
        s = self.stage
        if s == "version":
            v = self._take(12)
            if v is None:
                return False
            self._send(b"RFB 003.008\n")
            self.stage = "sectypes"
        elif s == "sectypes":
            if len(self.buf) < 1 or len(self.buf) < 1 + self.buf[0]:
                return False
            n = self.buf[0]
            types = self._take(1 + n)[1:]
            if n == 0 or 1 not in types:
                self.sock.abort()
                return False
            self._send(b"\x01")
            self.stage = "secresult"
        elif s == "secresult":
            r = self._take(4)
            if r is None:
                return False
            if struct.unpack(">I", r)[0] != 0:
                self.sock.abort()
                return False
            self._send(b"\x01")                                   # shared
            self.stage = "init"
        elif s == "init":
            if len(self.buf) < 24:
                return False
            namelen = struct.unpack(">I", bytes(self.buf[20:24]))[0]
            head = self._take(24 + namelen)
            if head is None:
                return False
            w, h = struct.unpack(">HH", head[:4])
            self._resize(w, h)
            # 32 bits a pixel, little-endian xRGB: the same bytes as QImage's RGB32
            self._send(struct.pack(">BxxxBBBBHHHBBBxxx", 0, 32, 24, 0, 1, 255, 255, 255, 16, 8, 0))
            encodings = [0, 1, -223]                              # raw, CopyRect, DesktopSize
            self._send(struct.pack(">BxH", 2, len(encodings)) + b"".join(struct.pack(">i", e) for e in encodings))
            self._up = True
            self.connectedChanged.emit()
            self._request(False)
            self.poll.start()
            self.stage = "message"
        elif s == "message":
            if not self.buf:
                return False
            kind = self.buf[0]
            if kind == 0:
                head = self._take(4)
                if head is None:
                    return False
                self.rects = struct.unpack(">H", head[2:4])[0]
                self.stage = "rect" if self.rects else "message"
            elif kind == 1:
                if len(self.buf) < 6:
                    return False
                n = struct.unpack(">H", bytes(self.buf[4:6]))[0]
                if self._take(6 + 6 * n) is None:
                    return False
            elif kind == 2:
                self._take(1)
                self.bell.emit()
            elif kind == 3:
                if len(self.buf) < 8:
                    return False
                n = struct.unpack(">I", bytes(self.buf[4:8]))[0]
                if self._take(8 + n) is None:
                    return False
            else:
                self.sock.abort()
                return False
        elif s == "rect":
            head = self._take(12) if self.rect is None else None
            if self.rect is None:
                if head is None:
                    return False
                self.rect = struct.unpack(">HHHHi", head)
            x, y, w, h, enc = self.rect
            if enc == 0:
                data = self._take(w * h * 4)
                if data is None:
                    return False
                # VNC leaves the fourth byte of each pixel as 0; Qt's scene graph would take that as see-through
                opaque = (np.frombuffer(data, dtype=np.uint32) | np.uint32(0xFF000000)).tobytes()
                part = QImage(opaque, w, h, w * 4, QImage.Format.Format_RGB32)
                p = QPainter(self.image)
                p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
                p.drawImage(x, y, part)
                p.end()
                self.frame.emit(QRectF(x, y, w, h))
            elif enc == 1:
                src = self._take(4)
                if src is None:
                    return False
                sx, sy = struct.unpack(">HH", src)
                piece = self.image.copy(sx, sy, w, h)
                p = QPainter(self.image)
                p.drawImage(x, y, piece)
                p.end()
                self.frame.emit(QRectF(x, y, w, h))
            elif enc == -223:
                self._resize(w, h)
            else:
                self.sock.abort()
                return False
            self.rect = None
            self.rects -= 1
            if self.rects <= 0:
                self.stage = "message"
        return True

    def _resize(self, w: int, h: int) -> None:
        if (w, h) != (self.image.width(), self.image.height()) and w > 0 and h > 0:
            self.image = QImage(w, h, QImage.Format.Format_RGB32)
            self.image.fill(QColor("#000000"))
            self.resized.emit()

    # ---- what the person does
    def key(self, keysym_: int, down: bool) -> None:
        if keysym_:
            self._send(struct.pack(">BBxxI", 4, 1 if down else 0, keysym_))

    def pointer(self, x: int, y: int, buttons: int) -> None:
        self.buttons = buttons
        self._send(struct.pack(">BBHH", 5, buttons & 0xFF, max(0, min(self.image.width() - 1, x)), max(0, min(self.image.height() - 1, y))))

    def paste(self, text: str) -> None:
        data = text.encode("latin-1", errors="replace")
        self._send(struct.pack(">BxxxI", 6, len(data)) + data)

    def close(self) -> None:
        self.closing = True
        self.retry.stop()
        self.poll.stop()
        self.sock.abort()


class Screen(QQuickPaintedItem):
    """A machine's screen in the window: the picture fitted with its own shape, and the keyboard and pointer passed
    through while it has focus."""
    clientChanged = Signal()
    grabbedChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._client = None
        self.setAcceptedMouseButtons(Qt.MouseButton.AllButtons)
        self.setAcceptHoverEvents(True)
        self.setFlag(QQuickPaintedItem.Flag.ItemAcceptsInputMethod, True)
        self.setActiveFocusOnTab(True)
        self.setFillColor(QColor("#000000"))
        self._held = set()
        self.visibleChanged.connect(self.update)                 # a still picture must show once it's visible
        self.widthChanged.connect(self.update)
        self.heightChanged.connect(self.update)

    def _get_client(self):
        return self._client

    def _set_client(self, c) -> None:
        if c is self._client:
            return
        if self._client is not None:
            for sig in (self._client.frame, self._client.resized):
                try:
                    sig.disconnect(self._changed)
                except (RuntimeError, TypeError):
                    pass
        self._client = c
        if c is not None:
            c.frame.connect(self._changed)
            c.resized.connect(self._changed)
        self.clientChanged.emit()
        self.update()

    client = Property(QObject, _get_client, _set_client, notify=clientChanged)

    def _changed(self, *_):
        self.update()

    def _fit(self) -> QRectF:
        img = self._client.image if self._client else None
        if img is None or img.isNull():
            return QRectF(0, 0, self.width(), self.height())
        s = min(self.width() / img.width(), self.height() / img.height())
        w, h = img.width() * s, img.height() * s
        return QRectF((self.width() - w) / 2, (self.height() - h) / 2, w, h)

    def paint(self, p: QPainter) -> None:
        if self._client is None:
            return
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        p.drawImage(self._fit(), self._client.image)

    def _guest(self, pos: QPointF):
        r = self._fit()
        img = self._client.image
        return int((pos.x() - r.x()) / r.width() * img.width()), int((pos.y() - r.y()) / r.height() * img.height())

    @staticmethod
    def _mask(buttons) -> int:
        b = int(buttons.value if hasattr(buttons, "value") else buttons)
        return (1 if b & 1 else 0) | (2 if b & 4 else 0) | (4 if b & 2 else 0)

    def mousePressEvent(self, e):
        self.forceActiveFocus()
        if self._client:
            x, y = self._guest(e.position())
            self._client.pointer(x, y, self._mask(e.buttons()))
        e.accept()

    def mouseReleaseEvent(self, e):
        if self._client:
            x, y = self._guest(e.position())
            self._client.pointer(x, y, self._mask(e.buttons()))
        e.accept()

    def mouseMoveEvent(self, e):
        if self._client:
            x, y = self._guest(e.position())
            self._client.pointer(x, y, self._mask(e.buttons()))

    def hoverMoveEvent(self, e):
        if self._client and self.hasActiveFocus():
            x, y = self._guest(e.position())
            self._client.pointer(x, y, self._client.buttons)

    def wheelEvent(self, e):
        if not self._client:
            return
        x, y = self._guest(e.position())
        bit = 8 if e.angleDelta().y() > 0 else 16
        self._client.pointer(x, y, self._client.buttons | bit)
        self._client.pointer(x, y, self._client.buttons & ~bit)
        e.accept()

    def keyPressEvent(self, e):
        if self._client:
            ks = keysym(e.key(), e.text())
            self._held.add(ks)
            self._client.key(ks, True)
        e.accept()

    def keyReleaseEvent(self, e):
        if self._client and not e.isAutoRepeat():
            ks = keysym(e.key(), e.text())
            self._client.key(ks, False)
            self._held.discard(ks)
        e.accept()

    def focusOutEvent(self, e):
        if self._client:                                          # nothing stays held down in the machine
            for ks in list(self._held):
                self._client.key(ks, False)
        self._held.clear()
        super().focusOutEvent(e)

    @Slot(str)
    def press(self, combo: str) -> None:
        """Send a key combination the window would otherwise keep, such as "ctrl+alt+delete"."""
        if not self._client:
            return
        names = {"ctrl": 0xFFE3, "alt": 0xFFE9, "shift": 0xFFE1, "super": 0xFFEB, "delete": 0xFFFF, "tab": 0xFF09, "escape": 0xFF1B,
                 "backspace": 0xFF08, "printscreen": 0xFF61, **{f"f{n}": 0xFFBD + n for n in range(1, 13)}}
        keys = [names.get(k, ord(k[0]) if len(k) == 1 else 0) for k in combo.lower().split("+")]
        for k in keys:
            self._client.key(k, True)
        for k in reversed(keys):
            self._client.key(k, False)

    @Slot(str)
    def type(self, text: str) -> None:
        """Type text into the machine, a key at a time (for pasting where the guest has no shared clipboard)."""
        if not self._client:
            return
        for ch in text:
            ks = 0xFF0D if ch == "\n" else keysym(0, ch)
            upper = ch.isupper() or ch in '~!@#$%^&*()_+{}|:"<>?'
            if upper:
                self._client.key(0xFFE1, True)
            self._client.key(ks, True)
            self._client.key(ks, False)
            if upper:
                self._client.key(0xFFE1, False)


# ------------------------------------------------------------------------------------------------- the machines
class Running(QObject):
    """One machine that's on: its QEMU process, its control socket and its screen."""

    def __init__(self, m: dict, folder: Path, owner: "Machines"):
        super().__init__(owner)
        self.m, self.folder, self.owner = m, folder, owner
        self.run = RUN_DIR / m["id"]
        shutil.rmtree(self.run, ignore_errors=True)
        self.run.mkdir(parents=True, exist_ok=True)
        self.state = "starting"
        self.proc = QProcess(self)
        self.proc.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self.log = ""
        self.proc.readyRead.connect(lambda: setattr(self, "log", (self.log + bytes(self.proc.readAll()).decode(errors="replace"))[-4000:]))
        self.proc.finished.connect(self._ended)
        self.tpm = None
        self.qmp = None
        self.screen = None

    def start(self, kvm: bool, boot_cd: bool) -> None:
        if self.m.get("tpm") and shutil.which("swtpm"):
            (self.folder / "tpm").mkdir(exist_ok=True)
            self.tpm = QProcess(self)
            self.tpm.start("swtpm", ["socket", "--tpmstate", f"dir={self.folder / 'tpm'}", "--ctrl", f"type=unixio,path={self.run / 'swtpm.sock'}",
                                     "--tpm2", "--terminate"])
            self.tpm.waitForStarted(3000)
            for _ in range(30):
                if (self.run / "swtpm.sock").exists():
                    break
                time.sleep(0.05)
        args = qemu_command(self.m, self.folder, self.run, kvm, boot_cd)
        if self.m.get("resume"):                                   # carry on where it was when Machines closed
            args += ["-loadvm", "huginn-resume"]
        self.proc.start(args[0], args[1:])
        self.qmp = Qmp(str(self.run / "qmp.sock"), self)
        self.qmp.ready.connect(self._ready)
        self.qmp.event.connect(self._event)
        self.screen = Rfb(str(self.run / "vnc.sock"), self)

    def _ready(self) -> None:
        self.state = "running"
        self.owner._changed_state(self)

    def _event(self, name: str, data: dict) -> None:
        if name == "STOP":
            self.state = "paused"
        elif name == "RESUME":
            self.state = "running"
        elif name in ("SHUTDOWN", "POWERDOWN") and name == "SHUTDOWN":
            self.state = "stopping"
        self.owner._changed_state(self)

    def _ended(self, code, _status) -> None:
        self.state = "off"
        if self.screen:
            self.screen.close()
        if self.qmp:
            self.qmp.close()
        if self.tpm is not None and self.tpm.state() != QProcess.ProcessState.NotRunning:
            self.tpm.kill()
        self.owner._ended(self, code)

    def snapshot_picture(self, then=None) -> None:
        if self.qmp and self.qmp.up:
            target = str(self.folder / "screen.png")
            self.qmp.run("screendump", {"filename": target, "format": "png"}, lambda r, e: then() if then else None)


class Machines(QObject):
    changed = Signal()
    said = Signal(str, bool)

    def __init__(self, demo: bool = False):
        super().__init__()
        self._demo = demo
        self._list = []
        self._running = {}
        self._open = ""
        self._limits = host_limits()
        self._version = 0
        self._shots = QTimer(self, interval=8000)
        self._shots.timeout.connect(self._pictures)
        self._shots.start()
        if demo:
            self._demo_fill()
        else:
            self._load()

    # ---- the library
    def _load(self) -> None:
        self._list = []
        if HOME_DIR.is_dir():
            for d in sorted(HOME_DIR.iterdir()):
                try:
                    m = json.loads((d / "machine.json").read_text(encoding="utf-8"))
                    m["id"] = d.name
                    self._list.append(m)
                except (OSError, ValueError):
                    continue
        self._list.sort(key=lambda m: -float(m.get("used", m.get("created", 0))))

    def _save(self, m: dict) -> None:
        if self._demo:
            return
        folder = HOME_DIR / m["id"]
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "machine.json").write_text(json.dumps({k: v for k, v in m.items() if k != "id"}, indent=2), encoding="utf-8")

    def _demo_fill(self) -> None:
        now = time.time()
        self._list = [{"id": "d1", "name": "Ubuntu 26.04", "system": "Ubuntu 26.04", "kind": "linux", "memory": 4096, "cpus": 4, "disk": 40, "firmware": "uefi", "used": now - 3600, "created": now - 86400 * 20,
                       "share": str(Path.home() / "Public"), "snapshots": [{"name": "Fresh install", "when": now - 86400 * 19}, {"name": "Before the upgrade", "when": now - 86400 * 2}]},
                      {"id": "d2", "name": "Windows 11", "system": "Windows 11", "kind": "windows", "memory": 8192, "cpus": 4, "disk": 80, "firmware": "uefi", "tpm": True,
                       "used": now - 86400 * 3, "created": now - 86400 * 40, "snapshots": []},
                      {"id": "d3", "name": "Fedora 43", "system": "Fedora 43", "kind": "linux", "memory": 4096, "cpus": 2, "disk": 40, "firmware": "uefi", "used": now - 86400 * 9,
                       "created": now - 86400 * 9, "snapshots": []},
                      {"id": "d4", "name": "Huginn OS nightly", "system": "Huginn OS", "kind": "linux", "memory": 4096, "cpus": 2, "disk": 40, "firmware": "uefi", "used": now - 600,
                       "created": now - 86400, "snapshots": [{"name": "Before Phase 3", "when": now - 7200}]}]
        self._demo_state = {"d1": "running", "d4": "paused"}
        self._demo_dir = RUN_DIR / f"demo-{os.getpid()}"
        self._demo_dir.mkdir(parents=True, exist_ok=True)
        for mid, look in (("d1", "ubuntu"), ("d2", "windows"), ("d4", "huginn")):
            demo_desktop(look).save(str(self._demo_dir / f"{mid}.png"))
        self._limits.update(kvm=True, qemu=True, tpm=True, uefi=True)

    def _state_of(self, mid: str) -> str:
        if self._demo:
            return self._demo_state.get(mid, "off")
        r = self._running.get(mid)
        return r.state if r else "off"

    def _view(self, m: dict) -> dict:
        folder = HOME_DIR / m["id"]
        shot = folder / "screen.png"
        used = m.get("used", 0)
        ago = time.time() - used if used else 0
        n = int(ago // 60) if ago < 3600 else int(ago // 3600) if ago < 86400 else int(ago // 86400)
        unit = "minute" if ago < 3600 else "hour" if ago < 86400 else "day"
        when = "Never started" if not used else "Just now" if ago < 120 else f"{n} {unit}{'s' if n != 1 else ''} ago"
        if self._demo:
            shot = self._demo_dir / f"{m['id']}.png"
        return {**m, "state": self._state_of(m["id"]), "when": when, "picture": QUrl.fromLocalFile(str(shot)).toString() + f"?{self._version}" if shot.exists() else "",
                "diskUsed": self._disk_used(m), "snapshots": m.get("snapshots", [])}

    def _disk_used(self, m: dict) -> str:
        try:
            size = (HOME_DIR / m["id"] / "disk.qcow2").stat().st_blocks * 512
        except OSError:
            size = int(m.get("disk", 0) * 0.3 * 1024 ** 3) if self._demo else 0
        return f"{size / 1024 ** 3:.1f} GB" if size >= 1024 ** 3 else f"{size // 1024 ** 2} MB"

    machines = Property("QVariantList", lambda self: [self._view(m) for m in self._list], notify=changed)
    limits = Property("QVariantMap", lambda self: self._limits, constant=True)
    openId = Property(str, lambda self: self._open, notify=changed)

    @Property("QVariantMap", notify=changed)
    def current(self):
        m = self._get(self._open)
        return self._view(m) if m else {}

    @Property(QObject, notify=changed)
    def screen(self):
        r = self._running.get(self._open)
        return r.screen if r else None

    def _get(self, mid: str) -> dict:
        return next((m for m in self._list if m["id"] == mid), None)

    # ---- making a machine
    @Slot(result="QVariantList")
    def installers(self) -> list:
        found = []
        for base in (Path.home() / "Downloads", Path.home() / "Desktop", Path.home() / "Documents", Path.home() / "ISOs", Path.home()):
            if base.is_dir():
                found += [q for q in base.glob("*.iso")]
        found = sorted(set(found), key=lambda q: -q.stat().st_mtime)
        out = [{"path": str(q), "file": q.name, "size": f"{q.stat().st_size / 1024 ** 3:.1f} GB", **recognise(str(q))} for q in found[:30]]
        if self._demo and not out:
            out = [{"path": "/demo/ubuntu-26.04-desktop-amd64.iso", "file": "ubuntu-26.04-desktop-amd64.iso", "size": "6.1 GB", **recognise("ubuntu-26.04-desktop-amd64.iso")},
                   {"path": "/demo/Win11_25H2_English_x64.iso", "file": "Win11_25H2_English_x64.iso", "size": "7.4 GB", **recognise("Win11_25H2_English_x64.iso")},
                   {"path": "/demo/Fedora-Workstation-Live-43.iso", "file": "Fedora-Workstation-Live-43.iso", "size": "2.3 GB", **recognise("Fedora-Workstation-Live-43.iso")}]
        return out

    @Slot(str, result="QVariantMap")
    def suggest(self, iso: str) -> dict:
        r = recognise(iso)
        r["memory"] = min(r["memory"], max(1024, self._limits["memory"] // 2))
        r["cpus"] = min(r["cpus"], max(1, self._limits["cpus"] // 2))
        r["tpm"] = r["kind"] == "windows"
        return r

    @Slot("QVariantMap", result=str)
    def create(self, spec) -> str:
        """Make a machine: its folder, a disk that grows as it fills, UEFI variables. Gives the new machine's id, or ""."""
        spec = spec.toVariant() if hasattr(spec, "toVariant") else dict(spec)
        name = (spec.get("name") or "").strip() or recognise(spec.get("iso", ""))["system"]
        mid = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:24] + "-" + uuid.uuid4().hex[:4]
        info = recognise(spec.get("iso", ""))
        m = {"id": mid, "name": name, "system": info["system"], "kind": spec.get("kind") or info["kind"], "iso": spec.get("iso", ""),
             "memory": int(spec.get("memory") or info["memory"]), "cpus": int(spec.get("cpus") or info["cpus"]), "disk": int(spec.get("disk") or info["disk"]),
             "firmware": "uefi" if self._limits["uefi"] else "bios", "tpm": bool(spec.get("tpm", info["kind"] == "windows")),
             "share": spec.get("share", ""), "network": "nat", "sound": True, "created": time.time(), "used": 0, "installed": False, "snapshots": []}
        if self._demo:
            self._list.insert(0, m)
            self.changed.emit()
            return mid
        if not shutil.which("qemu-img"):
            self.said.emit("Making machines needs QEMU (qemu-utils).", True)
            return ""
        folder = HOME_DIR / mid
        folder.mkdir(parents=True, exist_ok=True)
        r = subprocess.run(["qemu-img", "create", "-q", "-f", "qcow2", "-o", "lazy_refcounts=on", str(folder / "disk.qcow2"), f"{m['disk']}G"],
                           capture_output=True, text=True, timeout=60)
        if r.returncode != 0:
            shutil.rmtree(folder, ignore_errors=True)
            self.said.emit("Couldn't make its disk: " + r.stderr.strip()[:140], True)
            return ""
        if m["firmware"] == "uefi" and first(OVMF_VARS):
            subprocess.run(["qemu-img", "convert", "-q", "-f", "raw", "-O", "qcow2", first(OVMF_VARS), str(folder / "vars.qcow2")], timeout=60)
        self._save(m)
        self._list.insert(0, m)
        self.changed.emit()
        return mid

    @Slot(str, str, "QVariant")
    def setting(self, mid: str, key: str, value) -> None:
        m = self._get(mid)
        if not m or key not in ("name", "memory", "cpus", "share", "network", "iso", "sound"):
            return
        value = value.toVariant() if hasattr(value, "toVariant") else value
        if key in ("memory", "cpus"):
            value = int(value)
        if key == "share" and value == "public":                  # share the Public folder (made if it isn't there)
            value = str(Path.home() / "Public")
            if not self._demo:
                Path(value).mkdir(parents=True, exist_ok=True)
        m[key] = value
        self._save(m)
        if key == "iso" and mid in self._running:                # change the disc in a running machine
            r = self._running[mid]
            if value:
                r.qmp.hmp(f"change cd0 {value}")
            else:
                r.qmp.hmp("eject -f cd0")
        self.changed.emit()

    @Slot(str, result=str)
    def remove(self, mid: str) -> str:
        if mid in self._running:
            return "Shut it down first."
        self._list = [m for m in self._list if m["id"] != mid]
        if not self._demo:
            shutil.rmtree(HOME_DIR / mid, ignore_errors=True)
        if self._open == mid:
            self._open = ""
        self.changed.emit()
        return ""

    # ---- running
    @Slot(str)
    def open(self, mid: str) -> None:
        self._open = mid
        self.changed.emit()

    @Slot()
    def close(self) -> None:
        r = self._running.get(self._open)
        if r:
            r.snapshot_picture(self._picture_taken)
        self._open = ""
        self.changed.emit()

    @Slot(str)
    def start(self, mid: str) -> None:
        m = self._get(mid)
        if not m:
            return
        self._open = mid
        if self._demo:
            self._demo_state[mid] = "running"
            self.changed.emit()
            return
        if mid in self._running:
            self.changed.emit()
            return
        if not self._limits["qemu"]:
            self.said.emit("Running machines needs QEMU (qemu-system-x86).", True)
            return
        if m.get("tpm") and not self._limits["tpm"]:
            self.said.emit("Windows 11 wants a TPM: install swtpm. Starting without one.", True)
        boot_cd = not m.get("installed") and bool(m.get("iso")) and os.path.isfile(m.get("iso", ""))
        r = Running(m, HOME_DIR / mid, self)
        self._running[mid] = r
        r.start(self._limits["kvm"], boot_cd)
        if m.get("resume"):
            m["resume"] = False
        m["used"] = time.time()
        self._save(m)
        if not self._limits["kvm"]:
            self.said.emit("This computer doesn't allow KVM here, so the machine runs much slower (emulated).", True)
        self.changed.emit()

    def _changed_state(self, r: Running) -> None:
        self.changed.emit()

    def _ended(self, r: Running, code: int) -> None:
        mid = r.m["id"]
        self._running.pop(mid, None)
        if code != 0 and "qemu" in r.log.lower():
            last = [l for l in r.log.splitlines() if l.strip()][-1:] or [""]
            self.said.emit("The machine stopped: " + last[0][:160], True)
        self.changed.emit()
        r.deleteLater()

    def _qmp(self, mid: str):
        r = self._running.get(mid)
        return r.qmp if r and r.qmp and r.qmp.up else None

    @Slot(str)
    def pause(self, mid: str) -> None:
        if self._demo:
            self._demo_state[mid] = "paused" if self._demo_state.get(mid) == "running" else "running"
            self.changed.emit()
            return
        q = self._qmp(mid)
        if q:
            q.run("stop" if self._running[mid].state == "running" else "cont")

    @Slot(str)
    def shutDown(self, mid: str) -> None:
        """Ask the machine's own system to shut down (like pressing its power button)."""
        if self._demo:
            self._demo_state.pop(mid, None)
            self.changed.emit()
            return
        q = self._qmp(mid)
        if q:
            q.run("system_powerdown")
            self.said.emit("Asked it to shut down.", False)

    @Slot(str)
    def forceOff(self, mid: str) -> None:
        if self._demo:
            self._demo_state.pop(mid, None)
            self.changed.emit()
            return
        r = self._running.get(mid)
        if r is None:
            return
        q = self._qmp(mid)
        if q:
            q.run("quit")
            QTimer.singleShot(3000, lambda: r.proc.kill() if r.proc.state() != QProcess.ProcessState.NotRunning else None)
        else:
            r.proc.kill()

    @Slot(str)
    def restart(self, mid: str) -> None:
        q = self._qmp(mid)
        if q:
            q.run("system_reset")

    @Slot(str)
    def installed(self, mid: str) -> None:
        """The system is on its disk now: boot from the disk from now on, and take the installer out."""
        m = self._get(mid)
        if m:
            m["installed"] = True
            self._save(m)
            if mid in self._running and self._qmp(mid):
                self._qmp(mid).hmp("eject -f cd0")
            self.changed.emit()

    # ---- snapshots
    @Slot(str, str)
    def takeSnapshot(self, mid: str, name: str) -> None:
        m = self._get(mid)
        if not m:
            return
        name = (name or "").strip() or time.strftime("Snapshot %-d %b, %H:%M")
        tag = "h" + uuid.uuid4().hex[:8]
        entry = {"name": name, "tag": tag, "when": time.time()}

        def done(ok, err=""):
            if ok:
                m.setdefault("snapshots", []).append(entry)
                self._save(m)
                self.said.emit(f"Snapshot “{name}” taken.", False)
            else:
                self.said.emit("Couldn't take a snapshot: " + (err or "")[:140], True)
            self.changed.emit()
        if self._demo:
            return done(True)
        q = self._qmp(mid)
        if q:                                                     # a running machine: its memory too
            q.hmp(f"savevm {tag}", lambda r, e: done(not e and not (r or "").strip(), e or r))
        else:
            r = subprocess.run(["qemu-img", "snapshot", "-c", tag, str(HOME_DIR / mid / "disk.qcow2")], capture_output=True, text=True, timeout=120)
            done(r.returncode == 0, r.stderr)

    @Slot(str, str)
    def restoreSnapshot(self, mid: str, tag: str) -> None:
        m = self._get(mid)
        snap = next((s for s in (m or {}).get("snapshots", []) if s.get("tag") == tag or s.get("name") == tag), None)
        if not snap:
            return
        if self._demo:
            self.said.emit(f"Back to “{snap['name']}”.", False)
            return
        q = self._qmp(mid)
        if q:
            q.hmp(f"loadvm {snap['tag']}", lambda r, e: self.said.emit(f"Back to “{snap['name']}”." if not e and not (r or "").strip() else f"Couldn't go back: {e or r}", bool(e or (r or "").strip())))
        else:
            r = subprocess.run(["qemu-img", "snapshot", "-a", snap["tag"], str(HOME_DIR / mid / "disk.qcow2")], capture_output=True, text=True, timeout=120)
            self.said.emit(f"Back to “{snap['name']}”." if r.returncode == 0 else "Couldn't go back: " + r.stderr[:140], r.returncode != 0)

    @Slot(str, str)
    def deleteSnapshot(self, mid: str, tag: str) -> None:
        m = self._get(mid)
        if not m:
            return
        snap = next((s for s in m.get("snapshots", []) if s.get("tag") == tag or s.get("name") == tag), None)
        if not snap:
            return
        if not self._demo:
            q = self._qmp(mid)
            if q:
                q.hmp(f"delvm {snap['tag']}")
            else:
                subprocess.run(["qemu-img", "snapshot", "-d", snap["tag"], str(HOME_DIR / mid / "disk.qcow2")], capture_output=True, timeout=120)
        m["snapshots"] = [s for s in m["snapshots"] if s is not snap]
        self._save(m)
        self.changed.emit()

    # ---- pictures for the library
    def _pictures(self) -> None:
        for r in list(self._running.values()):
            if r.state == "running":
                r.snapshot_picture(self._picture_taken)

    def _picture_taken(self) -> None:
        self._version += 1
        self.changed.emit()

    @Slot(result=str)
    def status(self) -> str:
        return json.dumps({mid: r.state for mid, r in self._running.items()})

    def leaving(self) -> None:
        """Closing Machines saves each running machine as it is (memory and all) and carries on from there next time,
        like closing a laptop's lid."""
        from PySide6.QtCore import QCoreApplication, QEventLoop
        for r in list(self._running.values()):
            saved = []
            if r.qmp and r.qmp.up:
                r.qmp.run("stop")
                r.qmp.hmp("savevm huginn-resume", lambda res, err: saved.append(not err and not (res or "").strip()))
                end = time.time() + 120
                while not saved and time.time() < end and r.proc.state() != QProcess.ProcessState.NotRunning:
                    QCoreApplication.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 100)
                r.m["resume"] = bool(saved and saved[0])
                self._save(r.m)
                r.qmp.run("quit")
            r.proc.waitForFinished(5000)
            if r.proc.state() != QProcess.ProcessState.NotRunning:
                r.proc.kill()


def demo_desktop(look: str) -> QImage:
    """A made-up desktop for the demo's machines (nothing of anyone else's: shapes and colours only)."""
    from PySide6.QtGui import QLinearGradient, QRadialGradient
    W, H = 1280, 800
    img = QImage(W, H, QImage.Format.Format_RGB32)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    a, b = {"ubuntu": ("#2C001E", "#E95420"), "windows": ("#0B1B4A", "#3B9BFF"), "huginn": ("#08141A", "#43D9B8")}[look]
    g = QLinearGradient(0, 0, W, H)
    g.setColorAt(0, QColor(a))
    g.setColorAt(1, QColor(b))
    p.fillRect(0, 0, W, H, g)
    glow = QRadialGradient(W * 0.7, H * 0.35, W * 0.5)
    glow.setColorAt(0, QColor(255, 255, 255, 70))
    glow.setColorAt(1, QColor(255, 255, 255, 0))
    p.fillRect(0, 0, W, H, glow)
    p.setPen(Qt.PenStyle.NoPen)
    if look == "ubuntu":
        p.setBrush(QColor(0, 0, 0, 150))
        p.drawRect(0, 0, W, 28)
        p.drawRoundedRect(QRectF(10, 60, 64, 680), 16, 16)
        for k in range(7):
            p.setBrush(QColor([("#E95420"), ("#3B9BFF"), ("#F5C542"), ("#2FBF71"), ("#8E6BFF"), ("#FF5FA2"), ("#22D3EE")][k]))
            p.drawRoundedRect(QRectF(22, 76 + k * 64, 40, 40), 10, 10)
    elif look == "windows":
        p.setBrush(QColor(20, 24, 36, 210))
        p.drawRect(0, H - 48, W, 48)
        for k in range(6):
            p.setBrush(QColor(["#3B9BFF", "#F5C542", "#2FBF71", "#FF7A59", "#8E6BFF", "#22D3EE"][k]))
            p.drawRoundedRect(QRectF(W / 2 - 150 + k * 52, H - 40, 32, 32), 7, 7)
    else:
        p.setBrush(QColor(255, 255, 255, 36))
        p.drawRoundedRect(QRectF(W / 2 - 220, H - 74, 440, 58), 22, 22)
        p.drawRoundedRect(QRectF(16, 12, 300, 40), 18, 18)
        p.setBrush(QColor(15, 20, 25, 190))
        p.drawRoundedRect(QRectF(260, 150, 760, 460), 22, 22)
    p.end()
    return img
