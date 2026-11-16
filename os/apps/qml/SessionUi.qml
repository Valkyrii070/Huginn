import QtQuick
import QtQuick.Window
import QtQuick.Shapes

// The session daemon's windows: notification banners (top right), the level for volume, brightness and the
// microphone (bottom middle), and its questions (a Wi‑Fi password, a Bluetooth code, the power button, the battery)
// in the middle. Each is a window of its own, shown only while it has something in it.
QtObject {
    id: ui
    function make(role, body, w, h, input) {
        var c = layerShell ? Qt.createComponent("SessionLayer.qml") : null
        if (!c || c.status !== Component.Ready)
            c = Qt.createComponent("SessionWindow.qml")
        return c.createObject(null, { role: role, body: body, width: w, height: h, takesInput: input })
    }
    readonly property var bannersWin: make("banners", bannersBody, 400, 120, true)
    readonly property var osdWin: make("osd", osdBody, 320, 180, false)
    readonly property var promptWin: make("prompt", promptBody, 460, 300, true)
    readonly property bool hasBanners: Notifier.shown.length > 0
    readonly property bool hasOsd: Session.osdState.kind !== ""
    readonly property bool hasPrompt: !!Session.prompt.uid
    onHasBannersChanged: bannersWin.visible = hasBanners
    onHasOsdChanged: if (hasOsd) osdWin.visible = true
    onHasPromptChanged: { promptWin.visible = hasPrompt; if (hasPrompt) promptWin.requestActivate() }

    // ------------------------------------------------------------------ banners
    // A new one blooms out of the status icons at the top right, and its app's colour runs once round its edge; it
    // goes back into them. Plain glass, the app's colour glowing behind its icon. At most three on screen; several
    // from one app pile up under the newest ("2 more from Mail"). Reply where it is, if the app takes replies.
    property var piles: {
        var out = [], by = {}, all = Notifier.shown
        for (var i = 0; i < all.length; i++) {
            var n = all[i], k = n.app || "?"
            if (!(k in by)) { by[k] = out.length; out.push({ app: k, items: [] }) }
            out[by[k]].items.push(n)
        }
        return out.slice(0, 3)
    }
    property var ghosts: []                  // piles on their way back into the status icons
    property var lastPiles: []
    onPilesChanged: {
        var now = {}, gone = []
        for (var i = 0; i < piles.length; i++) now[piles[i].app] = true
        for (var j = 0; j < lastPiles.length; j++) if (!now[lastPiles[j].app]) gone.push(lastPiles[j])
        if (gone.length && Theme.t.openMs > 0) ghosts = ghosts.concat(gone)
        lastPiles = piles
    }
    component Card: Rectangle {
        id: card
        property var n: ({})
        property int more: 0
        property bool ghost: false
        readonly property color tone: n.colour ? (Theme.t.dark ? n.colour : (n.colourLight || n.colour)) : Theme.t.accent
        width: 372; height: col.height + 26; radius: 18
        color: Theme.t.dark ? Qt.rgba(0.10, 0.12, 0.14, 0.95) : Qt.rgba(0.98, 0.98, 0.99, 0.97)
        border.width: 1; border.color: n.urgency >= 2 ? Qt.rgba(1, 0.55, 0.45, 0.7) : Theme.t.islandLine
        Rectangle {   // the app's colour, glowing behind its icon
            x: 4; y: 4; width: 62; height: 62; radius: 31; opacity: 0.55
            gradient: Gradient { GradientStop { position: 0; color: Qt.rgba(card.tone.r, card.tone.g, card.tone.b, 0.75) } GradientStop { position: 1; color: "transparent" } }
        }
        Row {
            x: 14; y: 13; spacing: 12; width: parent.width - 28
            Rectangle { width: 38; height: 38; radius: 10; color: Theme.t.hover; clip: true
                Image { id: icon; anchors.fill: parent; anchors.margins: icon.status === Image.Ready ? 0 : 8; source: card.n.icon || ""; sourceSize: Qt.size(80, 80)
                    fillMode: Image.PreserveAspectCrop; smooth: true; visible: status === Image.Ready }
                Text { anchors.centerIn: parent; visible: icon.status !== Image.Ready; text: (card.n.app || "?")[0].toUpperCase(); color: card.tone; font.pixelSize: 17; font.weight: Font.DemiBold } }
            Column {
                id: col
                width: parent.width - 50; spacing: 3
                Row { width: parent.width
                    Text { width: parent.width - when.width; text: card.n.app || ""; color: Theme.t.text_secondary; font.pixelSize: 11; font.weight: Font.DemiBold; elide: Text.ElideRight
                        font.capitalization: Font.AllUppercase; font.letterSpacing: 0.6 }
                    Text { id: when; text: card.n.time || ""; color: Theme.t.text_secondary; font.pixelSize: 11 } }
                Text { width: parent.width; text: card.n.summary || ""; color: Theme.t.text; font.pixelSize: 14; font.weight: Font.DemiBold; wrapMode: Text.WordWrap; maximumLineCount: 2; elide: Text.ElideRight }
                Text { width: parent.width; visible: text !== ""; text: card.n.body || ""; color: Theme.t.text_secondary; font.pixelSize: 13; wrapMode: Text.WordWrap; maximumLineCount: 4; elide: Text.ElideRight }
                Row { visible: !card.ghost && (card.n.actions || []).length > 0; spacing: 6; topPadding: 6
                    Repeater { model: card.n.actions || []
                        Rectangle { required property var modelData; required property int index; objectName: "action-" + modelData.key
                            width: al.width + 22; height: 28; radius: 9; color: index === 0 ? card.tone : (ah.containsMouse ? Theme.t.hover : Qt.rgba(1, 1, 1, Theme.t.dark ? 0.09 : 0.6))
                            Text { id: al; anchors.centerIn: parent; text: parent.modelData.label; font.pixelSize: 12; font.weight: Font.DemiBold; color: parent.index === 0 ? "white" : Theme.t.text }
                            MouseArea { id: ah; anchors.fill: parent; hoverEnabled: true; onClicked: Notifier.invoke(card.n.id, parent.modelData.key) } } } }
                Rectangle {   // reply where it is: typing holds it open until you send
                    visible: !card.ghost && card.n.reply === true
                    width: parent.width; height: 34; radius: 11; color: Qt.rgba(1, 1, 1, Theme.t.dark ? 0.07 : 0.6)
                    border.width: field.activeFocus ? 1.5 : 1; border.color: field.activeFocus ? card.tone : Theme.t.islandLine
                    TextInput {
                        id: field
                        anchors { left: parent.left; leftMargin: 10; right: send.left; rightMargin: 6; verticalCenter: parent.verticalCenter }
                        color: Theme.t.text; font.pixelSize: 13; clip: true
                        onTextChanged: Notifier.hold(card.n.id, text !== "")
                        onAccepted: Notifier.reply(card.n.id, text)
                        Text { visible: !field.text; anchors.verticalCenter: parent.verticalCenter; text: card.n.replyHint || "Reply…"; color: Theme.t.text_secondary; font.pixelSize: 13 }
                    }
                    Rectangle { id: send; anchors { right: parent.right; rightMargin: 4; verticalCenter: parent.verticalCenter } width: 26; height: 26; radius: 13; color: card.tone; opacity: field.text ? 1 : 0.4
                        Text { anchors.centerIn: parent; text: "↑"; color: "white"; font.pixelSize: 14; font.weight: Font.Bold }
                        MouseArea { anchors.fill: parent; onClicked: Notifier.reply(card.n.id, field.text) } }
                }
                Text { visible: card.more > 0; topPadding: 4; text: card.more + " more from " + (card.n.app || "this app") + " · click to see them"; color: Theme.t.text_secondary; font.pixelSize: 12 }
            }
        }
    }
    property Component bannersBody: Item {
        id: bb
        property string open: ""             // the app whose pile is spread out
        Column {
            id: stack
            x: 12; y: 10; width: parent.width - 26; spacing: 10
            onHeightChanged: if (ui.bannersWin) ui.bannersWin.height = Math.max(40, height + 30)
            Repeater {
                model: ui.piles
                Item {
                    id: pile
                    required property var modelData
                    readonly property var head: modelData.items[0]
                    readonly property bool spread: bb.open === modelData.app
                    width: stack.width; height: spread ? spreadCol.height : card.height + Math.min(2, modelData.items.length - 1) * 7
                    objectName: "banner-" + head.id
                    // the ones under the newest, as edges
                    Repeater {
                        model: pile.spread ? 0 : Math.min(2, pile.modelData.items.length - 1)
                        Rectangle { required property int index; x: 10 * (index + 1); width: card.width - 20 * (index + 1); y: card.height - 12 + 7 * (index + 1); height: 14; radius: 10
                            color: Theme.t.dark ? Qt.rgba(0.16, 0.18, 0.21, 0.92 - index * 0.25) : Qt.rgba(0.92, 0.93, 0.95, 0.92 - index * 0.25); border.width: 1; border.color: Theme.t.islandLine; z: -1 - index }
                    }
                    Card { id: card; visible: !pile.spread; n: pile.head; more: pile.modelData.items.length - 1
                        transformOrigin: Item.TopRight
                        Component.onCompleted: bloom.start()
                        ParallelAnimation { id: bloom
                            NumberAnimation { target: card; property: "scale"; from: Theme.t.openMs ? 0.06 : 1; to: 1; duration: Theme.t.openMs ? 300 : 0; easing.type: Easing.OutBack; easing.overshoot: 0.9 }
                            NumberAnimation { target: card; property: "opacity"; from: 0; to: 1; duration: Theme.t.openMs ? 160 : 120 }
                            NumberAnimation { target: ring; property: "drawn"; from: 0; to: ring.perimeter; duration: Theme.t.openMs ? 700 : 0; easing.type: Easing.InOutQuad }
                        }
                        MouseArea { anchors.fill: parent; z: -1; hoverEnabled: true; acceptedButtons: Qt.LeftButton | Qt.MiddleButton
                            onContainsMouseChanged: Notifier.hold(pile.head.id, containsMouse)
                            onClicked: function (e) {
                                if (pile.modelData.items.length > 1 && e.button === Qt.LeftButton) { bb.open = pile.modelData.app; return }
                                if (e.button === Qt.MiddleButton || !pile.head.hasDefault) Notifier.dismiss(pile.head.id); else Notifier.invoke(pile.head.id, "default") } }
                        Shape {   // the app's colour runs once round its edge
                            id: ring
                            anchors.fill: parent; z: 5
                            readonly property real perimeter: 2 * (width + height)
                            property real drawn: 0
                            opacity: drawn >= perimeter - 1 ? 0 : 1
                            Behavior on opacity { NumberAnimation { duration: 400 } }
                            ShapePath {
                                strokeColor: card.tone; strokeWidth: 2.2; fillColor: "transparent"; capStyle: ShapePath.RoundCap
                                strokeStyle: ShapePath.DashLine; dashPattern: [Math.max(0.01, ring.drawn / 2.2), ring.perimeter / 2.2]
                                PathRectangle { x: 1; y: 1; width: ring.width - 2; height: ring.height - 2; radius: 18 }
                            }
                        }
                        Rectangle { x: -6; y: -6; width: 22; height: 22; radius: 11; visible: closeHit.containsMouse || cardHover.hovered; z: 6
                            color: Theme.t.dark ? "#3A3F47" : "#E5E7EB"; border.width: 1; border.color: Theme.t.islandLine
                            Text { anchors.centerIn: parent; text: "✕"; font.pixelSize: 11; color: Theme.t.text }
                            MouseArea { id: closeHit; anchors.fill: parent; hoverEnabled: true; onClicked: Notifier.dismissApp(pile.modelData.app) } }
                        HoverHandler { id: cardHover }
                    }
                    Column {   // a pile spread out: each of them
                        id: spreadCol
                        visible: pile.spread; width: parent.width; spacing: 8
                        Repeater { model: pile.spread ? pile.modelData.items : []
                            Card { required property var modelData; n: modelData
                                MouseArea { anchors.fill: parent; z: -1; onClicked: { if (modelData.hasDefault) Notifier.invoke(modelData.id, "default"); else Notifier.dismiss(modelData.id) } } } }
                        Text { text: "Show fewer"; color: Theme.t.accent; font.pixelSize: 12; font.weight: Font.DemiBold
                            MouseArea { anchors.fill: parent; anchors.margins: -4; onClicked: bb.open = "" } }
                    }
                }
            }
        }
        Repeater {   // gone: back into the status icons
            model: ui.ghosts
            Card {
                id: ghost
                required property var modelData
                ghost: true; n: modelData.items[0]; x: 12; y: 10
                transformOrigin: Item.TopRight
                Component.onCompleted: leave.start()
                SequentialAnimation { id: leave
                    ParallelAnimation {
                        NumberAnimation { target: ghost; property: "scale"; to: 0.06; duration: 220; easing.type: Easing.InCubic }
                        NumberAnimation { target: ghost; property: "opacity"; to: 0; duration: 220 }
                    }
                    ScriptAction { script: ui.ghosts = ui.ghosts.filter(function (g) { return g !== ghost.modelData }) }
                }
            }
        }
    }

    // ------------------------------------------------------------------ the level
    property Component osdBody: Item {
        id: ob
        readonly property var s: Session.osdState
        Rectangle {
            id: pill
            objectName: "osd"
            anchors.horizontalCenter: parent.horizontalCenter
            y: parent.height - height - 110
            width: 280; height: 56; radius: 28
            color: Theme.t.dark ? Qt.rgba(0.10, 0.12, 0.14, 0.92) : Qt.rgba(0.98, 0.98, 0.99, 0.95)
            border.width: 1; border.color: Theme.t.islandLine
            opacity: ob.s.kind ? 1 : 0
            Behavior on opacity { NumberAnimation { duration: 220 } }
            onOpacityChanged: if (opacity === 0 && !ob.s.kind && ui.osdWin) ui.osdWin.visible = false
            Row {
                anchors.centerIn: parent; spacing: 14
                Text { width: 26; horizontalAlignment: Text.AlignHCenter; anchors.verticalCenter: parent.verticalCenter; font.pixelSize: 19; color: Theme.t.text
                    text: ({ volume: ob.s.muted ? "🔇" : "🔊", mic: ob.s.muted ? "🎙" : "🎙", brightness: "☀", keyboard: "⌨" })[ob.s.kind] || "" }
                Item { width: 196; height: 26; anchors.verticalCenter: parent.verticalCenter
                    Rectangle { visible: !ob.s.text; anchors.verticalCenter: parent.verticalCenter; width: parent.width; height: 6; radius: 3; color: Theme.t.hover
                        Rectangle { objectName: "osdLevel"; width: parent.width * (ob.s.muted ? 0 : ob.s.level); height: parent.height; radius: 3
                            Behavior on width { NumberAnimation { duration: 120 } }
                            gradient: Gradient { orientation: Gradient.Horizontal; GradientStop { position: 0; color: Theme.t.glowA } GradientStop { position: 1; color: Theme.t.glowB } } } }
                    Text { visible: !!ob.s.text; anchors.verticalCenter: parent.verticalCenter; text: ob.s.text || ""; color: Theme.t.text; font.pixelSize: 14; font.weight: Font.DemiBold } }
            }
        }
    }

    // ------------------------------------------------------------------ a question
    property Component promptBody: Item {
        id: pb
        readonly property var p: Session.prompt
        property int remaining: p.countdown || 0
        Timer { running: !!pb.p.countdown && pb.remaining > 0; interval: 1000; repeat: true
            onTriggered: { pb.remaining -= 1
                if (pb.p.cancelWhen === "charging" && Session.charging()) { Session.answer(pb.p.uid, "cancel", "", ""); return }
                if (pb.remaining <= 0) Session.answer(pb.p.uid, pb.p.timeoutKey || "cancel", "", "") } }
        onPChanged: { remaining = p.countdown || 0; field.text = ""; ident.text = ""; if (p.field) Qt.callLater(function () { (p.identity ? ident : field).forceActiveFocus() }) }
        function go(key) { Session.answer(pb.p.uid, key, field.text, ident.text) }
        Rectangle {
            id: card
            objectName: "promptCard"
            x: 12; y: 12; width: parent.width - 24; height: col.height + 44; radius: 22
            onHeightChanged: if (ui.promptWin) ui.promptWin.height = height + 24
            color: Theme.t.dark ? Qt.rgba(0.11, 0.13, 0.15, 0.97) : Qt.rgba(0.98, 0.98, 0.99, 0.98)
            border.width: 1; border.color: Theme.t.islandLine
            Rectangle { anchors { left: parent.left; right: parent.right; top: parent.top; leftMargin: 30; rightMargin: 30 } height: 2; radius: 1
                gradient: Gradient { orientation: Gradient.Horizontal; GradientStop { position: 0; color: "transparent" } GradientStop { position: 0.5; color: Theme.t.glowA } GradientStop { position: 1; color: "transparent" } } }
            Column {
                id: col
                x: 22; y: 22; width: parent.width - 44; spacing: 12
                Text { objectName: "promptTitle"; width: parent.width; text: pb.p.title || ""; color: Theme.t.text; font.pixelSize: 18; font.weight: Font.DemiBold; wrapMode: Text.WordWrap }
                Text { width: parent.width; text: (pb.p.detail || "") + (pb.p.countdown ? "  (" + pb.remaining + " s)" : ""); color: Theme.t.text_secondary; font.pixelSize: 13; wrapMode: Text.WordWrap }
                Text { visible: !!pb.p.code; objectName: "promptCode"; anchors.horizontalCenter: parent.horizontalCenter; text: (pb.p.code || "").split("").join(" "); color: Theme.t.text
                    font.pixelSize: 34; font.weight: Font.Light; font.family: Theme.t.fontMono }
                Rectangle { visible: !!pb.p.identity; width: parent.width; height: 42; radius: 21; color: Theme.t.hover; border.width: 1; border.color: ident.activeFocus ? Theme.t.accent : Theme.t.islandLine
                    TextInput { id: ident; objectName: "promptIdentity"; anchors.fill: parent; anchors.leftMargin: 16; anchors.rightMargin: 16; verticalAlignment: TextInput.AlignVCenter
                        color: Theme.t.text; font.pixelSize: 14; clip: true; KeyNavigation.tab: field
                        Text { visible: !parent.text; text: "User name"; color: Theme.t.text_secondary; font.pixelSize: 14; anchors.verticalCenter: parent.verticalCenter } } }
                Rectangle { visible: !!pb.p.field; width: parent.width; height: 42; radius: 21; color: Theme.t.hover; border.width: 1; border.color: field.activeFocus ? Theme.t.accent : Theme.t.islandLine
                    TextInput { id: field; objectName: "promptField"; anchors.fill: parent; anchors.leftMargin: 16; anchors.rightMargin: 16; verticalAlignment: TextInput.AlignVCenter
                        color: Theme.t.text; font.pixelSize: 14; clip: true
                        echoMode: pb.p.field === "password" ? TextInput.Password : TextInput.Normal
                        inputMethodHints: pb.p.field === "number" ? Qt.ImhDigitsOnly : Qt.ImhNone
                        onAccepted: pb.go((pb.p.buttons || []).filter(function (b) { return b.primary }).map(function (b) { return b.key })[0] || "cancel")
                        Keys.onEscapePressed: pb.go("cancel")
                        Text { visible: !parent.text; text: pb.p.field === "password" ? "Password" : "Code"; color: Theme.t.text_secondary; font.pixelSize: 14; anchors.verticalCenter: parent.verticalCenter } } }
                Row {
                    anchors.right: parent.right; spacing: 8; topPadding: 4
                    Repeater { model: pb.p.buttons || []
                        Rectangle { required property var modelData; objectName: "promptButton-" + modelData.key
                            width: bl.width + 30; height: 36; radius: 18
                            color: modelData.primary ? (bh.containsMouse ? Qt.lighter(Theme.t.accent, 1.1) : Theme.t.accent) : (bh.containsMouse ? Theme.t.hover : "transparent")
                            border.width: modelData.primary ? 0 : 1; border.color: Theme.t.islandLine
                            Text { id: bl; anchors.centerIn: parent; text: parent.modelData.label; font.pixelSize: 13; font.weight: Font.DemiBold
                                color: parent.modelData.primary ? Theme.t.onAccent : Theme.t.text }
                            MouseArea { id: bh; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: pb.go(parent.modelData.key) } } }
                }
            }
        }
        Keys.onEscapePressed: pb.go("cancel")
        focus: true
    }
}
