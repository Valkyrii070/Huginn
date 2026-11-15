"""Characters: every emoji and symbol, findable by name. Click one to copy it, then paste it anywhere.

Emoji, their names and groups come from Unicode's own list (emoji-test.txt, in the unicode-data package) when it is
there, otherwise from the copy bundled with this app (data/emoji.json). Everything else (arrows, maths, currency,
accented letters…) comes from Python's Unicode database."""
import json
import os
import re
import unicodedata
from pathlib import Path

from PySide6.QtCore import Property, QObject, Signal, Slot
from PySide6.QtGui import QGuiApplication

HERE = Path(__file__).resolve().parent
TEST_FILES = [Path("/usr/share/unicode/emoji/emoji-test.txt"), Path("/usr/share/unicode-data/emoji/emoji-test.txt")]
TONES = ["", "\U0001F3FB", "\U0001F3FC", "\U0001F3FD", "\U0001F3FE", "\U0001F3FF"]
TONE_WORDS = {"\U0001F3FB": "light", "\U0001F3FC": "medium-light", "\U0001F3FD": "medium", "\U0001F3FE": "medium-dark", "\U0001F3FF": "dark"}
GROUPS = [("Smileys & Emotion", "Smileys", "😀"), ("People & Body", "People", "👋"), ("Animals & Nature", "Nature", "🦊"), ("Food & Drink", "Food", "🍓"),
          ("Travel & Places", "Places", "🚲"), ("Activities", "Activities", "⚽"), ("Objects", "Objects", "💡"), ("Symbols", "Symbols", "💟"), ("Flags", "Flags", "🏁")]
SYMBOLS = [("Arrows", "→", [(0x2190, 0x21FF), (0x27F0, 0x27FF), (0x2900, 0x297F)]),
           ("Maths", "∑", [(0x00B1, 0x00B1), (0x00D7, 0x00D7), (0x00F7, 0x00F7), (0x2200, 0x22FF), (0x2070, 0x209C), (0x2150, 0x218B)]),
           ("Money", "€", [(0x0024, 0x0024), (0x00A2, 0x00A5), (0x20A0, 0x20C0)]),
           ("Punctuation", "§", [(0x00A1, 0x00A1), (0x00A7, 0x00A7), (0x00AB, 0x00AB), (0x00B6, 0x00B7), (0x00BB, 0x00BB), (0x00BF, 0x00BF), (0x2010, 0x205E)]),
           ("Letters", "é", [(0x00C0, 0x00FF), (0x0100, 0x017F), (0x0180, 0x024F), (0x1E00, 0x1EFF)]),
           ("Greek", "Ω", [(0x0391, 0x03A9), (0x03B1, 0x03C9)]),
           ("Shapes", "◆", [(0x25A0, 0x25FF), (0x2500, 0x259F)]),
           ("Signs", "✓", [(0x2100, 0x214F), (0x2600, 0x26FF), (0x2700, 0x27BF), (0x2117, 0x2117), (0x00A9, 0x00A9), (0x00AE, 0x00AE), (0x2122, 0x2122)])]


def read_emoji_test(text: str) -> list:
    """Unicode's emoji-test.txt -> [{c, name, group, tones: [variants]}] with skin-tone variants folded into their base."""
    out, by_base, group = [], {}, ""
    for line in text.splitlines():
        if line.startswith("# group:"):
            group = line.split(":", 1)[1].strip()
            continue
        m = re.match(r"^([0-9A-F ]+?)\s*;\s*fully-qualified\s*#\s*(\S+)\s+E\d+\.\d+\s+(.+)$", line)
        if not m or group == "Component":
            continue
        char, name = "".join(chr(int(cp, 16)) for cp in m.group(1).split()), m.group(3).strip()
        base_name, _, tone = name.partition(": ")
        if tone and "skin tone" in tone and base_name in by_base:
            if "," not in tone:                                        # one tone for the whole emoji (not mixed couples)
                by_base[base_name]["tones"].append(char)
            continue
        item = {"c": char, "name": name, "group": group, "tones": []}
        by_base[name] = item
        out.append(item)
    return out


def read_bundled(path: Path) -> list:
    data = json.loads(path.read_text(encoding="utf-8"))
    out = []
    for char, name, group, tones in data["emoji"]:
        variants = []
        if tones:
            base = char.replace("️", "")
            variants = [base[0] + t + base[1:] if len(base) > 1 else base + t for t in TONES[1:]]
        out.append({"c": char, "name": name, "group": group, "tones": variants})
    return out


def load_emoji() -> list:
    for path in TEST_FILES:
        try:
            got = read_emoji_test(path.read_text(encoding="utf-8"))
            if got:
                return got
        except OSError:
            continue
    try:
        return read_bundled(HERE / "data" / "emoji.json")
    except (OSError, ValueError, KeyError):
        return []


def load_symbols() -> list:
    out = []
    for group, _, ranges in SYMBOLS:
        seen = set()
        for a, b in ranges:
            for cp in range(a, b + 1):
                ch = chr(cp)
                name = unicodedata.name(ch, "")
                if name and ch not in seen and unicodedata.category(ch)[0] not in "CZ":
                    seen.add(ch)
                    out.append({"c": ch, "name": name.lower(), "group": group, "tones": []})
    return out


class Characters(QObject):
    changed = Signal()
    pickedChanged = Signal()          # its own signal: pointing at a character mustn't rebuild the whole tray
    recentChanged = Signal()          # nor must copying one (the tray would jump back to the top)
    said = Signal(str, bool)
    FILE = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share") / "huginn" / "characters.json"

    def __init__(self, demo: bool = False):
        super().__init__()
        self._demo = demo
        self._all = load_emoji() + load_symbols()
        self._group, self._query, self._tone, self._picked = "Smileys & Emotion", "", 0, ""
        self._recent, self._starred = [], []
        if demo:
            self._recent = ["❤️", "😂", "👍", "🎉", "✨", "→", "€", "🙏"]
            self._starred = ["☕", "🌌", "🦊"]
            self._picked = "🦊"
        else:
            try:
                data = json.loads(self.FILE.read_text(encoding="utf-8"))
                self._recent, self._starred, self._tone = data.get("recent", [])[:24], data.get("starred", [])[:60], int(data.get("tone", 0)) % 6
            except (OSError, ValueError, AttributeError):
                pass
        self._by_char = {i["c"]: i for i in self._all}
        for i in self._all:                                     # a toned variant stars and names as its base
            for t in i["tones"]:
                self._by_char.setdefault(t, i)

    def _keep(self) -> None:
        if self._demo:
            return
        try:
            self.FILE.parent.mkdir(parents=True, exist_ok=True)
            self.FILE.write_text(json.dumps({"recent": self._recent, "starred": self._starred, "tone": self._tone}, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass

    def _toned(self, item: dict) -> str:
        return item["tones"][self._tone - 1] if self._tone and item["tones"] and len(item["tones"]) >= self._tone else item["c"]

    def _face(self, item: dict) -> dict:
        shown = self._toned(item)
        return {"c": shown, "base": item["c"], "name": item["name"], "group": item["group"], "tones": bool(item["tones"]), "star": item["c"] in self._starred}

    def _get_items(self) -> list:
        words = self._query.lower().split()
        if words:
            rows = [i for i in self._all if all(w in i["name"] for w in words)]
            rows.sort(key=lambda i: (not i["name"].startswith(words[0]), len(i["name"])))
            return [self._face(i) for i in rows[:400]]
        if self._group == "recent":
            return [dict(self._face(self._by_char.get(c) or {"c": c, "name": unicodedata.name(c[0], "").lower(), "group": "", "tones": []}), c=c) for c in self._recent]
        if self._group == "starred":
            return [self._face(self._by_char.get(c) or {"c": c, "name": unicodedata.name(c[0], "").lower(), "group": "", "tones": []}) for c in self._starred]
        return [self._face(i) for i in self._all if i["group"] == self._group]

    def _get_groups(self) -> list:
        out = [{"id": "recent", "name": "Recent", "mark": "🕘"}, {"id": "starred", "name": "Starred", "mark": "★"}]
        out += [{"id": g, "name": short, "mark": mark} for g, short, mark in GROUPS if any(i["group"] == g for i in self._all)]
        out += [{"id": g, "name": g, "mark": mark} for g, mark, _ in SYMBOLS]
        return out

    def _get_picked(self) -> dict:
        item = self._by_char.get(self._picked)
        if not item and self._picked:
            item = {"c": self._picked, "name": unicodedata.name(self._picked[0], "").lower(), "group": "", "tones": []}
        if not item:
            return {}
        face = self._face(item)
        face["code"] = " ".join(f"U+{ord(ch):04X}" for ch in face["c"] if ch != "️")
        face["html"] = "".join(f"&#x{ord(ch):X};" for ch in face["c"])
        face["variants"] = [item["c"]] + item["tones"]
        return face

    items = Property("QVariantList", _get_items, notify=changed)
    groups = Property("QVariantList", _get_groups, constant=True)
    group = Property(str, lambda self: self._group, notify=changed)
    picked = Property("QVariantMap", _get_picked, notify=pickedChanged)
    tone = Property(int, lambda self: self._tone, notify=changed)
    recent = Property("QVariantList", lambda self: self._recent[:12], notify=recentChanged)
    count = Property(int, lambda self: len(self._all), constant=True)

    @Slot(str)
    def setGroup(self, g: str) -> None:
        self._group = g
        self.changed.emit()

    @Slot(str)
    def search(self, text: str) -> None:
        self._query = text.strip()
        self.changed.emit()

    @Slot(str)
    def pick(self, c: str) -> None:
        if c != self._picked:
            self._picked = c
            self.pickedChanged.emit()

    @Slot(int)
    def setTone(self, n: int) -> None:
        self._tone = max(0, min(5, n))
        self._keep()
        self.changed.emit()
        self.pickedChanged.emit()

    @Slot(str)
    def copy(self, c: str) -> None:
        board = QGuiApplication.clipboard() if QGuiApplication.instance() else None
        if not c or not board:
            return
        board.setText(c)
        self._recent = [c] + [x for x in self._recent if x != c]
        del self._recent[24:]
        self._keep()
        self.recentChanged.emit()
        if self._group == "recent" and not self._query:
            self.changed.emit()
        self.said.emit(f"Copied {c}", False)

    @Slot(str)
    def star(self, c: str) -> None:
        base = self._by_char.get(c, {}).get("c", c)              # stars keep the plain one; your tone shows on it
        if base in self._starred:
            self._starred.remove(base)
        else:
            self._starred.append(base)
        self._keep()
        self.changed.emit()
        self.pickedChanged.emit()
