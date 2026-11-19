import QtQuick
import QtQuick.Window

// Huginn's password prompt (the polkit agent's window): a single glass card that floats above everything while an app
// waits for an administrator's yes. A lock in the realm's colour, what's being asked in plain words, the program or
// command asking, who can say yes, and the password. Wrong passwords shake the card; Escape or Cancel says no.
Window {
    id: win
    visible: Agent.active
    width: 460; height: card.height + 24
    flags: Qt.Dialog | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
    color: "transparent"
    title: "Authenticate"
    modality: Qt.ApplicationModal
    onVisibleChanged: if (visible) { pass.text = ""; Qt.callLater(function () { pass.focusIn(); win.requestActivate() }) }
    property int lastTries: 0
    readonly property int tries: Agent.tries
    onTriesChanged: { if (tries > lastTries) { shake.restart(); pass.text = "" } lastTries = tries }

    Rectangle {
        id: card
        objectName: "card"
        x: 12; y: 12; width: parent.width - 24; height: col.height + 44; radius: 20
        color: Theme.t.dark ? Qt.rgba(0.11, 0.13, 0.15, 0.97) : Qt.rgba(0.98, 0.98, 0.99, 0.98)
        border.width: 1; border.color: Theme.t.islandLine
        transform: Translate { id: nudge }
        SequentialAnimation { id: shake
            NumberAnimation { target: nudge; property: "x"; to: 12; duration: 50 } NumberAnimation { target: nudge; property: "x"; to: -10; duration: 60 }
            NumberAnimation { target: nudge; property: "x"; to: 6; duration: 60 } NumberAnimation { target: nudge; property: "x"; to: 0; duration: 50 } }
        // the realm's glow along the top edge
        Rectangle { anchors { left: parent.left; right: parent.right; top: parent.top; margins: 1 } height: 70; radius: 20
            gradient: Gradient { GradientStop { position: 0; color: Qt.alpha(Theme.t.accent, 0.16) } GradientStop { position: 1; color: "transparent" } } }
        MouseArea { anchors.fill: parent; property point p0
            onPressed: function (m) { p0 = Qt.point(m.x, m.y) }
            onPositionChanged: function (m) { win.x += m.x - p0.x; win.y += m.y - p0.y } }      // drag it by its card

        Column { id: col; x: 22; y: 22; width: parent.width - 44; spacing: 12
            Row { spacing: 14; width: parent.width
                Rectangle { width: 46; height: 46; radius: 15; color: Qt.alpha(Theme.t.accent, 0.18)
                    Glyph { anchors.centerIn: parent; name: "lock"; size: 24; ink: Theme.t.accent } }
                Column { width: parent.width - 60; spacing: 3; anchors.verticalCenter: parent.verticalCenter
                    Label { objectName: "title"; width: parent.width; wrapMode: Text.WordWrap; text: Agent.title; font.pixelSize: 15; font.weight: Font.DemiBold }
                    Label { width: parent.width; wrapMode: Text.WordWrap; secondary: true; font.pixelSize: 12
                        text: Agent.people.length > 1 ? "An administrator's password is needed." : Agent.people.length ? "Type the password for " + (Agent.people[0].realName || Agent.people[0].name) + "." : "" } } }
            // the program or command asking
            Rectangle { objectName: "detail"; visible: Agent.detail !== ""; width: parent.width; height: detailText.height + 16; radius: 10; color: Theme.t.group
                Text { id: detailText; x: 10; y: 8; width: parent.width - 20; wrapMode: Text.WrapAnywhere; text: Agent.detail; color: Theme.t.text; font.family: Theme.t.fontMono; font.pixelSize: 11; maximumLineCount: 4; elide: Text.ElideRight } }
            // who can say yes
            Flow { objectName: "people"; visible: Agent.people.length > 1; width: parent.width; spacing: 6
                Repeater { model: Agent.people
                    Seg { required property var modelData; required property int index; anchors.verticalCenter: undefined
                        text: modelData.realName || modelData.name; on: Agent.chosen === index; onClicked: { Agent.choose(index); pass.focusIn() } } } }
            TextBox { id: pass; objectName: "password"; width: parent.width; height: 40; secret: !Agent.echo
                placeholder: Agent.busy ? "Checking…" : (Agent.prompt || "Password"); enabled: !Agent.busy
                onAccepted: if (Agent.ready && text !== "") Agent.authenticate(text) }
            Label { objectName: "error"; visible: Agent.error !== "" || Agent.info !== ""; width: parent.width; wrapMode: Text.WordWrap; font.pixelSize: 12
                color: Agent.error !== "" ? Theme.t.danger : Theme.t.text_secondary; text: Agent.error || Agent.info }
            Item { width: parent.width; height: 38
                Label { anchors { left: parent.left; verticalCenter: parent.verticalCenter } width: parent.width - 220; elide: Text.ElideRight; font.pixelSize: 10; secondary: true; text: Agent.actionId }
                Row { anchors.right: parent.right; spacing: 8
                    Btn { objectName: "cancel"; text: "Cancel"; onClicked: Agent.cancel() }
                    Btn { objectName: "authenticate"; text: "Authenticate"; primary: true; opacity: Agent.ready && pass.text !== "" ? 1 : 0.5
                        onClicked: if (Agent.ready && pass.text !== "") Agent.authenticate(pass.text) } } } } }
    Shortcut { sequence: "Escape"; onActivated: Agent.cancel() }
}
