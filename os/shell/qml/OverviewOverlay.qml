import QtQuick

// The Overview's words and controls, over the windows Huginn's compositor has spread out (it draws them; this
// draws over them): the spaces strip on top (click one to go there, double-click its name to rename it, drag a
// window onto one to move it there, + for a new one, × to remove one: its windows move next door), a chip with the
// app's icon and name under each window, and typing to find one (matches lit, the others dimmed; Enter goes to the
// first; nothing found: Search everything with what was typed). Esc, or a click on nothing, goes back.
// "Glide with light" (Settings › Desktop & Dock): the realm's light sweeps up through it as it opens.
Item {
    id: ov
    readonly property var info: Status.overview
    readonly property bool open: info.open === true
    readonly property var wins: info.windows || []
    readonly property var spaces: info.spaces || Status.spaces.names || []
    readonly property int current: info.current !== undefined ? info.current : (Status.spaces.current || 0)
    property string query: ""
    property string dragging: ""
    property int dropOn: -1
    signal searchWanted(string text)
    function appFor(id) { var a = Apps.all; for (var i = 0; i < a.length; i++) if ((a[i].id || "").toLowerCase() === (id || "").toLowerCase() || (a[i].wm || "").toLowerCase() === (id || "").toLowerCase()) return a[i]; return null }
    readonly property var found: {
        var q = query.trim().toLowerCase(), out = []
        if (!q) return []
        for (var i = 0; i < wins.length; i++) {
            var a = appFor(wins[i].app)
            if ((wins[i].title || "").toLowerCase().indexOf(q) >= 0 || (a && a.name.toLowerCase().indexOf(q) >= 0)) out.push(wins[i].id)
        }
        return out
    }
    onFoundChanged: Status.overviewDo("dim:" + (query.trim() ? wins.filter(function (w) { return found.indexOf(w.id) < 0 }).map(function (w) { return w.id }).join(",") : ""))
    onOpenChanged: if (open) { query = ""; field.text = ""; field.forceActiveFocus(); if (Settings.overviewOpen === "light" && Theme.t.openMs > 0) sweep.restart() }
    visible: open || chips.opacity > 0
    Keys.onEscapePressed: { if (query) field.text = ""; else Status.overviewDo("close") }

    MouseArea { anchors.fill: parent; acceptedButtons: Qt.AllButtons; onClicked: Status.overviewDo("close") }

    // ---------------------------------------------------------------- the spaces
    Row {
        id: strip
        anchors.horizontalCenter: parent.horizontalCenter; y: 18
        spacing: 12
        opacity: ov.open ? 1 : 0
        Behavior on opacity { NumberAnimation { duration: Theme.t.openMs ? 220 : 0 } }
        Repeater {
            model: ov.spaces
            Column {
                id: sp
                required property var modelData
                required property int index
                spacing: 5
                Rectangle {
                    width: 150; height: 84; radius: 14; clip: true
                    color: Qt.rgba(1, 1, 1, sp.index === ov.current ? 0.16 : 0.07)
                    border.width: sp.index === ov.current || ov.dropOn === sp.index ? 2 : 1
                    border.color: sp.index === ov.current || ov.dropOn === sp.index ? Theme.t.accent : Qt.rgba(1, 1, 1, 0.15)
                    Flow {   // the apps on that space
                        anchors.centerIn: parent; width: parent.width - 24; spacing: 5
                        Repeater {
                            model: Status.windows.filter(function (w) { return w.space === sp.index && !w.minimised }).slice(0, 6)
                            AppIcon { required property var modelData; size: 24
                                readonly property var a: ov.appFor(modelData.appId)
                                name: a ? a.name : modelData.name; glyph: a ? a.glyph : ""; image: a ? a.image : ""; own: a ? a.own || "" : ""; web: false }
                        }
                    }
                    Label { visible: Status.windows.filter(function (w) { return w.space === sp.index }).length === 0; anchors.centerIn: parent; text: "Empty"; secondary: true; font.pixelSize: 12 }
                    MouseArea { anchors.fill: parent; hoverEnabled: true; id: spHit; onClicked: Status.spaceDo("switch:" + sp.index) }
                    Rectangle {   // remove (its windows move next door)
                        visible: spHit.containsMouse && ov.spaces.length > 1; x: parent.width - 26; y: 4; width: 22; height: 22; radius: 11; color: Qt.rgba(0, 0, 0, 0.55)
                        Label { anchors.centerIn: parent; text: "×"; color: "white"; font.pixelSize: 14 }
                        MouseArea { anchors.fill: parent; onClicked: Status.spaceDo("remove:" + sp.index) }
                    }
                }
                Item {
                    width: 150; height: 18
                    Label { id: spName; visible: !rename.visible; anchors.horizontalCenter: parent.horizontalCenter; text: sp.modelData; color: "#F5F7FA"; font.pixelSize: 12; font.weight: sp.index === ov.current ? Font.DemiBold : Font.Normal
                        MouseArea { anchors.fill: parent; anchors.margins: -4; onDoubleClicked: { rename.visible = true; rename.text = sp.modelData; rename.selectAll(); rename.forceActiveFocus() } } }
                    TextInput { id: rename; visible: false; anchors.horizontalCenter: parent.horizontalCenter; width: 140; horizontalAlignment: Text.AlignHCenter; color: "white"; font.pixelSize: 12
                        onAccepted: { Status.spaceDo("rename:" + sp.index + ":" + text); visible = false; field.forceActiveFocus() }
                        Keys.onEscapePressed: { visible = false; field.forceActiveFocus() } }
                }
            }
        }
        Rectangle {   // a new space
            width: 56; height: 84; radius: 14; color: addHit.containsMouse ? Qt.rgba(1, 1, 1, 0.14) : Qt.rgba(1, 1, 1, 0.06); border.width: 1; border.color: Qt.rgba(1, 1, 1, 0.15)
            Label { anchors.centerIn: parent; text: "+"; color: "#F5F7FA"; font.pixelSize: 26 }
            MouseArea { id: addHit; anchors.fill: parent; hoverEnabled: true; onClicked: Status.spaceDo("add") }
        }
    }

    // ---------------------------------------------------------------- each window: where it is, its name under it
    Item {
        id: chips
        anchors.fill: parent
        opacity: ov.open ? 1 : 0
        Behavior on opacity { NumberAnimation { duration: ov.open && Theme.t.openMs ? 240 : 100; easing.type: Easing.OutCubic } }
        Repeater {
            model: ov.wins
            Item {
                id: slot
                required property var modelData
                readonly property var a: ov.appFor(modelData.app)
                readonly property bool lit: ov.query.trim() === "" || ov.found.indexOf(modelData.id) >= 0
                x: modelData.x; y: modelData.y; width: modelData.w; height: modelData.h
                Rectangle {   // pointed at: an outline in the app's colour
                    anchors.fill: parent; anchors.margins: -3; radius: 13; color: "transparent"
                    border.width: 2.5; border.color: Theme.t.accent; visible: hit.containsMouse || (ov.query.trim() !== "" && ov.found[0] === slot.modelData.id)
                }
                MouseArea {
                    id: hit; anchors.fill: parent; hoverEnabled: true
                    drag.target: ghost; drag.threshold: 12
                    onPressed: { ghost.x = slot.x; ghost.y = slot.y }
                    onPositionChanged: if (drag.active) { ov.dragging = slot.modelData.id; ov.dropOn = ov.spaceAt(mapToItem(ov, mouseX, mouseY)) }
                    onReleased: {
                        if (ov.dragging !== "" && ov.dropOn >= 0) Status.spaceDo("move:" + slot.modelData.id + ":" + ov.dropOn)
                        ov.dragging = ""; ov.dropOn = -1
                    }
                    onClicked: if (ov.dragging === "") Status.overviewDo("activate:" + slot.modelData.id)
                }
                Rectangle {   // the chip: its app, its name
                    anchors { horizontalCenter: parent.horizontalCenter; top: parent.bottom; topMargin: 8 }
                    width: Math.min(parent.width + 40, chipRow.width + 20); height: 26; radius: 13
                    color: Qt.rgba(0.05, 0.06, 0.08, 0.78); opacity: slot.lit ? 1 : 0.35
                    Row {
                        id: chipRow; anchors.centerIn: parent; spacing: 6
                        AppIcon { size: 16; anchors.verticalCenter: parent.verticalCenter; name: slot.a ? slot.a.name : ""; glyph: slot.a ? slot.a.glyph : ""; image: slot.a ? slot.a.image : ""; own: slot.a ? slot.a.own || "" : ""; web: false }
                        Label { anchors.verticalCenter: parent.verticalCenter; width: Math.min(implicitWidth, slot.width + 10); elide: Text.ElideRight; text: slot.modelData.title || (slot.a ? slot.a.name : ""); color: "#F5F7FA"; font.pixelSize: 12; font.weight: Font.DemiBold }
                    }
                }
            }
        }
        Rectangle {   // a window being dragged to another space
            id: ghost
            visible: ov.dragging !== ""; width: 120; height: 76; radius: 10; color: Qt.rgba(1, 1, 1, 0.18); border.width: 2; border.color: Theme.t.accent
        }
    }
    function spaceAt(p) {
        var local = strip.mapFromItem(ov, p.x, p.y)
        if (local.y < 0 || local.y > 84) return -1
        var i = Math.floor(local.x / 162)
        return i >= 0 && i < spaces.length ? i : -1
    }
    Label {
        visible: ov.open && ov.wins.length === 0; anchors.centerIn: parent
        text: "No windows on " + (ov.spaces[ov.current] || "this space"); color: "#F5F7FA"; font.pixelSize: 16; opacity: 0.8
    }

    // ---------------------------------------------------------------- typing finds a window
    Rectangle {
        visible: ov.open && field.text !== ""
        anchors { horizontalCenter: parent.horizontalCenter; bottom: parent.bottom; bottomMargin: 100 }
        width: 360; height: 40; radius: 20; color: Qt.rgba(0.05, 0.06, 0.08, 0.85); border.width: 1.5; border.color: Theme.t.accent
        Glyph { x: 14; anchors.verticalCenter: parent.verticalCenter; name: "search"; size: 15; ink: "#F5F7FA" }
        Label { x: 38; anchors.verticalCenter: parent.verticalCenter; text: field.text; color: "#F5F7FA"; font.pixelSize: 14 }
        Label { anchors { right: parent.right; rightMargin: 14; verticalCenter: parent.verticalCenter } text: ov.found.length ? "Enter to go" : "Enter: Search everything"; color: "#B9C2CC"; font.pixelSize: 11 }
    }
    TextInput {
        id: field; width: 1; height: 1; opacity: 0
        onTextChanged: ov.query = text
        onAccepted: {
            if (ov.found.length) Status.overviewDo("activate:" + ov.found[0])
            else if (text.trim()) { Status.overviewDo("close"); ov.searchWanted(text) }
        }
        Keys.onEscapePressed: { if (text) text = ""; else Status.overviewDo("close") }
    }

    // ---------------------------------------------------------------- Glide with light: the realm's light sweeps up
    Rectangle {
        id: light
        width: parent.width; height: parent.height * 0.5; y: parent.height; opacity: 0
        gradient: Gradient {
            GradientStop { position: 0; color: "transparent" }
            GradientStop { position: 0.5; color: Qt.rgba(Theme.t.glowA.r, Theme.t.glowA.g, Theme.t.glowA.b, 0.22) }
            GradientStop { position: 0.75; color: Qt.rgba(Theme.t.glowB.r, Theme.t.glowB.g, Theme.t.glowB.b, 0.16) }
            GradientStop { position: 1; color: "transparent" }
        }
        SequentialAnimation {
            id: sweep
            ScriptAction { script: { light.y = ov.height; light.opacity = 1 } }
            NumberAnimation { target: light; property: "y"; to: -light.height; duration: 520; easing.type: Easing.InOutCubic }
            ScriptAction { script: light.opacity = 0 }
        }
    }
}
