import QtQuick
import QtQuick.Shapes

// Games, "the big screen": one game at a time, large, in the middle of the window, with the next ones peeking in
// from the sides like a console's home screen. The whole window takes on the colour of the game in front. Under it:
// its name and one Play button. The shops are chips above; a film strip along the bottom jumps anywhere. Left and
// Right move, Enter plays. A game's profile is an island that slides in on the right.
GlassWindow {
    id: win
    title: "Games"; width: 1080; height: 760; minimumWidth: 900; minimumHeight: 660; glow: "none"
    readonly property color pick: Qt.rgba(tintColor.r, tintColor.g, tintColor.b, 0.18)
    readonly property var cur: Backend.picked !== "" ? Backend.current : Backend.featured
    readonly property bool has: Backend.summary.games > 0
    property string sheet: ""            // "", "accounts", "add"
    property bool profile: false
    property bool renaming: false
    // The carousel is fed the games' ids, and only when the line-up really changes: the backend hands over a fresh
    // list after every little change, and a carousel that rebuilt each time would jump back to the start.
    property var ids: []
    readonly property var byId: { var m = {}, g = Backend.games; for (var i = 0; i < g.length; i++) m[g[i].id] = g[i]; return m }
    readonly property real stageW: width - (profile ? 392 : 0)
    readonly property real boxH: Math.max(210, Math.min(380, height - 440))
    readonly property real boxW: Math.round(boxH * 0.7)
    readonly property real curHue: hue(cur.name || "games")
    function hue(name) { var h = 0; for (var i = 0; i < name.length; i++) h = (h * 31 + name.charCodeAt(i)) % 360; return h / 360 }
    function initials(name) { var w = name.split(/\s+/).filter(function (x) { return /[A-Za-z0-9]/.test(x) }); return (w.length > 1 ? w[0][0] + w[1][0] : name.slice(0, 2)).toUpperCase() }
    function added(path) { Backend.addGame(path); profile = true; sheet = "" }
    function openAdd() { sheet = "add"; Backend.browse(Backend.folder) }
    function playGame() { if (cur.id && !cur.running) Backend.play(cur.id) }
    function refresh() { Backend.refresh() }
    function lineUp() {
        var g = Backend.games, now = []
        for (var i = 0; i < g.length; i++) now.push(g[i].id)
        if (now.join("\n") !== ids.join("\n")) ids = now
        var at = ids.indexOf(Backend.picked)
        if (at < 0 && ids.length) { at = Math.max(0, Math.min(reel.currentIndex, ids.length - 1)); Backend.choose(ids[at]) }
        if (at >= 0 && reel.currentIndex !== at) reel.currentIndex = at
    }
    function go(step) { if (ids.length) { var at = (reel.currentIndex + step + ids.length) % ids.length; Backend.choose(ids[at]) } }
    Connections { target: Backend; function onSaid(msg, wrong) { toast.say(msg, wrong) } function onChanged() { win.lineUp() } }
    Component.onCompleted: lineUp()
    DropArea { anchors.fill: parent; onDropped: function (drop) { if (drop.hasUrls) for (var i = 0; i < drop.urls.length; i++) Backend.addGame(drop.urls[i]) } }
    Item { id: keys; focus: true; Keys.onLeftPressed: win.go(-1); Keys.onRightPressed: win.go(1); Keys.onReturnPressed: if (win.cur.id && win.sheet === "" && !win.cur.running) Backend.play(win.cur.id) }

    // A game's box: its cover if the shop gave one, otherwise a poster drawn from its name, so no two look alike.
    // Rounded without shaders (so it also draws on a computer with no graphics acceleration): the drawn poster keeps
    // its shapes clear of the corners, and a real cover sits inset in the coloured case like a sleeve in a box.
    component Box: Rectangle { id: bx
        property var game: ({})
        property bool lit: false
        readonly property real h: win.hue(game.name || "x")
        readonly property int seed: Math.round(h * 360)
        radius: width * 0.085; border.width: lit ? Math.max(2, width * 0.012) : 1; border.color: lit ? "#FFFFFF" : "#40FFFFFF"
        gradient: Gradient { GradientStop { position: 0; color: Qt.hsla(bx.h, 0.62, 0.46, 1) } GradientStop { position: 1; color: Qt.hsla((bx.h + 0.09) % 1, 0.7, 0.2, 1) } }
        Item { anchors.fill: parent; visible: !bx.game.cover
            Rectangle { width: parent.width * 0.58; height: width; radius: width / 2; x: parent.width * (0.34 - ((bx.seed * 7) % 20) / 100); y: parent.height * 0.06; color: Qt.hsla((bx.h + 0.5) % 1, 0.75, 0.62, 0.36) }
            Rectangle { width: parent.width * 0.4; height: width; radius: width / 2; x: parent.width * (0.1 + ((bx.seed * 13) % 44) / 100); y: parent.height * (0.36 + ((bx.seed * 3) % 16) / 100); color: Qt.hsla((bx.h + 0.86) % 1, 0.8, 0.66, 0.34) }
            Item { x: bx.border.width; width: parent.width - 2 * x; y: parent.height * 0.3; height: parent.height * 0.45; clip: true
                Rectangle { width: parent.width * 2; height: bx.height * 0.11; x: -parent.width * 0.5; y: parent.height * (0.34 + (bx.seed % 14) / 100); rotation: -22 + (bx.seed % 3) * 5; color: "#24FFFFFF" }
                Rectangle { width: parent.width * 2; height: bx.height * 0.025; x: -parent.width * 0.5; y: parent.height * (0.62 + (bx.seed % 14) / 100); rotation: -22 + (bx.seed % 3) * 5; color: "#33FFFFFF" } }
            Rectangle { x: bx.border.width; width: parent.width - 2 * x; height: parent.height * 0.5 - x; y: parent.height * 0.5; radius: bx.radius; gradient: Gradient { GradientStop { position: 0; color: "#00000000" } GradientStop { position: 1; color: "#A6000000" } } }
            Label { x: parent.width * 0.1; y: parent.height * 0.07; text: win.initials(bx.game.name || "?"); color: "#F2FFFFFF"; font.pixelSize: Math.max(11, parent.width * 0.28); font.weight: Font.Black; font.letterSpacing: -1 }
            Label { visible: parent.width > 90; anchors { left: parent.left; right: parent.right; bottom: parent.bottom; margins: parent.width * 0.1 } wrapMode: Text.WordWrap; maximumLineCount: 3; elide: Text.ElideRight
                text: (bx.game.name || "").toUpperCase(); color: "#FFFFFF"; font.pixelSize: Math.max(9, parent.width * 0.075); font.weight: Font.Bold; font.letterSpacing: 1.2 } }
        Image { visible: !!bx.game.cover; anchors { fill: parent; margins: Math.ceil(bx.radius * 0.32) } source: bx.game.cover || ""; fillMode: Image.PreserveAspectCrop; asynchronous: true; sourceSize.width: 520 }
        Rectangle { visible: !!bx.game.running; anchors { right: parent.right; top: parent.top; margins: Math.max(5, parent.width * 0.07) } width: Math.max(8, parent.width * 0.07); height: width; radius: width / 2; color: "#4ADE80"; border.width: 2; border.color: "#FFFFFF" }
    }

    // ---------------- the room takes the colour of the game in front
    Shape { anchors.fill: parent; z: -1; visible: win.has
        ShapePath { strokeWidth: 0; strokeColor: "transparent"
            fillGradient: RadialGradient { centerX: win.stageW / 2; centerY: win.height * 0.4; focalX: centerX; focalY: centerY; centerRadius: Math.max(win.width * 0.62, win.height * 0.8)
                GradientStop { position: 0; color: Qt.hsla(win.curHue, 0.7, Theme.t.dark ? 0.34 : 0.7, Theme.t.dark ? 0.8 : 0.75); Behavior on color { ColorAnimation { duration: 320 } } }
                GradientStop { position: 0.5; color: Qt.hsla((win.curHue + 0.08) % 1, 0.7, Theme.t.dark ? 0.2 : 0.8, Theme.t.dark ? 0.42 : 0.45); Behavior on color { ColorAnimation { duration: 320 } } }
                GradientStop { position: 1; color: Qt.hsla(win.curHue, 0.6, 0.3, 0) } }
            startX: win.r; startY: 0
            PathLine { x: win.width - win.r; y: 0 } PathArc { x: win.width; y: win.r; radiusX: win.r; radiusY: win.r }
            PathLine { x: win.width; y: win.height - win.r } PathArc { x: win.width - win.r; y: win.height; radiusX: win.r; radiusY: win.r }
            PathLine { x: win.r; y: win.height } PathArc { x: 0; y: win.height - win.r; radiusX: win.r; radiusY: win.r }
            PathLine { x: 0; y: win.r } PathArc { x: 0 + win.r; y: 0; radiusX: win.r; radiusY: win.r } } }
    Image { anchors { fill: parent; margins: 5 } z: -1; source: "grain.png"; fillMode: Image.Tile; smooth: false; visible: win.has }

    islands: [
        Island { anchors { right: parent.right; rightMargin: 12 } y: 12
            IslandField { objectName: "search"; width: 170; placeholder: "Find a game"; onTextChanged: Backend.search(text) }
            Seg { icon: "user"; tip: "Steam accounts"; onClicked: win.sheet = "accounts" }
            Seg { icon: "history"; tip: "Look again"; onClicked: Backend.refresh() }
            Seg { icon: "plus"; text: "Add a Game"; onClicked: win.openAdd() } },
        // ---------------- the shops, as chips
        Island { objectName: "shops"; visible: win.has; x: Math.max(12, (win.stageW - width) / 2); y: 62
            Repeater { model: Backend.shelves
                Pressable { id: sh; required property var modelData; readonly property bool on: Backend.filter === modelData.id; width: shRow.width + 22; height: 30; radius: 11; anchors.verticalCenter: parent.verticalCenter
                    color: on ? Theme.t.accent : hovered ? Theme.t.hover : "transparent"; opacity: modelData.count > 0 || on ? 1 : 0.45; onClicked: Backend.setFilter(modelData.id)
                    Row { id: shRow; anchors.centerIn: parent; spacing: 6
                        Rectangle { visible: sh.modelData.ink !== ""; width: 8; height: 8; radius: 4; color: sh.modelData.ink; anchors.verticalCenter: parent.verticalCenter }
                        Label { text: sh.modelData.name; font.pixelSize: 12; font.weight: sh.on ? Font.DemiBold : Font.Medium; color: sh.on ? Theme.t.onAccent : Theme.t.text }
                        Label { text: sh.modelData.count; font.pixelSize: 11; color: sh.on ? Theme.t.onAccent : Theme.t.text_secondary; anchors.verticalCenter: parent.verticalCenter } } } }
            Pressable { id: runChip; readonly property bool on: Backend.filter === "running"; visible: Backend.summary.running > 0 || on; width: runRow.width + 22; height: 30; radius: 11; anchors.verticalCenter: parent.verticalCenter
                color: on ? Theme.t.accent : hovered ? Theme.t.hover : "transparent"; onClicked: Backend.setFilter(on ? "all" : "running")
                Row { id: runRow; anchors.centerIn: parent; spacing: 6
                    Rectangle { width: 8; height: 8; radius: 4; color: "#4ADE80"; anchors.verticalCenter: parent.verticalCenter }
                    Label { text: "Running"; font.pixelSize: 12; font.weight: Font.Medium; color: runChip.on ? Theme.t.onAccent : Theme.t.text }
                    Label { text: Backend.summary.running; font.pixelSize: 11; color: runChip.on ? Theme.t.onAccent : Theme.t.text_secondary; anchors.verticalCenter: parent.verticalCenter } } } },

        // ---------------- the film strip: every game in the line-up, small, to jump straight to one
        Rectangle { id: strip; objectName: "strip"; visible: win.has && win.ids.length > 1; z: 6; height: 62; radius: 20; color: Theme.t.island; border.width: 1; border.color: Theme.t.islandLine
            width: Math.min(win.stageW - 24, win.ids.length * 40 + 16); x: Math.max(12, (win.stageW - width) / 2); anchors { bottom: parent.bottom; bottomMargin: 14 }
            MouseArea { anchors.fill: parent }
            ListView { id: frames; anchors { fill: parent; leftMargin: 8; rightMargin: 8 } orientation: ListView.Horizontal; clip: true; spacing: 6; model: win.ids; currentIndex: reel.currentIndex; boundsBehavior: Flickable.StopAtBounds
                highlightMoveDuration: 200; preferredHighlightBegin: width / 2 - 17; preferredHighlightEnd: width / 2 + 17; highlightRangeMode: ListView.ApplyRange
                delegate: Item { id: fr; required property string modelData; required property int index; readonly property bool on: reel.currentIndex === index; width: 34; height: frames.height
                    Box { anchors.centerIn: parent; width: fr.on ? 34 : 30; height: fr.on ? 48 : 42; game: win.byId[fr.modelData] || ({}); lit: fr.on; opacity: fr.on || frTap.containsMouse ? 1 : 0.7
                        Behavior on width { NumberAnimation { duration: 120 } } Behavior on height { NumberAnimation { duration: 120 } } }
                    MouseArea { id: frTap; anchors.fill: parent; hoverEnabled: true; onClicked: Backend.choose(fr.modelData) } } } },
        Toast { id: toast; anchors { horizontalCenter: parent.horizontalCenter; bottom: parent.bottom; bottomMargin: 88 } },

        // ---------------- Steam accounts
        Item { anchors.fill: parent; z: 20; visible: win.sheet === "accounts"
            Rectangle { anchors.fill: parent; radius: win.r; color: "#66000000"; MouseArea { anchors.fill: parent; acceptedButtons: Qt.AllButtons; onClicked: win.sheet = "" } }
            Rectangle { anchors.centerIn: parent; width: 560; height: Math.min(parent.height - 80, 150 + Math.max(1, Backend.accounts.length) * 96); radius: 18; color: Theme.t.menu_bg; border.width: 1; border.color: Theme.t.menu_border
                MouseArea { anchors.fill: parent }
                Label { x: 24; y: 20; font.pixelSize: 17; font.weight: Font.DemiBold; text: "Steam accounts" }
                Label { x: 24; y: 46; width: parent.width - 48; wrapMode: Text.WordWrap; secondary: true; font.pixelSize: 12
                    text: Backend.accounts.length ? "Everyone who has signed in to Steam on this computer. Switching closes Steam and starts it as the other account; signing in itself always happens in Steam's own window."
                                                  : Backend.steamFound ? "Nobody has signed in to Steam here yet. Open Steam and sign in; the account then shows up here." : "Steam isn't set up on this computer yet." }
                ListView { id: accs; x: 16; y: 92; width: parent.width - 32; height: parent.height - 150; clip: true; spacing: 8; model: win.sheet === "accounts" ? Backend.accounts : []; boundsBehavior: Flickable.StopAtBounds
                    delegate: Rectangle { id: acc; required property var modelData; width: accs.width; height: 88; radius: 14; color: modelData.active ? win.pick : Theme.t.island; border.width: 1; border.color: modelData.active ? Theme.t.accent : Theme.t.islandLine
                        Rectangle { x: 14; anchors.verticalCenter: parent.verticalCenter; width: 56; height: 56; radius: 14; clip: true; color: Qt.hsla(win.hue(acc.modelData.name), 0.5, 0.42, 1)
                            Label { anchors.centerIn: parent; text: win.initials(acc.modelData.name); color: "#FFFFFF"; font.pixelSize: 20; font.weight: Font.Bold; visible: acc.modelData.avatar === "" }
                            Image { anchors.fill: parent; source: acc.modelData.avatar; sourceSize.width: 112; fillMode: Image.PreserveAspectCrop } }
                        Label { x: 84; y: 12; width: parent.width - 220; elide: Text.ElideRight; text: acc.modelData.name; font.pixelSize: 15; font.weight: Font.DemiBold }
                        Label { x: 84; y: 34; width: parent.width - 220; elide: Text.ElideRight; secondary: true; font.pixelSize: 11; text: acc.modelData.login + (acc.modelData.active ? "  ·  signed in now" : acc.modelData.seenWords ? "  ·  last here " + acc.modelData.seenWords.toLowerCase() : "") }
                        Row { x: 84; y: 56; spacing: 14
                            Label { font.pixelSize: 11; text: acc.modelData.games + (acc.modelData.games === 1 ? " game played here" : " games played here") }
                            Label { font.pixelSize: 11; color: Theme.t.accent; text: acc.modelData.minutes > 0 ? acc.modelData.hours : "" }
                            Label { font.pixelSize: 11; secondary: true; visible: acc.modelData.top !== ""; text: "Most: " + acc.modelData.top } }
                        Btn { visible: !acc.modelData.active; anchors { right: parent.right; rightMargin: 14; verticalCenter: parent.verticalCenter } text: Backend.busy === "switching" ? "Switching…" : "Switch"; opacity: Backend.busy ? 0.5 : 1
                            onClicked: Backend.switchAccount(acc.modelData.id) } } }
                Row { anchors { right: parent.right; rightMargin: 22; bottom: parent.bottom; bottomMargin: 18 } spacing: 8
                    Btn { text: Backend.steamInstalled ? "Open Steam" : "Get Steam"; onClicked: Backend.steamInstalled ? Backend.openSteam() : Backend.getSteam() }
                    Btn { primary: true; text: "Done"; onClicked: win.sheet = "" } }
                Label { anchors { left: parent.left; leftMargin: 24; bottom: parent.bottom; bottomMargin: 24 } width: 250; wrapMode: Text.WordWrap; secondary: true; font.pixelSize: 11; text: "Epic, GOG and Amazon accounts are signed in inside Heroic." } } },

        // ---------------- add a game of your own
        Item { anchors.fill: parent; z: 20; visible: win.sheet === "add"
            Rectangle { anchors.fill: parent; radius: win.r; color: "#66000000"; MouseArea { anchors.fill: parent; acceptedButtons: Qt.AllButtons; onClicked: win.sheet = "" } }
            Rectangle { anchors.centerIn: parent; width: 560; height: Math.min(parent.height - 80, 560); radius: 18; color: Theme.t.menu_bg; border.width: 1; border.color: Theme.t.menu_border
                MouseArea { anchors.fill: parent }
                Label { x: 24; y: 20; font.pixelSize: 17; font.weight: Font.DemiBold; text: "Add a game" }
                Label { x: 24; y: 46; width: parent.width - 48; wrapMode: Text.WordWrap; secondary: true; font.pixelSize: 12; text: "Pick the game's program: a Windows .exe, or a Linux game. You can also drop one onto this window from Files. Games from Steam, Epic, GOG and Amazon appear by themselves." }
                Rectangle { x: 16; y: 90; width: parent.width - 32; height: 36; radius: 10; color: Theme.t.group
                    Pressable { x: 4; y: 4; width: 28; height: 28; radius: 8; onClicked: Backend.browseUp(); Glyph { anchors.centerIn: parent; name: "up"; size: 14 } }
                    Label { x: 40; width: parent.width - 50; height: parent.height; verticalAlignment: Text.AlignVCenter; elide: Text.ElideLeft; text: Backend.folder; font.pixelSize: 12 } }
                ListView { id: files; x: 16; y: 134; width: parent.width - 32; height: parent.height - 192; clip: true; model: win.sheet === "add" ? Backend.listing : []; boundsBehavior: Flickable.StopAtBounds
                    delegate: Pressable { required property var modelData; width: files.width; height: 34; radius: 9; onClicked: { if (modelData.dir) Backend.browse(modelData.path); else win.added(modelData.path) }
                        Glyph { x: 10; anchors.verticalCenter: parent.verticalCenter; name: modelData.dir ? "folder" : "gamepad"; size: 15; ink: modelData.dir ? Theme.t.text_secondary : Theme.t.accent }
                        Label { x: 36; width: parent.width - 46; height: parent.height; verticalAlignment: Text.AlignVCenter; elide: Text.ElideRight; text: modelData.name; font.weight: modelData.dir ? Font.Normal : Font.DemiBold } } }
                Label { visible: Backend.listing.length === 0; anchors.centerIn: files; secondary: true; text: "No folders or games in here" }
                Btn { anchors { right: parent.right; rightMargin: 22; bottom: parent.bottom; bottomMargin: 18 } text: "Cancel"; onClicked: win.sheet = "" } } }
    ]

    // ---------------- nothing yet
    Column { visible: !win.has; anchors.centerIn: parent; spacing: 12; width: 500
        Glyph { name: "gamepad"; size: 64; ink: Theme.t.accent; anchors.horizontalCenter: parent.horizontalCenter }
        Label { anchors.horizontalCenter: parent.horizontalCenter; font.pixelSize: 22; font.weight: Font.Bold; text: "No games yet" }
        Label { width: parent.width; wrapMode: Text.WordWrap; horizontalAlignment: Text.AlignHCenter; secondary: true
            text: "Games you install with Steam appear here by themselves, Windows games included. Epic, GOG and Amazon games appear once they're installed with Heroic, a free launcher for those three shops. You can also add a game of your own." }
        Row { anchors.horizontalCenter: parent.horizontalCenter; spacing: 8
            Btn { primary: true; text: Backend.steamInstalled ? "Open Steam" : "Get Steam"; onClicked: Backend.steamInstalled ? Backend.openSteam() : Backend.getSteam() }
            Btn { text: Backend.heroicInstalled ? "Open Heroic" : "Get Heroic"; onClicked: Backend.heroicInstalled ? Backend.openHeroic() : Backend.getHeroic() }
            Btn { text: "Add a Game"; onClicked: win.openAdd() } } }

    // ---------------- the big screen
    Item { id: stage; visible: win.has; width: win.stageW; height: parent.height
        Behavior on width { NumberAnimation { duration: 200; easing.type: Easing.OutCubic } }
        PathView { id: reel; objectName: "shelf"; x: 0; y: 112; width: parent.width; height: win.boxH + 24; model: win.ids; clip: true
            pathItemCount: Math.min(win.ids.length, width > 900 ? 7 : 5); preferredHighlightBegin: 0.5; preferredHighlightEnd: 0.5; highlightRangeMode: PathView.StrictlyEnforceRange; highlightMoveDuration: 260; snapMode: PathView.SnapToItem
            onCurrentIndexChanged: if (win.ids[currentIndex] !== undefined && win.ids[currentIndex] !== Backend.picked) Backend.choose(win.ids[currentIndex])
            path: Path { startX: reel.width / 2 - win.boxW * 2.9; startY: reel.height / 2
                PathAttribute { name: "size"; value: 0.5 } PathAttribute { name: "dim"; value: 0.25 } PathAttribute { name: "depth"; value: 0 }
                PathLine { x: reel.width / 2 - win.boxW * 0.86; y: reel.height / 2 }
                PathAttribute { name: "size"; value: 0.74 } PathAttribute { name: "dim"; value: 0.7 } PathAttribute { name: "depth"; value: 5 }
                PathLine { x: reel.width / 2; y: reel.height / 2 }
                PathAttribute { name: "size"; value: 1 } PathAttribute { name: "dim"; value: 1 } PathAttribute { name: "depth"; value: 10 }
                PathLine { x: reel.width / 2 + win.boxW * 0.86; y: reel.height / 2 }
                PathAttribute { name: "size"; value: 0.74 } PathAttribute { name: "dim"; value: 0.7 } PathAttribute { name: "depth"; value: 5 }
                PathLine { x: reel.width / 2 + win.boxW * 2.9; y: reel.height / 2 }
                PathAttribute { name: "size"; value: 0.5 } PathAttribute { name: "dim"; value: 0.25 } PathAttribute { name: "depth"; value: 0 } }
            delegate: Item { id: card; required property string modelData; required property int index; readonly property bool front: PathView.isCurrentItem
                width: win.boxW; height: win.boxH; scale: PathView.size || 0.5; opacity: PathView.dim || 0; z: PathView.depth || 0
                Box { anchors.fill: parent; game: win.byId[card.modelData] || ({}); lit: card.front }
                MouseArea { anchors.fill: parent; onClicked: card.front ? null : Backend.choose(card.modelData); onDoubleClicked: Backend.play(card.modelData) } }
            WheelHandler { onWheel: function (w) { win.go(w.angleDelta.y + w.angleDelta.x < 0 ? 1 : -1) } } }
        // one game alone has no neighbours: show it by itself
        Box { visible: win.ids.length === 1; anchors.horizontalCenter: parent.horizontalCenter; y: 124; width: win.boxW; height: win.boxH; game: win.cur; lit: true }
        Pressable { visible: win.ids.length > 1; x: 16; y: reel.y + reel.height / 2 - 22; width: 44; height: 44; radius: 22; color: hovered ? Theme.t.hover : Theme.t.island; border.width: 1; border.color: Theme.t.islandLine; onClicked: win.go(-1); Glyph { anchors.centerIn: parent; name: "back"; size: 16 } }
        Pressable { visible: win.ids.length > 1; x: parent.width - 60; y: reel.y + reel.height / 2 - 22; width: 44; height: 44; radius: 22; color: hovered ? Theme.t.hover : Theme.t.island; border.width: 1; border.color: Theme.t.islandLine; onClicked: win.go(1); Glyph { anchors.centerIn: parent; name: "forward"; size: 16 } }

        Column { id: dock; objectName: "dock"; visible: win.ids.length > 0 && !!win.cur.id; anchors.horizontalCenter: parent.horizontalCenter; y: reel.y + reel.height + 10; width: Math.min(parent.width - 120, 640); spacing: 5
            Label { anchors.horizontalCenter: parent.horizontalCenter; font.pixelSize: 10; font.weight: Font.Bold; font.letterSpacing: 1.8; color: win.cur.running ? "#4ADE80" : Theme.t.text_secondary
                text: win.cur.running ? "PLAYING NOW" : win.cur.kind === "own" ? "YOUR GAME" : "FROM " + (win.cur.shop || "").toUpperCase() }
            Label { width: parent.width; horizontalAlignment: Text.AlignHCenter; elide: Text.ElideRight; text: win.cur.name || ""; font.pixelSize: 30; font.weight: Font.Black }
            Label { width: parent.width; horizontalAlignment: Text.AlignHCenter; elide: Text.ElideRight; secondary: true; font.pixelSize: 12
                text: win.cur.ready === false ? (win.cur.kind === "own" ? "Its file isn't where it was" : "Still downloading in " + win.cur.via)
                    : [win.cur.hours, win.cur.last ? "last played " + win.cur.last.toLowerCase() : "", win.cur.size, win.cur.kind === "own" ? win.cur.runnerName : ""].filter(function (x) { return !!x }).join("  ·  ") }
            Item { width: 1; height: 4 }
            Row { anchors.horizontalCenter: parent.horizontalCenter; spacing: 10
                Pressable { objectName: "profileButton"; width: 48; height: 48; radius: 24; color: win.profile ? Theme.t.accent : hovered ? Theme.t.hover : Theme.t.island; border.width: 1; border.color: Theme.t.islandLine; onClicked: win.profile = !win.profile
                    Glyph { anchors.centerIn: parent; name: "gear"; size: 18; ink: win.profile ? Theme.t.onAccent : Theme.t.icon } }
                Pressable { objectName: "play"; width: playRow.width + 64; height: 48; radius: 24; color: win.cur.running ? Theme.t.island : Theme.t.accent; border.width: win.cur.running ? 1.5 : 0; border.color: Theme.t.accent
                    opacity: win.cur.canRun === false || win.cur.ready === false ? 0.5 : 1; onClicked: win.cur.running ? Backend.stop(win.cur.id) : Backend.play(win.cur.id)
                    Row { id: playRow; anchors.centerIn: parent; spacing: 9
                        Glyph { name: win.cur.running ? "stop" : "play"; size: 16; ink: win.cur.running ? Theme.t.accent : Theme.t.onAccent; anchors.verticalCenter: parent.verticalCenter }
                        Label { text: win.cur.running ? "Stop" : "Play"; color: win.cur.running ? Theme.t.accent : Theme.t.onAccent; font.pixelSize: 17; font.weight: Font.Bold } } }
                Pressable { width: 48; height: 48; radius: 24; color: hovered ? Theme.t.hover : Theme.t.island; border.width: 1; border.color: Theme.t.islandLine; onClicked: Backend.showFolder(win.cur.id); Glyph { anchors.centerIn: parent; name: "folder"; size: 18 } } } }

        Column { visible: win.ids.length === 0; anchors.centerIn: parent; spacing: 12; width: Math.min(parent.width - 60, 400)
            Label { width: parent.width; wrapMode: Text.WordWrap; horizontalAlignment: Text.AlignHCenter; secondary: true
                text: Backend.filter === "epic" || Backend.filter === "gog" || Backend.filter === "amazon" ? (Backend.heroicInstalled ? "Nothing from this shop is installed. Install a game in Heroic and it shows up here." : "Games from this shop come through Heroic, which isn't installed yet.")
                    : Backend.filter === "steam" ? (Backend.steamInstalled ? "No Steam games are installed." : "Steam isn't installed yet.") : Backend.filter === "running" ? "Nothing is running" : Backend.filter === "own" ? "You haven't added a game of your own yet." : "Nothing matches" }
            Btn { visible: Backend.filter === "epic" || Backend.filter === "gog" || Backend.filter === "amazon"; anchors.horizontalCenter: parent.horizontalCenter
                text: Backend.heroicInstalled ? "Open Heroic" : "Get Heroic"; onClicked: Backend.heroicInstalled ? Backend.openHeroic() : Backend.getHeroic() }
            Btn { visible: Backend.filter === "own"; anchors.horizontalCenter: parent.horizontalCenter; text: "Add a Game"; onClicked: win.openAdd() } } }

    // ---------------- a game's profile
    Rectangle { id: pane; objectName: "pane"; visible: win.profile && win.has && !!win.cur.id; anchors { right: parent.right; rightMargin: 12; top: parent.top; topMargin: 64; bottom: parent.bottom; bottomMargin: 14 } width: 378; radius: 22; z: 6
        color: Theme.t.island; border.width: 1; border.color: Theme.t.islandLine; clip: true
        readonly property var g: win.cur
        readonly property bool mine: g.kind === "own"
        readonly property bool heroic: g.via === "Heroic"
        function fill() { if (argsBox.text !== (g.args || "")) argsBox.text = g.args || ""; if (envBox.text !== (g.env || "")) envBox.text = g.env || "" }
        onGChanged: fill()
        Component.onCompleted: fill()
        component Line: Item { property string title: ""; property string hint: ""; default property alias stuff: slot.data; width: parent.width; height: Math.max(44, hintLabel.visible ? 30 + hintLabel.height : 44)
            Label { y: 6; width: parent.width - slot.width - 12; elide: Text.ElideRight; text: parent.title; font.weight: Font.Medium }
            Label { id: hintLabel; visible: parent.hint !== ""; y: 25; width: parent.width - slot.width - 16; wrapMode: Text.WordWrap; text: parent.hint; secondary: true; font.pixelSize: 11 }
            Item { id: slot; anchors { right: parent.right; top: parent.top; topMargin: 4 } width: childrenRect.width; height: 30 } }
        component Choice: Pressable { id: ch; property var options: []; property string value: ""; signal picked(string id)
            readonly property int at: { for (var i = 0; i < options.length; i++) if (options[i].id === value) return i; return 0 }
            width: Math.min(190, chLabel.implicitWidth + 40); height: 30; radius: 10; color: hovered ? Theme.t.hover : Theme.t.group; border.width: 1; border.color: Theme.t.islandLine
            onClicked: if (options.length) picked(options[(at + 1) % options.length].id)
            Label { id: chLabel; x: 12; width: parent.width - 34; height: parent.height; verticalAlignment: Text.AlignVCenter; elide: Text.ElideRight; text: ch.options.length ? ch.options[ch.at].name : ""; font.pixelSize: 12 }
            Glyph { anchors { right: parent.right; rightMargin: 9; verticalCenter: parent.verticalCenter } name: "down"; size: 12; ink: Theme.t.text_secondary } }
        Pressable { anchors { right: parent.right; top: parent.top; margins: 12 } z: 2; width: 28; height: 28; radius: 14; onClicked: win.profile = false; Glyph { anchors.centerIn: parent; name: "x"; size: 13 } }
        Flickable { anchors { fill: parent; margins: 18 } contentHeight: col.height; clip: true; boundsBehavior: Flickable.StopAtBounds
            Column { id: col; width: parent.width; spacing: 6
                Label { text: "PROFILE"; color: Theme.t.accent; font.pixelSize: 10; font.weight: Font.Bold; font.letterSpacing: 1.4 }
                Item { width: parent.width; height: 40
                    Label { visible: !win.renaming; width: parent.width - 70; height: 36; verticalAlignment: Text.AlignVCenter; elide: Text.ElideRight; text: pane.g.name || ""; font.pixelSize: 20; font.weight: Font.Bold }
                    TextBox { id: nameBox; objectName: "nameBox"; visible: win.renaming; width: parent.width - 70; onAccepted: { Backend.rename(pane.g.id, text); win.renaming = false } }
                    Btn { visible: pane.mine; anchors.right: parent.right; y: 3; height: 28; text: win.renaming ? "Save" : "Rename"
                        onClicked: { if (win.renaming) { Backend.rename(pane.g.id, nameBox.text); win.renaming = false } else { nameBox.text = pane.g.name; win.renaming = true; nameBox.focusIn() } } } }
                Label { width: parent.width; wrapMode: Text.WrapAnywhere; maximumLineCount: 2; elide: Text.ElideRight; secondary: true; font.pixelSize: 11; text: pane.g.where || "" }
                Rectangle { visible: !pane.mine; width: parent.width; height: steamNote.height + 20; radius: 12; color: win.pick
                    Label { id: steamNote; x: 12; y: 10; width: parent.width - 24; wrapMode: Text.WordWrap; font.pixelSize: 11
                        text: pane.heroic ? "Heroic starts this " + (pane.g.shop || "") + " game and keeps its settings: which Wine or Proton, the overlay, arguments, cloud saves. Change them in Heroic; Games shows it and plays it."
                                          : "Steam starts this game, with its own Proton. Set the switches below, then copy the line they make into the game's Launch Options in Steam." } }
                Btn { visible: pane.heroic; text: "Open Heroic"; onClicked: Backend.openHeroic() }
                Column { visible: !pane.heroic; width: parent.width; spacing: 6

                Item { width: 1; height: 6 }
                Label { visible: pane.mine; text: "COMPATIBILITY"; secondary: true; font.pixelSize: 10; font.weight: Font.Bold; font.letterSpacing: 1.4 }
                Line { visible: pane.mine; title: "Runs with"; hint: pane.g.canRun === false ? "Needs Steam (for Proton) or Wine" : "Now: " + (pane.g.runnerName || "")
                    Choice { objectName: "runner"; options: Backend.runners; value: pane.g.runner || "auto"; onPicked: function (id) { Backend.setOption(pane.g.id, "runner", id) } } }
                Line { title: "Lock waiting (sync)"; hint: "How Windows' way of waiting is imitated. Change it only if a game stutters or hangs."
                    Choice { objectName: "sync"; options: Backend.syncs; value: pane.g.sync || ""; onPicked: function (id) { Backend.setOption(pane.g.id, "sync", id) } } }
                Line { title: "Game's language"; hint: "For games that pick their language from the computer's"
                    Choice { options: Backend.langs; value: pane.g.lang || ""; onPicked: function (id) { Backend.setOption(pane.g.id, "lang", id) } } }
                Line { title: "Skip in-game videos"; hint: "For a game that hangs on its intro film: videos are not played at all"
                    Toggle { on: !!pane.g.novideo; onToggled: function (v) { Backend.setOption(pane.g.id, "novideo", v) } } }

                Item { width: 1; height: 6 }
                Label { text: "PERFORMANCE"; secondary: true; font.pixelSize: 10; font.weight: Font.Bold; font.letterSpacing: 1.4 }
                Line { title: "Performance overlay"; hint: Backend.tools.mangohud ? "Frames per second and temperatures over the game (MangoHud)" : "MangoHud isn't installed"; opacity: Backend.tools.mangohud ? 1 : 0.5
                    Toggle { objectName: "overlay"; on: !!pane.g.overlay; onToggled: function (v) { Backend.setOption(pane.g.id, "overlay", v) } } }
                Line { title: "GameMode"; hint: Backend.tools.gamemode ? "Asks the computer for full speed while the game runs" : "GameMode isn't installed"; opacity: Backend.tools.gamemode ? 1 : 0.5
                    Toggle { on: !!pane.g.gamemode; onToggled: function (v) { Backend.setOption(pane.g.id, "gamemode", v) } } }

                Item { width: 1; height: 6 }
                Label { text: "STARTING IT"; secondary: true; font.pixelSize: 10; font.weight: Font.Bold; font.letterSpacing: 1.4 }
                Label { text: "Launch arguments"; font.weight: Font.Medium }
                TextBox { id: argsBox; objectName: "argsBox"; width: parent.width; mono: true; placeholder: "-windowed -skipintro"; onEdited: Backend.setOption(pane.g.id, "args", text) }
                Label { text: "Environment variables"; font.weight: Font.Medium }
                TextBox { id: envBox; objectName: "envBox"; width: parent.width; mono: true; placeholder: "DXVK_HUD=fps  NAME=value"; onEdited: Backend.setOption(pane.g.id, "env", text) }

                Item { width: 1; height: 6 }
                Label { text: "DLL PREFERENCES"; secondary: true; font.pixelSize: 10; font.weight: Font.Bold; font.letterSpacing: 1.4 }
                Label { width: parent.width; wrapMode: Text.WordWrap; secondary: true; font.pixelSize: 11; text: "Mods and fixes often ship their own copy of a Windows file such as dinput8. Say whose copy wins." }
                Repeater { model: pane.g.dllList || []
                    Rectangle { required property var modelData; width: parent.width; height: 36; radius: 10; color: Theme.t.group
                        Label { x: 12; height: parent.height; verticalAlignment: Text.AlignVCenter; text: modelData.name + ".dll"; font.family: Theme.t.fontMono; font.pixelSize: 12 }
                        Row { anchors { right: parent.right; rightMargin: 6; verticalCenter: parent.verticalCenter } spacing: 4
                            Pressable { width: dl.width + 18; height: 26; radius: 8; color: Theme.t.capsule; border.width: 1; border.color: Theme.t.capsule_border; onClicked: Backend.setDll(pane.g.id, modelData.name, modelData.how === "native" ? "builtin" : "native")
                                Label { id: dl; anchors.centerIn: parent; font.pixelSize: 11; text: modelData.how === "native" ? "The game's copy" : "Wine's copy" } }
                            Pressable { width: 26; height: 26; radius: 8; onClicked: Backend.setDll(pane.g.id, modelData.name, ""); Glyph { anchors.centerIn: parent; name: "x"; size: 11 } } } } }
                Row { width: parent.width; spacing: 6
                    TextBox { id: dllBox; objectName: "dllBox"; width: parent.width - 66; mono: true; placeholder: "dinput8"; onAccepted: { Backend.setDll(pane.g.id, text, "native"); text = "" } }
                    Btn { y: 3; text: "Add"; onClicked: { Backend.setDll(pane.g.id, dllBox.text, "native"); dllBox.text = "" } } }

                Item { width: 1; height: 6 }
                Rectangle { visible: pane.g.kind === "steam"; width: parent.width; height: lineCol.height + 22; radius: 12; color: Theme.t.group
                    Column { id: lineCol; x: 12; y: 11; width: parent.width - 24; spacing: 8
                        Label { text: "Launch Options line"; font.weight: Font.Medium }
                        Label { objectName: "line"; width: parent.width; wrapMode: Text.WrapAnywhere; font.family: Theme.t.fontMono; font.pixelSize: 11; text: pane.g.line || "Nothing to add: the switches above are all at their usual setting."; opacity: pane.g.line ? 1 : 0.6 }
                        Row { spacing: 6
                            Btn { primary: true; text: "Copy"; opacity: pane.g.line ? 1 : 0.5; onClicked: Backend.copyLine(pane.g.id) }
                            Btn { text: "Open in Steam"; onClicked: Backend.steamProperties(pane.g.id) } } } }
                }
                Label { visible: pane.mine && !!pane.g.windows; width: parent.width; wrapMode: Text.WrapAnywhere; secondary: true; font.pixelSize: 11; text: "Its Windows bottle (saves and settings): " + (pane.g.prefix || "") }
                Btn { visible: pane.mine; danger: true; text: "Take Off the Shelf"; onClicked: { Backend.removeGame(pane.g.id); win.profile = false } }
                Label { visible: pane.mine; width: parent.width; wrapMode: Text.WordWrap; secondary: true; font.pixelSize: 11; text: "Only removes it from this list. The game's files and saves stay." }
                Item { width: 1; height: 10 } } } }
}

