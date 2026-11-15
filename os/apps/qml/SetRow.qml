import QtQuick

// One setting: a name, a line saying what it does, and its control at the right. Clickable when `chevron` is set.
Item {
    id: r
    property string title: ""
    property string sub: ""
    property string glyph: ""
    property string picture: ""          // an image instead of a glyph (an app's icon, a person's picture)
    property color tile: "transparent"   // a coloured square behind the glyph
    property bool chevron: false
    property bool danger: false
    property bool round: false
    property int controlWidth: slot.width
    default property alias control: slot.data
    signal clicked()
    width: parent ? parent.width : 400
    height: Math.max(sub !== "" ? 58 : 48, texts.height + 20)
    Rectangle { visible: r.y > 1; x: 16; width: parent.width - 16; height: 1; color: Theme.t.separator }
    Rectangle { anchors.fill: parent; anchors.margins: 1; radius: 10; visible: r.chevron && area.containsMouse; color: Theme.t.hover }
    MouseArea { id: area; anchors.fill: parent; enabled: r.chevron; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: r.clicked() }
    readonly property int lead: (glyph !== "" || picture !== "") ? 52 : 16
    Rectangle { visible: r.glyph !== "" && r.picture === ""; x: 14; width: 28; height: 28; radius: 8; anchors.verticalCenter: parent.verticalCenter
        color: r.tile; Glyph { anchors.centerIn: parent; name: r.glyph; size: 16; ink: r.tile.a > 0 ? "#FFFFFF" : (r.danger ? Theme.t.danger : Theme.t.icon) } }
    Rectangle { visible: r.picture !== ""; x: 14; width: 28; height: 28; radius: r.round ? 14 : 7; anchors.verticalCenter: parent.verticalCenter; clip: true; color: "transparent"
        Image { anchors.fill: parent; source: r.picture; sourceSize: Qt.size(56, 56); fillMode: Image.PreserveAspectCrop; asynchronous: true } }
    Column { id: texts; x: r.lead; width: parent.width - r.lead - slot.width - (r.chevron ? 40 : 24); anchors.verticalCenter: parent.verticalCenter; spacing: 2
        Label { width: parent.width; text: r.title; elide: Text.ElideRight; color: r.danger ? Theme.t.danger : Theme.t.text }
        Label { visible: r.sub !== ""; width: parent.width; text: r.sub; secondary: true; font.pixelSize: 11; wrapMode: Text.WordWrap; maximumLineCount: 3; elide: Text.ElideRight } }
    Item { id: slot; anchors { right: parent.right; rightMargin: r.chevron ? 34 : 16; verticalCenter: parent.verticalCenter } width: childrenRect.width; height: childrenRect.height }
    Glyph { visible: r.chevron; anchors { right: parent.right; rightMargin: 12; verticalCenter: parent.verticalCenter } name: "forward"; size: 14; ink: Theme.t.text_secondary }
}
