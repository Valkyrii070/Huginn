"""Games: one shelf for everything you play.

Steam's installed games are read from Steam's own files (nothing is asked of Steam's servers, and this app never
sees a Steam password: signing in stays in Steam's window). Epic, GOG and Amazon games come the same way from
Heroic, the free launcher that signs in to those three shops: its lists are read, and it starts their games. Windows games you add yourself run through Proton
(the one Steam installs) or Wine, each in its own bottle, with a profile per game: which compatibility layer,
launch arguments, environment, the performance overlay, GameMode, how Wine waits on locks, DLL preferences.
Linux games run directly."""
import calendar
import hashlib
import json
import os
import re
import shlex
import shutil
import signal
import subprocess
import threading
import time
import uuid
from pathlib import Path

from PySide6.QtCore import Property, QObject, QTimer, QUrl, Signal, Slot

HERE = Path(__file__).resolve().parent
DATA_HOME = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share") / "huginn"
ID_BASE = 76561197960265728                       # a SteamID64 minus this is the folder name under userdata/
WINDOWS = (".exe", ".msi", ".bat", ".cmd")
# Things Steam installs like games that aren't games.
NOT_GAMES = re.compile(r"^(Proton\b|Steam Linux Runtime|Steamworks Common|SteamVR$|Steam Controller Configs)", re.I)
SYNC = {"": "Automatic", "fsync": "Fsync", "esync": "Esync", "none": "Off"}
LANGS = [("", "Same as the computer"), ("en_US", "English"), ("ja_JP", "Japanese"), ("zh_CN", "Chinese (Simplified)"), ("zh_TW", "Chinese (Traditional)"),
         ("ko_KR", "Korean"), ("ru_RU", "Russian"), ("de_DE", "German"), ("fr_FR", "French"), ("es_ES", "Spanish")]
DEFAULTS = {"runner": "auto", "args": "", "env": "", "overlay": False, "gamemode": False, "sync": "", "dlls": {}, "lang": "", "novideo": False}
ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
DLL_NAME = re.compile(r"^[A-Za-z0-9_.\-]{1,40}$")


# ============================================================================================== Steam's files
def read_vdf(text: str) -> dict:
    """Valve's text format ("key" "value" pairs and "key" { ... } blocks) as nested dicts. Broken input gives
    whatever was read up to the break, never an error."""
    tokens = re.findall(r'"((?:[^"\\]|\\.)*)"|([{}])', text)
    root: dict = {}
    stack, key = [root], None
    for word, brace in tokens:
        if brace == "{":
            if key is None:
                break
            child: dict = {}
            stack[-1][key] = child
            stack.append(child)
            key = None
        elif brace == "}":
            if len(stack) == 1:
                break
            stack.pop()
            key = None
        else:
            word = re.sub(r"\\(.)", lambda m: {"n": "\n", "t": "\t"}.get(m.group(1), m.group(1)), word)
            if key is None:
                key = word
            else:
                stack[-1][key] = word
                key = None
    return root


def write_vdf(data: dict, depth: int = 0) -> str:
    out, tab = [], "\t" * depth
    for key, value in data.items():
        name = str(key).replace("\\", "\\\\").replace('"', '\\"')
        if isinstance(value, dict):
            out.append(f'{tab}"{name}"\n{tab}{{\n{write_vdf(value, depth + 1)}{tab}}}\n')
        else:
            text = str(value).replace("\\", "\\\\").replace('"', '\\"')
            out.append(f'{tab}"{name}"\t\t"{text}"\n')
    return "".join(out)


def vget(data, *path):
    """Follow keys without minding their case (Steam writes "Software" in one file and "software" in the next)."""
    for want in path:
        if not isinstance(data, dict):
            return None
        hit = next((k for k in data if k.lower() == want.lower()), None)
        if hit is None:
            return None
        data = data[hit]
    return data


def steam_roots(home: Path = None) -> list:
    home = home or Path.home()
    seen, roots = set(), []
    for cand in (home / ".local/share/Steam", home / ".steam/steam", home / ".steam/root", home / ".steam/debian-installation",
                 home / ".var/app/com.valvesoftware.Steam/.local/share/Steam", home / "snap/steam/common/.local/share/Steam"):
        try:
            real = cand.resolve()
        except OSError:
            continue
        if real not in seen and (real / "steamapps").is_dir():
            seen.add(real)
            roots.append(real)
    return roots


def _read(path: Path, limit: int = 40_000_000) -> str:
    try:
        if path.stat().st_size > limit:
            return ""
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def steam_libraries(root: Path) -> list:
    libs = [root]
    folders = vget(read_vdf(_read(root / "steamapps/libraryfolders.vdf")), "libraryfolders") or {}
    for entry in folders.values():
        path = entry.get("path") if isinstance(entry, dict) else entry if isinstance(entry, str) else None
        if path and Path(path).is_dir() and Path(path).resolve() not in [p.resolve() for p in libs]:
            libs.append(Path(path))
    return libs


def steam_art(root: Path, appid: str, kind: str = "library_600x900") -> str:
    """Steam keeps each game's pictures on disk once it has shown them; use those, fetch nothing."""
    cache = root / "appcache/librarycache"
    for cand in (cache / f"{appid}_{kind}.jpg", cache / appid / f"{kind}.jpg"):
        if cand.is_file():
            return str(cand)
    try:
        for cand in sorted((cache / appid).rglob(f"{kind}*.jpg")):
            return str(cand)
    except OSError:
        pass
    return ""


def steam_games(root: Path) -> list:
    games = {}
    for lib in steam_libraries(root):
        try:
            manifests = sorted((lib / "steamapps").glob("appmanifest_*.acf"))
        except OSError:
            continue
        for manifest in manifests:
            state = vget(read_vdf(_read(manifest, 2_000_000)), "AppState") or {}
            appid, name = str(state.get("appid", "")), str(state.get("name", "")).strip()
            if not appid.isdigit() or not name or NOT_GAMES.match(name) or appid in games:
                continue
            folder = lib / "steamapps/common" / str(state.get("installdir", ""))
            try:
                flags = int(state.get("StateFlags", "4"))
            except ValueError:
                flags = 4
            games[appid] = {"id": "steam:" + appid, "appid": appid, "kind": "steam", "name": name, "folder": str(folder),
                            "size": _int(state.get("SizeOnDisk")), "last": _int(state.get("LastPlayed")), "ready": bool(flags & 4),
                            "cover": steam_art(root, appid), "hero": steam_art(root, appid, "library_hero") or steam_art(root, appid, "header")}
    return sorted(games.values(), key=lambda g: g["name"].lower())


def _int(value) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def steam_accounts(root: Path, names: dict = None) -> list:
    """Who has signed in to Steam on this computer, with what each has played here. `names` maps appid -> name."""
    users = vget(read_vdf(_read(root / "config/loginusers.vdf")), "users") or {}
    out = []
    for steamid, user in users.items():
        if not steamid.isdigit() or not isinstance(user, dict):
            continue
        played = account_playtime(root, steamid)
        minutes = sum(m for m, _ in played.values())
        top = max(played.items(), key=lambda kv: kv[1][0], default=None)
        avatar = root / "config/avatarcache" / f"{steamid}.png"
        out.append({"id": steamid, "login": str(vget(user, "AccountName") or ""), "name": str(vget(user, "PersonaName") or vget(user, "AccountName") or steamid),
                    "active": str(vget(user, "MostRecent") or "0") == "1", "remembered": str(vget(user, "RememberPassword") or "0") == "1",
                    "seen": _int(vget(user, "Timestamp")), "games": sum(1 for m, _ in played.values() if m > 0), "minutes": minutes,
                    "top": (names or {}).get(top[0], "") if top and top[1][0] > 0 else "", "avatar": str(avatar) if avatar.is_file() else ""})
    return sorted(out, key=lambda a: (not a["active"], -a["seen"]))


def account_playtime(root: Path, steamid: str) -> dict:
    """appid -> (minutes played, last played) for one account, from the notes Steam keeps for it on this computer."""
    try:
        folder = root / "userdata" / str(int(steamid) - ID_BASE) / "config/localconfig.vdf"
    except ValueError:
        return {}
    apps = vget(read_vdf(_read(folder)), "UserLocalConfigStore", "Software", "Valve", "Steam", "apps") or {}
    return {appid: (_int(vget(a, "Playtime")), _int(vget(a, "LastPlayed"))) for appid, a in apps.items() if isinstance(a, dict) and appid.isdigit()}


def switch_account(root: Path, steamid: str, home: Path = None) -> str:
    """Make `steamid` the account Steam signs in with next time it starts. Steam must be closed. Returns the
    account's login name. Only Steam's own "who was here last" notes change; passwords are never touched."""
    path = root / "config/loginusers.vdf"
    data = read_vdf(_read(path))
    users = vget(data, "users")
    if not isinstance(users, dict) or steamid not in users:
        raise ValueError("Steam doesn't know that account on this computer.")
    for sid, user in users.items():
        if isinstance(user, dict):
            _vset(user, "MostRecent", "1" if sid == steamid else "0")
            if sid == steamid:
                _vset(user, "AllowAutoLogin", "1")
    login = str(vget(users[steamid], "AccountName") or "")
    if not login:
        raise ValueError("That account has no login name saved.")
    backup = path.with_name("loginusers.vdf.before-huginn")
    if not backup.exists():
        shutil.copy2(path, backup)
    part = path.with_name(".loginusers.vdf.saving")
    part.write_text(write_vdf(data), encoding="utf-8")
    os.replace(part, path)
    for registry in ((home or Path.home()) / ".steam/registry.vdf", root.parent / "registry.vdf"):
        text = _read(registry, 5_000_000)
        if not text:
            continue
        safe = login.replace("\\", "\\\\").replace('"', '\\"')
        new, count = re.subn(r'("AutoLoginUser"\s+)"(?:[^"\\]|\\.)*"', lambda m: f'{m.group(1)}"{safe}"', text, count=1)
        if count and new != text:
            part = registry.with_name(".registry.vdf.saving")
            part.write_text(new, encoding="utf-8")
            os.replace(part, registry)
    return login


def _vset(block: dict, key: str, value: str) -> None:
    hit = next((k for k in block if k.lower() == key.lower()), key)
    block[hit] = value


def find_protons(roots: list) -> list:
    """Every Proton on this computer: the ones Steam installed, and ones dropped into compatibilitytools.d."""
    found = {}
    for root in roots:
        places = [lib / "steamapps/common" for lib in steam_libraries(root)] + [root / "compatibilitytools.d"]
        for place in places:
            try:
                folders = sorted(place.iterdir())
            except OSError:
                continue
            for folder in folders:
                if (folder / "proton").is_file() and re.search(r"proton", folder.name, re.I) and str(folder) not in found:
                    found[str(folder)] = {"id": "proton:" + str(folder), "name": folder.name.replace("_", " "), "path": str(folder), "rank": _version_rank(folder.name)}
    return sorted(found.values(), key=lambda p: p["rank"], reverse=True)


def _version_rank(name: str) -> tuple:
    numbers = tuple(int(n) for n in re.findall(r"\d+", name)[:3])
    special = 1 if re.search(r"experimental", name, re.I) else 0          # Experimental is newer than any numbered one
    return (0 if re.search(r"hotfix|beta", name, re.I) else 1, special, numbers)


# ============================================================================================== Heroic's files
# Heroic is one launcher for three shops. Inside it, Epic is "legendary", GOG is "gog" and Amazon is "nile".
SHOPS = {"epic": ("Epic", "legendary"), "gog": ("GOG", "gog"), "amazon": ("Amazon", "nile")}
LAUNCHED = ("steam",) + tuple(SHOPS)             # kinds another launcher starts and keeps the settings of


def heroic_homes(home: Path = None) -> list:
    home = home or Path.home()
    config = Path(os.environ.get("XDG_CONFIG_HOME") or home / ".config")
    out = []
    for p in (config / "heroic", home / ".config/heroic", home / ".var/app/com.heroicgameslauncher.hgl/config/heroic"):
        if p.is_dir() and p not in out:
            out.append(p)
    return out


def _json(path: Path):
    try:
        return json.loads(_read(path, 60_000_000) or "null")
    except ValueError:
        return None


def _bytes(value) -> int:
    """Heroic writes a size as a number in one file and as "12.4 GiB" in another."""
    if isinstance(value, (int, float)):
        return int(value)
    m = re.match(r"\s*([\d.]+)\s*([KMGT]?)i?B?\s*$", str(value or ""), re.I)
    try:
        return int(float(m.group(1)) * 1024 ** " KMGT".index(m.group(2).upper() or " ")) if m else 0
    except ValueError:
        return 0


def _stamp(value) -> int:
    """A time Heroic wrote (2026-11-13T18:20:00.000Z) as seconds since 1970; 0 if it can't be read."""
    try:
        return int(calendar.timegm(time.strptime(str(value)[:19], "%Y-%m-%dT%H:%M:%S")))
    except (ValueError, OverflowError):
        return 0


def heroic_games(cfg: Path) -> list:
    """What Heroic has installed from Epic, GOG and Amazon, with the names, covers and play time it keeps."""
    known = {}                                                    # (shop, app) -> the shop's own entry for it
    for shop, name, key in (("epic", "legendary_library.json", "library"), ("gog", "gog_library.json", "games"), ("amazon", "nile_library.json", "library")):
        data = _json(cfg / "store_cache" / name)
        for entry in (data.get(key) if isinstance(data, dict) else None) or []:
            if isinstance(entry, dict) and entry.get("app_name"):
                known[(shop, str(entry["app_name"]))] = entry
    played = _json(cfg / "store" / "timestamp.json")
    played = played if isinstance(played, dict) else {}
    found = []
    epic = _json(cfg / "legendaryConfig/legendary/installed.json")
    for app, e in (epic.items() if isinstance(epic, dict) else []):
        if isinstance(e, dict) and not e.get("is_dlc"):
            found.append(("epic", str(app), e.get("title"), e.get("install_path"), e.get("install_size")))
    gog = _json(cfg / "gog_store/installed.json")
    for e in (gog.get("installed") if isinstance(gog, dict) else None) or []:
        if isinstance(e, dict) and e.get("appName") and not e.get("is_dlc"):
            found.append(("gog", str(e["appName"]), None, e.get("install_path"), e.get("install_size")))
    amazon = _json(cfg / "nile_config/nile/installed.json")
    for e in (amazon if isinstance(amazon, list) else []):
        if isinstance(e, dict) and e.get("id"):
            found.append(("amazon", str(e["id"]), None, e.get("path"), e.get("size")))
    games = []
    for shop, app, title, folder, size in found:
        entry = known.get((shop, app), {})
        name = str(title or entry.get("title") or (Path(str(folder)).name if folder else "") or app).strip()
        times = played.get(app) if isinstance(played.get(app), dict) else {}
        games.append({"id": f"{shop}:{app}", "appid": app, "kind": shop, "name": name, "folder": str(folder or ""), "size": _bytes(size),
                      "last": _stamp(times.get("lastPlayed")), "minutes": _int(times.get("totalPlayed")), "ready": True,
                      "cover": heroic_art(cfg, entry.get("art_square") or entry.get("art_cover")), "hero": heroic_art(cfg, entry.get("art_cover") or entry.get("art_background"))})
    return sorted(games, key=lambda g: g["name"].lower())


def heroic_art(cfg: Path, url) -> str:
    """A picture Heroic has already saved on this computer (it names each by a fingerprint of its address).
    Nothing is fetched: a game Heroic hasn't shown yet simply has no cover here."""
    if not url or not isinstance(url, str):
        return ""
    cand = cfg / "images-cache" / hashlib.sha256(url.encode()).hexdigest()
    return str(cand) if cand.is_file() else ""


# ============================================================================================== starting a game
def parse_env(text: str) -> dict:
    """NAME=value lines (or separated by spaces, with quotes) -> {NAME: value}. Lines that aren't that are skipped."""
    out = {}
    for line in str(text or "").splitlines():
        try:
            parts = shlex.split(line, comments=True)
        except ValueError:
            continue
        for part in parts:
            name, eq, value = part.partition("=")
            if eq and ENV_NAME.match(name):
                out[name] = value
    return out


def split_args(text: str) -> list:
    try:
        return shlex.split(str(text or ""))
    except ValueError:
        return str(text or "").split()


def dll_overrides(dlls: dict, novideo: bool) -> str:
    parts = []
    for name, how in sorted((n.lower().removesuffix(".dll"), h) for n, h in (dlls or {}).items()):
        if DLL_NAME.match(name) and how in ("native", "builtin"):
            parts.append(f"{name}={'n,b' if how == 'native' else 'b'}")
    if novideo:
        parts.append("winegstreamer=d")
    return ";".join(parts)


def pick_runner(game: dict, protons: list, have: dict) -> dict:
    """What will actually run this game: {"kind": native|proton|wine|none, "name", "path"}."""
    want = game.get("runner") or "auto"
    windows = str(game.get("exe", "")).lower().endswith(WINDOWS)
    if want == "native" or (want == "auto" and not windows):
        return {"kind": "native", "name": "Runs directly", "path": ""}
    if want.startswith("proton:"):
        hit = next((p for p in protons if p["id"] == want), None)
        if hit:
            return {"kind": "proton", "name": hit["name"], "path": hit["path"]}
    if want == "wine" and have.get("wine"):
        return {"kind": "wine", "name": "Wine", "path": have["wine"]}
    if protons and want != "wine":
        return {"kind": "proton", "name": protons[0]["name"], "path": protons[0]["path"]}
    if have.get("wine"):
        return {"kind": "wine", "name": "Wine", "path": have["wine"]}
    return {"kind": "none", "name": "Nothing to run it with", "path": ""}


def build_launch(game: dict, protons: list, have: dict, steam_root: str = "") -> dict:
    """The command, the extra environment and the folder a game of yours starts with. Pure: runs nothing."""
    runner = pick_runner(game, protons, have)
    if runner["kind"] == "none":
        raise ValueError("This is a Windows game, and neither Proton (it comes with Steam) nor Wine is installed.")
    exe = str(game.get("exe", ""))
    env = {}
    wrap = []
    if game.get("gamemode") and have.get("gamemoderun"):
        wrap.append(have["gamemoderun"])
    if game.get("overlay") and have.get("mangohud"):
        wrap.append(have["mangohud"])
    sync = game.get("sync") or ""
    if runner["kind"] == "native":
        argv = wrap + [exe]
    else:
        prefix = str(game.get("prefix") or DATA_HOME / "games" / "bottles" / str(game.get("id", "game")))
        overrides = dll_overrides(game.get("dlls"), bool(game.get("novideo")))
        if overrides:
            env["WINEDLLOVERRIDES"] = overrides
        if game.get("lang"):
            env["LC_ALL"] = f"{game['lang']}.UTF-8"
        if runner["kind"] == "proton":
            if sync == "esync":
                env["PROTON_NO_FSYNC"] = "1"
            elif sync == "none":
                env["PROTON_NO_FSYNC"] = env["PROTON_NO_ESYNC"] = "1"
            if have.get("umu-run"):
                env.update({"WINEPREFIX": prefix, "GAMEID": "umu-default", "PROTONPATH": runner["path"]})
                argv = wrap + [have["umu-run"], exe]
            else:
                env.update({"STEAM_COMPAT_DATA_PATH": prefix, "STEAM_COMPAT_CLIENT_INSTALL_PATH": steam_root or str(Path.home() / ".steam/steam")})
                argv = wrap + [os.path.join(runner["path"], "proton"), "run", exe]
        else:
            env["WINEPREFIX"] = prefix
            if sync == "esync":
                env["WINEESYNC"] = "1"
            elif sync == "fsync":
                env["WINEFSYNC"] = "1"
            argv = wrap + [runner["path"], exe]
    env.update(parse_env(game.get("env")))                       # what you typed wins over what the switches set
    return {"argv": argv + split_args(game.get("args")), "env": env, "cwd": os.path.dirname(exe) or None, "runner": runner,
            "prefix": env.get("WINEPREFIX") or env.get("STEAM_COMPAT_DATA_PATH") or ""}


def steam_launch_options(profile: dict, have: dict = None) -> str:
    """The line to paste into a Steam game's Launch Options so Steam starts it with this profile."""
    have = have if have is not None else {"mangohud": "mangohud", "gamemoderun": "gamemoderun"}
    env = {}
    overrides = dll_overrides(profile.get("dlls"), bool(profile.get("novideo")))
    if overrides:
        env["WINEDLLOVERRIDES"] = overrides
    if profile.get("lang"):
        env["LC_ALL"] = f"{profile['lang']}.UTF-8"
    if profile.get("sync") == "esync":
        env["PROTON_NO_FSYNC"] = "1"
    elif profile.get("sync") == "none":
        env["PROTON_NO_FSYNC"] = env["PROTON_NO_ESYNC"] = "1"
    env.update(parse_env(profile.get("env")))
    words = [f"{k}={shlex.quote(v)}" for k, v in env.items()]
    if profile.get("gamemode") and have.get("gamemoderun"):
        words.append("gamemoderun")
    if profile.get("overlay") and have.get("mangohud"):
        words.append("mangohud")
    args = split_args(profile.get("args"))
    if not words and not args:
        return ""
    return " ".join(words + ["%command%"] + [shlex.quote(a) for a in args])


def hours_words(minutes: float) -> str:
    if minutes <= 0:
        return "Not played yet"
    if minutes < 60:
        return f"{int(minutes)} min"
    hours = minutes / 60
    return f"{hours:.1f} hours" if hours < 10 else f"{int(round(hours)):,} hours"


def ago_words(stamp: int, now: float = None) -> str:
    if not stamp:
        return ""
    days = int(((now or time.time()) - stamp) // 86400)
    if days <= 0:
        return "Today"
    if days == 1:
        return "Yesterday"
    if days < 14:
        return f"{days} days ago"
    if days < 70:
        return f"{days // 7} weeks ago"
    return time.strftime("%b %Y", time.localtime(stamp))


def size_words(size: int) -> str:
    if size <= 0:
        return ""
    return f"{size / 1e9:.1f} GB" if size >= 1e9 else f"{max(1, round(size / 1e6))} MB"


def game_name(path: str) -> str:
    """A name to start with for a game you add: its folder's name when the program is called game.exe or launcher.exe."""
    p = Path(path)
    stem = p.stem
    if stem.lower() in ("game", "launcher", "start", "play", "run", "setup", "bin", "main") or len(stem) < 3:
        parent = p.parent.name if p.parent.name.lower() not in ("bin", "binaries", "win64", "win32", "x64", "x86") else p.parent.parent.name
        stem = parent or stem
    words = re.sub(r"([a-z])([A-Z])", r"\1 \2", re.sub(r"[_\-.]+", " ", stem)).split()
    return " ".join(words)[:80] or "Game"


# ============================================================================================== the app
class Games(QObject):
    changed = Signal()
    said = Signal(str, bool)
    _back = Signal(object)
    TOOLS = ("steam", "heroic", "wine", "mangohud", "gamemoderun", "umu-run", "flatpak")

    def __init__(self, demo: bool = False, target=None):
        super().__init__()
        self._back.connect(lambda fn: fn())
        self._demo, self._file = demo, DATA_HOME / "games.json"
        self._own, self._profiles, self._steam, self._accounts, self._protons, self._heroic, self._hhomes = [], {}, [], [], [], [], []
        self._roots, self._have, self._picked, self._filter, self._query, self._busy = [], {}, "", "all", "", ""
        self._running, self._listing, self._folder = {}, [], str(Path.home())
        if demo:
            self._demo_fill()
            return
        self._load()
        self.refresh()
        self._watch = QTimer(self)
        self._watch.setInterval(2000)
        self._watch.timeout.connect(self._tick)
        self._watch.start()
        if target and Path(str(target)).is_file():
            QTimer.singleShot(0, lambda: self.addGame(str(target)))

    # ---- what's kept
    def _load(self) -> None:
        try:
            data = json.loads(self._file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        if not isinstance(data, dict):
            data = {}
        self._own = [g for g in data.get("games", []) if isinstance(g, dict) and g.get("id") and g.get("exe")]
        self._profiles = {k: v for k, v in (data.get("steam") or {}).items() if isinstance(v, dict)}

    def _keep(self) -> None:
        if self._demo:
            return
        try:
            self._file.parent.mkdir(parents=True, exist_ok=True)
            part = self._file.with_name(".games.json.saving")
            part.write_text(json.dumps({"games": self._own, "steam": self._profiles}, indent=1), encoding="utf-8")
            os.replace(part, self._file)
        except OSError as err:
            self.said.emit(f"Couldn't save your games: {err.strerror or err}", True)

    def _demo_fill(self) -> None:
        now = time.time()
        names = [("Hollow Fjord", 3120, 0, 9.4e9), ("Ironwake", 845, 2, 61e9), ("Starlane Drifters", 96, 5, 3.1e9), ("Thornfield Tactics", 2210, 9, 18e9),
                 ("Lanternfall", 0, 0, 1.2e9), ("Ember & Ash", 410, 30, 24e9), ("Glacier Run", 55, 44, 800e6)]
        self._steam = [{"id": f"steam:{1000 + i}", "appid": str(1000 + i), "kind": "steam", "name": n, "folder": "", "size": int(s), "last": int(now - d * 86400) if m else 0,
                        "ready": True, "cover": "", "hero": "", "minutes": m} for i, (n, m, d, s) in enumerate(names)]
        self._own = [dict(DEFAULTS, id="own1", name="Skyward Atelier", exe="/home/you/Games/Skyward Atelier/Atelier.exe", played=5400 * 60, last=int(now - 86400), added=int(now), overlay=True,
                          dlls={"dinput8": "native"}, lang="ja_JP"),
                     dict(DEFAULTS, id="own2", name="Pixel Harbor", exe="/home/you/Games/pixel-harbor/harbor.x86_64", played=320 * 60, last=int(now - 12 * 86400), added=int(now))]
        self._accounts = [{"id": "1", "login": "ravenkeeper", "name": "Ravenkeeper", "active": True, "remembered": True, "seen": int(now), "games": 6, "minutes": 6736, "top": "Hollow Fjord", "avatar": ""},
                          {"id": "2", "login": "muninn_alt", "name": "Muninn", "active": False, "remembered": True, "seen": int(now - 9 * 86400), "games": 3, "minutes": 1290, "top": "Ironwake", "avatar": ""}]
        self._protons = [{"id": "proton:/p/exp", "name": "Proton - Experimental", "path": "/p/exp", "rank": ()}, {"id": "proton:/p/9", "name": "Proton 9.0", "path": "/p/9", "rank": ()}]
        self._have = {"steam": "steam", "heroic": "heroic", "wine": "wine", "mangohud": "mangohud", "gamemoderun": "gamemoderun"}
        self._heroic = [{"id": f"{k}:d{i}", "appid": f"d{i}", "kind": k, "name": n, "folder": "", "size": int(s), "last": int(now - d * 86400), "minutes": m, "ready": True, "cover": "", "hero": ""}
                        for i, (k, n, m, d, s) in enumerate([("epic", "Cinder Circuit", 1480, 1, 44e9), ("epic", "Marrow Deep", 210, 20, 7e9), ("gog", "Old Kings' Road", 2890, 3, 12e9),
                                                             ("gog", "Tinker's Almanac", 35, 60, 600e6), ("amazon", "Saltwind", 120, 8, 5e9)])]
        self._hhomes = [Path("/demo")]
        self._roots = [Path("/demo")]
        self._picked = "own1"
        self._running = {}

    def bg(self, work, then=None) -> None:
        def go():
            try:
                result = work()
            except Exception as err:
                result = err
            if then:
                self._back.emit(lambda: then(result))
        threading.Thread(target=go, daemon=True).start()

    # ---- looking around
    @Slot()
    def refresh(self) -> None:
        if self._demo:
            return

        def look():
            roots = steam_roots()
            have = {tool: shutil.which(tool) or "" for tool in self.TOOLS}
            games, accounts = [], []
            for root in roots[:1]:
                games = steam_games(root)
                accounts = steam_accounts(root, {g["appid"]: g["name"] for g in games})
                active = next((a for a in accounts if a["active"]), None)
                played = account_playtime(root, active["id"]) if active else {}
                for g in games:
                    g["minutes"], last = played.get(g["appid"], (0, 0))
                    g["last"] = max(g["last"], last)
            homes = heroic_homes()
            heroic, seen = [], set()
            for cfg in homes:
                for g in heroic_games(cfg):
                    if g["id"] not in seen:
                        seen.add(g["id"])
                        heroic.append(g)
            return roots, have, games, accounts, find_protons(roots), heroic, homes

        def done(result):
            if isinstance(result, Exception):
                self.said.emit(f"Couldn't read the launchers' files: {result}", True)
                return
            self._roots, self._have, self._steam, self._accounts, self._protons, self._heroic, self._hhomes = result
            if not self._find(self._picked):
                self._picked = ""
            self.changed.emit()
        self.bg(look, done)

    def _find(self, ident: str):
        return next((g for g in self._own + self._steam + self._heroic if g["id"] == ident), None)

    def _profile(self, game: dict) -> dict:
        if game.get("kind") == "steam":
            return dict(DEFAULTS, **self._profiles.get(game["appid"], {}))
        if game.get("kind") in SHOPS:
            return dict(DEFAULTS)
        return dict(DEFAULTS, **{k: game[k] for k in DEFAULTS if k in game})

    def _face(self, g: dict) -> dict:
        kind = g.get("kind") if g.get("kind") in LAUNCHED else "own"
        steam = kind != "own"                                     # "someone else starts it": Steam, or Heroic for the three shops
        minutes = g.get("minutes", 0) if steam else g.get("played", 0) / 60
        runner = None if steam else pick_runner(g, self._protons, self._have)
        return {"id": g["id"], "kind": kind, "shop": {"steam": "Steam", "own": "Yours"}.get(kind) or SHOPS[kind][0], "via": "" if kind == "own" else "Steam" if kind == "steam" else "Heroic", "name": g["name"], "cover": _url(g.get("cover", "")), "hero": _url(g.get("hero", "")),
                "hours": hours_words(minutes), "minutes": minutes, "last": ago_words(g.get("last", 0)), "stamp": g.get("last", 0), "size": size_words(g.get("size", 0)),
                "ready": g.get("ready", True) if steam else (self._demo or os.path.isfile(g["exe"])), "running": g["id"] in self._running,
                "where": g.get("folder", "") if steam else g["exe"], "runnerName": ("Steam" if kind == "steam" else "Heroic") if steam else runner["name"], "canRun": steam or runner["kind"] != "none",
                "windows": (not steam) and str(g["exe"]).lower().endswith(WINDOWS)}

    def _all(self) -> list:
        faces = [self._face(g) for g in self._own + self._steam + self._heroic]
        return sorted(faces, key=lambda f: (-f["stamp"], f["name"].lower()))

    def _get_games(self) -> list:
        words = self._query.lower().split()
        out = []
        for f in self._all():
            if self._filter == "running" and not f["running"] or self._filter not in ("all", "running") and f["kind"] != self._filter:
                continue
            if all(w in f["name"].lower() for w in words):
                out.append(f)
        return out

    def _get_current(self) -> dict:
        g = self._find(self._picked)
        if not g:
            return {}
        face = self._face(g)
        profile = self._profile(g)
        face.update(profile)
        face["dllList"] = [{"name": k, "how": v} for k, v in sorted((profile.get("dlls") or {}).items())]
        face["line"] = steam_launch_options(profile, self._have) if face["kind"] == "steam" else ""
        face["prefix"] = "" if face["kind"] != "own" else str(g.get("prefix") or DATA_HOME / "games" / "bottles" / g["id"])
        return face

    def _get_featured(self) -> dict:
        faces = self._all()
        running = [f for f in faces if f["running"]]
        return (running or faces or [{}])[0]

    def _get_accounts(self) -> list:
        return [dict(a, hours=hours_words(a["minutes"]), avatar=_url(a["avatar"]), seenWords=ago_words(a["seen"])) for a in self._accounts]

    def _get_runners(self) -> list:
        out = [{"id": "auto", "name": "Automatic"}] + [{"id": p["id"], "name": p["name"]} for p in self._protons]
        if self._have.get("wine"):
            out.append({"id": "wine", "name": "Wine"})
        return out + [{"id": "native", "name": "Run directly (a Linux game)"}]

    def _get_summary(self) -> dict:
        faces = self._all()
        minutes = sum(f["minutes"] for f in faces)
        count = lambda kind: sum(1 for g in self._heroic if g["kind"] == kind)
        return {"games": len(faces), "steam": len(self._steam), "epic": count("epic"), "gog": count("gog"), "amazon": count("amazon"), "own": len(self._own),
                "hours": hours_words(minutes) if minutes else "0 hours", "running": len(self._running)}

    def _get_shelves(self) -> list:
        """The rail: every place games come from, with how many are here. A shop with none still shows, greyed."""
        s = self._get_summary()
        return [{"id": "all", "name": "Everything", "count": s["games"], "ink": ""}, {"id": "steam", "name": "Steam", "count": s["steam"], "ink": "#66C0F4"},
                {"id": "epic", "name": "Epic", "count": s["epic"], "ink": "#C9CDD4"}, {"id": "gog", "name": "GOG", "count": s["gog"], "ink": "#B46BFF"},
                {"id": "amazon", "name": "Amazon", "count": s["amazon"], "ink": "#FF9F1C"}, {"id": "own", "name": "Yours", "count": s["own"], "ink": "#4ADE80"}]

    games = Property("QVariantList", _get_games, notify=changed)
    current = Property("QVariantMap", _get_current, notify=changed)
    featured = Property("QVariantMap", _get_featured, notify=changed)
    accounts = Property("QVariantList", _get_accounts, notify=changed)
    runners = Property("QVariantList", _get_runners, notify=changed)
    summary = Property("QVariantMap", _get_summary, notify=changed)
    shelves = Property("QVariantList", _get_shelves, notify=changed)
    heroicFound = Property(bool, lambda self: bool(self._hhomes), notify=changed)
    heroicInstalled = Property(bool, lambda self: bool(self._hhomes) or bool(self._have.get("heroic")), notify=changed)
    picked = Property(str, lambda self: self._picked, notify=changed)
    filter = Property(str, lambda self: self._filter, notify=changed)
    busy = Property(str, lambda self: self._busy, notify=changed)
    steamFound = Property(bool, lambda self: bool(self._roots), notify=changed)
    steamInstalled = Property(bool, lambda self: bool(self._roots) or bool(self._have.get("steam")), notify=changed)
    tools = Property("QVariantMap", lambda self: {"mangohud": bool(self._have.get("mangohud")), "gamemode": bool(self._have.get("gamemoderun")), "wine": bool(self._have.get("wine")),
                                                  "proton": len(self._protons), "umu": bool(self._have.get("umu-run"))}, notify=changed)
    syncs = Property("QVariantList", lambda self: [{"id": k, "name": v} for k, v in SYNC.items()], constant=True)
    langs = Property("QVariantList", lambda self: [{"id": k, "name": v} for k, v in LANGS], constant=True)
    listing = Property("QVariantList", lambda self: self._listing, notify=changed)
    folder = Property(str, lambda self: self._folder, notify=changed)

    @Slot(str)
    def choose(self, ident: str) -> None:
        self._picked = ident if self._find(ident) else ""
        self.changed.emit()

    @Slot(str)
    def setFilter(self, name: str) -> None:
        self._filter = name if name in ("all", "steam", "epic", "gog", "amazon", "own", "running") else "all"
        self.changed.emit()

    @Slot(str)
    def search(self, text: str) -> None:
        self._query = text
        self.changed.emit()

    # ---- your own games
    @Slot(str)
    def browse(self, path: str) -> None:
        """Folders, and files that could be a game, in `path` (for the Add a Game sheet)."""
        folder = Path(path or Path.home()).expanduser()
        if not folder.is_dir():
            folder = Path.home()
        rows = []
        try:
            entries = sorted(folder.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
        except OSError:
            entries = []
        for entry in entries:
            if entry.name.startswith("."):
                continue
            try:
                if entry.is_dir():
                    rows.append({"name": entry.name, "path": str(entry), "dir": True})
                elif entry.suffix.lower() in WINDOWS[:1] or entry.suffix.lower() in (".appimage", ".x86_64", ".sh") or (entry.suffix == "" and os.access(entry, os.X_OK)):
                    rows.append({"name": entry.name, "path": str(entry), "dir": False})
            except OSError:
                continue
            if len(rows) >= 400:
                break
        self._folder, self._listing = str(folder), rows
        self.changed.emit()

    @Slot()
    def browseUp(self) -> None:
        self.browse(str(Path(self._folder).parent))

    @Slot(str)
    def addGame(self, path: str) -> None:
        path = QUrl(path).toLocalFile() if path.startswith("file:") else path
        if self._demo:
            return
        if not os.path.isfile(path):
            self.said.emit("That isn't a file.", True)
            return
        path = os.path.abspath(path)
        if any(g["exe"] == path for g in self._own):
            self._picked = next(g["id"] for g in self._own if g["exe"] == path)
            self.said.emit("That game is already here.", False)
            self.changed.emit()
            return
        game = dict(DEFAULTS, id=uuid.uuid4().hex[:12], name=game_name(path), exe=path, played=0, last=0, added=int(time.time()), dlls={})
        self._own.append(game)
        self._picked = game["id"]
        self._keep()
        self.changed.emit()
        runner = pick_runner(game, self._protons, self._have)
        self.said.emit(f"Added {game['name']}." if runner["kind"] != "none" else f"Added {game['name']}. It's a Windows game: it needs Steam (for Proton) or Wine to run.", runner["kind"] == "none")

    @Slot(str)
    def removeGame(self, ident: str) -> None:
        """Takes one of your own games off the shelf. Its files, saves and bottle stay where they are."""
        if ident in self._running:
            self.said.emit("Stop the game first.", True)
            return
        before = len(self._own)
        self._own = [g for g in self._own if g["id"] != ident]
        if len(self._own) != before:
            if self._picked == ident:
                self._picked = ""
            self._keep()
            self.changed.emit()

    @Slot(str, str)
    def rename(self, ident: str, name: str) -> None:
        g = self._find(ident)
        name = " ".join(name.split())[:80]
        if g and g.get("kind") not in LAUNCHED and name:
            g["name"] = name
            self._keep()
            self.changed.emit()

    @Slot(str, str, "QVariant")
    def setOption(self, ident: str, key: str, value) -> None:
        g = self._find(ident)
        if not g or key not in DEFAULTS or key == "dlls" or g.get("kind") in SHOPS:
            return
        if isinstance(DEFAULTS[key], bool):
            value = bool(value)
        else:
            value = str(value)[:4000]
            if key == "sync" and value not in SYNC or key == "lang" and value not in dict(LANGS):
                return
            if key == "runner" and value not in [r["id"] for r in self._get_runners()]:
                return
        self._store(g)[key] = value
        self._keep()
        self.changed.emit()

    def _store(self, g: dict) -> dict:
        return self._profiles.setdefault(g["appid"], {}) if g.get("kind") == "steam" else g

    @Slot(str, str, str)
    def setDll(self, ident: str, name: str, how: str) -> None:
        """how: native (the game's own copy first), builtin (Wine's), or "" to forget the preference."""
        g = self._find(ident)
        name = name.strip().lower().removesuffix(".dll")
        if g and g.get("kind") in SHOPS:
            return
        if not g or not DLL_NAME.match(name):
            if g:
                self.said.emit("A DLL's name is letters, digits, dots and dashes, like dinput8.", True)
            return
        store = self._store(g)
        dlls = dict(store.get("dlls") or {})
        if how in ("native", "builtin"):
            dlls[name] = how
        else:
            dlls.pop(name, None)
        store["dlls"] = dlls
        self._keep()
        self.changed.emit()

    # ---- playing
    @Slot(str)
    def play(self, ident: str) -> None:
        g = self._find(ident)
        if not g or self._demo:
            return
        if ident in self._running:
            self.said.emit(f"{g['name']} is already running.", False)
            return
        if g.get("kind") == "steam":
            if self._steam_do(f"steam://rungameid/{g['appid']}"):
                self.said.emit(f"Asked Steam to start {g['name']}.", False)
            return
        if g.get("kind") in SHOPS:
            if self._heroic_do("--no-gui", f"heroic://launch/{SHOPS[g['kind']][1]}/{g['appid']}"):
                self.said.emit(f"Asked Heroic to start {g['name']}.", False)
            return
        if not os.path.isfile(g["exe"]):
            self.said.emit("The game's file isn't there any more. Was it moved, or on a drive that isn't plugged in?", True)
            return
        try:
            plan = build_launch(g, self._protons, self._have, str(self._roots[0]) if self._roots else "")
            if plan["prefix"]:
                os.makedirs(plan["prefix"], exist_ok=True)
            logs = DATA_HOME / "games" / "logs"
            logs.mkdir(parents=True, exist_ok=True)
            if plan["runner"]["kind"] == "native" and not os.access(g["exe"], os.X_OK):
                os.chmod(g["exe"], os.stat(g["exe"]).st_mode | 0o100)             # a downloaded Linux game often isn't marked runnable
            with open(logs / f"{g['id']}.log", "wb") as log:
                proc = subprocess.Popen(plan["argv"], cwd=plan["cwd"], env=dict(os.environ, **plan["env"]), stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        except (OSError, ValueError) as err:
            self.said.emit(f"Couldn't start {g['name']}: {getattr(err, 'strerror', None) or err}", True)
            return
        self._running[ident] = {"proc": proc, "since": time.time()}
        g["last"] = int(time.time())
        self._keep()
        self.changed.emit()

    def _tick(self) -> None:
        ended = [ident for ident, run in self._running.items() if run["proc"].poll() is not None]
        for ident in ended:
            run = self._running.pop(ident)
            g = self._find(ident)
            took = time.time() - run["since"]
            if g:
                g["played"] = g.get("played", 0) + int(took)
                g["last"] = int(time.time())
                if run["proc"].returncode not in (0, None) and took < 8 and not run.get("stopped"):
                    self.said.emit(f"{g['name']} stopped straight away. Its log is in {DATA_HOME / 'games' / 'logs'}; another compatibility layer in its profile may help.", True)
        if ended:
            self._keep()
            self.changed.emit()

    @Slot(str)
    def stop(self, ident: str) -> None:
        run = self._running.get(ident)
        if not run:
            return
        run["stopped"] = True
        try:
            os.killpg(run["proc"].pid, signal.SIGTERM)
        except (OSError, ProcessLookupError):
            pass
        QTimer.singleShot(5000, lambda: self._force(ident, run))

    def _force(self, ident: str, run: dict) -> None:
        if self._running.get(ident) is run and run["proc"].poll() is None:
            try:
                os.killpg(run["proc"].pid, signal.SIGKILL)
            except (OSError, ProcessLookupError):
                pass

    def leaving(self) -> None:
        """The window is closing. Games keep running; note the time played so far so it isn't lost."""
        for ident, run in self._running.items():
            g = self._find(ident)
            if g:
                g["played"] = g.get("played", 0) + int(time.time() - run["since"])
        if self._running:
            self._keep()

    # ---- Steam itself
    def _steam_cmd(self) -> list:
        if self._have.get("steam"):
            return [self._have["steam"]]
        if self._have.get("flatpak") and any("com.valvesoftware.Steam" in str(r) for r in self._roots):
            return [self._have["flatpak"], "run", "com.valvesoftware.Steam"]
        return []

    def _steam_do(self, *words) -> bool:
        cmd = self._steam_cmd()
        if not cmd:
            self.said.emit("Steam isn't installed. Get it from the App Store.", True)
            return False
        try:
            subprocess.Popen(cmd + list(words), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
            return True
        except OSError as err:
            self.said.emit(f"Couldn't start Steam: {err.strerror or err}", True)
            return False

    @Slot()
    def openSteam(self) -> None:
        self._steam_do()

    def _heroic_do(self, *words) -> bool:
        if self._have.get("heroic"):
            cmd = [self._have["heroic"]]
        elif self._have.get("flatpak") and any("com.heroicgameslauncher.hgl" in str(h) for h in self._hhomes):
            cmd = [self._have["flatpak"], "run", "com.heroicgameslauncher.hgl"]
        else:
            self.said.emit("Heroic isn't installed. Get it from the App Store.", True)
            return False
        try:
            subprocess.Popen(cmd + list(words), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
            return True
        except OSError as err:
            self.said.emit(f"Couldn't start Heroic: {err.strerror or err}", True)
            return False

    @Slot()
    def openHeroic(self) -> None:
        self._heroic_do()

    @Slot()
    def getHeroic(self) -> None:
        self._open_app("store", "heroic")

    @Slot(str)
    def steamProperties(self, ident: str) -> None:
        g = self._find(ident)
        if g and g.get("kind") == "steam":
            self._steam_do(f"steam://gameproperties/{g['appid']}")

    @Slot()
    def getSteam(self) -> None:
        self._open_app("store", "steam")

    def _open_app(self, *words) -> None:
        import sys
        try:
            subprocess.Popen([sys.executable, str(HERE / "huginn_app.py"), *words], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        except OSError as err:
            self.said.emit(f"Couldn't open it: {err.strerror or err}", True)

    @Slot(str)
    def showFolder(self, ident: str) -> None:
        g = self._find(ident)
        if not g:
            return
        folder = g.get("folder") if g.get("kind") in LAUNCHED else os.path.dirname(g["exe"])
        if folder and os.path.isdir(folder):
            self._open_app("files", folder)
        else:
            self.said.emit("That folder isn't there.", True)

    @Slot(str)
    def copyLine(self, ident: str) -> None:
        from PySide6.QtGui import QGuiApplication
        line = self._get_current().get("line", "") if ident == self._picked else ""
        if line:
            QGuiApplication.clipboard().setText(line)
            self.said.emit("Copied. Paste it into the game's Launch Options in Steam.", False)

    @Slot(str)
    def switchAccount(self, steamid: str) -> None:
        """Close Steam, tell it which account was last here, and start it again. If Steam doesn't remember that
        account's password it asks for it in its own window; this app never sees it."""
        account = next((a for a in self._accounts if a["id"] == steamid), None)
        if self._demo or not account or not self._roots or self._busy:
            return
        if account["active"]:
            self.said.emit(f"Steam is already set to {account['name']}.", False)
            return
        if not self._steam_cmd():
            self.said.emit("Steam isn't installed.", True)
            return
        root, cmd = self._roots[0], self._steam_cmd()
        self._busy = "switching"
        self.changed.emit()

        def work():
            if steam_running():
                subprocess.run(cmd + ["-shutdown"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20)
                for _ in range(40):
                    if not steam_running():
                        break
                    time.sleep(0.5)
                else:
                    raise RuntimeError("Steam didn't close. Close it yourself and try again.")
            return switch_account(root, steamid)

        def done(result):
            self._busy = ""
            if isinstance(result, Exception):
                self.said.emit(str(result) if isinstance(result, (ValueError, RuntimeError)) else f"Couldn't switch: {result}", True)
                self.changed.emit()
                return
            self._steam_do()
            self.said.emit(f"Steam is starting as {account['name']}." + ("" if account["remembered"] else " It may ask for the password."), False)
            self.refresh()
        self.bg(work, done)


def steam_running() -> bool:
    try:
        return subprocess.run(["pgrep", "-x", "steam"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _url(path: str) -> str:
    return QUrl.fromLocalFile(path).toString() if path else ""
