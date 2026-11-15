import QtQuick
import QtMultimedia

// Camera, "the viewfinder": the picture fills the window; everything else is one island under your thumb.
GlassWindow {
    id: win
    title: "Camera"; width: 960; height: 660; glow: "none"; baseColor: "#0B0C0E"
    property bool video: false
    property int delay: 0                      // seconds to wait before a photo: 0, 3 or 10
    property int counting: 0
    property int which: 0                      // which camera, when there are several
    readonly property bool recording: rec.recorderState === MediaRecorder.RecordingState
    readonly property bool none: !demo && devices.videoInputs.length === 0
    function clock(ms) { var s = Math.floor(ms / 1000), m = Math.floor(s / 60); return (m < 10 ? "0" : "") + m + ":" + (s % 60 < 10 ? "0" : "") + (s % 60) }
    function local(url) { return decodeURIComponent(url.replace("file://", "")) }
    function snap() { var where = Backend.nextPhoto(); if (where !== "") { flash.opacity = 0.85; fade.restart(); still.captureToFile(local(where)) } }
    function press() {
        if (none || counting > 0) return
        if (video) { if (recording) rec.stop(); else { var where = Backend.nextVideo(); if (where !== "") { rec.outputLocation = where; rec.record() } } }
        else if (delay > 0) { counting = delay; tick.start() } else snap()
    }
    Connections { target: Backend; function onFailed(msg) { toast.say(msg, true) } }
    MediaDevices { id: devices }
    Loader { id: micLoader; active: !demo && win.video && devices.audioInputs.length > 0; sourceComponent: AudioInput {} }      // sound only for videos
    CaptureSession {
        camera: Camera { id: cam; active: !win.none && !demo; cameraDevice: devices.videoInputs.length ? devices.videoInputs[Math.min(win.which, devices.videoInputs.length - 1)] : devices.defaultVideoInput
            onErrorOccurred: function (error, text) { toast.say("The camera stopped: " + text, true) } }
        audioInput: micLoader.item
        imageCapture: ImageCapture { id: still; onImageSaved: Backend.refresh(); onErrorOccurred: function (id, error, text) { toast.say("Couldn't take the photo: " + text, true) } }
        recorder: MediaRecorder { id: rec; quality: MediaRecorder.HighQuality
            onRecorderStateChanged: if (recorderState === MediaRecorder.StoppedState) Backend.refresh()
            onErrorOccurred: function (error, text) { toast.say("Couldn't record: " + text, true) } }
        videoOutput: view }
    Timer { id: tick; interval: 1000; repeat: true; onTriggered: { win.counting -= 1; if (win.counting <= 0) { stop(); win.snap() } } }

    islands: [
        Island {   // under your thumb
            anchors { horizontalCenter: parent.horizontalCenter; bottom: parent.bottom; bottomMargin: 18 } height: 72; radius: 26; pad: 12
            Seg { text: "Photo"; on: !win.video; onClicked: if (!win.recording) win.video = false }
            Seg { text: "Video"; on: win.video; onClicked: win.video = true }
            Item { width: 86; height: 72
                Pressable { id: shutter; objectName: "shutter"; anchors.centerIn: parent; width: 58; height: 58; radius: 29; color: "transparent"; border.width: 3; border.color: "#FFFFFF"; opacity: win.none ? 0.4 : 1
                    onClicked: win.press()
                    Rectangle { anchors.centerIn: parent; width: win.recording ? 22 : 46; height: width; radius: win.recording ? 5 : 23; color: win.video ? "#E5484D" : "#FFFFFF"
                        Behavior on width { NumberAnimation { duration: 140 } } Behavior on radius { NumberAnimation { duration: 140 } } } } }
            Seg { visible: !win.video; icon: "clock"; text: win.delay === 0 ? "Off" : win.delay + " s"; tip: "Wait before the photo"; tipAbove: true; onClicked: win.delay = win.delay === 0 ? 3 : win.delay === 3 ? 10 : 0 }
            Label { visible: win.video; width: 62; horizontalAlignment: Text.AlignHCenter; anchors.verticalCenter: parent.verticalCenter; font.family: Theme.t.fontMono; font.pixelSize: 13
                text: win.clock(win.recording ? rec.duration : 0); color: win.recording ? "#E5484D" : Theme.t.text_secondary }
            Seg { visible: devices.videoInputs.length > 1; icon: "camera"; tip: "Other camera"; tipAbove: true; onClicked: if (!win.recording) win.which = (win.which + 1) % devices.videoInputs.length } },
        Pressable {   // the last one taken
            visible: Backend.last.path !== undefined; anchors { left: parent.left; leftMargin: 18; bottom: parent.bottom; bottomMargin: 22 } width: 64; height: 64; radius: 16
            color: Theme.t.island; border.width: 2; border.color: "#FFFFFF"; clip: true; onClicked: Backend.show(Backend.last.path)
            Image { anchors { fill: parent; margins: 2 } visible: !Backend.last.video; source: Backend.last.video || !Backend.last.url ? "" : Backend.last.url; fillMode: Image.PreserveAspectCrop; asynchronous: true; sourceSize.width: 160 }
            Glyph { visible: !!Backend.last.video; anchors.centerIn: parent; name: "video"; size: 26 } },
        Toast { id: toast; anchors { horizontalCenter: parent.horizontalCenter; top: parent.top; topMargin: 64 } }
    ]

    Rectangle { anchors { fill: parent; margins: 10; topMargin: 58; bottomMargin: 100 } radius: 18; color: "#000000"; clip: true
        VideoOutput { id: view; anchors.fill: parent; fillMode: VideoOutput.PreserveAspectFit; visible: !demo }
        Rectangle { visible: demo; anchors.fill: parent; radius: 18     // a stand-in scene for previews
            gradient: Gradient { GradientStop { position: 0; color: "#35506B" } GradientStop { position: 0.55; color: "#C98F6B" } GradientStop { position: 1; color: "#2B2A33" } } }
        Repeater { model: demo || !win.none ? [[0.33, 0], [0.67, 0], [0, 0.33], [0, 0.67]] : []      // thirds, to line things up
            Rectangle { required property var modelData; color: "#30FFFFFF"; x: modelData[0] * parent.width; y: modelData[1] * parent.height
                width: modelData[0] ? 1 : parent.width; height: modelData[1] ? 1 : parent.height } }
        Column { visible: win.none; anchors.centerIn: parent; spacing: 10
            Glyph { name: "camera"; size: 54; ink: "#8A8F98"; anchors.horizontalCenter: parent.horizontalCenter }
            Label { anchors.horizontalCenter: parent.horizontalCenter; color: "#C8CCD2"; font.pixelSize: 16; text: "No camera found" }
            Label { anchors.horizontalCenter: parent.horizontalCenter; color: "#8A8F98"; text: "Plug one in, or check that its cover or switch is open." } }
        Label { visible: win.counting > 0; anchors.centerIn: parent; text: win.counting; color: "#FFFFFF"; font.pixelSize: 160; font.weight: Font.Light }
        Rectangle { visible: win.recording; x: 16; y: 16; width: rl.width + 26; height: 26; radius: 13; color: "#B0000000"
            Rectangle { x: 9; width: 8; height: 8; radius: 4; color: "#E5484D"; anchors.verticalCenter: parent.verticalCenter }
            Label { id: rl; x: 22; anchors.verticalCenter: parent.verticalCenter; color: "#FFFFFF"; font.pixelSize: 11; text: "REC" } }
        Rectangle { id: flash; anchors.fill: parent; color: "#FFFFFF"; opacity: 0; NumberAnimation on opacity { id: fade; to: 0; duration: 260; running: false } }
    }
    Shortcut { sequence: "Space"; onActivated: win.press() }
}
