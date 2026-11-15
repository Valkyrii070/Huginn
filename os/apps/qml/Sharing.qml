import QtQuick

// Screen Sharing, "two doors": on the left, the door into this computer (one big button opens it, and while it's
// open the screen glows and the address and one-time password are written large enough to read out over the phone);
// on the right, the door into someone else's.
GlassWindow {
    id: win
    title: "Screen Sharing"; width: 1040; height: 700; minimumWidth: 860; minimumHeight: 600; glow: "centre"
    property string why: ""
    property bool full: false
    readonly property bool on: Backend.sharing
    Connections { target: Backend; function onSaid(msg, wrong) { toast.say(msg, wrong) } }

    islands: [ Toast { id: toast; anchors { horizontalCenter: parent.horizontalCenter; bottom: parent.bottom; bottomMargin: 22 } } ]

    // a little drawn monitor, used on both sides
    component Screen: Item {
        id: scr
        property bool lit: false
        property bool other: false
        width: 150; height: 112
        Rectangle { id: glass; width: parent.width; height: 92; radius: 12; color: scr.lit ? Theme.t.accent : Theme.t.group; border.width: 2
            border.color: scr.lit ? Qt.lighter(Theme.t.accent, 1.2) : Theme.t.islandLine
            Behavior on color { ColorAnimation { duration: 300 } }
            Glyph { anchors.centerIn: parent; name: scr.other ? "eye" : scr.lit ? "share" : "display"; size: 34; ink: scr.lit ? Theme.t.onAccent : Theme.t.icon } }
        Rectangle { anchors.horizontalCenter: parent.horizontalCenter; y: 94; width: 10; height: 10; color: Theme.t.islandLine }
        Rectangle { anchors.horizontalCenter: parent.horizontalCenter; y: 104; width: 60; height: 6; radius: 3; color: Theme.t.islandLine }
        Repeater { model: scr.lit ? 3 : 0
            Rectangle { required property int index; anchors.centerIn: glass; width: glass.width + 10 + index * 14; height: glass.height + 10 + index * 14; radius: 16 + index * 7
                color: "transparent"; border.width: 2; border.color: Theme.t.accent; opacity: 0
                SequentialAnimation on opacity { loops: Animation.Infinite; running: !demo
                    PauseAnimation { duration: index * 400 } NumberAnimation { from: 0.45; to: 0; duration: 1600 } PauseAnimation { duration: (2 - index) * 400 } }
                Component.onCompleted: if (demo) opacity = 0.35 - index * 0.1 } }
    }

    // ---------------- this computer
    Rectangle { id: mine; objectName: "mine"; x: 18; y: 64; width: (parent.width - 48) * 0.56; height: parent.height - 82; radius: 22
        color: Theme.t.island; border.width: win.on ? 2 : 1; border.color: win.on ? Theme.t.accent : Theme.t.islandLine
        Column { anchors { fill: parent; margins: 26 } spacing: 14
            Row { spacing: 22
                Screen { lit: win.on }
                Column { width: mine.width - 52 - 150 - 22; spacing: 6; anchors.verticalCenter: parent.verticalCenter
                    Label { text: win.on ? "Your screen is shared" : "Let someone see this screen"; font.pixelSize: 21; font.weight: Font.Bold; width: parent.width; wrapMode: Text.WordWrap }
                    Label { width: parent.width; wrapMode: Text.WordWrap; secondary: true; font.pixelSize: 12
                        text: win.on ? "They can see your screen and use your mouse and keyboard. Sharing stops when you press Stop or close this window."
                                     : "They'll see your screen and can use your mouse and keyboard, so only share with people you trust. They can use any Remote Desktop app, on any computer or phone." } } }
            Item { width: 1; height: 4 }
            Column { visible: win.on; width: parent.width; spacing: 12
                Repeater { model: [["Address", Backend.addresses.length ? Backend.addresses[0].ip : Backend.hostname], ["Name", Backend.login], ["Password", Backend.password]]
                    Item { required property var modelData; required property int index; width: parent.width; height: 52
                        Label { y: 2; text: modelData[0].toUpperCase(); font.pixelSize: 10; font.weight: Font.Bold; font.letterSpacing: 1.2; secondary: true }
                        Text { y: 16; text: modelData[1]; font.family: Theme.t.fontMono; font.pixelSize: index === 2 ? 30 : 24; font.weight: Font.DemiBold; color: index === 2 ? Theme.t.accent : Theme.t.text }
                        Seg { anchors { right: parent.right; verticalCenter: undefined } y: 18; text: "Copy"; onClicked: Backend.copy(modelData[1]) } } }
                Label { visible: Backend.addresses.length > 1; width: parent.width; wrapMode: Text.WordWrap; font.pixelSize: 11; secondary: true
                    text: "Also reachable at " + Backend.addresses.slice(1).map(function (a) { return a.ip + " (" + a.kind + ")" }).join(", ") }
                Flow { visible: Backend.screens.length > 0; width: parent.width; spacing: 6
                    Label { text: "Show "; font.pixelSize: 12; secondary: true; height: 30; verticalAlignment: Text.AlignVCenter }
                    Repeater { model: Backend.screens
                        Seg { required property var modelData; required property int index; anchors.verticalCenter: undefined; text: modelData.name; on: Backend.monitor === index - 1; onClicked: Backend.setMonitor(index - 1) } } }
                Rectangle { width: parent.width; height: 40; radius: 12; color: Theme.t.group
                    Row { x: 12; spacing: 8; anchors.verticalCenter: parent.verticalCenter
                        Rectangle { width: 9; height: 9; radius: 5; color: Backend.watching.length ? "#22C55E" : Theme.t.text_secondary; anchors.verticalCenter: parent.verticalCenter }
                        Label { font.pixelSize: 12; text: Backend.watching.length ? Backend.watching.join(", ") + (Backend.watching.length === 1 ? " is connected" : " are connected") : "Nobody has connected yet" } } } }
            Label { visible: !win.on && Backend.why !== ""; width: parent.width; wrapMode: Text.WordWrap; color: Theme.t.danger; font.pixelSize: 12; text: Backend.why } }
        Row { anchors { left: parent.left; leftMargin: 26; bottom: parent.bottom; bottomMargin: 24 } spacing: 10
            Btn { visible: !win.on; primary: true; enabled: Backend.canShare; text: "Share My Screen"; onClicked: Backend.start() }
            Btn { visible: win.on; danger: true; text: "Stop Sharing"; onClicked: Backend.stop() }
            Btn { visible: win.on; text: "New Password"; onClicked: Backend.start() } }
        Label { visible: !Backend.canShare; anchors { left: parent.left; leftMargin: 26; right: parent.right; rightMargin: 26; bottom: parent.bottom; bottomMargin: 70 } wrapMode: Text.WordWrap
            font.pixelSize: 12; color: Theme.t.danger; text: "Sharing needs KDE's Remote Desktop server (krdp). Get it from the App Store." } }

    // ---------------- someone else's
    Rectangle { id: theirs; objectName: "theirs"; x: mine.x + mine.width + 12; y: 64; width: parent.width - x - 18; height: parent.height - 82; radius: 22
        color: Theme.t.island; border.width: 1; border.color: Theme.t.islandLine
        Column { anchors { fill: parent; margins: 24 } spacing: 10
            Screen { other: true; anchors.horizontalCenter: parent.horizontalCenter; scale: 0.8; height: 96 }
            Label { anchors.horizontalCenter: parent.horizontalCenter; text: "See another screen"; font.pixelSize: 18; font.weight: Font.Bold }
            Label { width: parent.width; wrapMode: Text.WordWrap; horizontalAlignment: Text.AlignHCenter; secondary: true; font.pixelSize: 12; text: "Another Huginn computer, or a Windows PC with Remote Desktop turned on." }
            TextBox { id: addr; objectName: "addr"; width: parent.width; placeholder: "Address, like 192.168.1.20"; onAccepted: who.focusIn() }
            TextBox { id: who; width: parent.width; placeholder: "Name to sign in with"; text: "huginn"; onAccepted: pw.focusIn() }
            TextBox { id: pw; width: parent.width; secret: true; placeholder: "Password"; onAccepted: go.clicked() }
            Row { spacing: 10; Toggle { on: win.full; onToggled: function (v) { win.full = v } }
                Label { anchors.verticalCenter: parent.verticalCenter; font.pixelSize: 12; text: "Full screen (Ctrl+Alt+Enter to leave)" } }
            Label { visible: win.why !== ""; width: parent.width; wrapMode: Text.WordWrap; color: Theme.t.danger; font.pixelSize: 12; text: win.why }
            Btn { id: go; anchors.horizontalCenter: parent.horizontalCenter; primary: true; text: "Connect"
                onClicked: { win.why = Backend.view(addr.text, who.text, pw.text, win.full); if (win.why === "") pw.text = "" } }
            Label { visible: Backend.recent.length > 0; text: "RECENT"; font.pixelSize: 10; font.weight: Font.Bold; font.letterSpacing: 1.2; secondary: true; topPadding: 6 }
            Repeater { model: Backend.recent
                Pressable { required property var modelData; width: theirs.width - 48; height: 40; radius: 11; color: hovered ? Theme.t.hover : Theme.t.group
                    onClicked: { addr.text = modelData.host + (modelData.port !== 3389 ? ":" + modelData.port : ""); who.text = modelData.user; pw.focusIn() }
                    Glyph { x: 12; anchors.verticalCenter: parent.verticalCenter; name: "display"; size: 15 }
                    Label { x: 38; width: parent.width - 90; elide: Text.ElideRight; anchors.verticalCenter: parent.verticalCenter
                        text: (modelData.name || modelData.host) + "  "; font.weight: Font.DemiBold
                        Label { anchors { left: parent.left; leftMargin: parent.implicitWidth; verticalCenter: parent.verticalCenter } text: modelData.name ? modelData.host + " · " + modelData.user : modelData.user; secondary: true; font.pixelSize: 11; font.weight: Font.Normal } }
                    Pressable { anchors { right: parent.right; rightMargin: 6; verticalCenter: parent.verticalCenter } width: 28; height: 28; radius: 14; onClicked: Backend.forget(modelData.host)
                        Glyph { anchors.centerIn: parent; name: "x"; size: 12 } } } } }
        Label { visible: !Backend.canView; anchors { left: parent.left; leftMargin: 24; right: parent.right; rightMargin: 24; bottom: parent.bottom; bottomMargin: 18 } wrapMode: Text.WordWrap
            font.pixelSize: 12; color: Theme.t.danger; text: "Needs FreeRDP's viewer (freerdp-sdl). Get it from the App Store." } }
}
