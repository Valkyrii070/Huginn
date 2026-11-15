import QtQuick

// Music, "glow": the cover is the light. Now Playing shows it; Library is the list. The transport is one island.
GlassWindow {
    id: win
    title: "Music"
    property string view: demo ? "playing" : "library"
    glow: view === "playing" ? "centre" : "bottom"; glowY: 0.4
    property string album: ""
    property int current: demo ? 1 : -1
    property string filter: ""
    property var shown: Backend.items.filter(function (s) { return (!album || (s.album || "Unknown album") === album) && (s.title + s.artist + s.album).toLowerCase().indexOf(filter.toLowerCase()) >= 0 })
    readonly property var song: current >= 0 && current < shown.length ? shown[current] : null
    readonly property color pick: Qt.rgba(tintColor.r, tintColor.g, tintColor.b, 0.18)
    function play(i) { if (i < 0 || i >= shown.length) return; current = i; if (shown[i].url) { player.source = shown[i].url; player.play() } }
    // Playback: the real engine, or (with sample content) a stand-in that only holds numbers for the preview.
    QtObject { id: stub; property bool playing: true; property real position: 83000; property real duration: 228000; property url source; function play() {} function pause() {} }
    QtObject { id: stubAudio; property real volume: 0.7 }
    readonly property var player: engine.item ? engine.item.player : stub
    readonly property var out: engine.item ? engine.item.audio : stubAudio
    Loader { id: engine; active: !demo; source: "Engine.qml"; visible: false }
    Connections { target: engine.item; function onEnded() { win.play(win.current + 1) } }
    MprisLink { player: win.player; title: win.song ? win.song.title : ""; artist: win.song ? win.song.artist || "" : ""; album: win.song ? win.song.album || "" : ""
        onNext: win.play(win.current + 1); onPrevious: win.play(win.current - 1); onRaise: { win.raise(); win.requestActivate() } }
    islands: [
        Island {
            anchors { right: parent.right; rightMargin: 12 } y: 12
            IslandField { visible: win.view === "library"; text: win.filter; onTextChanged: win.filter = text; placeholder: "Search your music" }
            Seg { text: "Now Playing"; on: win.view === "playing"; onClicked: win.view = "playing" }
            Seg { text: "Library"; on: win.view === "library"; onClicked: win.view = "library" }
        },
        Island {   // the transport: the main island
            visible: Backend.items.length > 0; height: 58; radius: 20; pad: 12
            anchors { horizontalCenter: parent.horizontalCenter; bottom: parent.bottom; bottomMargin: 14 }
            Column { visible: win.view === "library"; width: 170; anchors.verticalCenter: parent.verticalCenter
                Label { width: parent.width; text: win.song ? win.song.title : "Nothing playing"; elide: Text.ElideRight; font.weight: Font.DemiBold; font.pixelSize: 12 }
                Label { width: parent.width; text: win.song ? win.song.artist : "Double-click a song"; elide: Text.ElideRight; secondary: true; font.pixelSize: 11 } }
            PlayerBar { width: Math.min(640, win.width - (win.view === "library" ? 260 : 80)); anchors.verticalCenter: parent.verticalCenter
                player: win.player; audio: win.out; onNext: win.play(win.current + 1); onPrevious: win.play(win.current - 1) }
        }
    ]
    Column { visible: Backend.items.length === 0; anchors.centerIn: parent; spacing: 8
        Glyph { name: "music"; size: 44; ink: Theme.t.text_secondary; anchors.horizontalCenter: parent.horizontalCenter }
        Label { text: "No music yet"; font.pixelSize: 17; font.weight: Font.DemiBold; anchors.horizontalCenter: parent.horizontalCenter }
        Label { text: "Songs you put in " + Backend.folder + " appear here."; secondary: true; anchors.horizontalCenter: parent.horizontalCenter } }

    // ---------------- Now Playing
    Column { visible: win.view === "playing" && Backend.items.length > 0; anchors.horizontalCenter: parent.horizontalCenter; y: Math.max(70, (win.height - 90 - height) / 2); spacing: 6
        Rectangle { width: Math.min(300, win.height - 300); height: width; radius: 22; anchors.horizontalCenter: parent.horizontalCenter
            gradient: Gradient { GradientStop { position: 0; color: Theme.t.accent } GradientStop { position: 1; color: "#7B61FF" } }
            border.width: 1; border.color: "#33FFFFFF"
            Glyph { anchors.centerIn: parent; name: "music"; size: parent.width * 0.3; ink: "#FFFFFF"; opacity: 0.9 } }
        Item { width: 1; height: 14 }
        Label { text: win.song ? win.song.title : "Nothing playing"; font.pixelSize: 22; font.weight: Font.DemiBold; anchors.horizontalCenter: parent.horizontalCenter }
        Label { text: win.song ? win.song.artist + (win.song.album ? "  ·  " + win.song.album : "") : "Pick a song in Library"; secondary: true; anchors.horizontalCenter: parent.horizontalCenter } }

    // ---------------- Library
    Item { visible: win.view === "library" && Backend.items.length > 0; anchors { fill: parent; topMargin: 64 }
        Flickable { id: chips; x: 14; width: parent.width - 28; height: 34; contentWidth: chipRow.width; clip: true
            Row { id: chipRow; height: 34; spacing: 6
                Seg { text: "All Songs"; icon: "music"; on: win.album === ""; onClicked: { win.album = ""; win.current = -1 } }
                Repeater { model: Backend.albums; Seg { required property var modelData; icon: "disc"; text: modelData.name; on: win.album === modelData.name; onClicked: { win.album = modelData.name; win.current = -1 } } } } }
        Rectangle { x: 14; y: 44; width: parent.width - 28; height: parent.height - 44 - 86; radius: 12; color: Theme.t.group; border.width: 1; border.color: Theme.t.islandLine; clip: true
            MouseArea { anchors.fill: parent }
            Row { x: 6; height: 30
                Label { width: 40; text: "#"; secondary: true; font.pixelSize: 11; leftPadding: 12; anchors.verticalCenter: parent.verticalCenter } Label { width: table.width * 0.38; text: "Title"; secondary: true; font.pixelSize: 11; anchors.verticalCenter: parent.verticalCenter }
                Label { width: table.width * 0.24; text: "Artist"; secondary: true; font.pixelSize: 11; anchors.verticalCenter: parent.verticalCenter } Label { width: table.width * 0.24; text: "Album"; secondary: true; font.pixelSize: 11; anchors.verticalCenter: parent.verticalCenter } }
            Flickable { id: table; x: 6; y: 30; width: parent.width - 12; height: parent.height - 36; contentHeight: songs.height; clip: true
                Column { id: songs; width: parent.width
                    Repeater { model: win.shown
                        Pressable { required property var modelData; required property int index; readonly property bool on: win.current === index
                            width: songs.width; height: 38; radius: 9; color: on ? win.pick : (hovered ? Qt.rgba(0.5, 0.5, 0.5, 0.07) : "transparent")
                            MouseArea { anchors.fill: parent; onDoubleClicked: win.play(index); onClicked: win.current = index }
                            Label { visible: !parent.on; x: 12; anchors.verticalCenter: parent.verticalCenter; text: index + 1; secondary: true; font.pixelSize: 12 }
                            Glyph { visible: parent.on; x: 10; anchors.verticalCenter: parent.verticalCenter; name: "volume"; size: 15; ink: Theme.t.accent }
                            Label { x: 40; width: table.width * 0.38 - 12; anchors.verticalCenter: parent.verticalCenter; text: modelData.title; elide: Text.ElideRight; color: parent.on ? Theme.t.accent : Theme.t.text; font.weight: parent.on ? Font.DemiBold : Font.Normal }
                            Label { x: 40 + table.width * 0.38; width: table.width * 0.24 - 12; anchors.verticalCenter: parent.verticalCenter; text: modelData.artist; elide: Text.ElideRight; secondary: true }
                            Label { x: 40 + table.width * 0.62; width: table.width * 0.24 - 12; anchors.verticalCenter: parent.verticalCenter; text: modelData.album; elide: Text.ElideRight; secondary: true }
                            Label { anchors { right: parent.right; rightMargin: 12; verticalCenter: parent.verticalCenter } text: modelData.length; secondary: true; font.pixelSize: 12; font.family: Theme.t.fontMono } } } } } }
    }
}
