#!/usr/bin/env python3
"""Huginn's settings for every app, through the desktop portal (org.freedesktop.impl.portal.Settings).

Apps of every kind (GTK, Qt, Electron, browsers, Flatpaks) ask the desktop portal whether to be dark, what the accent
colour is, and whether to use high contrast or less motion. This answers from Huginn's own settings — the same file
the shell and every Huginn app read (~/.config/huginn-shell/settings.json) — and tells them the moment one changes.
It is small (no window, no Qt) and stays running while you're signed in, so a change reaches apps right away.

KDE's settings backend comes after this one (huginn-portals.conf), so anything Huginn has no opinion on still has an
answer; where both have one, Huginn's wins.
"""
import argparse
import json
import os
import sys
from pathlib import Path

from gi.repository import Gio, GLib

BUS_NAME = "org.freedesktop.impl.portal.desktop.huginn.settings"
OBJECT = "/org/freedesktop/portal/desktop"
XML = """<node><interface name="org.freedesktop.impl.portal.Settings">
  <method name="ReadAll"><arg type="as" name="namespaces" direction="in"/><arg type="a{sa{sv}}" name="value" direction="out"/></method>
  <method name="Read"><arg type="s" name="namespace" direction="in"/><arg type="s" name="key" direction="in"/><arg type="v" name="value" direction="out"/></method>
  <signal name="SettingChanged"><arg type="s" name="namespace"/><arg type="s" name="key"/><arg type="v" name="value"/></signal>
  <property name="version" type="u" access="read"/>
</interface></node>"""

CONFIG = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "huginn-shell" / "settings.json"
TOKENS = [Path(__file__).resolve().parent.parent / "tokens" / "tokens.json", Path("/usr/share/huginn-os/tokens.json")]
DEFAULTS = {"dark": "true", "realm": "aurora", "contrast": "false", "reduceMotion": "false", "uiScale": "1"}


def hex_rgb(colour: str) -> tuple:
    c = colour.lstrip("#")
    return tuple(int(c[i:i + 2], 16) / 255.0 for i in (0, 2, 4)) if len(c) >= 6 else (0.26, 0.85, 0.72)


def named_accent(colour: str) -> str:
    """GNOME's nearest named accent (libadwaita apps take only these)."""
    import colorsys
    r, g, b = hex_rgb(colour)
    h, _l, sat = colorsys.rgb_to_hls(r, g, b)
    if sat < 0.15:
        return "slate"
    deg = h * 360
    for upto, name in ((15, "red"), (40, "orange"), (65, "yellow"), (150, "green"), (195, "teal"), (250, "blue"), (290, "purple"), (340, "pink")):
        if deg < upto:
            return name
    return "red"


def read_settings(path: Path = CONFIG) -> dict:
    values = dict(DEFAULTS)
    try:
        saved = json.loads(path.read_text(encoding="utf-8"))
        values.update({k: str(v) for k, v in saved.items() if k in DEFAULTS})
    except (OSError, ValueError, AttributeError):
        pass
    return values


def load_realms() -> dict:
    for p in TOKENS:
        try:
            return json.loads(p.read_text(encoding="utf-8")).get("realms", {})
        except (OSError, ValueError):
            continue
    return {}


def answers(values: dict, realms: dict) -> dict:
    """{namespace: {key: GLib.Variant}}: what Huginn says, worked out from its settings."""
    dark = values["dark"] == "true"
    contrast = values["contrast"] == "true"
    still = values["reduceMotion"] == "true"
    realm = realms.get(values["realm"]) or next(iter(realms.values()), {})
    accent = (realm.get("dark" if dark else "light") or {}).get("accent", "#43D9B8")
    try:
        scale = float(values["uiScale"])
    except ValueError:
        scale = 1.0
    gtk = "Breeze" if not contrast else ("HighContrastInverse" if dark else "HighContrast")   # in Huginn's colours (huginn_look.py)
    return {
        "org.freedesktop.appearance": {
            "color-scheme": GLib.Variant("u", 1 if dark else 2),           # 1: prefer dark, 2: prefer light
            "accent-color": GLib.Variant("(ddd)", hex_rgb(accent)),
            "contrast": GLib.Variant("u", 1 if contrast else 0),
            "reduced-motion": GLib.Variant("u", 1 if still else 0),
        },
        # What GTK reads through the portal outside GNOME: the theme (Breeze-GTK, which huginn_look.py gives Huginn's
        # colours), the font, motion.
        "org.gnome.desktop.interface": {
            "color-scheme": GLib.Variant("s", "prefer-dark" if dark else "prefer-light"),
            "gtk-theme": GLib.Variant("s", gtk),
            "font-name": GLib.Variant("s", "Inter Variable 10"),
            "document-font-name": GLib.Variant("s", "Inter Variable 11"),
            "monospace-font-name": GLib.Variant("s", "JetBrains Mono 10"),
            "enable-animations": GLib.Variant("b", not still),
            "text-scaling-factor": GLib.Variant("d", scale),
            "accent-color": GLib.Variant("s", named_accent(accent)),
        },
        "org.gnome.desktop.a11y.interface": {"high-contrast": GLib.Variant("b", contrast)},
        "org.gnome.desktop.wm.preferences": {"button-layout": GLib.Variant("s", "close,minimize,maximize:")},
    }


def wanted(namespace: str, patterns: list) -> bool:
    if not patterns or patterns == [""]:
        return True
    for p in patterns:
        if p == namespace or (p.endswith(".*") and namespace.startswith(p[:-1])) or (p.endswith("*") and namespace.startswith(p[:-1])):
            return True
    return False


class SettingsPortal:
    def __init__(self, conn, path: Path = CONFIG):
        self.conn, self.path = conn, path
        self.realms = load_realms()
        self.now = answers(read_settings(path), self.realms)
        node = Gio.DBusNodeInfo.new_for_xml(XML)
        conn.register_object(OBJECT, node.interfaces[0], self._call, self._get, None)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.monitor = Gio.File.new_for_path(str(path.parent)).monitor_directory(Gio.FileMonitorFlags.WATCH_MOVES, None)
        self.monitor.set_rate_limit(200)
        self.monitor.connect("changed", lambda *a: self._reread())

    def _get(self, conn, sender, path, iface, prop):
        return GLib.Variant("u", 2) if prop == "version" else None

    def _call(self, conn, sender, path, iface, method, params, inv):
        if method == "ReadAll":
            (patterns,) = params.unpack()
            out = {ns: keys for ns, keys in self.now.items() if wanted(ns, patterns)}
            inv.return_value(GLib.Variant.new_tuple(self._pack(out)))
        elif method == "Read":
            ns, key = params.unpack()
            value = self.now.get(ns, {}).get(key)
            if value is None:
                inv.return_dbus_error("org.freedesktop.portal.Error.NotFound", "Requested setting not found")
            else:
                inv.return_value(GLib.Variant.new_tuple(GLib.Variant("v", value)))
        else:
            inv.return_dbus_error("org.freedesktop.DBus.Error.UnknownMethod", method)

    @staticmethod
    def _pack(tree: dict) -> GLib.Variant:
        b = GLib.VariantBuilder.new(GLib.VariantType("a{sa{sv}}"))
        for ns, keys in tree.items():
            inner = GLib.VariantBuilder.new(GLib.VariantType("a{sv}"))
            for k, v in keys.items():
                inner.add_value(GLib.Variant.new_dict_entry(GLib.Variant("s", k), GLib.Variant("v", v)))
            b.add_value(GLib.Variant.new_dict_entry(GLib.Variant("s", ns), inner.end()))
        return b.end()

    def _reread(self) -> None:
        new = answers(read_settings(self.path), self.realms)
        for ns, keys in new.items():
            for k, v in keys.items():
                old = self.now.get(ns, {}).get(k)
                if old is None or not old.equal(v):
                    self.conn.emit_signal(None, OBJECT, "org.freedesktop.impl.portal.Settings", "SettingChanged",
                                          GLib.Variant("(ssv)", (ns, k, v)))
        self.now = new


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--print", action="store_true", help="show what apps are told, and leave")
    args = ap.parse_args()
    if args.print:
        for ns, keys in answers(read_settings(), load_realms()).items():
            for k, v in keys.items():
                print(f"{ns} {k} = {v.print_(False)}")
        return 0
    conn = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    SettingsPortal(conn)
    got = conn.call_sync("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus", "RequestName",
                         GLib.Variant("(su)", (BUS_NAME, 4)), GLib.VariantType("(u)"), 0, 5000, None)
    if got.unpack()[0] not in (1, 4):
        return 0
    GLib.MainLoop().run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
