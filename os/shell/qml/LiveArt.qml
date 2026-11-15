import QtQuick
import QtQuick.Effects

// What's playing: its cover, rounded; or the player's colour with a note on it.
Item {
    id: art
    property var it: ({})
    property real r: width * 0.25
    Rectangle { anchors.fill: parent; radius: art.r; visible: img.status !== Image.Ready
        gradient: Gradient { GradientStop { position: 0; color: art.it.tone || "#FF5FA2" } GradientStop { position: 1; color: "#7B61FF" } }
        Glyph { anchors.centerIn: parent; name: art.it.glyph || "music"; size: parent.width * 0.42; ink: "white" } }
    Image { id: img; anchors.fill: parent; source: art.it.art || ""; fillMode: Image.PreserveAspectCrop; visible: false; asynchronous: true; sourceSize: Qt.size(240, 240) }
    MultiEffect { anchors.fill: parent; source: img; visible: img.status === Image.Ready; maskEnabled: true; maskSource: mask }
    Rectangle { id: mask; anchors.fill: parent; radius: art.r; visible: false; layer.enabled: true }
}
