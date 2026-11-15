import QtQuick
import QtQuick.Window

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
    property Component bannersBody: Item {
        id: bb
        Column {
            id: stack
            x: 12; y: 10; width: parent.width - 26; spacing: 10
            onHeightChanged: if (ui.bannersWin) ui.bannersWin.height = Math.max(40, height + 22)
            Repeater {
                model: Notifier.shown
                Rectangle {
                    id: banner
                    required property var modelData
                    objectName: "banner-" + modelData.id
                    width: stack.width; height: col.height + 26; radius: 20
                    color: Theme.t.dark ? Qt.rgba(0.10, 0.12, 0.14, 0.94) : Qt.rgba(0.98, 0.98, 0.99, 0.96)
                    border.width: 1; border.color: modelData.urgency >= 2 ? Qt.rgba(1, 0.55, 0.45, 0.7) : Theme.t.islandLine
                    opacity: 0; scale: 0.96
                    Component.onCompleted: arrive.start()
                    ParallelAnimation { id: arrive
                        NumberAnimation { target: banner; property: "opacity"; to: 1; duration: 220; easing.type: Easing.OutCubic }
                        NumberAnimation { target: banner; property: "scale"; to: 1; duration: 260; easing.type: Easing.OutBack } }
                    MouseArea { id: over; anchors.fill: parent; hoverEnabled: true; acceptedButtons: Qt.LeftButton | Qt.MiddleButton
                        onContainsMouseChanged: Notifier.hold(banner.modelData.id, containsMouse)
                        onClicked: function (e) { if (e.button === Qt.MiddleButton || !banner.modelData.hasDefault) Notifier.dismiss(banner.modelData.id); else Notifier.invoke(banner.modelData.id, "default") } }
                    Row {
                        x: 14; y: 13; spacing: 12; width: parent.width - 28
                        Rectangle { width: 40; height: 40; radius: 11; color: Theme.t.hover; clip: true
                            Image { anchors.fill: parent; anchors.margins: icon.status === Image.Ready ? 0 : 8; id: icon; source: banner.modelData.icon; sourceSize: Qt.size(80, 80)
                                fillMode: Image.PreserveAspectCrop; smooth: true; visible: status === Image.Ready }
                            Text { anchors.centerIn: parent; visible: icon.status !== Image.Ready; text: (banner.modelData.app || "?")[0].toUpperCase(); color: Theme.t.text; font.pixelSize: 17; font.weight: Font.DemiBold } }
                        Column {
                            id: col
                            width: parent.width - 52; spacing: 3
                            Row { width: parent.width
                                Text { width: parent.width - when.width; text: banner.modelData.app; color: Theme.t.text_secondary; font.pixelSize: 11; font.weight: Font.DemiBold; elide: Text.ElideRight
                                    font.capitalization: Font.AllUppercase; font.letterSpacing: 0.6 }
                                Text { id: when; text: banner.modelData.time; color: Theme.t.text_secondary; font.pixelSize: 11 } }
                            Text { width: parent.width; text: banner.modelData.summary; color: Theme.t.text; font.pixelSize: 14; font.weight: Font.DemiBold; wrapMode: Text.WordWrap; maximumLineCount: 2; elide: Text.ElideRight }
                            Text { width: parent.width; visible: text !== ""; text: banner.modelData.body; color: Theme.t.text_secondary; font.pixelSize: 13; wrapMode: Text.WordWrap; maximumLineCount: 4; elide: Text.ElideRight }
                            Row { visible: banner.modelData.actions.length > 0; spacing: 6; topPadding: 6
                                Repeater { model: banner.modelData.actions
                                    Rectangle { required property var modelData; objectName: "action-" + modelData.key
                                        width: al.width + 22; height: 28; radius: 14; color: ah.containsMouse ? Theme.t.accent : Theme.t.hover
                                        Text { id: al; anchors.centerIn: parent; text: parent.modelData.label; font.pixelSize: 12; font.weight: Font.DemiBold
                                            color: ah.containsMouse ? Theme.t.onAccent : Theme.t.text }
                                        MouseArea { id: ah; anchors.fill: parent; hoverEnabled: true; onClicked: Notifier.invoke(banner.modelData.id, parent.modelData.key) } } } }
                        }
                    }
                    // close, on hover
                    Rectangle { x: -6; y: -6; width: 22; height: 22; radius: 11; visible: over.containsMouse || closeHit.containsMouse
                        color: Theme.t.dark ? "#3A3F47" : "#E5E7EB"; border.width: 1; border.color: Theme.t.islandLine
                        Text { anchors.centerIn: parent; text: "✕"; font.pixelSize: 11; color: Theme.t.text }
                        MouseArea { id: closeHit; anchors.fill: parent; hoverEnabled: true; onClicked: Notifier.dismiss(banner.modelData.id) } }
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
