import QtQuick
import QtQuick.Shapes

// Snapping. While a window is dragged to an edge or a corner: frosted glass where it'll land, the edge you're at lit
// in the realm's colour, and light running round its outline once (Huginn's compositor says where: Status.snapPreview).
// After snapping one window to a half (or a third): the other windows, offered for the rest (Status.snapAssist).
Item {
    id: sg
    readonly property var p: Status.snapPreview
    readonly property var a: Status.snapAssist
    readonly property bool previewing: p.w !== undefined && p.w > 0
    readonly property bool assisting: a.windows !== undefined && a.windows.length > 0
    // it goes when you do something else: another window comes forward, Alt+Tab, the Overview
    property string frontAtStart: ""
    function frontId() { var w = Status.windows.filter(function (x) { return x.active })[0]; return w ? String(w.id) : "" }
    onAssistingChanged: if (assisting) arm.restart(); else frontAtStart = ""
    Timer { id: arm; interval: 350; onTriggered: sg.frontAtStart = sg.frontId() }
    property bool closing: false
    function done() { if (closing) return; closing = true; Qt.callLater(function () { Status.assistDone(); sg.closing = false }) }
    Connections {
        target: Status
        enabled: sg.assisting
        function onWindowsChanged() { if (sg.frontAtStart !== "" && sg.frontId() !== sg.frontAtStart) sg.done() }
        function onSceneChanged() { if ((Status.switcher.windows || []).length > 0 || Status.overview.open) sg.done() }
    }
    function appFor(id) { var all = Apps.all; for (var i = 0; i < all.length; i++) if ((all[i].id || "").toLowerCase() === (id || "").toLowerCase() || (all[i].wm || "").toLowerCase() === (id || "").toLowerCase()) return all[i]; return null }

    // ---------------------------------------------------------------- where it'll land
    Item {
        id: glass
        visible: opacity > 0
        opacity: sg.previewing ? 1 : 0
        Behavior on opacity { NumberAnimation { duration: Theme.t.openMs ? 120 : 0 } }
        x: sg.previewing ? sg.p.x : x; y: sg.previewing ? sg.p.y : y
        width: sg.previewing ? sg.p.w : width; height: sg.previewing ? sg.p.h : height
        Behavior on x { NumberAnimation { duration: Theme.t.openMs ? 140 : 0; easing.type: Easing.OutCubic } }
        Behavior on y { NumberAnimation { duration: Theme.t.openMs ? 140 : 0; easing.type: Easing.OutCubic } }
        Behavior on width { NumberAnimation { duration: Theme.t.openMs ? 140 : 0; easing.type: Easing.OutCubic } }
        Behavior on height { NumberAnimation { duration: Theme.t.openMs ? 140 : 0; easing.type: Easing.OutCubic } }
        Rectangle { anchors.fill: parent; radius: 14; color: Qt.rgba(1, 1, 1, 0.09); border.width: 1.5; border.color: Qt.rgba(1, 1, 1, 0.28) }
        Rectangle {   // the edge you're at, lit
            readonly property string e: sg.p.edge || ""
            width: e === "top" ? parent.width - 28 : 3; height: e === "top" ? 3 : parent.height - 28; radius: 2
            x: e === "right" ? parent.width - 2 : e === "top" ? 14 : -1; y: e === "top" ? -1 : 14
            gradient: Gradient { orientation: parent.e === "top" ? Gradient.Horizontal : Gradient.Vertical
                GradientStop { position: 0; color: Theme.t.glowA } GradientStop { position: 1; color: Theme.t.glowB } }
            Rectangle { anchors.centerIn: parent; width: parent.width + 12; height: parent.height + 12; radius: 8; color: Theme.t.glowA; opacity: 0.22; z: -1 }
        }
        Shape {   // light running round the outline, once
            id: run
            anchors.fill: parent
            readonly property real perimeter: 2 * (width + height)
            property real drawn: 0
            opacity: drawn >= perimeter - 1 ? 0 : 1
            Behavior on opacity { NumberAnimation { duration: 300 } }
            ShapePath {
                strokeColor: Theme.t.glowA; strokeWidth: 2.2; fillColor: "transparent"; capStyle: ShapePath.RoundCap
                strokeStyle: ShapePath.DashLine; dashPattern: [Math.max(0.01, run.drawn / 2.2), run.perimeter / 2.2]
                PathRectangle { x: 1; y: 1; width: run.width - 2; height: run.height - 2; radius: 14 }
            }
        }
        NumberAnimation { id: runAnim; target: run; property: "drawn"; from: 0; to: run.perimeter; duration: Theme.t.openMs ? 650 : 0; easing.type: Easing.InOutQuad }
    }
    property string lastSnap: ""
    onPChanged: if (previewing && p.snap !== lastSnap) { lastSnap = p.snap; runAnim.restart() } else if (!previewing) lastSnap = ""

    // ---------------------------------------------------------------- fill the other half
    MouseArea { anchors.fill: parent; visible: sg.assisting; onClicked: Status.assistDone() }
    Rectangle {
        visible: sg.assisting
        x: sg.a.x || 0; y: sg.a.y || 0; width: sg.a.w || 0; height: sg.a.h || 0; radius: 14
        color: Qt.rgba(0.05, 0.06, 0.08, 0.55); border.width: 1; border.color: Qt.rgba(1, 1, 1, 0.16)
        MouseArea { anchors.fill: parent }
        Column {
            anchors.centerIn: parent; spacing: 14; width: parent.width - 48
            Label { text: "Fill this side with…"; color: "#F5F7FA"; font.pixelSize: 15; font.weight: Font.DemiBold }
            Flow {
                width: parent.width; spacing: 12
                Repeater {
                    model: sg.assisting ? sg.a.windows : []
                    Rectangle {
                        id: card
                        required property var modelData
                        readonly property var w: Status.windows.filter(function (x) { return x.id === modelData })[0]
                        readonly property var app: w ? sg.appFor(w.appId) : null
                        width: 170; height: 112; radius: 12; color: ch.containsMouse ? Qt.rgba(1, 1, 1, 0.16) : Qt.rgba(1, 1, 1, 0.08)
                        border.width: ch.containsMouse ? 2 : 1; border.color: ch.containsMouse ? Theme.t.accent : Qt.rgba(1, 1, 1, 0.14)
                        scale: ch.pressed ? Theme.t.pressScale : 1
                        AppIcon { anchors.horizontalCenter: parent.horizontalCenter; y: 16; size: 44; name: card.app ? card.app.name : ""; glyph: card.app ? card.app.glyph : ""; image: card.app ? card.app.image : ""; own: card.app ? card.app.own || "" : ""; web: false }
                        Label { x: 10; y: 70; width: parent.width - 20; horizontalAlignment: Text.AlignHCenter; elide: Text.ElideRight; text: card.w ? (card.w.title || card.w.name) : ""; color: "#F5F7FA"; font.pixelSize: 12; font.weight: Font.DemiBold }
                        Label { x: 10; y: 88; width: parent.width - 20; horizontalAlignment: Text.AlignHCenter; text: card.app ? card.app.name : ""; color: "#B9C2CC"; font.pixelSize: 11 }
                        MouseArea { id: ch; anchors.fill: parent; hoverEnabled: true; onClicked: { Status.windowDo(card.modelData, "snap:" + sg.a.snap); Status.assistDone() } }
                    }
                }
            }
        }
    }
}
