import QtQuick
import QtQuick.Window
import QtWayland.Compositor
import QtWayland.Compositor.XdgShell

// Huginn's own compositor (the preview session): one scene with everything in it. From the back: the realm's
// wallpaper and the widgets, the apps' windows (Chrome.qml: glass islands, no title bars), the top bar and the dock,
// the session daemon's banners / level / questions, the launcher and control centre, Alt+Tab, and the lock screen.
// Python's half (huginn_compositor.py, as `Comp`) does the keys, idle time, PAM, screenshots and D-Bus.
WaylandCompositor {
    id: comp
    socketName: Comp.socket
    property var windows: []                          // every Chrome, in no particular order
    property int topStack: 0
    property var focused: null                        // the window in front with the keyboard
    readonly property int top: 30                     // the top bar
    readonly property int bottom: 92                  // the dock and its margin
    readonly property var fullscreenWindow: windows.filter(function (w) { return w.fullscreen && !w.minimised })[0] || null
    readonly property bool anyMaximised: windows.some(function (w) { return w.maximized && !w.minimised && w.role === "" })
    readonly property bool inhibited: windows.some(function (w) { return w.inhibitsIdle && !w.minimised })
    // The screens (cage spans them all, side by side): the main one has the bar, the dock and the panels; windows
    // open on, and maximise to, the screen the window in front is on.
    readonly property var screens: Comp.screens.length ? Comp.screens : [{ x: 0, y: 0, width: screen.width, height: screen.height, main: true }]
    readonly property var ms: screens.filter(function (s) { return s.main })[0] || screens[0]
    property var here: ms
    function screenAt(px, py) {
        for (var i = 0; i < screens.length; i++) { var s = screens[i]; if (px >= s.x && px < s.x + s.width && py >= s.y && py < s.y + s.height) return s }
        return ms
    }
    function free(s) {                           // the room on a screen for windows: below the bar, above the dock (main only)
        var m = s === ms || (s.x === ms.x && s.y === ms.y)
        return Qt.rect(s.x, s.y + (m ? top : 0), s.width, s.height - (m ? top + bottom : 0))
    }
    onFocusedChanged: if (focused && focused.role === "") here = screenAt(focused.x + focused.width / 2, focused.y + focused.height / 2)
    onScreensChanged: {
        here = ms
        windows.forEach(function (w) {                   // a screen went away: its windows come to the main one
            if (w.role !== "" || w.minimised) return
            var on = screens.some(function (s) { return w.x + w.width / 2 >= s.x && w.x + w.width / 2 < s.x + s.width && w.y + w.height / 2 >= s.y && w.y + w.height / 2 < s.y + s.height })
            if (!on) { w.x = ms.x + Math.max(0, (ms.width - w.width) / 2); w.y = ms.y + top + 24 }
        })
    }
    onInhibitedChanged: Comp.setInhibited(inhibited)

    // ------------------------------------------------------------------ windows: where they go, which is in front
    function add(xdgSurface) {
        var c = chromeComp.createObject(screen.windowsLayer, { host: comp, xdgSurface: xdgSurface, stack: ++topStack })
        c.gone.connect(function () { comp.forget(c) })
        windows = windows.concat([c])
    }
    function forget(c) {
        windows = windows.filter(function (w) { return w !== c })
        if (focused === c) refocus()
        c.destroy()
    }
    function raise(c) {
        if (c.stack !== topStack) c.stack = ++topStack
        if (c.role === "" ) focused = c
    }
    function refocus() {
        var best = null
        windows.forEach(function (w) { if (!w.minimised && !w.closing && w.role === "" && (!best || w.stack > best.stack)) best = w })
        focused = best
        if (best && screen.open !== "launcher" && screen.open !== "search") best.activate()   // (the menu and Search keep the keys while open)
    }
    function place(c) {
        c.placed = true
        // the session's own surfaces go on the main screen; windows on the screen of the window in front
        var s = c.role !== "" ? ms : here, f = free(s)
        var W = s.width, H = s.height, X = s.x, Y = s.y
        if (c.role === "banners") { c.x = X + W - c.width - 10; c.y = Y + top + 8; return }
        if (c.role === "osd") { c.x = X + (W - c.width) / 2; c.y = Y + H - c.height - bottom - 24; return }
        if (c.role === "prompt") { c.x = X + (W - c.width) / 2; c.y = Y + (H - c.height) / 2; c.activate(); return }
        // bigger than the free space (a small screen): ask it to fit, then place it when it has
        var roomW = f.width - 24, roomH = f.height - (c.decorated ? 52 : 8)
        if (c.toplevel && !c.shrunk && (c.width > roomW || c.height > roomH)) {
            c.shrunk = true; c.placed = false
            c.toplevel.sendConfigure(Qt.size(Math.min(c.width, roomW), Math.min(c.height, roomH)), [XdgToplevel.ActivatedState])
            return
        }
        var parent = c.toplevel && c.toplevel.parentToplevel ? windows.filter(function (w) { return w.toplevel === c.toplevel.parentToplevel })[0] : null
        if (parent) { c.x = parent.x + (parent.width - c.width) / 2; c.y = parent.y + Math.max(24, (parent.height - c.height) / 3) }
        else {
            var lift = c.decorated ? 44 : 0, spare = f.height - c.height - lift
            var n = windows.filter(function (w) { return w.role === "" && w !== c && !w.minimised }).length % 6
            c.x = f.x + Math.max(0, (f.width - c.width) / 2 + (n - 2) * 26)
            c.y = f.y + lift + Math.max(8, spare / 2 + (n - 2) * 22)
        }
        if (!parent) {
            c.x = Math.max(f.x, Math.min(f.x + f.width - Math.min(c.width, f.width), c.x))
            c.y = Math.max(f.y + (c.decorated ? 44 : 0), c.y)
        }
        if (screen.open === "launcher" || screen.open === "search") raise(c)   // (a window that arrives while they're open doesn't take their keys)
        else c.activate()
    }
    function appWindows(app) {
        var wm = (app.wm || "").toLowerCase(), id = (app.id || "").toLowerCase()
        return windows.filter(function (w) { var a = w.appId.toLowerCase(); return w.role === "" && !w.closing && a !== "" && (a === wm || a === id) })
            .sort(function (a, b) { return b.stack - a.stack })
    }
    function activateApp(app) {
        var mine = appWindows(app)
        if (mine.length === 0) return false
        // its window in front already: the next of its windows; otherwise the one used last
        var pick = (focused === mine[0] && !mine[0].minimised && mine.length > 1) ? mine[mine.length - 1] : mine[0]
        pick.restore()
        screen.open = ""
        return true
    }

    // One more output for each other screen. Each keeps its own free room, so Maximise fills the screen a window is
    // on (Chrome gives its window the output under it) and a maximised window never jumps to another screen.
    property var extraOutputs: []
    property Instantiator moreScreens: Instantiator {
        model: comp.screens.length > 1 ? comp.screens.filter(function (s) { return !(s.x === comp.ms.x && s.y === comp.ms.y) }) : []
        delegate: WaylandOutput {
            required property var modelData
            readonly property var place: modelData
            compositor: comp; window: screen; sizeFollowsWindow: true
            availableGeometry: comp.free(modelData)
        }
        onObjectAdded: function (i, o) { comp.extraOutputs = comp.extraOutputs.concat([o]) }
        onObjectRemoved: function (i, o) { comp.extraOutputs = comp.extraOutputs.filter(function (x) { return x !== o }) }
    }
    function outputAt(px, py) {
        var s = screenAt(px, py)
        return extraOutputs.filter(function (o) { return o.place.x === s.x && o.place.y === s.y })[0] || output
    }

    // ------------------------------------------------------------------ the screen
    WaylandOutput {
        id: output
        sizeFollowsWindow: true
        availableGeometry: comp.free(comp.ms)            // what Maximise fills on the main screen
        window: Window {
            id: screen
            width: 1600; height: 1000
            visible: true
            // Never asks its host to make it full screen: cage fills the screen with it anyway, and cage 0.2 aborts if
            // a window asks before its first frame. Frameless: no title bar of Qt's own.
            flags: Comp.windowed ? Qt.Window : (Qt.Window | Qt.FramelessWindowHint)
            title: "Huginn OS"
            color: "black"
            property alias windowsLayer: windowLayer
            // frosted glass (Glass.qml): what the bar, dock and panels frost, and what desktop cards frost
            readonly property Item backdrop: backdropItem
            readonly property Item wallpaperLayer: desk
            readonly property bool frostOn: Comp.frost && !(typeof Settings !== "undefined" && Settings.reduceTransparency)
            property string open: ""                 // "launcher", "cc" or ""
            onOpenChanged: if (open === "" && comp.focused && !Comp.locked) comp.focused.activate()   // the keys go back to the window
            property bool tabsOpen: false
            property bool settled: !arriving
            Component.onCompleted: Comp.setScreen(screen)

            Item {
                id: backdropItem
                anchors.fill: parent
                Item {
                    id: desk
                    anchors.fill: parent
                    Repeater { model: comp.screens           // the realm's wallpaper on every screen
                        Wallpaper { required property var modelData; x: modelData.x; y: modelData.y; width: modelData.width; height: modelData.height } }
                }
                MouseArea { anchors.fill: parent; onPressed: { screen.open = ""; comp.focused = null } }
                Widgets { x: comp.ms.x + 22; y: comp.ms.y + 52; opacity: screen.settled ? 1 : 0; Behavior on opacity { NumberAnimation { duration: 600 } } }
                Item { id: windowLayer; anchors.fill: parent }
            }
            // the main screen: the bar, the dock and the panels live in it
            Item { id: mainArea; x: comp.ms.x; y: comp.ms.y; width: comp.ms.width; height: comp.ms.height }

            // ---- the bar and the dock (gone while something is full screen)
            TopBar {
                id: bar
                x: comp.ms.x; y: comp.ms.y; width: comp.ms.width; z: 2000
                visible: !comp.fullscreenWindow
                solid: comp.anyMaximised
                appName: comp.focused ? (comp.focused.app.name || comp.focused.title) : "Huginn"
                opacity: screen.settled ? 1 : 0; Behavior on opacity { NumberAnimation { duration: 500 } }
                onControlCentre: screen.open = screen.open === "cc" ? "" : "cc"
                onLauncher: screen.open = screen.open === "launcher" ? "" : "launcher"
                onSearch: screen.open = screen.open === "search" ? "" : "search"
                onWindowAction: function (action) { if (!comp.focused) return; if (action === "close") comp.focused.close(); else if (action === "minimise") comp.focused.minimise() }
            }
            // a maximised window of another app: its controls sit in the middle of the bar
            Rectangle {
                id: barCtl
                objectName: "barControls"
                readonly property var w: comp.focused && comp.focused.maximized && comp.focused.decorated ? comp.focused : null
                visible: w !== null && bar.visible; z: 2001
                x: comp.ms.x + (comp.ms.width - width) / 2; y: comp.ms.y + 3; height: 24; radius: 12; width: brow.width + 20
                color: Theme.t.island; border.width: 1; border.color: Theme.t.islandLine
                Row { id: brow; x: 10; height: parent.height; spacing: 7
                    Repeater { model: [{ c: "#FF5F57", f: "close" }, { c: "#FEBC2E", f: "min" }, { c: "#28C840", f: "max" }]
                        Rectangle { required property var modelData; width: 11; height: 11; radius: 6; color: modelData.c; anchors.verticalCenter: parent.verticalCenter
                            MouseArea { anchors.fill: parent; anchors.margins: -4
                                onClicked: { var w = barCtl.w; if (!w) return
                                    if (modelData.f === "close") w.close(); else if (modelData.f === "min") w.minimise(); else w.toggleMaximised() } } } }
                    Label { text: barCtl.w ? barCtl.w.title : ""; font.pixelSize: 11; width: Math.min(implicitWidth, 360); elide: Text.ElideRight; anchors.verticalCenter: parent.verticalCenter } }
            }
            Dock {
                id: dock
                z: 2000
                visible: !comp.fullscreenWindow
                anchors { horizontalCenter: mainArea.horizontalCenter; bottom: mainArea.bottom; bottomMargin: screen.settled ? 14 : -10 }
                opacity: screen.settled ? 1 : 0
                Behavior on opacity { NumberAnimation { duration: 500 } }
                Behavior on anchors.bottomMargin { NumberAnimation { duration: 550; easing.type: Easing.OutCubic } }
                activate: function (app) { return comp.activateApp(app) }
                menuOpen: screen.open === "launcher"
                onIslandWanted: function (app, x) { screen.open = ""; islandLayer.shown = true; dockIsland.open(app); dockIsland.x = Math.max(comp.ms.x + 8, Math.min(comp.ms.x + comp.ms.width - dockIsland.width - 8, dock.x + x - dockIsland.width / 2)) }
                onLauncher: screen.open = screen.open === "launcher" ? "" : "launcher"
                onControlCentre: screen.open = screen.open === "cc" ? "" : "cc"
                onTabsWanted: function (show) { if (show) { tabsHide.stop(); tabsShow.start() } else { tabsShow.stop(); tabsHide.restart() } }
                onLiveHover: function (inside) { screen.livePointer(inside) }
                onLiveFocus: function (id) { screen.liveFocus = id; liveHide.stop(); screen.liveOpen = true }
            }
            // the live island, opened: after a moment of pointing at it, or by itself while a call or an alarm rings
            property bool liveOpen: false
            property string liveFocus: ""
            function livePointer(inside) { if (inside) { liveHide.stop(); if (!liveOpen) liveShow.start() } else { liveShow.stop(); liveHide.restart() } }
            Timer { id: liveShow; interval: 300; onTriggered: screen.liveOpen = true }
            Timer { id: liveHide; interval: 350; onTriggered: { screen.liveOpen = false; screen.liveFocus = "" } }
            LivePanel {
                objectName: "livePanel"
                z: 2002
                shown: (screen.liveOpen || Live.ringing) && Live.active && screen.open === "" && !islandLayer.shown && dock.visible
                focusId: screen.liveFocus
                x: Math.max(comp.ms.x + 8, Math.min(comp.ms.x + comp.ms.width - width - 8, dock.x + dock.liveRight - width)); y: dock.y - height - 10
                originX: dock.x + dock.liveCentre - x
                onPointer: function (inside) { screen.livePointer(inside) }
                onOpenWanted: function (app) { dock.openApp(app) }
            }
            Connections {   // two players: the one whose window isn't in front gets the island
                target: comp
                function onFocusedChanged() { Live.setFront(comp.focused && comp.focused.app ? String(comp.focused.app.file || "").split("/").pop() : "") }
            }
            Timer { id: tabsShow; interval: 350; onTriggered: { Tabs.refresh(); screen.tabsOpen = true } }
            Timer { id: tabsHide; interval: 350; onTriggered: screen.tabsOpen = false }
            TabStack {
                z: 2002
                visible: opacity > 0; opacity: screen.tabsOpen ? 1 : 0
                x: dock.x + (dock.tabsX > 0 ? dock.tabsX : 150) - width / 2; y: dock.y - height - 12
                onHoverChanged: function (inside) { if (inside) tabsHide.stop(); else tabsHide.restart() }
                onPicked: screen.tabsOpen = false
                Behavior on opacity { NumberAnimation { duration: 150 } }
            }
            // the name of the dock item under the pointer
            Glass {
                z: 2003; popup: true; radius: Theme.t.radiusControl; visible: dock.tipText !== "" && !dock.inlineTips
                width: tipLabel.width + 16; height: 26; x: dock.x + dock.tipX - width / 2; y: dock.y - 34
                Label { id: tipLabel; anchors.centerIn: parent; text: dock.tipText; font.pixelSize: 12 }
            }
            Item {                                   // the control centre slides in from the main screen's edge, not the next screen
                x: comp.ms.x; y: comp.ms.y; width: comp.ms.width; height: comp.ms.height; z: 2010; clip: true
                ControlCentre {
                    objectName: "controlCentre"
                    y: 40; height: parent.height - 132
                    x: screen.open === "cc" ? parent.width - width - 10 : parent.width + 10
                    visible: x < parent.width
                    Behavior on x { NumberAnimation { duration: 220; easing.type: Easing.OutCubic } }
                }
            }
            Launcher {
                id: launcher
                objectName: "launcher"
                z: 2010
                onDone: screen.open = ""
                onSearchEverything: function (text) { search.startText = text; screen.open = "search" }
                shown: screen.open === "launcher"           // (its search field takes the keys when it shows)
                height: Math.min(660, comp.ms.height - 132)
                x: comp.ms.x + (comp.ms.width - width) / 2; y: comp.ms.y + comp.ms.height - height - 92
                orb: Qt.point(dock.x + 32 - x, dock.y + 32 - y)
            }
            Rectangle {   // the room behind the menu and Search dims a little
                x: comp.ms.x; y: comp.ms.y; width: comp.ms.width; height: comp.ms.height; z: 2005; color: "black"
                opacity: launcher.presence * 0.22 + search.presence * 0.4; visible: opacity > 0
            }
            Search {
                id: search
                objectName: "search"
                z: 2020
                x: comp.ms.x; y: comp.ms.y; width: comp.ms.width; height: comp.ms.height
                shown: screen.open === "search"
                onDone: { screen.open = ""; startText = "" }
            }
            Item {   // an app's island from the dock (right-click or a long press on its tile)
                id: islandLayer
                property bool shown: false
                z: 2030
                x: 0; y: 0; width: parent.width; height: parent.height
                visible: shown
                MouseArea { anchors.fill: parent; acceptedButtons: Qt.AllButtons; onClicked: islandLayer.shown = false }
                AppIsland { id: dockIsland; y: dock.y - height - 10; onDone: islandLayer.shown = false }
            }

            // ---- Alt+Tab
            Switcher {
                id: switcher
                z: 3000
                anchors.centerIn: mainArea
                windows: comp.windows.filter(function (w) { return w.role === "" && !w.closing }).sort(function (a, b) { return b.stack - a.stack })
                onChosen: function (w) { w.restore() }
            }

            // ---- a screenshot's flash
            Rectangle { id: flashRect; anchors.fill: parent; z: 4000; color: "white"; opacity: 0
                NumberAnimation on opacity { id: flashAnim; running: false; from: 0.5; to: 0; duration: 380; easing.type: Easing.OutCubic } }

            // ---- the lock screen: the same one as the KWin session's
            Rectangle { anchors.fill: parent; z: 4999; color: "black"; visible: Comp.locked && comp.screens.length > 1 }   // the other screens, while locked
            Loader {
                id: lockLoader
                objectName: "lock"
                x: comp.ms.x; y: comp.ms.y; width: comp.ms.width; height: comp.ms.height; z: 5000
                active: Comp.locked
                source: Comp.lockUi
                focus: active
                onLoaded: {
                    item.userName = Me.login; item.realName = Me.name; item.picture = Me.face
                    item.realm = Qt.binding(function () { return Theme.t.realm })
                    item.liveDir = Qt.binding(function () { return Theme.t.liveDir })
                    item.canSuspend = true
                    item.submit.connect(function (pw) { Comp.unlock(pw) })
                    item.suspend.connect(function () { Comp.suspend() })
                    item.done.connect(function () { Comp.unlocked() })
                    item.forceActiveFocus()
                    screen.open = ""
                }
            }
            Connections { target: Comp
                function onUnlockAnswer(ok, message) { if (!lockLoader.item) return; if (ok) lockLoader.item.succeed(); else lockLoader.item.fail(message) }
                function onLockedChanged() { if (!Comp.locked) comp.refocus() }
                function onSwitchStep(step) { switcher.step(step) }
                function onSwitchCommit() { switcher.commit() }
                function onSwitchCancel() { switcher.cancel() }
                function onCloseActive() { if (comp.focused) comp.focused.close() }
                function onMinimiseActive() { if (comp.focused) comp.focused.minimise() }
                function onMaximiseActive() { if (comp.focused) comp.focused.toggleMaximised() }
                function onToggleLauncher() { screen.open = screen.open === "launcher" ? "" : "launcher" }
                function onToggleSearch() { screen.open = screen.open === "search" ? "" : "search" }
                function onFlash() { flashAnim.restart() }
            }
            // ---- the screen turned off (the session daemon asks): black, until anything is touched
            Rectangle { objectName: "blank"; anchors.fill: parent; z: 6000; color: "black"; visible: opacity > 0; opacity: Comp.blank ? 1 : 0
                Behavior on opacity { NumberAnimation { duration: 400 } }
                MouseArea { anchors.fill: parent; enabled: Comp.blank; hoverEnabled: true } }
            // ---- just signed in: the sign-in island carries on, then the desktop comes in
            Rectangle { anchors.fill: parent; z: 6999; color: "black"; visible: !screen.settled && comp.screens.length > 1 }   // the other screens, until the desktop has come in
            Arrival { x: comp.ms.x; y: comp.ms.y; width: comp.ms.width; height: comp.ms.height; z: 7000; playing: arriving; opacity: arriving ? 1 : 0; onLeaving: screen.settled = true }
            Timer { running: !arriving; interval: 10; onTriggered: screen.settled = true }
        }
    }

    // tests only (HUGINN_COMPOSITOR_TEST=1): what the windows are doing, for org.huginn.Compositor.Windows
    property Timer reporter: Timer { running: Comp.testing; interval: 200; repeat: true
        onTriggered: Comp.report(JSON.stringify({ open: screen.open, focused: comp.focused ? comp.focused.title : "", switching: switcher.showing,
            switchIndex: switcher.index, windows: comp.windows.map(function (w) { return { title: w.title, appId: w.appId, role: w.role,
                x: Math.round(w.x), y: Math.round(w.y), w: Math.round(w.width), h: Math.round(w.height), minimised: w.minimised, active: w.active,
                maximized: w.maximized, fullscreen: w.fullscreen, decorated: w.decorated, stack: w.stack, app: w.app.name || "" } }) })) }

    // ------------------------------------------------------------------ protocols
    XdgShell {
        onToplevelCreated: function (toplevel, xdgSurface) { comp.add(xdgSurface) }
    }
    XdgDecorationManagerV1 { preferredMode: XdgToplevel.ServerSideDecoration }   // we give other apps their island; they draw no title bar
    IdleInhibitManagerV1 {}
    Component { id: chromeComp; Chrome {} }
}
