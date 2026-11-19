import QtQuick

// Passwords, "the vault door": locked, the window is one door with the light behind it; open, a list at the left and
// one entry at a time at the right, with nothing shown that you didn't ask to see.
GlassWindow {
    id: win
    title: "Passwords"; width: 980; height: 640; glow: Backend.locked ? "centre" : "bottom"
    property string query: ""
    property string at: ""                     // the entry being shown
    property var one: ({})                     // its fields, password included, only while shown
    property bool editing: false
    property bool shown: false                 // the password is in the open
    property var sheet: null                   // { kind: "delete" | "import" | "export" | "master" }
    property string doorWhy: ""
    property var rows: Backend.entries.filter(function (e) { var q = query.toLowerCase(); return q === "" || (e.title + " " + e.user + " " + e.site).toLowerCase().indexOf(q) >= 0 })
    function open(id) { at = id; one = id === "" ? ({}) : Backend.entry(id); editing = false; shown = false }
    function startNew() { at = ""; one = ({ title: "", user: "", password: Backend.generate(18, true, true), site: "", notes: "" }); editing = true; shown = true; fill() }
    function fill() { fTitle.text = one.title || ""; fUser.text = one.user || ""; fPass.text = one.password || ""; fSite.text = one.site || ""; fNotes.many = one.notes || "" }
    function keep() { var id = Backend.save(at, { title: fTitle.text, user: fUser.text, password: fPass.text, site: fSite.text, notes: fNotes.many }); if (id !== "") open(id) }
    function tryDoor() { doorWhy = Backend.exists ? Backend.unlock(door.text) : Backend.create(door.text, door2.text); door.text = ""; door2.text = "" }
    Connections { target: Backend
        function onFailed(msg) { toast.say(msg, true) }
        function onSaid(msg) { toast.say(msg, false) }
        function onChanged() { if (Backend.locked) { win.at = ""; win.one = ({}); win.editing = false; win.sheet = null; win.query = ""; door.focusIn() }
                               else if (win.at !== "" && !win.editing) win.one = Backend.entry(win.at) } }
    Component.onCompleted: if (Backend.locked) door.focusIn()

    islands: [
        Island { visible: !Backend.locked; anchors { right: parent.right; rightMargin: 12 } y: 12
            IslandField { id: search; width: 190; placeholder: "Search passwords"; onTextChanged: win.query = text }
            Seg { icon: "plus"; tip: "New password"; onClicked: win.startNew() }
            Seg { icon: "lock"; tip: "Lock now"; onClicked: Backend.lock() } },
        Island { visible: !Backend.locked; anchors { horizontalCenter: parent.horizontalCenter; bottom: parent.bottom; bottomMargin: 14 }
            Label { leftPadding: 10; rightPadding: 6; anchors.verticalCenter: parent.verticalCenter; font.pixelSize: 12; secondary: true
                text: Backend.entries.length + (Backend.entries.length === 1 ? " password" : " passwords") + (Backend.troubled ? " · " + Backend.troubled + " weak or reused" : " · all in good shape")
                      + (Backend.mailCount ? " · " + Backend.mailCount + (Backend.mailCount === 1 ? " mail account" : " mail accounts") + " kept here" : "") }
            IslandGap {}
            Seg { text: "Import"; onClicked: win.sheet = { kind: "import", files: Backend.importChoices() } }
            Seg { text: "Export"; onClicked: win.sheet = { kind: "export" } }
            Seg { text: "Master password"; onClicked: win.sheet = { kind: "master", why: "" } }
            Seg { text: "Unlock once"; on: Backend.shared; tip: Backend.shared ? "Unlocking here also unlocks the browser and Mail, until you lock or an hour passes unused. Click to turn off."
                                                                           : "Each app asks for the master password itself. Click to unlock them all together."; tipAbove: true
                onClicked: Backend.setShared(!Backend.shared) } },
        Toast { id: toast; anchors { horizontalCenter: parent.horizontalCenter; bottom: parent.bottom; bottomMargin: 64 } },
        Item { anchors.fill: parent; z: 20; visible: win.sheet !== null
            Rectangle { anchors.fill: parent; radius: win.r; color: "#66000000"; MouseArea { anchors.fill: parent; acceptedButtons: Qt.AllButtons } }
            Rectangle { id: card; anchors.centerIn: parent; width: 440; radius: 16; color: Theme.t.menu_bg; border.width: 1; border.color: Theme.t.menu_border
                readonly property string kind: win.sheet ? win.sheet.kind : ""
                height: kind === "master" ? 290 : kind === "import" ? 150 + Math.max(1, choices.count) * 34 : 176
                Label { x: 22; y: 20; width: parent.width - 44; font.pixelSize: 16; font.weight: Font.DemiBold; elide: Text.ElideRight
                    text: card.kind === "delete" ? "Delete “" + (win.one.title || "this entry") + "”?" : card.kind === "import" ? "Import passwords" : card.kind === "export" ? "Export every password?" : "Change the master password" }
                Label { visible: card.kind === "delete" || card.kind === "export"; x: 22; y: 52; width: parent.width - 44; wrapMode: Text.WordWrap; secondary: true
                    text: card.kind === "delete" ? "This can't be undone." : "The file is written in the open, so anyone who gets it can read them all. Use it to move to another app, then delete it. It is saved as “Huginn passwords.csv” in Documents." }
                Column { visible: card.kind === "import"; x: 16; y: 52; width: parent.width - 32
                    Label { x: 6; height: 24; secondary: true; font.pixelSize: 12; width: parent.width - 12; elide: Text.ElideRight
                        text: choices.count ? "Files a browser or another app exported (.csv):" : "Export your passwords from the browser as a .csv into Downloads, then come back." }
                    Repeater { id: choices; model: card.kind === "import" ? win.sheet.files : []
                        Pressable { required property var modelData; width: parent.width; height: 34; radius: 9; onClicked: { var p = modelData.path; win.sheet = null; Backend.importCsv(p) }
                            Glyph { x: 10; anchors.verticalCenter: parent.verticalCenter; name: "doc"; size: 15 }
                            Label { x: 36; width: parent.width - 170; elide: Text.ElideMiddle; anchors.verticalCenter: parent.verticalCenter; text: modelData.name }
                            Label { anchors { right: parent.right; rightMargin: 10; verticalCenter: parent.verticalCenter } text: modelData.where + " · " + modelData.when; secondary: true; font.pixelSize: 11 } } } }
                Column { visible: card.kind === "master"; x: 22; y: 56; spacing: 8
                    TextBox { id: mOld; width: card.width - 44; secret: true; placeholder: "Current master password"; onAccepted: mNew.focusIn() }
                    TextBox { id: mNew; width: card.width - 44; secret: true; placeholder: "New master password"; onAccepted: mNew2.focusIn() }
                    TextBox { id: mNew2; width: card.width - 44; secret: true; placeholder: "New one again"; onAccepted: changeBtn.clicked() }
                    Label { width: card.width - 44; wrapMode: Text.WordWrap; font.pixelSize: 12; color: win.sheet && win.sheet.why ? Theme.t.danger : Theme.t.text_secondary
                        text: card.kind === "master" && win.sheet.why ? win.sheet.why : "There is no way to get in without it, so pick one you will remember." } }
                Row { anchors { right: parent.right; rightMargin: 22; bottom: parent.bottom; bottomMargin: 20 } spacing: 8
                    Btn { text: "Cancel"; onClicked: { win.sheet = null; mOld.text = ""; mNew.text = ""; mNew2.text = "" } }
                    Btn { visible: card.kind === "delete"; danger: true; text: "Delete"; onClicked: { var id = win.at; win.sheet = null; win.open(""); Backend.remove(id) } }
                    Btn { visible: card.kind === "export"; primary: true; text: "Export"; onClicked: { win.sheet = null; Backend.exportCsv(Backend.exportPath) } }
                    Btn { id: changeBtn; visible: card.kind === "master"; primary: true; text: "Change"
                        onClicked: { var why = Backend.changeMaster(mOld.text, mNew.text, mNew2.text); mOld.text = ""; mNew.text = ""; mNew2.text = ""; if (why === "") win.sheet = null; else win.sheet = { kind: "master", why: why } } } } } }
    ]

    // ---------------- the door
    Column { visible: Backend.locked; anchors.centerIn: parent; anchors.verticalCenterOffset: -30; spacing: 14; width: 340
        Rectangle { width: 92; height: 92; radius: 46; anchors.horizontalCenter: parent.horizontalCenter; color: Theme.t.island; border.width: 1; border.color: Theme.t.islandLine
            Glyph { anchors.centerIn: parent; name: Backend.exists ? "lock" : "key"; size: 40; ink: Theme.t.accent } }
        Label { anchors.horizontalCenter: parent.horizontalCenter; font.pixelSize: 22; font.weight: Font.DemiBold; text: Backend.exists ? "Your vault is locked" : "Make your vault" }
        Label { width: parent.width; horizontalAlignment: Text.AlignHCenter; wrapMode: Text.WordWrap; secondary: true
            text: Backend.exists ? "Type the master password to open it. It is the same vault the Huginn browser fills from." : "One master password locks everything in it, here and in the Huginn browser. It is never saved anywhere, so there is no way to reset it: choose a few unrelated words you will remember." }
        TextBox { id: door; objectName: "door"; width: parent.width; secret: true; placeholder: "Master password"; onAccepted: Backend.exists ? win.tryDoor() : door2.focusIn() }
        TextBox { id: door2; objectName: "door2"; visible: !Backend.exists; width: parent.width; secret: true; placeholder: "Master password again"; onAccepted: win.tryDoor() }
        Label { visible: win.doorWhy !== ""; width: parent.width; horizontalAlignment: Text.AlignHCenter; wrapMode: Text.WordWrap; color: Theme.t.danger; font.pixelSize: 12; text: win.doorWhy }
        Btn { anchors.horizontalCenter: parent.horizontalCenter; primary: true; text: Backend.exists ? "Unlock" : "Create Vault"; onClicked: win.tryDoor() }
    }

    // ---------------- open: the cabinet. Every login is a tile; choosing one opens its card and the rest step aside.
    readonly property bool showPane: at !== "" || editing
    Flickable { id: cab; visible: !Backend.locked; x: 14; y: 62; width: win.showPane ? 296 : parent.width - 28; height: parent.height - 62 - 70; contentHeight: tiles.height + 4; clip: true; boundsBehavior: Flickable.StopAtBounds
        Behavior on width { NumberAnimation { duration: 160; easing.type: Easing.OutCubic } }
        Flow { id: tiles; width: cab.width; spacing: 10
            Repeater { model: win.rows
                Pressable { id: tile; required property var modelData; required property int index; readonly property bool on: win.at === modelData.id
                    readonly property color hue: Qt.hsla(((modelData.title.charCodeAt(0) || 65) * 37 % 360) / 360, 0.5, Theme.t.dark ? 0.52 : 0.44, 1)
                    width: 143; height: 122; radius: 18; color: on ? Theme.t.accent : hovered ? Theme.t.hover : Theme.t.island; border.width: 1; border.color: on ? Theme.t.accent : Theme.t.islandLine
                    onClicked: win.open(on ? "" : modelData.id)
                    Rectangle { x: 14; y: 14; width: 46; height: 46; radius: 15; color: tile.on ? Qt.rgba(1, 1, 1, 0.24) : tile.hue
                        Label { anchors.centerIn: parent; text: tile.modelData.title.charAt(0).toUpperCase(); font.pixelSize: 21; font.weight: Font.Bold; color: "#FFFFFF" } }
                    Rectangle { visible: tile.modelData.health !== ""; anchors { right: parent.right; top: parent.top; margins: 14 } width: 10; height: 10; radius: 5; color: tile.on ? Theme.t.onAccent : Theme.t.danger }
                    Label { x: 14; y: 70; width: parent.width - 28; elide: Text.ElideRight; text: tile.modelData.title; font.weight: Font.DemiBold; color: tile.on ? Theme.t.onAccent : Theme.t.text }
                    Label { x: 14; y: 90; width: parent.width - 28; elide: Text.ElideMiddle; text: tile.modelData.user || tile.modelData.site; font.pixelSize: 11; color: tile.on ? Theme.t.onAccent : Theme.t.text_secondary } } }
            Pressable { visible: !win.query; width: 143; height: 122; radius: 18; color: hovered ? Theme.t.hover : "transparent"; border.width: 1; border.color: Theme.t.capsule_border; onClicked: win.startNew()
                Glyph { anchors.centerIn: parent; anchors.verticalCenterOffset: -8; name: "plus"; size: 24; ink: Theme.t.text_secondary }
                Label { anchors { horizontalCenter: parent.horizontalCenter; bottom: parent.bottom; bottomMargin: 18 } text: "New"; secondary: true; font.pixelSize: 12 } } }
        Label { visible: win.rows.length === 0 && win.query !== ""; anchors.horizontalCenter: parent.horizontalCenter; y: 40; secondary: true; text: "Nothing matches" }
    }

    // ---------------- open: one entry
    component Line: Item { property string name; property string value; property bool hide: false; property string act: ""; property string actIcon: "doc"
        signal acted()
        width: pane.width - 48; height: 54
        Label { text: parent.name; secondary: true; font.pixelSize: 11 }
        Label { y: 20; width: parent.width - 90; elide: Text.ElideRight; font.pixelSize: 15; font.family: parent.hide ? Theme.t.fontMono : Theme.t.font; text: parent.value }
        Seg { visible: parent.act !== ""; anchors { right: parent.right; verticalCenter: undefined } y: 14; text: parent.act; onClicked: parent.acted() }
        Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: Theme.t.separator } }
    Rectangle { id: pane; visible: !Backend.locked && win.showPane; x: 322; y: 62; width: parent.width - 322 - 14; height: parent.height - 62 - 70; radius: 22; color: Theme.t.island; border.width: 1; border.color: Theme.t.islandLine
        Column { visible: win.at === "" && !win.editing; anchors.centerIn: parent; spacing: 10
            Glyph { name: "key"; size: 44; ink: Theme.t.text_secondary; anchors.horizontalCenter: parent.horizontalCenter }
            Label { secondary: true; text: Backend.entries.length ? "Choose an entry, or make a new one" : "Add your first password, or import them from your browser"; anchors.horizontalCenter: parent.horizontalCenter }
            Btn { primary: true; text: "New Password"; anchors.horizontalCenter: parent.horizontalCenter; onClicked: win.startNew() } }
        Column { visible: win.at !== "" && !win.editing; x: 24; y: 22; spacing: 10; width: parent.width - 48
            Item { width: parent.width; height: 44
                Label { width: parent.width - 170; elide: Text.ElideRight; font.pixelSize: 24; font.weight: Font.DemiBold; text: win.one.title || win.one.site || "Untitled" }
                Row { anchors.right: parent.right; spacing: 6; Btn { text: "Edit"; onClicked: { win.editing = true; win.shown = false; win.fill() } } Btn { text: "Delete"; onClicked: win.sheet = { kind: "delete" } } } }
            Line { visible: !!win.one.user; name: "Name"; value: win.one.user || ""; act: "Copy"; onActed: Backend.copy(win.at, "user") }
            Item { width: parent.width; height: 74
                Label { text: "Password"; secondary: true; font.pixelSize: 11 }
                Label { y: 20; width: parent.width - 150; elide: Text.ElideRight; font.pixelSize: 15; font.family: Theme.t.fontMono; text: win.shown ? (win.one.password || "") : "••••••••••••" }
                Row { anchors.right: parent.right; y: 14; spacing: 2
                    Seg { anchors.verticalCenter: undefined; icon: "eye"; on: win.shown; tip: win.shown ? "Hide" : "Show"; onClicked: win.shown = !win.shown }
                    Seg { anchors.verticalCenter: undefined; text: "Copy"; onClicked: Backend.copy(win.at, "password") } }
                Row { y: 50; spacing: 4
                    Repeater { model: 4; Rectangle { required property int index; width: 38; height: 4; radius: 2
                        color: index < (win.one.strength || 0) ? ((win.one.strength || 0) < 2 ? Theme.t.danger : Theme.t.accent) : Theme.t.group } }
                    Label { leftPadding: 8; y: -6; font.pixelSize: 11; secondary: true; text: ["", "Weak: easy to guess", "Fair", "Good", "Strong"][win.one.strength || 0] } }
                Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: Theme.t.separator } }
            Repeater { id: twofa; model: []                         // codes Authenticator keeps for this site, ticking along
                Line { required property var modelData; name: "Two-factor code · " + (modelData.issuer || "Authenticator") + (modelData.left ? " · " + modelData.left + " s" : "")
                    value: modelData.shown; hide: true; act: "Copy"; onActed: Backend.copyCode(modelData.code) } }
            Timer { running: win.at !== "" && !win.editing && !Backend.locked; repeat: true; interval: 1000; triggeredOnStart: true; onTriggered: twofa.model = Backend.codesFor(win.at) }
            Line { visible: !!win.one.site; name: /^https?:/.test(win.one.site || "") ? "Website · the browser offers this login there" : "Where"; value: win.one.site || ""
                act: /^https?:/.test(win.one.site || "") ? "Open" : "Copy"; onActed: /^https?:/.test(win.one.site || "") ? Backend.visit(win.at) : Backend.copy(win.at, "site") }
            Item { visible: !!win.one.notes; width: parent.width; height: noteText.height + 26
                Label { text: "Notes"; secondary: true; font.pixelSize: 11 }
                Label { id: noteText; y: 20; width: parent.width; wrapMode: Text.WordWrap; text: win.one.notes || "" } }
            Label { secondary: true; font.pixelSize: 11; text: win.one.changedText ? "Changed " + win.one.changedText : "" }
        }
        Column { visible: win.editing; x: 24; y: 22; spacing: 9; width: parent.width - 48
            Label { font.pixelSize: 20; font.weight: Font.DemiBold; text: win.at === "" ? "New password" : "Edit" }
            TextBox { id: fTitle; width: parent.width; placeholder: "What it is for (Bank, Mail…)" }
            TextBox { id: fUser; width: parent.width; placeholder: "Name or email you sign in with" }
            Row { spacing: 6; width: parent.width
                TextBox { id: fPass; width: parent.width - 232; mono: true; secret: !win.shown; placeholder: "Password" }
                Seg { anchors.verticalCenter: undefined; y: 3; icon: "eye"; on: win.shown; tip: win.shown ? "Hide" : "Show"; onClicked: win.shown = !win.shown }
                Btn { y: 3; text: "Random"; onClicked: { fPass.text = Backend.generate(18, true, true); win.shown = true } }
                Btn { y: 3; text: "Words"; onClicked: { fPass.text = Backend.phrase(4); win.shown = true } } }
            Row { spacing: 4
                Repeater { model: 4; Rectangle { required property int index; width: 38; height: 4; radius: 2; readonly property int s: Backend.strength(fPass.text)
                    color: index < s ? (s < 2 ? Theme.t.danger : Theme.t.accent) : Theme.t.group } }
                Label { leftPadding: 8; y: -6; font.pixelSize: 11; secondary: true; text: ["Type one, or let Huginn make it", "Weak: easy to guess", "Fair", "Good", "Strong"][Backend.strength(fPass.text)] } }
            TextBox { id: fSite; width: parent.width; placeholder: "Website, so the browser can fill it in (optional)" }
            TextBox { id: fNotes; width: parent.width; lines: 4; placeholder: "Notes (optional)" }
            Row { spacing: 8; Btn { primary: true; text: "Save"; onClicked: win.keep() } Btn { text: "Cancel"; onClicked: win.open(win.at) } }
        }
    }
    Shortcut { sequence: "Ctrl+F"; enabled: !Backend.locked; onActivated: search.focusInput() }
    Shortcut { sequence: "Ctrl+N"; enabled: !Backend.locked; onActivated: win.startNew() }
    Shortcut { sequence: "Ctrl+L"; enabled: !Backend.locked; onActivated: Backend.lock() }
}
