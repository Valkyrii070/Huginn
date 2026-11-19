#!/bin/sh
# Huginn's Terminal is the system's terminal: x-terminal-emulator runs it.
set -e
update-alternatives --install /usr/bin/x-terminal-emulator x-terminal-emulator /usr/bin/huginn-terminal 60
update-alternatives --set x-terminal-emulator /usr/bin/huginn-terminal

# Programs Huginn's own apps use behind the scenes (Phone uses KDE Connect, Screen Sharing uses FreeRDP, the look uses
# Kvantum) stay out of the start menu: a copy with NoDisplay in /usr/local/share, which comes first, so the
# packages' own files are untouched and the programs still run.
mkdir -p /usr/local/share/applications
for f in org.kde.kdeconnect.app org.kde.kdeconnect.nonplasma org.kde.kdeconnect.sms sdl-freerdp kvantummanager; do
    src=/usr/share/applications/$f.desktop
    [ -f "$src" ] || continue
    grep -v '^NoDisplay=' "$src" | sed '0,/^\[Desktop Entry\]/s//[Desktop Entry]\nNoDisplay=true/' > /usr/local/share/applications/$f.desktop
done
