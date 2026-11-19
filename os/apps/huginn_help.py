"""Help: short guides to Huginn OS and each of its apps, kept on this computer (apps/help/*.md) and searchable.

`huginn_app.py help mail` opens straight at Mail's guide."""
import json
import re
import sys
from pathlib import Path

from PySide6.QtCore import Property, QObject, QProcess, Signal, Slot

HERE = Path(__file__).resolve().parent
GUIDES = HERE / "help"
TOKENS = [HERE.parent / "tokens" / "tokens.json", Path("/usr/share/huginn-os/tokens.json")]
ICONS = [HERE.parent / "config/overlay/usr/share/icons/hicolor/scalable/apps", Path("/usr/share/icons/hicolor/scalable/apps")]
APP_OF = {"privacy-report": "privacy", "video": "video", "updates": "settings", "accounts": "settings", "ai": "settings", "installer": "os"}                    # guide name -> app key, where they differ
START = ["getting-started", "privacy", "passwords", "sharing"]               # shown first, as "Start here"
SHELF = {"Talk and plan": ["mail", "messages", "calendar", "contacts", "reminders", "phone"],
         "Write and work": ["writer", "sheets", "slides", "documents", "scan", "code", "notes", "translate", "print"],
         "Look, listen, play": ["photos", "easel", "music", "video", "podcasts", "books", "feeds", "games", "clips", "tempo", "camera", "recorder"],
         "Keep things safe": ["passwords", "authenticator", "privacy-report", "backup", "money"],
         "Find your way": ["maps", "weather", "clock", "calculator"],
         "Tools": ["files", "archives", "disks", "screenshot", "terminal", "machines", "monitor", "store", "settings", "updates", "accounts", "ai", "shortcuts", "characters", "fonts", "sharing", "welcome", "installer", "help"]}


def read_guide(text: str) -> dict:
    """'# Title\\nsummary\\n\\n## Heading\\nbody…' -> {title, summary, sections: [{title, body}]}."""
    title, summary, sections, cur = "", [], [], None
    for line in text.splitlines():
        if line.startswith("# ") and not title:
            title = line[2:].strip()
        elif line.startswith("## "):
            cur = {"title": line[3:].strip(), "body": []}
            sections.append(cur)
        elif cur is not None:
            cur["body"].append(line)
        elif line.strip():
            summary.append(line.strip())
    for s in sections:
        s["body"] = "\n".join(s["body"]).strip()
    return {"title": title, "summary": " ".join(summary), "sections": sections}


def plain(md: str) -> str:
    return re.sub(r"[*_`#>]", "", md)


def snippet(text: str, words: list, width: int = 110) -> str:
    low = norm(text)
    at = min((low.find(w) for w in words if low.find(w) >= 0), default=0)
    start = max(0, at - 30)
    while start > 0 and text[start - 1] not in " \n":
        start -= 1
    cut = text[start:start + width].replace("\n", " ").strip()
    return ("…" if start else "") + cut + ("…" if start + width < len(text) else "")


def load_all() -> dict:
    out = {}
    for path in sorted(GUIDES.glob("*.md")):
        try:
            g = read_guide(path.read_text(encoding="utf-8"))
        except OSError:
            continue
        if g["title"]:
            g["id"] = path.stem
            g["app"] = APP_OF.get(path.stem, path.stem)
            out[path.stem] = g
    return out


def colours() -> dict:
    for path in TOKENS:
        try:
            return json.loads(path.read_text(encoding="utf-8")).get("apps", {})
        except (OSError, ValueError):
            continue
    return {}


def icon_for(app: str) -> str:
    for folder in ICONS:
        p = folder / f"huginn-{app}.svg"
        if p.exists():
            return p.as_uri()
    p = ICONS[0] / "huginn-os.svg"
    return p.as_uri() if p.exists() else ""


def norm(text: str) -> str:
    """Lower case, hyphens and apostrophes dropped, so "wifi" finds "Wi-Fi" and "dont" finds "don't"."""
    return re.sub(r"[-'’]", "", text.lower())


def search(guides: dict, query: str) -> list:
    words = [w[:-1] if len(w) > 4 and w.endswith("s") else w for w in re.findall(r"\w+", norm(query)) if len(w) > 1 or w.isdigit()]
    if not words:
        return []
    hits = []
    for g in guides.values():
        title, summary = norm(g["title"]), norm(g["summary"])
        score = sum(8 for w in words if w in title) + sum(2 for w in words if w in summary)
        best, where, text = 0, "", g["summary"]
        for s in g["sections"]:
            head, body = norm(s["title"]), norm(plain(s["body"]))
            here = sum(4 for w in words if w in head) + sum(1 for w in words if w in body)
            if here and all(w in head + " " + body for w in words):
                here += 3
            if here > best:
                best, where, text = here, s["title"], plain(s["body"])
            score += here
        if score:
            hits.append((score, g, where, text))
    hits.sort(key=lambda h: -h[0])
    return [{"id": g["id"], "title": g["title"], "section": where, "text": snippet(text, [w for w in words])} for _, g, where, text in hits[:30]]


class Help(QObject):
    changed = Signal()
    said = Signal(str, bool)

    def __init__(self, demo: bool = False, target: str = ""):
        super().__init__()
        self._guides = load_all()
        self._cols = colours()
        self._query, self._open, self._section = "", "", ""
        want = (target or "").strip().lower()
        if want:
            self._open = want if want in self._guides else next((k for k, g in self._guides.items() if g["app"] == want), "")
        elif demo:
            self._open = ""

    def _tile(self, gid: str) -> dict:
        g = self._guides[gid]
        col = self._cols.get(g["app"]) or ["#7C9CFF", "#3B5BDB"]
        return {"id": gid, "title": g["title"], "summary": g["summary"], "colour": col[0], "deep": col[1], "icon": icon_for(g["app"]),
                "app": g["app"] if gid not in ("getting-started", "privacy") else ""}

    def _get_shelves(self) -> list:
        out = [{"name": "Start here", "tiles": [self._tile(g) for g in START if g in self._guides]}]
        for name, ids in SHELF.items():
            tiles = [self._tile(g) for g in ids if g in self._guides]
            if tiles:
                out.append({"name": name, "tiles": tiles})
        seen = {t["id"] for s in out for t in s["tiles"]}
        rest = [self._tile(g) for g in self._guides if g not in seen]
        if rest:
            out.append({"name": "More", "tiles": rest})
        return out

    def _get_article(self) -> dict:
        g = self._guides.get(self._open)
        if not g:
            return {}
        t = self._tile(self._open)
        t["sections"] = g["sections"]
        t["section"] = self._section
        return t

    shelves = Property("QVariantList", _get_shelves, notify=changed)
    results = Property("QVariantList", lambda self: search(self._guides, self._query), notify=changed)
    article = Property("QVariantMap", _get_article, notify=changed)
    query = Property(str, lambda self: self._query, notify=changed)
    count = Property(int, lambda self: len(self._guides), constant=True)

    @Slot(str)
    def search(self, text: str) -> None:
        self._query = text
        self.changed.emit()

    @Slot(str)
    def open(self, gid: str) -> None:
        self._open, self._section = (gid, "") if gid in self._guides else ("", "")
        self.changed.emit()

    @Slot(str, str)
    def openAt(self, gid: str, section: str) -> None:
        self._open, self._section = (gid, section) if gid in self._guides else ("", "")
        self.changed.emit()

    @Slot()
    def home(self) -> None:
        self._open, self._section = "", ""
        self.changed.emit()

    @Slot(str)
    def openApp(self, app: str) -> None:
        if not app or app == "help":
            return
        if QProcess.startDetached(sys.executable, [str(HERE / "huginn_app.py"), app]):
            self.said.emit("Opening…", False)
        else:
            self.said.emit("That app couldn't be opened", True)
