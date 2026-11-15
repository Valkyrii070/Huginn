#!/usr/bin/env python3
"""Reminders: the store every Huginn app shares, and the Reminders app's backend.

One file, ~/.local/share/huginn/reminders.json. Any app may add to it (Notes, Mail), Calendar shows what has a day,
and the shell tells you when one comes due, so nothing needs to stay running. Writers take a lock and merge with
what is on disk, item by item, newest change winning, so two windows never undo each other.
"""
import calendar as cal
import datetime as dt
import fcntl
import json
import os
import re
import time
import uuid
from pathlib import Path

DATA_HOME = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share") / "huginn"
FILE = DATA_HOME / "reminders.json"
REPEATS = {"daily": "every day", "weekly": "every week", "monthly": "every month", "yearly": "every year"}
FIRST_LIST = "Reminders"


# ------------------------------------------------------------------------------------------------- the store
def _read(path: Path = None) -> dict:
    try:
        data = json.loads((path or FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    items = [i for i in data.get("items", []) if isinstance(i, dict) and i.get("id") and isinstance(i.get("title"), str)]
    lists = [n for n in data.get("lists", []) if isinstance(n, str) and n.strip()]
    gone = {k: v for k, v in (data.get("gone") or {}).items() if isinstance(v, (int, float))}
    return {"lists": lists or [FIRST_LIST], "items": items, "gone": gone}


def change(edit, path: Path = None) -> dict:
    """Read what's on disk, let `edit(data)` change it, write it back, all under a lock. Returns the new data."""
    path = path or FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(str(path) + ".lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        data = _read(path)
        edit(data)
        cutoff = time.time() - 90 * 86400                         # what was deleted is remembered for a while, then forgotten
        data["gone"] = {k: v for k, v in data["gone"].items() if v > cutoff}
        part = path.with_name(".reminders.json.saving")
        part.write_text(json.dumps(data, indent=1), encoding="utf-8")
        os.replace(part, path)
    return data


def add_reminder(title: str, due: str = "", at: str = "", note: str = "", name: str = "", path: Path = None) -> dict:
    """For any app: put a reminder in. `due` is YYYY-MM-DD or "", `at` is HH:MM or ""."""
    item = {"id": uuid.uuid4().hex, "title": " ".join(title.split())[:300] or "Reminder", "note": note[:2000], "due": due, "time": at if due else "", "done": False,
            "list": name or FIRST_LIST, "repeat": "", "flag": False, "changed": time.time()}

    def edit(data):
        if item["list"] not in data["lists"]:
            item["list"] = data["lists"][0]
        data["items"].append(item)
    change(edit, path)
    return item


# ------------------------------------------------------------------------------------- "call Sam tomorrow 9am"
DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"]


def parse_when(text: str, today: dt.date = None) -> tuple:
    """Pull a day and a time out of what was typed. Returns (title without them, "YYYY-MM-DD" or "", "HH:MM" or "").
    Understands: today, tonight, tomorrow, a weekday (the next one), next week, in 3 days / 2 weeks, 2026-12-01,
    13 nov, nov 13, and times like 9am, 9:30 pm, 14:30, at 9, noon. A time alone means today (tomorrow if it has passed)."""
    today = today or dt.date.today()
    words, day, at = " " + " ".join(text.split()) + " ", None, ""

    def take(pattern: str):
        nonlocal words
        m = re.search(pattern, words, re.I)
        if m:
            words = words[:m.start()] + " " + words[m.end():]
        return m

    m = take(r"\s(?:at\s+)?(\d{1,2})[:.](\d\d)\s*(am|pm)?(?=\s)")
    if m and int(m.group(1)) < 24 and int(m.group(2)) < 60:
        hour = int(m.group(1)) % 12 + (12 if (m.group(3) or "").lower() == "pm" else 0) if m.group(3) else int(m.group(1))
        at = f"{hour:02d}:{m.group(2)}"
    if not at:
        m = take(r"\s(?:at\s+)?(\d{1,2})\s*(am|pm)(?=\s)")
        if m and 1 <= int(m.group(1)) <= 12:
            at = f"{int(m.group(1)) % 12 + (12 if m.group(2).lower() == 'pm' else 0):02d}:00"
    if not at:
        m = take(r"\sat\s+(\d{1,2})(?=\s)")
        if m and int(m.group(1)) < 24:
            hour = int(m.group(1))
            at = f"{hour + 12 if 1 <= hour <= 6 else hour:02d}:00"         # "at 3" is the afternoon
    if not at:
        m = take(r"\s(?:at\s+)?(noon|midday|midnight)(?=\s)")
        if m:
            at = "00:00" if m.group(1).lower() == "midnight" else "12:00"
    if take(r"\s(tonight|this evening)(?=\s)"):
        day, at = today, at or "19:00"
    elif take(r"\stoday(?=\s)"):
        day = today
    elif take(r"\s(tomorrow|tmrw)(?=\s)"):
        day = today + dt.timedelta(days=1)
    elif take(r"\snext week(?=\s)"):
        day = today + dt.timedelta(days=7)
    else:
        m = take(r"\sin\s+(\d{1,3}|a|an|one|two|three)\s+(day|week|month)s?(?=\s)")
        if m:
            n = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3}.get(m.group(1).lower()) or int(m.group(1))
            unit = m.group(2).lower()
            day = today + dt.timedelta(days=n * (7 if unit == "week" else 1)) if unit != "month" else _months_on(today, n)
    if day is None:
        m = take(r"\s(\d{4})-(\d\d)-(\d\d)(?=\s)")
        if m:
            try:
                day = dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            except ValueError:
                pass
    if day is None:
        names = "|".join(n[:3] + "(?:" + n[3:] + ")?" for n in MONTHS)
        m = take(rf"\s(?:on\s+)?(\d{{1,2}})(?:st|nd|rd|th)?\s+({names})(?=\s)") or take(rf"\s(?:on\s+)?({names})\s+(\d{{1,2}})(?:st|nd|rd|th)?(?=\s)")
        if m:
            a, b = m.group(1), m.group(2)
            num, name = (a, b) if a.isdigit() else (b, a)
            month = next(i for i, n in enumerate(MONTHS) if n.startswith(name.lower()[:3])) + 1
            try:
                day = dt.date(today.year, month, int(num))
                if day < today:
                    day = dt.date(today.year + 1, month, int(num))
            except ValueError:
                day = None
    if day is None:
        names = "|".join(n[:3] + "(?:" + n[3:] + ")?" for n in DAYS)
        m = take(rf"\s(?:on\s+|next\s+)?({names})(?=\s)")
        if m:
            want = next(i for i, n in enumerate(DAYS) if n.startswith(m.group(1).lower()[:3]))
            day = today + dt.timedelta(days=(want - today.weekday() - 1) % 7 + 1)
    if day is None and at:
        now = dt.datetime.now()
        day = today if (today != now.date() or at > now.strftime("%H:%M")) else today + dt.timedelta(days=1)
    title = re.sub(r"\s+(on|at|by)\s*$", "", " ".join(words.split()), flags=re.I).strip()
    return title, day.isoformat() if day else "", at if day else ""


def _months_on(day: dt.date, n: int) -> dt.date:
    month = day.month - 1 + n
    year, month = day.year + month // 12, month % 12 + 1
    return dt.date(year, month, min(day.day, cal.monthrange(year, month)[1]))


def next_due(due: str, repeat: str) -> str:
    day = dt.date.fromisoformat(due)
    if repeat == "daily":
        return (day + dt.timedelta(days=1)).isoformat()
    if repeat == "weekly":
        return (day + dt.timedelta(days=7)).isoformat()
    if repeat == "monthly":
        return _months_on(day, 1).isoformat()
    return _months_on(day, 12).isoformat()


def when_words(due: str, at: str, today: dt.date = None) -> str:
    if not due:
        return ""
    today = today or dt.date.today()
    day = dt.date.fromisoformat(due)
    gap = (day - today).days
    word = "Today" if gap == 0 else "Tomorrow" if gap == 1 else "Yesterday" if gap == -1 else day.strftime("%A") if 1 < gap < 7 else \
        f"{day.day} {cal.month_abbr[day.month]}" + (f" {day.year}" if day.year != today.year else "")
    return word + (f", {at}" if at else "")


def is_late(item: dict, now: dt.datetime = None) -> bool:
    now = now or dt.datetime.now()
    if item.get("done") or not item.get("due"):
        return False
    return (item["due"], item.get("time") or "23:59") < (now.date().isoformat(), now.strftime("%H:%M"))


def to_tell(items: list, told: dict, now: dt.datetime = None) -> list:
    """Which reminders have just come due and haven't been announced? (The shell asks this every half minute.)
    One with no time is announced at nine in the morning. Anything more than twelve hours late is left alone: an
    old list shouldn't shout at you when you log in. `told` maps id -> the due moment already announced."""
    now = now or dt.datetime.now()
    out = []
    for item in items:
        if item.get("done") or not item.get("due"):
            continue
        try:
            when = dt.datetime.fromisoformat(f"{item['due']}T{item.get('time') or '09:00'}")
        except ValueError:
            continue
        stamp = when.isoformat()
        if when <= now < when + dt.timedelta(hours=12) and told.get(item["id"]) != stamp:
            told[item["id"]] = stamp
            out.append(item)
    return out


# ------------------------------------------------------------------------------------------- the app's backend
try:
    from PySide6.QtCore import Property, QObject, QTimer, Signal, Slot
except ImportError:                                                # the store works without Qt (the shell reads the file itself)
    QObject = None

if QObject is not None:
    class Reminders(QObject):
        changed = Signal()
        said = Signal(str)

        def __init__(self, demo: bool = False, path: Path = None):
            super().__init__()
            self._demo, self._path, self._view, self._seen = demo, path or FILE, "today", None
            if demo:
                today = dt.date.today()
                d = lambda n: (today + dt.timedelta(days=n)).isoformat()      # noqa: E731
                rows = [("Send the release notes", d(0), "10:00", "", False, True), ("Call Sam about the dock", d(0), "16:30", "He wanted widgets that snap to a grid.", False, False),
                        ("Water the plants", d(-1), "", "", False, False), ("Book the hardware test", d(2), "11:00", "", False, False), ("Renew the domain", d(9), "", "", False, False),
                        ("Back up the build machine", d(0), "", "", True, False)]
                self._data = {"lists": [FIRST_LIST, "Huginn OS", "Home"], "gone": {},
                              "items": [{"id": str(i), "title": t, "due": due, "time": at, "note": note, "done": done, "flag": flag, "repeat": "weekly" if i == 2 else "",
                                         "list": ["Huginn OS", "Huginn OS", "Home", "Huginn OS", FIRST_LIST, "Home"][i], "changed": 0} for i, (t, due, at, note, done, flag) in enumerate(rows)]}
                return
            self._data = _read(self._path)
            self._seen = self._stamp()
            self._watch = QTimer(self)                             # Notes, Mail or another window may add one
            self._watch.setInterval(3000)
            self._watch.timeout.connect(self._absorb)
            self._watch.start()
            self._badge()

        def _stamp(self):
            try:
                st = self._path.stat()
                return st.st_mtime_ns, st.st_size
            except OSError:
                return None

        def _absorb(self) -> None:
            if self._stamp() != self._seen:
                self._seen, self._data = self._stamp(), _read(self._path)
                self._badge()
                self.changed.emit()

        def _do(self, edit) -> None:
            if self._demo:
                edit(self._data)
            else:
                self._data = change(edit, self._path)
                self._seen = self._stamp()
                self._badge()
            self.changed.emit()

        def _badge(self) -> None:
            base = os.environ.get("XDG_RUNTIME_DIR")
            if not base or self._demo:
                return
            n = sum(1 for i in self._data["items"] if not i.get("done") and i.get("due") and i["due"] <= dt.date.today().isoformat())
            try:
                folder = Path(base) / "huginn" / "badges"
                folder.mkdir(parents=True, exist_ok=True)
                if n:
                    (folder / "reminders").write_text(str(n), encoding="ascii")
                else:
                    (folder / "reminders").unlink(missing_ok=True)
            except OSError:
                pass

        # ---- what the screen shows
        def _in_view(self, i: dict, view: str) -> bool:
            today = dt.date.today().isoformat()
            if view == "done":
                return bool(i.get("done"))
            if i.get("done"):
                return False
            if view == "today":
                return bool(i.get("due")) and i["due"] <= today
            if view == "scheduled":
                return bool(i.get("due"))
            if view == "flagged":
                return bool(i.get("flag"))
            if view.startswith("list:"):
                return i.get("list") == view[5:]
            return True

        view = Property(str, lambda self: self._view, notify=changed)

        @Property("QVariantList", notify=changed)
        def views(self):
            count = lambda v: sum(1 for i in self._data["items"] if self._in_view(i, v))      # noqa: E731
            out = [{"id": "today", "name": "Today", "icon": "sun", "count": count("today")}, {"id": "scheduled", "name": "Scheduled", "icon": "calendar", "count": count("scheduled")},
                   {"id": "all", "name": "All", "icon": "inbox", "count": count("all")}, {"id": "flagged", "name": "Flagged", "icon": "star", "count": count("flagged")}]
            return out

        @Property("QVariantList", notify=changed)
        def lists(self):
            return [{"id": "list:" + n, "name": n, "count": sum(1 for i in self._data["items"] if not i.get("done") and i.get("list") == n)} for n in self._data["lists"]]

        @Property(str, notify=changed)
        def heading(self):
            if getattr(self, "_query", ""):
                return "Found"
            return self._view[5:] if self._view.startswith("list:") else {"today": "Today", "scheduled": "Scheduled", "all": "All", "flagged": "Flagged", "done": "Done"}.get(self._view, "")

        @Property("QVariantList", notify=changed)
        def rows(self):
            q = getattr(self, "_query", "")
            rows = [i for i in self._data["items"] if (q in (i["title"] + " " + i.get("note", "")).lower() and not i.get("done")) or (not q and self._in_view(i, self._view))] if q else \
                   [i for i in self._data["items"] if self._in_view(i, self._view)]
            if self._view == "done":
                rows.sort(key=lambda i: -float(i.get("changed") or 0))
            else:
                rows.sort(key=lambda i: (not i.get("due"), i.get("due") or "", i.get("time") or "99", i["title"].lower()))
            return [{"id": i["id"], "title": i["title"], "note": i.get("note", ""), "due": i.get("due", ""), "time": i.get("time", ""), "done": bool(i.get("done")),
                     "flag": bool(i.get("flag")), "list": i.get("list", ""), "repeat": i.get("repeat", ""), "repeats": REPEATS.get(i.get("repeat", ""), ""),
                     "when": when_words(i.get("due", ""), i.get("time", "")), "late": is_late(i)} for i in rows[:500]]

        @Slot(str)
        def setQuery(self, text: str) -> None:
            self._query = " ".join(text.lower().split())
            self.changed.emit()

        query = Property(str, lambda self: getattr(self, "_query", ""), notify=changed)

        @Slot(str, str)
        def snooze(self, ident: str, until: str) -> None:
            """Put one off: "hour" (an hour from now), "evening" (today 18:00), "tomorrow" (same time), "week" (next Monday 09:00)."""
            now = dt.datetime.now()

            def fn(i):
                at = i.get("time") or ""
                if until == "hour":
                    later = now + dt.timedelta(hours=1)
                    i["due"], i["time"] = later.date().isoformat(), later.strftime("%H:%M")
                elif until == "evening":
                    i["due"], i["time"] = now.date().isoformat(), "18:00"
                elif until == "tomorrow":
                    i["due"], i["time"] = (now.date() + dt.timedelta(days=1)).isoformat(), at
                elif until == "week":
                    i["due"], i["time"] = (now.date() + dt.timedelta(days=7 - now.weekday())).isoformat(), at or "09:00"
                i["done"] = False
                self.said.emit(f"Moved to {when_words(i['due'], i.get('time', ''))}.")
            self._edit(ident, fn)

        doneCount = Property(int, lambda self: sum(1 for i in self._data["items"] if i.get("done")), notify=changed)

        # ---- what you can do
        @Slot(str)
        def setView(self, view: str) -> None:
            self._view = view
            self.changed.emit()

        @Slot(str)
        def add(self, text: str) -> None:
            """A new one, from a line as it was typed: "Call Sam tomorrow 9am"."""
            title, due, at = parse_when(text)
            if not title and not text.strip():
                return
            if self._view == "today" and not due:
                due = dt.date.today().isoformat()
            item = {"id": uuid.uuid4().hex, "title": (title or text.strip())[:300], "note": "", "due": due, "time": at, "done": False, "flag": self._view == "flagged",
                    "list": self._view[5:] if self._view.startswith("list:") else self._data["lists"][0], "repeat": "", "changed": time.time()}
            self._do(lambda data: data["items"].append(item))
            if due and self._view not in ("today", "scheduled", "all") and not self._view.startswith("list:"):
                self.said.emit(f"Added for {when_words(due, at)}.")

        def _edit(self, ident: str, fn) -> None:
            def edit(data):
                for i in data["items"]:
                    if i["id"] == ident:
                        fn(i)
                        i["changed"] = time.time()
            self._do(edit)

        @Slot(str)
        def toggle(self, ident: str) -> None:
            """Tick it off. One that repeats moves on to its next day instead."""
            def fn(i):
                if not i.get("done") and i.get("repeat") in REPEATS and i.get("due"):
                    today = dt.date.today().isoformat()
                    i["due"] = next_due(i["due"], i["repeat"])
                    while i["due"] <= today and i["repeat"] != "yearly":       # long overdue: skip to the next one still ahead
                        i["due"] = next_due(i["due"], i["repeat"])
                    self.said.emit(f"Done. Next: {when_words(i['due'], i.get('time', ''))}.")
                else:
                    i["done"] = not i.get("done")
            self._edit(ident, fn)

        @Slot(str)
        def flag(self, ident: str) -> None:
            self._edit(ident, lambda i: i.update(flag=not i.get("flag")))

        @Slot(str, "QVariantMap", result=str)
        def save(self, ident: str, fields) -> str:
            """Change one from the details sheet. Returns "" or what's wrong."""
            title = " ".join(str(fields.get("title", "")).split())
            due, at = str(fields.get("due", "")).strip(), str(fields.get("time", "")).strip()
            if not title:
                return "It needs a few words to say what it is."
            if due and not re.fullmatch(r"\d{4}-\d\d-\d\d", due):
                _t, due, at2 = parse_when(due + (" " + at if at else ""))
                at = at2 or at
                if not due:
                    return "Write the day like tomorrow, friday, 13 nov or 2026-12-01."
            if at:
                m = re.fullmatch(r"(\d{1,2})[:.](\d\d)", at)
                if not m or int(m.group(1)) > 23 or int(m.group(2)) > 59:
                    _t, _d, at2 = parse_when("x " + at, dt.date.fromisoformat(due) if due else None)
                    if not at2:
                        return "Write the time like 14:30 or 9am."
                    at = at2
                else:
                    at = f"{int(m.group(1)):02d}:{m.group(2)}"
            if due:
                try:
                    dt.date.fromisoformat(due)
                except ValueError:
                    return "That day doesn't exist."
            repeat, name = str(fields.get("repeat", "")), str(fields.get("list", ""))
            self._edit(ident, lambda i: i.update(title=title[:300], note=str(fields.get("note", ""))[:2000], due=due, time=at if due else "",
                                                 repeat=repeat if repeat in REPEATS and due else "", list=name if name in self._data["lists"] else i.get("list", FIRST_LIST)))
            return ""

        @Slot(str)
        def remove(self, ident: str) -> None:
            def edit(data):
                data["items"] = [i for i in data["items"] if i["id"] != ident]
                data["gone"][ident] = time.time()
            self._do(edit)

        @Slot()
        def clearDone(self) -> None:
            def edit(data):
                for i in data["items"]:
                    if i.get("done"):
                        data["gone"][i["id"]] = time.time()
                data["items"] = [i for i in data["items"] if not i.get("done")]
            self._do(edit)

        @Slot(str, result=str)
        def addList(self, name: str) -> str:
            name = " ".join(name.split())[:40]
            if not name:
                return "Give the list a name."
            if name.lower() in (n.lower() for n in self._data["lists"]):
                return "There's already a list by that name."
            self._do(lambda data: data["lists"].append(name))
            self.setView("list:" + name)
            return ""

        @Slot(str)
        def removeList(self, name: str) -> None:
            """Take a list away. What was on it moves to the first list, so nothing is lost."""
            if name not in self._data["lists"] or len(self._data["lists"]) < 2:
                return

            def edit(data):
                data["lists"] = [n for n in data["lists"] if n != name]
                for i in data["items"]:
                    if i.get("list") == name:
                        i["list"], i["changed"] = data["lists"][0], time.time()
            self._do(edit)
            self.setView("all")
