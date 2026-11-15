import QtQuick

// A button in an island, with an icon and, always available, its name (shown on hover, or inline when `label` is set).
Pressable {
    id: b
    property string icon: ""
    property string tip: ""
    property string label: ""
    property bool on: false
    width: label ? row.width + 22 : 30; height: 30; radius: 11
    anchors.verticalCenter: parent ? parent.verticalCenter : undefined
    color: on ? Theme.t.accent : (hovered ? Theme.t.hover : "transparent")
    Row { id: row; anchors.centerIn: parent; spacing: 6
        Glyph { name: b.icon; size: 15; ink: b.on ? Theme.t.onAccent : Theme.t.icon; anchors.verticalCenter: parent.verticalCenter }
        Label { visible: b.label !== ""; text: b.label; font.pixelSize: 12; color: b.on ? Theme.t.onAccent : Theme.t.text; anchors.verticalCenter: parent.verticalCenter } }
    Rectangle { visible: b.hovered && b.tip !== "" && b.label === ""; z: 9; color: Theme.t.tooltip_bg; border.width: 1; border.color: Theme.t.menu_border; radius: 6
        width: t.width + 14; height: 24; anchors { top: parent.bottom; topMargin: 10; horizontalCenter: parent.horizontalCenter }
        Label { id: t; anchors.centerIn: parent; text: b.tip; font.pixelSize: 11 } }
}
