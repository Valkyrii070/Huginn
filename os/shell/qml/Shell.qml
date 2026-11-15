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
    property Timer tabsShow: Timer { interval: 350; onTriggered: { Tabs.refresh(); shell.tabsOpen = true } }
    property Timer tabsHide: Timer { interval: 350; onTriggered: shell.tabsOpen = false }
    property Connections keys: Connections {
        target: Status
        function onLauncherWanted() { shell.open = shell.open === "launcher" ? "" : "launcher" }
        function onSearchWanted(text) { shell.searchText = text; shell.open = shell.open === "search" && !text ? "" : "search" }
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
        visible: true; height: topBar.dropdownOpen ? 260 : 30; color: "transparent"
        LayerShell.Window.scope: "huginn-topbar"
        LayerShell.Window.keyboardInteractivity: LayerShell.Window.KeyboardInteractivityNone
        LayerShell.Window.layer: LayerShell.Window.LayerTop
        LayerShell.Window.anchors: LayerShell.Window.AnchorTop | LayerShell.Window.AnchorLeft | LayerShell.Window.AnchorRight
        LayerShell.Window.exclusionZone: 30
        MouseArea { anchors.fill: parent; enabled: topBar.dropdownOpen; onClicked: topBar.menusOpen = false }
        TopBar { id: topBar; width: parent.width; appName: Status.active.name || "Huginn"; solid: Status.active.maximized
            onWindowAction: function (action) { Status.windowAction(action) }
            opacity: shell.settled ? 1 : 0; Behavior on opacity { NumberAnimation { duration: 500; easing.type: Easing.OutCubic } } onControlCentre: shell.open = shell.open === "cc" ? "" : "cc"; onLauncher: shell.open = shell.open === "launcher" ? "" : "launcher"
            onSearch: shell.open = shell.open === "search" ? "" : "search" }
    },
    Window {   // dock. Wider than the dock, so the live island can grow and shrink without the surface changing size
        id: dockWin
        visible: true; width: Math.max(dock.width, dock.restWidth + 780); height: 78; color: "transparent"
        LayerShell.Window.scope: "huginn-dock"
        LayerShell.Window.keyboardInteractivity: LayerShell.Window.KeyboardInteractivityNone
        LayerShell.Window.layer: LayerShell.Window.LayerTop
        LayerShell.Window.anchors: LayerShell.Window.AnchorBottom
        LayerShell.Window.exclusionZone: 78
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
    Window {   // the name of the dock item under the pointer; never takes clicks
        visible: dock.tipText !== ""; width: dock.width; height: 34; color: "transparent"
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
    ]
}
