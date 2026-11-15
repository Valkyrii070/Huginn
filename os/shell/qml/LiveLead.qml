import QtQuick
import "live.js" as L

// The picture at the left of something going on: the cover, a ring counting down, a coloured round with a glyph (a
// call and an alarm pulse), or a bar of the calendar's colour.
Item {
    id: lead
    property var it: ({})
    property real now: Date.now()
    property int size: 40
    property bool round: false              // in a bubble: the cover is round too
    readonly property string kind: L.kindOf(it)
    width: kind === "event" ? 4 : size; height: size
    Rectangle { visible: lead.kind === "event"; anchors.fill: parent; radius: 2; color: lead.it.tone || Theme.t.accent }
    LiveArt { visible: lead.kind === "playing"; anchors.fill: parent; it: lead.it; r: lead.round ? width / 2 : width * 0.25 }
    LiveRing { visible: lead.kind === "timer"; anchors.fill: parent; tone: lead.it.tone || Theme.t.accent
        value: lead.it.total ? Math.max(0, L.left(lead.it, lead.now)) / lead.it.total : 0
        text: L.clock(L.left(lead.it, lead.now)) }
    Rectangle {
        id: round
        visible: lead.kind !== "event" && lead.kind !== "playing" && lead.kind !== "timer"
        anchors.fill: parent; radius: width / 2
        readonly property color tint: lead.it.tone || Theme.t.accent
        readonly property bool person: lead.kind === "call" && !!lead.it.initials
        color: person ? "transparent" : Qt.rgba(tint.r, tint.g, tint.b, 0.18)
        gradient: person ? who : null
        Gradient { id: who; GradientStop { position: 0; color: "#5EEAD4" } GradientStop { position: 1; color: "#3D7BFF" } }
        border.width: L.privacy(lead.it) || person ? 2 : 0; border.color: tint
        Glyph { visible: !round.person; anchors.centerIn: parent; name: lead.it.glyph || "bell"; size: lead.size * 0.45; ink: round.tint }
        Label { visible: round.person; anchors.centerIn: parent; text: lead.it.initials || ""; color: "#04121A"; font.pixelSize: Math.round(lead.size * 0.38); font.weight: Font.Bold }
        Rectangle { id: pulse; anchors.centerIn: parent; width: parent.width; height: width; radius: width / 2; color: "transparent"
            border.width: 2; border.color: round.tint; visible: (lead.kind === "call" || lead.kind === "alarm") && Theme.t.moveMs > 0
            SequentialAnimation on scale { running: pulse.visible; loops: Animation.Infinite; NumberAnimation { from: 1; to: 1.45; duration: 1100; easing.type: Easing.OutCubic } }
            SequentialAnimation on opacity { running: pulse.visible; loops: Animation.Infinite; NumberAnimation { from: 0.8; to: 0; duration: 1100; easing.type: Easing.OutCubic } } }
    }
}
