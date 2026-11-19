"""An app's menus, for the top bar's one menu (the app's name in the bar opens it).

Every Huginn app answers on the session bus as org.huginn.App.p<pid> (/org/huginn/App, interface org.huginn.App):
Menus() gives its menus as JSON and Trigger(id) does one. The shell finds the app in front by its window's process.

What's in them: About <App> and <App> Settings… first; then the app's own groups (APP_MENUS below), with Edit
(undo, cut, copy, paste… on whatever has the keyboard), View and Window for every app, and Help last; Minimise,
Close and Quit at the bottom. An item does one of:
    "short:Ctrl+N"   the app's own shortcut for it (its Shortcut is set off, as if the keys were pressed)
    "edit:copy"      cut/copy/paste/undo/redo/selectAll on the field that has the keyboard
    "backend:save"   a method of the app's backend, no arguments
    "qml:name"       a function of the app's window; "qml:apply:bold" passes one word
    "open:<path>"    the backend opens a file (Open recent)
    "win:…"          minimise, zoom, fullscreen, close; "app:quit", "app:help", "app:about", "app:settings"
"""
from __future__ import annotations

import json
import os
import sys
import weakref
from pathlib import Path

from gi.repository import Gio, GLib
from PySide6.QtCore import QEvent, QKeyCombination, QMetaObject, QObject, Q_ARG, Qt, Slot
from PySide6.QtGui import QGuiApplication, QKeyEvent, QKeySequence, QWindow
from PySide6.QtQml import QJSValue

XML = """<node><interface name="org.huginn.App">
  <method name="Menus"><arg type="s" name="json" direction="out"/></method>
  <method name="Trigger"><arg type="s" name="id" direction="in"/></method>
</interface></node>"""

SEP = {"sep": True}


def item(label, act, keys="", **more):
    return dict(label=label, id=act, keys=keys, **more)


EDIT = [item("Undo", "edit:undo", "Ctrl+Z"), item("Redo", "edit:redo", "Ctrl+Shift+Z"), SEP,
        item("Cut", "edit:cut", "Ctrl+X"), item("Copy", "edit:copy", "Ctrl+C"), item("Paste", "edit:paste", "Ctrl+V"),
        item("Select All", "edit:selectAll", "Ctrl+A")]
OFFICE_FILE = [item("New", "backend:create", "Ctrl+N"), item("Open…", "qml:openFile", "Ctrl+O"), item("Open recent", "recent"), SEP,
               item("Save", "backend:save", "Ctrl+S"), item("Export as PDF…", "qml:exportPdf", "Ctrl+Shift+E"), item("Share…", "qml:share")]

APP_MENUS = {
    "writer": [("File", OFFICE_FILE), ("Edit", EDIT + [SEP, item("Find…", "qml:find", "Ctrl+F")]),
               ("Format", [item("Bold", "qml:apply:bold", "Ctrl+B"), item("Italic", "qml:apply:italic", "Ctrl+I"), item("Underline", "qml:apply:underline", "Ctrl+U"), SEP,
                           item("Bigger", "qml:apply:bigger", "Ctrl+]"), item("Smaller", "qml:apply:smaller", "Ctrl+["), SEP,
                           item("Align left", "qml:apply:left"), item("Centre", "qml:apply:center"), item("Align right", "qml:apply:right"), item("Justify", "qml:apply:justify"), SEP,
                           item("Bulleted list", "qml:apply:bullet"), item("Numbered list", "qml:apply:number")]),
               ("Insert", [item("Picture…", "qml:insertImage"), item("Table", "qml:insertTable")])],
    "sheets": [("File", OFFICE_FILE), ("Edit", EDIT), ("Insert", [item("Row above", "qml:insertRow"), item("Column left", "qml:insertColumn"), item("Chart", "qml:insertChart")]),
               ("Format", [item("Bold", "qml:apply:bold", "Ctrl+B"), item("Number", "qml:apply:number"), item("Currency", "qml:apply:currency"), item("Percent", "qml:apply:percent")])],
    "slides": [("File", OFFICE_FILE), ("Edit", EDIT), ("Slide", [item("New slide", "qml:newSlide", "Ctrl+M"), item("Duplicate slide", "qml:duplicateSlide"), item("Delete slide", "qml:deleteSlide")]),
               ("View", [item("Present", "qml:present", "F5")])],
    "files": [("File", [item("New window", "app:newWindow", "Ctrl+N"), item("New folder", "qml:newFolder", "Ctrl+Shift+N"), item("New tab", "qml:newTab", "Ctrl+T"), SEP,
                        item("Open", "qml:openSelected", "Return"), item("Show in a new tab", "qml:openInTab"), SEP, item("Move to the Bin", "qml:trashSelected", "Delete")]),
              ("Edit", EDIT + [SEP, item("Find…", "qml:find", "Ctrl+F")]),
              ("View", [item("As icons", "qml:setGrid:true", "Ctrl+1"), item("As a list", "qml:setGrid:false", "Ctrl+2"), SEP,
                        item("Show hidden files", "qml:toggleHidden", "Ctrl+H")]),
              ("Go", [item("Back", "qml:goBack", "Alt+Left"), item("Forward", "qml:goForward", "Alt+Right"), item("Up", "qml:goUp", "Alt+Up"), SEP,
                      item("Home", "qml:goPlace:home"), item("Documents", "qml:goPlace:documents"), item("Downloads", "qml:goPlace:downloads"), item("Pictures", "qml:goPlace:pictures")])],
    "notes": [("File", [item("New note", "qml:newNote", "Ctrl+N"), item("Send by Mail", "backend:sendByMail")]), ("Edit", EDIT + [SEP, item("Find…", "qml:find", "Ctrl+F")]),
              ("Format", [item("Heading", "qml:apply:h1"), item("Checklist", "qml:apply:check"), item("Bulleted list", "qml:apply:bullets")])],
    "mail": [("Message", [item("New message", "short:Ctrl+N", "Ctrl+N"), item("Reply", "short:Ctrl+R", "Ctrl+R"), item("Send", "short:Ctrl+Return", "Ctrl+Enter"), SEP,
                          item("Delete", "short:Delete", "Delete")]),
             ("Edit", EDIT + [SEP, item("Find…", "short:Ctrl+F", "Ctrl+F")]), ("Mailbox", [item("Get new mail", "short:F5", "F5")])],
    "calendar": [("File", [item("New event", "qml:newEvent", "Ctrl+N"), item("Import…", "qml:importFile")]), ("Edit", EDIT),
                 ("View", [item("Today", "backend:today", "Ctrl+T"), item("Month", "qml:setView:month"), item("Week", "qml:setView:week")])],
    "code": [("File", [item("New file", "short:Ctrl+N", "Ctrl+N"), item("Open…", "short:Ctrl+O", "Ctrl+O"), item("Save", "short:Ctrl+S", "Ctrl+S"),
                       item("Save all", "short:Ctrl+Alt+S", "Ctrl+Alt+S"), SEP, item("Close tab", "short:Ctrl+W", "Ctrl+W")]),
             ("Edit", EDIT + [SEP, item("Find…", "short:Ctrl+F", "Ctrl+F"), item("Replace…", "short:Ctrl+H", "Ctrl+H"), item("Find in files…", "short:Ctrl+Shift+F", "Ctrl+Shift+F")]),
             ("Go", [item("Go to file…", "short:Ctrl+P", "Ctrl+P"), item("Go to line…", "short:Ctrl+G", "Ctrl+G"), item("Go to symbol…", "short:Ctrl+Shift+O", "Ctrl+Shift+O"),
                     item("Command palette…", "short:Ctrl+Shift+P", "Ctrl+Shift+P")]),
             ("Run", [item("Run", "short:F5", "F5"), item("Run without debugging", "short:Ctrl+F5", "Ctrl+F5"), item("Stop", "short:Shift+F5", "Shift+F5")]),
             ("View", [item("Sidebar", "short:Ctrl+B", "Ctrl+B"), item("Terminal", "short:Ctrl+`", "Ctrl+`"), item("Split", "short:Ctrl+\\", "Ctrl+\\"),
                       item("Word wrap", "short:Alt+Z", "Alt+Z"), SEP, item("Zoom in", "short:Ctrl+=", "Ctrl++"), item("Zoom out", "short:Ctrl+-", "Ctrl+−")])],
    "terminal": [("Shell", [item("New tab", "qml:newTab", "Ctrl+Shift+T"), item("Close tab", "qml:closeTab", "Ctrl+Shift+W")]),
                 ("Edit", [item("Copy", "qml:copy", "Ctrl+Shift+C"), item("Paste", "qml:paste", "Ctrl+Shift+V"), SEP, item("Find…", "qml:find", "Ctrl+Shift+F")])],
    # the pro apps: their own groups, from the shortcuts they already have (an item shows only if its shortcut is there)
    "easel": [("File", [item("New…", "short:Ctrl+N", "Ctrl+N"), item("Open…", "short:Ctrl+O", "Ctrl+O"), SEP, item("Save", "short:Ctrl+S", "Ctrl+S"),
                        item("Save as…", "short:Ctrl+Shift+S", "Ctrl+Shift+S"), item("Export…", "short:Ctrl+E", "Ctrl+E")]),
              ("Edit", [item("Undo", "short:Ctrl+Z", "Ctrl+Z"), item("Redo", "short:Ctrl+Shift+Z", "Ctrl+Shift+Z"), SEP, item("Cut", "short:Ctrl+X", "Ctrl+X"),
                        item("Copy", "short:Ctrl+C", "Ctrl+C"), item("Paste", "short:Ctrl+V", "Ctrl+V"), SEP, item("Free transform", "short:Ctrl+T", "Ctrl+T")]),
              ("Select", [item("All", "short:Ctrl+A", "Ctrl+A"), item("Deselect", "short:Ctrl+D", "Ctrl+D"), item("Invert", "short:Ctrl+Shift+I", "Ctrl+Shift+I")]),
              ("Layer", [item("New layer", "short:Ctrl+Shift+N", "Ctrl+Shift+N"), item("Duplicate layer", "short:Ctrl+J", "Ctrl+J"), SEP,
                         item("Group", "short:Ctrl+G", "Ctrl+G"), item("Ungroup", "short:Ctrl+Shift+G", "Ctrl+Shift+G")]),
              ("View", [item("Zoom in", "short:Ctrl+=", "Ctrl++"), item("Zoom out", "short:Ctrl+-", "Ctrl+−"), item("Fit on screen", "short:Ctrl+0", "Ctrl+0"),
                        item("Actual size", "short:Ctrl+1", "Ctrl+1"), SEP, item("Rulers", "short:Ctrl+R", "Ctrl+R"), item("Snap to guides", "short:Ctrl+;", "Ctrl+;")])],
    "clips": [("File", [item("Export…", "short:Ctrl+E", "Ctrl+E")]),
              ("Edit", [item("Undo", "short:Ctrl+Z", "Ctrl+Z"), item("Redo", "short:Ctrl+Shift+Z", "Ctrl+Shift+Z"), SEP, item("Cut at the playhead", "short:S", "S"),
                        item("Duplicate", "short:Ctrl+D", "Ctrl+D"), item("Delete", "short:Delete", "Delete"), item("Delete and close the gap", "short:Shift+Delete", "Shift+Delete")]),
              ("Clip", [item("Make a compound clip", "short:Alt+G", "Alt+G"), item("Open the compound clip", "short:Return", "Return"), SEP,
                        item("Add a marker", "short:M", "M"), item("Add a title", "short:T", "T")]),
              ("Playback", [item("Play or pause", "short:Space", "Space"), item("Play", "short:L", "L"), item("Pause", "short:K", "K"), SEP,
                            item("Back a frame", "short:Left", "←"), item("Forward a frame", "short:Right", "→"), item("Back a second", "short:Shift+Left", "Shift+←"),
                            item("Forward a second", "short:Shift+Right", "Shift+→"), SEP, item("Previous edit", "short:Up", "↑"), item("Next edit", "short:Down", "↓"),
                            item("Go to the start", "short:Home", "Home"), item("Go to the end", "short:End", "End")]),
              ("Tools", [item("Select", "short:A", "A"), item("Blade", "short:B", "B")]),
              ("View", [item("Zoom in", "short:=", "="), item("Zoom out", "short:-", "−")])],
    "tempo": [("Edit", [item("Undo", "short:Ctrl+Z", "Ctrl+Z"), item("Redo", "short:Ctrl+Shift+Z", "Ctrl+Shift+Z"), SEP, item("Duplicate region", "short:Ctrl+D", "Ctrl+D"),
                        item("Split region at the playhead", "short:Ctrl+T", "Ctrl+T"), item("Delete region", "short:Delete", "Delete")]),
              ("Transport", [item("Play or stop", "short:Space", "Space"), item("Record", "short:R", "R"), item("Go to the start", "short:Return", "Return"), SEP,
                             item("Cycle", "short:C", "C"), item("Metronome", "short:K", "K")]),
              ("View", [item("Musical typing", "short:Ctrl+K", "Ctrl+K")])],
    # everyday apps: what each one does, by its own shortcuts
    "books": [("Read", [item("Next page", "short:Space", "Space"), item("Previous page", "short:Shift+Space", "Shift+Space"), SEP,
                        item("Turn forward", "short:Right", "→"), item("Turn back", "short:Left", "←"), SEP, item("Close the book", "short:Escape", "Esc")])],
    "passwords": [("Vault", [item("New password", "short:Ctrl+N", "Ctrl+N"), item("Find…", "short:Ctrl+F", "Ctrl+F"), SEP, item("Lock", "short:Ctrl+L", "Ctrl+L")])],
    "scan": [("File", [item("Save as PDF", "short:Ctrl+S", "Ctrl+S")]), ("Page", [item("Turn", "short:Ctrl+R", "Ctrl+R"), item("Delete page", "short:Delete", "Delete")])],
    "contacts": [("Contact", [item("New contact", "short:Ctrl+N", "Ctrl+N"), item("Find…", "short:Ctrl+F", "Ctrl+F")])],
    "reminders": [("Reminder", [item("New reminder", "short:Ctrl+N", "Ctrl+N")])],
    "documents": [("File", [item("Save", "short:Ctrl+S", "Ctrl+S")]), ("Edit", EDIT + [SEP, item("Find…", "short:Ctrl+F", "Ctrl+F")])],
    "camera": [("Camera", [item("Take", "short:Space", "Space")])],
    "machines": [("Machine", [item("New machine", "short:Ctrl+N", "Ctrl+N")])],
    "recorder": [("Recording", [item("Record or stop", "short:Space", "Space")])],
    "music": [("Controls", [item("Play or pause", "qml:playPause", "Ctrl+P"), item("Next", "qml:nextSong", "Ctrl+Right"), item("Previous", "qml:previousSong", "Ctrl+Left"), SEP,
                            item("Louder", "qml:louder", "Ctrl+Up"), item("Quieter", "qml:quieter", "Ctrl+Down")]),
              ("View", [item("Now Playing", "qml:setView:playing", "Ctrl+1"), item("Library", "qml:setView:library", "Ctrl+2")])],
    "video": [("Controls", [item("Play or pause", "qml:playPause", "Ctrl+P"), item("Forward 10 seconds", "qml:skip:10000", "Ctrl+Right"),
                            item("Back 10 seconds", "qml:skip:-10000", "Ctrl+Left")]),
              ("View", [item("Videos", "qml:toggleList", "Ctrl+L")])],
    "photos": [("Picture", [item("Next", "qml:nextPicture", "Ctrl+Right"), item("Previous", "qml:previousPicture", "Ctrl+Left"), SEP,
                            item("Edit", "qml:edit", "Ctrl+E"), item("Rotate", "qml:rotate", "Ctrl+R"), item("Details", "qml:details", "Ctrl+I"), SEP,
                            item("Move to Trash", "qml:trashPicture", "Ctrl+Delete")]),
               ("View", [item("All Pictures", "qml:allPictures", "Ctrl+Up")])],
    "weather": [("Weather", [item("Add a place…", "qml:addPlace", "Ctrl+N"), item("Refresh", "qml:refresh", "Ctrl+R"), item("°C or °F", "qml:flipUnit", "Ctrl+U")])],
    "feeds": [("Feeds", [item("Follow…", "qml:follow", "Ctrl+N"), item("Your sources", "qml:sources", "Ctrl+Shift+S"), SEP,
                         item("Check for new stories", "qml:refresh", "Ctrl+R"), item("Mark all as read", "qml:allRead", "Ctrl+Shift+A")])],
    "messages": [("Chat", [item("New chat…", "qml:newChat", "Ctrl+N"), item("Account…", "qml:account", "Ctrl+,")])],
    "games": [("Game", [item("Play", "qml:playGame", "Ctrl+Return"), item("Add a game…", "qml:openAdd", "Ctrl+N"), item("Look again", "qml:refresh", "Ctrl+R")])],
    "clock": [("View", [item("World Clock", "qml:setPage:World Clock", "Ctrl+1"), item("Stopwatch", "qml:setPage:Stopwatch", "Ctrl+2"),
                        item("Timer", "qml:setPage:Timer", "Ctrl+3")])],
}
NAMES = {"files": "Files"}
# Apps that are about typing: they always have the Edit menu. Every other app has it only while you're typing in one
# of its fields (a search box, a name), where cut, copy and paste mean something.
TEXT_APPS = {"writer", "sheets", "slides", "notes", "mail", "code", "documents", "messages", "translate", "terminal"}


class AppMenu(QObject):
    def __init__(self, key: str, title: str, engine, backend):
        super().__init__()
        self._key, self._title, self._backend = key, title, backend
        self._engine_ref = weakref.ref(engine) if engine is not None else (lambda: None)    # (weak: torn down first at quit)
        self._bus = None
        self._ids = []
        try:
            self._bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
            node = Gio.DBusNodeInfo.new_for_xml(XML)
            self._ids.append(self._bus.register_object("/org/huginn/App", node.interfaces[0], self._call, None, None))
            Gio.bus_own_name_on_connection(self._bus, f"org.huginn.App.p{os.getpid()}", Gio.BusNameOwnerFlags.DO_NOT_QUEUE, None, None)
        except GLib.Error as err:
            print("menu: no session bus:", err.message, file=sys.stderr)
            self._bus = None
        self._bound = None                                    # the menus' own keys, worked out at the first key press
        QGuiApplication.instance().installEventFilter(self)

    # ------------------------------------------------------------------ the keys the menus show, working
    # A menu entry that shows a key (Ctrl+F for Find, Ctrl+W, Ctrl+Q, F1, F11…) works by that key too, even where the
    # app has no Shortcut of its own for it. The app's own Shortcuts still come first (Qt tries them before a key
    # reaches a window), and only keys with Ctrl or Alt, or the function keys, are taken: never what's typed.
    MODS = Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier | Qt.KeyboardModifier.AltModifier | Qt.KeyboardModifier.MetaModifier

    def _menu_keys(self) -> dict:
        keys = {}
        try:
            m = self.menus()
        except Exception:                                    # noqa: BLE001 (the window isn't there yet)
            return {}
        rows = [it for g in m["groups"] for it in g["items"]] + m["top"] + m["bottom"]
        for it in rows:
            key, act = it.get("keys", ""), it.get("id", "")
            if not key or not act or act.split(":")[0] in ("short", "edit", "recent") or not it.get("enabled", True):
                continue
            if "Super" in key or not ("Ctrl" in key or "Alt" in key or (key.startswith("F") and key[1:].isdigit())):
                continue
            if self._key == "terminal" and "Shift" not in key and not key.startswith("F"):
                continue                                     # Ctrl+W, Ctrl+Q… belong to the program in the terminal
            seq = QKeySequence(key.replace("Enter", "Return"))
            if seq.count():
                keys[seq.toString(QKeySequence.SequenceFormat.PortableText)] = act
        return keys

    def _close_sheet(self) -> bool:
        """Escape closes the sheet that's open over the window (a question, a list to pick from), in every app.
        Not a sheet that is the app's own start (Tempo's songs) or that guards something (unlocking)."""
        root = self._root()
        if root is None or self._key in ("tempo", "installer", "welcome"):
            return False
        v = root.property("sheet")
        if hasattr(v, "toVariant"):
            if v.isNull() or v.isUndefined():
                return False
            kind = (v.toVariant() or {}).get("kind", "") if isinstance(v.toVariant(), dict) else str(v.toVariant() or "")
            empty = QJSValue(QJSValue.SpecialValue.NullValue)
        elif isinstance(v, str) and v:
            kind, empty = v, ""
        elif isinstance(v, dict) and v:
            kind, empty = v.get("kind", ""), QJSValue(QJSValue.SpecialValue.NullValue)
        else:
            return False
        if kind in ("unlock", "gate", "setup", "master", "songs"):
            return False
        root.setProperty("sheet", empty)
        return True

    def eventFilter(self, obj, event) -> bool:
        if event.type() != QEvent.Type.KeyPress or not isinstance(obj, QWindow) or event.isAutoRepeat():
            return False
        mods = event.modifiers() & self.MODS
        key = event.key()
        if key == Qt.Key.Key_Escape and not mods:
            return self._close_sheet()
        if not (mods & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier)) and not (Qt.Key.Key_F1 <= key <= Qt.Key.Key_F35):
            return False
        if self._bound is None:
            if self._root() is None:
                return False
            self._bound = self._menu_keys()
        try:
            text = QKeySequence(QKeyCombination(mods, Qt.Key(key))).toString(QKeySequence.SequenceFormat.PortableText)
        except ValueError:
            return False
        act = self._bound.get(text)
        if not act and text == "Ctrl+F" and self._search_field() is not None:
            act = "find:"                                    # a search box that shows only now and then (a library view)
        if not act:
            return False
        self.trigger(act)
        return True

    @Slot(str)
    def snap(self, layout: str) -> None:
        """The fill button's layouts: this window (it's in front) snapped to a half, a third, a quarter…"""
        if self._bus:
            self._bus.call("org.huginn.Shell", "/org/huginn/Shell", "org.huginn.Shell", "Snap", GLib.Variant("(s)", (layout,)), None,
                           Gio.DBusCallFlags.NO_AUTO_START, 1500, None, None, None)

    # ------------------------------------------------------------------ what the bar asks
    def _root(self):
        engine = self._engine_ref()
        roots = engine.rootObjects() if engine is not None else []
        return roots[0] if roots else None

    def _window(self) -> QWindow | None:
        w = QGuiApplication.focusWindow()
        if w is not None:
            return w
        root = self._root()
        return root if isinstance(root, QWindow) else None

    def _has_qml(self, name: str) -> bool:
        root = self._root()
        if root is None:
            return False
        mo = root.metaObject()
        return any(mo.method(i).name().data().decode() == name for i in range(mo.methodCount()))

    def _has_backend(self, name: str) -> bool:
        return self._backend is not None and callable(getattr(self._backend, name, None))

    def _works(self, act: str) -> bool:
        kind, _, rest = act.partition(":")
        if kind == "qml":
            return self._has_qml(rest.split(":")[0])
        if kind == "backend":
            return self._has_backend(rest)
        if kind == "short":
            return self._shortcut(rest) is not None
        return True

    def _recent(self) -> list:
        files = getattr(self._backend, "files", None) if self._backend is not None else None
        try:
            rows = list(files)[:8] if files is not None else []
        except TypeError:
            rows = []
        out = []
        for r in rows:
            if isinstance(r, dict) and r.get("path"):
                out.append(item(r.get("name") or Path(r["path"]).name, "open:" + r["path"], "", sub=r.get("when", "") or r.get("modified", "")))
        return out

    def menus(self) -> dict:
        groups = []
        for name, items in APP_MENUS.get(self._key, []):
            rows = []
            for it in items:
                if it.get("sep"):
                    if rows and not rows[-1].get("sep"):
                        rows.append(SEP)
                    continue
                if it["id"] == "recent":
                    if self._has_backend("open"):
                        rec = self._recent()
                        if rec:
                            rows.append(dict(it, children=rec))
                    continue
                if self._works(it["id"]):                    # only what this app can really do
                    rows.append(dict(it, enabled=True))
            while rows and rows[-1].get("sep"):
                rows.pop()
            if rows:
                groups.append({"name": name, "items": rows})
        if not any(g["name"] == "Edit" for g in groups) and (self._key in TEXT_APPS or self._typing()):
            groups.insert(min(1, len(groups)), {"name": "Edit", "items": [dict(i, enabled=True) if not i.get("sep") else i for i in EDIT]})
        # Find… for every app with a search box, which Ctrl+F then reaches (unless the app has its own Find)
        if not any(it.get("label", "").startswith("Find") for g in groups for it in g["items"]) and self._search_field() is not None:
            edit = next((g for g in groups if g["name"] == "Edit"), None)
            if edit is None:
                edit = {"name": "Edit", "items": []}
                groups.insert(min(1, len(groups)), edit)
            edit["items"] = edit["items"] + ([SEP] if edit["items"] else []) + [item("Find…", "find:", "Ctrl+F", enabled=True)]
        if not any(g["name"] == "View" for g in groups):
            groups.append({"name": "View", "items": [item("Full screen", "win:fullscreen", "F11", enabled=True)]})
        else:
            next(g for g in groups if g["name"] == "View")["items"] += [SEP, item("Full screen", "win:fullscreen", "F11", enabled=True)]
        groups.append({"name": "Window", "items": [item("Minimise", "win:minimise", "Super+Down", enabled=True), item("Zoom", "win:zoom", "Super+Up", enabled=True)]})
        groups.append({"name": "Help", "items": [item(f"{self._title} Help", "app:help", "F1", enabled=True)]})
        return {"app": self._title, "key": self._key, "settings": self._has_qml("openSettings"), "groups": groups,
                "top": [item(f"About {self._title}", "app:about", enabled=True), item(f"{self._title} Settings…", "app:settings", "Ctrl+,", enabled=self._has_qml("openSettings"))],
                "bottom": [item("Minimise", "win:minimise", enabled=True), item("Close window", "win:close", "Ctrl+W", enabled=True),
                           item(f"Quit {self._title}", "app:quit", "Ctrl+Q", enabled=True)]}

    def _search_field(self):
        """The window's search box (an IslandField that's showing), if it has one."""
        root = self._root()
        if root is None:
            return None
        for obj in root.findChildren(QObject):
            if obj.metaObject().className().startswith("IslandField") and obj.property("visible") and obj.property("enabled") is not False:
                return obj
        return None

    def _typing(self) -> bool:
        """Is a text field what had the keyboard in this app (its window keeps that while the bar's menu is open)?"""
        root = self._root()
        focus = getattr(root, "activeFocusItem", lambda: None)() if isinstance(root, QWindow) else None
        if focus is None:
            return False
        name = focus.metaObject().className()
        return any(k in name for k in ("TextInput", "TextEdit", "TextField", "TextArea")) or focus.property("selectedText") is not None

    # ------------------------------------------------------------------ doing it
    def _shortcut(self, seq: str):
        root = self._root()
        if root is None:
            return None
        want = QKeySequence(seq)
        for obj in root.findChildren(QObject):
            if obj.metaObject().className() not in ("QQuickShortcut",):
                continue
            seqs = []
            for prop in ("sequence", "sequences"):
                v = obj.property(prop)
                if v is None:
                    continue
                for s in (v if isinstance(v, list) else [v]):
                    try:
                        if isinstance(s, QKeySequence):
                            seqs.append(s)
                        elif isinstance(s, int) or hasattr(s, "value"):        # StandardKey.Undo and friends: their keys here
                            seqs.extend(QKeySequence.keyBindings(QKeySequence.StandardKey(int(getattr(s, "value", s)))))
                        else:
                            seqs.append(QKeySequence(s))
                    except (TypeError, ValueError):
                        pass
            if any(s.matches(want) == QKeySequence.ExactMatch for s in seqs if not s.isEmpty()) and obj.property("enabled") is not False:
                return obj
        return None

    def trigger(self, act: str) -> None:
        kind, _, rest = act.partition(":")
        win = self._window()
        if kind == "short":
            sc = self._shortcut(rest)
            if sc is not None:
                QMetaObject.invokeMethod(sc, "activated")
            elif win is not None:
                seq = QKeySequence(rest)
                if seq.count():
                    combo = seq[0]
                    for t in (QKeyEvent.Type.KeyPress, QKeyEvent.Type.KeyRelease):
                        QGuiApplication.sendEvent(win, QKeyEvent(t, combo.key(), combo.keyboardModifiers()))
        elif kind == "edit":
            focus = getattr(win, "activeFocusItem", lambda: None)() if win is not None else None
            if focus is not None:
                QMetaObject.invokeMethod(focus, rest)
        elif kind == "find":
            field = self._search_field()
            if field is not None:
                QMetaObject.invokeMethod(field, "focusInput")
        elif kind == "backend" and self._has_backend(rest):
            getattr(self._backend, rest)()
        elif kind == "qml":
            name, _, arg = rest.partition(":")
            root = self._root()
            if root is not None and self._has_qml(name):
                if arg:
                    QMetaObject.invokeMethod(root, name, Q_ARG("QVariant", arg))
                else:
                    QMetaObject.invokeMethod(root, name)
        elif kind == "open" and self._has_backend("open"):
            self._backend.open(rest)
        elif kind == "win" and win is not None:
            if rest == "minimise":
                win.showMinimized()
            elif rest == "zoom":
                win.showNormal() if win.visibility() == QWindow.Maximized else win.showMaximized()
            elif rest == "fullscreen":
                win.showNormal() if win.visibility() == QWindow.FullScreen else win.showFullScreen()
            elif rest == "close":
                win.close()
        elif kind == "app":
            if rest == "quit":
                QGuiApplication.quit()
            elif rest == "help":
                from PySide6.QtCore import QProcess
                QProcess.startDetached(sys.executable, [str(Path(__file__).resolve().parent / "huginn_app.py"), "help", "--page", self._key])
            elif rest == "settings" and self._has_qml("openSettings"):
                QMetaObject.invokeMethod(self._root(), "openSettings")
            elif rest == "newWindow":
                from PySide6.QtCore import QProcess
                QProcess.startDetached(sys.executable, [str(Path(__file__).resolve().parent / "huginn_app.py"), self._key])
        if win is not None and kind not in ("win", "app"):
            win.requestActivate()

    def _call(self, _conn, _sender, _path, _iface, method, params, inv) -> None:
        if method == "Menus":
            try:
                inv.return_value(GLib.Variant("(s)", (json.dumps(self.menus()),)))
            except Exception as err:  # noqa: BLE001 — never leave the bar waiting
                print("menu:", err, file=sys.stderr)
                inv.return_value(GLib.Variant("(s)", ("{}",)))
            return
        if method == "Trigger":
            act = params.unpack()[0]
            inv.return_value(None)
            from PySide6.QtCore import QTimer
            QTimer.singleShot(0, lambda: self.trigger(act))         # after the bar's menu has closed and the window is back in front
            return
        inv.return_value(None)
