import QtQuick

// Compact launcher above the dock: category rail, search, web apps first. Type and press Enter to open the first app
// found, or click one; it closes once an app is on its way (and with Escape).
Glass {
    id: root
    popup: true; radius: 18; width: 430; height: 560; clip: true
    signal done()
    property string query: ""
    function go(app) { if (!app) return; Apps.launch(app.exec); root.done() }
    onVisibleChanged: if (visible) { input.text = ""; Qt.callLater(function () { input.forceActiveFocus() }) }
    property var results: Apps.all.filter(function (a) { return a.name.toLowerCase().indexOf(query.toLowerCase()) >= 0 })
    Rectangle {
        width: 54; height: parent.height; color: Theme.t.hover
        Column { y: 16; anchors.horizontalCenter: parent.horizontalCenter; spacing: 16
            Repeater { model: 5; Rectangle { required property int index; width: 20; height: 20; radius: 6; color: index === 0 ? Theme.t.accent : Theme.t.text_secondary; opacity: index === 0 ? 1 : 0.55 } } }
    }
    Column {
        x: 68; y: 14; width: parent.width - 82; spacing: 4
        Rectangle {
            width: parent.width; height: 34; radius: Theme.t.radiusCard; color: Theme.t.hover
            TextInput {
                id: input; anchors { fill: parent; leftMargin: 12; rightMargin: 12 } verticalAlignment: TextInput.AlignVCenter
                color: Theme.t.text; font.family: Theme.t.font; font.pixelSize: 13; focus: true
                onTextChanged: root.query = text
                Keys.onReturnPressed: root.go(root.results[0])
                Keys.onEnterPressed: root.go(root.results[0])
                Keys.onEscapePressed: root.done()
                Label { visible: !input.text; text: "Search apps, tabs and the web"; color: Theme.t.text_tertiary; anchors.verticalCenter: parent.verticalCenter }
            }
        }
        Repeater {
            model: root.results.slice(0, 11)
            Column {
                id: entry
                required property var modelData
                required property int index
                width: parent.width
                Label {
                    visible: entry.index === 0 || root.results[entry.index - 1].web !== entry.modelData.web
                    text: entry.modelData.web ? "WEB APPS" : "APPS"; color: Theme.t.text_tertiary; font.pixelSize: 11; font.weight: Font.DemiBold
                    topPadding: 10; bottomPadding: 4; leftPadding: 8
                }
                Pressable {
                    width: parent.width; height: 42; active: false; color: entry.index === 0 || hovered ? Theme.t.hover : "transparent"
                    onClicked: root.go(entry.modelData)
                    AppIcon { x: 8; anchors.verticalCenter: parent.verticalCenter; size: 30; name: entry.modelData.name; glyph: entry.modelData.glyph; image: entry.modelData.image; own: entry.modelData.own || ""; web: entry.modelData.web }
                    Label { x: 50; anchors.verticalCenter: parent.verticalCenter; text: entry.modelData.name; font.pixelSize: 14 }
                    Label { visible: entry.modelData.web; anchors { right: parent.right; rightMargin: 10; verticalCenter: parent.verticalCenter } text: "Huginn"; color: Theme.t.text_tertiary; font.pixelSize: 11 }
                }
            }
        }
    }
}
