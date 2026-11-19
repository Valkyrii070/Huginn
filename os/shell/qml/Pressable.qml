import QtQuick

// Hover tint + press scale, the same feel as Huginn's Start Page tiles.
Rectangle {
    id: root
    signal clicked()
    property bool active: false
    property alias hovered: area.containsMouse
    color: active ? Theme.t.accent : (area.containsMouse ? Theme.t.hover : "transparent")
    radius: Theme.t.radiusCard
    scale: area.pressed ? Theme.t.pressScale : 1
    Behavior on scale { NumberAnimation { duration: 100 } }
    Behavior on color { ColorAnimation { duration: Theme.t.hoverMs } }
    MouseArea { id: area; anchors.fill: parent; hoverEnabled: true; onClicked: root.clicked() }
}
