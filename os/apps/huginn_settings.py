"""Huginn Settings: the system's own settings.

Each page talks to the tool the system already uses for that job, so a change made here is the same change any other
tool would make, and a change made elsewhere shows up here:

    Wi-Fi & Network      NetworkManager (nmcli)              Bluetooth          BlueZ (bluetoothctl)
    Displays             KWin through kscreen-doctor          Night light        KWin's own setting (kwinrc)
    Sound                PipeWire through pactl               Battery & Power    UPower, power-profiles-daemon, Huginn's session daemon
    Keyboard & Mouse     KWin's input devices (D-Bus), kcminputrc, kxkbrc
    Date & Time          systemd's timedated (timedatectl)    Language           plasma-localerc (your account)
    Users                AccountsService (D-Bus)              Default Apps       mimeapps.list, ~/.config/autostart
    Privacy & Security   ufw, Flatpak's permission store, kscreenlockerrc, ktrashrc, recently-used files
    Notifications        ~/.config/huginn-shell/notifications.json, which the shell reads

Nothing here asks for the administrator password itself. Where the system guards a change (the firewall, the time
zone, other people's accounts) the system asks for it in its own window (polkit), never this app.
With --demo, or where a tool is missing, a page shows sample values or says what's missing.
"""
import json
import os
import pty
import re
import select
import shutil
import signal
import subprocess
import threading
import time
from pathlib import Path

from PySide6.QtCore import Property, QDateTime, QLocale, QObject, Signal, Slot

HOME = Path.home()
CONFIG = Path(os.environ.get("XDG_CONFIG_HOME") or HOME / ".config")
DATA = Path(os.environ.get("XDG_DATA_HOME") or HOME / ".local/share")
CACHE = Path(os.environ.get("XDG_CACHE_HOME") or HOME / ".cache")
ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]|\x1b[()][AB012]|[\x01\x02]")


# ---------------------------------------------------------------------------------------------- running the tools
def run(argv: list, stdin: str = None, timeout: float = 25) -> tuple:
    """(exit code, output, errors) of a tool. A tool that isn't installed gives 127, one that hangs 124."""
    try:
        done = subprocess.run(argv, input=stdin, capture_output=True, text=True, timeout=timeout,
                              env={**os.environ, "LC_ALL": "C.UTF-8", "LANG": "C.UTF-8"})
        return done.returncode, done.stdout, done.stderr
    except FileNotFoundError:
        return 127, "", f"{argv[0]} isn't installed"
    except subprocess.TimeoutExpired:
        return 124, "", f"{argv[0]} took too long to answer"
    except OSError as err:
        return 126, "", str(err)


RUN = run                       # tests put a stand-in here
HAVE = shutil.which


class Failed(Exception):
    """A change the system refused; the text is fit to show."""


def must(argv: list, stdin: str = None, timeout: float = 40, what: str = "") -> bool:
    """Run a tool that changes something: True, or Failed with words fit to show."""
    code, out, err = RUN(argv, stdin, timeout)
    if code != 0:
        text = (ANSI.sub("", err or out).strip().splitlines() or [""])[-1]
        if code == 127:
            raise Failed(f"{argv[0]} isn't installed, so this can't be changed here.")
        if "not authorized" in text.lower() or "authentication" in text.lower() and "fail" in text.lower() or code == 126 and argv[0] == "pkexec":
            raise Failed("The system said no: the administrator password wasn't given.")
        raise Failed(f"{what or 'That'} didn't work: {text[:180] or 'no reason given'}")
    return True


# ---------------------------------------------------------------------------------------------- KDE-style config files
def _group_header(groups) -> str:
    return "".join(f"[{g}]" for g in groups)


def kconfig_read(path: Path, groups, key: str, default: str = "") -> str:
    """One value from an INI file in KDE's style, where nested groups are written [A][B]."""
    want, inside = _group_header(groups), False
    try:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            s = line.strip()
            if s.startswith("["):
                inside = s == want
            elif inside and "=" in s:
                k, _, v = s.partition("=")
                if k.strip() == key:
                    return v.strip()
    except OSError:
        pass
    return default


def kconfig_write(path: Path, groups, key: str, value) -> None:
    """Change (or add) one value, leaving everything else in the file as it was. Uses kwriteconfig6 when the system
    has it, because it also tells KDE's programs (KWin, PowerDevil) that the file changed, so they act on it at once."""
    value = "true" if value is True else "false" if value is False else str(value)
    if HAVE("kwriteconfig6"):
        argv = ["kwriteconfig6", "--file", str(path)]
        for g in groups:
            argv += ["--group", g]
        code, _, _ = RUN(argv + ["--key", key, "--notify", value], None, 10)
        if code == 0:
            return
    want = _group_header(groups)
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        lines = []
    start = next((i for i, line in enumerate(lines) if line.strip() == want), -1)
    if start < 0:
        if lines and lines[-1].strip():
            lines.append("")
        lines += [want, f"{key}={value}"]
    else:
        end = next((i for i in range(start + 1, len(lines)) if lines[i].strip().startswith("[")), len(lines))
        hit = next((i for i in range(start + 1, end) if "=" in lines[i] and lines[i].split("=", 1)[0].strip() == key), -1)
        if hit >= 0:
            lines[hit] = f"{key}={value}"
        else:
            at = end
            while at > start + 1 and not lines[at - 1].strip():
                at -= 1
            lines.insert(at, f"{key}={value}")
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_name(f".{path.name}.saving")
    part.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.replace(part, path)


def dbus_call(bus: str, dest: str, path: str, method: str, *args) -> None:
    """A fire-and-forget D-Bus call (telling a program to read its settings again). Never fails loudly."""
    RUN(["dbus-send", f"--{bus}", "--type=method_call", f"--dest={dest}", path, method, *args], None, 5)


def busctl(bus: str, *args, timeout: float = 15, interactive: bool = False):
    """Run busctl and give back its --json=short answers (one per line); None when it failed."""
    argv = ["busctl", f"--{bus}", "--json=short"] + (["--allow-interactive-authorization=yes", "--timeout=120"] if interactive else []) + list(args)
    code, out, err = RUN(argv, None, 130 if interactive else timeout)
    if code != 0:
        busctl.last = ANSI.sub("", err).strip()
        return None
    rows = []
    for line in out.splitlines():
        try:
            rows.append(json.loads(line))
        except ValueError:
            pass
    return rows


busctl.last = ""


def plain(variant):
    """{"type": "s", "data": x} as busctl writes a D-Bus value → x (also inside dicts)."""
    if isinstance(variant, dict) and set(variant) == {"type", "data"}:
        return plain(variant["data"])
    if isinstance(variant, dict):
        return {k: plain(v) for k, v in variant.items()}
    return variant


# ---------------------------------------------------------------------------------------------- network (nmcli)
def terse(line: str) -> list:
    """Split one line of `nmcli -t` output on its colons (a colon inside a value comes as \\:)."""
    out, cur, esc = [], [], False
    for ch in line:
        if esc:
            cur.append(ch)
            esc = False
        elif ch == "\\":
            esc = True
        elif ch == ":":
            out.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    out.append("".join(cur))
    return out


def parse_wifi(text: str) -> list:
    """`nmcli -t -f IN-USE,SSID,SIGNAL,SECURITY,CHAN dev wifi list` → one entry per name, strongest first."""
    best = {}
    for line in text.splitlines():
        f = terse(line)
        if len(f) < 4 or not f[1].strip():
            continue                                     # a hidden network has no name to show
        sig = int(f[2]) if f[2].strip().isdigit() else 0
        sec = "" if f[3].strip() in ("", "--") else f[3].strip()
        item = {"ssid": f[1], "signal": sig, "secure": bool(sec), "security": sec, "inUse": f[0].strip() == "*",
                "band": ("5 GHz" if len(f) > 4 and f[4].isdigit() and int(f[4]) > 14 else "2.4 GHz") if len(f) > 4 and f[4].isdigit() else ""}
        old = best.get(f[1])
        if old is None:
            best[f[1]] = item
        else:
            old["inUse"] = old["inUse"] or item["inUse"]
            if sig > old["signal"]:
                old.update({k: v for k, v in item.items() if k != "inUse"})
    for w in best.values():
        w["bars"] = 1 + (w["signal"] >= 30) + (w["signal"] >= 55) + (w["signal"] >= 75)
    return sorted(best.values(), key=lambda w: (not w["inUse"], -w["signal"], w["ssid"].lower()))


def parse_devices(text: str) -> list:
    out = []
    for line in text.splitlines():
        f = terse(line)
        if len(f) >= 4 and f[1] in ("wifi", "ethernet", "gsm", "bt"):
            out.append({"device": f[0], "type": f[1], "state": f[2].split(" ")[0], "connection": f[3]})
    return out


def parse_connections(text: str) -> list:
    out = []
    for line in text.splitlines():
        f = terse(line)
        if len(f) >= 5:
            kind = {"802-11-wireless": "wifi", "802-3-ethernet": "ethernet", "vpn": "vpn", "wireguard": "vpn"}.get(f[2], f[2])
            out.append({"name": f[0], "uuid": f[1], "type": kind, "device": f[3], "active": f[4] == "yes", "wireguard": f[2] == "wireguard"})
    return out


def parse_details(text: str) -> dict:
    d = {"mac": "", "ip": "", "gateway": "", "dns": [], "ip6": ""}
    for line in text.splitlines():
        key, _, value = line.partition(":")
        value = value.replace("\\:", ":")
        if key == "GENERAL.HWADDR":
            d["mac"] = value
        elif key.startswith("IP4.ADDRESS") and not d["ip"]:
            d["ip"] = value.split("/")[0]
        elif key == "IP4.GATEWAY":
            d["gateway"] = value
        elif key.startswith("IP4.DNS") and value:
            d["dns"].append(value)
        elif key.startswith("IP6.ADDRESS") and not d["ip6"] and not value.startswith("fe80"):
            d["ip6"] = value.split("/")[0]
    d["dns"] = ", ".join(d["dns"])
    return d


def load_network() -> dict:
    if not HAVE("nmcli"):
        return {"available": False}
    _, radio, _ = RUN(["nmcli", "-t", "radio", "wifi"])
    _, devs, _ = RUN(["nmcli", "-t", "-f", "DEVICE,TYPE,STATE,CONNECTION", "device"])
    _, cons, _ = RUN(["nmcli", "-t", "-f", "NAME,UUID,TYPE,DEVICE,ACTIVE", "connection", "show"])
    devices, connections = parse_devices(devs), parse_connections(cons)
    wifi_on = radio.strip() == "enabled"
    networks = []
    if wifi_on and any(d["type"] == "wifi" for d in devices):
        _, scan, _ = RUN(["nmcli", "-t", "-f", "IN-USE,SSID,SIGNAL,SECURITY,CHAN", "device", "wifi", "list", "--rescan", "auto"], None, 30)
        networks = parse_wifi(scan)
    saved = {c["name"] for c in connections if c["type"] == "wifi"}
    for w in networks:
        w["saved"] = w["ssid"] in saved
    wifi_dev = next((d for d in devices if d["type"] == "wifi"), None)
    wired = next((d for d in devices if d["type"] == "ethernet"), None)
    details = {}
    for d in (wifi_dev, wired):
        if d and d["state"] == "connected":
            _, info, _ = RUN(["nmcli", "-t", "-f", "GENERAL.HWADDR,IP4.ADDRESS,IP4.GATEWAY,IP4.DNS,IP6.ADDRESS", "device", "show", d["device"]])
            details[d["device"]] = parse_details(info)
    code, rf, _ = RUN(["rfkill", "-J"])
    airplane = False
    if code == 0:
        try:
            blocks = [x for x in json.loads(rf).get("rfkilldevices", []) if x.get("type") in ("wlan", "bluetooth")]
            airplane = bool(blocks) and all(x.get("soft") == "blocked" for x in blocks)
        except (ValueError, AttributeError):
            pass
    hotspot = next((c for c in connections if c["name"] == "Huginn Hotspot" and c["active"]), None)
    return {"available": True, "wifiOn": wifi_on, "airplane": airplane, "hasWifi": wifi_dev is not None, "wifiDevice": (wifi_dev or {}).get("device", ""),
            "current": (wifi_dev or {}).get("connection", "") if (wifi_dev or {}).get("state") == "connected" else "",
            "networks": networks, "wired": wired, "details": details, "hotspot": hotspot is not None,
            "vpns": [c for c in connections if c["type"] == "vpn"], "saved": [c for c in connections if c["type"] == "wifi"]}


# ---------------------------------------------------------------------------------------------- bluetooth (bluetoothctl)
BT_KIND = {"audio-headset": "headphones", "audio-headphones": "headphones", "audio-card": "speaker", "input-keyboard": "keyboard",
           "input-mouse": "mouse", "input-gaming": "gamepad", "input-tablet": "pen", "phone": "phone", "computer": "computer"}


def _yes(text: str, key: str) -> bool:
    m = re.search(rf"^\s*{key}:\s*(\w+)", text, re.M)
    return bool(m) and m.group(1) == "yes"


def parse_bt_show(text: str) -> dict:
    text = ANSI.sub("", text)
    name = re.search(r"^\s*Alias:\s*(.+)$", text, re.M) or re.search(r"^\s*Name:\s*(.+)$", text, re.M)
    return {"present": "Controller" in text, "powered": _yes(text, "Powered"), "discoverable": _yes(text, "Discoverable"),
            "name": name.group(1).strip() if name else ""}


def parse_bt_devices(text: str) -> list:
    out = []
    for line in ANSI.sub("", text).splitlines():
        m = re.match(r"^\s*Device\s+([0-9A-F]{2}(?::[0-9A-F]{2}){5})\s+(.*)$", line.strip(), re.I)
        if m:
            out.append((m.group(1).upper(), m.group(2).strip()))
    return out


def parse_bt_info(text: str) -> dict:
    text = ANSI.sub("", text)
    icon = re.search(r"^\s*Icon:\s*(\S+)", text, re.M)
    battery = re.search(r"Battery Percentage:\s*0x[0-9a-f]+\s*\((\d+)\)", text, re.I)
    name = re.search(r"^\s*Alias:\s*(.+)$", text, re.M) or re.search(r"^\s*Name:\s*(.+)$", text, re.M)
    return {"name": name.group(1).strip() if name else "", "kind": BT_KIND.get(icon.group(1) if icon else "", "device"),
            "paired": _yes(text, "Paired"), "trusted": _yes(text, "Trusted"), "connected": _yes(text, "Connected"),
            "battery": int(battery.group(1)) if battery else -1}


def load_bluetooth(scan: bool = False) -> dict:
    if not HAVE("bluetoothctl"):
        return {"available": False}
    _, show, _ = RUN(["bluetoothctl", "show"])
    state = parse_bt_show(show)
    state["available"] = True
    devices = []
    if state["present"] and state["powered"]:
        if scan:
            RUN(["bluetoothctl", "--timeout", "10", "scan", "on"], None, 20)
        _, listing, _ = RUN(["bluetoothctl", "devices"])
        for mac, name in parse_bt_devices(listing):
            _, info, _ = RUN(["bluetoothctl", "info", mac])
            d = parse_bt_info(info)
            d.update({"mac": mac, "name": d["name"] or name})
            if d["paired"] or scan or d["connected"]:
                devices.append(d)
    state["devices"] = sorted(devices, key=lambda d: (not d["connected"], not d["paired"], d["name"].lower()))
    return state


# ---------------------------------------------------------------------------------------------- displays (kscreen-doctor)
ROTATIONS = {1: "normal", 2: "left", 4: "inverted", 8: "right"}


def parse_screens(text: str) -> list:
    try:
        data = json.loads(text)
    except ValueError:
        return []
    out = []
    for o in data.get("outputs", []):
        if not o.get("connected"):
            continue
        modes = []
        for m in o.get("modes", []):
            size = m.get("size") or {}
            modes.append({"id": str(m.get("id")), "w": int(size.get("width", 0)), "h": int(size.get("height", 0)), "hz": round(float(m.get("refreshRate", 0)), 2)})
        cur = next((m for m in modes if m["id"] == str(o.get("currentModeId"))), modes[0] if modes else {"id": "", "w": 0, "h": 0, "hz": 0})
        sizes = sorted({(m["w"], m["h"]) for m in modes}, key=lambda s: (-s[0] * s[1], -s[0]))
        rates = sorted({m["hz"] for m in modes if (m["w"], m["h"]) == (cur["w"], cur["h"])}, reverse=True)
        name = o.get("name", "")
        rot = ROTATIONS.get(int(o.get("rotation", 1) or 1), "normal")
        pos = o.get("pos") or {}
        out.append({"name": name, "builtIn": name.startswith(("eDP", "LVDS", "DSI")), "enabled": bool(o.get("enabled")),
                    "primary": int(o.get("priority", 0) or 0) == 1 or bool(o.get("primary")), "scale": float(o.get("scale", 1) or 1),
                    "rotation": rot, "x": int(pos.get("x", 0)), "y": int(pos.get("y", 0)), "w": cur["w"], "h": cur["h"], "hz": cur["hz"],
                    "modeId": cur["id"], "resolution": f"{cur['w']}x{cur['h']}",
                    "resolutions": [{"id": f"{w}x{h}", "label": f"{w} × {h}"} for w, h in sizes],
                    "rates": [{"id": str(r), "label": f"{r:g} Hz"} for r in rates], "modes": modes,
                    "label": "Built-in screen" if name.startswith(("eDP", "LVDS", "DSI")) else name.replace("-", " ")})
    return out


def best_mode(modes: list, w: int, h: int, hz: float = None) -> str:
    fit = [m for m in modes if m["w"] == w and m["h"] == h]
    if not fit:
        return ""
    if hz is not None:
        fit.sort(key=lambda m: abs(m["hz"] - hz))
        return fit[0]["id"]
    return max(fit, key=lambda m: m["hz"])["id"]


def load_displays() -> dict:
    kwinrc = CONFIG / "kwinrc"
    night = {"on": kconfig_read(kwinrc, ["NightColor"], "Active", "false") == "true",
             "mode": kconfig_read(kwinrc, ["NightColor"], "Mode", "Automatic"),
             "temp": int(kconfig_read(kwinrc, ["NightColor"], "NightTemperature", "4500") or 4500),
             "from": _hhmm(kconfig_read(kwinrc, ["NightColor"], "EveningBeginFixed", "2000")),
             "to": _hhmm(kconfig_read(kwinrc, ["NightColor"], "MorningBeginFixed", "0600"))}
    screens = []
    if HAVE("kscreen-doctor"):
        _, out, _ = RUN(["kscreen-doctor", "-j"])
        screens = parse_screens(out)
    brightness = -1
    if HAVE("brightnessctl"):
        code, out, _ = RUN(["brightnessctl", "-m", "-c", "backlight"])
        if code == 0 and out.count(",") >= 4:
            try:
                brightness = int(out.split(",")[3].rstrip("%"))
            except ValueError:
                pass
    return {"available": HAVE("kscreen-doctor") is not None, "screens": screens, "night": night, "brightness": brightness}


def _hhmm(text: str) -> str:
    text = re.sub(r"\D", "", text).zfill(4)[:4]
    return f"{text[:2]}:{text[2:]}"


# ---------------------------------------------------------------------------------------------- sound (pactl)
def _percent(volume: dict) -> int:
    vals = []
    for ch in (volume or {}).values():
        try:
            vals.append(int(str(ch.get("value_percent", "0")).rstrip("%")))
        except (ValueError, AttributeError):
            pass
    return round(sum(vals) / len(vals)) if vals else 0


def parse_endpoints(text: str, default: str, monitors: bool = False) -> list:
    try:
        items = json.loads(text or "[]")
    except ValueError:
        return []
    out = []
    for s in items:
        name = s.get("name", "")
        if not monitors and (name.endswith(".monitor") or (s.get("properties") or {}).get("device.class") == "monitor"):
            continue
        port = next((p.get("description", "") for p in s.get("ports", []) if p.get("name") == s.get("active_port")), "")
        out.append({"name": name, "label": s.get("description") or name, "port": port, "volume": _percent(s.get("volume")),
                    "mute": bool(s.get("mute")), "default": name == default})
    return sorted(out, key=lambda e: (not e["default"], e["label"].lower()))


def parse_streams(text: str) -> list:
    try:
        items = json.loads(text or "[]")
    except ValueError:
        return []
    out = []
    for s in items:
        props = s.get("properties") or {}
        app = props.get("application.name") or props.get("application.process.binary") or "Something"
        if props.get("media.role") == "event" or not s.get("has_volume", True):
            continue
        out.append({"index": int(s.get("index", -1)), "app": app, "icon": props.get("application.icon_name", ""),
                    "what": props.get("media.name", ""), "volume": _percent(s.get("volume")), "mute": bool(s.get("mute"))})
    return out


def load_sound() -> dict:
    if not HAVE("pactl"):
        return {"available": False}
    _, dsink, _ = RUN(["pactl", "get-default-sink"])
    _, dsource, _ = RUN(["pactl", "get-default-source"])
    _, sinks, _ = RUN(["pactl", "-f", "json", "list", "sinks"])
    _, sources, _ = RUN(["pactl", "-f", "json", "list", "sources"])
    _, streams, _ = RUN(["pactl", "-f", "json", "list", "sink-inputs"])
    return {"available": True, "outputs": parse_endpoints(sinks, dsink.strip()), "inputs": parse_endpoints(sources, dsource.strip()),
            "apps": parse_streams(streams)}


# ---------------------------------------------------------------------------------------------- battery and power
def parse_upower(text: str) -> dict:
    def get(key):
        m = re.search(rf"^\s*{re.escape(key)}:\s*(.+)$", text, re.M)
        return m.group(1).strip() if m else ""
    def num(key):
        m = re.match(r"[\d.]+", get(key))
        return float(m.group(0)) if m else 0.0
    left = get("time to empty") or get("time to full")
    full, design = num("energy-full"), num("energy-full-design")
    return {"percent": round(num("percentage")), "state": get("state") or "unknown", "timeLeft": left,
            "charging": get("state") in ("charging", "fully-charged", "pending-charge"),
            "health": round(100 * full / design) if full and design else round(num("capacity")) if get("capacity") else -1,
            "cycles": int(num("charge-cycles")) if get("charge-cycles") and get("charge-cycles") != "N/A" else -1,
            "rate": num("energy-rate"), "model": get("model")}


def parse_profiles(text: str) -> tuple:
    current, names = "", []
    for line in text.splitlines():
        m = re.match(r"^(\*?)\s*([a-z][a-z-]*):\s*$", line)
        if m:
            names.append(m.group(2))
            if m.group(1):
                current = m.group(2)
    return current, names


POWER_GROUPS = {"ac": "AC", "battery": "Battery"}


def load_power(shell_settings=None) -> dict:
    out = {"battery": None, "profile": "", "profiles": []}
    if HAVE("upower"):
        _, paths, _ = RUN(["upower", "-e"])
        for path in paths.split():
            if "battery_" in path:
                _, info, _ = RUN(["upower", "-i", path])
                if re.search(r"power supply:\s*yes", info):
                    out["battery"] = parse_upower(info)
                    break
    if HAVE("powerprofilesctl"):
        _, text, _ = RUN(["powerprofilesctl", "list"])
        out["profile"], out["profiles"] = parse_profiles(text)
    rules = power_rules()
    out["idle"] = {key: {"screenOff": int(rules[key].get("screenOff") or 0), "sleep": int(rules[key].get("sleep") or 0)} for key in POWER_GROUPS}
    out["lid"], out["button"] = str(rules.get("lid", "1")), str(rules.get("button", "16"))
    return out


# Battery & Power is carried out by Huginn's session daemon (huginn_sessiond.py), which reads this file and notices
# when it changes. The actions keep PowerDevil's numbers (1 sleep, 2 hibernate, 8 shut down, 16 ask, 32 lock, 64 screen off).
POWER_FILE = CONFIG / "huginn" / "power.json"
POWER_DEFAULTS = {"ac": {"screenOff": 600, "sleep": 900}, "battery": {"screenOff": 300, "sleep": 600}, "lid": "1", "button": "16"}


def power_rules() -> dict:
    out = json.loads(json.dumps(POWER_DEFAULTS))
    try:
        saved = json.loads(POWER_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        saved = {}
    for k, v in saved.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k].update(v)
        else:
            out[k] = v
    return out


def save_power(change) -> None:
    rules = power_rules()
    change(rules)
    POWER_FILE.parent.mkdir(parents=True, exist_ok=True)
    POWER_FILE.write_text(json.dumps(rules, indent=2), encoding="utf-8")
    dbus_call("session", "org.huginn.Session", "/org/huginn/Session", "org.huginn.Session.Reload")


# ---------------------------------------------------------------------------------------------- keyboard and pointing devices
POINTER_PROPS = ("name", "touchpad", "pointer", "keyboard", "tapToClick", "naturalScroll", "pointerAcceleration", "leftHanded",
                 "disableWhileTyping", "supportsDisableWhileTyping", "tapFingerCount", "scrollFactor")


def kwin_pointers() -> list:
    rows = busctl("user", "get-property", "org.kde.KWin", "/org/kde/KWin/InputDevice", "org.kde.KWin.InputDeviceManager", "devicesSysNames")
    if not rows:
        return []
    out = []
    for sysname in plain(rows[0]) or []:
        got = busctl("user", "call", "org.kde.KWin", f"/org/kde/KWin/InputDevice/{sysname}", "org.freedesktop.DBus.Properties", "GetAll", "s", "org.kde.KWin.InputDevice")
        if not got:
            continue
        props = plain(got[0])
        props = props[0] if isinstance(props, list) and props else props
        if not isinstance(props, dict) or not (props.get("pointer") or props.get("touchpad")) or props.get("keyboard") and not props.get("touchpad"):
            continue
        out.append({"sys": sysname, "name": props.get("name", sysname), "touchpad": bool(props.get("touchpad")),
                    "tap": bool(props.get("tapToClick")), "natural": bool(props.get("naturalScroll")), "left": bool(props.get("leftHanded")),
                    "speed": float(props.get("pointerAcceleration", 0.0)), "dwt": bool(props.get("disableWhileTyping")),
                    "canDwt": bool(props.get("supportsDisableWhileTyping")), "canTap": int(props.get("tapFingerCount", 0) or 0) > 0})
    return sorted(out, key=lambda p: (not p["touchpad"], p["name"].lower()))


def xkb_layouts(path: Path = Path("/usr/share/X11/xkb/rules/evdev.lst")) -> list:
    out, inside = [], False
    try:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("!"):
                inside = line.strip() == "! layout"
                continue
            if inside and line.strip():
                code, _, label = line.strip().partition(" ")
                out.append({"id": code, "label": label.strip()})
    except OSError:
        out = [{"id": c, "label": n} for c, n in (("us", "English (US)"), ("gb", "English (UK)"), ("de", "German"), ("fr", "French"),
                                                 ("es", "Spanish"), ("it", "Italian"), ("se", "Swedish"), ("no", "Norwegian"),
                                                 ("dk", "Danish"), ("nl", "Dutch"), ("pt", "Portuguese"), ("ru", "Russian"), ("jp", "Japanese"))]
    return sorted(out, key=lambda l: l["label"].lower())


CAPS = [("", "Caps Lock"), ("caps:ctrl_modifier", "Another Control key"), ("caps:escape", "Escape"), ("caps:none", "Nothing")]


def load_input() -> dict:
    rc, xkb = CONFIG / "kcminputrc", CONFIG / "kxkbrc"
    options = [o for o in kconfig_read(xkb, ["Layout"], "Options", "").split(",") if o]
    layouts = [l for l in kconfig_read(xkb, ["Layout"], "LayoutList", "").split(",") if l] or ["us"]
    names = {l["id"]: l["label"] for l in xkb_layouts()}
    return {"pointers": kwin_pointers() if HAVE("busctl") else [], "repeat": kconfig_read(rc, ["Keyboard"], "KeyRepeat", "repeat") != "nothing",
            "delay": int(kconfig_read(rc, ["Keyboard"], "RepeatDelay", "600") or 600), "rate": float(kconfig_read(rc, ["Keyboard"], "RepeatRate", "25") or 25),
            "layouts": [{"id": l, "label": names.get(l, l)} for l in layouts],
            "caps": next((o for o in options if o.startswith("caps:")), ""), "compose": "compose:ralt" in options,
            "capsChoices": [{"id": i, "label": n} for i, n in CAPS]}


# ---------------------------------------------------------------------------------------------- accessibility
OSK_FILES = ("/usr/share/applications/org.kde.plasma.keyboard.desktop", "/usr/share/applications/com.github.maliit.keyboard.desktop")
FILTERS = [("", "None"), ("0", "Red weak (protanopia)"), ("1", "Green weak (deuteranopia)"), ("2", "Blue weak (tritanopia)"), ("invert", "Inverted colours")]


def osk_desktop() -> str:
    return next((f for f in OSK_FILES if os.path.isfile(f)), "")


def load_a11y() -> dict:
    """What KDE's own accessibility settings say (kaccessrc, kwinrc, kcminputrc, kdeglobals): KWin and KAccess act
    on these, so the screen reader, zoom, colour filters and keyboard helps work everywhere, not only in Huginn's apps."""
    acc, kwin, inp, glob = CONFIG / "kaccessrc", CONFIG / "kwinrc", CONFIG / "kcminputrc", CONFIG / "kdeglobals"

    def yes(path, groups, key, default="false"):
        return kconfig_read(path, groups, key, default) == "true"

    def num(path, groups, key, default):
        try:
            return float(kconfig_read(path, groups, key, str(default)) or default)
        except ValueError:
            return float(default)
    cb = yes(kwin, ["Plugins"], "colorblindnesscorrectionEnabled")
    return {"reader": yes(acc, ["ScreenReader"], "Enabled"), "hasReader": bool(HAVE("orca")),
            "zoom": yes(kwin, ["Plugins"], "zoomEnabled", "true"), "zoomStep": num(kwin, ["Effect-zoom"], "ZoomFactor", 1.2),
            "zoomFollow": kconfig_read(kwin, ["Effect-zoom"], "MouseTracking", "0") or "0",
            "filter": "invert" if yes(acc, ["Huginn"], "Invert") else (kconfig_read(kwin, ["Effect-colorblindnesscorrection"], "Mode", "0") or "0") if cb else "",
            "filterStrength": num(kwin, ["Effect-colorblindnesscorrection"], "Intensity", 1.0),
            "filters": [{"id": i, "label": l} for i, l in FILTERS],
            "cursor": int(num(inp, ["Mouse"], "cursorSize", 24)),
            "sticky": yes(acc, ["Keyboard"], "StickyKeys"), "stickyLock": yes(acc, ["Keyboard"], "StickyKeysLatch", "true"),
            "slow": yes(acc, ["Keyboard"], "SlowKeys"), "slowDelay": int(num(acc, ["Keyboard"], "SlowKeysDelay", 300)),
            "bounce": yes(acc, ["Keyboard"], "BounceKeys"), "bounceDelay": int(num(acc, ["Keyboard"], "BounceKeysDelay", 500)),
            "mouseKeys": yes(acc, ["Mouse"], "MouseKeys"), "flash": yes(acc, ["Bell"], "VisibleBell"),
            "osk": kconfig_read(kwin, ["Wayland"], "InputMethod", "") != "", "hasOsk": bool(osk_desktop()),
            "animations": num(glob, ["KDE"], "AnimationDurationFactor", 1.0) > 0.01}


def kwin_effect(name: str, on: bool) -> None:
    dbus_call("session", "org.kde.KWin", "/Effects", "org.kde.kwin.Effects." + ("loadEffect" if on else "unloadEffect"), f"string:{name}")


def kwin_reconfigure_effect(name: str) -> None:
    dbus_call("session", "org.kde.KWin", "/Effects", "org.kde.kwin.Effects.reconfigureEffect", f"string:{name}")


# ---------------------------------------------------------------------------------------------- date, time, language
def parse_kv(text: str) -> dict:
    return dict(line.split("=", 1) for line in text.splitlines() if "=" in line)


def zones() -> list:
    try:
        import zoneinfo
        names = sorted(z for z in zoneinfo.available_timezones() if "/" in z and not z.startswith(("Etc/", "SystemV/", "US/", "posix/", "right/")))
    except Exception:                                            # noqa: BLE001  (no tz data at all)
        names = ["UTC"]
    return names


def zone_label(zone: str) -> str:
    city = zone.rsplit("/", 1)[-1].replace("_", " ")
    region = zone.split("/", 1)[0].replace("_", " ")
    return f"{city} ({region})"


def load_time(shell_settings=None) -> dict:
    info = {}
    if HAVE("timedatectl"):
        _, out, _ = RUN(["timedatectl", "show"])
        info = parse_kv(out)
    zone = info.get("Timezone") or _local_zone()
    return {"zone": zone, "zoneLabel": zone_label(zone), "ntp": info.get("NTP", "yes") == "yes", "synced": info.get("NTPSynchronized", "no") == "yes",
            "canNtp": info.get("CanNTP", "yes") == "yes", "available": bool(info)}


def _local_zone() -> str:
    try:
        return os.path.realpath("/etc/localtime").split("zoneinfo/", 1)[1]
    except (IndexError, OSError):
        return "UTC"


LANGUAGES = ["en_US", "en_GB", "en_CA", "en_AU", "de_DE", "fr_FR", "fr_CA", "es_ES", "es_MX", "it_IT", "pt_BR", "pt_PT", "nl_NL",
             "sv_SE", "nb_NO", "da_DK", "fi_FI", "is_IS", "pl_PL", "cs_CZ", "uk_UA", "ru_RU", "tr_TR", "el_GR", "ar_SA", "he_IL",
             "hi_IN", "ja_JP", "ko_KR", "zh_CN", "zh_TW", "id_ID", "vi_VN", "th_TH"]


def locale_label(code: str) -> str:
    q = QLocale(code)
    lang = q.nativeLanguageName() or code
    region = q.nativeTerritoryName() if hasattr(q, "nativeTerritoryName") else q.nativeCountryName()
    return f"{lang[:1].upper()}{lang[1:]} ({region})" if region else lang


def format_preview(code: str) -> dict:
    q = QLocale(code)
    now = QDateTime.currentDateTime()
    return {"date": q.toString(now.date(), QLocale.FormatType.LongFormat), "short": q.toString(now.date(), QLocale.FormatType.ShortFormat),
            "time": q.toString(now.time(), QLocale.FormatType.ShortFormat), "number": q.toString(1234567.89, "f", 2),
            "money": q.toCurrencyString(1234.5), "week": ["", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"][int(q.firstDayOfWeek().value if hasattr(q.firstDayOfWeek(), "value") else q.firstDayOfWeek())]}


def load_language() -> dict:
    rc = CONFIG / "plasma-localerc"
    env = (os.environ.get("LANG") or "en_US.UTF-8").split(".")[0]
    lang = kconfig_read(rc, ["Translations"], "LANGUAGE", "").split(":")[0] or env
    if "_" not in lang:
        lang = next((c for c in LANGUAGES if c.startswith(lang + "_")), lang)
    formats = kconfig_read(rc, ["Formats"], "LANG", "").split(".")[0] or env
    installed = set()
    code, out, _ = RUN(["locale", "-a"])
    if code == 0:
        installed = {l.split(".")[0] for l in out.split()}
    choices = sorted(({"id": c, "label": locale_label(c), "installed": c in installed} for c in set(LANGUAGES) | {lang, formats}), key=lambda c: c["label"].lower())
    return {"language": lang, "languageLabel": locale_label(lang), "formats": formats, "formatsLabel": locale_label(formats),
            "preview": format_preview(formats), "choices": choices}


# ---------------------------------------------------------------------------------------------- people (AccountsService)
ACCOUNTS = "org.freedesktop.Accounts"


def account_props(path: str) -> dict:
    got = busctl("system", "call", ACCOUNTS, path, "org.freedesktop.DBus.Properties", "GetAll", "s", "org.freedesktop.Accounts.User")
    if not got:
        return {}
    props = plain(got[0])
    props = props[0] if isinstance(props, list) and props else props
    if not isinstance(props, dict):
        return {}
    icon = props.get("IconFile", "")
    return {"path": path, "uid": int(props.get("Uid", 0)), "name": props.get("UserName", ""), "full": props.get("RealName", "") or props.get("UserName", ""),
            "admin": int(props.get("AccountType", 0)) == 1, "picture": f"file://{icon}" if icon and os.path.isfile(icon) else "",
            "locked": bool(props.get("Locked")), "system": bool(props.get("SystemAccount"))}


def load_users() -> dict:
    if not HAVE("busctl"):
        return {"available": False, "me": {"name": os.environ.get("USER", ""), "full": os.environ.get("USER", ""), "admin": False, "picture": ""}, "others": []}
    rows = busctl("system", "call", ACCOUNTS, "/org/freedesktop/Accounts", ACCOUNTS, "ListCachedUsers")
    paths = (plain(rows[0]) or [[]])[0] if rows else []
    people = [p for p in (account_props(path) for path in paths) if p and not p["system"]]
    me_uid = os.getuid()
    me = next((p for p in people if p["uid"] == me_uid), None)
    if me is None:
        found = busctl("system", "call", ACCOUNTS, "/org/freedesktop/Accounts", ACCOUNTS, "FindUserById", "x", str(me_uid))
        me = account_props((plain(found[0]) or [""])[0]) if found else {}
    return {"available": rows is not None, "me": me or {"name": os.environ.get("USER", ""), "full": "", "admin": False, "picture": ""},
            "others": [p for p in people if p["uid"] != me_uid]}


def change_password(old: str, new: str, timeout: float = 25) -> str:
    """Change this account's password with the system's own `passwd`, answering its questions on a pseudo-terminal
    (it only talks to a terminal). Returns "" when it worked, otherwise what passwd said."""
    pid, fd = pty.fork()
    if pid == 0:                                                 # the child: become passwd, in plain English
        try:
            os.execvpe("passwd", ["passwd"], {**os.environ, "LC_ALL": "C", "LANG": "C"})
        finally:
            os._exit(127)
    said, answers, sent, until = "", [old, new, new], 0, time.monotonic() + timeout
    try:
        while time.monotonic() < until:
            ready, _, _ = select.select([fd], [], [], 0.3)
            if not ready:
                continue
            try:
                chunk = os.read(fd, 4096).decode("utf-8", "replace")
            except OSError:
                break
            if not chunk:
                break
            said += chunk
            tail = said.rsplit("\n", 1)[-1].lower()
            if "bad password" in said.lower() or "password unchanged" in said.lower() or "authentication token manipulation" in said.lower():
                break
            if tail.rstrip().endswith(":") and "password" in tail and sent < len(answers):
                if sent == 0 and "new" in tail:                  # some systems don't ask for the old one
                    answers = [new, new]
                os.write(fd, (answers[sent] + "\n").encode("utf-8"))
                sent += 1
    finally:
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass
        try:
            _, status = os.waitpid(pid, 0)
        except ChildProcessError:
            status = 1
        os.close(fd)
    if "successfully" in said.lower():
        return ""
    for line in said.splitlines():
        low = line.lower()
        if "bad password" in low:
            return "That password is too easy to guess: " + line.split(":", 1)[-1].strip()
        if "authentication" in low and ("failure" in low or "manipulation" in low):
            return "The current password isn't right."
    return "The password wasn't changed." + (" passwd isn't installed." if os.WEXITSTATUS(status) == 127 else "")


AVATAR_COLOURS = [("#FF7A59", "#C2185B"), ("#5B8CFF", "#3A1FB8"), ("#27C281", "#0E7A5A"), ("#FFB547", "#E8590C"),
                  ("#B26BFF", "#5B2BB8"), ("#3CC8E8", "#1565C0"), ("#FF6FA8", "#8E24AA"), ("#9AA4B2", "#3C4554")]


def make_avatars(initials: str, folder: Path = None) -> list:
    """A set of pictures to choose from: the person's initials on each of Huginn's gradients (drawn here, so nothing
    is fetched from anywhere)."""
    from PySide6.QtGui import QColor, QFont, QImage, QLinearGradient, QPainter
    from PySide6.QtCore import Qt
    folder = folder or CACHE / "huginn" / "avatars"
    folder.mkdir(parents=True, exist_ok=True)
    out = []
    for i, (a, b) in enumerate(AVATAR_COLOURS):
        path = folder / f"{re.sub(r'[^A-Za-z0-9]', '', initials) or 'me'}-{i}.png"
        if not path.exists():
            img = QImage(256, 256, QImage.Format.Format_ARGB32_Premultiplied)
            img.fill(QColor(a))
            p = QPainter(img)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            g = QLinearGradient(0, 0, 256, 256)
            g.setColorAt(0, QColor(a))
            g.setColorAt(1, QColor(b))
            p.fillRect(0, 0, 256, 256, g)
            f = QFont("Inter")
            f.setPixelSize(104)
            f.setWeight(QFont.Weight.DemiBold)
            p.setFont(f)
            p.setPen(QColor("#FFFFFF"))
            p.drawText(img.rect(), int(Qt.AlignmentFlag.AlignCenter), initials[:2].upper())
            p.end()
            img.save(str(path))
        out.append(str(path))
    return out


def initials_of(name: str) -> str:
    parts = [p for p in re.split(r"\s+", name.strip()) if p]
    return ("".join(p[0] for p in parts[:2]) or "?").upper()


# ---------------------------------------------------------------------------------------------- apps: defaults and start-up
CATEGORIES = [("browser", "Web browser", "globe", ["x-scheme-handler/http", "x-scheme-handler/https", "text/html", "application/xhtml+xml"]),
              ("mail", "Mail", "mail", ["x-scheme-handler/mailto"]),
              ("calendar", "Calendar", "calendar", ["text/calendar"]),
              ("photos", "Photos", "image", ["image/jpeg", "image/png", "image/gif", "image/webp", "image/heic", "image/tiff", "image/bmp"]),
              ("music", "Music", "music", ["audio/mpeg", "audio/flac", "audio/ogg", "audio/x-wav", "audio/mp4", "audio/x-opus+ogg"]),
              ("video", "Videos", "video", ["video/mp4", "video/x-matroska", "video/webm", "video/quicktime", "video/x-msvideo"]),
              ("pdf", "PDF documents", "doc", ["application/pdf"]),
              ("text", "Text and code", "code", ["text/plain", "text/markdown", "text/x-python", "application/json"]),
              ("folders", "Folders", "folder", ["inode/directory"]),
              ("terminal", "Terminal", "terminal", [])]


def app_dirs() -> list:
    dirs = [DATA / "applications", DATA / "flatpak/exports/share/applications", Path("/var/lib/flatpak/exports/share/applications")]
    for d in (os.environ.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share").split(":"):
        if d:
            dirs.append(Path(d) / "applications")
    return dirs


def read_desktop(path: Path) -> dict:
    out, inside = {}, False
    try:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            s = line.strip()
            if s.startswith("["):
                inside = s == "[Desktop Entry]"
            elif inside and "=" in s and not s.startswith("#"):
                k, _, v = s.partition("=")
                out.setdefault(k.strip(), v.strip())
    except OSError:
        pass
    return out


def all_apps(dirs: list = None) -> dict:
    """Every app the menus would show: {desktop id: {name, icon, mimes, terminal}} (the first place found wins)."""
    seen = {}
    for d in dirs or app_dirs():
        try:
            files = sorted(d.glob("*.desktop"))
        except OSError:
            continue
        for f in files:
            if f.name in seen:
                continue
            e = read_desktop(f)
            seen[f.name] = None if (e.get("Type", "Application") != "Application" or e.get("Hidden") == "true") else {
                "id": f.name, "name": e.get("Name", f.stem), "icon": e.get("Icon", ""), "path": str(f),
                "mimes": [m for m in e.get("MimeType", "").split(";") if m], "nodisplay": e.get("NoDisplay") == "true",
                "terminal": "TerminalEmulator" in e.get("Categories", "") or e.get("X-Huginn-Terminal") == "true"}
    return {k: v for k, v in seen.items() if v}


def icon_url(app: dict) -> str:
    icon = (app or {}).get("icon", "")
    if app and app["id"].startswith("huginn-"):
        try:
            from huginn_shell import own_icon
            own = own_icon(app["id"][len("huginn-"):-len(".desktop")])
            if own:
                return own
        except ImportError:
            pass
    if icon.startswith("/"):
        return "file://" + icon
    return "image://sysicon/" + icon if icon else ""


def mime_files() -> list:
    out = [CONFIG / "mimeapps.list"]
    out += [Path(d) / "mimeapps.list" for d in (os.environ.get("XDG_CONFIG_DIRS") or "/etc/xdg").split(":") if d]
    out += [d / "mimeapps.list" for d in app_dirs()]
    return out


def mime_default(mime: str, files: list = None) -> str:
    for f in files or mime_files():
        value = kconfig_read(f, ["Default Applications"], mime, "")
        if value:
            return value.split(";")[0]
    return ""


def load_defaults(apps: dict = None) -> dict:
    apps = apps if apps is not None else all_apps()
    rows = []
    for key, label, glyph, mimes in CATEGORIES:
        if key == "terminal":
            choices = [a for a in apps.values() if a["terminal"]]
            current = kconfig_read(CONFIG / "kdeglobals", ["General"], "TerminalService", "") or "huginn-terminal.desktop"
        else:
            choices = [a for a in apps.values() if any(m in a["mimes"] for m in mimes)]
            current = mime_default(mimes[0])
        if current and current in apps and apps[current] not in choices:
            choices.append(apps[current])
        choices.sort(key=lambda a: (not a["id"].startswith("huginn"), a["name"].lower()))
        rows.append({"id": key, "label": label, "glyph": glyph, "current": current,
                     "currentName": apps[current]["name"] if current in apps else "Not set",
                     "currentIcon": icon_url(apps.get(current)),
                     "choices": [{"id": a["id"], "name": a["name"], "icon": icon_url(a)} for a in choices]})
    autostart = CONFIG / "autostart"
    startup = []
    for f in sorted(autostart.glob("*.desktop")) if autostart.is_dir() else []:
        e = read_desktop(f)
        startup.append({"file": str(f), "name": e.get("Name", f.stem), "on": e.get("Hidden") != "true" and e.get("X-GNOME-Autostart-enabled", "true") != "false",
                        "icon": icon_url({"id": f.name, "icon": e.get("Icon", "")})})
    addable = [{"id": a["id"], "name": a["name"], "icon": icon_url(a)} for a in sorted(apps.values(), key=lambda a: a["name"].lower())
               if not a["nodisplay"] and not any(s["file"].endswith("/" + a["id"]) for s in startup)]
    return {"categories": rows, "startup": startup, "addable": addable}


def set_default(category: str, app_id: str) -> None:
    for key, _, _, mimes in CATEGORIES:
        if key != category:
            continue
        if key == "terminal":
            kconfig_write(CONFIG / "kdeglobals", ["General"], "TerminalService", app_id)
            kconfig_write(CONFIG / "kdeglobals", ["General"], "TerminalApplication", app_id[:-len(".desktop")])
            return
        for m in mimes:
            kconfig_write(CONFIG / "mimeapps.list", ["Default Applications"], m, app_id + ";")
        if key == "browser":
            kconfig_write(CONFIG / "kdeglobals", ["General"], "BrowserApplication", app_id)
        return
    raise Failed("There's no such kind of file.")


# ---------------------------------------------------------------------------------------------- privacy and security
PERMISSION_NAMES = {("devices", "camera"): "Camera", ("devices", "microphone"): "Microphone", ("devices", "speakers"): "Speakers",
                    ("location", "location"): "Location", ("screenshot", "screenshot"): "Screenshots", ("background", "background"): "Running in the background",
                    ("notifications", "notification"): "Notifications", ("inhibit", "inhibit"): "Keeping the screen awake"}


def parse_permissions(text: str, apps: dict = None) -> list:
    out = []
    names = {k[:-len(".desktop")]: v["name"] for k, v in (apps or {}).items()}
    for line in text.splitlines():
        f = line.split()
        if len(f) < 4 or f[0] == "Table" or (f[0], f[1]) not in PERMISSION_NAMES:
            continue
        perm = f[3].lower()
        out.append({"table": f[0], "object": f[1], "app": f[2], "appName": names.get(f[2], f[2].rsplit(".", 1)[-1]),
                    "what": PERMISSION_NAMES[(f[0], f[1])], "allow": perm not in ("no", "none", "0")})
    return sorted(out, key=lambda p: (p["what"], p["appName"].lower()))


def load_privacy(apps: dict = None) -> dict:
    perms = []
    if HAVE("flatpak"):
        code, out, _ = RUN(["flatpak", "permissions"])
        if code == 0:
            perms = parse_permissions(out, apps if apps is not None else all_apps())
    ufw = _plain_kv(Path("/etc/ufw/ufw.conf")).get("ENABLED", "")
    lock = CONFIG / "kscreenlockerrc"
    trash = CONFIG / "ktrashrc"
    group = [str(DATA / "Trash")]
    remember = kconfig_read(CONFIG / "kactivitymanagerd-pluginsrc", ["Plugin-org.kde.ActivityManager.Resources.Scoring"], "what-to-remember", "0")
    return {"firewall": ufw.lower() == "yes", "hasFirewall": bool(ufw), "permissions": perms,
            "lockOn": kconfig_read(lock, ["Daemon"], "Autolock", "true") == "true", "lockAfter": int(kconfig_read(lock, ["Daemon"], "Timeout", "5") or 5),
            "lockOnWake": kconfig_read(lock, ["Daemon"], "LockOnResume", "true") == "true",
            "trashDays": int(kconfig_read(trash, group, "Days", "30") or 30) if kconfig_read(trash, group, "UseTimeLimit", "false") == "true" else 0,
            "remember": remember != "2", "recent": _recent_count()}


def _plain_kv(path: Path) -> dict:
    try:
        return {k.strip(): v.strip().strip('"') for k, _, v in (l.partition("=") for l in path.read_text().splitlines()) if k and not k.startswith("#")}
    except OSError:
        return {}


def _recent_count() -> int:
    try:
        return (DATA / "recently-used.xbel").read_text(encoding="utf-8", errors="replace").count("<bookmark ")
    except OSError:
        return 0


# ---------------------------------------------------------------------------------------------- notifications (Huginn's own)
NOTIFY_FILE = CONFIG / "huginn-shell" / "notifications.json"
NOTIFYING_APPS = ["mail", "messages", "calendar", "reminders", "clock", "phone", "feeds", "podcasts", "settings", "store", "backup",
                  "authenticator", "money", "screenshot", "recorder"]


def load_notifications(apps: dict = None) -> dict:
    try:
        saved = json.loads(NOTIFY_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        saved = {}
    apps = apps if apps is not None else all_apps()
    rows = []
    per = saved.get("apps") or {}
    names = {"settings": "Software Update"}
    for key in NOTIFYING_APPS:
        a = apps.get(f"huginn-{key}.desktop") or {"id": f"huginn-{key}.desktop", "name": key.title(), "icon": ""}
        mine = per.get(key) or {}
        rows.append({"id": key, "name": names.get(key, a["name"]), "icon": icon_url(a), "allow": mine.get("allow", True),
                     "sound": mine.get("sound", True), "banner": mine.get("banner", True)})
    for a in sorted(apps.values(), key=lambda a: a["name"].lower()):
        key = a["id"][:-len(".desktop")]
        if key.startswith("huginn") or a["nodisplay"] or key not in per:
            continue
        mine = per[key]
        rows.append({"id": key, "name": a["name"], "icon": icon_url(a), "allow": mine.get("allow", True), "sound": mine.get("sound", True), "banner": mine.get("banner", True)})
    return {"dnd": bool(saved.get("dnd")), "focus": bool(saved.get("focus")), "from": saved.get("from", "22:00"), "to": saved.get("to", "07:00"),
            "previews": saved.get("previews", "always"), "sounds": saved.get("sounds", True), "apps": rows}


def save_notifications(change) -> None:
    try:
        saved = json.loads(NOTIFY_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        saved = {}
    change(saved)
    NOTIFY_FILE.parent.mkdir(parents=True, exist_ok=True)
    part = NOTIFY_FILE.with_name(".notifications.json.saving")
    part.write_text(json.dumps(saved, indent=1), encoding="utf-8")
    os.replace(part, NOTIFY_FILE)


# ---------------------------------------------------------------------------------------------- about
def load_about() -> dict:
    info = _plain_kv(Path("/etc/os-release"))
    mem = ""
    try:
        kb = int(Path("/proc/meminfo").read_text().split()[1])
        mem = f"{round(kb / 1048576)} GB"
    except (OSError, ValueError, IndexError):
        pass
    cpu = ""
    try:
        cpu = next((l.split(":", 1)[1].strip() for l in Path("/proc/cpuinfo").read_text().splitlines() if l.startswith("model name")), "")
    except OSError:
        pass
    gpu = ""
    code, out, _ = RUN(["lspci"]) if HAVE("lspci") else (1, "", "")
    if code == 0:
        gpu = next((re.sub(r"^.*?: ", "", l).split(" (rev")[0] for l in out.splitlines() if re.search(r"VGA|3D controller|Display controller", l)), "")
    disk = shutil.disk_usage(HOME)
    uname = os.uname()
    model = ""
    for f in ("/sys/class/dmi/id/product_name", "/sys/class/dmi/id/product_version"):
        try:
            v = Path(f).read_text().strip()
            if v and v.lower() not in ("to be filled by o.e.m.", "system product name", "default string", "none"):
                model = f"{model} {v}".strip()
        except OSError:
            pass
    def gb(n):
        return f"{n / 1e9:.0f} GB"
    rows = [("Computer", model), ("Name", uname.nodename), ("Processor", re.sub(r"\s+", " ", cpu)), ("Graphics", gpu), ("Memory", mem),
            ("Storage", f"{gb(disk.free)} free of {gb(disk.total)}"), ("System", info.get("PRETTY_NAME", "")), ("Kernel", uname.release)]
    return {"rows": [{"name": k, "value": v} for k, v in rows if v], "used": round(1 - disk.free / disk.total, 3) if disk.total else 0}


# ---------------------------------------------------------------------------------------------- sample values
def demo_state() -> dict:
    nets = [("Raven Nest", 88, "WPA2", True), ("Raven Nest 5G", 74, "WPA3", False), ("Corner Café", 52, "", False),
            ("Library Guest", 40, "WPA2", False), ("DIRECT-4F Printer", 31, "WPA2", False), ("Neighbour's Wi‑Fi", 18, "WPA2", False)]
    networks = [{"ssid": n, "signal": s, "secure": bool(sec), "security": sec, "inUse": u, "saved": u or n == "Library Guest",
                 "bars": 1 + (s >= 30) + (s >= 55) + (s >= 75), "band": "5 GHz" if "5G" in n else "2.4 GHz"} for n, s, sec, u in nets]
    lp = format_preview("en_US")
    return {
        "network": {"available": True, "wifiOn": True, "airplane": False, "hasWifi": True, "wifiDevice": "wlp2s0", "current": "Raven Nest",
                    "networks": networks, "wired": {"device": "enp3s0", "type": "ethernet", "state": "unavailable", "connection": ""},
                    "details": {"wlp2s0": {"mac": "7C:B2:7D:41:0E:9A", "ip": "192.168.1.42", "gateway": "192.168.1.1", "dns": "192.168.1.1", "ip6": "fd00::42"}},
                    "hotspot": False, "vpns": [{"name": "Work VPN", "uuid": "v1", "type": "vpn", "device": "", "active": False, "wireguard": True},
                                               {"name": "Home (OpenVPN)", "uuid": "v2", "type": "vpn", "device": "", "active": False, "wireguard": False}],
                    "saved": [{"name": "Raven Nest", "uuid": "s1", "type": "wifi", "device": "wlp2s0", "active": True, "wireguard": False},
                              {"name": "Library Guest", "uuid": "s2", "type": "wifi", "device": "", "active": False, "wireguard": False}]},
        "bluetooth": {"available": True, "present": True, "powered": True, "discoverable": False, "name": "huginn-desk",
                      "devices": [{"mac": "AC:12:2F:00:11:22", "name": "Studio Headphones", "kind": "headphones", "paired": True, "trusted": True, "connected": True, "battery": 72},
                                  {"mac": "D4:22:CD:33:44:55", "name": "Raven Keyboard", "kind": "keyboard", "paired": True, "trusted": True, "connected": True, "battery": 41},
                                  {"mac": "F0:99:B6:66:77:88", "name": "Travel Mouse", "kind": "mouse", "paired": True, "trusted": True, "connected": False, "battery": -1},
                                  {"mac": "00:1A:7D:99:88:77", "name": "Living Room Speaker", "kind": "speaker", "paired": False, "trusted": False, "connected": False, "battery": -1}]},
        "displays": {"available": True, "brightness": 70, "night": {"on": True, "mode": "Automatic", "temp": 4200, "from": "20:00", "to": "06:00"},
                     "screens": [{"name": "eDP-1", "builtIn": True, "enabled": True, "primary": False, "scale": 1.5, "rotation": "normal", "x": 0, "y": 360,
                                  "w": 2880, "h": 1800, "hz": 120, "modeId": "1", "resolution": "2880x1800", "label": "Built-in screen",
                                  "resolutions": [{"id": "2880x1800", "label": "2880 × 1800"}, {"id": "1920x1200", "label": "1920 × 1200"}, {"id": "1440x900", "label": "1440 × 900"}],
                                  "rates": [{"id": "120", "label": "120 Hz"}, {"id": "60", "label": "60 Hz"}], "modes": []},
                                 {"name": "DP-2", "builtIn": False, "enabled": True, "primary": True, "scale": 1.25, "rotation": "normal", "x": 1920, "y": 0,
                                  "w": 3840, "h": 2160, "hz": 60, "modeId": "4", "resolution": "3840x2160", "label": "DP 2",
                                  "resolutions": [{"id": "3840x2160", "label": "3840 × 2160"}, {"id": "2560x1440", "label": "2560 × 1440"}, {"id": "1920x1080", "label": "1920 × 1080"}],
                                  "rates": [{"id": "60", "label": "60 Hz"}, {"id": "30", "label": "30 Hz"}], "modes": []}]},
        "sound": {"available": True,
                  "outputs": [{"name": "hp", "label": "Studio Headphones", "port": "Bluetooth", "volume": 46, "mute": False, "default": True},
                              {"name": "spk", "label": "Built-in Speakers", "port": "Speakers", "volume": 70, "mute": False, "default": False},
                              {"name": "hdmi", "label": "DP 2 (monitor)", "port": "DisplayPort", "volume": 100, "mute": False, "default": False}],
                  "inputs": [{"name": "mic", "label": "Built-in Microphone", "port": "Internal mic", "volume": 64, "mute": False, "default": True},
                             {"name": "usbmic", "label": "Podcast Mic (USB)", "port": "Microphone", "volume": 80, "mute": False, "default": False}],
                  "apps": [{"index": 1, "app": "Music", "icon": "", "what": "Night Drive", "volume": 80, "mute": False},
                           {"index": 2, "app": "Huginn", "icon": "", "what": "A video", "volume": 55, "mute": False},
                           {"index": 3, "app": "Messages", "icon": "", "what": "Alerts", "volume": 100, "mute": True}]},
        "notifications": {"dnd": False, "focus": True, "from": "22:00", "to": "07:00", "previews": "unlocked", "sounds": True,
                          "apps": [{"id": k, "name": {"settings": "Software Update"}.get(k, k.title()), "icon": "", "allow": k not in ("feeds", "money"),
                                    "sound": k in ("mail", "messages", "phone", "clock", "reminders"), "banner": True} for k in NOTIFYING_APPS]},
        "power": {"battery": {"percent": 78, "state": "discharging", "timeLeft": "5.2 hours", "charging": False, "health": 91, "cycles": 212, "rate": 7.4, "model": "5B10W13930"},
                  "profile": "balanced", "profiles": ["performance", "balanced", "power-saver"],
                  "idle": {"ac": {"screenOff": 600, "sleep": 1800}, "battery": {"screenOff": 300, "sleep": 900}}, "lid": "1", "button": "16"},
        "input": {"pointers": [{"sys": "event7", "name": "Built-in Touchpad", "touchpad": True, "tap": True, "natural": True, "left": False, "speed": 0.2, "dwt": True, "canDwt": True, "canTap": True},
                               {"sys": "event9", "name": "Travel Mouse", "touchpad": False, "tap": False, "natural": False, "left": False, "speed": 0.0, "dwt": False, "canDwt": False, "canTap": False}],
                  "repeat": True, "delay": 450, "rate": 30, "layouts": [{"id": "us", "label": "English (US)"}, {"id": "de", "label": "German"}],
                  "caps": "caps:ctrl_modifier", "compose": True, "capsChoices": [{"id": i, "label": n} for i, n in CAPS]},
        "time": {"zone": "America/Chicago", "zoneLabel": "Chicago (America)", "ntp": True, "synced": True, "canNtp": True, "available": True},
        "language": {"language": "en_US", "languageLabel": locale_label("en_US"), "formats": "en_US", "formatsLabel": locale_label("en_US"), "preview": lp,
                     "choices": [{"id": c, "label": locale_label(c), "installed": c in ("en_US", "de_DE", "en_GB")} for c in LANGUAGES[:14]]},
        "users": {"available": True, "me": {"uid": 1000, "name": "astrid", "full": "Astrid Berg", "admin": True, "picture": "", "path": "/u/1000"},
                  "others": [{"uid": 1001, "name": "sam", "full": "Sam", "admin": False, "picture": "", "path": "/u/1001", "locked": False},
                             {"uid": 1002, "name": "kids", "full": "Kids", "admin": False, "picture": "", "path": "/u/1002", "locked": False}]},
        "defaults": {"categories": [{"id": k, "label": l, "glyph": g, "current": f"huginn-{a}.desktop", "currentName": n, "currentIcon": "",
                                     "choices": [{"id": f"huginn-{a}.desktop", "name": n, "icon": ""}] + ([{"id": "org.mozilla.firefox.desktop", "name": "Firefox", "icon": ""}] if k == "browser" else [])}
                                    for (k, l, g, _), (a, n) in zip(CATEGORIES, [("", "Huginn"), ("mail", "Mail"), ("calendar", "Calendar"), ("photos", "Photos"), ("music", "Music"),
                                                                                  ("video", "Media Player"), ("documents", "Documents"), ("code", "Code"), ("files", "Files"), ("terminal", "Terminal")])],
                     "startup": [{"file": "/a/huginn-mail.desktop", "name": "Mail (watch the inbox)", "on": True, "icon": ""},
                                 {"file": "/a/syncthing.desktop", "name": "Syncthing", "on": False, "icon": ""}],
                     "addable": [{"id": "huginn-notes.desktop", "name": "Notes", "icon": ""}, {"id": "huginn-music.desktop", "name": "Music", "icon": ""}]},
        "privacy": {"firewall": True, "hasFirewall": True, "lockOn": True, "lockAfter": 5, "lockOnWake": True, "trashDays": 30, "remember": True, "recent": 128,
                    "permissions": [{"table": "devices", "object": "camera", "app": "us.zoom.Zoom", "appName": "Zoom", "what": "Camera", "allow": True},
                                    {"table": "devices", "object": "microphone", "app": "us.zoom.Zoom", "appName": "Zoom", "what": "Microphone", "allow": True},
                                    {"table": "location", "object": "location", "app": "org.gnome.Maps", "appName": "Maps", "what": "Location", "allow": False},
                                    {"table": "background", "object": "background", "app": "com.discordapp.Discord", "appName": "Discord", "what": "Running in the background", "allow": True}]},
        "a11y": {"reader": False, "hasReader": True, "zoom": True, "zoomStep": 1.2, "zoomFollow": "0", "filter": "", "filterStrength": 1.0,
                 "filters": [{"id": i, "label": l} for i, l in FILTERS], "cursor": 24, "sticky": False, "stickyLock": True, "slow": False,
                 "slowDelay": 300, "bounce": False, "bounceDelay": 500, "mouseKeys": False, "flash": False, "osk": False, "hasOsk": True, "animations": True},
        "look": {"loginRealm": "aurora", "canChange": True},
        "about": {"rows": [{"name": "Computer", "value": "Framework Laptop 13"}, {"name": "Name", "value": "huginn-desk"},
                           {"name": "Processor", "value": "AMD Ryzen 7 7840U"}, {"name": "Graphics", "value": "Radeon 780M"},
                           {"name": "Memory", "value": "32 GB"}, {"name": "Storage", "value": "612 GB free of 1 TB"},
                           {"name": "System", "value": "Huginn OS 0.1 (Ubuntu 26.04 LTS)"}, {"name": "Kernel", "value": "6.17.0-8-generic"}], "used": 0.39},
    }


# ---------------------------------------------------------------------------------------------- the sign-in screen's look
LOGIN_THEME = Path("/usr/share/sddm/themes/huginn")
LOGIN_LOOK = "/usr/libexec/huginn-login-look"            # writes theme.conf.user as root (through Huginn's password prompt)


def load_look() -> dict:
    """Which realm the sign-in screen wears (theme.conf.user wins over theme.conf, as SDDM reads them)."""
    realm = "aurora"
    for name in ("theme.conf", "theme.conf.user"):
        try:
            m = re.search(r"^realm\s*=\s*(\w+)", (LOGIN_THEME / name).read_text(encoding="utf-8"), re.M)
            if m:
                realm = m.group(1)
        except OSError:
            pass
    return {"loginRealm": realm, "canChange": os.access(LOGIN_LOOK, os.X_OK) and bool(HAVE("pkexec"))}


# ---------------------------------------------------------------------------------------------- the backend Settings talks to
PAGES = ("network", "bluetooth", "displays", "sound", "notifications", "power", "input", "time", "language", "users", "defaults", "privacy", "about", "a11y", "look")


class SystemSettings(QObject):
    """Settings' pages: each loads in the background when it's opened, and again after anything on it changes."""
    changed = Signal()
    said = Signal(str, bool)
    _back = Signal(str, object)

    def __init__(self, demo: bool = False, shell_settings=None):
        super().__init__()
        self._demo, self._shell = demo, shell_settings
        self._state = demo_state() if demo else {}
        self._busy = set()
        self._zones = None
        self._apps = None
        self._back.connect(self._take)

    def _page(name, sig):                                       # noqa: N805  (a helper for the class body)
        return Property("QVariantMap", lambda self: self._state.get(name, {}), notify=sig)

    network, bluetooth, displays, sound = _page("network", changed), _page("bluetooth", changed), _page("displays", changed), _page("sound", changed)
    notifications, power, input, time = _page("notifications", changed), _page("power", changed), _page("input", changed), _page("time", changed)
    language, users, defaults, privacy, about = _page("language", changed), _page("users", changed), _page("defaults", changed), _page("privacy", changed), _page("about", changed)
    a11y, look = _page("a11y", changed), _page("look", changed)
    del _page
    busy = Property("QVariantList", lambda self: sorted(self._busy), notify=changed)
    demo = Property(bool, lambda self: self._demo, constant=True)

    # -------------------------------------------------------------- loading
    def _known_apps(self) -> dict:
        if self._apps is None:
            self._apps = all_apps()
        return self._apps

    def _loader(self, page: str, **kw):
        return {"network": load_network, "bluetooth": lambda: load_bluetooth(kw.get("scan", False)), "displays": load_displays,
                "sound": load_sound, "notifications": lambda: load_notifications(self._known_apps()), "power": load_power,
                "input": load_input, "time": load_time, "language": load_language, "users": load_users,
                "defaults": lambda: load_defaults(self._known_apps()), "privacy": lambda: load_privacy(self._known_apps()), "about": load_about,
                "a11y": load_a11y, "look": load_look}[page]

    @Slot(str)
    def load(self, page: str) -> None:
        self._load(page)

    def _load(self, page: str, **kw) -> None:
        if self._demo or page not in PAGES or page in self._busy:
            return
        self._busy.add(page)
        self.changed.emit()
        loader = self._loader(page, **kw)

        def work():
            try:
                data = loader()
            except Exception as err:                             # noqa: BLE001  (a page should never take the app down)
                data = {"error": f"Couldn't read these settings: {err}"}
            self._back.emit(page, data)
        threading.Thread(target=work, daemon=True).start()

    @Slot(str, object)
    def _take(self, page: str, data) -> None:
        if page == "!said":
            self.said.emit(data[0], data[1])
            return
        if page == "!apps":
            self._apps = None
            return
        self._busy.discard(page)
        if isinstance(data, dict):
            self._state[page] = data
        self.changed.emit()

    def _act(self, page: str, fn, ok: str = "", reload: bool = True, demo_change=None) -> None:
        """Make a change in the background; say what happened; read the page again so it shows the truth."""
        if self._demo:
            if demo_change:
                demo_change(self._state.setdefault(page, {}))
                self.changed.emit()
            if ok:
                self.said.emit(ok, False)
            return

        def work():
            try:
                note = fn()
                if note or ok:
                    self._back.emit("!said", (note or ok, False))
            except Failed as err:
                self._back.emit("!said", (str(err), True))
            except Exception as err:                             # noqa: BLE001
                self._back.emit("!said", (f"That didn't work: {err}", True))
            if reload:
                self._busy.discard(page)
                try:
                    self._back.emit(page, self._loader(page)())
                except Exception:                                # noqa: BLE001
                    pass
        threading.Thread(target=work, daemon=True).start()

    # -------------------------------------------------------------- the sign-in screen
    @Slot(str)
    def setLoginRealm(self, realm: str) -> None:
        if not re.fullmatch(r"[a-z]+", realm or ""):
            return
        label = realm.capitalize().replace("Bifrost", "Bifröst")
        self._act("look", lambda: must(["pkexec", LOGIN_LOOK, realm], None, 130, "Changing the sign-in screen") and "",
                  ok=f"The sign-in screen now wears {label}.", demo_change=lambda st: st.update(loginRealm=realm))

    # -------------------------------------------------------------- Wi-Fi and network
    @Slot(bool)
    def setWifi(self, on: bool) -> None:
        self._act("network", lambda: must(["nmcli", "radio", "wifi", "on" if on else "off"], what="Turning Wi‑Fi " + ("on" if on else "off")) and "",
                  demo_change=lambda s: s.update(wifiOn=on))

    @Slot(bool)
    def setAirplane(self, on: bool) -> None:
        self._act("network", lambda: must(["rfkill", "block" if on else "unblock", "all"], what="Airplane mode") and "",
                  ok="Airplane mode is on: Wi‑Fi and Bluetooth are off." if on else "", demo_change=lambda s: s.update(airplane=on, wifiOn=not on))

    @Slot()
    def scanWifi(self) -> None:
        self._load("network")

    @Slot(str, str)
    def joinWifi(self, ssid: str, password: str) -> None:
        def work():
            argv = ["nmcli"] + (["--ask"] if password else []) + ["device", "wifi", "connect", ssid]
            code, out, err = RUN(argv, (password + "\n") if password else None, 60)
            if code != 0:
                text = ANSI.sub("", err or out)
                if "Secrets were required" in text or "802-1x" in text or "password" in text.lower():
                    raise Failed(f"Couldn't join “{ssid}”: the password wasn't right.")
                raise Failed(f"Couldn't join “{ssid}”: {text.strip().splitlines()[-1] if text.strip() else 'no reason given'}")
            return f"Joined “{ssid}”."
        self._act("network", work, demo_change=lambda s: [n.update(inUse=n["ssid"] == ssid, saved=n["saved"] or n["ssid"] == ssid) for n in s["networks"]] and s.update(current=ssid))

    @Slot(str)
    def joinSaved(self, name: str) -> None:
        self._act("network", lambda: must(["nmcli", "connection", "up", "id", name], None, 60, f"Joining “{name}”") and f"Joined “{name}”.")

    @Slot(str)
    def forget(self, uuid: str) -> None:
        self._act("network", lambda: must(["nmcli", "connection", "delete", "uuid", uuid], what="Forgetting it") and "Forgotten: it won't join by itself any more.",
                  demo_change=lambda s: s.update(saved=[c for c in s["saved"] if c["uuid"] != uuid]))

    @Slot(str)
    def forgetNetwork(self, ssid: str) -> None:
        self._act("network", lambda: must(["nmcli", "connection", "delete", "id", ssid], what="Forgetting it") and f"Forgot “{ssid}”.",
                  demo_change=lambda s: [n.update(saved=False, inUse=False) for n in s["networks"] if n["ssid"] == ssid])

    @Slot(str)
    def disconnect(self, device: str) -> None:
        self._act("network", lambda: must(["nmcli", "device", "disconnect", device], what="Disconnecting") and "",
                  demo_change=lambda s: [n.update(inUse=False) for n in s["networks"]] and s.update(current=""))

    @Slot(str, bool)
    def setVpn(self, uuid: str, on: bool) -> None:
        self._act("network", lambda: must(["nmcli", "connection", "up" if on else "down", "uuid", uuid], None, 60, "The VPN") and ("VPN connected." if on else "VPN disconnected."),
                  demo_change=lambda s: [v.update(active=on if v["uuid"] == uuid else v["active"]) for v in s["vpns"]])

    @Slot(str)
    def importVpn(self, path: str) -> None:
        path = path.replace("file://", "")
        kind = "wireguard" if path.endswith(".conf") and "[Peer]" in _peek(path) else "openvpn"
        self._act("network", lambda: must(["nmcli", "connection", "import", "type", kind, "file", path], what="Adding the VPN") and "The VPN was added. Switch it on below.")

    @Slot(bool)
    def setHotspot(self, on: bool) -> None:
        if not on:
            self._act("network", lambda: must(["nmcli", "connection", "down", "id", "Huginn Hotspot"], what="Stopping the hotspot") and "", demo_change=lambda s: s.update(hotspot=False))
            return
        import secrets
        word = "-".join(secrets.choice(["raven", "north", "frost", "amber", "cedar", "river", "ember", "stone", "cloud", "maple"]) for _ in range(2)) + str(secrets.randbelow(90) + 10)
        self._act("network", lambda: must(["nmcli", "device", "wifi", "hotspot", "con-name", "Huginn Hotspot", "ssid", f"{os.uname().nodename} hotspot", "password", word], None, 30, "Starting the hotspot")
                  and f"Hotspot on: “{os.uname().nodename} hotspot”, password {word}.", demo_change=lambda s: s.update(hotspot=True))

    # -------------------------------------------------------------- Bluetooth
    @Slot(bool)
    def setBluetooth(self, on: bool) -> None:
        self._act("bluetooth", lambda: (RUN(["rfkill", "unblock", "bluetooth"]) if on else None, must(["bluetoothctl", "power", "on" if on else "off"], what="Bluetooth"))[1] and "",
                  demo_change=lambda s: s.update(powered=on))

    @Slot()
    def scanBluetooth(self) -> None:
        if self._demo:
            self.said.emit("Looking for devices nearby…", False)
            return
        self._load("bluetooth", scan=True)

    @Slot(bool)
    def setDiscoverable(self, on: bool) -> None:
        self._act("bluetooth", lambda: must(["bluetoothctl", "discoverable", "on" if on else "off"], what="Being visible") and "", demo_change=lambda s: s.update(discoverable=on))

    @Slot(str)
    def pair(self, mac: str) -> None:
        def work():
            must(["bluetoothctl", "pair", mac], None, 60, "Pairing")
            RUN(["bluetoothctl", "trust", mac])
            must(["bluetoothctl", "connect", mac], None, 30, "Connecting")
            return "Paired and connected."
        self._act("bluetooth", work, demo_change=lambda s: [d.update(paired=True, trusted=True, connected=True) for d in s["devices"] if d["mac"] == mac])

    @Slot(str, bool)
    def setConnected(self, mac: str, on: bool) -> None:
        self._act("bluetooth", lambda: must(["bluetoothctl", "connect" if on else "disconnect", mac], None, 30, "Connecting" if on else "Disconnecting") and "",
                  demo_change=lambda s: [d.update(connected=on) for d in s["devices"] if d["mac"] == mac])

    @Slot(str)
    def unpair(self, mac: str) -> None:
        self._act("bluetooth", lambda: must(["bluetoothctl", "remove", mac], what="Forgetting the device") and "Forgotten.",
                  demo_change=lambda s: s.update(devices=[d for d in s["devices"] if d["mac"] != mac]))

    # -------------------------------------------------------------- displays
    def _screen(self, name: str) -> dict:
        return next((s for s in self._state.get("displays", {}).get("screens", []) if s["name"] == name), {})

    def _kscreen(self, *changes, what="The display") -> str:
        must(["kscreen-doctor", *changes], None, 30, what)
        return ""

    @Slot(str, str)
    def setResolution(self, name: str, size: str) -> None:
        w, h = (int(x) for x in size.split("x"))
        mode = best_mode(self._screen(name).get("modes", []), w, h)
        self._act("displays", lambda: self._kscreen(f"output.{name}.mode.{mode or size}", what="Changing the resolution"),
                  demo_change=lambda s: [x.update(resolution=size, w=w, h=h) for x in s["screens"] if x["name"] == name])

    @Slot(str, str)
    def setRate(self, name: str, hz: str) -> None:
        scr = self._screen(name)
        mode = best_mode(scr.get("modes", []), scr.get("w", 0), scr.get("h", 0), float(hz))
        self._act("displays", lambda: self._kscreen(f"output.{name}.mode.{mode}", what="Changing the refresh rate"),
                  demo_change=lambda s: [x.update(hz=float(hz)) for x in s["screens"] if x["name"] == name])

    @Slot(str, float)
    def setScale(self, name: str, scale: float) -> None:
        self._act("displays", lambda: self._kscreen(f"output.{name}.scale.{scale:g}", what="Changing the size of things"),
                  demo_change=lambda s: [x.update(scale=scale) for x in s["screens"] if x["name"] == name])

    @Slot(str, str)
    def setRotation(self, name: str, rotation: str) -> None:
        self._act("displays", lambda: self._kscreen(f"output.{name}.rotation.{rotation}", what="Turning the picture"),
                  demo_change=lambda s: [x.update(rotation=rotation) for x in s["screens"] if x["name"] == name])

    @Slot(str, bool)
    def setScreenOn(self, name: str, on: bool) -> None:
        if not on and sum(1 for s in self._state.get("displays", {}).get("screens", []) if s["enabled"]) <= 1:
            self.said.emit("That's the only screen that's on, so it stays on.", True)
            return
        self._act("displays", lambda: self._kscreen(f"output.{name}.{'enable' if on else 'disable'}"),
                  demo_change=lambda s: [x.update(enabled=on) for x in s["screens"] if x["name"] == name])

    @Slot(str)
    def setMain(self, name: str) -> None:
        self._act("displays", lambda: self._kscreen(f"output.{name}.priority.1", what="Choosing the main screen") or "The dock and top bar move to that screen.",
                  demo_change=lambda s: [x.update(primary=x["name"] == name) for x in s["screens"]])

    @Slot(str, int, int)
    def placeScreen(self, name: str, x: int, y: int) -> None:
        self._act("displays", lambda: self._kscreen(f"output.{name}.position.{max(0, x)},{max(0, y)}", what="Arranging the screens"),
                  demo_change=lambda s: [o.update(x=max(0, x), y=max(0, y)) for o in s["screens"] if o["name"] == name])

    @Slot(str, "QVariant")
    def setNight(self, key: str, value) -> None:
        keys = {"on": "Active", "mode": "Mode", "temp": "NightTemperature", "from": "EveningBeginFixed", "to": "MorningBeginFixed"}
        if key not in keys:
            return
        stored = value.replace(":", "") if key in ("from", "to") else value

        def work():
            kconfig_write(CONFIG / "kwinrc", ["NightColor"], keys[key], stored)
            dbus_call("session", "org.kde.KWin", "/KWin", "org.kde.KWin.reconfigure")
            return ""
        self._act("displays", work, demo_change=lambda s: s["night"].update({key: value}))

    @Slot(int)
    def setBrightness(self, percent: int) -> None:
        percent = max(1, min(100, int(percent)))
        self._act("displays", lambda: must(["brightnessctl", "-q", "-c", "backlight", "set", f"{percent}%"], what="Brightness") and "",
                  reload=False, demo_change=lambda s: s.update(brightness=percent))
        if not self._demo:
            self._state.setdefault("displays", {})["brightness"] = percent
            self.changed.emit()

    # -------------------------------------------------------------- sound
    def _sound_now(self, kind: str, name: str, **change) -> None:
        for e in self._state.get("sound", {}).get(kind, []):
            if e.get("name") == name or e.get("index") == name:
                e.update(change)
        self.changed.emit()

    @Slot(str, str)
    def setDefaultDevice(self, kind: str, name: str) -> None:
        tool = "set-default-sink" if kind == "outputs" else "set-default-source"
        self._act("sound", lambda: must(["pactl", tool, name], what="Switching") and "",
                  demo_change=lambda s: [e.update(default=e["name"] == name) for e in s[kind]])

    @Slot(str, str, int)
    def setVolume(self, kind: str, name: str, percent: int) -> None:
        tool = "set-sink-volume" if kind == "outputs" else "set-source-volume"
        if not self._demo:
            self._sound_now(kind, name, volume=percent)
            threading.Thread(target=RUN, args=(["pactl", tool, name, f"{max(0, min(150, percent))}%"],), daemon=True).start()
        else:
            self._sound_now(kind, name, volume=percent)

    @Slot(str, str, bool)
    def setMute(self, kind: str, name: str, mute: bool) -> None:
        tool = "set-sink-mute" if kind == "outputs" else "set-source-mute"
        self._sound_now(kind, name, mute=mute)
        if not self._demo:
            threading.Thread(target=RUN, args=(["pactl", tool, name, "1" if mute else "0"],), daemon=True).start()

    @Slot(int, int)
    def setAppVolume(self, index: int, percent: int) -> None:
        self._sound_now("apps", index, volume=percent)
        if not self._demo:
            threading.Thread(target=RUN, args=(["pactl", "set-sink-input-volume", str(index), f"{max(0, min(150, percent))}%"],), daemon=True).start()

    @Slot(int, bool)
    def setAppMute(self, index: int, mute: bool) -> None:
        self._sound_now("apps", index, mute=mute)
        if not self._demo:
            threading.Thread(target=RUN, args=(["pactl", "set-sink-input-mute", str(index), "1" if mute else "0"],), daemon=True).start()

    @Slot()
    def testSound(self) -> None:
        if self._demo:
            return
        for f in ("/usr/share/sounds/freedesktop/stereo/audio-volume-change.oga", "/usr/share/sounds/ocean/stereo/audio-volume-change.oga"):
            if os.path.isfile(f):
                threading.Thread(target=RUN, args=(["pw-play", f],), daemon=True).start()
                return

    # -------------------------------------------------------------- notifications
    @Slot(str, "QVariant")
    def setNotify(self, key: str, value) -> None:
        if key not in ("dnd", "focus", "from", "to", "previews", "sounds"):
            return
        self._act("notifications", lambda: save_notifications(lambda d: d.update({key: value})) or "", demo_change=lambda s: s.update({key: value}))

    @Slot(str, str, bool)
    def setAppNotify(self, app: str, field: str, on: bool) -> None:
        if field not in ("allow", "sound", "banner"):
            return
        self._act("notifications", lambda: save_notifications(lambda d: d.setdefault("apps", {}).setdefault(app, {}).update({field: on})) or "",
                  demo_change=lambda s: [a.update({field: on}) for a in s["apps"] if a["id"] == app])

    # -------------------------------------------------------------- battery and power
    @Slot(str)
    def setProfile(self, name: str) -> None:
        self._act("power", lambda: must(["powerprofilesctl", "set", name], what="Changing the power mode") and "", demo_change=lambda s: s.update(profile=name))

    @Slot(str, str, int)
    def setIdle(self, source: str, what: str, seconds: int) -> None:
        group = POWER_GROUPS.get(source)
        if not group or what not in ("screenOff", "sleep"):
            return

        def work():
            save_power(lambda r: r[source].update({what: max(0, int(seconds))}))
            return ""
        self._act("power", work, demo_change=lambda s: s["idle"][source].update({what: seconds}))

    @Slot(str, str)
    def setPowerAction(self, which: str, action: str) -> None:
        key = {"lid": "LidAction", "button": "PowerButtonAction"}.get(which)
        if not key:
            return

        def work():
            save_power(lambda r: r.update({which: str(action)}))
            return ""
        self._act("power", work, demo_change=lambda s: s.update({which: action}))

    # -------------------------------------------------------------- keyboard, mouse, touchpad
    @Slot(str, str, "QVariant")
    def setPointer(self, sysname: str, prop: str, value) -> None:
        names = {"tap": ("tapToClick", "b"), "natural": ("naturalScroll", "b"), "left": ("leftHanded", "b"), "speed": ("pointerAcceleration", "d"), "dwt": ("disableWhileTyping", "b")}
        if prop not in names:
            return
        dbus_name, kind = names[prop]
        text = ("true" if value else "false") if kind == "b" else f"{max(-1.0, min(1.0, float(value))):.2f}"

        def work():
            if busctl("user", "set-property", "org.kde.KWin", f"/org/kde/KWin/InputDevice/{sysname}", "org.kde.KWin.InputDevice", dbus_name, kind, text) is None:
                raise Failed("KWin didn't take the change: " + (busctl.last or "it isn't running"))
            return ""
        for p in self._state.get("input", {}).get("pointers", []):
            if p["sys"] == sysname:
                p[prop] = value
        self.changed.emit()
        self._act("input", work, reload=False)

    @Slot(str, "QVariant")
    def setKeyboard(self, key: str, value) -> None:
        def work():
            rc, xkb = CONFIG / "kcminputrc", CONFIG / "kxkbrc"
            if key == "repeat":
                kconfig_write(rc, ["Keyboard"], "KeyRepeat", "repeat" if value else "nothing")
            elif key == "delay":
                kconfig_write(rc, ["Keyboard"], "RepeatDelay", int(value))
            elif key == "rate":
                kconfig_write(rc, ["Keyboard"], "RepeatRate", f"{float(value):g}")
            elif key in ("layouts", "caps", "compose"):
                options = [o for o in kconfig_read(xkb, ["Layout"], "Options", "").split(",") if o]
                if key == "caps":
                    options = [o for o in options if not o.startswith("caps:")] + ([value] if value else [])
                elif key == "compose":
                    options = [o for o in options if not o.startswith("compose:")] + (["compose:ralt"] if value else [])
                else:
                    layouts = [l for l in value if re.fullmatch(r"[a-z]{2,8}", l)][:4] or ["us"]
                    kconfig_write(xkb, ["Layout"], "LayoutList", ",".join(layouts))
                    kconfig_write(xkb, ["Layout"], "VariantList", ",".join("" for _ in layouts))
                    kconfig_write(xkb, ["Layout"], "Use", "true")
                kconfig_write(xkb, ["Layout"], "Options", ",".join(options))
                kconfig_write(xkb, ["Layout"], "ResetOldOptions", "true")
                RUN(["dbus-send", "--session", "--type=signal", "/Layouts", "org.kde.keyboard.reloadConfig"], None, 5)
            dbus_call("session", "org.kde.KWin", "/KWin", "org.kde.KWin.reconfigure")
            return ""

        def demo(s):
            if key == "layouts":
                names = {l["id"]: l["label"] for l in xkb_layouts()}
                s["layouts"] = [{"id": l, "label": names.get(l, l)} for l in value]
            else:
                s[key] = value
        self._act("input", work, demo_change=demo)

    # -------------------------------------------------------------- accessibility
    @Slot(str, "QVariant")
    def setA11y(self, key: str, value) -> None:
        value = value.toVariant() if hasattr(value, "toVariant") else value

        def work():
            acc, kwin = CONFIG / "kaccessrc", CONFIG / "kwinrc"
            note = ""
            if key == "reader":
                kconfig_write(acc, ["ScreenReader"], "Enabled", bool(value))
                if HAVE("gsettings"):
                    RUN(["gsettings", "set", "org.gnome.desktop.a11y.applications", "screen-reader-enabled", "true" if value else "false"], None, 5)
                if value and HAVE("orca"):
                    subprocess.Popen(["orca", "--replace"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
                    note = "The screen reader is on. Meta+Alt+S turns it on and off from anywhere."
                elif not value:
                    RUN(["pkill", "-x", "orca"], None, 5)
            elif key == "zoom":
                kconfig_write(kwin, ["Plugins"], "zoomEnabled", bool(value))
                kwin_effect("zoom", bool(value))
            elif key in ("zoomStep", "zoomFollow"):
                kconfig_write(kwin, ["Effect-zoom"], {"zoomStep": "ZoomFactor", "zoomFollow": "MouseTracking"}[key], value)
                kwin_reconfigure_effect("zoom")
            elif key == "filter":
                was_inverted = kconfig_read(acc, ["Huginn"], "Invert", "false") == "true"
                cb = value not in ("", "invert")
                kconfig_write(kwin, ["Plugins"], "colorblindnesscorrectionEnabled", cb)
                if cb:
                    kconfig_write(kwin, ["Effect-colorblindnesscorrection"], "Mode", value)
                kwin_effect("colorblindnesscorrection", cb)
                if cb:
                    kwin_reconfigure_effect("colorblindnesscorrection")
                if (value == "invert") != was_inverted:             # KWin's invert effect toggles from its shortcut
                    kwin_effect("invert", True)
                    dbus_call("session", "org.kde.kglobalaccel", "/component/kwin", "org.kde.kglobalaccel.Component.invokeShortcut", "string:Invert")
                    kconfig_write(acc, ["Huginn"], "Invert", value == "invert")
            elif key == "filterStrength":
                kconfig_write(kwin, ["Effect-colorblindnesscorrection"], "Intensity", f"{float(value):.2f}")
                kwin_reconfigure_effect("colorblindnesscorrection")
            elif key == "cursor":
                size = int(value)
                kconfig_write(CONFIG / "kcminputrc", ["Mouse"], "cursorSize", size)
                if HAVE("plasma-apply-cursortheme"):
                    theme = kconfig_read(CONFIG / "kcminputrc", ["Mouse"], "cursorTheme", "breeze_cursors") or "breeze_cursors"
                    RUN(["plasma-apply-cursortheme", "--size", str(size), theme], None, 10)
                dbus_call("session", "org.kde.KWin", "/KWin", "org.kde.KWin.reconfigure")
                note = "Some apps show the new pointer size after they're opened again."
            elif key in ("sticky", "stickyLock", "slow", "slowDelay", "bounce", "bounceDelay"):
                names = {"sticky": "StickyKeys", "stickyLock": "StickyKeysLatch", "slow": "SlowKeys", "slowDelay": "SlowKeysDelay",
                         "bounce": "BounceKeys", "bounceDelay": "BounceKeysDelay"}
                kconfig_write(acc, ["Keyboard"], names[key], int(value) if key.endswith("Delay") else bool(value))
                dbus_call("session", "org.kde.KWin", "/KWin", "org.kde.KWin.reconfigure")
            elif key == "mouseKeys":
                kconfig_write(acc, ["Mouse"], "MouseKeys", bool(value))
                dbus_call("session", "org.kde.KWin", "/KWin", "org.kde.KWin.reconfigure")
            elif key == "flash":
                kconfig_write(acc, ["Bell"], "VisibleBell", bool(value))
                kconfig_write(acc, ["Bell"], "SystemBell", not value)
            elif key == "osk":
                kconfig_write(kwin, ["Wayland"], "InputMethod", osk_desktop() if value else "")
                dbus_call("session", "org.kde.KWin", "/KWin", "org.kde.KWin.reconfigure")
            elif key == "animations":
                kconfig_write(CONFIG / "kdeglobals", ["KDE"], "AnimationDurationFactor", "1" if value else "0")
            return note

        def demo(st):
            st[key] = value
        self._act("a11y", work, demo_change=demo)

    @Property("QVariantList", constant=True)
    def layoutChoices(self):
        return xkb_layouts()

    # -------------------------------------------------------------- date, time and language
    @Property("QVariantList", constant=True)
    def zoneChoices(self):
        if self._zones is None:
            self._zones = [{"id": z, "label": zone_label(z)} for z in zones()]
        return self._zones

    @Slot(str)
    def setZone(self, zone: str) -> None:
        if zone not in zones():
            return
        self._act("time", lambda: must(["timedatectl", "set-timezone", zone], None, 130, "Changing the time zone") and "",
                  ok=f"The time zone is now {zone_label(zone)}.", demo_change=lambda s: s.update(zone=zone, zoneLabel=zone_label(zone)))

    @Slot(bool)
    def setNtp(self, on: bool) -> None:
        self._act("time", lambda: must(["timedatectl", "set-ntp", "true" if on else "false"], None, 130, "Setting the clock") and "", demo_change=lambda s: s.update(ntp=on))

    @Slot(str)
    def setClock(self, when: str) -> None:
        if not re.fullmatch(r"\d{4}-\d\d-\d\d \d\d:\d\d", when.strip()):
            self.said.emit("Write the time as 2026-11-14 09:30.", True)
            return
        self._act("time", lambda: must(["timedatectl", "set-time", when.strip() + ":00"], None, 130, "Setting the clock") and "The clock is set.", ok="The clock is set." if self._demo else "")

    @Slot(str, str)
    def setLocale(self, what: str, code: str) -> None:
        if not re.fullmatch(r"[a-z]{2,3}_[A-Z]{2}", code):
            return
        rc = CONFIG / "plasma-localerc"

        def work():
            if what == "language":
                kconfig_write(rc, ["Translations"], "LANGUAGE", f"{code}:{code.split('_')[0]}")
            else:
                kconfig_write(rc, ["Formats"], "LANG", f"{code}.UTF-8")
            return "This takes effect the next time you sign in."

        def demo(s):
            if what == "language":
                s.update(language=code, languageLabel=locale_label(code))
            else:
                s.update(formats=code, formatsLabel=locale_label(code), preview=format_preview(code))
        self._act("language", work, demo_change=demo)

    @Slot(str, result="QVariantMap")
    def preview(self, code: str):
        return format_preview(code)

    # -------------------------------------------------------------- people
    def _user_call(self, path: str, method: str, *args, what: str = "") -> None:
        if busctl("system", "call", ACCOUNTS, path, "org.freedesktop.Accounts.User", method, *args, interactive=True) is None:
            raise Failed(f"{what or 'That'} didn't work" + (": " + busctl.last.splitlines()[-1] if busctl.last else "."))

    @Slot(str)
    def setFullName(self, name: str) -> None:
        name = name.strip()[:80]
        if not name:
            return
        me = self._state.get("users", {}).get("me", {})
        self._act("users", lambda: self._user_call(me.get("path", ""), "SetRealName", "s", name, what="Changing your name") or "",
                  demo_change=lambda s: s["me"].update(full=name))

    @Slot(result="QVariantList")
    def pictureChoices(self):
        me = self._state.get("users", {}).get("me", {})
        drawn = make_avatars(initials_of(me.get("full") or me.get("name") or "?"))
        pics = Path(os.environ.get("XDG_PICTURES_DIR") or HOME / "Pictures")
        photos = []
        try:
            photos = sorted((p for p in pics.iterdir() if p.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp")), key=lambda p: -p.stat().st_mtime)[:12]
        except OSError:
            pass
        return [{"path": p, "url": "file://" + p, "photo": False} for p in drawn] + [{"path": str(p), "url": "file://" + str(p), "photo": True} for p in photos]

    @Slot(str)
    def setPicture(self, path: str) -> None:
        path = path.replace("file://", "")
        if not os.path.isfile(path):
            return
        me = self._state.get("users", {}).get("me", {})

        def work():
            from PySide6.QtGui import QImage
            from PySide6.QtCore import Qt
            img = QImage(path)
            if img.isNull():
                raise Failed("That picture couldn't be read.")
            side = min(img.width(), img.height())
            square = img.copy((img.width() - side) // 2, (img.height() - side) // 2, side, side).scaled(512, 512, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
            out = HOME / ".face"
            square.save(str(out), "PNG")
            self._user_call(me.get("path", ""), "SetIconFile", "s", str(out), what="Changing your picture")
            return ""
        self._act("users", work, demo_change=lambda s: s["me"].update(picture="file://" + path))

    @Slot(str, str, str)
    def changePassword(self, old: str, new: str, again: str) -> None:
        if new != again:
            self.said.emit("The two new passwords aren't the same.", True)
            return
        if len(new) < 8:
            self.said.emit("Use at least 8 characters.", True)
            return

        def work():
            problem = change_password(old, new)
            if problem:
                raise Failed(problem)
            return "Your password is changed. Use the new one next time you sign in or unlock."
        self._act("users", work, reload=False, ok="Your password is changed." if self._demo else "")

    @Slot(str, str, bool)
    def addUser(self, full: str, login: str, admin: bool) -> None:
        login = login.strip().lower()
        if not re.fullmatch(r"[a-z_][a-z0-9_-]{0,30}", login):
            self.said.emit("A sign-in name is lower-case letters and numbers, starting with a letter.", True)
            return

        def work():
            got = busctl("system", "call", ACCOUNTS, "/org/freedesktop/Accounts", ACCOUNTS, "CreateUser", "ssi", login, full.strip() or login, "1" if admin else "0", interactive=True)
            if got is None:
                raise Failed("The account wasn't made" + (": " + busctl.last.splitlines()[-1] if busctl.last else "."))
            path = (plain(got[0]) or [""])[0]
            if path:
                busctl("system", "call", ACCOUNTS, path, "org.freedesktop.Accounts.User", "SetPasswordMode", "i", "1", interactive=True)
            return f"Made an account for {full or login}. They choose their own password the first time they sign in."
        self._act("users", work, demo_change=lambda s: s["others"].append({"uid": 1003, "name": login, "full": full or login, "admin": admin, "picture": "", "path": "", "locked": False}))

    @Slot(int, bool)
    def removeUser(self, uid: int, files: bool) -> None:
        if uid == os.getuid() and not self._demo:
            return

        def work():
            if busctl("system", "call", ACCOUNTS, "/org/freedesktop/Accounts", ACCOUNTS, "DeleteUser", "xb", str(uid), "true" if files else "false", interactive=True) is None:
                raise Failed("The account wasn't removed" + (": " + busctl.last.splitlines()[-1] if busctl.last else "."))
            return "The account is gone" + (", with its files." if files else "; its files are still in /home.")
        self._act("users", work, demo_change=lambda s: s.update(others=[o for o in s["others"] if o["uid"] != uid]))

    @Slot(int, bool)
    def setAdmin(self, uid: int, admin: bool) -> None:
        person = next((o for o in self._state.get("users", {}).get("others", []) if o["uid"] == uid), None)
        if not person:
            return
        self._act("users", lambda: self._user_call(person["path"], "SetAccountType", "i", "1" if admin else "0", what="Changing what they can do") or "",
                  demo_change=lambda s: [o.update(admin=admin) for o in s["others"] if o["uid"] == uid])

    # -------------------------------------------------------------- default apps and start-up
    @Slot(str, str)
    def setDefault(self, category: str, app_id: str) -> None:
        def demo(s):
            for c in s["categories"]:
                if c["id"] == category:
                    pick = next((a for a in c["choices"] if a["id"] == app_id), None)
                    if pick:
                        c.update(current=app_id, currentName=pick["name"], currentIcon=pick["icon"])
        self._act("defaults", lambda: set_default(category, app_id) or "", demo_change=demo)

    @Slot(str)
    def addStartup(self, app_id: str) -> None:
        def work():
            app = self._known_apps().get(app_id)
            if not app:
                raise Failed("That app isn't installed.")
            (CONFIG / "autostart").mkdir(parents=True, exist_ok=True)
            shutil.copyfile(app["path"], CONFIG / "autostart" / app_id)
            return f"{app['name']} will open when you sign in."
        self._act("defaults", work)

    @Slot(str, bool)
    def setStartup(self, file: str, on: bool) -> None:
        path = Path(file)
        if path.parent != CONFIG / "autostart" and not self._demo:
            return
        self._act("defaults", lambda: kconfig_write(path, ["Desktop Entry"], "Hidden", "false" if on else "true") or "",
                  demo_change=lambda s: [x.update(on=on) for x in s["startup"] if x["file"] == file])

    @Slot(str)
    def removeStartup(self, file: str) -> None:
        path = Path(file)
        if path.parent != CONFIG / "autostart" and not self._demo:
            return
        self._act("defaults", lambda: path.unlink() or "", demo_change=lambda s: s.update(startup=[x for x in s["startup"] if x["file"] != file]))

    # -------------------------------------------------------------- privacy and security
    @Slot(bool)
    def setFirewall(self, on: bool) -> None:
        self._act("privacy", lambda: must(["pkexec", "ufw", "enable" if on else "disable"], None, 130, "The firewall") and
                  ("The firewall is on: nothing from outside can reach this computer unless you allow it." if on else "The firewall is off."),
                  demo_change=lambda s: s.update(firewall=on))

    @Slot(str, str, str, bool)
    def setPermission(self, table: str, obj: str, app: str, allow: bool) -> None:
        value = {"location": "EXACT" if allow else "NONE"}.get(table, "yes" if allow else "no")
        argv = ["flatpak", "permission-set", table, obj, app, value]
        if table == "location":
            argv.append("0")
        self._act("privacy", lambda: must(argv, what="Changing the permission") and "",
                  demo_change=lambda s: [p.update(allow=allow) for p in s["permissions"] if (p["table"], p["object"], p["app"]) == (table, obj, app)])

    @Slot(str, str, str)
    def forgetPermission(self, table: str, obj: str, app: str) -> None:
        self._act("privacy", lambda: must(["flatpak", "permission-remove", table, obj, app], what="Resetting the permission") and "The app will ask again next time.",
                  demo_change=lambda s: s.update(permissions=[p for p in s["permissions"] if (p["table"], p["object"], p["app"]) != (table, obj, app)]))

    @Slot(str, "QVariant")
    def setPrivacy(self, key: str, value) -> None:
        def work():
            lock = CONFIG / "kscreenlockerrc"
            if key == "lockOn":
                kconfig_write(lock, ["Daemon"], "Autolock", bool(value))
            elif key == "lockAfter":
                kconfig_write(lock, ["Daemon"], "Timeout", int(value))
            elif key == "lockOnWake":
                kconfig_write(lock, ["Daemon"], "LockOnResume", bool(value))
            elif key == "trashDays":
                group = [str(DATA / "Trash")]
                kconfig_write(CONFIG / "ktrashrc", group, "UseTimeLimit", int(value) > 0)
                if int(value) > 0:
                    kconfig_write(CONFIG / "ktrashrc", group, "Days", int(value))
            elif key == "remember":
                kconfig_write(CONFIG / "kactivitymanagerd-pluginsrc", ["Plugin-org.kde.ActivityManager.Resources.Scoring"], "what-to-remember", 0 if value else 2)
                if not value:
                    return clear_history()
            return ""
        self._act("privacy", work, demo_change=lambda s: s.update({key: value}))

    @Slot(result="QVariantList")
    def vpnFiles(self):
        """VPN files a provider would have you download: WireGuard .conf (with a [Peer]) and OpenVPN .ovpn."""
        out = []
        for folder in (HOME / "Downloads", HOME / "Documents", HOME):
            try:
                for f in sorted(folder.iterdir(), key=lambda p: -p.stat().st_mtime)[:400]:
                    if f.suffix.lower() == ".ovpn" or (f.suffix.lower() == ".conf" and "[Peer]" in _peek(str(f))):
                        out.append({"id": str(f), "label": f.name, "sub": ("WireGuard" if f.suffix.lower() == ".conf" else "OpenVPN") + " · " + str(folder).replace(str(HOME), "~")})
            except OSError:
                continue
        return out[:40]

    @Slot(str)
    def openApp(self, key: str) -> None:
        if self._demo or not re.fullmatch(r"[a-z]+", key):
            return
        import sys
        subprocess.Popen([sys.executable, str(Path(__file__).resolve().parent / "huginn_app.py"), key], start_new_session=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    @Slot()
    def clearHistory(self) -> None:
        self._act("privacy", clear_history, demo_change=lambda s: s.update(recent=0))


def clear_history() -> str:
    """Forget which files were opened lately (the list apps show under Recent), and nothing else."""
    gone = 0
    for f in (DATA / "recently-used.xbel",):
        try:
            f.write_text('<?xml version="1.0" encoding="UTF-8"?>\n<xbel version="1.0" xmlns:bookmark="http://www.freedesktop.org/standards/desktop-bookmarks" '
                         'xmlns:mime="http://www.freedesktop.org/standards/shared-mime-info">\n</xbel>\n', encoding="utf-8")
            gone += 1
        except OSError:
            pass
    db = DATA / "kactivitymanagerd" / "resources" / "database"
    for f in (db, db.with_name("database-wal"), db.with_name("database-shm")):
        try:
            f.unlink()
        except OSError:
            pass
    return "Recent files are forgotten."


def _peek(path: str) -> str:
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace")[:4000]
    except OSError:
        return ""
