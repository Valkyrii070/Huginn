import QtQuick

// One line in a rail: a place, a page, a file. The chosen one takes the app's colour.
Pressable {
    id: item
    property string icon: ""
    property string text: ""
    property string trailing: ""
    property bool selected: false
    readonly property color fg: selected ? Theme.t.onAccent : Theme.t.text
    width: parent ? parent.width : 190; height: 32; radius: 11
    color: selected ? Theme.t.accent : (hovered ? Theme.t.hover : "transparent")
    Glyph { x: 10; anchors.verticalCenter: parent.verticalCenter; name: item.icon; size: 16; ink: item.selected ? Theme.t.onAccent : Theme.t.icon }
    Label { x: 36; anchors.verticalCenter: parent.verticalCenter; text: item.text; color: item.fg; font.weight: item.selected ? Font.DemiBold : Font.Normal; elide: Text.ElideRight; width: parent.width - (item.trailing !== "" ? 86 : 46) }
    Label { anchors { right: parent.right; rightMargin: 10; verticalCenter: parent.verticalCenter } text: item.trailing; font.pixelSize: 11; color: item.selected ? Theme.t.onAccent : Theme.t.text_secondary }
}
