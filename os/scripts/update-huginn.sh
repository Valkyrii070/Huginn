#!/usr/bin/env bash
# Refresh vendor/huginn from a Huginn checkout:  scripts/update-huginn.sh /path/to/Huginn
# The build installs whatever is in vendor/huginn, so the browser version in an image is the one
# recorded in vendor/huginn/SOURCE.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="${1:?usage: update-huginn.sh /path/to/Huginn}"
[ -f "$SRC/safari_browser.py" ] || { echo "No safari_browser.py in $SRC"; exit 1; }
rm -rf "$ROOT/vendor/huginn"
mkdir -p "$ROOT/vendor/huginn"
(cd "$SRC" && tar cf - --exclude=.git --exclude='*.bat' --exclude='*.ps1' --exclude='*.command' --exclude=docs \
    --exclude='*_test.py' --exclude=README.md --exclude=python --exclude=.python --exclude=__pycache__ \
    --exclude=test_out .) | (cd "$ROOT/vendor/huginn" && tar xf -)
cp "$SRC/docs/huginn-icon.png" "$ROOT/vendor/huginn/huginn-icon.png"
{
    echo "repo: $(git -C "$SRC" remote get-url origin 2>/dev/null || echo "$SRC")"
    echo "commit: $(git -C "$SRC" rev-parse HEAD 2>/dev/null || echo unknown)"
    echo "date: $(git -C "$SRC" log -1 --format=%cs 2>/dev/null || date +%F)"
} > "$ROOT/vendor/huginn/SOURCE"
echo "vendor/huginn now holds:"; cat "$ROOT/vendor/huginn/SOURCE"
