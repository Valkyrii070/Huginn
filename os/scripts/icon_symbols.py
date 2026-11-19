"""Huginn's line glyphs as icons: the action and symbolic part of the Huginn icon theme.

The glyphs are drawn once, in code, in shell/qml/Glyph.qml (and apps/qml/Glyph.qml), on a 24-unit grid. This runs
that drawing code with a context that writes down what it is asked to draw, turns every stroke into the outline of
the stroke (so each icon is one filled shape, which is what GTK's recolouring and KDE's both expect), and writes the
result as an SVG for every freedesktop icon name the glyph stands for.

The SVGs use KDE's colour-scheme class, so Qt apps get them in the scheme's text colour (dark or light), and GTK
recolours anything named -symbolic itself. The colour written into them is only for anything that does neither.

Used by scripts/make-icons.py; nothing here is run on its own.
"""
import json
import math
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GLYPHS = [ROOT / "shell" / "qml" / "Glyph.qml", ROOT / "apps" / "qml" / "Glyph.qml"]
FALLBACK_INK = "#8A919C"   # mid grey: readable on light and dark when nothing recolours it

# glyph -> names that are actions (written as the name and as name-symbolic)
ACTIONS = {
    "search": ["edit-find", "system-search", "search", "find-location"],
    "plus": ["list-add", "add", "value-increase", "tab-new"],
    "minus": ["list-remove", "remove", "value-decrease"],
    "x": ["window-close", "dialog-close", "tab-close", "dialog-cancel", "edit-delete-remove"],
    "trash": ["edit-delete", "delete", "edit-delete-shred"],
    "back": ["go-previous", "pan-start", "arrow-left", "go-previous-view"],
    "forward": ["go-next", "pan-end", "arrow-right", "go-next-view"],
    "up": ["go-up", "pan-up", "arrow-up"],
    "down": ["go-down", "pan-down", "arrow-down"],
    "first": ["go-first", "go-top"],
    "last": ["go-last", "go-bottom"],
    "home": ["go-home"],
    "refresh": ["view-refresh", "reload", "view-refresh-all"],
    "undo": ["edit-undo", "document-revert"],
    "redo": ["edit-redo"],
    "copy": ["edit-copy", "edit-duplicate"],
    "paste": ["edit-paste"],
    "cut": ["edit-cut"],
    "save": ["document-save", "document-save-as", "document-save-all"],
    "newfile": ["document-new"],
    "newfolder": ["folder-new", "folder-new-symbolic"],
    "folderopen": ["document-open", "document-open-folder"],
    "clear": ["edit-clear", "edit-clear-all", "edit-clear-history"],
    "selectall": ["edit-select-all"],
    "edit": ["document-edit", "edit-rename", "editor"],
    "play": ["media-playback-start"],
    "pause": ["media-playback-pause"],
    "stop": ["media-playback-stop", "process-stop"],
    "next": ["media-skip-forward", "media-seek-forward"],
    "prev": ["media-skip-backward", "media-seek-backward"],
    "record": ["media-record"],
    "repeat": ["media-playlist-repeat"],
    "shuffle": ["media-playlist-shuffle"],
    "eject": ["media-eject"],
    "volumehigh": ["audio-volume-high"],
    "volume": ["audio-volume-medium"],
    "volumelow": ["audio-volume-low"],
    "volumeoff": ["audio-volume-muted"],
    "mute": ["microphone-sensitivity-muted", "audio-input-microphone-muted"],
    "dots": ["view-more", "view-more-horizontal", "overflow-menu"],
    "menu": ["open-menu", "application-menu", "hamburger-menu"],
    "minimize": ["window-minimize"],
    "maximize": ["window-maximize"],
    "restore": ["window-restore", "window-unmaximize"],
    "expand": ["view-fullscreen"],
    "shrink": ["view-restore", "view-fullscreen-exit"],
    "fit": ["zoom-fit-best", "zoom-fit-page", "zoom-original"],
    "zoom": ["zoom-in"],
    "zoomout": ["zoom-out"],
    "bold": ["format-text-bold"],
    "italic": ["format-text-italic"],
    "underline": ["format-text-underline"],
    "strike": ["format-text-strikethrough"],
    "alignleft": ["format-justify-left"],
    "aligncenter": ["format-justify-center"],
    "alignright": ["format-justify-right"],
    "alignjustify": ["format-justify-fill"],
    "list": ["view-list", "view-list-details", "format-list-unordered"],
    "numbers": ["format-list-ordered"],
    "grid": ["view-grid", "view-list-icons", "view-app-grid"],
    "link": ["insert-link", "edit-link"],
    "image": ["insert-image"],
    "attach": ["mail-attachment", "document-attach"],
    "send": ["mail-send", "document-send"],
    "reply": ["mail-reply-sender", "mail-reply"],
    "replyall": ["mail-reply-all"],
    "forwardmail": ["mail-forward"],
    "mail": ["mail-message", "mail-message-new", "mail-unread"],
    "inbox": ["mail-inbox"],
    "star": ["starred", "rating", "bookmark-star"],
    "bookmark": ["bookmark-new", "bookmarks"],
    "heart": ["love", "emblem-love"],
    "tag": ["tag", "tag-new"],
    "filter": ["view-filter", "filter"],
    "sort": ["view-sort", "view-sort-ascending", "view-sort-descending"],
    "share": ["document-share", "send-to"],
    "upload": ["document-export", "cloud-upload", "upload"],
    "download": ["document-import", "download", "cloud-download"],
    "gear": ["configure", "preferences-system", "settings", "preferences-other"],
    "sliders": ["configure-shortcuts", "preferences-desktop", "adjustlevels"],
    "info": ["help-about", "help-info", "documentinfo", "document-properties"],
    "help": ["help-contents", "help-browser", "help-faq"],
    "check": ["object-select", "dialog-ok", "dialog-ok-apply", "checkmark"],
    "okcircle": ["emblem-ok", "emblem-default"],
    "lock": ["object-locked", "system-lock-screen", "changes-prevent"],
    "unlock": ["object-unlocked", "changes-allow"],
    "eye": ["view-visible", "view-reveal", "visibility"],
    "eyeoff": ["view-hidden", "view-conceal"],
    "power": ["system-shutdown"],
    "signout": ["system-log-out", "application-exit"],
    "history": ["document-open-recent", "edit-history", "history"],
    "printer": ["document-print", "document-print-preview"],
    "window": ["window-new"],
    "sidebar": ["sidebar-show", "view-sidebar"],
    "crop": ["transform-crop", "image-crop"],
    "rotate": ["object-rotate-right", "transform-rotate"],
    "flip": ["object-flip-horizontal"],
    "picker": ["color-picker"],
    "brush": ["draw-brush"],
    "eraser": ["draw-eraser"],
    "bucket": ["color-fill"],
    "type": ["insert-text", "draw-text"],
    "pin": ["mark-location"],
    "calendar": ["view-calendar", "appointment-new"],
    "clock": ["alarm", "appointment-soon"],
}
# glyph -> names whose ordinary icon is a coloured picture (a device, a place, a kind of file, a status): only the
# -symbolic one is the glyph
SYMBOLIC = {
    "folder": ["folder", "inode-directory", "folder-open"], "file": ["text-x-generic", "application-x-generic"],
    "doc": ["x-office-document", "text-x-generic-template"], "music": ["audio-x-generic", "folder-music"],
    "video": ["video-x-generic", "folder-videos"], "image": ["image-x-generic", "folder-pictures"],
    "home": ["user-home", "folder-home"], "download": ["folder-download"], "desktop": ["user-desktop", "computer", "video-display"],
    "trash": ["user-trash", "user-trash-full"], "star": ["emblem-favorite", "starred"],
    "share": ["emblem-shared", "folder-publicshare"], "globe": ["network-workgroup", "folder-remote", "web-browser", "applications-internet"],
    "wifi": ["network-wireless", "network-wireless-signal-excellent", "network-wireless-connected"],
    "wifioff": ["network-wireless-offline", "network-wireless-disabled"],
    "ethernet": ["network-wired"], "bluetooth": ["bluetooth", "bluetooth-active"], "battery": ["battery", "battery-good", "battery-full"],
    "keyboard": ["input-keyboard"], "mouse": ["input-mouse"], "gamepad": ["input-gaming", "applications-games"],
    "headphones": ["audio-headphones"], "speaker": ["audio-speakers", "audio-card"], "mic": ["audio-input-microphone"],
    "camera": ["camera-photo"], "webcam": ["camera-web"], "phone": ["call-start"], "smartphone": ["phone"],
    "laptop": ["computer-laptop"], "drive": ["drive-harddisk", "drive-harddisk-solidstate", "drive-multidisk"],
    "usb": ["drive-removable-media", "media-removable", "drive-removable-media-usb"], "sdcard": ["media-flash"],
    "disc": ["drive-optical", "media-optical"], "server": ["network-server"], "scanner": ["scanner"], "printer": ["printer"],
    "info": ["dialog-information"], "warning": ["dialog-warning"], "error": ["dialog-error"], "help": ["dialog-question"],
    "key": ["dialog-password"], "shield": ["security-high", "security-medium"], "lock": ["emblem-locked"],
    "bell": ["preferences-system-notifications", "notifications"], "sun": ["display-brightness", "weather-clear"],
    "moon": ["weather-clear-night"], "cloud": ["weather-overcast"], "cloudsun": ["weather-few-clouds"],
    "cloudmoon": ["weather-few-clouds-night"], "rain": ["weather-showers"], "snow": ["weather-snow"],
    "storm": ["weather-storm"], "fog": ["weather-fog"], "box": ["package-x-generic", "application-x-addon"],
    "bag": ["system-software-install", "org.gnome.Software"], "terminal": ["utilities-terminal", "application-x-executable"],
    "code": ["text-x-script", "applications-development"], "user": ["avatar-default", "system-users", "user-info"],
    "apps": ["view-app-grid", "applications-all"], "gear": ["emblem-system", "applications-system"],
    "calendar": ["x-office-calendar", "office-calendar"], "history": ["folder-recent", "document-open-recent"],
    "chat": ["user-available", "chat"], "palette": ["applications-graphics", "preferences-desktop-color"],
    "okcircle": ["emblem-ok"], "warning2": [],
}


def _engine_draw(names: list) -> dict:
    """Runs Glyph.qml's drawing code once for each name with a recording context; returns {name: [ops]}."""
    from PySide6.QtQml import QJSEngine
    text = GLYPHS[0].read_text(encoding="utf-8")
    body = text[text.index("onPaint: {") + len("onPaint: {"):text.rindex("    }\n}")]
    body = body.replace('var c = getContext("2d"), k = size / 24', "var c = ctx, k = 1")
    # cases that only the apps' copy has
    extra = ""
    if GLYPHS[1].is_file():
        other = GLYPHS[1].read_text(encoding="utf-8")
        have = set(re.findall(r'case "([a-z0-9]+)"', body))
        extra = "".join(m.group(0) + "\n" for m in re.finditer(r'^\s*case "([a-z0-9]+)":.*$', other, re.M) if m.group(1) not in have)
        body = body.replace("        default:", extra + "        default:", 1)
    recorder = r"""
    function Rec() { this.ops = []; this.cur = []; this.lineWidth = 1.7; this.dash = []; }
    Rec.prototype.reset = function () {}; Rec.prototype.scale = function () {};
    Rec.prototype.beginPath = function () { this.cur = [] };
    Rec.prototype.moveTo = function (x, y) { this.cur.push(["M", x, y]) };
    Rec.prototype.lineTo = function (x, y) { this.cur.push(["L", x, y]) };
    Rec.prototype.arc = function (x, y, r, a0, a1, ccw) { this.cur.push(["A", x, y, r, a0, a1, !!ccw]) };
    Rec.prototype.bezierCurveTo = function (a, b, c, d, e, f) { this.cur.push(["C", a, b, c, d, e, f]) };
    Rec.prototype.quadraticCurveTo = function (a, b, c, d) { this.cur.push(["Q", a, b, c, d]) };
    Rec.prototype.closePath = function () { this.cur.push(["Z"]) };
    Rec.prototype.roundedRect = function (x, y, w, h, rx, ry) { this.cur.push(["R", x, y, w, h, rx, ry]) };
    Rec.prototype.ellipse = function (x, y, w, h) { this.cur.push(["E", x, y, w, h]) };
    Rec.prototype.stroke = function () { this.ops.push({kind: "stroke", path: this.cur.slice(), width: this.lineWidth, dash: this.dash.slice()}) };
    Rec.prototype.fill = function () { this.ops.push({kind: "fill", path: this.cur.slice()}) };
    Rec.prototype.fillRect = function (x, y, w, h) { this.ops.push({kind: "fill", path: [["E0", x, y, w, h]]}) };
    Rec.prototype.setLineDash = function (d) { this.dash = d };
    function draw(name) { var ctx = new Rec(), size = 24, ink = "#000"; (function () { %s })(); return JSON.stringify(ctx.ops) }
    """ % body
    js = QJSEngine()
    result = js.evaluate(recorder)
    if result.isError():
        raise RuntimeError(f"Glyph.qml's drawing code would not run: {result.toString()}")
    fn = js.globalObject().property("draw")
    out = {}
    for name in names:
        got = fn.call([name])
        if got.isError():
            raise RuntimeError(f"glyph {name}: {got.toString()}")
        out[name] = json.loads(got.toString())
    return out


def _path(ops: list):
    """The ops of one glyph as a single filled QPainterPath: strokes outlined, all of it joined into one shape."""
    from PySide6.QtCore import QPointF, QRectF, Qt
    from PySide6.QtGui import QPainterPath, QPainterPathStroker
    total = QPainterPath()
    for op in ops:
        p = QPainterPath()
        p.setFillRule(Qt.WindingFill)
        started = False
        for cmd in op["path"]:
            kind = cmd[0]
            if kind == "M":
                p.moveTo(cmd[1], cmd[2])
                started = True
            elif kind == "L":
                p.lineTo(cmd[1], cmd[2]) if started else p.moveTo(cmd[1], cmd[2])
                started = True
            elif kind == "C":
                p.cubicTo(*cmd[1:7])
            elif kind == "Q":
                p.quadTo(*cmd[1:5])
            elif kind == "Z":
                p.closeSubpath()
            elif kind == "R":
                p.addRoundedRect(QRectF(*cmd[1:5]), cmd[5], cmd[6])
                started = False
            elif kind in ("E", "E0"):
                (p.addEllipse if kind == "E" else p.addRect)(QRectF(*cmd[1:5]))
                started = False
            elif kind == "A":
                x, y, r, a0, a1, ccw = cmd[1:7]
                if not ccw:
                    sweep = 2 * math.pi if a1 - a0 >= 2 * math.pi else (a1 - a0) % (2 * math.pi)
                    qt_sweep = -math.degrees(sweep)
                else:
                    sweep = 2 * math.pi if a0 - a1 >= 2 * math.pi else (a0 - a1) % (2 * math.pi)
                    qt_sweep = math.degrees(sweep)
                start = QPointF(x + r * math.cos(a0), y + r * math.sin(a0))
                if not started:
                    p.moveTo(start)
                    started = True
                p.arcTo(QRectF(x - r, y - r, 2 * r, 2 * r), -math.degrees(a0), qt_sweep)
        if op["kind"] == "stroke":
            s = QPainterPathStroker()
            s.setWidth(op["width"])
            s.setCapStyle(Qt.RoundCap)
            s.setJoinStyle(Qt.RoundJoin)
            if op["dash"]:
                s.setDashPattern([d / op["width"] for d in op["dash"]])
            p = s.createStroke(p)
        total = total.united(p.simplified())
    return total.simplified()


def _svg_d(path) -> str:
    from PySide6.QtGui import QPainterPath
    out, i, n = [], 0, path.elementCount()
    f = lambda v: f"{v:.2f}".rstrip("0").rstrip(".")   # noqa: E731
    while i < n:
        e = path.elementAt(i)
        if e.type == QPainterPath.ElementType.MoveToElement:
            out.append(f"M{f(e.x)} {f(e.y)}")
            i += 1
        elif e.type == QPainterPath.ElementType.LineToElement:
            out.append(f"L{f(e.x)} {f(e.y)}")
            i += 1
        else:   # a curve: this element and the next two (its control points and end)
            c2, end = path.elementAt(i + 1), path.elementAt(i + 2)
            out.append(f"C{f(e.x)} {f(e.y)} {f(c2.x)} {f(c2.y)} {f(end.x)} {f(end.y)}")
            i += 3
    return "".join(out) + "Z"


def svg(d: str, rule: str) -> str:
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="24" height="24">'
            f'<style id="current-color-scheme" type="text/css">.ColorScheme-Text {{ color:{FALLBACK_INK}; }}</style>'
            f'<path class="ColorScheme-Text" style="fill:currentColor" fill-rule="{rule}" d="{d}"/></svg>\n')


def write(theme: Path) -> tuple:
    """Writes the glyph icons into theme/symbolic/{actions,status}; returns (dirs for index.theme, count)."""
    from PySide6.QtCore import Qt
    wanted = sorted(set(ACTIONS) | set(k for k, v in SYMBOLIC.items() if v))
    ops = _engine_draw(wanted)
    files = {}
    for glyph in wanted:
        if not ops[glyph]:
            raise RuntimeError(f"Glyph.qml has no drawing for {glyph}")
        path = _path(ops[glyph])
        files[glyph] = svg(_svg_d(path), "evenodd" if path.fillRule() == Qt.OddEvenFill else "nonzero")
    count = 0
    for ctx, table, plain in (("actions", ACTIONS, True), ("status", SYMBOLIC, False)):
        where = theme / "symbolic" / ctx
        where.mkdir(parents=True, exist_ok=True)
        for old in where.glob("*.svg"):
            old.unlink()
        for glyph, names in table.items():
            for name in names:
                base = name[:-9] if name.endswith("-symbolic") else name
                for out in ([base, base + "-symbolic"] if plain else [base + "-symbolic"]):
                    (where / f"{out}.svg").write_text(files[glyph], encoding="utf-8")
                    count += 1
    return [("symbolic/actions", "Actions"), ("symbolic/status", "Status")], count
