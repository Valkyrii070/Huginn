#!/bin/sh
# Huginn's own boot screen and sign-in screen.
set -e
# Plymouth: the Huginn theme is the default (the initramfs is rebuilt at the end of the build, with it inside).
update-alternatives --install /usr/share/plymouth/themes/default.plymouth default.plymouth \
    /usr/share/plymouth/themes/huginn/huginn.plymouth 200
update-alternatives --set default.plymouth /usr/share/plymouth/themes/huginn/huginn.plymouth
# SDDM: /etc/sddm.conf.d/10-huginn.conf (from the overlay) picks the Huginn theme; make sure it's there.
test -f /usr/share/sddm/themes/huginn/Main.qml
# The live wallpapers the sign-in screen and the desktop share: a compiled scene and a still for each realm.
for realm in aurora bifrost muspelheim niflheim; do
    test -f "/usr/share/huginn-os/live/$realm.frag.qsb"
    test -f "/usr/share/huginn-os/live/stills/$realm.jpg"
done
test -f /usr/share/huginn-os/live/LiveWallpaper.qml
chmod 755 /usr/libexec/huginn-login-look
# The two sessions: "Huginn" (KWin, huginn.desktop, first in the list) and "Huginn OS (own compositor, preview)"
# (huginnos-preview.desktop: named to sort after it, so it is never the sign-in screen's default).
chmod 755 /usr/bin/huginn-session /usr/bin/huginn-session-preview /usr/libexec/huginn-session-apps
test -f /usr/share/huginn-shell/huginn_compositor.py
test -f /usr/share/huginn-shell/qml/Compositor.qml
# The desktop portal: Open and Save, screenshots and colours, "Allow …?", Open With and settings are Huginn's own.
test -f /usr/share/xdg-desktop-portal/huginn-portals.conf
test -f /usr/share/xdg-desktop-portal/portals/huginn.portal
test -f /usr/share/xdg-desktop-portal/portals/huginn-settings.portal
test -f /usr/share/huginn-apps/qml/PortalPrompt.qml
test -f /usr/share/huginn-apps/qml/PortalShot.qml
# KDE's backend still does screen sharing — but only offers it (and screenshots through KWin, global shortcuts, the
# background list) when XDG_CURRENT_DESKTOP is exactly "KDE", and Huginn's session says "Huginn:KDE". It is started
# through a small wrapper that tells it "KDE" in Huginn's KWin session; its own D-Bus file is set aside (dpkg-divert,
# so package updates keep to the side).
kde_portal=$(dpkg -L xdg-desktop-portal-kde | grep '/libexec/xdg-desktop-portal-kde$' | head -n1)
test -x "$kde_portal"
cat > /usr/libexec/huginn-portal-kde <<EOF2
#!/bin/sh
# KDE's portal backend in Huginn's session: see /usr/share/xdg-desktop-portal/huginn-portals.conf. In the preview
# session (Huginn's own compositor, no KWin) it is left as it is.
[ "\$XDG_SESSION_DESKTOP" = huginn-preview ] || export XDG_CURRENT_DESKTOP=KDE
exec $kde_portal "\$@"
EOF2
chmod 755 /usr/libexec/huginn-portal-kde
svc=/usr/share/dbus-1/services/org.freedesktop.impl.portal.desktop.kde.service
dpkg-divert --local --rename --divert "$svc.kde-original" --add "$svc"
cat > "$svc" <<'EOF2'
[D-BUS Service]
Name=org.freedesktop.impl.portal.desktop.kde
Exec=/usr/libexec/huginn-portal-kde
SystemdService=plasma-xdg-desktop-portal-kde.service
EOF2
mkdir -p /usr/lib/systemd/user/plasma-xdg-desktop-portal-kde.service.d
cat > /usr/lib/systemd/user/plasma-xdg-desktop-portal-kde.service.d/huginn.conf <<'EOF2'
# Huginn: started by systemd, KDE's portal backend goes through the same wrapper (see /usr/libexec/huginn-portal-kde).
[Service]
ExecStart=
ExecStart=/usr/libexec/huginn-portal-kde
EOF2
# The installation drive signs in to Huginn's session, not Plasma's (casper would pick Plasma).
chmod 755 /usr/libexec/huginn-live-session
systemctl enable huginn-live-session.service
