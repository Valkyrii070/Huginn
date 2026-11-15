import QtQuick

Rectangle {
    property alias text: input.text
    property string placeholder: "Search"
    property string icon: "search"
    signal accepted()
    width: 220; height: 30; radius: 15; color: Theme.t.capsule; border.width: 1; border.color: input.activeFocus ? Theme.t.accent : Theme.t.capsule_border
    Glyph { x: 10; anchors.verticalCenter: parent.verticalCenter; name: parent.icon; size: 14; ink: Theme.t.text_tertiary }
    TextInput { id: input; anchors { fill: parent; leftMargin: 32; rightMargin: 12 } verticalAlignment: TextInput.AlignVCenter; clip: true
        color: Theme.t.text; font.family: Theme.t.font; font.pixelSize: 13; selectionColor: Theme.t.accent; onAccepted: parent.accepted()
        Label { visible: !input.text; text: parent.parent.placeholder; color: Theme.t.text_tertiary; anchors.verticalCenter: parent.verticalCenter } }
}
