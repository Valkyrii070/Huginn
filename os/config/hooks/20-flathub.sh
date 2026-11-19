#!/bin/sh
# App Store source: add Flathub system-wide and fetch its catalogue so the store can be browsed on first start.
# Needs network during the build. Without it the build goes on: the App Store adds Flathub itself the first time
# it's opened with a connection (huginn_store.py, ensure_flathub).
set -e
if flatpak remote-add --system --if-not-exists flathub https://dl.flathub.org/repo/flathub.flatpakrepo; then
    flatpak update --system --appstream -y flathub || echo "Flathub catalogue not fetched; the store will fetch it on first use."
else
    echo "warning: Flathub not added (no network during the build); the App Store adds it on first use." >&2
fi
