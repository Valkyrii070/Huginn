"""Screen Sharing: let someone see and use this computer for a while, or see and use another one.

Sharing runs KDE's RDP server (krdpserver, package krdp) with a fresh one-time password, only while this window is
open. Any Remote Desktop app can connect: Huginn's own viewer, Windows' Remote Desktop Connection, Microsoft's
Windows App on a Mac or phone. Looking at another computer runs FreeRDP's viewer (sdl-freerdp, package freerdp-sdl),
handing it the password on stdin so it never shows up in the process list."""
import json
import os
import secrets
import shutil
import socket
import subprocess
from pathlib import Path

from PySide6.QtCore import Property, QObject, QProcess, QTimer, Signal, Slot
from PySide6.QtGui import QGuiApplication
from PySide6.QtNetwork import QAbstractSocket, QNetworkInterface

STATE = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share") / "huginn" / "sharing.json"
PORT = 3389
LOGIN = "huginn"
LETTERS = "abcdefghjkmnpqrstuvwxyz23456789"                     # no 0/o, 1/l/i to misread over the phone
VIEWERS = ["sdl-freerdp", "sdl-freerdp3", "wlfreerdp3", "xfreerdp3", "xfreerdp"]


def one_time_password() -> str:
    return "-".join("".join(secrets.choice(LETTERS) for _ in range(4)) for _ in range(3))


def port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("0.0.0.0", port))
            return True
        except OSError:
            return False


def addresses() -> list:
    """This computer's addresses other computers on the network can reach, Wi-Fi/Ethernet first."""
    out = []
    for iface in QNetworkInterface.allInterfaces():
        flags = iface.flags()
        if not (flags & QNetworkInterface.IsUp) or flags & QNetworkInterface.IsLoopBack:
            continue
        name = iface.name()
        if name.startswith(("docker", "veth", "br-", "virbr", "lxc")):
            continue
        for entry in iface.addressEntries():
            ip = entry.ip()
            if ip.protocol() == QAbstractSocket.IPv4Protocol and not ip.isLoopback():
                kind = "Wi-Fi" if name.startswith("wl") else "Cable" if name.startswith(("en", "eth")) else "VPN" if name.startswith(("tun", "wg", "tailscale")) else name
                out.append({"ip": ip.toString(), "kind": kind})
    order = {"Wi-Fi": 0, "Cable": 0, "VPN": 2}
    return sorted(out, key=lambda a: order.get(a["kind"], 1))


def watchers(port: int, text: str = None) -> list:
    """Who is connected to the sharing port right now (from `ss -tnH state established`)."""
    if text is None:
        try:
            text = subprocess.run(["ss", "-tnH", "state", "established", f"( sport = :{port} )"], capture_output=True, text=True, timeout=5).stdout
        except (OSError, subprocess.SubprocessError):
            return []
    seen = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 4:
            continue
        local, peer = parts[-2], parts[-1]
        if not local.endswith(f":{port}"):
            continue
        host = peer.rsplit(":", 1)[0].strip("[]")
        if host.startswith("::ffff:"):
            host = host[7:]
        if host not in seen:
            seen.append(host)
    return seen


def split_address(text: str) -> tuple:
    """'192.168.1.20', 'pc.local:3390', '[fe80::1]:3389' -> (host, port)."""
    text = text.strip().replace("rdp://", "").rstrip("/")
    if text.startswith("["):
        host, _, rest = text[1:].partition("]")
        return host, int(rest[1:]) if rest.startswith(":") and rest[1:].isdigit() else PORT
    if text.count(":") == 1:
        host, port = text.split(":")
        return host, int(port) if port.isdigit() else PORT
    return text, PORT


def viewer_args(host: str, port: int, user: str, password: str, full: bool) -> list:
    args = [f"/v:{host}:{port}", f"/u:{user}", f"/p:{password}", "/cert:tofu", "/dynamic-resolution", "+clipboard", "/sound", "/t:" + f"{host} · Huginn"]
    if full:
        args.append("/f")
    return args


def find_viewer() -> str:
    for name in VIEWERS:
        path = shutil.which(name)
        if path:
            return path
    return ""


class Sharing(QObject):
    changed = Signal()
    said = Signal(str, bool)

    def __init__(self, demo: bool = False):
        super().__init__()
        self._demo = demo
        self._server = shutil.which("krdpserver") or ""
        self._viewer = find_viewer()
        self._proc = None
        self._password, self._port, self._monitor = "", PORT, -1
        self._watching, self._why, self._log = [], "", ""
        self._recent = []
        self._kids = []
        if demo:
            self._server, self._viewer = "/usr/bin/krdpserver", "/usr/bin/sdl-freerdp"
            self._password, self._watching = "k7mp-2xq9-w4rt", ["192.168.1.37"]
            self._recent = [{"host": "studio-pc.local", "port": PORT, "user": "astrid", "name": "Studio PC"},
                            {"host": "192.168.1.52", "port": PORT, "user": "huginn", "name": "Mum's laptop"}]
        else:
            try:
                self._recent = json.loads(STATE.read_text(encoding="utf-8")).get("recent", [])[:8]
            except (OSError, ValueError, AttributeError):
                pass
        self._timer = QTimer(self)
        self._timer.setInterval(2000)
        self._timer.timeout.connect(self._look)

    def _keep(self) -> None:
        if self._demo:
            return
        try:
            STATE.parent.mkdir(parents=True, exist_ok=True)
            STATE.write_text(json.dumps({"recent": self._recent}), encoding="utf-8")   # never a password
        except OSError:
            pass

    def _look(self) -> None:
        now = watchers(self._port)
        if now != self._watching:
            new = [w for w in now if w not in self._watching]
            self._watching = now
            self.changed.emit()
            for w in new:
                self.said.emit(f"{w} is looking at your screen", False)

    # ---------------- what QML sees
    sharing = Property(bool, lambda self: self._demo or (self._proc is not None and self._proc.state() != QProcess.NotRunning), notify=changed)
    password = Property(str, lambda self: self._password, notify=changed)
    login = Property(str, lambda self: LOGIN, constant=True)
    port = Property(int, lambda self: self._port, notify=changed)
    watching = Property("QStringList", lambda self: self._watching, notify=changed)
    why = Property(str, lambda self: self._why, notify=changed)
    canShare = Property(bool, lambda self: bool(self._server), constant=True)
    canView = Property(bool, lambda self: bool(self._viewer), constant=True)
    recent = Property("QVariantList", lambda self: self._recent, notify=changed)
    monitor = Property(int, lambda self: self._monitor, notify=changed)
    hostname = Property(str, lambda self: socket.gethostname(), constant=True)

    def _get_addresses(self) -> list:
        if self._demo:
            return [{"ip": "192.168.1.24", "kind": "Wi-Fi"}, {"ip": "100.92.14.3", "kind": "VPN"}]
        return addresses()

    def _get_screens(self) -> list:
        app = QGuiApplication.instance()
        screens = app.screens() if app else []
        if self._demo:
            return [{"name": "Whole desktop"}, {"name": "Built-in screen"}, {"name": "DELL U2720Q"}]
        return [{"name": "Whole desktop"}] + [{"name": s.model() or s.name()} for s in screens] if len(screens) > 1 else []

    addresses = Property("QVariantList", _get_addresses, notify=changed)
    screens = Property("QVariantList", _get_screens, constant=True)

    @Slot(int)
    def setMonitor(self, n: int) -> None:
        self._monitor = n
        self.changed.emit()
        if self._proc is not None:
            self.start()

    @Slot()
    def start(self) -> None:
        """(Re)start sharing with a new one-time password."""
        if self._demo:
            self._password = one_time_password()
            self.changed.emit()
            return
        if not self._server:
            self._why = "Sharing needs KDE's Remote Desktop server (krdp). Get it from the App Store."
            self.changed.emit()
            return
        self._stop_server()
        if not port_free(self._port):
            self._why = f"Something else is already using port {self._port}, so sharing can't start."
            self.changed.emit()
            return
        self._why, self._log, self._password = "", "", one_time_password()
        args = ["-u", LOGIN, "-p", self._password, "--port", str(self._port)]
        if self._monitor >= 0:
            args += ["--monitor", str(self._monitor)]
        proc = QProcess(self)
        proc.setProcessChannelMode(QProcess.MergedChannels)
        proc.readyReadStandardOutput.connect(lambda: self._read(proc))
        proc.finished.connect(lambda code, status: self._ended(proc, code))
        proc.errorOccurred.connect(lambda err: self._ended(proc, -1) if err == QProcess.FailedToStart else None)
        self._proc = proc
        proc.start(self._server, args)
        self._timer.start()
        self.changed.emit()

    def _read(self, proc: QProcess) -> None:
        self._log = (self._log + bytes(proc.readAllStandardOutput()).decode(errors="replace"))[-4000:]

    def _ended(self, proc: QProcess, code: int) -> None:
        if proc is not self._proc:
            return
        self._proc = None
        self._timer.stop()
        self._watching = []
        if code != 0:
            last = [l for l in self._log.splitlines() if l.strip()][-1:] or ["it stopped straight away"]
            self._why = "Sharing stopped: " + last[0][:160]
        self.changed.emit()

    def _stop_server(self) -> None:
        proc, self._proc = self._proc, None
        if proc is not None:
            proc.terminate()
            if not proc.waitForFinished(2000):
                proc.kill()
                proc.waitForFinished(1000)
        self._timer.stop()
        self._watching = []

    @Slot()
    def stop(self) -> None:
        if self._demo:
            self.said.emit("Stopped sharing (demo)", False)
            return
        self._stop_server()
        self._password = ""
        self.changed.emit()
        self.said.emit("Stopped sharing. Nobody can see your screen.", False)

    @Slot(str)
    def copy(self, text: str) -> None:
        if QGuiApplication.instance():
            QGuiApplication.clipboard().setText(text)
            self.said.emit("Copied", False)

    @Slot(str, str, str, bool, result=str)
    def view(self, address: str, user: str, password: str, full: bool) -> str:
        """Open another computer's screen in FreeRDP's viewer."""
        host, port = split_address(address)
        if not host or " " in host:
            return "Type the other computer's address, like 192.168.1.20."
        if not user.strip():
            return "Type the name to sign in with."
        if not self._viewer:
            return "Looking at other screens needs FreeRDP's viewer (freerdp-sdl). Get it from the App Store."
        entry = {"host": host, "port": port, "user": user.strip(), "name": next((r.get("name", "") for r in self._recent if r["host"] == host), "")}
        self._recent = [entry] + [r for r in self._recent if r["host"] != host]
        del self._recent[8:]
        self._keep()
        self.changed.emit()
        if self._demo:
            return ""
        try:
            kid = subprocess.Popen([self._viewer, "/args-from:stdin"], stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                   start_new_session=True)
            kid.stdin.write(("\n".join(viewer_args(host, port, user.strip(), password, full)) + "\n").encode())
            kid.stdin.close()
            self._kids.append(kid)
        except OSError as e:
            return f"The viewer didn't start: {e.strerror}"
        self.said.emit(f"Connecting to {host}…", False)
        return ""

    @Slot(str, str)
    def rename(self, host: str, name: str) -> None:
        for r in self._recent:
            if r["host"] == host:
                r["name"] = name.strip()
        self._keep()
        self.changed.emit()

    @Slot(str)
    def forget(self, host: str) -> None:
        self._recent = [r for r in self._recent if r["host"] != host]
        self._keep()
        self.changed.emit()

    def leaving(self) -> None:
        """The window closed: sharing never outlives it."""
        if self._proc is not None:
            self._stop_server()
