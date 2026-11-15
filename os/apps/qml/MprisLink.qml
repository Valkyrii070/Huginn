import QtQuick

// Tells the standard media controls (MPRIS: the dock's live island, the keyboard's media keys, any other player
// remote) what this app is playing, and does what they ask: play, pause, skip, jump to a moment, come forward.
QtObject {
    id: link
    property var player: null               // a MediaPlayer (or a preview's stand-in)
    property string title: ""
    property string artist: ""
    property string album: ""
    property string art: ""
    signal next()
    signal previous()
    signal raise()
    readonly property bool isPlaying: player ? (player.playing !== undefined ? !!player.playing : player.playbackState === 1) : false
    function say() {
        if (typeof Mpris === "undefined" || !Mpris) return
        Mpris.update({ title: title, artist: artist, album: album, art: art, playing: isPlaying,
                       length: player && player.duration ? player.duration : 0, position: player && player.position ? player.position : 0 })
    }
    onTitleChanged: say()
    onIsPlayingChanged: say()
    property Connections fromPlayer: Connections { target: link.player; ignoreUnknownSignals: true
        function onDurationChanged() { link.say() } }
    property Timer tick: Timer { interval: 5000; repeat: true; running: link.isPlaying; onTriggered: link.say() }   // where it is, now and then
    property Connections fromOutside: Connections { target: typeof Mpris !== "undefined" ? Mpris : null; ignoreUnknownSignals: true
        function onCommand(what, value) {
            var p = link.player
            if (!p) return
            if (what === "playpause") { if (link.isPlaying) p.pause(); else p.play() }
            else if (what === "play") p.play()
            else if (what === "pause" || what === "stop") p.pause()
            else if (what === "next") link.next()
            else if (what === "previous") link.previous()
            else if (what === "setposition") { p.position = value; link.say() }
            else if (what === "raise") link.raise()
        } }
}
