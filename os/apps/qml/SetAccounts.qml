import QtQuick

// Online Accounts: your accounts as cards (each with switches for what it's used for), then tiles to add another.
Column {
    id: pg
    width: parent ? parent.width : 600; spacing: 18
    readonly property bool have: typeof Accounts !== "undefined"
    readonly property var list: have ? Accounts.accounts : []
    readonly property var marks: ({ google: "G", microsoft: "M", icloud: "", nextcloud: "N" })
    Connections { target: pg.have ? Accounts : null; function onSaid(msg, bad) { win.say(msg, bad) } }
    function start(p) {
        if (!p.ready) { win.say(p.name + " needs Huginn to be registered with it first (a free, one-time step for whoever builds this copy). Help › Online Accounts says how.", true); return }
        if (p.sign === "oauth") win.ask("Add " + p.name, "Type the address, then sign in on " + p.name + "'s own page, which opens in Huginn. Settings never sees your password.", [{ key: "email", label: "Email address" }], "Continue",
                                       function (v) { Accounts.add(p.id, { email: v.email }) })
        else if (p.sign === "password") win.ask("Add " + p.name, p.note, [{ key: "email", label: "Apple ID email address" }, { key: "password", label: "App-specific password", secret: true, placeholder: "xxxx-xxxx-xxxx-xxxx" }], "Add",
                                               function (v) { Accounts.add(p.id, { email: v.email, password: v.password }) })
        else win.ask("Add Nextcloud", "Type your Nextcloud's address. Its sign-in page opens in Huginn, and it gives this computer a password of its own (you can revoke it there any time).",
                     [{ key: "server", label: "Server", placeholder: "cloud.example.com" }], "Continue", function (v) { Accounts.add("nextcloud", { server: v.server }) })
    }
    SetCard { visible: !pg.have
        SetRow { title: "Online Accounts isn't available"; glyph: "cloud" } }
    // Passwords holds every sign-in, so it has to be open
    SetCard { visible: pg.have && !Accounts.vaultExists
        SetRow { title: "Set up Passwords first"; sub: "Sign-ins are kept in Passwords, under one master password only you know."; glyph: "key"; tile: "#1479A8"
            Btn { text: "Set Up…"; primary: true; onClicked: win.ask("Make a master password", "It unlocks every password and sign-in Huginn keeps. It can't be recovered, so choose one you'll remember.",
                                                                  [{ key: "a", label: "Master password", secret: true }, { key: "b", label: "Again", secret: true }], "Make It", function (v) { Accounts.create(v.a, v.b) }) } } }
    SetCard { visible: pg.have && Accounts.vaultExists && Accounts.locked
        SetRow { title: "Passwords is locked"; sub: "Unlock it to add accounts or keep them in step. Unlocking in any Huginn app works."; glyph: "lock"; tile: "#1479A8"
            Btn { text: "Unlock…"; primary: true; onClicked: win.ask("Unlock Passwords", "", [{ key: "m", label: "Master password", secret: true }], "Unlock", function (v) { var why = Accounts.unlock(v.m); if (why) win.say(why, true) }) } } }
    // waiting for the provider's own sign-in page
    Rectangle { visible: pg.have && Accounts.adding !== ""; width: parent.width; height: 64; radius: Theme.t.radiusCard; color: Qt.rgba(0.16, 0.47, 0.66, 0.16); border.width: 1; border.color: Qt.rgba(0.16, 0.47, 0.66, 0.5)
        Glyph { id: spin; x: 18; anchors.verticalCenter: parent.verticalCenter; name: "refresh"; size: 20; ink: "#40CFE0"; RotationAnimation on rotation { running: spin.visible; loops: Animation.Infinite; from: 0; to: 360; duration: 1200 } }
        Label { x: 52; anchors.verticalCenter: parent.verticalCenter; width: parent.width - 170; wrapMode: Text.WordWrap
            text: pg.have && Accounts.waiting ? "Finish signing in on " + Accounts.waiting + "'s page in Huginn, then come back here." : "Signing in and looking at the account…" }
        Btn { anchors { right: parent.right; rightMargin: 14; verticalCenter: parent.verticalCenter } text: "Cancel"; onClicked: Accounts.cancel() } }
    Repeater { model: pg.list
        Rectangle { id: acard; required property var modelData; width: pg.width; height: acol.height + 4; radius: Theme.t.radiusCard; color: Theme.t.group; border.width: 1; border.color: Theme.t.separator; clip: true
            Column { id: acol; width: parent.width
                Item { width: parent.width; height: 74
                    Rectangle { x: 16; width: 42; height: 42; radius: 12; anchors.verticalCenter: parent.verticalCenter
                        gradient: Gradient { GradientStop { position: 0; color: modelData.a } GradientStop { position: 1; color: modelData.b } }
                        Label { visible: pg.marks[modelData.provider] !== ""; anchors.centerIn: parent; text: pg.marks[modelData.provider] || ""; color: "#FFFFFF"; font.pixelSize: 20; font.weight: Font.Bold }
                        Glyph { visible: pg.marks[modelData.provider] === ""; anchors.centerIn: parent; name: "cloud"; size: 22; ink: "#FFFFFF" } }
                    Column { x: 72; anchors.verticalCenter: parent.verticalCenter; width: parent.width - 300; spacing: 2
                        Label { text: modelData.providerName + " · " + modelData.email; font.weight: Font.DemiBold; elide: Text.ElideRight; width: parent.width }
                        Label { width: parent.width; elide: Text.ElideRight; font.pixelSize: 11; color: modelData.error ? Theme.t.danger : Theme.t.text_secondary
                            text: modelData.error ? modelData.error : modelData.syncing ? "Bringing it up to date…" : "Up to date " + modelData.synced.toLowerCase() + (modelData.summary ? " · " + modelData.summary : "") } }
                    Row { anchors { right: parent.right; rightMargin: 14; verticalCenter: parent.verticalCenter } spacing: 8
                        Btn { visible: modelData.error.indexOf("Sign in again") >= 0; text: "Sign In Again"; primary: true
                            onClicked: { var a = modelData; Accounts.remove(a.id); pg.start(Accounts.providers.filter(function (p) { return p.id === a.provider })[0]) } }
                        Btn { visible: modelData.error.indexOf("Sign in again") < 0; text: "Sync Now"; enabled: !modelData.syncing; onClicked: Accounts.syncNow(modelData.id) }
                        Seg { icon: "trash"; tip: "Remove"; onClicked: { var a = modelData; win.confirm("Remove " + a.providerName + " (" + a.email + ")?", "Its mail, events and contacts leave this computer. Nothing on the account itself changes.", "Remove", function () { Accounts.remove(a.id) }) } } } }
                Repeater { model: modelData.services
                    SetRow { required property var modelData; title: modelData.label
                        glyph: ({ mail: "mail", calendar: "calendar", contacts: "user", files: "folder" })[modelData.id]; tile: ({ mail: "#3B82F6", calendar: "#E8590C", contacts: "#6D28D9", files: "#0A8071" })[modelData.id]
                        sub: ({ mail: "In Mail", calendar: "In Calendar · changes you make go back", contacts: "In Contacts", files: "In Files, as a place in the side bar" })[modelData.id]
                        Toggle { on: modelData.on; onToggled: function (v) { Accounts.setService(acard.modelData.id, modelData.id, v) } } } } } } }
    SetCard { visible: pg.have; title: pg.list.length ? "Add another account" : "Add an account"
        note: "Huginn connects straight to each provider. Nothing goes through anyone else's servers."
        Flow { width: parent.width; padding: 12; spacing: 12
            Repeater { model: pg.have ? Accounts.providers : []
                Pressable { required property var modelData; width: (pg.width - 24 - 12) / 2; height: 78; radius: 14; enabled: pg.have && Accounts.adding === ""
                    color: hovered ? Theme.t.hover : (Theme.t.dark ? "#10FFFFFF" : "#08141E28")
                    onClicked: if (Accounts.locked) win.say("Unlock Passwords first: that's where the sign-in is kept.", true); else pg.start(modelData)
                    Rectangle { x: 14; width: 46; height: 46; radius: 13; anchors.verticalCenter: parent.verticalCenter
                        gradient: Gradient { GradientStop { position: 0; color: modelData.a } GradientStop { position: 1; color: modelData.b } }
                        Label { visible: pg.marks[modelData.id] !== ""; anchors.centerIn: parent; text: pg.marks[modelData.id] || ""; color: "#FFFFFF"; font.pixelSize: 22; font.weight: Font.Bold }
                        Glyph { visible: pg.marks[modelData.id] === ""; anchors.centerIn: parent; name: "cloud"; size: 24; ink: "#FFFFFF" } }
                    Column { x: 74; anchors.verticalCenter: parent.verticalCenter; width: parent.width - 86; spacing: 2
                        Label { text: modelData.name; font.pixelSize: 15; font.weight: Font.DemiBold }
                        Label { width: parent.width; text: modelData.ready ? modelData.blurb : "Not registered in this copy of Huginn yet"; secondary: true; font.pixelSize: 11; elide: Text.ElideRight } } } } } }
}
