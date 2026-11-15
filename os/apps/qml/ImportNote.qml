import QtQuick

// Shown after a Word, Excel or PowerPoint file is opened: it is a copy, and this is what did not come across.
Rectangle {
    id: note
    property string file: ""
    property var dropped: []
    signal dismissed()
    visible: file !== ""; height: visible ? body.height + 20 : 0; radius: Theme.t.radiusCard
    color: Theme.t.dark ? "#2A2F35" : "#FFF7E8"; border.width: 1; border.color: Theme.t.dark ? "#4A4030" : "#E8C98A"
    Glyph { x: 12; y: 12; name: "info"; size: 16; ink: "#C46A00" }
    Column { id: body; x: 38; y: 10; width: parent.width - 38 - 44; spacing: 3
        Label { width: parent.width; wrapMode: Text.WordWrap; text: "You're working on a copy of “" + note.file + "”. The original file is unchanged."; font.weight: Font.DemiBold; color: Theme.t.dark ? Theme.t.text : "#101317" }
        Label { visible: note.dropped.length > 0; width: parent.width; wrapMode: Text.WordWrap; font.pixelSize: 12; lineHeight: 1.25; color: Theme.t.dark ? Theme.t.text_secondary : "#464D57"
            text: "Not carried over: " + note.dropped.join("; ") + "." } }
    Pressable { anchors { right: parent.right; rightMargin: 8; top: parent.top; topMargin: 8 } width: 26; height: 26; onClicked: note.dismissed(); Glyph { anchors.centerIn: parent; name: "x"; size: 12; ink: Theme.t.dark ? Theme.t.icon : "#464D57" } }
}
