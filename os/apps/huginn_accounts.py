"""Huginn Online Accounts: sign in once, and Mail, Calendar, Contacts and Files use the account.

    Google      its own sign-in page (OAuth 2 with PKCE). Mail over IMAP, calendars over CalDAV, contacts over CardDAV.
    Microsoft   its own sign-in page. Mail over IMAP, calendars and contacts through Microsoft Graph.
    iCloud      your Apple ID's address and an app-specific password. Mail, CalDAV and CardDAV.
    Nextcloud   Nextcloud's own login flow in the browser, which hands back a password just for this computer.
                Calendars, contacts, and your files (mounted with gvfs, so Files shows them).

Secrets (sign-in tokens, app passwords) live in the Passwords vault, in its "accounts" drawer, never on disk in the
clear. The list of accounts (no secrets) is ~/.config/huginn/accounts.json.

Calendars: events come into Calendar tagged with the account and calendar they belong to. Changing an event's name,
day or time in Calendar sends the change back (only those fields are touched in the server's copy, so invitees and
alarms stay as they were); deleting one deletes it on the server. Contacts come down from the account and are
refreshed from it (change them at the source).

`huginn_accounts.py watch` keeps everything in step every 15 minutes while you're signed in.
"""
import base64
import datetime as dt
import hashlib
import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path

from PySide6.QtCore import Property, QObject, QTimer, Signal, Slot

HERE = Path(__file__).resolve().parent
CONFIG = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "huginn"
DATA_HOME = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share") / "huginn"
LIST_FILE = CONFIG / "accounts.json"
STATE_DIR = DATA_HOME / "accounts"
CAL_FILE = DATA_HOME / "calendar.json"
CARD_FILE = DATA_HOME / "contacts.vcf"
MAIL_HOME = DATA_HOME / "mail"
WINDOW_BACK, WINDOW_AHEAD = 60, 400                     # days of events kept in step

GRAPH = "https://graph.microsoft.com/v1.0"
GRAPH_SCOPE = "offline_access https://graph.microsoft.com/Calendars.ReadWrite https://graph.microsoft.com/Contacts.Read"
OUTLOOK_SCOPE = "https://outlook.office.com/IMAP.AccessAsUser.All https://outlook.office.com/SMTP.Send"
PROVIDERS = {
    "google": {"name": "Google", "sign": "oauth", "services": ["mail", "calendar", "contacts"], "a": "#4285F4", "b": "#1A56C4",
               "scope": "https://mail.google.com/ https://www.googleapis.com/auth/calendar https://www.googleapis.com/auth/carddav",
               "caldav": "https://apidata.googleusercontent.com/caldav/v2/{email}/user", "carddav": "https://www.googleapis.com/carddav/v1/principals/{email}/lists/default/",
               "imap": ("imap.gmail.com", 993, "smtp.gmail.com", 465), "blurb": "Gmail, Google Calendar and Google Contacts"},
    "microsoft": {"name": "Microsoft", "sign": "oauth", "services": ["mail", "calendar", "contacts"], "a": "#2F9BFF", "b": "#0B5CAD",
                  "scope": f"{GRAPH_SCOPE} {OUTLOOK_SCOPE}", "token_scope": GRAPH_SCOPE,
                  "imap": ("outlook.office365.com", 993, "smtp.office365.com", 587), "blurb": "Outlook.com, Hotmail and Microsoft 365"},
    "icloud": {"name": "iCloud", "sign": "password", "services": ["mail", "calendar", "contacts"], "a": "#9AA5B4", "b": "#4A5566",
               "caldav": "https://caldav.icloud.com/", "carddav": "https://contacts.icloud.com/", "imap": ("imap.mail.me.com", 993, "smtp.mail.me.com", 587),
               "blurb": "iCloud Mail, Calendar and Contacts",
               "note": "Apple needs an app-specific password, not your usual one: on appleid.apple.com, Sign-In and Security → App-Specific Passwords."},
    "nextcloud": {"name": "Nextcloud", "sign": "flow", "services": ["calendar", "contacts", "files"], "a": "#2FA7E6", "b": "#0067A6",
                  "blurb": "Your own cloud: calendars, contacts and files"},
}
SERVICE_NAMES = {"mail": "Mail", "calendar": "Calendars", "contacts": "Contacts", "files": "Files"}
NS = {"d": "DAV:", "c": "urn:ietf:params:xml:ns:caldav", "cr": "urn:ietf:params:xml:ns:carddav", "a": "http://apple.com/ns/ical/", "cs": "http://calendarserver.org/ns/"}


class AccountError(Exception):
    """Something to tell the person, in words fit to show."""


# ------------------------------------------------------------------------------------------- the list of accounts
def read_list() -> list:
    try:
        return [a for a in json.loads(LIST_FILE.read_text(encoding="utf-8")) if isinstance(a, dict) and a.get("id") and a.get("provider") in PROVIDERS]
    except (OSError, ValueError):
        return []


def write_list(accounts: list) -> None:
    LIST_FILE.parent.mkdir(parents=True, exist_ok=True)
    part = LIST_FILE.with_name(".accounts.json.saving")
    part.write_text(json.dumps(accounts, indent=1), encoding="utf-8")
    os.replace(part, LIST_FILE)


def read_status() -> dict:
    try:
        return json.loads((STATE_DIR / "status.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def write_status(status: dict) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    part = STATE_DIR / ".status.json.saving"
    part.write_text(json.dumps(status, indent=1), encoding="utf-8")
    os.replace(part, STATE_DIR / "status.json")


# ------------------------------------------------------------------------------------------- talking HTTP
class Web:
    """HTTPS with an account's sign-in attached, following a provider's redirects only within its own domain."""

    def __init__(self, auth):
        self.auth = auth                                         # () -> {"Authorization": ...}

    @staticmethod
    def _site(host: str) -> str:
        parts = (host or "").lower().split(".")
        return ".".join(parts[-2:])

    def call(self, method: str, url: str, body: bytes = None, headers: dict = None, depth: str = None, hops: int = 5) -> tuple:
        if not url.startswith("https://") and not url.startswith("http://127.0.0.1") and not url.startswith("http://localhost"):
            raise AccountError("Huginn only talks to accounts over HTTPS.")
        h = {"User-Agent": "Huginn-OS-Online-Accounts", **(headers or {}), **self.auth()}
        if depth is not None:
            h["Depth"] = depth
        if body is not None and "Content-Type" not in h:
            h["Content-Type"] = "application/xml; charset=utf-8"
        req = urllib.request.Request(url, data=body, method=method, headers=h)

        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *a, **k):
                return None
        opener = urllib.request.build_opener(NoRedirect)
        try:
            with opener.open(req, timeout=40) as reply:
                return reply.status, dict(reply.headers), reply.read()
        except urllib.error.HTTPError as err:
            if err.code in (301, 302, 303, 307, 308) and hops > 0:
                target = urllib.parse.urljoin(url, err.headers.get("Location", ""))
                if self._site(urllib.parse.urlsplit(target).hostname) != self._site(urllib.parse.urlsplit(url).hostname):
                    raise AccountError("The server sent Huginn somewhere else, so it stopped there to keep your sign-in safe.") from None
                return self.call("GET" if err.code == 303 else method, target, body, headers, depth, hops - 1)
            if err.code in (401, 403):
                raise AccountError("The account didn't accept the sign-in. Sign in again from Settings.") from None
            return err.code, dict(err.headers or {}), err.read() or b""
        except urllib.error.URLError as err:
            raise AccountError(f"Couldn't reach {urllib.parse.urlsplit(url).hostname}. Check that you're online.") from err

    def json(self, method: str, url: str, data=None, headers: dict = None):
        status, _, body = self.call(method, url, json.dumps(data).encode() if data is not None else None, {"Content-Type": "application/json", "Accept": "application/json", **(headers or {})})
        if status >= 400:
            raise AccountError(f"The account answered {status}.")
        return json.loads(body or b"{}")


# ------------------------------------------------------------------------------------------- CalDAV and CardDAV
def multistatus(body: bytes) -> list:
    """A WebDAV multistatus answer → [(href, {"{ns}name": element})] for the properties that came back 200."""
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        return []
    out = []
    for resp in root.findall("d:response", NS):
        href = (resp.findtext("d:href", "", NS) or "").strip()
        props = {}
        for stat in resp.findall("d:propstat", NS):
            if " 200" not in (stat.findtext("d:status", "", NS) or "") and (stat.findtext("d:status", "", NS) or "").strip():
                continue
            for prop in stat.findall("d:prop", NS):
                for child in prop:
                    props[child.tag] = child
        out.append((href, props))
    return out


def _tag(prefix: str, name: str) -> str:
    return "{" + NS[prefix] + "}" + name


def propfind_xml(props: list) -> bytes:
    inner = "".join(f"<{p}/>" for p in props)
    return (f'<?xml version="1.0" encoding="utf-8"?><d:propfind xmlns:d="DAV:" xmlns:c="{NS["c"]}" xmlns:cr="{NS["cr"]}" xmlns:a="{NS["a"]}" xmlns:cs="{NS["cs"]}">'
            f"<d:prop>{inner}</d:prop></d:propfind>").encode()


def find_home(web: Web, start: str, kind: str) -> str:
    """Follow current-user-principal → calendar-home-set (or addressbook-home-set), as the standards describe."""
    home_prop = "c:calendar-home-set" if kind == "cal" else "cr:addressbook-home-set"
    status, _, body = web.call("PROPFIND", start, propfind_xml(["d:current-user-principal", home_prop]), depth="0")
    if status >= 400:
        raise AccountError(f"The account's {'calendars' if kind == 'cal' else 'contacts'} couldn't be found (it answered {status}).")
    rows = multistatus(body)
    for _, props in rows:
        home = props.get(_tag(home_prop.split(":")[0], home_prop.split(":")[1]))
        if home is not None and home.findtext("d:href", "", NS):
            return urllib.parse.urljoin(start, home.findtext("d:href", "", NS).strip())
    principal = next((p.get(_tag("d", "current-user-principal")) for _, p in rows if p.get(_tag("d", "current-user-principal")) is not None), None)
    if principal is None or not principal.findtext("d:href", "", NS):
        return start                                              # some servers only answer at the collection itself
    purl = urllib.parse.urljoin(start, principal.findtext("d:href", "", NS).strip())
    status, _, body = web.call("PROPFIND", purl, propfind_xml([home_prop]), depth="0")
    for _, props in multistatus(body):
        home = props.get(_tag(home_prop.split(":")[0], home_prop.split(":")[1]))
        if home is not None and home.findtext("d:href", "", NS):
            return urllib.parse.urljoin(purl, home.findtext("d:href", "", NS).strip())
    return purl


def list_collections(web: Web, home: str, kind: str) -> list:
    status, _, body = web.call("PROPFIND", home, propfind_xml(["d:resourcetype", "d:displayname", "a:calendar-color", "c:supported-calendar-component-set", "cs:getctag", "d:current-user-privilege-set"]), depth="1")
    out = []
    for href, props in multistatus(body):
        rtype = props.get(_tag("d", "resourcetype"))
        if rtype is None:
            continue
        wanted = rtype.find("c:calendar", NS) is not None if kind == "cal" else rtype.find("cr:addressbook", NS) is not None
        if not wanted:
            continue
        comps = props.get(_tag("c", "supported-calendar-component-set"))
        if kind == "cal" and comps is not None and comps.findall("c:comp", NS) and not any(c.get("name") == "VEVENT" for c in comps.findall("c:comp", NS)):
            continue                                              # a list of tasks, not a calendar
        name = (props.get(_tag("d", "displayname")).text if props.get(_tag("d", "displayname")) is not None else "") or href.rstrip("/").rsplit("/", 1)[-1]
        colour = (props.get(_tag("a", "calendar-color")).text if props.get(_tag("a", "calendar-color")) is not None else "") or ""
        out.append({"url": urllib.parse.urljoin(home, href), "name": urllib.parse.unquote(name.strip()), "colour": colour.strip()[:7] if colour.strip().startswith("#") else ""})
    return out


def caldav_events(web: Web, url: str, start: dt.datetime, end: dt.datetime) -> list:
    q = (f'<?xml version="1.0" encoding="utf-8"?><c:calendar-query xmlns:d="DAV:" xmlns:c="{NS["c"]}"><d:prop><d:getetag/><c:calendar-data/></d:prop>'
         f'<c:filter><c:comp-filter name="VCALENDAR"><c:comp-filter name="VEVENT"><c:time-range start="{start:%Y%m%dT%H%M%SZ}" end="{end:%Y%m%dT%H%M%SZ}"/>'
         f"</c:comp-filter></c:comp-filter></c:filter></c:calendar-query>").encode()
    status, _, body = web.call("REPORT", url, q, depth="1")
    if status >= 400:
        raise AccountError(f"A calendar couldn't be read (it answered {status}).")
    out = []
    for href, props in multistatus(body):
        data = props.get(_tag("c", "calendar-data"))
        if data is not None and data.text:
            etag = props.get(_tag("d", "getetag"))
            out.append({"href": urllib.parse.urljoin(url, href), "etag": (etag.text or "").strip() if etag is not None else "", "ics": data.text})
    return out


def carddav_cards(web: Web, url: str) -> list:
    q = (f'<?xml version="1.0" encoding="utf-8"?><cr:addressbook-query xmlns:d="DAV:" xmlns:cr="{NS["cr"]}"><d:prop><d:getetag/><cr:address-data/></d:prop>'
         "</cr:addressbook-query>").encode()
    status, _, body = web.call("REPORT", url, q, depth="1")
    if status >= 400:
        raise AccountError(f"An address book couldn't be read (it answered {status}).")
    out = []
    for href, props in multistatus(body):
        data = props.get(_tag("cr", "address-data"))
        if data is not None and data.text:
            out.append({"href": urllib.parse.urljoin(url, href), "vcf": data.text})
    return out


# ------------------------------------------------------------------------------------------- changing one event in place
def _unfold(text: str) -> list:
    lines = []
    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if raw[:1] in (" ", "\t") and lines:
            lines[-1] += raw[1:]
        else:
            lines.append(raw)
    return lines


def _stamp(value: str, params: list) -> dt.datetime:
    """A DTSTART/DTEND value as an aware datetime (a plain date is midnight, local)."""
    m = re.fullmatch(r"(\d{4})(\d\d)(\d\d)(?:T(\d\d)(\d\d)(\d\d)?(Z)?)?", value.strip())
    if not m:
        raise ValueError(value)
    if m.group(4) is None:
        return dt.datetime(int(m.group(1)), int(m.group(2)), int(m.group(3))).astimezone()
    when = dt.datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4)), int(m.group(5)), int(m.group(6) or 0))
    if m.group(7):
        return when.replace(tzinfo=dt.timezone.utc)
    zone = next((p.split("=", 1)[1].strip('"') for p in params if p.upper().startswith("TZID=")), "")
    if zone:
        try:
            from zoneinfo import ZoneInfo
            return when.replace(tzinfo=ZoneInfo(zone))
        except Exception:                                            # noqa: BLE001
            pass
    return when.astimezone()


def patch_ics(ics: str, title: str, date: str, clock: str) -> str:
    """The server's own copy of an event with only its name, day and time changed. Everything else in it (people
    invited, alarms, notes, the time zone block) stays exactly as it was."""
    lines = _unfold(ics)
    out, inside, master, done = [], False, False, False
    start = end = None
    for line in lines:
        head = line.split(":", 1)[0].split(";")
        if line.upper().startswith("BEGIN:VEVENT"):
            inside, master = True, True
        elif line.upper().startswith("END:VEVENT"):
            inside = False
        elif inside and head[0].upper() == "RECURRENCE-ID":
            master = False
        if inside and head[0].upper() == "DTSTART" and start is None:
            start = (line.split(":", 1)[1], head[1:])
        if inside and head[0].upper() == "DTEND" and end is None:
            end = (line.split(":", 1)[1], head[1:])
    all_day = start is not None and re.fullmatch(r"\d{8}", start[0].strip()) is not None
    try:
        old_start = _stamp(*start) if start else None
        old_end = _stamp(*end) if end else None
    except ValueError:
        old_start = old_end = None
    length = (old_end - old_start) if old_start and old_end else dt.timedelta(days=1) if all_day else dt.timedelta(hours=1)
    day = dt.date.fromisoformat(date)
    if clock and not all_day:
        hh, mm = (int(x) for x in clock.split(":"))
        new_start = dt.datetime(day.year, day.month, day.day, hh, mm).astimezone()
    else:
        new_start = dt.datetime(day.year, day.month, day.day).astimezone()
    new_end = new_start + length

    def fmt(when: dt.datetime) -> str:
        return when.strftime("%Y%m%d") if all_day else when.astimezone(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    inside = False
    for line in lines:
        name = line.split(":", 1)[0].split(";")[0].upper()
        if line.upper().startswith("BEGIN:VEVENT"):
            inside, master = True, True
        elif line.upper().startswith("END:VEVENT"):
            inside = False
        elif inside and name == "RECURRENCE-ID":
            master = False
        if inside and master and not done:
            if name == "SUMMARY":
                line = "SUMMARY:" + title.replace("\\", "\\\\").replace("\n", "\\n").replace(",", "\\,").replace(";", "\\;")
            elif name == "DTSTART":
                line = ("DTSTART;VALUE=DATE:" if all_day else "DTSTART:") + fmt(new_start)
            elif name == "DTEND":
                line = ("DTEND;VALUE=DATE:" if all_day else "DTEND:") + fmt(new_end)
            elif name == "DTSTAMP":
                line = "DTSTAMP:" + dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            elif name == "SEQUENCE":
                try:
                    line = f"SEQUENCE:{int(line.split(':', 1)[1]) + 1}"
                except ValueError:
                    pass
        if line.upper().startswith("END:VEVENT") and master:
            done = True
        out.append(line)
    return "\r\n".join(l for l in out if l != "") + "\r\n"


def event_hash(e: dict) -> str:
    return hashlib.sha1(json.dumps([e.get("title"), e.get("date"), e.get("time"), e.get("repeat")], sort_keys=True).encode()).hexdigest()[:16]


def read_ics(text: str) -> list:
    """Calendar's own reader, so events look exactly as they would if the file had been opened in Calendar."""
    sys.path.insert(0, str(HERE))
    import huginn_app
    return [e for e in huginn_app.Calendar.read_ics(text) if "id" in e]


# ------------------------------------------------------------------------------------------- Microsoft Graph
def graph_event(item: dict) -> dict:
    start = item.get("start") or {}
    when = dt.datetime.fromisoformat(start.get("dateTime", "")[:19]).replace(tzinfo=dt.timezone.utc).astimezone()
    return {"id": "ms-" + hashlib.sha1(item["id"].encode()).hexdigest()[:20], "title": item.get("subject") or "(no title)",
            "date": when.date().isoformat() if not item.get("isAllDay") else start.get("dateTime", "")[:10], "time": "" if item.get("isAllDay") else when.strftime("%H:%M")}


def graph_card(c: dict) -> str:
    def esc(v):
        return str(v).replace("\\", "\\\\").replace(",", "\\,").replace(";", "\\;").replace("\n", "\\n")
    lines = ["BEGIN:VCARD", "VERSION:3.0", f"FN:{esc(c.get('displayName') or '')}",
             f"N:{esc(c.get('surname') or '')};{esc(c.get('givenName') or '')};;;"]
    for m in c.get("emailAddresses") or []:
        if m.get("address"):
            lines.append(f"EMAIL;TYPE=INTERNET:{esc(m['address'])}")
    for kind, nums in (("CELL", [c.get("mobilePhone")]), ("WORK", c.get("businessPhones") or []), ("HOME", c.get("homePhones") or [])):
        for n in nums:
            if n:
                lines.append(f"TEL;TYPE={kind}:{esc(n)}")
    if c.get("companyName"):
        lines.append(f"ORG:{esc(c['companyName'])}")
    if c.get("birthday"):
        lines.append(f"BDAY:{c['birthday'][:10]}")
    lines.append(f"UID:ms-{c.get('id', uuid.uuid4().hex)}")
    lines.append("END:VCARD")
    return "\r\n".join(lines) + "\r\n"


# ------------------------------------------------------------------------------------------- one account in step
class Link:
    """What one account needs to talk to its provider: a way to sign each request, and where things are."""

    def __init__(self, acct: dict, secret: dict, rotated=None):
        self.acct, self.secret = acct, secret
        p = acct["provider"]
        if PROVIDERS[p]["sign"] == "oauth":
            sys.path.insert(0, str(HERE))
            import huginn_mail
            self._tokens = huginn_mail.Tokens(p, secret, rotated, scope=GRAPH_SCOPE if p == "microsoft" else "")
            self.web = Web(lambda: {"Authorization": "Bearer " + self._tokens.access()})
        else:
            user, pw = secret.get("user") or acct["email"], secret.get("password", "")
            basic = base64.b64encode(f"{user}:{pw}".encode()).decode()
            self.web = Web(lambda: {"Authorization": "Basic " + basic})

    def dav_start(self, kind: str) -> str:
        p = PROVIDERS[self.acct["provider"]]
        if self.acct["provider"] == "nextcloud":
            return self.acct["server"].rstrip("/") + ("/remote.php/dav/calendars/" if kind == "cal" else "/remote.php/dav/addressbooks/") + urllib.parse.quote(self.secret.get("user", "")) + "/"
        return p["caldav" if kind == "cal" else "carddav"].format(email=urllib.parse.quote(self.acct["email"]))


def sync_calendars(link: Link, cache: dict, local: list, log) -> tuple:
    """Bring one account's calendars into step. Returns (events from the account, new cache)."""
    acct = link.acct
    now = dt.datetime.now(dt.timezone.utc)
    start, end = now - dt.timedelta(days=WINDOW_BACK), now + dt.timedelta(days=WINDOW_AHEAD)
    mine = {e["id"]: e for e in local if e.get("account") == acct["id"]}
    pushed = 0
    # first, what changed here goes there (only where the server's copy hasn't changed meanwhile)
    for href, entry in list(cache.items()):
        ids = entry.get("ids", [])
        if ids and not any(i in mine for i in ids):
            if entry.get("graph"):
                status, _, _ = link.web.call("DELETE", f"{GRAPH}/me/events/{entry['graph']}")
            else:
                status, _, _ = link.web.call("DELETE", href, headers={"If-Match": entry.get("etag", "")} if entry.get("etag") else {})
            if status < 300 or status == 404:
                cache.pop(href)
                pushed += 1
            continue
        for i in ids:
            e = mine.get(i)
            if e is None or event_hash(e) == entry.get("hashes", {}).get(i):
                continue
            if entry.get("graph"):
                body = {"subject": e["title"]}
                if e.get("time"):
                    hh, mm = (int(x) for x in e["time"].split(":"))
                    d = dt.date.fromisoformat(e["date"])
                    s = dt.datetime(d.year, d.month, d.day, hh, mm).astimezone()
                    length = dt.timedelta(minutes=int(entry.get("minutes", 60)))
                    body["start"] = {"dateTime": s.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"), "timeZone": "UTC"}
                    body["end"] = {"dateTime": (s + length).astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"), "timeZone": "UTC"}
                link.web.json("PATCH", f"{GRAPH}/me/events/{entry['graph']}", body)
                pushed += 1
            elif len(ids) == 1 and not e.get("repeat"):          # a series with its exceptions is left to the server
                new = patch_ics(entry["ics"], e["title"], e["date"], e.get("time", ""))
                status, headers, _ = link.web.call("PUT", href, new.encode("utf-8"), {"Content-Type": "text/calendar; charset=utf-8", "If-Match": entry.get("etag", "")})
                if status < 300:
                    pushed += 1
                elif status == 412:
                    log(f"“{e['title']}” changed on the server too; the server's version was kept.")
    # then everything comes back from the server
    events, fresh = [], {}
    if acct["provider"] == "microsoft":
        cals = link.web.json("GET", f"{GRAPH}/me/calendars?$select=id,name,hexColor,canEdit")["value"]
        for cal in cals:
            if cal["id"] in acct.get("hidden", []):
                continue
            url = (f"{GRAPH}/me/calendars/{cal['id']}/calendarView?startDateTime={start:%Y-%m-%dT%H:%M:%SZ}&endDateTime={end:%Y-%m-%dT%H:%M:%SZ}"
                   "&$select=id,subject,start,end,isAllDay&$top=500")
            while url:
                page = link.web.json("GET", url, headers={"Prefer": 'outlook.timezone="UTC"'})
                for item in page.get("value", []):
                    try:
                        e = graph_event(item)
                    except (ValueError, KeyError):
                        continue
                    s0 = dt.datetime.fromisoformat(item["start"]["dateTime"][:19])
                    s1 = dt.datetime.fromisoformat(item["end"]["dateTime"][:19])
                    e.update(account=acct["id"], cal=cal.get("name", ""), colour=cal.get("hexColor") or PROVIDERS["microsoft"]["a"])
                    events.append(e)
                    fresh["ms:" + item["id"]] = {"graph": item["id"], "ids": [e["id"]], "hashes": {e["id"]: event_hash(e)}, "minutes": int((s1 - s0).total_seconds() // 60)}
                url = page.get("@odata.nextLink", "")
        return events, fresh, pushed
    home = find_home(link.web, link.dav_start("cal"), "cal")
    cals = list_collections(link.web, home, "cal")
    if not cals and acct["provider"] == "google":                 # Google always has the main calendar here
        cals = [{"url": f"https://apidata.googleusercontent.com/caldav/v2/{urllib.parse.quote(acct['email'])}/events", "name": "Calendar", "colour": ""}]
    for cal in cals:
        if cal["url"] in acct.get("hidden", []):
            continue
        for item in caldav_events(link.web, cal["url"], start, end):
            found = read_ics(item["ics"])
            for e in found:
                e.update(account=acct["id"], cal=cal["name"], colour=cal["colour"] or PROVIDERS[acct["provider"]]["a"])
            events += found
            fresh[item["href"]] = {"etag": item["etag"], "ics": item["ics"], "ids": [e["id"] for e in found], "hashes": {e["id"]: event_hash(e) for e in found}}
    return events, fresh, pushed


def sync_contacts(link: Link) -> list:
    acct = link.acct
    if acct["provider"] == "microsoft":
        out, url = [], f"{GRAPH}/me/contacts?$top=500"
        while url:
            page = link.web.json("GET", url)
            out += [graph_card(c) for c in page.get("value", [])]
            url = page.get("@odata.nextLink", "")
        return out
    home = find_home(link.web, link.dav_start("card"), "card")
    out = []
    for book in list_collections(link.web, home, "card") or [{"url": home}]:
        out += [c["vcf"] for c in carddav_cards(link.web, book["url"])]
    return out


def merge_calendar(acct_id: str, events: list) -> None:
    """Swap this account's events in calendar.json for the fresh ones, leaving everything else untouched."""
    try:
        local = json.loads(CAL_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        local = []
    keep = [e for e in local if isinstance(e, dict) and e.get("account") != acct_id]
    CAL_FILE.parent.mkdir(parents=True, exist_ok=True)
    part = CAL_FILE.with_name(".calendar.json.accounts")
    part.write_text(json.dumps(keep + events, indent=1), encoding="utf-8")
    os.replace(part, CAL_FILE)


def merge_contacts(acct_id: str, vcards: list) -> int:
    """Swap this account's cards in contacts.vcf for the fresh ones; each carries X-HUGINN-ACCOUNT so it can be found."""
    sys.path.insert(0, str(HERE))
    from huginn_more import read_vcards, write_vcards
    try:
        cards = read_vcards(CARD_FILE.read_text(encoding="utf-8", errors="replace"))
    except OSError:
        cards = []
    tag = f"X-HUGINN-ACCOUNT:{acct_id}"
    keep = [c for c in cards if tag not in (c.get("extra") or [])]
    fresh = []
    for text in vcards:
        for c in read_vcards(text):
            c["extra"] = [x for x in (c.get("extra") or []) if not x.startswith("X-HUGINN-ACCOUNT")] + [tag]
            fresh.append(c)
    CARD_FILE.parent.mkdir(parents=True, exist_ok=True)
    part = CARD_FILE.with_name(".contacts.vcf.accounts")
    part.write_text(write_vcards(keep + fresh), encoding="utf-8")
    os.replace(part, CARD_FILE)
    return len(fresh)


def forget_everywhere(acct_id: str) -> None:
    """Take an account's events and cards off this computer (nothing on the server changes)."""
    merge_calendar(acct_id, [])
    try:
        merge_contacts(acct_id, [])
    except Exception:                                                # noqa: BLE001
        pass
    for f in (STATE_DIR / f"{acct_id}.cal.json",):
        f.unlink(missing_ok=True)


def sync_one(acct: dict, secret: dict, rotated=None, log=print) -> dict:
    link = Link(acct, secret, rotated)
    result = {"when": time.time(), "error": ""}
    services = acct.get("services") or {}
    try:
        if services.get("calendar"):
            cache_file = STATE_DIR / f"{acct['id']}.cal.json"
            try:
                cache = json.loads(cache_file.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                cache = {}
            try:
                local = json.loads(CAL_FILE.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                local = []
            events, fresh, pushed = sync_calendars(link, cache, local, log)
            merge_calendar(acct["id"], events)
            STATE_DIR.mkdir(parents=True, exist_ok=True)
            cache_file.write_text(json.dumps(fresh), encoding="utf-8")
            result.update(events=len(events), sent=pushed)
        else:
            merge_calendar(acct["id"], [])
        if services.get("contacts"):
            result["contacts"] = merge_contacts(acct["id"], sync_contacts(link))
        else:
            merge_contacts(acct["id"], [])
        if services.get("files") and acct["provider"] == "nextcloud":
            result["files"] = mount_files(acct, secret)
    except AccountError as err:
        result["error"] = str(err)
    except (OSError, ValueError, KeyError) as err:
        result["error"] = f"Something went wrong: {err}"[:200]
    except Exception as err:                                        # noqa: BLE001  (a sign-in error from huginn_mail, mostly)
        result["error"] = "The account signed Huginn out. Sign in again from Settings." if str(err) == "signed-out" else str(err)[:200]
    return result


def files_url(acct: dict, secret: dict) -> str:
    host = urllib.parse.urlsplit(acct["server"])
    path = (host.path.rstrip("/") + "/remote.php/dav/files/" + urllib.parse.quote(secret.get("user", "")) + "/")
    return f"davs://{urllib.parse.quote(secret.get('user', ''))}@{host.netloc}{path}"


def mount_files(acct: dict, secret: dict) -> str:
    """Mount the Nextcloud files with gvfs (Files lists it) and add it to the places in Files' side bar."""
    url = files_url(acct, secret)
    code, _, err = run_tool(["gio", "mount", url], f"{secret.get('user', '')}\n{secret.get('password', '')}\n")
    if code != 0 and "already mounted" not in err.lower():
        return "not mounted: " + (err.strip().splitlines() or [""])[-1][:120]
    marks = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "gtk-3.0" / "bookmarks"
    try:
        have = marks.read_text(encoding="utf-8") if marks.exists() else ""
        if url not in have:
            marks.parent.mkdir(parents=True, exist_ok=True)
            marks.write_text(have + ("" if have.endswith("\n") or not have else "\n") + f"{url} Nextcloud\n", encoding="utf-8")
    except OSError:
        pass
    return "mounted"


def run_tool(argv: list, stdin: str = None) -> tuple:
    try:
        done = subprocess.run(argv, input=stdin, capture_output=True, text=True, timeout=60)
        return done.returncode, done.stdout, done.stderr
    except (OSError, subprocess.TimeoutExpired) as err:
        return 127, "", str(err)


# ------------------------------------------------------------------------------------------- Mail gets the account too
def mail_entry(acct: dict, secret: dict) -> tuple:
    """The account as Mail keeps it (accounts.json entry, vault secret), so Mail shows it like one added there."""
    imap = PROVIDERS[acct["provider"]]["imap"]
    cfg = {"id": "oa-" + acct["id"], "name": acct.get("name", ""), "email": acct["email"], "user": acct["email"], "imap_host": imap[0], "imap_port": imap[1],
           "smtp_host": imap[2], "smtp_port": imap[3], "oauth": acct["provider"] if PROVIDERS[acct["provider"]]["sign"] == "oauth" else "", "from": "accounts", "account": acct["id"]}
    if cfg["oauth"]:
        mail_secret = {"kind": "oauth", "provider": acct["provider"], "refresh": secret.get("refresh", ""), "email": acct["email"]}
    else:
        mail_secret = {"kind": "password", "password": secret.get("password", ""), "email": acct["email"]}
    return cfg, mail_secret


def set_mail(acct: dict, secret: dict, vault, on: bool) -> None:
    try:
        listed = json.loads((MAIL_HOME / "accounts.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        listed = []
    cfg, mail_secret = mail_entry(acct, secret)
    listed = [a for a in listed if isinstance(a, dict) and a.get("id") != cfg["id"]]
    if on:
        if any(a.get("email", "").lower() == acct["email"].lower() for a in listed):
            return                                               # already added in Mail by hand: leave that one be
        vault.set_secret("mail", cfg["id"], mail_secret)
        listed.append(cfg)
    else:
        vault.set_secret("mail", cfg["id"], None)
    MAIL_HOME.mkdir(parents=True, exist_ok=True)
    part = MAIL_HOME / ".accounts.json.saving"
    part.write_text(json.dumps(listed), encoding="utf-8")
    os.replace(part, MAIL_HOME / "accounts.json")


# ------------------------------------------------------------------------------------------- signing in
def nextcloud_flow(server: str, open_url, stopped, wait: float = 600) -> dict:
    """Nextcloud's Login Flow v2: open its page in the browser; it hands back a password made for this computer."""
    server = server.strip().rstrip("/")
    if not re.match(r"^https?://", server):
        server = "https://" + server
    if not server.startswith("https://"):
        raise AccountError("Use the https:// address of your Nextcloud.")
    req = urllib.request.Request(server + "/index.php/login/v2", data=b"", method="POST", headers={"User-Agent": "Huginn OS"})
    try:
        with urllib.request.urlopen(req, timeout=30) as reply:
            start = json.loads(reply.read())
    except (OSError, ValueError) as err:
        raise AccountError(f"That doesn't look like a Nextcloud at {urllib.parse.urlsplit(server).hostname}.") from err
    poll = start.get("poll") or {}
    if not start.get("login") or not poll.get("endpoint", "").startswith("https://"):
        raise AccountError("The Nextcloud didn't start its sign-in.")
    open_url(start["login"])
    until = time.monotonic() + wait
    while time.monotonic() < until:
        if stopped():
            raise AccountError("")
        time.sleep(2)
        req = urllib.request.Request(poll["endpoint"], data=urllib.parse.urlencode({"token": poll.get("token", "")}).encode(), method="POST", headers={"User-Agent": "Huginn OS"})
        try:
            with urllib.request.urlopen(req, timeout=20) as reply:
                done = json.loads(reply.read())
                return {"server": done.get("server") or server, "user": done.get("loginName", ""), "password": done.get("appPassword", "")}
        except urllib.error.HTTPError as err:
            if err.code != 404:
                raise AccountError(f"The Nextcloud answered {err.code}.") from None
        except (OSError, ValueError):
            continue
    raise AccountError("Nobody finished signing in, so Huginn stopped waiting.")


def oauth_ready(provider: str) -> bool:
    sys.path.insert(0, str(HERE))
    import huginn_mail
    return bool(huginn_mail.oauth_client(provider).get("client_id"))


# ------------------------------------------------------------------------------------------- Settings' page
DEMO = [{"id": "d1", "provider": "google", "email": "astrid@example.com", "name": "Astrid", "services": {"mail": True, "calendar": True, "contacts": True}},
        {"id": "d2", "provider": "nextcloud", "email": "astrid@cloud.raven.home", "server": "https://cloud.raven.home", "name": "", "services": {"calendar": True, "contacts": False, "files": True}},
        {"id": "d3", "provider": "icloud", "email": "astrid@icloud.com", "name": "", "services": {"mail": False, "calendar": True, "contacts": True}}]
DEMO_STATUS = {"d1": {"when": time.time() - 420, "error": "", "events": 214, "contacts": 388}, "d2": {"when": time.time() - 900, "error": "", "events": 41, "files": "mounted"},
               "d3": {"when": time.time() - 3600 * 5, "error": "The account didn't accept the sign-in. Sign in again from Settings.", "events": 0}}


class Accounts(QObject):
    changed = Signal()
    said = Signal(str, bool)
    _call = Signal(object)

    def __init__(self, demo: bool = False):
        super().__init__()
        self._demo = demo
        self._accounts = [dict(a) for a in DEMO] if demo else read_list()
        self._status = dict(DEMO_STATUS) if demo else read_status()
        self._adding, self._waiting, self._stop, self._syncing = "", "", False, set()
        self._call.connect(lambda fn: fn())
        self._vault = self._session = None
        if not demo:
            sys.path.insert(0, str(HERE))
            import huginn_vault as hv
            self._hv, self._vault = hv, hv.VaultFile()
            self._session = hv.Session(self._vault)
            self._session.try_unlock()
            self._watch = QTimer(self)                           # the background syncer writes status as it goes
            self._watch.setInterval(5000)
            self._watch.timeout.connect(self._reread)
            self._watch.start()

    def _reread(self) -> None:
        status, accounts = read_status(), read_list()
        if status != self._status or accounts != self._accounts:
            self._status, self._accounts = status, accounts
            self.changed.emit()

    def _since(self, when: float) -> str:
        if not when:
            return "Not yet"
        ago = time.time() - when
        return "Just now" if ago < 90 else f"{int(ago // 60)} min ago" if ago < 3600 else f"{int(ago // 3600)} h ago" if ago < 86400 else time.strftime("%b %-d", time.localtime(when))

    @Property("QVariantList", notify=changed)
    def accounts(self):
        out = []
        for a in self._accounts:
            p, st = PROVIDERS[a["provider"]], self._status.get(a["id"], {})
            bits = []
            if st.get("events"):
                bits.append(f"{st['events']} events")
            if st.get("contacts"):
                bits.append(f"{st['contacts']} contacts")
            out.append({"id": a["id"], "provider": a["provider"], "providerName": p["name"], "email": a["email"], "a": p["a"], "b": p["b"],
                        "services": [{"id": s, "label": SERVICE_NAMES[s], "on": bool((a.get("services") or {}).get(s))} for s in p["services"]],
                        "error": st.get("error", ""), "synced": self._since(st.get("when", 0)), "summary": ", ".join(bits), "syncing": a["id"] in self._syncing})
        return out

    @Property("QVariantList", constant=True)
    def providers(self):
        return [{"id": k, "name": v["name"], "a": v["a"], "b": v["b"], "sign": v["sign"], "blurb": v["blurb"], "note": v.get("note", ""),
                 "ready": True if v["sign"] != "oauth" or self._demo else oauth_ready(k)} for k, v in PROVIDERS.items()]

    locked = Property(bool, lambda self: not self._demo and (self._vault is None or self._vault.locked()), notify=changed)
    vaultExists = Property(bool, lambda self: self._demo or (self._vault is not None and self._vault.exists()), notify=changed)
    adding = Property(str, lambda self: self._adding, notify=changed)
    waiting = Property(str, lambda self: self._waiting, notify=changed)

    @Slot()
    def refresh(self) -> None:
        if self._demo:
            return
        if self._vault.locked():
            self._session.try_unlock()
        self._reread()
        self.changed.emit()

    @Slot(str, result=str)
    def unlock(self, master: str) -> str:
        if self._demo:
            return ""
        try:
            self._vault.unlock(master)
            self._session.unlocked()
        except self._hv.WrongPassword:
            return "That isn't the master password."
        except (self._hv.VaultError, OSError) as err:
            return f"Couldn't open Passwords: {err}"
        self.changed.emit()
        return ""

    @Slot(str, str)
    def create(self, master: str, again: str) -> None:
        if master != again or len(master) < 8:
            self.said.emit("The master password needs 8 characters or more, typed the same twice.", True)
            return
        try:
            self._vault.create(master)
            self._session.unlocked()
        except (self._hv.VaultError, OSError) as err:
            self.said.emit(f"Couldn't make the vault: {err}", True)
        self.changed.emit()

    @Slot(str, "QVariantMap")
    def add(self, provider: str, form) -> None:
        """form: {email, password} for iCloud, {email} for Google and Microsoft, {server} for Nextcloud."""
        if provider not in PROVIDERS or self._adding:
            return
        p = PROVIDERS[provider]
        email = str(form.get("email", "")).strip()
        if p["sign"] != "flow" and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
            self.said.emit("Type the account's email address.", True)
            return
        if self._demo:
            self._accounts.append({"id": uuid.uuid4().hex[:8], "provider": provider, "email": email or str(form.get("server", "")), "services": {s: True for s in p["services"]}})
            self.changed.emit()
            self.said.emit(f"{p['name']} is added.", False)
            return
        if self._vault.locked():
            self.said.emit("Unlock Passwords first: that's where the sign-in is kept.", True)
            return
        if p["sign"] == "oauth" and not oauth_ready(provider):
            self.said.emit(f"This copy of Huginn isn't registered with {p['name']} yet, so it can't use its sign-in page. See Help › Online Accounts.", True)
            return
        self._adding, self._stop = provider, False
        self._waiting = p["name"] if p["sign"] != "password" else ""
        self.changed.emit()
        threading.Thread(target=self._add, args=(provider, dict(form), email), daemon=True).start()

    def _open_url(self, url: str) -> None:
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        QDesktopServices.openUrl(QUrl(url))

    def _add(self, provider: str, form: dict, email: str) -> None:
        p = PROVIDERS[provider]
        try:
            acct = {"id": uuid.uuid4().hex[:12], "provider": provider, "email": email, "name": "", "services": {s: True for s in p["services"]}, "added": time.time()}
            if p["sign"] == "oauth":
                import huginn_mail
                got = huginn_mail.oauth_sign_in(provider, email, lambda url: self._call.emit(lambda: self._open_url(url)), lambda: self._stop,
                                                scope=p["scope"], token_scope=p.get("token_scope", ""), app_name="Settings")
                secret = {"kind": "oauth", "provider": provider, "refresh": got["refresh"], "access": got["access"], "expires": got["expires"]}
            elif p["sign"] == "password":
                secret = {"kind": "password", "user": email, "password": str(form.get("password", ""))}
                if not secret["password"]:
                    raise AccountError("Type the app-specific password.")
            else:
                got = nextcloud_flow(str(form.get("server", "")), lambda url: self._call.emit(lambda: self._open_url(url)), lambda: self._stop)
                secret = {"kind": "password", "user": got["user"], "password": got["password"]}
                acct.update(server=got["server"], email=f"{got['user']}@{urllib.parse.urlsplit(got['server']).hostname}")
            self._call.emit(lambda: setattr(self, "_waiting", "") or self.changed.emit())
            if any(a["provider"] == provider and a["email"].lower() == acct["email"].lower() for a in self._accounts):
                raise AccountError("That account is already here.")
            # a first look proves the sign-in works before anything is kept
            result = sync_one(acct, dict(secret))
            if result["error"]:
                raise AccountError(result["error"])
            self._call.emit(lambda: self._added(acct, {k: v for k, v in secret.items() if k not in ("access", "expires")}, result))
        except AccountError as err:
            self._call.emit(lambda m=str(err): self._failed(m))
        except Exception as err:                                    # noqa: BLE001  (a SignInError from Mail's sign-in)
            self._call.emit(lambda m=str(err): self._failed(m))

    def _failed(self, message: str) -> None:
        self._adding, self._waiting = "", ""
        self.changed.emit()
        if message:
            self.said.emit(message, True)

    def _added(self, acct: dict, secret: dict, result: dict) -> None:
        self._adding, self._waiting = "", ""
        try:
            self._vault.set_secret("accounts", acct["id"], secret)
            if acct["services"].get("mail"):
                set_mail(acct, secret, self._vault, True)
        except (self._hv.VaultError, OSError) as err:
            forget_everywhere(acct["id"])
            self.said.emit(f"Signed in, but couldn't keep the sign-in in Passwords: {err}", True)
            self.changed.emit()
            return
        self._accounts = read_list() + [acct]
        write_list(self._accounts)
        self._status[acct["id"]] = result
        write_status(self._status)
        self.changed.emit()
        name = PROVIDERS[acct["provider"]]["name"]
        bits = [f"{result['events']} events" if result.get("events") else "", f"{result['contacts']} contacts" if result.get("contacts") else ""]
        self.said.emit(f"{name} is added" + (": " + " and ".join(b for b in bits if b) + " came across." if any(bits) else "."), False)

    @Slot()
    def cancel(self) -> None:
        self._stop = True

    def _secret(self, ident: str) -> dict:
        if self._vault is None or self._vault.locked():
            raise AccountError("Unlock Passwords first: that's where the sign-in is kept.")
        secret = self._vault.secret("accounts", ident)
        if not secret:
            raise AccountError("This account's sign-in isn't in Passwords any more. Remove it and add it again.")
        return dict(secret)

    @Slot(str, str, bool)
    def setService(self, ident: str, service: str, on: bool) -> None:
        acct = next((a for a in self._accounts if a["id"] == ident), None)
        if acct is None or service not in PROVIDERS[acct["provider"]]["services"]:
            return
        acct.setdefault("services", {})[service] = on
        if self._demo:
            self.changed.emit()
            return
        try:
            if service == "mail":
                set_mail(acct, self._secret(ident), self._vault, on)
            elif service == "files" and not on:
                run_tool(["gio", "mount", "-u", files_url(acct, self._secret(ident))])
        except (AccountError, OSError, self._hv.VaultError) as err:
            self.said.emit(str(err), True)
        write_list(self._accounts)
        self.changed.emit()
        self.syncNow(ident)

    @Slot(str)
    def syncNow(self, ident: str) -> None:
        if self._demo:
            self.said.emit("Up to date.", False)
            return
        for acct in [a for a in self._accounts if ident in ("all", a["id"])]:
            if acct["id"] in self._syncing:
                continue
            try:
                secret = self._secret(acct["id"])
            except AccountError as err:
                self.said.emit(str(err), True)
                return
            self._syncing.add(acct["id"])
            self.changed.emit()

            def work(acct=acct, secret=secret):
                result = sync_one(acct, secret, lambda new, i=acct["id"]: self._call.emit(lambda: self._rotate(i, new)))
                self._call.emit(lambda: self._synced(acct["id"], result))
            threading.Thread(target=work, daemon=True).start()

    def _rotate(self, ident: str, refresh: str) -> None:
        try:
            secret = self._secret(ident)
            secret["refresh"] = refresh
            self._vault.set_secret("accounts", ident, secret)
        except (AccountError, OSError, self._hv.VaultError):
            pass

    def _synced(self, ident: str, result: dict) -> None:
        self._syncing.discard(ident)
        self._status = read_status()
        self._status[ident] = result
        write_status(self._status)
        self.changed.emit()
        if result.get("error"):
            self.said.emit(result["error"], True)

    @Slot(str)
    def remove(self, ident: str) -> None:
        acct = next((a for a in self._accounts if a["id"] == ident), None)
        if acct is None:
            return
        self._accounts = [a for a in self._accounts if a["id"] != ident]
        if not self._demo:
            write_list(self._accounts)
            try:
                secret = self._vault.secret("accounts", ident) or {} if not self._vault.locked() else {}
                set_mail(acct, secret, self._vault, False) if not self._vault.locked() else None
                if acct["provider"] == "nextcloud" and secret:
                    run_tool(["gio", "mount", "-u", files_url(acct, secret)])
                if not self._vault.locked():
                    self._vault.set_secret("accounts", ident, None)
            except (OSError, self._hv.VaultError):
                pass
            forget_everywhere(ident)
            self._status.pop(ident, None)
            write_status(self._status)
        self.changed.emit()
        self.said.emit(f"{PROVIDERS[acct['provider']]['name']} is removed from this computer. Nothing on the account itself changed.", False)


# ------------------------------------------------------------------------------------------- in the background
def watch(every: float = 900) -> None:
    """Keep every account in step while you're signed in. Needs Passwords unlocked (in any Huginn app)."""
    sys.path.insert(0, str(HERE))
    import huginn_vault as hv
    vault = hv.VaultFile()
    session = hv.Session(vault)
    while True:
        accounts = read_list()
        if accounts and (not vault.locked() or session.try_unlock()):
            vault.refresh()
            status = read_status()
            for acct in accounts:
                secret = vault.secret("accounts", acct["id"])
                if not secret:
                    continue

                def rotated(new, i=acct["id"]):
                    s = dict(vault.secret("accounts", i) or {})
                    s["refresh"] = new
                    try:
                        vault.set_secret("accounts", i, s)
                    except (hv.VaultError, OSError):
                        pass
                status[acct["id"]] = sync_one(acct, dict(secret), rotated, log=lambda m: None)
                write_status(status)
        time.sleep(every)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "watch":
        watch()
