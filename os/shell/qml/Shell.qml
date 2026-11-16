import QtQuick
import QtQuick.Window
import org.kde.layershell 1.0 as LayerShell

// Session shell: every piece is its own Wayland layer-shell surface on KWin.
// The root is a plain object, not an Item: windows nested in an Item that has no window of its own never map.
QtObject {
    id: shell
    property string open: ""
    property bool settled: !arriving       // after the arrival from the sign-in screen, the desktop's pieces come in
    property bool tabsOpen: false
    property string searchText: ""
    property var dockIsland: null              // the app whose island is open over the dock
    property real dockIslandX: 0
    // the live island, opened: after a moment of pointing at it (and while the pointer stays on it or the opened
    // island), or by itself while a call or an alarm rings
    property bool liveOpen: false
    property string liveFocus: ""
    readonly property bool liveShown: (liveOpen || Live.ringing) && Live.active && shell.open === "" && shell.dockIsland === null   // (dockIsland alone is the AppIsland's id)
    property Timer liveShow: Timer { interval: 300; onTriggered: shell.liveOpen = true }
    property Timer liveHide: Timer { interval: 350; onTriggered: { shell.liveOpen = false; shell.liveFocus = "" } }
    function livePointer(inside) { if (inside) { liveHide.stop(); if (!liveOpen) liveShow.start() } else { liveShow.stop(); liveHide.restart() } }
    // an app's windows above its dock tile (pointing at it for a moment, or clicking an app with several)
    property var winApp: null
    property real winX: 0
    property bool winPinned: false
    property Timer winHide: Timer { interval: 300; onTriggered: if (!shell.winPinned) shell.winApp = null }
    function windowsWanted(app, x, show, pinned) {
        if (show) { winHide.stop(); winApp = app; winX = x; winPinned = pinned; dock.tipText = ""; return }
        winHide.restart()
    }
    // where the dock's tiles are on the screen, and how windows hide into them (Huginn's compositor draws that)
    property Timer dockReport: Timer {
        interval: 400; running: true; repeat: true
        property string last: ""
        onTriggered: {
            if (!Status.ownCompositor) { stop(); return }
            var sw = dockWin.screen ? dockWin.screen.width : 0, sh = dockWin.screen ? dockWin.screen.height : 0
            if (!sw) return
            var tiles = dock.tileRects(), out = {}, x0 = (sw - dock.width) / 2, y0 = sh - dockWin.height
            for (var k in tiles) out[k] = [x0 + tiles[k][0], y0 + tiles[k][1], tiles[k][2], tiles[k][3]]
            var text = JSON.stringify({ tiles: out, style: Theme.t.openMs > 0 ? Settings.hideStyle : "none", glow: Theme.t.glowA.toString(), gaps: Settings.snapGaps,
                                       dark: Theme.t.dark, frost: !Settings.reduceTransparency && !Settings.contrast,
                                       remember: Settings.rememberPlaces, vrr: Settings.adaptiveSync })
            if (text !== last) { last = text; Status.dockLayout(text) }
        }
    }
    // notifications wait quietly while something has the whole screen or the screen is shared
    readonly property bool busyScreen: !!Live.privacy.screen || Status.windows.some(function (w) { return w.active && w.full })
    onBusyScreenChanged: Status.setBusyScreen(busyScreen)
    onOpenChanged: if (open === "cc") Status.notesSeen()
    // the app's menu, out of its name in the bar ("" the one menu; a group's name: the row-of-menus way)
    property string menuGroup: ""
    function appMenu(group) {
        if (shell.open === "menu" && menuGroup === group) { shell.open = ""; return }
        menuGroup = group
        if (group === "") Status.loadMenus()
        shell.open = "menu"
    }
    property Connections menuSource: Connections {
        target: Status
        function onActiveChanged() { if (topBar.rowMenus) Status.loadMenus() }
        function onTourWanted() { shell.startTour("first") }
    }
    // the Welcome tour (TourHost: full-screen pages, then the island on the desktop)
    property bool touring: false
    function startTour(kind) { touring = true; open = ""; tour.start(kind || "first") }
    // the first time (or after a big update): once the desktop has come in, and not over the installer
    property Timer tourAuto: Timer {
        interval: 1600; repeat: true
        running: shell.settled && Tour.due !== "" && !shell.touring
        onTriggered: {
            if (Status.windows.some(function (w) { return /install/i.test(w.appId) || /installer/i.test(w.name) })) return
            stop(); shell.startTour(Tour.due)
        }
    }
    function frontWindow() { var a = Status.windows.filter(function (w) { return w.active && !w.minimised }); return a.length ? a[0] : null }
    // a stack opened over its dock tile
    property string stackFolder: ""
    property real stackX: 0
    property bool stackMenu: false
    property Timer tabsShow: Timer { interval: 350; onTriggered: { Tabs.refresh(); shell.tabsOpen = true } }
    property Timer tabsHide: Timer { interval: 350; onTriggered: shell.tabsOpen = false }
    property Connections keys: Connections {
        target: Status
        function onLauncherWanted() { shell.open = shell.open === "launcher" ? "" : "launcher" }
        function onSearchWanted(text) { shell.searchText = text; shell.open = shell.open === "search" && !text ? "" : "search" }
        function onKeyWanted(what) {
            if (what === "today") shell.open = shell.open === "today" ? "" : "today"
            else if (what === "menu") shell.appMenu("")
        }
    }
    // The wallpaper, on every screen (screens plugged in later get one too); the widgets on the main screen, with the
    // bar and the dock.
    property Instantiator walls: Instantiator {
        model: Status.screenList
        delegate: Window {
            id: wall
            required property var modelData
            readonly property bool main: modelData.name === Status.primaryScreen || Status.primaryScreen === ""
            visible: true; color: "black"
            LayerShell.Window.screen: modelData                 // each on its own screen (else they all land on one)
            LayerShell.Window.wantsToBeOnActiveScreen: false
            LayerShell.Window.scope: "huginn-wallpaper"
            LayerShell.Window.keyboardInteractivity: LayerShell.Window.KeyboardInteractivityNone
            LayerShell.Window.layer: LayerShell.Window.LayerBackground
            LayerShell.Window.anchors: LayerShell.Window.AnchorTop | LayerShell.Window.AnchorBottom | LayerShell.Window.AnchorLeft | LayerShell.Window.AnchorRight
            LayerShell.Window.exclusionZone: -1
            Wallpaper { anchors.fill: parent }
            Widgets { visible: wall.main; x: 22; y: 52; opacity: shell.settled ? 1 : 0; Behavior on opacity { NumberAnimation { duration: 600; easing.type: Easing.OutCubic } } }
        }
    }
    property list<QtObject> surfaces: [
    Window {   // arriving from the sign-in screen: its island carries on for a moment, then fades (takes no input)
        id: arriveWin
        objectName: "arrival"
        visible: arrival.visible; color: "transparent"
        flags: Qt.WindowTransparentForInput
        LayerShell.Window.scope: "huginn-arrival"
        LayerShell.Window.keyboardInteractivity: LayerShell.Window.KeyboardInteractivityNone
        LayerShell.Window.layer: LayerShell.Window.LayerOverlay
        LayerShell.Window.anchors: LayerShell.Window.AnchorTop | LayerShell.Window.AnchorBottom | LayerShell.Window.AnchorLeft | LayerShell.Window.AnchorRight
        LayerShell.Window.exclusionZone: -1
        Arrival { id: arrival; anchors.fill: parent; playing: arriving; opacity: arriving ? 1 : 0; onLeaving: shell.settled = true }
    },
    Window {   // top bar
        // Grows while the dropdown menu list is open; the reserved strip (exclusionZone) stays 30 px.
        visible: true; height: 30; color: "transparent"
        LayerShell.Window.scope: "huginn-topbar"
        LayerShell.Window.keyboardInteractivity: LayerShell.Window.KeyboardInteractivityNone
        LayerShell.Window.layer: LayerShell.Window.LayerTop
        LayerShell.Window.anchors: LayerShell.Window.AnchorTop | LayerShell.Window.AnchorLeft | LayerShell.Window.AnchorRight
        LayerShell.Window.exclusionZone: 30
        TopBar { id: topBar; width: parent.width; appName: Status.active.name || "Huginn"; solid: Status.active.maximized
            onWindowAction: function (action) { Status.windowAction(action) }
            opacity: shell.settled ? 1 : 0; Behavior on opacity { NumberAnimation { duration: 500; easing.type: Easing.OutCubic } } onControlCentre: shell.open = shell.open === "cc" ? "" : "cc"; onLauncher: shell.open = shell.open === "launcher" ? "" : "launcher"
            onSearch: shell.open = shell.open === "search" ? "" : "search"
            todayOpen: shell.open === "today"; onToday: shell.open = shell.open === "today" ? "" : "today"
            menuOpen: shell.open === "menu"; menuGroup: shell.menuGroup
            onAppMenu: function (group) { shell.appMenu(group) } }
    },
    Window {   // dock. Wider than the dock, so the live island can grow and shrink without the surface changing size
        id: dockWin
        visible: true; width: Math.max(dock.width, dock.restWidth + 780); height: dock.tile + 34; color: "transparent"
        LayerShell.Window.scope: "huginn-dock"
        LayerShell.Window.keyboardInteractivity: LayerShell.Window.KeyboardInteractivityNone
        LayerShell.Window.layer: LayerShell.Window.LayerTop
        LayerShell.Window.anchors: LayerShell.Window.AnchorBottom
        LayerShell.Window.exclusionZone: dock.tile + 34
        Dock {
            id: dock; inlineTips: false; anchors { horizontalCenter: parent.horizontalCenter; top: parent.top; topMargin: shell.settled ? 0 : 24 }
            opacity: shell.settled ? 1 : 0
            Behavior on opacity { NumberAnimation { duration: 500; easing.type: Easing.OutCubic } }
            Behavior on anchors.topMargin { NumberAnimation { duration: 550; easing.type: Easing.OutCubic } }
            onLauncher: shell.open = shell.open === "launcher" ? "" : "launcher"
            onControlCentre: shell.open = shell.open === "cc" ? "" : "cc"
            activate: function (app) { return Status.activateApp(app) }   // a running app's window comes forward (KWin)
            menuOpen: shell.open === "launcher"
            onIslandWanted: function (app, x) { shell.open = ""; shell.dockIslandX = x; shell.dockIsland = app }
            onTabsWanted: function (show) { if (show) { shell.tabsHide.stop(); shell.tabsShow.start() } else { shell.tabsShow.stop(); shell.tabsHide.restart() } }
            onLiveHover: function (inside) { shell.livePointer(inside) }
            onLiveFocus: function (id) { shell.liveFocus = id; shell.liveHide.stop(); shell.liveOpen = true }
            onWindowsWanted: function (app, x, show, pinned) { shell.windowsWanted(app, x, show, pinned) }
            onStackWanted: function (folder, x, menu) { shell.open = ""; shell.winApp = null; shell.stackMenu = menu; shell.stackX = x; shell.stackFolder = shell.stackFolder === folder && !menu ? "" : folder }
        }
    },
    Window {   // the live island, opened: just above the dock, lined up with the island's right edge
        id: liveWin
        visible: shell.liveShown || livePanel.visible; width: dockWin.width; height: livePanel.height + 60; color: "transparent"
        LayerShell.Window.scope: "huginn-live"
        LayerShell.Window.keyboardInteractivity: LayerShell.Window.KeyboardInteractivityNone
        LayerShell.Window.layer: LayerShell.Window.LayerTop
        LayerShell.Window.anchors: LayerShell.Window.AnchorBottom
        LivePanel {
            id: livePanel
            shown: shell.liveShown; focusId: shell.liveFocus
            readonly property real dockX: (liveWin.width - dock.width) / 2
            x: Math.max(8, Math.min(liveWin.width - width - 8, dockX + dock.liveRight - width))
            y: liveWin.height - height - 10
            originX: dockX + dock.liveCentre - x
            onPointer: function (inside) { shell.livePointer(inside) }
            onOpenWanted: function (app) { dock.openApp(app) }
        }
    },
    Window {   // an app's windows, above its tile
        id: winsWin
        visible: shell.winApp !== null; width: dockWin.width; height: appWins.height + 12; color: "transparent"
        LayerShell.Window.scope: "huginn-app-windows"
        LayerShell.Window.keyboardInteractivity: LayerShell.Window.KeyboardInteractivityNone
        LayerShell.Window.layer: LayerShell.Window.LayerTop
        LayerShell.Window.anchors: LayerShell.Window.AnchorBottom
        AppWindows {
            id: appWins
            app: shell.winApp
            x: Math.max(8, Math.min(winsWin.width - width - 8, (winsWin.width - dock.width) / 2 + shell.winX - width / 2)); y: 4
            onHoverChanged: function (inside) { if (inside) shell.winHide.stop(); else shell.winHide.restart() }
            onPicked: { shell.winPinned = false; shell.winApp = null }
            onNewWindow: { var a = shell.winApp; shell.winPinned = false; shell.winApp = null; if (a) dock.start(a) }
        }
        // a click beside a shown-by-click island closes it
        Connections { target: Status; function onActiveChanged() { if (shell.winPinned) { shell.winPinned = false; shell.winApp = null } } }
    },
    Window {   // a stack, opened: over the work area, so a click beside it closes it
        id: stackWin
        visible: shell.stackFolder !== ""; color: "transparent"
        LayerShell.Window.scope: "huginn-stack"
        LayerShell.Window.layer: LayerShell.Window.LayerTop
        LayerShell.Window.anchors: LayerShell.Window.AnchorTop | LayerShell.Window.AnchorBottom | LayerShell.Window.AnchorLeft | LayerShell.Window.AnchorRight
        LayerShell.Window.keyboardInteractivity: shell.stackFolder !== "" ? LayerShell.Window.KeyboardInteractivityOnDemand : LayerShell.Window.KeyboardInteractivityNone
        MouseArea { anchors.fill: parent; acceptedButtons: Qt.AllButtons; onClicked: shell.stackFolder = "" }
        StackIsland {
            id: stackIsland
            folder: shell.stackFolder; startWithMenu: shell.stackMenu
            visible: shell.stackFolder !== ""; focus: true
            x: Math.max(8, Math.min(stackWin.width - width - 8, (stackWin.width - dock.width) / 2 + shell.stackX - width / 2))
            y: stackWin.height - height - 8
            onDone: shell.stackFolder = ""
        }
    },
    Window {   // a file that just landed in a stack flies into it, from the window in front (takes no input)
        id: flightWin
        visible: flight.running; color: "transparent"
        flags: Qt.WindowTransparentForInput
        LayerShell.Window.scope: "huginn-stack-flight"
        LayerShell.Window.keyboardInteractivity: LayerShell.Window.KeyboardInteractivityNone
        LayerShell.Window.layer: LayerShell.Window.LayerOverlay
        LayerShell.Window.anchors: LayerShell.Window.AnchorTop | LayerShell.Window.AnchorBottom | LayerShell.Window.AnchorLeft | LayerShell.Window.AnchorRight
        LayerShell.Window.exclusionZone: -1
        property point from: Qt.point(0, 0)
        property point to: Qt.point(0, 0)
        property real t: 0
        property string folder: ""
        FileArt {
            id: flyer
            size: 46 - 10 * flightWin.t
            // a curve up and over, then down into the pile
            readonly property point mid: Qt.point((flightWin.from.x + flightWin.to.x) / 2, Math.min(flightWin.from.y, flightWin.to.y) - 160)
            x: (1 - flightWin.t) * (1 - flightWin.t) * flightWin.from.x + 2 * (1 - flightWin.t) * flightWin.t * mid.x + flightWin.t * flightWin.t * flightWin.to.x - width / 2
            y: (1 - flightWin.t) * (1 - flightWin.t) * flightWin.from.y + 2 * (1 - flightWin.t) * flightWin.t * mid.y + flightWin.t * flightWin.t * flightWin.to.y - height / 2
            rotation: 18 * Math.sin(flightWin.t * Math.PI)
        }
        NumberAnimation {
            id: flight; target: flightWin; property: "t"; from: 0; to: 1; duration: 640; easing.type: Easing.InOutCubic
            onFinished: dock.stackLanded(flightWin.folder)
        }
        Connections {
            target: Stacks
            function onLanded(folder, name, kind) {
                var st = Stacks.stacks.filter(function (s) { return s.folder === folder })[0]
                if (!st || Theme.t.openMs === 0 || !shell.settled) { dock.stackLanded(folder); return }
                flyer.file = st.items.filter(function (i) { return i.name === name })[0] || { kind: kind }
                var w = Status.windows.filter(function (w) { return w.active && !w.minimised })[0]
                var sw = flightWin.screen ? flightWin.screen.width : 1280, sh = flightWin.screen ? flightWin.screen.height : 800
                flightWin.from = w && w.w > 0 ? Qt.point(w.x + w.w / 2, w.y + w.h / 2) : Qt.point(sw / 2, sh / 2)
                flightWin.to = Qt.point((sw - dock.width) / 2 + dock.stackX(folder), sh - dockWin.height + 32)
                flightWin.folder = folder
                flight.restart()
            }
        }
    },
    Window {   // the name of the dock item under the pointer; never takes clicks
        visible: dock.tipText !== "" && shell.winApp === null; width: dock.width; height: 34; color: "transparent"
        flags: Qt.WindowTransparentForInput
        LayerShell.Window.scope: "huginn-dock-tip"
        LayerShell.Window.keyboardInteractivity: LayerShell.Window.KeyboardInteractivityNone
        LayerShell.Window.layer: LayerShell.Window.LayerTop
        LayerShell.Window.anchors: LayerShell.Window.AnchorBottom
        Glass {
            popup: true; radius: Theme.t.radiusControl; width: tipLabel.width + 16; height: 26
            x: Math.max(0, Math.min(parent.width - width, dock.tipX - width / 2)); y: 2
            Label { id: tipLabel; anchors.centerIn: parent; text: dock.tipText; font.pixelSize: 12 }
        }
    },
    Window {   // Huginn's tab stack. As wide as the dock and centred like it, so dock x positions line up.
        visible: shell.tabsOpen; width: dock.width; height: 620; color: "transparent"
        LayerShell.Window.scope: "huginn-tabs"
        LayerShell.Window.keyboardInteractivity: LayerShell.Window.KeyboardInteractivityNone
        LayerShell.Window.layer: LayerShell.Window.LayerTop
        LayerShell.Window.anchors: LayerShell.Window.AnchorBottom
        MouseArea { anchors.fill: parent; onClicked: shell.tabsOpen = false }
        TabStack {
            x: Math.max(0, Math.min(parent.width - width, dock.tabsX - width / 2))
            anchors { bottom: parent.bottom; bottomMargin: 6 }
            onHoverChanged: function (inside) { if (inside) shell.tabsHide.stop(); else shell.tabsHide.restart() }
            onPicked: shell.tabsOpen = false
        }
    },
    Window {   // Today: under the bar (the work area, so a click beside its islands closes it)
        id: todayWin
        visible: shell.open === "today" || todayIslands.visible; color: "transparent"
        LayerShell.Window.scope: "huginn-today"
        LayerShell.Window.layer: LayerShell.Window.LayerTop
        LayerShell.Window.anchors: LayerShell.Window.AnchorTop | LayerShell.Window.AnchorBottom | LayerShell.Window.AnchorLeft | LayerShell.Window.AnchorRight
        LayerShell.Window.keyboardInteractivity: shell.open === "today" ? LayerShell.Window.KeyboardInteractivityExclusive : LayerShell.Window.KeyboardInteractivityNone
        MouseArea { anchors.fill: parent; acceptedButtons: Qt.AllButtons; onClicked: shell.open = "" }
        TodayIslands {
            id: todayIslands
            x: Math.max(10, topBar.dateLeft); y: 8; focus: true
            width: 652; height: parent.height - 16
            shown: shell.open === "today"
            origin: Qt.point(30, -16)
            onDone: shell.open = ""
        }
    },
    Window {   // the app's menu, under its name (the work area, so a click beside it closes it)
        id: menuWin
        visible: shell.open === "menu"; color: "transparent"
        LayerShell.Window.scope: "huginn-app-menu"
        LayerShell.Window.layer: LayerShell.Window.LayerOverlay
        LayerShell.Window.anchors: LayerShell.Window.AnchorTop | LayerShell.Window.AnchorBottom | LayerShell.Window.AnchorLeft | LayerShell.Window.AnchorRight
        LayerShell.Window.keyboardInteractivity: shell.open === "menu" ? LayerShell.Window.KeyboardInteractivityExclusive : LayerShell.Window.KeyboardInteractivityNone
        MouseArea { anchors.fill: parent; acceptedButtons: Qt.AllButtons; onClicked: shell.open = "" }
        AppMenuIsland {
            id: appMenuIsland
            shown: shell.open === "menu"; only: shell.menuGroup; focus: true
            x: Math.max(6, (shell.menuGroup === "" ? topBar.nameLeft : topBar.groupLeft(shell.menuGroup)) - 6); y: 3
            onDone: shell.open = ""
        }
    },
    Window {   // control centre: slides in from the right edge, and back out
        id: ccWin
        visible: shell.open === "cc" || ccPanel.x < width - 1; width: 364; color: "transparent"
        LayerShell.Window.scope: "huginn-control-centre"
        LayerShell.Window.layer: LayerShell.Window.LayerOverlay
        LayerShell.Window.anchors: LayerShell.Window.AnchorTop | LayerShell.Window.AnchorBottom | LayerShell.Window.AnchorRight
        LayerShell.Window.keyboardInteractivity: LayerShell.Window.KeyboardInteractivityOnDemand
        ControlCentre {
            id: ccPanel
            y: 10; width: parent.width - 20; height: parent.height - 20
            x: shell.open === "cc" ? 10 : parent.width
            opacity: shell.open === "cc" ? 1 : 0
            Behavior on x { NumberAnimation { duration: Theme.t.openMs ? 260 : 0; easing.type: Easing.OutCubic } }
            Behavior on opacity { NumberAnimation { duration: Theme.t.openMs ? 200 : 0 } }
        }
    },
    Window {   // launcher: the whole work area (between the bar and the dock), so a click beside it closes it
        id: launcherWin
        visible: shell.open === "launcher" || launcher.visible; color: "transparent"
        LayerShell.Window.scope: "huginn-launcher"
        LayerShell.Window.layer: LayerShell.Window.LayerOverlay
        LayerShell.Window.anchors: LayerShell.Window.AnchorTop | LayerShell.Window.AnchorBottom | LayerShell.Window.AnchorLeft | LayerShell.Window.AnchorRight
        LayerShell.Window.keyboardInteractivity: shell.open === "launcher" ? LayerShell.Window.KeyboardInteractivityExclusive : LayerShell.Window.KeyboardInteractivityNone
        Rectangle { anchors.fill: parent; color: "black"; opacity: launcher.presence * 0.22 }
        MouseArea { anchors.fill: parent; onClicked: shell.open = "" }
        Launcher {
            id: launcher; shown: shell.open === "launcher"; onDone: shell.open = ""
            onSearchEverything: function (text) { shell.searchText = text; shell.open = "search" }
            anchors { horizontalCenter: parent.horizontalCenter; bottom: parent.bottom; bottomMargin: 10 }
            height: Math.min(660, parent.height - 20)
            // the dock's orb (its window sits just below this one): where the menu grows from
            orb: Qt.point((launcherWin.width - dock.width) / 2 + 32 - x, launcherWin.height + 32 - y)
        }
    },
    Window {   // Search everything: over the whole screen, bar and dock included
        visible: shell.open === "search" || search.visible; color: "transparent"
        LayerShell.Window.scope: "huginn-search"
        LayerShell.Window.layer: LayerShell.Window.LayerOverlay
        LayerShell.Window.anchors: LayerShell.Window.AnchorTop | LayerShell.Window.AnchorBottom | LayerShell.Window.AnchorLeft | LayerShell.Window.AnchorRight
        LayerShell.Window.exclusionZone: -1
        LayerShell.Window.keyboardInteractivity: shell.open === "search" ? LayerShell.Window.KeyboardInteractivityExclusive : LayerShell.Window.KeyboardInteractivityNone
        Rectangle { anchors.fill: parent; color: "black"; opacity: search.presence * 0.4 }
        Search { id: search; anchors.fill: parent; shown: shell.open === "search"; startText: shell.searchText; onDone: { shell.open = ""; shell.searchText = "" } }
    },
    Window {   // an app's island, from the dock (right-click or a long press on its tile)
        id: islandWin
        visible: shell.dockIsland !== null; color: "transparent"
        LayerShell.Window.scope: "huginn-app-island"
        LayerShell.Window.layer: LayerShell.Window.LayerOverlay
        LayerShell.Window.anchors: LayerShell.Window.AnchorTop | LayerShell.Window.AnchorBottom | LayerShell.Window.AnchorLeft | LayerShell.Window.AnchorRight
        LayerShell.Window.keyboardInteractivity: shell.dockIsland ? LayerShell.Window.KeyboardInteractivityExclusive : LayerShell.Window.KeyboardInteractivityNone
        MouseArea { anchors.fill: parent; acceptedButtons: Qt.AllButtons; onClicked: shell.dockIsland = null }
        AppIsland {
            id: dockIsland
            visible: shell.dockIsland !== null
            x: Math.max(8, Math.min(islandWin.width - width - 8, (islandWin.width - dock.width) / 2 + shell.dockIslandX - width / 2))
            y: islandWin.height - height - 8
            onDone: shell.dockIsland = null
        }
        onVisibleChanged: if (visible) dockIsland.open(shell.dockIsland)
    }
    ,
    Window {   // the Welcome tour: over everything; it takes clicks only on its island (and on its full-screen pages)
        id: tourWin
        visible: tour.running; color: "transparent"
        LayerShell.Window.scope: "huginn-tour"
        LayerShell.Window.layer: LayerShell.Window.LayerOverlay
        LayerShell.Window.anchors: LayerShell.Window.AnchorTop | LayerShell.Window.AnchorBottom | LayerShell.Window.AnchorLeft | LayerShell.Window.AnchorRight
        LayerShell.Window.exclusionZone: -1
        LayerShell.Window.keyboardInteractivity: !tour.running ? LayerShell.Window.KeyboardInteractivityNone : tour.phase === "pages" ? LayerShell.Window.KeyboardInteractivityExclusive : LayerShell.Window.KeyboardInteractivityOnDemand
        TourHost {
            id: tour
            anchors.fill: parent; focus: true
            appName: topBar.appName
            todayOpen: shell.open === "today"; menuOpen: shell.open === "menu"
            windowCount: Status.windows.length
            snapped: { var w = shell.frontWindow(); return !!w && w.x <= 24 && w.w < tourWin.width * 0.62 && w.h > tourWin.height * 0.55 }
            target: function (name) {
                var W = tourWin.width, H = tourWin.height, dx = (W - dock.width) / 2
                var isl = dock.tile + 20, top = H - dockWin.height
                if (name === "dock") return Qt.rect(dx, top, dock.restWidth, isl)
                if (name === "orb") return Qt.rect(dx, top, isl, isl)
                if (name === "date") return Qt.rect(topBar.dateLeft, 4, topBar.dateWidth, 22)
                if (name === "name") return Qt.rect(topBar.nameLeft, 4, topBar.nameWidth, 22)
                if (name === "window") { var w = shell.frontWindow(); if (w && w.w > 0) return Qt.rect(w.x, w.y, w.w, w.h) }
                return Qt.rect(W / 2 - 1, H / 2 - 1, 2, 2)
            }
            onMaskChanged: function (r) { Tour.setMask(tourWin, r.x, r.y, r.width, r.height) }
            onCloseOpenThings: if (shell.open === "today" || shell.open === "menu") shell.open = ""
            onInstallWanted: Apps.launch("python3 /usr/share/huginn-apps/huginn_app.py installer")
            onFinished: shell.touring = false
        }
    }
    ,
    Window {   // the Overview's words and controls (Huginn's compositor spreads the windows under it)
        id: overviewWin
        visible: overview.visible; color: "transparent"
        LayerShell.Window.scope: "huginn-overview"
        LayerShell.Window.layer: LayerShell.Window.LayerOverlay
        LayerShell.Window.anchors: LayerShell.Window.AnchorTop | LayerShell.Window.AnchorBottom | LayerShell.Window.AnchorLeft | LayerShell.Window.AnchorRight
        LayerShell.Window.exclusionZone: -1
        LayerShell.Window.keyboardInteractivity: overview.open ? LayerShell.Window.KeyboardInteractivityExclusive : LayerShell.Window.KeyboardInteractivityNone
        OverviewOverlay { id: overview; anchors.fill: parent; focus: true; onSearchWanted: function (text) { shell.searchText = text; shell.open = "search" } }
    },
    Window {   // snapping: where a dragged window will land (takes no input), and filling the other half
        id: snapWin
        visible: snapGlass.previewing || snapGlass.assisting; color: "transparent"
        flags: snapGlass.assisting ? 0 : Qt.WindowTransparentForInput
        LayerShell.Window.scope: "huginn-snap"
        LayerShell.Window.layer: LayerShell.Window.LayerTop
        LayerShell.Window.anchors: LayerShell.Window.AnchorTop | LayerShell.Window.AnchorBottom | LayerShell.Window.AnchorLeft | LayerShell.Window.AnchorRight
        LayerShell.Window.exclusionZone: -1
        LayerShell.Window.keyboardInteractivity: LayerShell.Window.KeyboardInteractivityNone
        SnapGlass { id: snapGlass; anchors.fill: parent }
    },
    Window {   // Alt+Tab: the windows while Alt is held (Huginn's compositor goes through them)
        id: switchWin
        visible: Status.switcher.windows !== undefined && Status.switcher.windows.length > 1; color: "transparent"
        flags: Qt.WindowTransparentForInput
        width: switchWin.screen ? switchWin.screen.width : 1280; height: 190   // across the screen, in the middle (the island centres in it)
        LayerShell.Window.anchors: LayerShell.Window.AnchorLeft | LayerShell.Window.AnchorRight
        LayerShell.Window.exclusionZone: -1
        LayerShell.Window.scope: "huginn-switcher"
        LayerShell.Window.layer: LayerShell.Window.LayerOverlay
        LayerShell.Window.keyboardInteractivity: LayerShell.Window.KeyboardInteractivityNone
        Switcher {
            id: switcher
            anchors.centerIn: parent
            showing: switchWin.visible
            index: Status.switcher.at || 0
            windows: (Status.switcher.windows || []).map(function (w) {
                var a = overview.appFor(w.app), known = Status.windows.filter(function (x) { return x.id === w.id })[0]
                var g = a && a.colours && a.colours.length ? a.colours[0] : Theme.t.accent
                return { app: a || { name: w.title }, title: w.title, minimised: known ? known.minimised : false, glow: Qt.color(g) }
            })
        }
    },
    Window {   // the space's name, for a moment, after switching
        id: spaceWin
        visible: spaceName.opacity > 0; color: "transparent"
        flags: Qt.WindowTransparentForInput
        width: spaceName.width + 20; height: 60
        LayerShell.Window.scope: "huginn-space-name"
        LayerShell.Window.layer: LayerShell.Window.LayerOverlay
        LayerShell.Window.anchors: LayerShell.Window.AnchorTop
        LayerShell.Window.keyboardInteractivity: LayerShell.Window.KeyboardInteractivityNone
        Glass {
            id: spaceName
            popup: true; dense: true; radius: 18; x: 10; y: 12
            width: spaceLabel.width + 40; height: 40; opacity: 0
            property int last: -1
            Label { id: spaceLabel; anchors.centerIn: parent; text: (Status.spaces.names || [])[Status.spaces.current] || ""; font.pixelSize: 14; font.weight: Font.DemiBold }
            Connections {
                target: Status
                function onWindowsChanged() {
                    var cur = Status.spaces.current
                    if (spaceName.last >= 0 && cur !== spaceName.last && !overview.open) flash.restart()
                    spaceName.last = cur
                }
            }
            SequentialAnimation {
                id: flash
                NumberAnimation { target: spaceName; property: "opacity"; to: 1; duration: 120 }
                PauseAnimation { duration: 1100 }
                NumberAnimation { target: spaceName; property: "opacity"; to: 0; duration: 300 }
            }
        }
    },
    Window {   // the hot corner (top right; off until turned on): the Overview
        visible: Settings.hotCorner; width: 2; height: 2; color: "transparent"
        LayerShell.Window.scope: "huginn-hot-corner"
        LayerShell.Window.layer: LayerShell.Window.LayerOverlay
        LayerShell.Window.anchors: LayerShell.Window.AnchorTop | LayerShell.Window.AnchorRight
        LayerShell.Window.exclusionZone: -1
        LayerShell.Window.keyboardInteractivity: LayerShell.Window.KeyboardInteractivityNone
        MouseArea { anchors.fill: parent; hoverEnabled: true; onEntered: Status.overviewDo("toggle") }
    }
    ]
}
