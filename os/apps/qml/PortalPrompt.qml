import QtQuick
import QtQuick.Window

// Two questions the desktop asks for apps, as one glass card that floats above everything:
//   Access     "Allow Camera to use the camera?" — what's asked, why, the app's own choices, and yes or no.
//   Open With  "Open “Holiday plan.pdf” with" — the apps that can, the last one used already picked; Enter opens.
Window {
    id: win
    visible: Prompt.active
    width: 460; height: card.height + 24
    flags: Qt.Dialog | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
    color: "transparent"
    title: Prompt.kind === "apps" ? "Open With" : "Allow"
    readonly property bool apps: Prompt.kind === "apps"
    readonly property string glyph: {
        var i = Prompt.icon.toLowerCase()
        return apps ? "apps" : i.indexOf("camera") >= 0 ? "camera" : i.indexOf("screens") >= 0 ? "image" : i.indexOf("location") >= 0 ? "pin"
             : i.indexOf("microphone") >= 0 || i.indexOf("audio-input") >= 0 ? "mic" : i.indexOf("notif") >= 0 ? "bell" : "shield"
    }
    onVisibleChanged: if (visible) Qt.callLater(function () { win.requestActivate(); keys.forceActiveFocus() })
    onClosing: function (close) { Prompt.cancel() }

    Rectangle {
        id: card
        objectName: "card"
        x: 12; y: 12; width: parent.width - 24; height: col.height + 44; radius: 20
        color: Theme.t.dark ? Qt.rgba(0.11, 0.13, 0.15, 0.97) : Qt.rgba(0.98, 0.98, 0.99, 0.98)
        border.width: 1; border.color: Theme.t.islandLine
        Rectangle { anchors { left: parent.left; right: parent.right; top: parent.top; margins: 1 } height: 70; radius: 20
            gradient: Gradient { GradientStop { position: 0; color: Qt.rgba(Theme.t.accent.r, Theme.t.accent.g, Theme.t.accent.b, 0.16) } GradientStop { position: 1; color: "transparent" } } }
        MouseArea { anchors.fill: parent; property point p0
            onPressed: function (m) { p0 = Qt.point(m.x, m.y) }
            onPositionChanged: function (m) { win.x += m.x - p0.x; win.y += m.y - p0.y } }

        Column { id: col; x: 22; y: 22; width: parent.width - 44; spacing: 14
            Row { spacing: 14; width: parent.width
                Rectangle { width: 46; height: 46; radius: 15; color: Qt.rgba(Theme.t.accent.r, Theme.t.accent.g, Theme.t.accent.b, 0.18)
                    Glyph { anchors.centerIn: parent; name: win.glyph; size: 24; ink: Theme.t.accent } }
                Column { width: parent.width - 60; spacing: 3; anchors.verticalCenter: parent.verticalCenter
                    Label { objectName: "title"; width: parent.width; wrapMode: Text.WordWrap; text: Prompt.title; font.pixelSize: 15; font.weight: Font.DemiBold }
                    Label { visible: text !== ""; width: parent.width; wrapMode: Text.WordWrap; secondary: true; font.pixelSize: 12; text: Prompt.subtitle } } }
            Label { visible: !win.apps && Prompt.body !== ""; width: parent.width; wrapMode: Text.WordWrap; font.pixelSize: 12; text: Prompt.body }
            // the app's own choices (Access): a switch, or a few answers
            Repeater { model: win.apps ? [] : Prompt.choices
                Item { id: choiceRow; required property var modelData; width: col.width; height: modelData.options.length ? 64 : 28
                    Toggle { visible: choiceRow.modelData.options.length === 0; on: choiceRow.modelData.value === "true"; anchors.verticalCenter: parent.verticalCenter
                        objectName: "choice-" + choiceRow.modelData.id
                        onToggled: function (v) { Prompt.setChoice(choiceRow.modelData.id, v ? "true" : "false") } }
                    Label { x: choiceRow.modelData.options.length ? 0 : 50; anchors.verticalCenter: choiceRow.modelData.options.length ? undefined : parent.verticalCenter
                        text: choiceRow.modelData.label; font.pixelSize: 13 }
                    Island { visible: choiceRow.modelData.options.length > 0; y: 24; height: 34
                        Repeater { model: choiceRow.modelData.options
                            Seg { required property var modelData; text: modelData.label; on: choiceRow.modelData.value === modelData.id
                                onClicked: Prompt.setChoice(choiceRow.modelData.id, modelData.id) } } } } }
            // Open With: the apps that can
            Column { visible: win.apps; width: parent.width; spacing: 2
                Repeater { model: win.apps ? Prompt.apps : []
                    Pressable { id: appRow; required property var modelData; required property int index
                        objectName: "app-" + modelData.id
                        width: col.width; height: 48; radius: 12
                        readonly property bool picked: Prompt.chosen === modelData.id
                        color: picked ? Qt.rgba(Theme.t.accent.r, Theme.t.accent.g, Theme.t.accent.b, 0.20) : hovered ? Theme.t.hover : "transparent"
                        onClicked: Prompt.choose(modelData.id)
                        onDoubleClicked: { Prompt.choose(modelData.id); Prompt.answer(true) }
                        Image { id: pic; x: 10; anchors.verticalCenter: parent.verticalCenter; width: 32; height: 32; sourceSize: Qt.size(64, 64)
                            visible: appRow.modelData.image !== ""; source: appRow.modelData.image; smooth: true; mipmap: true }
                        Glyph { x: 16; anchors.verticalCenter: parent.verticalCenter; visible: appRow.modelData.image === ""; name: "apps"; size: 20 }
                        Column { x: 54; width: parent.width - 64; anchors.verticalCenter: parent.verticalCenter
                            Label { text: appRow.modelData.name; font.pixelSize: 13; font.weight: appRow.picked ? Font.DemiBold : Font.Normal; width: parent.width; elide: Text.ElideRight }
                            Label { visible: text !== ""; text: appRow.modelData.about; secondary: true; font.pixelSize: 11; width: parent.width; elide: Text.ElideRight } } } }
                Label { visible: Prompt.apps.length === 0; text: "No app on this computer opens this. Software has more."; secondary: true; font.pixelSize: 12 } }
            Item { width: parent.width; height: 38
                Row { anchors.right: parent.right; spacing: 8
                    Btn { objectName: "deny"; text: win.apps ? "Cancel" : Prompt.denyLabel; onClicked: win.apps ? Prompt.cancel() : Prompt.answer(false) }
                    Btn { objectName: "grant"; primary: true; text: win.apps ? "Open" : Prompt.grantLabel
                        enabled: !win.apps || Prompt.chosen !== ""; opacity: enabled ? 1 : 0.45
                        onClicked: Prompt.answer(true) } } } } }
    Item { id: keys; focus: true
        Keys.onReturnPressed: Prompt.answer(true)
        Keys.onEnterPressed: Prompt.answer(true)
        Keys.onEscapePressed: win.apps ? Prompt.cancel() : Prompt.answer(false)
        Keys.onUpPressed: win.step(-1)
        Keys.onDownPressed: win.step(1) }
    function step(d) {
        if (!apps || Prompt.apps.length === 0) return
        var i = 0
        for (var k = 0; k < Prompt.apps.length; k++) if (Prompt.apps[k].id === Prompt.chosen) i = k
        Prompt.choose(Prompt.apps[Math.max(0, Math.min(Prompt.apps.length - 1, i + d))].id)
    }
}
