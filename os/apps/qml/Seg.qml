import QtQuick

// One choice or action inside an island. `on` fills it with the app's colour.
Pressable {
    id: s
    property string text: ""
    property string icon: ""
    property string tip: ""
    property bool on: false
    property bool fill: false                  // in a Rail: take the full width, text at the left
    property bool danger: false
    property bool tipAbove: false              // for islands at the bottom of the window
    width: fill && parent ? parent.width : (text !== "" ? row.width + 22 : 30); height: 30; radius: 11
    anchors.verticalCenter: fill ? undefined : (parent ? parent.verticalCenter : undefined)
    color: on ? Theme.t.accent : (hovered ? Theme.t.hover : "transparent")
    Row { id: row; x: s.fill ? 10 : (s.width - width) / 2; anchors.verticalCenter: parent.verticalCenter; spacing: 6
        Glyph { visible: s.icon !== ""; name: s.icon; size: 15; ink: s.on ? Theme.t.onAccent : s.danger ? Theme.t.danger : Theme.t.icon; anchors.verticalCenter: parent.verticalCenter }
        Label { visible: s.text !== ""; text: s.text; font.pixelSize: 12; font.weight: s.on ? Font.DemiBold : Font.Medium
            color: s.on ? Theme.t.onAccent : s.danger ? Theme.t.danger : Theme.t.text; anchors.verticalCenter: parent.verticalCenter } }
    Rectangle { visible: s.hovered && s.tip !== "" && s.text === ""; z: 9; color: Theme.t.tooltip_bg; border.width: 1; border.color: Theme.t.menu_border; radius: 6
        width: t.width + 14; height: 24; y: s.tipAbove ? -34 : s.height + 10; anchors.horizontalCenter: parent.horizontalCenter
        Label { id: t; anchors.centerIn: parent; text: s.tip; font.pixelSize: 11 } }
}
