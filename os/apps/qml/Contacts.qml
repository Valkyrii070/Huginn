import QtQuick

// Contacts, "the index": the alphabet runs down the edge like the tabs of an address book; a person opens as a card.
GlassWindow {
    id: win
    title: "Contacts"; width: 980; height: 660; glow: "top"
    property string query: ""
    property string at: ""
    property var one: ({})
    property bool editing: false
    property var sheet: null                   // { kind: "delete" | "import" }
    readonly property var kinds: ["mobile", "home", "work"]
    property var flat: {                       // the list as it is drawn: favourites, then a heading before each letter
        var q = query.toLowerCase(), people = Backend.people.filter(function (p) { return q === "" || p.find.indexOf(q) >= 0 }), out = [], last = ""
        var favs = people.filter(function (p) { return p.fav })
        if (favs.length && q === "") { out.push({ head: "Favourites" }); favs.forEach(function (p) { out.push(p) }) }
        people.forEach(function (p) { if (p.letter !== last) { last = p.letter; out.push({ head: last }) } out.push(p) })
        return out
    }
    readonly property var letters: { var s = {}; Backend.people.forEach(function (p) { s[p.letter] = true }); return s }
    function open(id) { at = id; one = id === "" ? ({}) : Backend.person(id); editing = false }
    function jump(letter) { for (var i = 0; i < flat.length; i++) if (flat[i].head === letter) { list.positionViewAtIndex(i); return } }
    function startEdit(fresh) {
        if (fresh) { at = ""; one = ({ phones: [], emails: [] }) }
        var p = one.phones || [], e = one.emails || []
        fName.text = one.name || ""; fOrg.text = one.org || ""; fTitle.text = one.title || ""; fP1.text = p[0] ? p[0].value : ""; fP2.text = p[1] ? p[1].value : ""
        k1.kind = p[0] ? p[0].kind : "mobile"; k2.kind = p[1] ? p[1].kind : "home"; fE1.text = e[0] ? e[0].value : ""; fE2.text = e[1] ? e[1].value : ""
        ke1.kind = e[0] ? e[0].kind : "home"; ke2.kind = e[1] ? e[1].kind : "work"; fAddr.many = one.address || ""; fBday.text = one.birthday || ""; fSite.text = one.site || ""; fNotes.many = one.notes || ""
        editing = true; fName.focusIn()
    }
    function keep() {
        var more = { phones: (one.phones || []).slice(2), emails: (one.emails || []).slice(2) }
        var id = Backend.save(at, { name: fName.text, org: fOrg.text, title: fTitle.text, phones: [{ kind: k1.kind, value: fP1.text }, { kind: k2.kind, value: fP2.text }].concat(more.phones),
                                     emails: [{ kind: ke1.kind, value: fE1.text }, { kind: ke2.kind, value: fE2.text }].concat(more.emails), address: fAddr.many, birthday: fBday.text, site: fSite.text, notes: fNotes.many })
        if (id !== "") open(id)
    }
    Connections { target: Backend
        function onFailed(msg) { toast.say(msg, true) }
        function onSaid(msg) { toast.say(msg, false) }
        function onChanged() { if (win.at !== "" && !win.editing) { win.one = Backend.person(win.at); if (win.one.id === undefined) win.at = "" } } }
    Component.onCompleted: search.forceActiveFocus()

    islands: [
        Island { anchors { right: parent.right; rightMargin: 12 } y: 12
            IslandField { id: search; width: 190; placeholder: "Search people"; onTextChanged: win.query = text }
            Seg { icon: "plus"; tip: "New contact"; onClicked: win.startEdit(true) }
            IslandGap {}
            Seg { text: "Import"; onClicked: win.sheet = { kind: "import", files: Backend.importChoices() } }
            Seg { text: "Export All"; opacity: Backend.count ? 1 : 0.4; onClicked: if (Backend.count) Backend.exportFile(Backend.exportPath(""), "") } },
        Rectangle {   // the index
            x: 14; y: 62; width: 34; height: parent.height - 76; radius: 16; color: Theme.t.island; border.width: 1; border.color: Theme.t.islandLine
            Column { anchors.centerIn: parent
                Repeater { model: "ABCDEFGHIJKLMNOPQRSTUVWXYZ#".split("")
                    Item { required property string modelData; width: 34; height: Math.min(20, (win.height - 100) / 27)
                        Label { anchors.centerIn: parent; text: modelData; font.pixelSize: 10; font.weight: win.letters[modelData] ? Font.Bold : Font.Normal
                            color: win.letters[modelData] ? Theme.t.accent : Theme.t.text_tertiary }
                        MouseArea { anchors.fill: parent; enabled: !!win.letters[modelData]; onClicked: win.jump(modelData) } } } } },
        Toast { id: toast; anchors { horizontalCenter: parent.horizontalCenter; bottom: parent.bottom; bottomMargin: 18 } },
        Item { anchors.fill: parent; z: 20; visible: win.sheet !== null
            Rectangle { anchors.fill: parent; radius: win.r; color: "#66000000"; MouseArea { anchors.fill: parent; acceptedButtons: Qt.AllButtons } }
            Rectangle { id: card; anchors.centerIn: parent; width: 440; radius: 16; color: Theme.t.menu_bg; border.width: 1; border.color: Theme.t.menu_border
                readonly property string kind: win.sheet ? win.sheet.kind : ""
                height: kind === "import" ? 150 + Math.max(1, choices.count) * 34 : 160
                Label { x: 22; y: 20; width: parent.width - 44; font.pixelSize: 16; font.weight: Font.DemiBold; elide: Text.ElideRight
                    text: card.kind === "delete" ? "Delete " + (win.one.name || "this contact") + "?" : "Import contacts" }
                Label { visible: card.kind === "delete"; x: 22; y: 52; secondary: true; text: "This can't be undone." }
                Column { visible: card.kind === "import"; x: 16; y: 52; width: parent.width - 32
                    Label { x: 6; height: 24; secondary: true; font.pixelSize: 12; width: parent.width - 12; wrapMode: Text.WordWrap
                        text: choices.count ? "Contact files (.vcf) in Downloads, Documents and on the Desktop:" : "Export contacts from your phone or another app as a .vcf into Downloads, then come back." }
                    Repeater { id: choices; model: card.kind === "import" ? win.sheet.files : []
                        Pressable { required property var modelData; width: parent.width; height: 34; radius: 9; onClicked: { var p = modelData.path; win.sheet = null; Backend.importFile(p) }
                            Glyph { x: 10; anchors.verticalCenter: parent.verticalCenter; name: "user"; size: 15 }
                            Label { x: 36; width: parent.width - 170; elide: Text.ElideMiddle; anchors.verticalCenter: parent.verticalCenter; text: modelData.name }
                            Label { anchors { right: parent.right; rightMargin: 10; verticalCenter: parent.verticalCenter } text: modelData.where + " · " + modelData.when; secondary: true; font.pixelSize: 11 } } } }
                Row { anchors { right: parent.right; rightMargin: 22; bottom: parent.bottom; bottomMargin: 20 } spacing: 8
                    Btn { text: "Cancel"; onClicked: win.sheet = null }
                    Btn { visible: card.kind === "delete"; danger: true; text: "Delete"; onClicked: { var id = win.at; win.sheet = null; win.open(""); Backend.remove(id) } } } } }
    ]

    // ---------------- faces: everyone as a round portrait under their letter; choosing one opens their card beside them
    readonly property bool showPane: at !== "" || editing
    Flickable { id: list; x: 58; y: 62; width: win.showPane ? 286 : parent.width - 72; height: parent.height - 76; contentHeight: faces.height + 8; clip: true; boundsBehavior: Flickable.StopAtBounds
        Behavior on width { NumberAnimation { duration: 160; easing.type: Easing.OutCubic } }
        function positionViewAtIndex(i) { var it = people.itemAt(i); if (it) contentY = Math.max(0, Math.min(it.y, contentHeight - height)) }
        Flow { id: faces; width: list.width; spacing: 4
            Repeater { id: people; model: win.flat
                Item { id: face; required property var modelData; readonly property bool on: !modelData.head && win.at === modelData.id
                    readonly property color hue: Qt.hsla((((modelData.initials || "A").charCodeAt(0) * 29 + ((modelData.initials || "AA").charCodeAt(1) || 7) * 13) % 360) / 360, 0.46, Theme.t.dark ? 0.5 : 0.42, 1)
                    width: modelData.head ? faces.width : 92; height: modelData.head ? 30 : 118
                    Label { visible: !!face.modelData.head; x: 8; anchors.bottom: parent.bottom; anchors.bottomMargin: 4; text: face.modelData.head || ""; font.pixelSize: 12; font.weight: Font.Bold; color: Theme.t.accent }
                    Rectangle { visible: !!face.modelData.head; x: 8 + 26 + (face.modelData.head || "").length * 6; anchors.bottom: parent.bottom; anchors.bottomMargin: 11; width: parent.width - x - 8; height: 1; color: Theme.t.islandLine }
                    Pressable { visible: !face.modelData.head; anchors.fill: parent; radius: 16; color: hovered ? Theme.t.hover : "transparent"; onClicked: win.open(face.on ? "" : face.modelData.id)
                        Rectangle { anchors.horizontalCenter: parent.horizontalCenter; y: 8; width: 64; height: 64; radius: 32; color: face.hue; border.width: face.on ? 4 : 0; border.color: Theme.t.accent
                            Label { anchors.centerIn: parent; text: face.modelData.initials || ""; font.pixelSize: 21; font.weight: Font.DemiBold; color: "#FFFFFF" } }
                        Label { y: 78; width: parent.width - 8; x: 4; horizontalAlignment: Text.AlignHCenter; elide: Text.ElideRight; text: (face.modelData.name || "").split(" ")[0]; font.pixelSize: 12; font.weight: face.on ? Font.Bold : Font.Medium; color: face.on ? Theme.t.accent : Theme.t.text }
                        Label { y: 95; width: parent.width - 8; x: 4; horizontalAlignment: Text.AlignHCenter; elide: Text.ElideRight; text: (face.modelData.name || "").split(" ").slice(1).join(" "); secondary: true; font.pixelSize: 10 } } } } }
        Label { visible: win.flat.length === 0; anchors.horizontalCenter: parent.horizontalCenter; y: 60; secondary: true; text: win.query ? "Nobody matches" : "No contacts yet" }
    }

    component Fact: Item { property string name; property string value; property string kind: ""; property string icon: ""
        width: pane.width - 56; height: Math.max(48, val.height + 28); visible: value !== ""
        Label { text: parent.name; secondary: true; font.pixelSize: 11 }
        Label { id: val; y: 19; width: parent.width - 90; wrapMode: Text.WordWrap; font.pixelSize: 14; text: parent.value }
        Row { anchors.right: parent.right; y: 10; spacing: 2
            Seg { anchors.verticalCenter: undefined; visible: parent.parent.icon !== ""; icon: parent.parent.icon; tip: parent.parent.kind === "email" ? "Write an email" : parent.parent.kind === "phone" ? "Call" : "Open"
                onClicked: Backend.reach(parent.parent.kind, parent.parent.value) }
            Seg { anchors.verticalCenter: undefined; icon: "doc"; tip: "Copy"; onClicked: { copier.text = parent.parent.value; copier.selectAll(); copier.copy(); toast.say("Copied.", false) } } }
        Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: Theme.t.separator } }
    TextEdit { id: copier; visible: false }
    component Kind: Seg { property string kind: "mobile"; anchors.verticalCenter: undefined; y: 3; width: 74; text: kind.charAt(0).toUpperCase() + kind.slice(1)
        onClicked: kind = win.kinds[(win.kinds.indexOf(kind) + 1) % win.kinds.length] }

    Rectangle { id: pane; visible: win.showPane; x: 356; y: 62; width: parent.width - 370; height: parent.height - 76; radius: 22; color: Theme.t.island; border.width: 1; border.color: Theme.t.islandLine; clip: true
        Column { visible: win.at === "" && !win.editing; anchors.centerIn: parent; spacing: 10
            Glyph { name: "user"; size: 44; ink: Theme.t.text_secondary; anchors.horizontalCenter: parent.horizontalCenter }
            Label { secondary: true; anchors.horizontalCenter: parent.horizontalCenter; text: Backend.count ? "Choose someone" : "Add someone, or import a .vcf from your phone" }
            Btn { primary: true; text: "New Contact"; anchors.horizontalCenter: parent.horizontalCenter; onClicked: win.startEdit(true) } }
        Flickable { visible: win.at !== "" && !win.editing; anchors.fill: parent; contentHeight: view.height + 40; clip: true
            Column { id: view; x: 28; y: 24; width: parent.width - 56; spacing: 8
                Row { spacing: 18; height: 92
                    Rectangle { width: 84; height: 84; radius: 42; color: Qt.rgba(win.tintColor.r, win.tintColor.g, win.tintColor.b, 0.22); border.width: 1; border.color: Theme.t.accent
                        Label { anchors.centerIn: parent; text: win.one.initials || ""; font.pixelSize: 30; font.weight: Font.DemiBold; color: Theme.t.accent } }
                    Column { anchors.verticalCenter: parent.verticalCenter; spacing: 3; width: view.width - 270
                        Label { width: parent.width; elide: Text.ElideRight; font.pixelSize: 24; font.weight: Font.DemiBold; text: win.one.name || "" }
                        Label { visible: text !== ""; width: parent.width; elide: Text.ElideRight; secondary: true; text: [win.one.title, win.one.org].filter(function (x) { return x }).join(" · ") } } }
                Row { spacing: 6
                    Btn { text: win.one.fav ? "★ Favourite" : "☆ Favourite"; onClicked: Backend.toggleFav(win.at) }
                    Btn { text: "Edit"; onClicked: win.startEdit(false) }
                    Btn { text: "Share"; onClicked: Backend.exportFile(Backend.exportPath(win.at), win.at) }
                    Btn { text: "Delete"; onClicked: win.sheet = { kind: "delete" } } }
                Item { width: 1; height: 4 }
                Repeater { model: win.one.phones || []
                    Fact { required property var modelData; name: modelData.kind.charAt(0).toUpperCase() + modelData.kind.slice(1); value: modelData.value; kind: "phone"; icon: "phone" } }
                Repeater { model: win.one.emails || []
                    Fact { required property var modelData; name: "Email · " + modelData.kind; value: modelData.value; kind: "email"; icon: "mail" } }
                Fact { name: "Address"; value: win.one.address || "" }
                Fact { name: "Birthday"; value: win.one.birthdayText || "" }
                Fact { name: "Website"; value: win.one.site || ""; kind: "site"; icon: "forward" }
                Fact { name: "Notes"; value: win.one.notes || "" } } }
        Flickable { visible: win.editing; anchors.fill: parent; contentHeight: form.height + 44; clip: true
            Column { id: form; x: 28; y: 22; spacing: 8; width: parent.width - 56
                Label { font.pixelSize: 20; font.weight: Font.DemiBold; text: win.at === "" ? "New contact" : "Edit" }
                TextBox { id: fName; width: parent.width; placeholder: "Name" }
                Row { spacing: 8; TextBox { id: fOrg; width: (form.width - 8) / 2; placeholder: "Company (optional)" } TextBox { id: fTitle; width: (form.width - 8) / 2; placeholder: "Job (optional)" } }
                Row { spacing: 6; Kind { id: k1 } TextBox { id: fP1; width: form.width - 80; placeholder: "Phone" } }
                Row { spacing: 6; Kind { id: k2; kind: "home" } TextBox { id: fP2; width: form.width - 80; placeholder: "Another phone" } }
                Row { spacing: 6; Kind { id: ke1; kind: "home" } TextBox { id: fE1; width: form.width - 80; placeholder: "Email" } }
                Row { spacing: 6; Kind { id: ke2; kind: "work" } TextBox { id: fE2; width: form.width - 80; placeholder: "Another email" } }
                TextBox { id: fAddr; width: parent.width; lines: 2; placeholder: "Address" }
                Row { spacing: 8; TextBox { id: fBday; width: (form.width - 8) / 2; placeholder: "Birthday, like 1990-04-23" } TextBox { id: fSite; width: (form.width - 8) / 2; placeholder: "Website" } }
                TextBox { id: fNotes; width: parent.width; lines: 3; placeholder: "Notes" }
                Row { spacing: 8; Btn { primary: true; text: "Save"; onClicked: win.keep() } Btn { text: "Cancel"; onClicked: win.open(win.at) } } } }
    }
    Shortcut { sequence: "Ctrl+F"; onActivated: search.focusInput() }
    Shortcut { sequence: "Ctrl+N"; onActivated: win.startEdit(true) }
}
