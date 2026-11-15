"""Huginn Mail: real accounts.

Reads over IMAP and sends over SMTP, always inside TLS with the server's certificate checked. Message lists and the
messages you have opened are kept in a small database on this computer, so Mail opens at once and works offline for
reading. HTML messages are shown as text: nothing in a message is ever fetched from the internet, which also means
the tracking pictures senders hide in mail never load.

Every account's secret (its password, or its sign-in token) is kept in the Passwords vault, under the master
password, with the browser's logins. Mail holds them in memory only while the vault is unlocked for it.

Google and Microsoft accounts sign in through the provider's own page in the browser (OAuth 2, with PKCE); Mail
never sees that password, only a token it can use for mail and nothing else. That needs Huginn to be registered
with each provider once: see OAUTH below and the README.
"""
import base64
import datetime as dt
import email
import email.header
import email.policy
import email.utils
import html
import html.parser
import imaplib
import json
import os
import queue
import re
import shutil
import smtplib
import socket
import sqlite3
import ssl
import subprocess
import sys
import threading
import time
import urllib.parse
import uuid
from email.message import EmailMessage
from urllib.parse import unquote as urllib_unquote
from pathlib import Path

from PySide6.QtCore import Property, QObject, QStandardPaths, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices

DATA_HOME = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share") / "huginn"
MAIL_HOME = DATA_HOME / "mail"
WINDOW = 400                                                      # how many of the newest messages each mailbox keeps listed
PREFETCH = 25                                                     # how many of the newest are read ahead, for the preview line
APP_PW = {"google": "Or use an app password: Google Account → Security → 2-Step Verification → App passwords.",
          "apple": "Apple needs an app-specific password: account.apple.com → Sign-In and Security.",
          "yahoo": "Yahoo needs an app password: Account Security → Generate app password.",
          "aol": "AOL needs an app password: Account Security → Generate app password.",
          "fastmail": "Fastmail needs an app password: Settings → Privacy & Security → App passwords."}
PROVIDERS = {   # domain: (imap host, imap port, smtp host, smtp port, sign-in window, note)
    "gmail.com": ("imap.gmail.com", 993, "smtp.gmail.com", 465, "google", APP_PW["google"]),
    "googlemail.com": ("imap.gmail.com", 993, "smtp.gmail.com", 465, "google", APP_PW["google"]),
    "outlook.com": ("outlook.office365.com", 993, "smtp-mail.outlook.com", 587, "microsoft", ""),
    "hotmail.com": ("outlook.office365.com", 993, "smtp-mail.outlook.com", 587, "microsoft", ""),
    "live.com": ("outlook.office365.com", 993, "smtp-mail.outlook.com", 587, "microsoft", ""),
    "msn.com": ("outlook.office365.com", 993, "smtp-mail.outlook.com", 587, "microsoft", ""),
    "icloud.com": ("imap.mail.me.com", 993, "smtp.mail.me.com", 587, "", APP_PW["apple"]),
    "me.com": ("imap.mail.me.com", 993, "smtp.mail.me.com", 587, "", APP_PW["apple"]),
    "mac.com": ("imap.mail.me.com", 993, "smtp.mail.me.com", 587, "", APP_PW["apple"]),
    "yahoo.com": ("imap.mail.yahoo.com", 993, "smtp.mail.yahoo.com", 465, "", APP_PW["yahoo"]),
    "ymail.com": ("imap.mail.yahoo.com", 993, "smtp.mail.yahoo.com", 465, "", APP_PW["yahoo"]),
    "aol.com": ("imap.aol.com", 993, "smtp.aol.com", 465, "", APP_PW["aol"]),
    "fastmail.com": ("imap.fastmail.com", 993, "smtp.fastmail.com", 465, "", APP_PW["fastmail"]),
    "fastmail.fm": ("imap.fastmail.com", 993, "smtp.fastmail.com", 465, "", APP_PW["fastmail"]),
    "gmx.com": ("imap.gmx.com", 993, "mail.gmx.com", 465, "", ""), "gmx.net": ("imap.gmx.net", 993, "mail.gmx.net", 465, "", ""),
    "gmx.de": ("imap.gmx.net", 993, "mail.gmx.net", 465, "", ""), "web.de": ("imap.web.de", 993, "smtp.web.de", 587, "", ""),
    "zoho.com": ("imap.zoho.com", 993, "smtp.zoho.com", 465, "", ""), "mail.com": ("imap.mail.com", 993, "smtp.mail.com", 587, "", ""),
    "yandex.com": ("imap.yandex.com", 993, "smtp.yandex.com", 465, "", "Yandex needs an app password: Account → Security → App passwords."),
    "mailbox.org": ("imap.mailbox.org", 993, "smtp.mailbox.org", 465, "", ""), "posteo.de": ("posteo.de", 993, "posteo.de", 465, "", ""),
    "posteo.net": ("posteo.de", 993, "posteo.de", 465, "", ""), "runbox.com": ("mail.runbox.com", 993, "mail.runbox.com", 465, "", ""),
    "tuta.com": ("", 0, "", 0, "", "Tuta doesn't offer IMAP to any mail app, so it can't be added here."),
    "tutanota.com": ("", 0, "", 0, "", "Tuta doesn't offer IMAP to any mail app, so it can't be added here."),
    "proton.me": ("127.0.0.1", 1143, "127.0.0.1", 1025, "", "Proton Mail works through its Bridge app: run Bridge, and use the password Bridge shows, not your Proton one."),
    "protonmail.com": ("127.0.0.1", 1143, "127.0.0.1", 1025, "", "Proton Mail works through its Bridge app: run Bridge, and use the password Bridge shows, not your Proton one."),
    "pm.me": ("127.0.0.1", 1143, "127.0.0.1", 1025, "", "Proton Mail works through its Bridge app: run Bridge, and use the password Bridge shows, not your Proton one."),
}
# The providers that only let a mail app in through their own sign-in page. Huginn has to be registered with each
# once (free); the registration's public id goes in /etc/huginn/mail-oauth.json (for everyone on the computer) or
# ~/.config/huginn/mail-oauth.json:  {"google": {"client_id": "...", "client_secret": "..."}, "microsoft": {"client_id": "..."}}
OAUTH = {
    "google": {"name": "Google", "auth_url": "https://accounts.google.com/o/oauth2/v2/auth", "token_url": "https://oauth2.googleapis.com/token",
               "scope": "https://mail.google.com/", "redirect": "http://127.0.0.1:{port}/", "extra": {"access_type": "offline", "prompt": "consent"}},
    "microsoft": {"name": "Microsoft", "auth_url": "https://login.microsoftonline.com/common/oauth2/v2.0/authorize",
                  "token_url": "https://login.microsoftonline.com/common/oauth2/v2.0/token",
                  "scope": "https://outlook.office.com/IMAP.AccessAsUser.All https://outlook.office.com/SMTP.Send offline_access",
                  "redirect": "http://localhost:{port}/", "extra": {"prompt": "select_account"}},
}
ROLE_ICONS = {"inbox": "inbox", "starred": "star", "drafts": "edit", "sent": "send", "archive": "download", "junk": "x", "trash": "trash", "": "folder"}
ROLE_ORDER = ["inbox", "starred", "drafts", "sent", "archive", "junk", "trash", ""]


def oauth_client(provider: str) -> dict:
    """The provider's addresses plus this installation's registration with it. No "client_id" means not registered."""
    out = dict(OAUTH.get(provider) or {})
    for file in (Path("/etc/huginn/mail-oauth.json"), Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "huginn" / "mail-oauth.json"):
        try:
            mine = json.loads(file.read_text(encoding="utf-8")).get(provider)
        except (OSError, ValueError, AttributeError):
            continue
        if isinstance(mine, dict):
            for key in ("client_id", "client_secret", "auth_url", "token_url"):
                value = str(mine.get(key, "")).strip()
                if value and (not key.endswith("_url") or value.startswith(("https://", "http://127.0.0.1:", "http://localhost:"))):
                    out[key] = value
    return out


def guess_servers(address: str) -> dict:
    """What to try for an email address: the provider's known servers, or the usual names at its own domain."""
    address = address.strip()
    domain = address.rsplit("@", 1)[-1].lower() if "@" in address else ""
    known = PROVIDERS.get(domain)
    imap_host, imap_port, smtp_host, smtp_port, window, note = known or ("imap." + domain if domain else "", 993, "smtp." + domain if domain else "", 465, "", "")
    out = {"email": address, "user": address, "imap_host": imap_host, "imap_port": imap_port or 993, "smtp_host": smtp_host, "smtp_port": smtp_port or 465,
           "note": note, "known": known is not None, "blocked": known is not None and not imap_host, "oauth": window, "oauthName": "", "oauthReady": False, "passwordToo": window != "microsoft"}
    if window:
        client = oauth_client(window)
        out["oauthName"], out["oauthReady"] = client["name"], bool(client.get("client_id"))
        if not out["oauthReady"]:
            lead = f"{client['name']} only lets mail apps in through its own sign-in page, and this copy of Huginn isn't registered with {client['name']} yet (see the README: it takes a free registration, once). "
            out["note"] = lead + (note if window == "google" else "Until then this account can't be added.")
        elif window == "microsoft":
            out["note"] = "Microsoft asks you to sign in on its own page, in the browser."
        else:
            out["note"] = "Sign in on Google's own page, in the browser. " + note
    return out


# -------------------------------------------------------------------------------- signing in on the provider's page
class SignInError(Exception):
    pass


class MaybeSent(Exception):
    """The connection dropped after the message had started going out: it may or may not have arrived."""


def _post_form(url: str, fields: dict) -> dict:
    import urllib.error
    import urllib.request
    data = urllib.parse.urlencode(fields).encode("ascii")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json", "User-Agent": "HuginnMail/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=25) as reply:
            return json.loads(reply.read().decode("utf-8"))
    except urllib.error.HTTPError as err:
        try:
            return json.loads(err.read().decode("utf-8"))
        except ValueError:
            raise SignInError(f"The sign-in service answered {err.code}.") from None
    except (OSError, ValueError) as err:
        raise SignInError("Couldn't reach the sign-in service. Check that you're online.") from err


def oauth_sign_in(provider: str, address: str, open_url, stopped=lambda: False, wait: float = 300, scope: str = "", token_scope: str = "",
                  app_name: str = "Mail") -> dict:
    """Send the person to the provider's own sign-in page and wait for it to hand back a one-time code on this
    computer (a tiny web server on 127.0.0.1 that answers once). The code is swapped for tokens with a secret made
    for this one sign-in (PKCE), so a code that leaked would be useless. Returns {"refresh", "access", "expires"}."""
    import hashlib
    import secrets as rnd
    client = oauth_client(provider)
    if not client.get("client_id"):
        raise SignInError(f"This copy of Huginn isn't registered with {client.get('name', provider)} yet.")
    verifier, state = rnd.token_urlsafe(64), rnd.token_urlsafe(24)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).decode("ascii").rstrip("=")
    listeners = []
    first = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    first.bind(("127.0.0.1", 0))
    port = first.getsockname()[1]
    listeners.append(first)
    try:                                                           # "localhost" is ::1 for some browsers
        six = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
        six.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
        six.bind(("::1", port))
        listeners.append(six)
    except OSError:
        pass
    redirect = client["redirect"].format(port=port)
    query = {"client_id": client["client_id"], "redirect_uri": redirect, "response_type": "code", "scope": scope or client["scope"], "state": state,
             "code_challenge": challenge, "code_challenge_method": "S256", "login_hint": address, **client.get("extra", {})}
    code, problem = "", ""
    try:
        for sock in listeners:
            sock.listen(4)
            sock.settimeout(0.25)
        open_url(client["auth_url"] + ("&" if "?" in client["auth_url"] else "?") + urllib.parse.urlencode(query))
        until = time.monotonic() + wait
        while not code and not problem:
            if stopped():
                raise SignInError("")
            if time.monotonic() > until:
                raise SignInError(f"Nobody finished signing in, so {app_name} stopped waiting.")
            for sock in listeners:
                try:
                    conn, _ = sock.accept()
                except (socket.timeout, OSError):
                    continue
                with conn:
                    conn.settimeout(5)
                    try:
                        line = conn.makefile("rb").readline(8192).decode("ascii", "replace")
                    except OSError:
                        continue
                    answer = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(line.split(" ")[1] if line.count(" ") >= 2 else "").query))
                    good = answer.get("state") == state and bool(answer.get("code"))
                    if answer.get("state") == state and answer.get("error"):
                        problem = "You said no on the sign-in page." if answer["error"] == "access_denied" else f"The sign-in page reported: {answer.get('error_description') or answer['error']}"[:200]
                    elif good:
                        code = answer["code"]
                    text = f"You're signed in. Close this tab and go back to {app_name}." if good else f"That didn't work. Go back to {app_name} and try again." if problem else "Nothing to see here."
                    page = f"<!doctype html><meta charset=utf-8><title>Huginn {app_name}</title><body style='font:16px system-ui;margin:4em auto;max-width:28em;text-align:center'>{text}</body>".encode()
                    try:
                        conn.sendall(b"HTTP/1.1 " + (b"200 OK" if good or problem else b"404 Not Found") + b"\r\nContent-Type: text/html; charset=utf-8\r\nConnection: close\r\nContent-Length: "
                                     + str(len(page)).encode() + b"\r\n\r\n" + page)
                    except OSError:
                        pass
    finally:
        for sock in listeners:
            sock.close()
    if problem:
        raise SignInError(problem)
    fields = {"grant_type": "authorization_code", "code": code, "redirect_uri": redirect, "client_id": client["client_id"], "code_verifier": verifier}
    if client.get("client_secret"):
        fields["client_secret"] = client["client_secret"]
    if token_scope:                                                # Microsoft gives a token for one service at a time
        fields["scope"] = token_scope
    reply = _post_form(client["token_url"], fields)
    if not reply.get("access_token") or not reply.get("refresh_token"):
        raise SignInError("The sign-in finished but gave Mail nothing to stay signed in with: " + str(reply.get("error_description") or reply.get("error") or "no token")[:160])
    return {"refresh": reply["refresh_token"], "access": reply["access_token"], "expires": time.time() + float(reply.get("expires_in", 3000))}


class Tokens:
    """One account's sign-in token: hands out a short-lived pass for the mail servers, renewing it when it runs out."""

    def __init__(self, provider: str, secret: dict, rotated=None, scope: str = ""):
        self.provider, self.refresh, self._scope = provider, secret.get("refresh", ""), scope
        self._access, self._expires = secret.get("access", ""), float(secret.get("expires", 0))
        self._rotated, self._lock = rotated, threading.Lock()

    def access(self) -> str:
        with self._lock:
            if self._access and time.time() < self._expires - 90:
                return self._access
            client = oauth_client(self.provider)
            fields = {"grant_type": "refresh_token", "refresh_token": self.refresh, "client_id": client.get("client_id", "")}
            if client.get("client_secret"):
                fields["client_secret"] = client["client_secret"]
            if (self._scope or client.get("scope")) and self.provider == "microsoft":
                fields["scope"] = self._scope or client["scope"]
            reply = _post_form(client["token_url"], fields)
            if not reply.get("access_token"):
                gone = reply.get("error") in ("invalid_grant", "interaction_required", "invalid_client", "unauthorized_client")
                raise SignInError("signed-out" if gone else "Couldn't renew the sign-in: " + str(reply.get("error_description") or reply.get("error") or "no answer")[:160])
            self._access, self._expires = reply["access_token"], time.time() + float(reply.get("expires_in", 3000))
            if reply.get("refresh_token") and reply["refresh_token"] != self.refresh:
                self.refresh = reply["refresh_token"]              # some providers hand out a new one each time: keep the newest
                if self._rotated:
                    self._rotated(self.refresh)
            return self._access


def xoauth2(user: str, token: str) -> bytes:
    return f"user={user}\x01auth=Bearer {token}\x01\x01".encode("utf-8")


def read_mailto(link: str, given: dict = None) -> dict:
    """An email link (mailto:someone?subject=...&attach=/a/file) as a draft. Attachments must be ordinary files of
    yours, and never anything hidden or a key: a web page can make such a link, and you see the list before sending."""
    out = {}
    if given is None:
        if not link.lower().startswith("mailto:"):
            return out
        head, _, tail = link[7:].partition("?")
        fields = [("to", urllib_unquote(head))] + [(k.lower(), v) for k, v in urllib.parse.parse_qsl(tail, keep_blank_values=False)]
    else:
        fields = [(k, v) for k, v in given.items() if isinstance(v, str) and k in ("to", "cc", "subject", "body")] + [("attach", f) for f in (given.get("files") or []) if isinstance(f, str)]
        if clean_event(given.get("event")):
            out["event"] = clean_event(given["event"])
    files = []
    for key, value in fields:
        if key in ("to", "cc") and value.strip():
            out[key] = ", ".join(x for x in (out.get(key, ""), value.strip()[:2000]) if x)
        elif key in ("subject", "body"):
            out[key] = value[:200 if key == "subject" else 100_000]
        elif key == "x-huginn-event":
            try:
                event = clean_event(json.loads(value))
            except ValueError:
                event = {}
            if event:
                out["event"] = event
        elif key in ("attach", "attachment") and len(files) < 30:
            path = Path(urllib_unquote(value[7:]) if value.startswith("file://") else value).expanduser()
            try:
                real = path.resolve()
                risky = any(part.startswith(".") for part in real.relative_to(Path.home().resolve()).parts)
            except (OSError, ValueError):
                risky = True                                       # outside your home folder
            if not risky and real.is_file() and str(real) not in files:
                files.append(str(real))
    if files:
        out["files"] = files
    return out


# ---------------------------------------------------------------------------------------------- small tools
def utf7_decode(raw: str) -> str:
    """IMAP's own spelling of mailbox names ("Entw&APw-rfe") into text."""
    def one(m):
        if m.group(1) == "":
            return "&"
        try:
            return base64.b64decode(m.group(1).replace(",", "/") + "===").decode("utf-16-be")
        except (ValueError, UnicodeDecodeError):
            return m.group(0)
    return re.sub(r"&([^-]*)-", one, raw)


def utf7_encode(text: str) -> str:
    out, run = [], ""

    def flush():
        nonlocal run
        if run:
            out.append("&" + base64.b64encode(run.encode("utf-16-be")).decode().rstrip("=").replace("/", ",") + "-")
            run = ""
    for ch in text:
        if 0x20 <= ord(ch) <= 0x7E:
            flush()
            out.append("&-" if ch == "&" else ch)
        else:
            run += ch
    flush()
    return "".join(out)


def box(name: str) -> str:
    """A mailbox name as IMAP wants it sent."""
    return '"' + utf7_encode(name).replace("\\", "\\\\").replace('"', '\\"') + '"'


def header_text(value) -> str:
    if value is None:
        return ""
    try:
        return str(email.header.make_header(email.header.decode_header(str(value)))).replace("\r", "").replace("\n", " ").strip()
    except (LookupError, ValueError, UnicodeDecodeError):
        return str(value).strip()


class _Texter(html.parser.HTMLParser):
    """HTML mail → readable text. Links keep their address; nothing is ever loaded."""
    BLOCK = {"p", "div", "br", "tr", "li", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "table", "ul", "ol", "hr", "section", "article", "header", "footer"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out, self.skip, self.href = [], 0, ""

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "head", "title"):
            self.skip += 1
        elif tag in self.BLOCK:
            self.out.append("\n" + ("• " if tag == "li" else ""))
        elif tag == "a":
            self.href = dict(attrs).get("href") or ""
        elif tag == "img":
            alt = (dict(attrs).get("alt") or "").strip()
            if alt:
                self.out.append(f"[{alt}]")

    def handle_endtag(self, tag):
        if tag in ("script", "style", "head", "title"):
            self.skip = max(0, self.skip - 1)
        elif tag in ("p", "div", "tr", "table", "blockquote", "h1", "h2", "h3", "h4", "ul", "ol"):
            self.out.append("\n")
        elif tag == "a" and self.href:
            shown = "".join(self.out[-3:])
            if self.href.startswith(("http://", "https://")) and self.href.rstrip("/") not in shown:
                self.out.append(f" ({self.href})")
            self.href = ""
        elif tag in ("td", "th"):
            self.out.append("  ")

    def handle_data(self, data):
        if not self.skip:
            self.out.append(re.sub(r"\s+", " ", data))


def html_to_text(source: str) -> str:
    parser = _Texter()
    try:
        parser.feed(source)
        parser.close()
    except Exception:                                              # broken markup: show what was understood so far
        pass
    text = "".join(parser.out).replace("\xa0", " ").replace("‌", "").replace("​", "")
    text = re.sub(r"[ \t]+\n", "\n", re.sub(r"\n[ \t]+", "\n", text))
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def ics_event(text: str) -> dict:
    """The first event of a calendar file, as its own lines: {"METHOD": "REQUEST", "UID": ("UID", "abc"), ...} with each
    value a (line head with its parameters, value) pair; "ATTENDEE" is a list of them."""
    lines = []
    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if raw[:1] in (" ", "\t") and lines:
            lines[-1] += raw[1:]
        else:
            lines.append(raw)
    out, inside, depth = {"ATTENDEE": []}, False, 0
    for line in lines:
        head, _, value = line.partition(":")
        name = head.split(";")[0].upper()
        if name == "METHOD" and not inside:
            out["METHOD"] = value.strip().upper()
        elif name == "BEGIN" and value.upper() == "VEVENT" and "UID" not in out:
            inside = True
        elif name == "BEGIN" and inside:
            depth += 1                                             # an alarm inside the event: not ours to read
        elif name == "END" and inside and depth:
            depth -= 1
        elif name == "END" and value.upper() == "VEVENT":
            if inside:
                break
        elif inside and not depth:
            if name == "ATTENDEE":
                out["ATTENDEE"].append((head, value))
            elif name in ("UID", "SEQUENCE", "ORGANIZER", "DTSTART", "DTEND", "SUMMARY", "RECURRENCE-ID", "LOCATION") and name not in out:
                out[name] = (head, value)
    return out


def invite_of(data: bytes) -> dict:
    """What the reader shows about an invitation, or {} when the calendar file isn't one that wants an answer."""
    ev = ics_event(data[:500_000].decode("utf-8", "replace"))
    who = re.sub(r"(?i)^mailto:", "", ev.get("ORGANIZER", ("", ""))[1]).strip()
    unesc0 = lambda t: re.sub(r"\\([\\;,])", r"\1", t.replace("\\n", " ").replace("\\N", " ")).strip()     # noqa: E731
    if ev.get("METHOD") == "REPLY" and "UID" in ev and ev["ATTENDEE"]:
        head, value = ev["ATTENDEE"][0]
        state = next((p.split("=", 1)[1].upper() for p in head.split(";")[1:] if p.upper().startswith("PARTSTAT=")), "")
        said = {"ACCEPTED": "accepted", "DECLINED": "declined", "TENTATIVE": "may come to"}.get(state)
        if not said:
            return {}
        return {"title": unesc0(ev.get("SUMMARY", ("", "your invitation"))[1])[:200], "answer": said, "from": re.sub(r"(?i)^mailto:", "", value).strip()[:200], "when": "", "where": ""}
    if ev.get("METHOD") not in ("REQUEST", "CANCEL") or "UID" not in ev or "DTSTART" not in ev or not re.fullmatch(r"[^@\s]+@[^@\s]+", who):
        return {}
    m = re.fullmatch(r"(\d{4})(\d\d)(\d\d)(?:T(\d\d)(\d\d)\d*(Z)?)?", ev["DTSTART"][1].strip())
    when = ""
    if m:
        try:
            if m.group(4) is None:
                when = dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3))).strftime("%A %-d %B %Y")
            else:
                at = dt.datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4)), int(m.group(5)))
                zone = next((p.split("=", 1)[1].strip('"') for p in ev["DTSTART"][0].split(";")[1:] if p.upper().startswith("TZID=")), "")
                if m.group(6):
                    at = at.replace(tzinfo=dt.timezone.utc).astimezone()
                elif zone:
                    try:
                        from zoneinfo import ZoneInfo
                        at = at.replace(tzinfo=ZoneInfo(zone)).astimezone()
                    except Exception:
                        pass
                when = at.strftime("%A %-d %B %Y, %H:%M")
        except ValueError:
            when = ""
    unesc = lambda t: re.sub(r"\\([\\;,])", r"\1", t.replace("\\n", " ").replace("\\N", " ")).strip()      # noqa: E731
    out = {"title": unesc(ev.get("SUMMARY", ("", "Untitled"))[1])[:200] or "Untitled", "when": when, "from": who, "where": unesc(ev.get("LOCATION", ("", ""))[1])[:200]}
    if ev["METHOD"] == "CANCEL":
        out["cancelled"] = True
    return out


ANSWERS = {"accept": ("ACCEPTED", "Accepted", "accepted"), "maybe": ("TENTATIVE", "Maybe", "may come to"), "decline": ("DECLINED", "Declined", "declined")}


def invite_reply(cfg: dict, data: bytes, answer: str) -> EmailMessage:
    """The message that tells an organiser yes, maybe or no, in the form calendar programs understand (an iTIP reply)."""
    ev = ics_event(data[:500_000].decode("utf-8", "replace"))
    info = invite_of(data)
    if not info or info.get("answer") or info.get("cancelled") or answer not in ANSWERS:
        raise ValueError("This isn't an invitation that can be answered.")
    state, word, did = ANSWERS[answer]
    me = cfg["email"]
    mine = next((value for _head, value in ev["ATTENDEE"] if re.sub(r"(?i)^mailto:", "", value).strip().lower() == me.lower()), "mailto:" + me)
    name = re.sub(r'[";:,\r\n]', "", cfg.get("name") or "")
    lines = ["BEGIN:VCALENDAR", "PRODID:-//Huginn//Mail//EN", "VERSION:2.0", "METHOD:REPLY", "BEGIN:VEVENT", "UID:" + ev["UID"][1],
             "SEQUENCE:" + (ev.get("SEQUENCE", ("", "0"))[1].strip() or "0"), "DTSTAMP:" + dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
             ev["ORGANIZER"][0] + ":" + ev["ORGANIZER"][1], f"ATTENDEE;PARTSTAT={state}" + (f";CN={name}" if name else "") + ":" + mine]
    lines += [ev[k][0] + ":" + ev[k][1] for k in ("DTSTART", "DTEND", "RECURRENCE-ID", "SUMMARY") if k in ev]
    lines += ["END:VEVENT", "END:VCALENDAR"]
    body = f"{cfg.get('name') or me} {did} “{info['title']}”" + (f" ({info['when']})" if info["when"] else "") + "."
    return build_message(cfg, info["from"], "", f"{word}: {info['title']}", body, [], "", "", fold_lines(lines), "REPLY")


def fold_lines(lines: list) -> str:
    """Calendar text: no line longer than 75 bytes, as the format asks."""
    folded = []
    for line in lines:
        raw = line.encode("utf-8")
        while len(raw) > 73:
            cut = 73
            while cut and (raw[cut] & 0xC0) == 0x80:
                cut -= 1
            folded.append(raw[:cut].decode("utf-8"))
            raw = b" " + raw[cut:]
        folded.append(raw.decode("utf-8"))
    return "\r\n".join(folded) + "\r\n"


def clean_event(given) -> dict:
    """An event handed over by Calendar, checked: only the fields an invitation needs, in the shapes they must have."""
    if not isinstance(given, dict):
        return {}
    uid, title, date, at = (str(given.get(k, "")) for k in ("uid", "title", "date", "time"))
    if not re.fullmatch(r"[A-Za-z0-9@._-]{1,120}", uid) or not title.strip() or not re.fullmatch(r"\d{4}-\d\d-\d\d", date) or not re.fullmatch(r"(\d\d:\d\d)?", at):
        return {}
    try:
        dt.date.fromisoformat(date)
    except ValueError:
        return {}
    out, rule = {"uid": uid, "title": title.strip()[:200], "date": date, "time": at}, given.get("repeat")
    if isinstance(rule, dict) and rule.get("freq") in ("daily", "weekly", "monthly", "yearly"):
        keep = {"freq": rule["freq"], "interval": max(1, min(99, int(rule.get("interval") or 1))) if str(rule.get("interval") or 1).isdigit() else 1}
        if str(rule.get("count", "")).isdigit():
            keep["count"] = int(rule["count"])
        for key, ok in (("until", lambda v: isinstance(v, str) and re.fullmatch(r"\d{4}-\d\d-\d\d", v)),
                        ("days", lambda v: isinstance(v, list) and all(isinstance(d, int) and 0 <= d <= 6 for d in v)),
                        ("monthdays", lambda v: isinstance(v, list) and all(isinstance(d, int) and -31 <= d <= 31 and d for d in v)),
                        ("months", lambda v: isinstance(v, list) and all(isinstance(d, int) and 1 <= d <= 12 for d in v)),
                        ("nth", lambda v: isinstance(v, list) and all(isinstance(d, list) and len(d) == 2 and all(isinstance(x, int) for x in d) and -5 <= d[0] <= 5 and d[0] and 0 <= d[1] <= 6 for d in v)),
                        ("skip", lambda v: isinstance(v, list) and all(isinstance(d, str) and re.fullmatch(r"\d{4}-\d\d-\d\d", d) for d in v))):
            if rule.get(key) and ok(rule[key]):
                keep[key] = rule[key]
        out["repeat"] = keep
    return out


def invitation(cfg: dict, event: dict, guests: list) -> str:
    """The calendar text that makes a message an invitation (an iTIP request) from this account to these people."""
    esc = lambda t: re.sub(r"([\\;,])", r"\\\1", str(t)).replace("\n", "\\n").replace("\r", "")       # noqa: E731
    name = re.sub(r'[";:,\r\n]', "", cfg.get("name") or "")
    day = dt.date.fromisoformat(event["date"])
    lines = ["BEGIN:VCALENDAR", "PRODID:-//Huginn//Mail//EN", "VERSION:2.0", "METHOD:REQUEST", "BEGIN:VEVENT", "UID:" + event["uid"], "SEQUENCE:0",
             "DTSTAMP:" + dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ"), "ORGANIZER" + (f";CN={name}" if name else "") + ":mailto:" + cfg["email"]]
    lines += [f"ATTENDEE;ROLE=REQ-PARTICIPANT;PARTSTAT=NEEDS-ACTION;RSVP=TRUE:mailto:{g}" for g in guests]
    if event["time"]:
        start = dt.datetime.combine(day, dt.time(int(event["time"][:2]), int(event["time"][3:5]))).astimezone()
        utc = lambda t: t.astimezone(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")                                # noqa: E731
        lines += ["DTSTART:" + utc(start), "DTEND:" + utc(start + dt.timedelta(hours=1))]
    else:
        lines += ["DTSTART;VALUE=DATE:" + day.strftime("%Y%m%d"), "DTEND;VALUE=DATE:" + (day + dt.timedelta(days=1)).strftime("%Y%m%d")]
    lines.append("SUMMARY:" + esc(event["title"]))
    rule = event.get("repeat")
    if rule:
        names = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"]
        parts = ["FREQ=" + rule["freq"].upper()] + ([f"INTERVAL={rule['interval']}"] if rule.get("interval", 1) != 1 else [])
        if rule.get("count"):
            parts.append(f"COUNT={rule['count']}")
        elif rule.get("until"):
            parts.append("UNTIL=" + rule["until"].replace("-", "") + ("T235959Z" if event["time"] else ""))
        if rule.get("nth"):
            parts.append("BYDAY=" + ",".join(f"{n}{names[wd]}" for n, wd in rule["nth"]))
        elif rule.get("days"):
            parts.append("BYDAY=" + ",".join(names[d] for d in rule["days"]))
        if rule.get("monthdays"):
            parts.append("BYMONTHDAY=" + ",".join(str(d) for d in rule["monthdays"]))
        if rule.get("months"):
            parts.append("BYMONTH=" + ",".join(str(d) for d in rule["months"]))
        lines.append("RRULE:" + ";".join(parts))
        for skipped in rule.get("skip") or []:
            d = dt.date.fromisoformat(skipped)
            lines.append("EXDATE:" + utc(dt.datetime.combine(d, start.timetz()).astimezone()) if event["time"] else "EXDATE;VALUE=DATE:" + d.strftime("%Y%m%d"))
    lines += ["END:VEVENT", "END:VCALENDAR"]
    return fold_lines(lines)


def read_message(raw: bytes) -> dict:
    """A whole message → {text, was_html, attachments: [{name, size, kind, index}]}."""
    msg = email.message_from_bytes(raw, policy=email.policy.default)
    plain, rich, files = None, None, []
    for index, part in enumerate(msg.walk()):
        if part.is_multipart():
            continue
        kind, name = part.get_content_type(), part.get_filename()
        if name or part.get_content_disposition() == "attachment" or kind == "text/calendar":
            try:
                data = part.get_payload(decode=True) or b""
            except Exception:
                data = b""
            entry = {"name": header_text(name) or ("invitation.ics" if kind == "text/calendar" else "attachment"), "size": len(data), "kind": kind, "index": index}
            if kind in ("text/calendar", "application/ics") or str(name or "").lower().endswith(".ics"):
                invite = invite_of(data)
                if invite:
                    entry["invite"] = invite
            files.append(entry)
            continue
        if kind in ("text/plain", "text/html"):
            try:
                body = part.get_content()
            except Exception:
                body = (part.get_payload(decode=True) or b"").decode("utf-8", "replace")
            if kind == "text/plain" and plain is None:
                plain = body
            elif kind == "text/html" and rich is None:
                rich = body
    if plain is not None and plain.strip():
        return {"text": plain.replace("\r\n", "\n").rstrip(), "was_html": False, "attachments": files}
    if rich is not None:
        return {"text": html_to_text(rich), "was_html": True, "attachments": files}
    return {"text": "", "was_html": False, "attachments": files}


def when_text(stamp: float, now: float = None) -> str:
    now_dt, then = dt.datetime.fromtimestamp(now or time.time()), dt.datetime.fromtimestamp(stamp)
    if then.date() == now_dt.date():
        return then.strftime("%H:%M")
    if 0 < (now_dt.date() - then.date()).days < 7:
        return then.strftime("%a")
    return then.strftime("%-d %b" if os.name != "nt" else "%d %b") + ("" if then.year == now_dt.year else then.strftime(" %Y"))


def plain_error(err: Exception, what: str = "connect") -> str:
    """Whatever went wrong, in words someone can act on."""
    text = str(err)
    low = text.lower()
    if isinstance(err, ssl.SSLCertVerificationError) or "certificate" in low:
        return "The server's identity couldn't be checked, so Mail stopped rather than send your password. Check the server name."
    if isinstance(err, (imaplib.IMAP4.error, smtplib.SMTPAuthenticationError)) and any(w in low for w in ("auth", "login", "credential", "password", "535", "invalid")):
        return "The server didn't accept that name and password. Many providers need an app password instead of your usual one."
    if isinstance(err, socket.gaierror) or "name or service not known" in low or "nodename" in low or "temporary failure in name" in low:
        return "There is no server by that name, or this computer is offline."
    if isinstance(err, (socket.timeout, TimeoutError)) or "timed out" in low:
        return "The server didn't answer in time."
    if isinstance(err, ConnectionRefusedError) or "refused" in low:
        return "The server refused the connection. Check the server name and port."
    if isinstance(err, smtplib.SMTPRecipientsRefused):
        return "The server refused one of the addresses. Check them for typing mistakes."
    if isinstance(err, OSError) and ("unreachable" in low or "reset" in low or "eof" in low or "broken pipe" in low):
        return "The connection dropped. Check that you're online and try again."
    return f"Couldn't {what}: {text[:140]}"


# ---------------------------------------------------------------------------------------------- the cache
class Store:
    """What is kept on this computer for one account. Safe to use from the window's thread and the worker's."""

    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._db = sqlite3.connect(str(path), check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        with self._lock:
            self._db.executescript("""
                CREATE TABLE IF NOT EXISTS folders (name TEXT PRIMARY KEY, role TEXT, validity INTEGER DEFAULT 0, synced REAL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS messages (folder TEXT, uid INTEGER, msgid TEXT, refs TEXT, from_name TEXT, from_addr TEXT, rcpt TEXT, cc TEXT, subject TEXT,
                    stamp REAL, seen INTEGER, starred INTEGER, answered INTEGER, attach INTEGER, size INTEGER, snippet TEXT, body TEXT, was_html INTEGER,
                    files TEXT, PRIMARY KEY (folder, uid));
                CREATE INDEX IF NOT EXISTS by_time ON messages (folder, stamp DESC);""")
            self._db.commit()
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass

    def run(self, sql: str, args: tuple = ()) -> list:
        with self._lock:
            rows = self._db.execute(sql, args).fetchall()
            self._db.commit()
            return rows

    def many(self, sql: str, rows: list) -> None:
        with self._lock:
            self._db.executemany(sql, rows)
            self._db.commit()

    def close(self) -> None:
        with self._lock:
            self._db.close()


# ---------------------------------------------------------------------------------------------- the engine
class Engine:
    """One account's conversation with its servers. Every method blocks; Mail runs them on a worker thread."""
    HEADERS = "(UID FLAGS RFC822.SIZE BODY.PEEK[HEADER.FIELDS (FROM TO CC SUBJECT DATE MESSAGE-ID REFERENCES IN-REPLY-TO CONTENT-TYPE)])"

    def __init__(self, cfg: dict, secret, store: Store, context: ssl.SSLContext = None):
        """`secret()` gives {"password": ...} or, for a provider sign-in, {"access": a current token}."""
        self.cfg, self._secret, self.store = cfg, secret, store
        self._context = context or ssl.create_default_context()
        self._imap, self._selected, self.caps = None, "", set()

    # ---- connecting
    def _open(self):
        host, port = self.cfg["imap_host"], int(self.cfg["imap_port"])
        if port == 143:                                            # plain port: TLS must still start before anything is said
            conn = imaplib.IMAP4(host, port, timeout=25)
            conn.starttls(self._context)
        else:
            conn = imaplib.IMAP4_SSL(host, port, ssl_context=self._context, timeout=25)
        user, secret = self.cfg["user"], self._secret()
        if secret.get("access"):
            conn.authenticate("XOAUTH2", lambda _challenge: xoauth2(user, secret["access"]))
        else:
            password = secret.get("password", "")
            try:
                (user + password).encode("ascii")
                conn.login(user, password)
            except UnicodeEncodeError:
                conn.authenticate("PLAIN", lambda _challenge: b"\0" + user.encode("utf-8") + b"\0" + password.encode("utf-8"))
        self.caps = {c.upper() for c in conn.capabilities}
        return conn

    def imap(self):
        """The open connection, or a new one. A connection that has gone stale is noticed by the job runner, which
        drops it and runs the job once more."""
        if self._imap is None:
            self._imap, self._selected = self._open(), ""
        return self._imap

    def _drop(self) -> None:
        try:
            if self._imap is not None:
                self._imap.shutdown()
        except Exception:
            pass
        self._imap, self._selected = None, ""

    def close(self) -> None:
        try:
            if self._imap is not None:
                self._imap.logout()
        except Exception:
            pass
        self._imap = None

    def select(self, folder: str) -> int:
        """Open a mailbox; returns its UIDVALIDITY (a number that changes only if the server renumbered everything)."""
        conn = self.imap()
        if self._selected != folder:
            ok, data = conn.select(box(folder))
            if ok != "OK":
                self._selected = ""
                raise imaplib.IMAP4.error(f"The mailbox “{folder}” couldn't be opened.")
            self._selected = folder
        found = conn.response("UIDVALIDITY")[1]
        return int(found[0]) if found and found[0] else 0

    # ---- mailboxes
    def sync_folders(self) -> None:
        ok, lines = self.imap().list()
        seen = []
        for line in lines or []:
            if not isinstance(line, bytes):
                continue
            m = re.match(rb'\((?P<flags>[^)]*)\)\s+(?:"(?P<sep>[^"]*)"|NIL)\s+(?P<name>.+)$', line.strip())
            if not m:
                continue
            flags = m.group("flags").decode("ascii", "replace").lower()
            raw = m.group("name").decode("utf-8", "replace").strip()
            name = utf7_decode(raw[1:-1].replace('\\"', '"').replace("\\\\", "\\") if raw.startswith('"') else raw)
            if "\\noselect" in flags or "\\nonexistent" in flags:
                continue
            low = name.lower().rsplit("/", 1)[-1].rsplit(".", 1)[-1]
            role = ("inbox" if name.upper() == "INBOX" else "sent" if "\\sent" in flags else "trash" if "\\trash" in flags else "drafts" if "\\drafts" in flags
                    else "junk" if "\\junk" in flags else "archive" if "\\archive" in flags or "\\all" in flags else "starred_server" if "\\flagged" in flags
                    else "sent" if low in ("sent", "sent items", "sent mail", "sent messages") else "trash" if low in ("trash", "deleted items", "deleted messages", "bin")
                    else "drafts" if low in ("drafts", "draft") else "junk" if low in ("junk", "spam", "junk e-mail", "bulk mail") else "archive" if low in ("archive", "archives", "all mail") else "")
            if role == "starred_server":
                continue                                           # Gmail's "Starred" is the same messages again
            seen.append((name, role))
        taken = set()
        rows = []
        for name, role in seen:
            if role and role in taken:
                role = ""                                          # only one mailbox plays each part
            taken.add(role)
            rows.append((name, role))
        names = [n for n, _r in rows]
        for old in self.store.run("SELECT name FROM folders"):
            if old["name"] not in names:
                self.store.run("DELETE FROM folders WHERE name = ?", (old["name"],))
                self.store.run("DELETE FROM messages WHERE folder = ?", (old["name"],))
        for name, role in rows:
            self.store.run("INSERT INTO folders (name, role) VALUES (?, ?) ON CONFLICT(name) DO UPDATE SET role = excluded.role", (name, role))

    def folder_for(self, role: str) -> str:
        rows = self.store.run("SELECT name FROM folders WHERE role = ?", (role,))
        return rows[0]["name"] if rows else ""

    # ---- lists
    @staticmethod
    def _parse_fetch(data: list) -> list:
        """imaplib's FETCH reply → [(uid, flags, size, header bytes)]."""
        out = []
        for item in data or []:
            meta, payload = (item[0], item[1]) if isinstance(item, tuple) else (item, b"")
            if not isinstance(meta, bytes):
                continue
            uid = re.search(rb"UID (\d+)", meta)
            if not uid:
                continue
            flags = re.search(rb"FLAGS \(([^)]*)\)", meta)
            size = re.search(rb"RFC822\.SIZE (\d+)", meta)
            out.append((int(uid.group(1)), (flags.group(1).decode("ascii", "replace") if flags else ""), int(size.group(1)) if size else 0, payload or b""))
        return out

    def sync_folder(self, folder: str) -> int:
        """Bring one mailbox's list up to date. Returns how many messages are new since last time."""
        validity = self.select(folder)
        row = self.store.run("SELECT validity FROM folders WHERE name = ?", (folder,))
        if row and row[0]["validity"] and validity and row[0]["validity"] != validity:
            self.store.run("DELETE FROM messages WHERE folder = ?", (folder,))        # the server renumbered: start this mailbox again
        conn = self.imap()
        ok, data = conn.uid("SEARCH", None, "ALL")
        uids = sorted(int(u) for u in (data[0] or b"").split()) if ok == "OK" and data else []
        window = uids[-WINDOW:]
        have = {r["uid"] for r in self.store.run("SELECT uid FROM messages WHERE folder = ?", (folder,))}
        gone = [u for u in have if u not in set(window)]
        if gone:
            self.store.many("DELETE FROM messages WHERE folder = ? AND uid = ?", [(folder, u) for u in gone])
        fresh = [u for u in window if u not in have]
        for i in range(0, len(fresh), 80):
            chunk = fresh[i:i + 80]
            ok, data = conn.uid("FETCH", ",".join(map(str, chunk)), self.HEADERS)
            rows = []
            for uid, flags, size, raw in self._parse_fetch(data if ok == "OK" else []):
                head = email.message_from_bytes(raw, policy=email.policy.compat32)
                name, addr = email.utils.parseaddr(header_text(head.get("From")))
                try:
                    stamp = email.utils.parsedate_to_datetime(head.get("Date")).timestamp()
                except (TypeError, ValueError, OverflowError):
                    stamp = time.time()
                low = flags.lower()
                rows.append((folder, uid, (head.get("Message-ID") or "").strip(), " ".join((head.get("References") or "").split() + (head.get("In-Reply-To") or "").split()),
                             name or addr, addr, header_text(head.get("To")), header_text(head.get("Cc")), header_text(head.get("Subject")) or "(no subject)", stamp,
                             int("\\seen" in low), int("\\flagged" in low), int("\\answered" in low), int("multipart/mixed" in (head.get("Content-Type") or "").lower()), size))
            self.store.many("INSERT OR REPLACE INTO messages (folder, uid, msgid, refs, from_name, from_addr, rcpt, cc, subject, stamp, seen, starred, answered, attach, size)"
                            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
        old = [u for u in window if u in have]
        if old:                                                    # what changed elsewhere: read on a phone, starred in a browser
            ok, data = conn.uid("FETCH", f"{old[0]}:{old[-1]}", "(UID FLAGS)")
            self.store.many("UPDATE messages SET seen = ?, starred = ?, answered = ? WHERE folder = ? AND uid = ?",
                            [(int("\\seen" in f.lower()), int("\\flagged" in f.lower()), int("\\answered" in f.lower()), folder, uid)
                             for uid, f, _s, _r in self._parse_fetch(data if ok == "OK" else []) if uid in have])
        self.store.run("UPDATE folders SET validity = ?, synced = ? WHERE name = ?", (validity, time.time(), folder))
        return len(fresh)

    # ---- one message
    def fetch_body(self, folder: str, uid: int) -> bool:
        self.select(folder)
        ok, data = self.imap().uid("FETCH", str(uid), "(BODY.PEEK[])")
        raw = next((item[1] for item in data or [] if isinstance(item, tuple) and item[1]), None) if ok == "OK" else None
        if raw is None:
            return False
        parsed = read_message(raw)
        snippet = " ".join(l.strip() for l in parsed["text"].splitlines() if l.strip() and not l.lstrip().startswith(">"))[:160]
        self.store.run("UPDATE messages SET body = ?, was_html = ?, files = ?, snippet = ?, attach = ? WHERE folder = ? AND uid = ?",
                       (parsed["text"], int(parsed["was_html"]), json.dumps(parsed["attachments"]), snippet, int(bool(parsed["attachments"])), folder, uid))
        return True

    def attachment(self, folder: str, uid: int, index: int) -> tuple:
        """One attachment's (name, bytes), fetched afresh so big files are never kept in the cache."""
        self.select(folder)
        ok, data = self.imap().uid("FETCH", str(uid), "(BODY.PEEK[])")
        raw = next((item[1] for item in data or [] if isinstance(item, tuple) and item[1]), None)
        if raw is None:
            raise OSError("The message is no longer on the server.")
        msg = email.message_from_bytes(raw, policy=email.policy.default)
        for i, part in enumerate(msg.walk()):
            if i == index and not part.is_multipart():
                return header_text(part.get_filename()) or "attachment", part.get_payload(decode=True) or b""
        raise OSError("That attachment couldn't be found in the message.")

    def set_flag(self, folder: str, uid: int, flag: str, on: bool) -> None:
        self.select(folder)
        self.imap().uid("STORE", str(uid), "+FLAGS.SILENT" if on else "-FLAGS.SILENT", f"({flag})")

    def move(self, folder: str, uid: int, dest: str) -> None:
        self.select(folder)
        conn = self.imap()
        if "MOVE" in self.caps:
            ok, data = conn.uid("MOVE", str(uid), box(dest))
            if ok != "OK":
                raise imaplib.IMAP4.error(f"The server wouldn't move it to “{dest}”.")
        else:
            ok, data = conn.uid("COPY", str(uid), box(dest))
            if ok != "OK":
                raise imaplib.IMAP4.error(f"The server wouldn't move it to “{dest}”.")
            conn.uid("STORE", str(uid), "+FLAGS.SILENT", "(\\Deleted)")
            if "UIDPLUS" in self.caps:
                conn.uid("EXPUNGE", str(uid))
            else:
                conn.expunge()
        self.store.run("DELETE FROM messages WHERE folder = ? AND uid = ?", (folder, uid))

    def delete_for_good(self, folder: str, uid: int) -> None:
        self.select(folder)
        conn = self.imap()
        conn.uid("STORE", str(uid), "+FLAGS.SILENT", "(\\Deleted)")
        if "UIDPLUS" in self.caps:
            conn.uid("EXPUNGE", str(uid))
        else:
            conn.expunge()
        self.store.run("DELETE FROM messages WHERE folder = ? AND uid = ?", (folder, uid))

    # ---- sending
    def send(self, msg: EmailMessage) -> None:
        host, port = self.cfg["smtp_host"], int(self.cfg["smtp_port"])
        if port in (587, 25, 2525):                                # the ports where TLS starts after hello
            server = smtplib.SMTP(host, port, timeout=30)
            server.starttls(context=self._context)                 # no TLS, no sending: this raises if the server can't
        else:
            server = smtplib.SMTP_SSL(host, port, context=self._context, timeout=30)
        began, hand_over = [], server.data

        def data(body):                                            # from here on, a dropped line leaves it unknowable
            began.append(1)
            return hand_over(body)
        server.data = data
        try:
            smtp_login(server, self.cfg["user"], self._secret())
            server.send_message(msg)
        except (OSError, EOFError) as err:
            if began and can_wait(err):
                raise MaybeSent() from err
            raise
        finally:
            try:
                server.quit()
            except (smtplib.SMTPException, OSError):
                pass
        sent = self.folder_for("sent")
        if sent and "gmail" not in host:                           # Gmail files its own copy
            try:
                self.imap().append(box(sent), "(\\Seen)", imaplib.Time2Internaldate(time.time()), msg.as_bytes())
            except (imaplib.IMAP4.error, OSError):
                pass                                               # it was sent; only the copy is missing


def smtp_login(server, user: str, secret) -> None:
    """Sign in for sending, with a password or a provider token. Python's own login can't carry accented letters,
    so those go as AUTH PLAIN by hand."""
    if isinstance(secret, dict) and secret.get("access"):
        server.ehlo_or_helo_if_needed()
        code, reply = server.docmd("AUTH", "XOAUTH2 " + base64.b64encode(xoauth2(user, secret["access"])).decode("ascii"))
        if code == 334:                                            # the server's reason, base64; an empty line ends it
            code, reply = server.docmd("")
        if code != 235:
            raise smtplib.SMTPAuthenticationError(code, reply)
        return
    password = secret.get("password", "") if isinstance(secret, dict) else str(secret)
    try:
        (user + password).encode("ascii")
        server.login(user, password)
        return
    except UnicodeEncodeError:
        pass
    server.ehlo_or_helo_if_needed()
    blob = base64.b64encode(b"\0" + user.encode("utf-8") + b"\0" + password.encode("utf-8")).decode("ascii")
    code, reply = server.docmd("AUTH", "PLAIN " + blob)
    if code != 235:
        raise smtplib.SMTPAuthenticationError(code, reply)


def build_message(cfg: dict, to: str, cc: str, subject: str, body: str, files: list, reply_to_id: str = "", refs: str = "", calendar: str = "", method: str = "REQUEST") -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = email.utils.formataddr((cfg.get("name", ""), cfg["email"]))
    msg["To"] = ", ".join(a.strip() for a in re.split(r"[;,]", to) if a.strip())
    if cc.strip():
        msg["Cc"] = ", ".join(a.strip() for a in re.split(r"[;,]", cc) if a.strip())
    msg["Subject"] = subject.strip()
    msg["Date"] = email.utils.formatdate(localtime=True)
    msg["Message-ID"] = email.utils.make_msgid(domain=cfg["email"].rsplit("@", 1)[-1])
    if reply_to_id:
        msg["In-Reply-To"] = reply_to_id
        msg["References"] = (refs + " " + reply_to_id).strip()
    msg.set_content(body.replace("\r\n", "\n") + ("\n" if not body.endswith("\n") else ""))
    if calendar:                                                   # beside the words, the same thing for calendar programs
        msg.add_alternative(calendar, subtype="calendar", params={"method": method})
    import mimetypes
    for path in files:
        data = Path(path).read_bytes()
        kind = mimetypes.guess_type(path)[0] or "application/octet-stream"
        main, _, sub = kind.partition("/")
        msg.add_attachment(data, maintype=main, subtype=sub or "octet-stream", filename=Path(path).name)
    return msg


# ------------------------------------------------------------------------------------------------- the app
class _Line:
    """One account at work: its cache, its engine, and a thread that does one job at a time in order."""

    def __init__(self, cfg: dict, context, deliver, secret):
        self.cfg, self.context, self.deliver, self.secret = cfg, context, deliver, secret
        self.store = Store(MAIL_HOME / f"{cfg['id']}.db")
        self.engine, self.jobs, self.alive = None, queue.Queue(), True
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _run(self) -> None:
        while self.alive:
            job = self.jobs.get()
            if job is None:
                break
            work, then, fail = job
            try:
                if self.engine is None:
                    self.engine = Engine(self.cfg, self.secret, self.store, self.context)
                try:
                    result = work(self.engine)
                except (imaplib.IMAP4.abort, ConnectionError, ssl.SSLError, EOFError, TimeoutError):
                    self.engine._drop()                            # the server hung up while Mail sat idle: connect again, once
                    result = work(self.engine)
                if then:
                    self.deliver(lambda r=result: then(r))
            except Exception as err:                               # every failure ends as words on the screen, never a dead thread
                if self.engine is not None:
                    self.engine._drop()
                if isinstance(err, PermissionError):
                    why = LOCKED if str(err) == "locked" else "Mail has no password for this account any more. Open Accounts and sign in again."
                elif isinstance(err, MaybeSent):
                    why = "The connection dropped just as the message was going out, so Mail can't tell whether it arrived. Look in Sent, or ask, before sending it again."
                elif isinstance(err, SignInError):
                    why = "This account was signed out by its provider. Open Accounts and sign in again." if str(err) == "signed-out" else str(err)
                elif self.cfg.get("oauth") and isinstance(err, (imaplib.IMAP4.error, smtplib.SMTPAuthenticationError)) and "AUTH" in str(err).upper():
                    why = "The provider didn't accept this account's sign-in. Open Accounts and sign in again."
                else:
                    why = plain_error(err, "reach the mail server")
                if fail:
                    self.deliver(lambda w=why: fail(w))
            finally:
                self.jobs.task_done()

    def post(self, work, then=None, fail=None) -> None:
        self.jobs.put((work, then, fail))

    def hang_up(self) -> None:
        """Forget the connection (the vault was locked, or the sign-in changed); the next job starts a fresh one."""
        def work(engine):
            engine._drop()
        self.post(work)

    def stop(self) -> None:
        self.alive = False
        self.jobs.put(None)
        if self.engine is not None:
            self.engine.close()


def thread_key(r) -> str:
    """What ties a message to its conversation: the first message it answers, else itself, else its subject."""
    refs = (r["refs"] or "").split()
    if refs:
        return refs[0]
    if r["msgid"]:
        return r["msgid"]
    return "s:" + re.sub(r"(?i)^((re|fwd?|aw|sv)\s*:\s*)+", "", r["subject"] or "").strip().lower()


def can_wait(err: Exception) -> bool:
    """Is this a failure of the connection (so the message can wait in the Outbox), not a refusal?"""
    if isinstance(err, (ssl.SSLError, imaplib.IMAP4.error, SignInError, PermissionError)):
        return False
    if isinstance(err, smtplib.SMTPException):
        return isinstance(err, (smtplib.SMTPServerDisconnected, smtplib.SMTPConnectError))
    return isinstance(err, (OSError, EOFError))


LOCKED = "Passwords is locked, so Mail can't check for new mail. Unlock to carry on."


class Mail(QObject):
    changed = Signal()
    failed = Signal(str)
    said = Signal(str)
    signedIn = Signal(bool, str)                                   # how adding an account went
    wasSent = Signal(bool, str)                                    # how sending went
    asked = Signal("QVariantMap")                                  # another app handed Mail a message to write
    _call = Signal(object)

    def __init__(self, demo: bool = False, context: ssl.SSLContext = None, start_to: str = "", open_url=None):
        super().__init__()
        self._demo, self._context = demo, context
        self._open_url = open_url or (lambda url: QDesktopServices.openUrl(QUrl(url)))
        self._secrets, self._tokens, self._guard = {}, {}, threading.Lock()
        self._vault = self._session = None
        self._misses, self._wait_until, self._stop_sign_in, self._waiting = 0, 0.0, False, ""
        self._sending, self._prefs = set(), {}
        if not demo:
            try:
                self._prefs = json.loads((MAIL_HOME / "prefs.json").read_text(encoding="utf-8"))
            except (OSError, ValueError):
                self._prefs = {}
        if not isinstance(self._prefs, dict):
            self._prefs = {}
        self._grouped = bool(self._prefs.get("grouped", True))
        self._start = read_mailto(start_to)
        self._start_to = self._start.get("to", "")
        self._lines, self._accounts = {}, []
        self._acct, self._folder, self._open, self._query = "", "", "", ""
        self._busy, self._offline, self._adding = 0, "", False
        self._call.connect(lambda fn: fn())
        if demo:
            self._demo_rows = _demo_messages()
            self._accounts = [{"id": "demo", "name": "Val", "email": "val@example.com"}]
            self._acct, self._folder, self._open = "demo", "INBOX", "1:INBOX"
            return
        try:
            self._accounts = [a for a in json.loads((MAIL_HOME / "accounts.json").read_text(encoding="utf-8")) if isinstance(a, dict) and a.get("id")]
        except (OSError, ValueError):
            self._accounts = []
        import huginn_vault as hv
        self._hv, self._vault = hv, hv.VaultFile()
        self._session = hv.Session(self._vault)
        for cfg in self._accounts:
            self._lines[cfg["id"]] = _Line(cfg, context, self._call.emit, lambda i=cfg["id"]: self._secret_for(i))
        if self._accounts:
            self._acct = self._accounts[0]["id"]
            self._folder = "INBOX"
        if self._session.try_unlock():
            self._take_secrets()
        if self._accounts:
            QTimer.singleShot(0, self.refresh)
        self._badge_shown = None
        self._badge_soon = QTimer(self)
        self._badge_soon.setSingleShot(True)
        self._badge_soon.setInterval(700)
        self._badge_soon.timeout.connect(self._badge)
        self.changed.connect(self._badge_soon.start)
        self._step = QTimer(self)
        self._step.setInterval(2000)
        self._step.timeout.connect(self.inStep)
        self._step.start()
        self._tick = QTimer(self)
        self._tick.setInterval(3 * 60 * 1000)
        self._tick.timeout.connect(self._check_all)
        self._tick.start()
        self._listed = self._list_stamp()
        self._absorb = QTimer(self)                                # Settings › Online Accounts may add or take away an account
        self._absorb.setInterval(4000)
        self._absorb.timeout.connect(self._absorb_accounts)
        self._absorb.start()

    @staticmethod
    def _list_stamp():
        try:
            st = (MAIL_HOME / "accounts.json").stat()
            return st.st_mtime_ns, st.st_size
        except OSError:
            return None

    def _absorb_accounts(self) -> None:
        """Take in accounts Online Accounts added (and let go of ones it took away) without a restart."""
        stamp = self._list_stamp()
        if stamp == self._listed:
            return
        self._listed = stamp
        try:
            disk = [a for a in json.loads((MAIL_HOME / "accounts.json").read_text(encoding="utf-8")) if isinstance(a, dict) and a.get("id")]
        except (OSError, ValueError):
            return
        ids = {a["id"] for a in disk}
        new = [a for a in disk if a["id"] not in self._lines]
        gone = [a["id"] for a in self._accounts if a.get("from") == "accounts" and a["id"] not in ids]
        for cfg in new:
            self._accounts.append(cfg)
            self._lines[cfg["id"]] = _Line(cfg, self._context, self._call.emit, lambda i=cfg["id"]: self._secret_for(i))
        for ident in gone:
            self.removeAccount(ident)
        if new:
            try:
                self._vault.refresh()
            except (self._hv.VaultError, OSError):
                pass
            if not self._vault.locked():
                self._take_secrets()
            if not self._acct:
                self._acct, self._folder = new[0]["id"], "INBOX"
            self.changed.emit()
            self.refresh()

    # ------------------------------------------------------------------ the vault: where every account's secret lives
    def _secret_for(self, ident: str) -> dict:
        """What an account signs in with, right now. Called from the account's own thread."""
        with self._guard:
            if self._vault is None or self._vault.locked():
                raise PermissionError("locked")
            secret, tokens = self._secrets.get(ident), self._tokens.get(ident)
        if tokens is not None:
            return {"access": tokens.access()}
        if not secret or not secret.get("password"):
            raise PermissionError("none")
        return {"password": secret["password"]}

    def _take_secrets(self) -> None:
        """The vault has just been unlocked: read this app's drawer, and bring across anything an older Mail kept."""
        old = MAIL_HOME / "keys.json"
        if old.exists():
            try:
                for ident, packed in json.loads(old.read_text(encoding="utf-8")).items():
                    if any(a["id"] == ident for a in self._accounts) and not self._vault.secret("mail", ident):
                        self._vault.set_secret("mail", ident, {"kind": "password", "password": base64.b64decode(packed).decode("utf-8"),
                                                               "email": next(a["email"] for a in self._accounts if a["id"] == ident)})
                old.unlink()
            except (OSError, ValueError, self._hv.VaultError):
                pass
        try:                                                       # an account removed while locked left its secret behind
            for ident in [i for i in (self._vault.extras.get("mail") or {}) if not any(a["id"] == i for a in self._accounts)]:
                self._vault.set_secret("mail", ident, None)
        except (self._hv.VaultError, OSError):
            pass
        with self._guard:
            self._secrets = {a["id"]: dict(self._vault.secret("mail", a["id"]) or {}) for a in self._accounts}
            self._tokens = {i: Tokens(x["provider"], x, lambda new, i=i: self._call.emit(lambda: self._rotated(i, new)))
                            for i, x in self._secrets.items() if x.get("kind") == "oauth" and x.get("refresh")}
        if self._offline == LOCKED:
            self._offline = ""

    def _rotated(self, ident: str, refresh: str) -> None:
        """The provider swapped the long-lived token for a new one: the vault has to hold the newest."""
        secret = self._secrets.get(ident)
        if secret and not self._vault.locked():
            secret["refresh"] = refresh
            try:
                self._vault.set_secret("mail", ident, {k: v for k, v in secret.items() if k not in ("access", "expires")})
            except (self._hv.VaultError, OSError) as err:
                self.failed.emit(f"Couldn't save the renewed sign-in: {getattr(err, 'strerror', None) or err}")

    def _forget(self) -> None:
        with self._guard:
            self._vault.lock()
            self._secrets, self._tokens = {}, {}
        self._session.gen = None
        for line in self._lines.values():
            line.hang_up()

    def _old_vault(self) -> bool:
        return (DATA_HOME / "passwords.vault").exists() and not self._vault.exists()

    vaultExists = Property(bool, lambda self: self._demo or self._vault.exists(), notify=changed)
    vaultLocked = Property(bool, lambda self: not self._demo and self._vault.locked(), notify=changed)
    vaultOld = Property(bool, lambda self: not self._demo and self._old_vault(), notify=changed)     # made by the first Passwords app: it moves it across
    waiting = Property(str, lambda self: self._waiting, notify=changed)                               # "Google": the browser is showing its sign-in page

    @Slot()
    def inStep(self) -> None:
        """Every couple of seconds: unlock if Passwords or the browser did; lock if someone pressed Lock there.
        The session merely going quiet doesn't stop Mail checking for mail."""
        if self._demo:
            return
        if self._vault.locked():
            if self._session.try_unlock():
                self._take_secrets()
                self.changed.emit()
                self.refresh()
            return
        if self._session.gen is None and self._hv.sharing_on():
            self._session.unlocked()                               # unlocked here while nothing else was open: let the others in
        elif self._session.locked_elsewhere(by_hand_only=True):
            self._session.gen = None
            if not self._session.try_unlock():                     # locked by hand (not simply unlocked again by someone else)
                self._forget()
                self._offline = LOCKED
            self.changed.emit()

    @Slot(str, result=str)
    def unlockVault(self, master: str) -> str:
        wait = self._wait_until - time.monotonic()
        if wait > 0:
            return f"Too many tries. Wait {int(wait) + 1} seconds."
        try:
            self._vault.unlock(master)
        except self._hv.WrongPassword:
            self._misses += 1
            if self._misses >= 3:
                self._wait_until = time.monotonic() + min(300, 2 ** self._misses)
            return "That isn't the master password."
        except (self._hv.VaultError, OSError) as err:
            return f"Couldn't open the vault: {getattr(err, 'strerror', None) or err}"
        self._misses = 0
        self._session.unlocked()
        self._take_secrets()
        self.changed.emit()
        self.refresh()
        return ""

    @Slot(str, str, result=str)
    def createVault(self, master: str, again: str) -> str:
        """No vault yet (Passwords and the browser have never been set up): make it here."""
        if self._vault.exists() or self._old_vault():
            return "There is already a vault. Open Passwords to unlock it."
        if master != again:
            return "The two don't match."
        if len(master) < 10:
            return "Use at least 10 characters. A few unrelated words work well."
        try:
            self._vault.create(master)
        except (self._hv.VaultError, OSError) as err:
            return f"Couldn't create the vault: {getattr(err, 'strerror', None) or err}"
        self._session.unlocked()
        self._take_secrets()
        self.changed.emit()
        return ""

    def _badge(self, gone: bool = False) -> None:
        """Tell the dock how many unread messages the inboxes hold (a tiny file in the login's runtime folder)."""
        base = os.environ.get("XDG_RUNTIME_DIR")
        if self._demo or not base:
            return
        try:
            n = 0 if gone else sum(line.store.run("SELECT COUNT(*) AS n FROM messages WHERE folder = 'INBOX' AND seen = 0")[0]["n"] for line in self._lines.values())
        except (sqlite3.Error, IndexError):
            return
        if n == self._badge_shown:
            return
        self._badge_shown = n
        try:
            folder = Path(base) / "huginn" / "badges"
            folder.mkdir(parents=True, exist_ok=True)
            if n:
                part = folder / ".mail.part"
                part.write_text(str(n), encoding="ascii")
                os.replace(part, folder / "mail")
            else:
                (folder / "mail").unlink(missing_ok=True)
        except OSError:
            pass

    # ------------------------------------------------------------------ plumbing
    def _line(self) -> "_Line":
        return self._lines.get(self._acct)

    def _cfg(self) -> dict:
        return next((a for a in self._accounts if a["id"] == self._acct), {})

    def _save_accounts(self) -> None:
        MAIL_HOME.mkdir(parents=True, exist_ok=True)
        part = MAIL_HOME / ".accounts.json.saving"
        part.write_text(json.dumps(self._accounts), encoding="utf-8")
        os.replace(part, MAIL_HOME / "accounts.json")
        self._listed = self._list_stamp()

    def _job(self, work, then=None, quiet: bool = False, line: "_Line" = None) -> None:
        line = line or self._line()
        if line is None:
            return
        if not self._demo and self._vault.locked():                # what's already on this computer stays readable
            if self._offline != LOCKED:
                self._offline = LOCKED
                self.changed.emit()
            return
        self._busy += 1
        self.changed.emit()

        def ok(result):
            self._busy -= 1
            self._offline = ""
            if then:
                then(result)
            self.changed.emit()

        def bad(why):
            self._busy -= 1
            self._offline = why
            if not quiet:
                self.failed.emit(why)
            self.changed.emit()
        line.post(work, ok, bad)

    def settle(self) -> None:
        """For tests: wait until every queued job has finished and its result has been delivered."""
        from PySide6.QtCore import QCoreApplication
        for _ in range(200):
            for line in list(self._lines.values()):
                line.jobs.join()
            QCoreApplication.processEvents()
            if self._busy <= 0:
                QCoreApplication.processEvents()
                return
            time.sleep(0.01)

    @staticmethod
    def _split(ident: str) -> tuple:
        uid, _, folder = ident.partition(":")
        return folder, int(uid) if uid.isdigit() else 0

    # ------------------------------------------------------------------ what the screen shows
    startTo = Property(str, lambda self: self._start_to, constant=True)        # opened from an email link: who to write to
    startDraft = Property("QVariantMap", lambda self: self._start, constant=True)   # ...and the rest of what the link said

    def listen(self, show: bool = True) -> bool:
        """Be the one Mail that's running: a second start hands its email link over and leaves. False = hand-over done."""
        from PySide6.QtNetwork import QLocalServer, QLocalSocket
        name = f"huginn-mail-{os.getuid()}"
        probe = QLocalSocket()
        probe.connectToServer(name)
        if probe.waitForConnected(300):
            if not show:                                           # a background start finding Mail already there has nothing to say
                probe.disconnectFromServer()
                return False
            probe.write(json.dumps(self._start).encode("utf-8"))
            probe.waitForBytesWritten(1000)
            probe.disconnectFromServer()
            return False
        QLocalServer.removeServer(name)                            # a Mail that crashed leaves its door behind
        self._door = QLocalServer(self)
        self._door.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        self._door.listen(name)

        def came():
            conn = self._door.nextPendingConnection()

            def said():
                try:
                    draft = json.loads(bytes(conn.readAll()).decode("utf-8"))
                except ValueError:
                    return
                if isinstance(draft, dict):                        # only ever a draft to look at: nothing is sent by a hand-over
                    self.asked.emit(read_mailto("", draft))
            conn.readyRead.connect(said)
        self._door.newConnection.connect(came)
        return True

    @Slot(str, str)
    def openAttachment(self, ident: str, index_and_app: str) -> None:
        """Hand a contact card or a calendar file in a message to Contacts or Calendar."""
        index, _, app = index_and_app.partition(":")
        folder, uid = self._split(ident)
        if self._demo or app not in ("contacts", "calendar"):
            return
        cache = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "huginn" / "mail-handover"

        def work(engine):
            name, data = engine.attachment(folder, uid, int(index))
            cache.mkdir(parents=True, exist_ok=True)
            for old in cache.iterdir():
                old.unlink(missing_ok=True)
            target = cache / ("card.vcf" if app == "contacts" else "event.ics")
            target.write_bytes(data[:2_000_000])
            return target
        self._job(work, lambda target: subprocess.Popen([sys.executable, str(Path(__file__).with_name("huginn_app.py")), app, str(target)], start_new_session=True,
                                                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))

    @Slot(str)
    def remind(self, ident: str) -> None:
        """Put this message on today's list in Reminders."""
        r = self._full(ident) if not self._demo else None
        if not r:
            return
        import huginn_reminders
        huginn_reminders.add_reminder(r["subject"] or "A message", dt.date.today().isoformat(), "", f"Mail from {r['from_name'] or r['from_addr']}.")
        self.said.emit("Added to Reminders, for today.")

    @Slot(str)
    def addSender(self, ident: str) -> None:
        """Put whoever wrote this message into Contacts (Contacts opens and shows the card)."""
        r = self._full(ident) if not self._demo else None
        if not r or not r["from_addr"]:
            return
        cache = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "huginn" / "mail-handover"
        cache.mkdir(parents=True, exist_ok=True)
        esc = lambda t: re.sub(r"([\\;,])", r"\\\1", str(t)).replace("\n", " ").replace("\r", " ")      # noqa: E731
        name = r["from_name"] or r["from_addr"].split("@")[0]
        (cache / "card.vcf").write_text(f"BEGIN:VCARD\r\nVERSION:3.0\r\nFN:{esc(name)}\r\nEMAIL;TYPE=INTERNET:{esc(r['from_addr'])}\r\nEND:VCARD\r\n", encoding="utf-8")
        subprocess.Popen([sys.executable, str(Path(__file__).with_name("huginn_app.py")), "contacts", str(cache / "card.vcf")], start_new_session=True,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    hasAccount = Property(bool, lambda self: bool(self._accounts), notify=changed)
    accounts = Property("QVariantList", lambda self: [{"id": a["id"], "name": a.get("name", ""), "email": a["email"], "window": OAUTH.get(a.get("oauth"), {}).get("name", "")}
                                                      for a in self._accounts], notify=changed)
    account = Property(str, lambda self: self._acct, notify=changed)
    folder = Property(str, lambda self: self._folder, notify=changed)
    openId = Property(str, lambda self: self._open, notify=changed)
    syncing = Property(bool, lambda self: self._busy > 0, notify=changed)
    offline = Property(str, lambda self: self._offline, notify=changed)
    query = Property(str, lambda self: self._query, notify=changed)

    @staticmethod
    def _label(name: str, role: str) -> str:
        return {"inbox": "Inbox", "sent": "Sent", "trash": "Trash", "drafts": "Drafts", "junk": "Junk", "archive": "Archive"}.get(role) or name.rsplit("/", 1)[-1].rsplit(".", 1)[-1]

    @Property("QVariantList", notify=changed)
    def folders(self):
        if self._demo:
            rows = [("INBOX", "inbox"), ("Sent", "sent"), ("Trash", "trash")]
            count = lambda name: sum(1 for m in self._demo_rows if m["folder"] == name and not m["seen"])
            out = [{"name": n, "label": self._label(n, r), "icon": ROLE_ICONS[r], "role": r, "unread": count(n)} for n, r in rows]
            return out[:1] + [{"name": "*starred", "label": "Starred", "icon": "star", "role": "starred", "unread": 0}] + out[1:]
        line = self._line()
        if line is None:
            return []
        rows = line.store.run("SELECT f.name, f.role, (SELECT COUNT(*) FROM messages m WHERE m.folder = f.name AND m.seen = 0) AS unread FROM folders f")
        out = [{"name": r["name"], "label": self._label(r["name"], r["role"] or ""), "icon": ROLE_ICONS.get(r["role"] or "", "folder"), "role": r["role"] or "",
                "unread": r["unread"] if (r["role"] or "") not in ("sent", "trash", "drafts", "junk") else 0} for r in rows]
        if out:
            out.append({"name": "*starred", "label": "Starred", "icon": "star", "role": "starred", "unread": 0})
        return sorted(out, key=lambda f: (ROLE_ORDER.index(f["role"]) if f["role"] in ROLE_ORDER else 9, f["label"].lower()))

    def _row(self, r) -> dict:
        return {"id": f"{r['uid']}:{r['folder']}", "from": r["from_name"] or r["from_addr"] or "", "addr": r["from_addr"] or "", "to": r["rcpt"] or "",
                "subject": r["subject"] or "(no subject)", "time": when_text(r["stamp"]), "unread": not r["seen"], "starred": bool(r["starred"]),
                "attach": bool(r["attach"]), "answered": bool(r["answered"]), "snippet": r["snippet"] or ""}

    @Property("QVariantList", notify=changed)
    def messages(self):
        q = self._query.strip().lower()
        if self._demo:
            rows = [m for m in self._demo_rows if (m["starred"] if self._folder == "*starred" else m["folder"] == self._folder)]
            rows = [m for m in rows if not q or q in (m["subject"] + m["from_name"] + m["body"]).lower()]
            return [self._row(m) for m in sorted(rows, key=lambda m: -m["stamp"])]
        line = self._line()
        if line is None:
            return []
        where, args = ("starred = 1", ()) if self._folder == "*starred" else ("folder = ?", (self._folder,))
        if q:
            where += " AND (lower(subject) LIKE ? OR lower(from_name) LIKE ? OR lower(from_addr) LIKE ? OR lower(coalesce(body, '')) LIKE ?)"
            args += (f"%{q}%",) * 4
        rows = line.store.run(f"SELECT * FROM messages WHERE {where} ORDER BY stamp DESC LIMIT {WINDOW}", args)
        if not self._grouped:
            return [dict(self._row(r), count=1) for r in rows]
        out, at = [], {}
        for r in rows:                                             # newest first: the first of a conversation stands for it
            key = thread_key(r)
            if key in at:
                top = out[at[key]]
                top["count"] += 1
                top["unread"] = top["unread"] or not r["seen"]
                top["attach"] = top["attach"] or bool(r["attach"])
                top["starred"] = top["starred"] or bool(r["starred"])
            else:
                at[key] = len(out)
                out.append(dict(self._row(r), count=1))
        return out

    @Property("QVariantList", notify=changed)
    def conversation(self):
        """The other messages in the open one's conversation (in this mailbox), oldest first. Empty when it stands alone."""
        line = self._line()
        if self._demo or line is None or not self._open or not self._grouped:
            return []
        folder, uid = self._split(self._open)
        here = line.store.run("SELECT * FROM messages WHERE folder = ? AND uid = ?", (folder, uid))
        if not here:
            return []
        key = thread_key(here[0])
        rows = [r for r in line.store.run(f"SELECT * FROM messages WHERE folder = ? ORDER BY stamp DESC LIMIT {WINDOW}", (folder,)) if thread_key(r) == key]
        return [dict(self._row(r), open=r["uid"] == uid) for r in reversed(rows)] if len(rows) > 1 else []

    grouped = Property(bool, lambda self: self._grouped, notify=changed)
    stayOn = Property(bool, lambda self: bool(self._prefs.get("stay_on", True)), notify=changed)     # closing the window leaves Mail checking

    @Slot(bool)
    def setStayOn(self, on: bool) -> None:
        self._prefs["stay_on"] = bool(on)
        self._save_prefs()
        self.changed.emit()

    @Slot(bool)
    def setGrouped(self, on: bool) -> None:
        self._grouped = bool(on)
        self._prefs["grouped"] = self._grouped
        self._save_prefs()
        self.changed.emit()

    def _save_prefs(self) -> None:
        if self._demo:
            return
        try:
            MAIL_HOME.mkdir(parents=True, exist_ok=True)
            (MAIL_HOME / "prefs.json").write_text(json.dumps(self._prefs), encoding="utf-8")
        except OSError:
            pass

    # ------------------------------------------------------------------ signatures
    signature = Property(str, lambda self: self._cfg().get("signature", ""), notify=changed)
    signatureBlock = Property(str, lambda self: ("\n\n-- \n" + self._cfg()["signature"]) if self._cfg().get("signature", "").strip() else "", notify=changed)

    @Slot(str, str)
    def setSignature(self, ident: str, text: str) -> None:
        for a in self._accounts:
            if a["id"] == ident:
                a["signature"] = text.strip()[:2000]
        if not self._demo:
            self._save_accounts()
        self.changed.emit()

    @Slot(str, result=str)
    def signatureOf(self, ident: str) -> str:
        return next((a.get("signature", "") for a in self._accounts if a["id"] == ident), "")

    # ------------------------------------------------------------------ the outbox: written offline, sent when the server answers
    def _outbox_dir(self, ident: str) -> Path:
        return MAIL_HOME / "outbox" / re.sub(r"[^A-Za-z0-9]", "", ident)

    @Property("QVariantList", notify=changed)
    def outbox(self):
        out = []
        if self._demo or not self._acct:
            return out
        folder = self._outbox_dir(self._acct)
        for file in sorted(list(folder.glob("*.eml")) + list(folder.glob("*.held")), key=lambda f: f.stat().st_mtime):
            try:
                head = email.message_from_bytes(file.read_bytes()[:20000], policy=email.policy.default)
                out.append({"id": file.name, "to": str(head["To"] or ""), "subject": str(head["Subject"] or "(no subject)"), "time": when_text(file.stat().st_mtime),
                            "held": file.suffix == ".held"})
            except (OSError, ValueError):
                continue
        return out

    def _queue(self, ident: str, msg: EmailMessage) -> None:
        folder = self._outbox_dir(ident)
        folder.mkdir(parents=True, exist_ok=True)
        os.chmod(folder, 0o700)
        part = folder / f".{uuid.uuid4().hex}.part"
        part.write_bytes(msg.as_bytes())
        os.chmod(part, 0o600)
        os.replace(part, folder / f"{int(time.time() * 1000)}-{uuid.uuid4().hex[:6]}.eml")

    @Slot()
    def flushOutbox(self) -> None:
        """Try to send what's waiting, oldest first; whatever still can't go stays."""
        for ident, line in self._lines.items():
            for file in sorted(self._outbox_dir(ident).glob("*.eml")):
                if file.name in self._sending:
                    continue
                self._sending.add(file.name)

                def work(engine, file=file):
                    try:
                        if file.exists():
                            try:
                                engine.send(email.message_from_bytes(file.read_bytes(), policy=email.policy.default))
                            except MaybeSent:                      # never sent twice by itself: it waits for you to decide
                                os.replace(file, file.with_suffix(".held"))
                                return None
                            file.unlink(missing_ok=True)
                            return True
                        return False
                    finally:
                        self._sending.discard(file.name)

                def done(went, line=line):
                    if went is None:
                        self.failed.emit("A message in the Outbox may or may not have gone: the connection dropped mid-send. Open the Outbox to decide.")
                    if went:
                        self.said.emit("A message from the Outbox was sent.")
                        sent = (line.store.run("SELECT name FROM folders WHERE role = 'sent'") or [{"name": ""}])[0]["name"]
                        if sent:
                            self._sync(sent, line, True)
                self._job(work, done, True, line)

    @Slot(str)
    def dropQueued(self, name: str) -> None:
        if re.fullmatch(r"[0-9a-f-]+\.(eml|held)", name) and name not in self._sending:
            (self._outbox_dir(self._acct) / name).unlink(missing_ok=True)
        self.changed.emit()

    @Slot(str)
    def sendAnyway(self, name: str) -> None:
        """A message that may already have gone: send it again regardless."""
        file = self._outbox_dir(self._acct) / name
        if re.fullmatch(r"[0-9a-f-]+\.held", name) and file.exists():
            os.replace(file, file.with_suffix(".eml"))
            self.flushOutbox()
        self.changed.emit()

    @Property("QVariantMap", notify=changed)
    def current(self):
        if not self._open:
            return {}
        folder, uid = self._split(self._open)
        if self._demo:
            r = next((m for m in self._demo_rows if m["uid"] == uid and m["folder"] == folder), None)
        else:
            line = self._line()
            rows = line.store.run("SELECT * FROM messages WHERE folder = ? AND uid = ?", (folder, uid)) if line else []
            r = rows[0] if rows else None
        if r is None:
            return {}
        out = self._row(r)
        try:
            files = json.loads(r["files"] or "[]")
        except ValueError:
            files = []
        out.update({"body": r["body"] if r["body"] is not None else "", "loading": r["body"] is None, "wasHtml": bool(r["was_html"]), "cc": r["cc"] or "",
                    "date": dt.datetime.fromtimestamp(r["stamp"]).strftime("%A %-d %B %Y, %H:%M" if os.name != "nt" else "%A %d %B %Y, %H:%M"),
                    "files": [{"name": f["name"], "size": _size(f["size"]), "index": f["index"]} for f in files], "inTrash": self._role(folder) == "trash",
                    "invite": next((dict(f["invite"], index=f["index"]) for f in files if f.get("invite")), {}),
                    "mine": self._role(folder) in ("sent", "drafts")})
        return out

    def _role(self, folder: str) -> str:
        if self._demo:
            return {"INBOX": "inbox", "Sent": "sent", "Trash": "trash"}.get(folder, "")
        line = self._line()
        rows = line.store.run("SELECT role FROM folders WHERE name = ?", (folder,)) if line else []
        return (rows[0]["role"] or "") if rows else ""

    # ------------------------------------------------------------------ moving about
    @Slot(str)
    def setAccount(self, ident: str) -> None:
        if ident in self._lines and ident != self._acct:
            self._acct, self._folder, self._open, self._query, self._offline = ident, "INBOX", "", "", ""
            self.changed.emit()
            self.refresh()

    @Slot(str)
    def setFolder(self, name: str) -> None:
        self._folder, self._open = name, ""
        self.changed.emit()
        if not self._demo and name != "*starred":
            self._sync(name)

    @Slot(str)
    def search(self, text: str) -> None:
        self._query = text
        self.changed.emit()

    def _sync(self, folder: str, line: "_Line" = None, quiet: bool = False) -> None:
        def work(engine):
            new = engine.sync_folder(folder)
            rows = engine.store.run("SELECT uid FROM messages WHERE folder = ? AND body IS NULL AND size < 300000 ORDER BY stamp DESC LIMIT ?", (folder, PREFETCH))
            for r in rows:                                         # read the newest ahead, so each has a preview line and opens at once
                engine.fetch_body(folder, r["uid"])
            return new
        self._job(work, None, quiet, line)

    @Slot()
    def refresh(self) -> None:
        """Check the server now: the mailboxes, then the one being shown, then the inbox."""
        if self._demo or not self._line():
            return
        self._job(lambda engine: engine.sync_folders())
        if self._folder not in ("*starred", "INBOX"):
            self._sync(self._folder)
        self._sync("INBOX")
        self.flushOutbox()

    def _check_all(self) -> None:
        for line in self._lines.values():
            before = line.store.run("SELECT COUNT(*) AS n FROM messages WHERE folder = 'INBOX' AND seen = 0")[0]["n"]

            def work(engine, line=line, before=before):
                new = engine.sync_folder("INBOX")
                for r in engine.store.run("SELECT uid FROM messages WHERE folder = 'INBOX' AND body IS NULL AND size < 300000 ORDER BY stamp DESC LIMIT ?", (PREFETCH,)):
                    engine.fetch_body("INBOX", r["uid"])
                return new, before
            self._job(work, lambda res, line=line: self._tell_new(line, res[0]), True, line)
        self.flushOutbox()

    def _tell_new(self, line: "_Line", new: int) -> None:
        if new <= 0 or not shutil.which("notify-send"):
            return
        rows = line.store.run("SELECT from_name, subject FROM messages WHERE folder = 'INBOX' AND seen = 0 ORDER BY stamp DESC LIMIT 1")
        if rows:
            title = rows[0]["from_name"] if new == 1 else f"{new} new messages"
            try:
                subprocess.Popen(["notify-send", "-a", "Mail", "-i", "mail-unread", title, rows[0]["subject"]], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except OSError:
                pass

    # ------------------------------------------------------------------ one message
    @Slot(str)
    def read(self, ident: str) -> None:
        self._open = ident
        folder, uid = self._split(ident)
        if self._demo:
            for m in self._demo_rows:
                if m["uid"] == uid and m["folder"] == folder:
                    m["seen"] = 1
            self.changed.emit()
            return
        line = self._line()
        rows = line.store.run("SELECT seen, body FROM messages WHERE folder = ? AND uid = ?", (folder, uid))
        if not rows:
            self._open = ""
            self.changed.emit()
            return
        if rows[0]["body"] is None:
            self._job(lambda engine: engine.fetch_body(folder, uid))
        if not rows[0]["seen"]:
            line.store.run("UPDATE messages SET seen = 1 WHERE folder = ? AND uid = ?", (folder, uid))
            self._job(lambda engine: engine.set_flag(folder, uid, "\\Seen", True), None, True)
        self.changed.emit()

    def _flag(self, ident: str, column: str, flag: str, on: bool) -> None:
        folder, uid = self._split(ident)
        if self._demo:
            for m in self._demo_rows:
                if m["uid"] == uid and m["folder"] == folder:
                    m[column] = int(on)
            self.changed.emit()
            return
        self._line().store.run(f"UPDATE messages SET {column} = ? WHERE folder = ? AND uid = ?", (int(on), folder, uid))
        self.changed.emit()
        self._job(lambda engine: engine.set_flag(folder, uid, flag, on))

    @Slot(str)
    def toggleStar(self, ident: str) -> None:
        row = next((m for m in self.messages if m["id"] == ident), None) or (self.current if self._open == ident else None)
        if row:
            self._flag(ident, "starred", "\\Flagged", not row["starred"])

    @Slot(str)
    def markUnread(self, ident: str) -> None:
        self._flag(ident, "seen", "\\Seen", False)
        if self._open == ident:
            self._open = ""
            self.changed.emit()

    def _move_to(self, ident: str, role: str, word: str) -> None:
        folder, uid = self._split(ident)
        if self._demo:
            dest = {"trash": "Trash", "archive": "Trash", "junk": "Trash"}[role]
            for m in self._demo_rows:
                if m["uid"] == uid and m["folder"] == folder:
                    m["folder"] = dest
            self._open = ""
            self.changed.emit()
            return
        line = self._line()
        dest = (line.store.run("SELECT name FROM folders WHERE role = ?", (role,)) or [{"name": ""}])[0]["name"]
        if not dest:
            self.failed.emit(f"This account has no {word} mailbox.")
            return
        if dest == folder:
            return
        after = self.messages
        at = next((i for i, m in enumerate(after) if m["id"] == ident), -1)
        nxt = after[at + 1]["id"] if 0 <= at < len(after) - 1 else (after[at - 1]["id"] if at > 0 else "")
        line.store.run("DELETE FROM messages WHERE folder = ? AND uid = ?", (folder, uid))      # gone from the list at once
        self._open = nxt if self._open == ident else self._open
        self.changed.emit()
        self._job(lambda engine: engine.move(folder, uid, dest), lambda _r: self._sync(dest, None, True))
        if nxt and self._open == nxt:
            self.read(nxt)

    @Slot(str)
    def trash(self, ident: str) -> None:
        self._move_to(ident, "trash", "Trash")

    @Slot(str)
    def archive(self, ident: str) -> None:
        self._move_to(ident, "archive", "Archive")

    @Slot(str)
    def junk(self, ident: str) -> None:
        self._move_to(ident, "junk", "Junk")

    @Slot(str)
    def deleteForGood(self, ident: str) -> None:
        """Only for a message already in the Trash."""
        folder, uid = self._split(ident)
        if self._demo or self._role(folder) != "trash":
            return
        self._line().store.run("DELETE FROM messages WHERE folder = ? AND uid = ?", (folder, uid))
        if self._open == ident:
            self._open = ""
        self.changed.emit()
        self._job(lambda engine: engine.delete_for_good(folder, uid))

    @Slot(str, int)
    def saveAttachment(self, ident: str, index: int) -> None:
        folder, uid = self._split(ident)
        if self._demo:
            return
        downloads = Path(QStandardPaths.writableLocation(QStandardPaths.DownloadLocation) or Path.home() / "Downloads")

        def work(engine):
            name, data = engine.attachment(folder, uid, index)
            name = re.sub(r"[/\\\0]", "_", name).lstrip(".") or "attachment"          # the sender chooses the name: never a path
            downloads.mkdir(parents=True, exist_ok=True)
            target, n = downloads / name, 1
            while os.path.lexists(target):
                n += 1
                target = downloads / f"{Path(name).stem} {n}{Path(name).suffix}"
            target.write_bytes(data)
            return target
        self._job(work, lambda target: self.said.emit(f"Saved “{target.name}” in Downloads."))

    # ------------------------------------------------------------------ accounts
    @Slot(str, result="QVariantMap")
    def guess(self, address: str):
        return guess_servers(address)

    def _try_account(self, cfg: dict, secret_of, context) -> str:
        """Sign in for reading and for sending. Returns "" or, when only sending was refused, why. Raises on failure."""
        store = None
        try:
            MAIL_HOME.mkdir(parents=True, exist_ok=True)
            store = Store(MAIL_HOME / f"{cfg['id']}.db")
            engine = Engine(cfg, secret_of, store, context)
            try:
                engine.imap()
            except SignInError:
                raise
            except Exception as err:
                raise RuntimeError("Reading mail: " + plain_error(err)) from err
            engine.sync_folders()
            sending = ""
            try:
                if int(cfg["smtp_port"]) in (587, 25, 2525):
                    server = smtplib.SMTP(cfg["smtp_host"], int(cfg["smtp_port"]), timeout=25)
                    server.starttls(context=engine._context)
                else:
                    server = smtplib.SMTP_SSL(cfg["smtp_host"], int(cfg["smtp_port"]), context=engine._context, timeout=25)
                smtp_login(server, cfg["user"], secret_of())
                server.quit()
            except Exception as err:
                if not cfg.get("oauth"):
                    raise RuntimeError("Sending mail: " + plain_error(err)) from err
                sending = plain_error(err)                         # the provider let Mail read but not send: still worth having
            engine.close()
            return sending
        finally:
            if store is not None:
                store.close()

    @Slot("QVariantMap")
    def signIn(self, form) -> None:
        """Try an account: sign in for reading and for sending, and only keep it if that works. With `window` set,
        the signing in happens on the provider's own page in the browser, and Mail never sees a password."""
        if self._adding:
            return
        address = str(form.get("email", "")).strip()
        password = str(form.get("password", ""))
        again = str(form.get("again", ""))                         # an account that's already here, signing in afresh
        was = next((a for a in self._accounts if a["id"] == again), None)
        if was:
            address = was["email"]
        hint = guess_servers(address)
        window = hint["oauth"] if form.get("window") else ""
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", address):
            self.signedIn.emit(False, "That doesn't look like an email address.")
            return
        if self._vault.locked():
            self.signedIn.emit(False, "Unlock Passwords first: that's where Mail keeps the sign-in.")
            return
        if hint["blocked"]:
            self.signedIn.emit(False, hint["note"])
            return
        if window and not hint["oauthReady"]:
            self.signedIn.emit(False, hint["note"])
            return
        if not window and not hint["passwordToo"] and hint["known"]:
            self.signedIn.emit(False, f"{hint['oauthName']} no longer takes passwords from mail apps. Use its sign-in page instead.")
            return
        if not window and not password:
            self.signedIn.emit(False, "Type the password. Many providers need an app password instead of your usual one.")
            return
        if not was and any(a["email"].lower() == address.lower() for a in self._accounts):
            self.signedIn.emit(False, "That account is already here.")
            return
        try:
            cfg = dict(was) if was else {"id": uuid.uuid4().hex[:12], "name": str(form.get("name", "")).strip(), "email": address, "user": str(form.get("user", "")).strip() or address,
                                         "imap_host": str(form.get("imap_host", "")).strip() or hint["imap_host"], "imap_port": int(form.get("imap_port") or hint["imap_port"]),
                                         "smtp_host": str(form.get("smtp_host", "")).strip() or hint["smtp_host"], "smtp_port": int(form.get("smtp_port") or hint["smtp_port"])}
        except (TypeError, ValueError):
            self.signedIn.emit(False, "The port numbers should be numbers, like 993 and 465.")
            return
        if window:                                                 # a token for Google is only ever sent to Google's servers
            cfg.update(user=address, imap_host=hint["imap_host"], imap_port=hint["imap_port"], smtp_host=hint["smtp_host"], smtp_port=hint["smtp_port"])
        cfg["oauth"] = window
        if not cfg["imap_host"] or not cfg["smtp_host"]:
            self.signedIn.emit(False, "Mail needs the names of the incoming and outgoing servers.")
            return
        self._adding, self._stop_sign_in, self._waiting = True, False, hint["oauthName"] if window else ""
        self.changed.emit()
        context = self._context

        def work():
            try:
                if window:
                    got = oauth_sign_in(window, address, lambda url: self._call.emit(lambda: self._open_url(url)), lambda: self._stop_sign_in)
                    self._call.emit(lambda: (setattr(self, "_waiting", ""), self.changed.emit()))
                    secret = {"kind": "oauth", "provider": window, "refresh": got["refresh"], "email": address}
                    tokens = Tokens(window, got, lambda new: secret.__setitem__("refresh", new))
                    secret_of = lambda: {"access": tokens.access()}                    # noqa: E731
                else:
                    secret = {"kind": "password", "password": password, "email": address}
                    secret_of = lambda: {"password": password}                         # noqa: E731
                sending = self._try_account(cfg if not was else dict(cfg, id=cfg["id"] + ".try"), secret_of, context)
                self._call.emit(lambda: self._signed_in(cfg, secret, sending, was is not None))
            except Exception as err:
                why = "This account was signed out by its provider straight away. Try again." if str(err) == "signed-out" else str(err)
                if not was:
                    for leftover in MAIL_HOME.glob(f"{cfg['id']}.db*"):
                        leftover.unlink(missing_ok=True)
                self._call.emit(lambda why=why: self._sign_in_failed(why))
            finally:
                for leftover in MAIL_HOME.glob(f"{cfg['id']}.try.db*"):
                    leftover.unlink(missing_ok=True)
        self._adder = threading.Thread(target=work, daemon=True)
        self._adder.start()

    @Slot()
    def cancelSignIn(self) -> None:
        """Stop waiting for the provider's sign-in page."""
        self._stop_sign_in = True

    def _sign_in_failed(self, why: str) -> None:
        self._adding, self._waiting = False, ""
        self.changed.emit()
        self.signedIn.emit(False, why)

    def _signed_in(self, cfg: dict, secret: dict, sending: str, again: bool) -> None:
        self._adding, self._waiting = False, ""
        try:
            if self._vault.locked():
                raise self._hv.VaultError("Passwords was locked while you were signing in. Unlock and try again.")
            self._vault.set_secret("mail", cfg["id"], secret)
        except (self._hv.VaultError, OSError) as err:
            if not again:
                for leftover in MAIL_HOME.glob(f"{cfg['id']}.db*"):
                    leftover.unlink(missing_ok=True)
            self.changed.emit()
            self.signedIn.emit(False, f"Signed in, but couldn't keep the sign-in in Passwords: {getattr(err, 'strerror', None) or err}")
            return
        if again:
            self._accounts = [cfg if a["id"] == cfg["id"] else a for a in self._accounts]
            self._lines[cfg["id"]].cfg = cfg
            self._lines[cfg["id"]].hang_up()
        else:
            self._accounts.append(cfg)
            self._lines[cfg["id"]] = _Line(cfg, self._context, self._call.emit, lambda i=cfg["id"]: self._secret_for(i))
            self._acct, self._folder, self._open = cfg["id"], "INBOX", ""
        self._save_accounts()
        self._take_secrets()
        self._offline = ""
        self.changed.emit()
        name = OAUTH.get(cfg.get("oauth"), {}).get("name", "The provider")
        self.signedIn.emit(True, f"Reading works, but {name} refused sending: {sending}" if sending else "")
        self.refresh()

    adding = Property(bool, lambda self: self._adding, notify=changed)

    @Slot(str)
    def removeAccount(self, ident: str) -> None:
        """Take an account off this computer. Nothing on the server is touched."""
        line = self._lines.pop(ident, None)
        if line:
            line.stop()
            line.thread.join(timeout=5)
            line.store.close()
        if not self._vault.locked():
            try:
                self._vault.set_secret("mail", ident, None)
            except (self._hv.VaultError, OSError):
                pass
        with self._guard:
            self._secrets.pop(ident, None)
            self._tokens.pop(ident, None)
        shutil.rmtree(self._outbox_dir(ident), ignore_errors=True)
        for leftover in MAIL_HOME.glob(f"{ident}.db*"):
            leftover.unlink(missing_ok=True)
        self._accounts = [a for a in self._accounts if a["id"] != ident]
        self._save_accounts()
        if self._acct == ident:
            self._acct = self._accounts[0]["id"] if self._accounts else ""
            self._folder, self._open = "INBOX" if self._acct else "", ""
        self.changed.emit()

    # ------------------------------------------------------------------ writing
    def _full(self, ident: str):
        folder, uid = self._split(ident)
        if self._demo:
            return next((m for m in self._demo_rows if m["uid"] == uid and m["folder"] == folder), None)
        rows = self._line().store.run("SELECT * FROM messages WHERE folder = ? AND uid = ?", (folder, uid)) if self._line() else []
        return rows[0] if rows else None

    @staticmethod
    def _quote(r) -> str:
        when = dt.datetime.fromtimestamp(r["stamp"]).strftime("%-d %b %Y at %H:%M" if os.name != "nt" else "%d %b %Y at %H:%M")
        body = (r["body"] or "").strip()
        return f"\n\nOn {when}, {r['from_name'] or r['from_addr']} wrote:\n" + "\n".join("> " + line if line else ">" for line in body.splitlines())

    @Slot(str, bool, result="QVariantMap")
    def replyDraft(self, ident: str, everyone: bool):
        r = self._full(ident)
        if r is None:
            return {}
        mine = self._cfg().get("email", "").lower()
        subject = r["subject"] or ""
        others = []
        if everyone:
            for _name, addr in email.utils.getaddresses([r["rcpt"] or "", r["cc"] or ""]):
                if addr and addr.lower() not in (mine, (r["from_addr"] or "").lower()) and addr not in others:
                    others.append(addr)
        return {"to": r["from_addr"] or "", "cc": ", ".join(others), "subject": subject if re.match(r"(?i)re:", subject) else "Re: " + subject,
                "body": self.signatureBlock + self._quote(r), "replyId": r["msgid"] or "", "refs": r["refs"] or "", "replyTo": ident, "title": "Reply"}

    @Slot(str, result="QVariantMap")
    def forwardDraft(self, ident: str):
        r = self._full(ident)
        if r is None:
            return {}
        subject = r["subject"] or ""
        head = f"\n\n---------- Forwarded message ----------\nFrom: {r['from_name']} <{r['from_addr']}>\nSubject: {subject}\nTo: {r['rcpt'] or ''}\n\n"
        return {"to": "", "cc": "", "subject": subject if re.match(r"(?i)fwd?:", subject) else "Fwd: " + subject, "body": self.signatureBlock + head + (r["body"] or ""),
                "replyId": "", "refs": "", "replyTo": "", "title": "Forward"}

    @Slot(str, result="QVariantList")
    def suggest(self, text: str):
        """People to offer while an address is being typed: from Contacts first, then from mail already here."""
        want = text.strip().lower()
        if len(want) < 2:
            return []
        out, seen = [], set()

        def offer(name, addr):
            if addr and addr.lower() not in seen and (want in addr.lower() or want in (name or "").lower()) and len(out) < 6:
                seen.add(addr.lower())
                out.append({"name": name or addr, "addr": addr})
        try:
            from huginn_more import read_vcards
            for card in read_vcards((DATA_HOME / "contacts.vcf").read_text(encoding="utf-8", errors="replace")):
                for e in card["emails"]:
                    offer(card["name"], e["value"])
        except (OSError, ImportError):
            pass
        if self._demo:
            for m in self._demo_rows:
                offer(m["from_name"], m["from_addr"])
        elif self._line():
            for r in self._line().store.run("SELECT from_name, from_addr, COUNT(*) AS n FROM messages WHERE lower(from_addr) LIKE ? OR lower(from_name) LIKE ? GROUP BY from_addr ORDER BY n DESC LIMIT 12",
                                            (f"%{want}%", f"%{want}%")):
                offer(r["from_name"], r["from_addr"])
        return out

    @Slot("QVariantMap")
    def send(self, form) -> None:
        to, cc, subject, body = (str(form.get(k, "")) for k in ("to", "cc", "subject", "body"))
        files = [QUrl(str(f)).toLocalFile() if str(f).startswith("file:") else str(f) for f in form.get("files", [])]
        everyone = [a.strip() for a in re.split(r"[;,]", to + "," + cc) if a.strip()]
        if not everyone:
            self.wasSent.emit(False, "Who is it for? Add an address.")
            return
        bad = next((a for a in everyone if not re.fullmatch(r"(?:[^<>]*<)?[^@\s<>]+@[^@\s<>]+\.[^@\s<>]+>?", a)), "")
        if bad:
            self.wasSent.emit(False, f"“{bad}” doesn't look like an email address.")
            return
        missing = next((f for f in files if not Path(f).is_file()), "")
        if missing:
            self.wasSent.emit(False, f"The attachment “{Path(missing).name}” is no longer there.")
            return
        if sum(Path(f).stat().st_size for f in files) > 25 * 1024 * 1024:
            self.wasSent.emit(False, "The attachments add up to more than 25 MB, which most mail servers refuse.")
            return
        if self._demo or not self._line():
            self.wasSent.emit(False, "This is the preview: nothing is sent." if self._demo else "Add an account first.")
            return
        try:
            event = clean_event(form.get("event"))
            guests = [email.utils.parseaddr(a)[1] for a in everyone]
            msg = build_message(self._cfg(), to, cc, subject, body, files, str(form.get("replyId", "")), str(form.get("refs", "")),
                                invitation(self._cfg(), event, guests) if event else "")
        except OSError as err:
            self.wasSent.emit(False, f"Couldn't read an attachment: {err.strerror or err}")
            return
        reply_to = str(form.get("replyTo", ""))
        line = self._line()
        self._busy += 1
        self.changed.emit()

        def ok(_result):
            self._busy -= 1
            self.clearDraft()
            if reply_to:
                folder, uid = self._split(reply_to)
                line.store.run("UPDATE messages SET answered = 1 WHERE folder = ? AND uid = ?", (folder, uid))
                self._job(lambda engine: engine.set_flag(folder, uid, "\\Answered", True), None, True, line)
            self.wasSent.emit(True, "")
            sent = (line.store.run("SELECT name FROM folders WHERE role = 'sent'") or [{"name": ""}])[0]["name"]
            if sent:
                self._sync(sent, line, True)
            self.changed.emit()

        def bad(why):
            self._busy -= 1
            self.wasSent.emit(False, why.replace("reach the mail server", "send it"))
            self.changed.emit()

        def queued():
            self._busy -= 1
            try:
                self._queue(line.cfg["id"], msg)
            except OSError as err:
                self.wasSent.emit(False, f"Couldn't send it, and couldn't keep it for later either: {err.strerror or err}")
                self.changed.emit()
                return
            self.clearDraft()
            self.wasSent.emit(True, "queued")
            self.changed.emit()

        def work(engine):
            try:
                engine.send(msg)
                return True
            except Exception as err:
                if can_wait(err):
                    return False
                raise
        line.post(work, lambda went: ok(None) if went else queued(), bad)

    @Slot(str, int, str)
    def answerInvite(self, ident: str, index: int, answer: str) -> None:
        """Tell the organiser yes, maybe or no. Yes and maybe also put the event in Calendar."""
        folder, uid = self._split(ident)
        line, cfg = self._line(), self._cfg()
        if self._demo or line is None:
            return

        def work(engine):
            _name, data = engine.attachment(folder, uid, index)
            engine.send(invite_reply(cfg, data, answer))
            return data

        def done(data):
            self.said.emit({"accept": "Accepted. The organiser has been told.", "maybe": "Answered maybe.", "decline": "Declined. The organiser has been told."}[answer])
            if answer != "decline":
                self.openAttachment(ident, f"{index}:calendar")
        self._job(work, done)

    # an unsent message survives closing the window
    @Slot("QVariantMap")
    def keepDraft(self, form) -> None:
        if self._demo:
            return
        try:
            MAIL_HOME.mkdir(parents=True, exist_ok=True)
            kept = {k: form.get(k, "") if k != "files" else [str(f) for f in form.get("files", [])]
                    for k in ("to", "cc", "subject", "body", "files", "replyId", "refs", "replyTo", "title")}
            if clean_event(form.get("event")):
                kept["event"] = clean_event(form.get("event"))
            (MAIL_HOME / "unsent.json").write_text(json.dumps(kept), encoding="utf-8")
        except (OSError, TypeError):
            pass

    @Slot(result="QVariantMap")
    def draft(self):
        try:
            return json.loads((MAIL_HOME / "unsent.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    @Slot()
    def clearDraft(self) -> None:
        (MAIL_HOME / "unsent.json").unlink(missing_ok=True)

    @Slot(result="QVariantList")
    def attachChoices(self):
        """Files lately saved in Downloads, Documents or on the Desktop: the likeliest things to attach."""
        rows = []
        for where in (QStandardPaths.DownloadLocation, QStandardPaths.DocumentsLocation, QStandardPaths.DesktopLocation):
            folder = Path(QStandardPaths.writableLocation(where) or "")
            try:
                names = os.listdir(folder) if str(folder) not in ("", ".") else []
            except OSError:
                continue
            for name in names:
                full = folder / name
                try:
                    if name.startswith(".") or not full.is_file():
                        continue
                    st = full.stat()
                except OSError:
                    continue
                rows.append({"name": name, "path": str(full), "where": folder.name, "size": _size(st.st_size), "stamp": st.st_mtime})
        return sorted(rows, key=lambda r: -r["stamp"])[:8]

    @Slot(str, result="QVariantMap")
    def fileInfo(self, path: str):
        path = QUrl(path).toLocalFile() if path.startswith("file:") else path
        try:
            return {"name": Path(path).name, "path": path, "size": _size(Path(path).stat().st_size)} if Path(path).is_file() else {}
        except OSError:
            return {}

    def stop(self) -> None:
        self._badge(gone=True)
        for line in self._lines.values():
            line.stop()


def _size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit in ("B", "KB") else f"{n:.1f} {unit}"
        n /= 1024
    return ""


def _demo_messages() -> list:
    now = time.time()
    rows = [(1, "INBOX", "Sam Okafor", "sam@example.com", "Shell preview on my laptop", 0.6, 0, 1, 0,
             "Ran the preview this morning. The dock feels right, and the realm switch is instant.\n\nTwo notes: the launcher could remember the last search, and I'd like the widgets to snap to a grid.\n\nSam"),
            (2, "INBOX", "Ubuntu Security", "security@lists.example", "Notices for resolute, week 46", 26, 0, 0, 0, "Three packages in your image have updates this week. Rebuild from a newer snapshot to pick them up."),
            (3, "INBOX", "Ingrid Halvorsen", "ingrid@example.com", "Icon sketches, round two", 74, 1, 0, 1, "Attached are the line icons at 1.7 px stroke. I kept the corners soft to match the tiles."),
            (4, "INBOX", "Lakeside Vets", "hello@lakesidevets.example", "Reminder: Biscuit's check-up on Friday", 98, 1, 0, 0, "This is a reminder that Biscuit is booked in for 10:15 on Friday. Reply to this message if you need to move it."),
            (5, "Sent", "Val", "val@example.com", "Re: Icon sketches, round two", 70, 1, 0, 0, "These are lovely. Go with the second set.")]
    return [{"uid": u, "folder": f, "from_name": n, "from_addr": a, "rcpt": "val@example.com", "cc": "", "subject": s, "stamp": now - h * 3600, "seen": seen, "starred": star,
             "answered": 0, "attach": att, "size": len(b), "snippet": " ".join(b.split())[:160], "body": b, "was_html": 0, "msgid": f"<{u}@example.com>", "refs": "",
             "files": json.dumps([{"name": "icons-round-two.zip", "size": 482133, "kind": "application/zip", "index": 2}]) if att else "[]"} for u, f, n, a, s, h, seen, star, att, b in rows]
