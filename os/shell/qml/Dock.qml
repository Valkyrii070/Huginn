import QtQuick
import QtQuick.Shapes

// The dock: three separate islands. Left, the orb that opens the launcher. Middle, apps: pinned ones,
// then anything else that is running, then web apps installed from Huginn. Right, the live island, there only while
// something is going on (LiveIsland.qml; what it knows: huginn_island.py).
// Under each app, a bar for each window (up to three; a dim one when they're all hidden). Clicking an app that isn't
// open starts it, and a light in its colour runs round its tile until its window is there (the Ring). Clicking the
// app in front hides it (a ring spreads round its tile), and clicking again brings it back; an app with several
// windows shows them (as pointing at it for a moment does). Middle-click: a new window. Scroll: through its
// windows. Drop a file on it: opens it there.
Row {
    id: dock
    signal launcher()
    signal controlCentre()                 // kept for callers; the control centre opens from the top bar
    signal tabsWanted(bool show)           // pointer rests on / leaves the Huginn tile
    property real tabsX: 0                 // centre of the Huginn tile, in dock coordinates
    // The session shell draws names in a surface of its own (the dock's is only as tall as the dock),
    // so it turns inlineTips off and listens to tipText / tipX.
    property bool inlineTips: true
    property string tipText: ""
    property real tipX: 0
    property string tipFor: ""              // the app the name bubble belongs to
    // Under Huginn's own compositor: brings the app's window forward when it has one (returns true), instead of
    // starting it again. Elsewhere it stays null and a click starts the app.
    property var activate: null
    property bool menuOpen: false          // the start menu is open (it grows out of the orb)
    readonly property int tile: Math.max(32, Math.min(64, Settings.dockSize || 44))   // Settings › Desktop & Dock › Size
    onMenuOpenChanged: if (menuOpen && Theme.t.openMs > 0) orbPress.restart()
    function hover(item, app, open, inside) {
        var centre = appsIsland.x + main.x + item.x + item.width / 2
        if (app.name === "Huginn" && Tabs.installed) { if (inside) tabsX = centre; tabsWanted(inside); return }
        // Tracked by app, not by position: tiles move when an app opens or closes.
        if (inside) { tipX = centre; tipFor = app.name; tipText = app.name + (open ? " · open" : "") }
        else if (tipFor === app.name) { tipFor = ""; tipText = "" }
    }
    onNativesChanged: { tipFor = ""; tipText = "" }
    readonly property var pinnedNames: Apps.pinned          // "Keep in the dock" in an app's island changes it
    // Every window, by app (Status.windows: the compositor's or KWin's list).
    readonly property var winsByApp: {
        var m = {}, all = Status.windows
        for (var i = 0; i < all.length; i++) { var n = all[i].name; if (n) (m[n] = m[n] || []).push(all[i]) }
        return m
    }
    readonly property bool knowsWindows: Status.windows.length > 0
    function windowsOf(name) { return winsByApp[name] || [] }
    // Apps just started (their Ring runs until a window is there, or 12 s at most): name -> when
    property var starting: ({})
    function start(app) {
        var s = Object.assign({}, starting); s[app.name] = Date.now(); starting = s
        Apps.launch(app.exec); ringClock.start()
    }
    property Timer ringClock: Timer {
        interval: 500; repeat: true
        onTriggered: {
            var s = {}, any = false
            for (var n in dock.starting)
                if (Date.now() - dock.starting[n] < 12000 && dock.windowsOf(n).length === 0 && !(Apps.running.indexOf(n) >= 0 && !dock.knowsWindows && Date.now() - dock.starting[n] > 1500)) { s[n] = dock.starting[n]; any = true }
            dock.starting = s
            if (!any) stop()
        }
    }
    signal windowsWanted(var app, real x, bool show, bool pinned)    // an app's windows above it (pointing, or a click)
    signal stackWanted(string folder, real x, bool menu)             // a stack opened (or its menu, right-click)
    function stackX(folder) {   // the centre of a stack's tile, in dock coordinates
        for (var i = 0; i < stackRep.count; i++) { var t = stackRep.itemAt(i); if (t && t.stack.folder === folder) return t.mapToItem(dock, t.width / 2, 0).x }
        return width - 40
    }
    function tileRects() {   // each app's tile, in dock coordinates, by its ids (for windows hiding into them)
        var out = {}
        for (var i = 0; i < appRep.count; i++) {
            var t = appRep.itemAt(i)
            if (!t) continue
            var p = t.mapToItem(dock, 0, 0), a = t.app
            for (var k of [a.id, a.wm]) if (k) out[String(k).toLowerCase().replace(/\.desktop$/, "")] = [p.x, p.y, t.width, t.height]
        }
        return out
    }
    function stackLanded(folder) { for (var i = 0; i < stackRep.count; i++) { var t = stackRep.itemAt(i); if (t && t.stack.folder === folder) t.land() } }
    function clickApp(slot, app) {
        var wins = windowsOf(app.name)
        if (wins.length === 0) {
            if (!(dock.activate && dock.activate(app))) start(app)
            return
        }
        if (wins.length === 1) {
            var front = wins[0].active && !wins[0].minimised
            if (front && !Settings.dockClickHides) return              // Settings › Desktop & Dock: it stays
            if (front) slot.hid()
            Status.windowDo(wins[0].id, "toggle")
            return
        }
        windowsWanted(app, slot.mapToItem(dock, slot.width / 2, 0).x, true, true)
    }
    function stepWindows(app, forward) {   // scrolling over an app: its windows, one at a time
        var wins = windowsOf(app.name)
        if (wins.length === 0) return
        var at = -1
        for (var i = 0; i < wins.length; i++) if (wins[i].active) at = i
        var next = wins[((at < 0 ? 0 : at + (forward ? 1 : -1)) + wins.length) % wins.length]
        Status.windowDo(next.id, "activate")
    }
    signal islandWanted(var app, real x)   // right-click (or Menu key) on an app: its island, centred on x (dock coordinates)
    signal liveHover(bool inside)          // the pointer is on the live island (the host opens it after a moment)
    signal liveFocus(string id)            // a screen/camera/mic bubble was clicked: open the live island on it
    readonly property real liveRight: liveIsland.x + liveIsland.pillRight       // where the opened live island lines up
    readonly property real liveCentre: liveIsland.x + liveIsland.pillCentre
    readonly property real restWidth: orbIsland.width + spacing + appsIsland.width   // the dock without the live island
    function appNamed(name) { var all = Apps.all; for (var i = 0; i < all.length; i++) if (all[i].name === name) return all[i]; return null }
    function openApp(name) {   // bring it forward if it has a window, else start it
        var app = appNamed(name)
        if (app && !(dock.activate && dock.activate(app))) Apps.launch(app.exec)
    }
    // Pinned apps, then every other app that is running: found by its process (Apps.running) or by having a window
    // (Status.windows). A window whose app has no .desktop file at all (an AppImage, a game started by a launcher, a
    // program run from a terminal) still gets a tile, made from the window itself (Status.otherApps).
    readonly property var natives: {
        var all = Apps.all, run = Apps.running, out = [], seen = {}, i
        function add(a) { if (!seen[a.name]) { seen[a.name] = true; out.push(a) } }
        for (i = 0; i < pinnedNames.length; i++)
            for (var j = 0; j < all.length; j++)
                if (!all[j].web && all[j].name === pinnedNames[i]) { add(all[j]); break }
        for (i = 0; i < all.length; i++)
            if (!all[i].web && (run.indexOf(all[i].name) >= 0 || winsByApp[all[i].name])) add(all[i])
        var others = Status.otherApps || []
        for (i = 0; i < others.length; i++) add(others[i])
        return out
    }
    readonly property var webApps: Apps.all.filter(function (a) { return a.web }).slice(0, 4)
    spacing: 12

    component Island: Glass { height: dock.tile + 20; radius: 22 }
    component Divider: Rectangle { width: 1; height: 30; color: Theme.t.line; anchors.verticalCenter: parent.verticalCenter }
    component Tile: Item {
        id: slot
        property var app
        readonly property var wins: dock.windowsOf(app.name)
        readonly property bool open: wins.length > 0 || Apps.running.indexOf(app.name) >= 0
        readonly property bool allHidden: wins.length > 0 && wins.every(function (w) { return w.minimised })
        readonly property bool launching: dock.starting[app.name] !== undefined
        readonly property color tone: app.colours && app.colours.length ? (Theme.t.dark ? app.colours[0] : app.colours[1]) : Theme.t.accent
        property alias hovered: hit.containsMouse
        property bool inlineTip: true
        function hid() { if (Theme.t.openMs > 0) hideRing.restart() }
        width: dock.tile; height: dock.tile
        scale: hit.pressed ? Theme.t.pressScale : 1
        Behavior on scale { NumberAnimation { duration: 100 } }
        AppIcon { name: slot.app.name; glyph: slot.app.glyph; image: slot.app.image; own: slot.app.own || ""; web: slot.app.web }
        // Open: a bar for each window (three at most), a soft glow behind; all hidden: one dim bar.
        Rectangle { visible: slot.open && !slot.allHidden; width: 34; height: 9; radius: 5; color: Theme.t.accent; opacity: 0.22; anchors { horizontalCenter: parent.horizontalCenter; top: parent.bottom; topMargin: 1 } }
        Row {
            visible: slot.open && !slot.launching
            // Settings › Desktop & Dock › "Bars under open apps": off, one bar however many windows
            readonly property int n: slot.allHidden || !Settings.dockDots ? 1 : Math.max(1, Math.min(3, slot.wins.length))
            anchors { horizontalCenter: parent.horizontalCenter; top: parent.bottom; topMargin: 4 }
            spacing: 3
            Repeater {
                model: parent.n
                Rectangle { width: parent.n === 1 ? 22 : parent.n === 2 ? 9 : 6; height: 3; radius: 2; color: Theme.t.accent; opacity: slot.allHidden ? 0.4 : 1 }
            }
        }
        // The Ring: while the app starts, a light in its colour runs round its tile.
        Shape {
            id: ring
            visible: slot.launching; anchors.centerIn: parent; width: dock.tile + 8; height: dock.tile + 8
            preferredRendererType: Shape.CurveRenderer
            readonly property real perimeter: 4 * (ring.width - 2 * 15) + 2 * Math.PI * 15
            ShapePath {
                strokeColor: slot.tone; strokeWidth: 2.5; fillColor: "transparent"; capStyle: ShapePath.RoundCap
                strokeStyle: ShapePath.DashLine; dashPattern: [ring.perimeter * 0.32 / 2.5, ring.perimeter * 0.68 / 2.5]
                dashOffset: ring.run
                PathRectangle { x: 1; y: 1; width: ring.width - 2; height: ring.height - 2; radius: 15 }
            }
            property real run: 0
            NumberAnimation on run { from: 0; to: -ring.perimeter / 2.5; duration: 900; loops: Animation.Infinite; running: ring.visible }
        }
        Rectangle {   // the Ring's glow
            visible: slot.launching; anchors.centerIn: parent; width: dock.tile + 12; height: dock.tile + 12; radius: 18; color: "transparent"
            border.width: 6; border.color: slot.tone; opacity: 0.12
        }
        // Hidden: a ring of light spreads round the tile, once.
        Rectangle {
            id: spread
            anchors.centerIn: parent; width: dock.tile; height: dock.tile; radius: width * 0.32; color: "transparent"
            border.width: 2; border.color: Theme.t.glowA; opacity: 0
            ParallelAnimation {
                id: hideRing
                NumberAnimation { target: spread; property: "width"; from: dock.tile; to: dock.tile + 30; duration: 520; easing.type: Easing.OutCubic }
                NumberAnimation { target: spread; property: "height"; from: dock.tile; to: dock.tile + 30; duration: 520; easing.type: Easing.OutCubic }
                SequentialAnimation {
                    NumberAnimation { target: spread; property: "opacity"; from: 0; to: 0.9; duration: 90 }
                    NumberAnimation { target: spread; property: "opacity"; to: 0; duration: 430; easing.type: Easing.InQuad }
                }
            }
        }
        // A count the app wants seen (Mail: unread).
        Rectangle { readonly property int n: Apps.badges[slot.app.name] || 0; visible: n > 0; z: 3; height: 16; width: Math.max(16, bn.width + 9); radius: 8; color: "#E5484D"; border.width: 1; border.color: "#33000000"
            anchors { right: parent.right; rightMargin: -3; top: parent.top; topMargin: -3 }
            Label { id: bn; anchors.centerIn: parent; text: parent.n > 99 ? "99+" : parent.n; color: "white"; font.pixelSize: 10; font.weight: Font.Bold } }
        // Pointing for a moment at an open app: its windows show above it.
        Timer { id: lingering; interval: 650; onTriggered: if (slot.wins.length > 0 && !(slot.app.name === "Huginn" && Tabs.installed)) dock.windowsWanted(slot.app, slot.mapToItem(dock, slot.width / 2, 0).x, true, false) }
        MouseArea {
            id: hit; anchors.fill: parent; hoverEnabled: true; acceptedButtons: Qt.LeftButton | Qt.RightButton | Qt.MiddleButton
            onContainsMouseChanged: {
                if (containsMouse) lingering.restart()
                else { lingering.stop(); dock.windowsWanted(slot.app, 0, false, false) }
            }
            onClicked: function (m) {
                lingering.stop()
                if (m.button === Qt.RightButton) { dock.islandWanted(slot.app, slot.mapToItem(dock, slot.width / 2, 0).x); return }
                if (m.button === Qt.MiddleButton) { dock.start(slot.app); return }       // a new window
                dock.clickApp(slot, slot.app)
            }
            onPressAndHold: dock.islandWanted(slot.app, slot.mapToItem(dock, slot.width / 2, 0).x)
            onWheel: function (w) { dock.stepWindows(slot.app, w.angleDelta.y < 0) }
        }
        DropArea {   // a file dropped on an app opens there
            anchors.fill: parent; keys: ["text/uri-list"]
            onDropped: function (drop) { if (drop.hasUrls) { Apps.openWith(slot.app.name, drop.urls[0].toString()); drop.accept() } }
            Rectangle { anchors.fill: parent; anchors.margins: -4; radius: 15; color: "transparent"; border.width: 2; border.color: slot.tone; visible: parent.containsDrag }
        }
        // Name on hover: every dock item says what it is. The Huginn tile shows its tab stack there.
        Glass {
            visible: slot.inlineTip && hit.containsMouse && !(slot.app.name === "Huginn" && Tabs.installed); popup: true; radius: Theme.t.radiusControl
            width: tip.width + 16; height: 26
            anchors { horizontalCenter: parent.horizontalCenter; bottom: parent.top; bottomMargin: 16 }
            Label { id: tip; anchors.centerIn: parent; text: slot.app.name + ((Apps.badges[slot.app.name] || 0) > 0 ? " · " + Apps.badges[slot.app.name] + " unread" : slot.open ? " · open" : ""); font.pixelSize: 12 }
        }
    }

    // A stack: its newest files as a little pile of cards (the top one still arriving fills up); click: its files.
    component StackTile: Item {
        id: st
        property var stack
        readonly property var top3: stack ? stack.items.slice(0, 3) : []
        width: dock.tile; height: dock.tile
        function land() { if (Theme.t.openMs > 0) bounce.restart() }
        Item {
            id: pile
            anchors.fill: parent
            transformOrigin: Item.Bottom
            scale: hit.pressed ? Theme.t.pressScale : 1
            Behavior on scale { enabled: !bounce.running; NumberAnimation { duration: 100 } }
            Rectangle {   // empty: a tray
                visible: st.top3.length === 0; anchors.fill: parent; radius: 13; color: Qt.rgba(1, 1, 1, Theme.t.dark ? 0.06 : 0.4); border.width: 1; border.color: Theme.t.line
                Glyph { anchors.centerIn: parent; name: "download"; size: 20; ink: Theme.t.icon }
            }
            Repeater {
                model: st.top3.length
                FileArt {
                    required property int index
                    readonly property int depth: st.top3.length - 1 - index        // drawn deepest first
                    file: st.top3[depth]; size: 40 - depth * 3
                    anchors.centerIn: parent
                    anchors.horizontalCenterOffset: depth === 0 ? 0 : depth === 1 ? -4 : 4
                    anchors.verticalCenterOffset: -depth * 2
                    rotation: depth === 0 ? 0 : depth === 1 ? -9 : 8
                    opacity: depth === 0 ? 1 : 0.92
                }
            }
            SequentialAnimation {   // something landed: the pile bounces
                id: bounce
                NumberAnimation { target: pile; property: "scale"; to: 1.2; duration: 120; easing.type: Easing.OutQuad }
                NumberAnimation { target: pile; property: "scale"; to: 0.94; duration: 140; easing.type: Easing.InOutQuad }
                NumberAnimation { target: pile; property: "scale"; to: 1; duration: 220; easing.type: Easing.OutBack }
            }
        }
        MouseArea {
            id: hit; anchors.fill: parent; hoverEnabled: true; acceptedButtons: Qt.LeftButton | Qt.RightButton
            onContainsMouseChanged: {
                if (containsMouse) { dock.tipX = st.mapToItem(dock, st.width / 2, 0).x; dock.tipFor = st.stack.folder; dock.tipText = st.stack.name + (st.stack.busy ? " · arriving" : "") }
                else if (dock.tipFor === st.stack.folder) { dock.tipFor = ""; dock.tipText = "" }
            }
            onClicked: function (m) { dock.tipText = ""; dock.stackWanted(st.stack.folder, st.mapToItem(dock, st.width / 2, 0).x, m.button === Qt.RightButton) }
        }
        DropArea {   // files dropped on a stack go into its folder
            anchors.fill: parent; keys: ["text/uri-list"]
            onDropped: function (drop) { if (drop.hasUrls) { Stacks.dropInto(st.stack.folder, drop.urls); drop.accept() } }
            Rectangle { anchors.fill: parent; anchors.margins: -4; radius: 15; color: "transparent"; border.width: 2; border.color: Theme.t.accent; visible: parent.containsDrag }
        }
    }

    Island {
        id: orbIsland
        width: dock.tile + 20
        Pressable {
            anchors.centerIn: parent; width: dock.tile; height: dock.tile; radius: 13; onClicked: dock.launcher()
            Rectangle {   // while the start menu is open the orb glows, as the menu's light comes from it
                anchors.centerIn: parent; width: dock.tile - 4; height: dock.tile - 4; radius: 20; color: Theme.t.glowA
                opacity: dock.menuOpen ? 0.35 : 0
                Behavior on opacity { NumberAnimation { duration: 300 } }
            }
            Rectangle {
                id: orbDot
                anchors.centerIn: parent; width: 26; height: 26; radius: 13
                gradient: Gradient { GradientStop { position: 0; color: Theme.t.glowA } GradientStop { position: 0.45; color: Theme.t.glowA } GradientStop { position: 1; color: Theme.t.glowB } }
                border.width: dock.menuOpen ? 2 : 0; border.color: "#E6FFFFFF"
                SequentialAnimation {   // the press: it dips, then lets the menu out
                    id: orbPress
                    NumberAnimation { target: orbDot; property: "scale"; to: 0.8; duration: 70; easing.type: Easing.OutQuad }
                    NumberAnimation { target: orbDot; property: "scale"; to: 1.12; duration: 140; easing.type: Easing.OutQuad }
                    NumberAnimation { target: orbDot; property: "scale"; to: 1; duration: 160; easing.type: Easing.OutBack }
                }
            }
        }
    }
    Island {
        id: appsIsland
        width: main.width + 20
        DropArea {   // a folder dropped on the dock's end becomes a stack
            id: endDrop
            anchors { top: parent.top; bottom: parent.bottom; right: parent.right }
            width: 70; keys: ["text/uri-list"]
            onDropped: function (drop) { if (drop.hasUrls && Stacks.addFolder(drop.urls[0].toString())) drop.accept() }
        }
        Row {
            id: main; anchors.centerIn: parent; spacing: 8
            Repeater {
                id: appRep
                model: dock.natives
                Tile {
                    required property var modelData
                    app: modelData; inlineTip: dock.inlineTips
                    onHoveredChanged: dock.hover(this, modelData, open, hovered)
                }
            }
            Divider { visible: dock.webApps.length > 0 }
            Repeater { model: dock.webApps; Tile { required property var modelData; app: modelData; inlineTip: dock.inlineTips; onHoveredChanged: dock.hover(this, modelData, open, hovered) } }
            Divider { visible: Stacks.stacks.length > 0 || endDrop.containsDrag }
            Repeater { id: stackRep; model: Stacks.stacks; StackTile { required property var modelData; stack: modelData } }
            Item {   // drag a folder here: it becomes a stack
                width: endDrop.containsDrag ? dock.tile : 0; height: dock.tile
                Behavior on width { NumberAnimation { duration: 140 } }
                Rectangle { anchors.fill: parent; visible: parent.width > 30; radius: 13; color: "transparent"; border.width: 2; border.color: Theme.t.accent
                    Label { anchors.centerIn: parent; text: "+"; color: Theme.t.accent; font.pixelSize: 22 } }
            }
        }
    }
    LiveIsland {
        h: dock.tile + 20
        id: liveIsland
        onHovered: function (inside) { dock.liveHover(inside) }
        onFocusWanted: function (id) { dock.liveFocus(id) }
        onOpenWanted: function (app) { dock.openApp(app) }
        onIslandWanted: function (name, x) {
            var app = dock.appNamed(name)
            if (app) dock.islandWanted(app, liveIsland.x + x)
        }
    }
}
