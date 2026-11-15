import QtQuick

// A search box that lives inside an island (no background of its own).
Item {
    property alias text: input.text
    property string placeholder: "Search"
    signal accepted()
    function focusInput() { input.forceActiveFocus(); input.selectAll() }
    width: 176; height: 30; anchors.verticalCenter: parent ? parent.verticalCenter : undefined
    Glyph { x: 8; anchors.verticalCenter: parent.verticalCenter; name: "search"; size: 14; ink: input.activeFocus ? Theme.t.accent : Theme.t.text_secondary }
    TextInput { id: input; anchors { fill: parent; leftMargin: 30; rightMargin: 8 } verticalAlignment: TextInput.AlignVCenter; clip: true
        color: Theme.t.text; font.family: Theme.t.font; font.pixelSize: 12; selectionColor: Theme.t.accent; selectedTextColor: Theme.t.onAccent; onAccepted: parent.accepted()
        Label { visible: !input.text; text: parent.parent.placeholder; color: Theme.t.text_secondary; font.pixelSize: 12; anchors.verticalCenter: parent.verticalCenter } }
}
