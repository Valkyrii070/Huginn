import QtQuick
import QtMultimedia

// Podcasts, "the record shelf": your shows stand in a row of covers along the top; pick one up and its episodes
// are below. What's playing floats over the bottom as one rounded bar.
GlassWindow {
    id: win
    title: "Podcasts"; width: 900; height: 720; glow: "top"
    readonly property color pick: Qt.rgba(tintColor.r, tintColor.g, tintColor.b, 0.18)
    readonly property var now: Backend.now
    readonly property bool playing: player.playbackState === MediaPlayer.PlayingState
    property bool finding: false
    property string loaded: ""
    function clock(ms) { var s = Math.floor(ms / 1000), h = Math.floor(s / 3600), m = Math.floor(s % 3600 / 60), x = s % 60; return (h ? h + ":" + (m < 10 ? "0" : "") : "") + m + ":" + (x < 10 ? "0" : "") + x }
    function start(id) { Backend.play(id) }
    onNowChanged: { if (!now.url || demo || now.id === loaded) return; loaded = now.id; outLoader.active = true; player.source = now.url; player.play() }
    Connections { target: Backend; function onSaid(msg, wrong) { toast.say(msg, wrong) } }
    Loader { id: outLoader; active: false; sourceComponent: AudioOutput {} }
    MediaPlayer { id: player; audioOutput: outLoader.item; playbackRate: Backend.speed
        onSeekableChanged: if (seekable && win.now.spot > 0 && position < 1000) position = win.now.spot * 1000
        onErrorOccurred: function (error, text) { toast.say("That episode wouldn't play: " + text, true) } }
    Timer { interval: 8000; repeat: true; running: win.playing; onTriggered: Backend.heard(player.position / 1000, player.duration / 1000) }

    islands: [
        Island { anchors { right: parent.right; rightMargin: 12 } y: 12
            Seg { icon: "history"; tip: Backend.busy ? "Checking…" : "Check for new episodes"; opacity: Backend.busy ? 0.45 : 1; onClicked: Backend.refreshAll() }
            Seg { icon: "plus"; text: "Follow a Show"; onClicked: { win.finding = true; finder.text = ""; Backend.find(""); finder.focusIn() } } },
        Toast { id: toast; anchors { horizontalCenter: parent.horizontalCenter; bottom: parent.bottom; bottomMargin: 96 } },
        Item { anchors.fill: parent; z: 20; visible: win.finding
            Rectangle { anchors.fill: parent; radius: win.r; color: "#66000000"; MouseArea { anchors.fill: parent; acceptedButtons: Qt.AllButtons; onClicked: win.finding = false } }
            Rectangle { anchors.centerIn: parent; width: 500; height: 170 + Math.max(1, Backend.found.length) * 52; radius: 16; color: Theme.t.menu_bg; border.width: 1; border.color: Theme.t.menu_border
                MouseArea { anchors.fill: parent }
                Label { x: 22; y: 20; font.pixelSize: 16; font.weight: Font.DemiBold; text: "Follow a show" }
                TextBox { id: finder; objectName: "finder"; x: 22; y: 54; width: parent.width - 44; placeholder: "A show's name, or its feed address"; onAccepted: Backend.find(text) }
                Column { x: 16; y: 100; width: parent.width - 32
                    Label { visible: Backend.found.length === 0; x: 6; width: parent.width - 12; height: 52; verticalAlignment: Text.AlignVCenter; wrapMode: Text.WordWrap; secondary: true; font.pixelSize: 12
                        text: Backend.busy ? "Looking…" : "Press Enter to search. A name is looked up in Apple's public podcast directory (only those words are sent). A feed address goes straight to the show." }
                    Repeater { model: win.finding ? Backend.found : []
                        Pressable { required property var modelData; width: parent.width; height: 52; radius: 10; onClicked: { Backend.follow(modelData.feed); win.finding = false }
                            Rectangle { x: 8; anchors.verticalCenter: parent.verticalCenter; width: 38; height: 38; radius: 8; color: win.pick; clip: true; Image { anchors.fill: parent; source: modelData.image; asynchronous: true; sourceSize.width: 76 } }
                            Label { x: 56; y: 8; width: parent.width - 66; elide: Text.ElideRight; text: modelData.title; font.weight: Font.Medium }
                            Label { x: 56; y: 28; width: parent.width - 66; elide: Text.ElideRight; text: modelData.author; secondary: true; font.pixelSize: 11 } } } }
                Btn { anchors { right: parent.right; rightMargin: 22; bottom: parent.bottom; bottomMargin: 18 } text: "Done"; onClicked: win.finding = false } } }
    ]

    Column { visible: Backend.shows.length === 0; anchors.centerIn: parent; spacing: 10; width: 420
        Glyph { name: "podcast"; size: 56; ink: Theme.t.accent; anchors.horizontalCenter: parent.horizontalCenter }
        Label { anchors.horizontalCenter: parent.horizontalCenter; font.pixelSize: 20; font.weight: Font.DemiBold; text: "No shows yet" }
        Label { width: parent.width; wrapMode: Text.WordWrap; horizontalAlignment: Text.AlignHCenter; secondary: true; text: "Follow a show and its episodes appear here, newest first. No account, and nothing about what you listen to is sent anywhere." }
        Btn { anchors.horizontalCenter: parent.horizontalCenter; primary: true; text: "Follow a Show"; onClicked: { win.finding = true; finder.focusIn() } } }

    // ---------------- your shows, as covers on a shelf
    Flickable { id: shelf; visible: Backend.shows.length > 0; x: 18; y: 62; width: parent.width - 36; height: 150; contentWidth: covers.width; clip: true; boundsBehavior: Flickable.StopAtBounds
        Row { id: covers; spacing: 14
            Repeater { model: Backend.shows
                Item { id: cov; required property var modelData; required property int index; readonly property bool on: Backend.show === modelData.id; width: 108; height: 150
                    Rectangle { id: art; width: 108; height: 108; radius: 20; clip: true; color: Qt.hsla((index * 0.13 + 0.76) % 1, 0.45, 0.42, 1); border.width: cov.on ? 3 : 1; border.color: cov.on ? Theme.t.accent : Theme.t.islandLine
                        y: cov.on ? 0 : 6; Behavior on y { NumberAnimation { duration: 140 } }
                        Glyph { anchors.centerIn: parent; name: "podcast"; size: 40; ink: "#E6FFFFFF"; visible: cov.modelData.image === "" }
                        Image { anchors { fill: parent; margins: cov.on ? 3 : 1 } source: cov.modelData.image; asynchronous: true; sourceSize.width: 216; fillMode: Image.PreserveAspectCrop }
                        MouseArea { anchors.fill: parent; onClicked: Backend.choose(cov.modelData.id) } }
                    Rectangle { visible: cov.modelData.fresh > 0; x: 84; y: cov.on ? -4 : 2; width: Math.max(22, fr.width + 12); height: 22; radius: 11; color: Theme.t.accent; border.width: 2; border.color: Theme.t.island
                        Label { id: fr; anchors.centerIn: parent; text: cov.modelData.fresh; color: Theme.t.onAccent; font.pixelSize: 11; font.weight: Font.Bold } }
                    Label { y: 120; width: 108; horizontalAlignment: Text.AlignHCenter; elide: Text.ElideRight; text: cov.modelData.title; font.pixelSize: 12; font.weight: cov.on ? Font.DemiBold : Font.Normal; color: cov.on ? Theme.t.accent : Theme.t.text } } }
            Pressable { width: 108; height: 108; y: 6; radius: 20; color: hovered ? Theme.t.hover : "transparent"; border.width: 1; border.color: Theme.t.capsule_border; onClicked: { win.finding = true; finder.text = ""; Backend.find(""); finder.focusIn() }
                Glyph { anchors.centerIn: parent; name: "plus"; size: 26; ink: Theme.t.text_secondary } } } }

    // ---------------- the one you picked up
    Item { visible: Backend.shows.length > 0; anchors { left: parent.left; leftMargin: 18; right: parent.right; rightMargin: 18; top: shelf.bottom; topMargin: 8; bottom: parent.bottom; bottomMargin: win.now.id ? 92 : 14 }
        Label { id: head; width: parent.width - 110; elide: Text.ElideRight; text: Backend.current.title || ""; font.pixelSize: 24; font.weight: Font.Bold }
        Label { y: 34; width: parent.width - 110; maximumLineCount: 2; wrapMode: Text.WordWrap; elide: Text.ElideRight; text: Backend.current.about || Backend.current.author || ""; secondary: true; font.pixelSize: 12 }
        Btn { anchors.right: parent.right; height: 28; text: "Unfollow"; onClicked: Backend.unfollow(Backend.current.id) }
        Label { visible: Backend.episodes.length === 0; anchors.centerIn: parent; secondary: true; text: Backend.busy ? "Fetching episodes…" : "No episodes" }
        ListView { id: list; anchors { fill: parent; topMargin: 78 } clip: true; spacing: 6; model: Backend.episodes; boundsBehavior: Flickable.StopAtBounds
            delegate: Rectangle { id: row; required property var modelData; readonly property bool on: win.now.id === modelData.id; width: list.width; height: 66; radius: 12; color: on ? win.pick : hit.containsMouse ? Theme.t.hover : Theme.t.island
                border.width: 1; border.color: on ? Theme.t.accent : Theme.t.islandLine
                MouseArea { id: hit; anchors.fill: parent; hoverEnabled: true; onClicked: row.on ? (win.playing ? player.pause() : player.play()) : win.start(row.modelData.id) }
                Rectangle { x: 12; anchors.verticalCenter: parent.verticalCenter; width: 36; height: 36; radius: 18; color: row.on ? Theme.t.accent : "transparent"; border.width: 1.4; border.color: Theme.t.accent
                    Glyph { anchors.centerIn: parent; name: row.on && win.playing ? "pause" : "play"; size: 14; ink: row.on ? Theme.t.onAccent : Theme.t.accent } }
                Label { x: 60; y: 9; width: parent.width - 150; elide: Text.ElideRight; text: row.modelData.title; font.weight: row.modelData.played ? Font.Normal : Font.DemiBold; opacity: row.modelData.played ? 0.6 : 1 }
                Label { x: 60; y: 28; width: parent.width - 150; elide: Text.ElideRight; text: row.modelData.about; secondary: true; font.pixelSize: 11 }
                Label { x: 60; y: 45; secondary: true; font.pixelSize: 10
                    text: [row.modelData.date, row.modelData.length, row.modelData.played ? "Played" : row.modelData.spot > 0 ? win.clock(row.modelData.spot * 1000) + " in" : ""].filter(function (x) { return x }).join("  ·  ") }
                Row { anchors { right: parent.right; rightMargin: 10; verticalCenter: parent.verticalCenter } spacing: 5
                    Pressable { width: kl.width + 16; height: 26; radius: 8; border.width: 1; border.color: row.modelData.kept ? Theme.t.accent : Theme.t.capsule_border; color: "transparent"
                        opacity: row.modelData.kept || row.modelData.fetching || hit.containsMouse || hovered ? 1 : 0; onClicked: row.modelData.kept ? Backend.unkeep(row.modelData.id) : Backend.keep(row.modelData.id)
                        Label { id: kl; anchors.centerIn: parent; font.pixelSize: 11; text: row.modelData.fetching ? "Fetching…" : row.modelData.kept ? "Kept ✓" : "Keep" } }
                    Pressable { width: pl.width + 16; height: 26; radius: 8; border.width: 1; border.color: Theme.t.capsule_border; color: "transparent"
                        opacity: hit.containsMouse || hovered ? 1 : 0; onClicked: Backend.togglePlayed(row.modelData.id); Label { id: pl; anchors.centerIn: parent; font.pixelSize: 11; text: row.modelData.played ? "Not Played" : "Played" } } } } } }

    // ---------------- what's playing
    Rectangle { visible: !!win.now.id; anchors { horizontalCenter: parent.horizontalCenter; bottom: parent.bottom; bottomMargin: 14 } width: Math.min(parent.width - 60, 720); height: 68; radius: 34; color: Theme.t.menu_bg; border.width: 1; border.color: Theme.t.accent
        Row { x: 14; anchors.verticalCenter: parent.verticalCenter; spacing: 6
            Pressable { width: 38; height: 38; radius: 19; onClicked: player.position = Math.max(0, player.position - 15000); Label { anchors.centerIn: parent; text: "–15"; font.pixelSize: 12 } }
            Pressable { width: 44; height: 44; radius: 22; color: Theme.t.accent; onClicked: win.playing ? player.pause() : (outLoader.active = true, player.play())
                Glyph { anchors.centerIn: parent; name: win.playing ? "pause" : "play"; size: 17; ink: Theme.t.onAccent } }
            Pressable { width: 38; height: 38; radius: 19; onClicked: player.position = Math.min(player.duration, player.position + 30000); Label { anchors.centerIn: parent; text: "+30"; font.pixelSize: 12 } } }
        Label { x: 160; y: 12; width: parent.width - 360; elide: Text.ElideRight; text: win.now.title || ""; font.weight: Font.DemiBold }
        Pressable { anchors { right: parent.right; rightMargin: 14 } y: 8; width: 44; height: 24; radius: 8; border.width: 1; border.color: Theme.t.capsule_border; color: "transparent"
            onClicked: { var steps = [0.8, 1.0, 1.2, 1.5, 2.0], i = steps.indexOf(Backend.speed); Backend.setSpeed(steps[(i + 1) % steps.length]) }
            Label { anchors.centerIn: parent; text: Backend.speed + "×"; font.pixelSize: 11 } }
        Label { anchors { right: parent.right; rightMargin: 68 } y: 13; text: demo ? "12:40 / 42:00" : win.clock(player.position) + " / " + win.clock(player.duration); secondary: true; font.pixelSize: 11 }
        Rectangle { id: bar; x: 160; y: 44; width: parent.width - 178; height: 6; radius: 3; color: Theme.t.islandLine
            Rectangle { width: parent.width * (demo ? 0.3 : player.duration > 0 ? player.position / player.duration : 0); height: 6; radius: 3; color: Theme.t.accent }
            MouseArea { anchors { fill: parent; margins: -8 } onClicked: function (m) { if (player.seekable) player.position = Math.max(0, Math.min(1, (m.x - 8) / bar.width)) * player.duration } } }
        Label { x: 160; y: 28; width: parent.width - 300; elide: Text.ElideRight; text: win.now.show || ""; secondary: true; font.pixelSize: 11; visible: false } }
    onClosing: if (win.now.id && !demo) Backend.heard(player.position / 1000, player.duration / 1000)
}
