#!/usr/bin/env python3
"""Draw the app icons for every Huginn OS app.

    python3 scripts/make-icons.py            # writes the icons into the image's icon folder
    python3 scripts/make-icons.py --sheet F  # also writes one picture F showing them all

Each icon is a tile of smoked glass (a squircle) with a picture of what the app is for, glowing in the app's own colour
(tokens/tokens.json): the colour rises from deep at its foot to light at its top, glossy across its upper half, with a
soft halo of it on the glass. The tile is thick glass: a lit top edge, a darker foot, a shadow under it, and along its
bottom edge a thin line of the app's colour, as the dock's Ring. (Chosen on the design canvas, round 22: "smoked glass,
all together, without the spark".) They are written as SVG (hicolor/scalable) and as PNG at 256, 128, 64 and 48
pixels, named huginn-<app>, which is what the .desktop files and the dock ask for. It also renders the two marks kept in branding/: huginn-os (the
system's own logo) and huginn-browser. The pictures are drawn here, by hand, in SVG; nothing is traced or
borrowed. Change a picture below and run this again.
"""
import json
import re
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


# Richer pictures for the apps seen most (the dock's, and a few more): the same subjects with more to them.
DETAIL = {
    "files": f'<path {W} opacity=".55" d="M56 96a14 14 0 0 1 14-14h38l14 16h64a14 14 0 0 1 14 14v10H56z"/>'
             f'<rect {W} opacity=".9" x="78" y="92" width="96" height="40" rx="6" transform="rotate(-6 126 112)"/><rect fill="{{c}}" opacity=".5" x="90" y="104" width="52" height="6" rx="3" transform="rotate(-6 126 112)"/>'
             f'<rect {W} x="56" y="114" width="144" height="80" rx="14"/><rect fill="{{c}}" opacity=".55" x="104" y="128" width="48" height="8" rx="4"/>',
    "mail": f'<rect {W} x="52" y="78" width="152" height="104" rx="18"/><path fill="none" opacity=".25" d="M58 172l50-40M198 172l-50-40" stroke="{{c}}" stroke-width="6" stroke-linecap="round"/>'
            f'<path fill="none" stroke="{{c}}" stroke-width="11" stroke-linecap="round" stroke-linejoin="round" d="M68 98l60 44 60-44"/>'
            f'<rect fill="{{c}}" opacity=".45" x="104" y="158" width="48" height="7" rx="3.5"/><rect fill="{{c}}" opacity=".3" x="112" y="170" width="32" height="6" rx="3"/>',
    "calendar": f'<rect {W} x="60" y="68" width="136" height="128" rx="20"/><path fill="{{c}}" d="M60 88a20 20 0 0 1 20-20h96a20 20 0 0 1 20 20v18H60z"/>'
                f'<rect {W} x="88" y="54" width="12" height="30" rx="6"/><rect {W} x="156" y="54" width="12" height="30" rx="6"/>'
                f'<text x="128" y="174" text-anchor="middle" font-family="Inter, Inter Variable, sans-serif" font-weight="700" font-size="64" fill="{{c}}">16</text>',
    "photos": f'<rect {W} opacity=".45" x="70" y="58" width="120" height="104" rx="12" transform="rotate(-8 130 110)"/>'
              f'<rect {W} x="52" y="80" width="152" height="116" rx="16"/><path fill="{{c}}" d="M64 184l40-52 28 34 18-20 42 38z"/><circle fill="{{c}}" cx="168" cy="110" r="12"/>',
    "music": f'<path {W} d="M104 82l84-16v22l-84 16z"/><rect {W} x="104" y="90" width="12" height="86"/><rect {W} x="176" y="76" width="12" height="86"/>'
             f'<ellipse {W} cx="96" cy="176" rx="22" ry="17"/><ellipse {W} cx="168" cy="162" rx="22" ry="17"/>'
             + "".join(f'<path fill="none" stroke="#fff" stroke-width="7" stroke-linecap="round" opacity="{o}" d="M{x} {132 - r}a{r} {r} 0 0 0 0 {2 * r}"/>' for x, r, o in ((80, 18, .8), (66, 32, .45))),
    "notes": f'<path {W} d="M80 56h96a16 16 0 0 1 16 16v88l-40 40H80a16 16 0 0 1-16-16V72a16 16 0 0 1 16-16z"/><path fill="{{c}}" opacity=".35" d="M152 200v-28a12 12 0 0 1 12-12h28z"/>'
             f'<path fill="none" stroke="{{c}}" stroke-width="7" stroke-linecap="round" stroke-linejoin="round" d="M82 88l8 8 14-16"/><rect fill="{{c}}" opacity=".8" x="114" y="84" width="58" height="10" rx="5"/>'
             f'<rect fill="{{c}}" opacity=".8" x="86" y="114" width="84" height="10" rx="5"/><rect fill="{{c}}" opacity=".8" x="86" y="138" width="52" height="10" rx="5"/>',
    "writer": f'<rect {W} opacity=".4" x="58" y="62" width="96" height="124" rx="12"/><rect fill="{{c}}" opacity=".5" x="72" y="80" width="56" height="7" rx="3.5"/><rect fill="{{c}}" opacity=".5" x="72" y="96" width="40" height="7" rx="3.5"/>'
              f'<path {W} d="M168 64l30 30-84 84-42 8 8-42z"/><path fill="{{c}}" d="M156 76l30 30-8 8-30-30z"/><path fill="{{c}}" d="M80 186l6-30 24 24z"/>',
    "terminal": f'<rect fill="#0E1319" x="44" y="66" width="168" height="124" rx="20"/><path fill="#fff" opacity=".12" d="M64 66h128a20 20 0 0 1 20 20v8H44v-8a20 20 0 0 1 20-20z"/>'
                + "".join(f'<circle fill="#fff" opacity=".7" cx="{x}" cy="80" r="4.5"/>' for x in (62, 76, 90))
                + f'<path fill="none" stroke="#fff" stroke-width="12" stroke-linecap="round" stroke-linejoin="round" d="M72 112l26 22-26 22"/><rect {W} x="114" y="150" width="30" height="12" rx="6"/><rect {W} opacity=".7" x="152" y="142" width="14" height="22" rx="3"/>',
    "weather": f'<circle fill="#FFE08A" cx="100" cy="100" r="30"/>'
               + "".join(f'<rect fill="#FFE08A" x="96" y="50" width="8" height="16" rx="4" transform="rotate({a} 100 100)"/>' for a in range(0, 360, 45))
               + f'<circle {W} cx="108" cy="164" r="30"/><circle {W} cx="150" cy="148" r="40"/><circle {W} cx="186" cy="168" r="26"/><rect {W} x="108" y="166" width="78" height="28"/>',
    "clock": f'<circle {W} cx="128" cy="128" r="72"/>'
             + "".join(f'<rect fill="{{c}}" opacity="{1 if a % 90 == 0 else .45}" x="125" y="64" width="6" height="{14 if a % 90 == 0 else 9}" rx="3" transform="rotate({a} 128 128)"/>' for a in range(0, 360, 30))
             + f'<path fill="none" stroke="{{c}}" stroke-width="10" stroke-linecap="round" d="M128 92v36l26 16"/><path fill="none" stroke="#FF5F57" stroke-width="4" stroke-linecap="round" d="M128 128L98 168"/><circle fill="{{c}}" cx="128" cy="128" r="8"/>',
    "camera": f'<rect {W} x="98" y="66" width="60" height="30" rx="10"/><rect {W} x="48" y="84" width="160" height="110" rx="22"/>'
              f'<circle fill="{{c}}" cx="128" cy="140" r="38"/><circle fill="none" stroke="#fff" stroke-opacity=".5" stroke-width="5" cx="128" cy="140" r="27"/><circle fill="{{c}}" cx="128" cy="140" r="17"/>'
              f'<circle fill="#fff" opacity=".7" cx="120" cy="131" r="6"/><circle fill="{{c}}" cx="184" cy="106" r="7"/><rect fill="{{c}}" opacity=".5" x="62" y="100" width="22" height="8" rx="4"/>',
    "settings": "".join(f'<rect {W} x="116" y="52" width="24" height="40" rx="8" transform="rotate({a} 128 128)"/>' for a in range(0, 360, 45))
                + f'<circle {W} cx="128" cy="128" r="50"/><circle fill="none" stroke="{{c}}" stroke-opacity=".5" stroke-width="6" cx="128" cy="128" r="34"/><circle fill="{{c}}" cx="128" cy="128" r="18"/>',
    "store": f'<path fill="none" stroke="#fff" stroke-width="12" stroke-linecap="round" d="M98 102V90a30 30 0 0 1 60 0v12"/><path {W} d="M70 98h116l10 86a12 12 0 0 1-12 14H72a12 12 0 0 1-12-14z"/>'
             f'<circle fill="{{c}}" cx="100" cy="124" r="8"/><circle fill="{{c}}" cx="156" cy="124" r="8"/><path fill="{{c}}" d="M128 142l7 14 15 2-11 10 3 15-14-7-14 7 3-15-11-10 15-2z"/>',
}
PICS.update(DETAIL)


def mix(a: str, b: str, t: float) -> str:
    pa, pb = (int(a[i:i + 2], 16) for i in (1, 3, 5)), (int(b[i:i + 2], 16) for i in (1, 3, 5))
    return "#" + "".join(f"{round(x + (y - x) * t):02X}" for x, y in zip(pa, pb))


def squircle(x: float, y: float, w: float, h: float, n: float = 5.0, steps: int = 72) -> str:
    """A superellipse: softer at the corners than a rounded rectangle."""
    import math
    cx, cy, a, b = x + w / 2, y + h / 2, w / 2, h / 2
    pts = []
    for i in range(steps):
        t = 2 * math.pi * i / steps
        c, s = math.cos(t), math.sin(t)
        pts.append((cx + a * math.copysign(abs(c) ** (2 / n), c), cy + b * math.copysign(abs(s) ** (2 / n), s)))
    return "M" + " L".join(f"{px:.1f} {py:.1f}" for px, py in pts) + "Z"


TILE, INNER = squircle(14, 14, 228, 228), squircle(16.5, 16.5, 223, 223)


# The two marks, in the same glass: the raven glowing in the realm's light (Huginn OS) and in violet (the browser).
# Their bright original artwork stays in branding/ for Welcome, the boot screen and the browser's own project.
RAVEN = (f'<path {W} d="M14 200 C36 164 66 132 104 110 C108 80 126 56 152 56 C168 56 181 64 188 77 C206 78 226 88 238 104 '
         f'C222 106 205 111 190 116 C192 124 186 131 182 136 C174 166 174 206 182 242 H70 A56 56 0 0 1 14 186 Z"/>'
         f'<path fill="none" stroke="{{c}}" stroke-width="9" stroke-linecap="round" opacity=".55" d="M52 204 C84 168 122 160 150 178"/>'
         f'<path fill="none" stroke="{{c}}" stroke-width="9" stroke-linecap="round" opacity=".55" d="M96 226 C116 202 140 196 158 206"/>'
         f'<circle fill="{{c}}" cx="160" cy="86" r="7.5"/><circle {W} cx="162" cy="84" r="2.6"/>')
MARKS = {"huginn-os": ("#3DD6B5", "#7B61FF", ("#B9F5E8", "#7B61FF")), "huginn-browser": ("#8E7BFF", "#5B3FD6", ("#D9D2FF", "#7B61FF"))}


def icon(app: str, bright: str, deep: str, pic: str | None = None, ink: tuple | None = None, clip: bool = False) -> str:
    pic = PICS[app] if pic is None else pic

    def paint(white: str, detail: str) -> str:
        return pic.replace('fill="#fff"', f'fill="{white}"').replace('stroke="#fff"', f'stroke="{white}"').replace("{c}", detail)
    cut, rise = "#16191E", mix(bright, "#FFFFFF", 0.42)
    top, bottom = ink if ink else (rise, bright)
    inside = ' clip-path="url(#inside)"' if clip else ""
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256" width="256" height="256"><defs>'
            # the glass: smoke, the app's light rising from below, a sheen across the top, the rim
            f'<linearGradient id="tile" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#2B3038"/><stop offset="1" stop-color="#121519"/></linearGradient>'
            f'<radialGradient id="glow" cx=".5" cy="1.04" r=".72"><stop offset="0" stop-color="{bright}" stop-opacity=".42"/><stop offset="1" stop-color="{bright}" stop-opacity="0"/></radialGradient>'
            f'<linearGradient id="sheen" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#fff" stop-opacity=".14"/><stop offset=".42" stop-color="#fff" stop-opacity="0"/></linearGradient>'
            f'<radialGradient id="spec" cx=".38" cy="0" r=".6"><stop offset="0" stop-color="#fff" stop-opacity=".16"/><stop offset="1" stop-color="#fff" stop-opacity="0"/></radialGradient>'
            f'<linearGradient id="rim" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#fff" stop-opacity=".30"/><stop offset=".55" stop-color="#fff" stop-opacity=".06"/><stop offset="1" stop-color="{bright}" stop-opacity=".75"/></linearGradient>'
            # thick glass: a lit top edge, a darker foot, a shadow under it
            f'<linearGradient id="hi" gradientUnits="userSpaceOnUse" x1="0" y1="14" x2="0" y2="80"><stop offset="0" stop-color="#fff" stop-opacity=".55"/><stop offset="1" stop-color="#fff" stop-opacity="0"/></linearGradient>'
            f'<linearGradient id="lo" gradientUnits="userSpaceOnUse" x1="0" y1="180" x2="0" y2="242"><stop offset="0" stop-color="#000" stop-opacity="0"/><stop offset="1" stop-color="#000" stop-opacity=".55"/></linearGradient>'
            f'<filter id="drop" x="-20%" y="-20%" width="140%" height="150%"><feGaussianBlur stdDeviation="6"/><feOffset dy="6"/></filter>'
            f'<clipPath id="inside"><path d="{TILE}"/></clipPath>'
            # the picture: the app's colour rising, glossy on top, deeper at its foot, a halo
            f'<linearGradient id="ink" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{top}"/><stop offset="1" stop-color="{bottom}"/></linearGradient>'
            f'<filter id="halo" x="-30%" y="-30%" width="160%" height="160%"><feGaussianBlur stdDeviation="9"/></filter>'
            f'<filter id="soft" x="-40%" y="-40%" width="180%" height="180%"><feGaussianBlur stdDeviation="4"/></filter>'
            f'<mask id="shape" maskUnits="userSpaceOnUse" x="0" y="0" width="256" height="256">{paint("#fff", "#000")}</mask>'
            f'<linearGradient id="gloss" gradientUnits="userSpaceOnUse" x1="0" y1="56" x2="0" y2="200"><stop offset="0" stop-color="#fff" stop-opacity=".62"/>'
            f'<stop offset=".42" stop-color="#fff" stop-opacity=".08"/><stop offset=".43" stop-color="#fff" stop-opacity="0"/><stop offset="1" stop-color="#fff" stop-opacity="0"/></linearGradient>'
            f'<linearGradient id="foot" gradientUnits="userSpaceOnUse" x1="0" y1="120" x2="0" y2="206"><stop offset="0" stop-color="#000" stop-opacity="0"/><stop offset="1" stop-color="#000" stop-opacity=".28"/></linearGradient>'
            # Huginn's light along the bottom edge
            f'<linearGradient id="ring" gradientUnits="userSpaceOnUse" x1="14" y1="0" x2="242" y2="0"><stop offset=".08" stop-color="{bright}" stop-opacity="0"/>'
            f'<stop offset=".5" stop-color="{mix(bright, "#FFFFFF", 0.35)}"/><stop offset=".92" stop-color="{bright}" stop-opacity="0"/></linearGradient>'
            f'<clipPath id="low"><rect x="0" y="196" width="256" height="60"/></clipPath>'
            f'</defs>'
            f'<path d="{TILE}" fill="#000" opacity=".5" filter="url(#drop)"/>'
            f'<path d="{TILE}" fill="url(#tile)"/><path d="{TILE}" fill="url(#spec)"/><path d="{TILE}" fill="url(#glow)"/><path d="{TILE}" fill="url(#sheen)"/>'
            f'<g{inside}><g filter="url(#halo)" opacity=".55">{paint(bright, bright)}</g>{paint("url(#ink)", cut)}'
            f'<rect width="256" height="256" fill="url(#gloss)" mask="url(#shape)"/><rect width="256" height="256" fill="url(#foot)" mask="url(#shape)"/></g>'
            f'<path d="{TILE}" fill="none" stroke="url(#rim)" stroke-width="3"/>'
            f'<g clip-path="url(#inside)"><path d="{INNER}" fill="none" stroke="url(#hi)" stroke-width="5"/><path d="{INNER}" fill="none" stroke="url(#lo)" stroke-width="6"/></g>'
            f'<g clip-path="url(#low)"><path d="{TILE}" fill="none" stroke="url(#ring)" stroke-width="9" filter="url(#soft)" opacity=".9"/>'
            f'<path d="{TILE}" fill="none" stroke="url(#ring)" stroke-width="3.5"/></g>'
            f'</svg>\n')


# ------------------------------------------------------------------------------------------------ folders and files
# Huginn's icon theme ("Huginn", inheriting Breeze for everything else): folders and the common kinds of file, in the
# same smoked glass. A folder is a smoked-glass folder tinted with Files' blue, with what it holds glowing on its
# front; a file is a smoked-glass page with its kind glowing on it and a label in the kind's colour. Small sizes
# (16 to 24 pixels, lists) get plainer drawings: a flat shape in the colour, nothing that would blur into mush.
THEME = ROOT / "config" / "overlay" / "usr" / "share" / "icons" / "Huginn"
FOLDER_BLUE = ("#38B6FF", "#0B6FB8")
EMBLEM = {   # what's on a folder's front (drawn around 128,156 in a 256 box)
    "": "",
    "documents": f'<path {W} d="M108 120h30l20 20v46a8 8 0 0 1-8 8h-42a8 8 0 0 1-8-8v-58a8 8 0 0 1 8-8z"/><rect fill="{{c}}" x="112" y="152" width="32" height="6" rx="3"/><rect fill="{{c}}" x="112" y="166" width="24" height="6" rx="3"/>',
    "download": f'<path fill="none" stroke="#fff" stroke-width="13" stroke-linecap="round" stroke-linejoin="round" d="M128 118v60M104 156l24 24 24-24"/>',
    "music": f'<path {W} d="M116 126l40-8v12l-40 8z"/><rect {W} x="116" y="132" width="8" height="44"/><rect {W} x="148" y="124" width="8" height="44"/><ellipse {W} cx="112" cy="178" rx="12" ry="9"/><ellipse {W} cx="144" cy="170" rx="12" ry="9"/>',
    "pictures": f'<circle {W} cx="150" cy="134" r="9"/><path {W} d="M96 188l28-40 20 26 12-14 28 28z"/>',
    "videos": f'<rect {W} x="94" y="124" width="68" height="60" rx="12"/><path fill="{{c}}" d="M120 140l24 14-24 14z"/>',
    "desktop": f'<rect {W} x="92" y="122" width="72" height="48" rx="8"/><rect {W} x="122" y="170" width="12" height="12"/><rect {W} x="108" y="182" width="40" height="8" rx="4"/>',
    "home": f'<path {W} d="M128 112l40 34v40a6 6 0 0 1-6 6h-22v-26h-24v26H94a6 6 0 0 1-6-6v-40z"/>',
    "templates": f'<rect fill="none" stroke="#fff" stroke-width="9" stroke-dasharray="14 9" x="100" y="122" width="56" height="66" rx="8"/>',
    "public": f'<circle {W} cx="112" cy="140" r="12"/><circle {W} cx="146" cy="140" r="12"/><path {W} d="M90 188a22 18 0 0 1 44 0zM124 188a22 18 0 0 1 44 0z"/>',
}
FOLDERS = {"folder": "", "folder-open": "", "inode-directory": "", "folder-documents": "documents", "folder-download": "download",
           "folder-downloads": "download", "folder-music": "music", "folder-pictures": "pictures", "folder-images": "pictures",
           "folder-videos": "videos", "folder-video": "videos", "folder-desktop": "desktop", "user-desktop": "desktop",
           "user-home": "home", "folder-home": "home", "folder-templates": "templates", "folder-publicshare": "public"}
# kinds of file: (colour key in tokens' apps, label, picture key)
KINDS = {
    "text-plain": ("disks", "TXT", "lines"), "text-x-generic": ("disks", "TXT", "lines"),
    "application-pdf": ("documents", "PDF", "lines"),
    "image-x-generic": ("photos", "", "image"), "image-png": ("photos", "PNG", "image"), "image-jpeg": ("photos", "JPG", "image"), "image-svg+xml": ("photos", "SVG", "image"),
    "audio-x-generic": ("music", "", "note"), "audio-mpeg": ("music", "MP3", "note"), "audio-flac": ("music", "FLAC", "note"), "audio-x-wav": ("music", "WAV", "note"),
    "video-x-generic": ("video", "", "play"), "video-mp4": ("video", "MP4", "play"), "video-x-matroska": ("video", "MKV", "play"), "video-webm": ("video", "WEBM", "play"),
    "package-x-generic": ("archives", "", "zip"), "application-zip": ("archives", "ZIP", "zip"), "application-x-compressed-tar": ("archives", "TAR", "zip"),
    "application-x-7z-compressed": ("archives", "7Z", "zip"), "application-x-tar": ("archives", "TAR", "zip"),
    "x-office-document": ("writer", "DOC", "lines"), "application-vnd.oasis.opendocument.text": ("writer", "ODT", "lines"),
    "application-vnd.openxmlformats-officedocument.wordprocessingml.document": ("writer", "DOCX", "lines"), "application-msword": ("writer", "DOC", "lines"),
    "x-office-spreadsheet": ("sheets", "", "grid"), "application-vnd.oasis.opendocument.spreadsheet": ("sheets", "ODS", "grid"),
    "application-vnd.openxmlformats-officedocument.spreadsheetml.sheet": ("sheets", "XLSX", "grid"), "text-csv": ("sheets", "CSV", "grid"),
    "x-office-presentation": ("slides", "", "bars"), "application-vnd.oasis.opendocument.presentation": ("slides", "ODP", "bars"),
    "application-vnd.openxmlformats-officedocument.presentationml.presentation": ("slides", "PPTX", "bars"),
    "text-x-script": ("code", "", "code"), "text-x-python": ("code", "PY", "code"), "application-json": ("code", "JSON", "code"),
    "text-x-csrc": ("code", "C", "code"), "text-x-rust": ("code", "RS", "code"), "application-javascript": ("code", "JS", "code"),
    "text-html": ("help", "HTML", "globe"), "application-x-executable": ("terminal", "", "prompt"), "application-x-shellscript": ("terminal", "SH", "prompt"),
    "application-x-sharedlib": ("terminal", "SO", "prompt"), "unknown": ("disks", "", "dots"), "application-octet-stream": ("disks", "", "dots"),
}
GLYPH = {   # drawn around 128,128 in a 256 box, inside a page
    "lines": "".join(f'<rect {W} x="84" y="{96 + i * 20}" width="{[88, 88, 88, 56][i]}" height="10" rx="5"/>' for i in range(4)),
    "image": f'<circle {W} cx="154" cy="104" r="12"/><path {W} d="M80 164l36-50 26 32 16-18 34 36z"/>',
    "note": f'<path {W} d="M108 92l52-10v14l-52 10z"/><rect {W} x="108" y="100" width="9" height="56"/><rect {W} x="151" y="92" width="9" height="56"/><ellipse {W} cx="102" cy="158" rx="15" ry="11"/><ellipse {W} cx="145" cy="150" rx="15" ry="11"/>',
    "play": f'<path {W} d="M108 88l56 34-56 34z"/>',
    "zip": "".join(f'<rect {W} x="{122 if i % 2 else 128}" y="{80 + i * 12}" width="10" height="8" rx="2"/>' for i in range(6)) + f'<rect {W} x="114" y="152" width="28" height="22" rx="6"/>',
    "grid": f'<rect fill="none" stroke="#fff" stroke-width="8" x="82" y="88" width="92" height="76" rx="8"/><path fill="none" stroke="#fff" stroke-width="7" d="M82 114h92M82 139h92M113 88v76M144 88v76"/>',
    "bars": "".join(f'<rect {W} x="{88 + i * 22}" y="{164 - h}" width="14" height="{h}" rx="4"/>' for i, h in enumerate([30, 52, 40, 66])),
    "code": f'<path fill="none" stroke="#fff" stroke-width="12" stroke-linecap="round" stroke-linejoin="round" d="M106 98l-26 28 26 28M150 98l26 28-26 28"/>',
    "globe": f'<circle fill="none" stroke="#fff" stroke-width="9" cx="128" cy="124" r="40"/><path fill="none" stroke="#fff" stroke-width="7" d="M88 124h80M128 84c-18 22-18 58 0 80M128 84c18 22 18 58 0 80"/>',
    "prompt": f'<path fill="none" stroke="#fff" stroke-width="12" stroke-linecap="round" stroke-linejoin="round" d="M86 100l28 24-28 24"/><rect {W} x="126" y="142" width="44" height="12" rx="6"/>',
    "dots": "".join(f'<circle {W} cx="{100 + i * 28}" cy="126" r="9"/>' for i in range(3)),
}
FOLDER_BACK = "M28 76a20 20 0 0 1 20-20h52l22 22h86a20 20 0 0 1 20 20v16H28z"
FOLDER_FRONT = "M28 112a20 20 0 0 1 20-20h160a20 20 0 0 1 20 20v94a20 20 0 0 1-20 20H48a20 20 0 0 1-20-20z"
PAGE = "M68 18h88l52 52v152a18 18 0 0 1-18 18H68a18 18 0 0 1-18-18V36a18 18 0 0 1 18-18z"
FOLD = "M156 18v34a18 18 0 0 0 18 18h34z"


def _glass_defs(bright: str) -> str:
    rise = mix(bright, "#FFFFFF", 0.42)
    return (f'<linearGradient id="smoke" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#2B3038"/><stop offset="1" stop-color="#121519"/></linearGradient>'
            f'<linearGradient id="rim" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#fff" stop-opacity=".32"/><stop offset=".55" stop-color="#fff" stop-opacity=".06"/><stop offset="1" stop-color="{bright}" stop-opacity=".8"/></linearGradient>'
            f'<radialGradient id="glow" cx=".5" cy="1.05" r=".75"><stop offset="0" stop-color="{bright}" stop-opacity=".45"/><stop offset="1" stop-color="{bright}" stop-opacity="0"/></radialGradient>'
            f'<linearGradient id="ink" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{rise}"/><stop offset="1" stop-color="{bright}"/></linearGradient>'
            f'<filter id="halo" x="-30%" y="-30%" width="160%" height="160%"><feGaussianBlur stdDeviation="8"/></filter>'
            f'<filter id="drop" x="-20%" y="-20%" width="140%" height="150%"><feGaussianBlur stdDeviation="5"/><feOffset dy="5"/></filter>')


def folder_svg(emblem: str) -> str:
    bright, deep = FOLDER_BLUE
    tint_top, tint_bottom = mix(bright, "#2B3038", 0.55), mix(deep, "#121519", 0.55)
    pic = EMBLEM[emblem]
    paint = (lambda white, detail: pic.replace('fill="#fff"', f'fill="{white}"').replace('stroke="#fff"', f'stroke="{white}"').replace("{c}", detail))
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256" width="256" height="256"><defs>{_glass_defs(bright)}'
            f'<linearGradient id="tint" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{tint_top}"/><stop offset="1" stop-color="{tint_bottom}"/></linearGradient>'
            f'<linearGradient id="hi" gradientUnits="userSpaceOnUse" x1="0" y1="92" x2="0" y2="140"><stop offset="0" stop-color="#fff" stop-opacity=".5"/><stop offset="1" stop-color="#fff" stop-opacity="0"/></linearGradient></defs>'
            f'<path d="{FOLDER_FRONT}" fill="#000" opacity=".45" filter="url(#drop)"/>'
            f'<path d="{FOLDER_BACK}" fill="url(#smoke)"/><path d="{FOLDER_BACK}" fill="none" stroke="#fff" stroke-opacity=".18" stroke-width="3"/>'
            f'<path fill="#fff" opacity=".85" d="M60 80h136a8 8 0 0 1 8 8v20H52V88a8 8 0 0 1 8-8z"/>'   # a sheet of paper peeking out
            f'<path d="{FOLDER_FRONT}" fill="url(#tint)"/><path d="{FOLDER_FRONT}" fill="url(#glow)"/>'
            + (f'<g filter="url(#halo)" opacity=".6">{paint(bright, bright)}</g>{paint("url(#ink)", tint_bottom)}' if pic else "")
            + f'<path d="{FOLDER_FRONT}" fill="none" stroke="url(#rim)" stroke-width="3"/><path d="M48 95h160" stroke="url(#hi)" stroke-width="4" stroke-linecap="round"/></svg>\n')


def folder_small(emblem: str) -> str:
    bright, deep = FOLDER_BLUE
    pic = EMBLEM[emblem]
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256" width="256" height="256">'
            f'<path fill="{deep}" d="{FOLDER_BACK}"/><path fill="{bright}" d="{FOLDER_FRONT}"/>'
            + (f'<g transform="translate(128 160) scale(1.25) translate(-128 -156)">{pic.replace("{c}", bright)}</g>' if pic else "")
            + '</svg>\n')


def file_svg(kind: str, colours: dict) -> str:
    key, label, glyph = KINDS[kind]
    bright, deep = colours[key]
    pic = GLYPH[glyph]
    paint = (lambda white: pic.replace('fill="#fff"', f'fill="{white}"').replace('stroke="#fff"', f'stroke="{white}"'))
    tag = (f'<rect x="{128 - (18 + 19 * len(label)) / 2:.0f}" y="180" width="{18 + 19 * len(label)}" height="38" rx="12" fill="{bright}"/>'
           f'<text x="128" y="207" text-anchor="middle" font-family="Inter, Inter Variable, sans-serif" font-weight="800" font-size="25" fill="#0C1013">{label}</text>') if label else ""
    lift = ' transform="translate(0 -6)"' if label else ' transform="translate(0 16)"'
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256" width="256" height="256"><defs>{_glass_defs(bright)}</defs>'
            f'<path d="{PAGE}" fill="#000" opacity=".45" filter="url(#drop)"/><path d="{PAGE}" fill="url(#smoke)"/><path d="{PAGE}" fill="url(#glow)"/>'
            f'<path d="{FOLD}" fill="#fff" opacity=".16"/>'
            f'<g{lift}><g filter="url(#halo)" opacity=".55">{paint(bright)}</g>{paint("url(#ink)")}</g>{tag}'
            f'<path d="{PAGE}" fill="none" stroke="url(#rim)" stroke-width="3"/></svg>\n')


def file_small(kind: str, colours: dict) -> str:
    key, _label, glyph = KINDS[kind]
    bright, deep = colours[key]
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256" width="256" height="256">'
            f'<path fill="#E9EDF2" d="{PAGE}"/><path fill="#B8C0CA" d="{FOLD}"/>'
            f'<g transform="translate(128 128) scale(1.2) translate(-128 -128)">{GLYPH[glyph].replace("#fff", deep)}</g></svg>\n')


def theme(colours: dict) -> int:
    """Writes the Huginn icon theme: folders and kinds of file, big (scalable) and small (16, 22, 24)."""
    dirs = []
    for ctx, items, big, small in (("places", FOLDERS, lambda n: folder_svg(FOLDERS[n]), lambda n: folder_small(FOLDERS[n])),
                                   ("mimetypes", KINDS, lambda n: file_svg(n, colours), lambda n: file_small(n, colours))):
        for folder, draw, size in (("scalable", big, None), ("24", small, 24), ("22", small, 22), ("16", small, 16)):
            where = THEME / folder / ctx
            where.mkdir(parents=True, exist_ok=True)
            for name in items:
                (where / f"{name}.svg").write_text(draw(name), encoding="utf-8")
            dirs.append((f"{folder}/{ctx}", ctx, size))
    lines = ["[Icon Theme]", "Name=Huginn", "Comment=Huginn OS: folders and files in smoked glass", "Inherits=breeze,hicolor",
             "Directories=" + ",".join(d for d, _, _ in dirs), ""]
    for d, ctx, size in dirs:
        context = "Places" if ctx == "places" else "MimeTypes"
        if size is None:
            lines += [f"[{d}]", "Size=256", "MinSize=32", "MaxSize=512", f"Context={context}", "Type=Scalable", ""]
        else:
            lines += [f"[{d}]", f"Size={size}", f"Context={context}", "Type=Fixed", ""]
    (THEME / "index.theme").write_text("\n".join(lines), encoding="utf-8")
    return len(FOLDERS) + len(KINDS)


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
    # the installer wears Huginn OS's own mark, and the sign-in prompt (authenticate) has no icon of its own
    missing = sorted(set(k for k in colours if not k.startswith("_") and k not in ("installer", "authenticate")) ^ set(PICS))
    if missing:
        print("These apps have a colour but no picture, or the other way round:", ", ".join(missing))
        return 1
    from PySide6.QtCore import QByteArray, QRectF, Qt
    from PySide6.QtGui import QGuiApplication, QImage, QPainter
    from PySide6.QtSvg import QSvgRenderer
    app = QGuiApplication.instance() or QGuiApplication(["icons", "-platform", "offscreen"])      # noqa: F841
    made = {}

    def write(name: str, svg: str, sizes=(256, 128, 64, 48)) -> bool:
        (OUT / "scalable" / "apps").mkdir(parents=True, exist_ok=True)
        (OUT / "scalable" / "apps" / f"{name}.svg").write_text(svg, encoding="utf-8")
        draw = QSvgRenderer(QByteArray(svg.encode("utf-8")))
        if not draw.isValid():
            print(f"The picture for {name} isn't valid SVG.")
            return False
        for size in sizes:
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
        return True

    for name in PICS:
        if not write(f"huginn-{name}", icon(name, *colours[name])):
            return 1
    # the calendar without its date: the dock and the launcher write today's over it (AppIcon.qml)
    blank = re.sub(r"<text[^>]*>[^<]*</text>", "", PICS["calendar"])
    write("huginn-calendar-blank", icon("calendar", *colours["calendar"], pic=blank), sizes=(256, 128))
    made.pop("huginn-calendar-blank", None)
    # The two marks: Huginn OS itself, and the Huginn browser, in the same glass.
    for name, (bright, deep, ink) in MARKS.items():
        write(name, icon(name, bright, deep, pic=RAVEN, ink=ink, clip=True), sizes=(512, 256, 128, 64, 48, 32, 24, 16))
    print(f"Drew {len(made)} icons into {OUT}")
    print(f"Drew {theme(colours)} folders and kinds of file into {THEME}")
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
