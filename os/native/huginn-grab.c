/* huginn-grab: a picture of the screen from KWin, for Huginn OS.

   KWin hands out screen pictures (org.kde.KWin.ScreenShot2) only to programs a .desktop file names with
   X-KDE-DBUS-Restricted-Interfaces=org.kde.KWin.ScreenShot2, and it checks the program's own executable. Huginn's apps
   are Python, so they can't be named; this small program is (/usr/share/applications/huginn-grab.desktop), and the
   Screenshot app, the Print key and the screenshot portal ask it.

   huginn-grab OUT            every screen as one picture
   huginn-grab OUT SCREEN     one screen, by its connector name (DP-1, HDMI-A-2…)

   OUT gets a one-line header "HUGINNRAW width height stride format\n" (format: QImage::Format) and then the pixels;
   huginn_capture.py turns it into a PNG. On failure: KWin's reason on stderr, exit status 1.

   Build: cc -O2 -o huginn-grab huginn-grab.c $(pkg-config --cflags --libs gio-2.0 gio-unix-2.0) */
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <gio/gio.h>
#include <gio/gunixfdlist.h>

static guint32 get_u(GVariant *dict, const char *key)
{
    guint32 v = 0;
    if (!g_variant_lookup(dict, key, "u", &v))
        v = 0;
    return v;
}

int main(int argc, char **argv)
{
    if (argc < 2 || argc > 3) {
        fprintf(stderr, "usage: huginn-grab OUT [SCREEN]\n");
        return 2;
    }
    GError *err = NULL;
    GDBusConnection *bus = g_bus_get_sync(G_BUS_TYPE_SESSION, NULL, &err);
    if (!bus) {
        fprintf(stderr, "no session bus: %s\n", err->message);
        return 1;
    }
    int p[2];
    if (pipe2(p, O_CLOEXEC) != 0) {
        fprintf(stderr, "pipe: %s\n", strerror(errno));
        return 1;
    }
    GUnixFDList *fds = g_unix_fd_list_new();
    int handle = g_unix_fd_list_append(fds, p[1], &err);
    close(p[1]);
    if (handle < 0) {
        fprintf(stderr, "fd: %s\n", err->message);
        return 1;
    }
    GVariantBuilder opts;
    g_variant_builder_init(&opts, G_VARIANT_TYPE("a{sv}"));
    g_variant_builder_add(&opts, "{sv}", "include-cursor", g_variant_new_boolean(FALSE));
    g_variant_builder_add(&opts, "{sv}", "native-resolution", g_variant_new_boolean(TRUE));
    GVariant *args = argc == 3 ? g_variant_new("(sa{sv}h)", argv[2], &opts, handle) : g_variant_new("(a{sv}h)", &opts, handle);
    GVariant *res = g_dbus_connection_call_with_unix_fd_list_sync(bus, "org.kde.KWin", "/org/kde/KWin/ScreenShot2",
        "org.kde.KWin.ScreenShot2", argc == 3 ? "CaptureScreen" : "CaptureWorkspace", args, G_VARIANT_TYPE("(a{sv})"),
        G_DBUS_CALL_FLAGS_NONE, 15000, fds, NULL, NULL, &err);
    g_object_unref(fds);
    if (!res) {
        gchar *remote = g_dbus_error_get_remote_error(err);
        g_dbus_error_strip_remote_error(err);
        fprintf(stderr, "KWin said no (%s): %s\n", remote ? remote : "error", err->message);
        close(p[0]);
        return 1;
    }
    GVariant *dict = g_variant_get_child_value(res, 0);
    guint32 w = get_u(dict, "width"), h = get_u(dict, "height"), stride = get_u(dict, "stride"), format = get_u(dict, "format");
    const gchar *type = NULL;
    if (g_variant_lookup(dict, "type", "&s", &type) && strcmp(type, "raw") != 0) {
        fprintf(stderr, "KWin sent a picture of a kind this doesn't read (%s)\n", type);
        return 1;
    }
    if (!w || !h || stride < w) {
        fprintf(stderr, "KWin sent an empty picture\n");
        return 1;
    }
    FILE *out = fopen(argv[1], "wb");
    if (!out) {
        fprintf(stderr, "%s: %s\n", argv[1], strerror(errno));
        return 1;
    }
    fprintf(out, "HUGINNRAW %u %u %u %u\n", w, h, stride, format);
    size_t want = (size_t)stride * h, got = 0;
    char buf[1 << 16];
    while (got < want) {
        ssize_t n = read(p[0], buf, sizeof buf);
        if (n < 0 && errno == EINTR)
            continue;
        if (n <= 0)
            break;
        fwrite(buf, 1, (size_t)n, out);
        got += (size_t)n;
    }
    close(p[0]);
    if (fclose(out) != 0 || got < want) {
        fprintf(stderr, "the picture arrived cut short (%zu of %zu bytes)\n", got, want);
        unlink(argv[1]);
        return 1;
    }
    g_variant_unref(dict);
    g_variant_unref(res);
    return 0;
}
