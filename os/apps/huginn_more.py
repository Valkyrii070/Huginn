"""Huginn's second set of apps: Passwords, Contacts, Weather, Backup, Disks, Camera and Voice Recorder.

Each class here is the engine behind one screen in qml/. They keep to the same rules as the first set: plain words for
anything that goes wrong, nothing slow on the window's thread, and files written whole or not at all.
"""
import base64
import csv
import datetime as dt
import io
import json
import os
import re
import secrets
import shutil
import string
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

from PySide6.QtCore import Property, QLocale, QObject, QStandardPaths, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QGuiApplication

DATA_HOME = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share") / "huginn"


def human_size(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit in ("B", "KB") else f"{n:.1f} {unit}"
        n /= 1024
    return ""


def write_whole(path: Path, data: bytes, mode: int = 0o600) -> None:
    """Write a file so that it is either the old one or the new one, never half of each."""
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.parent / f".{path.name}.saving"
    fd = os.open(part, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
    try:
        with os.fdopen(fd, "wb") as out:
            out.write(data)
            out.flush()
            os.fsync(out.fileno())
        os.replace(part, path)
    except BaseException:
        try:
            os.unlink(part)
        except OSError:
            pass
        raise


def ago(stamp: float, now: float = None) -> str:
    """"just now", "5 minutes ago", "yesterday", "12 Mar"."""
    gap = (now or time.time()) - stamp
    if gap < 90:
        return "just now"
    if gap < 3600:
        return f"{int(gap // 60)} minutes ago"
    if gap < 86400:
        hours = int(gap // 3600)
        return f"{hours} hour{'' if hours == 1 else 's'} ago"
    if gap < 2 * 86400:
        return "yesterday"
    if gap < 7 * 86400:
        return f"{int(gap // 86400)} days ago"
    return dt.datetime.fromtimestamp(stamp).strftime("%b %-d, %Y" if os.name != "nt" else "%b %d, %Y")


def recent_files(suffixes: tuple, limit: int = 6) -> list:
    """Files of a kind lately saved in Downloads, Documents or on the Desktop: what "import" most likely means."""
    sp, rows = QStandardPaths, []
    for where in (sp.DownloadLocation, sp.DocumentsLocation, sp.DesktopLocation):
        folder = Path(sp.writableLocation(where) or "")
        try:
            names = os.listdir(folder) if str(folder) not in ("", ".") else []
        except OSError:
            continue
        for name in names:
            if name.lower().endswith(suffixes) and not name.startswith("."):
                try:
                    stamp = (folder / name).stat().st_mtime
                except OSError:
                    continue
                rows.append({"name": name, "path": str(folder / name), "where": folder.name, "when": ago(stamp), "stamp": stamp})
    return sorted(rows, key=lambda r: -r["stamp"])[:limit]


# ================================================================================================ Passwords
class Vault(QObject):
    """The Passwords app's view of the vault every Huginn app shares (see huginn_vault.py).

    It is the browser's own vault file, so a login saved while browsing shows here and one added here fills in the
    browser. Mail keeps its accounts' secrets in it too. Unlocking here can unlock the others for this session, and
    Lock locks them all.
    """
    changed = Signal()
    failed = Signal(str)
    said = Signal(str)
    IDLE_MS = 5 * 60 * 1000                                       # this app alone; with sharing on, the session's hour applies
    CLEAR_MS = 30 * 1000

    def __init__(self, file: Path = None, demo: bool = False):
        super().__init__()
        import huginn_vault as hv
        self._hv = hv
        self._file = hv.VaultFile(file)
        self._session = hv.Session(self._file)
        self._old = DATA_HOME / "passwords.vault"                 # the first Passwords kept its own file: brought across on unlock
        self._demo = demo
        self._misses, self._wait_until = 0, 0.0
        self._copied = ""
        self._demo_rows = []
        if demo:                                                   # for previews: open, with made-up entries, never written
            now = time.time()
            self._demo_rows = [{"id": f"d{i}", "title": t, "username": u, "password": p, "url": s, "note": n, "updated": now - d * 86400}
                               for i, (t, u, p, s, n, d) in enumerate([
                                   ("Nordlys Bank", "val.example", "plum-lantern-otter-quartz", "https://nordlysbank.example", "Card reader lives in the desk drawer.", 12),
                                   ("Mail", "val@example.com", "kT7#mQ2$xP9vLw4z", "https://mail.example", "", 40), ("Trainline", "val@example.com", "summer2019", "https://trains.example", "", 900),
                                   ("Photo prints", "val@example.com", "summer2019", "https://prints.example", "", 700), ("Wi-Fi at home", "", "copper-thistle-banjo-88", "", "Router admin is on 192.168.1.1", 200),
                                   ("Library card", "20418837", "4417", "https://library.example", "", 30), ("Streaming", "val@example.com", "Vx3!pRz8#nQw2Ld", "https://stream.example", "", 3)])]
        self._idle = QTimer(self)
        self._idle.setSingleShot(True)
        self._idle.setInterval(self.IDLE_MS)
        self._idle.timeout.connect(self._idle_out)
        self._wipe = QTimer(self)
        self._wipe.setSingleShot(True)
        self._wipe.setInterval(self.CLEAR_MS)
        self._wipe.timeout.connect(self._clear_clipboard)
        self._step = QTimer(self)                                  # keeping in step with the browser and Mail
        self._step.setInterval(2000)
        self._step.timeout.connect(self.inStep)
        if not demo:
            self._step.start()
            self._session.try_unlock()

    # ------------------------------------------------------------------ state
    def _rows(self) -> list:
        return self._demo_rows if self._demo else self._file.entries

    def _touch(self) -> None:
        if not self.locked:
            self._idle.start()
            self._session.touch()

    exists = Property(bool, lambda self: self._demo or self._file.exists() or self._old.exists(), notify=changed)
    locked = Property(bool, lambda self: not self._demo and self._file.locked(), notify=changed)
    shared = Property(bool, lambda self: self._hv.sharing_on(), notify=changed)
    mailCount = Property(int, lambda self: 0 if self._demo else len(self._file.extras.get("mail") or {}), notify=changed)

    @Slot()
    def inStep(self) -> None:
        """Every couple of seconds: join a session another app opened, lock if another app locked, pick up changes."""
        if self._demo:
            return
        if self._file.locked():
            if self._session.try_unlock():
                self._idle.start()
                self.changed.emit()
            return
        if self._session.locked_elsewhere():
            self._forget()
            self.changed.emit()
            return
        if self._file.refresh():
            self.changed.emit()

    @Slot(bool)
    def setShared(self, on: bool) -> None:
        self._hv.set_sharing(on)
        if on and not self._file.locked():
            self._session.gen = None
            self._session.unlocked()
        elif not on:
            self._session.gen = None
        self.changed.emit()

    def _idle_out(self) -> None:
        if self._hv.sharing_on() and self._session.gen is not None:
            return                                                 # the session's own hour decides, for every app together
        self._forget()
        self.changed.emit()

    def _forget(self) -> None:
        self._file.lock()
        self._session.gen = None
        self._idle.stop()
        self._clear_clipboard()

    # ------------------------------------------------------------------ the door
    @Slot(str, str, result=str)
    def create(self, master: str, again: str) -> str:
        """Make a new, empty vault. Returns "" or why not."""
        if self._file.exists() or self._old.exists():
            return "There is already a vault here."
        if master != again:
            return "The two don't match."
        if len(master) < 10:
            return "Use at least 10 characters. A few unrelated words work well."
        try:
            self._file.create(master)
        except (self._hv.VaultError, OSError) as err:
            return f"Couldn't create the vault: {getattr(err, 'strerror', None) or err}"
        self._session.unlocked()
        self._touch()
        self.changed.emit()
        return ""

    def _bring_old_across(self, master: str) -> str:
        """The first Passwords had a file of its own. Open it with the same master password and move everything
        into the shared vault."""
        from cryptography.exceptions import InvalidTag
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
        try:
            doc = json.loads(self._old.read_text(encoding="utf-8"))
            salt, nonce, sealed = (base64.b64decode(doc[k]) for k in ("salt", "nonce", "data"))
            key = Scrypt(salt=salt, length=32, n=int(doc["n"]), r=int(doc.get("r", 8)), p=int(doc.get("p", 1))).derive(master.encode("utf-8"))
            rows = json.loads(AESGCM(key).decrypt(nonce, sealed, b"huginn-vault-1").decode("utf-8"))
        except InvalidTag:
            return "That isn't the master password."
        except (OSError, ValueError, KeyError, TypeError):
            return "The old vault file is damaged."
        try:
            if self._file.exists():
                self._file.unlock(master)
            else:
                self._file.create(master)
            for r in rows:
                self._file.put("", r.get("site", ""), r.get("user", ""), r.get("password", ""), r.get("title", ""), r.get("notes", ""))
            os.replace(self._old, self._old.with_suffix(".vault.moved"))
        except self._hv.WrongPassword:
            return "The browser's vault has a different master password. Unlock with that one; the old file is left as it is."
        except (self._hv.VaultError, OSError) as err:
            return f"Couldn't move the old vault across: {getattr(err, 'strerror', None) or err}"
        return ""

    @Slot(str, result=str)
    def unlock(self, master: str) -> str:
        wait = self._wait_until - time.monotonic()
        if wait > 0:
            return f"Too many tries. Wait {int(wait) + 1} seconds."
        try:
            if self._old.exists() and not self._file.exists():
                why = self._bring_old_across(master)
                if why:
                    raise self._hv.WrongPassword(why) if "master password" in why else self._hv.VaultError(why)
            else:
                self._file.unlock(master)
        except self._hv.WrongPassword as err:
            self._misses += 1
            if self._misses >= 5:                                  # slow down someone trying one after another
                self._wait_until = time.monotonic() + min(300, 5 * 2 ** (self._misses - 5))
            return str(err)
        except OSError as err:
            return f"Couldn't read the vault: {err.strerror or err}"
        except (self._hv.VaultError, ValueError, KeyError) as err:
            return (str(err) if isinstance(err, self._hv.VaultError) else "The vault file is damaged.") + " A spare copy sits beside it (passwords.vault.bak)."
        self._misses = 0
        self._session.unlocked()
        self._touch()
        self.changed.emit()
        return ""

    @Slot()
    def lock(self) -> None:
        """Lock here, and in the browser and Mail too."""
        if self._demo or self._file.locked():
            return
        self._session.lock_everywhere()
        self._forget()
        self.changed.emit()

    @Slot(str, str, str, result=str)
    def changeMaster(self, old: str, new: str, again: str) -> str:
        if self._file.locked():
            return "Unlock the vault first."
        if new != again:
            return "The two new ones don't match."
        if len(new) < 10:
            return "Use at least 10 characters."
        try:
            self._file.change_master(old, new)
        except self._hv.WrongPassword:
            return "That isn't the current master password."
        except (self._hv.VaultError, OSError) as err:
            return f"Couldn't save: {getattr(err, 'strerror', None) or err}"
        self.said.emit("The master password is changed, for the browser and Mail too.")
        return ""

    # ------------------------------------------------------------------ entries
    @staticmethod
    def _site(row: dict) -> str:
        url = row.get("url") or ""
        if not url:
            return row.get("place", "")
        host = urllib.parse.urlsplit(url).hostname or ""
        return host[4:] if host.startswith("www.") else host

    def _health(self, row: dict, sites: dict) -> str:
        pw = row.get("password", "")
        if not pw:
            return ""
        if len(sites.get(pw, ())) > 1:
            return "reused"
        return "weak" if self.strength(pw) < 2 else ""

    @Property("QVariantList", notify=changed)
    def entries(self):
        """What the list shows. Passwords stay out of it; ask for one entry to see its own."""
        sites = {}
        for row in self._rows():
            sites.setdefault(row.get("password", ""), set()).add(self._site(row) or row.get("id"))
        out = [{"id": r["id"], "title": r.get("title") or self._site(r) or "Untitled", "user": r.get("username", ""), "site": self._site(r),
                "health": self._health(r, sites)} for r in self._rows() if r.get("id")]
        return sorted(out, key=lambda r: r["title"].lower())

    @Property(int, notify=changed)
    def troubled(self):
        return sum(1 for r in self.entries if r["health"])

    @Slot(str, result="QVariantMap")
    def entry(self, ident: str):
        self._touch()
        row = next((r for r in self._rows() if r.get("id") == ident), None)
        if not row:
            return {}
        return {"id": row["id"], "title": row.get("title", ""), "user": row.get("username", ""), "password": row.get("password", ""),
                "site": (row.get("url") or row.get("place", "")), "notes": row.get("note", ""), "previous": row.get("previous", ""),
                "strength": self.strength(row.get("password", "")), "changedText": ago(row["updated"]) if row.get("updated") else "",
                "usedText": ago(row["used"]) if row.get("used") else ""}

    @Slot(str, "QVariantMap", result=str)
    def save(self, ident: str, fields) -> str:
        """Add an entry (ident "") or change one. Returns its id, or "" if it couldn't be saved."""
        if self.locked:
            return ""
        self._touch()
        clean = {k: str(fields.get(k, "")).strip() if k != "password" else str(fields.get(k, "")) for k in ("title", "user", "password", "site", "notes")}
        if not any(clean.values()):
            self.failed.emit("There is nothing to save yet.")
            return ""
        if self._demo:
            row = next((r for r in self._demo_rows if r["id"] == ident), None) or {"id": uuid.uuid4().hex}
            row.update({"title": clean["title"], "username": clean["user"], "password": clean["password"], "url": clean["site"], "note": clean["notes"], "updated": time.time()})
            if row not in self._demo_rows:
                self._demo_rows.append(row)
            self.changed.emit()
            return row["id"]
        try:
            self._file.refresh()
            row = self._file.put(ident, clean["site"], clean["user"], clean["password"], clean["title"], clean["notes"])
        except (self._hv.VaultError, OSError) as err:
            self.failed.emit(f"Couldn't save: {getattr(err, 'strerror', None) or err}")
            return ""
        self.changed.emit()
        return row["id"]

    @Slot(str)
    def remove(self, ident: str) -> None:
        if self.locked:
            return
        if self._demo:
            self._demo_rows = [r for r in self._demo_rows if r["id"] != ident]
        else:
            try:
                self._file.refresh()
                self._file.delete(ident)
            except (self._hv.VaultError, OSError) as err:
                self.failed.emit(f"Couldn't delete it: {getattr(err, 'strerror', None) or err}")
        self._touch()
        self.changed.emit()

    # ------------------------------------------------------------------ making and judging passwords
    @Slot(int, bool, bool, result=str)
    def generate(self, length: int, digits: bool, symbols: bool) -> str:
        """A random password from the system's own randomness, with at least one of each kind asked for."""
        length = max(8, min(64, length))
        sets = [string.ascii_lowercase, string.ascii_uppercase] + ([string.digits] if digits else []) + (["!@#$%^&*-_=+?"] if symbols else [])
        while True:
            pw = "".join(secrets.choice("".join(sets)) for _ in range(length))
            if all(any(c in s for c in pw) for s in sets):
                return pw

    @Slot(int, result=str)
    def phrase(self, words: int) -> str:
        """A passphrase: a few plain words, easy to type and hard to guess."""
        return "-".join(secrets.choice(WORDS) for _ in range(max(3, min(8, words))))

    @Slot(str, result=int)
    def strength(self, pw: str) -> int:
        """0 (none) to 4 (strong): a plain estimate from length and variety, marked down for the obvious."""
        if not pw:
            return 0
        kinds = sum(bool(re.search(p, pw)) for p in (r"[a-z]", r"[A-Z]", r"\d", r"[^A-Za-z0-9]"))
        pool = {1: 26, 2: 52, 3: 62, 4: 80}[kinds]
        import math
        bits = len(pw) * math.log2(pool)
        low = pw.lower()
        if len(set(pw)) <= max(2, len(pw) // 4) or any(w in low for w in ("password", "qwerty", "123456", "letmein", "abc123", "iloveyou", "admin")):
            bits = min(bits, 20)
        if re.fullmatch(r"[A-Za-z]+\d{1,4}!?", pw):                 # Name2024!
            bits *= 0.45
        return 1 if bits < 36 else 2 if bits < 55 else 3 if bits < 75 else 4

    # ------------------------------------------------------------------ the clipboard
    @Slot(str, str)
    def copy(self, ident: str, what: str) -> None:
        """Copy a name or a password. A copied password is wiped from the clipboard half a minute later."""
        row = self.entry(ident)
        board = QGuiApplication.clipboard() if QGuiApplication.instance() else None
        if not row or not board or what not in ("user", "password", "site"):
            return
        board.setText(row.get(what, ""))
        if what == "password":
            self._copied = row.get(what, "")
            self._wipe.start()
            self.said.emit("Password copied. It leaves the clipboard in 30 seconds.")
        else:
            self.said.emit("Copied.")

    def _clear_clipboard(self) -> None:
        board = QGuiApplication.clipboard() if QGuiApplication.instance() else None
        if board and self._copied and board.text() == self._copied:
            board.clear()
        self._copied = ""
        self._wipe.stop()

    @Slot(str, result="QVariantList")
    def codesFor(self, ident: str) -> list:
        """The two-factor codes Authenticator keeps for this login's site (the same vault), worked out now."""
        row = next((r for r in self._rows() if r.get("id") == ident), None)
        if not row or self._demo or self._file.locked():
            return []
        import huginn_auth
        return huginn_auth.codes_for_login(self._file, row.get("url") or "", row.get("title") or "")

    @Slot(str)
    def copyCode(self, code: str) -> None:
        board = QGuiApplication.clipboard() if QGuiApplication.instance() else None
        if board and code:
            board.setText(code)
            self._copied = code
            self._wipe.start()
            self.said.emit("Code copied. It leaves the clipboard in 30 seconds.")

    @Slot(str)
    def visit(self, ident: str) -> None:
        """Open the entry's website in the browser, where it will offer to fill it in."""
        from PySide6.QtGui import QDesktopServices
        row = next((r for r in self._rows() if r.get("id") == ident), None)
        if row and row.get("url"):
            QDesktopServices.openUrl(QUrl(row["url"]))

    # ------------------------------------------------------------------ moving in and out
    @Slot(str, result=int)
    def importCsv(self, path: str) -> int:
        """Bring in what a browser or another manager exported (name/title, url, username, password, note columns)."""
        if self.locked or self._demo:
            return 0
        path = QUrl(path).toLocalFile() if path.startswith("file:") else path
        try:
            with open(path, newline="", encoding="utf-8-sig") as f:
                rows = list(csv.DictReader(f))
        except (OSError, csv.Error, UnicodeDecodeError) as err:
            self.failed.emit(f"Couldn't read that file: {getattr(err, 'strerror', None) or err}")
            return 0

        def pick(row, *names):
            low = {(k or "").strip().lower(): (v or "") for k, v in row.items()}
            return next((low[n] for n in names if low.get(n)), "")
        hv = self._hv
        self._file.refresh()
        have = {(r.get("url") or r.get("place", ""), r.get("username", ""), r.get("password", "")) for r in self._file.entries}
        added = 0
        try:
            for row in rows:
                site, user = pick(row, "url", "login_uri", "website", "origin_url"), pick(row, "username", "login_username", "login", "email")
                password = pick(row, "password", "login_password")
                mark = (hv.login_origin(site) or site.strip(), user, password)
                if not password and not user or mark in have:
                    continue
                have.add(mark)
                self._file.put("", site, user, password, pick(row, "name", "title", "account"), pick(row, "note", "notes", "comment"))
                added += 1
        except (hv.VaultError, OSError) as err:
            self.failed.emit(f"Couldn't save: {getattr(err, 'strerror', None) or err}")
        self._touch()
        self.changed.emit()
        self.said.emit(f"{added} added." + (" That file holds your passwords in the open: delete it once you've checked they're all here." if added else " Nothing new was in that file."))
        return added

    @Slot(str, result=bool)
    def exportCsv(self, path: str) -> bool:
        """Write everything out in the open, in the columns browsers read. For moving house, not for keeping."""
        if self.locked:
            return False
        path = QUrl(path).toLocalFile() if path.startswith("file:") else path
        out = io.StringIO()
        writer = csv.writer(out)
        writer.writerow(["name", "url", "username", "password", "note"])
        for r in self._rows():
            writer.writerow([r.get("title", ""), r.get("url") or r.get("place", ""), r.get("username", ""), r.get("password", ""), r.get("note", "")])
        try:
            write_whole(Path(path), out.getvalue().encode("utf-8"))
        except OSError as err:
            self.failed.emit(f"Couldn't write it: {err.strerror or err}")
            return False
        self.said.emit("Exported. That file is not protected: move it where it's going, then delete it.")
        return True

    @Slot(result="QVariantList")
    def importChoices(self):
        return recent_files((".csv",))

    exportPath = Property(str, lambda self: str(Path(QStandardPaths.writableLocation(QStandardPaths.DocumentsLocation) or Path.home()) / "Huginn passwords.csv"), constant=True)


WORDS = ("amber anchor apple arrow autumn badger bamboo banjo basket beacon berry birch biscuit blanket bonfire breeze bridge bronze "
         "butter cabin cactus candle canyon carpet castle cedar cherry cinder circus clover cobalt comet copper coral cotton cradle "
         "cricket crystal daisy dancer desert dragon drift eagle ember engine falcon feather fern fiddle forest fossil fountain fox "
         "garden garlic ginger glacier goblet granite harbor hazel hedge honey island ivory jacket jasmine jungle kettle kitten ladder "
         "lagoon lantern lemon lilac lizard lobster magnet mango maple marble meadow melon mirror monsoon mountain mustard nectar "
         "needle nutmeg oasis ocean olive orbit orchid otter oyster paddle pebble pepper pickle pigeon pillow planet plum pocket "
         "pumpkin puzzle quartz rabbit raven ribbon river rocket saddle saffron salmon sandal shadow silver sparrow spruce squirrel "
         "sunset teapot thistle thunder tiger timber tulip tunnel turtle velvet violet walnut willow window winter yonder zephyr").split()


# ================================================================================================= Contacts
def _vc_out(text: str) -> str:
    text = str(text).replace(chr(92), chr(92) * 2).replace("\n", chr(92) + "n")
    return text.replace(";", chr(92) + ";").replace(",", chr(92) + ",")


def _vc_in(text: str) -> str:
    return re.sub(r"\\(.)", lambda m: "\n" if m.group(1) in "nN" else m.group(1), text)


def _vc_split(text: str, sep: str = ";") -> list:
    """Split on separators that aren't escaped."""
    parts, now, i = [], "", 0
    while i < len(text):
        if text[i] == "\\" and i + 1 < len(text):
            now += text[i:i + 2]
            i += 2
            continue
        if text[i] == sep:
            parts.append(now)
            now = ""
        else:
            now += text[i]
        i += 1
    return parts + [now]


def read_vcards(text: str) -> list:
    """Every card in a .vcf, as plain dicts. What Huginn has no field for is kept in "extra" and written back."""
    lines = re.sub(r"\r?\n[ \t]", "", text.replace("\r\n", "\n")).split("\n")
    cards, now = [], None
    for line in lines:
        upper = line.strip().upper()
        if upper == "BEGIN:VCARD":
            now = {"id": "", "name": "", "given": "", "family": "", "org": "", "title": "", "phones": [], "emails": [], "address": "",
                   "birthday": "", "site": "", "notes": "", "fav": False, "extra": []}
            continue
        if now is None or ":" not in line:
            continue
        if upper == "END:VCARD":
            if not now["name"]:
                now["name"] = " ".join(p for p in (now["given"], now["family"]) if p) or now["org"] or (now["emails"][0]["value"] if now["emails"] else "")
            if now["name"] or now["phones"] or now["emails"]:
                now["id"] = now["id"] or uuid.uuid4().hex
                cards.append(now)
            now = None
            continue
        head, value = line.split(":", 1)
        bits = head.split(";")
        key = bits[0].split(".")[-1].upper()                       # "item1.TEL" is TEL
        kinds = [k.lower() for b in bits[1:] for k in (b.split("=", 1)[1] if "=" in b else b).split(",")]
        kind = next((k for k in kinds if k in ("cell", "mobile", "home", "work", "fax", "other", "iphone", "main")), "")
        kind = {"cell": "mobile", "iphone": "mobile"}.get(kind, kind)
        if key == "FN":
            now["name"] = _vc_in(value).strip()
        elif key == "N":
            parts = [_vc_in(p).strip() for p in _vc_split(value)] + [""] * 5
            now["family"], now["given"] = parts[0], " ".join(p for p in (parts[1], parts[2]) if p)
        elif key == "ORG":
            now["org"] = " · ".join(p for p in (_vc_in(p).strip() for p in _vc_split(value)) if p)
        elif key == "TITLE":
            now["title"] = _vc_in(value).strip()
        elif key == "TEL":
            now["phones"].append({"kind": kind or "mobile", "value": _vc_in(value).strip().removeprefix("tel:")})
        elif key == "EMAIL":
            now["emails"].append({"kind": kind or "home", "value": _vc_in(value).strip()})
        elif key == "ADR" and not now["address"]:
            parts = [_vc_in(p).strip() for p in _vc_split(value)]
            now["address"] = "\n".join(p for p in parts if p)
        elif key == "BDAY":
            m = re.match(r"(\d{4})-?(\d{2})-?(\d{2})", value.strip())
            now["birthday"] = "-".join(m.groups()) if m else ""
        elif key == "URL" and not now["site"]:
            now["site"] = _vc_in(value).strip()
        elif key == "NOTE":
            now["notes"] = _vc_in(value)
        elif key == "UID":
            now["id"] = re.sub(r"[^A-Za-z0-9-]", "", value)[:64]
        elif key == "CATEGORIES":
            cats = [c.strip() for c in _vc_split(value, ",")]
            now["fav"] = any(c.lower() in ("favourite", "favorite", "starred") for c in cats)
            rest = [c for c in cats if c.lower() not in ("favourite", "favorite", "starred") and c]
            if rest:
                now["extra"].append("CATEGORIES:" + ",".join(rest))
        elif key not in ("VERSION", "PRODID", "REV"):
            now["extra"].append(line)                              # photos, nicknames, anniversaries: carried, not shown
    return cards


def write_vcards(cards: list) -> str:
    out = []

    def put(line: str) -> None:                                    # fold at 75 bytes, as the format asks
        raw = line.encode("utf-8")
        first = True
        while raw:
            room = 75 if first else 74
            cut = min(room, len(raw))
            while cut < len(raw) and (raw[cut] & 0xC0) == 0x80:
                cut -= 1
            out.append(("" if first else " ") + raw[:cut].decode("utf-8"))
            raw, first = raw[cut:], False
    for c in cards:
        put("BEGIN:VCARD")
        put("VERSION:3.0")
        put("UID:" + c["id"])
        put("FN:" + _vc_out(c["name"]))
        given, family = c.get("given", ""), c.get("family", "")
        if not given and not family and c["name"] and c["name"] != c.get("org"):
            given, _, family = c["name"].rpartition(" ") if " " in c["name"] else (c["name"], "", "")
        put(f"N:{_vc_out(family)};{_vc_out(given)};;;")
        if c.get("org"):
            put("ORG:" + _vc_out(c["org"]))
        if c.get("title"):
            put("TITLE:" + _vc_out(c["title"]))
        for p in c.get("phones", []):
            if p.get("value"):
                put(f"TEL;TYPE={'CELL' if p.get('kind') == 'mobile' else p.get('kind', 'other').upper()}:{_vc_out(p['value'])}")
        for e in c.get("emails", []):
            if e.get("value"):
                put(f"EMAIL;TYPE={e.get('kind', 'home').upper()}:{_vc_out(e['value'])}")
        if c.get("address"):
            put("ADR:;;" + _vc_out(c["address"].replace("\n", ", ")) + ";;;;")
        if c.get("birthday"):
            put("BDAY:" + c["birthday"])
        if c.get("site"):
            put("URL:" + _vc_out(c["site"]))
        if c.get("notes"):
            put("NOTE:" + _vc_out(c["notes"]))
        others = next((line.split(":", 1)[1] for line in c.get("extra", []) if line.upper().startswith("CATEGORIES:")), "")
        if c.get("fav") or others:
            put("CATEGORIES:" + ",".join(x for x in ("Favourite" if c.get("fav") else "", others) if x))
        for line in c.get("extra", []):
            if not line.upper().startswith("CATEGORIES:"):
                put(line)
        put("END:VCARD")
    return "\r\n".join(out) + ("\r\n" if out else "")


class Contacts(QObject):
    """An address book kept as one ordinary .vcf file, so any other app or phone can read it."""
    changed = Signal()
    failed = Signal(str)
    said = Signal(str)

    def __init__(self, demo: bool = False, file: Path = None):
        super().__init__()
        self._file = file or DATA_HOME / "contacts.vcf"
        self._demo = demo
        self._cards = []
        if demo:
            self._cards = read_vcards(DEMO_CARDS)
        else:
            try:
                self._cards = read_vcards(self._file.read_text(encoding="utf-8", errors="replace"))
            except OSError:
                self._cards = []
            self._gone, self._seen = set(), self._stamp()
            self._watch = QTimer(self)                             # another window (or Mail handing over a card) may add people
            self._watch.setInterval(4000)
            self._watch.timeout.connect(self._absorb)
            self._watch.start()

    def _stamp(self):
        try:
            st = self._file.stat()
            return st.st_mtime_ns, st.st_size
        except OSError:
            return None

    def _absorb(self) -> None:
        """Take in people another window added, keeping out the ones this window removed."""
        if self._stamp() == self._seen:
            return
        self._seen = self._stamp()
        try:
            disk = read_vcards(self._file.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            return
        mine = {c["id"] for c in self._cards}
        fresh = [c for c in disk if c["id"] not in mine and c["id"] not in self._gone]
        if fresh:
            self._cards.extend(fresh)
            self.changed.emit()

    def _keep(self) -> bool:
        if self._demo:
            return True
        try:
            self._seen = None
            self._absorb()                                         # never write over what another window added meanwhile
            write_whole(self._file, write_vcards(self._cards).encode("utf-8"))
            self._seen = self._stamp()
            return True
        except OSError as err:
            self.failed.emit(f"Couldn't save your contacts: {err.strerror or err}")
            return False

    @staticmethod
    def _sort_key(card: dict) -> str:
        return card["name"].lower()

    @staticmethod
    def _initials(name: str) -> str:
        words = [w for w in re.split(r"[\s\-]+", name) if w and w[0].isalnum()]
        return ((words[0][0] + (words[-1][0] if len(words) > 1 else "")) if words else "?").upper()

    @Property("QVariantList", notify=changed)
    def people(self):
        rows = []
        for c in sorted(self._cards, key=self._sort_key):
            first = c["name"][:1].upper()
            rows.append({"id": c["id"], "name": c["name"], "sub": c["org"] or (c["emails"][0]["value"] if c["emails"] else (c["phones"][0]["value"] if c["phones"] else "")),
                         "initials": self._initials(c["name"]), "letter": first if first.isalpha() else "#", "fav": c["fav"],
                         "find": " ".join([c["name"], c["org"], c["notes"]] + [p["value"] for p in c["phones"]] + [e["value"] for e in c["emails"]]).lower()})
        return rows

    count = Property(int, lambda self: len(self._cards), notify=changed)

    @Slot(str, result="QVariantMap")
    def person(self, ident: str):
        c = next((c for c in self._cards if c["id"] == ident), None)
        if not c:
            return {}
        out = {k: v for k, v in c.items() if k != "extra"}
        out["initials"] = self._initials(c["name"])
        out["birthdayText"] = ""
        if c["birthday"]:
            try:
                born = dt.date.fromisoformat(c["birthday"])
                today = dt.date.today()
                turn = born.replace(year=today.year) if (born.month, born.day) != (2, 29) else dt.date(today.year, 3, 1)
                if turn < today:
                    turn = turn.replace(year=today.year + 1)
                days = (turn - today).days
                out["birthdayText"] = born.strftime("%B %-d" if os.name != "nt" else "%B %d") + \
                    (" · today" if days == 0 else " · tomorrow" if days == 1 else f" · in {days} days" if days < 31 else "")
            except ValueError:
                pass
        return out

    @Slot(str, "QVariantMap", result=str)
    def save(self, ident: str, fields) -> str:
        """Add someone (ident "") or change them. Returns their id, or "" with a reason sent to `failed`."""
        name = str(fields.get("name", "")).strip()
        phones = [{"kind": str(p.get("kind", "mobile")), "value": str(p.get("value", "")).strip()} for p in fields.get("phones", []) if str(p.get("value", "")).strip()]
        emails = [{"kind": str(e.get("kind", "home")), "value": str(e.get("value", "")).strip()} for e in fields.get("emails", []) if str(e.get("value", "")).strip()]
        org = str(fields.get("org", "")).strip()
        if not (name or org or phones or emails):
            self.failed.emit("Give them a name, a number or an email first.")
            return ""
        bad = next((e["value"] for e in emails if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", e["value"])), "")
        if bad:
            self.failed.emit(f"“{bad}” doesn't look like an email address.")
            return ""
        birthday = str(fields.get("birthday", "")).strip()
        if birthday:
            try:
                birthday = dt.date.fromisoformat(birthday).isoformat()
            except ValueError:
                self.failed.emit("Write a birthday as year-month-day, like 1990-04-23.")
                return ""
        card = next((c for c in self._cards if c["id"] == ident), None)
        before = [dict(c) for c in self._cards]
        if card is None:
            card = {"id": uuid.uuid4().hex, "fav": False, "extra": [], "given": "", "family": ""}
            self._cards.append(card)
        if card.get("name") != name:
            card["given"], card["family"] = "", ""                 # the parts are worked out again from the new name
        card.update({"name": name or org or (emails[0]["value"] if emails else phones[0]["value"]), "org": org, "title": str(fields.get("title", "")).strip(),
                     "phones": phones, "emails": emails, "address": str(fields.get("address", "")).strip(), "birthday": birthday,
                     "site": str(fields.get("site", "")).strip(), "notes": str(fields.get("notes", "")).strip()})
        if not self._keep():
            self._cards = before
            return ""
        self.changed.emit()
        return card["id"]

    @Slot(str)
    def toggleFav(self, ident: str) -> None:
        card = next((c for c in self._cards if c["id"] == ident), None)
        if card:
            card["fav"] = not card["fav"]
            self._keep()
            self.changed.emit()

    @Slot(str)
    def remove(self, ident: str) -> None:
        before = list(self._cards)
        self._cards = [c for c in self._cards if c["id"] != ident]
        if not self._demo:
            self._gone.add(ident)
        if not self._keep():
            self._cards = before
        self.changed.emit()

    @Slot(str, result=int)
    def importFile(self, path: str) -> int:
        """Add the people in a .vcf from a phone or another address book. Someone already here (same name and same
        first number or email) is not added twice."""
        path = QUrl(path).toLocalFile() if path.startswith("file:") else path
        try:
            new = read_vcards(Path(path).read_text(encoding="utf-8", errors="replace"))
        except OSError as err:
            self.failed.emit(f"Couldn't read that file: {err.strerror or err}")
            return 0

        def mark(c):
            return (c["name"].lower(), (c["phones"][0]["value"] if c["phones"] else ""), (c["emails"][0]["value"].lower() if c["emails"] else ""))
        have, ids, before, added = {mark(c) for c in self._cards}, {c["id"] for c in self._cards}, list(self._cards), 0
        for c in new:
            if mark(c) in have:
                continue
            if c["id"] in ids:
                c["id"] = uuid.uuid4().hex
            have.add(mark(c))
            ids.add(c["id"])
            self._cards.append(c)
            added += 1
        if added and not self._keep():
            self._cards = before
            return 0
        self.changed.emit()
        self.said.emit(f"{added} added." if added else ("Everyone in that file is already here." if new else "No contacts were found in that file."))
        return added

    @Slot(result="QVariantList")
    def importChoices(self):
        return recent_files((".vcf", ".vcard"))

    @Slot(str, str, result=bool)
    def exportFile(self, path: str, ident: str) -> bool:
        """Write one person (or everyone, ident "") to a .vcf to send or to move to a phone."""
        path = QUrl(path).toLocalFile() if path.startswith("file:") else path
        cards = [c for c in self._cards if not ident or c["id"] == ident]
        try:
            write_whole(Path(path), write_vcards(cards).encode("utf-8"), 0o644)
        except OSError as err:
            self.failed.emit(f"Couldn't write it: {err.strerror or err}")
            return False
        self.said.emit(f"Saved “{Path(path).name}” in {Path(path).parent.name or '/'}.")
        return True

    @Slot(str, result=str)
    def exportPath(self, ident: str) -> str:
        folder = Path(QStandardPaths.writableLocation(QStandardPaths.DocumentsLocation) or Path.home())
        card = next((c for c in self._cards if c["id"] == ident), None)
        return str(folder / ((re.sub(r"[/\\\0]", " ", card["name"]) if card else "Contacts") + ".vcf"))

    @Slot(str, str)
    def reach(self, kind: str, value: str) -> None:
        """Start an email, a call or a web page with whatever app handles it."""
        from PySide6.QtGui import QDesktopServices
        url = {"email": "mailto:" + value, "phone": "tel:" + re.sub(r"[^\d+]", "", value)}.get(kind, value if "://" in value else "https://" + value)
        if not QDesktopServices.openUrl(QUrl(url)):
            self.failed.emit("No app is set up for that.")


DEMO_CARDS = """BEGIN:VCARD
VERSION:3.0
FN:Astrid Lindqvist
ORG:Nordlys Studio
TITLE:Art Director
TEL;TYPE=CELL:+46 70 123 45 67
EMAIL;TYPE=WORK:astrid@nordlys.example
BDAY:1988-11-14
CATEGORIES:Favourite
NOTE:Met at the print fair. Prefers calls after lunch.
END:VCARD
BEGIN:VCARD
VERSION:3.0
FN:Ben Okafor
TEL;TYPE=CELL:+1 312 555 0142
EMAIL;TYPE=HOME:ben.okafor@example.com
ADR:;;14 Larch Street;Chicago;IL;60614;USA
END:VCARD
BEGIN:VCARD
VERSION:3.0
FN:Carmen Ruiz
ORG:Ruiz & Daughters Bakery
TEL;TYPE=WORK:+1 312 555 0198
EMAIL;TYPE=WORK:orders@ruizbakery.example
URL:ruizbakery.example
CATEGORIES:Favourite
END:VCARD
BEGIN:VCARD
VERSION:3.0
FN:Dmitri Volkov
TEL;TYPE=CELL:+1 773 555 0107
END:VCARD
BEGIN:VCARD
VERSION:3.0
FN:Freya Halloran
ORG:Halloran Dental
TEL;TYPE=WORK:+1 312 555 0155
EMAIL;TYPE=WORK:front.desk@hallorandental.example
END:VCARD
BEGIN:VCARD
VERSION:3.0
FN:Gus Tanaka
TEL;TYPE=CELL:+1 708 555 0121
EMAIL;TYPE=HOME:gus.t@example.com
BDAY:1994-03-02
END:VCARD
BEGIN:VCARD
VERSION:3.0
FN:Mum
TEL;TYPE=HOME:+1 815 555 0170
TEL;TYPE=CELL:+1 815 555 0171
CATEGORIES:Favourite
END:VCARD
BEGIN:VCARD
VERSION:3.0
FN:Priya Raman
ORG:Lakeside Vets
TEL;TYPE=WORK:+1 312 555 0133
END:VCARD
"""


# ================================================================================================== Weather
WMO = {0: ("Clear", "sun"), 1: ("Mostly clear", "sun"), 2: ("Partly cloudy", "cloudsun"), 3: ("Cloudy", "cloud"), 45: ("Fog", "fog"), 48: ("Freezing fog", "fog"),
       51: ("Light drizzle", "rain"), 53: ("Drizzle", "rain"), 55: ("Heavy drizzle", "rain"), 56: ("Freezing drizzle", "rain"), 57: ("Freezing drizzle", "rain"),
       61: ("Light rain", "rain"), 63: ("Rain", "rain"), 65: ("Heavy rain", "rain"), 66: ("Freezing rain", "rain"), 67: ("Freezing rain", "rain"),
       71: ("Light snow", "snow"), 73: ("Snow", "snow"), 75: ("Heavy snow", "snow"), 77: ("Snow grains", "snow"), 80: ("Light showers", "rain"),
       81: ("Showers", "rain"), 82: ("Heavy showers", "rain"), 85: ("Snow showers", "snow"), 86: ("Heavy snow showers", "snow"),
       95: ("Thunderstorm", "storm"), 96: ("Thunderstorm with hail", "storm"), 99: ("Thunderstorm with hail", "storm")}


class Weather(QObject):
    """The forecast for places you pick by name. Nothing works out where you are: the only thing sent anywhere is the
    latitude and longitude of the place you chose, to open-meteo.com, which needs no account or key."""
    changed = Signal()
    found = Signal()
    failed = Signal(str)
    _arrived = Signal(str, "QVariant", str)
    FORECAST = "https://api.open-meteo.com/v1/forecast"
    SEARCH = "https://geocoding-api.open-meteo.com/v1/search"

    def __init__(self, demo: bool = False, file: Path = None):
        super().__init__()
        self._file = file or DATA_HOME / "weather.json"
        self._demo = demo
        self._places, self._at, self._data, self._got = [], 0, {}, {}
        self._loading, self._error, self._matches, self._searching = False, "", [], False
        imperial = QLocale().measurementSystem() != QLocale.MeasurementSystem.MetricSystem
        self._unit = "f" if imperial else "c"
        if demo:
            self._places = [{"name": "Chicago", "region": "Illinois, United States", "lat": 41.85, "lon": -87.65},
                            {"name": "Oslo", "region": "Norway", "lat": 59.91, "lon": 10.75}]
            self._unit = "f"
            self._data = {"0": demo_forecast()}
            self._got = {"0": time.time()}
        else:
            try:
                saved = json.loads(self._file.read_text(encoding="utf-8"))
                self._places = [p for p in saved.get("places", []) if isinstance(p, dict) and "lat" in p and "lon" in p][:12]
                self._unit = saved.get("unit") if saved.get("unit") in ("c", "f") else self._unit
                self._at = min(int(saved.get("at", 0)), max(0, len(self._places) - 1))
                self._data = saved.get("data", {}) if isinstance(saved.get("data"), dict) else {}
                self._got = saved.get("got", {}) if isinstance(saved.get("got"), dict) else {}
            except (OSError, ValueError, TypeError):
                pass
        self._arrived.connect(self._on_arrived)
        self._tick = QTimer(self)
        self._tick.setInterval(30 * 60 * 1000)
        self._tick.timeout.connect(self.refresh)
        if not demo:
            self._tick.start()
            QTimer.singleShot(0, self._refresh_if_old)

    def _keep(self) -> None:
        if self._demo:
            return
        try:
            write_whole(self._file, json.dumps({"places": self._places, "unit": self._unit, "at": self._at, "data": self._data, "got": self._got}).encode(), 0o644)
        except OSError:
            pass

    def _key(self) -> str:
        return str(self._at)

    def _fetch(self, url: str) -> dict:
        """One web request. Tests stand in for this."""
        req = urllib.request.Request(url, headers={"User-Agent": "HuginnWeather/1.0"})
        with urllib.request.urlopen(req, timeout=12) as reply:
            return json.loads(reply.read().decode("utf-8"))

    def _go(self, what: str, url: str, tag: str) -> None:
        def work():
            try:
                self._arrived.emit(what, self._fetch(url), tag)
            except Exception as err:                               # no network, a timeout, a bad reply: all "couldn't reach"
                self._arrived.emit(what, {"__error": str(getattr(err, "reason", err))}, tag)
        self._worker = threading.Thread(target=work, daemon=True)
        self._worker.start()

    # ------------------------------------------------------------------ places
    places = Property("QVariantList", lambda self: list(self._places), notify=changed)
    current = Property(int, lambda self: self._at, notify=changed)
    unit = Property(str, lambda self: self._unit, notify=changed)
    loading = Property(bool, lambda self: self._loading, notify=changed)
    error = Property(str, lambda self: self._error, notify=changed)
    matches = Property("QVariantList", lambda self: list(self._matches), notify=found)
    searching = Property(bool, lambda self: self._searching, notify=found)

    @Slot(str)
    def search(self, text: str) -> None:
        text = text.strip()
        if len(text) < 2:
            self._matches, self._searching = [], False
            self.found.emit()
            return
        self._searching = True
        self.found.emit()
        self._go("search", self.SEARCH + "?" + urllib.parse.urlencode({"name": text, "count": 6, "language": "en", "format": "json"}), text)

    @Slot(int)
    def add(self, index: int) -> None:
        if not 0 <= index < len(self._matches) or len(self._places) >= 12:
            return
        m = self._matches[index]
        same = next((i for i, p in enumerate(self._places) if abs(p["lat"] - m["lat"]) < 0.05 and abs(p["lon"] - m["lon"]) < 0.05), -1)
        if same >= 0:
            self._at = same
        else:
            self._places.append({k: m[k] for k in ("name", "region", "lat", "lon")})
            self._at = len(self._places) - 1
        self._matches = []
        self.found.emit()
        self._keep()
        self.changed.emit()
        self.refresh()

    @Slot(int)
    def choose(self, index: int) -> None:
        if 0 <= index < len(self._places) and index != self._at:
            self._at = index
            self._error = ""
            self._keep()
            self.changed.emit()
            self._refresh_if_old()

    @Slot(int)
    def forget(self, index: int) -> None:
        if not 0 <= index < len(self._places):
            return
        self._places.pop(index)
        data, got = {}, {}
        for key in list(self._data):                               # the saved forecasts are numbered by place: renumber them
            i = int(key)
            if i != index:
                data[str(i - (i > index))], got[str(i - (i > index))] = self._data[key], self._got.get(key, 0)
        self._data, self._got = data, got
        self._at = max(0, min(self._at - (self._at > index), len(self._places) - 1))
        self._keep()
        self.changed.emit()

    @Slot()
    def flipUnit(self) -> None:
        self._unit = "c" if self._unit == "f" else "f"
        self._keep()
        self.changed.emit()
        self.refresh()

    def _refresh_if_old(self) -> None:
        if self._places and time.time() - self._got.get(self._key(), 0) > 20 * 60:
            self.refresh()

    @Slot()
    def refresh(self) -> None:
        if self._demo or not self._places or self._loading:
            return
        p = self._places[self._at]
        query = {"latitude": p["lat"], "longitude": p["lon"], "timezone": "auto", "forecast_days": 8,
                 "current": "temperature_2m,apparent_temperature,relative_humidity_2m,weather_code,wind_speed_10m,is_day",
                 "hourly": "temperature_2m,precipitation_probability,weather_code,is_day",
                 "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max,sunrise,sunset",
                 "temperature_unit": "fahrenheit" if self._unit == "f" else "celsius", "wind_speed_unit": "mph" if self._unit == "f" else "kmh"}
        self._loading, self._error = True, ""
        self.changed.emit()
        self._go("forecast", self.FORECAST + "?" + urllib.parse.urlencode(query), f"{self._at}|{p['lat']}|{self._unit}")

    def _on_arrived(self, what: str, reply, tag: str) -> None:
        reply = dict(reply) if isinstance(reply, dict) else {}
        if what == "search":
            self._searching = False
            out = []
            for r in reply.get("results") or []:
                try:
                    region = ", ".join(x for x in (r.get("admin1"), r.get("country")) if x)
                    out.append({"name": str(r["name"]), "region": region, "lat": float(r["latitude"]), "lon": float(r["longitude"])})
                except (KeyError, TypeError, ValueError):
                    continue
            self._matches = out
            if "__error" in reply:
                self.failed.emit("Couldn't search: this computer doesn't seem to be online.")
            self.found.emit()
            return
        self._loading = False
        at, lat, unit = (tag.split("|") + ["", ""])[:3]
        still = at.isdigit() and int(at) < len(self._places) and str(self._places[int(at)]["lat"]) == lat and unit == self._unit
        if "__error" in reply or "current" not in reply or "daily" not in reply:
            if still:
                self._error = "Couldn't get the forecast. " + ("Showing the last one." if self._data.get(at) else "Check that you're online.")
        elif still:
            self._data[at], self._got[at], self._error = reply, time.time(), ""
            self._keep()
        self.changed.emit()

    # ------------------------------------------------------------------ what the screen shows
    @staticmethod
    def _look(code, is_day=True) -> tuple:
        text, icon = WMO.get(int(code) if code is not None else -1, ("", "cloud"))
        if icon in ("sun", "cloudsun") and not is_day:
            icon = "moon" if icon == "sun" else "cloudmoon"
        return text, icon

    @staticmethod
    def _clock(iso: str) -> str:
        try:
            return dt.datetime.fromisoformat(iso).strftime("%-I:%M %p" if os.name != "nt" else "%I:%M %p").lower()
        except (ValueError, TypeError):
            return ""

    @Property("QVariantMap", notify=changed)
    def now(self):
        d = self._data.get(self._key())
        if not d or not self._places:
            return {}
        try:
            c, daily = d["current"], d["daily"]
            text, icon = self._look(c.get("weather_code"), bool(c.get("is_day", 1)))
            got = self._got.get(self._key(), 0)
            return {"place": self._places[self._at]["name"], "region": self._places[self._at].get("region", ""),
                    "temp": round(c["temperature_2m"]), "feels": round(c.get("apparent_temperature", c["temperature_2m"])), "text": text, "icon": icon,
                    "wind": f"{round(c.get('wind_speed_10m', 0))} {'mph' if self._unit == 'f' else 'km/h'}", "humidity": f"{round(c.get('relative_humidity_2m', 0))}%",
                    "high": round(daily["temperature_2m_max"][0]), "low": round(daily["temperature_2m_min"][0]),
                    "sunrise": self._clock(daily["sunrise"][0]), "sunset": self._clock(daily["sunset"][0]), "day": bool(c.get("is_day", 1)),
                    "updated": "Updated " + ago(got) if got else "", "old": bool(got) and time.time() - got > 3 * 3600}
        except (KeyError, IndexError, TypeError, ValueError):
            return {}

    @Property("QVariantList", notify=changed)
    def hours(self):
        d = self._data.get(self._key())
        try:
            h, start = d["hourly"], d["current"]["time"][:13]
            first = next((i for i, t in enumerate(h["time"]) if t[:13] >= start), 0)
            rows = []
            for i in range(first, min(first + 24, len(h["time"]))):
                _text, icon = self._look(h["weather_code"][i], bool((h.get("is_day") or [1] * len(h["time"]))[i]))
                when = dt.datetime.fromisoformat(h["time"][i])
                rows.append({"time": "Now" if i == first else when.strftime("%-I %p" if os.name != "nt" else "%I %p").lower(), "temp": round(h["temperature_2m"][i]),
                             "icon": icon, "rain": int((h.get("precipitation_probability") or [0] * len(h["time"]))[i] or 0)})
            return rows
        except (KeyError, IndexError, TypeError, ValueError, AttributeError):
            return []

    @Property("QVariantList", notify=changed)
    def days(self):
        d = self._data.get(self._key())
        try:
            daily = d["daily"]
            lows, highs = daily["temperature_2m_min"], daily["temperature_2m_max"]
            floor, ceil = min(lows), max(highs)
            rows = []
            for i, day in enumerate(daily["time"][:8]):
                text, icon = self._look(daily["weather_code"][i])
                rows.append({"day": "Today" if i == 0 else dt.date.fromisoformat(day).strftime("%a"), "icon": icon, "text": text, "high": round(highs[i]), "low": round(lows[i]),
                             "rain": int((daily.get("precipitation_probability_max") or [0] * 8)[i] or 0),
                             "from": (lows[i] - floor) / max(1e-6, ceil - floor), "to": (highs[i] - floor) / max(1e-6, ceil - floor)})
            return rows
        except (KeyError, IndexError, TypeError, ValueError, AttributeError):
            return []


def demo_forecast() -> dict:
    base = dt.datetime.now().replace(minute=0, second=0, microsecond=0)
    hours = [base + dt.timedelta(hours=i) for i in range(48)]
    temps = [58 - 9 * abs(((h.hour - 15) % 24) - 12) / 12 * 2 + 9 for h in hours]
    codes = [2, 2, 3, 3, 61, 61, 63, 3, 2, 1, 0, 0] * 4
    days = [dt.date.today() + dt.timedelta(days=i) for i in range(8)]
    return {"current": {"time": base.isoformat(timespec="minutes"), "temperature_2m": temps[0], "apparent_temperature": 51.0, "relative_humidity_2m": 62, "weather_code": 2,
                        "wind_speed_10m": 11.2, "is_day": 1 if 7 <= base.hour < 18 else 0},
            "hourly": {"time": [h.isoformat(timespec="minutes") for h in hours], "temperature_2m": temps, "precipitation_probability": [0, 5, 10, 20, 55, 70, 80, 40, 15, 5, 0, 0] * 4,
                       "weather_code": codes, "is_day": [1 if 7 <= h.hour < 18 else 0 for h in hours]},
            "daily": {"time": [d.isoformat() for d in days], "weather_code": [2, 61, 3, 0, 0, 71, 3, 1], "temperature_2m_max": [57, 52, 49, 55, 58, 36, 41, 47],
                      "temperature_2m_min": [44, 43, 38, 39, 42, 28, 30, 34], "precipitation_probability_max": [20, 80, 30, 0, 5, 65, 20, 10],
                      "sunrise": [f"{d.isoformat()}T06:38" for d in days], "sunset": [f"{d.isoformat()}T16:34" for d in days]}}


# =================================================================================================== Backup
BACKUP_SKIP = (".cache", ".local/share/Trash", ".local/share/huginn/thumbs", ".thumbnails", ".var/app/*/cache", "snap/*/common/.cache",
               ".local/share/gvfs-metadata", ".gvfs", ".local/share/baloo", ".npm/_cacache")
STAMP = "%Y-%m-%d %H.%M.%S"


def backup_config() -> dict:
    try:
        cfg = json.loads((DATA_HOME / "backup.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        cfg = {}
    return {"dest": str(cfg.get("dest", "")), "schedule": cfg.get("schedule") if cfg.get("schedule") in ("off", "daily", "weekly") else "off",
            "keep": max(2, min(365, int(cfg.get("keep", 30) or 30)))}


def backup_root(dest: str) -> Path:
    import socket
    return Path(dest) / "Huginn Backups" / (socket.gethostname() or "computer")


def backup_list(dest: str) -> list:
    """Finished backups at a destination, newest first: [{name, path, when, info}]."""
    out = []
    try:
        names = os.listdir(backup_root(dest))
    except OSError:
        return out
    for name in names:
        try:
            when = dt.datetime.strptime(name, STAMP).timestamp()
        except ValueError:
            continue                                               # unfinished ones end in ".inprogress"
        path = backup_root(dest) / name
        try:
            info = json.loads((path / ".huginn-backup.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            info = {}
        out.append({"name": name, "path": str(path), "when": when, "info": info})
    return sorted(out, key=lambda b: -b["when"])


def _skipped(rel: str, skip: tuple) -> bool:
    import fnmatch
    return any(fnmatch.fnmatch(rel, pat) for pat in skip)


def run_backup(source: Path, dest: str, keep: int = 30, progress=None, stopped=None, skip: tuple = BACKUP_SKIP) -> dict:
    """Copy `source` into a new dated folder at `dest`. A file that hasn't changed since the last backup is not copied
    again: the new backup shares it with the old one (a hard link), so every backup looks complete but only changes
    take space. Returns {ok, error, files, copied, shared, skipped, bytes, seconds, path}."""
    began = time.time()
    root = backup_root(dest)
    result = {"ok": False, "error": "", "files": 0, "copied": 0, "shared": 0, "skipped": 0, "bytes": 0, "seconds": 0, "path": "", "links": True}
    if not dest or not Path(dest).is_dir():
        result["error"] = "The backup drive isn't connected."
        return result
    if not os.access(dest, os.W_OK):
        result["error"] = "You aren't allowed to save on that drive."
        return result
    source = Path(os.path.abspath(source))
    inside = os.path.relpath(os.path.abspath(dest), source)
    skip = tuple(skip) + ((inside, inside + "/*") if not inside.startswith("..") and inside != "." else ())
    if inside == ".":
        result["error"] = "A backup can't be kept in the folder it is backing up."
        return result
    try:
        root.mkdir(parents=True, exist_ok=True)
    except OSError as err:
        result["error"] = f"Couldn't use that drive: {err.strerror or err}"
        return result
    for stale in root.glob("*.inprogress"):                        # left by a backup that was cut off
        shutil.rmtree(stale, ignore_errors=True)
    previous = backup_list(dest)
    last = Path(previous[0]["path"]) if previous else None

    # can this drive share files between backups? (FAT and exFAT can't)
    probe_a, probe_b = root / ".huginn-probe-a", root / ".huginn-probe-b"
    try:
        probe_a.write_bytes(b"x")
        os.link(probe_a, probe_b)
    except OSError:
        result["links"] = False
    finally:
        for p in (probe_a, probe_b):
            try:
                p.unlink()
            except OSError:
                pass

    # first pass: what there is, and how much of it is new
    plan, need = [], 0
    for folder, dirs, files in os.walk(source):
        rel_dir = os.path.relpath(folder, source)
        rel_dir = "" if rel_dir == "." else rel_dir
        links = [d for d in dirs if os.path.islink(os.path.join(folder, d))]           # a link to a folder is kept as a link
        dirs[:] = sorted(d for d in dirs if d not in links and not _skipped(os.path.join(rel_dir, d), skip))
        for name in sorted(files) + links:
            rel = os.path.join(rel_dir, name)
            if _skipped(rel, skip):
                continue
            try:
                st = os.lstat(os.path.join(folder, name))
            except OSError:
                result["skipped"] += 1
                continue
            same = False
            if last is not None and result["links"] and not os.path.islink(os.path.join(folder, name)):
                try:
                    old = os.lstat(last / rel)
                    same = old.st_size == st.st_size and int(old.st_mtime) == int(st.st_mtime) and not os.path.islink(last / rel)
                except OSError:
                    same = False
            plan.append((rel, st, same))
            if not same:
                need += st.st_size
        if stopped and stopped():
            result["error"] = "stopped"
            return result
    try:
        free = shutil.disk_usage(dest).free
    except OSError:
        free = need + 1
    if need + 64 * 1024 * 1024 > free:
        result["error"] = f"The backup drive needs {human_size(need)} free and has {human_size(free)}."
        return result

    work = root / (dt.datetime.fromtimestamp(began).strftime(STAMP) + ".inprogress")
    done_bytes = 0
    import stat as S
    try:
        work.mkdir()
        made = {""}
        for rel, st, same in plan:
            if stopped and stopped():
                raise InterruptedError
            src, target = source / rel, work / rel
            parent = os.path.dirname(rel)
            if parent not in made:
                target.parent.mkdir(parents=True, exist_ok=True)
                made.add(parent)
            try:
                if S.S_ISLNK(st.st_mode):
                    os.symlink(os.readlink(src), target)
                elif S.S_ISREG(st.st_mode):
                    if same:
                        try:
                            os.link(last / rel, target)
                            result["shared"] += 1
                        except OSError:
                            shutil.copy2(src, target)
                            result["copied"] += 1
                            result["bytes"] += st.st_size
                    else:
                        with open(src, "rb") as fin, open(target, "wb") as fout:
                            while True:
                                if stopped and stopped():
                                    raise InterruptedError
                                block = fin.read(1024 * 1024)
                                if not block:
                                    break
                                fout.write(block)
                                done_bytes += len(block)
                                if progress:
                                    progress(min(1.0, done_bytes / max(1, need)))
                        try:
                            shutil.copystat(src, target)
                        except OSError:
                            pass
                        result["copied"] += 1
                        result["bytes"] += st.st_size
                else:
                    result["skipped"] += 1                         # sockets, pipes, devices
                    continue
                result["files"] += 1
            except InterruptedError:
                raise
            except OSError:
                result["skipped"] += 1                             # unreadable, or a name the drive can't hold
        for folder, dirs, _files in os.walk(source):               # empty folders, and each folder's own dates
            rel_dir = os.path.relpath(folder, source)
            rel_dir = "" if rel_dir == "." else rel_dir
            dirs[:] = [d for d in dirs if not _skipped(os.path.join(rel_dir, d), skip) and not os.path.islink(os.path.join(folder, d))]
            try:
                (work / rel_dir).mkdir(parents=True, exist_ok=True)
            except OSError:
                pass
        result["seconds"] = round(time.time() - began, 1)
        (work / ".huginn-backup.json").write_text(json.dumps({k: result[k] for k in ("files", "copied", "shared", "skipped", "bytes", "seconds", "links")} | {"source": str(source)}), encoding="utf-8")
        final = root / dt.datetime.fromtimestamp(began).strftime(STAMP)
        os.rename(work, final)
        result["path"], result["ok"] = str(final), True
    except InterruptedError:
        shutil.rmtree(work, ignore_errors=True)
        result["error"] = "stopped"
        return result
    except OSError as err:
        shutil.rmtree(work, ignore_errors=True)
        result["error"] = f"The backup stopped: {err.strerror or err}"
        return result
    for old in backup_list(dest)[keep:]:                           # the oldest make room; files newer backups share stay
        shutil.rmtree(old["path"], ignore_errors=True)
    return result


def backup_state(update: dict = None) -> dict:
    file = DATA_HOME / "backup-state.json"
    try:
        state = json.loads(file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        state = {}
    if update:
        state.update(update)
        try:
            write_whole(file, json.dumps(state).encode(), 0o644)
        except OSError:
            pass
    return state


class Backup(QObject):
    changed = Signal()
    failed = Signal(str)
    said = Signal(str)
    _finished = Signal("QVariant")
    _moved = Signal()

    def __init__(self, demo: bool = False, source: Path = None):
        super().__init__()
        self._demo, self._source = demo, source or Path.home()
        self._cfg = backup_config()
        self._busy, self._progress, self._stop, self._what = False, 0.0, False, ""
        self._snap, self._rel = "", ""
        self._finished.connect(self._after)
        self._moved.connect(self.changed)
        self._runtime = Path(os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid() if hasattr(os, 'getuid') else 0}")

    def _sh(self, args, timeout: int = 30) -> tuple:
        try:
            done = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
            return done.returncode, (done.stdout or "") + (done.stderr or "")
        except (OSError, subprocess.SubprocessError) as err:
            return 1, str(err)

    def _keep(self) -> None:
        if not self._demo:
            try:
                write_whole(DATA_HOME / "backup.json", json.dumps(self._cfg).encode(), 0o644)
            except OSError as err:
                self.failed.emit(f"Couldn't save the settings: {err.strerror or err}")

    # ------------------------------------------------------------------ where to
    @Property("QVariantList", notify=changed)
    def drives(self):
        """Places a backup could go: drives plugged in and servers connected, with the room on each."""
        if self._demo:
            return [{"name": "Backup Drive", "path": "/media/demo/Backup Drive", "free": "412.6 GB free", "chosen": True}]
        spots = []
        try:
            with open("/proc/self/mounts", encoding="utf-8", errors="replace") as mounts:
                spots = [line.split()[1].replace("\\040", " ") for line in mounts if len(line.split()) > 1]
        except OSError:
            pass
        spots = [s for s in spots if s.startswith(("/media/", "/run/media/", "/mnt/"))]
        try:
            spots += [str(self._runtime / "gvfs" / n) for n in sorted(os.listdir(self._runtime / "gvfs")) if ":" in n]
        except OSError:
            pass
        if self._cfg["dest"] and self._cfg["dest"] not in spots and Path(self._cfg["dest"]).is_dir():
            spots.append(self._cfg["dest"])
        rows = []
        for spot in dict.fromkeys(spots):
            try:
                free = shutil.disk_usage(spot).free
            except OSError:
                continue
            rows.append({"name": Path(spot).name or spot, "path": spot, "free": human_size(free) + " free", "chosen": spot == self._cfg["dest"]})
        return rows

    dest = Property(str, lambda self: self._cfg["dest"], notify=changed)
    destName = Property(str, lambda self: "Backup Drive" if self._demo else (Path(self._cfg["dest"]).name or self._cfg["dest"]), notify=changed)
    connected = Property(bool, lambda self: self._demo or bool(self._cfg["dest"]) and Path(self._cfg["dest"]).is_dir(), notify=changed)
    schedule = Property(str, lambda self: self._cfg["schedule"], notify=changed)
    keep = Property(int, lambda self: self._cfg["keep"], notify=changed)
    busy = Property(bool, lambda self: self._busy, notify=changed)
    progress = Property(float, lambda self: self._progress, notify=changed)
    doing = Property(str, lambda self: self._what, notify=changed)

    @Slot(str, result=str)
    def choose(self, path: str) -> str:
        """Pick where backups go: a drive from the list, or any folder's path. Returns "" or why not."""
        path = QUrl(path).toLocalFile() if path.startswith("file:") else os.path.expanduser(path.strip())
        if not path or not Path(path).is_dir():
            return "There is no folder there."
        if not os.access(path, os.W_OK):
            return "You aren't allowed to save there."
        real, src = os.path.realpath(path), os.path.realpath(self._source)
        if real == src:
            return "A backup can't be kept in the folder it is backing up."
        self._cfg["dest"] = path
        self._keep()
        self.changed.emit()
        if (real + "/").startswith(src + "/"):
            self.said.emit("That folder is on the same drive as your files. If the drive fails, both are lost: another drive is safer.")
        return ""

    @Slot(int)
    def setKeep(self, count: int) -> None:
        self._cfg["keep"] = max(2, min(365, count))
        self._keep()
        self.changed.emit()

    # ------------------------------------------------------------------ history
    def _history(self) -> list:
        if self._demo:
            now = time.time()
            return [{"name": dt.datetime.fromtimestamp(now - gap).strftime(STAMP), "path": f"demo{i}", "when": now - gap,
                     "info": {"files": 48210 + i * 7, "copied": c, "bytes": c * 310_000, "shared": 48210 - c, "skipped": 0, "seconds": 41 + c // 9}}
                    for i, (gap, c) in enumerate([(2.2 * 3600, 37), (26 * 3600, 212), (50 * 3600, 18), (74 * 3600, 95), (5 * 86400, 1403), (6 * 86400, 64), (9 * 86400, 48210)])]
        return backup_list(self._cfg["dest"]) if self._cfg["dest"] else []

    @Property("QVariantList", notify=changed)
    def history(self):
        rows = []
        for b in self._history():
            info, when = b["info"], dt.datetime.fromtimestamp(b["when"])
            rows.append({"path": b["path"], "when": ago(b["when"]), "day": when.strftime("%a %-d %b" if os.name != "nt" else "%a %d %b"),
                         "time": when.strftime("%H:%M"), "files": int(info.get("files", 0)), "new": int(info.get("copied", 0)),
                         "size": human_size(info.get("bytes", 0)), "skipped": int(info.get("skipped", 0))})
        return rows

    @Property("QVariantMap", notify=changed)
    def status(self):
        """One line for the middle of the window: {state: none|ok|old|missing|error, title, detail}."""
        history, state = self._history(), ({} if self._demo else backup_state())
        if not self._cfg["dest"] and not self._demo:
            return {"state": "none", "title": "No backups yet", "detail": "Choose a drive, and Huginn keeps a copy of your files on it."}
        if not history:
            detail = "The backup drive isn't connected." if not self.connected else "Ready for the first backup. It copies everything, so it takes the longest."
            return {"state": "missing" if not self.connected else "none", "title": "No backups yet", "detail": detail}
        last = history[0]
        age = time.time() - last["when"]
        info = last["info"]
        detail = f"{int(info.get('files', 0)):,} files kept safe on “{self.destName}”."
        if state.get("error") and state.get("error_at", 0) > last["when"]:
            return {"state": "error", "title": "Last backup " + ago(last["when"]), "detail": "The latest try didn't finish: " + state["error"]}
        if not self.connected:
            return {"state": "missing", "title": "Last backup " + ago(last["when"]), "detail": f"“{self.destName}” isn't connected. Plug it in to back up."}
        limit = {"daily": 2, "weekly": 9}.get(self._cfg["schedule"], 14) * 86400
        return {"state": "old" if age > limit else "ok", "title": "Last backup " + ago(last["when"]), "detail": detail}

    # ------------------------------------------------------------------ backing up
    @Slot()
    def backUpNow(self) -> None:
        if self._busy or self._demo:
            return
        if not self.connected:
            self.failed.emit("The backup drive isn't connected.")
            return
        self._busy, self._progress, self._stop, self._what = True, 0.0, False, "Looking at what has changed…"
        self.changed.emit()

        def tick(frac: float) -> None:
            if frac - self._progress > 0.01 or frac >= 1:
                self._progress, self._what = frac, "Copying what is new…"
                self._moved.emit()

        def work():
            self._finished.emit(run_backup(self._source, self._cfg["dest"], self._cfg["keep"], tick, lambda: self._stop))
        self._worker = threading.Thread(target=work, daemon=True)
        self._worker.start()

    @Slot()
    def stop(self) -> None:
        self._stop = True

    def _after(self, result) -> None:
        result = dict(result)
        if "restored" in result or "restore_error" in result:
            self._after_restore(result)
            return
        self._busy, self._what = False, ""
        if result.get("ok"):
            backup_state({"ok_at": time.time(), "error": ""})
            extra = "" if result.get("links", True) else " This drive can't share unchanged files between backups, so each one takes full room; formatting it as ext4 in Disks fixes that."
            skipped = f" {result['skipped']} couldn't be read and were left out." if result.get("skipped") else ""
            self.said.emit(f"Backed up. {result['copied']:,} new or changed, {result['shared']:,} unchanged.{skipped}{extra}")
        elif result.get("error") == "stopped":
            self.said.emit("Stopped. Nothing half-done was kept.")
        else:
            backup_state({"error": result.get("error", ""), "error_at": time.time()})
            self.failed.emit(result.get("error") or "The backup didn't finish.")
        self.changed.emit()

    def wait(self) -> None:
        if getattr(self, "_worker", None):
            self._worker.join()

    # ------------------------------------------------------------------ going back
    snapshot = Property(str, lambda self: self._snap, notify=changed)
    folder = Property(str, lambda self: self._rel, notify=changed)

    @Slot(str)
    def openSnapshot(self, path: str) -> None:
        self._snap, self._rel = path, ""
        self.changed.emit()

    @Slot(str)
    def openFolder(self, rel: str) -> None:
        self._rel = rel.strip("/")
        self.changed.emit()

    @Slot()
    def up(self) -> None:
        if self._rel:
            self._rel = os.path.dirname(self._rel)
        else:
            self._snap = ""
        self.changed.emit()

    @Property("QVariantList", notify=changed)
    def crumbs(self):
        out, at = [{"name": "Home", "rel": ""}], ""
        for part in [p for p in self._rel.split("/") if p]:
            at = os.path.join(at, part)
            out.append({"name": part, "rel": at})
        return out

    @Property("QVariantList", notify=changed)
    def files(self):
        """What the open backup holds in the open folder."""
        if not self._snap:
            return []
        if self._demo:
            names = [("Documents", True), ("Music", True), ("Pictures", True), ("Projects", True), ("Budget 2026.xlsx", False), ("Lease.pdf", False), ("Notes.md", False)]
            return [{"name": n, "rel": n, "dir": d, "size": "" if d else "184 KB", "hidden": False} for n, d in names] if not self._rel else []
        here = Path(self._snap) / self._rel
        rows = []
        try:
            names = os.listdir(here)
        except OSError:
            return rows
        for name in names:
            if name == ".huginn-backup.json":
                continue
            full = here / name
            is_dir = full.is_dir() and not full.is_symlink()
            try:
                size = "" if is_dir else human_size(os.lstat(full).st_size)
            except OSError:
                continue
            rows.append({"name": name, "rel": os.path.join(self._rel, name), "dir": is_dir, "size": size, "hidden": name.startswith(".")})
        return sorted(rows, key=lambda r: (not r["dir"], r["hidden"], r["name"].lower()))

    @Slot(str)
    def restore(self, rel: str) -> None:
        """Bring one file or folder back from the open backup. Nothing is ever replaced: if the original is still
        there, what comes back sits beside it with the backup's date in its name."""
        if not self._snap or self._busy or self._demo:
            return
        src = Path(self._snap) / rel
        target = self._source / rel
        if not os.path.lexists(src):
            self.failed.emit("That is no longer in the backup.")
            return
        if os.path.lexists(target):
            day = Path(self._snap).name[:10]
            stem, suffix = (target.name, "") if src.is_dir() else (target.stem, target.suffix)
            n = 1
            while True:
                target = target.parent / (f"{stem} (from {day}){suffix}" if n == 1 else f"{stem} (from {day}) {n}{suffix}")
                if not os.path.lexists(target):
                    break
                n += 1
        self._busy, self._progress, self._stop, self._what = True, 0.0, False, f"Bringing back “{src.name}”…"
        self.changed.emit()

        def work():
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                if src.is_dir() and not src.is_symlink():
                    shutil.copytree(src, target, symlinks=True)    # real copies: changing them can't touch the backup
                elif src.is_symlink():
                    os.symlink(os.readlink(src), target)
                else:
                    shutil.copy2(src, target)
                self._finished.emit({"restored": str(target)})
            except OSError as err:
                if target.is_dir() and not target.is_symlink():
                    shutil.rmtree(target, ignore_errors=True)
                self._finished.emit({"restore_error": f"Couldn't bring it back: {err.strerror or err}"})
        self._worker = threading.Thread(target=work, daemon=True)
        self._worker.start()

    def _after_restore(self, result: dict) -> None:
        self._busy, self._what = False, ""
        if result.get("restored"):
            where = Path(result["restored"])
            home = str(self._source)
            shown = "Home" + str(where.parent)[len(home):] if str(where.parent).startswith(home) else str(where.parent)
            self.said.emit(f"“{where.name}” is back in {shown}.")
        else:
            self.failed.emit(result.get("restore_error", "Couldn't bring it back."))
        self.changed.emit()

    # ------------------------------------------------------------------ on a schedule
    @Slot(str)
    def setSchedule(self, how: str) -> None:
        """off, daily or weekly. Huginn asks the system to run the backup by itself, whether or not this app is open;
        if the drive isn't plugged in at the time, it waits for the next turn."""
        if how not in ("off", "daily", "weekly"):
            return
        self._cfg["schedule"] = how
        self._keep()
        if not self._demo:
            units = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "systemd" / "user"
            try:
                if how == "off":
                    self._sh(["systemctl", "--user", "disable", "--now", "huginn-backup.timer"])
                    for name in ("huginn-backup.timer", "huginn-backup.service"):
                        (units / name).unlink(missing_ok=True)
                else:
                    units.mkdir(parents=True, exist_ok=True)
                    script = Path(__file__).resolve()
                    (units / "huginn-backup.service").write_text(
                        f"[Unit]\nDescription=Huginn Backup\n\n[Service]\nType=oneshot\nExecStart={sys.executable or 'python3'} {script} backup-run\nNice=10\nIOSchedulingClass=idle\n", encoding="utf-8")
                    (units / "huginn-backup.timer").write_text(
                        f"[Unit]\nDescription=Huginn Backup, {how}\n\n[Timer]\nOnCalendar={how}\nPersistent=true\nRandomizedDelaySec=15min\n\n[Install]\nWantedBy=timers.target\n", encoding="utf-8")
                    self._sh(["systemctl", "--user", "daemon-reload"])
                    code, out = self._sh(["systemctl", "--user", "enable", "--now", "huginn-backup.timer"])
                    if code != 0:
                        self.failed.emit("The schedule is saved, but the system didn't take it. Back Up Now still works.")
            except OSError as err:
                self.failed.emit(f"Couldn't set the schedule: {err.strerror or err}")
        self.changed.emit()


def backup_run_once() -> int:
    """What the schedule runs: one backup, quietly. A drive that isn't there is not an error, just a missed turn."""
    cfg = backup_config()
    if not cfg["dest"] or not Path(cfg["dest"]).is_dir():
        backup_state({"missed_at": time.time()})
        return 0
    result = run_backup(Path.home(), cfg["dest"], cfg["keep"])
    if result["ok"]:
        backup_state({"ok_at": time.time(), "error": ""})
        return 0
    backup_state({"error": result["error"], "error_at": time.time()})
    return 1


# ==================================================================================================== Disks
SYSTEM_SPOTS = ("/", "/boot", "/boot/efi", "/home", "/usr", "/var", "[SWAP]", "/cdrom", "/rofs")
FORMATS = [{"id": "exfat", "name": "For any computer", "detail": "Windows, Mac and Huginn can all use it. Best for sticks and cards.", "label": 15},
           {"id": "ext4", "name": "For Huginn only", "detail": "Sturdier, and backups on it take far less room. Windows and Mac can't read it.", "label": 16},
           {"id": "vfat", "name": "For older devices", "detail": "Cameras, car stereos, consoles. No file can be bigger than 4 GB.", "label": 11}]


class Disks(QObject):
    changed = Signal()
    failed = Signal(str)
    said = Signal(str)
    _finished = Signal(str, str)

    def __init__(self, demo: bool = False):
        super().__init__()
        self._demo, self._rows, self._busy, self._what = demo, [], False, ""
        self._finished.connect(self._after)
        self.refresh()

    def _sh(self, args, timeout: int = 30) -> tuple:
        try:
            done = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
            return done.returncode, (done.stdout or "") + (done.stderr or "")
        except (OSError, subprocess.SubprocessError) as err:
            return 1, str(err)

    @staticmethod
    def _yes(v) -> bool:
        return v in (True, 1, "1", "true")

    def _read(self) -> list:
        if self._demo:
            gb = 1024 ** 3
            return [{"dev": "/dev/nvme0n1", "name": "Internal Drive", "detail": "Samsung SSD 980 · 500 GB", "removable": False, "system": True, "size": 500 * gb, "parts": [
                        {"dev": "/dev/nvme0n1p1", "label": "System start-up", "fs": "vfat", "size": 1 * gb, "mount": "/boot/efi", "used": 0.2 * gb, "free": 0.8 * gb, "system": True, "locked": False},
                        {"dev": "/dev/nvme0n1p2", "label": "Huginn OS", "fs": "ext4", "size": 499 * gb, "mount": "/", "used": 187 * gb, "free": 312 * gb, "system": True, "locked": False}]},
                    {"dev": "/dev/sda", "name": "USB Drive", "detail": "SanDisk Ultra · 64 GB", "removable": True, "system": False, "size": 64 * gb, "parts": [
                        {"dev": "/dev/sda1", "label": "HOLIDAY", "fs": "exfat", "size": 64 * gb, "mount": "/media/val/HOLIDAY", "used": 21.5 * gb, "free": 42.5 * gb, "system": False, "locked": False}]},
                    {"dev": "/dev/sdb", "name": "USB Drive", "detail": "WD Elements · 2 TB", "removable": True, "system": False, "size": 2000 * gb, "parts": [
                        {"dev": "/dev/sdb1", "label": "Backup Drive", "fs": "ext4", "size": 2000 * gb, "mount": "", "used": 0, "free": 0, "system": False, "locked": False}]}]
        code, out = self._sh(["lsblk", "-J", "-b", "-p", "-o", "NAME,LABEL,SIZE,MOUNTPOINT,RM,HOTPLUG,FSTYPE,TYPE,MODEL,VENDOR,TRAN,FSUSED,FSAVAIL"], 10)
        try:
            tree = json.loads(out)["blockdevices"] if code == 0 else []
        except (ValueError, KeyError, TypeError):
            tree = []
        drives = []
        for node in tree:
            if node.get("type") not in ("disk", "rom") or (node.get("name") or "").startswith(("/dev/loop", "/dev/ram", "/dev/zram")):
                continue
            removable = self._yes(node.get("rm")) or self._yes(node.get("hotplug")) or node.get("tran") == "usb"
            parts = []

            def walk(n, locked_by=""):
                kids = n.get("children") or []
                fs, spot = n.get("fstype") or "", n.get("mountpoint") or ""
                if fs == "crypto_LUKS" and kids:
                    for k in kids:
                        walk(k, n.get("name") or "")
                    return
                if n is not node and (fs or n.get("type") == "part") and not kids or (n is node and fs and not kids):
                    parts.append({"dev": n.get("name") or "", "label": n.get("label") or "", "fs": fs, "size": int(n.get("size") or 0), "mount": spot,
                                  "used": int(n.get("fsused") or 0), "free": int(n.get("fsavail") or 0), "locked": fs == "crypto_LUKS",
                                  "system": spot in SYSTEM_SPOTS or spot.startswith(("/boot/", "/run/live", "/usr/", "/var/", "/snap/")) or fs in ("swap", "squashfs")})
                    return
                for k in kids:
                    walk(k, locked_by)
            walk(node)
            if not parts and not int(node.get("size") or 0):
                continue                                           # an empty card reader slot
            model = " ".join(x for x in ((node.get("vendor") or "").strip(), (node.get("model") or "").strip()) if x)
            drives.append({"dev": node.get("name") or "", "name": ("USB Drive" if node.get("tran") == "usb" else "Card" if "mmc" in (node.get("name") or "") and removable else
                                                                   "Removable Drive" if removable else "Internal Drive"),
                           "detail": " · ".join(x for x in (model, human_size(int(node.get("size") or 0))) if x), "removable": removable,
                           "system": any(p["system"] for p in parts), "size": int(node.get("size") or 0), "parts": parts})
        return sorted(drives, key=lambda d: (not d["system"], d["removable"], d["dev"]))

    @Slot()
    def refresh(self) -> None:
        rows = self._read()
        if rows != self._rows:
            self._rows = rows
            self.changed.emit()

    @Property("QVariantList", notify=changed)
    def drives(self):
        out = []
        for d in self._rows:
            parts = []
            for p in d["parts"]:
                kind = {"vfat": "FAT", "exfat": "exFAT", "ext4": "ext4", "ntfs": "NTFS (Windows)", "btrfs": "Btrfs", "swap": "Swap", "crypto_LUKS": "Locked",
                        "iso9660": "Disc image", "apfs": "Mac", "hfsplus": "Mac"}.get(p["fs"], p["fs"] or "Empty")
                parts.append(dict(p, name=p["label"] or ("Start-up" if p["mount"] in ("/boot", "/boot/efi") else "Unnamed"), kind=kind, sizeText=human_size(p["size"]),
                                  usedText=(human_size(p["used"]) + " used · " + human_size(p["free"]) + " free") if p["mount"] else "Not opened",
                                  usedFrac=(p["used"] / max(1, p["used"] + p["free"])) if p["mount"] else 0.0, share=p["size"] / max(1, d["size"]),
                                  canChange=not p["system"] and not d["system"] and not p["locked"]))
            out.append(dict(d, parts=parts, canEject=d["removable"] and not d["system"]))
        return out

    formats = Property("QVariantList", lambda self: FORMATS, constant=True)
    busy = Property(bool, lambda self: self._busy, notify=changed)
    doing = Property(str, lambda self: self._what, notify=changed)

    def _find(self, dev: str):
        for d in self._rows:
            for p in d["parts"]:
                if p["dev"] == dev:
                    return d, p
        return None, None

    def _allowed(self, dev: str):
        """The one gate every change goes through: never the drive Huginn runs from."""
        d, p = self._find(dev)
        if p is None:
            self.failed.emit("That drive is no longer connected.")
            return None, None
        if d["system"] or p["system"]:
            self.failed.emit("That is part of the drive Huginn runs from. It can't be changed from here.")
            return None, None
        return d, p

    @staticmethod
    def _object(dev: str) -> str:
        name = "".join(c if c.isalnum() else f"_{ord(c):02x}" for c in os.path.basename(dev))
        return "/org/freedesktop/UDisks2/block_devices/" + name

    def _start(self, what: str, work) -> None:
        self._busy, self._what = True, what
        self.changed.emit()

        def run():
            try:
                good, bad = work()
            except Exception as err:
                good, bad = "", f"It stopped: {err}"
            self._finished.emit(good, bad)
        self._worker = threading.Thread(target=run, daemon=True)
        self._worker.start()

    def _after(self, good: str, bad: str) -> None:
        self._busy, self._what = False, ""
        self.refresh()
        self.changed.emit()
        if bad:
            self.failed.emit(bad)
        elif good:
            self.said.emit(good)

    def wait(self) -> None:
        if getattr(self, "_worker", None):
            self._worker.join()

    @staticmethod
    def _why(out: str, fallback: str) -> str:
        low = out.lower()
        if "not authorized" in low or "notauthorized" in low or "dismissed" in low:
            return "You didn't have permission, or the request was cancelled."
        if "busy" in low:
            return "Something on it is still open. Close it and try again."
        return fallback

    @Slot(str)
    def open(self, dev: str) -> None:
        d, p = self._find(dev)
        if p is None or self._busy:
            return

        def work():
            code, out = self._sh(["udisksctl", "mount", "-b", dev, "--no-user-interaction"], 60)
            return ("Opened.", "") if code == 0 else ("", self._why(out, "Couldn't open it. It may be damaged or in a format Huginn can't read."))
        self._start("Opening…", work)

    @Slot(str)
    def close(self, dev: str) -> None:
        d, p = self._allowed(dev)
        if p is None or self._busy:
            return

        def work():
            code, out = self._sh(["udisksctl", "unmount", "-b", dev, "--no-user-interaction"], 120)
            return ("Closed.", "") if code == 0 else ("", self._why(out, "Couldn't close it."))
        self._start("Closing…", work)

    @Slot(str)
    def eject(self, drive: str) -> None:
        d = next((x for x in self._rows if x["dev"] == drive), None)
        if d is None or self._busy:
            return
        if d["system"] or not d["removable"]:
            self.failed.emit("That drive is part of this computer.")
            return

        def work():
            for p in d["parts"]:
                if p["mount"]:
                    code, out = self._sh(["udisksctl", "unmount", "-b", p["dev"], "--no-user-interaction"], 120)
                    if code != 0:
                        return "", self._why(out, f"Couldn't close “{p['label'] or 'it'}”.")
            self._sh(["udisksctl", "power-off", "-b", drive, "--no-user-interaction"], 30)
            return "It is safe to unplug.", ""
        self._start("Ejecting…", work)

    @Slot(str, str, result=str)
    def labelProblem(self, fs: str, label: str) -> str:
        """Why a name won't do for a format, or ""."""
        limit = next((f["label"] for f in FORMATS if f["id"] == fs), 16)
        if len(label.encode("utf-8")) > limit:
            return f"That format allows names up to {limit} letters."
        if any(c in label for c in '"*/:<>?\\|\'') or label != label.strip():
            return "A drive's name can't have those marks in it."
        if fs == "vfat" and not all(c.isascii() and (c.isalnum() or c in " _-") for c in label):
            return "For older devices, use only letters, numbers and spaces."
        return ""

    @Slot(str, str)
    def rename(self, dev: str, label: str) -> None:
        d, p = self._allowed(dev)
        if p is None or self._busy:
            return
        problem = self.labelProblem(p["fs"], label)
        if problem:
            self.failed.emit(problem)
            return
        if p["fs"] == "vfat":
            label = label.upper()

        def work():
            code, out = self._sh(["gdbus", "call", "--system", "--dest", "org.freedesktop.UDisks2", "--object-path", self._object(dev),
                                  "--method", "org.freedesktop.UDisks2.Filesystem.SetLabel", label, "{}"], 60)
            return (f"Renamed to “{label}”.", "") if code == 0 else ("", self._why(out, "Couldn't rename it. Some formats need the drive closed first."))
        self._start("Renaming…", work)

    @Slot(str, str, str, bool)
    def erase(self, dev: str, fs: str, label: str, sure: bool) -> None:
        """Format: everything on it is erased and it starts empty in the chosen format. `sure` must be true, and the
        drive Huginn runs from is refused whatever is passed."""
        d, p = self._allowed(dev)
        if p is None or self._busy:
            return
        if not sure:
            self.failed.emit("Tick the box to say you understand everything on it will be erased.")
            return
        if fs not in [f["id"] for f in FORMATS]:
            self.failed.emit("Huginn doesn't make that format.")
            return
        problem = self.labelProblem(fs, label)
        if problem:
            self.failed.emit(problem)
            return
        if fs == "vfat":
            label = label.upper()
        tool = {"exfat": "mkfs.exfat", "ext4": "mkfs.ext4", "vfat": "mkfs.vfat"}[fs]
        if not shutil.which(tool) and not self._demo and not getattr(self, "_skip_tool_check", False):
            self.failed.emit("The part of the system that makes that format isn't installed.")
            return

        def work():
            if p["mount"]:
                code, out = self._sh(["udisksctl", "unmount", "-b", dev, "--no-user-interaction"], 120)
                if code != 0:
                    return "", self._why(out, "Couldn't close it first, so nothing was erased.")
            options = "{'label': <'%s'>, 'update-partition-type': <true>%s}" % (label.replace("'", ""), ", 'take-ownership': <true>" if fs == "ext4" else "")
            code, out = self._sh(["gdbus", "call", "--system", "--dest", "org.freedesktop.UDisks2", "--object-path", self._object(dev),
                                  "--method", "org.freedesktop.UDisks2.Block.Format", fs, options, "--timeout", "3600"], 3700)
            if code != 0:
                return "", self._why(out, "Couldn't erase it. Nothing may have changed; check the drive before using it.")
            self._sh(["udisksctl", "mount", "-b", dev, "--no-user-interaction"], 60)
            return f"“{label or 'The drive'}” is erased and ready.", ""
        self._start("Erasing…", work)


# ================================================================================= Camera and Voice Recorder
class Shelf(QObject):
    """The files one small app makes (recordings, or photos and clips): list them, name the next, rename, bin."""
    changed = Signal()
    failed = Signal(str)

    def __init__(self, kind: str, demo: bool = False):
        super().__init__()
        sp = QStandardPaths
        self._kind, self._demo = kind, demo
        if kind == "recorder":
            self._folders = [Path(sp.writableLocation(sp.MusicLocation) or Path.home() / "Music") / "Recordings"]
            self._suffixes = (".m4a", ".ogg", ".opus", ".wav", ".mp3", ".flac", ".aac", ".mka", ".webm")
        else:
            self._folders = [Path(sp.writableLocation(sp.PicturesLocation) or Path.home() / "Pictures") / "Camera",
                             Path(sp.writableLocation(sp.MoviesLocation) or Path.home() / "Videos") / "Camera"]
            self._suffixes = (".jpg", ".jpeg", ".png", ".mp4", ".mkv", ".webm", ".mov")

    @Property("QVariantList", notify=changed)
    def items(self):
        if self._demo:
            now = time.time()
            names = [("Interview with Astrid", 3 * 3600, "4.1 MB", "12:48"), ("Song idea", 26 * 3600, "0.9 MB", "2:07"), ("Lecture, week 6", 3 * 86400, "22.6 MB", "58:31"),
                     ("Shopping list", 5 * 86400, "0.2 MB", "0:24")] if self._kind == "recorder" else []
            return [{"name": n, "path": f"/demo/{n}.m4a", "url": "", "when": ago(now - gap), "size": size, "length": length, "video": False} for n, gap, size, length in names]
        rows = []
        for folder in self._folders:
            try:
                names = os.listdir(folder)
            except OSError:
                continue
            for name in names:
                full = folder / name
                if full.suffix.lower() not in self._suffixes or name.startswith("."):
                    continue
                try:
                    st = full.stat()
                except OSError:
                    continue
                if st.st_size == 0:
                    continue
                rows.append({"name": full.stem, "path": str(full), "url": QUrl.fromLocalFile(str(full)).toString(), "stamp": st.st_mtime, "when": ago(st.st_mtime),
                             "size": human_size(st.st_size), "length": "", "video": full.suffix.lower() in (".mp4", ".mkv", ".webm", ".mov")})
        return sorted(rows, key=lambda r: -r["stamp"])

    @Property("QVariantMap", notify=changed)
    def last(self):
        items = self.items
        return items[0] if items else {}

    def _next(self, folder: Path, word: str, suffix: str) -> str:
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except OSError as err:
            self.failed.emit(f"Couldn't make the folder to save in: {err.strerror or err}")
            return ""
        base = f"{word} {dt.datetime.now().strftime('%Y-%m-%d %H.%M.%S')}"
        n, target = 1, folder / f"{base}{suffix}"
        while os.path.lexists(target):
            n += 1
            target = folder / f"{base} {n}{suffix}"
        return QUrl.fromLocalFile(str(target)).toString()

    @Slot(result=str)
    def nextRecording(self) -> str:
        return self._next(self._folders[0], "Recording", ".m4a")

    @Slot(result=str)
    def nextPhoto(self) -> str:
        return self._next(self._folders[0], "Photo", ".jpg")

    @Slot(result=str)
    def nextVideo(self) -> str:
        return self._next(self._folders[-1], "Video", ".mp4")

    @Slot()
    def refresh(self) -> None:
        self.changed.emit()

    @Slot(str, str, result=str)
    def rename(self, path: str, new: str) -> str:
        src, new = Path(path), new.strip()
        if not new or "/" in new or new in (".", ".."):
            return "That name won't do."
        target = src.with_name(new + src.suffix)
        if target == src:
            return ""
        if os.path.lexists(target):
            return f"“{new}” is already here."
        try:
            os.rename(src, target)
        except OSError as err:
            return f"Couldn't rename it: {err.strerror or err}"
        self.changed.emit()
        return ""

    @Slot(str)
    def remove(self, path: str) -> None:
        """To the Trash, so it can be brought back."""
        try:
            from huginn_app import move_to_trash
            move_to_trash(path)
        except (OSError, ImportError) as err:
            self.failed.emit(f"Couldn't move it to the Trash: {getattr(err, 'strerror', None) or err}")
        self.changed.emit()

    @Slot(str)
    def show(self, path: str) -> None:
        """Open a file, or the folder it is in, with the usual app."""
        from PySide6.QtGui import QDesktopServices
        target = Path(path) if path else self._folders[0]
        target.mkdir(parents=True, exist_ok=True) if not path else None
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(target))):
            self.failed.emit("No app is set up to open that.")

    folderName = Property(str, lambda self: "Music/Recordings" if self._kind == "recorder" else "Pictures/Camera", constant=True)


if __name__ == "__main__":
    if sys.argv[1:2] == ["backup-run"]:
        sys.exit(backup_run_once())
    print(__doc__)
