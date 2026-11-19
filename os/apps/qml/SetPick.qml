import QtQuick

// A button showing the current choice; clicking it asks the window to show the choices in a sheet.
Pressable {
    id: p
    property string text: ""
    property string picture: ""
    property int maxWidth: 260
    width: Math.min(maxWidth, row.width + 26); height: 30; radius: 10
    color: hovered ? Theme.t.hover : (Theme.t.dark ? "#22FFFFFF" : "#14141E28")
    Row { id: row; x: 10; spacing: 6; anchors.verticalCenter: parent.verticalCenter
        Image { visible: p.picture !== ""; source: p.picture; width: 18; height: 18; sourceSize: Qt.size(36, 36); anchors.verticalCenter: parent.verticalCenter }
        Label { text: p.text; font.pixelSize: 12; width: Math.min(implicitWidth, p.maxWidth - 50 - (p.picture !== "" ? 24 : 0)); elide: Text.ElideRight; anchors.verticalCenter: parent.verticalCenter }
        Glyph { name: "down"; size: 12; ink: Theme.t.text_secondary; anchors.verticalCenter: parent.verticalCenter } }
}
