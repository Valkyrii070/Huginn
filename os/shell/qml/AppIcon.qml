import QtQuick

// An app's dock or launcher tile. Huginn's own apps use a line icon drawn in code (Glyph), other apps
// use their icon from the system icon theme, and an app with neither falls back to its first letter.
// Web apps are round, native apps are rounded squares.
Rectangle {
    id: tile
    property string name: ""
    property string glyph: ""
    property string image: ""
    property string own: ""                     // one of Huginn's own app pictures: it is the whole tile
    property bool web: false
    property int size: 44
    readonly property bool brand: name === "Huginn"
    width: size; height: size
    radius: web ? size / 2 : size * 0.3
    color: own !== "" ? "transparent" : Theme.t.view
    border.width: own !== "" ? 0 : 1
    border.color: Theme.t.line
    gradient: brand ? huginn : null
    Gradient { id: huginn; GradientStop { position: 0; color: Theme.t.glowA } GradientStop { position: 1; color: Theme.t.glowB } }
    Image { visible: tile.own !== ""; anchors.centerIn: parent; width: Math.round(tile.size * 1.1); height: width; source: tile.own; sourceSize: Qt.size(128, 128); smooth: true; mipmap: true }
    Glyph { visible: tile.glyph !== "" && tile.own === ""; anchors.centerIn: parent; name: tile.glyph; size: Math.round(tile.size * 0.5); ink: tile.brand ? "#0B1512" : Theme.t.icon }
    Image {
        visible: tile.glyph === "" && tile.image !== "" && tile.own === ""
        anchors.centerIn: parent; width: Math.round(tile.size * 0.68); height: width
        source: tile.glyph === "" ? tile.image : ""; sourceSize: Qt.size(96, 96); fillMode: Image.PreserveAspectFit; smooth: true
    }
    Text {
        visible: tile.glyph === "" && tile.image === "" && tile.own === ""
        anchors.centerIn: parent; text: tile.name.charAt(0).toUpperCase(); color: Theme.t.text
        font.family: Theme.t.font; font.weight: Font.DemiBold; font.pixelSize: Math.round(tile.size * 0.4)
    }
}
