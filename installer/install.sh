#!/usr/bin/env bash
# Huginn's installer for macOS and Linux (Windows uses Install Huginn.bat).
#   macOS: "Install Huginn (Mac).command" runs this. It makes Huginn.app in Applications
#          (Launchpad, Spotlight, Finder) and can keep it in the Dock.
#   Linux: "Install Huginn (Linux).sh" runs this. It puts Huginn in your apps menu, and can add it
#          to the desktop and (GNOME) pin it to the dock.
# It installs for you only, no administrator password: Huginn and its own Python go in one
# folder. Options: --yes (no questions), --no-desktop, --no-dock, --uninstall.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE="$(cd "$HERE/.." && pwd)"
OS="$(uname -s)"
ARCH="$(uname -m)"
ASK=1; DESKTOP=1; DOCK=1; UNINSTALL=0
for arg in "$@"; do
  case "$arg" in
    --yes|-y) ASK=0 ;;
    --no-desktop) DESKTOP=0 ;;
    --no-dock) DOCK=0 ;;
    --uninstall) UNINSTALL=1 ;;
    *) echo "Unknown option: $arg"; exit 2 ;;
  esac
done
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
elif [ "$OS" = Linux ]; then
  TARGET="${HUGINN_TARGET:-$DATA_HOME/huginn}"
  VENV="$TARGET/.python"
  LAUNCHER="$HOME/.local/bin/huginn"
  ENTRY="$DATA_HOME/applications/huginn.desktop"
  ICONS="$DATA_HOME/icons/hicolor"
else
  echo "Huginn's installer knows macOS and Linux; on Windows, run Install Huginn.bat."; exit 1
fi

desktop_folder() {
  local d=""
  command -v xdg-user-dir >/dev/null 2>&1 && d="$(xdg-user-dir DESKTOP 2>/dev/null || true)"
  [ -n "$d" ] && [ "$d" != "$HOME" ] || d="$HOME/Desktop"
  printf '%s' "$d"
}

# ------------------------------------------------------------------------------------- remove
if [ "$UNINSTALL" = 1 ]; then
  banner "Remove Huginn" "Huginn and its own Python go; your bookmarks, history and passwords stay unless you say otherwise."
  pkill -f "$TARGET/safari_browser.py" 2>/dev/null || true
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
else
  banner "Install Huginn" "A quiet, private browser, named for Odin's raven of thought. It goes in your apps menu."
fi
say "  ${D}Takes a few minutes: it fetches its own Python and the browser engine (a few hundred MB).${N}"
say "  ${D}For you only, no administrator password. Remove it any time (see README.txt).${N}"
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
mkdir -p "$TARGET"
chmod -R u+w "$TARGET" 2>/dev/null || true         # installing again: some files came read-only
if [ "$(cd "$SOURCE" && pwd -P)" != "$(cd "$TARGET" && pwd -P)" ]; then
  (cd "$SOURCE" && tar cf - --exclude=./python --exclude='./.python' --exclude='__pycache__' --exclude=./test_out \
      --exclude=./engine/standard-engine --exclude='*.log' --exclude=./engine/installed.json \
      --exclude=./engine/state.json --exclude=./engine/status.json --exclude=./engine/status.txt \
      --exclude=./engine/build-log.txt --exclude=./engine/builder.pid --exclude=./engine/restart.json \
      --exclude=./engine/last-error.txt --exclude=./engine/update-check.json --exclude=./.git .) \
    | (cd "$TARGET" && tar xf -) || fail "Copying failed."
fi
chmod +x "$TARGET/installer/install.sh" 2>/dev/null || true
done_ "Copied Huginn"

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
if [ -z "$PY" ]; then
  case "$OS-$ARCH" in
    Darwin-arm64) UVA=aarch64-apple-darwin ;;
    Darwin-x86_64) UVA=x86_64-apple-darwin ;;
    Linux-x86_64) UVA=x86_64-unknown-linux-gnu ;;
    Linux-aarch64) UVA=aarch64-unknown-linux-gnu ;;
    *) fail "No ready-made Python for $OS on $ARCH. Install Python 3.10 or newer, then run this again." ;;
  esac
  mkdir -p "$TARGET/.tools"
  curl -fsSL "https://github.com/astral-sh/uv/releases/latest/download/uv-$UVA.tar.gz" -o "$TARGET/.tools/uv.tar.gz" \
    || fail "Couldn't download what Huginn needs. Check the internet connection, then try again."
  tar xzf "$TARGET/.tools/uv.tar.gz" -C "$TARGET/.tools" --strip-components 1 && rm -f "$TARGET/.tools/uv.tar.gz"
  UV="$TARGET/.tools/uv"
  export UV_PYTHON_INSTALL_DIR="$TARGET/.tools/python"
  "$UV" python install 3.12 --quiet || fail "Couldn't get Python. Check the internet connection, then try again."
  "$UV" venv --quiet --allow-existing --python 3.12 "$VENV" || fail "Couldn't set up Python."
else
  "$PY" -m venv "$VENV" || fail "Couldn't set up Python (on Debian/Ubuntu: sudo apt install python3-venv)."
fi
done_ "Python ready"

# 3. The browser engine (PySide6 / Qt WebEngine) and the password manager's encryption library
step "Getting the browser engine (a few hundred MB)"
if [ -n "$UV" ]; then
  "$UV" pip install --python "$VENV/bin/python" --upgrade PySide6 cryptography \
    || fail "Couldn't download the browser engine. Check the internet connection, then try again."
else
  "$VENV/bin/python" -m pip install --disable-pip-version-check --quiet --upgrade pip >/dev/null 2>&1 || true
  "$VENV/bin/python" -m pip install --disable-pip-version-check --upgrade PySide6 cryptography \
    || fail "Couldn't download the browser engine. Check the internet connection, then try again."
fi
"$VENV/bin/python" -c "import PySide6.QtWebEngineWidgets, cryptography" 2>/dev/null \
  || fail "The browser engine didn't start. On Linux it may need your desktop's graphics libraries (libnss3, libxkbcommon)."
done_ "Browser engine ready"

# 4. Into the system: an app bundle on macOS, a launcher and menu entry on Linux
step "Adding Huginn to your apps"
ICONDIR="$(mktemp -d)"
"$VENV/bin/python" "$TARGET/safari_browser.py" --export-icon "$ICONDIR" >/dev/null 2>&1 || true
VERSION="$(head -n1 "$TARGET/version.txt" 2>/dev/null | tr -d '\r' || true)"; VERSION="${VERSION:-1.0}"
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
exec "$HERE/python/bin/python" "$HERE/huginn/safari_browser.py" "$@" >"$LOGS/huginn.log" 2>&1
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
  LSREG=/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister
  [ -x "$LSREG" ] && "$LSREG" -f "$BUNDLE" >/dev/null 2>&1 || true   # Launchpad and Spotlight see it now
  touch "$BUNDLE"
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
  mkdir -p "$(dirname "$LAUNCHER")" "$(dirname "$ENTRY")"
  cat > "$LAUNCHER" <<LAUNCH
#!/bin/sh
# Starts Huginn (installed in $TARGET).
exec "$VENV/bin/python" "$TARGET/safari_browser.py" "\$@"
LAUNCH
  chmod +x "$LAUNCHER"
  for s in 16 32 48 64 128 256 512; do
    if [ -f "$ICONDIR/huginn-$s.png" ]; then
      mkdir -p "$ICONS/${s}x${s}/apps" && cp "$ICONDIR/huginn-$s.png" "$ICONS/${s}x${s}/apps/huginn.png"
    fi
  done
  cat > "$ENTRY" <<DESKTOP
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
MimeType=text/html;application/xhtml+xml;x-scheme-handler/http;x-scheme-handler/https;
Keywords=browser;web;internet;private;
Actions=new-window;

[Desktop Action new-window]
Name=New Window
Exec=$LAUNCHER
DESKTOP
  command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$(dirname "$ENTRY")" 2>/dev/null || true
  command -v gtk-update-icon-cache >/dev/null 2>&1 && gtk-update-icon-cache -q -t "$ICONS" 2>/dev/null || true
  done_ "In your apps menu (search for Huginn)"
  if [ "$DESKTOP" = 1 ]; then
    DESK="$(desktop_folder)"
    if [ -d "$DESK" ]; then
      cp "$ENTRY" "$DESK/huginn.desktop" && chmod +x "$DESK/huginn.desktop"
      command -v gio >/dev/null 2>&1 && gio set "$DESK/huginn.desktop" metadata::trusted true 2>/dev/null || true
      done_ "On your desktop"
    fi
  fi
  if [ "$DOCK" = 1 ]; then
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
else
  say "  ${D}Open it from your apps menu$( [ "$DESKTOP" = 1 ] && printf ' or the desktop'), or type huginn in a terminal.${N}"
  say "  ${D}To remove it: $TARGET/installer/install.sh --uninstall${N}"
fi
say "  ${D}The folder you unzipped isn't needed any more.${N}"
say ""
if ask "Open Huginn now?" y; then
  if [ "$OS" = Darwin ]; then
    open "$BUNDLE"
    say "  ${D}Opening Huginn. You can close this window.${N}"; say ""
  else
    (nohup "$LAUNCHER" >/dev/null 2>&1 &)
  fi
fi
finish 0
