import QtQuick
import QtQuick.Window

// Design preview: the whole shell in one ordinary window. Runs anywhere Qt runs.
Window {
    id: win
    width: 1600; height: 1000; visible: true; title: "Huginn Shell preview"
    color: Theme.t.window
    property string open: startOpen === "tabs" || startOpen === "live" ? "" : startOpen
    property bool tabsOpen: startOpen === "tabs"
    Timer { id: tabsShow; interval: 350; onTriggered: { Tabs.refresh(); win.tabsOpen = true } }
    Timer { id: tabsHide; interval: 350; onTriggered: win.tabsOpen = false }
    Wallpaper { anchors.fill: parent }
    MouseArea { anchors.fill: parent; onClicked: win.open = "" }
    Widgets { x: 22; y: 52 }
    property string searchText: ""
    TopBar { width: parent.width; onControlCentre: win.open = win.open === "cc" ? "" : "cc"; onLauncher: win.open = win.open === "launcher" ? "" : "launcher"; onSearch: win.open = win.open === "search" ? "" : "search" }
    Dock {
        id: dock
        anchors { horizontalCenter: parent.horizontalCenter; bottom: parent.bottom; bottomMargin: 14 }
        onLauncher: win.open = win.open === "launcher" ? "" : "launcher"
        onControlCentre: win.open = win.open === "cc" ? "" : "cc"
        onTabsWanted: function (show) { if (show) { tabsHide.stop(); tabsShow.start() } else { tabsShow.stop(); tabsHide.restart() } }
        onLiveHover: function (inside) { if (inside) { liveHide.stop(); liveShow.start() } else { liveShow.stop(); liveHide.restart() } }
        onLiveFocus: function (id) { win.liveFocus = id; win.liveOpen = true }
    }
    property bool liveOpen: startOpen === "live"
    property string liveFocus: ""
    Timer { id: liveShow; interval: 300; onTriggered: win.liveOpen = true }
    Timer { id: liveHide; interval: 350; onTriggered: { win.liveOpen = false; win.liveFocus = "" } }
    LivePanel {
        objectName: "livePanel"
        shown: (win.liveOpen || Live.ringing) && Live.active
        focusId: win.liveFocus
        x: Math.min(parent.width - width - 8, dock.x + dock.liveRight - width); y: dock.y - height - 10
        originX: dock.x + dock.liveCentre - x
        onPointer: function (inside) { if (inside) liveHide.stop(); else if (startOpen !== "live") liveHide.restart() }
        onOpenWanted: function (app) { dock.openApp(app) }
    }
    Arrival { anchors.fill: parent; z: 50; playing: arriving; opacity: arriving ? 1 : 0 }
    TabStack {
        visible: opacity > 0; opacity: win.tabsOpen ? 1 : 0
        x: dock.x + (dock.tabsX > 0 ? dock.tabsX : 150) - width / 2; y: dock.y - height - 12
        onHoverChanged: function (inside) { if (inside) tabsHide.stop(); else tabsHide.restart() }
        onPicked: win.tabsOpen = false
        Behavior on opacity { NumberAnimation { duration: 150 } }
    }
    ControlCentre {
        y: 40; height: parent.height - 132
        x: win.open === "cc" ? parent.width - width - 10 : parent.width + 10
        Behavior on x { NumberAnimation { duration: 220; easing.type: Easing.OutCubic } }
    }
    Rectangle { anchors.fill: parent; color: "black"; opacity: launcher.presence * 0.22 + search.presence * 0.4; visible: opacity > 0 }
    Launcher {
        id: launcher
        onDone: win.open = ""
        onSearchEverything: function (text) { search.startText = text; win.open = "search" }
        shown: win.open === "launcher"
        height: Math.min(660, parent.height - 132)
        anchors { horizontalCenter: parent.horizontalCenter; bottom: parent.bottom; bottomMargin: 92 }
        orb: Qt.point(dock.x + 32 - x, dock.y + 32 - y)
    }
    Search {
        id: search
        anchors.fill: parent
        shown: win.open === "search"
        onDone: win.open = ""
        Component.onCompleted: if (startQuery) text = startQuery
    }
}
