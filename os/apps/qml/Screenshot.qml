import QtQuick

// Screenshot, "viewfinder": the screen freezes and you drag a frame over it, with one island of tools.
// Then mark the picture up; one island holds what happens next.
GlassWindow {
    id: win
    title: "Screenshot"; heading: Backend.image ? "Mark Up" : ""; width: 980; height: 680; glow: "bottom"; padTop: 58
    bare: Backend.framing                                 // while you drag a frame the frozen screen fills the display
    property int delay: 0
    property string tool: "pen"
    property color ink: Theme.t.danger
    property var marks: demo ? [{ tool: "box", ink: "#FF5F57", pts: [0.33, 0.07, 0.56, 0.16] }, { tool: "pen", ink: "#43D9B8", pts: [0.60, 0.20, 0.62, 0.17, 0.65, 0.19, 0.68, 0.15, 0.71, 0.18] }] : []
    property var drawing: null
    property string notice: ""
    Connections { target: Backend; function onFailed(msg) { win.notice = msg; hide.restart() }
        function onChanged() {
            if (!Backend.image) win.marks = []
            if (Backend.busy) return
            if (Backend.framing) { stage.set(0.2, 0.2, 0.6, 0.6); win.showFullScreen(); stage.forceActiveFocus() }     // the screen is frozen: frame it
            else if (!win.visible || win.visibility === Window.FullScreen) win.showNormal() } }
    function capture(framed) {                            // this window steps aside so it isn't in the picture
        if (Backend.busy) return
        win.hide(); framed ? Backend.frame(win.delay) : Backend.take(false, win.delay) }
    Timer { id: hide; interval: 6000; onTriggered: win.notice = "" }
    function write(path, then) { win.drawing = null; frame.grabToImage(function (r) { if (r.saveToFile(path)) then(path); else win.notice = "The picture couldn't be saved." }, Qt.size(shot.sourceSize.width, shot.sourceSize.height)) }

    toolbar: [
        Seg { visible: !!Backend.image; icon: "back"; text: "Undo"; opacity: win.marks.length ? 1 : 0.4; onClicked: win.marks = win.marks.slice(0, -1) },
        Row { visible: !!Backend.image; spacing: 6; anchors.verticalCenter: parent.verticalCenter
            Repeater { model: [Theme.t.danger, "#FFB340", Theme.t.accent, Theme.t.glowB, "#101317", "#FFFFFF"]
                Rectangle { required property color modelData; width: 20; height: 20; radius: 10; color: modelData; border.width: Qt.colorEqual(win.ink, modelData) ? 3 : 1; border.color: Qt.colorEqual(win.ink, modelData) ? Theme.t.text : Theme.t.capsule_border
                    MouseArea { anchors.fill: parent; onClicked: win.ink = parent.modelData } } } },
        Repeater { model: Backend.image ? [["marker", "Highlight", "edit"], ["box", "Box", "expand"], ["pen", "Pen", "edit"]] : []
            Seg { required property var modelData; icon: modelData[2]; text: modelData[1]; on: win.tool === modelData[0]; onClicked: win.tool = modelData[0] } }
    ]
    Connections { target: Backend; function onRecorded(path) { win.lastVideo = path; win.notice = "" } }
    property string lastVideo: ""
    property bool recSound: true
    Timer { interval: 1000; repeat: true; running: Backend.recording === "on"; onTriggered: recClock.text = win.span(Backend.recordedFor) }
    function span(s) { return Math.floor(s / 60) + ":" + (s % 60 < 10 ? "0" : "") + (s % 60) }
    // ---------------- Take one
    Column { visible: !Backend.image && !Backend.framing; anchors.centerIn: parent; spacing: 22
        Row { spacing: 16; anchors.horizontalCenter: parent.horizontalCenter
            Repeater { model: [["Whole Screen", "Everything you can see", "display", false], ["Choose an Area", "Drag a frame on your screen", "expand", true]]
                Pressable { required property var modelData; width: 250; height: 170; radius: 16; color: hovered ? Theme.t.hover : Theme.t.group; border.width: 1; border.color: Theme.t.islandLine
                    opacity: Backend.busy ? 0.5 : 1; onClicked: win.capture(modelData[3])
                    Glyph { y: 34; anchors.horizontalCenter: parent.horizontalCenter; name: modelData[2]; size: 44; ink: Theme.t.accent }
                    Label { y: 96; anchors.horizontalCenter: parent.horizontalCenter; text: modelData[0]; font.pixelSize: 16; font.weight: Font.DemiBold }
                    Label { y: 122; anchors.horizontalCenter: parent.horizontalCenter; text: modelData[1]; secondary: true; font.pixelSize: 12 } } } }
        Row { spacing: 10; anchors.horizontalCenter: parent.horizontalCenter
            Label { text: "Wait first:"; secondary: true; anchors.verticalCenter: parent.verticalCenter }
            Repeater { model: [[0, "No"], [3, "3 seconds"], [10, "10 seconds"]]; Btn { required property var modelData; pill: true; primary: win.delay === modelData[0]; text: modelData[1]; onClicked: win.delay = modelData[0] } } }
        Label { anchors.horizontalCenter: parent.horizontalCenter; text: win.notice || (Backend.busy ? "Taking the screenshot…" : "Screenshots are saved in " + Backend.folder); color: win.notice ? Theme.t.danger : Theme.t.text_secondary; font.pixelSize: 12 }
        Rectangle { anchors.horizontalCenter: parent.horizontalCenter; width: 516; height: 58; radius: 16; color: Backend.recording === "on" ? Qt.rgba(0.9, 0.28, 0.3, 0.16) : Theme.t.group; border.width: 1; border.color: Backend.recording === "on" ? "#E5484D" : Theme.t.islandLine
            Rectangle { x: 18; anchors.verticalCenter: parent.verticalCenter; width: 14; height: 14; radius: Backend.recording === "on" ? 3 : 7; color: "#E5484D"
                SequentialAnimation on opacity { running: Backend.recording === "on"; loops: Animation.Infinite; NumberAnimation { to: 0.3; duration: 700 } NumberAnimation { to: 1; duration: 700 } } }
            Label { x: 44; y: 11; text: Backend.recording === "on" ? "Recording" : Backend.recording === "asking" ? "Choose what to record…" : Backend.recording === "ending" ? "Finishing the video…" : "Record a Video"; font.weight: Font.DemiBold }
            Label { id: recClock; x: 44; y: 31; secondary: true; font.pixelSize: 11; visible: Backend.recording === "on"; text: "0:00" }
            Label { x: 44; y: 31; width: 250; elide: Text.ElideMiddle; secondary: true; font.pixelSize: 11; visible: Backend.recording !== "on"
                text: win.lastVideo ? "Saved: " + win.lastVideo.split("/").pop() : "Your desktop asks which screen or window." }
            Row { anchors { right: parent.right; rightMargin: 12; verticalCenter: parent.verticalCenter } spacing: 6
                Btn { visible: win.lastVideo !== "" && Backend.recording === ""; height: 28; text: "Show"; onClicked: Backend.reveal(win.lastVideo) }
                Btn { visible: Backend.recording === ""; height: 28; text: win.recSound ? "Sound: On" : "Sound: Off"; onClicked: win.recSound = !win.recSound }
                Btn { objectName: "recBtn"; height: 28; primary: Backend.recording === ""; danger: Backend.recording === "on"; opacity: Backend.recording === "ending" ? 0.5 : 1
                    text: Backend.recording === "on" ? "Stop" : Backend.recording === "asking" ? "Cancel" : "Record"; onClicked: Backend.recording === "" ? Backend.record(win.recSound) : Backend.stopRecording() } } } }
    // ---------------- Mark it up
    Item { visible: !!Backend.image && !Backend.framing; anchors { fill: parent; bottomMargin: 66 }
        Item { id: frame; anchors.centerIn: parent
            readonly property real fit: Math.min((parent.width - 32) / Math.max(1, shot.sourceSize.width), (parent.height - 32) / Math.max(1, shot.sourceSize.height), 1)
            width: shot.sourceSize.width * fit; height: shot.sourceSize.height * fit
            Image { id: shot; anchors.fill: parent; source: Backend.image; cache: false; smooth: true }
            Canvas { id: ink; anchors.fill: parent
                property var all: win.marks; property var live: win.drawing
                onAllChanged: requestPaint(); onLiveChanged: requestPaint(); onWidthChanged: requestPaint()
                onPaint: { var c = getContext("2d"); c.reset(); c.lineCap = "round"; c.lineJoin = "round"
                    var list = all.concat(live ? [live] : [])
                    for (var i = 0; i < list.length; i++) { var m = list[i], p = m.pts; c.strokeStyle = m.ink; c.globalAlpha = m.tool === "marker" ? 0.4 : 1; c.lineWidth = (m.tool === "marker" ? 0.022 : 0.005) * width
                        c.beginPath()
                        if (m.tool === "box") { if (p.length >= 4) c.rect(p[0] * width, p[1] * height, (p[2] - p[0]) * width, (p[3] - p[1]) * height) }
                        else { for (var k = 0; k + 1 < p.length; k += 2) k ? c.lineTo(p[k] * width, p[k + 1] * height) : c.moveTo(p[k] * width, p[k + 1] * height) }
                        c.stroke() } } }
            MouseArea { anchors.fill: parent; cursorShape: Qt.CrossCursor
                onPressed: function (m) { win.drawing = { tool: win.tool, ink: win.ink.toString(), pts: [m.x / width, m.y / height, m.x / width, m.y / height] } }
                onPositionChanged: function (m) { if (!win.drawing) return; var d = win.drawing, p = d.pts.slice(), x = Math.max(0, Math.min(1, m.x / width)), y = Math.max(0, Math.min(1, m.y / height))
                    if (d.tool === "box") { p[2] = x; p[3] = y } else p.push(x, y); win.drawing = { tool: d.tool, ink: d.ink, pts: p } }
                onReleased: { if (win.drawing) { win.marks = win.marks.concat([win.drawing]); win.drawing = null } } } } }
    Island {   // what happens to the picture: the main island
        visible: !!Backend.image && !Backend.framing; z: 6; anchors { horizontalCenter: parent.horizontalCenter; bottom: parent.bottom; bottomMargin: 14 }
        Label { leftPadding: 10; rightPadding: 6; width: Math.min(implicitWidth, win.width - 460); elide: Text.ElideMiddle; font.pixelSize: 12; anchors.verticalCenter: parent.verticalCenter
            color: win.notice ? Theme.t.danger : Theme.t.text_secondary; text: win.notice || (Backend.saved ? "Saved as " + Backend.saved : "Draw on the picture, then save or copy it.") }
        IslandGap {}
        Seg { text: "Discard"; danger: true; onClicked: Backend.discard() }
        Seg { visible: Backend.saved !== ""; text: "Show in Files"; onClicked: Backend.reveal(Backend.saved) }
        Seg { text: "Copy"; onClicked: win.write(Backend.nextPath().replace(/[^/]+$/, ".copy.png"), function (p) { Backend.copy(p); win.notice = ""; Backend.wasSaved("") ; win.notice = "Copied. Paste it anywhere." ; hide.restart() }) }
        Seg { text: "Save"; on: true; onClicked: win.write(Backend.nextPath(), function (p) { Backend.wasSaved(p) }) }
    }
    // ---------------- Frame it: the screen as it was, filling the display. Drag the part you want.
    Item { id: stage; objectName: "stage"; visible: Backend.framing; anchors.fill: parent; z: 50
        property real fx: 0.2; property real fy: 0.2; property real fw: 0.6; property real fh: 0.6      // the frame, as fractions of the picture
        readonly property bool whole: fw > 0.999 && fh > 0.999
        onVisibleChanged: if (visible) forceActiveFocus()      // so Enter and Esc work at once
        Component.onCompleted: if (visible) forceActiveFocus()
        function lim(v) { return Math.max(0, Math.min(1, v)) }
        function set(x, y, w, h) { fx = x; fy = y; fw = w; fh = h }
        function take() { (fw * Backend.pixels[0] < 8 || fh * Backend.pixels[1] < 8) ? Backend.crop(0, 0, 1, 1) : Backend.crop(fx, fy, fw, fh) }   // a frame too small to mean anything: the whole screen
        function cancel() { Backend.discard() }
        Keys.onPressed: function (e) { if (e.key === Qt.Key_Return || e.key === Qt.Key_Enter) { take(); e.accepted = true } else if (e.key === Qt.Key_Escape) { cancel(); e.accepted = true } }
        Rectangle { anchors.fill: parent; color: "#000000" }
        Item { id: pic; anchors.centerIn: parent
            readonly property real k: Math.min(stage.width / Math.max(1, Backend.pixels[0]), stage.height / Math.max(1, Backend.pixels[1]))
            width: Backend.pixels[0] * k; height: Backend.pixels[1] * k
            Image { anchors.fill: parent; source: Backend.framing ? Backend.image : ""; cache: false }
            Repeater { model: 4   // everything outside the frame is dimmed: above, below, left, right
                Rectangle { required property int index; color: "#99000000"
                    x: index === 3 ? sel.x + sel.width : 0; y: index === 1 ? sel.y + sel.height : index === 0 ? 0 : sel.y
                    width: index < 2 ? pic.width : index === 2 ? sel.x : pic.width - sel.x - sel.width
                    height: index === 0 ? sel.y : index === 1 ? pic.height - sel.y - sel.height : sel.height } }
            MouseArea { anchors.fill: parent; cursorShape: Qt.CrossCursor; property real ax: 0; property real ay: 0   // drag anywhere: a new frame
                onPressed: function (m) { ax = stage.lim(m.x / width); ay = stage.lim(m.y / height); stage.set(ax, ay, 0, 0) }
                onPositionChanged: function (m) { var bx = stage.lim(m.x / width), by = stage.lim(m.y / height); stage.set(Math.min(ax, bx), Math.min(ay, by), Math.abs(bx - ax), Math.abs(by - ay)) } }
            Rectangle { id: sel; x: stage.fx * pic.width; y: stage.fy * pic.height; width: stage.fw * pic.width; height: stage.fh * pic.height; color: "transparent"; border.width: 2; border.color: Theme.t.accent
                MouseArea { anchors.fill: parent; cursorShape: Qt.SizeAllCursor; property real ox: 0; property real oy: 0   // drag inside: move the frame
                    onPressed: function (m) { ox = m.x; oy = m.y }
                    onPositionChanged: function (m) { stage.set(Math.max(0, Math.min(1 - stage.fw, (sel.x + m.x - ox) / pic.width)), Math.max(0, Math.min(1 - stage.fh, (sel.y + m.y - oy) / pic.height)), stage.fw, stage.fh) } }
                Repeater { model: 4   // a handle on each corner
                    Rectangle { required property int index; readonly property bool atLeft: index % 2 === 0; readonly property bool atTop: index < 2
                        width: 14; height: 14; radius: 7; color: Theme.t.accent; border.width: 2; border.color: "#0C1013"; x: atLeft ? -7 : sel.width - 7; y: atTop ? -7 : sel.height - 7
                        MouseArea { anchors { fill: parent; margins: -8 } cursorShape: parent.atLeft === parent.atTop ? Qt.SizeFDiagCursor : Qt.SizeBDiagCursor; property real ex: 0; property real ey: 0
                            onPressed: { ex = parent.atLeft ? stage.fx + stage.fw : stage.fx; ey = parent.atTop ? stage.fy + stage.fh : stage.fy }   // the opposite corner stays put
                            onPositionChanged: function (m) { var p = mapToItem(pic, m.x, m.y), px = stage.lim(p.x / pic.width), py = stage.lim(p.y / pic.height)
                                stage.set(Math.min(px, ex), Math.min(py, ey), Math.abs(px - ex), Math.abs(py - ey)) } } } }
                Rectangle { visible: sel.width > 4; x: 0; y: sel.y > 34 ? -28 : 6; width: sz.width + 16; height: 22; radius: 7; color: Theme.t.accent
                    Label { id: sz; anchors.centerIn: parent; text: Math.round(stage.fw * Backend.pixels[0]) + " × " + Math.round(stage.fh * Backend.pixels[1]); color: Theme.t.onAccent; font.pixelSize: 11; font.weight: Font.Bold } }
            }
        }
        Island {   // the one island of tools
            anchors { horizontalCenter: parent.horizontalCenter; bottom: parent.bottom; bottomMargin: 26 }
            Seg { icon: "expand"; text: "Area"; on: !stage.whole; onClicked: stage.set(0.2, 0.2, 0.6, 0.6) }
            Seg { icon: "display"; text: "Whole Screen"; on: stage.whole; onClicked: stage.set(0, 0, 1, 1) }
            IslandGap {}
            Label { text: "Enter to capture  ·  Esc to cancel"; secondary: true; font.pixelSize: 11; leftPadding: 4; rightPadding: 8; anchors.verticalCenter: parent.verticalCenter }
            Seg { text: "Cancel"; onClicked: stage.cancel() }
            Seg { text: "Capture"; on: true; onClicked: stage.take() }
        }
    }
}
