#!/usr/bin/env python3
"""Draw the app icons for every Huginn OS app.

    python3 scripts/make-icons.py            # writes the icons into the image's icon folder
    python3 scripts/make-icons.py --sheet F  # also writes one picture F showing them all

Each icon is a rounded tile in the app's own colour (tokens/tokens.json) with a white picture of what the app is
for. They are written as SVG (hicolor/scalable) and as PNG at 256, 128, 64 and 48 pixels, named huginn-<app>, which
is what the .desktop files and the dock ask for. It also renders the two marks kept in branding/: huginn-os (the
system's own logo) and huginn-browser. The pictures are drawn here, by hand, in SVG; nothing is traced or
borrowed. Change a picture below and run this again.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "config" / "overlay" / "usr" / "share" / "icons" / "hicolor"

# The picture on each tile. "W" parts are white; {c} is the app's deep colour, for details cut into the white.
W = 'fill="#fff"'
PICS = {
    "files": f'<path {W} opacity=".72" d="M56 96a14 14 0 0 1 14-14h38l14 16h64a14 14 0 0 1 14 14v10H56z"/><rect {W} x="56" y="110" width="144" height="80" rx="14"/>',
    "calendar": f'<rect {W} x="60" y="68" width="136" height="128" rx="20"/><path fill="{{c}}" d="M60 88a20 20 0 0 1 20-20h96a20 20 0 0 1 20 20v18H60z"/>'
                f'<rect {W} x="88" y="54" width="12" height="30" rx="6"/><rect {W} x="156" y="54" width="12" height="30" rx="6"/>'
                + "".join(f'<circle fill="{{c}}" opacity="{0.9 if (i, j) == (1, 0) else 0.35}" cx="{92 + i * 36}" cy="{132 + j * 34}" r="10"/>' for j in range(2) for i in range(3)),
    "mail": f'<rect {W} x="52" y="78" width="152" height="104" rx="18"/><path fill="none" stroke="{{c}}" stroke-width="11" stroke-linecap="round" stroke-linejoin="round" d="M68 98l60 44 60-44"/>',
    "settings": "".join(f'<rect {W} x="116" y="52" width="24" height="40" rx="8" transform="rotate({a} 128 128)"/>' for a in range(0, 360, 45))
                + f'<circle {W} cx="128" cy="128" r="50"/><circle fill="{{c}}" cx="128" cy="128" r="20"/>',
    "monitor": f'<path fill="none" stroke="#fff" stroke-width="13" stroke-linecap="round" stroke-linejoin="round" d="M52 136h30l16-44 24 84 20-58 12 18h50"/>',
    "store": f'<path fill="none" stroke="#fff" stroke-width="12" stroke-linecap="round" d="M98 102V90a30 30 0 0 1 60 0v12"/><path {W} d="M70 98h116l10 86a12 12 0 0 1-12 14H72a12 12 0 0 1-12-14z"/>'
             f'<circle fill="{{c}}" cx="100" cy="124" r="8"/><circle fill="{{c}}" cx="156" cy="124" r="8"/>',
    "video": f'<rect {W} x="52" y="80" width="152" height="96" rx="20"/><path fill="{{c}}" d="M114 104l40 24-40 24z"/>',
    "music": f'<path {W} d="M104 82l84-16v22l-84 16z"/><rect {W} x="104" y="90" width="12" height="86"/><rect {W} x="176" y="76" width="12" height="86"/><ellipse {W} cx="96" cy="176" rx="22" ry="17"/><ellipse {W} cx="168" cy="162" rx="22" ry="17"/>',
    "notes": f'<path {W} d="M80 56h96a16 16 0 0 1 16 16v88l-40 40H80a16 16 0 0 1-16-16V72a16 16 0 0 1 16-16z"/><path fill="{{c}}" opacity=".35" d="M152 200v-28a12 12 0 0 1 12-12h28z"/>'
             + "".join(f'<rect fill="{{c}}" opacity=".8" x="86" y="{84 + i * 24}" width="{[84, 84, 52][i]}" height="10" rx="5"/>' for i in range(3)),
    "photos": f'<circle {W} opacity=".95" cx="170" cy="94" r="16"/><path {W} d="M48 190l52-80 34 46 20-24 54 58z"/>',
    "documents": f'<path {W} d="M86 52h56l42 42v98a14 14 0 0 1-14 14H86a14 14 0 0 1-14-14V66a14 14 0 0 1 14-14z"/><path fill="{{c}}" opacity=".4" d="M142 52v30a12 12 0 0 0 12 12h30z"/>'
                 + "".join(f'<rect fill="{{c}}" opacity=".75" x="92" y="{118 + i * 22}" width="{[72, 72, 44][i]}" height="9" rx="4.5"/>' for i in range(3)),
    "calculator": f'<rect {W} x="72" y="50" width="112" height="156" rx="20"/><rect fill="{{c}}" x="88" y="66" width="80" height="34" rx="8"/>'
                  + "".join(f'<circle fill="{{c}}" opacity="{1 if (i, j) == (2, 2) else 0.55}" cx="{100 + i * 28}" cy="{124 + j * 26}" r="9"/>' for j in range(3) for i in range(3)),
    "clock": f'<circle {W} cx="128" cy="128" r="70"/><path fill="none" stroke="{{c}}" stroke-width="11" stroke-linecap="round" d="M128 84v44l30 18"/><circle fill="{{c}}" cx="128" cy="128" r="8"/>',
    "terminal": f'<rect fill="#0E1319" x="44" y="66" width="168" height="124" rx="20"/><path fill="none" stroke="#fff" stroke-width="12" stroke-linecap="round" stroke-linejoin="round" d="M72 104l28 24-28 24"/><rect {W} x="116" y="146" width="52" height="12" rx="6"/>',
    "screenshot": f'<path fill="none" stroke="#fff" stroke-width="13" stroke-linecap="round" stroke-linejoin="round" d="M60 96V76a16 16 0 0 1 16-16h20M160 60h20a16 16 0 0 1 16 16v20M196 160v20a16 16 0 0 1-16 16h-20M96 196H76a16 16 0 0 1-16-16v-20"/><circle {W} cx="128" cy="128" r="24"/>',
    "archives": f'<rect {W} x="64" y="102" width="128" height="90" rx="14"/><rect {W} opacity=".8" x="52" y="68" width="152" height="40" rx="12"/>'
                + "".join(f'<rect fill="{{c}}" x="{122 if i % 2 else 126}" y="{78 + i * 16}" width="10" height="9" rx="3"/>' for i in range(6)),
    "welcome": f'<path {W} d="M128 48c9 46 34 71 80 80-46 9-71 34-80 80-9-46-34-71-80-80 46-9 71-34 80-80z"/><circle {W} opacity=".8" cx="190" cy="70" r="10"/>',
    "writer": f'<path {W} d="M156 58l42 42-96 96-50 8 8-50z"/><path fill="none" stroke="{{c}}" stroke-width="9" stroke-linecap="round" d="M138 78l40 40"/><path fill="{{c}}" d="M52 204l6-36 30 30z"/>',
    "sheets": f'<rect {W} x="52" y="64" width="152" height="128" rx="18"/><path fill="{{c}}" opacity=".3" d="M52 82a18 18 0 0 1 18-18h116a18 18 0 0 1 18 18v20H52z"/>'
              f'<path fill="none" stroke="{{c}}" stroke-width="7" opacity=".8" d="M52 102h152M52 146h152M102 64v128M154 64v128"/>',
    "slides": f'<rect {W} x="48" y="62" width="160" height="104" rx="16"/><rect {W} x="122" y="162" width="12" height="30"/><rect {W} x="92" y="188" width="72" height="12" rx="6"/>'
              + "".join(f'<rect fill="{{c}}" opacity=".85" x="{80 + i * 28}" y="{142 - h}" width="16" height="{h}" rx="4"/>' for i, h in enumerate([28, 46, 36, 58])),
    "passwords": f'<circle fill="none" stroke="#fff" stroke-width="18" cx="96" cy="128" r="32"/><rect {W} x="124" y="119" width="88" height="18" rx="9"/><rect {W} x="172" y="130" width="14" height="28" rx="5"/><rect {W} x="196" y="130" width="14" height="20" rx="5"/>',
    "contacts": f'<circle {W} cx="128" cy="100" r="34"/><path {W} d="M64 200a64 54 0 0 1 128 0z"/>',
    "weather": f'<circle fill="#FFE08A" cx="100" cy="100" r="34"/><circle {W} cx="108" cy="164" r="30"/><circle {W} cx="150" cy="148" r="40"/><circle {W} cx="186" cy="168" r="26"/><rect {W} x="108" y="166" width="78" height="28"/>',
    "backup": f'<path fill="none" stroke="#fff" stroke-width="15" stroke-linecap="round" d="M128 70a58 58 0 1 1-54 37"/><path {W} d="M134 42l-38 26 36 28z"/><path fill="none" stroke="#fff" stroke-width="11" stroke-linecap="round" stroke-linejoin="round" d="M128 104v26l18 12"/>',
    "disks": f'<circle {W} cx="128" cy="128" r="72"/><circle fill="{{c}}" opacity=".25" cx="128" cy="128" r="50"/><circle fill="{{c}}" cx="128" cy="128" r="22"/><circle {W} cx="128" cy="128" r="7"/>',
    "camera": f'<rect {W} x="98" y="66" width="60" height="30" rx="10"/><rect {W} x="48" y="84" width="160" height="110" rx="22"/><circle fill="{{c}}" cx="128" cy="140" r="34"/><circle {W} opacity=".45" cx="128" cy="140" r="16"/><circle fill="{{c}}" cx="184" cy="106" r="7"/>',
    "recorder": f'<rect {W} x="102" y="48" width="52" height="94" rx="26"/><path fill="none" stroke="#fff" stroke-width="13" stroke-linecap="round" d="M80 124a48 48 0 0 0 96 0"/><rect {W} x="122" y="170" width="12" height="26"/><rect {W} x="98" y="192" width="60" height="13" rx="6.5"/>',
    "reminders": f'<circle {W} cx="84" cy="90" r="17"/><path fill="none" stroke="{{c}}" stroke-width="7" stroke-linecap="round" stroke-linejoin="round" d="M76 90l6 7 11-13"/>'
                 + "".join(f'<circle fill="none" stroke="#fff" stroke-width="9" cx="84" cy="{y}" r="13"/>' for y in (130, 170))
                 + "".join(f'<rect {W} opacity="{o}" x="114" y="{y}" width="{w}" height="14" rx="7"/>' for y, w, o in ((83, 82, 0.6), (123, 82, 1), (163, 56, 1))),
    "phone": f'<rect {W} x="84" y="44" width="88" height="168" rx="22"/><rect fill="{{c}}" x="96" y="64" width="64" height="118" rx="10"/><rect {W} opacity=".5" x="112" y="76" width="32" height="8" rx="4"/><circle fill="{{c}}" cx="128" cy="196" r="7"/>',
    "print": f'<rect {W} opacity=".8" x="84" y="52" width="88" height="48" rx="8"/><rect {W} x="48" y="92" width="160" height="76" rx="18"/><circle fill="{{c}}" cx="182" cy="116" r="7"/>'
             f'<rect {W} stroke="{{c}}" stroke-width="5" x="80" y="140" width="96" height="64" rx="8"/><rect fill="{{c}}" opacity=".7" x="96" y="160" width="64" height="8" rx="4"/><rect fill="{{c}}" opacity=".7" x="96" y="178" width="40" height="8" rx="4"/>',
    "maps": f'<path {W} d="M128 46a54 54 0 0 1 54 54c0 40-54 110-54 110S74 140 74 100a54 54 0 0 1 54-54z"/><circle fill="{{c}}" cx="128" cy="100" r="21"/>',
    "podcasts": f'<path fill="none" stroke="#fff" stroke-width="13" stroke-linecap="round" d="M82 158a58 58 0 1 1 92 0"/><path fill="none" stroke="#fff" stroke-width="13" stroke-linecap="round" d="M104 142a31 31 0 1 1 48 0"/><circle {W} cx="128" cy="122" r="13"/><rect {W} x="119" y="146" width="18" height="62" rx="9"/>',
    "books": f'<path {W} d="M124 84c-22-16-46-18-72-10v104c26-8 50-6 72 10z"/><path {W} opacity=".8" d="M132 84c22-16 46-18 72-10v104c-26-8-50-6-72 10z"/>'
             + "".join(f'<path fill="none" stroke="{{c}}" stroke-width="6" stroke-linecap="round" opacity=".7" d="M70 {y}c14-3 26-2 38 3"/>' for y in (102, 124, 146)),
    "games": f'<path {W} d="M84 84h88c38 0 56 36 56 68 0 34-30 42-48 20l-12-16H88l-12 16c-18 22-48 14-48-20 0-32 18-68 56-68z"/><rect fill="{{c}}" x="62" y="114" width="44" height="13" rx="6.5"/><rect fill="{{c}}" x="77.5" y="98.500" width="13" height="44" rx="6.5"/><circle fill="{{c}}" cx="160" cy="130" r="9"/><circle fill="{{c}}" cx="184" cy="110" r="9"/>',
    "translate": f'<rect {W} x="44" y="56" width="104" height="92" rx="18"/><path fill="none" stroke="{{c}}" stroke-width="10" stroke-linecap="round" stroke-linejoin="round" d="M76 126l20-48 20 48M83 110h26"/>'
                 f'<rect {W} opacity=".88" x="108" y="112" width="104" height="92" rx="18"/><path fill="none" stroke="{{c}}" stroke-width="9" stroke-linecap="round" stroke-linejoin="round" d="M134 140h52M160 130v10M144 184c16-10 26-24 30-44M178 184c-12-6-22-16-28-28"/>',
    "authenticator": f'<path {W} d="M128 42l68 26v50c0 46-28 78-68 96-40-18-68-50-68-96V68z"/><circle fill="none" stroke="{{c}}" stroke-width="11" cx="128" cy="124" r="34"/><path fill="none" stroke="{{c}}" stroke-width="10" stroke-linecap="round" stroke-linejoin="round" d="M128 104v20l14 10"/>',
    "messages": f'<path {W} opacity=".78" d="M116 112h60a34 34 0 0 1 34 34v14a34 34 0 0 1-34 34h-4l8 18-30-18h-34a34 34 0 0 1-34-34v-14a34 34 0 0 1 34-34z"/>'
                f'<path {W} d="M80 52h70a36 36 0 0 1 36 36v16a36 36 0 0 1-36 36h-38l-34 22 8-22h-6a36 36 0 0 1-36-36V88a36 36 0 0 1 36-36z"/>'
                + "".join(f'<circle fill="{{c}}" cx="{x}" cy="96" r="8"/>' for x in (92, 115, 138)),
    "privacy": f'<path {W} d="M40 128c26-42 58-62 88-62s62 20 88 62c-26 42-58 62-88 62s-62-20-88-62z"/><circle fill="{{c}}" cx="128" cy="128" r="32"/><circle {W} cx="140" cy="116" r="9"/>',
    "feeds": f'<rect {W} x="50" y="54" width="156" height="148" rx="18"/><rect fill="{{c}}" x="70" y="74" width="116" height="18" rx="5"/>'
             f'<rect fill="{{c}}" opacity=".85" x="70" y="104" width="54" height="42" rx="6"/>'
             + "".join(f'<rect fill="{{c}}" opacity=".55" x="{x}" y="{y}" width="{w}" height="8" rx="4"/>' for x, y, w in ((134, 106, 52), (134, 122, 52), (134, 138, 40), (70, 160, 116), (70, 176, 116))),
    "clips": f'<rect {W} x="50" y="58" width="156" height="140" rx="20"/>'
             + "".join(f'<rect fill="{{c}}" x="{x}" y="{y}" width="12" height="16" rx="4"/>' for x in (62, 182) for y in (72, 100, 128, 156))
             + f'<path fill="{{c}}" d="M112 100l46 28-46 28z"/>',
    "shortcuts": f'<path {W} d="M146 36L74 140h46l-14 80 78-110h-48z"/>',
    "money": f'<rect {W} opacity=".72" x="66" y="54" width="118" height="44" rx="12"/><rect {W} x="42" y="80" width="172" height="122" rx="24"/>'
             f'<rect fill="{{c}}" x="146" y="118" width="68" height="46" rx="16"/><circle {W} cx="170" cy="141" r="9"/>',
    "characters": f'<circle {W} cx="128" cy="128" r="80"/><circle fill="{{c}}" cx="100" cy="110" r="11"/><circle fill="{{c}}" cx="156" cy="110" r="11"/>'
                  f'<path fill="none" stroke="{{c}}" stroke-width="12" stroke-linecap="round" d="M90 148c22 30 54 30 76 0"/>',
    "fonts": f'<path {W} d="M114 48h28l64 156h-34l-14-36h-60l-14 36H50z"/><path fill="{{c}}" d="M128 96l-20 50h40z"/>'
             f'<rect {W} x="40" y="196" width="60" height="12" rx="6"/><rect {W} x="156" y="196" width="60" height="12" rx="6"/>',
    "sharing": f'<rect {W} x="44" y="62" width="168" height="114" rx="18"/><rect {W} x="116" y="174" width="24" height="18"/><rect {W} x="88" y="190" width="80" height="14" rx="7"/>'
               f'<path fill="none" stroke="{{c}}" stroke-width="12" stroke-linecap="round" stroke-linejoin="round" d="M128 152v-58M104 116l24-24 24 24"/>',
    "help": f'<circle {W} cx="128" cy="128" r="80"/><path fill="none" stroke="{{c}}" stroke-width="17" stroke-linecap="round" stroke-linejoin="round" d="M102 106a26 26 0 1 1 38 24c-9 5-12 11-12 22"/><circle fill="{{c}}" cx="128" cy="182" r="11"/>',
    "easel": f'<path {W} d="M124 54c-48 0-84 31-84 72 0 39 31 68 68 68 15 0 19-10 15-21-4-11 2-21 15-21h24c31 0 52-21 52-46 0-31-40-52-90-52z"/>'
             f'<circle fill="{{c}}" cx="126" cy="168" r="0"/><circle fill="{{c}}" opacity=".95" cx="90" cy="112" r="13"/><circle fill="{{c}}" opacity=".7" cx="124" cy="88" r="12"/>'
             f'<circle fill="{{c}}" opacity=".45" cx="162" cy="96" r="11"/><circle fill="{{c}}" opacity=".85" cx="84" cy="150" r="11"/>'
             f'<rect {W} x="168" y="92" width="16" height="96" rx="8" transform="rotate(38 176 140)"/><path fill="{{c}}" d="M136 186c4-14 14-22 24-20l8 7c-2 12-14 20-32 13z"/>',
    "scan": f'<path {W} d="M80 40h70l42 42v130a14 14 0 0 1-14 14H80a14 14 0 0 1-14-14V54a14 14 0 0 1 14-14z"/><path fill="{{c}}" opacity=".35" d="M150 40v30a12 12 0 0 0 12 12h30z"/>'
            + "".join(f'<rect fill="{{c}}" opacity=".3" x="86" y="{y}" width="{w}" height="9" rx="4.5"/>' for y, w in ((96, 56), (150, 84), (170, 70), (190, 80)))
            + f'<rect fill="{{c}}" x="40" y="118" width="176" height="14" rx="7"/><rect {W} opacity=".9" x="52" y="122" width="152" height="6" rx="3"/>',
    "machines": f'<rect {W} opacity=".55" x="76" y="46" width="146" height="100" rx="18"/><rect {W} x="40" y="78" width="158" height="108" rx="18"/>'
                f'<rect fill="{{c}}" x="54" y="92" width="130" height="80" rx="9"/><path fill="none" stroke="#fff" stroke-width="10" stroke-linecap="round" stroke-linejoin="round" d="M74 116l18 16-18 16M104 150h30"/>'
                f'<rect {W} x="104" y="186" width="30" height="16" rx="3"/><rect {W} x="80" y="198" width="78" height="12" rx="6"/>',
    "tempo": f'<path fill="none" stroke="#fff" stroke-width="11" stroke-linecap="round" stroke-linejoin="round" d="M42 84h24l12-28 18 52 16-40 14 28 10-12h78"/>'
              f'<rect {W} x="42" y="118" width="172" height="94" rx="16"/>'
              + "".join(f'<rect fill="{{c}}" opacity=".35" x="{42 + 172 * i / 7 - 1.5:.1f}" y="118" width="3" height="94"/>' for i in range(1, 7))
              + "".join(f'<rect fill="{{c}}" x="{42 + 172 * i / 7 - 9:.1f}" y="118" width="18" height="54" rx="4"/>' for i in (1, 2, 4, 5, 6)),
    "code": f'<rect {W} x="40" y="58" width="176" height="140" rx="22"/><path fill="none" stroke="{{c}}" stroke-width="13" stroke-linecap="round" stroke-linejoin="round" d="M102 98l-30 30 30 30M154 98l30 30-30 30M138 88l-20 80"/>',
}


def mix(a: str, b: str, t: float) -> str:
    pa, pb = (int(a[i:i + 2], 16) for i in (1, 3, 5)), (int(b[i:i + 2], 16) for i in (1, 3, 5))
    return "#" + "".join(f"{round(x + (y - x) * t):02X}" for x, y in zip(pa, pb))


def icon(app: str, bright: str, deep: str) -> str:
    top, bottom = mix(bright, deep, 0.18), mix(deep, "#000000", 0.08)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256" width="256" height="256">'
            f'<defs><linearGradient id="g" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{top}"/><stop offset="1" stop-color="{bottom}"/></linearGradient>'
            f'<linearGradient id="s" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#fff" stop-opacity=".34"/><stop offset=".5" stop-color="#fff" stop-opacity="0"/></linearGradient>'
            f'<filter id="d" x="-20%" y="-20%" width="140%" height="150%"><feDropShadow dx="0" dy="5" stdDeviation="6" flood-color="#000" flood-opacity=".22"/></filter></defs>'
            f'<rect x="14" y="14" width="228" height="228" rx="56" fill="url(#g)"/><rect x="14" y="14" width="228" height="228" rx="56" fill="url(#s)"/>'
            f'<rect x="15.5" y="15.5" width="225" height="225" rx="54.5" fill="none" stroke="#fff" stroke-opacity=".22" stroke-width="3"/>'
            f'<g filter="url(#d)">{PICS[app].replace("{c}", mix(deep, "#000000", 0.12))}</g></svg>\n')


def main() -> int:
    colours = json.loads((ROOT / "tokens" / "tokens.json").read_text(encoding="utf-8"))

    def find(node):
        if isinstance(node, dict):
            if isinstance(node.get("weather"), list):
                return node
            for value in node.values():
                hit = find(value)
                if hit is not None:
                    return hit
    colours = find(colours)
    missing = sorted(set(k for k in colours if not k.startswith("_")) ^ set(PICS))
    if missing:
        print("These apps have a colour but no picture, or the other way round:", ", ".join(missing))
        return 1
    from PySide6.QtCore import QByteArray, QRectF, Qt
    from PySide6.QtGui import QGuiApplication, QImage, QPainter
    from PySide6.QtSvg import QSvgRenderer
    app = QGuiApplication.instance() or QGuiApplication(["icons", "-platform", "offscreen"])      # noqa: F841
    made = {}
    for name in PICS:
        svg = icon(name, *colours[name])
        (OUT / "scalable" / "apps").mkdir(parents=True, exist_ok=True)
        (OUT / "scalable" / "apps" / f"huginn-{name}.svg").write_text(svg, encoding="utf-8")
        draw = QSvgRenderer(QByteArray(svg.encode("utf-8")))
        if not draw.isValid():
            print(f"The picture for {name} isn't valid SVG.")
            return 1
        for size in (256, 128, 64, 48):
            img = QImage(size, size, QImage.Format_ARGB32_Premultiplied)
            img.fill(Qt.transparent)
            painter = QPainter(img)
            painter.setRenderHint(QPainter.Antialiasing)
            draw.render(painter, QRectF(0, 0, size, size))
            painter.end()
            folder = OUT / f"{size}x{size}" / "apps"
            folder.mkdir(parents=True, exist_ok=True)
            img.save(str(folder / f"huginn-{name}.png"))
            if size == 128:
                made[name] = img
    # The two marks: Huginn OS itself, and the Huginn browser. Their artwork lives in branding/ (the raven is the
    # browser's own); each has a plainer version for 32 pixels and below.
    for name in ("huginn-os", "huginn-browser"):
        art, small = ROOT / "branding" / f"{name}.svg", ROOT / "branding" / f"{name}-small.svg"
        (OUT / "scalable" / "apps" / f"{name}.svg").write_text(art.read_text(encoding="utf-8"), encoding="utf-8")
        for size in (512, 256, 128, 64, 48, 32, 24, 16):
            draw = QSvgRenderer(str(small if size <= 32 else art))
            img = QImage(size, size, QImage.Format_ARGB32_Premultiplied)
            img.fill(Qt.transparent)
            painter = QPainter(img)
            painter.setRenderHint(QPainter.Antialiasing)
            draw.render(painter, QRectF(0, 0, size, size))
            painter.end()
            folder = OUT / f"{size}x{size}" / "apps"
            folder.mkdir(parents=True, exist_ok=True)
            img.save(str(folder / f"{name}.png"))
            if size == 128:
                made[name] = img
    print(f"Drew {len(made)} icons into {OUT}")
    if "--sheet" in sys.argv:
        target, cols = sys.argv[sys.argv.index("--sheet") + 1], 7
        rows = -(-len(made) // cols)
        sheet = QImage(cols * 150 + 30, rows * 150 + 30, QImage.Format_RGB32)
        sheet.fill(0x15181C)
        painter = QPainter(sheet)
        for i, img in enumerate(made.values()):
            painter.drawImage(26 + (i % cols) * 150, 26 + (i // cols) * 150, img)
        painter.end()
        sheet.save(target)
    return 0


if __name__ == "__main__":
    sys.exit(main())
