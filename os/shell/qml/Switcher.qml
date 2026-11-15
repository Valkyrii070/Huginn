import QtQuick

// Alt+Tab: the open windows as a row of tiles in a glass island, the one picked in the app's own colour. Hold Alt
// and press Tab to move along (Shift+Tab back), let go of Alt to go to it, Escape to stay where you were.
Glass {
    id: sw
    popup: true; radius: 26
    property var windows: []
    property int index: 0
    property bool showing: false
    signal chosen(var w)
    visible: opacity > 0
    opacity: showing && windows.length > 0 ? 1 : 0
    Behavior on opacity { NumberAnimation { duration: 120 } }
    width: Math.min(row.width + 28, (parent ? parent.width : 1600) - 80); height: 150
    function step(by) {
        if (windows.length === 0) return
        if (!showing) { showing = true; index = windows.length > 1 ? 0 : 0 }
        index = (index + by + windows.length) % windows.length
    }
    function commit() { if (showing && windows[index]) chosen(windows[index]); showing = false }
    function cancel() { showing = false }
    Row {
        id: row
        x: 14; anchors.verticalCenter: parent.verticalCenter; spacing: 10
        Repeater {
            model: sw.windows
            Rectangle {
                required property var modelData
                required property int index
                readonly property bool on: index === sw.index
                objectName: "switch-" + index
                width: 120; height: 122; radius: 18
                color: on ? Qt.rgba(modelData.glow.r, modelData.glow.g, modelData.glow.b, 0.22) : "transparent"
                border.width: on ? 1.5 : 0; border.color: modelData.glow
                AppIcon { anchors { horizontalCenter: parent.horizontalCenter; top: parent.top; topMargin: 16 } name: modelData.app.name || modelData.title
                    glyph: modelData.app.glyph || ""; image: modelData.app.image || ""; own: modelData.app.own || ""; web: false; opacity: modelData.minimised ? 0.5 : 1 }
                Label { x: 8; y: 74; width: parent.width - 16; horizontalAlignment: Text.AlignHCenter; elide: Text.ElideRight; font.pixelSize: 12
                    font.weight: Font.DemiBold; text: modelData.app.name || modelData.title }
                Label { x: 8; y: 94; width: parent.width - 16; horizontalAlignment: Text.AlignHCenter; elide: Text.ElideRight; font.pixelSize: 11; secondary: true
                    text: modelData.title !== modelData.app.name ? modelData.title : (modelData.minimised ? "Minimised" : "") }
                MouseArea { anchors.fill: parent; onClicked: { sw.index = index; sw.commit() } }
            }
        }
    }
}
