import QtQuick

Text {
    property bool secondary: false
    color: secondary ? Theme.t.text_secondary : Theme.t.text
    font.family: Theme.t.font
    font.pixelSize: 13
    renderType: Text.NativeRendering
}
