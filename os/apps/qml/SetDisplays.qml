import QtQuick

// Displays: a map of the screens to drag about, then each screen's resolution, size, refresh and turn; brightness;
// night light.
Column {
    id: pg
    width: parent ? parent.width : 600; spacing: 18
    readonly property var d: Backend.displays
    readonly property var screens: d.screens || []
    property string chosen: ""
    readonly property string sel: screens.some(function (s) { return s.name === pg.chosen }) ? chosen : (screens.length ? screens[0].name : "")
    readonly property var cur: screens.filter(function (s) { return s.name === pg.sel })[0] || null
    readonly property var scales: [[1, "100%"], [1.25, "125%"], [1.5, "150%"], [1.75, "175%"], [2, "200%"]]
    function logical(s) { var turned = s.rotation === "left" || s.rotation === "right"; return { w: (turned ? s.h : s.w) / s.scale, h: (turned ? s.w : s.h) / s.scale } }
    SetCard { visible: pg.d.available === false && pg.screens.length === 0
        SetRow { title: "Screens can't be changed here"; sub: "kscreen-doctor isn't installed, so this page can only show night light."; glyph: "display" } }
    // the arrangement
    Rectangle { visible: pg.screens.length > 1; width: parent.width; height: 220; radius: Theme.t.radiusCard; color: Theme.t.group; border.width: 1; border.color: Theme.t.separator
        id: map
        readonly property var box: { var minx = 1e9, miny = 1e9, maxx = -1e9, maxy = -1e9
            for (var i = 0; i < pg.screens.length; i++) { var s = pg.screens[i], l = pg.logical(s); if (!s.enabled) continue
                minx = Math.min(minx, s.x); miny = Math.min(miny, s.y); maxx = Math.max(maxx, s.x + l.w); maxy = Math.max(maxy, s.y + l.h) }
            return { x: minx, y: miny, w: Math.max(1, maxx - minx), h: Math.max(1, maxy - miny) } }
        readonly property real k: Math.min((width - 80) / box.w, (height - 60) / box.h)
        Label { x: 14; y: 10; text: "Drag the screens to match how they sit on your desk"; secondary: true; font.pixelSize: 11 }
        Repeater { model: pg.screens.filter(function (s) { return s.enabled })
            Rectangle { id: tile; required property var modelData
                readonly property var l: pg.logical(modelData)
                x: (map.width - map.box.w * map.k) / 2 + (modelData.x - map.box.x) * map.k; y: 30 + (map.height - 40 - map.box.h * map.k) / 2 + (modelData.y - map.box.y) * map.k
                width: l.w * map.k - 4; height: l.h * map.k - 4; radius: 8
                color: pg.sel === modelData.name ? Qt.rgba(Theme.t.accent.r, Theme.t.accent.g, Theme.t.accent.b, 0.35) : (Theme.t.dark ? "#2AFFFFFF" : "#22141E28")
                border.width: pg.sel === modelData.name ? 2 : 1; border.color: pg.sel === modelData.name ? Theme.t.accent : Theme.t.separator
                Column { anchors.centerIn: parent; spacing: 2
                    Label { anchors.horizontalCenter: parent.horizontalCenter; text: modelData.label; font.pixelSize: 12; font.weight: Font.DemiBold }
                    Label { anchors.horizontalCenter: parent.horizontalCenter; text: modelData.primary ? "Main" : ""; font.pixelSize: 10; secondary: true } }
                Rectangle { visible: modelData.primary; x: 6; y: 5; width: parent.width - 12; height: 4; radius: 2; color: Theme.t.text_secondary }   // the top bar lives here
                MouseArea { anchors.fill: parent; drag.target: tile; cursorShape: Qt.OpenHandCursor
                    onPressed: pg.chosen = modelData.name
                    onReleased: { var nx = Math.round(map.box.x + (tile.x - (map.width - map.box.w * map.k) / 2) / map.k), ny = Math.round(map.box.y + (tile.y - 30 - (map.height - 40 - map.box.h * map.k) / 2) / map.k)
                                  // snap to the nearest edge of another screen so they touch
                                  for (var i = 0; i < pg.screens.length; i++) { var o = pg.screens[i]; if (o.name === modelData.name || !o.enabled) continue; var ol = pg.logical(o)
                                      if (Math.abs(nx - (o.x + ol.w)) < 200) nx = o.x + ol.w; else if (Math.abs(nx + tile.l.w - o.x) < 200) nx = o.x - tile.l.w
                                      if (Math.abs(ny - o.y) < 200) ny = o.y; else if (Math.abs(ny - (o.y + ol.h)) < 200) ny = o.y + ol.h }
                                  var minX = 0, minY = 0
                                  Backend.placeScreen(modelData.name, Math.round(nx), Math.round(ny)) } } } } }
    Row { visible: pg.screens.length > 1; spacing: 6
        Repeater { model: pg.screens; Seg { required property var modelData; text: modelData.label; on: pg.sel === modelData.name; onClicked: pg.chosen = modelData.name } } }
    SetCard { visible: pg.cur !== null; title: pg.cur ? pg.cur.label : ""
        SetRow { visible: pg.screens.length > 1; title: "Use this screen"; Toggle { on: pg.cur ? pg.cur.enabled : false; onToggled: function (v) { Backend.setScreenOn(pg.cur.name, v) } } }
        SetRow { visible: pg.screens.length > 1 && pg.cur && pg.cur.enabled; title: "Main screen"; sub: "Where the top bar and dock live"
            Btn { text: pg.cur && pg.cur.primary ? "This is the main one" : "Make Main"; enabled: pg.cur && !pg.cur.primary; onClicked: Backend.setMain(pg.cur.name) } }
        SetRow { title: "Resolution"; sub: pg.cur && pg.cur.resolutions.length && pg.cur.resolution !== pg.cur.resolutions[0].id ? "The sharpest is " + pg.cur.resolutions[0].label : "The sharpest this screen can show"
            SetPick { text: pg.cur ? pg.cur.resolution.replace("x", " × ") : ""; onClicked: win.pick("Resolution", pg.cur.resolutions.map(function (r, i) { return { id: r.id, label: r.label, sub: i === 0 ? "Best for this screen" : "" } }), pg.cur.resolution,
                                                                                                          function (v) { Backend.setResolution(pg.cur.name, v) }) } }
        SetRow { title: "Size of things"; sub: "Bigger makes text and buttons easier to read; smaller fits more"
            SetChoice { each: 62; options: pg.scales.map(function (s) { return [String(s[0]), s[1]] }); value: pg.cur ? String(pg.cur.scale) : "1"; onPicked: function (v) { Backend.setScale(pg.cur.name, Number(v)) } } }
        SetRow { visible: pg.cur && pg.cur.rates.length > 1; title: "Refresh rate"; sub: "Higher is smoother"
            SetChoice { each: 74; options: pg.cur ? pg.cur.rates.slice(0, 4).map(function (r) { return [r.id, r.label] }) : []; value: pg.cur ? String(pg.cur.hz) : ""; onPicked: function (v) { Backend.setRate(pg.cur.name, v) } } }
        SetRow { title: "Turn"; sub: "For a screen on its side"
            SetChoice { each: 70; options: [["normal", "None"], ["left", "Left"], ["right", "Right"], ["inverted", "Upside"]]; value: pg.cur ? pg.cur.rotation : "normal"; onPicked: function (v) { Backend.setRotation(pg.cur.name, v) } } } }
    SetCard { visible: pg.d.brightness >= 0; title: "Brightness"
        SetRow { title: "Brightness"; SetSlider { width: 280; glyphLeft: "sun"; value: pg.d.brightness / 100; onMoved: function (v) { Backend.setBrightness(Math.round(v * 100)) } } } }
    SetCard { title: "Night light"; note: "Warmer colours in the evening are easier on the eyes and help you sleep."
        SetRow { title: "Night light"; glyph: "moon"; tile: "#F08C3B"; sub: pg.d.night && pg.d.night.on ? (pg.d.night.mode === "Times" ? "From " + pg.d.night.from + " to " + pg.d.night.to : pg.d.night.mode === "Constant" ? "On all the time" : "From sunset to sunrise") : "Off"
            Toggle { on: !!(pg.d.night && pg.d.night.on); onToggled: function (v) { Backend.setNight("on", v) } } }
        SetRow { visible: !!(pg.d.night && pg.d.night.on); title: "When"
            SetChoice { each: 100; options: [["Automatic", "Sunset to sunrise"], ["Times", "Set hours"], ["Constant", "Always"]]; value: pg.d.night ? pg.d.night.mode : ""; onPicked: function (v) { Backend.setNight("mode", v) } } }
        SetRow { visible: !!(pg.d.night && pg.d.night.on && pg.d.night.mode === "Times"); title: "Hours"
            Row { spacing: 8
                SetPick { text: pg.d.night ? pg.d.night.from : ""; onClicked: win.pick("Night light starts at", hours(), pg.d.night.from, function (v) { Backend.setNight("from", v) }) }
                Label { text: "to"; secondary: true; anchors.verticalCenter: parent.verticalCenter }
                SetPick { text: pg.d.night ? pg.d.night.to : ""; onClicked: win.pick("Night light ends at", hours(), pg.d.night.to, function (v) { Backend.setNight("to", v) }) } } }
        SetRow { visible: !!(pg.d.night && pg.d.night.on); title: "Warmth"
            SetSlider { width: 260; lowText: "Less"; highText: "More"; fill: "#F08C3B"; value: pg.d.night ? (6500 - pg.d.night.temp) / 3700 : 0.5
                onMoved: function (v) { Backend.setNight("temp", Math.round((6500 - v * 3700) / 100) * 100) } } } }
    function hours() { var out = []; for (var h = 0; h < 24; h++) for (var m = 0; m < 60; m += 30) { var t = (h < 10 ? "0" : "") + h + ":" + (m ? "30" : "00"); out.push({ id: t, label: t }) } return out }
}
