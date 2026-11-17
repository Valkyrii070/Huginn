import QtQuick
import QtQuick.Shapes

// The Welcome tour. First two full-screen pages over the scene you signed in to (Welcome; Make it yours: a realm
// and light or dark, picked live). Then the desktop comes in and the tour's island grows out of Continue and walks
// you round: it glides beside each part, and a line of light runs from it to that part and round it, once. Each step
// has one thing to try (never needed: Next always works); do it and the step ticks and moves on by itself.
// After a big update the same island shows only what's new (kind "whatsnew": Tour.whatsNew).
// The host gives `target(name)` (a rect on the screen: "dock", "date", "name", "window", "orb", "centre") and the
// state the checks watch (todayOpen, menuOpen, windowCount, snapped).
Item {
    id: tour
    property bool running: false
    property string kind: "first"                     // "first" or "whatsnew"
    property var target: function (name) { return Qt.rect(width / 2 - 40, height / 2 - 40, 80, 80) }
    property string appName: "Huginn"
    property bool todayOpen: false
    property bool menuOpen: false
    property int windowCount: 0
    property bool snapped: false
    property bool live: Tour.live
    signal finished()
    signal closeOpenThings()                         // what a try opened (Today, a menu) closes as the tour moves on
    signal installWanted()
    signal maskChanged(var rect)                      // where the tour takes clicks (empty: the whole screen)
    readonly property bool motion: Theme.t.openMs > 0
    component Btn: Rectangle {
        id: b
        property string text: ""
        property bool primary: false
        signal clicked()
        width: bl.width + 26; height: 30; radius: 11
        color: primary ? Theme.t.accent : Qt.rgba(1, 1, 1, Theme.t.dark ? 0.1 : 0.5)
        scale: bh.pressed ? Theme.t.pressScale : 1
        Label { id: bl; anchors.centerIn: parent; text: b.text; font.pixelSize: 13; font.weight: Font.DemiBold; color: b.primary ? (Theme.t.dark ? "#0B1512" : "white") : Theme.t.text }
        MouseArea { id: bh; anchors.fill: parent; onClicked: b.clicked() }
    }

    property string phase: "pages"                    // "pages", then "island"
    property int page: 0
    property int step: 0
    property bool done: false                         // this step's try was done
    readonly property var steps: kind === "whatsnew" ? Tour.whatsNew : [
        { target: "dock", title: "The dock", words: "Your apps, with stacks like Downloads at the end. Click an app to open it; click the one in front to hide it.",
          "try": "open an app", done: "It's open", check: "window" },
        { target: "date", title: "The top bar", words: "The date opens Today: your month, the weather and what's coming. The icons on the right open the Control Centre, where notifications wait.",
          "try": "click the date", done: "That's Today", check: "today" },
        { target: "name", title: "The app's own menu", words: "Click the name of the app in front for its own menu: its settings at the top, then every command, which you can search. Every app's works the same way.",
          "try": "click " + tour.appName, done: "That's " + tour.appName + "'s menu", check: "menu" },
        { target: "window", title: "Windows and spaces", words: "Drag a window to an edge to snap it. Super+Tab, or three fingers up, shows every window and your spaces.",
          "try": "drag a window to the left", done: "Snapped", check: "snap" },
        { target: "orb", title: "You're ready", words: "Super opens the start menu; Super+Space searches everything. More apps are in the Store, and the tour again in Help.",
          "try": "", done: "", check: "", last: true }
    ]
    readonly property var cur: steps.length ? steps[Math.min(step, steps.length - 1)] : ({})
    readonly property bool lastStep: step >= steps.length - 1

    function start(k) {
        kind = k || "first"; step = 0; done = false
        phase = kind === "first" ? "pages" : "island"; page = 0
        running = true
        if (phase === "island") enterIsland(Qt.point(width / 2, height / 2))
        else maskChanged(Qt.rect(0, 0, 0, 0))
    }
    function finish() {
        Tour.finished(kind)
        closeOpenThings()
        running = false; phase = "pages"
        maskChanged(Qt.rect(0, 0, 0, 0))
        finished()
    }
    function next() { if (lastStep) finish(); else { closeOpenThings(); step++; done = false; place() } }
    function back() { if (step > 0) { closeOpenThings(); step--; done = false; place() } }

    // ---------------------------------------------------------------- where the island goes, and the line of light
    readonly property int iw: 340
    readonly property int ih: 214
    property rect aim: Qt.rect(0, 0, 0, 0)            // the part the island is about
    property string nub: "down"
    function spot() {
        var r = target(cur.target || "centre"), x, y, n
        if (!r || r.width <= 0) r = Qt.rect(width / 2 - 1, height / 2 - 1, 2, 2)
        if (cur.target === "dock" || cur.target === "orb" && !cur.last) { x = r.x + r.width / 2 - iw / 2; y = r.y - 22 - ih; n = "down" }
        else if (cur.target === "date") { x = Math.max(12, r.x - 10); y = r.y + r.height + 18; n = "up" }
        else if (cur.target === "name") { x = Math.min(width - iw - 16, r.x + 640); y = 120; n = "left" }
        else if (cur.target === "window") { x = r.x + r.width / 2 - iw / 2; y = Math.min(height - ih - 110, r.y + r.height - ih - 40); n = "up" }
        else { x = width / 2 - iw / 2; y = height / 2 - ih / 2 - 40; n = "down" }   // the last step: the line goes to the start button
        return { x: Math.max(12, Math.min(width - iw - 12, x)), y: Math.max(40, Math.min(height - ih - 12, y)), nub: n, aim: r }
    }
    function place() {
        var s = spot()
        aim = s.aim; nub = s.nub
        line.reset()
        if (motion) { glideX.to = s.x; glideY.to = s.y; glide.restart() }
        else { fadeMove.x = s.x; fadeMove.y = s.y; fadeMove.restart() }
    }
    function enterIsland(from) {
        phase = "island"
        var s = spot()
        aim = s.aim; nub = s.nub
        island.x = from.x - iw / 2; island.y = from.y - ih / 2
        grow.restart()
        afterGrow.x = s.x; afterGrow.y = s.y
    }
    function arrived() {
        maskChanged(Qt.rect(island.x - 4, island.y - 10, iw + 8, ih + 20))
        if (motion && cur.target) line.run()
    }
    // a rounded rectangle traced clockwise, from a point on one of its edges
    function outline(r, rad, side, at) {
        var x = r.x, y = r.y, w = r.width, h = r.height, R = Math.min(rad, w / 2, h / 2)
        var tr = "L " + (x + w - R) + " " + y + " A " + R + " " + R + " 0 0 1 " + (x + w) + " " + (y + R)
        var rt = "L " + (x + w) + " " + (y + h - R) + " A " + R + " " + R + " 0 0 1 " + (x + w - R) + " " + (y + h)
        var bt = "L " + (x + R) + " " + (y + h) + " A " + R + " " + R + " 0 0 1 " + x + " " + (y + h - R)
        var lf = "L " + x + " " + (y + R) + " A " + R + " " + R + " 0 0 1 " + (x + R) + " " + y
        if (side === "top") return tr + " " + rt + " " + bt + " " + lf + " L " + at + " " + y
        return bt + " " + lf + " " + tr + " " + rt + " " + " L " + at + " " + (y + h)
    }
    readonly property var lead: {
        var r = aim, ix = island.x, iy = island.y, p = "", len = 0
        if (!running || phase !== "island" || r.width <= 0) return { path: "M 0 0", len: 1 }
        var pad = 5, o = Qt.rect(r.x - pad, r.y - pad, r.width + 2 * pad, r.height + 2 * pad)
        var per = 2 * (o.width + o.height)
        if (nub === "down") {           // from under the island down (or round) to the part's top edge
            var sx = ix + iw / 2, sy = iy + ih + 7, tx = Math.max(o.x + 14, Math.min(o.x + o.width - 14, sx))
            p = "M " + sx + " " + sy + " C " + sx + " " + (sy + 60) + " " + tx + " " + (o.y - 60) + " " + tx + " " + o.y + " " + outline(o, 18, "top", tx)
            len = Math.abs(o.y - sy) + Math.abs(tx - sx) * 0.9 + per
        } else if (nub === "up") {      // from above the island up to the part's bottom edge
            var ux = ix + 59, uy = iy - 7, bx = Math.max(o.x + 10, Math.min(o.x + o.width - 10, ux))
            p = "M " + ux + " " + uy + " C " + ux + " " + (uy - 30) + " " + bx + " " + (o.y + o.height + 30) + " " + bx + " " + (o.y + o.height) + " " + outline(o, 9, "bottom", bx)
            len = Math.abs(uy - o.y - o.height) + Math.abs(bx - ux) + per
        } else {                        // from the island's left, curving up to the part's bottom edge
            var lx = ix - 7, ly = iy + 29, cx = o.x + o.width / 2
            p = "M " + lx + " " + ly + " C " + (lx - 240) + " " + ly + " " + cx + " " + (ly - 40) + " " + cx + " " + (o.y + o.height) + " " + outline(o, 8, "bottom", cx)
            len = Math.abs(lx - cx) + Math.abs(ly - o.y - o.height) + per
        }
        return { path: p, len: len }
    }

    // ---------------------------------------------------------------- the try-it checks
    property int windowsAtStep: 0
    onStepChanged: windowsAtStep = windowCount
    onTodayOpenChanged: if (todayOpen && running && phase === "island" && cur.check === "today") tick()
    onMenuOpenChanged: if (menuOpen && running && phase === "island" && cur.check === "menu") tick()
    onWindowCountChanged: if (running && phase === "island" && cur.check === "window" && windowCount > windowsAtStep) tick()
    onSnappedChanged: if (snapped && running && phase === "island" && cur.check === "snap") tick()
    function tick() { if (done) return; done = true; moveOn.restart() }
    Timer { id: moveOn; interval: tour.cur.check === "today" || tour.cur.check === "menu" ? 2400 : 1500; onTriggered: if (tour.done && tour.running) tour.next() }

    visible: running
    Keys.onPressed: function (e) {
        if (!running) return
        if (e.key === Qt.Key_Escape) { finish(); e.accepted = true }
        else if (phase === "pages" && (e.key === Qt.Key_Return || e.key === Qt.Key_Enter || e.key === Qt.Key_Right)) { pageNext(); e.accepted = true }
        else if (phase === "island" && (e.key === Qt.Key_Return || e.key === Qt.Key_Enter || e.key === Qt.Key_Right)) { next(); e.accepted = true }
        else if (phase === "island" && e.key === Qt.Key_Left) { back(); e.accepted = true }
    }
    function pageNext() { if (page === 0) page = 1; else { leavePages.restart() } }

    // ---------------------------------------------------------------- the two full-screen pages (C)
    Rectangle {
        id: scrim
        anchors.fill: parent
        visible: opacity > 0
        opacity: tour.running && tour.phase === "pages" ? 1 : 0
        Behavior on opacity { NumberAnimation { duration: tour.motion ? 500 : 150; easing.type: Easing.OutCubic } }
        gradient: Gradient {
            GradientStop { position: 0; color: Qt.rgba(Qt.color(Theme.t.glowB).r * 0.12, Qt.color(Theme.t.glowB).g * 0.12, Qt.color(Theme.t.glowB).b * 0.15, 0.97) }
            GradientStop { position: 0.6; color: Qt.rgba(0.03, 0.04, 0.05, 0.97) }
            GradientStop { position: 1; color: Qt.rgba(Qt.color(Theme.t.glowA).r * 0.22, Qt.color(Theme.t.glowA).g * 0.22, Qt.color(Theme.t.glowA).b * 0.22, 0.97) }
        }
        MouseArea { anchors.fill: parent }
        Column {   // 1 · Welcome
            id: page1
            anchors.horizontalCenter: parent.horizontalCenter; y: parent.height * 0.3
            spacing: 0; opacity: tour.page === 0 ? 1 : 0; visible: opacity > 0
            transform: Translate { x: tour.page === 0 ? 0 : -50; Behavior on x { NumberAnimation { duration: 300; easing.type: Easing.OutCubic } } }
            Behavior on opacity { NumberAnimation { duration: 260 } }
            Label { anchors.horizontalCenter: parent.horizontalCenter; text: ("Hello" + (Me.name ? ", " + Me.name.split(" ")[0] : "")).toUpperCase(); secondary: true; font.pixelSize: 13; font.letterSpacing: 1.2; height: 30 }
            Label { anchors.horizontalCenter: parent.horizontalCenter; text: "Welcome to Huginn OS"; font.pixelSize: 46; font.weight: Font.Light; color: "#F5F7FA"; height: 66 }
            Label { anchors.horizontalCenter: parent.horizontalCenter; text: "Let's make it yours, then take a quick look around. About a minute."; font.pixelSize: 16; color: "#B9C2CC"; height: 96 }
            Rectangle {
                anchors.horizontalCenter: parent.horizontalCenter; width: gs.width + 44; height: 42; radius: 14; color: Theme.t.accent
                scale: gsHit.pressed ? Theme.t.pressScale : 1
                Label { id: gs; anchors.centerIn: parent; text: "Get started"; color: Theme.t.dark ? "#0B1512" : "white"; font.pixelSize: 15; font.weight: Font.DemiBold }
                MouseArea { id: gsHit; anchors.fill: parent; onClicked: tour.page = 1 }
            }
            Item { width: 1; height: 16 }
            Label { anchors.horizontalCenter: parent.horizontalCenter; text: "Skip the tour"; color: "#B9C2CC"; font.pixelSize: 13
                MouseArea { anchors.fill: parent; anchors.margins: -6; onClicked: tour.finish() } }
        }
        Column {   // 2 · Make it yours
            id: page2
            anchors.horizontalCenter: parent.horizontalCenter; y: parent.height * 0.28
            spacing: 0; opacity: tour.page === 1 ? 1 : 0; visible: opacity > 0
            transform: Translate { x: tour.page === 1 ? 0 : 50; Behavior on x { NumberAnimation { duration: 300; easing.type: Easing.OutCubic } } }
            Behavior on opacity { NumberAnimation { duration: 260 } }
            Label { anchors.horizontalCenter: parent.horizontalCenter; text: "Make it yours"; font.pixelSize: 46; font.weight: Font.Light; color: "#F5F7FA"; height: 66 }
            Label { anchors.horizontalCenter: parent.horizontalCenter; text: "Pick a realm, and light or dark. Both are in Settings › Appearance later."; font.pixelSize: 16; color: "#B9C2CC"; height: 56 }
            Row {
                anchors.horizontalCenter: parent.horizontalCenter; spacing: 28; height: 104
                Repeater {
                    model: Theme.t.realms
                    Column {
                        required property var modelData
                        spacing: 8
                        Rectangle {
                            anchors.horizontalCenter: parent.horizontalCenter; width: 52; height: 52; radius: 26
                            gradient: Gradient { GradientStop { position: 0; color: modelData.a } GradientStop { position: 1; color: modelData.b } }
                            border.width: Theme.t.realm === modelData.id ? 3 : 0; border.color: "white"
                            scale: rh.pressed ? 0.92 : rh.containsMouse ? 1.06 : 1
                            Behavior on scale { NumberAnimation { duration: 120 } }
                            MouseArea { id: rh; anchors.fill: parent; hoverEnabled: true; onClicked: Theme.setRealm(modelData.id) }
                        }
                        Label { anchors.horizontalCenter: parent.horizontalCenter; text: modelData.label; font.pixelSize: 13; color: Theme.t.realm === modelData.id ? "#F5F7FA" : "#B9C2CC" }
                    }
                }
            }
            Rectangle {
                anchors.horizontalCenter: parent.horizontalCenter; width: 168; height: 34; radius: 11; color: Qt.rgba(1, 1, 1, 0.08)
                Row {
                    anchors.centerIn: parent; spacing: 2
                    Repeater {
                        model: [["Light", false], ["Dark", true]]
                        Rectangle {
                            required property var modelData
                            width: 80; height: 28; radius: 9; color: Theme.t.dark === modelData[1] ? Qt.rgba(1, 1, 1, 0.18) : "transparent"
                            Label { anchors.centerIn: parent; text: modelData[0]; color: "#F5F7FA"; font.pixelSize: 13; font.weight: Theme.t.dark === modelData[1] ? Font.DemiBold : Font.Normal }
                            MouseArea { anchors.fill: parent; onClicked: Theme.setDark(modelData[1]) }
                        }
                    }
                }
            }
            Item { width: 1; height: 26 }
            Rectangle {
                id: cont
                anchors.horizontalCenter: parent.horizontalCenter; width: cl.width + 44; height: 42; radius: 14; color: Theme.t.accent
                scale: clHit.pressed ? Theme.t.pressScale : 1
                Label { id: cl; anchors.centerIn: parent; text: "Continue"; color: Theme.t.dark ? "#0B1512" : "white"; font.pixelSize: 15; font.weight: Font.DemiBold }
                MouseArea { id: clHit; anchors.fill: parent; onClicked: leavePages.restart() }
            }
        }
        Row {   // which page
            anchors { horizontalCenter: parent.horizontalCenter; bottom: parent.bottom; bottomMargin: 70 }
            spacing: 6
            Repeater { model: 2; Rectangle { required property int index; width: index === tour.page ? 20 : 7; height: 7; radius: 4; color: index === tour.page ? Theme.t.accent : Qt.rgba(1, 1, 1, 0.22)
                Behavior on width { NumberAnimation { duration: 150 } } } }
        }
    }
    // Continue: the pages leave, the desktop comes in, and the island grows out of the button
    SequentialAnimation {
        id: leavePages
        ScriptAction { script: { var p = cont.mapToItem(tour, cont.width / 2, cont.height / 2); tour.enterIsland(p) } }
    }

    // ---------------------------------------------------------------- the island (B)
    Item {
        id: island
        visible: tour.running && tour.phase === "island"
        width: tour.iw; height: tour.ih
        transformOrigin: Item.Center
        Rectangle {   // the nub, pointing at the part
            width: 14; height: 14; rotation: 45; color: Qt.rgba(0.135, 0.15, 0.17, 0.97); border.width: 1; border.color: Qt.rgba(1, 1, 1, 0.1)
            x: tour.nub === "left" ? -7 : tour.nub === "up" ? 52 : island.width / 2 - 7
            y: tour.nub === "left" ? 22 : tour.nub === "up" ? -7 : island.height - 7
            opacity: glide.running ? 0 : 1
            Behavior on opacity { NumberAnimation { duration: 150 } }
        }
        Glass {
            anchors.fill: parent; popup: true; dense: true; radius: 22
            Column {
                x: 16; y: 14; width: parent.width - 32; spacing: 8
                Item {
                    width: parent.width; height: 16
                    Label { id: count; anchors.verticalCenter: parent.verticalCenter; text: (tour.kind === "whatsnew" ? "What's new · " : "") + (tour.step + 1) + " of " + tour.steps.length; secondary: true; font.pixelSize: 11; font.weight: Font.DemiBold }
                    Rectangle {   // how far along: a line of light
                        anchors { left: count.right; leftMargin: 10; right: skip.left; rightMargin: 10; verticalCenter: parent.verticalCenter }
                        height: 3; radius: 2; color: Qt.rgba(1, 1, 1, 0.12)
                        Rectangle { width: parent.width * (tour.step + 1) / Math.max(1, tour.steps.length); height: 3; radius: 2
                            Behavior on width { NumberAnimation { duration: 300; easing.type: Easing.OutCubic } }
                            gradient: Gradient { orientation: Gradient.Horizontal; GradientStop { position: 0; color: Theme.t.glowA } GradientStop { position: 1; color: Theme.t.glowB } } }
                    }
                    Label { id: skip; visible: !tour.lastStep; anchors { right: parent.right; verticalCenter: parent.verticalCenter } text: "Skip"; secondary: true; font.pixelSize: 12
                        MouseArea { anchors.fill: parent; anchors.margins: -6; onClicked: tour.finish() } }
                }
                Label { text: tour.cur.title || ""; font.pixelSize: 17; font.weight: Font.DemiBold }
                Label { width: parent.width; text: tour.cur.words || ""; wrapMode: Text.WordWrap; secondary: true; font.pixelSize: 13; lineHeight: 1.15 }
                Rectangle {   // the thing to try, or that it's done
                    visible: !!tour.cur["try"]
                    width: tryRow.width + 20; height: 28; radius: 10
                    color: tour.done ? Qt.alpha(Theme.t.accent, 0.16) : Qt.rgba(1, 1, 1, 0.06)
                    border.width: 1; border.color: tour.done ? Qt.alpha(Theme.t.accent, 0.55) : Qt.rgba(1, 1, 1, 0.14)
                    Row {
                        id: tryRow; anchors.centerIn: parent; spacing: 7
                        Label { visible: tour.done; text: "✓"; color: Theme.t.accent; font.pixelSize: 13; font.weight: Font.Bold; anchors.verticalCenter: parent.verticalCenter }
                        Rectangle { visible: !tour.done; width: 6; height: 6; radius: 3; color: Theme.t.accent; anchors.verticalCenter: parent.verticalCenter }
                        Label { text: tour.done ? tour.cur.done : "Try it: " + tour.cur["try"]; font.pixelSize: 12; font.weight: tour.done ? Font.DemiBold : Font.Normal; anchors.verticalCenter: parent.verticalCenter }
                    }
                }
            }
            Row {
                anchors { right: parent.right; bottom: parent.bottom; margins: 14 }
                spacing: 6
                Btn { visible: tour.step > 0 && !(tour.lastStep && tour.live); text: "Back"; onClicked: tour.back() }
                Btn { visible: tour.lastStep && tour.live; text: "Keep trying"; onClicked: tour.finish() }
                Btn { visible: tour.lastStep && tour.live; text: "Install Huginn OS"; primary: true; onClicked: { tour.finish(); tour.installWanted() } }
                Btn { visible: !(tour.lastStep && tour.live); text: tour.lastStep ? "Done" : "Next"; primary: true; onClicked: tour.next() }
            }
        }
        // growing out of Continue
        ParallelAnimation {
            id: grow
            NumberAnimation { target: island; property: "scale"; from: 0.25; to: 1; duration: tour.motion ? 380 : 0; easing.type: Easing.OutBack; easing.overshoot: 1.05 }
            NumberAnimation { target: island; property: "opacity"; from: 0; to: 1; duration: tour.motion ? 260 : 150 }
            onFinished: { glideX.to = afterGrow.x; glideY.to = afterGrow.y; glide.restart() }
        }
        QtObject { id: afterGrow; property real x: 0; property real y: 0 }
        ParallelAnimation {
            id: glide
            NumberAnimation { id: glideX; target: island; property: "x"; duration: tour.motion ? 440 : 0; easing.type: Easing.InOutCubic }
            NumberAnimation { id: glideY; target: island; property: "y"; duration: tour.motion ? 440 : 0; easing.type: Easing.InOutCubic }
            onFinished: tour.arrived()
        }
        SequentialAnimation {   // Reduce Motion: fade out here, in there
            id: fadeMove
            property real x: 0
            property real y: 0
            NumberAnimation { target: island; property: "opacity"; to: 0; duration: 100 }
            ScriptAction { script: { island.x = fadeMove.x; island.y = fadeMove.y } }
            NumberAnimation { target: island; property: "opacity"; to: 1; duration: 140 }
            ScriptAction { script: tour.arrived() }
        }
    }

    // ---------------------------------------------------------------- the line of light
    Shape {
        id: line
        anchors.fill: parent
        visible: tour.running && tour.phase === "island" && opacity > 0
        opacity: 0
        preferredRendererType: Shape.CurveRenderer
        property real drawn: 0
        function reset() { lineAnim.stop(); opacity = 0; drawn = 0 }
        function run() { lineAnim.restart() }
        ShapePath {
            strokeColor: Theme.t.glowA; strokeWidth: 2.4; fillColor: "transparent"; capStyle: ShapePath.RoundCap; joinStyle: ShapePath.RoundJoin
            strokeStyle: ShapePath.DashLine
            dashPattern: [Math.max(0.01, line.drawn / 2.4), (tour.lead.len + 40) / 2.4]
            PathSvg { path: tour.lead.path }
        }
        SequentialAnimation {
            id: lineAnim
            ScriptAction { script: { line.drawn = 0; line.opacity = 1 } }
            NumberAnimation { target: line; property: "drawn"; to: tour.lead.len + 10; duration: 900; easing.type: Easing.InOutQuad }
            PauseAnimation { duration: 350 }
            NumberAnimation { target: line; property: "opacity"; to: 0; duration: 450 }
        }
    }
    Shape {   // its glow, under it
        anchors.fill: parent; z: -1
        visible: line.visible; opacity: line.opacity * 0.35
        preferredRendererType: Shape.CurveRenderer
        ShapePath {
            strokeColor: Theme.t.glowB; strokeWidth: 7; fillColor: "transparent"; capStyle: ShapePath.RoundCap
            strokeStyle: ShapePath.DashLine
            dashPattern: [Math.max(0.01, line.drawn / 7), (tour.lead.len + 40) / 7]
            PathSvg { path: tour.lead.path }
        }
    }
}
