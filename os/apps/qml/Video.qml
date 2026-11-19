import QtQuick

// Media Player, "stage": all picture. The list of videos and the transport float over it.
GlassWindow {
    id: win
    title: "Media Player"; glow: "none"; baseColor: "#050507"
    property int current: demo ? 0 : -1
    property bool showList: !demo
    readonly property var clip: current >= 0 && current < Backend.items.length ? Backend.items[current] : null
    heading: clip ? clip.title : ""
    bare: visibility === Window.FullScreen && !hover.containsMouse
    function play(i) { if (i < 0 || i >= Backend.items.length) return; current = i; showList = false; if (Backend.items[i].url) { player.source = Backend.items[i].url; player.play() } }
    function full() { win.visibility === Window.FullScreen ? win.showNormal() : win.showFullScreen() }
    function playPause() { if (player.playing) player.pause(); else player.play() }
    function skip(ms) { player.position = Math.max(0, Math.min(player.duration, player.position + Number(ms))) }
    function toggleList() { showList = !showList }
    // Playback: the real engine, or (with sample content) a stand-in that only holds numbers for the preview.
    QtObject { id: stub; property bool playing: true; property real position: 83000; property real duration: 228000; property url source; function play() {} function pause() {} }
    QtObject { id: stubAudio; property real volume: 0.7 }
    readonly property var player: engine.item ? engine.item.player : stub
    readonly property var out: engine.item ? engine.item.audio : stubAudio
    MprisLink { player: win.player; title: win.clip ? win.clip.title : ""
        onNext: win.play(win.current + 1); onPrevious: win.play(win.current - 1); onRaise: { win.raise(); win.requestActivate() } }
    islands: [
        Island { anchors { right: parent.right; rightMargin: 12 } y: 12
            Seg { icon: "list"; text: "Videos"; on: win.showList; onClicked: win.showList = !win.showList }
            Seg { icon: "expand"; tip: "Full screen"; onClicked: win.full() } },
        Rail { visible: win.showList; x: 12; y: 64; width: 280; maxHeight: win.height - 64 - 90
            SideTitle { text: "YOUR VIDEOS" }
            Repeater { model: Backend.items
                SideItem { required property var modelData; required property int index; icon: "video"; text: modelData.title; trailing: modelData.length; selected: win.current === index; onClicked: win.play(index) } }
            Label { visible: Backend.items.length === 0; padding: 10; width: parent.width; wrapMode: Text.WordWrap; secondary: true; font.pixelSize: 12; text: "Videos in " + Backend.folderName + " appear here." } },
        Island {   // the transport: the one wide island
            height: 58; radius: 20; pad: 12; anchors { horizontalCenter: parent.horizontalCenter; bottom: parent.bottom; bottomMargin: 14 }
            PlayerBar { width: Math.min(900, win.width - 64); anchors.verticalCenter: parent.verticalCenter; player: win.player; audio: win.out
                onNext: win.play(win.current + 1); onPrevious: win.play(win.current - 1) } }
    ]
    Rectangle { anchors.fill: parent; radius: win.r; color: "#000000"
        Loader { id: engine; active: !demo; source: "Engine.qml"; anchors { fill: parent; margins: win.r > 1 ? 6 : 0 } }
        Rectangle { visible: demo; anchors.fill: parent; radius: win.r
            gradient: Gradient { GradientStop { position: 0; color: "#17122B" } GradientStop { position: 0.55; color: "#2A1F55" } GradientStop { position: 1; color: "#0B0A14" } }
            Rectangle { anchors { bottom: parent.bottom; bottomMargin: parent.height * 0.3 } width: parent.width; height: 2; color: Theme.t.accent; opacity: 0.35 } }
        Column { visible: !demo && !(engine.item && engine.item.hasVideo); anchors.centerIn: parent; spacing: 8
            Glyph { name: "video"; size: 44; ink: "#8A9199"; anchors.horizontalCenter: parent.horizontalCenter }
            Label { text: win.clip ? "Loading…" : "Choose a video from the list"; color: "#C4CBD3"; anchors.horizontalCenter: parent.horizontalCenter } }
        MouseArea { id: hover; anchors.fill: parent; hoverEnabled: true; onClicked: player.playing ? player.pause() : player.play(); onDoubleClicked: win.full() } }
}
