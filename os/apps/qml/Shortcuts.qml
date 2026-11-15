import QtQuick

// Shortcuts, "the recipe cards": every shortcut is a bright card of its own colour (press ▶ to run it), and opening
// one shows its recipe as a chain: the WHEN block at the top, then each DO step hanging from it in order, joined by
// a thread. Starters wait at the bottom as dashed cards, one click to add.
GlassWindow {
    id: win
    title: "Shortcuts"; width: 1120; height: 760; minimumWidth: 880; minimumHeight: 560; glow: "right"
    readonly property bool editing: !!Backend.current.id
    readonly property var cur: Backend.current
    readonly property var swatches: ["#FF4FC3", "#FF5A36", "#FF9F1C", "#FFC53D", "#3DDC6E", "#10B981", "#22B8CF", "#3D7BFF", "#7C9CFF", "#A855F7", "#FB7185", "#94A3B8"]
    readonly property var glyphs: ["play", "sun", "moon", "home", "image", "phone", "wifi", "bell", "music", "doc", "edit", "star", "clock", "download", "shield", "gamepad"]
    property bool addingStep: false
    Connections { target: Backend; function onSaid(msg, wrong) { toast.say(msg, wrong) } }
    function setWhen(extra) { var w = JSON.parse(JSON.stringify(win.cur.whenData || { kind: "manual" })); for (var k in extra) w[k] = extra[k]; Backend.setWhen(win.cur.id, w) }

    component Tag: Rectangle { property alias text: tagText.text; property color ink: "#FFFFFF"; width: tagText.width + 16; height: 22; radius: 11; color: "#33FFFFFF"
        Label { id: tagText; anchors.centerIn: parent; font.pixelSize: 10; font.weight: Font.DemiBold; color: parent.ink } }

    islands: [
        Island { anchors { right: parent.right; rightMargin: 12 } y: 12
            Rectangle { width: watchRow.width + 20; height: 28; radius: 14; color: "transparent"; anchors.verticalCenter: parent.verticalCenter
                Row { id: watchRow; anchors.centerIn: parent; spacing: 6
                    Rectangle { width: 8; height: 8; radius: 4; anchors.verticalCenter: parent.verticalCenter; color: Backend.watching ? "#3DDC6E" : Theme.t.text_secondary }
                    Label { font.pixelSize: 12; secondary: true; text: Backend.watching ? "Watching for triggers" : "Not watching yet" } } }
            IslandGap {}
            Seg { objectName: "newShortcut"; icon: "plus"; text: "New Shortcut"; onClicked: Backend.create() } },
        Toast { id: toast; anchors { horizontalCenter: parent.horizontalCenter; bottom: parent.bottom; bottomMargin: 22 } }
    ]

    // ---------------- the cards
    Flickable { id: board; x: 16; y: 64; width: parent.width - 32 - (win.editing ? 440 : 0); height: parent.height - 64 - 12; contentHeight: boardCol.height + 20; clip: true; boundsBehavior: Flickable.StopAtBounds
        Behavior on width { NumberAnimation { duration: 180; easing.type: Easing.OutCubic } }
        Column { id: boardCol; width: board.width; spacing: 18
            Flow { id: cards; objectName: "cards"; width: parent.width; spacing: 14
                Repeater { model: Backend.shortcuts
                    Pressable { id: tile; required property var modelData; readonly property bool on: Backend.current.id === modelData.id
                        width: 214; height: 146; radius: 24; color: modelData.colour; opacity: modelData.auto && !modelData.on ? 0.5 : 1
                        border.width: on ? 3 : 0; border.color: Theme.t.text
                        onClicked: Backend.choose(on ? "" : modelData.id)
                        Rectangle { anchors.fill: parent; radius: parent.radius; gradient: Gradient { GradientStop { position: 0; color: "#26FFFFFF" } GradientStop { position: 1; color: "#26000000" } } }
                        Rectangle { x: 16; y: 16; width: 40; height: 40; radius: 13; color: "#33FFFFFF"; Glyph { anchors.centerIn: parent; name: tile.modelData.glyph; size: 20; ink: "#FFFFFF" } }
                        Pressable { visible: !tile.modelData.auto; anchors { right: parent.right; top: parent.top; margins: 14 } width: 38; height: 38; radius: 19; color: hovered ? "#FFFFFF" : "#40FFFFFF"
                            onClicked: Backend.runNow(tile.modelData.id); Glyph { anchors.centerIn: parent; name: "play"; size: 15; ink: parent.hovered ? tile.modelData.colour : "#FFFFFF" } }
                        Toggle { visible: tile.modelData.auto; anchors { right: parent.right; top: parent.top; margins: 18 } on: tile.modelData.on; onToggled: function (v) { Backend.set(tile.modelData.id, "on", v) } }
                        Label { x: 16; y: 74; width: parent.width - 32; elide: Text.ElideRight; text: tile.modelData.name; color: "#FFFFFF"; font.pixelSize: 16; font.weight: Font.Bold }
                        Label { x: 16; y: 96; width: parent.width - 32; elide: Text.ElideRight; text: tile.modelData.when; color: "#E6FFFFFF"; font.pixelSize: 11 }
                        Label { x: 16; y: 116; width: parent.width - 32; elide: Text.ElideRight; font.pixelSize: 10; color: tile.modelData.lastOk ? "#B3FFFFFF" : "#FFFFFF"; font.weight: tile.modelData.lastOk ? Font.Normal : Font.Bold
                            text: tile.modelData.last ? (tile.modelData.lastOk ? "Ran " : "Stopped ") + tile.modelData.last : tile.modelData.chain.length + (tile.modelData.chain.length === 1 ? " step" : " steps") } } }
                Pressable { width: 214; height: 146; radius: 24; color: hovered ? Theme.t.hover : "transparent"; border.width: 1.5; border.color: Theme.t.capsule_border; onClicked: Backend.create()
                    Glyph { anchors.centerIn: parent; anchors.verticalCenterOffset: -10; name: "plus"; size: 26; ink: Theme.t.text_secondary }
                    Label { anchors { horizontalCenter: parent.horizontalCenter; bottom: parent.bottom; bottomMargin: 30 } text: "New Shortcut"; secondary: true } } }
            Label { visible: Backend.starters.length > 0; text: "STARTERS"; font.pixelSize: 11; font.weight: Font.Bold; font.letterSpacing: 1.2; secondary: true; topPadding: 6 }
            Flow { width: parent.width; spacing: 14; visible: Backend.starters.length > 0
                Repeater { model: Backend.starters
                    Pressable { required property var modelData; width: 214; height: 168; radius: 24; color: hovered ? Theme.t.hover : Theme.t.island; border.width: 1; border.color: Theme.t.islandLine
                        onClicked: Backend.addStarter(modelData.index)
                        Rectangle { x: 16; y: 16; width: 34; height: 34; radius: 11; color: modelData.colour; Glyph { anchors.centerIn: parent; name: modelData.glyph; size: 16; ink: "#FFFFFF" } }
                        Label { x: 60; y: 16; width: parent.width - 76; elide: Text.ElideRight; text: modelData.name; font.weight: Font.DemiBold }
                        Label { x: 60; y: 35; width: parent.width - 76; elide: Text.ElideRight; text: modelData.when; font.pixelSize: 10; color: Theme.t.accent }
                        Label { x: 16; y: 62; width: parent.width - 32; wrapMode: Text.WordWrap; maximumLineCount: 4; elide: Text.ElideRight; text: modelData.about; font.pixelSize: 11; secondary: true }
                        Label { x: 16; anchors { bottom: parent.bottom; bottomMargin: 14 } text: "Add"; font.pixelSize: 12; font.weight: Font.DemiBold; color: Theme.t.accent } } } } } }

    // ---------------- the recipe
    Rectangle { id: pane; objectName: "recipe"; visible: win.editing; anchors { right: parent.right; rightMargin: 12; top: parent.top; topMargin: 62; bottom: parent.bottom; bottomMargin: 12 } width: 428; radius: 24
        color: Theme.t.island; border.width: 1; border.color: Theme.t.islandLine; clip: true
        Pressable { anchors { right: parent.right; top: parent.top; margins: 12 } z: 3; width: 28; height: 28; radius: 14; onClicked: Backend.choose(""); Glyph { anchors.centerIn: parent; name: "x"; size: 13 } }
        Flickable { anchors { fill: parent; margins: 18; bottomMargin: 66 } contentHeight: recipe.height + 10; clip: true; boundsBehavior: Flickable.StopAtBounds
            Column { id: recipe; width: parent.width; spacing: 10
                TextBox { id: nameBox; objectName: "nameBox"; width: parent.width - 40; text: win.cur.name || ""; onEdited: Backend.set(win.cur.id, "name", text) }
                Flow { width: parent.width; spacing: 6
                    Repeater { model: win.swatches; Pressable { required property string modelData; width: 22; height: 22; radius: 11; color: modelData; border.width: win.cur.colour === modelData ? 2 : 0; border.color: Theme.t.text
                        onClicked: Backend.set(win.cur.id, "colour", modelData) } } }
                Flow { width: parent.width; spacing: 4
                    Repeater { model: win.glyphs; Pressable { required property string modelData; width: 28; height: 28; radius: 9; color: win.cur.glyph === modelData ? Theme.t.accent : hovered ? Theme.t.hover : "transparent"
                        onClicked: Backend.set(win.cur.id, "glyph", modelData); Glyph { anchors.centerIn: parent; name: modelData; size: 14; ink: win.cur.glyph === modelData ? Theme.t.onAccent : Theme.t.icon } } } }

                // WHEN
                Rectangle { objectName: "whenBlock"; width: parent.width; height: whenCol.height + 28; radius: 18; color: win.cur.colour || Theme.t.accent
                    Column { id: whenCol; x: 14; y: 14; width: parent.width - 28; spacing: 8
                        Label { text: "WHEN"; color: "#FFFFFF"; font.pixelSize: 10; font.weight: Font.Black; font.letterSpacing: 1.6 }
                        Flow { width: parent.width; spacing: 4
                            Repeater { model: Backend.triggers
                                Pressable { required property var modelData; readonly property bool on: (win.cur.kind || "manual") === modelData.id; width: trig.width + 18; height: 26; radius: 13; color: on ? "#FFFFFF" : "#33FFFFFF"
                                    onClicked: Backend.setWhen(win.cur.id, { kind: modelData.id, at: "08:00", below: 20 })
                                    Label { id: trig; anchors.centerIn: parent; text: modelData.name; font.pixelSize: 11; color: parent.on ? "#141414" : "#FFFFFF" } } } }
                        Row { visible: win.cur.kind === "time"; spacing: 6
                            TextBox { id: atBox; objectName: "atBox"; width: 80; text: win.cur.whenData ? (win.cur.whenData.at || "08:00") : ""; onAccepted: win.setWhen({ at: text }); onEdited: if (/^\d{1,2}[:.]\d\d$/.test(text)) win.setWhen({ at: text }) }
                            Repeater { model: Backend.days
                                Pressable { required property string modelData; readonly property bool on: !win.cur.whenData || !win.cur.whenData.days || win.cur.whenData.days.indexOf(modelData) >= 0
                                    width: 30; height: 30; radius: 15; y: 3; color: on ? "#FFFFFF" : "#33FFFFFF"
                                    onClicked: { var d = (win.cur.whenData.days || Backend.days).slice(); var i = d.indexOf(modelData); if (i >= 0) d.splice(i, 1); else d.push(modelData); win.setWhen({ days: d }) }
                                    Label { anchors.centerIn: parent; text: modelData.charAt(0); font.pixelSize: 11; font.weight: Font.Bold; color: parent.on ? "#141414" : "#FFFFFF" } } } }
                        TextBox { visible: win.cur.kind === "wifi" || win.cur.kind === "phone" || win.cur.kind === "drive"; width: parent.width
                            placeholder: win.cur.kind === "wifi" ? "The network's name" : win.cur.kind === "phone" ? "Any phone, or its name" : "Any drive, or its name"
                            text: win.cur.whenData ? (win.cur.whenData.name || win.cur.whenData.label || "") : ""; onEdited: win.setWhen(win.cur.kind === "drive" ? { label: text } : { name: text }) }
                        Row { visible: win.cur.kind === "battery"; spacing: 8
                            Label { anchors.verticalCenter: parent.verticalCenter; text: "Below"; color: "#FFFFFF" }
                            Repeater { model: [10, 15, 20, 30]; Pressable { required property int modelData; readonly property bool on: !!(win.cur.whenData && win.cur.whenData.below === modelData)
                                width: 46; height: 28; radius: 14; color: on ? "#FFFFFF" : "#33FFFFFF"; onClicked: win.setWhen({ below: modelData })
                                Label { anchors.centerIn: parent; text: modelData + "%"; font.pixelSize: 11; color: parent.on ? "#141414" : "#FFFFFF" } } } }
                        Label { visible: win.cur.kind === "manual"; width: parent.width; wrapMode: Text.WordWrap; color: "#E6FFFFFF"; font.pixelSize: 11; text: "Press ▶ on its card, or put it in the apps menu." }
                        Label { visible: win.cur.kind === "drive"; width: parent.width; wrapMode: Text.WordWrap; color: "#E6FFFFFF"; font.pixelSize: 11; text: "Steps can use {drive}, where the drive is." }
                        Label { visible: win.cur.kind === "login"; width: parent.width; wrapMode: Text.WordWrap; color: "#E6FFFFFF"; font.pixelSize: 11; text: "Runs each time you sign in." } } }

                // DO, as a chain
                Repeater { id: chain; model: win.cur.steps || []
                    Column { id: link; required property var modelData; required property int index; width: recipe.width; spacing: 0
                        Rectangle { anchors.horizontalCenter: parent.horizontalCenter; width: 3; height: 16; radius: 1.5; color: win.cur.colour || Theme.t.accent; opacity: 0.6 }
                        Rectangle { width: parent.width; height: stepCol.height + 24; radius: 16; color: Theme.t.group; border.width: 1; border.color: Theme.t.islandLine
                            Rectangle { x: 12; y: 12; width: 24; height: 24; radius: 12; color: win.cur.colour || Theme.t.accent; Label { anchors.centerIn: parent; text: link.index + 1; color: "#FFFFFF"; font.pixelSize: 11; font.weight: Font.Bold } }
                            Row { anchors { right: parent.right; rightMargin: 8 } y: 8; spacing: 2
                                Pressable { width: 26; height: 26; radius: 8; opacity: link.index > 0 ? 1 : 0.3; onClicked: Backend.moveStep(win.cur.id, link.index, -1); Glyph { anchors.centerIn: parent; name: "up"; size: 12 } }
                                Pressable { width: 26; height: 26; radius: 8; opacity: link.index < chain.count - 1 ? 1 : 0.3; onClicked: Backend.moveStep(win.cur.id, link.index, 1); Glyph { anchors.centerIn: parent; name: "down"; size: 12 } }
                                Pressable { width: 26; height: 26; radius: 8; onClicked: Backend.removeStep(win.cur.id, link.index); Glyph { anchors.centerIn: parent; name: "x"; size: 11 } } }
                            Column { id: stepCol; x: 46; y: 14; width: parent.width - 60; spacing: 6
                                Label { text: win.cur.chain ? win.cur.chain[link.index] : ""; width: parent.width - 90; elide: Text.ElideRight; font.weight: Font.DemiBold }
                                Flow { visible: link.modelData.do === "app"; width: parent.width - 10; spacing: 4
                                    Repeater { model: link.modelData.do === "app" ? Backend.appList.slice(0, 60) : []
                                        Pressable { required property var modelData; readonly property bool on: link.modelData.app === modelData.id; width: appName.width + 16; height: 24; radius: 12
                                            color: on ? Theme.t.accent : hovered ? Theme.t.hover : "transparent"; border.width: 1; border.color: Theme.t.islandLine; onClicked: Backend.setStep(win.cur.id, link.index, { app: modelData.id })
                                            Label { id: appName; anchors.centerIn: parent; text: modelData.name; font.pixelSize: 11; color: parent.on ? Theme.t.onAccent : Theme.t.text } } } }
                                TextBox { visible: ["site", "file", "command"].indexOf(link.modelData.do) >= 0; width: parent.width - 10; mono: link.modelData.do === "command"
                                    placeholder: link.modelData.do === "site" ? "example.com" : link.modelData.do === "file" ? "~/Documents/Plans.odt" : "a command for the shell"
                                    text: link.modelData.url || link.modelData.path || link.modelData.command || ""
                                    onEdited: Backend.setStep(win.cur.id, link.index, link.modelData.do === "site" ? { url: text } : link.modelData.do === "file" ? { path: text } : { command: text }) }
                                Label { visible: link.modelData.do === "command"; width: parent.width - 10; wrapMode: Text.WordWrap; font.pixelSize: 10; color: Theme.t.danger; text: "Runs exactly what you type, as you. Only use commands you understand." }
                                TextBox { visible: link.modelData.do === "notify"; width: parent.width - 10; placeholder: "Title"; text: link.modelData.title || ""; onEdited: Backend.setStep(win.cur.id, link.index, { title: text }) }
                                TextBox { visible: link.modelData.do === "notify"; width: parent.width - 10; placeholder: "Words (optional)"; text: link.modelData.text || ""; onEdited: Backend.setStep(win.cur.id, link.index, { text: text }) }
                                Row { visible: link.modelData.do === "wait" || link.modelData.do === "volume"; spacing: 4
                                    Repeater { model: link.modelData.do === "wait" ? [2, 5, 10, 30, 60] : [0, 25, 50, 75, 100]
                                        Pressable { required property int modelData; readonly property bool on: (link.modelData.do === "wait" ? link.modelData.seconds : link.modelData.level) === modelData
                                            width: wv.width + 16; height: 26; radius: 13; color: on ? Theme.t.accent : hovered ? Theme.t.hover : "transparent"; border.width: 1; border.color: Theme.t.islandLine
                                            onClicked: Backend.setStep(win.cur.id, link.index, link.modelData.do === "wait" ? { seconds: modelData } : { level: modelData })
                                            Label { id: wv; anchors.centerIn: parent; font.pixelSize: 11; color: parent.on ? Theme.t.onAccent : Theme.t.text
                                                text: link.modelData.do === "wait" ? modelData + " s" : modelData === 0 ? "Mute" : modelData + "%" } } } }
                                Row { visible: link.modelData.do === "wifi"; spacing: 4
                                    Seg { text: "On"; on: !!link.modelData.on; onClicked: Backend.setStep(win.cur.id, link.index, { on: true }) }
                                    Seg { text: "Off"; on: !link.modelData.on; onClicked: Backend.setStep(win.cur.id, link.index, { on: false }) } }
                                Label { visible: link.modelData.do === "photos"; width: parent.width - 10; wrapMode: Text.WordWrap; font.pixelSize: 11; secondary: true
                                    text: "New photos and videos go to Pictures/Imported, in a folder for the day. Ones copied before are skipped." } } } } }

                Rectangle { anchors.horizontalCenter: parent.horizontalCenter; width: 3; height: 16; radius: 1.5; color: win.cur.colour || Theme.t.accent; opacity: 0.6 }
                Pressable { objectName: "addStep"; width: parent.width; height: 40; radius: 14; color: hovered ? Theme.t.hover : "transparent"; border.width: 1.5; border.color: Theme.t.capsule_border
                    onClicked: win.addingStep = !win.addingStep
                    Row { anchors.centerIn: parent; spacing: 6; Glyph { name: "plus"; size: 14; anchors.verticalCenter: parent.verticalCenter } Label { text: "Add a step"; font.weight: Font.DemiBold } } }
                Flow { visible: win.addingStep; width: parent.width; spacing: 6
                    Repeater { model: Backend.stepKinds
                        Pressable { required property var modelData; width: sk.width + 20; height: 30; radius: 15; color: hovered ? Theme.t.hover : Theme.t.group; border.width: 1; border.color: Theme.t.islandLine
                            onClicked: { Backend.addStep(win.cur.id, modelData.id); win.addingStep = false }
                            Label { id: sk; anchors.centerIn: parent; text: modelData.name; font.pixelSize: 12 } } } }
                Label { visible: !!win.cur.lastWords; width: parent.width; wrapMode: Text.WordWrap; font.pixelSize: 11; color: win.cur.lastOk ? Theme.t.text_secondary : Theme.t.danger
                    text: "Last run " + (win.cur.last || "") + ": " + (win.cur.lastWords || "") } } }
        Row { anchors { left: parent.left; leftMargin: 18; bottom: parent.bottom; bottomMargin: 16 } spacing: 8
            Btn { objectName: "runNow"; primary: true; text: "Run Now"; onClicked: Backend.runNow(win.cur.id) }
            Btn { danger: true; text: "Delete"; onClicked: Backend.remove(win.cur.id) } }
        Row { visible: !win.cur.auto; anchors { right: parent.right; rightMargin: 18; bottom: parent.bottom; bottomMargin: 20 } spacing: 8
            Label { anchors.verticalCenter: parent.verticalCenter; font.pixelSize: 12; text: "In the apps menu" }
            Toggle { on: !!win.cur.menu; onToggled: function (v) { Backend.set(win.cur.id, "menu", v) } } } }
}
