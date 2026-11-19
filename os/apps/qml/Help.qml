import QtQuick

// Help, "the field guide": a big question in the middle of the page and the guides on shelves below it, each with
// its app's own icon and colour. Reading one, the whole window takes on that app's colour; the contents run down the
// left and the guide reads down a comfortable column on the right.
GlassWindow {
    id: win
    title: "Help"; width: 1000; height: 740; minimumWidth: 760; minimumHeight: 520; glow: Backend.article.id ? "left" : "top"
    readonly property var art: Backend.article
    readonly property bool reading: !!art.id
    tintColor: reading && art.colour ? art.colour : Theme.t.accent
    Behavior on tintColor { ColorAnimation { duration: 350 } }
    Connections { target: Backend; function onSaid(msg, wrong) { toast.say(msg, wrong) } }
    Shortcut { sequence: "Escape"; enabled: win.reading; onActivated: Backend.home() }

    islands: [
        Island { visible: win.reading; x: 124; y: 12
            Seg { icon: "back"; text: "All Guides"; onClicked: Backend.home() } },
        Island { visible: win.reading; anchors { right: parent.right; rightMargin: 12 } y: 12
            IslandField { width: 200; placeholder: "Search the guides"; onAccepted: { Backend.search(text); Backend.home() } } },
        Toast { id: toast; anchors { horizontalCenter: parent.horizontalCenter; bottom: parent.bottom; bottomMargin: 22 } }
    ]

    // ---------------- the front page
    Flickable { id: front; objectName: "front"; visible: !win.reading; anchors { fill: parent; topMargin: 56 } contentHeight: page.height + 40; clip: true; boundsBehavior: Flickable.StopAtBounds
        Column { id: page; width: Math.min(front.width - 48, 900); x: (front.width - width) / 2; spacing: 18
            Item { width: 1; height: 18 }
            Label { anchors.horizontalCenter: parent.horizontalCenter; text: "How can we help?"; font.pixelSize: 32; font.weight: Font.Bold }
            Rectangle { anchors.horizontalCenter: parent.horizontalCenter; width: Math.min(parent.width, 620); height: 56; radius: 28; color: Theme.t.island; border.width: 1; border.color: ask.activeFocus ? Theme.t.accent : Theme.t.islandLine
                Glyph { x: 20; anchors.verticalCenter: parent.verticalCenter; name: "search"; size: 18; ink: Theme.t.accent }
                TextInput { id: ask; objectName: "ask"; x: 52; width: parent.width - 72; anchors.verticalCenter: parent.verticalCenter; font.pixelSize: 17; color: Theme.t.text; clip: true
                    selectByMouse: true; text: Backend.query; onTextEdited: Backend.search(text)
                    Text { visible: !ask.text; text: "Ask in your own words: “share my screen”, “add a font”, “lost password”"; font: ask.font; color: Theme.t.text_secondary; elide: Text.ElideRight; width: parent.width } } }
            Label { anchors.horizontalCenter: parent.horizontalCenter; visible: Backend.query === ""; secondary: true; font.pixelSize: 12; text: Backend.count + " short guides, all on this computer" }

            // answers
            Column { visible: Backend.query !== ""; width: parent.width; spacing: 6
                Label { visible: Backend.results.length === 0; anchors.horizontalCenter: parent.horizontalCenter; secondary: true; text: "No guide mentions that. Try fewer or different words." }
                Repeater { model: Backend.results
                    Pressable { required property var modelData; width: page.width; height: 66; radius: 14; color: hovered ? Theme.t.hover : Theme.t.island; border.width: 1; border.color: Theme.t.islandLine
                        onClicked: Backend.openAt(modelData.id, modelData.section)
                        Column { x: 18; width: parent.width - 36; anchors.verticalCenter: parent.verticalCenter; spacing: 3
                            Label { width: parent.width; elide: Text.ElideRight; font.weight: Font.DemiBold; text: modelData.title + (modelData.section ? "  ›  " + modelData.section : "") }
                            Label { width: parent.width; elide: Text.ElideRight; secondary: true; font.pixelSize: 12; text: modelData.text } } } } }

            // shelves
            Repeater { model: Backend.query === "" ? Backend.shelves : []
                Column { required property var modelData; required property int index; width: page.width; spacing: 10
                    Label { text: modelData.name.toUpperCase(); font.pixelSize: 11; font.weight: Font.Bold; font.letterSpacing: 1.3; secondary: true; topPadding: index ? 8 : 0 }
                    Flow { width: parent.width; spacing: 10
                        Repeater { model: modelData.tiles
                            Pressable { id: tile; required property var modelData; width: (page.width - 20) / 3; height: 76; radius: 16
                                color: hovered ? Qt.rgba(Qt.color(modelData.colour).r, Qt.color(modelData.colour).g, Qt.color(modelData.colour).b, 0.16) : Theme.t.island
                                border.width: 1; border.color: Theme.t.islandLine; onClicked: Backend.open(modelData.id)
                                Rectangle { x: 12; anchors.verticalCenter: parent.verticalCenter; width: 48; height: 48; radius: 12; color: tile.modelData.colour; visible: !tile.modelData.icon
                                    Glyph { anchors.centerIn: parent; name: "info"; size: 22; ink: "#FFFFFF" } }
                                Image { x: 12; anchors.verticalCenter: parent.verticalCenter; width: 48; height: 48; sourceSize: Qt.size(96, 96); source: tile.modelData.icon; visible: !!tile.modelData.icon; asynchronous: true }
                                Column { x: 72; width: parent.width - 84; anchors.verticalCenter: parent.verticalCenter; spacing: 2
                                    Label { width: parent.width; elide: Text.ElideRight; text: tile.modelData.title; font.weight: Font.DemiBold }
                                    Label { width: parent.width; maximumLineCount: 2; wrapMode: Text.WordWrap; elide: Text.ElideRight; secondary: true; font.pixelSize: 11; text: tile.modelData.summary } } } } } } } } }

    // ---------------- reading a guide
    Item { id: reader; objectName: "reader"; visible: win.reading; anchors { fill: parent; topMargin: 64; leftMargin: 18; rightMargin: 18; bottomMargin: 18 }
        Column { id: side; width: 240; spacing: 10
            Image { width: 72; height: 72; sourceSize: Qt.size(144, 144); source: win.art.icon || ""; visible: !!win.art.icon }
            Label { width: parent.width; wrapMode: Text.WordWrap; text: win.art.title || ""; font.pixelSize: 24; font.weight: Font.Bold }
            Label { width: parent.width; wrapMode: Text.WordWrap; secondary: true; font.pixelSize: 12; text: win.art.summary || "" }
            Btn { visible: !!win.art.app && win.art.app !== "help"; primary: true; text: "Open " + (win.art.title || ""); onClicked: Backend.openApp(win.art.app) }
            Item { width: 1; height: 6 }
            Repeater { model: win.art.sections || []
                Pressable { required property var modelData; required property int index; width: side.width; height: 32; radius: 10
                    readonly property bool on: col.at === index
                    color: on ? Qt.rgba(win.tintColor.r, win.tintColor.g, win.tintColor.b, 0.18) : hovered ? Theme.t.hover : "transparent"
                    onClicked: col.jump(index)
                    Rectangle { visible: parent.on; x: 0; width: 3; height: 18; radius: 2; anchors.verticalCenter: parent.verticalCenter; color: win.tintColor }
                    Label { x: 12; width: parent.width - 20; elide: Text.ElideRight; anchors.verticalCenter: parent.verticalCenter; font.pixelSize: 12; text: modelData.title
                        font.weight: parent.on ? Font.DemiBold : Font.Normal } } } }
        Rectangle { x: side.width + 22; width: parent.width - x; height: parent.height; radius: 20; color: Theme.t.island; border.width: 1; border.color: Theme.t.islandLine
            Flickable { id: col; anchors { fill: parent; margins: 4 } contentHeight: body.height + 60; clip: true; boundsBehavior: Flickable.StopAtBounds
                property int at: 0
                function jump(i) { var it = parts.itemAt(i); if (it) contentY = Math.min(Math.max(0, it.y - 10), Math.max(0, contentHeight - height)) }
                onContentYChanged: { var best = 0; for (var i = 0; i < parts.count; i++) { var it = parts.itemAt(i); if (it && it.y - 30 <= contentY) best = i } at = best }
                Column { id: body; x: 30; y: 26; width: Math.min(col.width - 60, 640); spacing: 22
                    Repeater { id: parts; model: win.art.sections || []
                        Column { required property var modelData; width: body.width; spacing: 6
                            Label { width: parent.width; wrapMode: Text.WordWrap; text: modelData.title; font.pixelSize: 18; font.weight: Font.Bold }
                            Text { width: parent.width; wrapMode: Text.WordWrap; textFormat: Text.MarkdownText; text: modelData.body; color: Theme.t.text; font.pixelSize: 15; lineHeight: 1.3
                                font.family: Theme.t.font } } } }
                Timer { id: settle; interval: 60; onTriggered: { var want = win.art.section || ""; var secs = win.art.sections || []
                    for (var i = 0; i < secs.length; i++) if (secs[i].title === want) { col.jump(i); return } col.contentY = 0 } }
                Connections { target: Backend; function onChanged() { settle.restart() } } } } }
}
