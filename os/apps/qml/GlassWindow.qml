import QtQuick
import QtQuick.Window
import QtQuick.Shapes

// The frame of a glass-and-islands app: no title bar, a rounded window tinted with the app's colour, light in that
// colour coming from where the app's main island sits, and controls floating in islands above the content.
Window {
    id: win
    property string glow: "bottom"            // where the light comes from: bottom, top, left, right, centre or none
    property real glowX: 0.5                  // for "centre": the light's place, as fractions of the window
    property real glowY: 0.42
    property color baseColor: Theme.t.appBase  // the window's own colour (Terminal is darker than its tint)
    property int padTop: 0                    // room kept clear of the islands, for content that fills the window
    property int padBottom: 0
    property int padLeft: 0
    property int padRight: 0
    property real corner: Theme.t.radiusWindow
    property bool bare: false                 // true: nothing floats and nothing is kept clear (a slide show, a film)
    // The older way to say the same things, kept so an app can list its side column and its buttons simply:
    property int sidebarWidth: 0              // above 0: `sidebar` shows as a rail down the left
    property alias sidebar: sideRail.items
    property alias toolbar: toolIsland.items  // shows as the island at the top right, first item rightmost
    property string heading: ""               // shown beside the app's name
    default property alias content: body.data
    property alias islands: over.data         // the floating layer: Island items, anchored to the window
    property bool maximised: visibility === Window.Maximized
    readonly property real r: maximised || visibility === Window.FullScreen ? 0.01 : corner
    property color tintColor: Theme.t.accent   // Help borrows the colour of the app it is talking about
    // Where something `w` wide sits to be in the middle (a start screen's picture and button), in the window's own
    // coordinates: the middle of the whole window, unless that would run into the island down the left (`rail`, or the
    // sidebar); then the middle of the room beside it. `top` and `h`: where it is up and down, for whether they meet.
    function middleX(w, top, h, rail) {
        var r = rail || sideRail, mid = (width - w) / 2
        if (!r || !r.visible || r.width <= 0 || r.height <= 0) return mid
        var right = r.x + r.width + 20
        if (mid >= right || top > r.y + r.height + 16 || top + h < r.y - 16) return mid
        return right + Math.max(0, (width - right - w) / 2)
    }
    width: 1100; height: 720; minimumWidth: 720; minimumHeight: 460
    visible: true; color: "transparent"
    flags: Qt.Window | Qt.FramelessWindowHint

    Rectangle { anchors.fill: parent; radius: win.r; color: win.baseColor }
    Shape {   // the glow: one gradient painted in the window's own rounded outline (no blur, so it costs nothing)
        anchors.fill: parent; visible: win.glow !== "none"
        ShapePath {
            strokeWidth: 0; strokeColor: "transparent"
            fillGradient: RadialGradient {
                centerX: win.glow === "left" ? -win.width * 0.05 : win.glow === "right" ? win.width * 1.05 : win.glow === "centre" ? win.width * win.glowX : win.width / 2
                centerY: win.glow === "bottom" ? win.height * 1.1 : win.glow === "top" ? -win.height * 0.1 : win.glow === "centre" ? win.height * win.glowY : win.height / 2
                focalX: centerX; focalY: centerY; focalRadius: 0
                centerRadius: win.glow === "left" || win.glow === "right" ? win.height * 0.85 : win.glow === "centre" ? win.height * 0.62 : Math.max(win.width * 0.48, win.height * 0.8)
                GradientStop { position: 0; color: Qt.rgba(win.tintColor.r, win.tintColor.g, win.tintColor.b, Theme.t.glowStrength) }
                GradientStop { position: 0.55; color: Qt.rgba(win.tintColor.r, win.tintColor.g, win.tintColor.b, Theme.t.glowStrength * 0.28) }
                GradientStop { position: 1; color: Qt.rgba(win.tintColor.r, win.tintColor.g, win.tintColor.b, 0) }
            }
            startX: win.r; startY: 0
            PathLine { x: win.width - win.r; y: 0 } PathArc { x: win.width; y: win.r; radiusX: win.r; radiusY: win.r }
            PathLine { x: win.width; y: win.height - win.r } PathArc { x: win.width - win.r; y: win.height; radiusX: win.r; radiusY: win.r }
            PathLine { x: win.r; y: win.height } PathArc { x: 0; y: win.height - win.r; radiusX: win.r; radiusY: win.r }
            PathLine { x: 0; y: win.r } PathArc { x: win.r; y: 0; radiusX: win.r; radiusY: win.r }
        }
    }
    // A light grain over the glow: a soft gradient in so few shades shows rings, and grain breaks them up.
    Image { anchors { fill: parent; margins: 5 } source: "grain.png"; fillMode: Image.Tile; smooth: false; visible: win.glow !== "none" }
    Rectangle { anchors.fill: parent; radius: win.r; color: "transparent"; border.width: 1; border.color: Theme.t.islandLine }
    // With no title bar, any empty part of the window moves it; double-click the top strip to maximise.
    MouseArea {
        anchors.fill: parent
        onPressed: win.startSystemMove()
        onDoubleClicked: function (m) { if (m.y < 64) win.maximised ? win.showNormal() : win.showMaximized() }
    }
    Item { id: body; anchors { fill: parent; topMargin: win.bare ? 0 : win.padTop; bottomMargin: win.bare ? 0 : win.padBottom; rightMargin: win.bare ? 0 : win.padRight
                              leftMargin: win.bare ? 0 : Math.max(win.padLeft, win.sidebarWidth > 0 ? win.sidebarWidth + 24 : 0) } }
    Item { id: over; anchors.fill: parent; z: 5; visible: !win.bare }
    Rail { id: sideRail; visible: win.sidebarWidth > 0 && !win.bare; x: 12; y: 64; z: 6; width: Math.max(win.sidebarWidth, 60); maxHeight: win.height - 64 - 14 }
    Island { id: toolIsland; visible: width > 12 && !win.bare; z: 7; rtl: true; anchors { right: parent.right; rightMargin: 12 } y: 12 }
    Island {   // close, minimise, maximise and the app's name: always top left
        x: 12; y: 12; z: 6; drags: true; visible: !win.bare
        Item { width: 4; height: 1 }
        Repeater {
            model: [["#FF5F57", "Close"], ["#FEBC2E", "Minimize"], ["#28C840", "Maximize"]]
            Rectangle {
                required property var modelData
                required property int index
                width: 12; height: 12; radius: 6; color: modelData[0]; border.width: 1; border.color: "#22000000"; anchors.verticalCenter: parent.verticalCenter
                MouseArea { anchors.fill: parent; anchors.margins: -3; hoverEnabled: true
                    onClicked: index === 0 ? win.close() : index === 1 ? win.showMinimized() : (win.maximised ? win.showNormal() : win.showMaximized())
                    // the fill button, held (or pointed at for a moment): the layouts
                    onPressAndHold: if (index === 2 && layouts.able) layouts.shown = true
                    onContainsMouseChanged: if (index === 2) { if (containsMouse) layoutsHover.restart(); else layoutsHover.stop() } }
            }
        }
        Label { text: win.title; font.pixelSize: 12; font.weight: Font.DemiBold; leftPadding: 4; rightPadding: win.heading !== "" ? 2 : 8; anchors.verticalCenter: parent.verticalCenter }
        Label { visible: win.heading !== ""; text: win.heading; secondary: true; font.pixelSize: 12; rightPadding: 8; width: Math.min(implicitWidth, 240); elide: Text.ElideRight; anchors.verticalCenter: parent.verticalCenter }
    }
    // The fill button's layouts: halves, thirds, two-thirds, quarters, all of it (Settings › Desktop & Dock can turn
    // them off). Huginn's shell does it, under its own compositor or KWin.
    Timer { id: layoutsHover; interval: 650; onTriggered: if (layouts.able) layouts.shown = true }
    MouseArea { anchors.fill: parent; z: 19; visible: layouts.shown; onClicked: layouts.shown = false }
    Rectangle {
        id: layouts
        property bool shown: false
        readonly property bool able: typeof AppMenu !== "undefined" && AppMenu !== null && Settings.fillButtonLayouts !== false
        visible: shown; z: 20; x: 12; y: 48
        width: grid.width + 20; height: grid.height + 20; radius: 16
        color: Theme.t.dark ? Qt.rgba(0.11, 0.12, 0.15, 0.97) : Qt.rgba(0.98, 0.98, 0.99, 0.98); border.width: 1; border.color: Theme.t.islandLine
        transformOrigin: Item.TopLeft
        scale: shown ? 1 : 0.9
        Behavior on scale { NumberAnimation { duration: Theme.t.openMs ? 140 : 0; easing.type: Easing.OutCubic } }
        Grid {
            id: grid
            x: 10; y: 10; columns: 4; spacing: 8
            Repeater {
                model: [["left", [[0, 0, .5, 1]]], ["right", [[.5, 0, .5, 1]]], ["left-third", [[0, 0, .333, 1]]], ["right-third", [[.667, 0, .333, 1]]],
                        ["left-two-thirds", [[0, 0, .667, 1]]], ["right-two-thirds", [[.333, 0, .667, 1]]], ["top-left", [[0, 0, .5, .5]]], ["top-right", [[.5, 0, .5, .5]]],
                        ["bottom-left", [[0, .5, .5, .5]]], ["bottom-right", [[.5, .5, .5, .5]]], ["max", [[0, 0, 1, 1]]]]
                Rectangle {
                    required property var modelData
                    width: 56; height: 36; radius: 7; color: lh.containsMouse ? Qt.alpha(Theme.t.accent, 0.18) : Theme.t.hover
                    border.width: lh.containsMouse ? 1.5 : 1; border.color: lh.containsMouse ? Theme.t.accent : Theme.t.islandLine
                    Repeater {
                        model: parent.modelData[1]
                        Rectangle { required property var modelData; x: 4 + modelData[0] * 48; y: 4 + modelData[1] * 28; width: modelData[2] * 48; height: modelData[3] * 28; radius: 4
                            color: lh.containsMouse ? Theme.t.accent : Theme.t.text_secondary; opacity: 0.85 }
                    }
                    MouseArea { id: lh; anchors.fill: parent; hoverEnabled: true; onClicked: { layouts.shown = false; AppMenu.snap(parent.modelData[0]) } }
                }
            }
        }
    }
    MouseArea {   // resize from the bottom-right corner
        width: 16; height: 16; z: 9; anchors { right: parent.right; bottom: parent.bottom } cursorShape: Qt.SizeFDiagCursor
        onPressed: win.startSystemResize(Qt.RightEdge | Qt.BottomEdge)
    }
}
