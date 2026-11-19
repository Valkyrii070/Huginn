#!/bin/sh
# Builds xwayland-satellite — X11 apps as windows of their own in Huginn's compositor (the preview session; Qt's
# compositor has no XWayland) — with Huginn's small patch (patches/xwayland-satellite/), into
# vendor/xwayland-satellite/. build.sh runs it when that binary is missing and cargo is installed.
#
# Needs: git, cargo with Rust 1.85 or newer (rustup), clang, libxcb-cursor-dev, and the network (GitHub, crates.io).
set -eu
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VERSION=v0.8.3
OUT="$ROOT/vendor/xwayland-satellite"
SRC="${WORK:-$ROOT/work}/xwayland-satellite-src"
if [ -x "$OUT/xwayland-satellite" ] && [ "$(cat "$OUT/VERSION" 2>/dev/null)" = "$VERSION" ]; then
    echo "xwayland-satellite $VERSION is already built"; exit 0
fi
rm -rf "$SRC"
git clone -q --depth 1 --branch "$VERSION" https://github.com/Supreeeme/xwayland-satellite "$SRC"
for p in "$ROOT"/patches/xwayland-satellite/*.patch; do git -C "$SRC" apply "$p"; done
(cd "$SRC" && cargo build --release --locked)
install -D -m 755 "$SRC/target/release/xwayland-satellite" "$OUT/xwayland-satellite"
install -m 644 "$SRC/LICENSE" "$OUT/LICENSE"
echo "$VERSION" > "$OUT/VERSION"
echo "xwayland-satellite $VERSION built into $OUT"
