import QtQuick

// What Huginn AI can do here: a small island of choices. `items` is [[key, label, note], ...]; a key of "" is a line.
Rectangle {
    id: m
    property var items: []
    property string note: ""
    signal chosen(string key)
    visible: false
    width: 260; height: col.height + 12
    radius: 16; color: Theme.t.island; border.width: 1; border.color: Theme.t.islandLine
    MouseArea { anchors.fill: parent; acceptedButtons: Qt.AllButtons }
    Column {
        id: col; x: 6; y: 6; width: parent.width - 12
        Row { x: 8; height: 30; spacing: 8
            Glyph { name: "sparkle"; size: 14; ink: Theme.t.accent; anchors.verticalCenter: parent.verticalCenter }
            Label { text: "Huginn AI"; font.pixelSize: 12; font.weight: Font.DemiBold; anchors.verticalCenter: parent.verticalCenter } }
        Repeater { model: m.items
            Item { required property var modelData; width: col.width; height: modelData[0] === "" ? 9 : 32
                Rectangle { visible: parent.modelData[0] === ""; anchors.centerIn: parent; width: parent.width - 16; height: 1; color: Theme.t.islandLine }
                Pressable { visible: parent.modelData[0] !== ""; anchors.fill: parent; radius: 9; color: hovered ? Theme.t.hover : "transparent"
                    // the key is read before the menu hides: hiding it changes nothing it is built from, but say it first
                    onClicked: { var k = parent.modelData[0]; m.visible = false; m.chosen(k) }
                    Label { x: 10; anchors.verticalCenter: parent.verticalCenter; text: parent.parent.modelData[1]; font.pixelSize: 13 }
                    Label { anchors { right: parent.right; rightMargin: 10; verticalCenter: parent.verticalCenter } text: parent.parent.modelData[2] || ""; secondary: true; font.pixelSize: 11 } } } }
        Label { visible: m.note !== ""; x: 10; width: parent.width - 20; topPadding: 4; bottomPadding: 4; text: m.note; wrapMode: Text.WordWrap; secondary: true; font.pixelSize: 11 }
    }
}
