"""Privacy Report: what on this computer used the camera, the microphone, your screen and your location, which
apps talked to the internet, and what the Huginn browser stopped from following you.

A small watcher started with your session (python3 huginn_privacy.py watch) looks every few seconds:
  * camera and microphone: PipeWire's graph (pw-dump) says which app's stream is fed by a camera or a microphone;
    a program that opens a camera directly (/dev/video*) is caught by its open files;
  * your screen: a PipeWire stream fed by the desktop's screen-sharing source;
  * location: GeoClue says whether any app is using it (not which);
  * the internet: ss lists each of your programs' connections (addresses only: nothing is looked up unless you ask).
What it sees is written only to ~/.local/state/huginn (kept 30 days) and shown only here."""
import datetime as dt
import fcntl
import ipaddress
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

STATE = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local/state") / "huginn"
LOG, NOW, NET = STATE / "privacy.jsonl", STATE / "privacy-now.json", STATE / "privacy-net.json"
KEEP_DAYS = 30
SENSORS = ("camera", "mic", "screen", "location")
NAMES = {"huginn_app.py": "", "python3": "", "pipewire": "", "wireplumber": "", "xdg-desktop-portal": "", "kwin_wayland": ""}


def app_name(pid: int) -> str:
    """A person-friendly name for a process: 'Voice Recorder' for 'python3 huginn_app.py recorder'."""
    try:
        argv = Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")
        argv = [a.decode("utf-8", "replace") for a in argv if a]
    except OSError:
        return ""
    if not argv:
        return ""
    for i, a in enumerate(argv):
        if a.endswith("huginn_app.py") and i + 1 < len(argv):
            return {"recorder": "Voice Recorder", "screenshot": "Screenshot", "print": "Print & Scan", "store": "App Store", "monitor": "System Monitor"}.get(argv[i + 1], argv[i + 1].title())
        if a.endswith("safari_browser.py"):
            return "Huginn"
        if a.endswith(".py") and i > 0:
            return Path(a).stem.replace("huginn_", "").replace("_", " ").title()
    base = os.path.basename(argv[0])
    return {"chrome": "Chrome", "firefox": "Firefox", "zoom": "Zoom", "discord": "Discord", "obs": "OBS Studio", "kdeconnectd": "KDE Connect",
            "Discord": "Discord", "steam": "Steam", "steamwebhelper": "Steam", "QtWebEngineProcess": "Huginn (page)"}.get(base, base)


# ============================================================================================= looking
def pw_streams(raw: str) -> list:
    """From pw-dump's JSON: [(sensor, app, pid)] for every capture stream that is running now."""
    try:
        objs = json.loads(raw or "[]")
    except ValueError:
        return []
    nodes, links = {}, []
    for o in objs if isinstance(objs, list) else []:
        info = o.get("info") or {}
        if o.get("type") == "PipeWire:Interface:Node":
            nodes[o.get("id")] = {"props": info.get("props") or {}, "state": info.get("state", "")}
        elif o.get("type") == "PipeWire:Interface:Link":
            links.append((info.get("output-node-id"), info.get("input-node-id"), info.get("state", "")))
    out = []
    for nid, node in nodes.items():
        p = node["props"]
        kind = p.get("media.class", "")
        if kind not in ("Stream/Input/Audio", "Stream/Input/Video") or node["state"] not in ("running", "idle"):
            continue
        feeds = [nodes.get(src, {}).get("props", {}) for src, dst, state in links if dst == nid and state in ("active", "paused", "init", "negotiating", "allocating")]
        sensor = ""
        for src in feeds:
            if kind == "Stream/Input/Audio" and src.get("media.class") == "Audio/Source" and not str(src.get("node.name", "")).endswith(".monitor"):
                sensor = "mic"
            elif kind == "Stream/Input/Video" and src.get("media.class") == "Video/Source":
                sensor = "camera" if src.get("device.api") in ("v4l2", "libcamera") or "camera" in str(src.get("media.role", "")).lower() else "screen"
        if sensor and node["state"] == "running":
            pid = p.get("application.process.id") or p.get("pipewire.sec.pid")
            name = p.get("application.name") or p.get("application.process.binary") or ""
            try:
                name = app_name(int(pid)) or name
            except (TypeError, ValueError):
                pass
            out.append((sensor, name or "An app", int(pid) if str(pid).isdigit() else 0))
    return out


def video_openers(proc: Path = Path("/proc")) -> list:
    """[(app, pid)] for your programs that hold a camera device (/dev/video*) open themselves."""
    me, out = os.getuid(), []
    for entry in proc.iterdir() if proc.is_dir() else []:
        if not entry.name.isdigit():
            continue
        try:
            if entry.stat().st_uid != me:
                continue
            for fd in (entry / "fd").iterdir():
                if os.readlink(fd).startswith("/dev/video"):
                    out.append((app_name(int(entry.name)) or entry.name, int(entry.name)))
                    break
        except OSError:
            continue
    return out


def location_in_use() -> bool:
    if not any(Path(p).exists() for p in ("/usr/share/dbus-1/system-services/org.freedesktop.GeoClue2.service", "/usr/libexec/geoclue")):
        return False
    tool = shutil.which("busctl")
    if not tool:
        return False
    try:
        out = subprocess.run([tool, "--system", "get-property", "org.freedesktop.GeoClue2", "/org/freedesktop/GeoClue2/Manager", "org.freedesktop.GeoClue2.Manager", "InUse"],
                             capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return False
    return out.strip() == "b true"


def location_service() -> bool:
    return any(Path(p).exists() for p in ("/usr/share/dbus-1/system-services/org.freedesktop.GeoClue2.service", "/usr/libexec/geoclue"))


def connections(raw: str) -> list:
    """ss -tunpH output -> [(app, pid, remote ip)] for connections to other machines."""
    out = []
    for line in (raw or "").splitlines():
        parts = line.split()
        if len(parts) < 6:
            continue
        peer = parts[5]
        ip = peer.rsplit(":", 1)[0].strip("[]")
        ip = ip.split("%")[0]
        try:
            addr = ipaddress.ip_address(ip)
        except ValueError:
            continue
        if addr.is_loopback or addr.is_unspecified or addr.is_link_local or addr.is_multicast:
            continue
        users = re.findall(r'\("([^"]+)",pid=(\d+)', line)
        for name, pid in users[:1]:
            out.append((app_name(int(pid)) or name, int(pid), str(addr)))
    return out


# ============================================================================================= keeping
def _locked(fn):
    STATE.mkdir(parents=True, exist_ok=True)
    with open(STATE / ".privacy.lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        return fn()


def record(event: dict) -> None:
    def go():
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(event) + "\n")
    _locked(go)


def read_log(since: float) -> list:
    out = []
    try:
        with open(LOG, encoding="utf-8") as f:
            for line in f:
                try:
                    e = json.loads(line)
                except ValueError:
                    continue
                if isinstance(e, dict) and e.get("end", 0) >= since and e.get("what") in SENSORS:
                    out.append(e)
    except OSError:
        pass
    return out


def prune(now: float) -> None:
    cutoff = now - KEEP_DAYS * 86400

    def go():
        try:
            lines = LOG.read_text(encoding="utf-8").splitlines()
        except OSError:
            return
        kept = [ln for ln in lines if '"end"' in ln and json.loads(ln).get("end", 0) >= cutoff] if lines else []
        if len(kept) != len(lines):
            part = LOG.with_name(".privacy.jsonl.saving")
            part.write_text("".join(ln + "\n" for ln in kept), encoding="utf-8")
            os.replace(part, LOG)
        try:
            net = json.loads(NET.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        days = {d: v for d, v in net.items() if d >= dt.date.fromtimestamp(cutoff).isoformat()}
        if len(days) != len(net):
            NET.write_text(json.dumps(days), encoding="utf-8")
    _locked(go)


def add_net(day: str, seen: list) -> None:
    def go():
        try:
            net = json.loads(NET.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            net = {}
        today = net.setdefault(day, {})
        for app, _, ip in seen:
            today.setdefault(app, {})
            today[app][ip] = today[app].get(ip, 0) + 1
        part = NET.with_name(".privacy-net.saving")
        part.write_text(json.dumps(net), encoding="utf-8")
        os.replace(part, NET)
    _locked(go)


class Watcher:
    """Turns looks into stretches of time: 'the microphone, Voice Recorder, 10:02 to 10:09'."""
    def __init__(self, look=None):
        self.look = look or self.look_now
        self.open = {}                                                 # (sensor, app) -> start time

    @staticmethod
    def look_now() -> set:
        seen = set()
        tool = shutil.which("pw-dump")
        if tool:
            try:
                for sensor, app, _ in pw_streams(subprocess.run([tool], capture_output=True, text=True, timeout=10).stdout):
                    seen.add((sensor, app))
            except (OSError, subprocess.SubprocessError):
                pass
        for app, _ in video_openers():
            seen.add(("camera", app))
        if location_in_use():
            seen.add(("location", "An app"))
        return seen

    def step(self, now: float) -> None:
        seen = self.look()
        for key in seen:
            self.open.setdefault(key, now)
        for key in [k for k in self.open if k not in seen]:
            start = self.open.pop(key)
            record({"what": key[0], "app": key[1], "start": round(start), "end": round(now)})
        _locked(lambda: NOW.write_text(json.dumps([{"what": w, "app": a, "start": round(s)} for (w, a), s in self.open.items()]), encoding="utf-8"))

    def serve(self) -> int:
        lock = open(Path(os.environ.get("XDG_RUNTIME_DIR") or "/tmp") / "huginn-privacy.lock", "w")
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return 0
        last_net = last_prune = 0.0
        while True:
            now = time.time()
            try:
                self.step(now)
                if now - last_net >= 15 and shutil.which("ss"):
                    raw = subprocess.run(["ss", "-tunpH", "state", "established"], capture_output=True, text=True, timeout=10).stdout
                    add_net(dt.date.today().isoformat(), list({(a, 0, ip) for a, _, ip in connections(raw)}))
                    last_net = now
                if now - last_prune >= 6 * 3600:
                    prune(now)
                    last_prune = now
            except Exception as err:
                print("privacy:", err, file=sys.stderr)
            time.sleep(3)


def watching() -> bool:
    path = Path(os.environ.get("XDG_RUNTIME_DIR") or "/tmp") / "huginn-privacy.lock"
    try:
        with open(path, "a") as f:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(f, fcntl.LOCK_UN)
            return False
    except OSError:
        return True


def browser_trackers(since: float, home: Path = None) -> dict:
    """What the Huginn browser blocked: {count, trackers: [(name, n)], sites: [(site, n)]}."""
    data_home = Path(os.environ.get("XDG_DATA_HOME") or (home or Path.home()) / ".local/share")
    out = {"count": 0, "trackers": [], "sites": [], "found": False}
    for path in (data_home / "SafariQt/SafariQt/browser-data.json", data_home / "Huginn/Huginn/browser-data.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        out["found"] = True
        rows = [t for t in data.get("trackers", []) if isinstance(t, dict) and t.get("time", 0) >= since]
        trackers, sites = {}, {}
        for t in rows:
            trackers[t.get("tracker", "?")] = trackers.get(t.get("tracker", "?"), 0) + 1
            if t.get("site"):
                sites[t["site"]] = sites.get(t["site"], 0) + 1
        out["count"] += len(rows)
        out["trackers"] = sorted(trackers.items(), key=lambda kv: -kv[1])[:8]
        out["sites"] = sorted(sites.items(), key=lambda kv: -kv[1])[:8]
    return out


# ============================================================================================= the report
try:
    from PySide6.QtCore import Property, QObject, QTimer, Signal, Slot
except ImportError:
    QObject = object

if QObject is not object:
    class Privacy(QObject):
        changed = Signal()
        said = Signal(str, bool)
        _back = Signal(object)

        def __init__(self, demo: bool = False):
            super().__init__()
            self._back.connect(lambda fn: fn())
            self._demo, self._days, self._names = demo, 7, {}
            self._now_ts = time.time()
            if demo:
                return
            self._timer = QTimer(self)
            self._timer.setInterval(3000)
            self._timer.timeout.connect(self._tick)
            self._timer.start()
            QTimer.singleShot(500, self._wake)

        def _tick(self) -> None:
            self._now_ts = time.time()
            self.changed.emit()

        def _wake(self) -> None:
            if not watching():
                try:
                    subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "watch"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
                except OSError:
                    pass
                QTimer.singleShot(1500, self.changed.emit)

        # ---- the numbers (made-up ones for previews)
        def _events(self) -> list:
            now = self._now_ts
            if self._demo:
                day = 86400
                base = dt.datetime.combine(dt.date.today(), dt.time()).timestamp()
                rows = [("mic", "Voice Recorder", -1, 10.2, 10.7), ("camera", "Camera", -1, 14.0, 14.2), ("screen", "Screenshot", -2, 11.0, 11.3), ("mic", "Huginn", -2, 19.0, 20.1),
                        ("camera", "Huginn", -2, 19.0, 20.1), ("mic", "Discord", -4, 21.0, 22.5), ("location", "An app", -3, 9.0, 9.05), ("screen", "Huginn", -5, 15.0, 15.8), ("mic", "Voice Recorder", 0, 8.5, 8.9)]
                return [{"what": w, "app": a, "start": base + d * day + s * 3600, "end": base + d * day + e * 3600} for w, a, d, s, e in rows]
            return read_log(now - self._days * 86400)

        def _ongoing(self) -> list:
            if self._demo:
                return [{"what": "mic", "app": "Voice Recorder", "start": time.time() - 95}]
            try:
                return json.loads(NOW.read_text(encoding="utf-8")) if watching() else []
            except (OSError, ValueError):
                return []

        def _lanes(self) -> list:
            """Per sensor: its stretches as shares of the week (for drawing) and per app totals."""
            start = dt.datetime.combine(dt.date.today() - dt.timedelta(days=self._days - 1), dt.time()).timestamp()
            span = self._days * 86400
            events = self._events() + [dict(e, end=time.time()) for e in self._ongoing()]
            lanes = []
            for sensor, title in (("camera", "Camera"), ("mic", "Microphone"), ("screen", "Screen"), ("location", "Location")):
                rows = [e for e in events if e["what"] == sensor and e["end"] >= start and e["start"] <= time.time() + 60]
                apps = {}
                for e in rows:
                    apps[e["app"]] = apps.get(e["app"], 0) + max(1, e["end"] - max(e["start"], start))
                lanes.append({"id": sensor, "title": title, "count": len(rows),
                              "marks": [{"x": min(1.0, max(0.0, (e["start"] - start) / span)), "w": max(0.004, (min(e["end"], time.time()) - max(e["start"], start)) / span), "app": e["app"],
                                         "when": dt.datetime.fromtimestamp(e["start"]).strftime("%a %H:%M"), "long": _span(e["end"] - e["start"])} for e in rows],
                              "apps": [{"name": a, "time": _span(t)} for a, t in sorted(apps.items(), key=lambda kv: -kv[1])]})
            return lanes

        def _get_now(self) -> list:
            words = {"camera": "camera", "mic": "microphone", "screen": "screen", "location": "location"}
            return [{"what": e["what"], "text": f"{e['app']} is using the {words[e['what']]}" if e["what"] != "location" else "An app is using your location",
                     "since": _span(time.time() - e["start"])} for e in self._ongoing()]

        def _get_network(self) -> list:
            if self._demo:
                rows = {"Huginn": 186, "Mail": 6, "Steam": 14, "Feeds": 23, "Weather": 1, "Discord": 9, "KDE Connect": 1}
                return [{"name": k, "places": v, "share": v / 186, "ips": []} for k, v in sorted(rows.items(), key=lambda kv: -kv[1])]
            try:
                net = json.loads(NET.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                net = {}
            since = (dt.date.today() - dt.timedelta(days=self._days - 1)).isoformat()
            apps = {}
            for day, by_app in net.items():
                if day < since:
                    continue
                for app, ips in by_app.items():
                    apps.setdefault(app, set()).update(ips)
            top = max([len(v) for v in apps.values()] + [1])
            return [{"name": a, "places": len(ips), "share": len(ips) / top, "ips": [{"ip": ip, "host": self._names.get(ip, "")} for ip in sorted(ips)[:60]]}
                    for a, ips in sorted(apps.items(), key=lambda kv: -len(kv[1]))]

        def _get_browser(self) -> dict:
            if self._demo:
                return {"count": 1284, "found": True, "trackers": [{"name": n, "count": c} for n, c in [("doubleclick.net", 312), ("google-analytics.com", 240), ("facebook.net", 131), ("scorecardresearch.com", 77), ("hotjar.com", 41)]],
                        "sites": [{"name": n, "count": c} for n, c in [("news.example", 402), ("recipes.example", 190), ("shop.example", 88)]]}
            got = browser_trackers(time.time() - self._days * 86400)
            return {"count": got["count"], "found": got["found"], "trackers": [{"name": n, "count": c} for n, c in got["trackers"]], "sites": [{"name": n, "count": c} for n, c in got["sites"]]}

        def _get_days(self) -> list:
            return [(dt.date.today() - dt.timedelta(days=self._days - 1 - i)).strftime("%a") for i in range(self._days)]

        lanes = Property("QVariantList", _lanes, notify=changed)
        now = Property("QVariantList", _get_now, notify=changed)
        network = Property("QVariantList", _get_network, notify=changed)
        browser = Property("QVariantMap", _get_browser, notify=changed)
        days = Property("QVariantList", _get_days, notify=changed)
        watching = Property(bool, lambda self: self._demo or watching(), notify=changed)
        locationService = Property(bool, lambda self: self._demo or location_service(), constant=True)
        dayShare = Property(float, lambda self: ((time.time() - dt.datetime.combine(dt.date.today(), dt.time()).timestamp()) / 86400 + self._days - 1) / self._days, notify=changed)

        @Slot(str)
        def lookUp(self, ip: str) -> None:
            """Ask for the name behind an address (this asks your DNS server, so only when you click)."""
            def go():
                try:
                    return socket.gethostbyaddr(ip)[0]
                except (OSError, UnicodeError):
                    return "no name"
            def done(name):
                self._names[ip] = name if isinstance(name, str) else "no name"
                self.changed.emit()
            threading.Thread(target=lambda: self._back.emit(lambda: done(go())), daemon=True).start()

        @Slot()
        def forget(self) -> None:
            """Delete everything the watcher wrote."""
            for path in (LOG, NET):
                try:
                    path.unlink()
                except OSError:
                    pass
            self.said.emit("The report's history is gone. It starts again from now.", False)
            self.changed.emit()


def _span(seconds: float) -> str:
    seconds = max(0, int(seconds))
    if seconds < 60:
        return f"{seconds} s"
    if seconds < 3600:
        return f"{seconds // 60} min"
    return f"{seconds // 3600} h {seconds % 3600 // 60:02d} min"


if __name__ == "__main__":
    if sys.argv[1:2] == ["watch"]:
        sys.exit(Watcher().serve())
    print(__doc__)
