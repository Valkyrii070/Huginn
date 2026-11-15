import QtQuick

// Search everything (Super+Space, or the magnifier in the top bar): one bar in the middle of the screen, and what it
// finds arrives as islands. On the left, the top hit, big; on the right, in a fixed order so nothing jumps while
// results come in: apps, files, Settings pages and Huginn's open tabs; along the bottom, the web, always last.
// Before you type: pick up where you left off, the apps you use, and a few quick actions.
// Everything is found on this computer; only "Search the web" sends what you typed anywhere.
//
// Keys: Up/Down move through every result, Enter opens, Shift+Enter searches the web, Tab narrows it down
// (All, Apps, Files, Settings, Huginn), the Menu key or Shift+F10 (or right-click) opens an app's island, Escape
// clears and then closes.
Item {
    id: root
    signal done()
    property bool shown: false
    property string text: ""                   // what's typed (the bar's text)
    property string startText: ""              // what it opens with (from the start menu's Tab), set by the host
    property int current: 0
    property string scope: "All"
    readonly property var scopes: ["All", "Apps", "Files", "Settings", "Huginn"]
    readonly property bool typing: text.trim() !== ""
    readonly property bool still: Theme.t.openMs === 0
    readonly property real presence: bar.opacity
    visible: shown || bar.opacity > 0.01

    function colourOf(a) { return a && a.colours && a.colours.length ? (Theme.t.dark ? a.colours[0] : a.colours[1]) : Theme.t.accent }
    function want(s) { return scope === "All" || scope === s }
    readonly property var apps: {
        var q = text.trim().toLowerCase()
        if (!q || !want("Apps")) return []
        var first = [], other = []
        Apps.all.forEach(function (a) {
            var n = a.name.toLowerCase()
            if (n.split(/[\s&-]+/).some(function (w) { return w.indexOf(q) === 0 })) first.push(a)
            else if (n.indexOf(q) >= 0 || (a.keywords || "").toLowerCase().indexOf(q) >= 0) other.push(a)
        })
        return first.concat(other).slice(0, 5)
    }
    readonly property var tabs: {
        var q = text.trim().toLowerCase()
        if (!q || !want("Huginn")) return []
        return Tabs.list.filter(function (t) { return (t.title + " " + t.url).toLowerCase().indexOf(q) >= 0 }).slice(0, 4)
    }
    readonly property var files: want("Files") ? SearchData.files : []
    readonly property var pages: want("Settings") ? SearchData.settings : []
    readonly property var sum: scope === "All" ? SearchData.answer : ({})
    // The best match: a sum, an app whose name starts so, then a file, then a Settings page.
    readonly property var best: {
        if (!typing) return null
        if (sum.value) return { kind: "answer", data: sum }
        var q = text.trim().toLowerCase()
        if (apps.length && apps[0].name.toLowerCase().indexOf(q) === 0) return { kind: "app", data: apps[0] }
        if (files.length) return { kind: "file", data: files[0] }
        if (apps.length) return { kind: "app", data: apps[0] }
        if (pages.length) return { kind: "setting", data: pages[0] }
        if (tabs.length) return { kind: "tab", data: tabs[0] }
        return null
    }
    // Everything the keys move through, in the order it shows.
    readonly property var items: {
        var out = [], i, t = best
        if (!typing) {
            for (i = 0; i < SearchData.resume.length; i++) out.push({ kind: "resume", data: SearchData.resume[i] })
            for (i = 0; i < Apps.recent.length; i++) out.push({ kind: "app", data: Apps.recent[i] })
            return out
        }
        if (t) out.push(t)
        for (i = 0; i < apps.length; i++) if (!(t && t.kind === "app" && t.data === apps[i])) out.push({ kind: "app", data: apps[i] })
        for (i = 0; i < files.length; i++) if (!(t && t.kind === "file" && t.data === files[i])) out.push({ kind: "file", data: files[i] })
        for (i = 0; i < pages.length; i++) if (!(t && t.kind === "setting" && t.data === pages[i])) out.push({ kind: "setting", data: pages[i] })
        for (i = 0; i < tabs.length; i++) if (!(t && t.kind === "tab" && t.data === tabs[i])) out.push({ kind: "tab", data: tabs[i] })
        out.push({ kind: "web", data: { text: text.trim() } })
        return out
    }
    function isCurrent(kind, data) { var it = items[current]; return !!it && it.kind === kind && it.data === data }
    function activate(it) {
        if (!it) return
        if (it.kind === "app") Apps.launch(it.data.exec)
        else if (it.kind === "file") SearchData.openFile(it.data.path)
        else if (it.kind === "setting") SearchData.openSetting(it.data.id)
        else if (it.kind === "tab") Tabs.open(it.data.url)
        else if (it.kind === "web") SearchData.web(it.data.text)
        else if (it.kind === "answer") SearchData.copy(it.data.copy)
        else if (it.kind === "resume") { if (it.data.kind === "music") SearchData.resumePlayer(it.data.player); else SearchData.openFile(it.data.path) }
        root.done()
    }
    function islandFor(app, item) {
        if (!app || !item) return
        var p = item.mapToItem(root, item.width / 2, item.height)
        island.open(app)
        island.x = Math.max(8, Math.min(root.width - island.width - 8, p.x - island.width / 2))
        island.y = p.y + island.height + 8 < root.height ? p.y + 4 : Math.max(8, p.y - item.height - island.height - 4)
        island.visible = true
    }

    onTextChanged: { if (input.text !== text) input.text = text; current = 0; SearchData.find(text) }
    readonly property bool others: items.length - (best ? 1 : 0) - (typing ? 1 : 0) > 0
    onScopeChanged: current = 0
    onShownChanged: {
        if (shown) {
            scope = "All"; current = 0; island.visible = false
            SearchData.opened()
            input.text = root.startText
            input.cursorPosition = input.text.length
            SearchData.find(input.text)
            enter.restart()
            Qt.callLater(function () { input.forceActiveFocus() })
        } else {
            enter.stop(); leave.restart()
        }
    }

    // in: the bar drops into place, the islands rise after it (a plain fade with Reduce Motion); out: a quick fade
    property real rise: 0
    ParallelAnimation {
        id: enter
        NumberAnimation { target: bar; property: "opacity"; from: 0; to: 1; duration: root.still ? 120 : 160 }
        NumberAnimation { target: bar; property: "drop"; from: root.still ? 0 : -16; to: 0; duration: root.still ? 0 : 260; easing.type: Easing.OutBack; easing.overshoot: 1.1 }
        SequentialAnimation {
            PauseAnimation { duration: root.still ? 0 : 60 }
            NumberAnimation { target: root; property: "rise"; from: 0; to: 1; duration: root.still ? 120 : 300; easing.type: Easing.OutCubic }
        }
    }
    ParallelAnimation {
        id: leave
        NumberAnimation { target: bar; property: "opacity"; to: 0; duration: 120 }
        NumberAnimation { target: root; property: "rise"; to: 0; duration: 120 }
    }

    MouseArea { anchors.fill: parent; onClicked: { if (island.visible) island.visible = false; else root.done() } }   // a click beside it closes it

    readonly property real w: Math.min(900, width - 80)
    readonly property real lx: (width - w) / 2

    // ---------------------------------------------------------------- the bar
    Glass {
        id: bar
        property real drop: 0
        popup: true; radius: 24
        x: root.lx; y: Math.round(root.height * 0.1) + drop; width: root.w; height: 68
        opacity: 0
        MouseArea { anchors.fill: parent; onClicked: input.forceActiveFocus() }
        Glyph { x: 22; anchors.verticalCenter: parent.verticalCenter; name: "search"; size: 24; ink: Theme.t.accent }
        TextInput {
            id: input
            anchors { left: parent.left; leftMargin: 60; right: scopePill.left; rightMargin: 12; verticalCenter: parent.verticalCenter }
            color: Theme.t.text; font.family: Theme.t.font; font.pixelSize: 22; focus: true; selectByMouse: true; clip: true
            selectionColor: Theme.t.accent; selectedTextColor: Theme.t.onAccent
            onTextChanged: root.text = text
            Label { visible: !input.text; text: "Search apps, files, settings and the web"; color: Theme.t.text_tertiary; font.pixelSize: 22; anchors.verticalCenter: parent.verticalCenter }
            Keys.onPressed: function (e) {
                if (island.visible) { if (e.key === Qt.Key_Escape) { island.visible = false; e.accepted = true } return }
                if (e.key === Qt.Key_Down) { root.current = Math.min(root.items.length - 1, root.current + 1); e.accepted = true }
                else if (e.key === Qt.Key_Up) { root.current = Math.max(0, root.current - 1); e.accepted = true }
                else if (e.key === Qt.Key_Tab) { root.scope = root.scopes[(root.scopes.indexOf(root.scope) + 1) % root.scopes.length]; e.accepted = true }
                else if (e.key === Qt.Key_Backtab) { root.scope = root.scopes[(root.scopes.indexOf(root.scope) + root.scopes.length - 1) % root.scopes.length]; e.accepted = true }
                else if ((e.key === Qt.Key_Return || e.key === Qt.Key_Enter) && (e.modifiers & Qt.ShiftModifier)) { if (root.typing) root.activate({ kind: "web", data: { text: root.text.trim() } }); e.accepted = true }
                else if (e.key === Qt.Key_Return || e.key === Qt.Key_Enter) { root.activate(root.items[root.current]); e.accepted = true }
                else if (e.key === Qt.Key_Menu || (e.key === Qt.Key_F10 && (e.modifiers & Qt.ShiftModifier))) {
                    var it = root.items[root.current]
                    if (it && it.kind === "app") root.islandFor(it.data, bar)
                    e.accepted = true
                }
                else if (e.key === Qt.Key_Escape) { if (input.text) input.text = ""; else root.done(); e.accepted = true }
            }
        }
        Rectangle {
            id: scopePill
            anchors { right: parent.right; rightMargin: 14; verticalCenter: parent.verticalCenter }
            width: scopeRow.width + 20; height: 34; radius: 12; color: Theme.t.hover
            Row {
                id: scopeRow
                anchors.centerIn: parent; spacing: 8
                Label { anchors.verticalCenter: parent.verticalCenter; text: root.scope; font.pixelSize: 13 }
                Rectangle { anchors.verticalCenter: parent.verticalCenter; width: 32; height: 20; radius: 6; color: Theme.t.hover; border.width: 1; border.color: Theme.t.line
                    Label { anchors.centerIn: parent; text: "Tab"; font.pixelSize: 10; font.weight: Font.DemiBold } }
            }
            MouseArea { anchors.fill: parent; onClicked: root.scope = root.scopes[(root.scopes.indexOf(root.scope) + 1) % root.scopes.length] }
        }
    }

    // ---------------------------------------------------------------- pieces
    component Isl: Glass {
        id: isl
        property string title: ""
        property int order: 0
        popup: true; radius: 24
        opacity: Math.max(0, Math.min(1, root.rise * 1.6 - order * 0.12))
        transform: Translate { y: (1 - Math.min(1, root.rise * 1.3)) * (14 + isl.order * 4) }
        MouseArea { anchors.fill: parent; acceptedButtons: Qt.AllButtons }     // (clicks on an island stay there)
        Label { visible: isl.title !== ""; x: 18; y: 14; text: isl.title.toUpperCase(); color: Theme.t.text_tertiary; font.pixelSize: 11; font.weight: Font.DemiBold; font.letterSpacing: 0.7 }
    }
    component ResultRow: Pressable {
        id: rr
        property string kind: ""
        property var item: ({})
        property string title: ""
        property string sub: ""
        property string glyph: "doc"
        property var app: null
        readonly property bool on: root.isCurrent(kind, item)
        width: parent ? parent.width : 300; height: sub ? 50 : 42; radius: 14
        color: on ? Qt.rgba(tintc.r, tintc.g, tintc.b, 0.22) : (hovered ? Theme.t.hover : "transparent")
        border.width: on ? 1 : 0; border.color: Qt.rgba(tintc.r, tintc.g, tintc.b, 0.45)
        readonly property color tintc: app ? root.colourOf(app) : Theme.t.accent
        onHoveredChanged: if (hovered) { var i = root.items.findIndex(function (it) { return it.kind === rr.kind && it.data === rr.item }); if (i >= 0) root.current = i }
        onClicked: root.activate({ kind: rr.kind, data: rr.item })
        AppIcon { visible: !!rr.app; x: 10; anchors.verticalCenter: parent.verticalCenter; size: 32; name: rr.app ? rr.app.name : ""; glyph: rr.app ? rr.app.glyph : ""; image: rr.app ? rr.app.image : ""; own: rr.app ? (rr.app.own || "") : ""; web: rr.app ? rr.app.web : false }
        Rectangle { visible: !rr.app; x: 10; anchors.verticalCenter: parent.verticalCenter; width: 32; height: 32; radius: 10; color: Theme.t.hover
            Glyph { anchors.centerIn: parent; name: rr.glyph; size: 17; ink: Theme.t.icon } }
        Column {
            x: 54; anchors.verticalCenter: parent.verticalCenter; width: parent.width - 64; spacing: 1
            Label { text: rr.title; width: parent.width; elide: Text.ElideRight; font.pixelSize: 14 }
            Label { visible: rr.sub !== ""; text: rr.sub; width: parent.width; elide: Text.ElideMiddle; font.pixelSize: 12; color: Theme.t.text_secondary }
        }
        MouseArea { anchors.fill: parent; acceptedButtons: Qt.RightButton; enabled: !!rr.app; onClicked: root.islandFor(rr.app, rr) }
    }
    component Action: Pressable {
        id: ac
        property string label: ""
        property bool primary: false
        property color fill: Theme.t.accent
        width: acl.width + 28; height: 36; radius: 11
        color: primary ? fill : (hovered ? Theme.t.pressed || Theme.t.hover : Theme.t.hover)
        Label { id: acl; anchors.centerIn: parent; text: ac.label; font.pixelSize: 13; font.weight: ac.primary ? Font.DemiBold : Font.Normal; color: ac.primary ? Theme.t.onAccent : Theme.t.text }
    }

    component List: Isl {
        id: li
        property alias model: rep.model
        property alias delegate: rep.delegate
        visible: rep.count > 0
        width: parent.width; height: visible ? listCol.height + 48 : 0
        Column { id: listCol; x: 8; y: 38; width: parent.width - 16; spacing: 2; Repeater { id: rep } }
    }

    readonly property real top0: bar.y - bar.drop + bar.height + 12

    // ---------------------------------------------------------------- before you type
    Item {
        visible: !root.typing
        x: root.lx; y: root.top0; width: root.w; height: idleRight.height
        Isl {
            id: resumeIsl
            title: "Pick up where you left off"; order: 0
            width: parent.width * 0.53; height: idleRight.height
            Column {
                x: 10; y: 40; width: parent.width - 20; spacing: 4
                Repeater {
                    model: SearchData.resume
                    ResultRow {
                        required property var modelData
                        kind: "resume"; item: modelData; title: modelData.name; sub: modelData.sub
                        glyph: modelData.kind === "music" ? "pause" : "doc"
                    }
                }
                Label {
                    visible: SearchData.resume.length === 0; x: 8; width: parent.width - 16; wrapMode: Text.Wrap
                    text: "Files you open, and music you pause, show up here."; color: Theme.t.text_secondary; font.pixelSize: 13
                }
            }
        }
        Column {
            id: idleRight
            anchors.right: parent.right; width: parent.width * 0.47 - 10; spacing: 10
            Isl {
                title: "Suggested"; order: 1
                width: parent.width; height: 44 + sugg.height + 8
                Grid {
                    id: sugg
                    x: 8; y: 38; columns: 3; width: parent.width - 16
                    Repeater {
                        model: Apps.recent.slice(0, 6)
                        Pressable {
                            id: sp
                            required property var modelData
                            width: sugg.width / 3; height: 88; radius: 14
                            color: root.isCurrent("app", modelData) || hovered ? Theme.t.hover : "transparent"
                            onClicked: root.activate({ kind: "app", data: modelData })
                            AppIcon { y: 10; anchors.horizontalCenter: parent.horizontalCenter; size: 42; name: sp.modelData.name; glyph: sp.modelData.glyph; image: sp.modelData.image; own: sp.modelData.own || ""; web: sp.modelData.web }
                            Label { anchors { bottom: parent.bottom; bottomMargin: 8; horizontalCenter: parent.horizontalCenter } text: sp.modelData.name; font.pixelSize: 12; color: Theme.t.text_secondary; width: parent.width - 8; horizontalAlignment: Text.AlignHCenter; elide: Text.ElideRight }
                            MouseArea { anchors.fill: parent; acceptedButtons: Qt.RightButton; onClicked: root.islandFor(sp.modelData, sp) }
                        }
                    }
                }
            }
            Isl {
                title: "Quick actions"; order: 2
                width: parent.width; height: 40 + quick.height + 12
                Grid {
                    id: quick
                    x: 12; y: 38; columns: 2; spacing: 6; width: parent.width - 24
                    Repeater {
                        model: [{ g: "plus", t: "New note", f: function () { var n = Apps.all.filter(function (a) { return a.name === "Notes" })[0]; if (n) Apps.launch(n.exec) } },
                                { g: "crop", t: "Screenshot", f: function () { Status.screenshot("choose") } },
                                { g: "moon", t: Status.dnd ? "Notifications on" : "Do Not Disturb", f: function () { Status.setDnd(!Status.dnd) } },
                                { g: "lock", t: "Lock screen", f: function () { Status.power("lock") } }]
                        Pressable {
                            id: qa
                            required property var modelData
                            width: (quick.width - 6) / 2; height: 40; radius: 12; color: hovered ? Theme.t.pressed || Theme.t.hover : Theme.t.hover
                            onClicked: { qa.modelData.f(); root.done() }
                            Row { x: 12; anchors.verticalCenter: parent.verticalCenter; spacing: 9
                                Glyph { anchors.verticalCenter: parent.verticalCenter; name: qa.modelData.g; size: 16; ink: Theme.t.icon }
                                Label { anchors.verticalCenter: parent.verticalCenter; text: qa.modelData.t; font.pixelSize: 13 } }
                        }
                    }
                }
            }
        }
    }

    // ---------------------------------------------------------------- what it found
    Item {
        visible: root.typing
        x: root.lx; y: root.top0; width: root.w; height: Math.max(topIsl.height, right.height)
        Isl {
            id: topIsl
            order: 0
            visible: root.best !== null
            title: "Top hit"
            width: root.others ? parent.width * 0.5 : parent.width; height: Math.max(210, right.height)
            readonly property var hit: root.best
            readonly property var app: hit && hit.kind === "app" ? hit.data : null
            readonly property color tint: app ? root.colourOf(app) : Theme.t.accent
            Rectangle {   // its own colour, from the top-left
                anchors.fill: parent; radius: parent.radius; opacity: 0.22
                gradient: Gradient { orientation: Gradient.Horizontal; GradientStop { position: 0; color: topIsl.tint } GradientStop { position: 0.7; color: "transparent" } }
            }
            Rectangle { anchors.fill: parent; radius: parent.radius; color: "transparent"; border.width: root.current === 0 ? 1 : 0; border.color: Qt.rgba(topIsl.tint.r, topIsl.tint.g, topIsl.tint.b, 0.55) }
            Column {
                x: 22; y: 44; width: parent.width - 44; spacing: 14
                // a sum
                Column {
                    visible: !!topIsl.hit && topIsl.hit.kind === "answer"; spacing: 2; width: parent.width
                    Label { text: topIsl.hit && topIsl.hit.kind === "answer" ? topIsl.hit.data.detail : ""; color: Theme.t.text_secondary; font.pixelSize: 14 }
                    Label { text: topIsl.hit && topIsl.hit.kind === "answer" ? topIsl.hit.data.value : ""; font.pixelSize: 44; font.weight: Font.DemiBold; width: parent.width; elide: Text.ElideRight }
                    Label { text: "Worked out on this computer"; color: Theme.t.text_tertiary; font.pixelSize: 12; topPadding: 4 }
                }
                // a picture: the picture itself
                Image {
                    visible: !!topIsl.hit && topIsl.hit.kind === "file" && topIsl.hit.data.kind === "image" && status === Image.Ready
                    width: parent.width; height: 170; fillMode: Image.PreserveAspectCrop; asynchronous: true; smooth: true
                    source: visible || (topIsl.hit && topIsl.hit.kind === "file" && topIsl.hit.data.kind === "image") ? topIsl.hit.data.url : ""
                    sourceSize.width: 600
                }
                Row {
                    visible: !!topIsl.hit && topIsl.hit.kind !== "answer"; spacing: 16; width: parent.width
                    Item {
                        width: 60; height: 60
                        AppIcon { visible: !!topIsl.app; size: 60; name: topIsl.app ? topIsl.app.name : ""; glyph: topIsl.app ? topIsl.app.glyph : ""; image: topIsl.app ? topIsl.app.image : ""; own: topIsl.app ? (topIsl.app.own || "") : ""; web: topIsl.app ? topIsl.app.web : false }
                        Rectangle { visible: !topIsl.app; anchors.fill: parent; radius: 16; color: Theme.t.hover
                            Glyph { anchors.centerIn: parent; size: 28; ink: Theme.t.icon
                                name: !topIsl.hit ? "" : topIsl.hit.kind === "setting" ? topIsl.hit.data.glyph : topIsl.hit.kind === "tab" ? "globe" : (topIsl.hit.data.kind || "doc") } }
                    }
                    Column {
                        anchors.verticalCenter: parent.verticalCenter; width: parent.width - 76; spacing: 3
                        Label {
                            width: parent.width; elide: Text.ElideRight; font.pixelSize: 21; font.weight: Font.DemiBold
                            text: !topIsl.hit ? "" : topIsl.hit.kind === "app" ? topIsl.hit.data.name : topIsl.hit.kind === "setting" ? topIsl.hit.data.label : topIsl.hit.kind === "tab" ? topIsl.hit.data.title : (topIsl.hit.data.name || "")
                        }
                        Label {
                            width: parent.width; elide: Text.ElideMiddle; font.pixelSize: 13; color: Theme.t.text_secondary
                            text: !topIsl.hit ? "" : topIsl.hit.kind === "app" ? (topIsl.hit.data.about || "App") : topIsl.hit.kind === "setting" ? "Settings · " + topIsl.hit.data.sub
                                  : topIsl.hit.kind === "tab" ? "Open tab in Huginn · " + topIsl.hit.data.site : (topIsl.hit.data.where || "") + (topIsl.hit.data.when ? " · " + topIsl.hit.data.when : "")
                        }
                    }
                }
                Row {
                    spacing: 8
                    Action {
                        primary: true; fill: topIsl.tint
                        label: !topIsl.hit ? "" : topIsl.hit.kind === "answer" ? "Copy" : topIsl.hit.kind === "setting" ? "Open in Settings" : topIsl.hit.kind === "tab" ? "Switch to tab" : "Open"
                        onClicked: root.activate(topIsl.hit)
                    }
                    Action { visible: !!topIsl.hit && topIsl.hit.kind === "file"; label: "Show in Files"; onClicked: { SearchData.reveal(topIsl.hit.data.path); root.done() } }
                    Action { visible: !!topIsl.app; label: "More…"; onClicked: root.islandFor(topIsl.app, this) }
                }
            }
        }
        Column {
            id: right
            x: topIsl.visible ? topIsl.width + 10 : 0
            width: parent.width - x; spacing: 10
            List {
                title: "Apps"; order: 1
                model: root.apps.filter(function (a) { return !(root.best && root.best.kind === "app" && root.best.data === a) })
                delegate: ResultRow { required property var modelData; kind: "app"; item: modelData; app: modelData; title: modelData.name; sub: modelData.about || "" }
            }
            List {
                title: "Files"; order: 2
                model: root.files.filter(function (f) { return !(root.best && root.best.kind === "file" && root.best.data === f) }).slice(0, 5)
                delegate: ResultRow { required property var modelData; kind: "file"; item: modelData; title: modelData.name; sub: modelData.where + " · " + modelData.when; glyph: modelData.kind }
            }
            List {
                title: "Settings"; order: 3
                model: root.pages.filter(function (p) { return !(root.best && root.best.kind === "setting" && root.best.data === p) })
                delegate: ResultRow { required property var modelData; kind: "setting"; item: modelData; title: modelData.label; sub: modelData.sub; glyph: modelData.glyph }
            }
            List {
                title: "Huginn · open tabs"; order: 4
                model: root.tabs.filter(function (t) { return !(root.best && root.best.kind === "tab" && root.best.data === t) })
                delegate: ResultRow { required property var modelData; kind: "tab"; item: modelData; title: modelData.title; sub: modelData.site; glyph: "globe" }
            }
            Label {
                visible: !root.best && SearchData.files.length === 0
                width: parent.width; horizontalAlignment: Text.AlignHCenter; topPadding: 20
                text: "Nothing on this computer matches “" + root.text.trim() + "”."; color: Theme.t.text_secondary; font.pixelSize: 13
            }
        }
    }
    Isl {   // the web: always last, and only when you choose it
        visible: root.typing
        order: 5
        x: root.lx; y: root.top0 + Math.max(topIsl.visible ? topIsl.height : 0, right.height) + 10; width: root.w; height: 60
        ResultRow {
            x: 8; y: 6; width: parent.width - 16
            kind: "web"; item: root.items.length ? root.items[root.items.length - 1].data : ({})
            title: "Search the web for “" + root.text.trim() + "”"; sub: "Opens in Huginn · the only result that leaves this computer"; glyph: "globe"
        }
    }

    Row {   // the privacy line: said the first few times
        visible: SearchData.privacyNote && bar.opacity > 0.5
        anchors.horizontalCenter: parent.horizontalCenter
        y: root.height - 140; spacing: 8; opacity: root.rise
        Glyph { anchors.verticalCenter: parent.verticalCenter; name: "shield"; size: 14; ink: Theme.t.accent }
        Label { anchors.verticalCenter: parent.verticalCenter; text: "Searched on this computer. Nothing is sent anywhere until you choose a web result."; font.pixelSize: 12; color: Theme.t.text_secondary }
    }

    AppIsland { id: island; visible: false; z: 50; onDone: { island.visible = false; input.forceActiveFocus() } }
}
