import QtQuick

// Hover tint + press: it gives a little as you press (90 ms) and springs back as you let go (Huginn's motion).
Rectangle {
    id: root
    signal clicked()
    signal doubleClicked()
    property bool active: false
    property alias hovered: area.containsMouse
    color: active ? Theme.t.accent : (area.containsMouse ? Theme.t.hover : "transparent")
    radius: Theme.t.radiusCard
    scale: area.pressed ? Theme.t.pressScale : 1
    Behavior on scale { NumberAnimation { duration: area.pressed ? 90 : 180; easing.type: area.pressed ? Easing.OutQuad : Easing.OutBack; easing.overshoot: 2.2 } }
    Behavior on color { ColorAnimation { duration: Theme.t.hoverMs } }
    MouseArea { id: area; anchors.fill: parent; hoverEnabled: true; onClicked: root.clicked(); onDoubleClicked: root.doubleClicked() }
}
