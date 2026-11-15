import QtQuick

// Phone, "in your hand": no lists. The phone you picked stands in the middle of the window, filled as far as its
// battery is; what you can do to it sits around it in a ring of round buttons.
GlassWindow {
    id: win
    title: "Phone"; width: 820; height: 640; glow: "centre"
    readonly property color pick: Qt.rgba(tintColor.r, tintColor.g, tintColor.b, 0.18)
    readonly property var dev: Backend.device
    readonly property bool live: !!dev.id && dev.paired && dev.here
    property bool choosing: false
    property var chosen: []
    Connections { target: Backend; function onSaid(msg, wrong) { toast.say(msg, wrong) } }

    islands: [
        Island { visible: Backend.devices.length > 0; anchors.horizontalCenter: parent.horizontalCenter; y: 12
            Repeater { model: Backend.devices
                Seg { required property var modelData; text: modelData.name; on: Backend.picked === modelData.id; opacity: modelData.here ? 1 : 0.55; tip: !modelData.paired ? "Not paired" : modelData.here ? "Connected" : "Out of reach"
                    onClicked: Backend.pick(modelData.id) } } },
        Island { anchors { right: parent.right; rightMargin: 12 } y: 12; visible: Backend.ready
            Seg { icon: "history"; tip: "Look again"; onClicked: Backend.refresh() } },
        Toast { id: toast; anchors { horizontalCenter: parent.horizontalCenter; bottom: parent.bottom; bottomMargin: 18 } },
        Item { anchors.fill: parent; z: 20; visible: win.choosing
            Rectangle { anchors.fill: parent; radius: win.r; color: "#66000000"; MouseArea { anchors.fill: parent; acceptedButtons: Qt.AllButtons; onClicked: win.choosing = false } }
            Rectangle { anchors.centerIn: parent; width: 460; height: 130 + Math.max(1, Backend.choices.length) * 36; radius: 16; color: Theme.t.menu_bg; border.width: 1; border.color: Theme.t.menu_border
                MouseArea { anchors.fill: parent }
                Label { x: 22; y: 20; font.pixelSize: 16; font.weight: Font.DemiBold; text: "Send to " + (win.dev.name || "") }
                Column { x: 16; y: 52; width: parent.width - 32
                    Label { visible: Backend.choices.length === 0; x: 6; height: 36; verticalAlignment: Text.AlignVCenter; secondary: true; text: "Nothing recent. Use “Send to Phone” on a file in Files." }
                    Repeater { model: win.choosing ? Backend.choices : []
                        Pressable { required property var modelData; readonly property bool on: win.chosen.indexOf(modelData.path) >= 0; width: parent.width; height: 36; radius: 9; color: on ? win.pick : hovered ? Theme.t.hover : "transparent"
                            onClicked: { var c = win.chosen.slice(), i = c.indexOf(modelData.path); if (i >= 0) c.splice(i, 1); else c.push(modelData.path); win.chosen = c }
                            Glyph { x: 10; anchors.verticalCenter: parent.verticalCenter; name: parent.on ? "check" : "file"; size: 14; ink: parent.on ? Theme.t.accent : Theme.t.text_secondary }
                            Label { x: 34; width: parent.width - 170; elide: Text.ElideMiddle; anchors.verticalCenter: parent.verticalCenter; text: modelData.name }
                            Label { anchors { right: parent.right; rightMargin: 10; verticalCenter: parent.verticalCenter } text: modelData.where + " · " + modelData.size; secondary: true; font.pixelSize: 11 } } } }
                Row { anchors { right: parent.right; rightMargin: 22; bottom: parent.bottom; bottomMargin: 18 } spacing: 8
                    Btn { text: "Cancel"; onClicked: win.choosing = false }
                    Btn { primary: true; opacity: win.chosen.length ? 1 : 0.5; text: win.chosen.length > 1 ? "Send " + win.chosen.length + " Files" : "Send"; onClicked: { if (win.chosen.length) { Backend.sendFiles(win.chosen); win.choosing = false } } } } } }
    ]

    // ---------------- nothing to talk to
    Column { visible: !Backend.ready || Backend.devices.length === 0; anchors.centerIn: parent; spacing: 10; width: 440
        Glyph { name: "phone"; size: 54; ink: Theme.t.accent; anchors.horizontalCenter: parent.horizontalCenter }
        Label { anchors.horizontalCenter: parent.horizontalCenter; font.pixelSize: 20; font.weight: Font.DemiBold; text: Backend.ready ? "Looking for your phone…" : "KDE Connect isn't installed" }
        Label { width: parent.width; wrapMode: Text.WordWrap; horizontalAlignment: Text.AlignHCenter; secondary: true
            text: Backend.ready ? "Install the free KDE Connect app on the phone (Android or iPhone), put both on the same Wi-Fi, and open it. The phone will appear here."
                                : "Phone works through KDE Connect, which this computer doesn't have. Install the kdeconnect package and open Phone again." } }

    // ---------------- the phone, and what you can do to it
    component Orb: Item { id: orb; property string icon: ""; property string label: ""; property string hint: ""; signal clicked(); width: 150; height: 96
        Pressable { id: ball; anchors.horizontalCenter: parent.horizontalCenter; width: 58; height: 58; radius: 29; color: hovered ? Theme.t.accent : win.pick; border.width: 1; border.color: Theme.t.accent; onClicked: orb.clicked()
            Glyph { anchors.centerIn: parent; name: orb.icon; size: 22; ink: ball.hovered ? Theme.t.onAccent : Theme.t.accent } }
        Label { y: 64; anchors.horizontalCenter: parent.horizontalCenter; text: orb.label; font.weight: Font.DemiBold; font.pixelSize: 13 }
        Label { y: 81; width: parent.width; horizontalAlignment: Text.AlignHCenter; elide: Text.ElideRight; text: orb.hint; secondary: true; font.pixelSize: 10 } }

    Item { id: stage; visible: Backend.devices.length > 0 && !!win.dev.id; anchors { fill: parent; topMargin: 64; bottomMargin: 12 }
        Rectangle { id: body; anchors.horizontalCenter: parent.horizontalCenter; y: 26; width: 176; height: 340; radius: 34; color: Theme.t.menu_bg; border.width: 2; border.color: win.live ? Theme.t.accent : Theme.t.islandLine; opacity: win.dev.here ? 1 : 0.6
            Rectangle { id: screen; anchors { fill: parent; margins: 9 } radius: 26; color: Theme.t.island; clip: true
                Rectangle { anchors { left: parent.left; right: parent.right; bottom: parent.bottom } height: parent.height * Math.max(0, win.dev.battery || 0) / 100; color: win.pick
                    Behavior on height { NumberAnimation { duration: 500; easing.type: Easing.OutCubic } } }
                Rectangle { anchors.horizontalCenter: parent.horizontalCenter; y: 8; width: 54; height: 14; radius: 7; color: Theme.t.menu_bg }
                Column { anchors.centerIn: parent; spacing: 2
                    Label { anchors.horizontalCenter: parent.horizontalCenter; text: win.dev.battery >= 0 ? win.dev.battery + "%" : "–"; font.pixelSize: 38; font.weight: Font.Bold; color: Theme.t.accent }
                    Label { anchors.horizontalCenter: parent.horizontalCenter; secondary: true; font.pixelSize: 11; text: win.dev.battery >= 0 ? (win.dev.charging ? "charging" : "battery") : !win.dev.paired ? "not paired" : win.dev.here ? "connected" : "out of reach" } } } }
        Orb { visible: win.live; anchors { right: body.left; rightMargin: 44 } y: 70; icon: "send"; label: "Send Files"; hint: "Pictures, documents"; onClicked: { win.chosen = []; win.choosing = true } }
        Orb { visible: win.live; anchors { right: body.left; rightMargin: 44 } y: 214; icon: "doc"; label: "Send Clipboard"; hint: "What you last copied"; onClicked: Backend.sendClipboard() }
        Orb { visible: win.live; anchors { left: body.right; leftMargin: 44 } y: 70; icon: "bell"; label: "Ring It"; hint: "Find a lost phone"; onClicked: Backend.ring() }
        Orb { visible: win.live; anchors { left: body.right; leftMargin: 44 } y: 214; icon: "wifi"; label: "Ping"; hint: "Check they can talk"; onClicked: Backend.ping() }

        Column { anchors { horizontalCenter: parent.horizontalCenter; top: body.bottom; topMargin: 16 } width: 520; spacing: 10
            Label { anchors.horizontalCenter: parent.horizontalCenter; text: win.dev.name || ""; font.pixelSize: 22; font.weight: Font.Bold }
            Rectangle { visible: Backend.waiting.length > 0; width: parent.width; height: 50; radius: 25; color: win.pick; border.width: 1; border.color: Theme.t.accent
                Label { x: 20; anchors.verticalCenter: parent.verticalCenter; width: parent.width - 220; elide: Text.ElideMiddle; text: Backend.waiting.length === 1 ? "Ready to send: " + Backend.waiting[0].name : "Ready to send: " + Backend.waiting.length + " files" }
                Row { anchors { right: parent.right; rightMargin: 10; verticalCenter: parent.verticalCenter } spacing: 6
                    Btn { height: 28; text: "Not Now"; onClicked: Backend.dropWaiting() }
                    Btn { height: 28; primary: true; opacity: win.live ? 1 : 0.5; text: "Send"; onClicked: Backend.sendWaiting() } } }
            Row { visible: win.live; width: parent.width; spacing: 8
                TextBox { id: words; objectName: "words"; width: parent.width - 88; placeholder: "A note or a web address to send"; onAccepted: { Backend.sendText(text); text = "" } }
                Btn { width: 80; text: "Send"; onClicked: { Backend.sendText(words.text); words.text = "" } } }
            Label { visible: !win.live; width: parent.width; wrapMode: Text.WordWrap; horizontalAlignment: Text.AlignHCenter; secondary: true
                text: !win.dev.paired ? "Pairing lets the two trust each other. You confirm it on the phone; nothing is shared before that." : "Open KDE Connect on the phone and make sure both are on the same network." }
            Row { anchors.horizontalCenter: parent.horizontalCenter; spacing: 8
                Btn { visible: !win.dev.paired && !!win.dev.here; primary: true; text: "Pair"; onClicked: Backend.pair(win.dev.id) }
                Btn { visible: !!win.dev.paired; height: 26; text: "Unpair"; onClicked: Backend.unpair(win.dev.id) } }
            Label { visible: win.live; width: parent.width; wrapMode: Text.WordWrap; horizontalAlignment: Text.AlignHCenter; secondary: true; font.pixelSize: 11; text: "Files the phone sends arrive in Downloads." } } }
}
