"""Huginn OS's password prompt: the polkit authentication agent for the session.

When an app asks the system for something only an administrator may do (install software, change the time, run a
command as root with pkexec), polkit asks the session's agent to check who's there. This is that agent: it
registers itself with polkit on the system bus, and for each request shows a small Huginn dialog (what's being
asked, and by which program, who can say yes, a password), then lets polkit's own helper check the password
(PolkitAgent.Session: the setuid helper or its socket, whichever this polkit has). Nothing here sees /etc/shadow,
and a password typed in goes only to the helper.

    python3 huginn_polkit.py                 the session's agent (started by huginn-session-apps)
    python3 huginn_polkit.py --process PID   answer only for one process (as pkttyagent does), for tests
"""
import argparse
import grp
import os
import pwd
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
for shell_dir in (HERE.parent / "shell", Path("/usr/share/huginn-shell")):
    if (shell_dir / "huginn_shell.py").exists():
        sys.path.insert(0, str(shell_dir))
        break

import gi  # noqa: E402

gi.require_version("Polkit", "1.0")
gi.require_version("PolkitAgent", "1.0")
from gi.repository import Gio, GLib, Polkit, PolkitAgent  # noqa: E402
from PySide6.QtCore import Property, QObject, QTimer, QUrl, Signal, Slot  # noqa: E402

AGENT_PATH = "/org/huginn/PolicyKit1/AuthenticationAgent"
AGENT_XML = """
<node>
  <interface name="org.freedesktop.PolicyKit1.AuthenticationAgent">
    <method name="BeginAuthentication">
      <arg type="s" name="action_id" direction="in"/>
      <arg type="s" name="message" direction="in"/>
      <arg type="s" name="icon_name" direction="in"/>
      <arg type="a{ss}" name="details" direction="in"/>
      <arg type="s" name="cookie" direction="in"/>
      <arg type="a(sa{sv})" name="identities" direction="in"/>
    </method>
    <method name="CancelAuthentication">
      <arg type="s" name="cookie" direction="in"/>
    </method>
  </interface>
</node>
"""
CANCELLED = "org.freedesktop.PolicyKit1.Error.Cancelled"



def qt_runs_glib() -> bool:
    """Ubuntu's Qt runs GLib's loop itself, and GLib's sources (D-Bus) are served with Qt's events. Turning GLib's
    loop by hand from a Qt timer as well would run Qt's events inside Qt's events: a window drawn in the middle of
    drawing another, which can leave a surface waiting forever for its compositor."""
    from PySide6.QtCore import QAbstractEventDispatcher
    d = QAbstractEventDispatcher.instance()
    return d is not None and "Glib" in d.metaObject().className()

def person(uid: int) -> dict:
    try:
        p = pwd.getpwuid(uid)
    except KeyError:
        return {"uid": uid, "name": str(uid), "realName": ""}
    return {"uid": uid, "name": p.pw_name, "realName": (p.pw_gecos or "").split(",")[0]}


def people_for(identities: list, me: int) -> list:
    """The people polkit will accept a password from: users named, and members of groups named (an administrator
    group, usually), you first when you're one of them. Root last: it rarely has a password on Huginn OS."""
    uids = []
    for kind, info in identities:
        if kind == "unix-user":
            uids.append(int(info.get("uid", -1)))
        elif kind == "unix-group":
            try:
                g = grp.getgrgid(int(info.get("gid", -1)))
            except KeyError:
                continue
            for member in g.gr_mem:
                try:
                    uids.append(pwd.getpwnam(member).pw_uid)
                except KeyError:
                    pass
            uids += [p.pw_uid for p in pwd.getpwall() if p.pw_gid == g.gr_gid]
    seen, out = set(), []
    for uid in sorted(uids, key=lambda u: (u != me, u == 0, u)):
        if uid >= 0 and uid not in seen:
            seen.add(uid)
            out.append(person(uid))
    return out


def asker(details: dict) -> str:
    """Which program is asking, by name: a Huginn app by its own name, anything else by its command."""
    for key in ("polkit.subject-pid", "polkit.caller-pid"):
        pid = details.get(key, "")
        if not pid.isdigit():
            continue
        try:
            argv = [a for a in Path(f"/proc/{pid}/cmdline").read_bytes().decode(errors="replace").split("\0") if a]
        except OSError:
            continue
        if not argv:
            continue
        for k, a in enumerate(argv):
            if a.endswith("huginn_app.py") and k + 1 < len(argv):
                return argv[k + 1].replace("-", " ").title()
            if a.endswith((".py", "huginn")) and "huginn" in a:
                return Path(a).stem.replace("huginn_", "").replace("_", " ").title() or "Huginn"
        return Path(argv[0]).name
    return ""


def plain_message(action_id: str, message: str, details: dict) -> tuple:
    """(what's asked, in plain words; the program or command asking, if known)."""
    import re
    command = details.get("command_line") or ""
    as_user = details.get("user") or "root"
    m = re.search(r"run [`'\"‘](.+?)['`\"’] as (?:the super ?user|user (\S+))", message or "")
    if action_id == "org.freedesktop.policykit.exec" and (command or m):
        command = command or m.group(1)
        as_user = (m.group(2) if m and m.group(2) else as_user)
        return (f"Run a command as {'the administrator' if as_user in ('root', '') else as_user}", command)
    who = asker(details)
    return (message or "An app wants to make a change that needs an administrator.", f"Asked by {who}" if who else "")


def process_start_time(pid: int) -> int:
    """A process's start time in clock ticks since boot, as polkit identifies processes by."""
    try:
        stat = Path(f"/proc/{pid}/stat").read_text()
        return int(stat[stat.rindex(")") + 2:].split()[19])
    except (OSError, ValueError, IndexError):
        return 0


class Agent(QObject):
    """One request at a time (polkit asks again once one is answered). The window shows `active`; QML calls
    authenticate(password), cancel() and choose(index)."""
    changed = Signal()
    failed = Signal(str)                  # couldn't register (another agent has the session, no polkit)

    def __init__(self, process: int = 0):
        super().__init__()
        self._process = process
        self._bus = None
        self._reg = 0
        self._inv = None                  # the BeginAuthentication call waiting for its answer
        self._cookie = ""
        self._people = []
        self._chosen = 0
        self._session = None
        self._asking = ""                 # what the helper asked for ("Password:"), "" while it's busy
        self._echo = False
        self._error = ""
        self._info = ""
        self._busy = False
        self._title = ""
        self._detail = ""
        self._action = ""
        self._details = {}
        self._tries = 0
        self.registered = False

    # ---------------------------------------------------------------- registering with polkit
    def start(self) -> bool:
        try:
            self._bus = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
            node = Gio.DBusNodeInfo.new_for_xml(AGENT_XML)
            self._reg = self._bus.register_object(AGENT_PATH, node.interfaces[0], self._on_call, None, None)
            if self._process:
                subject = ("unix-process", {"pid": GLib.Variant("u", self._process),
                                            "start-time": GLib.Variant("t", process_start_time(self._process))})
            else:
                subject = ("unix-session", {"session-id": GLib.Variant("s", self._session_id())})
            locale = os.environ.get("LC_MESSAGES") or os.environ.get("LANG") or "C"
            self._bus.call_sync("org.freedesktop.PolicyKit1", "/org/freedesktop/PolicyKit1/Authority", "org.freedesktop.PolicyKit1.Authority",
                                "RegisterAuthenticationAgent", GLib.Variant("((sa{sv})ss)", (subject, locale, AGENT_PATH)),
                                None, Gio.DBusCallFlags.NONE, -1, None)
        except GLib.Error as err:
            self.failed.emit(err.message)
            return False
        self.registered = True
        return True

    def _session_id(self) -> str:
        sid = os.environ.get("XDG_SESSION_ID", "")
        if sid:
            return sid
        try:                                                   # ask logind which session this process is in
            r = self._bus.call_sync("org.freedesktop.login1", "/org/freedesktop/login1", "org.freedesktop.login1.Manager", "GetSessionByPID",
                                    GLib.Variant("(u)", (os.getpid(),)), GLib.VariantType("(o)"), Gio.DBusCallFlags.NONE, -1, None)
            path = r.unpack()[0]
            r = self._bus.call_sync("org.freedesktop.login1", path, "org.freedesktop.DBus.Properties", "Get",
                                    GLib.Variant("(ss)", ("org.freedesktop.login1.Session", "Id")), GLib.VariantType("(v)"), Gio.DBusCallFlags.NONE, -1, None)
            return r.unpack()[0]
        except GLib.Error:
            return ""

    def _on_call(self, conn, sender, path, iface, method, params, invocation):
        if method == "BeginAuthentication":
            action_id, message, icon_name, details, cookie, identities = params.unpack()
            if self._inv is not None:                          # one at a time: polkit asks again later
                invocation.return_dbus_error(CANCELLED, "Another request is being answered")
                return
            self._begin(invocation, action_id, message, icon_name, dict(details), cookie, identities)
        elif method == "CancelAuthentication":
            cookie = params.unpack()[0]
            invocation.return_value(None)
            if cookie == self._cookie:
                self._finish(False, "cancelled")

    # ---------------------------------------------------------------- one request
    def _begin(self, invocation, action_id, message, icon_name, details, cookie, identities) -> None:
        self._inv, self._cookie, self._action, self._details = invocation, cookie, action_id, details
        self._people = people_for(identities, os.getuid())
        self._chosen = 0
        self._error = self._info = ""
        self._tries = 0
        self._title, self._detail = plain_message(action_id, message, details)
        if not self._people:
            self._finish(False, "nobody to ask")
            return
        self._new_session()
        self.changed.emit()

    def _new_session(self) -> None:
        if self._session is not None:
            try:
                self._session.cancel()
            except GLib.Error:
                pass
        who = self._people[self._chosen]
        self._session = PolkitAgent.Session.new(Polkit.UnixUser.new(who["uid"]), self._cookie)
        self._session.connect("request", self._on_request)
        self._session.connect("show-error", lambda _s, text: self._say(text, True))
        self._session.connect("show-info", lambda _s, text: self._say(text, False))
        self._session.connect("completed", self._on_completed)
        self._asking, self._busy = "", True
        self._session.initiate()

    def _on_request(self, _session, request: str, echo_on: bool) -> None:
        self._asking, self._echo, self._busy = request or "Password:", bool(echo_on), False
        self.changed.emit()

    def _say(self, text: str, bad: bool) -> None:
        if bad:
            self._error = text
        else:
            self._info = text
        self.changed.emit()

    def _on_completed(self, _session, gained: bool) -> None:
        if gained:
            self._finish(True)
            return
        if self._inv is None:
            return
        self._tries += 1
        self._error = "That password didn't work. Try again."
        self._new_session()                                    # a session answers once: start another for the next try
        self.changed.emit()

    def _finish(self, ok: bool, why: str = "") -> None:
        inv, self._inv = self._inv, None
        if self._session is not None:
            if not ok:
                try:
                    self._session.cancel()
                except GLib.Error:
                    pass
            self._session = None
        if inv is not None:
            if ok:
                inv.return_value(None)
            else:
                inv.return_dbus_error(CANCELLED, why or "cancelled")
        self._cookie, self._asking, self._busy = "", "", False
        self.changed.emit()

    # ---------------------------------------------------------------- what the window uses
    active = Property(bool, lambda self: self._inv is not None, notify=changed)
    title = Property(str, lambda self: self._title, notify=changed)
    detail = Property(str, lambda self: self._detail, notify=changed)
    actionId = Property(str, lambda self: self._action, notify=changed)
    people = Property("QVariantList", lambda self: self._people, notify=changed)
    chosen = Property(int, lambda self: self._chosen, notify=changed)
    prompt = Property(str, lambda self: self._asking.rstrip(": ") if self._asking else "", notify=changed)
    echo = Property(bool, lambda self: self._echo, notify=changed)
    ready = Property(bool, lambda self: bool(self._asking) and not self._busy, notify=changed)
    busy = Property(bool, lambda self: self._busy, notify=changed)
    error = Property(str, lambda self: self._error, notify=changed)
    info = Property(str, lambda self: self._info, notify=changed)
    tries = Property(int, lambda self: self._tries, notify=changed)

    @Slot(str)
    def authenticate(self, password: str) -> None:
        if self._session is None or not self._asking:
            return
        self._asking, self._busy, self._error = "", True, ""
        self.changed.emit()
        self._session.response(password)

    @Slot()
    def cancel(self) -> None:
        if self._inv is not None:
            self._finish(False, "The person cancelled")

    @Slot(int)
    def choose(self, index: int) -> None:
        if 0 <= index < len(self._people) and index != self._chosen and self._inv is not None:
            self._chosen = index
            self._error = ""
            self._new_session()
            self.changed.emit()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--process", type=int, default=0, help="answer for this process only (tests)")
    ap.add_argument("--dark", action="store_true")
    args = ap.parse_args()
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtQml import QQmlApplicationEngine
    from huginn_shell import make_theme
    app = QGuiApplication(sys.argv[:1])
    app.setApplicationName("Authenticate")
    app.setDesktopFileName("huginn-authenticate")
    app.setQuitOnLastWindowClosed(False)                       # the window comes and goes; the agent stays
    tokens, settings, theme = make_theme(args.dark, False, "", persist=False, app="authenticate")
    agent = Agent(args.process)
    if not agent.start():
        print("huginn-polkit: couldn't register with polkit (another agent may have this session)", file=sys.stderr)
        return 1
    if QGuiApplication.instance().eventDispatcher().metaObject().className().find("Glib") < 0:
        pump = QTimer(interval=15)                              # Qt without GLib's loop: turn it by hand
        pump.timeout.connect(lambda: GLib.MainContext.default().iteration(False))
        if not qt_runs_glib():
            pump.start()
    engine = QQmlApplicationEngine()
    ctx = engine.rootContext()
    for name, obj in (("Theme", theme), ("Settings", settings), ("Agent", agent)):
        ctx.setContextProperty(name, obj)
    engine.load(QUrl.fromLocalFile(str(HERE / "qml" / "Authenticate.qml")))
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
