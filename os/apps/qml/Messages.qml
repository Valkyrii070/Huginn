import QtQuick

// Messages, "the people strip": the people and groups you talk to sit along the top as round faces (a dot when
// something new came in), and the chosen conversation runs down the middle like a river of bubbles, yours on the
// right in the app's blue. Writing happens in one floating island at the bottom.
GlassWindow {
    id: win
    title: "Messages"; width: 1040; height: 760; minimumWidth: 720; minimumHeight: 520; glow: "bottom"
    visible: !(typeof startHidden !== "undefined" && startHidden)
    property var sheet: null
    property string why: ""
    property bool otherServer: false
    function newChat() { sheet = { kind: "new" } }
    function account() { sheet = { kind: "account" } }
    function hue(s) { var h = 0; for (var i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) % 360; return h / 360 }
    function signIn() { why = Backend.signIn(addr.text, pass.text, master.text, otherServer ? server.text : ""); if (why === "") { pass.text = ""; master.text = "" } }
    Connections { target: Backend
        function onSaid(msg, wrong) { toast.say(msg, wrong) }
        function onShown() { win.show(); win.raise(); win.requestActivate() } }
    onActiveChanged: Backend.setFocused(active)

    islands: [
        Island { visible: Backend.state === "ready"; anchors { right: parent.right; rightMargin: 12 } y: 12
            IslandField { width: 170; placeholder: "Find a chat"; onTextChanged: Backend.search(text) }
            Seg { icon: "plus"; text: "New Chat"; onClicked: { win.sheet = { kind: "new" }; whoBox.text = ""; whoBox.focusIn() } }
            Seg { icon: "gear"; tip: "Account"; onClicked: win.sheet = { kind: "account" } } },
        Toast { id: toast; anchors { horizontalCenter: parent.horizontalCenter; bottom: parent.bottom; bottomMargin: 92 } },

        Item { anchors.fill: parent; z: 20; visible: win.sheet !== null
            Rectangle { anchors.fill: parent; radius: win.r; color: "#66000000"; MouseArea { anchors.fill: parent; acceptedButtons: Qt.AllButtons; onClicked: win.sheet = null } }
            Rectangle { id: card; anchors.centerIn: parent; width: 480; radius: 18; color: Theme.t.menu_bg; border.width: 1; border.color: Theme.t.menu_border
                readonly property string kind: win.sheet ? win.sheet.kind : ""
                height: kind === "new" ? 230 : kind === "files" ? Math.min(win.height - 80, 130 + Math.max(1, files.count) * 38) : kind === "leave" ? 180 : 360
                MouseArea { anchors.fill: parent }
                Label { x: 24; y: 20; width: parent.width - 48; elide: Text.ElideRight; font.pixelSize: 17; font.weight: Font.DemiBold
                    text: ({ "new": "Start a chat", "account": "Your Matrix account", "files": "Send a file", "leave": "Leave “" + (Backend.current.name || "") + "”?" })[card.kind] || "" }
                Column { visible: card.kind === "new"; x: 24; y: 56; width: parent.width - 48; spacing: 10
                    Label { width: parent.width; wrapMode: Text.WordWrap; secondary: true; text: "Their Matrix address. The chat is end-to-end encrypted; they're asked to join." }
                    TextBox { id: whoBox; objectName: "whoBox"; width: parent.width; placeholder: "@name:matrix.org"; onAccepted: newOk.clicked() }
                    Label { visible: win.why !== "" && card.kind === "new"; color: Theme.t.danger; font.pixelSize: 12; text: win.why } }
                Column { visible: card.kind === "account"; x: 24; y: 56; width: parent.width - 48; spacing: 10
                    Label { text: Backend.me; font.weight: Font.DemiBold; font.pixelSize: 15 }
                    Label { secondary: true; font.pixelSize: 12; text: "This computer is device " + Backend.device }
                    Row { spacing: 8
                        Glyph { name: Backend.encryption ? "lock" : "info"; size: 15; ink: Backend.encryption ? Theme.t.accent : Theme.t.danger; anchors.verticalCenter: parent.verticalCenter }
                        Label { width: 390; wrapMode: Text.WordWrap; font.pixelSize: 12
                            text: Backend.encryption ? "End-to-end encryption is on: new chats are encrypted, and this device's keys are locked with your vault." : "Encryption isn't available (python3-olm is missing), so encrypted chats can't be read here." } }
                    Row { spacing: 10; Toggle { on: Backend.stayOn; onToggled: function (v) { Backend.setPref("stay", v) } }
                        Label { anchors.verticalCenter: parent.verticalCenter; font.pixelSize: 12; text: "Keep getting messages after the window closes" } }
                    Row { spacing: 10; Toggle { on: Backend.preview; onToggled: function (v) { Backend.setPref("preview", v) } }
                        Label { anchors.verticalCenter: parent.verticalCenter; width: 380; wrapMode: Text.WordWrap; font.pixelSize: 12; text: "Show the words of a new message in its notice (otherwise only who it's from)" } } }
                Repeater { id: files; model: card.kind === "files" ? win.sheet.list : []
                    Pressable { required property var modelData; required property int index; x: 16; y: 56 + index * 38; width: card.width - 32; height: 36; radius: 9
                        onClicked: { Backend.sendFile(modelData.path); win.sheet = null }
                        Glyph { x: 10; anchors.verticalCenter: parent.verticalCenter; name: "file"; size: 15 }
                        Label { x: 36; width: parent.width - 170; elide: Text.ElideMiddle; anchors.verticalCenter: parent.verticalCenter; text: modelData.name }
                        Label { anchors { right: parent.right; rightMargin: 10; verticalCenter: parent.verticalCenter } text: modelData.where + " · " + modelData.size; secondary: true; font.pixelSize: 11 } } }
                Label { visible: card.kind === "leave"; x: 24; y: 56; width: parent.width - 48; wrapMode: Text.WordWrap; secondary: true; text: "You'll stop getting its messages. Someone in it can ask you back." }
                Btn { visible: card.kind === "account"; anchors { left: parent.left; leftMargin: 22; bottom: parent.bottom; bottomMargin: 20 } danger: true; text: "Sign Out"; onClicked: { win.sheet = null; Backend.signOut() } }
                Row { anchors { right: parent.right; rightMargin: 22; bottom: parent.bottom; bottomMargin: 20 } spacing: 8
                    Btn { text: card.kind === "account" || card.kind === "files" ? "Done" : "Cancel"; onClicked: { win.sheet = null; win.why = "" } }
                    Btn { id: newOk; visible: card.kind === "new"; primary: true; text: "Start"; onClicked: { win.why = Backend.startChat(whoBox.text); if (win.why === "") win.sheet = null } }
                    Btn { visible: card.kind === "leave"; danger: true; text: "Leave"; onClicked: { var id = Backend.current.id; win.sheet = null; Backend.leave(id) } } } } }
    ]

    // ---------------- signing in, unlocking, waiting
    Column { visible: Backend.state === "signin"; anchors.centerIn: parent; spacing: 12; width: 380
        Rectangle { anchors.horizontalCenter: parent.horizontalCenter; width: 84; height: 84; radius: 42; color: Theme.t.accent
            Glyph { anchors.centerIn: parent; name: "send"; size: 36; ink: Theme.t.onAccent } }
        Label { anchors.horizontalCenter: parent.horizontalCenter; font.pixelSize: 22; font.weight: Font.Bold; text: "Sign in to Matrix" }
        Label { width: parent.width; wrapMode: Text.WordWrap; horizontalAlignment: Text.AlignHCenter; secondary: true
            text: "Matrix is an open chat network: your friends can be on any Matrix app or server. Your sign-in is kept in your vault, with Passwords." }
        TextBox { id: addr; objectName: "addr"; width: parent.width; placeholder: "Your Matrix address, like @name:matrix.org"; onAccepted: pass.focusIn() }
        TextBox { id: pass; objectName: "pass"; width: parent.width; secret: true; placeholder: "Password"; onAccepted: win.signIn() }
        TextBox { id: master; width: parent.width; secret: true; placeholder: "Your vault's master password (new vault: pick one)"; onAccepted: win.signIn() }
        TextBox { id: server; visible: win.otherServer; width: parent.width; placeholder: "Server address, like https://matrix.example.org" }
        Label { width: parent.width; horizontalAlignment: Text.AlignHCenter; wrapMode: Text.WordWrap; font.pixelSize: 12; color: Theme.t.danger; visible: (win.why || Backend.why) !== ""; text: win.why || Backend.why }
        Btn { anchors.horizontalCenter: parent.horizontalCenter; primary: true; text: Backend.busy === "signing in" ? "Signing In…" : "Sign In"; onClicked: win.signIn() }
        Row { anchors.horizontalCenter: parent.horizontalCenter; spacing: 16
            Seg { text: win.otherServer ? "Usual server" : "Other server"; onClicked: win.otherServer = !win.otherServer }
            Seg { text: "Make an account"; onClicked: Qt.openUrlExternally("https://app.element.io/#/register") } } }
    Column { visible: Backend.state === "locked"; anchors.centerIn: parent; spacing: 12; width: 340
        Glyph { anchors.horizontalCenter: parent.horizontalCenter; name: "lock"; size: 44; ink: Theme.t.accent }
        Label { anchors.horizontalCenter: parent.horizontalCenter; font.pixelSize: 20; font.weight: Font.DemiBold; text: "Your vault is locked" }
        Label { width: parent.width; wrapMode: Text.WordWrap; horizontalAlignment: Text.AlignHCenter; secondary: true; text: "Messages keeps its sign-in there. Type the master password." }
        TextBox { id: door; objectName: "door"; width: parent.width; secret: true; placeholder: "Master password"; onAccepted: { win.why = Backend.unlock(text); text = "" } }
        Label { visible: win.why !== ""; width: parent.width; horizontalAlignment: Text.AlignHCenter; color: Theme.t.danger; font.pixelSize: 12; text: win.why }
        Btn { anchors.horizontalCenter: parent.horizontalCenter; primary: true; text: "Unlock"; onClicked: { win.why = Backend.unlock(door.text); door.text = "" } } }
    Column { visible: Backend.state === "connecting" || Backend.state === "broken" || Backend.state === "start"; anchors.centerIn: parent; spacing: 10; width: 360
        Glyph { anchors.horizontalCenter: parent.horizontalCenter; name: Backend.state === "broken" ? "info" : "history"; size: 36; ink: Theme.t.accent }
        Label { width: parent.width; horizontalAlignment: Text.AlignHCenter; wrapMode: Text.WordWrap; text: Backend.state === "broken" ? Backend.why : Backend.why || "Catching up…" } }

    // ---------------- the people strip
    ListView { id: strip; objectName: "strip"; visible: Backend.state === "ready"; x: 16; y: 62; width: parent.width - 32; height: 98; orientation: ListView.Horizontal; spacing: 6; clip: true
        boundsBehavior: Flickable.StopAtBounds
        header: Row { spacing: 6
            Repeater { model: Backend.invites
                Item { required property var modelData; width: 84; height: 96
                    Rectangle { anchors.horizontalCenter: parent.horizontalCenter; y: 4; width: 60; height: 60; radius: 30; color: "transparent"; border.width: 2; border.color: Theme.t.accent
                        Label { anchors.centerIn: parent; text: "?"; font.pixelSize: 22; font.weight: Font.Bold; color: Theme.t.accent } }
                    Label { anchors.horizontalCenter: parent.horizontalCenter; y: 68; width: 80; horizontalAlignment: Text.AlignHCenter; elide: Text.ElideRight; font.pixelSize: 11; text: modelData.name }
                    Row { anchors.horizontalCenter: parent.horizontalCenter; y: 82; spacing: 2
                        Label { text: "Join"; font.pixelSize: 10; font.weight: Font.Bold; color: Theme.t.accent; MouseArea { anchors.fill: parent; onClicked: Backend.answerInvite(modelData.id, true) } }
                        Label { text: " · "; font.pixelSize: 10; secondary: true }
                        Label { text: "No"; font.pixelSize: 10; secondary: true; MouseArea { anchors.fill: parent; onClicked: Backend.answerInvite(modelData.id, false) } } } } } }
        model: Backend.rooms
        delegate: Pressable { id: face; required property var modelData; readonly property bool on: Backend.current.id === modelData.id; width: 84; height: 96; radius: 16
            color: hovered && !on ? Theme.t.hover : "transparent"; onClicked: Backend.open(modelData.id)
            Rectangle { anchors.horizontalCenter: parent.horizontalCenter; y: 4; width: 60; height: 60; radius: 30; color: Qt.hsla(win.hue(face.modelData.name), 0.5, Theme.t.dark ? 0.45 : 0.5, 1)
                border.width: face.on ? 3 : 0; border.color: Theme.t.accent
                Label { anchors.centerIn: parent; text: face.modelData.initials; color: "#FFFFFF"; font.pixelSize: 20; font.weight: Font.Bold }
                Rectangle { visible: face.modelData.unread > 0; anchors { right: parent.right; top: parent.top; rightMargin: -2; topMargin: -2 } width: Math.max(20, badge.width + 10); height: 20; radius: 10; color: Theme.t.accent
                    border.width: 2; border.color: Theme.t.dark ? "#1A1D24" : "#FFFFFF"
                    Label { id: badge; anchors.centerIn: parent; text: face.modelData.unread; font.pixelSize: 10; font.weight: Font.Bold; color: Theme.t.onAccent } }
                Rectangle { visible: face.modelData.members > 2; anchors { right: parent.right; bottom: parent.bottom } width: 20; height: 20; radius: 10; color: Theme.t.menu_bg
                    Glyph { anchors.centerIn: parent; name: "user"; size: 11 } } }
            Label { anchors.horizontalCenter: parent.horizontalCenter; y: 70; width: 80; horizontalAlignment: Text.AlignHCenter; elide: Text.ElideRight; font.pixelSize: 11
                font.weight: face.modelData.unread ? Font.Bold : Font.Normal; text: face.modelData.name } } }

    Column { visible: Backend.state === "ready" && Backend.rooms.length === 0 && Backend.invites.length === 0; anchors.centerIn: parent; spacing: 10; width: 360
        Label { anchors.horizontalCenter: parent.horizontalCenter; font.pixelSize: 20; font.weight: Font.Bold; text: "No chats yet" }
        Label { width: parent.width; wrapMode: Text.WordWrap; horizontalAlignment: Text.AlignHCenter; secondary: true; text: "Start one with a friend's Matrix address. You're " + Backend.me + " if they want to start one with you." }
        Btn { anchors.horizontalCenter: parent.horizontalCenter; primary: true; text: "New Chat"; onClicked: { win.sheet = { kind: "new" }; whoBox.focusIn() } } }

    // ---------------- the conversation
    Item { id: talk; visible: Backend.state === "ready" && !!Backend.current.id; x: 16; y: 168; width: parent.width - 32; height: parent.height - 168 - 84
        Item { id: head; width: parent.width; height: 34
            Label { anchors.horizontalCenter: parent.horizontalCenter; y: 0; text: Backend.current.name || ""; font.pixelSize: 16; font.weight: Font.Bold }
            Row { anchors.horizontalCenter: parent.horizontalCenter; y: 20; spacing: 6
                Glyph { visible: !!Backend.current.encrypted; name: "lock"; size: 11; ink: Theme.t.accent; anchors.verticalCenter: parent.verticalCenter }
                Label { font.pixelSize: 11; secondary: true; text: (Backend.current.encrypted ? "End-to-end encrypted" : "Not encrypted") + (Backend.current.members > 2 ? " · " + Backend.current.members + " people" : "") } }
            Seg { anchors { right: parent.right; verticalCenter: undefined } y: 2; text: "Leave"; onClicked: win.sheet = { kind: "leave" } } }
        ListView { id: river; objectName: "river"; anchors { fill: parent; topMargin: 44 } clip: true; spacing: 3; model: Backend.thread; boundsBehavior: Flickable.StopAtBounds
            onCountChanged: Qt.callLater(positionViewAtEnd)
            header: Item { width: river.width; height: Backend.current.more ? 40 : 0
                Seg { visible: !!Backend.current.more; anchors.centerIn: parent; text: "Earlier messages"; onClicked: Backend.earlier() } }
            delegate: Column { id: msg; required property var modelData; width: river.width; spacing: 2
                Label { visible: msg.modelData.day !== ""; width: parent.width; horizontalAlignment: Text.AlignHCenter; topPadding: 12; bottomPadding: 6; font.pixelSize: 11; font.weight: Font.Bold; secondary: true; text: msg.modelData.day }
                Label { visible: msg.modelData.first && !msg.modelData.mine && Backend.current.members > 2; x: 14; topPadding: 6; font.pixelSize: 11; font.weight: Font.DemiBold; color: Qt.hsla(win.hue(msg.modelData.name), 0.6, Theme.t.dark ? 0.7 : 0.4, 1); text: msg.modelData.name }
                Item { width: parent.width; height: bubble.height
                    Rectangle { id: bubble; x: msg.modelData.mine ? parent.width - width - 4 : 4; width: Math.min(river.width * 0.68, bodyCol.width + 26); height: bodyCol.height + 16; radius: 18
                        color: msg.modelData.kind === "locked" ? "transparent" : msg.modelData.mine ? Theme.t.accent : Theme.t.island; border.width: msg.modelData.mine && msg.modelData.kind !== "locked" ? 0 : 1; border.color: Theme.t.islandLine
                        Column { id: bodyCol; x: 13; y: 8; spacing: 4
                            Label { visible: msg.modelData.kind !== "file" && msg.modelData.kind !== "image"; width: Math.min(implicitWidth, river.width * 0.68 - 26); wrapMode: Text.Wrap
                                text: msg.modelData.kind === "emote" ? "* " + msg.modelData.name + " " + msg.modelData.body : msg.modelData.body; font.italic: msg.modelData.kind === "locked" || msg.modelData.kind === "emote"
                                color: msg.modelData.mine && msg.modelData.kind !== "locked" ? Theme.t.onAccent : msg.modelData.kind === "locked" ? Theme.t.text_secondary : Theme.t.text; font.pixelSize: msg.modelData.kind === "locked" ? 12 : 14 }
                            Row { visible: msg.modelData.kind === "file" || msg.modelData.kind === "image"; spacing: 10
                                Rectangle { width: 36; height: 36; radius: 10; color: msg.modelData.mine ? "#33FFFFFF" : Theme.t.group; Glyph { anchors.centerIn: parent; name: msg.modelData.kind === "image" ? "image" : "file"; size: 16; ink: msg.modelData.mine ? Theme.t.onAccent : Theme.t.icon } }
                                Column { Label { text: msg.modelData.file ? msg.modelData.file.name : ""; font.weight: Font.DemiBold; color: msg.modelData.mine ? Theme.t.onAccent : Theme.t.text }
                                         Label { text: msg.modelData.file ? msg.modelData.file.size : ""; font.pixelSize: 11; color: msg.modelData.mine ? Theme.t.onAccent : Theme.t.text_secondary } }
                                Seg { visible: !msg.modelData.mine; anchors.verticalCenter: parent.verticalCenter; text: "Save"; onClicked: Backend.saveFile(msg.modelData.id) } } }
                        Label { visible: false; text: msg.modelData.time } }
                    Label { anchors { verticalCenter: bubble.verticalCenter } x: msg.modelData.mine ? bubble.x - width - 8 : bubble.x + bubble.width + 8; font.pixelSize: 10; secondary: true; text: msg.modelData.time
                        opacity: tap.containsMouse ? 1 : 0 }
                    MouseArea { id: tap; anchors.fill: bubble; hoverEnabled: true; acceptedButtons: Qt.NoButton } } } } }
    Label { visible: Backend.state === "ready" && Backend.rooms.length > 0 && !Backend.current.id; anchors.centerIn: parent; secondary: true; text: "Pick someone along the top" }

    // ---------------- writing
    Rectangle { id: compose; visible: talk.visible; anchors { horizontalCenter: parent.horizontalCenter; bottom: parent.bottom; bottomMargin: 18 } width: Math.min(parent.width - 48, 760); height: Math.max(54, writer.height + 18); radius: 27
        color: Theme.t.island; border.width: 1; border.color: Theme.t.islandLine
        Pressable { x: 8; anchors.verticalCenter: parent.verticalCenter; width: 38; height: 38; radius: 19; onClicked: win.sheet = { kind: "files", list: Backend.fileChoices() }
            Glyph { anchors.centerIn: parent; name: "plus"; size: 17 } }
        TextBox { id: writer; objectName: "writer"; x: 52; anchors.verticalCenter: parent.verticalCenter; width: parent.width - 52 - 56; placeholder: Backend.busy ? "Busy: " + Backend.busy + "…" : "Message " + (Backend.current.name || "")
            onAccepted: { Backend.send(text); text = "" } }
        Pressable { objectName: "sendBtn"; anchors { right: parent.right; rightMargin: 8; verticalCenter: parent.verticalCenter } width: 40; height: 40; radius: 20; color: Theme.t.accent
            onClicked: { Backend.send(writer.text); writer.text = "" }
            Glyph { anchors.centerIn: parent; name: "send"; size: 17; ink: Theme.t.onAccent } } }
}
