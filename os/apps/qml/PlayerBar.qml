import QtQuick

// Transport controls shared by Music and Media Player.
Item {
    id: bar
    property var player
    property var audio
    property bool canStep: true
    signal next()
    signal previous()
    function clock(ms) { var s = Math.floor(ms / 1000); return Math.floor(s / 60) + ":" + ("0" + s % 60).slice(-2) }
    height: 46
    Row { id: transport; anchors.verticalCenter: parent.verticalCenter; spacing: 4
        Pressable { visible: bar.canStep; width: 34; height: 34; radius: 17; onClicked: bar.previous(); Glyph { anchors.centerIn: parent; name: "prev"; size: 16 } }
        Pressable { width: 40; height: 40; radius: 20; color: Theme.t.accent; onClicked: bar.player.playing ? bar.player.pause() : bar.player.play()
            Glyph { anchors.centerIn: parent; name: bar.player.playing ? "pause" : "play"; size: 16; ink: Theme.t.onAccent } }
        Pressable { visible: bar.canStep; width: 34; height: 34; radius: 17; onClicked: bar.next(); Glyph { anchors.centerIn: parent; name: "next"; size: 16 } } }
    Label { id: pos; anchors { left: transport.right; leftMargin: 14; verticalCenter: parent.verticalCenter } text: bar.clock(bar.player.position); secondary: true; font.pixelSize: 11; font.family: Theme.t.fontMono }
    Meter { anchors { left: pos.right; leftMargin: 10; right: dur.left; rightMargin: 10; verticalCenter: parent.verticalCenter } interactive: true
        value: bar.player.duration > 0 ? bar.player.position / bar.player.duration : (demo ? 0.36 : 0); onMoved: function (v) { bar.player.position = v * bar.player.duration } }
    Label { id: dur; anchors { right: vol.left; rightMargin: 18; verticalCenter: parent.verticalCenter } text: bar.clock(bar.player.duration); secondary: true; font.pixelSize: 11; font.family: Theme.t.fontMono }
    Row { id: vol; anchors { right: parent.right; verticalCenter: parent.verticalCenter } spacing: 8
        Glyph { name: "volume"; size: 16; anchors.verticalCenter: parent.verticalCenter }
        Meter { width: 90; interactive: true; value: bar.audio.volume; onMoved: function (v) { bar.audio.volume = v } anchors.verticalCenter: parent.verticalCenter } }
}
