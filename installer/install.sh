#!/usr/bin/env bash
# Huginn's installer for macOS and Linux (Windows uses Install Huginn.bat).
#   macOS: "Install Huginn (Mac).command" runs this. It makes Huginn.app in Applications
#          (Launchpad, Spotlight, Finder) and can keep it in the Dock.
#   Linux: "Install Huginn (Linux).sh" runs this. It puts Huginn in your apps menu, and can add it
#          to the desktop and (GNOME) pin it to the dock.
# It installs for you only, no administrator password: Huginn and its own Python go in one
# folder. Options: --yes (no questions), --no-desktop, --no-dock, --no-open, --uninstall.
# Linux, for every user (e.g. a distribution's image): sudo ... --system [--default] puts
# Huginn in /opt/huginn with /usr/bin/huginn, the apps menu entry and icons under /usr/share,
# and registers it as a web browser (--default: the system's default one). --root=DIR does
# the same into DIR for packaging (see build-deb.sh), touching nothing outside it.
# --system-engine (Linux): no Python or engine of its own - Huginn runs on the distribution's
# python3 and PySide6 (Ubuntu 25.04+ / Debian 13+), which play H.264 video and get the
# engine's security fixes with the system's updates.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE="$(cd "$HERE/.." && pwd)"
OS="$(uname -s)"
ARCH="$(uname -m)"
ASK=1; DESKTOP=1; DOCK=1; UNINSTALL=0; OPEN=1; SYSTEM=0; ROOT=""; MAKE_DEFAULT=0; SYS_ENGINE=0
for arg in "$@"; do
  case "$arg" in
    --yes|-y) ASK=0 ;;
    --no-desktop) DESKTOP=0 ;;
    --no-dock) DOCK=0 ;;
    --no-open) OPEN=0 ;;
    --uninstall) UNINSTALL=1 ;;
    --system) SYSTEM=1 ;;
    --default) MAKE_DEFAULT=1 ;;
    --root=*) ROOT="${arg#--root=}"; SYSTEM=1 ;;
    --system-engine) SYS_ENGINE=1 ;;
    *) echo "Unknown option: $arg"; exit 2 ;;
  esac
done
if [ "$SYSTEM" = 1 ]; then
  [ "$OS" = Linux ] || { echo "--system is for Linux."; exit 2; }
  ASK=0; DESKTOP=0; DOCK=0; OPEN=0                 # for every user: no per-user desktop or dock changes
  if [ -z "$ROOT" ] && [ "$(id -u)" != 0 ]; then
    echo "A system-wide install needs administrator rights: sudo \"$0\" $*"; exit 1
  fi
  [ -z "$ROOT" ] || { mkdir -p "$ROOT" && ROOT="$(cd "$ROOT" && pwd)"; }
fi
[ "$SYS_ENGINE" = 0 ] || [ "$OS" = Linux ] || { echo "--system-engine is for Linux."; exit 2; }
# The distribution's packages Huginn runs on with --system-engine (Ubuntu / Debian names).
ENGINE_PACKAGES="python3-pyside6.qtwebenginewidgets python3-pyside6.qtmultimedia python3-pyside6.qttexttospeech python3-pyside6.qtsvg python3-cryptography qt6-qpa-plugins"
[ -t 0 ] || ASK=0                                  # no terminal to answer in: take the defaults
# On a Mac it's double-clicked like any installer, so it asks nothing: Huginn goes in Applications
# and the Dock (--no-dock to skip that) and opens when it's ready.
[ "$OS" = Darwin ] && ASK=0

# ------------------------------------------------------------------------------------- look
if [ -t 1 ]; then
  B=$'\033[1m'; D=$'\033[2m'; A=$'\033[38;5;79m'; R=$'\033[38;5;203m'; N=$'\033[0m'
else
  B=""; D=""; A=""; R=""; N=""
fi
if [ "$OS" = Darwin ]; then                        # a copy of what it said, for when something goes wrong
  LOGS="$HOME/Library/Logs/Huginn"
  mkdir -p "$LOGS" 2>/dev/null && exec > >(tee "$LOGS/$([ "$UNINSTALL" = 1 ] && echo uninstall || echo install).log") 2>&1
fi
say()  { printf '%s\n' "$*"; }
step() { printf '  %s•%s %s\n' "$A" "$N" "$*"; }
done_() { printf '  %s✓%s %s\n' "$A" "$N" "$*"; }
fail() { printf '\n  %s✗ %s%s\n\n' "$R" "$*" "$N"; finish 1; }
ask() {                                            # ask "Question" default(y/n) -> 0 for yes
  local q="$1" def="$2" reply
  if [ "$ASK" = 0 ]; then [ "$def" = y ]; return; fi
  if [ "$def" = y ]; then printf '  %s [Y/n] ' "$q"; else printf '  %s [y/N] ' "$q"; fi
  read -r reply || reply=""
  reply="$(printf '%s' "$reply" | tr '[:upper:]' '[:lower:]')"
  if [ -z "$reply" ]; then [ "$def" = y ]; else [ "${reply:0:1}" = y ]; fi
}
finish() {                                         # a failed .command keeps its window open to read
  local code="${1:-0}"
  if [ "$OS" = Darwin ] && [ "$code" != 0 ] && [ -t 0 ] && [ "${HUGINN_NO_PAUSE:-}" = "" ]; then
    printf '\n  %sPress Return to close this window.%s' "$D" "$N"; read -r _ || true
  fi
  exit "$code"
}
banner() {
  say ""
  say "  ${A}ᚺ ᚢ ᚷ ᛁ ᚾ ᚾ${N}"
  say "  ${B}$1${N}"
  say "  ${D}$2${N}"
  say ""
}

# ------------------------------------------------------------------------------------- where
DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
if [ "$OS" = Darwin ]; then
  if [ -w /Applications ]; then APPS=/Applications; else APPS="$HOME/Applications"; fi
  BUNDLE="${HUGINN_BUNDLE:-$APPS/Huginn.app}"
  TARGET="$BUNDLE/Contents/Resources/huginn"
  VENV="$BUNDLE/Contents/Resources/python"
elif [ "$OS" = Linux ] && [ "$SYSTEM" = 1 ]; then
  TARGET="${HUGINN_TARGET:-/opt/huginn}"
  VENV="$TARGET/.python"
  LAUNCHER="/usr/bin/huginn"
  ENTRY="/usr/share/applications/huginn.desktop"
  ICONS="/usr/share/icons/hicolor"
elif [ "$OS" = Linux ]; then
  TARGET="${HUGINN_TARGET:-$DATA_HOME/huginn}"
  VENV="$TARGET/.python"
  LAUNCHER="$HOME/.local/bin/huginn"
  ENTRY="$DATA_HOME/applications/huginn.desktop"
  ICONS="$DATA_HOME/icons/hicolor"
else
  echo "Huginn's installer knows macOS and Linux; on Windows, run Install Huginn.bat."; exit 1
fi

W="$ROOT"                                          # files are written under W; their contents name the real paths
system_hooks() { [ "$SYSTEM" = 1 ] && [ -z "$ROOT" ]; }   # refresh the system's menus, icons, alternatives

# Ubuntu 23.10+ lets a program make the user namespaces Chromium's page sandbox is built from
# only when an AppArmor profile allows it. The namespace is made by the browser's own process
# (not by QtWebEngineProcess), so the profile has to cover the `huginn` command itself; without
# it the engine stops at once ("credentials.cc: Permission denied"). AppArmor attaches a profile
# by a program's path, which is why the launcher is a Python script run through its "#!" line
# and not a shell script that starts Python.
apparmor_profile() {
  local where="$LAUNCHER"
  [ "$SYSTEM" = 1 ] || where='/{usr/bin,home/*/.local/bin}/huginn'   # whoever installs it for themselves
  cat <<PROFILE
# Huginn's web engine (Chromium) builds its page sandbox from user namespaces, which
# Ubuntu 23.10 and later allow only to programs whose AppArmor profile says so.
abi <abi/4.0>,
include <tunables/global>

profile huginn $where flags=(unconfined) {
  userns,

  # Site-specific additions and overrides.
  include if exists <local/huginn>
}
PROFILE
}
userns_restricted() { [ "$(cat /proc/sys/kernel/apparmor_restrict_unprivileged_userns 2>/dev/null)" = 1 ]; }

desktop_folder() {
  local d=""
  command -v xdg-user-dir >/dev/null 2>&1 && d="$(xdg-user-dir DESKTOP 2>/dev/null || true)"
  [ -n "$d" ] && [ "$d" != "$HOME" ] || d="$HOME/Desktop"
  printf '%s' "$d"
}

# ------------------------------------------------------------------------------------- remove
if [ "$UNINSTALL" = 1 ]; then
  banner "Remove Huginn" "Huginn and its own Python go; your bookmarks, history and passwords stay unless you say otherwise."
  pkill -f "$TARGET/safari_browser.py" 2>/dev/null || true            # started as a script (older launchers)
  pkill -f "$VENV/bin/python -c import os, sys; sys.path.insert" 2>/dev/null || true   # this installer's launcher
  [ "$SYS_ENGINE" = 0 ] || pkill -f "import safari_browser; sys.exit(safari_browser.main())" 2>/dev/null || true
  pkill -f "^[^ ]*python[^ ]*( -[^ ]+)* $LAUNCHER( |\$)" 2>/dev/null || true   # this installer's launcher (a Python script)
  if [ "$SYSTEM" = 1 ]; then                     # for every user: the program goes, people's own data stays
    rm -rf "$W$TARGET" "$W$LAUNCHER" "$W$ENTRY"
    find "$W$ICONS" -name huginn.png -delete 2>/dev/null || true
    if system_hooks && [ -f /etc/apparmor.d/huginn ]; then
      command -v apparmor_parser >/dev/null 2>&1 && apparmor_parser -R /etc/apparmor.d/huginn >/dev/null 2>&1 || true
      rm -f /etc/apparmor.d/huginn
    fi
    if system_hooks; then
      for alt in x-www-browser gnome-www-browser; do
        command -v update-alternatives >/dev/null 2>&1 && update-alternatives --remove "$alt" "$LAUNCHER" >/dev/null 2>&1 || true
      done
      [ -f /etc/xdg/mimeapps.list ] && sed -i '/=huginn\.desktop;*$/d' /etc/xdg/mimeapps.list 2>/dev/null || true
      command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database /usr/share/applications 2>/dev/null || true
      command -v gtk-update-icon-cache >/dev/null 2>&1 && gtk-update-icon-cache -q -t "$ICONS" 2>/dev/null || true
    fi
    done_ "Removed Huginn for every user (each person's bookmarks and settings stay in their home folder)"
    say ""; finish 0
  fi
  if [ "$OS" = Darwin ]; then
    rm -rf "$BUNDLE" && done_ "Removed $BUNDLE"
    say "  ${D}If Huginn was in your Dock, drag it out (it shows a question mark now).${N}"
    DATA="$HOME/Library/Application Support/SafariQt"; PREFS="$HOME/Library/Preferences/com.safariqt.SafariQt.plist"
  else
    rm -rf "$TARGET" "$LAUNCHER" "$ENTRY" "$(desktop_folder)/huginn.desktop"
    find "$ICONS" -name huginn.png -delete 2>/dev/null || true
    if command -v gsettings >/dev/null 2>&1 && gsettings get org.gnome.shell favorite-apps >/dev/null 2>&1; then
      favs="$(gsettings get org.gnome.shell favorite-apps | sed "s/, 'huginn.desktop'//; s/'huginn.desktop', //; s/'huginn.desktop'//")"
      gsettings set org.gnome.shell favorite-apps "$favs" 2>/dev/null || true
    fi
    command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$DATA_HOME/applications" 2>/dev/null || true
    done_ "Removed Huginn, its launcher and menu entry"
    DATA="$DATA_HOME/SafariQt"; PREFS="${XDG_CONFIG_HOME:-$HOME/.config}/SafariQt"
  fi
  if ask "Also remove your bookmarks, history, passwords and settings?" n; then
    if [ -d "$DATA" ]; then                       # the key that signs updates you share is kept
      find "$DATA" -mindepth 1 -maxdepth 1 ! -name release-key.pem -exec rm -rf {} + 2>/dev/null || true
    fi
    rm -rf "$PREFS"
    done_ "Removed your Huginn data"
  else
    say "  ${D}Your bookmarks, history, passwords and settings were kept.${N}"
  fi
  say ""; say "  ${B}Huginn has been removed.${N} Thanks for flying with the ravens."; say ""
  finish 0
fi

# ------------------------------------------------------------------------------------- install
[ -f "$SOURCE/safari_browser.py" ] || fail "Unzip the whole Huginn folder first, then run this again."
if [ "$OS" = Darwin ]; then
  banner "Install Huginn" "A quiet, private browser, named for Odin's raven of thought. It goes in $APPS as Huginn.app."
elif [ "$SYSTEM" = 1 ]; then
  banner "Install Huginn for everyone" "A quiet, private browser, named for Odin's raven of thought. It goes in $W$TARGET."
else
  banner "Install Huginn" "A quiet, private browser, named for Odin's raven of thought. It goes in your apps menu."
fi
if [ "$SYS_ENGINE" = 1 ]; then
  say "  ${D}It runs on this system's Python and browser engine, so it takes a moment.${N}"
else
  say "  ${D}Takes a few minutes: it fetches its own Python and the browser engine (a few hundred MB).${N}"
fi
if [ "$SYSTEM" = 1 ]; then
  say "  ${D}For every user of this computer; the system's package manager or this script updates it.${N}"
else
  say "  ${D}For you only, no administrator password. Remove it any time (see README.txt).${N}"
fi
say ""
if [ "$OS" = Darwin ]; then
  ask "Keep Huginn in the Dock?" y || DOCK=0
else
  ask "Add Huginn to the desktop?" y || DESKTOP=0
  if command -v gsettings >/dev/null 2>&1 && gsettings get org.gnome.shell favorite-apps >/dev/null 2>&1; then
    ask "Pin Huginn to the dock?" y || DOCK=0
  else
    DOCK=0
  fi
fi
say ""

# 1. Huginn's files (not anything a copy of Huginn made while running)
step "Copying Huginn"
mkdir -p "$W$TARGET"
chmod -R u+w "$W$TARGET" 2>/dev/null || true       # installing again: some files came read-only
if [ "$(cd "$SOURCE" && pwd -P)" != "$(cd "$W$TARGET" && pwd -P)" ]; then
  (cd "$SOURCE" && tar cf - --exclude=./python --exclude='./.python' --exclude='__pycache__' --exclude=./test_out \
      --exclude=./engine/standard-engine --exclude='*.log' --exclude=./engine/installed.json \
      --exclude=./engine/state.json --exclude=./engine/status.json --exclude=./engine/status.txt \
      --exclude=./engine/build-log.txt --exclude=./engine/builder.pid --exclude=./engine/restart.json \
      --exclude=./engine/last-error.txt --exclude=./engine/update-check.json --exclude=./.git .) \
    | (cd "$W$TARGET" && tar xf -) || fail "Copying failed."
fi
chmod +x "$W$TARGET/installer/install.sh" 2>/dev/null || true
if [ "$SYSTEM" = 1 ]; then                         # a program for everyone: no publisher files or test leftovers,
  rm -f "$W$TARGET/update.json" "$W$TARGET/release-key.pem"   # nor what only Windows or developers use
  rm -rf "$W$TARGET/test_out" "$W$TARGET/docs"
  rm -f "$W$TARGET"/{.gitattributes,.gitignore,README.md,run.bat,setup.bat,build-engine.bat,restore-engine.bat} \
        "$W$TARGET"/Install\ Huginn* "$W$TARGET"/*_test.py "$W$TARGET/installer/install.ps1" \
        "$W$TARGET"/engine/{build_engine.py,codec_check.py,codec_test.mp4,gnu_tools.zip}
fi
done_ "Copied Huginn"

if [ "$SYS_ENGINE" = 1 ]; then
  # 2-3. The distribution's Python and engine (its packages bring every library they need).
  step "Checking the system's browser engine"
  PY="${HUGINN_PYTHON:-$(command -v python3 || true)}"
  [ -n "$PY" ] && "$PY" -c "import PySide6.QtWebEngineWidgets, PySide6.QtMultimedia, PySide6.QtTextToSpeech, PySide6.QtSvg, cryptography" 2>/dev/null \
    || fail "The system's browser engine isn't installed. On Ubuntu 25.04+ or Debian 13+: sudo apt install $ENGINE_PACKAGES"
  TOOLPY="$PY"
  RUNPY="$PY"
  [ -z "$ROOT" ] || RUNPY=/usr/bin/python3          # a package runs on the system's python3
  rm -rf "${W:?}$VENV"                               # an earlier install's own engine isn't used any more
  done_ "Using the system's engine (PySide6 $("$PY" -c 'import PySide6; print(PySide6.__version__)'))"
else
  # 2. Python of its own: the system's on Linux when it's new enough, else one fetched by uv
  #    (Astral's Python manager, a single file, kept in the install folder).
  step "Getting Python"
  PY=""
  if [ -n "${HUGINN_PYTHON:-}" ]; then
    PY="$HUGINN_PYTHON"
  elif [ "$OS" = Linux ] && command -v python3 >/dev/null 2>&1 \
       && python3 -c 'import sys, venv, ensurepip; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
    PY="$(command -v python3)"
  fi
  UV=""
  if [ -z "$PY" ] && [ -n "$ROOT" ]; then              # a package's Python must be the system's own
    fail "Packaging needs the system's Python 3.10 or newer with venv (Debian/Ubuntu: apt install python3-venv)."
  fi
  if [ -z "$PY" ]; then
    case "$OS-$ARCH" in
      Darwin-arm64) UVA=aarch64-apple-darwin ;;
      Darwin-x86_64) UVA=x86_64-apple-darwin ;;
      Linux-x86_64) UVA=x86_64-unknown-linux-gnu ;;
      Linux-aarch64) UVA=aarch64-unknown-linux-gnu ;;
      *) fail "No ready-made Python for $OS on $ARCH. Install Python 3.10 or newer, then run this again." ;;
    esac
    mkdir -p "$W$TARGET/.tools"
    curl -fsSL "https://github.com/astral-sh/uv/releases/latest/download/uv-$UVA.tar.gz" -o "$W$TARGET/.tools/uv.tar.gz" \
      || fail "Couldn't download what Huginn needs. Check the internet connection, then try again."
    tar xzf "$W$TARGET/.tools/uv.tar.gz" -C "$W$TARGET/.tools" --strip-components 1 && rm -f "$W$TARGET/.tools/uv.tar.gz"
    UV="$W$TARGET/.tools/uv"
    export UV_PYTHON_INSTALL_DIR="$W$TARGET/.tools/python"
    "$UV" python install 3.12 --quiet || fail "Couldn't get Python. Check the internet connection, then try again."
    "$UV" venv --quiet --allow-existing --python 3.12 "$W$VENV" || fail "Couldn't set up Python."
  else
    "$PY" -m venv "$W$VENV" || fail "Couldn't set up Python (on Debian/Ubuntu: sudo apt install python3-venv)."
  fi
  done_ "Python ready"

  # 3. The browser engine (PySide6 / Qt WebEngine) and the password manager's encryption library
  step "Getting the browser engine (a few hundred MB)"
  if [ -n "$UV" ]; then
    "$UV" pip install --python "$W$VENV/bin/python" --upgrade PySide6 cryptography \
      || fail "Couldn't download the browser engine. Check the internet connection, then try again."
  else
    "$W$VENV/bin/python" -m pip install --disable-pip-version-check --quiet --upgrade pip >/dev/null 2>&1 || true
    "$W$VENV/bin/python" -m pip install --disable-pip-version-check --upgrade PySide6 cryptography \
      || fail "Couldn't download the browser engine. Check the internet connection, then try again."
  fi
  "$W$VENV/bin/python" -c "import PySide6.QtWebEngineWidgets, cryptography" 2>/dev/null \
    || fail "The browser engine didn't start. On Linux it may need your desktop's graphics libraries (libnss3, libxkbcommon)."
  "$W$VENV/bin/python" -m compileall -q "$W$TARGET/safari_browser.py" >/dev/null 2>&1 || true   # starts ~0.2 s sooner
  done_ "Browser engine ready"
  TOOLPY="$W$VENV/bin/python"
  RUNPY="$VENV/bin/python"
fi

# Linux: the engine imports fine without them, but Qt can't open a window on an X11 desktop
# when a system library its X11 plugin uses is missing (since Qt 6.5 that's usually
# libxcb-cursor0, which some distributions leave out). Say which, and how to add them.
MISSING_LIBS=""
if [ "$OS" = Linux ] && [ "$SYS_ENGINE" = 0 ] && command -v ldd >/dev/null 2>&1; then
  QTDIR="$("$TOOLPY" -c 'import PySide6, os; print(os.path.join(os.path.dirname(PySide6.__file__), "Qt"))' 2>/dev/null || true)"
  for lib in "$QTDIR/plugins/platforms/libqxcb.so" "$QTDIR/lib/libQt6XcbQpa.so.6" "$QTDIR/lib/libQt6WebEngineCore.so.6"; do
    [ -f "$lib" ] && MISSING_LIBS="$MISSING_LIBS $(ldd "$lib" 2>/dev/null | awk '/not found/ {print $1}')"
  done
  MISSING_LIBS="$(printf '%s\n' $MISSING_LIBS | sort -u | tr '\n' ' ' | sed 's/^ *//; s/ *$//')"
fi
if [ -n "$MISSING_LIBS" ]; then
  FIX=""
  if command -v apt-get >/dev/null 2>&1; then       # libxcb-cursor.so.0 -> libxcb-cursor0, libxkbcommon-x11.so.0 -> libxkbcommon-x11-0
    PKGS="$(printf '%s\n' $MISSING_LIBS | sed -E 's/\.so(\.([0-9]+))?.*$/ \2/; s/([0-9]) ([0-9]+)$/\1-\2/; s/ //' | tr '\n' ' ')"
    FIX="sudo apt-get install -y $PKGS"
  elif command -v dnf >/dev/null 2>&1; then FIX="sudo dnf install -y xcb-util-cursor xcb-util-wm xcb-util-image xcb-util-keysyms xcb-util-renderutil libxkbcommon-x11"
  elif command -v pacman >/dev/null 2>&1; then FIX="sudo pacman -S --needed xcb-util-cursor xcb-util-wm xcb-util-image xcb-util-keysyms xcb-util-renderutil libxkbcommon-x11"
  elif command -v zypper >/dev/null 2>&1; then FIX="sudo zypper install libxcb-cursor0 libxcb-icccm4 libxcb-image0 libxcb-keysyms1 libxcb-render-util0 libxkbcommon-x11-0"
  fi
  say ""
  say "  ${B}One more thing:${N} on an X11 desktop Huginn's window needs system libraries that aren't installed:"
  say "  ${D}$MISSING_LIBS${N}"
  if [ -n "$FIX" ] && [ "$ASK" = 1 ] && [ -t 0 ] && ask "Install them now? (runs: $FIX - asks for your password)" y; then
    # shellcheck disable=SC2086
    if $FIX; then MISSING_LIBS=""; done_ "System libraries installed"; else say "  ${D}That didn't work; you can run it yourself later.${N}"; fi
  elif [ -n "$FIX" ]; then
    say "  ${D}Add them with:  $FIX${N}"
  fi
  [ -n "$MISSING_LIBS" ] && say "  ${D}(On a Wayland desktop Huginn opens without them.)${N}"
  say ""
fi

# 4. Into the system: an app bundle on macOS, a launcher and menu entry on Linux
step "Adding Huginn to your apps"
ICONDIR="$(mktemp -d)"
QT_QPA_PLATFORM=offscreen "$TOOLPY" "$W$TARGET/safari_browser.py" --export-icon "$ICONDIR" >/dev/null 2>&1 || true
VERSION="$(head -n1 "$W$TARGET/version.txt" 2>/dev/null | tr -d '\r' || true)"; VERSION="${VERSION:-1.0}"
if [ "$OS" = Darwin ]; then
  mkdir -p "$BUNDLE/Contents/MacOS" "$BUNDLE/Contents/Resources"
  cat > "$BUNDLE/Contents/MacOS/Huginn" <<'LAUNCH'
#!/bin/bash
# Starts Huginn with the Python inside this app. CFProcessPath tells macOS this Python is
# Huginn.app (its name in the menu bar, its icon and place in the Dock, its permissions).
HERE="$(cd "$(dirname "$0")/../Resources" && pwd)"
export CFProcessPath="$(cd "$(dirname "$0")" && pwd)/Huginn"
LOGS="$HOME/Library/Logs/Huginn"
mkdir -p "$LOGS" 2>/dev/null || LOGS=/dev
# Imported rather than run as a script, so Python uses its compiled copy (about 0.2 s sooner).
# Its folder goes in the environment, not the arguments: macOS would treat a path argument as
# a document to open.
export HUGINN_DIR="$HERE/huginn"
exec "$HERE/python/bin/python" -c 'import os, sys; sys.path.insert(0, os.environ.pop("HUGINN_DIR")); import safari_browser; sys.exit(safari_browser.main())' \
  "$@" >"$LOGS/huginn.log" 2>&1
LAUNCH
  chmod +x "$BUNDLE/Contents/MacOS/Huginn"
  cat > "$BUNDLE/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>Huginn</string>
  <key>CFBundleDisplayName</key><string>Huginn</string>
  <key>CFBundleIdentifier</key><string>io.github.valkyrii070.huginn</string>
  <key>CFBundleExecutable</key><string>Huginn</string>
  <key>CFBundleIconFile</key><string>Huginn</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>$VERSION</string>
  <key>CFBundleVersion</key><string>$VERSION</string>
  <key>LSMinimumSystemVersion</key><string>11.0</string>
  <key>NSHighResolutionCapable</key><true/>
  <key>NSSupportsAutomaticGraphicsSwitching</key><true/>
  <key>NSCameraUsageDescription</key><string>A website you're on wants to use your camera.</string>
  <key>NSMicrophoneUsageDescription</key><string>A website you're on wants to use your microphone.</string>
  <key>NSLocationWhenInUseUsageDescription</key><string>A website you're on wants to know where you are.</string>
  <key>LSApplicationCategoryType</key><string>public.app-category.productivity</string>
  <key>CFBundleURLTypes</key>
  <array><dict>
    <key>CFBundleURLName</key><string>Web site URL</string>
    <key>CFBundleURLSchemes</key><array><string>http</string><string>https</string></array>
  </dict></array>
  <key>CFBundleDocumentTypes</key>
  <array><dict>
    <key>CFBundleTypeName</key><string>HTML document</string>
    <key>CFBundleTypeRole</key><string>Viewer</string>
    <key>LSItemContentTypes</key><array><string>public.html</string><string>public.xhtml</string></array>
  </dict></array>
</dict>
</plist>
PLIST
  if command -v iconutil >/dev/null 2>&1 && [ -f "$ICONDIR/huginn-1024.png" ]; then
    SET="$ICONDIR/Huginn.iconset"; mkdir -p "$SET"
    for s in 16 32 128 256 512; do
      cp "$ICONDIR/huginn-$s.png" "$SET/icon_${s}x${s}.png"
      cp "$ICONDIR/huginn-$((s * 2)).png" "$SET/icon_${s}x${s}@2x.png" 2>/dev/null || true
    done
    iconutil -c icns "$SET" -o "$BUNDLE/Contents/Resources/Huginn.icns" 2>/dev/null || true
  fi
  xattr -dr com.apple.quarantine "$BUNDLE" 2>/dev/null || true      # it's yours now: no "downloaded" warning
  # No lsregister -f or touch here: macOS registers the app by itself when it first opens
  # (just below), and forcing it made that first window wait about 12 seconds.
  done_ "Huginn.app is in $APPS (Launchpad and Spotlight too)"
  if [ "$DOCK" = 1 ]; then
    if ! defaults read com.apple.dock persistent-apps 2>/dev/null | grep -q "$BUNDLE"; then
      defaults write com.apple.dock persistent-apps -array-add \
        "<dict><key>tile-data</key><dict><key>file-data</key><dict><key>_CFURLString</key><string>$BUNDLE</string><key>_CFURLStringType</key><integer>0</integer></dict></dict></dict>"
      killall Dock 2>/dev/null || true
    fi
    done_ "Kept in the Dock"
  fi
else
  mkdir -p "$(dirname "$W$LAUNCHER")" "$(dirname "$W$ENTRY")"
  case "$RUNPY" in *[[:space:]]*) SCRIPT_LAUNCHER=0 ;; *) [ "${#RUNPY}" -le 120 ] && SCRIPT_LAUNCHER=1 || SCRIPT_LAUNCHER=0 ;; esac
  if [ "$SCRIPT_LAUNCHER" = 1 ]; then
    # A Python script, not a shell script that starts Python: the AppArmor profile that lets
    # the page sandbox work is attached to this file's path (see apparmor_profile above).
    # -I: Python takes no code from the environment (PYTHONPATH and the like) or from the
    # folder it's started in, so nothing else can borrow this command's profile.
    cat > "$W$LAUNCHER" <<LAUNCH
#!$RUNPY -I
# Starts Huginn (installed in $TARGET).
# Imported rather than run as a script, so Python uses its compiled copy (about 0.2 s sooner).
import sys

sys.path.insert(0, "$TARGET")
sys.argv[0] = "huginn"
import safari_browser  # noqa: E402

sys.exit(safari_browser.main())
LAUNCH
  else                                               # a "#!" line can't hold this path: pages run unsandboxed on Ubuntu
    cat > "$W$LAUNCHER" <<LAUNCH
#!/bin/sh
# Starts Huginn (installed in $TARGET).
# Imported rather than run as a script, so Python uses its compiled copy (about 0.2 s sooner).
export HUGINN_DIR="$TARGET"
exec "$RUNPY" -c 'import os, sys; sys.path.insert(0, os.environ.pop("HUGINN_DIR")); import safari_browser; sys.exit(safari_browser.main())' \
  "\$@"
LAUNCH
  fi
  chmod 755 "$W$LAUNCHER"
  for s in 16 32 48 64 128 256 512; do
    if [ -f "$ICONDIR/huginn-$s.png" ]; then
      mkdir -p "$W$ICONS/${s}x${s}/apps" && cp "$ICONDIR/huginn-$s.png" "$W$ICONS/${s}x${s}/apps/huginn.png"
    fi
  done
  cat > "$W$ENTRY" <<DESKTOP
[Desktop Entry]
Type=Application
Version=1.0
Name=Huginn
GenericName=Web Browser
Comment=A quiet, private browser
Exec=$LAUNCHER %U
Icon=huginn
Terminal=false
StartupNotify=true
StartupWMClass=huginn
Categories=Network;WebBrowser;
MimeType=text/html;application/xhtml+xml;application/xml;text/xml;image/svg+xml;x-scheme-handler/http;x-scheme-handler/https;x-scheme-handler/about;x-scheme-handler/unknown;
Keywords=browser;web;internet;private;huginn;
Actions=new-tab;new-private-window;

[Desktop Action new-tab]
Name=New Tab
Exec=$LAUNCHER --new-tab

[Desktop Action new-private-window]
Name=New Private Window
Exec=$LAUNCHER --private-window
DESKTOP
  chmod 644 "$W$ENTRY"
  if [ "$SYSTEM" = 1 ]; then                       # the page sandbox's AppArmor profile (Ubuntu 23.10+)
    if system_hooks && grep -qs huginn-webengine /etc/apparmor.d/huginn && command -v apparmor_parser >/dev/null 2>&1; then
      apparmor_parser -R /etc/apparmor.d/huginn >/dev/null 2>&1 || true      # an older Huginn's profile, named differently
    fi
    mkdir -p "$W/etc/apparmor.d" && apparmor_profile > "$W/etc/apparmor.d/huginn" && chmod 644 "$W/etc/apparmor.d/huginn"
    if system_hooks && command -v apparmor_parser >/dev/null 2>&1 && [ -d /sys/kernel/security/apparmor ]; then
      apparmor_parser -r -W /etc/apparmor.d/huginn >/dev/null 2>&1 || true
    fi
  elif userns_restricted && ! grep -qs '^profile huginn .*local/bin' /etc/apparmor.d/huginn && command -v apparmor_parser >/dev/null 2>&1; then
    say ""
    say "  ${B}One more thing:${N} Ubuntu runs a browser's page sandbox only with a small security profile for it."
    PROFILE_TMP="$(mktemp)"; apparmor_profile > "$PROFILE_TMP"
    if [ "$ASK" = 1 ] && [ -t 0 ] && ask "Add Huginn's profile now? (copies it to /etc/apparmor.d - asks for your password)" y \
       && { ! grep -qs huginn-webengine /etc/apparmor.d/huginn || sudo apparmor_parser -R /etc/apparmor.d/huginn >/dev/null 2>&1 || true; } \
       && sudo install -m 644 "$PROFILE_TMP" /etc/apparmor.d/huginn && sudo apparmor_parser -r -W /etc/apparmor.d/huginn; then
      done_ "Page sandbox profile added"
    else
      say "  ${D}Without it Huginn runs pages with the sandbox off. To add it later, run this installer again.${N}"
    fi
    rm -f "$PROFILE_TMP"
  fi
  if [ "$SYSTEM" = 1 ]; then                       # readable by everyone; pages compiled once, here
    chmod -R a+rX,go-w "$W$TARGET"
    # Copied files keep whoever unpacked Huginn as their owner, and the fetched tools the owner
    # recorded in their archive. A program every user runs must be root's alone to change.
    [ "$(id -u)" != 0 ] || chown -R 0:0 "$W$TARGET" "$W$LAUNCHER" "$W$ENTRY"
    "$TOOLPY" -m compileall -q "$W$TARGET/safari_browser.py" "$W$TARGET/engine" >/dev/null 2>&1 || true
  fi
  if [ "$SYSTEM" = 0 ] || system_hooks; then
    command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$(dirname "$ENTRY")" 2>/dev/null || true
    command -v gtk-update-icon-cache >/dev/null 2>&1 && gtk-update-icon-cache -q -t "$ICONS" 2>/dev/null || true
  fi
  if [ "$SYSTEM" = 1 ]; then
    done_ "In the apps menu for every user, and huginn in a terminal"
  else
    done_ "In your apps menu (search for Huginn)"
  fi
  # A web browser to the system (Debian's x-www-browser, GNOME's gnome-www-browser), and with
  # --default the one links open in: for everyone (system install) or for you.
  if system_hooks && command -v update-alternatives >/dev/null 2>&1; then
    for alt in x-www-browser gnome-www-browser; do
      update-alternatives --install "/usr/bin/$alt" "$alt" "$LAUNCHER" 210 >/dev/null 2>&1 || true
      [ "$MAKE_DEFAULT" = 1 ] && update-alternatives --set "$alt" "$LAUNCHER" >/dev/null 2>&1 || true
    done
  fi
  if [ "$MAKE_DEFAULT" = 1 ]; then
    if [ "$SYSTEM" = 1 ]; then                      # the freedesktop defaults every user starts with
      LIST="$W/etc/xdg/mimeapps.list"
      mkdir -p "$(dirname "$LIST")"
      [ -f "$LIST" ] || printf '[Default Applications]\n' > "$LIST"
      grep -q '^\[Default Applications\]' "$LIST" || printf '\n[Default Applications]\n' >> "$LIST"
      for mime in text/html application/xhtml+xml x-scheme-handler/http x-scheme-handler/https x-scheme-handler/about x-scheme-handler/unknown; do
        sed -i "\#^$mime=#d" "$LIST"
        sed -i "/^\[Default Applications\]/a $mime=huginn.desktop" "$LIST"
      done
      done_ "The default web browser for every user"
    elif command -v xdg-settings >/dev/null 2>&1 && xdg-settings set default-web-browser huginn.desktop 2>/dev/null; then
      done_ "Your default web browser"
    fi
  fi
  if [ "$DESKTOP" = 1 ] && [ "$SYSTEM" = 0 ]; then
    DESK="$(desktop_folder)"
    if [ -d "$DESK" ]; then
      cp "$ENTRY" "$DESK/huginn.desktop" && chmod +x "$DESK/huginn.desktop"
      command -v gio >/dev/null 2>&1 && gio set "$DESK/huginn.desktop" metadata::trusted true 2>/dev/null || true
      done_ "On your desktop"
    fi
  fi
  if [ "$DOCK" = 1 ] && [ "$SYSTEM" = 0 ]; then
    favs="$(gsettings get org.gnome.shell favorite-apps 2>/dev/null || echo "@as []")"
    case "$favs" in
      *huginn.desktop*) ;;
      "@as []"|"[]") gsettings set org.gnome.shell favorite-apps "['huginn.desktop']" ;;
      *) gsettings set org.gnome.shell favorite-apps "${favs%]}, 'huginn.desktop']" ;;
    esac
    done_ "Pinned to the dock"
  fi
fi
rm -rf "$ICONDIR"

say ""
say "  ${B}Huginn is ready.${N} A short tour shows you around the first time it opens."
if [ "$OS" = Darwin ]; then
  say "  ${D}Open it from the Dock, Launchpad, Spotlight (⌘ Space, Huginn) or Applications.${N}"
  say "  ${D}To remove it: drag Huginn from Applications to the Bin (your bookmarks stay).${N}"
elif [ "$SYSTEM" = 1 ]; then
  say "  ${D}Everyone on this computer finds it in their apps menu, or types huginn in a terminal.${N}"
  say "  ${D}To remove it: sudo $TARGET/installer/install.sh --system --uninstall${N}"
else
  say "  ${D}Open it from your apps menu$( [ "$DESKTOP" = 1 ] && printf ' or the desktop'), or type huginn in a terminal.${N}"
  say "  ${D}To remove it: $TARGET/installer/install.sh --uninstall${N}"
fi
[ "$SYSTEM" = 1 ] || say "  ${D}The folder you unzipped isn't needed any more.${N}"
say ""
if [ "$OPEN" = 1 ] && ask "Open Huginn now?" y; then
  if [ "$OS" = Darwin ]; then
    open "$BUNDLE"
    say "  ${D}Opening Huginn. You can close this window.${N}"; say ""
  else
    (nohup "$LAUNCHER" >/dev/null 2>&1 &)
  fi
fi
finish 0
