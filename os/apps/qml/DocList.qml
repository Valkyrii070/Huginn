import QtQuick

// Sidebar content shared by Writer, Sheets and Slides: a "new" button and the documents of that kind.
Column {
    id: docs
    property string newLabel: "New"
    property string icon: "doc"
    property string empty: ""
    width: parent ? parent.width : 200; spacing: 2
    Pressable { width: parent.width; height: 34; radius: 11; color: Theme.t.accent; onClicked: Backend.create()
        Row { anchors.centerIn: parent; spacing: 6; Glyph { name: "plus"; size: 14; ink: Theme.t.onAccent; anchors.verticalCenter: parent.verticalCenter } Label { text: docs.newLabel; color: Theme.t.onAccent; font.weight: Font.DemiBold } } }
    Item { width: 1; height: 6 }
    Repeater { model: Backend.files
        Pressable { required property var modelData; width: docs.width; height: 46; radius: 11
            color: Backend.current === modelData.path ? Theme.t.hover : (hovered ? Qt.rgba(0.5, 0.5, 0.5, 0.08) : "transparent"); onClicked: Backend.open(modelData.path)
            Glyph { x: 10; anchors.verticalCenter: parent.verticalCenter; name: docs.icon; size: 16; ink: modelData.foreign ? Theme.t.text_secondary : Theme.t.accent }
            Label { x: 36; y: 7; width: parent.width - 46; text: modelData.name; elide: Text.ElideRight; font.weight: Backend.current === modelData.path ? Font.DemiBold : Font.Normal }
            Label { x: 36; y: 25; text: (modelData.foreign ? modelData.kind + " file · opens as a copy" : modelData.when); secondary: true; font.pixelSize: 11 } } }
    Label { visible: Backend.files.length === 0; leftPadding: 10; width: parent.width; wrapMode: Text.WordWrap; secondary: true; font.pixelSize: 12; text: docs.empty }
}
