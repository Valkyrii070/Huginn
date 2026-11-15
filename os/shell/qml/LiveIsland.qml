import QtQuick
import "live.js" as L

// The live island, at the right end of the dock: one island as wide as what it shows, and beside it, round bubbles for
// up to two more things going on (and for the screen, the camera and the microphone whenever they're on). It isn't there
// when nothing is going on. What it hears about, and the rules for what gets the island: shell/huginn_island.py.
// Point at it and the host opens it (LivePanel) after a moment; click it to go to the app; right-click for the app's
// island; scroll over it and the next thing takes it; click a bubble and that one does.
Row {
    id: isl
    spacing: 12
    signal hovered(bool inside)             // the pointer is on the island or a bubble (the host opens it after a moment)
    signal focusWanted(string id)           // a screen/camera/mic bubble was clicked: open the island on it
    signal openWanted(string app)           // the island was clicked: bring that app forward (or start it)
    signal islandWanted(string app, real x) // right-click: the app's own island, centred on x (in this item)
    readonly property var main: Live.main
    readonly property real pillRight: pill.x + pill.width
    readonly property real pillCentre: pill.x + pill.width / 2
    readonly property bool anyHover: pillArea.containsMouse || hoverCount > 0
    property int hoverCount: 0
    onAnyHoverChanged: hovered(anyHover)
    property real now: Date.now()
    Timer { interval: 250; repeat: true; running: Live.active; onTriggered: isl.now = Date.now() }
    visible: Live.active || pill.width > 0.5 || bubbleList.width > 0.5

    // ---- the island: two faces, so the old one fades out as the new one comes in, while the island changes size
    property var faceA: ({})
    property var faceB: ({})
    property bool onA: true
    onMainChanged: {
        var cur = onA ? faceA : faceB
        if (main && cur && main.id && cur.id === main.id) { if (onA) faceA = main; else faceB = main; return }   // the same thing, news about it
        if (onA) faceB = main; else faceA = main
        onA = !onA
    }
    Glass {
        id: pill
        height: 64; radius: 22
        readonly property Item face: isl.onA ? fa : fb
        width: isl.main && isl.main.id ? face.want : 0
        visible: width > 0.5
        clip: true
        Behavior on width { NumberAnimation { duration: Theme.t.moveMs; easing.type: Easing.OutBack; easing.overshoot: 0.9 } }
        Rectangle {   // the colour of what it shows, faintly, from the left
            anchors.fill: parent; radius: parent.radius; opacity: 0.16
            gradient: Gradient { orientation: Gradient.Horizontal
                GradientStop { position: 0; color: isl.main && isl.main.tone ? isl.main.tone : "transparent" } GradientStop { position: 0.7; color: "transparent" } } }
        MouseArea {
            id: pillArea
            anchors.fill: parent; hoverEnabled: true; acceptedButtons: Qt.LeftButton | Qt.RightButton
            property real wheel: 0
            onClicked: function (m) {
                if (!isl.main || !isl.main.id) return
                if (m.button === Qt.RightButton) { isl.islandWanted(isl.main.app || "", pill.x + pill.width / 2); return }
                var app = Live.openApp(isl.main.id)
                if (app) isl.openWanted(app)
            }
            onWheel: function (w) {
                wheel += w.angleDelta.y + w.angleDelta.x
                if (Math.abs(wheel) >= 120) { Live.cycle(wheel < 0 ? 1 : -1); wheel = 0 }
            }
            Face { id: fa; it: isl.faceA; opacity: isl.onA ? 1 : 0; Behavior on opacity { NumberAnimation { duration: Theme.t.openMs } } }
            Face { id: fb; it: isl.faceB; opacity: isl.onA ? 0 : 1; Behavior on opacity { NumberAnimation { duration: Theme.t.openMs } } }
        }
    }

    // ---- the bubbles: a list that keeps its order, so they slide and pop instead of jumping
    readonly property var bubbleData: { var m = {}; var b = Live.bubbles; for (var i = 0; i < b.length; i++) m[b[i].id] = b[i]; return m }
    readonly property string lastRest: { var b = Live.bubbles, id = ""; for (var i = 0; i < b.length; i++) if (!L.privacy(b[i])) id = b[i].id; return id }
    ListModel { id: bubbleModel }
    function syncBubbles() {
        var want = Live.bubbles.map(function (b) { return b.id })
        for (var i = bubbleModel.count - 1; i >= 0; i--) if (want.indexOf(bubbleModel.get(i).bid) < 0) bubbleModel.remove(i)
        for (var j = 0; j < want.length; j++) {
            var at = -1
            for (var k = j; k < bubbleModel.count; k++) if (bubbleModel.get(k).bid === want[j]) { at = k; break }
            if (at < 0) bubbleModel.insert(j, { bid: want[j] })
            else if (at !== j) bubbleModel.move(at, j, 1)
        }
    }
    Connections { target: Live; function onChanged() { isl.syncBubbles() } }
    Component.onCompleted: syncBubbles()
    ListView {
        id: bubbleList
        orientation: ListView.Horizontal; interactive: false; spacing: 12
        height: 64; width: count > 0 ? count * 64 + (count - 1) * 12 : 0
        visible: width > 0.5
        Behavior on width { NumberAnimation { duration: Theme.t.moveMs; easing.type: Easing.OutCubic } }
        model: bubbleModel
        add: Transition { ParallelAnimation {
            NumberAnimation { property: "scale"; from: 0.3; to: 1; duration: Theme.t.moveMs; easing.type: Easing.OutBack }
            NumberAnimation { property: "opacity"; from: 0; to: 1; duration: Theme.t.openMs } } }
        remove: Transition { ParallelAnimation {
            NumberAnimation { property: "scale"; to: 0.3; duration: Theme.t.closeMs; easing.type: Easing.InBack }
            NumberAnimation { property: "opacity"; to: 0; duration: Theme.t.closeMs } } }
        displaced: Transition { NumberAnimation { properties: "x"; duration: Theme.t.moveMs; easing.type: Easing.OutCubic } }
        delegate: Bubble {}
    }

    // ---- the pieces
    component Face: Row {
        id: face
        property var it: ({})
        readonly property string kind: L.kindOf(it)
        readonly property bool priv: L.privacy(it)
        readonly property real want: kind ? width + 26 : 0
        x: 12; height: 64; spacing: 12
        LiveLead { it: face.it; now: isl.now; anchors.verticalCenter: parent.verticalCenter }
        Column {
            anchors.verticalCenter: parent.verticalCenter; spacing: face.kind === "progress" ? 5 : 1
            width: face.priv ? Math.min(250, Math.max(150, t1.implicitWidth)) : 150
            Label { id: t1; width: parent.width; text: face.it.title || ""; elide: Text.ElideRight; font.pixelSize: 14; font.weight: Font.DemiBold }
            LiveBar { visible: face.kind === "progress"; width: parent.width; value: face.it.progress === undefined ? -1 : face.it.progress; tone: face.it.tone || Theme.t.accent }
            Label { width: parent.width; text: L.sub(face.it, isl.now); elide: Text.ElideRight; font.pixelSize: 12; secondary: true }
        }
        LiveEq { visible: face.kind === "playing"; playing: !!face.it.playing; tone: face.it.tone || Theme.t.accent; anchors.verticalCenter: parent.verticalCenter }
        Repeater {
            model: L.quick(face.it)
            RoundButton { required property var modelData; a: modelData; target: face.it; anchors.verticalCenter: parent ? parent.verticalCenter : undefined }
        }
    }

    component RoundButton: Rectangle {
        id: rb
        property var a: ({})
        property var target: ({})
        readonly property string tone: L.tone(a)
        readonly property bool worded: tone === "go" && !!a.label
        width: worded ? jl.width + 28 : 36; height: 36; radius: 18
        color: tone === "go" ? (target.tone || "#3DDC84") : tone === "danger" ? "#FF5A5F" : (hit.containsMouse ? Theme.t.pressed : Theme.t.hover)
        scale: hit.pressed ? Theme.t.pressScale : 1
        Behavior on scale { NumberAnimation { duration: 100 } }
        Glyph { visible: !rb.worded; anchors.centerIn: parent; name: rb.a.glyph || "check"; size: 16; ink: rb.tone ? "white" : Theme.t.text }
        Label { id: jl; visible: rb.worded; anchors.centerIn: parent; text: rb.a.label || ""; color: "#14080A"; font.weight: Font.DemiBold }
        MouseArea { id: hit; anchors.fill: parent; hoverEnabled: true; onClicked: Live.act(rb.target.id, rb.a.id) }
    }

    component Bubble: Item {
        id: bub
        required property string bid
        required property int index
        readonly property var it: isl.bubbleData[bid] || ({})
        readonly property string kind: L.kindOf(it)
        readonly property bool ringed: kind === "timer" || kind === "progress" || kind === "event"
        width: 64; height: 64
        Glass { anchors.fill: parent; radius: 32 }
        LiveLead { visible: !bub.ringed; anchors.centerIn: parent; it: bub.it; now: isl.now; size: bub.kind === "playing" ? 44 : 44; round: true }
        LiveRing {
            visible: bub.ringed; anchors.centerIn: parent; width: 46; height: 46; tone: bub.it.tone || Theme.t.accent
            value: bub.kind === "timer" ? (bub.it.total ? Math.max(0, L.left(bub.it, isl.now)) / bub.it.total : 0)
                 : bub.kind === "event" ? 1 : (bub.it.progress >= 0 ? bub.it.progress : 0.25)
            text: bub.kind === "timer" ? L.clock(L.left(bub.it, isl.now)) : ""
            glyph: bub.kind === "timer" ? "" : (bub.it.glyph || "download")
            RotationAnimation on rotation { running: bub.kind === "progress" && !(bub.it.progress >= 0) && Theme.t.moveMs > 0; loops: Animation.Infinite; from: 0; to: 360; duration: 1600 }
        }
        Rectangle {   // more going on than there are bubbles: how many more
            visible: Live.extra > 0 && bub.bid === isl.lastRest
            anchors { right: parent.right; top: parent.top; rightMargin: -2; topMargin: -2 }
            height: 18; width: Math.max(18, more.width + 10); radius: 9; color: Theme.t.accent
            Label { id: more; anchors.centerIn: parent; text: "+" + Live.extra; font.pixelSize: 10; font.weight: Font.Bold; color: Theme.t.onAccent }
        }
        MouseArea {
            anchors.fill: parent; hoverEnabled: true; acceptedButtons: Qt.LeftButton | Qt.RightButton
            onContainsMouseChanged: isl.hoverCount = Math.max(0, isl.hoverCount + (containsMouse ? 1 : -1))
            Component.onDestruction: if (containsMouse) isl.hoverCount = Math.max(0, isl.hoverCount - 1)
            onClicked: function (m) {
                if (m.button === Qt.RightButton) { isl.islandWanted(bub.it.app || "", bubbleList.x + bub.x + 32); return }
                if (L.privacy(bub.it)) isl.focusWanted(bub.bid); else Live.pick(bub.bid)
            }
        }
    }
}
