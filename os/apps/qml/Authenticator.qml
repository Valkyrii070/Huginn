import QtQuick

// Authenticator, "the dial wall": every code is a round dial, the digits in the middle and the time left running
// round the rim, so you can see at a glance which code is about to change. Click a dial to copy its code. Locked,
// it is the same vault door as Passwords: one master password for both.
GlassWindow {
    id: win
    title: "Authenticator"; width: 960; height: 660; minimumWidth: 640; minimumHeight: 480; glow: Backend.locked ? "centre" : "top"
    property string doorWhy: ""
    property var sheet: null            // { kind: "add" | "edit", tab, why, code }
    property string flash: ""           // the dial that was just copied
    function tryDoor() { doorWhy = Backend.exists ? Backend.unlock(door.text) : Backend.create(door.text, door2.text); door.text = ""; door2.text = "" }
    function addCode() { sheet = { kind: "add", tab: Backend.canScan ? "scan" : "paste", why: "" } }
    function lockNow() { Backend.lock() }
    function addDone(why) { if (why === "") win.sheet = null; else win.sheet = { kind: "add", tab: win.sheet ? win.sheet.tab : "paste", why: why } }
    function edit(c) { win.sheet = { kind: "edit", code: c, why: "" }; eIssuer.text = c.issuer; eAccount.text = c.account; eSite.text = c.site }
    Connections { target: Backend
        function onFailed(msg) { toast.say(msg, true) }
        function onSaid(msg) { toast.say(msg, false) }
        function onChanged() { if (Backend.locked) { win.sheet = null; win.flash = "" } } }
    Component.onCompleted: if (Backend.locked) door.focusIn()
    Timer { id: unflash; interval: 1400; onTriggered: win.flash = "" }
    DropArea { anchors.fill: parent; enabled: !Backend.locked
        onDropped: function (drop) { if (drop.hasUrls) { var why = Backend.addPicture(drop.urls[0]); if (why) toast.say(why, true) } else if (drop.hasText) { var w2 = Backend.addLink(drop.text); if (w2) toast.say(w2, true) } } }

    islands: [
        Island { visible: !Backend.locked; anchors { right: parent.right; rightMargin: 12 } y: 12
            IslandField { width: 170; placeholder: "Search codes"; onTextChanged: Backend.search(text) }
            Seg { icon: "plus"; text: "Add"; onClicked: win.sheet = { kind: "add", tab: Backend.canScan ? "scan" : "paste", why: "" } }
            Seg { icon: "lock"; tip: "Lock now (Passwords too)"; onClicked: Backend.lock() } },
        Toast { id: toast; anchors { horizontalCenter: parent.horizontalCenter; bottom: parent.bottom; bottomMargin: 24 } },

        // ---------------- add a code / change one
        Item { anchors.fill: parent; z: 20; visible: win.sheet !== null
            Rectangle { anchors.fill: parent; radius: win.r; color: "#66000000"; MouseArea { anchors.fill: parent; acceptedButtons: Qt.AllButtons; onClicked: win.sheet = null } }
            Rectangle { id: card; anchors.centerIn: parent; width: 470; radius: 18; color: Theme.t.menu_bg; border.width: 1; border.color: Theme.t.menu_border
                readonly property string kind: win.sheet ? win.sheet.kind : ""
                readonly property string tab: win.sheet && win.sheet.tab ? win.sheet.tab : ""
                height: kind === "edit" ? 300 : tab === "type" ? 380 : 270
                MouseArea { anchors.fill: parent }
                Label { x: 24; y: 20; font.pixelSize: 17; font.weight: Font.DemiBold; text: card.kind === "edit" ? "Change “" + (win.sheet.code.issuer || "code") + "”" : "Add a code" }
                Row { visible: card.kind === "add"; x: 20; y: 54; spacing: 4
                    Seg { text: "Scan the screen"; on: card.tab === "scan"; onClicked: win.sheet = { kind: "add", tab: "scan", why: "" } }
                    Seg { text: "Paste"; on: card.tab === "paste"; onClicked: win.sheet = { kind: "add", tab: "paste", why: "" } }
                    Seg { objectName: "typeTab"; text: "Type a key"; on: card.tab === "type"; onClicked: { win.sheet = { kind: "add", tab: "type", why: "" }; tIssuer.focusIn() } } }
                Column { x: 24; y: 100; width: parent.width - 48; spacing: 10
                    Label { visible: card.kind === "add" && card.tab === "scan"; width: parent.width; wrapMode: Text.WordWrap
                        text: Backend.canScan ? "Open the site's two-factor set-up page so its QR code is on the screen, then choose the part of the screen with the code in it."
                                              : "Reading QR codes needs zbar-tools, which isn't installed. Paste the set-up link instead, or type the key the site shows under the QR code." }
                    Label { visible: card.kind === "add" && card.tab === "paste"; width: parent.width; wrapMode: Text.WordWrap
                        text: "Copy the set-up link (it starts with otpauth://) or a picture of the QR code, then press Paste. A Google Authenticator export works too, with every code in it. You can also drop a picture onto this window." }
                    TextBox { id: tIssuer; objectName: "tIssuer"; visible: card.tab === "type" && card.kind === "add"; width: parent.width; placeholder: "Site or service, like GitHub"; onAccepted: tAccount.focusIn() }
                    TextBox { id: tAccount; visible: card.tab === "type" && card.kind === "add"; width: parent.width; placeholder: "Your account on it (optional)"; onAccepted: tKey.focusIn() }
                    TextBox { id: tKey; objectName: "tKey"; visible: card.tab === "type" && card.kind === "add"; width: parent.width; mono: true; placeholder: "The key, like JBSW Y3DP EHPK 3PXP"; onAccepted: addTyped.clicked() }
                    TextBox { id: tSite; visible: card.tab === "type" && card.kind === "add"; width: parent.width; placeholder: "Its web address (optional: shows the code in Passwords)" }
                    TextBox { id: eIssuer; objectName: "eIssuer"; visible: card.kind === "edit"; width: parent.width; placeholder: "Site or service" }
                    TextBox { id: eAccount; visible: card.kind === "edit"; width: parent.width; placeholder: "Account" }
                    TextBox { id: eSite; visible: card.kind === "edit"; width: parent.width; placeholder: "Web address (optional)" }
                    Label { visible: !!(win.sheet && win.sheet.why); width: parent.width; wrapMode: Text.WordWrap; color: Theme.t.danger; font.pixelSize: 12; text: win.sheet && win.sheet.why ? win.sheet.why : "" } }
                Btn { visible: card.kind === "edit"; anchors { left: parent.left; leftMargin: 22; bottom: parent.bottom; bottomMargin: 20 } danger: true; text: "Remove"
                    onClicked: { var id = win.sheet.code.id; win.sheet = { kind: "remove", code: win.sheet.code } } }
                Row { anchors { right: parent.right; rightMargin: 22; bottom: parent.bottom; bottomMargin: 20 } spacing: 8
                    Btn { text: "Cancel"; onClicked: win.sheet = null }
                    Btn { visible: card.kind === "add" && card.tab === "scan"; primary: true; text: "Choose the Area"; opacity: Backend.canScan ? 1 : 0.5; onClicked: if (Backend.canScan) { win.sheet = null; Backend.scanScreen() } }
                    Btn { objectName: "pasteBtn"; visible: card.kind === "add" && card.tab === "paste"; primary: true; text: "Paste"; onClicked: win.addDone(Backend.addClipboard()) }
                    Btn { id: addTyped; objectName: "addTyped"; visible: card.kind === "add" && card.tab === "type"; primary: true; text: "Add"
                        onClicked: { var why = Backend.addTyped(tIssuer.text, tAccount.text, tKey.text, tSite.text); if (why === "") { tIssuer.text = ""; tAccount.text = ""; tKey.text = ""; tSite.text = "" } win.addDone(why) } }
                    Btn { visible: card.kind === "edit"; primary: true; text: "Save"
                        onClicked: { var why = Backend.edit(win.sheet.code.id, eIssuer.text, eAccount.text, eSite.text); if (why === "") win.sheet = null; else win.sheet = { kind: "edit", code: win.sheet.code, why: why } } } } }
            // removing is the one thing here that can lock you out of a site: say so, and ask
            Rectangle { visible: win.sheet !== null && win.sheet.kind === "remove"; anchors.centerIn: parent; width: 440; height: 196; radius: 18; color: Theme.t.menu_bg; border.width: 1; border.color: Theme.t.menu_border
                MouseArea { anchors.fill: parent }
                Label { x: 24; y: 20; width: parent.width - 48; elide: Text.ElideRight; font.pixelSize: 17; font.weight: Font.DemiBold; text: "Remove “" + (win.sheet && win.sheet.code ? win.sheet.code.issuer : "") + "”?" }
                Label { x: 24; y: 54; width: parent.width - 48; wrapMode: Text.WordWrap; secondary: true
                    text: "Without this code you may not be able to sign in to that site. Turn two-factor sign-in off on the site first, or make sure you have its backup codes." }
                Row { anchors { right: parent.right; rightMargin: 22; bottom: parent.bottom; bottomMargin: 20 } spacing: 8
                    Btn { text: "Keep It"; onClicked: win.sheet = null }
                    Btn { danger: true; text: "Remove"; onClicked: { var id = win.sheet.code.id; win.sheet = null; Backend.remove(id) } } } } }
    ]

    // ---------------- the door (the same vault as Passwords)
    Column { visible: Backend.locked; anchors.centerIn: parent; anchors.verticalCenterOffset: -20; spacing: 14; width: 340
        Item { width: 120; height: 120; anchors.horizontalCenter: parent.horizontalCenter
            Ring { anchors.fill: parent; value: 0.72; thickness: 7; full: true }
            Glyph { anchors.centerIn: parent; name: Backend.exists ? "lock" : "key"; size: 40; ink: Theme.t.accent } }
        Label { anchors.horizontalCenter: parent.horizontalCenter; font.pixelSize: 22; font.weight: Font.DemiBold; text: Backend.exists ? "Your codes are locked" : "Make your vault" }
        Label { width: parent.width; horizontalAlignment: Text.AlignHCenter; wrapMode: Text.WordWrap; secondary: true
            text: Backend.exists ? "They are kept in the same vault as Passwords. Type its master password." : "Codes are kept in the vault Passwords and the Huginn browser use. Pick a master password for it; there is no way to reset it." }
        TextBox { id: door; objectName: "door"; width: parent.width; secret: true; placeholder: "Master password"; onAccepted: Backend.exists ? win.tryDoor() : door2.focusIn() }
        TextBox { id: door2; visible: !Backend.exists; width: parent.width; secret: true; placeholder: "Master password again"; onAccepted: win.tryDoor() }
        Label { visible: win.doorWhy !== ""; width: parent.width; horizontalAlignment: Text.AlignHCenter; wrapMode: Text.WordWrap; color: Theme.t.danger; font.pixelSize: 12; text: win.doorWhy }
        Btn { anchors.horizontalCenter: parent.horizontalCenter; primary: true; text: Backend.exists ? "Unlock" : "Create Vault"; onClicked: win.tryDoor() } }

    // ---------------- nothing yet
    Column { visible: !Backend.locked && Backend.count === 0; anchors.centerIn: parent; spacing: 12; width: 420
        Glyph { anchors.horizontalCenter: parent.horizontalCenter; name: "shield"; size: 56; ink: Theme.t.accent }
        Label { anchors.horizontalCenter: parent.horizontalCenter; font.pixelSize: 21; font.weight: Font.Bold; text: "No codes yet" }
        Label { width: parent.width; wrapMode: Text.WordWrap; horizontalAlignment: Text.AlignHCenter; secondary: true
            text: "When a site offers two-factor sign-in with an \"authenticator app\", it shows a QR code. Add it here and this app makes the six-digit code the site asks for, with no phone needed." }
        Btn { anchors.horizontalCenter: parent.horizontalCenter; primary: true; text: "Add a Code"; onClicked: win.sheet = { kind: "add", tab: Backend.canScan ? "scan" : "paste", why: "" } } }

    // ---------------- the wall of dials
    Flickable { id: wall; visible: !Backend.locked && Backend.count > 0; x: 16; y: 66; width: parent.width - 32; height: parent.height - 66 - 12; contentHeight: dials.height + 20; clip: true; boundsBehavior: Flickable.StopAtBounds
        Flow { id: dials; objectName: "dials"; width: wall.width; spacing: 0
            readonly property int across: Math.max(1, Math.floor(width / 200))
            Repeater { model: Backend.codes
                Item { id: dial; required property var modelData; width: dials.width / dials.across; height: 240
                    readonly property bool soon: !modelData.hotp && modelData.left <= 5
                    readonly property bool copied: win.flash === modelData.id
                    Pressable { id: face; anchors.horizontalCenter: parent.horizontalCenter; y: 8; width: 178; height: 178; radius: 89; color: dial.copied ? Theme.t.accent : hovered ? Theme.t.hover : Theme.t.island
                        border.width: 1; border.color: Theme.t.islandLine
                        onClicked: { Backend.copyCode(dial.modelData.id); win.flash = dial.modelData.id; unflash.restart() }
                        Ring { anchors { fill: parent; margins: 6 } value: dial.modelData.hotp ? 1 : dial.modelData.share; thickness: 6; full: true; visible: !dial.copied
                            ink: dial.soon ? Theme.t.danger : Theme.t.accent }
                        Label { anchors.centerIn: parent; anchors.verticalCenterOffset: -6; text: dial.copied ? "Copied" : dial.modelData.shown; font.family: dial.copied ? font.family : Theme.t.fontMono
                            font.pixelSize: dial.copied ? 20 : (dial.modelData.digits > 6 ? 25 : 30); font.weight: Font.Bold; color: dial.copied ? Theme.t.onAccent : dial.soon ? Theme.t.danger : Theme.t.text }
                        Label { visible: !dial.copied; anchors { horizontalCenter: parent.horizontalCenter; top: parent.verticalCenter; topMargin: 18 } font.pixelSize: 11; secondary: true
                            text: dial.modelData.hotp ? "on demand" : Math.ceil(dial.modelData.left) + " s" + (face.hovered && dial.modelData.next ? "  ·  next " + dial.modelData.next : "") } }
                    Label { anchors.horizontalCenter: parent.horizontalCenter; y: 194; width: parent.width - 24; horizontalAlignment: Text.AlignHCenter; elide: Text.ElideRight; text: dial.modelData.issuer; font.weight: Font.DemiBold }
                    Label { anchors.horizontalCenter: parent.horizontalCenter; y: 213; width: parent.width - 24; horizontalAlignment: Text.AlignHCenter; elide: Text.ElideMiddle; text: dial.modelData.account; secondary: true; font.pixelSize: 11 }
                    Row { visible: face.hovered || more.hovered || nxt.hovered; anchors { right: face.right; top: face.top } spacing: 4
                        Pressable { id: nxt; visible: dial.modelData.hotp; width: 28; height: 28; radius: 14; color: hovered ? Theme.t.hover : Theme.t.menu_bg; border.width: 1; border.color: Theme.t.islandLine
                            onClicked: Backend.nextCode(dial.modelData.id); Glyph { anchors.centerIn: parent; name: "next"; size: 12 } }
                        Pressable { id: more; width: 28; height: 28; radius: 14; color: hovered ? Theme.t.hover : Theme.t.menu_bg; border.width: 1; border.color: Theme.t.islandLine
                            onClicked: win.edit(dial.modelData); Glyph { anchors.centerIn: parent; name: "edit"; size: 12 } } } } } }
        Label { visible: Backend.codes.length === 0; anchors.horizontalCenter: parent.horizontalCenter; y: 60; secondary: true; text: "Nothing matches" } }
}
