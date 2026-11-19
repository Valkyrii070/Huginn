import QtQuick
import QtQuick.Effects
import QtWayland.Compositor
import QtWayland.Compositor.XdgShell

// One app window in Huginn's compositor. Huginn's own apps draw their glass and islands themselves, so here they
// get only a soft shadow and, while in front, a faint glow in the app's own colour. Other apps (which we ask not
// to draw a title bar) get a floating island above the window: close, minimise, maximise and the app's name, to
// drag it by, plus edges to resize from. The session daemon's windows ("huginn:banners", "huginn:osd",
// "huginn:prompt") get no chrome: the compositor places them itself.
Item {
    id: chrome
    property var host                                  // the compositor scene: placing, raising, focus
    property XdgSurface xdgSurface
    readonly property XdgToplevel toplevel: xdgSurface ? xdgSurface.toplevel : null
    readonly property string appId: toplevel ? toplevel.appId : ""
    readonly property string title: toplevel ? toplevel.title : ""
    readonly property string role: title.indexOf("huginn:") === 0 ? title.slice(7) : ""
    readonly property bool ours: appId.indexOf("huginn") === 0 || appId.indexOf("org.huginn") === 0
    readonly property bool decorated: !ours && role === "" && !fullscreen
    readonly property bool maximized: toplevel ? toplevel.maximized : false
    readonly property bool fullscreen: toplevel ? toplevel.fullscreen : false
    readonly property bool active: toplevel ? toplevel.activated : false
    readonly property var app: Comp.appFor(appId)
    readonly property color glow: app.colour ? app.colour : Theme.t.accent
    readonly property bool inhibitsIdle: surfaceItem.surface ? surfaceItem.surface.inhibitsIdle : false
    property bool minimised: false
    property bool closing: false
    property bool placed: false
    property bool shrunk: false                        // asked once to fit a small screen
    property int stack: 0
    signal gone()
    width: surfaceItem.width; height: surfaceItem.height
    z: role !== "" ? 1000 + stack : stack
    visible: !minimised || hideAnim.running

    function activate() { if (!minimised) { surfaceItem.takeFocus(); host.raise(chrome) } }
    function close() { if (toplevel) toplevel.sendClose() }
    function minimise() { if (!minimised && role === "") { minimised = true; hideAnim.restart(); host.refocus() } }
    function restore() { if (minimised) { minimised = false; showAnim.restart() } activate() }
    function toggleMaximised() { if (!toplevel) return; if (maximized) toplevel.unsetMaximized(); else toplevel.setMaximized() }

    // ---- shadow and, in front, the app's glow
    RectangularShadow {
        anchors.fill: surfaceItem
        visible: chrome.role === "" && !chrome.fullscreen && !chrome.maximized
        radius: chrome.ours ? Theme.t.radiusWindow : 10
        blur: chrome.active ? 56 : 32; spread: -4
        offset.y: chrome.active ? 18 : 10
        color: Qt.rgba(0, 0, 0, chrome.active ? 0.5 : 0.32)
        Behavior on blur { NumberAnimation { duration: 180 } }
    }
    RectangularShadow {
        anchors.fill: surfaceItem
        visible: chrome.ours && chrome.active && chrome.role === "" && !chrome.fullscreen && !chrome.maximized
        radius: Theme.t.radiusWindow; blur: 44; spread: -10
        color: Qt.rgba(chrome.glow.r, chrome.glow.g, chrome.glow.b, 0.30)
    }

    ShellSurfaceItem {
        id: surfaceItem
        objectName: "surface"
        shellSurface: chrome.xdgSurface
        moveItem: chrome
        output: chrome.host.outputAt(chrome.x + chrome.width / 2, chrome.y + chrome.height / 2)   // the screen it's on
        autoCreatePopupItems: true
        focusOnClick: chrome.role === "" || chrome.role === "prompt"
        inputEventsEnabled: chrome.role !== "osd"
        onSurfaceDestroyed: { bufferLocked = true; chrome.closing = true; closeAnim.start() }
        // A click anywhere in the window brings it forward.
        TapHandler { gesturePolicy: TapHandler.DragThreshold; onPressedChanged: if (pressed) chrome.host.raise(chrome) }
    }

    // ---- other apps: an island above the window to move, close, minimise and maximise it by
    Rectangle {
        id: island
        objectName: "island"
        visible: chrome.decorated && !chrome.maximized
        y: -44; x: 0; height: 36; radius: 14; width: Math.min(row.width + 16, Math.max(140, chrome.width))
        color: Theme.t.island; border.width: 1; border.color: chrome.active ? Qt.rgba(chrome.glow.r, chrome.glow.g, chrome.glow.b, 0.55) : Theme.t.islandLine
        MouseArea {
            anchors.fill: parent
            property point grab
            onPressed: function (m) { grab = Qt.point(m.x, m.y); chrome.activate() }
            onPositionChanged: function (m) { if (pressed) { chrome.x += m.x - grab.x; chrome.y = Math.max(chrome.host.top + 44, chrome.y + m.y - grab.y) } }
            onDoubleClicked: chrome.toggleMaximised()
        }
        Row {
            id: row
            x: 10; height: parent.height; spacing: 7
            Repeater {
                model: [{ c: "#FF5F57", f: "close" }, { c: "#FEBC2E", f: "min" }, { c: "#28C840", f: "max" }]
                Rectangle {
                    required property var modelData
                    objectName: "chrome-" + modelData.f
                    width: 12; height: 12; radius: 6; anchors.verticalCenter: parent.verticalCenter
                    color: chrome.active || dot.containsMouse ? modelData.c : Theme.t.separator
                    MouseArea { id: dot; anchors.fill: parent; anchors.margins: -4; hoverEnabled: true
                        onClicked: modelData.f === "close" ? chrome.close() : modelData.f === "min" ? chrome.minimise() : chrome.toggleMaximised() }
                }
            }
            Item { width: 2; height: 1 }
            Label { text: chrome.app.name || chrome.title; font.pixelSize: 12; font.weight: Font.DemiBold; anchors.verticalCenter: parent.verticalCenter }
            Label { visible: chrome.title !== "" && chrome.title !== chrome.app.name; text: chrome.title; secondary: true; font.pixelSize: 12
                width: Math.min(implicitWidth, 260); elide: Text.ElideRight; anchors.verticalCenter: parent.verticalCenter }
            Item { width: 2; height: 1 }
        }
    }
    // edges to resize other apps from (ours ask for it themselves)
    Repeater {
        model: chrome.decorated && !chrome.maximized ? [Qt.RightEdge, Qt.BottomEdge, Qt.RightEdge | Qt.BottomEdge, Qt.LeftEdge, Qt.LeftEdge | Qt.BottomEdge] : []
        MouseArea {
            required property int modelData
            readonly property bool r: modelData & Qt.RightEdge
            readonly property bool l: modelData & Qt.LeftEdge
            readonly property bool b: modelData & Qt.BottomEdge
            x: r ? chrome.width - 4 : l ? -6 : 0; y: b ? chrome.height - 4 : 0
            width: (r || l) ? 10 : chrome.width; height: b ? 10 : chrome.height
            cursorShape: (r && b) ? Qt.SizeFDiagCursor : (l && b) ? Qt.SizeBDiagCursor : (r || l) ? Qt.SizeHorCursor : Qt.SizeVerCursor
            property point start
            property size from
            property real left0
            onPressed: function (m) { start = mapToItem(chrome.parent, m.x, m.y); from = Qt.size(chrome.width, chrome.height); left0 = chrome.x; chrome.activate() }
            onPositionChanged: function (m) {
                if (!pressed || !chrome.toplevel) return
                var p = mapToItem(chrome.parent, m.x, m.y), w = from.width, h = from.height
                if (r) w = from.width + p.x - start.x
                if (l) w = from.width - (p.x - start.x)
                if (b) h = from.height + p.y - start.y
                w = Math.max(240, w); h = Math.max(160, h)
                chrome.toplevel.sendResizing(Qt.size(w, h))
                if (l) chrome.x = left0 + from.width - w
            }
            onReleased: if (chrome.toplevel) chrome.toplevel.sendResizing(Qt.size(chrome.width, chrome.height))
        }
    }

    // ---- coming, going, minimising
    transformOrigin: Item.Center
    opacity: 0; scale: 0.94
    ParallelAnimation { id: openAnim; running: true
        NumberAnimation { target: chrome; property: "opacity"; to: 1; duration: chrome.role === "osd" ? 120 : 190; easing.type: Easing.OutCubic }
        NumberAnimation { target: chrome; property: "scale"; to: 1; duration: 230; easing.type: Easing.OutBack; easing.overshoot: 0.6 } }
    ParallelAnimation { id: closeAnim
        NumberAnimation { target: chrome; property: "opacity"; to: 0; duration: 160; easing.type: Easing.InCubic }
        NumberAnimation { target: chrome; property: "scale"; to: 0.94; duration: 160; easing.type: Easing.InCubic }
        onFinished: chrome.gone() }
    ParallelAnimation { id: hideAnim
        NumberAnimation { target: chrome; property: "opacity"; to: 0; duration: 220; easing.type: Easing.InCubic }
        NumberAnimation { target: chrome; property: "scale"; to: 0.6; duration: 240; easing.type: Easing.InCubic } }
    ParallelAnimation { id: showAnim
        NumberAnimation { target: chrome; property: "opacity"; to: 1; duration: 200; easing.type: Easing.OutCubic }
        NumberAnimation { target: chrome; property: "scale"; to: 1; duration: 240; easing.type: Easing.OutBack; easing.overshoot: 0.6 } }

    Connections {
        target: chrome.toplevel
        function onSetMinimized() { chrome.minimise() }
        function onActivatedChanged() { if (chrome.toplevel.activated) chrome.host.raise(chrome) }
    }
    // placed once its size is known: the daemon's windows where they belong, others in the middle of the free space
    onWidthChanged: if (!placed && width > 1 && height > 1) host.place(chrome)
    Timer { running: chrome.shrunk && !chrome.placed; interval: 1500; onTriggered: chrome.host.place(chrome) }   // it didn't change size
    onHeightChanged: if (!placed && width > 1 && height > 1) host.place(chrome)
    onRoleChanged: if (placed) host.place(chrome)
}
