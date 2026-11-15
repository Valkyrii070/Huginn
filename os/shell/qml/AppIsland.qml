import QtQuick

// An app's own island: what you'd want to do with that app, right where it is. The same one opens from the start
// menu, the dock and Search everything (right-click, a long press, or the Menu key / Shift+F10).
//   its recent files (the desktop's shared recent list, then the newest files of its kinds), its own actions from
//   its .desktop file (New Window, New Private Window…), Keep in the dock, and Uninstall for App Store apps.
// Keys: Up/Down, Enter, Escape. It tints itself with the app's own colour.
Glass {
    id: isle
    popup: true; dense: true; radius: 22; width: 300
    height: col.height + 16
    signal done()
    property var app: null
    property var info: ({})
    property int current: -1
    readonly property color tint: app && app.colours && app.colours.length ? (Theme.t.dark ? app.colours[0] : app.colours[1]) : Theme.t.accent
    readonly property var rows: {
        var out = [], i, info = isle.info
        if (!app || !info.name) return out
        out.push({ kind: "open", glyph: "forward", label: info.running ? "Show " + app.name : "Open " + app.name })
        for (i = 0; i < (info.actions || []).length; i++) out.push({ kind: "action", glyph: "plus", label: info.actions[i], index: i })
        if ((info.recent || []).length) {
            out.push({ kind: "head", label: "Recent" })
            for (i = 0; i < info.recent.length; i++)
                out.push({ kind: "file", glyph: "doc", label: info.recent[i].name, sub: info.recent[i].where + " · " + info.recent[i].when, path: info.recent[i].path })
        }
        out.push({ kind: "line" })
        if (!app.web) out.push({ kind: "pin", glyph: "pin", label: info.pinned ? "Remove from the dock" : "Keep in the dock" })
        if (info.removable) out.push({ kind: "store", glyph: "bag", label: "Uninstall…" })
        return out
    }
    readonly property var picks: rows.map(function (r, i) { return r.kind === "head" || r.kind === "line" ? -1 : i }).filter(function (i) { return i >= 0 })

    function open(a) {
        app = a; info = a ? Apps.island(a.name) : ({}); current = -1
        forceActiveFocus()
    }
    function act(r) {
        if (!r) return
        if (r.kind === "open") Apps.launch(app.exec)
        else if (r.kind === "action") Apps.runAction(app.name, r.index)
        else if (r.kind === "file") Apps.openWith(app.name, r.path)
        else if (r.kind === "pin") Apps.setPinned(app.name, !info.pinned)
        else if (r.kind === "store") Apps.showInStore(app.name)
        isle.done()
    }
    function step(by) {
        if (!picks.length) return
        var at = picks.indexOf(current)
        current = picks[at < 0 ? (by > 0 ? 0 : picks.length - 1) : Math.max(0, Math.min(picks.length - 1, at + by))]
    }
    Keys.onUpPressed: step(-1)
    Keys.onDownPressed: step(1)
    Keys.onReturnPressed: act(rows[current])
    Keys.onEnterPressed: act(rows[current])
    Keys.onEscapePressed: isle.done()

    // in: a quick lift and fade (none with Reduce Motion)
    opacity: 0; scale: 0.94
    NumberAnimation on opacity { id: fadeIn; running: false; to: 1; duration: Theme.t.openMs * 0.7; easing.type: Easing.OutCubic }
    NumberAnimation on scale { id: growIn; running: false; to: 1; duration: Theme.t.openMs; easing.type: Easing.OutBack; easing.overshoot: 1.2 }
    onVisibleChanged: if (visible) { opacity = Theme.t.openMs ? 0 : 1; scale = Theme.t.openMs ? 0.94 : 1; fadeIn.restart(); growIn.restart() }

    Rectangle {   // the app's own colour, faintly, from the top
        anchors.fill: parent; radius: parent.radius; opacity: 0.16
        gradient: Gradient { GradientStop { position: 0; color: isle.tint } GradientStop { position: 0.55; color: "transparent" } }
    }
    Column {
        id: col
        x: 8; y: 8; width: parent.width - 16; spacing: 1
        Row {
            spacing: 12; leftPadding: 8; topPadding: 6; bottomPadding: 8
            AppIcon { size: 36; name: isle.app ? isle.app.name : ""; glyph: isle.app ? isle.app.glyph : ""; image: isle.app ? isle.app.image : ""; own: isle.app ? (isle.app.own || "") : ""; web: isle.app ? isle.app.web : false }
            Column {
                anchors.verticalCenter: parent.verticalCenter; spacing: 1
                Label { text: isle.app ? isle.app.name : ""; font.pixelSize: 15; font.weight: Font.DemiBold }
                Label { text: isle.info.about || (isle.app && isle.app.web ? "Web app" : ""); visible: text !== ""; color: Theme.t.text_secondary; font.pixelSize: 12; width: 200; elide: Text.ElideRight }
            }
        }
        Repeater {
            model: isle.rows
            Item {
                id: r
                required property var modelData
                required property int index
                width: col.width
                height: modelData.kind === "line" ? 9 : modelData.kind === "head" ? 26 : (modelData.sub ? 44 : 36)
                Rectangle { visible: r.modelData.kind === "line"; anchors.centerIn: parent; width: parent.width - 16; height: 1; color: Theme.t.line }
                Label { visible: r.modelData.kind === "head"; x: 10; anchors.bottom: parent.bottom; anchors.bottomMargin: 4; text: (r.modelData.label || "").toUpperCase(); color: Theme.t.text_tertiary; font.pixelSize: 11; font.weight: Font.DemiBold; font.letterSpacing: 0.6 }
                Pressable {
                    visible: r.modelData.kind !== "line" && r.modelData.kind !== "head"
                    anchors.fill: parent; radius: 11
                    color: isle.current === r.index || hovered ? Theme.t.hover : "transparent"
                    onHoveredChanged: if (hovered) isle.current = r.index
                    onClicked: isle.act(r.modelData)
                    Glyph { x: 10; anchors.verticalCenter: parent.verticalCenter; name: r.modelData.glyph || ""; size: 16; ink: r.modelData.kind === "store" ? Theme.t.danger : Theme.t.icon }
                    Column {
                        x: 36; anchors.verticalCenter: parent.verticalCenter; width: parent.width - 46; spacing: 1
                        Label { text: r.modelData.label || ""; width: parent.width; elide: Text.ElideRight; font.pixelSize: 13; color: r.modelData.kind === "store" ? Theme.t.danger : Theme.t.text }
                        Label { visible: !!r.modelData.sub; text: r.modelData.sub || ""; width: parent.width; elide: Text.ElideRight; font.pixelSize: 11; color: Theme.t.text_tertiary }
                    }
                }
            }
        }
    }
    MouseArea { anchors.fill: parent; z: -2; acceptedButtons: Qt.AllButtons }   // clicks on the island stay in it
}
