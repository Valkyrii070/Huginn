"""Huginn Software Update: one place for every kind of update.

    System       Ubuntu's packages (the kernel, drivers, Qt WebEngine, every library) through PackageKit (pkgcli, or pkcon before 1.3),
                 or apt through pkexec when PackageKit isn't there. The system asks for the administrator password
                 in its own window; this app never sees it.
    Apps         apps from Flathub, for you and for everyone on the computer (flatpak update).
    Firmware     the computer's own firmware and devices that take updates (fwupd, from the LVFS).
    Huginn       the browser, from its own repository (vendor/huginn/SOURCE says which). A newer Huginn goes into
                 ~/.local/share/huginn-os/browser, and /usr/bin/huginn starts whichever copy is newer, so it needs
                 no password and the previous copy stays for "Go Back".

Automatic updates (on by default): every six hours `huginn_updates.py watch` looks; apps and Huginn are brought up
to date at once, and system updates are downloaded and put in place for the next restart (PackageKit's offline
updates), so nothing changes under a running program. What it found is kept in ~/.cache/huginn/updates.json, which
Settings and the App Store read.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

from PySide6.QtCore import Property, QObject, Signal, Slot

HOME = Path.home()
CACHE = Path(os.environ.get("XDG_CACHE_HOME") or HOME / ".cache") / "huginn"
STATE = CACHE / "updates.json"
BROWSER_HOME = Path(os.environ.get("XDG_DATA_HOME") or HOME / ".local/share") / "huginn-os" / "browser"
SYSTEM_BROWSER = Path("/usr/share/huginn")
RESTART_NAMES = re.compile(r"^(linux-(image|modules|firmware)|systemd|libc6|libsystemd|dbus|nvidia-|mesa|libgl|kwin|plasma-workspace|qt6-|libqt6)")
ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
RUNTIME_MARKS = (".Platform", ".Sdk", ".GL.", ".GL32.", ".Codecs", ".Extension", "openh264", ".Locale", ".Debug", ".Gtk3theme", ".KStyle",
                 ".PlatformTheme", ".WaylandDecoration", ".ffmpeg", ".VAAPI")



def pk(what: str) -> list:
    """PackageKit's command line for `what` (refresh, update, offline): pkgcli from PackageKit 1.3 (Ubuntu 26.04),
    pkcon before it; [] when neither is installed."""
    if HAVE("pkgcli"):
        return {"refresh": ["pkgcli", "refresh"], "update": ["pkgcli", "update", "-y"],
                "offline": ["pkgcli", "offline-update", "prepare", "-y"]}[what]
    if HAVE("pkcon"):
        return {"refresh": ["pkcon", "refresh", "--noninteractive"], "update": ["pkcon", "update", "-y", "--noninteractive"],
                "offline": ["pkcon", "update", "--only-download", "-y", "--noninteractive"]}[what]
    return []

def run(argv: list, stdin: str = None, timeout: float = 120) -> tuple:
    try:
        done = subprocess.run(argv, input=stdin, capture_output=True, text=True, timeout=timeout, env={**os.environ, "LC_ALL": "C.UTF-8"})
        return done.returncode, done.stdout, done.stderr
    except FileNotFoundError:
        return 127, "", f"{argv[0]} isn't installed"
    except subprocess.TimeoutExpired:
        return 124, "", f"{argv[0]} took too long"
    except OSError as err:
        return 126, "", str(err)


RUN = run
HAVE = shutil.which


def fetch(url: str, timeout: float = 30) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "Huginn-OS-Software-Update", "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=timeout) as reply:          # noqa: S310  (https only, below)
        return reply.read()


FETCH = fetch


# ------------------------------------------------------------------------------------------- what's waiting
def parse_apt(text: str) -> list:
    """`apt list --upgradable` → [{id, name, version, from, security}]."""
    out = []
    for line in text.splitlines():
        m = re.match(r"^([^/\s]+)/(\S+)\s+(\S+)\s+\S+(?:\s+\[upgradable from:\s*([^\]]+)\])?", line)
        if m:
            out.append({"id": "deb:" + m.group(1), "name": m.group(1), "version": m.group(3), "from": (m.group(4) or "").strip(),
                        "security": "-security" in m.group(2), "kind": "system"})
    return out


def parse_apt_simulation(text: str) -> list:
    """`apt-get -s dist-upgrade` → the same rows as parse_apt, for what apt would really put in: its "Inst" lines.
    Ubuntu holds some updates back for a while (phased updates, rolled out to a few computers at a time) and some
    need a choice apt won't make by itself; `apt list --upgradable` lists those too, so they'd be shown as ready,
    "installed", and still be there afterwards."""
    out = []
    for line in text.splitlines():
        m = re.match(r"^Inst\s+(\S+)\s+(?:\[([^\]]+)\]\s+)?\((\S+)\s+([^)]*)\)", line)
        if m:
            out.append({"id": "deb:" + m.group(1), "name": m.group(1), "version": m.group(3), "from": (m.group(2) or "").strip(),
                        "security": "-security" in m.group(4), "kind": "system", "new": not m.group(2)})
    return out


def check_system(refresh: bool = True) -> list:
    if refresh and pk("refresh"):
        RUN(pk("refresh"), None, 300)
    code, out, _ = RUN(["apt-get", "-s", "-o", "Debug::NoLocking=1", "dist-upgrade"], None, 180)
    if code == 0:
        return [i for i in parse_apt_simulation(out) if not i.get("new")]      # new packages come with an update; they aren't one
    code, out, _ = RUN(["apt", "list", "--upgradable"], None, 120)
    return parse_apt(out) if code == 0 else []


def parse_flatpak(text: str, where: str) -> list:
    out = []
    for line in text.splitlines():
        f = line.split("\t")
        if len(f) >= 2 and "." in f[0]:
            out.append({"id": f"flatpak:{where}:{f[0]}", "app": f[0], "name": f[1] or f[0], "version": f[2] if len(f) > 2 else "", "from": "",
                        "security": False, "kind": "app", "where": where, "runtime": any(w in f[0] for w in RUNTIME_MARKS)})
    return out


def check_flatpak() -> list:
    if not HAVE("flatpak"):
        return []
    out = []
    for where in ("user", "system"):
        code, text, _ = RUN(["flatpak", "remote-ls", f"--{where}", "--updates", "--columns=application,name,version"], None, 180)
        if code == 0:
            out += parse_flatpak(text, where)
    return out


def parse_fwupd(text: str) -> list:
    try:
        data = json.loads(text)
    except ValueError:
        return []
    out = []
    for dev in data.get("Devices", []):
        rel = (dev.get("Releases") or [{}])[0]
        if rel:
            out.append({"id": "fw:" + str(dev.get("DeviceId", dev.get("Name", ""))), "name": dev.get("Name", "Firmware"), "version": rel.get("Version", ""),
                        "from": dev.get("Version", ""), "security": "security" in (rel.get("Summary", "") + " ".join(rel.get("Issues", []) or [])).lower() or bool(rel.get("Issues")),
                        "kind": "firmware", "note": re.sub(r"<[^>]+>", " ", rel.get("Description", "")).strip()[:300]})
    return out


def check_firmware() -> list:
    if not HAVE("fwupdmgr"):
        return []
    code, text, _ = RUN(["fwupdmgr", "get-updates", "--json", "--no-unreported-check", "--no-metadata-check"], None, 120)
    return parse_fwupd(text) if code == 0 else []


def read_source(folder: Path) -> dict:
    """vendor/huginn/SOURCE: repo, commit, date."""
    out = {}
    try:
        for line in (folder / "SOURCE").read_text(encoding="utf-8").splitlines():
            k, _, v = line.partition(":")
            out[k.strip()] = v.strip()
    except OSError:
        pass
    return out


def browser_installed() -> dict:
    """The copy of Huginn that /usr/bin/huginn starts: the newer of the system's and the one Software Update fetched."""
    system, mine = read_source(SYSTEM_BROWSER), read_source(BROWSER_HOME / "current")
    if mine.get("date", "") > system.get("date", "") and (BROWSER_HOME / "current" / "safari_browser.py").is_file():
        return {**mine, "where": "yours"}
    return {**system, "where": "system"}


def github_repo(url: str) -> str:
    m = re.match(r"https://github\.com/([\w.-]+/[\w.-]+?)(?:\.git)?/?$", url or "")
    return m.group(1) if m else ""


def check_huginn() -> list:
    have = browser_installed()
    repo = github_repo(have.get("repo", "")) or github_repo(read_source(SYSTEM_BROWSER).get("repo", ""))
    if not repo:
        return []
    try:
        label = ""
        try:
            ref = json.loads(FETCH(f"https://api.github.com/repos/{repo}/releases/latest")).get("tag_name", "")
            label = ref
        except urllib.error.HTTPError as err:
            if err.code != 404:
                raise
            ref = ""
        if not ref:                                                   # no releases: follow the main branch
            ref = json.loads(FETCH(f"https://api.github.com/repos/{repo}")).get("default_branch", "main")
        head = json.loads(FETCH(f"https://api.github.com/repos/{repo}/commits/{ref}"))
        sha = head.get("sha", "")
        date = ((head.get("commit") or {}).get("committer") or {}).get("date", "")[:10]
    except (OSError, ValueError, urllib.error.URLError, AttributeError):
        return []
    if not sha or sha == have.get("commit") or (date and date <= have.get("date", "")):
        return []
    return [{"id": "huginn", "name": "Huginn", "version": label or (date + " · " + sha[:7]), "from": have.get("date", ""), "security": False,
             "kind": "huginn", "repo": repo, "sha": sha, "date": date}]


def needs_restart(items: list) -> bool:
    return Path("/var/run/reboot-required").exists() or any(i["kind"] == "system" and RESTART_NAMES.match(i["name"]) for i in items)


# ------------------------------------------------------------------------------------------- putting them in
class Stopped(Exception):
    pass


def safe_members(tar: tarfile.TarFile, top_only: bool = True):
    """Only plain files and folders that stay inside the folder they're unpacked into."""
    for m in tar.getmembers():
        name = m.name.split("/", 1)[1] if top_only and "/" in m.name else ("" if top_only else m.name)
        if not name or name.startswith("/") or ".." in Path(name).parts or not (m.isfile() or m.isdir()):
            continue
        m.name = name
        m.mode = 0o755 if m.isdir() else (0o644 | (m.mode & 0o111))
        yield m


def install_huginn(item: dict, root: Path = None) -> str:
    """Fetch that version of Huginn, check it, and make it the one /usr/bin/huginn starts. The old one stays."""
    root = root or BROWSER_HOME
    data = FETCH(f"https://codeload.github.com/{item['repo']}/tar.gz/{item['sha']}", 300)
    target = root / item["sha"][:12]
    part = root / f".{item['sha'][:12]}.part"
    shutil.rmtree(part, ignore_errors=True)
    part.mkdir(parents=True)
    import io
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
        members = list(safe_members(tar))
        try:
            tar.extractall(part, members=members, filter="data")
        except TypeError:                                             # an older Python without extraction filters
            tar.extractall(part, members=members)                     # noqa: S202  (members checked by safe_members)
    if not (part / "safari_browser.py").is_file():
        shutil.rmtree(part, ignore_errors=True)
        raise RuntimeError("That version of Huginn is missing its main file, so it wasn't put in.")
    code, _, err = RUN([sys.executable, "-m", "py_compile", str(part / "safari_browser.py")], None, 60)
    if code != 0:
        shutil.rmtree(part, ignore_errors=True)
        raise RuntimeError("That version of Huginn doesn't start (" + (err.strip().splitlines() or ["it has an error"])[-1][:120] + "), so it wasn't put in.")
    (part / "SOURCE").write_text(f"repo: https://github.com/{item['repo']}.git\ncommit: {item['sha']}\ndate: {item['date']}\n", encoding="utf-8")
    shutil.rmtree(target, ignore_errors=True)
    os.replace(part, target)
    current = root / "current"
    if current.is_symlink() or current.exists():
        old = os.readlink(current) if current.is_symlink() else ""
        if old and old != target.name:
            (root / "previous").unlink(missing_ok=True)
            os.symlink(old, root / "previous")
        current.unlink()
    os.symlink(target.name, current)
    keep = {target.name, os.readlink(root / "previous") if (root / "previous").is_symlink() else ""}
    for old in root.iterdir():                                       # keep the newest two copies
        if old.is_dir() and not old.is_symlink() and old.name not in keep and not old.name.startswith("."):
            shutil.rmtree(old, ignore_errors=True)
    return "Huginn is up to date. Open windows keep the old version until you start Huginn again."


def roll_back_huginn(root: Path = None) -> str:
    root = root or BROWSER_HOME
    prev, current = root / "previous", root / "current"
    if prev.is_symlink():
        target = os.readlink(prev)
        mine = os.readlink(current) if current.is_symlink() else ""
        current.unlink(missing_ok=True)
        os.symlink(target, current)
        prev.unlink()
        if mine:
            os.symlink(mine, prev)
        return "Huginn went back to the version before."
    if current.is_symlink():
        current.unlink()
        return "Huginn went back to the version that came with the system."
    return "There's no other version to go back to."


def run_stream(argv: list, on_line, stopped=lambda: False) -> int:
    """Run a tool, handing each line it prints to on_line; stop it if asked."""
    try:
        proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1, env={**os.environ, "LC_ALL": "C.UTF-8"})
    except FileNotFoundError:
        return 127
    for line in proc.stdout:
        on_line(ANSI.sub("", line).rstrip())
        if stopped():
            proc.terminate()
            break
    return proc.wait()


def save_state(state: dict) -> None:
    try:
        STATE.parent.mkdir(parents=True, exist_ok=True)
        part = STATE.with_name(".updates.json.part")
        part.write_text(json.dumps(state, indent=1), encoding="utf-8")
        os.replace(part, STATE)
    except OSError:
        pass


def load_state() -> dict:
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def auto_wanted() -> bool:
    try:
        cfg = Path(os.environ.get("XDG_CONFIG_HOME") or HOME / ".config") / "huginn-shell" / "settings.json"
        return json.loads(cfg.read_text(encoding="utf-8")).get("autoUpdate", "true") == "true"
    except (OSError, ValueError, AttributeError):
        return True


def look_everywhere(refresh: bool = True) -> list:
    items = []
    for check in (lambda: check_system(refresh), check_flatpak, check_firmware, check_huginn):
        try:
            items += check()
        except Exception:                                            # noqa: BLE001  (one source failing mustn't hide the rest)
            pass
    return items


DEMO = [{"id": "deb:linux-image-generic", "name": "linux-image-generic", "version": "6.17.0-9", "from": "6.17.0-8", "security": True, "kind": "system"},
        {"id": "deb:libqt6webenginecore6", "name": "libqt6webenginecore6", "version": "6.10.1-1ubuntu2", "from": "6.10.1-1ubuntu1", "security": True, "kind": "system"},
        {"id": "deb:mesa-vulkan-drivers", "name": "mesa-vulkan-drivers", "version": "25.2.4-1", "from": "25.2.3-1", "security": False, "kind": "system"},
        {"id": "deb:firefox-locale", "name": "openssl", "version": "3.5.1-2ubuntu0.2", "from": "3.5.1-2ubuntu0.1", "security": True, "kind": "system"},
        {"id": "flatpak:system:org.kde.krita", "app": "org.kde.krita", "name": "Krita", "version": "5.3.1", "from": "", "security": False, "kind": "app", "where": "system", "runtime": False},
        {"id": "flatpak:system:org.libreoffice.LibreOffice", "app": "org.libreoffice.LibreOffice", "name": "LibreOffice", "version": "25.8.3", "from": "", "security": False, "kind": "app", "where": "system", "runtime": False},
        {"id": "flatpak:system:org.freedesktop.Platform.GL.default", "app": "org.freedesktop.Platform.GL.default", "name": "Mesa", "version": "25.2.4", "from": "", "security": False, "kind": "app", "where": "system", "runtime": True},
        {"id": "fw:uefi", "name": "System Firmware", "version": "0.3.22", "from": "0.3.18", "security": True, "kind": "firmware", "note": "Fixes a security problem in the firmware's network boot and makes sleep more reliable."},
        {"id": "huginn", "name": "Huginn", "version": "2026-11-14 · 4b1e9c2", "from": "2026-11-13", "security": False, "kind": "huginn", "repo": "Valkyrii070/Huginn", "sha": "4b1e9c2", "date": "2026-11-14"}]


class Updates(QObject):
    """Software Update in Settings, and the App Store's Updates page."""
    changed = Signal()
    said = Signal(str, bool)
    _back = Signal(str, object)

    def __init__(self, demo: bool = False, shell_settings=None):
        super().__init__()
        self._demo, self._settings = demo, shell_settings
        saved = {} if demo else load_state()
        self._items = list(DEMO) if demo else saved.get("items", [])
        self._checked = time.time() - 1800 if demo else float(saved.get("checked", 0))
        self._phase, self._progress, self._line = "idle", 0.0, ""
        self._restart = bool(saved.get("restart")) if not demo else False
        self._stop = False
        self._back.connect(self._take)

    def _emit(self, what, data=None):
        self._back.emit(what, data)

    @Slot(str, object)
    def _take(self, what: str, data) -> None:
        if what == "said":
            self.said.emit(*data)
        elif what == "items":
            self._items, self._checked, self._phase = data, time.time(), "idle"
            save_state({"checked": self._checked, "items": self._items, "restart": self._restart})
        elif what == "phase":
            self._phase = data
        elif what == "progress":
            self._progress, self._line = data
        elif what == "done":
            gone, restart = data
            self._items = [i for i in self._items if i["id"] not in gone]
            self._restart = self._restart or restart
            self._phase, self._progress = "idle", 0.0
            save_state({"checked": self._checked, "items": self._items, "restart": self._restart})
        self.changed.emit()

    items = Property("QVariantList", lambda self: self._items, notify=changed)
    count = Property(int, lambda self: len([i for i in self._items if not i.get("runtime")]), notify=changed)
    phase = Property(str, lambda self: self._phase, notify=changed)
    progress = Property(float, lambda self: self._progress, notify=changed)
    line = Property(str, lambda self: self._line, notify=changed)
    restart = Property(bool, lambda self: self._restart, notify=changed)
    demo = Property(bool, lambda self: self._demo, constant=True)

    @Property(str, notify=changed)
    def checked(self):
        if not self._checked:
            return "Never"
        ago = time.time() - self._checked
        return "Just now" if ago < 90 else f"{int(ago // 60)} minutes ago" if ago < 3600 else f"{int(ago // 3600)} hours ago" if ago < 86400 else time.strftime("%B %-d", time.localtime(self._checked))

    @Property("QVariantMap", notify=changed)
    def huginn(self):
        have = {"commit": "dc892f21", "date": "2026-11-13", "where": "system"} if self._demo else browser_installed()
        return {"date": have.get("date", ""), "commit": have.get("commit", "")[:7], "yours": have.get("where") == "yours",
                "canGoBack": not self._demo and ((BROWSER_HOME / "previous").is_symlink() or (BROWSER_HOME / "current").is_symlink())}

    @Slot(bool)
    def look(self, force: bool) -> None:
        if self._phase != "idle" or (not force and time.time() - self._checked < 3600):
            return
        if self._demo:
            self._checked = time.time()
            self.changed.emit()
            return
        self._phase = "checking"
        self.changed.emit()
        threading.Thread(target=lambda: self._emit("items", look_everywhere(force)), daemon=True).start()

    @Slot(str)
    def install(self, which: str) -> None:
        """which: "all", or a kind (system, app, firmware, huginn), or one item's id."""
        if self._phase != "idle":
            return
        chosen = [i for i in self._items if which == "all" or i["kind"] == which or i["id"] == which]
        if not chosen:
            return
        if self._demo:
            self._items = [i for i in self._items if i not in chosen]
            self._restart = self._restart or any(i["kind"] in ("system", "firmware") and (i["kind"] == "firmware" or RESTART_NAMES.match(i["name"])) for i in chosen)
            self.changed.emit()
            self.said.emit("Everything chosen is up to date.", False)
            return
        self._phase, self._stop = "installing", False
        self.changed.emit()
        threading.Thread(target=self._install, args=(chosen,), daemon=True).start()

    def _install(self, chosen: list) -> None:
        done, restart, problems = set(), False, []
        steps = [k for k in ("app", "huginn", "firmware", "system") if any(i["kind"] == k for i in chosen)]
        for n, kind in enumerate(steps):
            part = [i for i in chosen if i["kind"] == kind]
            base = n / len(steps)

            def line(text, base=base):
                m = re.search(r"(\d{1,3})(?:\.\d+)?%", text)
                frac = min(1.0, int(m.group(1)) / 100) if m else None
                self._emit("progress", (base + (frac or 0) / len(steps), text[:140]))
            stopped = lambda: self._stop                                      # noqa: E731
            last = {"text": ""}

            def line(text, base=base, line=line, last=last):
                if text.strip():
                    last["text"] = text.strip()
                line(text)

            def why(what: str) -> str:
                tail = re.sub(r"^(E|Error|error):\s*", "", last["text"])[:120]
                return what + (f" ({tail})" if tail and not re.search(r"\d+%", tail) else "")
            try:
                if kind == "app":
                    for where in sorted({i["where"] for i in part}):
                        ids = [i["app"] for i in part if i["where"] == where]
                        everything = len(ids) == len([i for i in self._items if i["kind"] == "app" and i["where"] == where])
                        code = run_stream(["flatpak", "update", f"--{where}", "-y", "--noninteractive"] + ([] if everything else ids), line, stopped)
                        if code == 0:
                            done |= {i["id"] for i in part if i["where"] == where}
                        else:
                            problems.append(why("Some apps weren't updated"))
                elif kind == "huginn":
                    line("Fetching Huginn…")
                    self._emit("said", (install_huginn(part[0]), False))
                    done.add("huginn")
                elif kind == "firmware":
                    code = run_stream(["fwupdmgr", "update", "-y", "--no-reboot-check"], line, stopped)
                    if code == 0:
                        done |= {i["id"] for i in part}
                        restart = True
                    else:
                        problems.append(why("The firmware wasn't updated"))
                else:
                    if pk("update"):
                        code = run_stream(pk("update"), line, stopped)
                    else:
                        code = run_stream(["pkexec", "apt-get", "-y", "-o", "Dpkg::Options::=--force-confold", "full-upgrade"], line, stopped)
                    if code == 0:
                        done |= {i["id"] for i in part}
                        restart = restart or needs_restart(part)
                    else:
                        problems.append("The system wasn't updated" + (" (the password wasn't given)" if code in (126, 127) else why("")))
            except Exception as err:                                      # noqa: BLE001
                problems.append(str(err)[:160])
            if self._stop:
                problems.append("Stopped")
                break
        # What's really still waiting: look again rather than trusting the tools' exit codes (PackageKit and apt can
        # end well having put in only part of it), and say so plainly.
        self._emit("progress", (1.0, "Checking what went in…"))
        try:
            fresh = look_everywhere(False)
        except Exception:                                                 # noqa: BLE001
            fresh = None
        if fresh is None:
            self._emit("done", (done, restart))
        else:
            self._emit("done", ({i["id"] for i in chosen} | done, restart))
            self._emit("items", fresh)
        waiting = [i for i in chosen if fresh is not None and any(f["id"] == i["id"] for f in fresh)]
        put_in = len(chosen) - len(waiting)
        if not waiting and not problems:
            self._emit("said", ("Up to date." + (" Restart to finish." if restart else ""), False))
        else:
            names = ", ".join(i["name"] for i in waiting[:3]) + (f" and {len(waiting) - 3} more" if len(waiting) > 3 else "")
            text = (f"{put_in} of {len(chosen)} updates went in. " if put_in else "The updates didn't go in. ") + \
                   (f"Still waiting: {names}. " if waiting else "") + ("; ".join(problems) + "." if problems else "")
            self._emit("said", (text.strip(), True))

    @Slot()
    def stop(self) -> None:
        self._stop = True

    @Slot()
    def goBack(self) -> None:
        if self._demo:
            self.said.emit("Huginn went back to the version before.", False)
            return
        try:
            self.said.emit(roll_back_huginn(), False)
        except OSError as err:
            self.said.emit(f"Couldn't go back: {err}", True)
        self.changed.emit()

    @Slot()
    def restartNow(self) -> None:
        if not self._demo:
            RUN(["systemctl", "reboot"], None, 10)


# ------------------------------------------------------------------------------------------- in the background
def watch(every: float = 6 * 3600, first_wait: float = 300) -> None:
    """Look for updates now and then. With automatic updates on, apps and Huginn are updated straight away and
    system updates are downloaded and set to go in at the next restart."""
    time.sleep(first_wait)
    while True:
        items = look_everywhere(True)
        restart = needs_restart(items)
        if auto_wanted():
            for where in ("user", "system"):
                if any(i["kind"] == "app" and i.get("where") == where for i in items):
                    if RUN(["flatpak", "update", f"--{where}", "-y", "--noninteractive"], None, 3600)[0] == 0:
                        items = [i for i in items if not (i["kind"] == "app" and i.get("where") == where)]
            for i in [i for i in items if i["kind"] == "huginn"]:
                try:
                    install_huginn(i)
                    items.remove(i)
                except Exception:                                    # noqa: BLE001
                    pass
            if any(i["kind"] == "system" for i in items) and pk("offline"):
                if HAVE("pkgcli"):                             # PackageKit 1.3 (26.04): one step downloads and triggers
                    RUN(pk("offline"), None, 7200)
                elif RUN(pk("offline"), None, 7200)[0] == 0:
                    RUN(["pkcon", "offline-trigger"], None, 60)
        save_state({"checked": time.time(), "items": items, "restart": restart, "auto": auto_wanted()})
        if items and HAVE("notify-send"):
            security = any(i.get("security") for i in items)
            RUN(["notify-send", "--app-name=Software Update", "--icon=huginn-settings", "Updates are ready" if not auto_wanted() else "Updates will go in when you restart",
                 ("Some fix security problems. " if security else "") + "Open Settings › Software Update."], None, 10)
        time.sleep(every)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "watch":
        watch()
    elif len(sys.argv) > 1 and sys.argv[1] == "check":
        print(json.dumps(look_everywhere(True), indent=1))
