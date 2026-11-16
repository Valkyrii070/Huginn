"""Today: what opens from the date in the top bar (or Super+T). Four islands: the month, the weather now and over
the next hours (your first place in Weather), the agenda (today, tomorrow, later this week, with reminders) and
clocks. Pick a day and its events show; open an event in place; add one by typing it as you'd say it
("Lunch with Astrid Friday 12", "remind me to call Sam tomorrow at 5").

Reads Calendar's and Reminders' own files (through Calendar's backend, as the desktop's cards do) and Weather's.
Which islands show and which clocks: ~/.config/huginn-shell/today.json.
"""
from __future__ import annotations

import calendar as cal
import datetime as dt
import json
import os
import re
import sys
from pathlib import Path

from PySide6.QtCore import Property, QObject, QTimer, Signal, Slot

CONFIG = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "huginn-shell" / "today.json"
DATA = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share") / "huginn"
ZONES = {"Reykjavík": "Atlantic/Reykjavik", "London": "Europe/London", "Paris": "Europe/Paris", "Berlin": "Europe/Berlin",
         "New York": "America/New_York", "Chicago": "America/Chicago", "Los Angeles": "America/Los_Angeles", "Tokyo": "Asia/Tokyo",
         "Sydney": "Australia/Sydney", "Singapore": "Asia/Singapore", "Dubai": "Asia/Dubai", "São Paulo": "America/Sao_Paulo"}
DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"]
TONES = ["#8E7BFF", "#3DD68C", "#FF5470", "#38B6FF", "#FFB340"]


# ----------------------------------------------------------------------------------------------- reading what's typed
def parse(text: str, today: dt.date | None = None) -> dict:
    """'Lunch with Astrid Friday 12' -> {title, date, time, end, reminder}. Understands today/tonight/tomorrow,
    weekdays (this or next), 'next week', 'in 3 days', 'Nov 20' / '20 Nov' / '20/11', times like 12, 3pm, 15:30,
    'at 9', 'noon'; 'remind me to …' makes a reminder."""
    today = today or dt.date.today()
    words = text.strip()
    out = {"title": "", "date": "", "time": "", "end": "", "reminder": False}
    low = words.lower()
    m = re.match(r"^\s*(remind me (to|about)\s+|reminder:?\s+|todo:?\s+)", low)
    if m:
        out["reminder"] = True
        words = words[m.end():]
        low = words.lower()
    date = None
    spans = []

    def take(pattern):
        found = re.search(pattern, low)
        if found:
            spans.append(found.span())
        return found

    if (f := take(r"\b(today|tonight)\b")):
        date = today
        if f.group(1) == "tonight" and not out["time"]:
            out["time"] = "19:00"
    elif take(r"\btomorrow\b"):
        date = today + dt.timedelta(days=1)
    elif (f := take(r"\bin (\d+) (day|days|week|weeks)\b")):
        n = int(f.group(1))
        date = today + dt.timedelta(days=n * (7 if f.group(2).startswith("week") else 1))
    elif take(r"\bnext week\b"):
        date = today + dt.timedelta(days=7 - today.weekday())
    if date is None and (f := take(r"\b(next |this |on )?(mon|tue|tues|wed|thu|thur|thurs|fri|sat|sun)(day|sday|nesday|rsday|urday)?\b")):
        idx = [d[:3] for d in DAYS].index(f.group(2)[:3])
        ahead = (idx - today.weekday()) % 7
        word = (f.group(1) or "").strip()
        if ahead == 0 and word != "this":
            ahead = 7                                      # "Friday" on a Friday: the next one
        date = today + dt.timedelta(days=ahead)
    if date is None:
        mon = r"(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*"
        f = take(rf"\b(\d{{1,2}})(st|nd|rd|th)? {mon}\b") or take(rf"\b{mon} (\d{{1,2}})(st|nd|rd|th)?\b")
        if f:
            g = f.groups()
            day, month = (int(g[0]), g[2]) if g[0].isdigit() else (int(g[1]), g[0])
            mi = [m_[:3] for m_ in MONTHS].index(month[:3]) + 1
            try:
                date = dt.date(today.year, mi, day)
                if date < today:
                    date = dt.date(today.year + 1, mi, day)
            except ValueError:
                date = None
        elif (f := take(r"\b(\d{1,2})/(\d{1,2})\b")):
            try:
                date = dt.date(today.year, int(f.group(2)), int(f.group(1)))
                if date < today:
                    date = date.replace(year=today.year + 1)
            except ValueError:
                date = None
    # the time
    t = take(r"\b(at )?(noon|midday|midnight)\b")
    if t:
        out["time"] = "12:00" if t.group(2) != "midnight" else "00:00"
    else:
        t = (take(r"\b(at |@ ?)?(?P<h>\d{1,2})[:.](?P<m>\d{2}) ?(?P<ap>am|pm|a\.m\.|p\.m\.)?(?=\W|$)")
             or take(r"\b(at |@ ?)?(?P<h>\d{1,2}) ?(?P<ap>am|pm|a\.m\.|p\.m\.)(?=\W|$)")
             or take(r"\b(at |@ ?)(?P<h>\d{1,2})\b")
             or (take(r"\b(?P<h>\d{1,2})$") if date is not None else None))
        if t:
            g = t.groupdict()
            hour, minute = int(g["h"]), int(g.get("m") or 0)
            ampm = (g.get("ap") or "").replace(".", "")
            if ampm == "pm" and hour < 12:
                hour += 12
            elif ampm == "am" and hour == 12:
                hour = 0
            elif not ampm and 1 <= hour <= 7 and not g.get("m"):   # "at 3" is the afternoon
                hour += 12
            if 0 <= hour < 24 and 0 <= minute < 60:
                out["time"] = f"{hour:02d}:{minute:02d}"
    # what's left is the title
    title = words
    for a, b in sorted(spans, reverse=True):
        title = title[:a] + " " + title[b:]
    title = re.sub(r"\s+(on|at|by|for)\s*$", "", re.sub(r"\s{2,}", " ", title)).strip(" ,.-")
    out["title"] = title[:1].upper() + title[1:] if title else ""
    if date is None and out["time"]:
        date = today
    out["date"] = date.isoformat() if date else ""
    if out["time"] and not out["reminder"]:
        h, mi_ = map(int, out["time"].split(":"))
        end = (dt.datetime.combine(today, dt.time(h, mi_)) + dt.timedelta(hours=1)).time()
        out["end"] = end.strftime("%H:%M")
    return out


H24 = [False]                      # the bar's clock is 24-hour (Settings: clock24); set by Today


def clock_words(hhmm: str) -> str:
    """'15:30' -> '3:30 PM', or as it is where the clock is 24-hour (the same as the bar's clock)."""
    if not hhmm:
        return ""
    h, m = map(int, hhmm.split(":"))
    if H24[0]:
        return f"{h:02d}:{m:02d}"
    return f"{(h % 12) or 12}:{m:02d} {'AM' if h < 12 else 'PM'}"


# ----------------------------------------------------------------------------------------------- Today
class Today(QObject):
    changed = Signal()

    def __init__(self, demo: bool = False, settings=None):
        super().__init__()
        self._demo = demo
        self._settings = settings
        self._cfg = {"islands": {"month": True, "weather": True, "agenda": True, "clocks": True}, "clocks": ["Reykjavík", "New York", "Tokyo"]}
        try:
            saved = json.loads(CONFIG.read_text(encoding="utf-8"))
            self._cfg["islands"].update(saved.get("islands", {}))
            if isinstance(saved.get("clocks"), list):
                self._cfg["clocks"] = [c for c in saved["clocks"] if c in ZONES][:4]
        except (OSError, ValueError, AttributeError):
            pass
        t = dt.date.today()
        self._year, self._month, self._picked = t.year, t.month, ""
        self._calendar = None
        self._weather = {}
        if not demo:
            for d in (Path("/usr/share/huginn-apps"), Path(__file__).resolve().parent.parent / "apps"):
                if (d / "huginn_app.py").exists() and str(d) not in sys.path:
                    sys.path.append(str(d))
        from PySide6.QtCore import QFileSystemWatcher
        try:
            CONFIG.parent.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        self._cfg_watch = QFileSystemWatcher([str(CONFIG.parent)] if CONFIG.parent.is_dir() else [], self)   # Settings › Desktop & Dock
        self._cfg_watch.directoryChanged.connect(lambda _: self._reload_cfg())
        self._tick = QTimer(self, interval=30000, timeout=self.refresh)
        self._tick.start()
        QTimer.singleShot(1200, self.refresh)

    def _reload_cfg(self) -> None:
        try:
            saved = json.loads(CONFIG.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        islands = {**self._cfg["islands"], **saved.get("islands", {})}
        clocks = [c for c in saved.get("clocks", self._cfg["clocks"]) if c in ZONES][:4]
        if islands != self._cfg["islands"] or clocks != self._cfg["clocks"]:
            self._cfg["islands"], self._cfg["clocks"] = islands, clocks
            self.changed.emit()

    # ---- reading
    def _cal(self):
        if self._calendar is None:
            try:
                from huginn_app import Calendar
                self._calendar = Calendar(self._demo)
            except Exception:  # noqa: BLE001 — Calendar isn't installed
                self._calendar = False
        return self._calendar or None

    def _on(self, day: dt.date) -> list:
        c = self._cal()
        if not c:
            return []
        try:
            rows = c._on(day)
        except Exception:  # noqa: BLE001
            return []
        out = []
        for i, e in enumerate(rows):
            end = e.get("end", "") if isinstance(e.get("end"), str) and ":" in e.get("end", "") else ""
            when = "Due today" if e.get("reminder") and day == dt.date.today() else ""
            if e.get("time"):
                when = clock_words(e["time"]) + ("–" + clock_words(end) if end else "")
            elif not e.get("reminder"):
                when = "All day"
            out.append({"id": e.get("id", ""), "title": e.get("title", ""), "date": day.isoformat(), "time": e.get("time", ""), "when": when,
                        "reminder": bool(e.get("reminder")), "where": e.get("where", "") or e.get("location", ""), "notes": e.get("notes", "") or e.get("description", ""),
                        "remind": e.get("alarm", "") or e.get("remind", ""), "call": e.get("call", "") or e.get("url", ""),
                        "repeats": e.get("repeats", ""), "tone": TONES[sum(map(ord, e.get("title", ""))) % len(TONES)]})
        return out

    def _read_weather(self) -> dict:
        try:
            saved = json.loads((DATA / "weather.json").read_text(encoding="utf-8"))
            at = int(saved.get("at", 0))
            place = saved["places"][at]
            fc = saved.get("data", {}).get(str(at)) or {}
        except (OSError, ValueError, KeyError, IndexError, TypeError):
            return {}
        try:
            from huginn_more import WMO
        except Exception:  # noqa: BLE001
            WMO = {}

        def deg(v):
            return "" if v is None else f"{round(v)}°".replace("-", "−")
        cur, daily, hourly = fc.get("current") or {}, fc.get("daily") or {}, fc.get("hourly") or {}
        today = dt.date.today().isoformat()
        hi = lo = ""
        for i, day in enumerate(daily.get("time") or []):
            if day == today:
                hi, lo = deg((daily.get("temperature_2m_max") or [None] * (i + 1))[i]), deg((daily.get("temperature_2m_min") or [None] * (i + 1))[i])
        hours = []
        now = dt.datetime.now()
        for i, stamp in enumerate(hourly.get("time") or []):
            try:
                when = dt.datetime.fromisoformat(stamp)
            except ValueError:
                continue
            if when > now and len(hours) < 5:
                hours.append({"hour": when.strftime("%H:00") if H24[0] else when.strftime("%-I %p"),
                              "temp": deg((hourly.get("temperature_2m") or [None] * (i + 1))[i]),
                              "rain": (hourly.get("precipitation_probability") or [0] * (i + 1))[i] or 0})
        code = cur.get("weather_code")
        return {"place": place.get("name", ""), "temp": deg(cur.get("temperature_2m")), "words": WMO.get(code, ("", ""))[0],
                "high": hi, "low": lo, "hours": hours, "code": code if code is not None else -1, "day": bool(cur.get("is_day", 1))}

    @Slot()
    def refresh(self) -> None:
        try:
            H24[0] = self._settings is not None and str(self._settings.property("clock24")).lower() == "true"
        except Exception:  # noqa: BLE001
            pass
        if self._demo:
            self._weather = {"place": "Chicago", "temp": "−1°", "words": "Clear", "high": "4°", "low": "−3°", "code": 0, "day": True,
                             "hours": [{"hour": f"{h} PM", "temp": t, "rain": 0} for h, t in ((3, "2°"), (4, "1°"), (5, "0°"), (6, "−1°"), (7, "−2°"))]}
        else:
            self._weather = self._read_weather()
        c = self._cal()
        if c is not None:
            try:
                c._absorb()
            except Exception:  # noqa: BLE001
                pass
        self.changed.emit()

    # ---- what QML reads
    def _month_days(self) -> list:
        today, out = dt.date.today(), []
        for day in cal.Calendar(firstweekday=0).itermonthdates(self._year, self._month):
            evs = self._on(day) if day.month == self._month else []
            out.append({"date": day.isoformat(), "day": day.day, "inMonth": day.month == self._month, "today": day == today,
                        "picked": day.isoformat() == self._picked, "dots": [e["tone"] for e in evs[:3]]})
        return out

    def _agenda(self) -> list:
        """Sections: the picked day's, or Today / Tomorrow / Later this week."""
        today = dt.date.today()
        if self._picked:
            day = dt.date.fromisoformat(self._picked)
            label = "TODAY" if day == today else "TOMORROW" if day == today + dt.timedelta(days=1) else day.strftime("%A, %B ").upper() + str(day.day)
            return [{"label": label, "items": self._on(day), "date": self._picked}]
        out = [{"label": "TODAY", "items": self._on(today), "date": today.isoformat()},
               {"label": "TOMORROW", "items": self._on(today + dt.timedelta(days=1)), "date": (today + dt.timedelta(days=1)).isoformat()}]
        later = []
        for n in range(2, 7):
            d = today + dt.timedelta(days=n)
            for e in self._on(d):
                e["when"] = d.strftime("%a, %b ") + str(d.day) + (" · " + e["when"] if e["when"] and e["when"] != "All day" else "")
                later.append(e)
        if later:
            out.append({"label": "LATER THIS WEEK", "items": later[:4], "date": ""})
        return out

    def _clocks(self) -> list:
        try:
            from zoneinfo import ZoneInfo
        except ImportError:
            return []
        here, out = dt.datetime.now().astimezone(), []
        for city in self._cfg["clocks"]:
            try:
                there = here.astimezone(ZoneInfo(ZONES[city]))
            except Exception:  # noqa: BLE001
                continue
            diff = (there.date() - here.date()).days
            out.append({"city": city, "time": clock_words(there.strftime("%H:%M")), "plus": "+1" if diff > 0 else "−1" if diff < 0 else ""})
        return out

    title = Property(str, lambda self: f"{cal.month_name[self._month]} {self._year}", notify=changed)
    weekdays = Property("QVariantList", lambda self: [d[:1].upper() for d in DAYS], constant=True)
    days = Property("QVariantList", _month_days, notify=changed)
    agenda = Property("QVariantList", _agenda, notify=changed)
    picked = Property(str, lambda self: self._picked, notify=changed)
    weather = Property("QVariantMap", lambda self: self._weather, notify=changed)
    clocks = Property("QVariantList", _clocks, notify=changed)
    islands = Property("QVariantMap", lambda self: self._cfg["islands"], notify=changed)
    clockCities = Property("QVariantList", lambda self: list(self._cfg["clocks"]), notify=changed)
    allCities = Property("QVariantList", lambda self: list(ZONES), constant=True)

    # ---- doing
    @Slot(int)
    def step(self, months: int) -> None:
        m = self._month - 1 + months
        self._year, self._month = self._year + m // 12, m % 12 + 1
        self.changed.emit()

    @Slot(str)
    def pick(self, iso: str) -> None:
        """A day in the month: its events show (the same day again, or "", goes back to today and what's coming)."""
        self._picked = "" if iso == self._picked or iso == dt.date.today().isoformat() else iso
        self.changed.emit()

    @Slot()
    def reset(self) -> None:
        t = dt.date.today()
        self._year, self._month, self._picked = t.year, t.month, ""
        self.changed.emit()

    @Slot(str, result="QVariantMap")
    def preview(self, text: str) -> dict:
        """What typing makes, before Enter: {title, when, reminder, ok}."""
        p = parse(text)
        if not p["title"]:
            return {"ok": False}
        day = dt.date.fromisoformat(p["date"]) if p["date"] else None
        today = dt.date.today()
        words = ("Today" if day == today else "Tomorrow" if day == today + dt.timedelta(days=1) else day.strftime("%a, %b ") + str(day.day)) if day else ""
        if p["time"]:
            words += (" · " if words else "") + clock_words(p["time"]) + ("–" + clock_words(p["end"]) if p["end"] else "")
        if p["reminder"]:
            words = ("Reminder · " + words) if words else "Reminder"
        elif not day:
            words = "Today · All day"
        return {"ok": True, "title": p["title"], "when": words, "reminder": p["reminder"]}

    @Slot(str, result=bool)
    def add(self, text: str) -> bool:
        p = parse(text)
        if not p["title"] or self._demo:
            return bool(p["title"])
        if p["reminder"]:
            try:
                from huginn_reminders import add_reminder
                add_reminder(p["title"], due=p["date"], at=p["time"])
            except Exception:  # noqa: BLE001
                return False
        else:
            c = self._cal()
            if not c:
                return False
            c.select(p["date"] or dt.date.today().isoformat())
            c.add(p["title"], p["time"])
        self.refresh()
        return True

    @Slot(str)
    def openInCalendar(self, iso: str) -> None:
        from PySide6.QtCore import QProcess
        for d in (Path("/usr/share/huginn-apps"), Path(__file__).resolve().parent.parent / "apps"):
            if (d / "huginn_app.py").exists():
                QProcess.startDetached("python3", [str(d / "huginn_app.py"), "calendar"] + (["--page", iso] if iso else []))
                return

    @Slot(str)
    def join(self, url: str) -> None:
        if url:
            from PySide6.QtCore import QUrl
            from PySide6.QtGui import QDesktopServices
            QDesktopServices.openUrl(QUrl(url))

    @Slot(str, bool)
    def setIsland(self, name: str, on: bool) -> None:
        if name in self._cfg["islands"]:
            self._cfg["islands"][name] = on
            self._save()

    @Slot("QVariantList")
    def setClocks(self, cities: list) -> None:
        self._cfg["clocks"] = [c for c in cities if c in ZONES][:4]
        self._save()

    def _save(self) -> None:
        try:
            CONFIG.parent.mkdir(parents=True, exist_ok=True)
            CONFIG.write_text(json.dumps(self._cfg, indent=1, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass
        self.changed.emit()
