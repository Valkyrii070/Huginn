import QtQuick

// Privacy Report, "the week in ink": black, white and one signal colour per sense. At the top, what is happening
// right now; below it four tracks across the last seven days (camera, microphone, screen, location) with a mark
// wherever something used them; then who went online, and what the Huginn browser stopped.
GlassWindow {
    id: win
    title: "Privacy Report"; width: 1100; height: 780; minimumWidth: 880; minimumHeight: 600; glow: "top"
    property string open: ""                   // the app whose addresses are shown
    property var tip: null
    readonly property var inks: ({ camera: "#3DDC6E", mic: "#FF9F1C", screen: "#7C9CFF", location: "#FF4FC3" })
    readonly property var glyphs: ({ camera: "camera", mic: "mic", screen: "display", location: "pin" })
    Connections { target: Backend; function onSaid(msg, wrong) { toast.say(msg, wrong) } }

    component Panel: Rectangle { radius: 22; color: Theme.t.island; border.width: 1; border.color: Theme.t.islandLine }
    component Heading: Label { font.pixelSize: 11; font.weight: Font.Bold; font.letterSpacing: 1.2; secondary: true }

    islands: [
        Island { anchors { right: parent.right; rightMargin: 12 } y: 12
            Row { spacing: 6; leftPadding: 8; rightPadding: 8; anchors.verticalCenter: parent.verticalCenter
                Rectangle { width: 8; height: 8; radius: 4; anchors.verticalCenter: parent.verticalCenter; color: Backend.watching ? "#3DDC6E" : Theme.t.text_secondary }
                Label { font.pixelSize: 12; secondary: true; text: Backend.watching ? "Keeping watch" : "Starting the watcher…" } }
            IslandGap {}
            Seg { text: "Forget the History"; onClicked: Backend.forget() } },
        Toast { id: toast; anchors { horizontalCenter: parent.horizontalCenter; bottom: parent.bottom; bottomMargin: 22 } },
        Rectangle { visible: win.tip !== null; z: 30; x: win.tip ? Math.min(win.width - width - 12, win.tip.x) : 0; y: win.tip ? win.tip.y : 0; width: tipText.width + 20; height: 30; radius: 10
            color: Theme.t.menu_bg; border.width: 1; border.color: Theme.t.menu_border
            Label { id: tipText; anchors.centerIn: parent; font.pixelSize: 12; text: win.tip ? win.tip.text : "" } }
    ]

    Flickable { anchors { fill: parent; topMargin: 62; leftMargin: 18; rightMargin: 18; bottomMargin: 12 } contentHeight: page.height + 12; clip: true; boundsBehavior: Flickable.StopAtBounds
        Column { id: page; width: parent.width; spacing: 16
            // ---------------- right now
            Panel { objectName: "rightNow"; width: parent.width; height: Math.max(74, nowCol.height + 36)
                Column { id: nowCol; x: 22; y: 18; width: parent.width - 44; spacing: 8
                    Heading { text: "RIGHT NOW" }
                    Label { visible: Backend.now.length === 0; width: parent.width; wrapMode: Text.WordWrap; font.pixelSize: 16
                        text: "Nothing is using the camera, the microphone or your screen." }
                    Repeater { model: Backend.now
                        Row { required property var modelData; spacing: 10
                            Rectangle { width: 30; height: 30; radius: 15; color: win.inks[modelData.what]
                                Glyph { anchors.centerIn: parent; name: win.glyphs[modelData.what]; size: 15; ink: "#101010" }
                                SequentialAnimation on opacity { loops: Animation.Infinite; running: true; NumberAnimation { to: 0.45; duration: 900 } NumberAnimation { to: 1; duration: 900 } } }
                            Label { anchors.verticalCenter: parent.verticalCenter; text: modelData.text; font.pixelSize: 16; font.weight: Font.DemiBold }
                            Label { anchors.verticalCenter: parent.verticalCenter; text: "for " + modelData.since; secondary: true } } } } }

            // ---------------- the week
            Panel { objectName: "week"; width: parent.width; height: 74 + Backend.lanes.length * 74
                Heading { x: 22; y: 18; text: "THE LAST SEVEN DAYS" }
                Item { id: track; x: 190; y: 40; width: parent.width - 190 - 230; height: parent.height - 56
                    Repeater { model: Backend.days
                        Item { required property string modelData; required property int index; x: track.width * index / 7; width: track.width / 7; height: track.height
                            Label { anchors.horizontalCenter: parent.horizontalCenter; text: modelData; font.pixelSize: 10; secondary: true }
                            Rectangle { visible: index > 0; width: 1; y: 18; height: parent.height - 18; color: Theme.t.islandLine } } }
                    Rectangle { x: track.width * Backend.dayShare; y: 16; width: 2; height: track.height - 14; color: Theme.t.text; opacity: 0.6 } }
                Column { x: 22; y: 62; width: parent.width - 44; spacing: 14
                    Repeater { model: Backend.lanes
                        Item { id: lane; required property var modelData; width: parent.width; height: 60
                            Rectangle { y: 10; width: 36; height: 36; radius: 18; color: lane.modelData.count ? win.inks[lane.modelData.id] : Theme.t.group
                                Glyph { anchors.centerIn: parent; name: win.glyphs[lane.modelData.id]; size: 17; ink: lane.modelData.count ? "#101010" : Theme.t.text_secondary } }
                            Label { x: 48; y: 10; text: lane.modelData.title; font.weight: Font.DemiBold }
                            Label { x: 48; y: 29; width: 118; elide: Text.ElideRight; font.pixelSize: 11; secondary: true
                                text: lane.modelData.id === "location" && !Backend.locationService ? "no location service" : lane.modelData.count === 0 ? "not used" : lane.modelData.count + (lane.modelData.count === 1 ? " time" : " times") }
                            Rectangle { x: track.x - 22; y: 18; width: track.width; height: 20; radius: 10; color: Theme.t.group
                                Repeater { model: lane.modelData.marks
                                    Rectangle { required property var modelData; x: parent.width * modelData.x; width: Math.max(6, parent.width * modelData.w); height: 20; radius: 6; color: win.inks[lane.modelData.id]
                                        MouseArea { anchors.fill: parent; hoverEnabled: true
                                            onEntered: { var p = mapToItem(win.contentItem, 0, -34); win.tip = { x: p.x, y: p.y, text: modelData.app + " · " + modelData.when + " · " + modelData.long } }
                                            onExited: win.tip = null } } } }
                            Column { x: track.x - 22 + track.width + 18; y: 6; width: 200; spacing: 2
                                Repeater { model: lane.modelData.apps.slice(0, 3)
                                    Label { required property var modelData; width: 200; elide: Text.ElideRight; font.pixelSize: 11; text: modelData.name + "  ·  " + modelData.time } } } } } } }

            Row { width: parent.width; spacing: 16
                // ---------------- who went online
                Panel { objectName: "online"; width: (parent.width - 16) * 0.55; height: Math.max(300, netCol.height + 70)
                    Heading { x: 22; y: 18; text: "WHO WENT ONLINE" }
                    Label { x: 22; y: 36; width: parent.width - 44; wrapMode: Text.WordWrap; font.pixelSize: 11; secondary: true; text: "Programs that connected to other computers this week, and to how many different places." }
                    Column { id: netCol; x: 22; y: 72; width: parent.width - 44; spacing: 4
                        Repeater { model: Backend.network
                            Column { required property var modelData; width: netCol.width; spacing: 4
                                Pressable { width: parent.width; height: 34; radius: 10; color: hovered ? Theme.t.hover : "transparent"; onClicked: win.open = win.open === modelData.name ? "" : modelData.name
                                    Label { x: 8; width: 140; height: parent.height; verticalAlignment: Text.AlignVCenter; elide: Text.ElideRight; text: modelData.name; font.weight: Font.Medium }
                                    Rectangle { x: 156; anchors.verticalCenter: parent.verticalCenter; width: (parent.width - 156 - 90) * modelData.share; height: 8; radius: 4; color: Theme.t.text; opacity: 0.8 }
                                    Label { anchors { right: parent.right; rightMargin: 8 } height: parent.height; verticalAlignment: Text.AlignVCenter; font.pixelSize: 12; secondary: true
                                        text: modelData.places + (modelData.places === 1 ? " place" : " places") } }
                                Column { visible: win.open === modelData.name; x: 16; width: parent.width - 16; spacing: 2
                                    Repeater { model: win.open === modelData.name ? modelData.ips : []
                                        Item { required property var modelData; width: parent.width; height: 24
                                            Label { font.family: Theme.t.fontMono; font.pixelSize: 11; text: modelData.ip; anchors.verticalCenter: parent.verticalCenter }
                                            Label { x: 200; width: parent.width - 290; elide: Text.ElideMiddle; font.pixelSize: 11; secondary: true; text: modelData.host; anchors.verticalCenter: parent.verticalCenter }
                                            Seg { visible: !modelData.host; anchors { right: parent.right; verticalCenter: parent.verticalCenter } text: "Look Up"; onClicked: Backend.lookUp(modelData.ip) } } } } } }
                        Label { visible: Backend.network.length === 0; secondary: true; text: Backend.watching ? "Nothing yet. Connections show up here as they happen." : "The watcher isn't running yet." } } }
                // ---------------- what Huginn stopped
                Panel { objectName: "trackers"; width: (parent.width - 16) * 0.45; height: Math.max(300, trackCol.height + 40)
                    Column { id: trackCol; x: 22; y: 18; width: parent.width - 44; spacing: 8
                        Heading { text: "WHAT HUGINN STOPPED" }
                        Label { text: Backend.browser.count.toLocaleString(Qt.locale(), "f", 0); font.pixelSize: 54; font.weight: Font.Black }
                        Label { width: parent.width; wrapMode: Text.WordWrap; secondary: true; font.pixelSize: 12
                            text: Backend.browser.found ? "trackers kept from following you around the web this week." : "Once you browse with Huginn, the trackers it blocks are counted here." }
                        Repeater { model: Backend.browser.trackers
                            Item { required property var modelData; width: parent.width; height: 20
                                Label { text: modelData.name; font.pixelSize: 12 }
                                Label { anchors.right: parent.right; text: modelData.count; font.pixelSize: 12; secondary: true } } }
                        Label { visible: Backend.browser.sites.length > 0; topPadding: 6; text: "Most tracked sites"; font.pixelSize: 11; font.weight: Font.Bold; secondary: true }
                        Repeater { model: Backend.browser.sites
                            Item { required property var modelData; width: parent.width; height: 20
                                Label { text: modelData.name; font.pixelSize: 12 }
                                Label { anchors.right: parent.right; text: modelData.count; font.pixelSize: 12; secondary: true } } } } } }
            Label { width: parent.width; wrapMode: Text.WordWrap; font.pixelSize: 11; secondary: true
                text: "This report is kept only on this computer, in ~/.local/state/huginn, for 30 days. Location is shown when an app uses it, but the location service doesn't say which app." } } }
}
