"""Authenticator: the six-digit codes that sites ask for after the password (two-factor sign-in).

The secrets behind the codes live in the same vault as Passwords, the browser and Mail (drawer "otp"), under the
same master password and the same "unlock once". A code is worked out here from the secret and the clock
(RFC 6238, TOTP) or a counter (RFC 4226, HOTP); nothing goes over the network.

Codes come in as an otpauth:// link, a QR code (in a picture, on the clipboard, or anywhere on the screen), a
Google Authenticator export (otpauth-migration://), or a key typed in by hand."""
import base64
import hashlib
import hmac
import os
import re
import shutil
import struct
import subprocess
import tempfile
import time
import uuid
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from PySide6.QtCore import Property, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QGuiApplication

import huginn_more

DRAWER = "otp"
ALGOS = {"SHA1": hashlib.sha1, "SHA256": hashlib.sha256, "SHA512": hashlib.sha512}


# ============================================================================================= the codes
def clean_secret(text: str) -> str:
    """A key as people get it: spaces, dashes, lower case, missing padding. Returns it as plain base32, or ""."""
    key = re.sub(r"[\s\-]", "", str(text or "")).upper().rstrip("=")
    if not key or not re.fullmatch(r"[A-Z2-7]+", key):
        return ""
    try:
        base64.b32decode(key + "=" * (-len(key) % 8))
    except (ValueError, base64.binascii.Error):
        return ""
    return key


def hotp(secret: str, counter: int, digits: int = 6, algo: str = "SHA1") -> str:
    key = base64.b32decode(secret + "=" * (-len(secret) % 8))
    mac = hmac.new(key, struct.pack(">Q", int(counter)), ALGOS.get(algo, hashlib.sha1)).digest()
    at = mac[-1] & 0x0F
    number = struct.unpack(">I", mac[at:at + 4])[0] & 0x7FFFFFFF
    return str(number % 10 ** digits).zfill(digits)


def totp(secret: str, now: float = None, period: int = 30, digits: int = 6, algo: str = "SHA1") -> str:
    return hotp(secret, int((time.time() if now is None else now) // period), digits, algo)


def entry_from(fields: dict) -> dict:
    """A checked entry from loose fields, or raises ValueError with words for the person."""
    secret = clean_secret(fields.get("secret", ""))
    if not secret:
        raise ValueError("That key isn't right. It's letters A to Z and digits 2 to 7, like JBSW Y3DP EHPK 3PXP.")
    kind = str(fields.get("type") or "totp").lower()
    algo = str(fields.get("algo") or fields.get("algorithm") or "SHA1").upper().replace("-", "")
    try:
        digits, period, counter = int(fields.get("digits") or 6), int(fields.get("period") or 30), int(fields.get("counter") or 0)
    except (TypeError, ValueError):
        raise ValueError("The link has a number that isn't a number.") from None
    if kind not in ("totp", "hotp") or algo not in ALGOS or digits not in (6, 7, 8) or not 10 <= period <= 300 or counter < 0:
        raise ValueError("This kind of code isn't supported (it needs 6 to 8 digits, SHA1/256/512, every 10 to 300 seconds).")
    issuer, account = " ".join(str(fields.get("issuer") or "").split())[:80], " ".join(str(fields.get("account") or "").split())[:120]
    if not issuer and not account:
        raise ValueError("Give it a name: the site, or your account on it.")
    return {"issuer": issuer, "account": account, "secret": secret, "type": kind, "algo": algo, "digits": digits, "period": period,
            "counter": counter, "site": str(fields.get("site") or "")[:200]}


def parse_otpauth(link: str) -> dict:
    """otpauth://totp/Issuer:account?secret=...&issuer=...&digits=6&period=30&algorithm=SHA1"""
    url = urlparse(str(link).strip())
    if url.scheme.lower() != "otpauth" or url.netloc.lower() not in ("totp", "hotp"):
        raise ValueError("That isn't a two-factor link (they start with otpauth://).")
    label = unquote(url.path.lstrip("/"))
    query = {k.lower(): v[-1] for k, v in parse_qs(url.query).items()}
    issuer, _, account = label.partition(":") if ":" in label else ("", "", label)
    return entry_from({"type": url.netloc.lower(), "secret": query.get("secret", ""), "issuer": query.get("issuer") or issuer.strip(),
                       "account": account.strip(), "algo": query.get("algorithm"), "digits": query.get("digits"), "period": query.get("period"),
                       "counter": query.get("counter")})


def _varint(data: bytes, at: int):
    shift = value = 0
    while True:
        if at >= len(data) or shift > 63:
            raise ValueError("cut short")
        byte = data[at]
        at += 1
        value |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return value, at
        shift += 7


def _fields(data: bytes):
    """The fields of one protobuf message: (number, value) with bytes for strings and messages, ints for numbers."""
    at = 0
    while at < len(data):
        key, at = _varint(data, at)
        number, wire = key >> 3, key & 7
        if wire == 0:
            value, at = _varint(data, at)
        elif wire == 2:
            size, at = _varint(data, at)
            if at + size > len(data):
                raise ValueError("cut short")
            value, at = data[at:at + size], at + size
        elif wire == 1:
            value, at = data[at:at + 8], at + 8
        elif wire == 5:
            value, at = data[at:at + 4], at + 4
        else:
            raise ValueError("unknown field type")
        yield number, value


def parse_migration(link: str) -> list:
    """Google Authenticator's "Transfer accounts" QR: otpauth-migration://offline?data=<base64 protobuf>. Returns
    the entries it holds (one QR can hold several)."""
    url = urlparse(str(link).strip())
    data = (parse_qs(url.query).get("data") or [""])[-1]
    if url.scheme.lower() != "otpauth-migration" or not data:
        raise ValueError("That isn't a Google Authenticator export.")
    try:
        raw = base64.b64decode(data.replace(" ", "+") + "=" * (-len(data) % 4))
        out = []
        for number, value in _fields(raw):
            if number != 1 or not isinstance(value, bytes):
                continue
            f = {}
            for n, v in _fields(value):
                f[n] = v
            algo = {1: "SHA1", 2: "SHA256", 3: "SHA512"}.get(f.get(4, 1), "SHA1")
            digits = {1: 6, 2: 8}.get(f.get(5, 1), 6)
            kind = {1: "hotp", 2: "totp"}.get(f.get(6, 2), "totp")
            name = f.get(2, b"").decode("utf-8", "replace")
            issuer = f.get(3, b"").decode("utf-8", "replace")
            if ":" in name and not issuer:
                issuer, name = name.split(":", 1)
            elif issuer and name.startswith(issuer + ":"):
                name = name[len(issuer) + 1:]
            secret = base64.b32encode(f.get(1, b"")).decode().rstrip("=")
            out.append(entry_from({"secret": secret, "issuer": issuer, "account": name.strip(), "algo": algo, "digits": digits, "type": kind, "counter": f.get(7, 0)}))
    except (ValueError, base64.binascii.Error) as err:
        raise ValueError(f"The export couldn't be read ({err}).") from None
    if not out:
        raise ValueError("The export is empty.")
    return out


def entries_from_text(text: str) -> list:
    """Every code in some text: otpauth:// links and Google exports, one per line."""
    found = []
    for word in re.findall(r"otpauth(?:-migration)?://\S+", str(text or ""), re.I):
        found.extend(parse_migration(word) if word.lower().startswith("otpauth-migration") else [parse_otpauth(word)])
    return found


def read_qr(image: str) -> str:
    """The text in every QR code in a picture (zbarimg, from zbar-tools). "" if none or no zbarimg."""
    tool = shutil.which("zbarimg")
    if not tool or not os.path.isfile(image):
        return ""
    try:
        out = subprocess.run([tool, "--raw", "-q", "-Sdisable", "-Sqrcode.enable", image], capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return ""
    return out.stdout


def site_words(entry: dict) -> set:
    """Lower-case words that tie a code to a login: its issuer and its site."""
    words = set()
    for text in (entry.get("issuer", ""), entry.get("site", "")):
        host = urlparse(text if "://" in text else "").hostname or ""
        for part in re.split(r"[\s.\-_/:]+", (host or text).lower()):
            if len(part) > 2 and part not in ("www", "com", "org", "net", "app", "the", "inc", "llc", "ltd"):
                words.add(part)
    return words


def codes_for(entries: dict, url: str, title: str = "") -> list:
    """The codes that belong with a login (Passwords shows them on the login): by site, then by name."""
    host = (urlparse(url).hostname or "").lower()
    hits = []
    for ident, e in entries.items():
        if not isinstance(e, dict):
            continue
        if e.get("site") and host and (urlparse(e["site"]).hostname or e["site"]).lower().lstrip(".") in (host, ".".join(host.split(".")[-2:])):
            hits.append(ident)
        elif site_words(e) & set(re.split(r"[\s.\-_/:]+", f"{host} {title}".lower())):
            hits.append(ident)
    return hits


# ============================================================================================= the app
class Authenticator(huginn_more.Vault):
    """Passwords' door (the same vault, master password and "unlock once"), with the codes behind it."""
    TICK_MS = 1000
    codesChanged = Signal()

    def __init__(self, file: Path = None, demo: bool = False):
        super().__init__(file, demo)
        self.changed.connect(self.codesChanged)
        self._query, self._shown = "", {}
        self._demo_codes = {}
        if demo:
            for i, (iss, acc, sec, site) in enumerate([("Nordlys Bank", "val.example", "JBSWY3DPEHPK3PXP", "https://nordlysbank.example"),
                                                        ("GitHub", "valkyrii070", "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ", "https://github.com"),
                                                        ("Mail", "astrid@example.com", "KRSXG5CTMVRXEZLUKN2XAZLSNFXGO", ""),
                                                        ("Cloud storage", "astrid@example.com", "MFRGGZDFMZTWQ2LKNNWG23TPOBYXE", ""),
                                                        ("Game store", "ravenkeeper", "ONSWG4TFOQYTEMZUGU3DOOBZ", ""), ("Work VPN", "astrid", "NBSWY3DPO5XXE3DE", "")]):
                self._demo_codes[f"d{i}"] = dict(entry_from({"secret": sec, "issuer": iss, "account": acc, "site": site}), added=time.time() - i * 86400 * 9)
        self._clock = QTimer(self)
        self._clock.setInterval(self.TICK_MS)
        self._clock.timeout.connect(self._tick)
        self._clock.start()
        self._shot = None

    def _codes(self) -> dict:
        if self._demo:
            return self._demo_codes
        return dict(self._file.extras.get(DRAWER) or {}) if not self._file.locked() else {}

    def _tick(self) -> None:
        if not self.locked:
            self.changed.emit()

    def _store(self, ident: str, entry) -> None:
        if self._demo:
            if entry is None:
                self._demo_codes.pop(ident, None)
            else:
                self._demo_codes[ident] = entry
            return
        self._file.set_secret(DRAWER, ident, entry)

    # ---- what QML sees
    def _get_codes(self) -> list:
        now = time.time()
        words = self._query.lower().split()
        out = []
        for ident, e in self._codes().items():
            if not isinstance(e, dict) or not e.get("secret"):
                continue
            name = f"{e.get('issuer', '')} {e.get('account', '')}".lower()
            if not all(w in name for w in words):
                continue
            period = int(e.get("period") or 30)
            try:
                code = hotp(e["secret"], e.get("counter", 0), e.get("digits", 6), e.get("algo", "SHA1")) if e.get("type") == "hotp" \
                    else totp(e["secret"], now, period, e.get("digits", 6), e.get("algo", "SHA1"))
                upcoming = "" if e.get("type") == "hotp" else totp(e["secret"], now + period, period, e.get("digits", 6), e.get("algo", "SHA1"))
            except (ValueError, base64.binascii.Error):
                continue
            left = 0 if e.get("type") == "hotp" else period - (now % period)
            half = len(code) // 2
            out.append({"id": ident, "issuer": e.get("issuer") or e.get("account"), "account": e.get("account") if e.get("issuer") else "",
                        "code": code, "shown": code[:half] + " " + code[half:], "next": upcoming[:half] + " " + upcoming[half:] if upcoming else "",
                        "left": left, "period": period, "share": left / period if period else 0, "hotp": e.get("type") == "hotp",
                        "site": e.get("site", ""), "added": e.get("added", 0), "algo": e.get("algo", "SHA1"), "digits": e.get("digits", 6)})
        return sorted(out, key=lambda c: (c["issuer"] or "").lower())

    codes = Property("QVariantList", _get_codes, notify=codesChanged)
    count = Property(int, lambda self: len(self._codes()), notify=codesChanged)
    canScan = Property(bool, lambda self: bool(shutil.which("zbarimg")), notify=codesChanged)

    @Slot(str)
    def search(self, text: str) -> None:
        self._query = text
        self.changed.emit()

    # ---- adding
    def _add(self, entries: list) -> int:
        have = {(e.get("secret"), e.get("issuer", "").lower(), e.get("account", "").lower()) for e in self._codes().values() if isinstance(e, dict)}
        added = 0
        for e in entries:
            if (e["secret"], e["issuer"].lower(), e["account"].lower()) in have:
                continue
            have.add((e["secret"], e["issuer"].lower(), e["account"].lower()))
            self._store(uuid.uuid4().hex[:12], dict(e, added=time.time()))
            added += 1
        self._touch()
        self.changed.emit()
        return added

    def _report(self, entries: list, source: str) -> str:
        added = self._add(entries)
        if not added:
            return "That code is already here." if entries else f"No two-factor code found in {source}."
        names = ", ".join(sorted({e["issuer"] or e["account"] for e in entries}))[:120]
        self.said.emit(f"Added {names}." if added == 1 else f"Added {added} codes: {names}.")
        return ""

    @Slot(str, result=str)
    def addLink(self, text: str) -> str:
        """A pasted otpauth:// link or Google export. Returns "" or why not."""
        if self.locked:
            return "Unlock first."
        try:
            entries = entries_from_text(text)
        except ValueError as err:
            return str(err)
        return self._report(entries, "that text") if entries else "No two-factor link in that text. It starts with otpauth://."

    @Slot(str, str, str, str, result=str)
    def addTyped(self, issuer: str, account: str, secret: str, site: str) -> str:
        if self.locked:
            return "Unlock first."
        try:
            entry = entry_from({"issuer": issuer, "account": account, "secret": secret, "site": site})
        except ValueError as err:
            return str(err)
        return self._report([entry], "that key")

    @Slot(str, result=str)
    def addPicture(self, path: str) -> str:
        """A picture of a QR code (a screenshot of the site's set-up page, say)."""
        path = QUrl(path).toLocalFile() if str(path).startswith("file:") else str(path)
        if self.locked:
            return "Unlock first."
        if not self.canScan:
            return "Reading QR codes needs zbar-tools, which isn't installed."
        text = read_qr(path)
        if not text.strip():
            return "No QR code found in that picture."
        try:
            return self._report(entries_from_text(text), "the QR code")
        except ValueError as err:
            return str(err)

    @Slot(result=str)
    def addClipboard(self) -> str:
        """Whatever was copied: a link, or a picture with a QR code."""
        board = QGuiApplication.clipboard()
        image = board.image() if board else None
        if image is not None and not image.isNull():
            fd, tmp = tempfile.mkstemp(suffix=".png", dir=os.environ.get("XDG_RUNTIME_DIR") or None)
            os.close(fd)
            try:
                image.save(tmp)
                return self.addPicture(tmp)
            finally:
                os.unlink(tmp)
        text = board.text() if board else ""
        return self.addLink(text) if text.strip() else "The clipboard is empty."

    @Slot()
    def scanScreen(self) -> None:
        """The desktop asks which part of the screen to take; any QR code in it is read."""
        if self.locked:
            return
        import huginn_app
        if self._shot is None:
            self._shot = huginn_app.Capture()
            self._shot.changed.connect(self._shot_done)
            self._shot.failed.connect(lambda why: self.failed.emit(why))
        self._shot.take(True, 0)

    def _shot_done(self) -> None:
        if self._shot._busy or not self._shot._image:
            return
        path, self._shot._image = self._shot._image, ""
        why = self.addPicture(path)
        if why:
            self.failed.emit(why)
        if path.startswith(str(Path(os.environ.get("XDG_RUNTIME_DIR") or "/tmp"))):
            try:
                os.unlink(path)
            except OSError:
                pass

    # ---- using
    @Slot(str)
    def copyCode(self, ident: str) -> None:
        hit = next((c for c in self._get_codes() if c["id"] == ident), None)
        board = QGuiApplication.clipboard()
        if not hit or not board:
            return
        board.setText(hit["code"])
        self._copied = hit["code"]
        self._wipe.start()
        self._touch()
        self.said.emit(f"{hit['issuer']} code copied. It leaves the clipboard in 30 seconds.")

    @Slot(str)
    def nextCode(self, ident: str) -> None:
        """A counter-based code: step to the next one (after the last was used)."""
        e = self._codes().get(ident)
        if isinstance(e, dict) and e.get("type") == "hotp":
            self._store(ident, dict(e, counter=int(e.get("counter", 0)) + 1))
            self._touch()
            self.changed.emit()

    @Slot(str, str, str, str, result=str)
    def edit(self, ident: str, issuer: str, account: str, site: str) -> str:
        e = self._codes().get(ident)
        if not isinstance(e, dict):
            return "That code is gone."
        issuer, account = " ".join(issuer.split())[:80], " ".join(account.split())[:120]
        if not issuer and not account:
            return "Give it a name."
        self._store(ident, dict(e, issuer=issuer, account=account, site=site.strip()[:200]))
        self._touch()
        self.changed.emit()
        return ""

    @Slot(str)
    def remove(self, ident: str) -> None:
        if ident in self._codes():
            self._store(ident, None)
            self._touch()
            self.changed.emit()
            self.said.emit("Removed. Before you sign out of that site, make sure two-factor sign-in still works for you some other way.")


def codes_for_login(vault_file, url: str, title: str = "") -> list:
    """For Passwords: the live codes that go with a login, as [{issuer, account, shown, left}]."""
    box = vault_file.extras.get(DRAWER) or {} if not vault_file.locked() else {}
    now, out = time.time(), []
    for ident in codes_for(box, url, title):
        e = box[ident]
        try:
            period = int(e.get("period") or 30)
            code = hotp(e["secret"], e.get("counter", 0), e.get("digits", 6), e.get("algo", "SHA1")) if e.get("type") == "hotp" \
                else totp(e["secret"], now, period, e.get("digits", 6), e.get("algo", "SHA1"))
        except (KeyError, ValueError, base64.binascii.Error):
            continue
        out.append({"id": ident, "issuer": e.get("issuer", ""), "account": e.get("account", ""), "code": code,
                    "shown": code[:len(code) // 2] + " " + code[len(code) // 2:], "left": 0 if e.get("type") == "hotp" else int(period - now % period)})
    return out
