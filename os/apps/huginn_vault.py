"""The one password vault Huginn's apps share.

Passwords, the Huginn browser and Mail all open the same file: the browser's own vault
(~/.local/share/SafariQt/SafariQt/passwords.vault), in the browser's own format. A login saved in the browser shows
in Passwords; one added in Passwords fills in the browser; Mail keeps its accounts' secrets in it too.

    file      JSON: {"format", "version", "kdf": scrypt parameters and salt, "master": the vault key sealed by the
              master password, "data": everything else sealed by the vault key}. AES-256-GCM throughout.
    sharing   each app keeps its own copy in memory. Before any app writes, it reads what is on disk and folds the
              two together change by change (a three-way merge against what it last read), so two apps open at once
              never lose each other's work. Each app also looks for the other's changes every couple of seconds.
    one       unlocking in one app can unlock the others for this login session, through a small agent that holds
    unlock    the vault key in memory (never the master password, never on disk). See VaultAgent for who it trusts.

No Qt in here, so the browser can carry the same logic.
"""
import base64
import hashlib
import json
import os
import re
import secrets
import shutil
import socket
import struct
import subprocess
import sys
import threading
import time
import urllib.parse
import uuid
from pathlib import Path

try:
    from cryptography.exceptions import InvalidTag
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
except ImportError:                                               # python3-cryptography is in the image
    AESGCM = None

    class InvalidTag(Exception):
        pass

VAULT_FORMAT = "SafariQt passwords"                                # the browser's first name: kept so every vault still opens
SCRYPT_PARAMS = {"n": 2 ** 16, "r": 8, "p": 1}
MIN_MASTER_LENGTH = 8
SECOND_LEVEL = {"co", "com", "org", "net", "gov", "ac", "edu", "or", "ne", "go", "gob", "nom", "mil", "sch"}


class VaultError(Exception):
    pass


class WrongPassword(VaultError):
    pass


def vault_path() -> Path:
    """Where the browser keeps its vault, so there is only ever one."""
    data = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share")
    return data / "SafariQt" / "SafariQt" / "passwords.vault"


def _b64e(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _b64d(text: str) -> bytes:
    return base64.b64decode(text.encode("ascii"))


def derive_key(password: str, salt: bytes, params: dict = None) -> bytes:
    p = params or SCRYPT_PARAMS
    return hashlib.scrypt(password.encode("utf-8"), salt=salt, n=int(p["n"]), r=int(p["r"]), p=int(p["p"]), maxmem=512 * 1024 * 1024, dklen=32)


def seal(key: bytes, plaintext: bytes, aad: bytes) -> str:
    nonce = os.urandom(12)
    return _b64e(nonce + AESGCM(key).encrypt(nonce, plaintext, aad))


def unseal(key: bytes, token: str, aad: bytes) -> bytes:
    raw = _b64d(token)
    return AESGCM(key).decrypt(raw[:12], raw[12:], aad)


def login_origin(url: str) -> str:
    """'accounts.example.com:8443/login?x' → 'https://accounts.example.com:8443'. "" if it isn't a web address."""
    url = url.strip()
    if not url:
        return ""
    try:
        q = urllib.parse.urlsplit(url if "://" in url else "https://" + url)
        host, port = (q.hostname or "").lower(), q.port
    except ValueError:
        return ""
    if q.scheme not in ("http", "https") or not host or " " in host:
        return ""
    default = 443 if q.scheme == "https" else 80
    host = f"[{host}]" if ":" in host else host
    return f"{q.scheme}://{host}" + (f":{port}" if port not in (None, default) else "")


def site_of(url: str) -> str:
    """The site a login belongs to ('https://news.bbc.co.uk' → 'bbc.co.uk'), as the browser reckons it."""
    try:
        host = (urllib.parse.urlsplit(url if "://" in url else "//" + url).hostname or "").lower().strip(".")
    except ValueError:
        return ""
    if not host or "." not in host or ":" in host or re.fullmatch(r"[\d.]+", host):
        return host
    parts = host.split(".")
    if len(parts) >= 3 and len(parts[-1]) == 2 and parts[-2] in SECOND_LEVEL:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def merge3(base: dict, mine: dict, theirs: dict) -> dict:
    """Fold two sets of changes to the same {key: value} together. A key changed (or removed) here keeps this
    side's answer; anything else takes what the other side has now."""
    out = {}
    for key in set(mine) | set(theirs):
        was, me, them = base.get(key), mine.get(key), theirs.get(key)
        take = me if me != was else them
        if take is not None:
            out[key] = take
    return out


class VaultFile:
    """The vault as one app holds it: locked, or unlocked with the logins in memory."""

    def __init__(self, path: Path = None):
        self.path = Path(path) if path else vault_path()
        self.entries, self.never, self.extras = [], set(), {}
        self._key, self._header, self._base, self._stamp = None, {}, None, None

    # ------------------------------------------------------------------ state
    def exists(self) -> bool:
        return self.path.is_file()

    def locked(self) -> bool:
        return self._key is None

    def _read_header(self, fresh: bool = False) -> dict:
        if fresh or not self._header:
            with open(self.path, encoding="utf-8") as f:
                header = json.load(f)
            if not isinstance(header, dict) or header.get("format") != VAULT_FORMAT:
                raise VaultError("The password file isn't a Huginn vault.")
            self._header = header
        return self._header

    def _disk_stamp(self):
        try:
            st = os.stat(self.path)
            return (st.st_mtime_ns, st.st_size)
        except OSError:
            return None

    def _snapshot(self) -> dict:
        return {"entries": {e["id"]: json.dumps(e, sort_keys=True) for e in self.entries if e.get("id")},
                "never": {n: True for n in self.never}, "extras": {k: json.dumps(v, sort_keys=True) for k, v in self.extras.items()}}

    # ------------------------------------------------------------------ create, unlock, lock
    def create(self, master: str) -> None:
        if self.exists():
            raise VaultError("A password vault already exists.")
        if len(master) < MIN_MASTER_LENGTH:
            raise VaultError(f"The master password needs at least {MIN_MASTER_LENGTH} characters.")
        salt, key = os.urandom(16), os.urandom(32)
        self._header = {"format": VAULT_FORMAT, "version": 1, "kdf": {"name": "scrypt", **SCRYPT_PARAMS, "salt": _b64e(salt)},
                        "master": seal(derive_key(master, salt), key, b"master")}
        self._key, self.entries, self.never, self.extras, self._base = key, [], set(), {}, None
        self.save()

    def master_key(self, master: str) -> bytes:
        header = self._read_header(fresh=True)                     # fresh: another app may have changed the master password
        kdf = header["kdf"]
        try:
            return unseal(derive_key(master, _b64d(kdf["salt"]), kdf), header["master"], b"master")
        except InvalidTag:
            raise WrongPassword("That isn't the master password.") from None

    def unlock(self, master: str) -> None:
        self.adopt(self.master_key(master))

    def adopt(self, key: bytes) -> None:
        """Unlock with the vault key itself (from the session agent). Raises VaultError if it doesn't fit."""
        payload = self._open(key)
        self._key = key
        self._take(payload)

    def _open(self, key: bytes) -> dict:
        header = self._read_header(fresh=True)
        stamp = self._disk_stamp()
        try:
            payload = json.loads(unseal(key, header["data"], b"data"))
        except InvalidTag:
            raise VaultError("The password file is damaged, or was changed by something other than Huginn.") from None
        self._stamp = stamp
        return payload

    def _take(self, payload: dict) -> None:
        self.entries = [e for e in payload.get("entries", []) if isinstance(e, dict)]
        self.never = set(payload.get("never", []))
        self.extras = payload.get("extras") if isinstance(payload.get("extras"), dict) else {}
        self._base = self._snapshot()

    def key(self) -> bytes:
        return self._key

    def lock(self) -> None:
        self._key, self.entries, self.never, self.extras, self._base = None, [], set(), {}, None

    def change_master(self, old: str, new: str) -> None:
        self.master_key(old)
        if len(new) < MIN_MASTER_LENGTH:
            raise VaultError(f"The master password needs at least {MIN_MASTER_LENGTH} characters.")
        self._require()
        salt = os.urandom(16)
        self._pending_master = {"kdf": {"name": "scrypt", **SCRYPT_PARAMS, "salt": _b64e(salt)}, "master": seal(derive_key(new, salt), self._key, b"master")}
        try:
            self.save()
        finally:
            self._pending_master = None

    def _require(self) -> None:
        if self._key is None:
            raise VaultError("The passwords are locked.")

    # ------------------------------------------------------------------ reading what another app wrote, and writing
    def refresh(self) -> bool:
        """Pick up what another app has saved since this one last looked. True if anything changed."""
        if self._key is None or self._disk_stamp() == self._stamp:
            return False
        try:
            payload = self._open(self._key)
        except (VaultError, OSError, ValueError):
            return False
        before = self._snapshot()
        self._take(payload)
        return self._snapshot() != before

    def _fold_in_disk(self) -> None:
        """Just before writing: if the file moved on since this app read it, fold its changes into ours."""
        if self._base is None or not self.exists() or self._disk_stamp() == self._stamp:
            if self.exists():
                self._read_header(fresh=True)
            return
        try:
            payload = self._open(self._key)
        except (VaultError, OSError, ValueError):
            return                                                 # unreadable on disk: ours is the only good copy
        theirs = VaultFile(self.path)
        theirs._take(payload)
        base, mine, other = self._base, self._snapshot(), theirs._snapshot()
        entries = merge3(base["entries"], mine["entries"], other["entries"])
        order = [e["id"] for e in self.entries] + [e["id"] for e in theirs.entries]
        self.entries = [json.loads(entries[i]) for i in dict.fromkeys(order) if i in entries]
        self.never = set(merge3(base["never"], mine["never"], other["never"]))
        self.extras = {k: json.loads(v) for k, v in merge3(base["extras"], mine["extras"], other["extras"]).items()}

    def save(self) -> None:
        self._require()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lock = open(str(self.path) + ".lock", "a+")
        try:
            try:
                import fcntl
                fcntl.flock(lock, fcntl.LOCK_EX)                   # one writer at a time, across apps
            except (ImportError, OSError):
                pass
            self._fold_in_disk()
            if getattr(self, "_pending_master", None):
                self._header.update(self._pending_master)
            payload = {"entries": self.entries, "never": sorted(self.never), "saved": time.time()}
            if self.extras:
                payload["extras"] = self.extras
            self._header["data"] = seal(self._key, json.dumps(payload).encode("utf-8"), b"data")
            tmp = str(self.path) + ".tmp"
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(self._header, f)
                f.flush()
                os.fsync(f.fileno())
            if self.exists():
                shutil.copy2(self.path, str(self.path) + ".bak")   # the previous version, in case of a crash
            os.replace(tmp, self.path)
            self._stamp, self._base = self._disk_stamp(), self._snapshot()
        finally:
            lock.close()

    # ------------------------------------------------------------------ logins
    def entry(self, ident: str):
        return next((e for e in self.entries if e.get("id") == ident), None)

    def put(self, ident: str, url: str, username: str, password: str, title: str = "", note: str = "") -> dict:
        """Add a login (ident "") or change one. The browser's fields, the browser's rules: a changed password keeps
        the one before it."""
        self._require()
        now = time.time()
        entry = self.entry(ident) if ident else None
        if entry is None:
            entry = {"id": uuid.uuid4().hex, "url": "", "username": "", "password": "", "title": "", "note": "", "created": now, "updated": now, "used": 0}
            self.entries.append(entry)
        elif entry.get("password") and entry["password"] != password:
            entry["previous"] = entry["password"]
        entry.update({"url": login_origin(url) if login_origin(url) else "", "username": username, "password": password, "title": title, "note": note, "updated": now})
        if url.strip() and not entry["url"]:
            entry["place"] = url.strip()                            # not a web address ("Wi-Fi at home"): kept as written
        else:
            entry.pop("place", None)
        self.save()
        return entry

    def delete(self, ident: str) -> None:
        self._require()
        self.entries = [e for e in self.entries if e.get("id") != ident]
        self.save()

    def matches(self, url: str) -> list:
        """Logins for a page: the same origin first, then the same site (https only)."""
        origin = login_origin(url)
        if not origin or self.locked():
            return []
        site, secure = site_of(origin), origin.startswith("https://")
        exact = [e for e in self.entries if e.get("url") == origin]
        related = [e for e in self.entries if e.get("url") and e["url"] != origin and secure and e["url"].startswith("https://") and site_of(e["url"]) == site]
        newest = lambda e: -float(e.get("used") or e.get("updated") or 0)       # noqa: E731
        return sorted(exact, key=newest) + sorted(related, key=newest)

    # ------------------------------------------------------------------ other apps' secrets (Mail's), under the same lock
    def secret(self, drawer: str, name: str):
        return (self.extras.get(drawer) or {}).get(name)

    def set_secret(self, drawer: str, name: str, value) -> None:
        self._require()
        self.refresh()
        box = dict(self.extras.get(drawer) or {})
        if value is None:
            box.pop(name, None)
        else:
            box[name] = value
        if box:
            self.extras[drawer] = box
        else:
            self.extras.pop(drawer, None)
        self.save()


# ============================================================================================= one unlock
def runtime_dir() -> Path:
    return Path(os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}")


def agent_socket() -> Path:
    return runtime_dir() / "huginn-vault.sock"


def sharing_on() -> bool:
    """"Unlock once for all Huginn apps" (Passwords can turn it off)."""
    try:
        cfg = json.loads((Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "huginn" / "vault.json").read_text(encoding="utf-8"))
        return bool(cfg.get("share", True))
    except (OSError, ValueError):
        return True


def set_sharing(on: bool) -> None:
    folder = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "huginn"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "vault.json").write_text(json.dumps({"share": bool(on)}), encoding="utf-8")
    if not on:
        agent_ask({"do": "lock"})


TRUSTED_SCRIPTS = ("huginn_app.py", "huginn_vault.py", "huginn_mail.py", "huginn_accounts.py", "safari_browser.py", "huginn")
IDLE_SECONDS = 60 * 60                                            # the same hour the browser has always used


def peer_is_huginn(pid: int) -> bool:
    """Is the program on the other end one of Huginn's own, installed where only the administrator can change it?

    The agent only answers programs run as you, and of those only a Python started on one of Huginn's own scripts
    that sits in a root-owned place (/usr/share/huginn-apps, /opt/huginn, /usr/bin). A script in your home folder
    doesn't qualify, so a copy someone altered can't ask. This narrows who can ask; it is not a wall: a program
    already running as you has other ways to reach an unlocked app's memory. Locking (or turning sharing off) is."""
    try:
        argv = Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")
        exe = os.path.realpath(f"/proc/{pid}/exe")
    except OSError:
        return False
    if not os.path.basename(exe).startswith("python"):
        return False
    words = [a.decode("utf-8", "replace") for a in argv[1:] if a]
    while words and words[0] in ("-I", "-E", "-s", "-B", "-u", "-O"):
        words.pop(0)
    if not words or words[0].startswith("-"):
        return False                                               # -c, -m and friends run code that isn't ours
    script = os.path.realpath(words[0] if os.path.isabs(words[0]) else os.path.join(os.path.realpath(f"/proc/{pid}/cwd"), words[0]))
    if os.path.basename(script) not in TRUSTED_SCRIPTS:
        return False
    try:
        for part in (script, os.path.dirname(script)):
            st = os.stat(part)
            if st.st_uid != 0 or st.st_mode & 0o022:
                return False
    except OSError:
        return False
    return True


class VaultAgent:
    """Holds the vault key for this login session, in memory only, and hands it to Huginn's own apps.

    Started by whichever app unlocks first. It forgets the key after an hour without use, when any app says Lock,
    and when it exits (logging out ends it). It never sees the master password."""

    def __init__(self, path: Path = None, check=peer_is_huginn, idle: float = IDLE_SECONDS):
        self.path, self.check, self.idle = path or agent_socket(), check, idle
        self._key, self._used, self._gen, self._idled = None, 0.0, 0, False
        self._lock = threading.Lock()

    def answer(self, ask: dict) -> dict:
        with self._lock:
            if self._key is not None and time.monotonic() - self._used > self.idle:
                self._key, self._idled = None, True
                self._gen += 1
            do = ask.get("do")
            if do == "put" and sharing_on():
                try:
                    key = _b64d(str(ask.get("key", "")))
                except ValueError:
                    key = b""
                if len(key) == 32:
                    if key != self._key:
                        self._gen += 1
                    self._key, self._used, self._idled = key, time.monotonic(), False
            elif do == "get":
                if self._key is not None and sharing_on():
                    if ask.get("touch", True):
                        self._used = time.monotonic()
                    return {"ok": True, "key": _b64e(self._key), "gen": self._gen}
                return {"ok": True, "key": "", "gen": self._gen, "idled": self._idled}
            elif do == "touch":
                if self._key is not None:
                    self._used = time.monotonic()
            elif do == "lock":
                if self._key is not None:
                    self._gen += 1
                self._key, self._idled = None, False
            return {"ok": True, "open": self._key is not None, "gen": self._gen}

    def serve(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.path.unlink()
        except OSError:
            pass
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        old = os.umask(0o177)
        try:
            server.bind(str(self.path))
        finally:
            os.umask(old)
        server.listen(8)
        self._server = server
        quiet_since = time.monotonic()
        server.settimeout(30)
        while True:
            try:
                conn, _ = server.accept()
            except socket.timeout:
                with self._lock:
                    if self._key is not None and time.monotonic() - self._used > self.idle:
                        self._key, self._idled = None, True
                        self._gen += 1
                    if self._key is None and time.monotonic() - quiet_since > 120:
                        break                                      # nothing to hold and nobody asking: go away
                continue
            except OSError:
                break
            quiet_since = time.monotonic()
            threading.Thread(target=self._talk, args=(conn,), daemon=True).start()
        try:
            server.close()
            self.path.unlink()
        except OSError:
            pass

    def _talk(self, conn) -> None:
        try:
            pid, uid, _gid = struct.unpack("3i", conn.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i")))
            if uid != os.getuid() or not self.check(pid):
                conn.sendall(b'{"ok": false}\n')
                return
            conn.settimeout(5)
            line = conn.makefile("rb").readline(4096)
            conn.sendall(json.dumps(self.answer(json.loads(line.decode("utf-8")))).encode() + b"\n")
        except (OSError, ValueError, struct.error):
            pass
        finally:
            conn.close()


def agent_ask(ask: dict, start: bool = False, path: Path = None) -> dict:
    """One question to the session agent. {} if there is none (and `start` is off) or it won't answer us."""
    if not hasattr(socket, "AF_UNIX"):
        return {}
    path = path or agent_socket()
    for attempt in range(2):
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:
                conn.settimeout(3)
                conn.connect(str(path))
                conn.sendall(json.dumps(ask).encode() + b"\n")
                reply = json.loads(conn.makefile("rb").readline(4096).decode("utf-8") or "{}")
                return reply if reply.get("ok") else {}
        except (OSError, ValueError):
            if attempt or not start:
                return {}
            try:
                subprocess.Popen([sys.executable or "python3", str(Path(__file__).resolve()), "agent"], start_new_session=True,
                                 stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except OSError:
                return {}
            for _ in range(40):
                if path.exists():
                    break
                time.sleep(0.05)
    return {}


class Session:
    """What an app does around its VaultFile to take part in "unlock once"."""

    def __init__(self, vault: VaultFile):
        self.vault, self.gen = vault, None

    def try_unlock(self) -> bool:
        """Unlock from the session, if another Huginn app already did. No prompt, no error."""
        if not self.vault.locked():
            return True
        if not self.vault.exists() or not sharing_on():
            return False
        reply = agent_ask({"do": "get"})
        if not reply.get("key"):
            return False
        try:
            self.vault.adopt(_b64d(reply["key"]))
        except (VaultError, OSError, ValueError):
            return False
        self.gen = reply.get("gen")
        return True

    def unlocked(self) -> None:
        """This app was just unlocked with the master password: let the others in."""
        if sharing_on() and not self.vault.locked():
            reply = agent_ask({"do": "put", "key": _b64e(self.vault.key())}, start=True)
            self.gen = reply.get("gen")

    def lock_everywhere(self) -> None:
        agent_ask({"do": "lock"})
        self.gen = None

    def locked_elsewhere(self, by_hand_only: bool = False) -> bool:
        """Did another app lock the session since this one joined it? (Then this one should lock too.)
        `by_hand_only` ignores the session simply going idle: Mail keeps checking for mail then."""
        if self.gen is None or self.vault.locked():
            return False
        reply = agent_ask({"do": "get", "touch": False})
        if not reply or (reply.get("key") and reply.get("gen") == self.gen):
            return False
        return not (by_hand_only and reply.get("idled") and not reply.get("key"))

    def touch(self) -> None:
        if self.gen is not None:
            agent_ask({"do": "touch"})


# ============================================================================================ small helpers
PASSWORD_ALPHABET = "abcdefghijkmnopqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def generate_password() -> str:
    """The browser's strong password: three groups of six, mixed case and digits."""
    while True:
        word = "-".join("".join(secrets.choice(PASSWORD_ALPHABET) for _ in range(6)) for _ in range(3))
        if any(c.islower() for c in word) and any(c.isupper() for c in word) and any(c.isdigit() for c in word):
            return word


if __name__ == "__main__":
    if sys.argv[1:2] == ["agent"]:
        VaultAgent().serve()
    else:
        print(__doc__)
