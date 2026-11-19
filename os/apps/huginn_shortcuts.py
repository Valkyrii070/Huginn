"""Shortcuts: little recipes of "when this happens, do these things".

A shortcut is a trigger and a list of steps. Ones you start yourself can sit in the apps menu; the others are
watched for by a small helper that starts with your session (python3 huginn_shortcuts.py agent) and checks, every
few seconds, the clock, plugged-in drives, your phone (KDE Connect), the Wi-Fi network and the battery. Everything
runs as you, on this computer; nothing is sent anywhere.

    python3 huginn_shortcuts.py agent        the watcher (one per session)
    python3 huginn_shortcuts.py run ID       run one shortcut now"""
import configparser
import datetime as dt
import fcntl
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA_HOME = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share") / "huginn"
STATE_HOME = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local/state") / "huginn"
DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
PICTURES = (".jpg", ".jpeg", ".png", ".heic", ".heif", ".dng", ".cr2", ".cr3", ".nef", ".arw", ".raf", ".orf", ".rw2", ".mp4", ".mov", ".m4v", ".avi", ".mts")
TRIGGERS = {"manual": "When I start it", "time": "At a time", "login": "When I sign in", "drive": "When a drive is plugged in",
            "phone": "When my phone connects", "wifi": "When I join a Wi-Fi network", "battery": "When the battery runs low"}
STEPS = {"app": "Open an app", "site": "Open a website", "file": "Open a file or folder", "notify": "Show a notice", "wait": "Wait",
         "photos": "Copy photos from the drive", "backup": "Back up now", "volume": "Set the volume", "wifi": "Turn Wi-Fi on or off", "command": "Run a command"}


def files() -> tuple:
    return DATA_HOME / "shortcuts.json", STATE_HOME / "shortcuts-state.json"


def load() -> list:
    try:
        data = json.loads(files()[0].read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [s for s in (data.get("shortcuts", []) if isinstance(data, dict) else []) if isinstance(s, dict) and s.get("id")]


def save(shortcuts: list) -> None:
    path = files()[0]
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_name(".shortcuts.json.saving")
    part.write_text(json.dumps({"shortcuts": shortcuts}, indent=1, ensure_ascii=False), encoding="utf-8")
    os.replace(part, path)


def state() -> dict:
    try:
        data = json.loads(files()[1].read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def note_run(ident: str, ok: bool, words: str) -> None:
    """Remember when a shortcut last ran and how it went (the agent and the app both write this; one at a time)."""
    path = files()[1]
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path.with_name(".shortcuts-state.lock"), "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        data = state()
        data[ident] = {"time": int(time.time()), "ok": ok, "words": words[:300]}
        part = path.with_name(".shortcuts-state.saving")
        part.write_text(json.dumps(data), encoding="utf-8")
        os.replace(part, path)


# ============================================================================================= the world, read
def removable_mounts() -> dict:
    """Drives the desktop mounted for you (USB sticks, camera cards): {mount point: label}."""
    out = {}
    user = os.environ.get("USER") or Path.home().name
    for root in (Path("/media") / user, Path("/run/media") / user):
        try:
            for p in root.iterdir():
                if p.is_dir() and os.path.ismount(p):
                    out[str(p)] = p.name
        except OSError:
            continue
    return out


def phones() -> set:
    tool = shutil.which("kdeconnect-cli")
    if not tool:
        return set()
    try:
        out = subprocess.run([tool, "--list-available", "--name-only"], capture_output=True, text=True, timeout=8).stdout
    except (OSError, subprocess.SubprocessError):
        return set()
    return {line.strip() for line in out.splitlines() if line.strip()}


def wifi_name() -> str:
    tool = shutil.which("nmcli")
    if not tool:
        return ""
    try:
        out = subprocess.run([tool, "-t", "-f", "active,ssid", "dev", "wifi"], capture_output=True, text=True, timeout=8).stdout
    except (OSError, subprocess.SubprocessError):
        return ""
    for line in out.splitlines():
        if line.startswith("yes:"):
            return line[4:].replace("\\:", ":")
    return ""


def battery() -> tuple:
    """(percent, on battery?) or (None, False) on a computer with no battery."""
    for bat in sorted(Path("/sys/class/power_supply").glob("BAT*")):
        try:
            return int((bat / "capacity").read_text().strip()), (bat / "status").read_text().strip() == "Discharging"
        except (OSError, ValueError):
            continue
    return None, False


def apps() -> list:
    """The apps in the apps menu: [{id, name, exec}]."""
    dirs = [Path.home() / ".local/share/applications"] + [Path(d) / "applications" for d in os.environ.get("XDG_DATA_DIRS", "/usr/local/share:/usr/share").split(":")]
    seen, out = set(), []
    for folder in dirs:
        for path in sorted(folder.glob("*.desktop")) if folder.is_dir() else []:
            if path.name in seen or path.name.startswith("huginn-shortcut-"):
                continue
            seen.add(path.name)
            parser = configparser.ConfigParser(interpolation=None, strict=False)
            try:
                parser.read(path, encoding="utf-8")
                entry = parser["Desktop Entry"]
            except (configparser.Error, KeyError, UnicodeDecodeError):
                continue
            if entry.get("Type") != "Application" or entry.get("NoDisplay", "false").lower() == "true" or not entry.get("Exec"):
                continue
            out.append({"id": path.name, "name": entry.get("Name", path.stem), "exec": re.sub(r"\s*%[a-zA-Z]", "", entry.get("Exec", ""))})
    return sorted(out, key=lambda a: a["name"].lower())


# ============================================================================================= doing
def _start(argv: list) -> None:
    subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)


def fill(text: str, ctx: dict) -> str:
    """{drive}, {phone}, {wifi} and {date} in a step's words."""
    return re.sub(r"\{(drive|phone|wifi|date)\}", lambda m: str(ctx.get(m.group(1), "")), str(text or ""))


def copy_pictures(drive: str, into: Path, done_file: Path) -> tuple:
    """Copy the photos and videos on a drive (its DCIM folder if it has one) into `into`/<today>, skipping any
    copied before (by name and size). Returns (copied, skipped)."""
    root = Path(drive)
    source = root / "DCIM" if (root / "DCIM").is_dir() else root
    try:
        known = set(json.loads(done_file.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        known = set()
    target = into / dt.date.today().isoformat()
    copied = skipped = 0
    for path in sorted(source.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in PICTURES or any(part.startswith(".") for part in path.relative_to(root).parts):
            continue
        try:
            key = f"{path.name}|{path.stat().st_size}"
        except OSError:
            continue
        if key in known:
            skipped += 1
            continue
        target.mkdir(parents=True, exist_ok=True)
        dest, n = target / path.name, 1
        while dest.exists():
            dest, n = target / f"{path.stem} ({n}){path.suffix}", n + 1
        shutil.copy2(path, dest)
        known.add(key)
        copied += 1
    if copied:
        done_file.parent.mkdir(parents=True, exist_ok=True)
        done_file.write_text(json.dumps(sorted(known)), encoding="utf-8")
    return copied, skipped


def run_step(step: dict, ctx: dict) -> str:
    """Do one step. Returns words about what happened; raises RuntimeError with words when it can't."""
    kind = step.get("do")
    if kind == "app":
        hit = next((a for a in apps() if a["id"] == step.get("app")), None)
        if not hit:
            raise RuntimeError("That app isn't installed any more.")
        _start(shlex.split(hit["exec"]))
        return f"Opened {hit['name']}."
    if kind == "site":
        url = fill(step.get("url", ""), ctx).strip()
        if not re.match(r"https?://", url):
            url = "https://" + url
        _start(["xdg-open", url])
        return f"Opened {url}."
    if kind == "file":
        path = Path(fill(step.get("path", ""), ctx)).expanduser()
        if not path.exists():
            raise RuntimeError(f"{path} isn't there.")
        _start(["xdg-open", str(path)])
        return f"Opened {path.name}."
    if kind == "notify":
        title, body = fill(step.get("title", "") or "Shortcut", ctx), fill(step.get("text", ""), ctx)
        if shutil.which("notify-send"):
            subprocess.run(["notify-send", "--app-name=Shortcuts", "--icon=huginn-shortcuts", title, body], timeout=10, capture_output=True)
        return f"Said “{title}”."
    if kind == "wait":
        secs = max(1, min(3600, int(step.get("seconds") or 5)))
        time.sleep(secs)
        return f"Waited {secs} s."
    if kind == "photos":
        if not ctx.get("drive"):
            raise RuntimeError("This step needs the trigger “When a drive is plugged in”.")
        pictures = Path(os.environ.get("XDG_PICTURES_DIR") or Path.home() / "Pictures") / "Imported"
        copied, skipped = copy_pictures(ctx["drive"], pictures, DATA_HOME / "imported-pictures.json")
        return f"Copied {copied} photos and videos to Pictures/Imported" + (f" ({skipped} were already there)." if skipped else ".")
    if kind == "backup":
        done = subprocess.run([sys.executable, str(HERE / "huginn_more.py"), "backup-run"], capture_output=True, text=True, timeout=6 * 3600)
        if done.returncode:
            raise RuntimeError("The backup didn't finish. Open Backup to see why.")
        return "Backed up."
    if kind == "volume":
        level = max(0, min(100, int(step.get("level") if step.get("level") is not None else 50)))
        tool = shutil.which("wpctl")
        if not tool:
            raise RuntimeError("The sound system's tool (wpctl) isn't there.")
        subprocess.run([tool, "set-mute", "@DEFAULT_AUDIO_SINK@", "1" if level == 0 else "0"], timeout=10, capture_output=True)
        if level:
            subprocess.run([tool, "set-volume", "@DEFAULT_AUDIO_SINK@", f"{level}%"], timeout=10, capture_output=True)
        return "Muted." if level == 0 else f"Volume {level}%."
    if kind == "wifi":
        tool = shutil.which("nmcli")
        if not tool:
            raise RuntimeError("NetworkManager isn't there.")
        on = bool(step.get("on"))
        subprocess.run([tool, "radio", "wifi", "on" if on else "off"], timeout=15, capture_output=True)
        return "Wi-Fi on." if on else "Wi-Fi off."
    if kind == "command":
        cmd = fill(step.get("command", ""), ctx).strip()
        if not cmd:
            raise RuntimeError("The command is empty.")
        done = subprocess.run(["/bin/sh", "-c", cmd], capture_output=True, text=True, timeout=600, stdin=subprocess.DEVNULL)
        if done.returncode:
            raise RuntimeError(f"The command stopped with code {done.returncode}: {(done.stderr or done.stdout).strip()[:160]}")
        return "Ran the command."
    raise RuntimeError("This step is of a kind this version doesn't know.")


def run(shortcut: dict, ctx: dict = None) -> tuple:
    """All of a shortcut's steps, in order; stops at the first that fails. Returns (ok, words) and records them."""
    ctx = dict(ctx or {}, date=dt.date.today().isoformat())
    said = []
    ok = True
    for n, step in enumerate(shortcut.get("steps", []), 1):
        try:
            said.append(run_step(step, ctx))
        except (RuntimeError, OSError, ValueError, subprocess.SubprocessError) as err:
            said.append(f"Step {n} didn't work: {err}")
            ok = False
            break
    words = " ".join(said) or "Nothing to do: it has no steps."
    note_run(shortcut["id"], ok, words)
    if not ok and shutil.which("notify-send"):
        subprocess.run(["notify-send", "--app-name=Shortcuts", f"“{shortcut.get('name', 'Shortcut')}” stopped", said[-1]], timeout=10, capture_output=True)
    return ok, words


# ============================================================================================= the watcher
class Agent:
    """Looks around every few seconds and runs the shortcuts whose moment came."""
    TICK = 5

    def __init__(self):
        self.mtime, self.shortcuts = None, []
        self.mounts, self.phones, self.wifi, self.low = None, None, None, set()
        self.fired_minute = set()

    def reload(self) -> None:
        try:
            mtime = files()[0].stat().st_mtime
        except OSError:
            mtime = 0
        if mtime != self.mtime:
            self.mtime, self.shortcuts = mtime, load()

    def due(self, now: dt.datetime) -> list:
        """(shortcut, context) for everything that should run now. Changes are noticed against the last look,
        so a drive that was already in at login doesn't count as plugged in."""
        self.reload()
        auto = [s for s in self.shortcuts if s.get("on", True) and s.get("when", {}).get("kind") not in (None, "manual", "login")]
        out = []
        minute = now.strftime("%Y-%m-%d %H:%M")
        for s in auto:
            w = s["when"]
            if w["kind"] == "time" and w.get("at") == now.strftime("%H:%M") and DAYS[now.weekday()] in (w.get("days") or DAYS) and (s["id"], minute) not in self.fired_minute:
                self.fired_minute.add((s["id"], minute))
                out.append((s, {}))
        self.fired_minute = {k for k in self.fired_minute if k[1] == minute}
        kinds = {s["when"]["kind"] for s in auto}
        if "drive" in kinds:
            mounts = removable_mounts()
            if self.mounts is not None:
                for path, label in mounts.items():
                    if path not in self.mounts:
                        out += [(s, {"drive": path}) for s in auto if s["when"]["kind"] == "drive" and (not s["when"].get("label") or s["when"]["label"].lower() == label.lower())]
            self.mounts = mounts
        if "phone" in kinds:
            now_phones = phones()
            if self.phones is not None:
                for name in now_phones - self.phones:
                    out += [(s, {"phone": name}) for s in auto if s["when"]["kind"] == "phone" and (not s["when"].get("name") or s["when"]["name"].lower() == name.lower())]
            self.phones = now_phones
        if "wifi" in kinds:
            name = wifi_name()
            if self.wifi is not None and name and name != self.wifi:
                out += [(s, {"wifi": name}) for s in auto if s["when"]["kind"] == "wifi" and s["when"].get("name", "").lower() == name.lower()]
            self.wifi = name
        if "battery" in kinds:
            level, draining = battery()
            if level is not None:
                for s in [s for s in auto if s["when"]["kind"] == "battery"]:
                    below = draining and level <= int(s["when"].get("below") or 20)
                    if below and s["id"] not in self.low:
                        out.append((s, {}))
                    (self.low.add if below else self.low.discard)(s["id"])
        return out

    def login(self) -> list:
        self.reload()
        return [(s, {}) for s in self.shortcuts if s.get("on", True) and s.get("when", {}).get("kind") == "login"]

    def serve(self) -> int:
        lock_path = Path(os.environ.get("XDG_RUNTIME_DIR") or "/tmp") / "huginn-shortcuts.lock"
        lock = open(lock_path, "w")
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return 0                                                # already watching in this session
        lock.write(str(os.getpid()))
        lock.flush()
        for s, ctx in self.login():
            threading.Thread(target=run, args=(s, ctx), daemon=True).start()
        while True:
            try:
                for s, ctx in self.due(dt.datetime.now()):
                    threading.Thread(target=run, args=(s, ctx), daemon=True).start()
            except Exception as err:                                # one bad look never stops the watching
                print("shortcuts:", err, file=sys.stderr)
            time.sleep(self.TICK)


def agent_running() -> bool:
    path = Path(os.environ.get("XDG_RUNTIME_DIR") or "/tmp") / "huginn-shortcuts.lock"
    try:
        with open(path, "a") as f:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(f, fcntl.LOCK_UN)
            return False
    except OSError:
        return True


# ============================================================================================= the app's side
def describe_when(w: dict) -> str:
    kind = (w or {}).get("kind", "manual")
    if kind == "time":
        days = w.get("days") or DAYS
        when = "every day" if len(days) == 7 else "on weekdays" if days == DAYS[:5] else "at weekends" if days == DAYS[5:] else "on " + ", ".join(days)
        return f"At {w.get('at', '08:00')} {when}"
    if kind == "drive":
        return f"When “{w['label']}” is plugged in" if w.get("label") else "When a drive is plugged in"
    if kind == "phone":
        return f"When {w['name']} connects" if w.get("name") else "When my phone connects"
    if kind == "wifi":
        return f"When I join “{w.get('name', '')}”"
    if kind == "battery":
        return f"When the battery is below {w.get('below', 20)}%"
    return TRIGGERS.get(kind, TRIGGERS["manual"])


def describe_step(s: dict, names: dict = None) -> str:
    kind = s.get("do")
    if kind == "app":
        return "Open " + (names or {}).get(s.get("app"), (s.get("app") or "an app").removesuffix(".desktop").removeprefix("huginn-").title())
    if kind == "site":
        return "Open " + (s.get("url") or "a website")
    if kind == "file":
        return "Open " + (Path(s.get("path", "")).name or "a file")
    if kind == "notify":
        return f"Say “{s.get('title') or 'Shortcut'}”"
    if kind == "wait":
        return f"Wait {s.get('seconds', 5)} seconds"
    if kind == "volume":
        return "Mute the sound" if int(s.get("level", 50)) == 0 else f"Set the volume to {s.get('level', 50)}%"
    if kind == "wifi":
        return "Turn Wi-Fi " + ("on" if s.get("on") else "off")
    if kind == "command":
        return "Run " + (s.get("command") or "a command")[:40]
    return STEPS.get(kind, "A step")


STARTERS = [
    {"name": "Bring in camera photos", "colour": "#FF9F1C", "glyph": "image", "when": {"kind": "drive", "label": ""},
     "steps": [{"do": "photos"}, {"do": "notify", "title": "Photos copied", "text": "They're in Pictures/Imported."}],
     "about": "Plug in a camera card or a phone in file mode, and its new photos land in Pictures."},
    {"name": "Morning desk", "colour": "#FFC53D", "glyph": "sun", "when": {"kind": "time", "at": "08:30", "days": DAYS[:5]},
     "steps": [{"do": "app", "app": "huginn-feeds.desktop"}, {"do": "app", "app": "huginn-calendar.desktop"}, {"do": "app", "app": "huginn-mail.desktop"}],
     "about": "On weekdays at half past eight: the news, today's calendar and your mail."},
    {"name": "Home, back up", "colour": "#10B981", "glyph": "home", "when": {"kind": "wifi", "name": "Home"},
     "steps": [{"do": "backup"}, {"do": "notify", "title": "Backed up", "text": "Your files are safe."}],
     "about": "When the laptop joins your home Wi-Fi, a backup runs. Change “Home” to your network's name."},
    {"name": "Quiet evening", "colour": "#7C9CFF", "glyph": "moon", "when": {"kind": "time", "at": "22:00", "days": DAYS},
     "steps": [{"do": "volume", "level": 25}, {"do": "notify", "title": "Evening", "text": "Sound turned down for the night."}],
     "about": "At ten every night, the sound goes down."},
    {"name": "Phone's here", "colour": "#5EEAD4", "glyph": "phone", "when": {"kind": "phone", "name": ""},
     "steps": [{"do": "notify", "title": "{phone} connected", "text": "Files and the clipboard can go across now."}],
     "about": "A notice when your phone (with KDE Connect) comes within reach."},
    {"name": "Save the battery", "colour": "#FB7185", "glyph": "wifi", "when": {"kind": "battery", "below": 15},
     "steps": [{"do": "volume", "level": 0}, {"do": "notify", "title": "Battery low", "text": "Sound muted to save power. Plug in soon."}],
     "about": "Below 15%, mute and say so."},
]


try:
    from PySide6.QtCore import Property, QObject, QTimer, Signal, Slot
except ImportError:                                                   # the agent runs without Qt
    QObject = object


if QObject is not object:
    class Shortcuts(QObject):
        changed = Signal()
        said = Signal(str, bool)
        _back = Signal(object)

        def __init__(self, demo: bool = False):
            super().__init__()
            self._back.connect(lambda fn: fn())
            self._demo, self._picked, self._apps = demo, "", None
            self._state = {}
            if demo:
                self._list = [dict(s, id=f"s{i}", on=True) for i, s in enumerate(STARTERS[:4])]
                self._list.append({"id": "s9", "name": "Writing time", "colour": "#6C7BFF", "glyph": "edit", "on": True, "when": {"kind": "manual"},
                                   "steps": [{"do": "volume", "level": 0}, {"do": "app", "app": "huginn-writer.desktop"}, {"do": "site", "url": "https://mynoise.example"}]})
                self._state = {"s0": {"time": int(time.time()) - 3600 * 26, "ok": True, "words": "Copied 48 photos and videos to Pictures/Imported."},
                               "s1": {"time": int(time.time()) - 3600 * 5, "ok": True, "words": "Opened Feeds. Opened Calendar. Opened Mail."}}
                self._picked = "s0"
                return
            self._list = load()
            self._state = state()
            self._watch = QTimer(self)
            self._watch.setInterval(3000)
            self._watch.timeout.connect(self._look)
            self._watch.start()

        def _look(self) -> None:
            fresh = state()
            if fresh != self._state:
                self._state = fresh
                self.changed.emit()

        def _keep(self) -> None:
            if not self._demo:
                try:
                    save(self._list)
                except OSError as err:
                    self.said.emit(f"Couldn't save: {err.strerror or err}", True)
            self.changed.emit()

        def _find(self, ident: str):
            return next((s for s in self._list if s["id"] == ident), None)

        def _names(self) -> dict:
            if self._apps is None:
                self._apps = [] if self._demo else apps()
            names = {a["id"]: a["name"] for a in self._apps}
            names.update({"huginn-feeds.desktop": "Feeds", "huginn-calendar.desktop": "Calendar", "huginn-mail.desktop": "Mail", "huginn-writer.desktop": "Writer"} if self._demo else {})
            return names

        def _face(self, s: dict) -> dict:
            names = self._names()
            last = self._state.get(s["id"], {})
            kind = s.get("when", {}).get("kind", "manual")
            return {"id": s["id"], "name": s.get("name") or "Shortcut", "colour": s.get("colour") or "#FF4FC3", "glyph": s.get("glyph") or "play", "on": s.get("on", True),
                    "kind": kind, "auto": kind != "manual", "when": describe_when(s.get("when")), "chain": [describe_step(x, names) for x in s.get("steps", [])],
                    "steps": s.get("steps", []), "whenData": s.get("when", {"kind": "manual"}), "menu": bool(s.get("menu")),
                    "last": _ago(last.get("time", 0)), "lastOk": last.get("ok", True), "lastWords": last.get("words", "")}

        shortcuts = Property("QVariantList", lambda self: [self._face(s) for s in self._list], notify=changed)
        current = Property("QVariantMap", lambda self: self._face(self._find(self._picked)) if self._find(self._picked) else {}, notify=changed)
        starters = Property("QVariantList", lambda self: [{"name": s["name"], "colour": s["colour"], "glyph": s["glyph"], "about": s["about"], "when": describe_when(s["when"]), "index": i}
                                                          for i, s in enumerate(STARTERS) if not any(x.get("name") == s["name"] for x in self._list)], notify=changed)
        triggers = Property("QVariantList", lambda self: [{"id": k, "name": v} for k, v in TRIGGERS.items()], constant=True)
        stepKinds = Property("QVariantList", lambda self: [{"id": k, "name": v} for k, v in STEPS.items()], constant=True)
        def _get_apps(self) -> list:
            self._names()
            return [{"id": a["id"], "name": a["name"]} for a in self._apps or []]

        appList = Property("QVariantList", _get_apps, notify=changed)
        watching = Property(bool, lambda self: self._demo or agent_running(), notify=changed)
        days = Property("QVariantList", lambda self: DAYS, constant=True)

        @Slot(str)
        def choose(self, ident: str) -> None:
            self._picked = ident if self._find(ident) else ""
            self.changed.emit()

        @Slot(result=str)
        def create(self) -> str:
            s = {"id": uuid.uuid4().hex[:10], "name": "New shortcut", "colour": "#FF4FC3", "glyph": "play", "on": True, "when": {"kind": "manual"}, "steps": []}
            self._list.append(s)
            self._picked = s["id"]
            self._keep()
            return s["id"]

        @Slot(int)
        def addStarter(self, index: int) -> None:
            if 0 <= index < len(STARTERS):
                s = {k: v for k, v in STARTERS[index].items() if k != "about"}
                s = json.loads(json.dumps(s))
                s.update(id=uuid.uuid4().hex[:10], on=True)
                self._list.append(s)
                self._picked = s["id"]
                self._keep()
                self._wake()

        @Slot(str, str, "QVariant")
        def set(self, ident: str, key: str, value) -> None:
            s = self._find(ident)
            if not s:
                return
            if key == "name":
                s["name"] = " ".join(str(value).split())[:60] or "Shortcut"
                self._menu(s)
            elif key in ("colour", "glyph"):
                s[key] = str(value)[:20]
            elif key == "on":
                s["on"] = bool(value)
            elif key == "menu":
                s["menu"] = bool(value)
                self._menu(s)
            self._keep()

        @Slot(str, "QVariantMap")
        def setWhen(self, ident: str, when: dict) -> None:
            s = self._find(ident)
            kind = (when or {}).get("kind")
            if not s or kind not in TRIGGERS:
                return
            clean = {"kind": kind}
            if kind == "time":
                at = str(when.get("at") or "08:00").strip()
                m = re.fullmatch(r"(\d{1,2})[:.](\d{2})", at)
                clean["at"] = f"{int(m.group(1)):02d}:{m.group(2)}" if m and int(m.group(1)) < 24 and int(m.group(2)) < 60 else "08:00"
                clean["days"] = [d for d in DAYS if d in (when.get("days") or DAYS)] or DAYS
            elif kind in ("phone", "wifi"):
                clean["name"] = str(when.get("name") or "").strip()[:80]
            elif kind == "drive":
                clean["label"] = str(when.get("label") or "").strip()[:80]
            elif kind == "battery":
                try:
                    clean["below"] = max(5, min(90, int(when.get("below") or 20)))
                except (TypeError, ValueError):
                    clean["below"] = 20
            s["when"] = clean
            self._keep()
            if kind != "manual":
                self._wake()

        @Slot(str, str)
        def addStep(self, ident: str, kind: str) -> None:
            s = self._find(ident)
            if s and kind in STEPS:
                step = {"do": kind}
                step.update({"wait": {"seconds": 5}, "volume": {"level": 50}, "wifi": {"on": False}, "notify": {"title": "", "text": ""}}.get(kind, {}))
                s.setdefault("steps", []).append(step)
                self._keep()

        @Slot(str, int, "QVariantMap")
        def setStep(self, ident: str, at: int, fields: dict) -> None:
            s = self._find(ident)
            if not s or not 0 <= at < len(s.get("steps", [])):
                return
            step = s["steps"][at]
            for k, v in (fields or {}).items():
                if k in ("app", "url", "path", "title", "text", "command"):
                    step[k] = str(v)[:2000]
                elif k in ("seconds", "level"):
                    try:
                        step[k] = max(0, min(3600 if k == "seconds" else 100, int(v)))
                    except (TypeError, ValueError):
                        pass
                elif k == "on":
                    step[k] = bool(v)
            self._keep()

        @Slot(str, int, int)
        def moveStep(self, ident: str, at: int, by: int) -> None:
            s = self._find(ident)
            steps = s.get("steps", []) if s else []
            to = at + by
            if 0 <= at < len(steps) and 0 <= to < len(steps):
                steps.insert(to, steps.pop(at))
                self._keep()

        @Slot(str, int)
        def removeStep(self, ident: str, at: int) -> None:
            s = self._find(ident)
            if s and 0 <= at < len(s.get("steps", [])):
                s["steps"].pop(at)
                self._keep()

        @Slot(str)
        def remove(self, ident: str) -> None:
            s = self._find(ident)
            if s:
                s["menu"] = False
                self._menu(s)
                self._list.remove(s)
                if self._picked == ident:
                    self._picked = ""
                self._keep()

        @Slot(str)
        def runNow(self, ident: str) -> None:
            s = self._find(ident)
            if not s or self._demo:
                return
            if not s.get("steps"):
                self.said.emit("Add a step first.", True)
                return
            snapshot = json.loads(json.dumps(s))

            def go():
                try:
                    result = run(snapshot, {})
                except Exception as err:
                    result = (False, str(err))
                self._back.emit(lambda: (setattr(self, "_state", state()), self.said.emit(result[1], not result[0]), self.changed.emit()))
            threading.Thread(target=go, daemon=True).start()
            self.said.emit(f"Running “{s.get('name')}”…", False)

        def _menu(self, s: dict) -> None:
            """A shortcut you start yourself can have its own entry in the apps menu."""
            if self._demo:
                return
            path = Path.home() / ".local/share/applications" / f"huginn-shortcut-{s['id']}.desktop"
            if s.get("menu"):
                path.parent.mkdir(parents=True, exist_ok=True)
                name = s.get("name", "Shortcut").replace("\n", " ")
                path.write_text("[Desktop Entry]\nType=Application\n" f"Name={name}\nComment=A shortcut\n"
                                f"Exec={shlex.quote(sys.executable)} {shlex.quote(str(HERE / 'huginn_shortcuts.py'))} run {s['id']}\nIcon=huginn-shortcuts\nCategories=Utility;\n", encoding="utf-8")
            else:
                try:
                    path.unlink()
                except OSError:
                    pass

        def _wake(self) -> None:
            """Automatic shortcuts need the watcher; start it if this session doesn't have one yet."""
            if self._demo or agent_running():
                return
            try:
                _start([sys.executable, str(HERE / "huginn_shortcuts.py"), "agent"])
            except OSError:
                pass
            QTimer.singleShot(1500, self.changed.emit)


def _ago(stamp: int) -> str:
    if not stamp:
        return ""
    gap = time.time() - stamp
    if gap < 60:
        return "just now"
    if gap < 3600:
        return f"{int(gap // 60)} min ago"
    if gap < 86400:
        return f"{int(gap // 3600)} h ago"
    return dt.datetime.fromtimestamp(stamp).strftime("%-d %b, %H:%M")


if __name__ == "__main__":
    if sys.argv[1:2] == ["agent"]:
        sys.exit(Agent().serve())
    if sys.argv[1:2] == ["run"] and len(sys.argv) > 2:
        hit = next((s for s in load() if s["id"] == sys.argv[2]), None)
        if not hit:
            print("No such shortcut.", file=sys.stderr)
            sys.exit(2)
        ok, words = run(hit)
        print(words)
        sys.exit(0 if ok else 1)
    print(__doc__)
