#!/usr/bin/env bash
# Builds huginn_<version>_<arch>.deb: Huginn for every user of a Debian or Ubuntu based system
# (Huginn OS's image, for one). Run it on the release the package is for: the package uses
# that release's Python, and its dependencies are worked out from the libraries the browser
# engine loads there.
#   installer/build-deb.sh [output folder]      (needs dpkg-deb, and the internet for the engine)
#   installer/build-deb.sh --system-engine [output folder]
#       A small package (about 1 MB, for every architecture) that runs on the distribution's
#       python3 and PySide6 instead of bringing its own: Ubuntu 25.04+ / Debian 13+, built
#       on a machine with those installed. The distribution's Qt WebEngine plays H.264 / AAC
#       video, and its security fixes come with the system's updates. (Huginn OS's choice.)
# The package puts Huginn in /opt/huginn, /usr/bin/huginn, the apps menu entry and icons
# under /usr/share, and registers it as an x-www-browser. Make it the default for everyone
# with:  sudo update-alternatives --set x-www-browser /usr/bin/huginn  (plus the
# [Default Applications] lines in /etc/xdg/mimeapps.list - install.sh --system --default
# writes both), or ship that mimeapps.list in the image.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE="$(cd "$HERE/.." && pwd)"
SYS_ENGINE=0; OUT="$SOURCE/dist"
for arg in "$@"; do
  case "$arg" in
    --system-engine) SYS_ENGINE=1 ;;
    -*) echo "Unknown option: $arg"; exit 2 ;;
    *) OUT="$arg" ;;
  esac
done
command -v dpkg-deb >/dev/null 2>&1 || { echo "build-deb.sh needs dpkg-deb (Debian or Ubuntu)."; exit 1; }

PY_FOR_TOOLS="$(command -v python3)"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
if [ "$SYS_ENGINE" = 1 ]; then
  bash "$HERE/install.sh" --root="$STAGE" --yes --no-open --system-engine
else
  bash "$HERE/install.sh" --root="$STAGE" --yes --no-open
fi

APP="$STAGE/opt/huginn"

# A slimmer engine (skip with HUGINN_FULL_ENGINE=1): PySide6 brings all of Qt, but Huginn uses
# only its widgets, web engine, multimedia and speech. Qt's developer tools, translations
# (Huginn loads none; the web engine's own locales stay), and modules such as 3D, Charts,
# SQL, Bluetooth and Designer go, and the identical copies pip makes of each library (a
# wheel can't hold symlinks) become links. Then every library left must still resolve.
if [ -z "${HUGINN_FULL_ENGINE:-}" ] && [ "$SYS_ENGINE" = 0 ]; then
  for P in "$APP"/.python/lib/python3*/site-packages/PySide6; do
    [ -d "$P" ] || continue
    before="$(du -sm "$P" | cut -f1)"
    unresolved() { find "$P" \( -name '*.so*' -o -name QtWebEngineProcess \) -type f -exec ldd {} + 2>/dev/null | grep 'not found' | awk '{print $1}' | sort -u; }
    ALREADY="$(unresolved || true)"                # e.g. an embedded-Linux plugin's library PySide6 doesn't ship
    : "${P:?}"
    rm -rf "$P"/{assistant,balsam,balsamui,designer,linguist,lrelease,lupdate,qmlformat,qmllint,qmlls,qsb,svgtoqml} \
           "${P:?}"/{doc,include,typesystems,glue,lib,scripts} "$P/Qt/metatypes" \
           "$P"/Qt/libexec/{qmlcachegen,qmlimportscanner,qmltyperegistrar,rcc,uic}
    find "$P" -name '*.pyi' -delete
    find "$P/Qt/translations" -maxdepth 1 -name '*.qm' -delete
    for m in 3DCore 3DRender 3DInput 3DLogic 3DExtras 3DAnimation 3DQuick 3DQuickRender 3DQuickInput 3DQuickExtras \
             3DQuickAnimation 3DQuickScene2D 3DQuickScene3D Quick3D Quick3DUtils Quick3DRuntimeRender Quick3DAssetImport \
             Quick3DAssetUtils Quick3DParticles Quick3DHelpers Quick3DHelpersImpl Quick3DPhysics Quick3DPhysicsHelpers \
             Quick3DEffects Quick3DGlslParser Quick3DIblBaker Quick3DParticleEffects Quick3DXr Quick3DSpatialAudio \
             Charts ChartsQml DataVisualization DataVisualizationQml Graphs GraphsWidgets Bluetooth Nfc SerialBus \
             Sensors SensorsQuick Location Scxml ScxmlQml RemoteObjects RemoteObjectsQml \
             HttpServer Designer DesignerComponents UiTools Help SpatialAudio VirtualKeyboard VirtualKeyboardQml \
             VirtualKeyboardSettings WebView WebViewQuick; do
      rm -f "$P/Qt/lib/libQt6$m.so"* "$P/Qt$m.abi3.so" "$P/Qt$m.pyi"
      rm -rf "$P/Qt$m"
    done
    rm -rf "$P"/Qt/qml/{Qt3D,QtQuick3D,QtCharts,QtGraphs,QtDataVisualization,QtLocation,QtSensors,QtScxml,QtRemoteObjects,QtVirtualKeyboard,QtWebView}
    rm -rf "$P"/Qt/plugins/{assetimporters,canbus,designer,geometryloaders,geoservices,renderers,renderplugins,sceneparsers,scxmldatamodel,sensors,sqldrivers,webview,qmltooling,virtualkeyboard}
    rm -f "$P"/Qt/plugins/platforminputcontexts/libqtvirtualkeyboardplugin.so
    "$PY_FOR_TOOLS" - "$P" <<'DEDUPE'
import hashlib, os, sys
seen = {}
for root, _dirs, files in os.walk(sys.argv[1]):
    for name in sorted(files, key=len, reverse=True):          # libfoo.so.6.12.0 kept, libfoo.so.6 -> it
        path = os.path.join(root, name)
        if os.path.islink(path) or os.path.getsize(path) < 65536:
            continue
        with open(path, "rb") as f:
            key = (os.path.getsize(path), hashlib.sha256(f.read()).hexdigest())
        if key in seen and os.path.dirname(seen[key]) == root:
            os.remove(path)
            os.symlink(os.path.basename(seen[key]), path)
        else:
            seen.setdefault(key, path)
DEDUPE
    # Whatever was there only to serve a module that went (a 3D scene loader, say) goes too.
    for _ in 1 2 3 4; do
      GONE="$(comm -13 <(printf '%s\n' "$ALREADY") <(unresolved || true) | grep . || true)"
      [ -n "$GONE" ] || break
      PATTERN="$(printf '%s\n' "$GONE" | sed 's/\./\\./g' | paste -sd'|' -)"
      while IFS= read -r f; do
        ldd "$f" 2>/dev/null | grep 'not found' | grep -Eq "$PATTERN" && rm -f "$f"
      done < <(find "$P" \( -name '*.so*' -o -name QtWebEngineProcess \) -type f)
    done
    MISSING="$(comm -13 <(printf '%s\n' "$ALREADY") <(unresolved || true) | grep . || true)"
    if [ -n "$MISSING" ]; then
      echo "Slimming left the engine needing something it took out:"; echo "$MISSING"; exit 1
    fi
    "$APP/.python/bin/python" -c "import PySide6.QtWebEngineWidgets, PySide6.QtMultimedia, PySide6.QtTextToSpeech, PySide6.QtSvg" \
      || { echo "The slimmed engine doesn't import."; exit 1; }
    echo "Engine slimmed: ${before} MB -> $(du -sm "$P" | cut -f1) MB"
  done
fi

# The release's version (e.g. HUGINN_VERSION=2026.11.12.1), else version.txt's, else today's.
VERSION="${HUGINN_VERSION:-$(head -n1 "$APP/version.txt" 2>/dev/null | tr -d '\r' || true)}"
[[ "$VERSION" =~ ^[0-9][0-9.]*$ ]] || VERSION="$(date +%Y.%-m.%-d).0"
printf '%s\n' "$VERSION" > "$APP/version.txt"                 # Huginn's About shows it
if [ "$SYS_ENGINE" = 1 ]; then
  # Pure Python: one package for every architecture, compiled where it's installed.
  ARCH=all
  rm -rf "$APP/__pycache__" "$APP/engine/__pycache__"
  DEPS="python3 (>= 3.10), python3-pyside6.qtwebenginewidgets (>= 6.10), python3-pyside6.qtwebenginecore, python3-pyside6.qtwebchannel, python3-pyside6.qtmultimedia, python3-pyside6.qttexttospeech, python3-pyside6.qtsvg, python3-pyside6.qtnetwork, python3-cryptography, qt6-qpa-plugins"
  RECOMMENDS="qt6-wayland, qt6-speech-speechd-plugin, "
else
  ARCH="$(dpkg --print-architecture)"
  PY="$(readlink -f "$APP/.python/bin/python")"
  PYVER="$("$PY" -c 'import sys; print(f"{sys.version_info[0]}.{sys.version_info[1]}")')"

  # Dependencies: the packages that own the system libraries Qt WebEngine and its plugins load.
  LIBS="$(find "$APP/.python" \( -name 'libQt6*.so*' -o -path '*/plugins/*.so' -o -name QtWebEngineProcess \) -type f \
            -exec ldd {} + 2>/dev/null | awk '$2 == "=>" && $3 ~ /^\// {print $3}' | grep -v "^$APP" | sort -u)"
  DEPS="python$PYVER"
  for lib in $LIBS; do
    for candidate in "$lib" "$(readlink -f "$lib")" "/usr$lib" "${lib#/usr}"; do
      pkg="$(dpkg -S "$candidate" 2>/dev/null | head -n1 | cut -d: -f1 | cut -d, -f1)" && [ -n "$pkg" ] && break
    done
    [ -n "${pkg:-}" ] && DEPS="$DEPS, $pkg"
    pkg=""
  done
  DEPS="$(printf '%s\n' "$DEPS" | tr ',' '\n' | sed 's/^ *//' | sort -u | grep -v '^libc6$' | paste -sd, - | sed 's/,/, /g')"
  # Qt's X11 plugin also needs these at run time (dlopen'd, so ldd doesn't list them all).
  DEPS="$DEPS, libxcb-cursor0, libxkbcommon-x11-0"
  RECOMMENDS=""
fi

SIZE="$(du -sk "$STAGE" | cut -f1)"
mkdir -p "$STAGE/DEBIAN"
cat > "$STAGE/DEBIAN/control" <<CONTROL
Package: huginn
Version: $VERSION
Section: web
Priority: optional
Architecture: $ARCH
Installed-Size: $SIZE
Depends: $DEPS
Recommends: ${RECOMMENDS}xdg-utils, speech-dispatcher, fonts-inter, fonts-noto-core, fonts-noto-color-emoji
Provides: www-browser, gnome-www-browser
Maintainer: Huginn <noreply@github.com>
Homepage: https://github.com/Valkyrii070/Huginn
Description: quiet, private web browser
 Huginn is a Safari-style, privacy-first web browser built on Qt WebEngine.
 Trackers, ads, cookie pop-ups and fingerprinting are blocked from the
 start; Muninn remembers what pages said so you can find them again; and
 Valhalla keeps the tabs you closed this week.
CONTROL
cat > "$STAGE/DEBIAN/postinst" <<'POSTINST'
#!/bin/sh
set -e
if [ "$1" = configure ]; then
  if [ -f /etc/apparmor.d/huginn ] && command -v apparmor_parser >/dev/null 2>&1 && [ -d /sys/kernel/security/apparmor ]; then
    apparmor_parser -r -W /etc/apparmor.d/huginn >/dev/null 2>&1 || true      # the page sandbox's profile
  fi
  [ -d /opt/huginn/.python ] || python3 -m compileall -q /opt/huginn/safari_browser.py /opt/huginn/engine >/dev/null 2>&1 || true
  update-alternatives --install /usr/bin/x-www-browser x-www-browser /usr/bin/huginn 210
  update-alternatives --install /usr/bin/gnome-www-browser gnome-www-browser /usr/bin/huginn 210
  command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database -q /usr/share/applications || true
  command -v gtk-update-icon-cache >/dev/null 2>&1 && gtk-update-icon-cache -q -t /usr/share/icons/hicolor || true
fi
exit 0
POSTINST
cat > "$STAGE/DEBIAN/prerm" <<'PRERM'
#!/bin/sh
set -e
rm -rf /opt/huginn/__pycache__ /opt/huginn/engine/__pycache__   # bytecode made here, so dpkg can remove the folders
if [ "$1" = remove ] || [ "$1" = deconfigure ]; then
  if [ -f /etc/apparmor.d/huginn ] && command -v apparmor_parser >/dev/null 2>&1 && [ -d /sys/kernel/security/apparmor ]; then
    apparmor_parser -R /etc/apparmor.d/huginn >/dev/null 2>&1 || true
  fi
  update-alternatives --remove x-www-browser /usr/bin/huginn
  update-alternatives --remove gnome-www-browser /usr/bin/huginn
fi
exit 0
PRERM
cat > "$STAGE/DEBIAN/postrm" <<'POSTRM'
#!/bin/sh
set -e
if [ "$1" = remove ] || [ "$1" = purge ]; then
  rm -rf /opt/huginn/__pycache__ /opt/huginn/engine/__pycache__     # bytecode Python made later
  rmdir /opt/huginn/engine /opt/huginn 2>/dev/null || true
  command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database -q /usr/share/applications || true
  command -v gtk-update-icon-cache >/dev/null 2>&1 && gtk-update-icon-cache -q -t /usr/share/icons/hicolor || true
fi
exit 0
POSTRM
chmod 755 "$STAGE/DEBIAN/postinst" "$STAGE/DEBIAN/prerm" "$STAGE/DEBIAN/postrm"
chmod 755 "$STAGE"

mkdir -p "$OUT"
DEB="$OUT/huginn_${VERSION}_${ARCH}.deb"
dpkg-deb --root-owner-group -Zxz --build "$STAGE" "$DEB" >/dev/null
echo "Built $DEB ($(du -h "$DEB" | cut -f1))"
echo "Depends: $DEPS"
