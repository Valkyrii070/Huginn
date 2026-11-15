import QtQuick
import "live.js" as L

// The live island, opened: point at it for a moment (calls and alarms open it by themselves). What it shows, with all
// its controls, and under that, everything else going on; clicking one of those opens the island on it instead.
// It grows out of the island (originX: the island's centre, in this item) and shrinks back into it.
Glass {
    id: panel
    property string focusId: ""
    property bool shown: false
    property real originX: width - 150
    signal pointer(bool inside)                 // the pointer is on it (the host keeps it open)
    signal openWanted(string app)               // "go to the app" from inside it
    readonly property var all: Live.main && Live.main.id ? [Live.main].concat(Live.others) : Live.others
    readonly property var it: { for (var i = 0; i < all.length; i++) if (all[i].id === focusId) return all[i]; return all.length ? all[0] : ({}) }
    readonly property string kind: L.kindOf(it)
    readonly property var rest: all.filter(function (x) { return x.id !== panel.it.id })
    readonly property color tone: it.tone || Theme.t.accent
    property real now: Date.now()
    Timer { interval: 250; repeat: true; running: panel.visible; onTriggered: panel.now = Date.now() }
    onShownChanged: if (shown && kind === "playing") Live.refresh(it.id)
    onKindChanged: if (shown && kind === "playing") Live.refresh(it.id)

    width: 380; height: body.implicitHeight + 36; radius: 28; dense: true
    opacity: shown ? 1 : 0
    visible: opacity > 0.01
    property real grow: shown ? 1 : 0.55
    Behavior on grow { NumberAnimation { duration: panel.shown ? Theme.t.openMs * 1.3 : Theme.t.closeMs; easing.type: panel.shown ? Easing.OutBack : Easing.InCubic; easing.overshoot: 1.1 } }
    Behavior on opacity { NumberAnimation { duration: panel.shown ? Theme.t.openMs : Theme.t.closeMs } }
    transform: Scale { origin.x: panel.originX; origin.y: panel.height + 40; xScale: panel.grow; yScale: panel.grow }
    HoverHandler { onHoveredChanged: panel.pointer(hovered) }

    Rectangle {   // the colour of what it shows, as a glow from the top
        anchors.fill: parent; radius: parent.radius
        gradient: Gradient {
            GradientStop { position: 0; color: Qt.rgba(panel.tone.r, panel.tone.g, panel.tone.b, Theme.t.dark ? 0.24 : 0.16) }
            GradientStop { position: 0.6; color: "transparent" } }
    }

    Column {
        id: body
        x: 18; y: 18; width: parent.width - 36; spacing: 14
        Loader {
            width: parent.width
            sourceComponent: panel.kind === "playing" ? playingView : panel.kind === "timer" || panel.kind === "alarm" ? timerView
                           : panel.kind === "call" ? callView : panel.kind === "event" ? eventView : L.privacy(panel.it) ? privacyView : progressView
        }
        Rectangle { visible: panel.rest.length > 0; width: parent.width; height: 1; color: Theme.t.line }
        Column {
            visible: panel.rest.length > 0; width: parent.width; spacing: 2
            Label { text: "ALSO HAPPENING"; font.pixelSize: 11; font.weight: Font.DemiBold; font.letterSpacing: 0.9; color: Theme.t.text_tertiary; bottomPadding: 4 }
            Repeater {
                model: panel.rest
                Rectangle {
                    id: row
                    required property var modelData
                    readonly property string k: L.kindOf(modelData)
                    width: parent.width; height: 40; radius: 12
                    color: rowHit.containsMouse ? Theme.t.hover : "transparent"
                    Row {
                        x: 6; spacing: 12; anchors.verticalCenter: parent.verticalCenter
                        LiveRing { visible: row.k === "timer" || row.k === "progress"; width: 30; height: 30; tone: row.modelData.tone || Theme.t.accent
                            value: row.k === "timer" ? (row.modelData.total ? Math.max(0, L.left(row.modelData, panel.now)) / row.modelData.total : 0) : (row.modelData.progress >= 0 ? row.modelData.progress : 0.25)
                            glyph: row.k === "progress" ? (row.modelData.glyph || "download") : "" }
                        LiveLead { visible: row.k !== "timer" && row.k !== "progress"; it: row.modelData; now: panel.now; size: 30 }
                        Label { width: row.width - 30 - 12 - 12 - value.width - 18; anchors.verticalCenter: parent.verticalCenter; text: row.modelData.title || ""; elide: Text.ElideRight }
                        Label {
                            id: value; anchors.verticalCenter: parent.verticalCenter; secondary: true
                            text: row.k === "timer" ? L.clock(L.left(row.modelData, panel.now)) : row.k === "progress" ? (row.modelData.progress >= 0 ? Math.round(row.modelData.progress * 100) + "%" : "")
                                : row.k === "playing" ? (row.modelData.playing ? "Playing" : "Paused") : row.k === "event" ? L.sub(row.modelData, panel.now).split(" · ")[0]
                                : row.k === "call" ? "Calling" : L.privacy(row.modelData) ? "On" : ""
                        }
                    }
                    MouseArea { id: rowHit; anchors.fill: parent; hoverEnabled: true; onClicked: panel.focusId = row.modelData.id }
                }
            }
        }
    }

    // ---- the buttons along the bottom of a view
    component Actions: Row {
        id: acts
        property var list: []
        spacing: 8
        visible: list.length > 0
        Repeater {
            model: acts.list
            Rectangle {
                id: pb
                required property var modelData
                readonly property string t: L.tone(modelData)
                width: (acts.width - acts.spacing * (acts.list.length - 1)) / Math.max(1, acts.list.length); height: 40; radius: 13
                color: t === "primary" || t === "go" ? panel.tone : t === "danger" ? "#FF5A5F" : (pbHit.containsMouse ? Theme.t.pressed : Theme.t.hover)
                readonly property color ink: t === "danger" ? "white" : t ? "#10142A" : Theme.t.text
                scale: pbHit.pressed ? Theme.t.pressScale : 1
                Behavior on scale { NumberAnimation { duration: 100 } }
                Row { anchors.centerIn: parent; spacing: 7
                    Glyph { visible: !!pb.modelData.glyph; name: pb.modelData.glyph || ""; size: 15; ink: pb.ink; anchors.verticalCenter: parent.verticalCenter }
                    Label { text: pb.modelData.label || ""; color: pb.ink; font.weight: Font.DemiBold; anchors.verticalCenter: parent.verticalCenter } }
                MouseArea { id: pbHit; anchors.fill: parent; hoverEnabled: true
                    onClicked: {
                        if (pb.modelData.id === "open" && panel.it.source === "board") { var app = Live.openApp(panel.it.id); if (app) panel.openWanted(app) }   // "go to the app"
                        else Live.act(panel.it.id, pb.modelData.id)
                    } }
            }
        }
    }
    component Round: Rectangle {
        id: rd
        property string glyph: ""
        property string act: ""
        property bool filled: false
        width: 40; height: width; radius: width / 2
        color: filled ? panel.tone : (rdHit.containsMouse ? Theme.t.hover : "transparent")
        scale: rdHit.pressed ? Theme.t.pressScale : 1
        Behavior on scale { NumberAnimation { duration: 100 } }
        Glyph { anchors.centerIn: parent; name: rd.glyph; size: rd.width * 0.42; ink: rd.filled ? "#1A0710" : Theme.t.text }
        MouseArea { id: rdHit; anchors.fill: parent; hoverEnabled: true; onClicked: Live.act(panel.it.id, rd.act) }
    }
    component Head: Row {   // the picture, the title and two lines under it
        id: head
        property int lead: 44
        property string line2: L.sub(panel.it, panel.now)
        property string line3: ""
        spacing: 14
        LiveLead { it: panel.it; now: panel.now; size: head.lead; anchors.verticalCenter: parent.verticalCenter }
        Column { anchors.verticalCenter: parent.verticalCenter; spacing: 2; width: head.width - head.lead - 14
            Label { width: parent.width; text: panel.it.title || ""; font.pixelSize: 18; font.weight: Font.DemiBold; elide: Text.ElideRight }
            Label { width: parent.width; visible: text !== ""; text: head.line2; secondary: true; elide: Text.ElideRight }
            Label { width: parent.width; visible: text !== ""; text: head.line3; font.pixelSize: 12; color: Theme.t.text_tertiary; elide: Text.ElideRight } }
    }

    // ---- one view for each kind of thing
    Component { id: playingView
        Column { id: pv; spacing: 14
            readonly property real pos: L.position(panel.it, panel.now)
            property real dragging: -1
            Row { spacing: 14; width: parent.width
                LiveArt { width: 76; height: 76; it: panel.it; r: 16 }
                Column { width: parent.width - 76 - 14 - 14 - 27; anchors.verticalCenter: parent.verticalCenter; spacing: 3
                    Label { width: parent.width; text: panel.it.title || ""; font.pixelSize: 18; font.weight: Font.DemiBold; elide: Text.ElideRight }
                    Label { width: parent.width; text: panel.it.sub || ""; secondary: true; elide: Text.ElideRight } }
                LiveEq { playing: !!panel.it.playing; tone: panel.tone; anchors.verticalCenter: parent.verticalCenter }
            }
            Column { visible: (panel.it.length || 0) > 0; width: parent.width; spacing: 5
                Item { id: track; width: parent.width; height: 14
                    readonly property real frac: pv.dragging >= 0 ? pv.dragging : (panel.it.length ? pv.pos / panel.it.length : 0)
                    Rectangle { anchors.verticalCenter: parent.verticalCenter; width: parent.width; height: 5; radius: 3; color: Theme.t.line
                        Rectangle { width: parent.width * Math.min(1, track.frac); height: parent.height; radius: 3; color: panel.tone } }
                    Rectangle { visible: seek.containsMouse || seek.pressed; x: parent.width * Math.min(1, track.frac) - 7; anchors.verticalCenter: parent.verticalCenter; width: 14; height: 14; radius: 7; color: "white" }
                    MouseArea { id: seek; anchors.fill: parent; anchors.margins: -6; hoverEnabled: true
                        function at(mx) { return Math.max(0, Math.min(1, (mx - 6) / track.width)) }
                        onPressed: function (m) { pv.dragging = at(m.x) }
                        onPositionChanged: function (m) { if (pressed) pv.dragging = at(m.x) }
                        onReleased: function (m) { Live.seek(panel.it.id, at(m.x) * panel.it.length); pv.dragging = -1 } }
                }
                Item { width: parent.width; height: 14
                    Label { text: L.clock(track.frac * (panel.it.length || 0)); font.pixelSize: 11; secondary: true }
                    Label { anchors.right: parent.right; text: "−" + L.clock((1 - track.frac) * (panel.it.length || 0)); font.pixelSize: 11; secondary: true } }
            }
            Row { anchors.horizontalCenter: parent.horizontalCenter; spacing: 18
                Round { glyph: "prev"; act: "previous"; anchors.verticalCenter: parent.verticalCenter }
                Round { glyph: panel.it.playing ? "pause" : "play"; act: "playpause"; filled: true; width: 52 }
                Round { glyph: "next"; act: "next"; anchors.verticalCenter: parent.verticalCenter } }
        }
    }
    Component { id: timerView
        Column { id: tv; spacing: 16
            readonly property real leftMs: L.left(panel.it, panel.now)
            Row { spacing: 18; width: parent.width
                Item { width: 112; height: 112
                    LiveRing { anchors.fill: parent; tone: panel.tone; thick: 7; value: panel.kind === "alarm" ? 1 : (panel.it.total ? Math.max(0, tv.leftMs) / panel.it.total : 0) }
                    Column { anchors.centerIn: parent
                        Label { anchors.horizontalCenter: parent.horizontalCenter; text: panel.kind === "alarm" ? "0:00" : L.clock(tv.leftMs); font.pixelSize: 24; font.weight: Font.Bold }
                        Label { anchors.horizontalCenter: parent.horizontalCenter; visible: !!panel.it.total; text: "of " + L.clock(panel.it.total || 0); font.pixelSize: 11; secondary: true } } }
                Column { anchors.verticalCenter: parent.verticalCenter; spacing: 3; width: parent.width - 130
                    Label { width: parent.width; text: panel.kind === "alarm" ? "Time's up" : (panel.it.title || "Timer"); font.pixelSize: 18; font.weight: Font.DemiBold; elide: Text.ElideRight; color: panel.kind === "alarm" ? Theme.t.danger : Theme.t.text }
                    Label { width: parent.width; text: (panel.it.title && panel.kind === "alarm" ? panel.it.title + " · " : "Timer · ") + (panel.it.app || "Clock"); secondary: true; elide: Text.ElideRight }
                    Label { width: parent.width; visible: panel.kind === "timer"; text: panel.it.paused ? "Paused" : "Rings at " + Qt.formatTime(new Date(panel.it.ends || 0), "HH:mm"); font.pixelSize: 12; color: Theme.t.text_tertiary } }
            }
            Actions { width: parent.width; list: panel.it.actions || [] }
        }
    }
    Component { id: callView
        Column { spacing: 14
            Head { width: parent.width; lead: 56; line2: panel.it.replied ? "Sent: “" + panel.it.replied + "”" : (panel.it.sub || "") }
            Actions { width: parent.width; list: panel.it.actions || [] }
            Flow { width: parent.width; spacing: 8; visible: (panel.it.replies || []).length > 0 && !panel.it.replied
                Repeater { model: panel.it.replies || []
                    Rectangle { required property string modelData; height: 30; width: rl.width + 22; radius: 10; color: chip.containsMouse ? Theme.t.pressed : Theme.t.hover
                        Label { id: rl; anchors.centerIn: parent; text: parent.modelData; font.pixelSize: 12 }
                        MouseArea { id: chip; anchors.fill: parent; hoverEnabled: true; onClicked: Live.act(panel.it.id, "reply:" + parent.modelData) } } } }
        }
    }
    Component { id: eventView
        Column { spacing: 14
            Row { spacing: 14; width: parent.width
                Rectangle { width: 4; height: ev.height; radius: 2; color: panel.tone }
                Column { id: ev; width: parent.width - 18; spacing: 3
                    Label { width: parent.width; text: panel.it.title || ""; font.pixelSize: 18; font.weight: Font.DemiBold; elide: Text.ElideRight }
                    Label { width: parent.width; text: (panel.it.sub ? panel.it.sub + " · " : "") + L.sub(panel.it, panel.now).split(" · ")[0]; secondary: true }
                    Label { width: parent.width; visible: !!panel.it.url; text: panel.it.url || ""; font.pixelSize: 12; color: Theme.t.text_tertiary; elide: Text.ElideMiddle } } }
            Actions { width: parent.width; list: panel.it.actions || [] }
        }
    }
    Component { id: progressView
        Column { spacing: 14
            Row { spacing: 14; width: parent.width
                LiveLead { it: panel.it; now: panel.now; size: 44; anchors.verticalCenter: parent.verticalCenter }
                Column { width: parent.width - 58; anchors.verticalCenter: parent.verticalCenter; spacing: 6
                    Label { width: parent.width; text: panel.it.title || ""; font.pixelSize: 15; font.weight: Font.DemiBold; elide: Text.ElideRight }
                    LiveBar { width: parent.width; height: 5; value: panel.it.progress === undefined ? -1 : panel.it.progress; tone: panel.tone }
                    Label { width: parent.width; text: (panel.it.progress >= 0 ? Math.round(panel.it.progress * 100) + "% · " : "") + (panel.it.sub || ""); font.pixelSize: 12; secondary: true; elide: Text.ElideRight } } }
            Actions { width: parent.width; list: panel.it.actions || [] }
        }
    }
    Component { id: privacyView
        Column { spacing: 12
            Head { width: parent.width; line2: "In use right now" }
            Repeater { model: panel.it.apps || []
                Row { required property var modelData; width: parent.width; spacing: 10
                    Label { width: parent.width - since.width - 10; text: modelData.name; font.weight: Font.DemiBold; elide: Text.ElideRight }
                    Label { id: since; text: "Since " + Qt.formatTime(new Date((modelData.since || 0) * 1000), "HH:mm"); secondary: true } } }
            Actions { width: parent.width; list: panel.it.actions || [] }
            Label { width: parent.width; wrapMode: Text.WordWrap; font.pixelSize: 11; color: Theme.t.text_tertiary
                text: "This shows whenever anything uses the " + (panel.kind === "screen" ? "screen" : panel.kind === "camera" ? "camera" : "microphone") + ". It can't be hidden." }
        }
    }
}
