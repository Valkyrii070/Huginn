import QtQuick

// The wash of colour a new item arrives with: put it inside a row (anchors.fill) and it fades as it settles.
Rectangle {
    id: w
    property color tone: Theme.t.accent
    radius: parent ? parent.radius || 0 : 0
    color: Qt.rgba(tone.r, tone.g, tone.b, 0.28)
    opacity: Theme.t.openMs > 0 ? 1 : 0
    Component.onCompleted: if (Theme.t.openMs > 0) fade.start()
    NumberAnimation { id: fade; target: w; property: "opacity"; to: 0; duration: 900; easing.type: Easing.InQuad }
}
