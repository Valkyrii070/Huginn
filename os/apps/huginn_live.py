"""How an app tells the dock's live island what it is doing, and how a player app gets the standard media controls.

LiveReport ("LiveIsland" in an app's QML): report(key, props) says "this is going on" (a timer, an install, a screen
recording); the island shows it until end(key) or until the app quits. Buttons pressed in the island come back as
action(key, what). The shell side is org.huginn.Live on the session bus (shell/huginn_island.py). If the shell isn't
running, reports go nowhere and nothing breaks; when it starts again, what is still going on is sent again.

    props: kind     "timer" | "alarm" | "progress" | "screen" | "call" | "event" | "playing"
           title, sub
           glyph    a Glyph name for the round picture (optional)
           progress 0..1, or -1 when how far along isn't known
           ends     for a timer: when it rings (ms since 1970); total: its whole length (ms); paused: true/false;
                    left: ms left while paused
           actions  [{"id": "pause", "label": "Pause", "glyph": "pause", "tone": "primary" | "danger" | "go" | ""}]

Mpris ("Mpris" in Music, Podcasts and Video): the app appears as org.mpris.MediaPlayer2.huginn_<app>, so the live
island, the keyboard's media keys and any other MPRIS-aware tool can see and control what it plays.
update({title, artist, album, art, length, position, playing}) whenever any of that changes (times in ms);
command(what, value) when something asks it to play, pause, skip or seek (value: ms for "seek"/"setposition").
"""
import json
import sys
import time

from gi.repository import Gio, GLib
from PySide6.QtCore import QObject, Signal, Slot

LIVE = ("org.huginn.Live", "/org/huginn/Live", "org.huginn.Live")


def _bus():
    try:
        return Gio.bus_get_sync(Gio.BusType.SESSION, None)
    except GLib.Error as err:
        print("live: no session bus:", err.message, file=sys.stderr)
        return None


class LiveReport(QObject):
    action = Signal(str, str)

    def __init__(self, app: str, quiet: bool = False):
        super().__init__()
        self._app, self._now = app, {}
        self._bus = None if quiet else _bus()                # quiet: previews and screenshots tell nobody
        if self._bus:
            self._bus.signal_subscribe(LIVE[0], LIVE[2], "Action", LIVE[1], None, Gio.DBusSignalFlags.NONE, self._on_action)
            self._bus.signal_subscribe("org.freedesktop.DBus", "org.freedesktop.DBus", "NameOwnerChanged", "/org/freedesktop/DBus",
                                       LIVE[0], Gio.DBusSignalFlags.NONE, self._on_owner)

    def _id(self, key: str) -> str:
        return f"{self._app}:{key}"

    def _send(self, method: str, args) -> None:
        if self._bus:
            self._bus.call(LIVE[0], LIVE[1], LIVE[2], method, args, None, Gio.DBusCallFlags.NO_AUTO_START, 2000, None, None, None)

    @Slot(str, "QVariantMap")
    def report(self, key: str, props) -> None:
        props = dict(props or {})
        props.setdefault("app", self._app)
        if self._now.get(key) == props:
            return
        self._now[key] = props
        self._send("Set", GLib.Variant("(ss)", (self._id(key), json.dumps(props))))

    @Slot(str)
    def end(self, key: str) -> None:
        if self._now.pop(key, None) is not None:
            self._send("End", GLib.Variant("(s)", (self._id(key),)))

    def _on_action(self, _conn, _sender, _path, _iface, _signal, params) -> None:
        ident, what = params.unpack()
        prefix = self._app + ":"
        if ident.startswith(prefix) and ident[len(prefix):] in self._now:
            self.action.emit(ident[len(prefix):], what)

    def _on_owner(self, _conn, _sender, _path, _iface, _signal, params) -> None:
        _name, _old, new = params.unpack()
        if new:                                             # the shell (re)started: tell it what is still going on
            for key, props in self._now.items():
                self._send("Set", GLib.Variant("(ss)", (self._id(key), json.dumps(props))))


MPRIS_XML = """<node>
<interface name="org.mpris.MediaPlayer2">
  <method name="Raise"/><method name="Quit"/>
  <property name="CanQuit" type="b" access="read"/><property name="CanRaise" type="b" access="read"/>
  <property name="HasTrackList" type="b" access="read"/><property name="Identity" type="s" access="read"/>
  <property name="DesktopEntry" type="s" access="read"/>
  <property name="SupportedUriSchemes" type="as" access="read"/><property name="SupportedMimeTypes" type="as" access="read"/>
</interface>
<interface name="org.mpris.MediaPlayer2.Player">
  <method name="Next"/><method name="Previous"/><method name="Pause"/><method name="PlayPause"/><method name="Stop"/><method name="Play"/>
  <method name="Seek"><arg type="x" name="Offset" direction="in"/></method>
  <method name="SetPosition"><arg type="o" name="TrackId" direction="in"/><arg type="x" name="Position" direction="in"/></method>
  <method name="OpenUri"><arg type="s" name="Uri" direction="in"/></method>
  <signal name="Seeked"><arg type="x" name="Position"/></signal>
  <property name="PlaybackStatus" type="s" access="read"/><property name="Rate" type="d" access="readwrite"/>
  <property name="Metadata" type="a{sv}" access="read"/><property name="Volume" type="d" access="readwrite"/>
  <property name="Position" type="x" access="read"/><property name="MinimumRate" type="d" access="read"/>
  <property name="MaximumRate" type="d" access="read"/><property name="CanGoNext" type="b" access="read"/>
  <property name="CanGoPrevious" type="b" access="read"/><property name="CanPlay" type="b" access="read"/>
  <property name="CanPause" type="b" access="read"/><property name="CanSeek" type="b" access="read"/>
  <property name="CanControl" type="b" access="read"/>
</interface></node>"""
PATH = "/org/mpris/MediaPlayer2"
ROOT, PLAYER = "org.mpris.MediaPlayer2", "org.mpris.MediaPlayer2.Player"


class Mpris(QObject):
    command = Signal(str, float)

    def __init__(self, key: str, identity: str, desktop: str, quiet: bool = False):
        super().__init__()
        self._key, self._identity, self._desktop = key, identity, desktop
        self._quiet = quiet
        self._state = {"title": "", "artist": "", "album": "", "art": "", "length": 0, "position": 0, "playing": False, "track": 0}
        self._status, self._at = "Stopped", time.monotonic()
        self._bus, self._ids = None, []

    def _start(self) -> None:
        """Only once there is something to show: a player that hasn't played anything isn't announced."""
        if self._bus is not None:
            return
        self._bus = False if self._quiet else _bus()
        if not self._bus:
            self._bus = False
            return
        node = Gio.DBusNodeInfo.new_for_xml(MPRIS_XML)
        for iface in node.interfaces:
            self._ids.append(self._bus.register_object(PATH, iface, self._call, self._get, None))
        Gio.bus_own_name_on_connection(self._bus, f"org.mpris.MediaPlayer2.huginn_{self._key}", Gio.BusNameOwnerFlags.DO_NOT_QUEUE, None, None)

    def _position_us(self) -> int:
        pos = self._state["position"] + ((time.monotonic() - self._at) * 1000 if self._state["playing"] else 0)
        return int(max(0, pos) * 1000)

    def _metadata(self) -> dict:
        s = self._state
        meta = {"mpris:trackid": GLib.Variant("o", f"/org/huginn/{self._key}/track/{s['track']}")}
        if s["length"]:
            meta["mpris:length"] = GLib.Variant("x", int(s["length"] * 1000))
        if s["title"]:
            meta["xesam:title"] = GLib.Variant("s", s["title"])
        if s["artist"]:
            meta["xesam:artist"] = GLib.Variant("as", [s["artist"]])
        if s["album"]:
            meta["xesam:album"] = GLib.Variant("s", s["album"])
        if s["art"]:
            meta["mpris:artUrl"] = GLib.Variant("s", s["art"])
        return meta

    def _props(self, iface: str) -> dict:
        if iface == ROOT:
            return {"CanQuit": GLib.Variant("b", False), "CanRaise": GLib.Variant("b", True), "HasTrackList": GLib.Variant("b", False),
                    "Identity": GLib.Variant("s", self._identity), "DesktopEntry": GLib.Variant("s", self._desktop),
                    "SupportedUriSchemes": GLib.Variant("as", []), "SupportedMimeTypes": GLib.Variant("as", [])}
        return {"PlaybackStatus": GLib.Variant("s", self._status), "Rate": GLib.Variant("d", 1.0), "Metadata": GLib.Variant("a{sv}", self._metadata()),
                "Volume": GLib.Variant("d", 1.0), "Position": GLib.Variant("x", self._position_us()), "MinimumRate": GLib.Variant("d", 1.0),
                "MaximumRate": GLib.Variant("d", 1.0), "CanGoNext": GLib.Variant("b", True), "CanGoPrevious": GLib.Variant("b", True),
                "CanPlay": GLib.Variant("b", True), "CanPause": GLib.Variant("b", True), "CanSeek": GLib.Variant("b", bool(self._state["length"])),
                "CanControl": GLib.Variant("b", True)}

    def _get(self, _conn, _sender, _path, iface, name):
        return self._props(iface).get(name)

    def _call(self, _conn, _sender, _path, iface, method, params, inv) -> None:
        inv.return_value(None)
        if method == "Raise":
            self.command.emit("raise", 0)
        elif method in ("Play", "Pause", "PlayPause", "Next", "Previous", "Stop"):
            self.command.emit(method.lower(), 0)
        elif method == "Seek":
            self.command.emit("setposition", max(0, self._position_us() + params.unpack()[0]) / 1000)
        elif method == "SetPosition":
            self.command.emit("setposition", max(0, params.unpack()[1]) / 1000)

    def _changed(self, iface: str, names: list) -> None:
        if self._bus:
            props = self._props(iface)
            self._bus.emit_signal(None, PATH, "org.freedesktop.DBus.Properties", "PropertiesChanged",
                                  GLib.Variant("(sa{sv}as)", (iface, {n: props[n] for n in names}, [])))

    @Slot("QVariantMap")
    def update(self, data) -> None:
        data = dict(data or {})
        old = dict(self._state)
        expected = old["position"] + ((time.monotonic() - self._at) * 1000 if old["playing"] else 0)
        for k in ("title", "artist", "album", "art"):
            if k in data:
                self._state[k] = str(data[k] or "")
        for k in ("length", "position"):
            if k in data:
                self._state[k] = max(0.0, float(data[k] or 0))
        if "playing" in data:
            self._state["playing"] = bool(data["playing"])
        if self._state["title"] != old["title"] or self._state["art"] != old["art"]:
            self._state["track"] += 1
        self._at = time.monotonic()
        if not self._state["title"] and not self._state["playing"]:
            status = "Stopped"
        else:
            status = "Playing" if self._state["playing"] else "Paused"
        if status != "Stopped":
            self._start()
        names = []
        if status != self._status:
            self._status = status
            names.append("PlaybackStatus")
        if any(self._state[k] != old[k] for k in ("title", "artist", "album", "art", "length", "track")):
            names.append("Metadata")
        if names:
            self._changed(PLAYER, names)
        if "position" in data and abs(self._state["position"] - expected) > 2500 and not names and self._bus:                               # a jump, not the clock ticking: say so (Seeked)
            self._bus.emit_signal(None, PATH, PLAYER, "Seeked", GLib.Variant("(x)", (self._position_us(),)))
