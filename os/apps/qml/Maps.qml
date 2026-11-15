import QtQuick

// Maps, "the table": the map is the whole window; one island on the left holds what you asked for.
GlassWindow {
    id: win
    title: "Maps"; width: 1060; height: 700; glow: "none"
    readonly property color pick: Qt.rgba(tintColor.r, tintColor.g, tintColor.b, 0.18)
    readonly property bool routing: !!Backend.origin.name || !!Backend.goal.name
    readonly property var pane: mapLoader.item
    readonly property var pins: { var p = [], i; for (i = 0; i < Backend.saved.length; i++) p.push({ lat: Backend.saved[i].lat, lon: Backend.saved[i].lon, name: Backend.saved[i].name, detail: Backend.saved[i].detail, kind: "kept" })
        for (i = 0; i < Backend.results.length; i++) p.push({ lat: Backend.results[i].lat, lon: Backend.results[i].lon, name: Backend.results[i].name, detail: Backend.results[i].detail, kind: "found" })
        if (Backend.origin.name) p.push({ lat: Backend.origin.lat, lon: Backend.origin.lon, name: Backend.origin.name, detail: "", kind: "from" })
        if (Backend.goal.name) p.push({ lat: Backend.goal.lat, lon: Backend.goal.lon, name: Backend.goal.name, detail: "", kind: "to" }); return p }
    Connections { target: Backend
        function onSaid(msg, wrong) { toast.say(msg, wrong) }
        function onMoved(lat, lon, zoom) { if (win.pane) win.pane.look(lat, lon, zoom) } }
    Component.onCompleted: { if (Backend.startWith !== "") { finder.text = Backend.startWith; Backend.search(Backend.startWith) } else finder.focusIn() }

    // ---------------- the map
    Rectangle { anchors { fill: parent; margins: 6 } radius: win.r - 4; color: Theme.t.island; clip: true
        Loader { id: mapLoader; anchors.fill: parent; active: !demo; source: "MapPane.qml"
            onLoaded: { item.tiles = Backend.tileHost; item.ink = Theme.t.accent; item.look(Backend.view[0], Backend.view[1], Backend.view[2]); item.pins = Qt.binding(function () { return win.pins }); item.line = Qt.binding(function () { return Backend.route.line || [] })
                item.settled.connect(function (lat, lon, zoom) { Backend.looked(lat, lon, zoom) }); item.picked.connect(function (pin) { finder.text = pin.name }) } }
        Canvas { visible: demo; anchors.fill: parent; onPaint: { var c = getContext("2d"); c.strokeStyle = Qt.rgba(0.5, 0.5, 0.5, 0.18); c.lineWidth = 1
                for (var x = 0; x < width; x += 46) { c.beginPath(); c.moveTo(x + (x % 92) / 6, 0); c.lineTo(x - 40, height); c.stroke() } for (var y = 0; y < height; y += 46) { c.beginPath(); c.moveTo(0, y); c.lineTo(width, y + 30); c.stroke() }
                c.strokeStyle = Theme.t.accent; c.lineWidth = 6; c.lineCap = "round"; c.beginPath(); c.moveTo(width * 0.48, height * 0.24); c.bezierCurveTo(width * 0.62, height * 0.3, width * 0.55, height * 0.62, width * 0.8, height * 0.74); c.stroke() } }
        Label { visible: mapLoader.status === Loader.Error; anchors.centerIn: parent; width: 380; wrapMode: Text.WordWrap; horizontalAlignment: Text.AlignHCenter; secondary: true
            text: "The map can't be drawn: this computer is missing Qt's map parts (QtLocation). Search and directions still work in the panel." }
        Rectangle { anchors { right: parent.right; bottom: parent.bottom; margins: 8 } width: cr.width + 12; height: 20; radius: 6; color: "#B0FFFFFF"; visible: !demo
            Label { id: cr; anchors.centerIn: parent; text: "© OpenStreetMap contributors"; color: "#333"; font.pixelSize: 10 } } }

    islands: [
        Island { anchors { right: parent.right; rightMargin: 12 } y: 12
            Seg { text: Backend.miles ? "mi" : "km"; tip: "Switch between kilometres and miles"; onClicked: Backend.flipUnits() }
            Seg { icon: "route"; text: "Directions"; on: win.routing; onClicked: win.routing ? Backend.clearRoute() : Backend.setEnd("from", Backend.saved.length ? Backend.saved[0] : ({})) } },
        Toast { id: toast; anchors { horizontalCenter: parent.horizontalCenter; bottom: parent.bottom; bottomMargin: 18 } }
    ]

    Rectangle { id: panel; x: 12; y: 64; width: 330; height: Math.min(parent.height - 76, inner.height + 20); radius: 16; color: Theme.t.menu_bg; border.width: 1; border.color: Theme.t.menu_border
        MouseArea { anchors.fill: parent }
        Flickable { anchors { fill: parent; margins: 10 } contentHeight: inner.height; clip: true; boundsBehavior: Flickable.StopAtBounds
            Column { id: inner; width: parent.width; spacing: 8
                TextBox { id: finder; objectName: "finder"; width: parent.width; placeholder: "A place or an address"; onAccepted: Backend.search(text) }
                Label { visible: Backend.results.length === 0 && !win.routing && Backend.saved.length === 0; width: parent.width; wrapMode: Text.WordWrap; secondary: true; font.pixelSize: 12
                    text: Backend.busy ? "Looking…" : "Press Enter to search. Huginn never works out where you are; what you type goes to OpenStreetMap's search, and the map pictures come from its servers." }

                // a trip
                Column { visible: win.routing; width: parent.width; spacing: 6
                    Repeater { model: [["from", "From", Backend.origin], ["to", "To", Backend.goal]]
                        Rectangle { required property var modelData; width: parent.width; height: 40; radius: 10; color: Theme.t.island; border.width: 1; border.color: Theme.t.islandLine
                            Rectangle { x: 12; anchors.verticalCenter: parent.verticalCenter; width: 10; height: 10; radius: 5; color: modelData[0] === "to" ? "#E5484D" : Theme.t.accent }
                            Label { x: 32; width: parent.width - 70; elide: Text.ElideRight; anchors.verticalCenter: parent.verticalCenter; text: modelData[2].name || (modelData[1] + ": search, then choose it below"); opacity: modelData[2].name ? 1 : 0.6 }
                            Pressable { visible: !!modelData[2].name; anchors { right: parent.right; rightMargin: 6; verticalCenter: parent.verticalCenter } width: 26; height: 26; radius: 8; onClicked: Backend.setEnd(modelData[0], ({}))
                                Glyph { anchors.centerIn: parent; name: "x"; size: 11; ink: Theme.t.text_secondary } } } }
                    Row { spacing: 5
                        Repeater { model: [["driving", "Drive"], ["cycling", "Cycle"], ["walking", "Walk"]]
                            Pressable { required property var modelData; width: ml.width + 18; height: 26; radius: 9; color: Backend.mode === modelData[0] ? win.pick : "transparent"; border.width: 1; border.color: Backend.mode === modelData[0] ? Theme.t.accent : Theme.t.capsule_border
                                onClicked: Backend.setMode(modelData[0]); Label { id: ml; anchors.centerIn: parent; text: modelData[1]; font.pixelSize: 12 } } }
                        Pressable { width: sl.width + 18; height: 26; radius: 9; border.width: 1; border.color: Theme.t.capsule_border; color: "transparent"; onClicked: Backend.swap(); Label { id: sl; anchors.centerIn: parent; text: "Swap"; font.pixelSize: 12 } } }
                    Label { visible: !!Backend.route.time; text: (Backend.route.time || "") + "  ·  " + (Backend.route.distance || ""); font.pixelSize: 18; font.weight: Font.Bold; color: Theme.t.accent }
                    Label { visible: Backend.busy; text: "Working out the way…"; secondary: true; font.pixelSize: 12 }
                    Repeater { model: Backend.route.steps || []
                        Item { required property var modelData; required property int index; width: parent.width; height: st.height + 10
                            Label { x: 2; y: 5; width: 20; text: index + 1; secondary: true; font.pixelSize: 11 }
                            Label { id: st; x: 24; y: 5; width: parent.width - 90; wrapMode: Text.WordWrap; text: modelData.text; font.pixelSize: 12 }
                            Label { anchors { right: parent.right; rightMargin: 2 } y: 5; text: modelData.far; secondary: true; font.pixelSize: 11 } } } }

                // what was found, and what you kept
                Repeater { model: Backend.results
                    Rectangle { required property var modelData; width: parent.width; height: 74; radius: 10; color: Theme.t.island; border.width: 1; border.color: Theme.t.islandLine
                        MouseArea { anchors.fill: parent; onClicked: Backend.show(modelData) }
                        Label { x: 12; y: 8; width: parent.width - 24; elide: Text.ElideRight; text: modelData.name; font.weight: Font.DemiBold }
                        Label { x: 12; y: 27; width: parent.width - 24; elide: Text.ElideRight; text: modelData.detail; secondary: true; font.pixelSize: 11 }
                        Row { x: 10; y: 46; spacing: 5
                            Repeater { model: [["From Here", "from"], ["To Here", "to"], ["Keep", "keep"]]
                                Pressable { required property var modelData; width: bl.width + 14; height: 22; radius: 7; border.width: 1; border.color: Theme.t.capsule_border; color: hovered ? Theme.t.hover : "transparent"
                                    onClicked: modelData[1] === "keep" ? Backend.keep(parent.parent.parent.modelData) : Backend.setEnd(modelData[1], parent.parent.parent.modelData)
                                    Label { id: bl; anchors.centerIn: parent; text: modelData[0]; font.pixelSize: 11 } } } } } }
                Label { visible: Backend.saved.length > 0; text: "KEPT PLACES"; secondary: true; font.pixelSize: 10; font.weight: Font.DemiBold; topPadding: 4 }
                Repeater { model: Backend.saved
                    Pressable { required property var modelData; required property int index; width: parent.width; height: 40; radius: 10; color: hovered ? Theme.t.hover : "transparent"; onClicked: Backend.show(modelData)
                        Glyph { x: 10; anchors.verticalCenter: parent.verticalCenter; name: "pin"; size: 15; ink: Theme.t.accent }
                        Label { x: 34; y: 4; width: parent.width - 120; elide: Text.ElideRight; text: modelData.name; font.pixelSize: 13 }
                        Label { x: 34; y: 21; width: parent.width - 120; elide: Text.ElideRight; text: modelData.detail; secondary: true; font.pixelSize: 10 }
                        Row { anchors { right: parent.right; rightMargin: 6; verticalCenter: parent.verticalCenter } spacing: 2
                            Pressable { width: 30; height: 26; radius: 8; onClicked: Backend.setEnd(Backend.origin.name ? "to" : "from", modelData); Glyph { anchors.centerIn: parent; name: "route"; size: 13; ink: Theme.t.text_secondary } }
                            Pressable { width: 26; height: 26; radius: 8; onClicked: Backend.forget(index); Glyph { anchors.centerIn: parent; name: "x"; size: 10; ink: Theme.t.text_secondary } } } } } } } }
}
