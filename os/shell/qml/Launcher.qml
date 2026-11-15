import QtQuick
import QtQuick.Shapes

// The start menu (Super): islands over the dock. On top, a greeting and the app search; in the middle, the groups,
// Recent and every app (it scrolls), lit in the colour of the app under the pointer; below, you and the power row.
//
// Opening: the islands spring out of the dock's orb (`orb`, in this item's coordinates, set by the host), the realm's
// light sweeps up through the glass and each app appears as it passes. Closing pulls them back into the orb.
// Reduce Motion: a plain fade.
//
// Keys: type to search apps; arrows move; Enter opens; Tab hands what you typed to Search everything; the Menu key
// or Shift+F10 opens the app's island (right-click does too); Escape steps back (question, search, menu).
Item {
    id: root
    width: 700; height: 660
    signal done()
    signal searchEverything(string text)       // (the host opens Search, which closes the menu)
    property bool shown: false
    property point orb: Qt.point(width * 0.16, height + 70)
    property string query: ""
    property string group: ""
    property int current: -1
    property string confirm: ""
    property string hint: ""
    property var lit: null                     // the app under the pointer (or the keys): the glass takes its colour
    property Item litItem: null
    property real sweep: -0.8                  // the light's top edge, as a fraction of the middle island (1.15 = below it)
    readonly property bool still: Theme.t.openMs === 0
    readonly property real speed: still ? 0 : Theme.t.openMs / 220
    readonly property real presence: main.opacity    // for the host's dimming
    visible: shown || main.opacity > 0.01 || head.opacity > 0.01

    readonly property var groups: [
        { id: "", label: "All" }, { id: "internet", label: "Internet" }, { id: "work", label: "Work" },
        { id: "media", label: "Photos & Music" }, { id: "create", label: "Create" }, { id: "utilities", label: "Utilities" },
        { id: "games", label: "Games" }, { id: "system", label: "System" } ]
    readonly property var present: groups.filter(function (g) { return g.id === "" || Apps.all.some(function (a) { return a.group === g.id }) })
    readonly property bool searching: query.trim() !== ""
    readonly property var results: find(query, group)
    readonly property bool showRecent: !searching && group === "" && Apps.recent.length > 0
    readonly property var power: [
        { id: "lock", label: "Lock", glyph: "lock" }, { id: "sleep", label: "Sleep", glyph: "moon" },
        { id: "restart", label: "Restart", glyph: "refresh", ask: "Restart now?" },
        { id: "shutdown", label: "Shut Down", glyph: "power", ask: "Shut down now?" },
        { id: "signout", label: "Sign Out", glyph: "signout", ask: "Sign out? Open apps will close." } ]

    function find(q, g) {
        q = q.trim().toLowerCase()
        if (!q) return g ? Apps.all.filter(function (a) { return a.group === g }) : Apps.all
        var first = [], inName = [], other = []
        Apps.all.forEach(function (a) {
            var n = a.name.toLowerCase()
            if (n.split(/[\s&-]+/).some(function (w) { return w.indexOf(q) === 0 })) first.push(a)
            else if (n.indexOf(q) >= 0) inName.push(a)
            else if ((a.keywords || "").toLowerCase().indexOf(q) >= 0) other.push(a)
        })
        return first.concat(inName, other)
    }
    function colourOf(a) { return a && a.colours && a.colours.length ? (Theme.t.dark ? a.colours[0] : a.colours[1]) : Theme.t.accent }
    function go(app) { if (!app) return; Apps.launch(app.exec); root.done() }
    function move(by) {
        if (!results.length) return
        current = current < 0 ? 0 : Math.max(0, Math.min(results.length - 1, current + by))
        grid.positionViewAtIndex(current, GridView.Contain)
        lit = results[current]; litItem = grid.itemAtIndex(current)
    }
    function islandFor(app, item) {
        if (!app || !item) return
        var p = item.mapToItem(root, item.width / 2, item.height)
        island.open(app)
        island.x = Math.max(0, Math.min(root.width - island.width, p.x - island.width / 2))
        island.y = p.y + island.height + 6 < root.height ? p.y + 4 : Math.max(0, p.y - item.height - island.height - 4)
        island.visible = true
    }
    function closeIsland() { island.visible = false; input.forceActiveFocus() }
    function act(p) {
        if (p.ask && confirm !== p.id) { confirm = p.id; return }
        confirm = ""
        root.done()
        Status.power(p.id)
    }
    function greeting() {
        var h = new Date().getHours(), first = (Me.name || "").trim().split(/\s+/)[0]
        var hello = h >= 5 && h < 12 ? "Good morning" : h >= 12 && h < 17 ? "Good afternoon" : h >= 17 && h < 23 ? "Good evening" : "Hello"
        return first ? hello + ", " + first : hello
    }

    onQueryChanged: { current = searching ? 0 : -1; grid.positionViewAtBeginning() }
    onGroupChanged: { current = -1; grid.positionViewAtBeginning() }
    onShownChanged: {
        if (shown) {
            input.text = ""; group = ""; confirm = ""; hint = ""; current = -1; lit = null; litItem = null; island.visible = false
            hello.text = greeting(); today.text = Qt.formatDate(new Date(), "dddd, MMMM d")
            grid.positionViewAtBeginning()
            closing.stop()
            if (still) { foot.s = 1; main.s = 1; head.s = 1; sweep = -0.8; glow.opacity = 1; fade.restart() }
            else opening.restart()
            Qt.callLater(function () { input.forceActiveFocus() })
        } else {
            opening.stop(); fade.stop()
            closing.restart()
        }
    }

    // ---------------------------------------------------------------- the motion
    component Spring: SequentialAnimation {
        id: sp
        property Item target
        property int delay: 0
        PauseAnimation { duration: sp.delay * root.speed }
        PropertyAction { target: sp.target; property: "s"; value: 0.06 }
        ParallelAnimation {
            NumberAnimation { target: sp.target; property: "s"; to: 1; duration: 340 * root.speed; easing.type: Easing.OutBack; easing.overshoot: 0.9 }
            NumberAnimation { target: sp.target; property: "opacity"; from: 0; to: 1; duration: 110 * root.speed }
        }
    }
    ParallelAnimation {
        id: opening
        PropertyAction { targets: [foot, main, head]; property: "opacity"; value: 0 }
        PropertyAction { target: root; property: "sweep"; value: 1.15 }
        PropertyAction { target: glow; property: "opacity"; value: 0 }
        Spring { target: foot; delay: 0 }
        Spring { target: main; delay: 35 }
        Spring { target: head; delay: 70 }
        SequentialAnimation {
            PauseAnimation { duration: 60 * root.speed }
            NumberAnimation { target: root; property: "sweep"; to: -0.8; duration: 440 * root.speed; easing.type: Easing.InOutCubic }
        }
        SequentialAnimation {
            PauseAnimation { duration: 260 * root.speed }
            NumberAnimation { target: glow; property: "opacity"; to: 1; duration: 320 * root.speed; easing.type: Easing.OutCubic }
        }
    }
    ParallelAnimation {
        id: closing
        NumberAnimation { targets: [foot, main, head]; property: "s"; to: root.still ? 1 : 0.1; duration: Theme.t.closeMs || 120; easing.type: Easing.InCubic }
        NumberAnimation { targets: [foot, main, head]; property: "opacity"; to: 0; duration: Theme.t.closeMs || 120; easing.type: Easing.InCubic }
        NumberAnimation { target: glow; property: "opacity"; to: 0; duration: 100 }
    }
    NumberAnimation { id: fade; targets: [foot, main, head]; property: "opacity"; from: 0; to: 1; duration: 150 }

    // Every island grows from the orb: its own scale, around the orb's point in its coordinates.
    component Isle: Glass {
        id: isle
        property real s: 1
        popup: true
        opacity: 0
        transform: Scale { origin.x: root.orb.x - isle.x; origin.y: root.orb.y - isle.y; xScale: isle.s; yScale: isle.s }
    }

    // ---------------------------------------------------------------- top: hello, and the app search
    Isle {
        id: head
        width: root.width; height: 60; radius: 30
        Rectangle {   // the realm's orb, as on the dock
            x: 14; anchors.verticalCenter: parent.verticalCenter; width: 32; height: 32; radius: 16
            gradient: Gradient { orientation: Gradient.Horizontal; GradientStop { position: 0; color: Theme.t.glowA } GradientStop { position: 0.45; color: Theme.t.glowA } GradientStop { position: 1; color: Theme.t.glowB } }
        }
        Column {
            x: 58; anchors.verticalCenter: parent.verticalCenter; spacing: 1; width: field.x - x - 12
            Label { id: hello; font.pixelSize: 15; font.weight: Font.DemiBold; elide: Text.ElideRight; width: parent.width }
            Label { id: today; font.pixelSize: 12; color: Theme.t.text_secondary }
        }
        Rectangle {
            id: field
            anchors { right: parent.right; rightMargin: 10; verticalCenter: parent.verticalCenter }
            width: 300; height: 40; radius: 20; color: Theme.t.hover
            border.width: 1; border.color: input.activeFocus && root.searching ? Theme.t.accent : Theme.t.line
            Glyph { x: 14; anchors.verticalCenter: parent.verticalCenter; name: "search"; size: 16; ink: Theme.t.text_secondary }
            TextInput {
                id: input
                anchors { fill: parent; leftMargin: 38; rightMargin: tabCap.visible ? tabCap.width + 18 : 14 } verticalAlignment: TextInput.AlignVCenter
                color: Theme.t.text; font.family: Theme.t.font; font.pixelSize: 13; focus: true; selectByMouse: true; clip: true
                selectionColor: Theme.t.accent; selectedTextColor: Theme.t.onAccent
                onTextChanged: root.query = text
                Label { visible: !input.text; text: "Search apps"; color: Theme.t.text_tertiary; font.pixelSize: 13; anchors.verticalCenter: parent.verticalCenter }
                Keys.onPressed: function (e) {
                    var editing = root.searching
                    if (e.key === Qt.Key_Tab) { root.searchEverything(input.text); e.accepted = true }
                    else if (e.key === Qt.Key_Return || e.key === Qt.Key_Enter) {
                        if (root.current >= 0) root.go(root.results[root.current])
                        else if (root.searching && root.results.length) root.go(root.results[0])
                        else if (root.searching) { root.searchEverything(input.text) }
                        e.accepted = true
                    }
                    else if (e.key === Qt.Key_Down) { root.move(root.current < 0 ? 0 : 6); e.accepted = true }
                    else if (e.key === Qt.Key_Up) { if (root.current >= 0 && root.current < 6) root.current = -1; else root.move(-6); e.accepted = true }
                    else if (e.key === Qt.Key_Right && (!editing || root.current >= 0)) { root.move(1); e.accepted = true }
                    else if (e.key === Qt.Key_Left && root.current >= 0) { root.move(-1); e.accepted = true }
                    else if (e.key === Qt.Key_PageDown) { root.move(18); e.accepted = true }
                    else if (e.key === Qt.Key_PageUp) { root.move(-18); e.accepted = true }
                    else if (e.key === Qt.Key_Menu || (e.key === Qt.Key_F10 && (e.modifiers & Qt.ShiftModifier))) {
                        var i = Math.max(0, root.current)
                        root.islandFor(root.results[i], grid.itemAtIndex(i))
                        e.accepted = true
                    }
                    else if (e.key === Qt.Key_Escape) {
                        if (root.confirm) root.confirm = ""
                        else if (input.text) input.text = ""
                        else root.done()
                        e.accepted = true
                    }
                }
            }
            Rectangle {
                id: tabCap
                visible: root.searching
                anchors { right: parent.right; rightMargin: 8; verticalCenter: parent.verticalCenter }
                width: tabLabel.width + 12; height: 22; radius: 6; color: Theme.t.hover; border.width: 1; border.color: Theme.t.line
                Label { id: tabLabel; anchors.centerIn: parent; text: "Tab"; font.pixelSize: 11; font.weight: Font.DemiBold }
            }
        }
    }

    // ---------------------------------------------------------------- middle: groups, Recent, every app
    Isle {
        id: main
        y: head.height + 10; width: root.width; height: root.height - head.height - foot.height - 20; radius: 28
        clip: true

        Shape {   // the light of the app under the pointer
            id: glow
            opacity: 0
            readonly property point at: root.litItem ? root.litItem.mapToItem(main, root.litItem.width / 2, root.litItem.height / 2) : Qt.point(main.width * 0.5, main.height * 1.05)
            property color c: root.lit ? root.colourOf(root.lit) : Theme.t.glowA
            Behavior on c { ColorAnimation { duration: 260 } }
            x: at.x - width / 2; y: at.y - height / 2
            Behavior on x { NumberAnimation { duration: 260; easing.type: Easing.OutCubic } }
            Behavior on y { NumberAnimation { duration: 260; easing.type: Easing.OutCubic } }
            width: 400; height: 340
            ShapePath {
                strokeWidth: -1; strokeColor: "transparent"
                fillGradient: RadialGradient {
                    centerX: 200; centerY: 170; centerRadius: 190; focalX: 200; focalY: 170
                    GradientStop { position: 0; color: Qt.rgba(glow.c.r, glow.c.g, glow.c.b, root.lit ? 0.36 : 0.16) }
                    GradientStop { position: 0.55; color: Qt.rgba(glow.c.r, glow.c.g, glow.c.b, root.lit ? 0.11 : 0.05) }
                    GradientStop { position: 1; color: Qt.rgba(glow.c.r, glow.c.g, glow.c.b, 0) }
                }
                startX: 0; startY: 0
                PathLine { x: 400; y: 0 } PathLine { x: 400; y: 340 } PathLine { x: 0; y: 340 } PathLine { x: 0; y: 0 }
            }
        }

        Item {   // the realm's light, sweeping up through the glass as it opens
            id: light
            anchors.fill: parent
            visible: root.sweep > -0.79 && root.sweep < 1.14
            readonly property color a: Theme.t.glowA
            readonly property color b: Theme.t.glowB
            Rectangle {
                width: parent.width; height: parent.height * 0.7; y: root.sweep * parent.height
                gradient: Gradient {
                    GradientStop { position: 0; color: "transparent" }
                    GradientStop { position: 0.32; color: Qt.rgba(light.b.r, light.b.g, light.b.b, 0.22) }
                    GradientStop { position: 0.58; color: Qt.rgba(light.a.r, light.a.g, light.a.b, 0.30) }
                    GradientStop { position: 1; color: "transparent" }
                }
            }
        }

        Flow {   // the groups; the selected one sits on a pill that slides between them
            id: chips
            x: 18; y: 16; width: parent.width - 36; spacing: 6
            Rectangle {
                id: pill
                height: 32; radius: 16; color: Theme.t.accent; visible: !root.searching && width > 0
                Behavior on x { NumberAnimation { duration: root.still ? 0 : 240; easing.type: Easing.OutCubic } }
                Behavior on y { NumberAnimation { duration: root.still ? 0 : 240; easing.type: Easing.OutCubic } }
                Behavior on width { NumberAnimation { duration: root.still ? 0 : 240; easing.type: Easing.OutCubic } }
            }
            Repeater {
                model: root.present
                Item {
                    id: chip
                    required property var modelData
                    readonly property bool on: root.group === modelData.id && !root.searching
                    width: chipLabel.width + 26; height: 32
                    function place() { if (on) { pill.x = x; pill.y = y; pill.width = width } }
                    onOnChanged: place()
                    onXChanged: place()
                    Component.onCompleted: place()
                    Rectangle { anchors.fill: parent; radius: 16; color: Theme.t.hover; opacity: chip.on ? 0 : (chipArea.containsMouse ? 1 : 0.55) }
                    Label { id: chipLabel; anchors.centerIn: parent; text: chip.modelData.label; font.pixelSize: 13; font.weight: chip.on ? Font.DemiBold : Font.Medium; color: chip.on ? Theme.t.onAccent : Theme.t.text_secondary }
                    MouseArea { id: chipArea; anchors.fill: parent; hoverEnabled: true; onClicked: { root.group = chip.modelData.id; input.text = ""; input.forceActiveFocus() } }
                }
            }
        }

        // One app: its icon and name. It shows as the light reaches it, glows in its colour under the pointer,
        // and right-click (or a long press) opens its island.
        component Tile: Item {
            id: t
            property var app
            property int index: -1
            property int size: 44
            readonly property bool here: root.lit === app
            readonly property real reveal: {
                if (root.still || root.sweep <= -0.79) return 1
                var y = t.mapToItem(main, 0, t.height / 2).y / Math.max(1, main.height)   // re-read as the light moves
                return Math.max(0, Math.min(1, (y + 0.1 - (root.sweep + 0.35)) * 5))
            }
            width: 110; height: size + 52
            opacity: reveal
            transform: Translate { y: (1 - t.reveal) * 14 }
            Rectangle {
                anchors { fill: parent; margins: 3 } radius: 16
                color: t.here || (root.current === t.index && t.index >= 0) ? Theme.t.hover : "transparent"
                border.width: root.current === t.index && t.index >= 0 ? 1 : 0; border.color: Theme.t.line
            }
            AppIcon {
                id: icon
                y: 10; anchors.horizontalCenter: parent.horizontalCenter
                size: t.size; name: t.app.name; glyph: t.app.glyph; image: t.app.image; own: t.app.own || ""; web: t.app.web
                scale: hit.pressed ? 0.94 : (t.here ? 1.07 : 1)
                Behavior on scale { NumberAnimation { duration: 160; easing.type: Easing.OutBack } }
            }
            Label {
                anchors { top: icon.bottom; topMargin: 7; horizontalCenter: parent.horizontalCenter }
                width: parent.width - 10; horizontalAlignment: Text.AlignHCenter; elide: Text.ElideRight
                text: t.app.name; font.pixelSize: 12; color: t.here ? Theme.t.text : Theme.t.text_secondary
            }
            Rectangle {   // already open
                visible: Apps.running.indexOf(t.app.name) >= 0
                width: 5; height: 5; radius: 2.5; color: Theme.t.accent
                anchors { horizontalCenter: parent.horizontalCenter; bottom: parent.bottom; bottomMargin: 2 }
            }
            MouseArea {
                id: hit; anchors.fill: parent; hoverEnabled: true; acceptedButtons: Qt.LeftButton | Qt.RightButton
                onContainsMouseChanged: if (containsMouse) { root.lit = t.app; root.litItem = t }
                onClicked: function (m) { if (m.button === Qt.RightButton) root.islandFor(t.app, t); else root.go(t.app) }
                onPressAndHold: root.islandFor(t.app, t)
            }
        }

        GridView {
            id: grid
            x: 18; y: chips.y + chips.height + 10
            width: parent.width - 36; height: parent.height - y - (everything.visible ? everything.height + 24 : 8)
            cellWidth: width / 6; cellHeight: 98
            clip: true; boundsBehavior: Flickable.StopAtBounds; flickDeceleration: 4000
            model: root.results
            header: Column {
                width: grid.width
                Label { visible: root.showRecent; leftPadding: 8; topPadding: 2; bottomPadding: 2; text: "RECENT"; color: Theme.t.text_tertiary; font.pixelSize: 11; font.weight: Font.DemiBold; font.letterSpacing: 0.7 }
                Row {
                    visible: root.showRecent; height: visible ? 104 : 0
                    Repeater { model: root.showRecent ? Apps.recent : []; Tile { required property var modelData; app: modelData; size: 48; width: grid.cellWidth } }
                }
                Label {
                    leftPadding: 8; topPadding: root.showRecent ? 8 : 2; bottomPadding: 2
                    text: root.searching ? (root.results.length ? "APPS" : "") : (root.group === "" ? "ALL APPS · " + Apps.all.length : "")
                    visible: text !== ""; color: Theme.t.text_tertiary; font.pixelSize: 11; font.weight: Font.DemiBold; font.letterSpacing: 0.7
                }
            }
            delegate: Tile { required property var modelData; required property int index; app: modelData; width: grid.cellWidth }
            Label {
                visible: root.searching && root.results.length === 0
                y: 30; width: parent.width; horizontalAlignment: Text.AlignHCenter
                text: "No app is called “" + root.query.trim() + "”."; color: Theme.t.text_secondary; font.pixelSize: 13
            }
        }
        Rectangle {   // the slim bar that says where you are
            visible: grid.contentHeight > grid.height + 1
            x: parent.width - 8; width: 4; radius: 2; color: Theme.t.text_tertiary; opacity: grid.moving ? 0.8 : 0.35
            height: Math.max(36, grid.height * grid.height / Math.max(1, grid.contentHeight))
            y: grid.y + (grid.height - height) * Math.max(0, Math.min(1, (grid.contentY - grid.originY) / Math.max(1, grid.contentHeight - grid.height)))
            Behavior on opacity { NumberAnimation { duration: 200 } }
        }

        Pressable {   // Search everything for what you typed (Tab)
            id: everything
            visible: root.searching
            anchors { left: parent.left; right: parent.right; bottom: parent.bottom; margins: 14 }
            height: 56; radius: 16; color: hovered ? Theme.t.hover : Qt.rgba(1, 1, 1, Theme.t.dark ? 0.05 : 0.5)
            border.width: 1; border.color: Theme.t.line
            onClicked: { root.searchEverything(input.text) }
            Rectangle { x: 10; anchors.verticalCenter: parent.verticalCenter; width: 36; height: 36; radius: 11; color: Theme.t.hover
                Glyph { anchors.centerIn: parent; name: "search"; size: 18; ink: Theme.t.icon } }
            Column {
                x: 58; anchors.verticalCenter: parent.verticalCenter; spacing: 1
                Label { text: "Search everything for “" + root.query.trim() + "”"; font.pixelSize: 14; font.weight: Font.DemiBold }
                Label { text: "Files, settings, answers and Huginn's tabs · on this computer"; font.pixelSize: 12; color: Theme.t.text_secondary }
            }
            Rectangle { anchors { right: parent.right; rightMargin: 12; verticalCenter: parent.verticalCenter } width: 34; height: 22; radius: 6; color: Theme.t.hover; border.width: 1; border.color: Theme.t.line
                Label { anchors.centerIn: parent; text: "Tab"; font.pixelSize: 11; font.weight: Font.DemiBold } }
        }
    }

    // ---------------------------------------------------------------- bottom: you, and the power row
    Item {
        id: foot
        property real s: 1
        y: root.height - height; width: root.width; height: 52
        opacity: 0
        transform: Scale { origin.x: root.orb.x - foot.x; origin.y: root.orb.y - foot.y; xScale: foot.s; yScale: foot.s }
        Glass {
            popup: true; height: 52; radius: 26; width: who.width + 30
            Row {
                id: who
                x: 10; anchors.verticalCenter: parent.verticalCenter; spacing: 10
                Rectangle {
                    width: 32; height: 32; radius: 16; color: Theme.t.accent; clip: true
                    Label { anchors.centerIn: parent; text: (Me.name || "?")[0].toUpperCase(); color: Theme.t.onAccent; font.pixelSize: 14; font.weight: Font.DemiBold; visible: !face.visible }
                    Image { id: face; anchors.fill: parent; source: Me.face || ""; visible: Me.face !== "" && status === Image.Ready; fillMode: Image.PreserveAspectCrop; smooth: true }
                }
                Label { anchors.verticalCenter: parent.verticalCenter; text: root.hint || Me.name || ""; font.pixelSize: 13; color: root.hint ? Theme.t.text_secondary : Theme.t.text }
            }
        }
        Glass {
            id: powerPill
            popup: true; height: 52; radius: 26
            anchors.right: parent.right
            width: root.confirm ? askRow.width + 30 : buttons.width + 14
            Behavior on width { NumberAnimation { duration: root.still ? 0 : 200; easing.type: Easing.OutCubic } }
            clip: true
            Row {
                id: buttons
                visible: root.confirm === ""
                x: 7; anchors.verticalCenter: parent.verticalCenter; spacing: 4
                Repeater {
                    model: root.power.filter(function (p) { return Status.powerCaps[p.id] !== false })
                    Pressable {
                        id: pb
                        required property var modelData
                        width: 38; height: 38; radius: 12
                        onClicked: root.act(modelData)
                        onHoveredChanged: root.hint = hovered ? modelData.label : (root.hint === modelData.label ? "" : root.hint)
                        Glyph { anchors.centerIn: parent; name: pb.modelData.glyph; size: 18; ink: Theme.t.icon }
                    }
                }
            }
            Row {
                id: askRow
                visible: root.confirm !== ""
                x: 16; anchors.verticalCenter: parent.verticalCenter; spacing: 10
                readonly property var p: root.power.filter(function (x) { return x.id === root.confirm })[0] || ({})
                Label { anchors.verticalCenter: parent.verticalCenter; text: askRow.p.ask || ""; font.pixelSize: 13; font.weight: Font.DemiBold }
                Pressable {
                    width: cancelLabel.width + 26; height: 34; radius: 10; color: hovered ? Theme.t.hover : Theme.t.view
                    onClicked: root.confirm = ""
                    Label { id: cancelLabel; anchors.centerIn: parent; text: "Cancel" }
                }
                Pressable {
                    width: goLabel.width + 26; height: 34; radius: 10; color: Theme.t.danger
                    onClicked: root.act(askRow.p)
                    Label { id: goLabel; anchors.centerIn: parent; text: askRow.p.label || ""; color: "white"; font.weight: Font.DemiBold }
                }
            }
        }
    }

    AppIsland { id: island; visible: false; z: 50; onDone: root.closeIsland() }

    // clicks on the menu stay in it (the host closes it on a click outside); a click beside the island closes it
    MouseArea { anchors.fill: parent; z: -2; acceptedButtons: Qt.AllButtons; onClicked: if (island.visible) root.closeIsland(); onWheel: function (w) { w.accepted = true } }
}
