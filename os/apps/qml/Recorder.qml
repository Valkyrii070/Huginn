import QtQuick
import QtMultimedia

// Voice Recorder, "the red light": one big button and a clock; what you have recorded lines up at the right.
GlassWindow {
    id: win
    title: "Voice Recorder"; width: 880; height: 600; glow: "bottom"
    property string at: ""                     // the recording that is selected
    property var sheet: null                   // { kind: "rename", path, name, why }
    readonly property bool recording: rec.recorderState !== MediaRecorder.StoppedState
    readonly property bool paused: rec.recorderState === MediaRecorder.PausedState
    readonly property bool noMic: !demo && devices.audioInputs.length === 0
    function clock(ms) { var s = Math.floor(ms / 1000), m = Math.floor(s / 60), h = Math.floor(m / 60); return (h ? h + ":" : "") + (m % 60 < 10 ? "0" : "") + (m % 60) + ":" + (s % 60 < 10 ? "0" : "") + (s % 60) }
    function start() { var where = Backend.nextRecording(); if (where === "") return; player.stop(); rec.outputLocation = where; rec.record() }
    Connections { target: Backend; function onFailed(msg) { toast.say(msg, true) } }
    MediaDevices { id: devices }
    // the microphone and the speaker are only reached for when there is one and it is needed
    Loader { id: micLoader; active: !demo && devices.audioInputs.length > 0; sourceComponent: AudioInput {} }
    Loader { id: outLoader; active: false; sourceComponent: AudioOutput {} }
    CaptureSession { audioInput: micLoader.item
        recorder: MediaRecorder { id: rec; quality: MediaRecorder.HighQuality
            mediaFormat { fileFormat: MediaFormat.Mpeg4Audio; audioCodec: MediaFormat.AudioCodec.AAC }
            onRecorderStateChanged: if (recorderState === MediaRecorder.StoppedState) { Backend.refresh(); if (Backend.items.length) win.at = Backend.items[0].path }
            onErrorOccurred: function (error, text) { toast.say("Couldn't record: " + text, true) } } }
    MediaPlayer { id: player; audioOutput: outLoader.item }

    islands: [
        Toast { id: toast; anchors { horizontalCenter: parent.horizontalCenter; bottom: parent.bottom; bottomMargin: 18 } },
        Item { anchors.fill: parent; z: 20; visible: win.sheet !== null
            Rectangle { anchors.fill: parent; radius: win.r; color: "#66000000"; MouseArea { anchors.fill: parent; acceptedButtons: Qt.AllButtons } }
            Rectangle { anchors.centerIn: parent; width: 420; height: 176; radius: 16; color: Theme.t.menu_bg; border.width: 1; border.color: Theme.t.menu_border
                function go() { var why = Backend.rename(win.sheet.path, nameBox.text); if (why === "") { win.sheet = null; if (Backend.items.length) win.at = "" } else win.sheet = { kind: "rename", path: win.sheet.path, name: nameBox.text, why: why } }
                Label { x: 22; y: 20; font.pixelSize: 16; font.weight: Font.DemiBold; text: "Rename" }
                TextBox { id: nameBox; x: 22; y: 56; width: parent.width - 44; onAccepted: parent.go() }
                Label { x: 22; y: 98; width: parent.width - 44; elide: Text.ElideRight; color: Theme.t.danger; font.pixelSize: 12; text: win.sheet ? (win.sheet.why || "") : "" }
                Row { anchors { right: parent.right; rightMargin: 22; bottom: parent.bottom; bottomMargin: 20 } spacing: 8
                    Btn { text: "Cancel"; onClicked: win.sheet = null } Btn { primary: true; text: "Rename"; onClicked: parent.parent.go() } } } }
    ]
    onSheetChanged: if (sheet) { nameBox.text = sheet.name; nameBox.focusIn(); nameBox.input.selectAll() }

    // ---------------- the red light
    Item { x: 0; y: 62; width: parent.width - 330; height: parent.height - 62
        Column { anchors.centerIn: parent; anchors.verticalCenterOffset: -20; spacing: 18
            Label { anchors.horizontalCenter: parent.horizontalCenter; font.pixelSize: 76; font.weight: Font.Light; font.family: Theme.t.fontMono
                text: win.clock(win.recording ? rec.duration : 0); color: win.recording && !win.paused ? Theme.t.text : Theme.t.text_secondary }
            Label { anchors.horizontalCenter: parent.horizontalCenter; secondary: true
                text: win.noMic ? "No microphone found. Plug one in and it will be used." : win.paused ? "Paused" : win.recording ? "Recording from " + (micLoader.item && micLoader.item.device.description ? micLoader.item.device.description : "the microphone") : "Ready"
                color: win.noMic ? Theme.t.danger : Theme.t.text_secondary }
            Item { width: 200; height: 120; anchors.horizontalCenter: parent.horizontalCenter
                Rectangle { anchors.centerIn: parent; width: 112; height: 112; radius: 56; color: "transparent"; border.width: 2; border.color: Theme.t.accent; opacity: win.recording && !win.paused ? 0.5 : 0
                    SequentialAnimation on scale { running: win.recording && !win.paused; loops: Animation.Infinite; NumberAnimation { from: 0.86; to: 1.12; duration: 900; easing.type: Easing.InOutSine } NumberAnimation { from: 1.12; to: 0.86; duration: 900; easing.type: Easing.InOutSine } } }
                Pressable { id: big; objectName: "big"; anchors.centerIn: parent; width: 88; height: 88; radius: 44; color: Theme.t.island; border.width: 2; border.color: Theme.t.islandLine; opacity: win.noMic ? 0.4 : 1
                    onClicked: if (!win.noMic) { if (win.recording) rec.stop(); else win.start() }
                    Rectangle { anchors.centerIn: parent; width: win.recording ? 30 : 56; height: width; radius: win.recording ? 7 : 28; color: "#E5484D"
                        Behavior on width { NumberAnimation { duration: 140 } } Behavior on radius { NumberAnimation { duration: 140 } } } } }
            Btn { anchors.horizontalCenter: parent.horizontalCenter; opacity: win.recording ? 1 : 0; text: win.paused ? "Carry On" : "Pause"; onClicked: if (win.recording) { if (win.paused) rec.record(); else rec.pause() } }
        }
        Label { anchors { horizontalCenter: parent.horizontalCenter; bottom: parent.bottom; bottomMargin: 18 } secondary: true; font.pixelSize: 11; text: "Saved in " + Backend.folderName }
    }

    // ---------------- what you have recorded
    Rectangle { x: parent.width - 330; y: 62; width: 316; height: parent.height - 76; radius: 16; color: Theme.t.island; border.width: 1; border.color: Theme.t.islandLine
        Label { visible: Backend.items.length === 0; anchors.centerIn: parent; width: parent.width - 40; horizontalAlignment: Text.AlignHCenter; wrapMode: Text.WordWrap; secondary: true; text: "Your recordings will line up here" }
        ListView { anchors { fill: parent; margins: 6 } clip: true; spacing: 2; model: Backend.items
            delegate: Pressable { id: it; required property var modelData; readonly property bool open: win.at === modelData.path; readonly property bool playing: open && player.playbackState === MediaPlayer.PlayingState
                width: ListView.view.width; height: open ? 92 : 50; radius: 12; color: open ? Qt.rgba(win.tintColor.r, win.tintColor.g, win.tintColor.b, 0.18) : (hovered ? Theme.t.hover : "transparent")
                onClicked: { if (win.at !== modelData.path) { player.stop(); win.at = modelData.path } }
                Label { x: 12; y: 8; width: parent.width - 24; elide: Text.ElideRight; text: modelData.name; font.weight: Font.Medium }
                Label { x: 12; y: 27; text: modelData.when + " · " + (modelData.length ? modelData.length + " · " : "") + modelData.size; secondary: true; font.pixelSize: 11 }
                Row { visible: it.open; x: 8; y: 52; spacing: 2
                    Seg { anchors.verticalCenter: undefined; icon: it.playing ? "pause" : "play"; on: it.playing; tip: it.playing ? "Pause" : "Play"
                        onClicked: { if (it.playing) player.pause(); else { outLoader.active = true; if (player.source.toString() !== it.modelData.url) player.source = it.modelData.url; player.play() } } }
                    Label { y: 7; leftPadding: 4; rightPadding: 8; font.pixelSize: 11; font.family: Theme.t.fontMono; secondary: true
                        text: player.source.toString() === it.modelData.url && player.duration > 0 ? win.clock(player.position) + " / " + win.clock(player.duration) : "" }
                    Seg { anchors.verticalCenter: undefined; text: "Rename"; onClicked: win.sheet = { kind: "rename", path: it.modelData.path, name: it.modelData.name, why: "" } }
                    Seg { anchors.verticalCenter: undefined; icon: "folder"; tip: "Show in Files"; onClicked: Backend.show("") }
                    Seg { anchors.verticalCenter: undefined; icon: "trash"; danger: true; tip: "Move to the Trash"; onClicked: { player.stop(); player.source = ""; win.at = ""; Backend.remove(it.modelData.path) } } } } } }
    Shortcut { sequence: "Space"; enabled: win.sheet === null && !win.noMic; onActivated: big.clicked() }
}
