"""Open… for any Huginn app: the desktop's own Open window (Huginn's, through the desktop portal), asked from QML.

    Picker.open("Open a document", [["Documents", "*.odt *.docx *.md *.txt"]], function (paths) { ... })

The function gets the chosen paths (an empty list if nothing was chosen, or if there's no portal to ask).
"""
from __future__ import annotations

import secrets
import sys
import urllib.parse
import weakref

from PySide6.QtCore import QObject, Slot
from PySide6.QtQml import QJSValue

PORTAL = ("org.freedesktop.portal.Desktop", "/org/freedesktop/portal/desktop", "org.freedesktop.portal.FileChooser")


class Picker(QObject):
    def __init__(self, engine, app: str = ""):
        super().__init__()
        self._engine, self._app, self._waiting = weakref.ref(engine), app, {}     # (weak: the app tears the engine down first)

    @Slot(str, "QVariantList", QJSValue)
    def open(self, title: str, filters, done: QJSValue) -> None:
        self._ask("OpenFile", title, filters, done, multiple=False)

    @Slot(str, "QVariantList", QJSValue)
    def openMany(self, title: str, filters, done: QJSValue) -> None:
        self._ask("OpenFile", title, filters, done, multiple=True)

    def _ask(self, method: str, title: str, filters, done: QJSValue, multiple: bool) -> None:
        try:
            from gi.repository import Gio, GLib
            bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        except Exception as err:                                  # noqa: BLE001 (no bus: nothing to ask)
            print("picker:", err, file=sys.stderr)
            self._answer(done, [])
            return
        token = "huginn" + secrets.token_hex(6)
        sender = bus.get_unique_name().lstrip(":").replace(".", "_")
        handle = f"/org/freedesktop/portal/desktop/request/{sender}/{token}"
        rows = []
        for f in filters or []:
            name, patterns = (list(f) + ["", ""])[:2]
            globs = [(0, g) for g in str(patterns).split() if g]
            if globs:
                rows.append((str(name), globs))
        options = {"handle_token": GLib.Variant("s", token), "multiple": GLib.Variant("b", multiple), "modal": GLib.Variant("b", True)}
        if rows:
            options["filters"] = GLib.Variant("a(sa(us))", rows)
            options["current_filter"] = GLib.Variant("(sa(us))", rows[0])

        def answered(_c, _s, _p, _i, _sig, params):
            sub = self._waiting.pop(handle, None)
            if sub is not None:
                bus.signal_unsubscribe(sub)
            code, results = params.unpack()
            uris = results.get("uris", []) if code == 0 else []
            paths = [urllib.parse.unquote(urllib.parse.urlparse(u).path) for u in uris if u.startswith("file://")]
            self._answer(done, paths)
        self._waiting[handle] = bus.signal_subscribe(PORTAL[0], "org.freedesktop.portal.Request", "Response", handle, None,
                                                     Gio.DBusSignalFlags.NONE, answered)

        def asked(source, result):
            try:
                source.call_finish(result)
            except GLib.Error as err:                             # no portal running: say nothing was chosen
                print("picker: the desktop portal didn't answer:", err.message, file=sys.stderr)
                sub = self._waiting.pop(handle, None)
                if sub is not None:
                    bus.signal_unsubscribe(sub)
                self._answer(done, [])
        bus.call(PORTAL[0], PORTAL[1], PORTAL[2], method, GLib.Variant("(ssa{sv})", ("", title, options)), None,
                 Gio.DBusCallFlags.NONE, -1, None, asked)

    def _answer(self, done: QJSValue, paths: list) -> None:
        engine = self._engine()
        if engine is not None and done is not None and done.isCallable():
            done.call([engine.toScriptValue(paths)])
