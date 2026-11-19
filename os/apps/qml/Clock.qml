import QtQuick

// Clock, "dial": a real dial; the modes switch in the island the light comes from.
GlassWindow {
    id: win
    title: "Clock"; width: 820; height: 600; glow: "bottom"; padTop: 60; padBottom: 66
    property string page: startPage || "World Clock"
    function setPage(p) { page = p }
    property real hAngle: 0
    property real mAngle: 0
    property real sAngle: 0
    property var cities: Backend.world()
    property string now: ""
    property string today: ""
    // stopwatch
    property bool running: false
    property real elapsed: 0
    property real since: 0
    property var laps: []
    // timer
    property int setMinutes: 5
    property real left: 0
    property real until: 0
    property bool counting: false
    property bool rang: false
    property real total: 0                 // the whole length of the timer that's running (it grows with +1 min)
    // The dock's live island shows the timer while it runs (a ring counting down) and rings there when it's done;
    // its buttons (Pause, +1 min, Cancel, Stop) work from there too.
    readonly property string liveKey: rang ? "rang" : counting ? "on:" + until + ":" + total : left > 0 ? "paused:" + Math.round(left) : "off"
    onLiveKeyChanged: {
        var plus = { id: "add60", label: "+1 min" }, cancel = { id: "cancel", label: "Cancel", glyph: "x" }
        if (rang) LiveIsland.report("timer", { kind: "alarm", title: "Timer", glyph: "bell",
            actions: [{ id: "stop", label: "Stop", glyph: "stop", tone: "danger" }, { id: "again", label: "Again", glyph: "refresh" }] })
        else if (counting) LiveIsland.report("timer", { kind: "timer", title: "Timer", ends: until, total: total, paused: false,
            actions: [plus, { id: "pause", label: "Pause", glyph: "pause", tone: "primary" }, cancel] })
        else if (left > 0) LiveIsland.report("timer", { kind: "timer", title: "Timer", left: left, total: total, paused: true,
            actions: [plus, { id: "resume", label: "Resume", glyph: "play", tone: "primary" }, cancel] })
        else LiveIsland.end("timer")
    }
    function startTimer(ms) { rang = false; total = ms; until = Date.now() + ms; left = ms; counting = true }
    Connections { target: LiveIsland
        function onAction(key, what) {
            if (key !== "timer") return
            if (what === "pause" && win.counting) { win.left = win.until - Date.now(); win.counting = false }
            else if (what === "resume" && win.left > 0) { win.until = Date.now() + win.left; win.counting = true }
            else if (what === "add60") { if (win.counting) win.until += 60000; else win.left += 60000; win.total += 60000 }
            else if (what === "cancel" || what === "stop") { win.counting = false; win.left = 0; win.rang = false }
            else if (what === "again") win.startTimer(win.setMinutes * 60000)
        } }
    function fmt(ms, tenths) { var t = Math.max(0, ms), m = Math.floor(t / 60000), s = Math.floor(t / 1000) % 60; return (m < 10 ? "0" : "") + m + ":" + (s < 10 ? "0" : "") + s + (tenths ? "." + Math.floor(t / 100) % 10 : "") }
    Timer { interval: 1000; running: true; repeat: true; triggeredOnStart: true; onTriggered: { var d = new Date(); win.now = Qt.formatTime(d, "HH:mm:ss"); win.today = Qt.formatDate(d, "dddd, MMMM d"); win.sAngle = d.getSeconds() * 6; win.mAngle = d.getMinutes() * 6 + d.getSeconds() / 10; win.hAngle = (d.getHours() % 12) * 30 + d.getMinutes() / 2; if (d.getSeconds() === 0 || win.cities.length === 0) win.cities = Backend.world() } }
    Timer { interval: 50; running: win.running || win.counting; repeat: true
        onTriggered: { if (win.running) win.elapsed = Date.now() - win.since; if (win.counting) { win.left = win.until - Date.now(); if (win.left <= 0) { win.counting = false; win.left = 0; win.rang = true } } } }
    islands: [
        Island { anchors { horizontalCenter: parent.horizontalCenter; bottom: parent.bottom; bottomMargin: 14 }
            Repeater { model: [["World Clock", "clock"], ["Stopwatch", "play"], ["Timer", "bell"]]
                Seg { required property var modelData; icon: modelData[1]; on: win.page === modelData[0]; onClicked: win.page = modelData[0]
                    text: modelData[0] + (modelData[0] === "Timer" && win.counting ? "  ·  " + win.fmt(win.left, false) : "") } } }
    ]
    component Hand: Rectangle { id: hand; property real angle: 0; property real len: 40; x: 80 - width / 2; y: 80 - len; height: len; radius: width / 2; antialiasing: true
        transform: Rotation { origin.x: hand.width / 2; origin.y: hand.len; angle: hand.angle } }
    component Big: Label { font.pixelSize: 72; font.weight: Font.Light; font.family: Theme.t.font; anchors.horizontalCenter: parent.horizontalCenter }
    Column { visible: win.page === "World Clock"; x: 28; y: 10; width: parent.width - 56; spacing: 18
        Row { anchors.horizontalCenter: parent.horizontalCenter; spacing: 36
            Rectangle { width: 160; height: 160; radius: 80; color: Theme.t.group; border.width: 1; border.color: Theme.t.islandLine   // the dial
                Repeater { model: 12; Rectangle { required property int index; x: 79; y: 7; width: 2; height: index % 3 === 0 ? 11 : 5; color: index % 3 === 0 ? Theme.t.text : Theme.t.text_secondary; antialiasing: true
                    transform: Rotation { origin.x: 1; origin.y: 73; angle: index * 30 } } }
                Hand { width: 5; len: 44; angle: win.hAngle; color: Theme.t.text }
                Hand { width: 3; len: 62; angle: win.mAngle; color: Theme.t.text }
                Hand { width: 1.5; len: 68; angle: win.sAngle; color: Theme.t.accent }
                Rectangle { anchors.centerIn: parent; width: 10; height: 10; radius: 5; color: Theme.t.accent } }
            Column { anchors.verticalCenter: parent.verticalCenter
                Label { text: win.now; font.pixelSize: 64; font.weight: Font.Light } Label { text: win.today; secondary: true; font.pixelSize: 15 } } }
        Grid { columns: 2; spacing: 12; width: parent.width
            Repeater { model: win.cities
                Card { required property var modelData; width: (parent.width - 12) / 2; height: 68
                    Rectangle { x: 14; anchors.verticalCenter: parent.verticalCenter; width: 10; height: 10; radius: 5; color: modelData.night ? Theme.t.glowB : Theme.t.caution || "#FFB340" }
                    Label { x: 36; y: 14; text: modelData.city; font.weight: Font.DemiBold } Label { x: 36; y: 36; text: modelData.note; secondary: true; font.pixelSize: 11 }
                    Label { anchors { right: parent.right; rightMargin: 16; verticalCenter: parent.verticalCenter } text: modelData.time; font.pixelSize: 26; font.weight: Font.Light } } } } }
    Column { visible: win.page === "Stopwatch"; anchors.horizontalCenter: parent.horizontalCenter; y: 40; width: Math.min(parent.width - 56, 420); spacing: 22
        Big { text: win.fmt(win.elapsed, true) }
        Row { anchors.horizontalCenter: parent.horizontalCenter; spacing: 10
            Btn { width: 110; height: 36; text: win.running ? "Lap" : "Reset"; onClicked: { if (win.running) { var l = win.laps.slice(); l.unshift(win.elapsed); win.laps = l } else { win.elapsed = 0; win.laps = [] } } }
            Btn { width: 110; height: 36; primary: !win.running; danger: win.running; text: win.running ? "Stop" : "Start"; onClicked: { if (!win.running) win.since = Date.now() - win.elapsed; win.running = !win.running } } }
        Column { width: parent.width
            Repeater { model: win.laps
                Item { required property real modelData; required property int index; width: parent.width; height: 34
                    Rectangle { width: parent.width; height: 1; color: Theme.t.separator }
                    Label { anchors.verticalCenter: parent.verticalCenter; text: "Lap " + (win.laps.length - index); secondary: true } Label { anchors { right: parent.right; verticalCenter: parent.verticalCenter } text: win.fmt(modelData, true); font.family: Theme.t.fontMono } } } } }
    Column { visible: win.page === "Timer"; anchors.horizontalCenter: parent.horizontalCenter; y: 40; width: Math.min(parent.width - 56, 420); spacing: 22
        Big { text: win.counting || win.left > 0 ? win.fmt(win.left, false) : win.fmt(win.setMinutes * 60000, false); color: win.rang ? Theme.t.danger : Theme.t.text }
        Label { visible: win.rang; text: "Time's up"; color: Theme.t.danger; font.weight: Font.DemiBold; anchors.horizontalCenter: parent.horizontalCenter }
        Row { visible: !win.counting && win.left <= 0; anchors.horizontalCenter: parent.horizontalCenter; spacing: 8
            Repeater { model: [1, 5, 10, 15, 30, 60]; Btn { required property int modelData; pill: true; primary: win.setMinutes === modelData; text: modelData + " min"; onClicked: { win.setMinutes = modelData; win.rang = false } } } }
        Row { anchors.horizontalCenter: parent.horizontalCenter; spacing: 10
            Btn { width: 110; height: 36; text: "Cancel"; visible: win.counting || win.left > 0; onClicked: { win.counting = false; win.left = 0; win.rang = false } }
            Btn { width: 110; height: 36; primary: !win.counting; text: win.counting ? "Pause" : (win.left > 0 ? "Resume" : "Start")
                onClicked: { win.rang = false; if (win.counting) { win.counting = false } else if (win.left > 0) { win.until = Date.now() + win.left; win.counting = true } else win.startTimer(win.setMinutes * 60000) } } }
        Label { width: parent.width; horizontalAlignment: Text.AlignHCenter; wrapMode: Text.WordWrap; secondary: true; font.pixelSize: 12; text: "The timer runs while Clock is open, and shows in the dock's live island. Sound and alarms that work with Clock closed come later." } }
}
