"""Huginn engine builder (the browser was first called SafariQt).

Rebuilds Qt WebEngine (the Chromium-based engine the browser runs on) with H.264 video and
AAC audio switched on, then swaps it into this folder's portable Python. Run it through
build-engine.bat (or restore-engine.bat to put the standard engine back).

  * Every step records when it is finished, so running it again after an error, a reboot or
    a shutdown carries on where it stopped.
  * Running it again later also updates the engine when a newer patch release is out.
  * Before the new engine is put in, it is checked against the browser's own Qt files; after,
    a video check and the browser's test suites run, and the original engine is put back
    automatically if the video check fails.

Progress: engine\\status.txt and engine\\build-log.txt. Compiler output: <work folder>\\logs.
"""
import argparse
import collections
import ctypes
import hashlib
import html
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ElementTree
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
APP = HERE.parent
PYDIR = APP / "python"
PYEXE = PYDIR / "python.exe"
PYSIDE = PYDIR / "Lib" / "site-packages" / "PySide6"
STATUS_FILE = HERE / "status.txt"
STATUS_JSON = HERE / "status.json"          # the same, for the browser's Video formats panel
LOCK_FILE = HERE / "builder.pid"            # one builder at a time
UPDATE_FILE = HERE / "update-check.json"    # written by --check-only
RESTART_FILE = HERE / "restart.json"        # the browser closed itself for the swap: reopen it after
BROWSER_SCRIPT = APP / "safari_browser.py"
PYWEXE = PYDIR / "pythonw.exe"
STATE_FILE = HERE / "state.json"
INSTALLED_FILE = HERE / "installed.json"
BACKUP_DIR = HERE / "standard-engine"
ERROR_FILE = HERE / "last-error.txt"
LOG_FILE = HERE / "build-log.txt"
GNU_ZIP = HERE / "gnu_tools.zip"
CODEC_CHECK = HERE / "codec_check.py"

IS_WINDOWS = os.name == "nt"
WORK_DIRNAME = "sqtb"                  # short on purpose: Chromium's paths are very deep
MIN_FREE_GB = 60                       # source ~5 GB + build ~25 GB + tools, with headroom
VS_FREE_GB = 10                        # Build Tools land on the system drive
QT_SITE = "https://download.qt.io/"
SOURCE_ROOTS = ("official_releases/qtwebengine/", "official_releases/additional_libraries/qtwebengine/",
                "archive/qtwebengine/", "archive/additional_libraries/qtwebengine/")
QT_REPO = QT_SITE + "online/qtsdkrepository/windows_x86/desktop/"
# Since Qt 6.12, Qt WebEngine is released on its own; when no source tarball is published for a
# release, its git tag is used instead (GitHub mirror first, Qt's own server second).
QT_GIT_REPOS = ("https://github.com/qt/qtwebengine.git", "https://code.qt.io/qt/qtwebengine.git")
MINGIT_RELEASE = "https://api.github.com/repos/git-for-windows/git/releases/latest"
GIT_CONFIG = ("-c", "core.longpaths=true", "-c", "core.autocrlf=false", "-c", "core.symlinks=false",
              "-c", "advice.detachedHead=false", "-c", "credential.helper=")
VS_BOOTSTRAPPER = "https://aka.ms/vs/17/release/vs_BuildTools.exe"
VS_COMPONENTS = ("Microsoft.VisualStudio.Workload.VCTools",
                 "Microsoft.VisualStudio.Component.VC.Tools.x86.x64",
                 "Microsoft.VisualStudio.Component.VC.ATL",
                 "Microsoft.VisualStudio.Component.Windows11SDK.26100")
MIN_SDK_BUILD = 26100                  # Qt WebEngine 6.140 needs Windows 11 SDK 10.0.26100+
BUILD_PYTHON = "3.12.10"
NUGET_PYTHON = "https://www.nuget.org/api/v2/package/python/" + BUILD_PYTHON
NODE_DIST = "https://nodejs.org/dist/"
PIP_PACKAGES = ("html5lib", "cmake>=3.27,<5", "ninja", "py7zr", "zstandard")
# gperf, bison and flex for Windows, from conda-forge (pinned by checksum). Downloaded on each
# PC rather than shipped with the browser.
CONDA_FORGE = "https://conda.anaconda.org/conda-forge/win-64/"
GNU_PACKAGES = (
    ("gperf-3.3-hac47afa_2.conda", "9e089ee0f5054f51f5be1ca5ed50066932ec5dade879648ebf0c6b4afc00d00c",
     {"Library/bin/gperf.exe": ["gperf.exe"]}),
    ("winflexbison-2.5.25-h7cafa3a_0.conda", "eb9a7097dbea7bdf472a26c099e69c0b594e6cae09f8dea780e4b8e9f7212698",
     {"Library/bin/win_bison.exe": ["win_bison.exe", "bison.exe"],
      "Library/bin/win_flex.exe": ["win_flex.exe", "flex.exe"], "Library/bin/data/": ["data/"]}),
)
# Parts of Qt WebEngine the browser never uses: skipping them saves disk space and time.
SKIPPED_FEATURES = ("-DFEATURE_webenginedriver=OFF", "-DFEATURE_qtwebengine_quick_build=OFF")
QT_MODULES = ("qtwebchannel", "qtpositioning")
ENGINE_BINARIES = ("Qt6WebEngineCore.dll", "Qt6WebEngineWidgets.dll", "Qt6WebEngineQuick.dll",
                   "Qt6WebEngineQuickDelegatesQml.dll", "QtWebEngineProcess.exe")
STEPS = ("vs", "tools", "qt", "source", "configure", "build", "install", "verify", "cleanup")
STEP_TITLES = {"vs": "Microsoft C++ Build Tools", "tools": "Build tools (Python, Node.js, CMake, Ninja)",
               "qt": "Qt development files", "source": "Engine source code",
               "configure": "Configuring the build", "build": "Compiling the engine",
               "install": "Putting the new engine in", "verify": "Checking the new engine",
               "cleanup": "Cleaning up"}
USER_AGENT = "SafariQt-engine-builder/1.0"
IDLE_PRIORITY_CLASS = 0x00000040
BELOW_NORMAL_PRIORITY_CLASS = 0x00004000


# ----------------------------------------------------------------------------- output

class BuildError(Exception):
    """A step failed; message is for the user, details go to last-error.txt."""

    def __init__(self, message, details=""):
        super().__init__(message)
        self.details = details


_log_handle = None


def log(message="", console=True):
    global _log_handle
    if console:
        print(message, flush=True)
    try:
        if _log_handle is None:
            _log_handle = open(LOG_FILE, "a", encoding="utf-8")
        _log_handle.write(time.strftime("%Y-%m-%d %H:%M:%S  ") + message + "\n")
        _log_handle.flush()
    except OSError:
        pass


def write_atomic(path, text):
    path = Path(path)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


STATUS_CONTEXT = {}                          # current step: key, number, title (set by Builder.heading)
DISK = {"path": None, "baseline": None, "lowest": None}


def note_disk():
    """Tracks the lowest free space seen on the work drive: baseline - lowest = real peak use."""
    if DISK["path"] is None:
        return
    try:
        free = shutil.disk_usage(DISK["path"]).free
    except OSError:
        return
    DISK["lowest"] = free if DISK["lowest"] is None else min(DISK["lowest"], free)


def set_status(state, step, detail="", **extra):
    """state: RUNNING / WAITING / DONE / FAILED. status.txt is for people (and Claude);
    status.json carries the same for the browser: step key/number, progress 0-1, eta in
    seconds, what it is waiting for, the error, and this process id."""
    lines = [state, f"step: {step}"]
    if detail:
        lines.append(detail)
    lines.append("updated: " + time.strftime("%Y-%m-%d %H:%M:%S"))
    note_disk()
    data = {"state": state.lower(), "title": step, "detail": detail, "steps": len(STEPS),
            "pid": os.getpid(), "updated": time.time(), **STATUS_CONTEXT, **extra}
    try:
        write_atomic(STATUS_FILE, "\n".join(lines) + "\n")
        write_atomic(STATUS_JSON, json.dumps(data))
    except OSError:
        pass


def fmt_size(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit in ("B", "KB") else f"{n:.1f} {unit}"
        n /= 1024


def fmt_duration(seconds):
    seconds = int(max(0, seconds))
    h, m = seconds // 3600, (seconds % 3600) // 60
    return f"{h} h {m:02d} min" if h else f"{m} min"


# ----------------------------------------------------------------------------- state

def load_json(path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def save_state(state):
    write_atomic(STATE_FILE, json.dumps(state, indent=2))


def version_tuple(text):
    return tuple(int(x) for x in re.findall(r"\d+", str(text)))


RELEASE_CONFIG = "RelWithDebInfo"            # what Qt's Windows packages ship as their release build


def release_config(build_dir):
    """The configuration the browser uses. Qt's Windows packages are built for RelWithDebInfo
    and Debug, and a module configured against them builds both - the Debug copy of
    Chromium doubles the compile time and the disk space, and the browser never uses it."""
    build_dir = Path(build_dir)
    for config in ("RelWithDebInfo", "Release", "MinSizeRel"):
        if (build_dir / f"build-{config}.ninja").exists():
            return config
    return None                                   # a single-configuration build


ENGINE_DATA = ("qtwebengine_resources.pak", "qtwebengine_resources_100p.pak", "qtwebengine_resources_200p.pak",
               "qtwebengine_devtools_resources.pak", "icudtl.dat", "v8_context_snapshot.bin")


def cache_value(build_dir, name):
    try:
        text = (Path(build_dir) / "CMakeCache.txt").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    m = re.search(rf"^{re.escape(name)}:[A-Z]+=(.*)$", text, re.M)
    return m.group(1).strip() if m else None


def engine_output_dirs(build_dir, config):
    """src/core/<config>/<arch> folders where Chromium's build put the engine and its data."""
    root = Path(build_dir) / "src" / "core" / config
    return [d for d in sorted(root.iterdir()) if d.is_dir()] if root.is_dir() else []


def alias_install_config(build_dir, log_fn=None):
    """Qt WebEngine takes its data files (Unicode data, language packs) from
    src/core/<CMAKE_BUILD_TYPE>/<arch>. A build configured with a build type that isn't one of
    its configurations (Release, while Qt's Windows packages build RelWithDebInfo) looks in a
    folder that doesn't exist; this copies the files there."""
    build_dir = Path(build_dir)
    wanted, config = cache_value(build_dir, "CMAKE_BUILD_TYPE"), release_config(build_dir)
    if not wanted or not config or wanted == config or (build_dir / f"build-{wanted}.ninja").exists():
        return 0
    copied = 0
    for out in engine_output_dirs(build_dir, config):
        alias = build_dir / "src" / "core" / wanted / out.name
        files = [out / "icudtl.dat"] + sorted((out / "qtwebengine_locales").glob("*.pak"))
        for src in files:
            if not src.is_file():
                continue
            dst = alias / src.relative_to(out)
            if not dst.exists() or dst.stat().st_size != src.stat().st_size:
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
                copied += 1
    if copied and log_fn:
        log_fn(f"  pointed Qt's '{wanted}' data folder at the {config} build ({copied} files)")
    return copied


def complete_install(inst, build_dir, config):
    """The engine's data files are installed only for Qt's install configuration; make sure
    the release build's own copies are in the install folder (never Debug '.debug' ones)."""
    inst = Path(inst)
    added = []
    for out in engine_output_dirs(build_dir, config):
        for name in ENGINE_DATA:
            src, dst = out / name, inst / "resources" / name
            if src.is_file() and not dst.exists():
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
                added.append(dst)
        for src in sorted((out / "qtwebengine_locales").glob("*.pak")):
            dst = inst / "translations" / "qtwebengine_locales" / src.name
            if not dst.exists():
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
                added.append(dst)
        break                                             # one architecture
    return added


def reset_for_target(state, target, qt_version):
    """A new engine version (or Qt version) invalidates the source/build steps, but tools
    and Visual Studio stay valid."""
    keep = {"vs", "tools"}
    if state.get("qt") == qt_version:
        keep.add("qt")
    if state.get("target") != target or state.get("qt") != qt_version:
        state["done"] = [s for s in state.get("done", []) if s in keep]
    state["target"], state["qt"] = target, qt_version
    return state


# ----------------------------------------------------------------------------- network

def _request(url, headers=None):
    return urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **(headers or {})})


def fetch_text(url, timeout=60):
    with urllib.request.urlopen(_request(url), timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def file_sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def file_digest(path, algorithm):
    h = hashlib.new(algorithm)
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def file_md5(path):
    return file_digest(path, "md5")


def download(url, dest, sha256=None, label=None, attempts=5):
    """Downloads with resume and retries. Returns the final URL after redirects."""
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and (sha256 is None or file_sha256(dest) == sha256.lower()):
        return url
    part = dest.with_name(dest.name + ".part")
    label = label or dest.name
    last_error = None
    for attempt in range(1, attempts + 1):
        try:
            have = part.stat().st_size if part.exists() else 0
            headers = {"Range": f"bytes={have}-"} if have else {}
            try:
                response = urllib.request.urlopen(_request(url, headers), timeout=60)
            except urllib.error.HTTPError as e:
                if e.code == 416 and have:              # .part was already complete
                    response = None
                else:
                    raise
            final_url = url
            if response is not None:
                with response:
                    final_url = response.geturl()
                    if have and response.status != 206:
                        have = 0                          # server ignored the range: restart
                    length = int(response.headers.get("Content-Length") or 0)
                    total = length + have if length else 0
                    done, shown = have, 0.0
                    with open(part, "ab" if have else "wb") as f:
                        while True:
                            chunk = response.read(1 << 20)
                            if not chunk:
                                break
                            f.write(chunk)
                            done += len(chunk)
                            if time.time() - shown > 10:
                                shown = time.time()
                                pct = f" ({done * 100 // total}%)" if total else ""
                                print(f"    {label}: {fmt_size(done)}{pct}", flush=True)
                    if total and done < total:
                        raise OSError(f"download stopped at {fmt_size(done)} of {fmt_size(total)}")
            if sha256 and file_sha256(part) != sha256.lower():
                part.unlink()
                raise OSError("downloaded file did not match its checksum")
            os.replace(part, dest)
            return final_url
        except (urllib.error.URLError, OSError, TimeoutError, ConnectionError) as e:
            last_error = e
            log(f"    download problem ({e}); trying again ({attempt}/{attempts})")
            time.sleep(min(60, 5 * attempt))
    raise BuildError(f"Could not download {label}", f"{url}\n{last_error}")


def list_dir(url):
    """Child entries ('name/' for folders) of a download.qt.io directory listing."""
    if not url.endswith("/"):
        url += "/"
    page = fetch_text(url)
    children = set()
    for href in re.findall(r'href\s*=\s*"([^"]+)"', page, re.I):
        full = urllib.parse.urljoin(url, html.unescape(href))
        if not full.startswith(url) or full == url:
            continue
        rest = urllib.parse.unquote(full[len(url):])
        if "?" in rest or "#" in rest or rest.count("/") > 1 or (rest.count("/") == 1 and not rest.endswith("/")):
            continue
        children.add(rest)
    return sorted(children)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def url_exists(url, trace=None):
    """True/False from download.qt.io itself (it answers with a redirect to a mirror when the
    file exists and 404 when it doesn't). Network problems raise."""
    opener = urllib.request.build_opener(_NoRedirect)
    request = urllib.request.Request(url, method="HEAD", headers={"User-Agent": USER_AGENT})
    try:
        with opener.open(request, timeout=30) as r:
            status = r.status
    except urllib.error.HTTPError as e:
        status = e.code
    if trace is not None:
        trace.append(f"HEAD {url} -> {status}")
    if status in (404, 410):
        return False
    if status < 400:
        return True
    raise urllib.error.URLError(f"HTTP {status} for {url}")


def probe_sources(minor, current_patch, site=QT_SITE, trace=None):
    """Since Qt 6.12, Qt WebEngine releases live at official_releases/qtwebengine/<version>/.
    Patch numbers are consecutive, so walk up until a few are missing."""
    found, misses, patch = {}, 0, 0
    while misses < 3 and patch < 60:
        version = f"6.{minor}.{patch}"
        url = f"{site}official_releases/qtwebengine/{version}/qtwebengine-everywhere-src-{version}.tar.xz"
        if url_exists(url, trace):
            found[patch] = {"tar.xz": url}
            misses = 0
        elif patch >= current_patch:
            misses += 1
        patch += 1
    return found


def git_remote_refs(repo):
    """{ref: sha} advertised by a git server over smart HTTP (no git needed)."""
    request = urllib.request.Request(repo + "/info/refs?service=git-upload-pack",
                                     headers={"User-Agent": "git/2.47 " + USER_AGENT})
    with urllib.request.urlopen(request, timeout=60) as r:
        data = r.read()
    refs, i = {}, 0
    while i + 4 <= len(data):
        try:
            size = int(data[i:i + 4], 16)
        except ValueError:
            break
        if size == 0:                                     # flush packet
            i += 4
            continue
        line = data[i + 4:i + size].split(b"\0")[0].strip().decode("utf-8", "replace")
        i += size
        sha, _, ref = line.partition(" ")
        if re.fullmatch(r"[0-9a-f]{40}", sha) and ref:
            refs[ref] = sha
    return refs


def git_release_tags(minor, repos=QT_GIT_REPOS, trace=None):
    """{patch: (repo, ref, kind, commit)} for 6.<minor>.<patch> releases in Qt's git: a release tag
    (v6.140.0) when Qt has tagged it, otherwise the frozen release branch (6.140.0) that the
    release is built from. RC/beta tags and the moving 6.<minor> branch are never used."""
    pattern = re.compile(rf"refs/(tags/v|heads/)6\.{minor}(?:\.(\d+))?(-[\w.]+)?(\^\{{\}})?")
    for repo in repos:
        try:
            refs = git_remote_refs(repo)
        except (urllib.error.URLError, OSError, TimeoutError) as e:
            if trace is not None:
                trace.append(f"git refs {repo} -> {e}")
            continue
        found, related = {}, []
        for ref in refs:
            m = pattern.fullmatch(ref)
            if not m or m.group(4):
                continue
            related.append(ref)
            if m.group(3) or m.group(2) is None:
                continue
            patch, kind = int(m.group(2)), "tag" if m.group(1) == "tags/v" else "branch"
            name = ref.split("/", 2)[2]
            commit = refs.get(ref + "^{}", refs[ref])             # annotated tag -> its commit
            if patch not in found or (kind == "tag" and found[patch][2] == "branch"):
                found[patch] = (repo, name, kind, commit)
        if trace is not None:
            trace.append(f"git refs {repo} -> {len(refs)} refs; 6.{minor} refs: {sorted(related)[:20]}")
        if found:
            return found
    return {}


def parse_chromium_version(text):
    """(based on, security patches up to) from Qt WebEngine's CHROMIUM_VERSION file."""
    based = re.search(r"Based on Chromium version:\s*([\d.]+)", text or "")
    patched = re.search(r"security patches up to Chromium version:\s*([\d.]+)", text or "")
    return (based.group(1) if based else None), (patched.group(1) if patched else None)


def remote_chromium_version(repo, commit):
    """CHROMIUM_VERSION at a commit, read straight from GitHub or Qt's git web view."""
    urls = []
    m = re.match(r"https://github\.com/([^/]+/[^/.]+)", repo)
    if m:
        urls.append(f"https://raw.githubusercontent.com/{m.group(1)}/{commit}/CHROMIUM_VERSION")
    urls.append(f"https://code.qt.io/cgit/qt/qtwebengine.git/plain/CHROMIUM_VERSION?id={commit}")
    for url in urls:
        try:
            based, patched = parse_chromium_version(fetch_text(url, timeout=30))
            if patched or based:
                return based, patched
        except (urllib.error.URLError, OSError, TimeoutError):
            continue
    return None, None


def is_up_to_date(ours, installed, target, source, available_security, current_security):
    """Whether the engine this builder put in needs rebuilding: a newer release, or (for a
    release branch, which keeps receiving fixes) newer Chromium security patches."""
    if not ours:
        return False
    if version_tuple(installed.get("webengine", "0")) < version_tuple(target):
        return False
    if source.get("kind") != "git":
        return True
    if available_security and current_security:
        return version_tuple(available_security) <= version_tuple(current_security)
    return installed.get("source", {}).get("commit") == source.get("commit")


def find_sources(minor, roots=SOURCE_ROOTS, site=QT_SITE, trace=None):
    """{patch: {"tar.xz": url, "zip": url}} for qtwebengine-everywhere-src-6.<minor>.<patch>."""
    found = {}
    folder = re.compile(rf"6\.{minor}(\.\d+)?")
    archive = re.compile(rf"qtwebengine-everywhere-src-6\.{minor}\.(\d+)\.(tar\.xz|zip)")

    def crawl(url, depth):
        try:
            entries = list_dir(url)
        except (urllib.error.URLError, OSError, TimeoutError) as e:
            if trace is not None:
                trace.append(f"GET {url} -> {e}")
            return
        if trace is not None:
            trace.append(f"GET {url} -> {len(entries)} entries: {entries[:12]}")
        for entry in entries:
            if entry.endswith("/"):
                name = entry[:-1]
                if depth < 3 and (folder.fullmatch(name) or name in ("src", "submodules", "single")):
                    crawl(url + entry, depth + 1)
            else:
                m = archive.fullmatch(entry)
                if m:
                    found.setdefault(int(m.group(1)), {}).setdefault(m.group(2), url + entry)

    for root in roots:
        crawl(site + root, 0)
    return found


def expected_checksum(url):
    """('sha256'|'md5', hex) published next to a download.qt.io file, or None."""
    name = url.rsplit("/", 1)[1]
    for suffix, kind in ((".sha256", "sha256"), (".md5", "md5")):
        try:
            text = fetch_text(url + suffix, timeout=30)
            m = re.search(r"\b([0-9a-fA-F]{64}|[0-9a-fA-F]{32})\b", text)
            if m and len(m.group(1)) == (64 if kind == "sha256" else 32):
                return kind, m.group(1).lower()
        except (urllib.error.URLError, OSError, TimeoutError):
            pass
    try:
        text = fetch_text(url.rsplit("/", 1)[0] + "/md5sums.txt", timeout=30)
        for line in text.splitlines():
            parts = line.split()
            if len(parts) >= 2 and parts[-1].lstrip("*").endswith(name):
                return "md5", parts[0].lower()
    except (urllib.error.URLError, OSError, TimeoutError):
        pass
    return None


# ----------------------------------------------------------------------------- Qt packages

def qt_package_index(qt_version, repo=QT_REPO, trace=None):
    """Packages from Qt's online repository for one Qt version: {name: {version, archives,
    dependencies, base}}. Handles both layouts (qt6_6101/qt6_6101/Updates.xml before 6.11,
    qt6_6110/Updates.xml after)."""
    folder = "qt6_" + "".join(str(x) for x in version_tuple(qt_version))
    root = f"{repo}{folder}/"
    candidates = [root, f"{root}{folder}/"]
    try:
        candidates += [root + d for d in list_dir(root) if d.endswith("/") and d not in (folder + "/",)
                       and "src_doc_examples" not in d and "debug" not in d]
    except (urllib.error.URLError, OSError, TimeoutError) as e:
        if trace is not None:
            trace.append(f"GET {root} -> {e}")
    packages = {}
    for base in candidates:
        try:
            xml_text = fetch_text(base + "Updates.xml")
        except (urllib.error.URLError, OSError, TimeoutError) as e:
            if trace is not None:
                trace.append(f"GET {base}Updates.xml -> {e}")
            continue
        found = 0
        for update in ElementTree.fromstring(xml_text).iter("PackageUpdate"):
            name = (update.findtext("Name") or "").strip()
            if not name or name in packages:
                continue
            split = lambda tag: [x.strip() for x in (update.findtext(tag) or "").split(",") if x.strip()]  # noqa: E731
            packages[name] = {"version": (update.findtext("Version") or "").strip(), "base": base,
                              "archives": split("DownloadableArchives"), "dependencies": split("Dependencies")}
            found += 1
        if trace is not None:
            trace.append(f"GET {base}Updates.xml -> {found} packages")
    return packages


def qt_packages_for(packages, qt_version, modules):
    """(arch, [(package, archive url)]) for the MSVC x64 desktop Qt plus the given add-ons,
    following each package's dependencies within the same Qt version and architecture."""
    tag = "".join(str(x) for x in version_tuple(qt_version))
    arches = sorted({m.group(1) for name in packages
                     for m in [re.fullmatch(rf"qt\.qt6\.{tag}\.(win64_msvc\d{{4}}_64)", name)] if m})
    if not arches:
        raise BuildError(f"Qt {qt_version} for MSVC isn't in Qt's package index", "\n".join(sorted(packages)[:80]))
    arch = "win64_msvc2022_64" if "win64_msvc2022_64" in arches else arches[-1]
    wanted = [f"qt.qt6.{tag}.{arch}"]
    for module in modules:
        name = next((n for n in packages if re.fullmatch(rf"qt\.qt6\.{tag}\.(addons\.)?{module}\.{arch}", n)), None)
        if not name:
            raise BuildError(f"Qt {qt_version} add-on '{module}' isn't in Qt's package index",
                             "\n".join(n for n in sorted(packages) if module in n))
        wanted.append(name)
    chosen, todo = [], list(wanted)
    while todo:
        name = todo.pop(0)
        if name in chosen or name not in packages:
            continue
        chosen.append(name)
        for dep in packages[name]["dependencies"]:
            if dep.startswith(f"qt.qt6.{tag}.") and arch in dep and not re.search(r"debug|examples|\.doc|\.src", dep):
                todo.append(dep)
    files = []
    for name in chosen:
        info = packages[name]
        for archive in info["archives"]:
            files.append((name, f"{info['base']}{name}/{info['version']}{archive}"))
    if not files:
        raise BuildError(f"Qt {qt_version} packages list no files to download", json.dumps(chosen))
    return arch, files


# ----------------------------------------------------------------------------- archives

def extract_zip(archive, dest, strip=0, prefix=""):
    """Extracts members under `prefix`, dropping `strip` leading path parts."""
    dest = Path(dest)
    with zipfile.ZipFile(archive) as z:
        for info in z.infolist():
            name = info.filename.replace("\\", "/")
            if prefix and not name.startswith(prefix):
                continue
            parts = name.split("/")[strip:]
            if not parts or not parts[0] or ".." in parts:
                continue
            target = dest.joinpath(*parts)
            if name.endswith("/"):
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with z.open(info) as src, open(target, "wb") as out:
                shutil.copyfileobj(src, out, 1 << 20)


def extract_tar(archive, dest, progress=None):
    """Streams a .tar.xz into dest, dropping the top folder. Links that Windows can't create
    without special rights are copied from their targets afterwards."""
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    deferred, count = [], 0

    def strip(name):
        parts = name.split("/", 1)
        return parts[1] if len(parts) == 2 else ""

    with tarfile.open(archive, mode="r|*") as tar:
        for member in tar:
            member.name = strip(member.name)
            if not member.name:
                continue
            if member.issym() or member.islnk():
                if member.islnk():
                    member.linkname = strip(member.linkname)
                deferred.append(member)
                continue
            try:
                tar.extract(member, dest, filter="data")
            except (tarfile.TarError, OSError) as e:
                raise BuildError("Could not unpack the engine source", f"{member.name}: {e}")
            count += 1
            if progress and count % 5000 == 0:
                progress(count)
    skipped = []
    for member in deferred:
        target = dest / member.name
        if member.islnk():
            source = dest / member.linkname
        else:
            source = (target.parent / member.linkname).resolve()
            if dest.resolve() not in source.parents:
                skipped.append(member.name)
                continue
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            if source.is_dir():
                shutil.copytree(source, target, dirs_exist_ok=True)
            elif source.exists():
                shutil.copy2(source, target)
            else:
                skipped.append(member.name)
        except OSError:
            skipped.append(member.name)
    return count, skipped


def remove_tree(path):
    def retry(func, p, _exc):
        try:
            os.chmod(p, 0o700)
            func(p)
        except OSError:
            pass
    if Path(path).exists():
        if sys.version_info >= (3, 12):
            shutil.rmtree(path, onexc=retry)
        else:                                               # pragma: no cover
            shutil.rmtree(path, onerror=retry)


# ----------------------------------------------------------------------------- processes

def run(cmd, env=None, cwd=None, logfile=None, priority=None, on_line=None, timeout=None, tail=400):
    """Runs a command, streaming its output to `logfile`. Returns (exit code, last lines)."""
    flags = priority or 0
    last = collections.deque(maxlen=tail)
    handle = open(logfile, "a", encoding="utf-8", errors="replace") if logfile else None
    try:
        if handle:
            handle.write(f"\n==== {time.strftime('%Y-%m-%d %H:%M:%S')}  {' '.join(map(str, cmd))}\n")
        proc = subprocess.Popen([str(c) for c in cmd], cwd=cwd, env=env, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                creationflags=flags if IS_WINDOWS else 0)
        watchdog = None
        if timeout:
            def stop():
                last.append(f"[stopped after {timeout} s]")
                proc.kill()
            watchdog = threading.Timer(timeout, stop)
            watchdog.daemon = True
            watchdog.start()
        try:
            for raw in proc.stdout:
                line = raw.decode("utf-8", "replace").rstrip("\r\n")
                last.append(line)
                if handle:
                    handle.write(line + "\n")
                if on_line:
                    on_line(line)
            code = proc.wait()
        finally:
            if watchdog:
                watchdog.cancel()
        return code, list(last)
    finally:
        if handle:
            handle.close()


def which(name, env):
    """Windows looks programs up in *this* process's PATH, not the child's, so resolve them."""
    found = shutil.which(name, path=(env or os.environ).get("PATH"))
    if not found:
        raise BuildError(f"Build tool '{name}' was not found", (env or os.environ).get("PATH", ""))
    return found


def capture(cmd, env=None, cwd=None, timeout=600):
    out = subprocess.run([str(c) for c in cmd], env=env, cwd=cwd, capture_output=True, timeout=timeout)
    return out.returncode, out.stdout.decode("utf-8", "replace") + out.stderr.decode("utf-8", "replace")


ERROR_LINE = re.compile(r"FAILED:|error C\d+|error LNK\d+|fatal error|CMake Error|ninja: build stopped|"
                        r"Traceback|Error:|ERROR:|error:", re.I)


def error_excerpt(lines, limit=120):
    """The interesting part of a failed command's output."""
    hits = [i for i, line in enumerate(lines) if ERROR_LINE.search(line)]
    if not hits:
        return "\n".join(lines[-limit:])
    start = max(0, hits[0] - 5)
    return "\n".join(lines[start:start + limit])


# ----------------------------------------------------------------------------- this PC

APP_CONTROL_BLOCKED = ("Windows blocked the new engine: Smart App Control (or another app-control policy) "
                       "only lets programs with a trusted publisher's signature load, and an engine built on this "
                       "PC has none. The standard engine was put back. To use H.264 builds, Smart App Control has "
                       "to be off (Windows Security > App & browser control).")


def smart_app_control_state(read=None):
    """'on', 'evaluation', 'off' or None (not Windows 11 / unknown). Read-only."""
    if read is None:
        if not IS_WINDOWS:
            return None

        def read():
            import winreg
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\CI\Policy") as key:
                return winreg.QueryValueEx(key, "VerifiedAndReputablePolicyState")[0]
    try:
        value = read()
    except (OSError, ImportError):
        return None
    return {0: "off", 1: "on", 2: "evaluation"}.get(value)


def app_control_blocked(text):
    return "Application Control policy" in text or "blocked this file" in text


def total_ram_gb():
    if not IS_WINDOWS:
        try:
            return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 2 ** 30
        except (ValueError, OSError, AttributeError):
            return 8.0

    class MemoryStatus(ctypes.Structure):
        _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
    status = MemoryStatus()
    status.dwLength = ctypes.sizeof(MemoryStatus)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))
    return status.ullTotalPhys / 2 ** 30


def fixed_drives():
    if not IS_WINDOWS:
        return ["/"]
    mask = ctypes.windll.kernel32.GetLogicalDrives()
    drives = []
    for i in range(26):
        if mask & (1 << i):
            root = f"{chr(65 + i)}:\\"
            if ctypes.windll.kernel32.GetDriveTypeW(ctypes.c_wchar_p(root)) == 3:   # DRIVE_FIXED
                drives.append(root)
    return drives


def choose_work_dir(state, needed_gb=MIN_FREE_GB, drives=None, system_drive=None):
    """Reuses the folder from an earlier run; otherwise picks the system drive when it has
    room (usually the fastest disk), else the fixed drive with the most free space."""
    if state.get("work") and Path(state["work"]).exists():
        return Path(state["work"])
    drives = drives if drives is not None else fixed_drives()
    system_drive = system_drive or os.environ.get("SystemDrive", "C:")

    def same(a, b):
        return a.rstrip("\\/").upper() == b.rstrip("\\/").upper()
    free = {}
    for d in drives:
        try:
            free[d] = shutil.disk_usage(d).free / 2 ** 30
        except OSError:
            pass
    roomy = [d for d, gb in free.items() if gb >= needed_gb]
    if not roomy:
        listing = ", ".join(f"{d} {gb:.0f} GB free" for d, gb in free.items()) or "no drives found"
        raise BuildError(f"Not enough disk space: the build needs about {needed_gb} GB free on one drive "
                         f"({listing}).")
    system = [d for d in roomy if same(d, system_drive)]
    pick = system[0] if system else max(roomy, key=lambda d: free[d])
    return Path(pick) / WORK_DIRNAME


def parallel_jobs(cpus=None, ram_gb=None):
    """Each compiler process can take 2+ GB on Chromium code, so memory limits the jobs."""
    cpus = cpus or os.cpu_count() or 4
    ram_gb = ram_gb if ram_gb is not None else total_ram_gb()
    return max(1, min(cpus, int((ram_gb - 2) // 2.5)))


def pid_alive(pid):
    """True while that process exists (and, on Windows, is a Python - pids get reused)."""
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    if not IS_WINDOWS:
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(0x1000, False, pid)          # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return False
    try:
        code = ctypes.c_ulong()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)) or code.value != 259:   # STILL_ACTIVE
            return False
        buffer = ctypes.create_unicode_buffer(1024)
        size = ctypes.c_ulong(len(buffer))
        if kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
            return os.path.basename(buffer.value).lower().startswith("python")
        return True
    finally:
        kernel32.CloseHandle(handle)


def acquire_lock(lock_file=None):
    """Only one builder at a time (the browser's Build button and build-engine.bat could
    both start one). Returns False if another is running."""
    lock_file = Path(lock_file or LOCK_FILE)
    try:
        other = int(lock_file.read_text().strip())
    except (OSError, ValueError):
        other = 0
    if other and other != os.getpid() and pid_alive(other):
        return False
    write_atomic(lock_file, str(os.getpid()))
    return True


def release_lock(lock_file=None):
    lock_file = Path(lock_file or LOCK_FILE)
    try:
        if int(lock_file.read_text().strip()) == os.getpid():
            lock_file.unlink()
    except (OSError, ValueError):
        pass


RELAUNCHED = {"done": False}


def relaunch_browser():
    """After the browser closed itself for the swap ('Restart to finish'), open it again;
    it reads restart.json to bring the tabs back. Once per run, and only for a recent
    restart.json (the browser ignores older ones too)."""
    if RELAUNCHED["done"] or not RESTART_FILE.exists() or file_in_use(PYSIDE / "Qt6WebEngineCore.dll"):
        return False
    try:
        if time.time() - RESTART_FILE.stat().st_mtime > 6 * 3600:
            return False
    except OSError:
        return False
    exe = PYWEXE if PYWEXE.exists() else PYEXE
    flags = (0x08000000 | 0x00000200 | 0x00000008) if IS_WINDOWS else 0   # NO_WINDOW|NEW_GROUP|DETACHED
    try:
        subprocess.Popen([str(exe), str(BROWSER_SCRIPT)], cwd=str(APP), creationflags=flags,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         close_fds=True)
        RELAUNCHED["done"] = True
        return True
    except OSError:
        return False


def dir_size(path):
    total, stack = 0, [str(path)]
    while stack:
        try:
            with os.scandir(stack.pop()) as entries:
                for entry in entries:
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            stack.append(entry.path)
                        else:
                            total += entry.stat(follow_symlinks=False).st_size
                    except OSError:
                        pass
        except OSError:
            pass
    return total


def keep_awake(on=True):
    """Stops Windows sleeping mid-build (only while this window is open)."""
    if IS_WINDOWS:
        flags = 0x80000000 | (0x00000001 if on else 0)    # ES_CONTINUOUS | ES_SYSTEM_REQUIRED
        ctypes.windll.kernel32.SetThreadExecutionState(flags)


def lower_own_priority():
    if IS_WINDOWS:
        handle = ctypes.windll.kernel32.GetCurrentProcess()
        ctypes.windll.kernel32.SetPriorityClass(handle, BELOW_NORMAL_PRIORITY_CLASS)


def pyside_info():
    """Versions of the browser's own Qt/PySide, read in a child process so this one never
    loads (and locks) the engine DLL."""
    code = ("import json, importlib.metadata as md\n"
            "from PySide6 import QtCore\n"
            "from PySide6 import QtWebEngineCore as W\n"
            "def v(n):\n"
            "    try: return md.version(n)\n"
            "    except Exception: return None\n"
            "print('PYSIDE_INFO ' + json.dumps({'qt': QtCore.qVersion(), 'pyside': v('PySide6'),"
            " 'wheel': v('PySide6_WebEngine'), 'webengine': W.qWebEngineVersion(),"
            " 'chromium': W.qWebEngineChromiumVersion(),"
            " 'security': getattr(W, 'qWebEngineChromiumSecurityPatchVersion', lambda: '')()}))\n")
    rc, out = capture([PYEXE, "-c", code], cwd=APP, timeout=180)
    m = re.search(r"PYSIDE_INFO (\{.*\})", out)
    if rc != 0 or not m:
        raise BuildError("Could not read the browser's engine version", out[-3000:])
    return json.loads(m.group(1))


# ----------------------------------------------------------------------------- Visual Studio

def program_files_x86():
    return Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"))


def vswhere(*args, products="*"):
    exe = program_files_x86() / "Microsoft Visual Studio" / "Installer" / "vswhere.exe"
    if not exe.exists():
        return []
    rc, out = capture([exe, "-products", products, "-version", "[17.0,18.0)", "-format", "json", "-utf8", *args],
                      timeout=120)
    try:
        return json.loads(out[out.find("["):]) if rc == 0 else []
    except ValueError:
        return []


def find_visual_studio():
    """Newest Visual Studio 2022 (any edition) with the C++ compiler and ATL."""
    found = vswhere("-requires", "Microsoft.VisualStudio.Component.VC.Tools.x86.x64",
                    "Microsoft.VisualStudio.Component.VC.ATL")
    found = [i for i in found
             if (Path(i["installationPath"]) / "VC" / "Auxiliary" / "Build" / "vcvarsall.bat").exists()]
    found.sort(key=lambda i: version_tuple(i.get("installationVersion", "0")), reverse=True)
    return Path(found[0]["installationPath"]) if found else None


def windows_sdk_build():
    include = program_files_x86() / "Windows Kits" / "10" / "Include"
    builds = []
    if include.exists():
        for d in include.iterdir():
            m = re.fullmatch(r"10\.0\.(\d+)\.0", d.name)
            if m and (d / "um" / "windows.h").exists():
                builds.append(int(m.group(1)))
    return max(builds, default=0)


def msvc_environment(vs_path):
    bat = Path(vs_path) / "VC" / "Auxiliary" / "Build" / "vcvarsall.bat"
    out = subprocess.run(f'cmd.exe /d /s /c ""{bat}" x64 >nul 2>&1 && set"', capture_output=True, timeout=300)
    env = {}
    for line in out.stdout.decode("mbcs" if IS_WINDOWS else "utf-8", "replace").splitlines():
        key, sep, value = line.partition("=")
        if sep and key:
            env[key.upper()] = value
    if "VCTOOLSINSTALLDIR" not in env:
        raise BuildError("The Microsoft C++ tools didn't start (vcvarsall failed)",
                         out.stdout.decode(errors="replace")[-3000:])
    return env


# ----------------------------------------------------------------------------- the builder

class Builder:
    def __init__(self, args):
        self.args = args
        self.state = load_json(STATE_FILE, {})
        self.state.setdefault("done", [])
        self.info = None
        self.work = None
        self.env = None
        self.jobs = 1

    # paths inside the work folder (kept short for Chromium)
    @property
    def tools(self): return self.work / "t"
    @property
    def downloads(self): return self.work / "dl"
    @property
    def src(self): return self.work / "s"
    @property
    def bld(self): return self.work / "b"
    @property
    def inst(self): return self.work / "inst"
    @property
    def logs(self): return self.work / "logs"
    @property
    def build_python(self): return self.tools / "py" / "python.exe"

    def done(self, step):
        return step in self.state["done"]

    def mark(self, step):
        if step not in self.state["done"]:
            self.state["done"].append(step)
        save_state(self.state)

    def heading(self, step):
        number = STEPS.index(step) + 1
        STATUS_CONTEXT.update(key=step, number=number)
        log(f"\n[{number}/{len(STEPS)}] {STEP_TITLES[step]}")
        set_status("RUNNING", f"{number}/{len(STEPS)} {STEP_TITLES[step]}")

    def discover(self):
        """What the browser runs now, and the newest engine source for it. Shared by a real
        build and by --check-only (the browser's update check)."""
        if not PYEXE.exists() or not PYSIDE.exists():
            raise BuildError("The browser's Python isn't set up yet - run setup.bat first.")
        info = pyside_info()
        engine = version_tuple(info["webengine"])          # e.g. (6, 140, 0)
        minor, patch = engine[1], engine[2] if len(engine) > 2 else 0
        installed = load_json(INSTALLED_FILE, {})
        ours = bool(installed) and (PYSIDE / "Qt6WebEngineCore.dll").exists() and \
            installed.get("core_sha256") == file_sha256(PYSIDE / "Qt6WebEngineCore.dll")
        trace = []
        try:
            sources = probe_sources(minor, patch, trace=trace)
        except (urllib.error.URLError, OSError, TimeoutError) as e:
            raise BuildError(f"Could not reach download.qt.io ({e})", "\n".join(trace + [repr(e)]))
        if not sources:                                   # unexpected layout: look around
            sources = find_sources(minor, trace=trace)
        tags = git_release_tags(minor, trace=trace)
        best_tarball = max((p for p in sources if p >= patch), default=None)
        best_tag = max((p for p in tags if p >= patch), default=None)
        if best_tarball is None and best_tag is None:
            raise BuildError(f"No Qt WebEngine 6.{minor}.x source release was found (download.qt.io or Qt's git).",
                             "\n".join(trace))
        security = None
        if best_tarball is not None and (best_tag is None or best_tarball >= best_tag):
            best = best_tarball
            files = sources[best]
            source = {"kind": "tarball", "url": files.get("tar.xz") or files.get("zip")}
            where = "Qt's source package"
        else:
            best = best_tag
            repo, ref, kind, commit = tags[best]
            source = {"kind": "git", "repo": repo, "tag": ref, "ref_kind": kind, "commit": commit}
            security = remote_chromium_version(repo, commit)[1]
            where = f"Qt's git release tag {ref}" if kind == "tag" else \
                f"Qt's {ref} release branch (Qt hasn't published a source package or tag for it yet)"
        target = f"6.{minor}.{best}"
        return {"info": info, "minor": minor, "patch": patch, "installed": installed, "ours": ours,
                "source": source, "where": where, "target": target, "best": best, "security": security,
                "trace": trace,
                "up_to_date": is_up_to_date(ours, installed, target, source, security, info.get("security"))}

    def check_only(self):
        """The browser's daily update check: writes update-check.json, changes nothing else."""
        result = {"checked": time.time()}
        try:
            d = self.discover()
            result.update(ours=d["ours"], current=d["info"]["webengine"], current_security=d["info"].get("security"),
                          available=d["target"], available_security=d["security"], source=d["where"],
                          update_available=d["ours"] and not d["up_to_date"])
        except BuildError as e:
            result["error"] = str(e)
        write_atomic(UPDATE_FILE, json.dumps(result, indent=2))
        print(json.dumps(result), flush=True)
        return 0

    # ------------------------------------------------------------------ 0. what to build
    def check(self):
        log("Huginn engine builder")
        log("=======================")
        STATUS_CONTEXT.update(key="check", number=0)
        set_status("RUNNING", "0 Looking up the newest engine source")
        sac = smart_app_control_state()
        if sac == "on":
            raise BuildError("Smart App Control is on, and it blocks an engine built on this PC (it has no publisher "
                             "signature), so building would be wasted. Turn Smart App Control off in Windows Security "
                             "> App & browser control to use H.264 builds, or keep the standard engine.")
        if sac == "evaluation":
            log("Note: Smart App Control is in evaluation mode. If Windows turns it on, it will block the "
                "engine built here (it isn't signed).")
        log("Looking up the newest engine source (download.qt.io and Qt's git) ...")
        d = self.discover()
        self.info = info = d["info"]
        installed, ours, target, where, best, patch = (d["installed"], d["ours"], d["target"], d["where"],
                                                       d["best"], d["patch"])
        for line in d["trace"]:
            log("  " + line, console=False)
        log(f"Browser engine now: Qt WebEngine {info['webengine']} (Chromium {info['chromium']}"
            + (f", security patches to {info['security']}" if info.get("security") else "") + f"), Qt {info['qt']}")
        if installed and not ours:
            log("The engine files were replaced since the last build (PySide6 was updated), "
                "so this builds again for the new version.")
        new_source = d["source"]
        done = self.state.get("done", [])
        if ("configure" in done and "install" not in done and self.state.get("target") and not self.args.force
                and Path(self.state.get("work") or "/nonexistent").joinpath("b").is_dir()):
            # A build is under way: finish it rather than start over for a newer release or
            # branch commit (the next update check picks those up).
            if target != self.state["target"]:
                log(f"Finishing the Qt WebEngine {self.state['target']} build that's under way first "
                    f"({target} can be built afterwards).")
            kept = dict(self.state.get("source") or new_source)
            local = Path(self.state["work"]) / "s" / "CHROMIUM_VERSION"
            if not kept.get("commit") and local.exists():
                based, patched = parse_chromium_version(local.read_text(encoding="utf-8", errors="replace"))
                kept.setdefault("chromium", based)
                kept.setdefault("security", patched)
                if patched and patched == d.get("security") and new_source.get("commit"):
                    kept["commit"] = new_source["commit"]
            target, new_source = self.state["target"], kept
        if self.state.get("target") == target and self.state.get("source", {}).get("commit") \
                and new_source.get("commit") != self.state["source"].get("commit"):
            self.state["done"] = [s for s in self.state.get("done", []) if s in ("vs", "tools", "qt")]
        self.state["source"] = new_source
        log(f"Building: Qt WebEngine {target} with H.264/AAC, from {where}"
            + (" (newer patch release)" if best > patch else "")
            + (f"; security patches up to Chromium {d['security']}" if d["security"] else ""))

        unfinished = self.state.get("target") == target and any(s not in self.state["done"] for s in STEPS)
        if d["up_to_date"] and not unfinished and not self.args.force:
            log("\nThe engine is already built with H.264/AAC and up to date - nothing to do.")
            set_status("DONE", "up to date", f"engine {installed.get('webengine')} with H.264/AAC")
            return False
        if self.args.force:
            self.state["done"] = [s for s in self.state["done"] if s in ("vs", "tools", "qt")]

        try:
            repo = list_dir(QT_REPO)
        except (urllib.error.URLError, OSError) as e:
            raise BuildError("Could not reach download.qt.io", str(e))
        qt_folder = "qt6_" + "".join(str(x) for x in version_tuple(info["qt"]))
        if qt_folder + "/" not in repo:
            raise BuildError(f"Qt {info['qt']} development files aren't on download.qt.io ({qt_folder} missing).")

        self.state = reset_for_target(self.state, target, info["qt"])
        ram, cpus = total_ram_gb(), os.cpu_count() or 4
        self.jobs = parallel_jobs(cpus, ram)
        self.work = choose_work_dir(self.state)
        if not self.work.exists():                        # new (or deleted) work folder
            self.state["done"] = [s for s in self.state["done"] if s == "vs"]
        self.state["work"] = str(self.work)
        save_state(self.state)
        DISK.update(path=self.work.anchor, baseline=shutil.disk_usage(self.work.anchor).free, lowest=None)
        free = shutil.disk_usage(self.work.anchor).free / 2 ** 30
        log(f"This PC: {cpus} logical cores, {ram:.0f} GB memory -> {self.jobs} compile jobs at a time")
        log(f"Work folder: {self.work} ({free:.0f} GB free on that drive)")
        estimate = 32 / self.jobs
        log(f"The compile step usually takes roughly {max(1, round(estimate * 0.6))}-{max(2, round(estimate * 1.5))} hours "
            "here. It runs at low priority, so games and other programs get the CPU first.")
        self.state["system"] = {"cpus": cpus, "ram_gb": round(ram), "jobs": self.jobs}
        save_state(self.state)
        self.work.mkdir(parents=True, exist_ok=True)
        for d in (self.tools, self.downloads, self.logs):
            d.mkdir(exist_ok=True)

        if "codec_before" not in self.state:
            result = run_codec_check(self.logs / "codec_check_before.txt")
            self.state["codec_before"] = result.get("summary", "unknown")
            save_state(self.state)
            log(f"Video check with the current engine: {self.state['codec_before']}")
        return True

    # ------------------------------------------------------------------ 1. Visual Studio
    def step_vs(self):
        vs, sdk = find_visual_studio(), windows_sdk_build()
        if vs and sdk >= MIN_SDK_BUILD:
            log(f"Found: {vs} (Windows SDK 10.0.{sdk})")
        else:
            system = os.environ.get("SystemDrive", "C:") + "\\"
            if shutil.disk_usage(system).free / 2 ** 30 < VS_FREE_GB:
                raise BuildError(f"Microsoft's C++ Build Tools need about {VS_FREE_GB} GB free on {system}.")
            boot = self.downloads / "vs_BuildTools.exe"
            download(VS_BOOTSTRAPPER, boot, label="Visual Studio installer")
            existing = vswhere(products="Microsoft.VisualStudio.Product.BuildTools")
            cmd = [boot]
            if existing:
                cmd += ["modify", "--installPath", existing[0]["installationPath"]]
            cmd += ["--passive", "--wait", "--norestart", "--nocache"]
            for component in VS_COMPONENTS:
                cmd += ["--add", component]
            log("Installing Microsoft C++ Build Tools 2022 (about 6 GB, 10-30 minutes).")
            log(">>> Windows will ask for permission - click Yes. <<<")
            set_status("WAITING", "1/9 Microsoft C++ Build Tools",
                       "Waiting for the Windows permission prompt / installer", waiting_for="permission")
            rc = subprocess.run([str(c) for c in cmd]).returncode
            if rc in (0, 3010) and self.disk_on_system_drive():
                DISK.update(baseline=shutil.disk_usage(DISK["path"]).free, lowest=None)   # don't count VS
            if rc not in (0, 3010):
                hint = " (it was cancelled)" if rc in (1602, 1223, 5007, 87) else ""
                raise BuildError(f"The C++ Build Tools installer stopped with code {rc}{hint}.")
            vs, sdk = find_visual_studio(), windows_sdk_build()
            if not vs or sdk < MIN_SDK_BUILD:
                raise BuildError("The C++ Build Tools installed but the compiler or Windows SDK is still missing.",
                                 f"vs={vs} sdk=10.0.{sdk}")
            log(f"Installed: {vs} (Windows SDK 10.0.{sdk})")
        self.state["vs_path"] = str(vs)
        self.mark("vs")

    # ------------------------------------------------------------------ 2. tools
    def step_tools(self):
        py = self.build_python
        if not py.exists():
            pkg = self.downloads / f"python.{BUILD_PYTHON}.nupkg"
            download(NUGET_PYTHON, pkg, label=f"Python {BUILD_PYTHON}")
            remove_tree(py.parent)
            extract_zip(pkg, py.parent, strip=1, prefix="tools/")
        if capture([py, "-m", "pip", "--version"])[0] != 0:
            rc, out = capture([py, "-m", "ensurepip", "--upgrade"])
            if rc != 0:
                raise BuildError("Could not set up pip for the build Python", out[-3000:])
        rc, lines = run([py, "-m", "pip", "install", "--disable-pip-version-check", "--no-warn-script-location",
                         "--upgrade", *PIP_PACKAGES], logfile=self.logs / "tools.log")
        if rc != 0:
            raise BuildError("Could not install the build tools (CMake, Ninja, html5lib, py7zr)", error_excerpt(lines))

        node_dir = self.tools / "node"
        if not (node_dir / "node.exe").exists():
            releases = json.loads(fetch_text(NODE_DIST + "index.json"))
            release = next(r for r in releases if r.get("lts") and version_tuple(r["version"])[0] >= 20
                           and "win-x64-zip" in r.get("files", []))
            version = release["version"]
            name = f"node-{version}-win-x64.zip"
            sums = fetch_text(f"{NODE_DIST}{version}/SHASUMS256.txt")
            digest = next(line.split()[0] for line in sums.splitlines() if line.strip().endswith(" " + name))
            archive = self.downloads / name
            download(f"{NODE_DIST}{version}/{name}", archive, sha256=digest, label=f"Node.js {version}")
            remove_tree(node_dir)
            extract_zip(archive, node_dir, strip=1)

        gnu = self.tools / "gnu"
        if not (gnu / "gperf.exe").exists():
            if GNU_ZIP.exists():
                extract_zip(GNU_ZIP, gnu)
            else:
                self.fetch_gnu_tools(gnu)
            for dll in ("vcruntime140.dll", "vcruntime140_1.dll"):
                if (PYDIR / dll).exists():
                    shutil.copy2(PYDIR / dll, gnu / dll)
        self.env = None                                   # rebuild PATH now the tools exist
        self.make_env()
        for tool in (["python", "--version"], ["node", "--version"], ["cmake", "--version"],
                     ["ninja", "--version"], ["gperf", "--version"], ["bison", "--version"], ["flex", "--version"]):
            rc, out = capture([which(tool[0], self.env), *tool[1:]], env=self.env)
            first = out.strip().splitlines()[0] if out.strip() else ""
            if rc != 0:
                raise BuildError(f"Build tool '{tool[0]}' doesn't run", out[-2000:])
            log(f"  {tool[0]}: {first}")
        self.mark("tools")

    def fetch_gnu_tools(self, gnu):
        """gperf, bison and flex from conda-forge, checked against pinned checksums."""
        gnu.mkdir(parents=True, exist_ok=True)
        for name, sha256, wanted in GNU_PACKAGES:
            archive = self.downloads / name
            download(CONDA_FORGE + name, archive, sha256=sha256, label=name.split("-")[0])
            script = ("import io, json, sys, tarfile, zipfile, shutil, zstandard, pathlib\n"
                      "archive, dest, wanted = sys.argv[1], pathlib.Path(sys.argv[2]), json.loads(sys.argv[3])\n"
                      "z = zipfile.ZipFile(archive)\n"
                      "inner = next(n for n in z.namelist() if n.startswith('pkg-') and n.endswith('.tar.zst'))\n"
                      "data = zstandard.ZstdDecompressor().stream_reader(io.BytesIO(z.read(inner)))\n"
                      "with tarfile.open(fileobj=data, mode='r|') as tar:\n"
                      "    for member in tar:\n"
                      "        for src, targets in wanted.items():\n"
                      "            if member.isfile() and (member.name == src or (src.endswith('/') and member.name.startswith(src))):\n"
                      "                rel = member.name[len(src):]\n"
                      "                payload = tar.extractfile(member).read()\n"
                      "                for t in targets:\n"
                      "                    out = dest / (t + rel if src.endswith('/') else t)\n"
                      "                    out.parent.mkdir(parents=True, exist_ok=True)\n"
                      "                    out.write_bytes(payload)\n")
            rc, out = capture([self.build_python, "-c", script, archive, gnu, json.dumps(wanted)], timeout=600)
            if rc != 0:
                raise BuildError(f"Couldn't unpack {name}", out[-3000:])
        if not (gnu / "gperf.exe").exists() or not (gnu / "bison.exe").exists():
            raise BuildError("gperf/bison didn't unpack as expected", "\n".join(p.name for p in gnu.iterdir()))

    def make_env(self):
        if self.env is not None:
            return self.env
        env = msvc_environment(self.state["vs_path"]) if IS_WINDOWS else {k.upper(): v for k, v in os.environ.items()}
        site = self.tools / "py" / "Lib" / "site-packages"
        paths = [self.tools / "py", self.tools / "py" / "Scripts", site / "cmake" / "data" / "bin",
                 site / "ninja" / "data" / "bin", self.tools / "node", self.tools / "gnu"]
        env["PATH"] = os.pathsep.join(str(p) for p in paths if p.exists()) + os.pathsep + env.get("PATH", "")
        for key in ("PYTHONHOME", "PYTHONPATH", "QTDIR"):
            env.pop(key, None)
        env["PYTHONUTF8"] = "1"
        env["NINJAFLAGS"] = f"-j{self.jobs}"
        env["CMAKE_GENERATOR"] = "Ninja"
        self.env = env
        return env

    # ------------------------------------------------------------------ 3. Qt SDK
    def qt_prefix(self):
        """The unpacked Qt matching the browser's Qt version. Qt 6.12's packages unpack straight
        into the qt folder (bin, lib...); older ones into qt/<version>/<compiler>/."""
        root = self.work / "qt"
        for bat in [root / "bin" / "qt-configure-module.bat", *sorted(root.glob("*/*/bin/qt-configure-module.bat"))]:
            if not bat.exists():
                continue
            prefix = bat.parent.parent
            for cfg in (prefix / "lib" / "cmake" / "Qt6").glob("Qt6ConfigVersion*.cmake"):
                text = cfg.read_text(encoding="utf-8", errors="replace")
                if re.search(rf'PACKAGE_VERSION\s+"{re.escape(self.info["qt"])}"', text):
                    return prefix
        return None

    def step_qt(self):
        if not self.qt_prefix():
            qt, trace = self.info["qt"], []
            packages = qt_package_index(qt, trace=trace)
            for line in trace:
                log("  " + line, console=False)
            if not packages:
                raise BuildError(f"Couldn't read Qt's package index for Qt {qt}", "\n".join(trace))
            arch, files = qt_packages_for(packages, qt, QT_MODULES)
            log(f"Downloading Qt {qt} ({arch}) with {', '.join(QT_MODULES)}: {len(files)} packages ...")
            target = self.work / "qt"
            remove_tree(target)                           # never mix two Qt versions
            for i, (package, url) in enumerate(files, 1):
                name = url.rsplit("/", 1)[1]
                set_status("RUNNING", "3/9 Qt development files", f"package {i} of {len(files)}: {name}",
                           progress=(i - 1) / len(files))
                sha1 = None
                try:
                    m = re.search(r"\b([0-9a-fA-F]{40})\b", fetch_text(url + ".sha1", timeout=30))
                    sha1 = m.group(1).lower() if m else None
                except (urllib.error.URLError, OSError, TimeoutError):
                    pass
                archive = self.downloads / "qt" / name
                download(url, archive, label=name)
                if sha1 and file_digest(archive, "sha1") != sha1:
                    archive.unlink()
                    raise BuildError(f"{name} didn't match Qt's checksum - run again to re-download.")
                rc, out = capture([self.build_python, "-c",
                                   "import sys, py7zr; py7zr.SevenZipFile(sys.argv[1]).extractall(sys.argv[2])",
                                   archive, target], timeout=1800)
                if rc != 0:
                    raise BuildError(f"Couldn't unpack {name}", out[-3000:])
            if not self.qt_prefix():
                raise BuildError(f"Qt {qt} unpacked but qt-configure-module wasn't found",
                                 "\n".join(str(p) for p in target.glob("*/*")))
        prefix = self.qt_prefix()
        missing = [m for m in ("Qt6Quick", "Qt6WebChannel", "Qt6Positioning", "Qt6Widgets", "Qt6BuildInternals")
                   if not (prefix / "lib" / "cmake" / m).exists()]
        if missing:
            raise BuildError("The Qt development files are incomplete: " + ", ".join(missing))
        log(f"Qt development files: {prefix}")
        for f in (self.downloads / "qt").glob("*.7z"):
            f.unlink()
        self.mark("qt")

    # ------------------------------------------------------------------ 4. source
    def step_source(self):
        if self.state["source"]["kind"] == "git":
            return self.source_from_git()
        url = self.state["source"]["url"]
        name = url.rsplit("/", 1)[1]
        archive = self.downloads / name
        checksum = expected_checksum(url)
        log(f"Downloading {name} (about 650 MB) ...")
        final = download(url, archive, sha256=checksum[1] if checksum and checksum[0] == "sha256" else None,
                         label="engine source")
        if checksum and checksum[0] == "md5" and file_md5(archive) != checksum[1]:
            archive.unlink()
            raise BuildError("The engine source didn't match its published checksum - run again to re-download.")
        if not checksum and not final.startswith("https://"):
            raise BuildError("The engine source came over an unencrypted mirror with no checksum to check it "
                             "against - run again to try another mirror.", final)
        log("  verified against the checksum published by Qt" if checksum else "  (no checksum published; came over HTTPS)")
        log("Unpacking (a few hundred thousand files - this can take 15-40 minutes) ...")
        remove_tree(self.src)
        started = time.time()

        def progress(n):
            set_status("RUNNING", "4/9 Engine source code", f"unpacked {n:,} files")
            if n % 50000 == 0:
                log(f"  {n:,} files ...")
        if name.endswith(".zip"):
            extract_zip(archive, self.src, strip=1)
            skipped = []
        else:
            count, skipped = extract_tar(archive, self.src, progress)
            log(f"  {count:,} files in {fmt_duration(time.time() - started)}")
        if skipped:
            log(f"  {len(skipped)} links could not be created (not needed on Windows): {skipped[:5]}")
        if not (self.src / "CMakeLists.txt").exists():
            raise BuildError("The unpacked engine source looks incomplete (no CMakeLists.txt).")
        self.mark("source")

    def ensure_git(self):
        found = shutil.which("git")
        if found:
            return found
        exe = self.tools / "git" / "cmd" / "git.exe"
        if not exe.exists():
            release = json.loads(fetch_text(MINGIT_RELEASE))
            asset = next((a for a in release.get("assets", [])
                          if re.fullmatch(r"MinGit-[\d.]+-64-bit\.zip", a.get("name", ""))), None)
            if not asset:
                raise BuildError("Couldn't find portable Git (MinGit) to download the engine source",
                                 json.dumps([a.get("name") for a in release.get("assets", [])]))
            digest = asset.get("digest") or ""
            archive = self.downloads / asset["name"]
            download(asset["browser_download_url"], archive, label="portable Git",
                     sha256=digest.split(":", 1)[1] if digest.startswith("sha256:") else None)
            remove_tree(self.tools / "git")
            extract_zip(archive, self.tools / "git")
        return str(exe)

    def fetch_chromium(self, git, repo, env):
        """Fetches exactly the Chromium commit Qt WebEngine pins. (A plain 'submodule update'
        first downloads the Chromium repo's default branch - an unrelated 2014 snapshot.)
        Falls back to 'submodule update' for servers that refuse fetching a commit by id."""
        log_file = self.logs / "source.log"
        rc, out = capture([git, "-C", self.src, "rev-parse", "HEAD:src/3rdparty"], env=env)
        sha = out.strip().splitlines()[-1] if rc == 0 and out.strip() else ""
        if re.fullmatch(r"[0-9a-f]{40}", sha):
            url = repo.rsplit("/", 1)[0] + "/qtwebengine-chromium.git"
            target = self.src / "src" / "3rdparty"
            steps = [[git, *GIT_CONFIG, "-C", target, "init", "-q"],
                     [git, *GIT_CONFIG, "-C", target, "fetch", "--depth", "1", "--no-tags", url, sha],
                     [git, *GIT_CONFIG, "-C", target, "checkout", "-q", "--force", "FETCH_HEAD"]]
            for cmd in steps:
                rc, lines = run(cmd, env=env, logfile=log_file)
                if rc != 0:
                    break
            if rc == 0:
                return rc, lines
            log("  fetching the Chromium commit directly didn't work; using git submodule update")
            remove_tree(target / ".git")
        return run([git, *GIT_CONFIG, "-C", self.src, "submodule", "update", "--init", "--depth", "1",
                    "src/3rdparty"], env=env, logfile=log_file)

    def source_from_git(self):
        git = self.ensure_git()
        tag = self.state["source"]["tag"]
        repos = [self.state["source"]["repo"]] + [r for r in QT_GIT_REPOS if r != self.state["source"]["repo"]]
        env = dict(os.environ, GIT_TERMINAL_PROMPT="0", GCM_INTERACTIVE="never")
        problems = []
        for repo in repos:
            log(f"Downloading Qt WebEngine {tag} and its Chromium code from {repo.split('/')[2]} "
                "(about 2 GB, then a few hundred thousand files are written - 15-45 minutes) ...")
            set_status("RUNNING", "4/9 Engine source code", f"downloading {tag} with git from {repo.split('/')[2]}")
            remove_tree(self.src)
            rc, lines = run([git, *GIT_CONFIG, "clone", "--depth", "1", "--branch", tag, "--no-tags", repo, self.src],
                            env=env, logfile=self.logs / "source.log")
            if rc == 0:
                set_status("RUNNING", "4/9 Engine source code", "downloading the Chromium part (the big one)")
                rc, lines = self.fetch_chromium(git, repo, env)
            if rc == 0 and (self.src / "CMakeLists.txt").exists() and (self.src / "src" / "3rdparty" / "chromium").is_dir():
                based, patched = parse_chromium_version(
                    (self.src / "CHROMIUM_VERSION").read_text(encoding="utf-8", errors="replace")
                    if (self.src / "CHROMIUM_VERSION").exists() else "")
                self.state["source"].update(chromium=based, security=patched)
                # The git history isn't needed to build (Chromium's version stamp is in the
                # files), so it goes now rather than taking space until the end.
                for git_dir in (self.src / ".git", self.src / "src" / "3rdparty" / ".git"):
                    if git_dir.is_dir():
                        remove_tree(git_dir)
                    elif git_dir.exists():
                        git_dir.unlink()
                log(f"  source ready ({tag}" + (f", security patches up to Chromium {patched}" if patched else "") + ")")
                self.mark("source")
                return
            problems.append(f"{repo}: exit {rc}\n{error_excerpt(lines, 40)}")
            log(f"  that didn't work ({repo.split('/')[2]}); " + ("trying the next server" if repo != repos[-1] else ""))
        raise BuildError(f"Downloading the engine source ({tag}) with git failed", "\n\n".join(problems))

    # ------------------------------------------------------------------ 5. configure
    def step_configure(self):
        prefix = self.qt_prefix()
        base = [prefix / "bin" / "qt-configure-module.bat", self.src,
                "-webengine-proprietary-codecs", "-no-feature-qtpdf-build",
                "--", f"-DCMAKE_BUILD_TYPE={RELEASE_CONFIG}", "-DQT_FEATURE_webengine_rust_build=OFF",
                "-DQT_BUILD_EXAMPLES=OFF", "-DQT_BUILD_TESTS=OFF", *SKIPPED_FEATURES,
                f"-DPython3_EXECUTABLE={self.build_python}", "-DPython3_FIND_REGISTRY=NEVER"]
        # Qt's Windows packages are RelWithDebInfo + Debug, and Qt WebEngine's build ties the
        # two together (asking for one configuration still compiles Chromium for both), so only
        # the release one is configured. If this Qt refuses that, both are built after all.
        for single in (True, False):
            if self.bld.exists():
                remove_tree(self.bld)
            self.bld.mkdir(parents=True)
            cmd = base + ([f"-DCMAKE_CONFIGURATION_TYPES={RELEASE_CONFIG}"] if single else [])
            rc, lines = run(cmd, env=self.env, cwd=self.bld, logfile=self.logs / "configure.log")
            if rc == 0 and (self.bld / "build.ninja").exists():
                break
            if single:
                log("  configuring for the release build alone didn't work here; building both configurations")
        if rc != 0 or not (self.bld / "build.ninja").exists():
            raise BuildError("Configuring the engine build failed", error_excerpt(lines))
        if (self.bld / "build-Debug.ninja").exists():
            log("  note: this Qt builds a Debug copy too, which roughly doubles the compile time")
        summary_file = self.bld / "config.summary"
        summary = summary_file.read_text(encoding="utf-8", errors="replace") if summary_file.exists() else "\n".join(lines)
        standard = parse_exports(dumpbin(PYSIDE / "Qt6WebEngineCore.dll", "/exports", self.env)) \
            if IS_WINDOWS else None
        problems = check_summary(summary, standard)
        if problems:
            raise BuildError("The build was configured without features the browser needs: " + "; ".join(problems),
                             summary[-6000:])
        log("  H.264/AAC (proprietary codecs): yes")
        self.mark("configure")

    # ------------------------------------------------------------------ 6. build
    def step_build(self):
        tracker = ProgressTracker()
        last_write = [0.0]

        def on_line(line):
            if tracker.feed(line) and time.time() - last_write[0] > 30:
                last_write[0] = time.time()
                set_status("RUNNING", "6/9 Compiling the engine", tracker.describe(),
                           progress=tracker.done / tracker.total if tracker.total else 0, eta=tracker.eta())
                print(f"  {tracker.describe()}", flush=True)

        config = release_config(self.bld)
        alias_install_config(self.bld, log)
        cmd = [which("cmake", self.env), "--build", self.bld, "--parallel", str(self.jobs)]
        if config:
            cmd += ["--config", config]
            log(f"  building the {config} configuration only (the browser doesn't use a Debug build)")
        rc, lines = run(cmd, env=self.env, cwd=self.bld, logfile=self.logs / "compile.log", priority=IDLE_PRIORITY_CLASS,
                        on_line=on_line)
        if rc != 0:
            raise BuildError("Compiling the engine failed", error_excerpt(lines))
        log(f"  compiled ({tracker.describe()})")
        self.mark("build")

    # ------------------------------------------------------------------ 7. install
    def step_install(self):
        remove_tree(self.inst)
        config = release_config(self.bld)
        rc, lines = run([which("cmake", self.env), "--install", self.bld, "--prefix", self.inst,
                         *(["--config", config] if config else [])], env=self.env, cwd=self.bld,
                        logfile=self.logs / "install.log")
        if rc != 0:
            raise BuildError("Collecting the built engine failed", error_excerpt(lines))
        if config:
            added = complete_install(self.inst, self.bld, config)
            if added:
                log(f"  added the engine's data files from the {config} build ({len(added)} files)")
        plan = install_plan(self.inst, PYSIDE)
        names = {Path(dst).name for _, dst in plan}
        if ("Qt6WebEngineCore.dll" not in names or "QtWebEngineProcess.exe" not in names
                or "qtwebengine_resources.pak" not in names or "icudtl.dat" not in names):
            raise BuildError("The build finished but the engine files are missing", json.dumps([str(d) for _, d in plan]))
        log("Checking the new engine fits the browser's Qt files ...")
        problems = compatibility_problems(plan, PYSIDE, lambda dll: dumpbin(dll, "/exports", self.env),
                                          lambda dll: dumpbin(dll, "/imports", self.env))
        if problems:
            raise BuildError("The new engine doesn't match the browser's Qt version, so it was not put in",
                             "\n".join(problems[:60]))
        log("  compatible")
        swap_in(plan, self.info, self.state["target"], extra={"source": self.state.get("source", {})})
        log(f"New engine in place ({len(plan)} files); the standard one is saved in {BACKUP_DIR.name}\\")
        self.mark("install")

    # ------------------------------------------------------------------ 8. verify
    def step_verify(self):
        result = run_codec_check(self.logs / "codec_check_after.txt")
        log(f"  video check: {result.get('summary', 'no result')}")
        if not result.get("ok"):
            restore_standard_engine("the video check failed")
            if "install" in self.state.get("done", []):     # the next run puts it in again first
                self.state["done"].remove("install")
                save_state(self.state)
            details = json.dumps(result, indent=2)[-4000:]
            if app_control_blocked(details):
                raise BuildError(APP_CONTROL_BLOCKED, details)
            raise BuildError("The new engine didn't pass the video check, so the standard engine was put back.", details)
        report = {"codec": result}
        if relaunch_browser():                  # it plays H.264 now: no need to wait for the checks
            log("  Huginn reopened with your tabs")
        for script in ("security_test.py", "adblock_test.py"):
            if not (APP / script).exists():
                continue
            set_status("RUNNING", "8/9 Checking the new engine", f"running {script}")
            out_file = HERE / f"verify_{script.replace('.py', '')}.txt"
            rc, lines = run([PYEXE, APP / script], cwd=APP, timeout=1800)
            out_file.write_text("\n".join(lines), encoding="utf-8")
            m = None
            for line in reversed(lines):
                m = re.search(r"(\d+) passed, (\d+) failed, (\d+) uncaught", line)
                if m:
                    break
            result_text = f"{m.group(1)} passed, {m.group(2)} failed" if m else f"no result (exit {rc})"
            report[script] = result_text
            log(f"  {script}: {result_text}")
        installed = load_json(INSTALLED_FILE, {})
        installed["verified"] = report
        write_atomic(INSTALLED_FILE, json.dumps(installed, indent=2))
        self.mark("verify")

    # ------------------------------------------------------------------ 9. cleanup
    def disk_on_system_drive(self):
        system = os.environ.get("SystemDrive", "C:").rstrip("\\/").upper()
        return str(DISK["path"] or "").rstrip("\\/").upper() == system

    def step_cleanup(self):
        note_disk()
        if DISK["baseline"] is not None and DISK["lowest"] is not None:
            peak = max(0, DISK["baseline"] - DISK["lowest"])
            log(f"  most disk space used during this build: {fmt_size(peak)}")
            installed = load_json(INSTALLED_FILE, {})
            if installed:
                installed["build_disk_peak_gb"] = round(peak / 2 ** 30, 1)
                write_atomic(INSTALLED_FILE, json.dumps(installed, indent=2))
        before = shutil.disk_usage(self.work.anchor).free
        if not self.args.keep_build:
            for path in (self.src, self.bld, self.inst):
                remove_tree(path)
            for f in self.downloads.glob("qtwebengine-everywhere-src-*"):
                f.unlink()
        freed = shutil.disk_usage(self.work.anchor).free - before
        log(f"  freed {fmt_size(max(0, freed))}; kept the tools and Qt files in {self.work} for future updates")
        self.mark("cleanup")

    # ------------------------------------------------------------------ driver
    def still_valid(self, step):
        """A step marked done whose results have since been deleted runs again."""
        checks = {
            "vs": lambda: Path(self.state.get("vs_path", "")).exists(),
            "tools": lambda: self.build_python.exists() and (self.tools / "node" / "node.exe").exists()
            and (self.tools / "gnu" / "gperf.exe").exists(),
            "qt": lambda: self.qt_prefix() is not None,
            "source": lambda: (self.src / "CMakeLists.txt").exists() or self.done("build"),
            "configure": lambda: (self.bld / "build.ninja").exists() or self.done("install"),
            "install": lambda: built_engine_in_place(),        # not if it was rolled back since
        }
        return checks.get(step, lambda: True)()

    def run_all(self):
        if not self.check():
            return 0
        lower_own_priority()
        keep_awake(True)                  # downloads and compiling both stop if Windows sleeps
        try:
            self.run_steps()
        finally:
            keep_awake(False)
        installed = load_json(INSTALLED_FILE, {})
        verified = installed.get("verified", {})
        log("\nDone. The browser now plays H.264/AAC video.")
        set_status("DONE", "finished", f"engine {installed.get('webengine')} with H.264/AAC; "
                   + "; ".join(f"{k}: {v if isinstance(v, str) else v.get('summary')}" for k, v in verified.items()))
        return 0

    def run_steps(self):
        for step in STEPS:
            if self.done(step) and not self.still_valid(step):
                self.state["done"].remove(step)
                save_state(self.state)
            if self.done(step):
                continue
            self.heading(step)
            if step not in ("vs", "tools"):
                self.make_env()
            getattr(self, "step_" + step)()


# ----------------------------------------------------------------------------- build checks

class ProgressTracker:
    """Follows ninja's '[done/total]' lines; the Chromium part is the one with the biggest total."""
    PATTERN = re.compile(r"^\[(\d+)/(\d+)\]")

    def __init__(self, clock=time.time):
        self.clock = clock
        self.done = self.total = 0
        self.samples = collections.deque(maxlen=400)

    def feed(self, line):
        m = self.PATTERN.match(line)
        if not m:
            return False
        done, total = int(m.group(1)), int(m.group(2))
        if total < self.total * 0.5:            # a small sub-build; keep showing the big one
            return False
        if total != self.total:
            self.samples.clear()
        self.done, self.total = done, total
        self.samples.append((self.clock(), done))
        return True

    def eta(self):
        if len(self.samples) < 2:
            return None
        (t0, d0), (t1, d1) = self.samples[0], self.samples[-1]
        if d1 <= d0 or t1 <= t0:
            return None
        return (self.total - self.done) * (t1 - t0) / (d1 - d0)

    def describe(self):
        if not self.total:
            return "starting"
        text = f"{self.done:,} of {self.total:,} steps ({self.done * 100 // self.total}%)"
        eta = self.eta()
        return text + (f", about {fmt_duration(eta)} left at the current pace" if eta else "")


FEATURE_MARKERS = {          # configure label -> a function the standard engine exports if it has it
    "WebChannel support": "setWebChannel@QWebEnginePage",
    "Spellchecker": "setSpellCheckEnabled@QWebEngineProfile",
    "Printing and PDF": "printToPdf@QWebEnginePage",
    "Extensions": "QWebEngineExtensionManager",
    "Geolocation": None,
}


def check_summary(summary, standard_exports=None):
    """Problems with the configure summary: codecs must be on, and no feature the browser's
    standard engine has (judged by its exported functions) may be off."""
    def flag(label):
        m = re.search(rf"^\s*{re.escape(label)}\s*\.+\s*(yes|no)\s*$", summary, re.M | re.I)
        return m.group(1).lower() if m else None
    problems = []
    codecs = re.search(r"^.*proprietary.*?\.{2,}\s*(yes|no)\s*$", summary, re.M | re.I)
    if not codecs or codecs.group(1).lower() != "yes":
        problems.append("proprietary codecs (H.264/AAC) are not enabled")
    for label, marker in FEATURE_MARKERS.items():
        if flag(label) != "no":
            continue
        if marker is None or standard_exports is None or any(marker in name for name in standard_exports):
            problems.append(f"{label} is off")
    return problems


EXPORT_LINE = re.compile(r"^\s+\d+\s+[0-9A-Fa-f]+\s+(?:[0-9A-Fa-f]{8,16}\s+)?([^\s=]+)(?:\s|$)")
IMPORT_DLL = re.compile(r"^\s{4}(\S+\.dll)\s*$", re.I)
IMPORT_NAME = re.compile(r"^\s+[0-9A-Fa-f]+\s+(\S+)\s*$")


def parse_exports(text):
    names, started = set(), False
    for line in text.splitlines():
        if re.match(r"^\s+ordinal\s+hint\s+RVA\s+name", line):
            started = True
            continue
        if started and line.strip().startswith("Summary"):
            break
        if started:
            m = EXPORT_LINE.match(line)
            if m:
                names.add(m.group(1))
    return names


def parse_imports(text):
    imports, current = {}, None
    for line in text.splitlines():
        m = IMPORT_DLL.match(line)
        if m:
            current = imports.setdefault(m.group(1).lower(), set())
            continue
        if line.strip().startswith("Summary"):
            current = None
            continue
        if current is not None:
            m = IMPORT_NAME.match(line)
            if m and not line.strip().startswith(("Import", "Index")):
                current.add(m.group(1))
    return imports


def dumpbin(path, flag, env):
    rc, out = capture([which("dumpbin", env), "/nologo", flag, path], env=env, timeout=600)
    if rc != 0:
        raise BuildError(f"dumpbin {flag} failed on {Path(path).name}", out[-2000:])
    return out


def install_plan(inst, pyside):
    """[(new file, destination in PySide6)] for the engine binaries, resources and locales."""
    inst, pyside = Path(inst), Path(pyside)
    plan = []
    bins = {p.name: p for p in inst.rglob("*") if p.name in ENGINE_BINARIES and p.is_file()}
    for name in ENGINE_BINARIES:
        if name in bins and (pyside / name).exists():
            plan.append((bins[name], pyside / name))
    resources = inst / "resources"
    if resources.is_dir():
        for p in resources.rglob("*"):
            if p.is_file():
                plan.append((p, pyside / "resources" / p.relative_to(resources)))
    locales = inst / "translations" / "qtwebengine_locales"
    if locales.is_dir():
        for p in locales.glob("*.pak"):
            plan.append((p, pyside / "translations" / "qtwebengine_locales" / p.name))
    return plan


def compatibility_problems(plan, pyside, exports_of, imports_of):
    """The browser's PySide modules and the untouched Qt files must still find every function
    they use, and the new engine must find everything it needs in the browser's Qt DLLs."""
    problems, cache = [], {}

    def exports(path):
        key = str(path).lower()
        if key not in cache:
            cache[key] = parse_exports(exports_of(path))
        return cache[key]

    new_by_name = {Path(dst).name.lower(): src for src, dst in plan}
    browser_files = {p.name.lower(): p for p in Path(pyside).iterdir()}   # Windows ignores case
    replaced = {str(Path(dst)).lower() for _, dst in plan}
    staying = [p for p in Path(pyside).rglob("*") if p.suffix.lower() in (".dll", ".pyd", ".exe")
               and p.is_file() and str(p).lower() not in replaced]
    users_cache = {}

    def imported_from(dll_name):
        """{file that stays: names it imports from dll_name} for the browser's own files."""
        if dll_name not in users_cache:
            users = {}
            for f in staying:
                key = "imports:" + str(f).lower()
                if key not in cache:
                    try:
                        cache[key] = parse_imports(imports_of(f))
                    except BuildError:
                        cache[key] = {}
                names = cache[key].get(dll_name)
                if names:
                    users[f] = names
            users_cache[dll_name] = users
        return users_cache[dll_name]

    for src, dst in plan:
        if Path(dst).suffix.lower() != ".dll" or not Path(dst).exists():
            continue
        missing = exports(dst) - exports(src)
        if not missing:
            continue
        # Removed functions only matter if a file that stays in place imports them. (Qt's
        # internal functions change between versions; the Qt files that use them are
        # replaced together with the engine.)
        for user, names in imported_from(Path(dst).name.lower()).items():
            used = names & missing
            if used:
                problems.append(f"{user.name} uses {len(used)} functions the new {Path(dst).name} lacks, "
                                f"e.g. {sorted(used)[:5]}")
    for src, dst in plan:
        if Path(dst).suffix.lower() not in (".dll", ".exe"):
            continue
        for dll, names in parse_imports(imports_of(src)).items():
            provider = new_by_name.get(dll)
            if provider is None:
                provider = browser_files.get(dll)
                if not dll.startswith("qt6") or provider is None:
                    continue                         # Windows' own DLLs
            missing = names - exports(provider)
            if missing:
                problems.append(f"{Path(src).name} needs {len(missing)} functions {dll} doesn't have, "
                                f"e.g. {sorted(missing)[:5]}")
    return problems


# ----------------------------------------------------------------------------- swapping

def file_in_use(path):
    """A DLL or EXE that a running program has loaded can't be opened for writing."""
    try:
        with open(path, "r+b"):
            return False
    except FileNotFoundError:
        return False
    except PermissionError:
        return True


def wait_until_closed(paths, poll=15, sleep=time.sleep):
    told = False
    while any(file_in_use(p) for p in paths):
        if not told:
            log(">>> Close Huginn (all its windows) so the new engine can be put in - "
                "this continues by itself once it's closed. <<<")
            set_status("WAITING", "Putting the new engine in", "Waiting for Huginn to be closed",
                       waiting_for="browser")
            told = True
        sleep(poll)


def copy_over(src, dst):
    dst = Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name(dst.name + ".sqtnew")
    shutil.copy2(src, tmp)
    os.replace(tmp, dst)


def wheel_files(pyside):
    """Paths (relative to PySide6/) that the PySide6 wheels installed, from their RECORD files."""
    files = set()
    for record in Path(pyside).parent.glob("[Pp]y[Ss]ide6*.dist-info/RECORD"):
        for line in record.read_text(encoding="utf-8", errors="replace").splitlines():
            path = line.split(",", 1)[0].replace("\\", "/")
            if path.startswith("PySide6/"):
                files.add(path[len("PySide6/"):])
    return files


def swap_in(plan, info, version, backup_dir=None, installed_file=None, pyside=None, sleep=time.sleep, extra=None):
    backup_dir = Path(backup_dir or BACKUP_DIR)
    installed_file = Path(installed_file or INSTALLED_FILE)
    pyside = Path(pyside or PYSIDE)
    core = pyside / "Qt6WebEngineCore.dll"
    wait_until_closed([core, pyside / "QtWebEngineProcess.exe"], sleep=sleep)
    installed = load_json(installed_file, {})
    ours = bool(installed) and core.exists() and installed.get("core_sha256") == file_sha256(core)
    manifest_path = backup_dir / "manifest.json"
    manifest = load_json(manifest_path, {})
    if not ours or manifest.get("wheel") != info.get("wheel"):
        # The current files are the standard ones from the PySide6 download: keep a copy.
        from_wheel = wheel_files(pyside)
        previously_added = set(manifest.get("added", []))
        remove_tree(backup_dir)
        files, added = [], []
        for _, dst in plan:
            rel = Path(dst).relative_to(pyside).as_posix()
            ours_before = rel not in from_wheel if from_wheel else rel in previously_added
            if Path(dst).exists() and not ours_before:
                target = backup_dir / "files" / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(dst, target)
                files.append(rel)
            else:
                added.append(rel)
        manifest = {"wheel": info.get("wheel"), "webengine": info.get("webengine"),
                    "chromium": info.get("chromium"), "files": files, "added": added,
                    "saved": time.strftime("%Y-%m-%d %H:%M:%S")}
        write_atomic(manifest_path, json.dumps(manifest, indent=2))
    else:
        known = set(manifest.get("files", [])) | set(manifest.get("added", []))
        for _, dst in plan:
            rel = Path(dst).relative_to(pyside).as_posix()
            if rel not in known:
                manifest.setdefault("added", []).append(rel)
        write_atomic(manifest_path, json.dumps(manifest, indent=2))
    try:
        for src, dst in plan:
            copy_over(src, dst)
    except OSError as e:
        restore_standard_engine("copying the new engine failed", backup_dir, installed_file, pyside, sleep,
                                force=True)
        raise BuildError("Couldn't copy the new engine in (is Huginn still open?) - the standard engine "
                         "was put back; run again to retry.", str(e))
    record = {"webengine": version, "qt": info.get("qt"), "wheel": info.get("wheel"), "codecs": "H.264/AAC",
              "core_sha256": file_sha256(core), "core_size": core.stat().st_size,
              "core_mtime": core.stat().st_mtime, "installed": time.strftime("%Y-%m-%d %H:%M:%S")}
    record.update(extra or {})
    write_atomic(installed_file, json.dumps(record, indent=2))


def built_engine_in_place(installed_file=None, pyside=None):
    """Whether the engine this builder put in is still there (not rolled back or replaced)."""
    installed = load_json(Path(installed_file or INSTALLED_FILE), {})
    core = Path(pyside or PYSIDE) / "Qt6WebEngineCore.dll"
    return bool(installed) and core.exists() and installed.get("core_sha256") == file_sha256(core)


def restore_standard_engine(reason="", backup_dir=None, installed_file=None, pyside=None, sleep=time.sleep,
                            force=False):
    """force: put the saved files back even though installed.json says nothing is installed
    (used when a swap fails half way)."""
    backup_dir = Path(backup_dir or BACKUP_DIR)
    installed_file = Path(installed_file or INSTALLED_FILE)
    pyside = Path(pyside or PYSIDE)
    manifest = load_json(backup_dir / "manifest.json", {})
    installed = load_json(installed_file, {})
    core = pyside / "Qt6WebEngineCore.dll"
    if not force and (not installed or not core.exists() or installed.get("core_sha256") != file_sha256(core)):
        installed_file.unlink(missing_ok=True)
        return "The standard engine is already in place."
    if not manifest.get("files"):
        raise BuildError("No saved copy of the standard engine was found - run setup.bat to reinstall PySide6.")
    log(f"Putting the standard engine back ({reason})" if reason else "Putting the standard engine back")
    wait_until_closed([core, pyside / "QtWebEngineProcess.exe"], sleep=sleep)
    for rel in manifest["files"]:
        copy_over(backup_dir / "files" / rel, pyside / rel)
    for rel in manifest.get("added", []):
        (pyside / rel).unlink(missing_ok=True)
    installed_file.unlink(missing_ok=True)
    return f"Standard engine restored (Qt WebEngine {manifest.get('webengine')})."


def run_codec_check(out_file):
    rc, lines = run([PYEXE, CODEC_CHECK], cwd=APP, timeout=300, logfile=out_file)
    for line in reversed(lines):
        if line.startswith("CODEC_RESULT "):
            try:
                return json.loads(line[len("CODEC_RESULT "):])
            except ValueError:
                break
    return {"ok": False, "summary": f"the check didn't finish (exit {rc})", "tail": lines[-30:]}


# ----------------------------------------------------------------------------- entry point

def main(argv=None):
    parser = argparse.ArgumentParser(description="Build Huginn's engine with H.264/AAC video support.")
    parser.add_argument("--restore", action="store_true", help="put the standard engine back")
    parser.add_argument("--force", action="store_true", help="rebuild even when up to date")
    parser.add_argument("--keep-build", action="store_true", help="keep the 25+ GB build folder afterwards")
    parser.add_argument("--check-only", action="store_true",
                        help="only check whether a newer engine is out (writes update-check.json)")
    parser.add_argument("--relaunch", action="store_true",
                        help="(always on now) reopen the browser if it closed itself for the swap")
    args = parser.parse_args(argv)
    if args.check_only:
        return Builder(args).check_only()
    if not acquire_lock():
        print("The engine builder is already running.", flush=True)
        return 0
    try:
        return run_builder(args)
    finally:
        release_lock()
        relaunch_browser()                      # a no-op unless 'Restart to finish' closed it


def run_builder(args):
    ERROR_FILE.unlink(missing_ok=True)
    try:
        if args.restore:
            message = restore_standard_engine("you asked for it")
            log(message)
            set_status("DONE", "restored", message)
            return 0
        return Builder(args).run_all()
    except BuildError as e:
        log(f"\nSTOPPED: {e}")
        if e.details:
            log("  details are in engine\\last-error.txt", console=True)
        ERROR_FILE.write_text(f"{e}\n\n{e.details}\n", encoding="utf-8")
        set_status("FAILED", str(e), "details: engine\\last-error.txt. Run build-engine.bat again to continue.",
                   error=str(e))
        return 1
    except KeyboardInterrupt:
        log("\nStopped. Run build-engine.bat again to continue where it left off.")
        set_status("FAILED", "stopped by the user", "Run build-engine.bat again to continue.")
        return 1
    except Exception as e:                                # unexpected: keep the traceback
        import traceback
        details = traceback.format_exc()
        log(f"\nSTOPPED (unexpected problem): {e}")
        ERROR_FILE.write_text(details, encoding="utf-8")
        set_status("FAILED", f"unexpected problem: {e}", "details: engine\\last-error.txt",
                   error=f"unexpected problem: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
