import QtQuick

// Translate, "the fold": what you wrote above, what it means below, and the two languages sit on the fold between them.
GlassWindow {
    id: win
    title: "Translate"; width: 700; height: 740; glow: "none"
    readonly property color pick: Qt.rgba(tintColor.r, tintColor.g, tintColor.b, 0.18)
    property var sheet: null                   // "from" | "to" | "packs"
    function nameOf(list, code) { for (var i = 0; i < list.length; i++) if (list[i].code === code) return list[i].name; return "" }
    Connections { target: Backend; function onSaid(msg, wrong) { toast.say(msg, wrong) } }
    Timer { id: soon; interval: 650; onTriggered: Backend.translate(src.many) }
    Component.onCompleted: src.focusIn()
    Row { visible: Backend.hasPacks && !Backend.keepHistory; anchors { right: parent.right; rightMargin: 24; bottom: parent.bottom; bottomMargin: 26 } z: 2
        Btn { height: 22; visible: Backend.result === ""; text: "Keep Earlier Translations"; onClicked: Backend.setKeepHistory(true) } }

    islands: [
        Island { visible: Backend.ready; anchors { right: parent.right; rightMargin: 12 } y: 12
            Seg { icon: "download"; text: "Languages"; onClicked: { win.sheet = "packs"; Backend.lookForPacks() } } },
        Toast { id: toast; anchors { horizontalCenter: parent.horizontalCenter; bottom: parent.bottom; bottomMargin: 18 } },
        Item { anchors.fill: parent; z: 20; visible: win.sheet !== null
            Rectangle { anchors.fill: parent; radius: win.r; color: "#66000000"; MouseArea { anchors.fill: parent; acceptedButtons: Qt.AllButtons; onClicked: win.sheet = null } }
            Rectangle { anchors.centerIn: parent; width: 460; height: Math.min(win.height - 80, 110 + rows.height); radius: 16; color: Theme.t.menu_bg; border.width: 1; border.color: Theme.t.menu_border
                MouseArea { anchors.fill: parent }
                Label { x: 22; y: 20; font.pixelSize: 16; font.weight: Font.DemiBold; text: win.sheet === "packs" ? "Languages" : win.sheet === "from" ? "Translate from" : "Translate to" }
                Flickable { x: 16; y: 52; width: parent.width - 32; height: parent.height - 110; contentHeight: rows.height; clip: true; boundsBehavior: Flickable.StopAtBounds
                    Column { id: rows; width: parent.width
                        Repeater { model: win.sheet === "from" ? Backend.sources : win.sheet === "to" ? Backend.targets : []
                            Pressable { required property var modelData; width: parent.width; height: 34; radius: 9; color: (win.sheet === "from" ? Backend.source : Backend.target) === modelData.code ? win.pick : hovered ? Theme.t.hover : "transparent"
                                onClicked: { if (win.sheet === "from") Backend.setSource(modelData.code); else Backend.setTarget(modelData.code); win.sheet = null; soon.restart() }
                                Label { x: 12; anchors.verticalCenter: parent.verticalCenter; text: modelData.name } } }
                        Label { visible: win.sheet === "packs"; x: 6; width: parent.width - 12; wrapMode: Text.WordWrap; secondary: true; font.pixelSize: 12; bottomPadding: 6
                            text: "Each pack translates one way between two languages and is about 100 MB. Fetching a pack is the only time Translate uses the network." }
                        Repeater { model: win.sheet === "packs" ? Backend.packs : []
                            Item { required property var modelData; width: parent.width; height: 32
                                Label { x: 12; anchors.verticalCenter: parent.verticalCenter; text: modelData.from + "  →  " + modelData.to }
                                Label { anchors { right: parent.right; rightMargin: 12; verticalCenter: parent.verticalCenter } text: "Installed"; secondary: true; font.pixelSize: 11 } } }
                        Repeater { model: win.sheet === "packs" ? Backend.localPacks : []
                            Item { required property var modelData; width: parent.width; height: 34
                                Label { x: 12; width: parent.width - 130; elide: Text.ElideMiddle; anchors.verticalCenter: parent.verticalCenter; text: modelData.name + "  ·  in " + modelData.where }
                                Btn { anchors { right: parent.right; rightMargin: 6; verticalCenter: parent.verticalCenter } height: 26; opacity: Backend.fetching ? 0.5 : 1; text: Backend.fetching === "file" ? "Adding…" : "Add File"; onClicked: Backend.addPackFile(modelData.path) } } }
                        Label { visible: win.sheet === "packs" && Backend.fetching === "list"; x: 12; height: 32; verticalAlignment: Text.AlignVCenter; secondary: true; text: "Seeing what's on offer…" }
                        Repeater { model: win.sheet === "packs" ? Backend.offered : []
                            Item { required property var modelData; width: parent.width; height: 34
                                Label { x: 12; width: parent.width - 110; elide: Text.ElideRight; anchors.verticalCenter: parent.verticalCenter; text: modelData.from + "  →  " + modelData.to }
                                Btn { anchors { right: parent.right; rightMargin: 6; verticalCenter: parent.verticalCenter } height: 26; opacity: Backend.fetching ? 0.5 : 1
                                    text: Backend.fetching === modelData.a + ">" + modelData.b ? "Fetching…" : "Get"; onClicked: Backend.getPack(modelData.a, modelData.b) } } } } }
                Btn { anchors { right: parent.right; rightMargin: 22; bottom: parent.bottom; bottomMargin: 16 } text: "Done"; onClicked: win.sheet = null } } }
    ]

    Column { visible: !Backend.ready || !Backend.hasPacks; anchors.centerIn: parent; spacing: 10; width: 460
        Glyph { name: "translate"; size: 56; ink: Theme.t.accent; anchors.horizontalCenter: parent.horizontalCenter }
        Label { anchors.horizontalCenter: parent.horizontalCenter; font.pixelSize: 20; font.weight: Font.DemiBold; text: Backend.ready ? "Choose your languages" : "The translator isn't installed" }
        Label { width: parent.width; wrapMode: Text.WordWrap; horizontalAlignment: Text.AlignHCenter; secondary: true
            text: Backend.ready ? "Translate works on this computer, so it needs a language pack for each pair you use. Get them once; after that no text ever leaves the machine."
                                : "Translate uses Argos Translate, which this computer doesn't have. It can be added with “pipx install argostranslate” (see the README); nothing is sent to an online translator instead." }
        Btn { visible: Backend.ready; anchors.horizontalCenter: parent.horizontalCenter; primary: true; text: "Get Languages"; onClicked: { win.sheet = "packs"; Backend.lookForPacks() } } }

    Item { id: fold; visible: Backend.hasPacks; anchors { fill: parent; topMargin: 64; leftMargin: 18; rightMargin: 18; bottomMargin: 18 }
        readonly property real half: (height - 30) / 2
        // the fold: both languages, and the button that turns them round
        Row { z: 3; anchors.horizontalCenter: parent.horizontalCenter; y: fold.half - 7; spacing: 8
            Pressable { width: Math.max(150, fl.width + 34); height: 44; radius: 22; color: Theme.t.menu_bg; border.width: 1; border.color: Theme.t.menu_border; onClicked: win.sheet = "from"
                Label { id: fl; anchors.centerIn: parent; text: win.nameOf(Backend.sources, Backend.source) || "From"; font.weight: Font.DemiBold } }
            Pressable { width: 44; height: 44; radius: 22; color: Theme.t.accent; onClicked: { var t = Backend.result; if (Backend.swap() && t !== "") { src.many = t; soon.restart() } }
                Glyph { anchors.centerIn: parent; name: "share"; size: 16; ink: Theme.t.onAccent; rotation: 90 } }
            Pressable { width: Math.max(150, tl.width + 34); height: 44; radius: 22; color: Theme.t.menu_bg; border.width: 1; border.color: Theme.t.accent; onClicked: win.sheet = "to"
                Label { id: tl; anchors.centerIn: parent; text: win.nameOf(Backend.targets, Backend.target) || "To"; font.weight: Font.DemiBold; color: Theme.t.accent } } }
        Rectangle { width: parent.width; height: fold.half; radius: 22; color: Theme.t.island; border.width: 1; border.color: Theme.t.islandLine
            TextBox { id: src; objectName: "src"; anchors { fill: parent; margins: 10; bottomMargin: Backend.document !== "" ? 64 : 22 } lines: 8; placeholder: "Type or paste here"; onEdited: soon.restart() }
            Rectangle { visible: Backend.document !== ""; anchors { left: parent.left; right: parent.right; bottom: parent.bottom; margins: 10 } height: 46; radius: 10; color: win.pick; border.width: 1; border.color: Theme.t.accent
                Label { x: 12; width: parent.width - 200; elide: Text.ElideMiddle; anchors.verticalCenter: parent.verticalCenter; text: Backend.document; font.pixelSize: 12 }
                Row { anchors { right: parent.right; rightMargin: 8; verticalCenter: parent.verticalCenter } spacing: 6
                    Btn { height: 26; text: "Not Now"; onClicked: Backend.dropDocument() }
                    Btn { height: 26; primary: true; opacity: Backend.busy ? 0.5 : 1; text: Backend.busy ? "Working…" : "Translate File"; onClicked: Backend.translateDocument() } } }
            Pressable { visible: src.many !== ""; anchors { right: parent.right; bottom: parent.bottom; margins: 14 } width: 28; height: 28; radius: 9; color: Theme.t.hover; onClicked: { src.many = ""; Backend.translate("") }
                Glyph { anchors.centerIn: parent; name: "x"; size: 11; ink: Theme.t.text_secondary } } }
        Rectangle { y: fold.half + 30; width: parent.width; height: fold.half; radius: 22; color: win.pick; border.width: 1; border.color: Theme.t.islandLine
            Flickable { anchors { fill: parent; margins: 20; topMargin: 30 } contentHeight: out.height; clip: true
                TextEdit { id: out; objectName: "out"; width: parent.width; readOnly: true; selectByMouse: true; wrapMode: TextEdit.Wrap; text: Backend.result; color: Theme.t.text; font.pixelSize: 20; font.weight: Font.Medium; opacity: Backend.busy ? 0.5 : 1 } }
            Label { visible: Backend.result === "" && !Backend.busy && Backend.history.length === 0; x: 20; y: 30; secondary: true; text: "The translation appears here" }
            Column { visible: Backend.result === "" && !Backend.busy && Backend.history.length > 0; x: 14; y: 26; width: parent.width - 28; spacing: 4
                Item { width: parent.width; height: 24
                    Label { x: 6; anchors.verticalCenter: parent.verticalCenter; text: "EARLIER"; secondary: true; font.pixelSize: 10; font.weight: Font.DemiBold }
                    Row { anchors { right: parent.right; verticalCenter: parent.verticalCenter } spacing: 6
                        Btn { height: 22; text: "Clear"; onClicked: Backend.clearHistory() } Btn { height: 22; text: "Don't Keep"; onClicked: Backend.setKeepHistory(false) } } }
                Repeater { model: Backend.history.slice(0, 4)
                    Pressable { required property var modelData; width: parent.width; height: 52; radius: 10; color: hovered ? Theme.t.hover : "transparent"
                        onClicked: { Backend.setSource(modelData.a); Backend.setTarget(modelData.b); src.many = modelData.from; soon.restart() }
                        Label { x: 8; y: 6; width: parent.width - 16; elide: Text.ElideRight; text: modelData.from; font.pixelSize: 13 }
                        Label { x: 8; y: 26; width: parent.width - 16; elide: Text.ElideRight; text: modelData.to + "   ·   " + modelData.pair; secondary: true; font.pixelSize: 11 } } } }
            Label { visible: Backend.busy && Backend.result === ""; x: 20; y: 30; secondary: true; text: "Translating…" }
            Btn { visible: Backend.result !== ""; anchors { right: parent.right; bottom: parent.bottom; margins: 14 } height: 28; text: "Copy"; onClicked: { out.selectAll(); out.copy(); out.deselect(); toast.say("Copied.", false) } } } }
    Shortcut { sequence: "Escape"; enabled: win.sheet !== null; onActivated: win.sheet = null }
}
