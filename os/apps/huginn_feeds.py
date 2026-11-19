"""Feeds: news and blogs you follow, as a paper you read in the morning.

Reads RSS (0.9x, 1.0 and 2.0), Atom and JSON Feed. Each site is asked directly for its own feed and nobody else is
told what you read; a feed that hasn't changed answers "nothing new" (ETag / Last-Modified) and costs nothing.
Articles are shown as plain text with links: no scripts, no styles, no pictures from the web (those would tell the
site who is reading and when). Open the article in Huginn for the full page."""
import calendar
import datetime as dt
import email.utils
import hashlib
import html
import json
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path

from PySide6.QtCore import Property, QObject, QStandardPaths, QTimer, QUrl, Signal, Slot

DATA_HOME = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share") / "huginn"
AGENT = "Huginn Feeds/1.0 (desktop app; https://github.com/Valkyrii070/Huginn)"
KEEP = 400                  # newest articles kept per feed (starred ones are always kept)
FRESH = 30 * 60             # how often the open app checks again
ATOM, RDF, RSS1, CONTENT, DC = ("{http://www.w3.org/2005/Atom}", "{http://www.w3.org/1999/02/22-rdf-syntax-ns#}", "{http://purl.org/rss/1.0/}",
                                "{http://purl.org/rss/1.0/modules/content/}", "{http://purl.org/dc/elements/1.1/}")
ALLOWED = {"p", "br", "h1", "h2", "h3", "h4", "h5", "h6", "i", "em", "b", "strong", "blockquote", "ul", "ol", "li", "sup", "sub", "hr", "u", "pre", "code", "a", "s", "small"}


# ============================================================================================= reading feeds
def _text(node, *tags) -> str:
    for tag in tags:
        found = node.find(tag)
        if found is not None and (found.text or "").strip():
            return found.text.strip()
    return ""


def when(text: str) -> int:
    """A feed's date (RFC 822 in RSS, ISO 8601 in Atom and JSON Feed) as seconds since 1970, or 0."""
    text = (text or "").strip()
    if not text:
        return 0
    try:
        return int(email.utils.parsedate_to_datetime(text).timestamp())
    except (TypeError, ValueError, IndexError):
        pass
    m = re.match(r"(\d{4})-(\d\d)-(\d\d)(?:[T ](\d\d):(\d\d)(?::(\d\d)(?:\.\d+)?)?)?\s*(Z|[+-]\d\d:?\d\d)?", text)
    if not m:
        return 0
    y, mo, d, h, mi, s = (int(x or 0) for x in m.groups()[:6])
    try:
        stamp = calendar.timegm((y, mo, d, h, mi, s, 0, 0, 0))
    except (ValueError, OverflowError):
        return 0
    zone = m.group(7)
    if zone and zone != "Z":
        sign = 1 if zone[0] == "+" else -1
        zone = zone[1:].replace(":", "")
        stamp -= sign * (int(zone[:2]) * 3600 + int(zone[2:4]) * 60)
    return int(stamp)


def clean_html(markup: str, base: str = "") -> str:
    """An article's HTML cut down to text structure and plain links. Everything that could run, style itself or
    load something from the web is dropped. Relative links are made whole against `base`."""
    text = re.sub(r"(?is)<(script|style|head|iframe|object|embed|svg|math|form|noscript|template|video|audio|picture)\b.*?</\1\s*>", " ", markup or "")
    text = re.sub(r"(?is)<!--.*?-->|<!\[CDATA\[|\]\]>", "", text)
    text = re.sub(r"(?is)<(div|section|article|aside|figure|figcaption|header|footer|tr|table|dd|dt|dl|main)\b[^>]*>", "<p>", text)
    text = re.sub(r"(?is)</(div|section|article|aside|figure|figcaption|header|footer|tr|table|dd|dt|dl|main)\s*>", "</p>", text)

    def tag(m):
        close, name = m.group(1), m.group(2).lower()
        if name not in ALLOWED:
            return ""
        if name == "a" and not close:
            href = re.search(r"""href\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+))""", m.group(0), re.I)
            url = html.unescape(next((g for g in href.groups() if g is not None), "")) if href else ""
            url = urllib.parse.urljoin(base, url.strip()) if base else url.strip()
            if not re.match(r"https?://", url, re.I):
                return "<a>"
            return '<a href="' + html.escape(url, quote=True) + '">'
        return f"<{close}{name}>"
    text = re.sub(r"<(/?)([A-Za-z][A-Za-z0-9]*)\b[^>]*?/?>", tag, text)
    text = re.sub(r"(<p>\s*)+", "<p>", re.sub(r"(</p>\s*)+", "</p>", text))
    return re.sub(r"<p>\s*</p>", "", text).strip()


def plain(markup: str, most: int = 400) -> str:
    text = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", markup or "")
    text = html.unescape(re.sub(r"<[^>]+>", " ", text))
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= most else text[:most].rsplit(" ", 1)[0] + "…"


def _item(fid: str, link: str, guid: str, title: str, author: str, stamp: int, body: str, base: str) -> dict:
    link = urllib.parse.urljoin(base, link.strip()) if link else ""
    if link and not re.match(r"https?://", link, re.I):
        link = ""
    key = guid or link or (title + str(stamp))
    content = clean_html(body, link or base)
    return {"id": hashlib.sha1(f"{fid}|{key}".encode()).hexdigest()[:16], "feed": fid, "title": plain(title, 300) or plain(body, 90) or "Untitled",
            "link": link, "author": plain(author, 120), "stamp": stamp, "summary": plain(body, 320), "content": content}


def parse_feed(raw: bytes, fid: str = "", base: str = "") -> dict:
    """Any feed as {title, site, about, items: [...]}. Raises ValueError for anything that isn't one."""
    head = raw[:300_000].lstrip()
    if head[:1] in (b"{", b"["):
        try:
            data = json.loads(raw.decode("utf-8", "replace"))
        except ValueError:
            raise ValueError("That isn't a feed.") from None
        if not isinstance(data, dict) or not str(data.get("version", "")).startswith("https://jsonfeed.org/"):
            raise ValueError("That isn't a feed.")
        items = []
        for e in (data.get("items") or [])[:KEEP]:
            if not isinstance(e, dict):
                continue
            who = e.get("authors") or ([e["author"]] if isinstance(e.get("author"), dict) else [])
            author = ", ".join(str(a.get("name", "")) for a in who if isinstance(a, dict))
            items.append(_item(fid, str(e.get("url") or ""), str(e.get("id") or ""), str(e.get("title") or ""), author,
                               when(str(e.get("date_published") or e.get("date_modified") or "")), str(e.get("content_html") or html.escape(str(e.get("content_text") or e.get("summary") or ""))), base))
        return {"title": plain(str(data.get("title") or ""), 160), "site": str(data.get("home_page_url") or ""), "about": plain(str(data.get("description") or ""), 300), "items": items}
    if re.search(rb"<!(DOCTYPE[^>]*\[|ENTITY)", head, re.I):
        raise ValueError("That feed uses a trick this app won't follow.")        # no entity expansion, ever
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        raise ValueError("That isn't a feed.") from None
    name = root.tag
    items = []
    if name == ATOM + "feed":
        site = next((ln.get("href", "") for ln in root.findall(ATOM + "link") if ln.get("rel", "alternate") == "alternate"), "")
        for e in root.findall(ATOM + "entry")[:KEEP]:
            link = next((ln.get("href", "") for ln in e.findall(ATOM + "link") if ln.get("rel", "alternate") == "alternate"), "")
            content = e.find(ATOM + "content")
            summary = e.find(ATOM + "summary")
            body = next((n for n in (content, summary) if n is not None), None)
            text = (body.text or "") if body is not None and body.get("type", "text") != "xhtml" else \
                (ET.tostring(body, encoding="unicode") if body is not None else "")
            if body is not None and body.get("type", "text") == "text":
                text = html.escape(text).replace("\n", "<br>")
            author = ", ".join(_text(a, ATOM + "name") for a in e.findall(ATOM + "author"))
            items.append(_item(fid, link, _text(e, ATOM + "id"), _text(e, ATOM + "title"), author, when(_text(e, ATOM + "published", ATOM + "updated")), re.sub(r"<(/?)[A-Za-z][\w.-]*:", r"<\1", text), site or base))
        return {"title": plain(_text(root, ATOM + "title"), 160), "site": site, "about": plain(_text(root, ATOM + "subtitle"), 300), "items": items}
    if name == "rss":
        channel = root.find("channel")
        if channel is None:
            raise ValueError("That isn't a feed.")
        site = _text(channel, "link")
        for e in channel.findall("item")[:KEEP]:
            guid = e.find("guid")
            link = _text(e, "link") or (guid.text.strip() if guid is not None and guid.get("isPermaLink", "true") != "false" and (guid.text or "").startswith("http") else "")
            items.append(_item(fid, link, guid.text.strip() if guid is not None and guid.text else "", _text(e, "title"), _text(e, "author", DC + "creator"),
                               when(_text(e, "pubDate", DC + "date")), _text(e, CONTENT + "encoded", "description"), site or base))
        return {"title": plain(_text(channel, "title"), 160), "site": site, "about": plain(_text(channel, "description"), 300), "items": items}
    if name == RDF + "RDF":
        channel = root.find(RSS1 + "channel")
        site = _text(channel, RSS1 + "link") if channel is not None else ""
        for e in root.findall(RSS1 + "item")[:KEEP]:
            items.append(_item(fid, _text(e, RSS1 + "link"), e.get(RDF + "about", ""), _text(e, RSS1 + "title"), _text(e, DC + "creator"),
                               when(_text(e, DC + "date")), _text(e, CONTENT + "encoded", RSS1 + "description"), site or base))
        return {"title": plain(_text(channel, RSS1 + "title") if channel is not None else "", 160), "site": site, "about": "", "items": items}
    raise ValueError("That isn't a feed.")


def find_feeds(page: bytes, base: str) -> list:
    """The feeds a web page points to with <link rel="alternate" type="...rss/atom/json...">."""
    head = page[:600_000].decode("utf-8", "replace")
    found = []
    for tag in re.findall(r"(?is)<link\b[^>]*>", head):
        attrs = {k.lower(): html.unescape(v or w) for k, v, w in re.findall(r"""([\w-]+)\s*=\s*(?:"([^"]*)"|'([^']*)')""", tag)}
        if "alternate" in attrs.get("rel", "").lower().split() and re.search(r"(rss|atom|feed)\+xml|feed\+json|json", attrs.get("type", ""), re.I) and attrs.get("href"):
            url = urllib.parse.urljoin(base, attrs["href"])
            if url not in found:
                found.append(url)
    return found


def opml(feeds: list) -> str:
    rows = "".join(f'    <outline type="rss" text="{html.escape(f.get("title") or f["url"], quote=True)}" title="{html.escape(f.get("title") or f["url"], quote=True)}"'
                   f' xmlUrl="{html.escape(f["url"], quote=True)}" htmlUrl="{html.escape(f.get("site") or "", quote=True)}"/>\n' for f in feeds)
    return f'<?xml version="1.0" encoding="UTF-8"?>\n<opml version="2.0">\n  <head><title>Feeds from Huginn OS</title></head>\n  <body>\n{rows}  </body>\n</opml>\n'


def read_opml(raw: bytes) -> list:
    if re.search(rb"<!(DOCTYPE[^>]*\[|ENTITY)", raw[:200_000], re.I):
        raise ValueError("That file uses a trick this app won't follow.")
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        raise ValueError("That isn't an OPML file.") from None
    if root.tag.lower() != "opml":
        raise ValueError("That isn't an OPML file.")
    out = []
    for node in root.iter("outline"):
        url = node.get("xmlUrl") or node.get("xmlurl") or ""
        if re.match(r"https?://", url, re.I) and url not in [o["url"] for o in out]:
            out.append({"url": url, "title": node.get("title") or node.get("text") or "", "site": node.get("htmlUrl") or ""})
    return out


def ago(stamp: int, now: float = None) -> str:
    if not stamp:
        return ""
    gap = (now or time.time()) - stamp
    if gap < 90:
        return "just now"
    if gap < 3600:
        return f"{int(gap // 60)} min ago"
    if gap < 86400:
        return f"{int(gap // 3600)} h ago"
    days = int(gap // 86400)
    if days < 7:
        return "yesterday" if days == 1 else f"{days} days ago"
    return dt.datetime.fromtimestamp(stamp).strftime("%-d %b" if days < 300 else "%-d %b %Y")


# ============================================================================================= the app
class Feeds(QObject):
    changed = Signal()
    said = Signal(str, bool)
    _back = Signal(object)

    def __init__(self, demo: bool = False, target: str = ""):
        super().__init__()
        self._back.connect(lambda fn: fn())
        self._demo, self._file = demo, DATA_HOME / "feeds.json"
        self._feeds, self._items, self._lock = [], {}, threading.Lock()
        self._view, self._query, self._open, self._busy = "front", "", "", 0
        self._size = 18                                        # the reader's letter size, which you can change
        if demo:
            self._demo_fill()
            return
        self._load()
        self._timer = QTimer(self)
        self._timer.setInterval(FRESH * 1000)
        self._timer.timeout.connect(self.refresh)
        self._timer.start()
        QTimer.singleShot(400, self.refresh)
        if target:
            QTimer.singleShot(0, lambda: self.follow(str(target)))

    # ---- keeping
    def _load(self) -> None:
        try:
            data = json.loads(self._file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        data = data if isinstance(data, dict) else {}
        self._feeds = [f for f in data.get("feeds", []) if isinstance(f, dict) and f.get("id") and f.get("url")]
        items = data.get("items") if isinstance(data.get("items"), dict) else {}
        self._items = {k: [i for i in v if isinstance(i, dict) and i.get("id")] for k, v in items.items() if isinstance(v, list)}
        size = data.get("size", 18)
        self._size = size if isinstance(size, int) and 14 <= size <= 26 else 18

    def _keep(self) -> None:
        if self._demo:
            return
        try:
            self._file.parent.mkdir(parents=True, exist_ok=True)
            part = self._file.with_name(".feeds.json.saving")
            part.write_text(json.dumps({"feeds": self._feeds, "items": self._items, "size": self._size}, ensure_ascii=False), encoding="utf-8")
            os.replace(part, self._file)
        except OSError as err:
            self.said.emit(f"Couldn't save: {err.strerror or err}", True)

    def _demo_fill(self) -> None:
        now = int(time.time())
        papers = [("f1", "The Fjord Ledger", "https://ledger.example", [
                    ("Ferry timetable changes for the winter season", 2, "Three routes run less often from December, and the night boat to the islands stops until March.", False),
                    ("Harbour market returns with forty new stalls", 26, "Fishmongers, bakers and a record shop take over the old customs hall every Saturday.", False),
                    ("Council votes to keep the library open on Sundays", 50, "After a petition with 4,000 names, the main branch keeps its weekend hours.", True)]),
                  ("f2", "Open Desk", "https://opendesk.example", [
                    ("Why small distributions matter", 5, "One-person Linux projects try ideas the big ones can't, and some of those ideas come back to everyone.", False),
                    ("A practical look at Wayland portals", 30, "Screen sharing, file pickers and screenshots now ask first. Here is how that works and why it is good.", False),
                    ("Ten years of the same keyboard shortcuts", 80, "Muscle memory is a feature. Changing a shortcut costs users more than it seems.", True)]),
                  ("f3", "Northern Skies", "https://skies.example", [
                    ("Aurora forecast: strong chance on Friday night", 1, "A burst from the sun arrives late on Friday. Head away from the city lights after ten.", False),
                    ("How to photograph the aurora with a phone", 70, "Night mode, a steady surface and patience. No tripod needed for a first try.", True)]),
                  ("f4", "Kitchen Notes", "https://kitchen.example", [
                    ("Rye bread that keeps for a week", 9, "A dense, dark loaf with seeds and a long, slow rise. It only gets better.", False),
                    ("Five soups for the first cold week", 40, "Simple pots that use what's in the cupboard.", False)])]
        for fid, title, site, rows in papers:
            self._feeds.append({"id": fid, "url": site + "/feed", "title": title, "site": site, "checked": now - 600, "error": ""})
            self._items[fid] = [{"id": f"{fid}-{i}", "feed": fid, "title": t, "link": f"{site}/{i}", "author": "", "stamp": now - h * 3600, "summary": s,
                                 "content": "<p>" + html.escape(s) + "</p><p>The rest of the article would be here, as plain text with its links.</p>", "read": r, "star": i == 2}
                                for i, (t, h, s, r) in enumerate(rows)]

    def _feed(self, fid: str):
        return next((f for f in self._feeds if f["id"] == fid), None)

    def _all(self) -> list:
        return [i for rows in self._items.values() for i in rows]

    # ---- what QML sees
    def _face(self, i: dict) -> dict:
        f = self._feed(i["feed"]) or {}
        return {"id": i["id"], "feed": i["feed"], "source": f.get("title") or "", "title": i["title"], "summary": i["summary"], "when": ago(i.get("stamp", 0)),
                "stamp": i.get("stamp", 0), "read": bool(i.get("read")), "star": bool(i.get("star")), "link": i.get("link", ""), "author": i.get("author", ""),
                "mins": max(1, round(len(plain(i.get("content") or i.get("summary") or "", 10 ** 7).split()) / 220))}

    def _get_articles(self) -> list:
        words = self._query.lower().split()
        rows = self._all()
        if self._view == "front":
            rows = [i for i in rows if not i.get("read")] or sorted(rows, key=lambda i: -i.get("stamp", 0))[:12]
        elif self._view == "starred":
            rows = [i for i in rows if i.get("star")]
        elif self._view != "all":
            rows = self._items.get(self._view, [])
        if words:
            rows = [i for i in self._all() if all(w in (i["title"] + " " + i["summary"]).lower() for w in words)]
        return [self._face(i) for i in sorted(rows, key=lambda i: -i.get("stamp", 0))[:300]]

    def _get_sources(self) -> list:
        return [{"id": f["id"], "title": f.get("title") or f["url"], "site": f.get("site", ""), "url": f["url"], "error": f.get("error", ""),
                 "unread": sum(1 for i in self._items.get(f["id"], []) if not i.get("read")), "checked": ago(f.get("checked", 0))}
                for f in sorted(self._feeds, key=lambda f: (f.get("title") or f["url"]).lower())]

    def _get_article(self) -> dict:
        hit = next((i for i in self._all() if i["id"] == self._open), None)
        if not hit:
            return {}
        face = self._face(hit)
        face["content"] = hit.get("content") or ("<p>" + html.escape(hit.get("summary", "")) + "</p>")
        face["date"] = dt.datetime.fromtimestamp(hit["stamp"]).strftime("%A %-d %B %Y, %H:%M") if hit.get("stamp") else ""
        return face

    articles = Property("QVariantList", _get_articles, notify=changed)
    sources = Property("QVariantList", _get_sources, notify=changed)
    article = Property("QVariantMap", _get_article, notify=changed)
    view = Property(str, lambda self: self._view, notify=changed)
    busy = Property(bool, lambda self: self._busy > 0, notify=changed)
    unread = Property(int, lambda self: sum(1 for i in self._all() if not i.get("read")), notify=changed)
    starred = Property(int, lambda self: sum(1 for i in self._all() if i.get("star")), notify=changed)
    today = Property(str, lambda self: dt.date.today().strftime("%A %-d %B %Y"), notify=changed)
    size = Property(int, lambda self: self._size, notify=changed)

    @Slot(int)
    def setSize(self, n: int) -> None:
        """The reader's letter size, 14 to 26 points, remembered."""
        self._size = max(14, min(26, n))
        self._keep()
        self.changed.emit()

    @Slot(str)
    def setView(self, name: str) -> None:
        self._view = name if name in ("front", "starred", "all") or self._feed(name) else "front"
        self._open = ""
        self.changed.emit()

    @Slot(str)
    def search(self, text: str) -> None:
        self._query = text
        self.changed.emit()

    @Slot(str)
    def read(self, ident: str) -> None:
        """Open an article (and count it as read)."""
        hit = next((i for i in self._all() if i["id"] == ident), None)
        self._open = ident if hit else ""
        if hit and not hit.get("read"):
            hit["read"] = True
            self._keep()
        self.changed.emit()

    @Slot()
    def close(self) -> None:
        self._open = ""
        self.changed.emit()

    @Slot(str, bool)
    def setRead(self, ident: str, on: bool) -> None:
        for i in self._all():
            if i["id"] == ident:
                i["read"] = on
        self._keep()
        self.changed.emit()

    @Slot(str)
    def star(self, ident: str) -> None:
        for i in self._all():
            if i["id"] == ident:
                i["star"] = not i.get("star")
        self._keep()
        self.changed.emit()

    @Slot()
    def allRead(self) -> None:
        """Everything in the current view counts as read."""
        ids = {a["id"] for a in self._get_articles()}
        for i in self._all():
            if i["id"] in ids:
                i["read"] = True
        self._keep()
        self.changed.emit()

    @Slot(str)
    def openLink(self, url: str) -> None:
        if re.match(r"https?://", url or "", re.I):
            from PySide6.QtGui import QDesktopServices
            QDesktopServices.openUrl(QUrl(url))

    # ---- following and fetching
    def _get(self, url: str, etag: str = "", modified: str = "") -> tuple:
        headers = {"User-Agent": AGENT, "Accept": "application/rss+xml, application/atom+xml, application/feed+json, application/json, application/xml, text/xml, text/html;q=0.8, */*;q=0.5"}
        if etag:
            headers["If-None-Match"] = etag
        if modified:
            headers["If-Modified-Since"] = modified
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=25) as reply:
                return reply.status, reply.read(15_000_000), reply.headers.get("ETag", ""), reply.headers.get("Last-Modified", ""), reply.geturl(), reply.headers.get("Content-Type", "")
        except urllib.error.HTTPError as err:
            if err.code == 304:
                return 304, b"", etag, modified, url, ""
            raise

    def _bg(self, work, then) -> None:
        self._busy += 1
        self.changed.emit()

        def go():
            try:
                result = work()
            except Exception as err:
                result = err
            self._back.emit(lambda: (setattr(self, "_busy", self._busy - 1), then(result), self.changed.emit()))
        threading.Thread(target=go, daemon=True).start()

    @Slot(str)
    def follow(self, address: str) -> None:
        """A feed's address, or any page of a site that has one."""
        address = address.strip()
        if address.startswith("feed:"):
            address = address[5:].lstrip("/") if address[5:].startswith("//") else address[5:]
        if address and not re.match(r"https?://", address, re.I):
            address = "https://" + address
        if self._demo or not re.match(r"https?://[^\s/]+\.[^\s/]+|https?://(localhost|127\.0\.0\.1)\b", address) or re.search(r"\s", address):
            if not self._demo:
                self.said.emit("Type a web address, like example.com or example.com/feed.", True)
            return

        def look():
            status, body, etag, modified, final, _ = self._get(address)
            try:
                return final, parse_feed(body, "", final), etag, modified
            except ValueError:
                pass
            tried = find_feeds(body, final) or [urllib.parse.urljoin(final, p) for p in ("/feed", "/rss.xml", "/atom.xml", "/feed.xml", "/index.xml", "/rss", "/feed.json")]
            for url in tried[:8]:
                try:
                    status, raw, etag, modified, got, _ = self._get(url)
                    return got, parse_feed(raw, "", got), etag, modified
                except (ValueError, urllib.error.URLError, OSError):
                    continue
            raise ValueError("No feed found there. Try the feed's own address (it often ends in /feed or .xml).")

        def done(result):
            if isinstance(result, Exception):
                self.said.emit(str(result) if isinstance(result, ValueError) else _net_words(result), True)
                return
            url, parsed, etag, modified = result
            if any(f["url"] == url for f in self._feeds):
                self.said.emit("You already follow that.", False)
                self.setView(next(f["id"] for f in self._feeds if f["url"] == url))
                return
            fid = uuid.uuid4().hex[:10]
            title = parsed["title"] or urllib.parse.urlparse(url).hostname or url
            self._feeds.append({"id": fid, "url": url, "title": title, "site": parsed["site"], "etag": etag, "modified": modified, "checked": int(time.time()), "error": ""})
            self._merge(fid, parsed["items"], first=True)
            self._keep()
            self.setView(fid)
            self.said.emit(f"Following {title}.", False)
        self._bg(look, done)

    def _merge(self, fid: str, fresh: list, first: bool = False) -> int:
        have = {i["id"]: i for i in self._items.get(fid, [])}
        new = 0
        for item in fresh:
            item = dict(item, id=hashlib.sha1(f"{fid}|{item['id']}".encode()).hexdigest()[:16], feed=fid)
            old = have.get(item["id"])
            if old:
                old.update({k: item[k] for k in ("title", "summary", "content", "link", "author") if item.get(k)})
            else:
                item.update(read=False, star=False)
                if first:                                                # following a feed: only its newest few count as new
                    item["read"] = new >= 10
                have[item["id"]] = item
                new += 1
        rows = sorted(have.values(), key=lambda i: -i.get("stamp", 0))
        self._items[fid] = [i for n, i in enumerate(rows) if n < KEEP or i.get("star")]
        return new

    @Slot()
    def refresh(self) -> None:
        if self._demo or not self._feeds:
            return
        feeds = [dict(f) for f in self._feeds]

        def work():
            out = {}
            for f in feeds:
                try:
                    status, raw, etag, modified, _, _ = self._get(f["url"], f.get("etag", ""), f.get("modified", ""))
                    out[f["id"]] = ("same", etag, modified) if status == 304 else ("new", parse_feed(raw, "", f["url"]), etag, modified)
                except ValueError as err:
                    out[f["id"]] = ("error", str(err))
                except Exception as err:
                    out[f["id"]] = ("error", _net_words(err))
            return out

        def done(result):
            if isinstance(result, Exception):
                return
            fresh = 0
            for fid, answer in result.items():
                f = self._feed(fid)
                if not f:
                    continue
                f["checked"] = int(time.time())
                if answer[0] == "error":
                    f["error"] = answer[1]
                    continue
                f["error"] = ""
                if answer[0] == "new":
                    _, parsed, f["etag"], f["modified"] = answer
                    fresh += self._merge(fid, parsed["items"])
                    if parsed["title"] and not f.get("renamed"):
                        f["title"] = parsed["title"]
            self._keep()
            if fresh:
                self.said.emit(f"{fresh} new " + ("article" if fresh == 1 else "articles") + ".", False)
        self._bg(work, done)

    @Slot(str)
    def unfollow(self, fid: str) -> None:
        f = self._feed(fid)
        if f:
            self._feeds.remove(f)
            self._items.pop(fid, None)
            if self._view == fid:
                self._view = "front"
            self._keep()
            self.changed.emit()
            self.said.emit(f"Stopped following {f.get('title')}.", False)

    @Slot(str, str)
    def rename(self, fid: str, title: str) -> None:
        f = self._feed(fid)
        title = " ".join(title.split())[:120]
        if f and title:
            f["title"], f["renamed"] = title, True
            self._keep()
            self.changed.emit()

    # ---- moving between apps
    def _documents(self) -> Path:
        return Path(QStandardPaths.writableLocation(QStandardPaths.DocumentsLocation) or Path.home() / "Documents")

    @Slot(result=str)
    def exportOpml(self) -> str:
        if not self._feeds:
            return ""
        path = self._documents() / "Feeds.opml"
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(opml(self._feeds), encoding="utf-8")
        except OSError as err:
            self.said.emit(f"Couldn't save it: {err.strerror or err}", True)
            return ""
        self.said.emit(f"Saved {len(self._feeds)} feeds to Documents/Feeds.opml. Other feed readers can import it.", False)
        return str(path)

    @Slot(result="QVariantList")
    def opmlChoices(self) -> list:
        out = []
        for folder in (self._documents(), Path(QStandardPaths.writableLocation(QStandardPaths.DownloadLocation) or Path.home() / "Downloads")):
            try:
                for p in sorted(folder.glob("*.opml")) + sorted(folder.glob("*.xml")):
                    if p.stat().st_size < 5_000_000 and (p.suffix == ".opml" or b"<opml" in p.read_bytes()[:500].lower()):
                        out.append({"name": p.name, "path": str(p), "where": folder.name})
            except OSError:
                continue
        return out[:30]

    @Slot(str)
    def importOpml(self, path: str) -> None:
        path = QUrl(path).toLocalFile() if path.startswith("file:") else path
        try:
            rows = read_opml(Path(path).read_bytes())
        except (OSError, ValueError) as err:
            self.said.emit(str(err) if isinstance(err, ValueError) else f"Couldn't read it: {err.strerror or err}", True)
            return
        known = {f["url"] for f in self._feeds}
        added = [r for r in rows if r["url"] not in known]
        for r in added:
            self._feeds.append({"id": uuid.uuid4().hex[:10], "url": r["url"], "title": r["title"] or r["url"], "site": r["site"], "checked": 0, "error": "", "renamed": bool(r["title"])})
        self._keep()
        self.changed.emit()
        self.said.emit(f"Following {len(added)} more feeds. Fetching them now." if added else "You already follow everything in that file.", False)
        if added:
            self.refresh()


def _net_words(err: Exception) -> str:
    text = str(getattr(err, "reason", err))
    if isinstance(err, urllib.error.HTTPError):
        return {404: "The feed isn't there any more (404).", 403: "The site refused (403).", 410: "The feed was taken down (410)."}.get(err.code, f"The site answered with an error ({err.code}).")
    if "Name or service" in text or "resolution" in text or "unreachable" in text:
        return "This computer seems to be offline."
    if "timed out" in text:
        return "The site took too long to answer."
    return f"Couldn't reach it: {text}"[:160]
