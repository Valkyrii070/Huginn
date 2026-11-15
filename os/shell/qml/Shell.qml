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
    property Timer tabsShow: Timer { interval: 350; onTriggered: { Tabs.refresh(); shell.tabsOpen = true } }
    property Timer tabsHide: Timer { interval: 350; onTriggered: shell.tabsOpen = false }
    property list<QtObject> surfaces: [

    Window {   // wallpaper + widgets
        visible: true; color: "black"
        LayerShell.Window.scope: "huginn-wallpaper"
        LayerShell.Window.keyboardInteractivity: LayerShell.Window.KeyboardInteractivityNone
        LayerShell.Window.layer: LayerShell.Window.LayerBackground
        LayerShell.Window.anchors: LayerShell.Window.AnchorTop | LayerShell.Window.AnchorBottom | LayerShell.Window.AnchorLeft | LayerShell.Window.AnchorRight
        LayerShell.Window.exclusionZone: -1
        Wallpaper { anchors.fill: parent }
        Widgets { x: 22; y: 52; opacity: shell.settled ? 1 : 0; Behavior on opacity { NumberAnimation { duration: 600; easing.type: Easing.OutCubic } } }
    },
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
            opacity: shell.settled ? 1 : 0; Behavior on opacity { NumberAnimation { duration: 500; easing.type: Easing.OutCubic } } onControlCentre: shell.open = shell.open === "cc" ? "" : "cc"; onLauncher: shell.open = shell.open === "launcher" ? "" : "launcher" }
    },
    Window {   // dock
        visible: true; width: dock.width; height: 78; color: "transparent"
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
            onTabsWanted: function (show) { if (show) { shell.tabsHide.stop(); shell.tabsShow.start() } else { shell.tabsShow.stop(); shell.tabsHide.restart() } }
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
    Window {   // control centre
        visible: shell.open === "cc"; width: 364; color: "transparent"
        LayerShell.Window.scope: "huginn-control-centre"
        LayerShell.Window.layer: LayerShell.Window.LayerOverlay
        LayerShell.Window.anchors: LayerShell.Window.AnchorTop | LayerShell.Window.AnchorBottom | LayerShell.Window.AnchorRight
        LayerShell.Window.keyboardInteractivity: LayerShell.Window.KeyboardInteractivityOnDemand
        ControlCentre { anchors { fill: parent; margins: 10 } }
    },
    Window {   // launcher
        visible: shell.open === "launcher"; width: 450; height: 580; color: "transparent"
        LayerShell.Window.scope: "huginn-launcher"
        LayerShell.Window.layer: LayerShell.Window.LayerOverlay
        LayerShell.Window.anchors: LayerShell.Window.AnchorBottom
        LayerShell.Window.keyboardInteractivity: LayerShell.Window.KeyboardInteractivityExclusive
        Launcher { anchors.centerIn: parent; onDone: shell.open = "" }
    }
    ]
}
