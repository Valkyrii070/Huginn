#!/usr/bin/env bash
# Huginn OS ISO build: debootstrap -> chroot customise -> squashfs -> hybrid BIOS/UEFI ISO.
#
#   sudo scripts/build.sh                 full build
#   sudo scripts/build.sh --from rootfs   reuse the bootstrap tarball, rebuild from package install onward
#   sudo scripts/build.sh --from customise  reuse the installed chroot: apply the overlay and hooks again, then repack
#   sudo scripts/build.sh --from image    reuse the finished chroot, only repack squashfs + ISO
#   sudo scripts/build.sh --check         only validate the package lists against the archive
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=../config/build.conf
source "$ROOT/config/build.conf"
# Local changes that stay out of the repository (a nearer mirror, faster compression for test builds…).
if [[ -f "$ROOT/config/build.local.conf" ]]; then
    # shellcheck source=/dev/null
    source "$ROOT/config/build.local.conf"
fi

WORK="${WORK:-$ROOT/work}"
OUT="${OUT:-$ROOT/out}"
CHROOT="$WORK/chroot"
IMAGE="$WORK/image"
BOOTSTRAP_TAR="$WORK/bootstrap-$SUITE-${SNAPSHOT:-live}.tar"
FROM="bootstrap"
CHECK_ONLY=0

while [[ $# -gt 0 ]]; do
    case "$1" in
        --from) FROM="$2"; shift 2 ;;
        --check) CHECK_ONLY=1; shift ;;
        *) echo "Unknown option: $1" >&2; exit 2 ;;
    esac
done

[[ $EUID -eq 0 ]] || { echo "Run as root: sudo $0" >&2; exit 1; }

# One timestamp for every file the build creates, so two builds of the same commit match.
SOURCE_DATE_EPOCH="${SOURCE_DATE_EPOCH:-$(git -C "$ROOT" log -1 --format=%ct 2>/dev/null || date +%s)}"
export SOURCE_DATE_EPOCH
BUILD_ID="$(date -u -d "@$SOURCE_DATE_EPOCH" +%Y%m%d)"
ISO="$OUT/$DISTRO_ID-$DISTRO_VERSION-$BUILD_ID-$ARCH.iso"

if [[ -n "${SNAPSHOT:-}" ]]; then
    APT_MIRROR="$SNAPSHOT_MIRROR/$SNAPSHOT"
else
    APT_MIRROR="$MIRROR"
fi

log() { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33mwarning: %s\033[0m\n' "$*" >&2; }
die() { printf '\033[1;31merror: %s\033[0m\n' "$*" >&2; exit 1; }

umount_chroot() {
    local m
    for m in tmp/hc/crates tmp/hc/target dev/pts dev proc sys run; do
        mountpoint -q "$CHROOT/$m" && umount -l "$CHROOT/$m"
    done
    return 0
}
trap umount_chroot EXIT

mount_chroot() {
    mount --bind /dev "$CHROOT/dev"
    mount -t devpts devpts "$CHROOT/dev/pts"
    mount -t proc proc "$CHROOT/proc"
    mount -t sysfs sysfs "$CHROOT/sys"
    mount -t tmpfs tmpfs "$CHROOT/run"
}

in_chroot() {
    chroot "$CHROOT" /usr/bin/env -i \
        HOME=/root TERM="${TERM:-linux}" PATH=/usr/sbin:/usr/bin:/sbin:/bin \
        DEBIAN_FRONTEND=noninteractive LC_ALL=C.UTF-8 \
        SOURCE_DATE_EPOCH="$SOURCE_DATE_EPOCH" "$@"
}

package_list() {
    # All packages from config/package-lists/*.list, comments and blanks stripped.
    cat "$ROOT"/config/package-lists/*.list | sed 's/#.*//' | awk 'NF {print $1}' | sort -u
}

stage_bootstrap() {
    log "Bootstrap $SUITE ($ARCH) from $APT_MIRROR"
    rm -rf "$CHROOT"
    mkdir -p "$CHROOT"
    debootstrap --arch="$ARCH" --variant=minbase --components="$COMPONENTS" \
        --include=ca-certificates,gpgv "$SUITE" "$CHROOT" "$APT_MIRROR"
    tar -C "$CHROOT" -cf "$BOOTSTRAP_TAR" .
}

stage_restore_bootstrap() {
    [[ -f "$BOOTSTRAP_TAR" ]] || { echo "No bootstrap tarball; run a full build first." >&2; exit 1; }
    log "Restore bootstrap tarball"
    umount_chroot
    rm -rf "$CHROOT"
    mkdir -p "$CHROOT"
    tar -C "$CHROOT" -xf "$BOOTSTRAP_TAR"
}

stage_configure_apt() {
    log "Configure apt"
    local pockets="$SUITE $SUITE-updates $SUITE-security"
    cat > "$CHROOT/etc/apt/sources.list.d/ubuntu.sources" <<SRC
Types: deb
URIs: $APT_MIRROR
Suites: $pockets
Components: ${COMPONENTS//,/ }
Signed-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg
SRC
    rm -f "$CHROOT/etc/apt/sources.list"
    # Lean installs: no recommends, no snapd pulled back in by a dependency.
    cat > "$CHROOT/etc/apt/apt.conf.d/90huginn" <<'APT'
APT::Install-Recommends "false";
APT::Install-Suggests "false";
Acquire::Check-Valid-Until "false";
APT
    # Building behind an HTTPS proxy (build.local.conf: APT_PROXY, APT_CA): for the build only, removed in cleanup.
    rm -f "$CHROOT/etc/apt/apt.conf.d/89huginn-build-proxy" "$CHROOT/usr/local/share/huginn-build-ca.crt"
    if [[ -n "${APT_PROXY:-}" ]]; then
        echo "Acquire::https::Proxy \"$APT_PROXY\";" > "$CHROOT/etc/apt/apt.conf.d/89huginn-build-proxy"
        if [[ -n "${APT_CA:-}" ]]; then
            install -D -m 644 "$APT_CA" "$CHROOT/usr/local/share/huginn-build-ca.crt"
            echo 'Acquire::https::CaInfo "/usr/local/share/huginn-build-ca.crt";' >> "$CHROOT/etc/apt/apt.conf.d/89huginn-build-proxy"
        fi
    fi
    cat > "$CHROOT/etc/apt/preferences.d/no-snapd" <<'PIN'
Package: snapd
Pin: release *
Pin-Priority: -10
PIN
    in_chroot apt-get update
}

stage_check_packages() {
    log "Validate package lists against the archive"
    local missing=() pkg
    while read -r pkg; do
        if ! in_chroot apt-cache show "$pkg" >/dev/null 2>&1; then
            missing+=("$pkg")
        fi
    done < <(package_list)
    if (( ${#missing[@]} )); then
        printf 'Not found in %s: %s\n' "$SUITE" "${missing[*]}" >&2
        echo "Fix config/package-lists/*.list (apt-cache search inside the chroot helps)." >&2
        exit 1
    fi
    echo "All $(package_list | wc -l) packages resolve."
}

stage_install() {
    log "Install packages"
    # Stop services from starting inside the chroot.
    printf '#!/bin/sh\nexit 101\n' > "$CHROOT/usr/sbin/policy-rc.d"
    chmod +x "$CHROOT/usr/sbin/policy-rc.d"
    in_chroot apt-get -y dist-upgrade
    local pkgs
    mapfile -t pkgs < <(package_list)
    in_chroot apt-get -y install "${pkgs[@]}"

    # Apps Huginn has its own of stay out, even if a dependency brings one in.
    local unwanted=() p
    while read -r p; do
        in_chroot dpkg-query -W -f='${Status}' "$p" 2>/dev/null | grep -q 'install ok installed' && unwanted+=("$p")
    done < <(sed 's/#.*//' "$ROOT/config/not-wanted.list" | awk 'NF {print $1}')
    if (( ${#unwanted[@]} )); then
        warn "pulled in by a dependency, taking out: ${unwanted[*]}"
        in_chroot apt-get -y purge "${unwanted[@]}"
        for p in "${pkgs[@]}"; do
            in_chroot dpkg-query -W -f='${Status}' "$p" 2>/dev/null | grep -q 'install ok installed' \
                || die "taking out ${unwanted[*]} also took out $p: fix config/not-wanted.list or the package lists"
        done
    fi
}

# Rounded corners for every window, as Huginn's own apps draw theirs: KDE-Rounded-Corners (a KWin effect, GPL-3.0,
# vendor/rounded-corners), built here against this very KWin. Its build tools come and go again; the libraries the
# effect itself uses stay.
build_rounded_corners() {
    local src="$ROOT/vendor/rounded-corners" pin="66d7ce9"
    if [ ! -d "$src/src" ] && command -v git >/dev/null 2>&1; then      # fetched once, at the version tested with this KWin
        git clone -q https://github.com/matinlotfali/KDE-Rounded-Corners "$src" && git -C "$src" checkout -q "$pin" || rm -rf "$src"
    fi
    [ -d "$src/src" ] || { warn "no vendor/rounded-corners: other apps' windows keep square corners"; return 0; }
    rm -rf "$CHROOT/tmp/rc"; cp -r "$src" "$CHROOT/tmp/rc"
    local deps="cmake g++ make extra-cmake-modules kwin-dev qt6-base-private-dev qt6-base-dev-tools libkf6kcmutils-dev libkf6configwidgets-dev libkf6i18n-dev libdrm-dev gettext"
    in_chroot sh -c "dpkg-query -W -f='\${Package}\n' | sort > /tmp/rc-before.txt"
    if in_chroot env DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends $deps > "$WORK/rc-deps.log" 2>&1 \
       && in_chroot sh -c "cd /tmp/rc && cmake -B build -DCMAKE_INSTALL_PREFIX=/usr -DCMAKE_BUILD_TYPE=Release && cmake --build build -j$(nproc) && cmake --install build" > "$WORK/rc-build.log" 2>&1; then
        # keep what the effect links against; everything else the build brought in goes again
        in_chroot sh -c 'for f in $(find /usr/lib/x86_64-linux-gnu/qt6/plugins -name "*roundcorners*" -o -name "*shapecorners*" | grep "\.so$"); do
            ldd "$f" | awk "/=> \\//{print \$3}" | xargs -r dpkg -S 2>/dev/null | cut -d: -f1 | sort -u | xargs -r apt-mark manual >/dev/null; done'
        install -D -m 644 "$src/LICENSE" "$CHROOT/usr/share/doc/huginn-rounded-corners/LICENSE"
    else
        warn "the rounded-corners effect didn't build (see $WORK/rc-build.log): other apps' windows keep square corners"
        tail -15 "$WORK/rc-build.log" "$WORK/rc-deps.log" 2>/dev/null || true
    fi
    in_chroot sh -c "dpkg-query -W -f='\${Package}\n' | sort > /tmp/rc-after.txt; comm -13 /tmp/rc-before.txt /tmp/rc-after.txt > /tmp/rc-new.txt"
    in_chroot sh -c 'grep -E -- "-dev\$|^(cmake|cmake-data|g\+\+|g\+\+-[0-9]+|make|extra-cmake-modules|gettext|qt6-base-dev-tools)\$" /tmp/rc-new.txt | xargs -r env DEBIAN_FRONTEND=noninteractive apt-get purge -y' > "$WORK/rc-purge.log" 2>&1 || true
    in_chroot env DEBIAN_FRONTEND=noninteractive apt-get autoremove -y --purge >> "$WORK/rc-purge.log" 2>&1 || true
    rm -rf "$CHROOT/tmp/rc" "$CHROOT"/tmp/rc-*.txt
}

build_compositor() {
    # Huginn's own compositor (compositor/, Rust, built on Smithay): the "own compositor" session at the sign-in screen.
    # Rust and the headers are put in the image only while it builds, then taken out again, as for rounded corners.
    local src="$ROOT/compositor" crates="$WORK/cargo-home" target="$WORK/compositor-target"
    [ -f "$src/Cargo.toml" ] || return 0
    local deps="rustc cargo pkg-config libudev-dev libinput-dev libgbm-dev libseat-dev libxkbcommon-dev libegl-dev libgles-dev libdrm-dev libpixman-1-dev libdisplay-info-dev libwayland-dev"
    in_chroot sh -c "dpkg-query -W -f='\${Package}\n' | sort > /tmp/hc-before.txt"
    if ! in_chroot env DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends $deps > "$WORK/comp-deps.log" 2>&1; then
        warn "Rust or the compositor's headers didn't install (see $WORK/comp-deps.log): no \"own compositor\" session"
        tail -15 "$WORK/comp-deps.log" || true
    else
        # The crates (the libraries it's built from, Cargo.lock pins them) are fetched here on the build computer
        # when it has cargo, and kept in the work folder between builds; the build inside the image then runs offline.
        mkdir -p "$crates" "$target" "$CHROOT/tmp/hc/src" "$CHROOT/tmp/hc/crates" "$CHROOT/tmp/hc/target"
        local where=chroot
        if command -v cargo >/dev/null 2>&1 \
           && CARGO_HOME="$crates" cargo fetch --locked --manifest-path "$src/Cargo.toml" > "$WORK/comp-fetch.log" 2>&1; then
            where=host
        fi
        rsync -a --delete "$src/" "$CHROOT/tmp/hc/src/"
        mount --bind "$crates" "$CHROOT/tmp/hc/crates"
        mount --bind "$target" "$CHROOT/tmp/hc/target"
        local offline="--offline"
        if [ "$where" = chroot ]; then                   # no cargo here: the image fetches them itself
            offline=""
        fi
        if in_chroot sh -c "cd /tmp/hc/src && CARGO_HOME=/tmp/hc/crates CARGO_TARGET_DIR=/tmp/hc/target cargo build --release --locked $offline" \
               > "$WORK/comp-build.log" 2>&1; then
            install -m 755 "$target/release/huginn-compositor" "$CHROOT/usr/bin/huginn-compositor"
            install -D -m 644 "$src/LICENSE-Smithay.txt" "$CHROOT/usr/share/doc/huginn-compositor/LICENSE-Smithay.txt"
            # keep what it links against; everything else the build brought in goes again
            in_chroot sh -c 'ldd /usr/bin/huginn-compositor | awk "/=> \//{print \$3}" | xargs -r dpkg -S 2>/dev/null | cut -d: -f1 | sort -u | xargs -r apt-mark manual >/dev/null'
        else
            warn "Huginn's compositor didn't build (see $WORK/comp-build.log): no \"own compositor\" session"
            tail -25 "$WORK/comp-build.log" || true
        fi
        umount "$CHROOT/tmp/hc/crates" "$CHROOT/tmp/hc/target"
    fi
    in_chroot sh -c "dpkg-query -W -f='\${Package}\n' | sort > /tmp/hc-after.txt; comm -13 /tmp/hc-before.txt /tmp/hc-after.txt > /tmp/hc-new.txt"
    in_chroot sh -c 'grep -E -- "-dev\$|^(rustc|rustc-[0-9.]+|cargo|cargo-[0-9.]+|libstd-rust-[0-9.]+(-dev)?|gcc|gcc-[0-9]+|cpp|cpp-[0-9]+|pkg-config|pkgconf|pkgconf-bin|libwayland-bin|libc-dev-bin)\$" /tmp/hc-new.txt | xargs -r env DEBIAN_FRONTEND=noninteractive apt-get purge -y' > "$WORK/comp-purge.log" 2>&1 || true
    in_chroot env DEBIAN_FRONTEND=noninteractive apt-get autoremove -y --purge >> "$WORK/comp-purge.log" 2>&1 || true
    rm -rf "$CHROOT/tmp/hc" "$CHROOT"/tmp/hc-*.txt
    # Without it, the session menu mustn't offer a session that can't start.
    [ -x "$CHROOT/usr/bin/huginn-compositor" ] || rm -f "$CHROOT/usr/share/wayland-sessions/huginnos-preview.desktop"
    # Left by earlier builds (with --from customise): the session's old file name, and xwayland-satellite, which the
    # Python preview compositor needed and this one doesn't (XWayland is built in).
    rm -rf "$CHROOT/usr/share/wayland-sessions/huginn-preview.desktop" "$CHROOT/usr/libexec/huginn/xwayland-satellite" \
           "$CHROOT/usr/share/doc/huginn-xwayland-satellite"
}

stage_customise() {
    log "Apply overlay, theme and system defaults"
    rsync -a --chown=root:root "$ROOT/config/overlay/" "$CHROOT/"

    # Theme files generated from the design tokens.
    local theme="$WORK/theme"
    rm -rf "$theme"
    # (Kvantum's themes for Qt apps are KvAdapta's drawing in Huginn's colours: KvAdapta comes from the image.)
    [ -f "$CHROOT/usr/share/Kvantum/KvAdaptaDark/KvAdaptaDark.svg" ] || die "Kvantum's KvAdapta theme is missing (qt6-style-kvantum-themes)"
    python3 "$ROOT/tokens/gen_theme.py" "$ROOT/tokens/tokens.json" "$theme" "$CHROOT/usr/share/Kvantum"
    install -d "$CHROOT/usr/share/color-schemes" "$CHROOT/usr/share/huginn-os/gtk" \
               "$CHROOT/usr/lib/x86_64-linux-gnu/qt6/qml/org/huginn/tokens"
    install -m 644 "$theme"/color-schemes/*.colors "$CHROOT/usr/share/color-schemes/"
    install -m 644 "$theme"/gtk/*.css "$CHROOT/usr/share/huginn-os/gtk/"
    install -m 644 "$theme"/qml/* "$CHROOT/usr/lib/x86_64-linux-gnu/qt6/qml/org/huginn/tokens/"
    local kv
    for kv in "$theme"/kvantum/*/; do
        install -d "$CHROOT/usr/share/Kvantum/$(basename "$kv")"
        install -m 644 "$kv"* "$CHROOT/usr/share/Kvantum/$(basename "$kv")/"
    done
    # Everyone else's apps start in Huginn's look (the shell then follows each user's realm: apps/huginn_look.py):
    # Qt and KDE apps in the Kvantum style and the Aurora colours, GTK apps in Breeze-GTK with them.
    sed -n '/^\[Colors:/,$p' "$theme/color-schemes/HuginnAuroraDark.colors" | sed '/^\[General\]/,$d' >> "$CHROOT/etc/xdg/kdeglobals"
    install -d "$CHROOT/etc/xdg/Kvantum" "$CHROOT/etc/gtk-3.0" "$CHROOT/etc/gtk-4.0"
    printf '[General]\ntheme=HuginnAuroraDark\n' > "$CHROOT/etc/xdg/Kvantum/kvantum.kvconfig"
    for v in 3.0 4.0; do
        printf '[Settings]\ngtk-theme-name=Breeze\ngtk-icon-theme-name=Huginn\ngtk-application-prefer-dark-theme=true\ngtk-font-name=Inter Variable 10\n' > "$CHROOT/etc/gtk-$v/settings.ini"
    done

    # Huginn Shell and the tokens it reads.
    install -d "$CHROOT/usr/share/huginn-shell/qml"
    install -m 755 "$ROOT"/shell/*.py "$CHROOT/usr/share/huginn-shell/"
    install -m 644 "$ROOT"/shell/qml/*.qml "$ROOT"/shell/qml/*.js "$CHROOT/usr/share/huginn-shell/qml/"
    install -m 644 "$ROOT/tokens/tokens.json" "$CHROOT/usr/share/huginn-os/tokens.json"
    install -d "$CHROOT/usr/share/huginn-apps/qml"
    install -m 755 "$ROOT"/apps/*.py "$CHROOT/usr/share/huginn-apps/"
    install -m 644 "$ROOT"/apps/qml/*.qml "$ROOT"/apps/qml/*.png "$CHROOT/usr/share/huginn-apps/qml/"
    # Help's guides, and data the apps carry (Characters' emoji list, with its licence).
    install -d "$CHROOT/usr/share/huginn-apps/help" "$CHROOT/usr/share/huginn-apps/data"
    install -m 644 "$ROOT"/apps/help/*.md "$CHROOT/usr/share/huginn-apps/help/"
    cp -r --no-preserve=ownership "$ROOT"/apps/data/. "$CHROOT/usr/share/huginn-apps/data/"   # Characters' emoji list, Clips' wipe patterns
    # Compiled once here: users can't write next to these files, so otherwise every start compiles them again (the
    # shell and the apps are large Python files; on a slow computer that alone takes seconds at every sign-in).
    in_chroot python3 -m compileall -q /usr/share/huginn-apps /usr/share/huginn-shell

    build_rounded_corners
    build_compositor

    # huginn-grab: KWin hands pictures of the screen only to programs a .desktop file names, by their executable;
    # Huginn's apps are Python, so this small native helper is the one named (native/huginn-grab.c).
    if command -v cc >/dev/null 2>&1 && pkg-config --exists gio-2.0 gio-unix-2.0 2>/dev/null; then
        cc -O2 -Wall -o "$WORK/huginn-grab" "$ROOT/native/huginn-grab.c" $(pkg-config --cflags --libs gio-2.0 gio-unix-2.0) \
            && install -D -m 755 "$WORK/huginn-grab" "$CHROOT/usr/libexec/huginn/huginn-grab" \
            || warn "huginn-grab didn't build: screenshots fall back to KDE's portal backend"
    else
        warn "no C compiler or GIO headers here: huginn-grab isn't built (screenshots fall back to KDE's portal backend)"
    fi

    # Huginn, the browser, from vendor/huginn (see vendor/huginn/SOURCE for the version).
    # Its launcher and menu entry come from the overlay; the per-user installer is left out.
    # When this kit is the os/ folder of the Huginn repository, the browser is the repository itself.
    local browser="$ROOT/vendor/huginn"
    if [ ! -f "$browser/safari_browser.py" ] && [ -f "$ROOT/../safari_browser.py" ]; then
        browser="$(cd "$ROOT/.." && pwd)"
        install -m 644 "$browser/docs/huginn-icon.png" "$WORK/huginn-icon.png"
    fi
    [ -f "$browser/safari_browser.py" ] || die "no browser: run scripts/update-huginn.sh /path/to/Huginn (or build from the Huginn repository's os/ folder)"
    rm -rf "$CHROOT/usr/share/huginn"
    install -d "$CHROOT/usr/share/huginn"
    rsync -a --chown=root:root --chmod=D755,F644 --exclude=installer --exclude='Install Huginn*' \
        --exclude='.git*' --exclude=huginn-icon.png --exclude=/os --exclude=/docs --exclude='*.bat' --exclude='*.ps1' \
        --exclude='*.command' --exclude='*_test.py' --exclude=/python --exclude=__pycache__ --exclude=test_out \
        "$browser/" "$CHROOT/usr/share/huginn/"
    in_chroot python3 -m compileall -q /usr/share/huginn/safari_browser.py
    # Icons: Huginn draws its own at every size; if that fails here, the 256 px picture is used.
    if in_chroot env QT_QPA_PLATFORM=offscreen HOME=/tmp python3 /usr/share/huginn/safari_browser.py --export-icon /tmp/huginn-icons \
            && [ -f "$CHROOT/tmp/huginn-icons/huginn-256.png" ]; then
        local size
        for size in 16 32 48 64 128 256 512; do
            [ -f "$CHROOT/tmp/huginn-icons/huginn-$size.png" ] || continue
            install -D -m 644 "$CHROOT/tmp/huginn-icons/huginn-$size.png" \
                "$CHROOT/usr/share/icons/hicolor/${size}x${size}/apps/huginn.png"
        done
    else
        warn "Huginn could not draw its icons here; using the 256 px picture"
        local icon="$browser/huginn-icon.png"
        [ -f "$icon" ] || icon="$WORK/huginn-icon.png"
        install -D -m 644 "$icon" "$CHROOT/usr/share/icons/hicolor/256x256/apps/huginn.png"
    fi
    rm -rf "$CHROOT/tmp/huginn-icons"
    in_chroot gtk-update-icon-cache -q -t -f /usr/share/icons/hicolor || true
    in_chroot update-mime-database /usr/share/mime || true            # Easel's .easel files
    in_chroot python3 -c "import PySide6.QtWebEngineWidgets, cryptography" \
        || die "Huginn's browser engine (Qt WebEngine) is not importable in the image"

    # Identity.
    echo "$LIVE_HOSTNAME" > "$CHROOT/etc/hostname"
    cat > "$CHROOT/etc/os-release" <<REL
NAME="$DISTRO_NAME"
PRETTY_NAME="$DISTRO_NAME $DISTRO_VERSION"
ID=$DISTRO_ID
ID_LIKE="ubuntu debian"
VERSION_ID="$DISTRO_VERSION"
VERSION_CODENAME=$SUITE
UBUNTU_CODENAME=$SUITE
BUILD_ID=$BUILD_ID
REL
    cat > "$CHROOT/etc/casper.conf" <<CASPER
export USERNAME="$LIVE_USER"
export USERFULLNAME="$DISTRO_NAME"
export HOST="$LIVE_HOSTNAME"
export BUILD_SYSTEM="Ubuntu"
export FLAVOUR="$DISTRO_NAME"
CASPER
    in_chroot locale-gen en_US.UTF-8
    in_chroot update-locale LANG=en_US.UTF-8
    in_chroot systemctl enable NetworkManager sddm ufw
    in_chroot systemctl set-default graphical.target

    # Optional hooks: config/hooks/*.sh run inside the chroot, in name order.
    if compgen -G "$ROOT/config/hooks/*.sh" >/dev/null; then
        install -d "$CHROOT/tmp/hooks"
        install -m 755 "$ROOT"/config/hooks/*.sh "$CHROOT/tmp/hooks/"
        local hook
        for hook in "$CHROOT"/tmp/hooks/*.sh; do
            log "Hook $(basename "$hook")"
            in_chroot "/tmp/hooks/$(basename "$hook")"
        done
    fi

    # The installer puts GRUB's own package for the computer's firmware (UEFI or BIOS) on the installed system, so
    # GRUB keeps itself up to date there. The live system has both GRUBs' files but neither package (they conflict),
    # so the two packages ride on the ISO, in pool/ (stage_image moves them there).
    install -d "$CHROOT/var/cache/huginn-pool"
    in_chroot sh -c 'cd /var/cache/huginn-pool && apt-get download grub-efi-amd64 grub-pc'
}

stage_cleanup() {
    log "Clean chroot"
    in_chroot apt-get -y autoremove --purge
    in_chroot apt-get clean
    in_chroot update-initramfs -u -k all
    rm -f "$CHROOT/usr/sbin/policy-rc.d" "$CHROOT/etc/apt/apt.conf.d/89huginn-build-proxy" "$CHROOT/usr/local/share/huginn-build-ca.crt"
    rm -rf "$CHROOT"/tmp/* "$CHROOT"/var/lib/apt/lists/* "$CHROOT"/var/cache/apt/*.bin \
           "$CHROOT"/var/log/*.log "$CHROOT"/var/log/apt/* "$CHROOT/root/.bash_history"
    : > "$CHROOT/etc/machine-id"
    # (empty folders left under /home by testing in the chroot; /home itself stays)
    [ -d "$CHROOT/home" ] && find "$CHROOT/home" -mindepth 1 -depth -type d -empty -delete
    umount_chroot
}

stage_image() {
    log "Assemble ISO tree"
    rm -rf "$IMAGE"
    mkdir -p "$IMAGE"/{casper,boot/grub,.disk,pool}
    # The installer's GRUB packages: fetched into the chroot by stage_customise, kept in $WORK/pool so that
    # --from image can repack again and again.
    mkdir -p "$WORK/pool"
    if compgen -G "$CHROOT/var/cache/huginn-pool/*.deb" >/dev/null; then
        rm -f "$WORK"/pool/*.deb
        mv "$CHROOT"/var/cache/huginn-pool/*.deb "$WORK/pool/"
    fi
    rmdir "$CHROOT/var/cache/huginn-pool" 2>/dev/null || true
    compgen -G "$WORK/pool/*.deb" >/dev/null || die "no GRUB packages for the installer: run with --from customise"
    cp "$WORK"/pool/*.deb "$IMAGE/pool/"

    local kernel initrd
    kernel="$(find "$CHROOT/boot" -maxdepth 1 -name 'vmlinuz-*' | sort -V | tail -1)"
    initrd="$(find "$CHROOT/boot" -maxdepth 1 -name 'initrd.img-*' | sort -V | tail -1)"
    [[ -n "$kernel" && -n "$initrd" ]] || { echo "Kernel or initrd missing in chroot." >&2; exit 1; }
    cp "$kernel" "$IMAGE/casper/vmlinuz"
    cp "$initrd" "$IMAGE/casper/initrd"

    chroot "$CHROOT" dpkg-query -W --showformat='${Package} ${Version}\n' > "$IMAGE/casper/filesystem.manifest"
    cp "$IMAGE/casper/filesystem.manifest" "$OUT/$(basename "$ISO" .iso).manifest"

    local comp_opts=(-comp "$SQUASHFS_COMP")
    [[ "$SQUASHFS_COMP" == "zstd" ]] && comp_opts+=(-Xcompression-level "$SQUASHFS_LEVEL")
    # Timestamps come from the exported SOURCE_DATE_EPOCH; mksquashfs refuses that plus -mkfs-time/-all-time.
    mksquashfs "$CHROOT" "$IMAGE/casper/filesystem.squashfs" -noappend -all-root \
        -e boot/vmlinuz-* -e boot/initrd.img-* "${comp_opts[@]}"
    du -sx --block-size=1 "$CHROOT" | cut -f1 > "$IMAGE/casper/filesystem.size"

    echo "$DISTRO_NAME $DISTRO_VERSION \"$SUITE\" - $ARCH ($BUILD_ID)" > "$IMAGE/.disk/info"
    cat > "$IMAGE/boot/grub/grub.cfg" <<GRUB
set default=0
set timeout=3
insmod all_video
set gfxpayload=keep

menuentry "$DISTRO_NAME (live)" {
    linux /casper/vmlinuz boot=casper quiet splash ---
    initrd /casper/initrd
}
menuentry "$DISTRO_NAME (safe graphics)" {
    linux /casper/vmlinuz boot=casper nomodeset ---
    initrd /casper/initrd
}
menuentry "$DISTRO_NAME (verbose boot)" {
    linux /casper/vmlinuz boot=casper ---
    initrd /casper/initrd
}
GRUB
    find "$IMAGE" -exec touch -h -d "@$SOURCE_DATE_EPOCH" {} +
}

stage_iso() {
    log "Build ISO"
    mkdir -p "$OUT"
    # grub-mkrescue writes a hybrid image that boots on BIOS and UEFI (not Secure Boot; see README).
    grub-mkrescue -o "$ISO" "$IMAGE" -- \
        -volid "$(echo "${DISTRO_ID}_${DISTRO_VERSION}" | tr '[:lower:].-' '[:upper:]__' | cut -c1-32)" \
        -volume_date all_file_dates "=$SOURCE_DATE_EPOCH"
    (cd "$OUT" && sha256sum "$(basename "$ISO")" > "$(basename "$ISO").sha256")
    log "Done: $ISO ($(du -h "$ISO" | cut -f1))"
}

mkdir -p "$WORK" "$OUT"

case "$FROM" in
    bootstrap) stage_bootstrap ;;
    rootfs)    stage_restore_bootstrap ;;
    customise|image) [[ -d "$CHROOT/usr" ]] || die "no chroot in $CHROOT: run a full build first" ;;
    *) echo "--from takes bootstrap, rootfs, customise or image" >&2; exit 2 ;;
esac

if [[ "$FROM" == "customise" ]]; then
    mount_chroot
    stage_configure_apt                 # the package lists were cleaned away at the end of the last build
    stage_install                       # quick when nothing changed; picks up packages added to the lists since
    stage_customise
    stage_cleanup
elif [[ "$FROM" != "image" ]]; then
    mount_chroot
    stage_configure_apt
    stage_check_packages
    (( CHECK_ONLY )) && exit 0
    stage_install
    stage_customise
    stage_cleanup
fi
stage_image
stage_iso
