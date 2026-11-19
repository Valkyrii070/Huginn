"""Recently used files, in the desktop's shared list (~/.local/share/recently-used.xbel, the freedesktop one GTK and
KDE apps also write), so the start menu's app islands and Search everything can offer "pick up where you left off".

    note(path, app, command)     Huginn's apps call this when they open or save a file
    for_app(names, mimes, n)     an app's recent files: from the list, then the newest files of its kinds nearby
    latest(n)                    the newest files of all, for Search everything
"""
import mimetypes
import os
import time
from pathlib import Path

try:
    from gi.repository import GLib
except ImportError:                                        # (other systems: the list is simply empty)
    GLib = None

XBEL = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share") / "recently-used.xbel"
NEARBY = ("Documents", "Desktop", "Downloads", "Pictures", "Music", "Videos")


def _load():
    if GLib is None:
        return None
    book = GLib.BookmarkFile()
    try:
        book.load_from_file(str(XBEL))
    except GLib.Error:
        pass
    return book


def note(path: str, app: str, command: str) -> None:
    """Add (or bring forward) a file in the shared list, opened by `app` (its desktop id, e.g. huginn-writer)."""
    if GLib is None or not path or not os.path.isfile(path):
        return
    uri = Path(path).resolve().as_uri()
    book = _load()
    try:
        book.set_mime_type(uri, mimetypes.guess_type(path)[0] or "application/octet-stream")
        book.add_application(uri, app, command)
        book.set_visited_date_time(uri, GLib.DateTime.new_now_local())
        XBEL.parent.mkdir(parents=True, exist_ok=True)
        book.to_file(str(XBEL))
    except (GLib.Error, OSError, TypeError):
        pass


def ago(stamp: float) -> str:
    gap = max(0, time.time() - stamp)
    if gap < 60:
        return "just now"
    if gap < 3600:
        return f"{int(gap // 60)} min ago"
    if gap < 86400:
        return f"{int(gap // 3600)} h ago"
    if gap < 2 * 86400:
        return "yesterday"
    if gap < 7 * 86400:
        return f"{int(gap // 86400)} days ago"
    return time.strftime("%b %-d", time.localtime(stamp))


def _row(path: str, stamp: float) -> dict:
    p = Path(path)
    home = str(Path.home())
    where = str(p.parent).replace(home, "Home", 1).replace("/", " › ")
    return {"name": p.name, "path": str(p), "where": where, "when": ago(stamp), "stamp": stamp,
            "mime": mimetypes.guess_type(str(p))[0] or ""}


def _entries():
    """[(path, stamp, [app names])] from the shared list, newest first; files that are gone are skipped."""
    book = _load()
    out = []
    if book is None:
        return out
    for uri in book.get_uris():
        if not uri.startswith("file://"):
            continue
        try:
            path = GLib.filename_from_uri(uri)[0]
        except GLib.Error:
            continue
        if not os.path.isfile(path):
            continue
        try:
            stamp = book.get_modified_date_time(uri).to_unix()
            apps = list(book.get_applications(uri))
        except (GLib.Error, AttributeError, TypeError):
            stamp, apps = os.path.getmtime(path), []
        out.append((path, stamp, apps))
    return sorted(out, key=lambda e: -e[1])


def _exts(mimes: list) -> tuple:
    exts = set()
    for m in mimes or []:
        exts.update(mimetypes.guess_all_extensions(m))
    return tuple(sorted(exts))


def for_app(names: list, mimes: list, limit: int = 4) -> list:
    """An app's recent files: those the shared list says it opened (by any of `names`), then the newest files of
    the kinds it opens in Documents, Desktop and Downloads."""
    wanted = {n.lower() for n in names if n}
    rows, seen = [], set()
    for path, stamp, apps in _entries():
        if wanted & {a.lower() for a in apps}:
            rows.append(_row(path, stamp))
            seen.add(path)
        if len(rows) >= limit:
            return rows
    exts = _exts(mimes)
    if not exts:
        return rows
    found = []
    for folder in ("Documents", "Desktop", "Downloads"):
        base = Path.home() / folder
        try:
            for entry in os.scandir(base):
                if entry.is_file() and entry.name.lower().endswith(exts) and not entry.name.startswith(".") and entry.path not in seen:
                    found.append((entry.path, entry.stat().st_mtime))
        except OSError:
            continue
    for path, stamp in sorted(found, key=lambda f: -f[1])[:max(0, limit - len(rows))]:
        rows.append(_row(path, stamp))
    return rows


def latest(limit: int = 3) -> list:
    rows = [_row(p, s) for p, s, _ in _entries()[:limit]]
    if len(rows) < limit:                                  # a new account: the newest files nearby
        have = {r["path"] for r in rows}
        found = []
        for folder in ("Documents", "Desktop"):
            try:
                found += [(e.path, e.stat().st_mtime) for e in os.scandir(Path.home() / folder)
                          if e.is_file() and not e.name.startswith(".") and e.path not in have]
            except OSError:
                pass
        rows += [_row(p, s) for p, s in sorted(found, key=lambda f: -f[1])[:limit - len(rows)]]
    return rows
