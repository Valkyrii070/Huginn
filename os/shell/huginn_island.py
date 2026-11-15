"""The dock's live island: what is going on right now, and which of it gets the island.

Where it hears about things:
  * anything playing with the standard media controls (MPRIS): Music, Podcasts, Video, the Huginn browser (Netflix,
    YouTube…), Spotify and the like;
  * apps telling it, over org.huginn.Live on the session bus (apps/huginn_live.py): Clock's timer, App Store
    installs, Screenshot's screen recording;
  * the camera, the microphone and your screen: the Privacy Report's watcher (~/.local/state/huginn/privacy-now.json);
  * files still arriving in Downloads;
  * Calendar: an event starting within 10 minutes;
  * a call on your phone, through KDE Connect.

The rules, as decided with the mockups:
  * the most important thing gets the island; up to two more wait beside it in bubbles; clicking a bubble swaps it in;
  * order: a call, a timer or alarm going off, something playing, a timer counting down, an event, downloads/installs;
  * the screen, the camera and the microphone are not in that order: each says so in the island for a few seconds,
    then stays as a bubble for as long as it is on. They are never bumped and don't count in the two;
  * two things playing: the one whose window is NOT in front wins (its controls are what you can't see); otherwise
    the one that started last;
  * calls and alarms open the island by themselves (ringing).
"""
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

from gi.repository import Gio, GLib
from PySide6.QtCore import Property, QObject, QTimer, Signal, Slot

LIVE_XML = """<node><interface name="org.huginn.Live">
  <method name="Set"><arg type="s" name="id" direction="in"/><arg type="s" name="props" direction="in"/></method>
  <method name="End"><arg type="s" name="id" direction="in"/></method>
  <method name="Media"><arg type="s" name="what" direction="in"/><arg type="b" name="handled" direction="out"/></method>
  <signal name="Action"><arg type="s" name="id"/><arg type="s" name="action"/></signal>
</interface></node>"""
ROOT, PLAYER = "org.mpris.MediaPlayer2", "org.mpris.MediaPlayer2.Player"
MPRIS = "org.mpris.MediaPlayer2."
PHONE = "org.kde.kdeconnect.device.telephony"

RANK = {"call": 0, "alarm": 1, "playing": 2, "timer": 3, "paused": 3.5, "event": 4, "progress": 5}
PRIVACY = ("screen", "camera", "mic")
TONES = {"call": "#3DDC84", "alarm": "#A5B4FC", "timer": "#A5B4FC", "event": "#FF5470", "progress": "#22D3EE",
         "screen": "#FF5A5F", "camera": "#3DD6B5", "mic": "#FFB340", "playing": "#FF5FA2"}
APP_TONES = {"huginn-music": "#FF5FA2", "huginn-podcasts": "#D8B4FE", "huginn-video": "#8E6BFF", "huginn": "#7B61FF"}
BUBBLES = 2                 # besides the screen, camera and microphone
ANNOUNCE_MS = 4000          # how long the screen/camera/mic say so in the island before they become a bubble
PAUSED_KEEP_S = 120         # a paused player stays this long (so it can be picked up again), then goes
EVENT_BEFORE, EVENT_AFTER = 10 * 60, 5 * 60
DOWNLOAD_PARTS = ("*.part", "*.crdownload", "*.download")
STATE = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local/state") / "huginn"
LINK = re.compile(r"https?://[^\s<>\"']+")


def same_app(a: str, b: str) -> bool:
    """Is a player's DesktopEntry the window in front's app id? ('huginn-music' vs 'huginn-music.desktop', 'org.x.Y' vs 'y')"""
    def norm(s):
        s = (s or "").lower().removesuffix(".desktop")
        return s, s.rsplit(".", 1)[-1]
    if not a or not b:
        return False
    (fa, la), (fb, lb) = norm(a), norm(b)
    return fa == fb or la == lb


def arrange(items: list, front: str = "", pinned: str = "", announcing: str = "") -> tuple:
    """(main, bubbles, others, extra) from everything going on.
    main: what the island shows ({} for none); bubbles: what waits beside it; others: everything but main (the opened
    island lists them); extra: how many more there are than bubbles show."""
    priv = sorted((i for i in items if i["kind"] in PRIVACY), key=lambda i: PRIVACY.index(i["kind"]))
    rest = [i for i in items if i["kind"] not in PRIVACY]

    def key(i):
        kind = i["kind"]
        rank = RANK.get(kind, 6)
        if kind == "playing" and not i.get("playing", True):
            rank = RANK["paused"]
        in_front = 1 if kind == "playing" and same_app(i.get("desktop", ""), front) else 0
        return rank, in_front, -float(i.get("since", 0))
    rest.sort(key=key)
    by_id = {i["id"]: i for i in rest + priv}
    if rest and rest[0]["kind"] in ("call", "alarm"):
        main = rest[0]                                      # nothing beats these, not even a bubble you picked
    elif announcing in by_id:
        main = by_id[announcing]
    elif pinned in by_id and by_id[pinned]["kind"] not in PRIVACY:
        main = by_id[pinned]
    else:
        main = rest[0] if rest else {}
    waiting = [i for i in rest if i is not main]
    shown_priv = [p for p in priv if p is not main]
    return main, waiting[:BUBBLES] + shown_priv, waiting + shown_priv, max(0, len(waiting) - BUBBLES)


def _launch(desktop_id: str, uris=()) -> bool:
    try:
        info = Gio.DesktopAppInfo.new(desktop_id if desktop_id.endswith(".desktop") else desktop_id + ".desktop")
        return bool(info and info.launch_uris(list(uris), None))
    except (GLib.Error, TypeError):
        return False


def _open_uri(uri: str) -> None:
    try:
        Gio.AppInfo.launch_default_for_uri(uri, None)
    except GLib.Error as err:
        print("live: couldn't open", uri, err, file=sys.stderr)


class Live(QObject):
    changed = Signal()

    def __init__(self, demo: bool = False, scenario: str = ""):
        super().__init__()
        self._demo = demo
        self._items, self._players, self._owners, self._board = {}, {}, {}, {}
        self._front, self._pinned, self._announcing = "", "", ""
        self._seen_priv, self._dismissed, self._downloads_since = set(), set(), 0.0
        self._snapshot = None
        self._main, self._bubbles, self._others, self._extra = {}, [], [], 0
        self._announce = QTimer(self, singleShot=True, interval=ANNOUNCE_MS, timeout=self._announce_done)
        self._bus = None
        if demo:
            self._items = {i["id"]: i for i in demo_items(scenario)}
            self._announcing = next((i["id"] for i in self._items.values() if i.get("announce")), "")
            self._arrange()
            return
        self._calendar = None
        try:
            self._bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        except GLib.Error:
            self._bus = None
        if self._bus:
            node = Gio.DBusNodeInfo.new_for_xml(LIVE_XML)
            self._bus.register_object("/org/huginn/Live", node.interfaces[0], self._on_call, None, None)
            Gio.bus_own_name_on_connection(self._bus, "org.huginn.Live", Gio.BusNameOwnerFlags.REPLACE | Gio.BusNameOwnerFlags.ALLOW_REPLACEMENT, None, None)
            self._bus.signal_subscribe("org.freedesktop.DBus", "org.freedesktop.DBus", "NameOwnerChanged", "/org/freedesktop/DBus", None,
                                       Gio.DBusSignalFlags.NONE, self._on_owner)
            self._bus.signal_subscribe(None, "org.freedesktop.DBus.Properties", "PropertiesChanged", "/org/mpris/MediaPlayer2", None,
                                       Gio.DBusSignalFlags.NONE, self._on_props)
            self._bus.signal_subscribe(None, PLAYER, "Seeked", "/org/mpris/MediaPlayer2", None, Gio.DBusSignalFlags.NONE, self._on_seeked)
            self._bus.signal_subscribe(None, PHONE, "callReceived", None, None, Gio.DBusSignalFlags.NONE, self._on_phone)
            self._bus.call("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus", "ListNames", None, GLib.VariantType("(as)"),
                           Gio.DBusCallFlags.NONE, 2000, None, self._listed, None)
        for interval, fn in ((1500, self._read_privacy), (2000, self._read_downloads), (30000, self._read_calendar), (10000, self._arrange)):
            QTimer(self, interval=interval, timeout=fn).start()
        QTimer.singleShot(1500, self._read_calendar)

    # ------------------------------------------------------------------------------------------------ the result
    def _arrange(self) -> None:
        items = list(self._items.values()) + [p for p in (self._player_item(n) for n in self._players) if p]
        items = self._merge_screen(items)
        if self._pinned and not any(i["id"] == self._pinned for i in items):
            self._pinned = ""
        main, bubbles, others, extra = arrange(items, self._front, self._pinned, self._announcing)
        snap = json.dumps([main, bubbles, others, extra], sort_keys=True, default=str)
        if snap != self._snapshot:
            self._snapshot = snap
            self._main, self._bubbles, self._others, self._extra = main, bubbles, others, extra
            self.changed.emit()

    @staticmethod
    def _merge_screen(items: list) -> list:
        """Screenshot's own recording and the watcher's 'your screen is shared' are the same thing: one bubble, with
        Stop from the app."""
        reported = {i["kind"]: i for i in items if i["kind"] in PRIVACY and i.get("source") == "board"}
        out = []
        for i in items:
            if i["kind"] in PRIVACY and i.get("source") == "board":
                if not any(w["kind"] == i["kind"] and w.get("source") != "board" for w in items):
                    out.append(i)                           # the watcher hasn't seen it (yet): the app's own word stands
            elif i["kind"] in PRIVACY and i["kind"] in reported:
                r = reported[i["kind"]]
                out.append(dict(i, actions=list(r.get("actions") or []) + list(i.get("actions") or []), stopId=r["id"], title=r.get("title") or i["title"]))
            else:
                out.append(i)
        return out

    main = Property("QVariantMap", lambda self: self._main, notify=changed)
    bubbles = Property("QVariantList", lambda self: self._bubbles, notify=changed)
    others = Property("QVariantList", lambda self: self._others, notify=changed)
    extra = Property(int, lambda self: self._extra, notify=changed)
    active = Property(bool, lambda self: bool(self._main or self._bubbles), notify=changed)
    ringing = Property(bool, lambda self: self._main.get("kind") in ("call", "alarm"), notify=changed)

    @Property("QVariantMap", notify=changed)
    def privacy(self):
        on = {i["kind"] for i in [self._main] + self._bubbles if i}
        return {k: k in on for k in PRIVACY}

    # ------------------------------------------------------------------------------------------------ what you do
    @Slot(str)
    def pick(self, ident: str) -> None:
        """A bubble was clicked: it takes the island (until it ends, or a call or an alarm comes)."""
        self._pinned = ident
        self._arrange()

    @Slot(int)
    def cycle(self, step: int) -> None:
        """Scrolling over the island: the next thing takes it."""
        order = [self._main] + [b for b in self._bubbles if b.get("kind") not in PRIVACY] if self._main else []
        if len(order) > 1:
            self.pick(order[step % len(order)]["id"] if step > 0 else order[-1]["id"])

    @Slot(str)
    def setFront(self, app_id: str) -> None:
        self._front = app_id or ""
        self._arrange()

    @Slot(str, str)
    def act(self, ident: str, action: str) -> None:
        item = self._find(ident)
        if item is None:
            return
        if self._demo:
            print("live:", ident, action, file=sys.stderr)
            return
        if ident.startswith("mpris:"):
            name = ident[6:]
            method = {"playpause": "PlayPause", "play": "Play", "pause": "Pause", "next": "Next", "previous": "Previous", "raise": "Raise"}.get(action)
            if method and self._bus:
                self._bus.call(name, "/org/mpris/MediaPlayer2", ROOT if method == "Raise" else PLAYER, method, None, None, Gio.DBusCallFlags.NONE, 2000, None, None, None)
            return
        if item.get("source") == "board" or (action == "stop" and item.get("stopId")):
            target = item.get("stopId") if action == "stop" and item.get("stopId") else ident
            if self._bus:
                self._bus.emit_signal(None, "/org/huginn/Live", "org.huginn.Live", "Action", GLib.Variant("(ss)", (target, action)))
            return
        if ident == "downloads":
            _open_uri(Path(item.get("folder") or Path.home() / "Downloads").as_uri())
        elif ident.startswith("event:"):
            if action == "join" and item.get("url"):
                _open_uri(item["url"])
            elif action == "hide":
                self._dismissed.add(ident)
                self._items.pop(ident, None)
                self._arrange()
            else:
                _launch("huginn-calendar")
        elif ident.startswith("call:"):
            if action == "silence" and self._bus:
                self._bus.call("org.kde.kdeconnect", item["path"], PHONE, "sendMutePacket", None, None, Gio.DBusCallFlags.NONE, 2000, None, None, None)
            elif action.startswith("reply:") and shutil.which("kdeconnect-cli"):
                subprocess.Popen(["kdeconnect-cli", "-d", item["device"], "--destination", item["number"], "--send-sms", action[6:]],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                item["replied"] = action[6:]
                self._arrange()
            else:
                _launch("huginn-phone")
        elif item["kind"] in PRIVACY:
            _launch("huginn-privacy")

    @Slot(str, result=str)
    def openApp(self, ident: str) -> str:
        """The island was clicked: go to what it is about. Returns the app's name for the dock to bring forward or
        start, or "" when it was taken care of here."""
        item = self._find(ident)
        if not item:
            return ""
        if ident.startswith("mpris:"):
            self.act(ident, "raise")
            return ""
        if ident == "downloads" or ident.startswith("event:") or ident.startswith("call:"):
            self.act(ident, "open")
            return ""
        if item["kind"] in PRIVACY and item.get("source") != "board":
            self.act(ident, "report")
            return ""
        return item.get("app", "")

    @Slot(str, float)
    def seek(self, ident: str, ms: float) -> None:
        name = ident[6:] if ident.startswith("mpris:") else ""
        p = self._players.get(name)
        if not p or not self._bus:
            return
        track = p["meta"].get("mpris:trackid") or "/org/mpris/MediaPlayer2/TrackList/NoTrack"
        self._bus.call(name, "/org/mpris/MediaPlayer2", PLAYER, "SetPosition", GLib.Variant("(ox)", (track, int(ms * 1000))), None,
                       Gio.DBusCallFlags.NONE, 2000, None, None, None)
        p["position"], p["posAt"] = ms, time.time() * 1000
        self._arrange()

    @Slot(str)
    def refresh(self, ident: str) -> None:
        """The island was opened on a player: ask where it is now (players don't announce their position)."""
        if ident.startswith("mpris:") and self._bus:
            self._get_position(ident[6:])

    def media(self, what: str) -> bool:
        """The keyboard's media keys: they work on whatever is playing in the island (or the first player)."""
        target = self._main if self._main.get("kind") == "playing" else next((o for o in self._others if o.get("kind") == "playing"), None)
        if not target:
            return False
        self.act(target["id"], {"playPause": "playpause", "play": "play", "pause": "pause", "next": "next", "previous": "previous"}.get(what, "playpause"))
        return True

    def _find(self, ident: str):
        return next((i for i in [self._main] + self._others if i and i.get("id") == ident), None)

    # ------------------------------------------------------------------------------------------------ apps telling it
    def _on_call(self, conn, sender, path, iface, method, params, inv) -> None:
        if method == "Set":
            ident, raw = params.unpack()
            try:
                props = json.loads(raw)
            except ValueError:
                props = None
            if not isinstance(props, dict):
                inv.return_dbus_error("org.huginn.Live.Error", "props must be a JSON object")
                return
            inv.return_value(None)
            old = self._items.get(ident, {})
            item = {k: v for k, v in props.items() if isinstance(k, str)}
            item.update(id=ident, source="board", sender=sender, kind=str(props.get("kind") or "progress"), since=old.get("since") or time.time())
            item.setdefault("tone", TONES.get(item["kind"], "#22D3EE"))
            self._items[ident] = item
            self._board[ident] = sender
            self._arrange()
        elif method == "End":
            inv.return_value(None)
            ident = params.unpack()[0]
            if self._items.pop(ident, None) is not None:
                self._board.pop(ident, None)
                self._arrange()
        elif method == "Media":
            inv.return_value(GLib.Variant("(b)", (self.media(params.unpack()[0]),)))
        else:
            inv.return_dbus_error("org.freedesktop.DBus.Error.UnknownMethod", method)

    def _on_owner(self, _c, _s, _p, _i, _sig, params) -> None:
        name, old, new = params.unpack()
        if name.startswith(MPRIS):
            if new:
                self._add_player(name)
            elif self._players.pop(name, None) is not None:
                self._arrange()
        elif not new and name.startswith(":"):
            gone = [i for i, owner in self._board.items() if owner == name]
            for i in gone:
                self._board.pop(i, None)
                self._items.pop(i, None)
            if gone:
                self._arrange()

    # ------------------------------------------------------------------------------------------------ players (MPRIS)
    def _listed(self, bus, res, _data) -> None:
        try:
            names = bus.call_finish(res).unpack()[0]
        except GLib.Error:
            return
        for n in names:
            if n.startswith(MPRIS):
                self._add_player(n)

    def _add_player(self, name: str) -> None:
        if name in self._players or not self._bus:
            return
        self._players[name] = {"status": "Stopped", "meta": {}, "identity": "", "desktop": "", "position": 0.0, "posAt": 0.0, "rate": 1.0,
                               "since": time.time(), "pausedAt": 0.0}
        dbus = ("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus")

        def owner(bus, res, _):
            try:
                self._owners[bus.call_finish(res).unpack()[0]] = name
            except GLib.Error:
                pass
        self._bus.call(*dbus, "GetNameOwner", GLib.Variant("(s)", (name,)), GLib.VariantType("(s)"), Gio.DBusCallFlags.NONE, 2000, None, owner, None)
        for iface in (ROOT, PLAYER):
            self._bus.call(name, "/org/mpris/MediaPlayer2", "org.freedesktop.DBus.Properties", "GetAll", GLib.Variant("(s)", (iface,)),
                           GLib.VariantType("(a{sv})"), Gio.DBusCallFlags.NONE, 2000, None, self._got_all, (name, iface))

    def _got_all(self, bus, res, data) -> None:
        name, iface = data
        try:
            props = bus.call_finish(res).unpack()[0]
        except GLib.Error:
            return
        self._player_update(name, iface, props)

    def _player_update(self, name: str, iface: str, props: dict) -> None:
        p = self._players.get(name)
        if p is None:
            return
        if iface == ROOT:
            p["identity"] = str(props.get("Identity", p["identity"]) or "")
            p["desktop"] = str(props.get("DesktopEntry", p["desktop"]) or "")
        else:
            if "PlaybackStatus" in props:
                status = str(props["PlaybackStatus"])
                if status == "Playing" and p["status"] != "Playing":
                    p["since"] = time.time()                 # "the newest" means the one that started playing last
                    self._get_position(name)
                if status == "Paused" and p["status"] != "Paused":
                    p["pausedAt"] = time.time()
                    self._get_position(name)
                p["status"] = status
            if "Metadata" in props:
                meta = props["Metadata"] or {}
                if meta.get("mpris:trackid") != p["meta"].get("mpris:trackid") or meta.get("xesam:title") != p["meta"].get("xesam:title"):
                    p["position"], p["posAt"] = 0.0, time.time() * 1000
                    self._get_position(name)
                p["meta"] = meta
            if "Position" in props:
                p["position"], p["posAt"] = float(props["Position"] or 0) / 1000, time.time() * 1000
            if "Rate" in props:
                p["rate"] = float(props["Rate"] or 1.0)
        self._arrange()

    def _get_position(self, name: str) -> None:
        def got(bus, res, _):
            try:
                value = bus.call_finish(res).unpack()[0]
            except GLib.Error:
                return
            p = self._players.get(name)
            if p is not None:
                p["position"], p["posAt"] = float(value or 0) / 1000, time.time() * 1000
                self._arrange()
        self._bus.call(name, "/org/mpris/MediaPlayer2", "org.freedesktop.DBus.Properties", "Get", GLib.Variant("(ss)", (PLAYER, "Position")),
                       GLib.VariantType("(v)"), Gio.DBusCallFlags.NONE, 1500, None, got, None)

    def _on_props(self, _c, sender, _p, _i, _sig, params) -> None:
        iface, changed, invalidated = params.unpack()
        name = self._owners.get(sender)
        if name is None or iface not in (ROOT, PLAYER):
            return
        self._player_update(name, iface, changed)
        if invalidated:
            self._bus.call(name, "/org/mpris/MediaPlayer2", "org.freedesktop.DBus.Properties", "GetAll", GLib.Variant("(s)", (iface,)),
                           GLib.VariantType("(a{sv})"), Gio.DBusCallFlags.NONE, 2000, None, self._got_all, (name, iface))

    def _on_seeked(self, _c, sender, _p, _i, _sig, params) -> None:
        name = self._owners.get(sender)
        if name in self._players:
            self._players[name]["position"], self._players[name]["posAt"] = params.unpack()[0] / 1000, time.time() * 1000
            self._arrange()

    def _player_item(self, name: str):
        p = self._players[name]
        status = p["status"]
        if status not in ("Playing", "Paused") or (status == "Paused" and time.time() - p["pausedAt"] > PAUSED_KEEP_S):
            return None
        meta, playing = p["meta"], status == "Playing"
        ident = p["identity"] or name[len(MPRIS):].split(".")[0].replace("huginn_", "").title()
        title = str(meta.get("xesam:title") or "")
        artist = meta.get("xesam:artist") or []
        artist = ", ".join(artist) if isinstance(artist, list) else str(artist)
        return {"id": "mpris:" + name, "kind": "playing", "app": ident, "desktop": p["desktop"], "title": title or ident,
                "sub": " · ".join(x for x in (artist, ident) if x) if title else ("Playing" if playing else "Paused"),
                "art": str(meta.get("mpris:artUrl") or ""), "length": float(meta.get("mpris:length") or 0) / 1000,
                "position": p["position"], "posAt": p["posAt"], "rate": p["rate"], "playing": playing, "since": p["since"],
                "tone": APP_TONES.get((p["desktop"] or "").lower().removesuffix(".desktop"), TONES["playing"]), "glyph": "music"}

    # ------------------------------------------------------------------------------------------------ camera, mic, screen
    def _read_privacy(self) -> None:
        now_file = STATE / "privacy-now.json"
        try:
            fresh = time.time() - now_file.stat().st_mtime < 15     # the watcher writes every 3 s while it runs
            rows = json.loads(now_file.read_text(encoding="utf-8")) if fresh else []
        except (OSError, ValueError):
            rows = []
        by = {}
        for r in rows if isinstance(rows, list) else []:
            if isinstance(r, dict) and r.get("what") in PRIVACY:
                by.setdefault(r["what"], []).append({"name": str(r.get("app") or "An app"), "since": float(r.get("start") or time.time())})
        changed = False
        for what in PRIVACY:
            ident = "privacy:" + what
            apps = by.get(what)
            if not apps:
                if self._items.pop(ident, None) is not None:
                    changed = True
                self._seen_priv.discard(ident)
                continue
            item = privacy_item(what, apps)
            if self._items.get(ident, {}).get("apps") != item["apps"]:
                self._items[ident] = item
                changed = True
            if ident not in self._seen_priv:                 # it just started: say so in the island for a moment
                self._seen_priv.add(ident)
                self._announcing = ident
                self._announce.start()
        if changed:
            self._arrange()

    def _announce_done(self) -> None:
        self._announcing = ""
        self._arrange()

    # ------------------------------------------------------------------------------------------------ downloads, calendar, phone
    def _read_downloads(self) -> None:
        folder = Path.home() / "Downloads"
        parts = [f for pattern in DOWNLOAD_PARTS for f in folder.glob(pattern)] if folder.is_dir() else []
        if not parts:
            self._downloads_since = 0.0
            if self._items.pop("downloads", None) is not None:
                self._arrange()
            return
        self._downloads_since = self._downloads_since or time.time()
        name = parts[0].name
        for suffix in (".part", ".crdownload", ".download"):
            name = name.removesuffix(suffix)
        title = f"Downloading {name}" if len(parts) == 1 else f"Downloading {len(parts)} files"
        item = {"id": "downloads", "kind": "progress", "app": "Files", "title": title, "sub": "Downloads", "glyph": "download", "progress": -1,
                "tone": "#38B6FF", "since": self._downloads_since, "folder": str(folder), "actions": [{"id": "open", "label": "Show", "glyph": "folder"}]}
        if self._items.get("downloads", {}).get("title") != title:
            self._items["downloads"] = item
            self._arrange()

    def _read_calendar(self) -> None:
        try:
            if self._calendar is None:
                apps = [Path("/usr/share/huginn-apps"), Path(__file__).resolve().parent.parent / "apps"]
                for d in apps:
                    if (d / "huginn_app.py").exists() and str(d) not in sys.path:
                        sys.path.append(str(d))
                from huginn_app import Calendar
                self._calendar = Calendar(False)
            rows = self._calendar.upcoming
        except Exception:                                   # noqa: BLE001 - no Calendar, or its file unreadable
            rows = []
        found = calendar_items(rows, dt.datetime.now(), self._dismissed)
        old = {k for k in self._items if k.startswith("event:")}
        for k in old - set(found):
            self._items.pop(k, None)
        self._items.update(found)
        if old or found:
            self._arrange()

    def _on_phone(self, _c, _s, path, _i, _sig, params) -> None:
        event, number, name = params.unpack()
        ident = "call:" + (number or name or "unknown")
        if event == "ringing":
            parts = path.strip("/").split("/")
            device = parts[-2] if len(parts) >= 2 else ""
            self._items[ident] = {"id": ident, "kind": "call", "app": "Phone", "title": name or number or "Unknown caller", "sub": "Calling · your phone",
                                  "number": number, "device": device, "path": path, "glyph": "phone", "tone": TONES["call"], "since": time.time(),
                                  "initials": initials(name or number), "replies": ["Can't talk now", "I'll call you back soon"],
                                  "actions": [{"id": "silence", "label": "Silence", "glyph": "mute"}, {"id": "open", "label": "Phone", "glyph": "phone"}]}
            QTimer.singleShot(60000, lambda: self._end_call(ident))
        else:
            self._end_call(ident)
            return
        self._arrange()

    def _end_call(self, ident: str) -> None:
        if self._items.pop(ident, None) is not None:
            self._arrange()


def initials(text: str) -> str:
    words = [w for w in re.split(r"\s+", text or "") if w and w[0].isalpha()]
    return ("".join(w[0] for w in words[:2]) or "#").upper()


def privacy_item(what: str, apps: list) -> dict:
    names = sorted({a["name"] for a in apps})
    since = min(a["since"] for a in apps)
    doing = {"screen": "sharing your screen", "camera": "using the camera", "mic": "using the microphone"}[what]
    who = names[0] if len(names) == 1 else f"{len(names)} apps"
    return {"id": "privacy:" + what, "kind": what, "app": names[0], "title": f"{who} {'is' if len(names) == 1 else 'are'} {doing}",
            "sub": "Since " + time.strftime("%H:%M", time.localtime(since)), "apps": [{"name": n, "since": min(a["since"] for a in apps if a["name"] == n)} for n in names],
            "glyph": {"screen": "display", "camera": "camera", "mic": "mic"}[what], "tone": TONES[what], "since": since,
            "actions": [{"id": "report", "label": "Privacy Report", "glyph": "shield"}]}


def calendar_items(rows: list, now: dt.datetime, dismissed=()) -> dict:
    """Calendar events (not reminders) starting within 10 minutes, or started up to 5 minutes ago."""
    out = {}
    for e in rows or []:
        if e.get("reminder") or not e.get("time"):
            continue
        try:
            start = dt.datetime.fromisoformat(f"{e['date']}T{e['time']}")
        except (KeyError, ValueError):
            continue
        gap = (start - now).total_seconds()
        ident = f"event:{e.get('id', e.get('title'))}@{e['date']}"
        if not (-EVENT_AFTER <= gap <= EVENT_BEFORE) or ident in dismissed:
            continue
        url = next((m.group(0) for v in e.values() if isinstance(v, str) for m in [LINK.search(v)] if m), "")
        actions = ([{"id": "join", "label": "Join", "glyph": "video", "tone": "go"}] if url else []) + \
                  [{"id": "open", "label": "Calendar", "glyph": "calendar"}, {"id": "hide", "label": "Hide", "glyph": "x"}]
        out[ident] = {"id": ident, "kind": "event", "app": "Calendar", "title": e.get("title") or "Event", "starts": start.timestamp() * 1000,
                      "sub": e.get("time", ""), "url": url, "glyph": "calendar", "tone": TONES["event"], "since": start.timestamp(), "actions": actions}
    return out


def demo_items(scenario: str) -> list:
    """What the previews show: Music playing, a download and a Clock timer (and a call, or the screen shared)."""
    now = time.time()
    music = {"id": "mpris:demo.music", "kind": "playing", "app": "Music", "desktop": "huginn-music", "title": "Northbound", "sub": "Late drive · Music",
             "art": "", "length": 225000.0, "position": 161000.0, "posAt": now * 1000, "rate": 1.0, "playing": True, "since": now - 60, "tone": "#FF5FA2", "glyph": "music"}
    download = {"id": "downloads", "kind": "progress", "app": "Files", "title": "Downloading huginn-os-0.2.iso", "sub": "Downloads", "glyph": "download",
                "progress": 0.6, "tone": "#38B6FF", "since": now - 120, "actions": [{"id": "open", "label": "Show", "glyph": "folder"}]}
    timer = {"id": "Clock:timer", "kind": "timer", "app": "Clock", "title": "Timer", "sub": "Clock", "glyph": "bell", "ends": now * 1000 + 222000, "total": 300000,
             "paused": False, "tone": "#A5B4FC", "since": now - 78, "source": "board",
             "actions": [{"id": "add60", "label": "+1 min"}, {"id": "pause", "label": "Pause", "glyph": "pause", "tone": "primary"}, {"id": "cancel", "label": "Cancel", "glyph": "x"}]}
    if scenario == "none":
        return []
    if scenario == "one":
        return [music]
    if scenario == "call":
        call = {"id": "call:+3545551234", "kind": "call", "app": "Phone", "title": "Kári Jónsson", "sub": "Calling · your phone", "glyph": "phone", "tone": "#3DDC84",
                "initials": "KJ", "since": now, "replies": ["Can't talk now", "I'll call you back soon"],
                "actions": [{"id": "silence", "label": "Silence", "glyph": "mute"}, {"id": "open", "label": "Phone", "glyph": "phone"}]}
        return [music, download, call]
    if scenario in ("share", "announce"):
        share = dict(privacy_item("screen", [{"name": "Discord", "since": now - 300}]), announce=scenario == "announce")
        cam = privacy_item("camera", [{"name": "Discord", "since": now - 300}])
        return [music, share, cam]
    if scenario == "event":
        ev = calendar_items([{"id": "1", "date": dt.date.today().isoformat(), "time": (dt.datetime.now() + dt.timedelta(minutes=5)).strftime("%H:%M"),
                              "title": "Design review", "location": "https://meet.example.org/design"}], dt.datetime.now())
        return list(ev.values()) + [download]
    return [music, download, timer]
