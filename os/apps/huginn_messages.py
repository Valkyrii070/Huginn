"""Messages: chat over Matrix, the open network anyone can run a server for (matrix.org is the biggest one).

Conversations are end-to-end encrypted when python3-olm is installed (it is, in Huginn OS): new chats are made
encrypted, and messages in them can only be read on the devices of the people in the chat. The sign-in token and the
key that locks this device's encryption store are kept in the shared vault, next to Passwords and Mail; the password
itself isn't kept. The Matrix work is done by matrix-nio (python3-matrix-nio) on a thread of its own.

Not yet: verifying devices with emoji, reading old encrypted messages from before this device signed in (they need
the other device's key backup), calls."""
import asyncio
import datetime as dt
import json
import mimetypes
import os
import re
import secrets
import shutil
import subprocess
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path

from PySide6.QtCore import Property, QObject, QStandardPaths, QTimer, QUrl, Signal, Slot

HOME = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share") / "huginn" / "messages"
DRAWER = "matrix"
FILE_LIMIT = 100 * 1024 * 1024

try:
    import nio
    from nio.crypto import ENCRYPTION_ENABLED
    HAVE_NIO = True
except ImportError:
    nio, ENCRYPTION_ENABLED, HAVE_NIO = None, False, False


def server_of(user: str) -> str:
    m = re.fullmatch(r"@?[^:@\s]+:([A-Za-z0-9.\-]+(?::\d+)?)", user.strip())
    return m.group(1) if m else ""


def find_homeserver(server: str) -> str:
    """Where a Matrix server's client API lives: its .well-known says, or it is the server itself."""
    if re.match(r"https?://", server):
        return server.rstrip("/")
    try:
        req = urllib.request.Request(f"https://{server}/.well-known/matrix/client", headers={"Accept": "application/json", "User-Agent": "Huginn Messages"})
        with urllib.request.urlopen(req, timeout=10) as r:
            base = json.loads(r.read(100_000)).get("m.homeserver", {}).get("base_url", "")
            if base.startswith(("https://", "http://")):
                return base.rstrip("/")
    except (OSError, ValueError, AttributeError):
        pass
    return f"https://{server}"


def initials(name: str) -> str:
    words = [w for w in re.split(r"[\s@:._-]+", name) if w]
    return ((words[0][0] + (words[1][0] if len(words) > 1 else "")) if words else "?").upper()


def stamp_words(ms: int, now: float = None) -> str:
    when = dt.datetime.fromtimestamp(ms / 1000)
    today = dt.date.fromtimestamp(now or time.time())
    if when.date() == today:
        return when.strftime("%H:%M")
    if (today - when.date()).days < 7:
        return when.strftime("%a %H:%M")
    return when.strftime("%-d %b")


class Messages(QObject):
    changed = Signal()
    said = Signal(str, bool)
    shown = Signal()
    _back = Signal(object)

    def __init__(self, demo: bool = False, vault_file: Path = None):
        super().__init__()
        self._back.connect(lambda fn: fn())
        self._demo = demo
        self._state, self._why = "start", ""                   # start | signin | locked | connecting | ready | broken
        self._me, self._client, self._loop, self._thread = "", None, None, None
        self._rooms, self._invites, self._timeline, self._prev = {}, {}, {}, {}
        self._secret_ids = set()                                # rooms seen encrypted: nothing is ever sent to them in the clear
        self._open, self._query, self._busy = "", "", ""
        self._prefs = {"stay": True, "preview": False}
        self._badge = -1
        self._focused = True
        if demo:
            self._demo_fill()
            return
        import huginn_vault as hv
        self._hv = hv
        self._vault = hv.VaultFile(vault_file)
        self._session = hv.Session(self._vault)
        self._load_prefs()
        if not HAVE_NIO:
            self._state, self._why = "broken", "Messages needs matrix-nio (python3-matrix-nio), which isn't installed."
            return
        QTimer.singleShot(0, self._begin)

    @staticmethod
    def stay_wanted() -> bool:
        try:
            return bool(json.loads((HOME / "prefs.json").read_text(encoding="utf-8")).get("stay", True))
        except (OSError, ValueError):
            return True

    # ---- preferences (not secret)
    def _load_prefs(self) -> None:
        try:
            self._prefs.update(json.loads((HOME / "prefs.json").read_text(encoding="utf-8")))
        except (OSError, ValueError):
            pass

    def _save_prefs(self) -> None:
        HOME.mkdir(parents=True, exist_ok=True)
        (HOME / "prefs.json").write_text(json.dumps(self._prefs), encoding="utf-8")

    # ---- the account, from the vault
    def _begin(self) -> None:
        if not self._vault.exists():
            self._state = "signin"
        elif self._vault.locked() and not self._session.try_unlock():
            self._state = "locked" if (HOME / "signed-in").exists() else "signin"
        else:
            self._restore()
        self.changed.emit()

    @Slot(str, result=str)
    def unlock(self, master: str) -> str:
        try:
            self._vault.unlock(master)
        except self._hv.WrongPassword as err:
            return str(err)
        except (self._hv.VaultError, OSError) as err:
            return str(err)
        self._session.unlocked()
        self._restore()
        self.changed.emit()
        return ""

    def _restore(self) -> None:
        acct = self._vault.secret(DRAWER, "account") if not self._vault.locked() else None
        if not acct:
            self._state = "signin"
            return
        self._start_client(acct)

    def _start_client(self, acct: dict) -> None:
        self._me = acct["user_id"]
        self._state = "connecting"
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._loop.run_forever, daemon=True)
        self._thread.start()
        self._run(self._connect(acct))

    def _run(self, coro, then=None):
        """Run a coroutine on the Matrix thread; `then(result)` comes back on the screen's thread."""
        if not self._loop:
            return
        fut = asyncio.run_coroutine_threadsafe(coro, self._loop)

        def done(f):
            try:
                result = f.result()
            except Exception as err:                               # every failure becomes something the screen can say
                result = err
            if then:
                self._back.emit(lambda: then(result))
        fut.add_done_callback(done)

    async def _connect(self, acct: dict) -> None:
        store = HOME / "store"
        store.mkdir(parents=True, exist_ok=True)
        os.chmod(store, 0o700)
        config = nio.AsyncClientConfig(store_sync_tokens=False, encryption_enabled=ENCRYPTION_ENABLED, pickle_key=acct.get("pickle", "huginn"))
        client = nio.AsyncClient(acct["homeserver"], acct["user_id"], device_id=acct["device_id"], store_path=str(store), config=config)
        client.restore_login(acct["user_id"], acct["device_id"], acct["access_token"])
        self._client = client
        client.add_event_callback(self._on_event, (nio.RoomMessage, nio.MegolmEvent))
        client.add_event_callback(self._on_invite, (nio.InviteMemberEvent,))
        first = True
        while True:
            try:
                resp = await client.sync(timeout=30000, full_state=first, sync_filter={"room": {"timeline": {"limit": 40}}, "presence": {"not_types": ["*"]}})
            except Exception as err:                                # network gone: wait and try again
                self._back.emit(lambda e=err: self._set("connecting", f"Can't reach the server ({e.__class__.__name__}). Trying again…"))
                await asyncio.sleep(8)
                continue
            if isinstance(resp, nio.SyncError):
                if resp.status_code in ("M_UNKNOWN_TOKEN", "M_MISSING_TOKEN"):
                    self._back.emit(lambda: self._signed_out_elsewhere())
                    return
                await asyncio.sleep(8)
                continue
            first = False
            await self._on_sync(resp)                               # nio only runs response callbacks in sync_forever
            if ENCRYPTION_ENABLED:
                try:
                    if client.should_upload_keys:
                        await client.keys_upload()
                    if client.should_query_keys:
                        await client.keys_query()
                    if client.should_claim_keys:
                        await client.keys_claim(client.get_users_for_key_claiming())
                    await client.send_to_device_messages()
                except Exception:
                    pass

    def _set(self, state: str, why: str = "") -> None:
        self._state, self._why = state, why
        self.changed.emit()

    def _signed_out_elsewhere(self) -> None:
        self._forget_account()
        self._set("signin", "You were signed out (from another device, or the session ended). Sign in again.")

    # ---- what arrives
    def _item(self, room, event) -> dict:
        """One message as the screen shows it."""
        e = {"id": event.event_id, "sender": event.sender, "name": room.user_name(event.sender) or event.sender, "mine": event.sender == self._me,
             "ts": event.server_timestamp, "time": stamp_words(event.server_timestamp), "kind": "text", "body": "", "file": None}
        if isinstance(event, nio.MegolmEvent):
            e.update(kind="locked", body="This message can't be read on this device: it was sent before you signed in here, or its key hasn't arrived yet.")
        elif isinstance(event, (nio.RoomMessageText, nio.RoomMessageNotice)):
            e["body"] = event.body
        elif isinstance(event, nio.RoomMessageEmote):
            e.update(kind="emote", body=event.body)
        elif isinstance(event, (nio.RoomMessageMedia, nio.RoomEncryptedMedia)):
            src = event.source.get("content", {})
            e.update(kind="image" if isinstance(event, (nio.RoomMessageImage, nio.RoomEncryptedImage)) else "file", body=event.body,
                     file={"url": getattr(event, "url", ""), "name": event.body, "size": (src.get("info") or {}).get("size", 0), "key": getattr(event, "key", None),
                           "hash": (getattr(event, "hashes", None) or {}).get("sha256"), "iv": getattr(event, "iv", None)})
        else:
            e["body"] = getattr(event, "body", "") or ""
        return e

    async def _on_event(self, room, event) -> None:
        item = self._item(room, event)
        rid = room.room_id
        self._back.emit(lambda: self._arrived(rid, item))

    def _arrived(self, rid: str, item: dict) -> None:
        rows = self._timeline.setdefault(rid, [])
        if any(r["id"] == item["id"] for r in rows):
            return
        rows.append(item)
        rows.sort(key=lambda r: r["ts"])
        del rows[:-600]
        fresh = time.time() * 1000 - item["ts"] < 120_000
        if fresh and not item["mine"] and (rid != self._open or not self._focused) and self._state == "ready":
            room = self._client.rooms.get(rid) if self._client else None
            self._notify(room.display_name if room else "Messages", item)
        if rid == self._open and self._focused and not item["mine"]:
            self._read(rid, item["id"])
        self.changed.emit()

    async def _on_invite(self, room, event) -> None:
        self._back.emit(self.changed.emit)

    async def _on_sync(self, resp) -> None:
        prev = {rid: info.timeline.prev_batch for rid, info in resp.rooms.join.items()}
        self._back.emit(lambda: self._synced(prev))

    def _synced(self, prev: dict) -> None:
        for rid, token in prev.items():
            self._prev.setdefault(rid, token)
        if self._state != "ready":
            self._set("ready", "")
        self._write_badge()
        self.changed.emit()

    def _notify(self, title: str, item: dict) -> None:
        if not shutil.which("notify-send"):
            return
        body = (item["body"][:140] if self._prefs.get("preview") and item["kind"] in ("text", "emote") else "New message")
        subprocess.Popen(["notify-send", "--app-name=Messages", "--icon=huginn-messages", f"{item['name']} · {title}" if item["name"] != title else title, body],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def _unread_total(self) -> int:
        if not self._client:
            return 0
        return sum(r.unread_notifications for r in self._client.rooms.values()) + len(self._client.invited_rooms)

    def _write_badge(self) -> None:
        base = os.environ.get("XDG_RUNTIME_DIR")
        n = self._unread_total()
        if self._demo or not base or n == self._badge:
            return
        self._badge = n
        folder = Path(base) / "huginn" / "badges"
        try:
            folder.mkdir(parents=True, exist_ok=True)
            if n:
                (folder / ".messages.part").write_text(str(n), encoding="ascii")
                os.replace(folder / ".messages.part", folder / "messages")
            else:
                (folder / "messages").unlink(missing_ok=True)
        except OSError:
            pass

    # ---- what QML sees
    def _demo_fill(self) -> None:
        now = int(time.time() * 1000)
        self._me = "@val:huginn.example"
        people = [("!r1", "Ingrid Solberg", "@ingrid:matrix.example", True, 0), ("!r2", "Book club", "", True, 3), ("!r3", "Magnus", "@magnus:huginn.example", True, 1),
                  ("!r4", "Desk crew", "", False, 0), ("!r5", "Mum", "@mum:matrix.example", True, 0)]
        lines = {"!r1": [("@ingrid:matrix.example", "Are you still up for the ferry on Saturday?", 95), ("@val:huginn.example", "Yes! The 9:40 one?", 90), ("@ingrid:matrix.example", "Perfect. I'll bring coffee ☕", 88),
                         ("@val:huginn.example", "I'll bring the cinnamon buns then", 30), ("@ingrid:matrix.example", "Deal. See you at the pier", 4)],
                 "!r2": [("@sigrid:x.example", "Chapter nine was something else", 300), ("@tor:x.example", "No spoilers, I'm on six", 200), ("@sigrid:x.example", "Fine 🙊", 180)],
                 "!r3": [("@magnus:huginn.example", "Sent you the photos from the trip", 60)], "!r4": [("@val:huginn.example", "Moved the meeting to Thursday", 3000)], "!r5": [("@mum:matrix.example", "Call me when you can x", 9000)]}
        for rid, name, peer, enc, unread in people:
            self._rooms[rid] = {"id": rid, "name": name, "peer": peer, "encrypted": enc, "unread": unread, "members": 2 if peer else 6}
            self._timeline[rid] = [{"id": f"{rid}{i}", "sender": s, "name": s.split(":")[0].lstrip("@").title() if s != self._me else "You", "mine": s == self._me,
                                    "ts": now - m * 60000, "time": stamp_words(now - m * 60000), "kind": "text", "body": b, "file": None} for i, (s, b, m) in enumerate(lines[rid])]
        self._timeline["!r3"].append({"id": "!r3img", "sender": "@magnus:huginn.example", "name": "Magnus", "mine": False, "ts": now - 59 * 60000, "time": stamp_words(now - 59 * 60000),
                                      "kind": "file", "body": "Lofoten-photos.zip", "file": {"name": "Lofoten-photos.zip", "size": 48_200_000}})
        self._invites = {"!i1": {"id": "!i1", "name": "Northern lights watchers", "by": "Astrid"}}
        self._open, self._state = "!r1", "ready"

    def _room_face(self, room) -> dict:
        if self._demo:
            r = dict(room)
            last = self._timeline.get(r["id"], [{}])[-1]
            r.update(initials=initials(r["name"]), last=("You: " if last.get("mine") else "") + (last.get("body") or ""), when=last.get("time", ""), ts=last.get("ts", 0))
            return r
        rows = self._timeline.get(room.room_id, [])
        last = rows[-1] if rows else {}
        peer = next((u for u in room.users if u != self._me), "") if room.member_count <= 2 else ""
        if room.encrypted:
            self._secret_ids.add(room.room_id)
        return {"id": room.room_id, "name": room.display_name or room.room_id, "initials": initials(room.display_name or "?"), "encrypted": room.encrypted,
                "unread": room.unread_notifications, "members": room.member_count, "peer": peer,
                "last": ("You: " if last.get("mine") else "") + (last.get("body") or "")[:80], "when": last.get("time", ""), "ts": last.get("ts", 0)}

    def _client_rooms(self) -> list:
        """The rooms nio knows (it changes them on its own thread, so copy with care)."""
        for _ in range(5):
            try:
                return list(self._client.rooms.values()) if self._client else []
            except RuntimeError:
                time.sleep(0.01)
        return []

    def _get_rooms(self) -> list:
        rooms = list(self._rooms.values()) if self._demo else self._client_rooms()
        faces = [self._room_face(r) for r in rooms]
        words = self._query.lower().split()
        faces = [f for f in faces if all(w in f["name"].lower() for w in words)]
        return sorted(faces, key=lambda f: -f["ts"])

    def _get_invites(self) -> list:
        if self._demo:
            return list(self._invites.values())
        if not self._client:
            return []
        return [{"id": rid, "name": r.display_name or "A chat", "by": r.user_name(r.inviter) if getattr(r, "inviter", None) else ""} for rid, r in self._client.invited_rooms.items()]

    def _get_thread(self) -> list:
        rows = self._timeline.get(self._open, [])
        out, last_sender, last_day = [], None, None
        for r in rows:
            day = dt.date.fromtimestamp(r["ts"] / 1000)
            face = dict(r, first=r["sender"] != last_sender or day != last_day, day=day.strftime("%A %-d %B") if day != last_day else "",
                        size=_size(r["file"]["size"]) if r.get("file") and r["file"].get("size") else "")
            face["file"] = None if not r.get("file") else {"name": r["file"].get("name", ""), "size": face["size"]}
            out.append(face)
            last_sender, last_day = r["sender"], day
        return out

    def _get_current(self) -> dict:
        if not self._open:
            return {}
        room = self._rooms.get(self._open) if self._demo else self._client.rooms.get(self._open) if self._client else None
        if room is None:
            return {}
        face = self._room_face(room)
        face["more"] = bool(self._prev.get(self._open)) and not self._demo
        return face

    rooms = Property("QVariantList", _get_rooms, notify=changed)
    invites = Property("QVariantList", _get_invites, notify=changed)
    thread = Property("QVariantList", _get_thread, notify=changed)
    current = Property("QVariantMap", _get_current, notify=changed)
    state = Property(str, lambda self: self._state, notify=changed)
    why = Property(str, lambda self: self._why, notify=changed)
    me = Property(str, lambda self: self._me, notify=changed)
    busy = Property(str, lambda self: self._busy, notify=changed)
    encryption = Property(bool, lambda self: self._demo or ENCRYPTION_ENABLED, constant=True)
    hasAccount = Property(bool, lambda self: self._state in ("ready", "connecting") or self._demo, notify=changed)
    stayOn = Property(bool, lambda self: bool(self._prefs.get("stay", True)), notify=changed)
    preview = Property(bool, lambda self: bool(self._prefs.get("preview")), notify=changed)
    device = Property(str, lambda self: (self._client.device_id if self._client else "DEMODEVICE" if self._demo else ""), notify=changed)

    @Slot(str)
    def search(self, text: str) -> None:
        self._query = text
        self.changed.emit()

    @Slot(bool)
    def setFocused(self, on: bool) -> None:
        self._focused = on
        if on and self._open:
            self._read_latest()

    @Slot(str)
    def open(self, rid: str) -> None:
        self._open = rid
        self._read_latest()
        self.changed.emit()

    def _read_latest(self) -> None:
        rows = self._timeline.get(self._open, [])
        if rows and not self._demo:
            self._read(self._open, rows[-1]["id"])
        elif self._demo and self._open in self._rooms:
            self._rooms[self._open]["unread"] = 0

    def _read(self, rid: str, event_id: str) -> None:
        if self._client:
            self._run(self._client.room_read_markers(rid, event_id, event_id), lambda r: (self._write_badge(), self.changed.emit()))

    # ---- signing in and out
    @Slot(str, str, str, str, result=str)
    def signIn(self, address: str, password: str, master: str, homeserver: str = "") -> str:
        """Matrix address (@name:server) and password. With no vault yet, `master` makes one. `homeserver` is only
        for servers that don't say where they live (https://matrix.example.org). Returns "" or why not; the result
        of the sign-in itself comes later (state ready, or why)."""
        if self._demo:
            return ""
        address = address.strip()
        server = server_of(address)
        if not server:
            return "Type your full Matrix address, like @name:matrix.org."
        if not password:
            return "Type your password."
        if not self._vault.exists():
            if len(master) < 10:
                return "Pick a master password for your vault (at least 10 characters). It protects your sign-in, with your other passwords."
            try:
                self._vault.create(master)
                self._session.unlocked()
            except (self._hv.VaultError, OSError) as err:
                return f"Couldn't make the vault: {err}"
        elif self._vault.locked():
            why = self.unlock(master) if master else "Type your vault's master password too."
            if why:
                return why
        user = address if address.startswith("@") else "@" + address
        self._busy = "signing in"
        self.changed.emit()

        def go():
            base = homeserver.strip().rstrip("/") if re.match(r"https?://", homeserver.strip()) else find_homeserver(server)
            loop = asyncio.new_event_loop()
            try:
                client = nio.AsyncClient(base, user)
                resp = loop.run_until_complete(client.login(password, device_name="Huginn OS"))
                loop.run_until_complete(client.close())
            finally:
                loop.close()
            return base, resp

        def done(result):
            self._busy = ""
            if isinstance(result, Exception):
                self._set("signin", f"Couldn't reach {server}: {result}")
                return
            base, resp = result
            if not isinstance(resp, nio.LoginResponse):
                words = {"M_FORBIDDEN": "That address and password don't match.", "M_USER_DEACTIVATED": "That account was closed.",
                         "M_LIMIT_EXCEEDED": "Too many tries. Wait a minute."}.get(getattr(resp, "status_code", ""), getattr(resp, "message", "") or "Sign-in didn't work.")
                self._set("signin", words)
                return
            acct = {"user_id": resp.user_id, "device_id": resp.device_id, "access_token": resp.access_token, "homeserver": base, "pickle": secrets.token_urlsafe(24)}
            try:
                self._vault.set_secret(DRAWER, "account", acct)
            except (self._hv.VaultError, OSError) as err:
                self._set("signin", f"Signed in, but the sign-in couldn't be kept in the vault: {err}")
                return
            HOME.mkdir(parents=True, exist_ok=True)
            (HOME / "signed-in").write_text(resp.user_id, encoding="utf-8")
            self._start_client(acct)
            self.changed.emit()
        threading.Thread(target=lambda: self._back.emit(lambda: done(_safe(go))), daemon=True).start()
        return ""

    @Slot()
    def signOut(self) -> None:
        """Sign this device out on the server, and forget the token and this device's keys here."""
        if self._demo or not self._client:
            return
        client = self._client

        async def out():
            try:
                await client.logout()
            finally:
                await client.close()
        self._run(out(), lambda r: (self._forget_account(), self._set("signin", "")))

    def _forget_account(self) -> None:
        if self._loop:
            self._loop.call_soon_threadsafe(self._loop.stop)
        self._client, self._loop = None, None
        self._timeline.clear()
        self._prev.clear()
        self._open = ""
        try:
            if not self._vault.locked():
                self._vault.set_secret(DRAWER, "account", None)
        except (self._hv.VaultError, OSError):
            pass
        shutil.rmtree(HOME / "store", ignore_errors=True)
        (HOME / "signed-in").unlink(missing_ok=True)
        self._badge = -1
        self._write_badge()

    @Slot(str, bool)
    def setPref(self, key: str, on: bool) -> None:
        if key in ("stay", "preview"):
            self._prefs[key] = bool(on)
            if not self._demo:
                self._save_prefs()
                if key == "stay":
                    from PySide6.QtGui import QGuiApplication
                    if QGuiApplication.instance():
                        QGuiApplication.instance().setQuitOnLastWindowClosed(not on)
            self.changed.emit()

    # ---- talking
    @Slot(str)
    def send(self, text: str) -> None:
        text = text.strip()
        if not text or not self._open:
            return
        if self._demo:
            now = int(time.time() * 1000)
            self._timeline[self._open].append({"id": f"d{now}", "sender": self._me, "name": "You", "mine": True, "ts": now, "time": stamp_words(now), "kind": "text", "body": text, "file": None})
            self.changed.emit()
            return
        rid, client = self._open, self._client
        content = {"msgtype": "m.emote", "body": text[4:]} if text.startswith("/me ") else {"msgtype": "m.text", "body": text}

        secret = rid in self._secret_ids

        async def go():
            room = client.rooms.get(rid)
            if secret and not (client.olm and room and room.encrypted):
                return NOT_READY                                    # never fall back to sending it in the clear
            if room and room.encrypted and not room.members_synced:
                await client.joined_members(rid)
            return await client.room_send(rid, "m.room.message", content, ignore_unverified_devices=True)
        self._run(go(), lambda r: self.said.emit("Not sent: " + _why(r), True) if not isinstance(r, nio.RoomSendResponse) else None)

    @Slot(result="QVariantList")
    def fileChoices(self) -> list:
        out = []
        for loc in (QStandardPaths.PicturesLocation, QStandardPaths.DownloadLocation, QStandardPaths.DocumentsLocation):
            folder = Path(QStandardPaths.writableLocation(loc) or Path.home())
            try:
                out += [p for p in folder.iterdir() if p.is_file() and not p.name.startswith(".")]
            except OSError:
                continue
        out.sort(key=lambda p: -p.stat().st_mtime)
        return [{"name": p.name, "path": str(p), "where": p.parent.name, "size": _size(p.stat().st_size)} for p in out[:40]]

    @Slot(str)
    def sendFile(self, path: str) -> None:
        path = QUrl(path).toLocalFile() if path.startswith("file:") else path
        p = Path(path)
        if self._demo or not self._open or not p.is_file():
            return
        if p.stat().st_size > FILE_LIMIT:
            self.said.emit("That file is over 100 MB; most servers won't take it.", True)
            return
        rid, client = self._open, self._client
        kind = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
        self._busy = f"sending {p.name}"
        self.changed.emit()

        must_hide = rid in self._secret_ids

        async def go():
            room = client.rooms.get(rid)
            if must_hide and not (client.olm and room and room.encrypted):
                return NOT_READY
            secret = bool(room and room.encrypted and ENCRYPTION_ENABLED)
            data = p.read_bytes()
            up, keys = await client.upload(lambda *_: data, content_type=kind, filename=p.name, encrypt=secret, filesize=len(data))
            if not isinstance(up, nio.UploadResponse):
                return up
            content = {"msgtype": "m.image" if kind.startswith("image/") else "m.video" if kind.startswith("video/") else "m.audio" if kind.startswith("audio/") else "m.file",
                       "body": p.name, "info": {"mimetype": kind, "size": len(data)}}
            if secret:
                content["file"] = dict(keys, url=up.content_uri, mimetype=kind)
            else:
                content["url"] = up.content_uri
            if room and room.encrypted and not room.members_synced:
                await client.joined_members(rid)
            return await client.room_send(rid, "m.room.message", content, ignore_unverified_devices=True)

        def done(r):
            self._busy = ""
            if not isinstance(r, nio.RoomSendResponse):
                self.said.emit("Not sent: " + _why(r), True)
            self.changed.emit()
        self._run(go(), done)

    @Slot(str)
    def saveFile(self, event_id: str) -> None:
        """Download a file someone sent (decrypting it here if the chat is encrypted) into Downloads."""
        item = next((r for r in self._timeline.get(self._open, []) if r["id"] == event_id), None)
        if self._demo or not item or not item.get("file") or not item["file"].get("url"):
            return
        f, client = item["file"], self._client
        folder = Path(QStandardPaths.writableLocation(QStandardPaths.DownloadLocation) or Path.home() / "Downloads")

        async def go():
            resp = await client.download(f["url"])
            if not isinstance(resp, nio.DownloadResponse):
                return resp
            body = resp.body
            if f.get("key"):
                from nio.crypto import attachments
                body = attachments.decrypt_attachment(body, f["key"]["k"], f["hash"], f["iv"])
            name = re.sub(r'[\\/:*?"<>|]+', "_", f.get("name") or "file") or "file"
            target, n = folder / name, 2
            while target.exists():
                target, n = folder / f"{Path(name).stem} ({n}){Path(name).suffix}", n + 1
            folder.mkdir(parents=True, exist_ok=True)
            target.write_bytes(body)
            return target

        self._run(go(), lambda r: self.said.emit(f"Saved {r.name} in Downloads.", False) if isinstance(r, Path) else self.said.emit("Couldn't get it: " + _why(r), True))

    @Slot()
    def earlier(self) -> None:
        """Fetch older messages in the open chat."""
        rid, token, client = self._open, self._prev.get(self._open), self._client
        if self._demo or not rid or not token or not client:
            return

        async def go():
            resp = await client.room_messages(rid, start=token, limit=40)
            if not isinstance(resp, nio.RoomMessagesResponse):
                return resp
            room = client.rooms.get(rid)
            items = []
            for ev in resp.chunk:
                if isinstance(ev, nio.MegolmEvent):
                    try:
                        ev = client.decrypt_event(ev)
                    except Exception:
                        pass
                if isinstance(ev, (nio.RoomMessage, nio.MegolmEvent)):
                    items.append(self._item(room, ev))
            return resp.end, items

        def done(r):
            if isinstance(r, tuple):
                end, items = r
                self._prev[rid] = end if items else None
                for it in items:
                    rows = self._timeline.setdefault(rid, [])
                    if not any(x["id"] == it["id"] for x in rows):
                        rows.append(it)
                self._timeline[rid].sort(key=lambda x: x["ts"])
                self.changed.emit()
        self._run(go(), done)

    @Slot(str, result=str)
    def startChat(self, who: str) -> str:
        """A new, encrypted chat with someone (their Matrix address)."""
        who = who.strip()
        if not who.startswith("@"):
            who = "@" + who
        if not server_of(who):
            return "Type their full Matrix address, like @name:matrix.org."
        if who == self._me:
            return "That's you."
        if self._demo:
            return ""
        client = self._client
        existing = next((r for r in client.rooms.values() if r.member_count <= 2 and who in r.users), None) if client else None
        if existing:
            self.open(existing.room_id)
            return ""

        async def go():
            state = [{"type": "m.room.encryption", "state_key": "", "content": {"algorithm": "m.megolm.v1.aes-sha2"}}] if ENCRYPTION_ENABLED else []
            return await client.room_create(is_direct=True, invite=[who], preset=nio.RoomPreset.trusted_private_chat, initial_state=state)

        def done(r):
            if isinstance(r, nio.RoomCreateResponse):
                self._open = r.room_id
                if ENCRYPTION_ENABLED:
                    self._secret_ids.add(r.room_id)
                self.said.emit(f"Asked {who} to chat. They'll see it next time they open Matrix.", False)
            else:
                self.said.emit("Couldn't start the chat: " + _why(r), True)
            self.changed.emit()
        self._run(go(), done)
        return ""

    @Slot(str, bool)
    def answerInvite(self, rid: str, yes: bool) -> None:
        if self._demo:
            self._invites.pop(rid, None)
            self.changed.emit()
            return
        client = self._client

        async def go():
            if yes:
                return await client.join(rid)
            await client.room_leave(rid)
            return await client.room_forget(rid)

        def done(r):
            if yes and isinstance(r, nio.JoinResponse):
                self._open = rid
            elif isinstance(r, Exception) or isinstance(r, nio.ErrorResponse):
                self.said.emit(_why(r), True)
            self.changed.emit()
        self._run(go(), done)

    @Slot(str)
    def leave(self, rid: str) -> None:
        if self._demo:
            self._rooms.pop(rid, None)
            self._open = ""
            self.changed.emit()
            return
        client = self._client

        async def go():
            await client.room_leave(rid)
            return await client.room_forget(rid)
        self._run(go(), lambda r: (setattr(self, "_open", "" if self._open == rid else self._open), self.changed.emit()))

    # ---- one window
    def listen(self, show: bool = True) -> bool:
        """Be the only Messages running: a second start brings this window up and leaves."""
        from PySide6.QtNetwork import QLocalServer, QLocalSocket
        name = f"huginn-messages-{os.getuid()}"
        probe = QLocalSocket()
        probe.connectToServer(name)
        if probe.waitForConnected(300):
            if show:
                probe.write(b"show")
                probe.waitForBytesWritten(1000)
            probe.disconnectFromServer()
            return False
        QLocalServer.removeServer(name)
        self._door = QLocalServer(self)
        self._door.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        self._door.listen(name)
        self._door.newConnection.connect(lambda: self._door.nextPendingConnection().readyRead.connect(self.shown.emit))
        return True

    def stop(self) -> None:
        if self._client and self._loop:
            client = self._client
            try:
                asyncio.run_coroutine_threadsafe(client.close(), self._loop).result(timeout=3)
            except Exception:
                pass
            self._loop.call_soon_threadsafe(self._loop.stop)


def _safe(fn):
    try:
        return fn()
    except Exception as err:
        return err


NOT_READY = "keys not ready"


def _why(r) -> str:
    if r == NOT_READY:
        return "this chat is encrypted and its keys aren't ready yet. Try again in a moment."
    if isinstance(r, Exception):
        return str(r) or r.__class__.__name__
    return getattr(r, "message", "") or getattr(r, "status_code", "") or "something went wrong"


def _size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return ""
