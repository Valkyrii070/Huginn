import QtQuick

// Fonts, "the proof sheet": one warm sheet of paper where every typeface sets your own words, one line each, on a
// ruled baseline. Type at the top to change the words; pull the slider to change the size. Click a line and the
// font's specimen page slides in from the right: every style, a size waterfall and its letters.
GlassWindow {
    id: win
    title: "Fonts"; width: 1100; height: 760; minimumWidth: 780; minimumHeight: 540; glow: "top"
    property var sheet: null
    function addFonts() { sheet = { kind: "files", list: Backend.fileChoices() } }
    property string why: ""
    readonly property color paper: Theme.t.dark ? "#211D18" : "#FBF7EF"
    readonly property color ink: Theme.t.dark ? "#F2EADF" : "#2A2118"
    readonly property color rule: Theme.t.dark ? "#3A3229" : "#E8DDCB"
    readonly property var fam: Backend.family
    readonly property var tryIt: Backend.trying
    readonly property string words: Backend.sample !== "" ? Backend.sample : "Type something to try"
    Connections { target: Backend; function onSaid(msg, wrong) { toast.say(msg, wrong) } }
    DropArea { anchors.fill: parent; onDropped: function (d) { if (d.hasUrls) win.why = Backend.tryFile(d.urls[0].toString()); if (win.why !== "") toast.say(win.why, true) } }

    islands: [
        Island { x: 134; y: 12   // which fonts: just right of the window's own island
            Repeater { model: [["all", "All"], ["mine", "Yours"], ["starred", "Starred"], ["mono", "Monospace"]]
                Seg { required property var modelData; text: modelData[1] + "  " + (Backend.counts[modelData[0]] || 0); on: Backend.view === modelData[0]; onClicked: Backend.setView(modelData[0]) } } },
        Island { anchors { right: parent.right; rightMargin: 12 } y: 12
            IslandField { width: 170; placeholder: "Find a font"; onTextChanged: Backend.search(text) }
            Seg { icon: "plus"; text: "Add Fonts"; onClicked: win.sheet = { kind: "files", list: Backend.fileChoices() } } },
        Toast { id: toast; anchors { horizontalCenter: parent.horizontalCenter; bottom: parent.bottom; bottomMargin: 22 } },

        Item { anchors.fill: parent; z: 20; visible: win.sheet !== null || !!win.tryIt.family
            Rectangle { anchors.fill: parent; radius: win.r; color: "#66000000"; MouseArea { anchors.fill: parent; acceptedButtons: Qt.AllButtons; onClicked: { win.sheet = null; Backend.stopTrying() } } }
            Rectangle { id: card; anchors.centerIn: parent; radius: 18; color: Theme.t.menu_bg; border.width: 1; border.color: Theme.t.menu_border
                readonly property bool trying: !!win.tryIt.family
                width: trying ? Math.min(win.width - 80, 720) : 500
                height: trying ? 330 : Math.min(win.height - 80, 150 + Math.max(1, picks.count) * 38)
                MouseArea { anchors.fill: parent }
                Label { x: 24; y: 20; width: parent.width - 48; elide: Text.ElideRight; font.pixelSize: 17; font.weight: Font.DemiBold
                    text: card.trying ? "Try “" + win.tryIt.family + "”" : "Add fonts" }
                Label { visible: !card.trying; x: 24; y: 46; width: parent.width - 48; wrapMode: Text.WordWrap; secondary: true; font.pixelSize: 12
                    text: picks.count ? "Fonts and font .zips in Downloads, Desktop and Documents. Or drop one on this window." : "No font files in Downloads, Desktop or Documents. Download one (a .ttf, .otf or .zip) or drop it on this window." }
                Repeater { id: picks; model: !card.trying && win.sheet ? win.sheet.list : []
                    Pressable { required property var modelData; required property int index; x: 16; y: 78 + index * 38; width: card.width - 32; height: 36; radius: 9
                        onClicked: { win.why = Backend.tryFile(modelData.path); if (win.why === "") win.sheet = null; else toast.say(win.why, true) }
                        Label { x: 12; text: "Aa"; font.pixelSize: 15; font.weight: Font.Bold; color: Theme.t.accent; anchors.verticalCenter: parent.verticalCenter }
                        Label { x: 44; width: parent.width - 160; elide: Text.ElideMiddle; anchors.verticalCenter: parent.verticalCenter; text: modelData.name }
                        Label { anchors { right: parent.right; rightMargin: 10; verticalCenter: parent.verticalCenter } text: modelData.where; secondary: true; font.pixelSize: 11 } } }
                Column { visible: card.trying; x: 24; y: 54; width: parent.width - 48; spacing: 10
                    Label { secondary: true; font.pixelSize: 12; text: win.tryIt.name + (win.tryIt.files > 1 ? " · " + win.tryIt.files + " files" : "") + (win.tryIt.families && win.tryIt.families.length > 1 ? " · " + win.tryIt.families.join(", ") : "") }
                    Rectangle { width: parent.width; height: 170; radius: 14; color: win.paper
                        Text { anchors { fill: parent; margins: 18 } wrapMode: Text.Wrap; elide: Text.ElideRight; color: win.ink; font.family: win.tryIt.family || ""; font.pixelSize: 40; text: win.words } }
                    Label { visible: !!win.tryIt.installed; font.pixelSize: 12; color: Theme.t.accent; text: "You've already installed this one." } }
                Row { anchors { right: parent.right; rightMargin: 22; bottom: parent.bottom; bottomMargin: 20 } spacing: 8
                    Btn { text: card.trying ? "Not Now" : "Done"; onClicked: { win.sheet = null; Backend.stopTrying() } }
                    Btn { visible: card.trying; primary: true; text: "Install for Me"; onClicked: { win.why = Backend.install(win.tryIt.path); if (win.why !== "") toast.say(win.why, true) } } } } }
    ]

    // ---------------- your words, your size
    Item { id: bar; x: 18; y: 66; width: parent.width - 36; height: 52
        TextBox { id: say; objectName: "say"; width: parent.width - 330; anchors.verticalCenter: parent.verticalCenter; text: Backend.sample; placeholder: "Type something to try"; onEdited: Backend.setSample(text) }
        Row { anchors { right: parent.right; verticalCenter: parent.verticalCenter } spacing: 10
            Seg { text: "Next sample"; onClicked: { var s = Backend.samples, i = (s.indexOf(Backend.sample) + 1) % s.length; Backend.setSample(s[i]); say.text = s[i] } }
            Meter { width: 130; anchors.verticalCenter: parent.verticalCenter; interactive: true; value: (Backend.size - 10) / 110; onMoved: function (v) { Backend.setSize(Math.round(10 + v * 110)) } }
            Label { width: 44; anchors.verticalCenter: parent.verticalCenter; text: Backend.size + " pt"; font.pixelSize: 12; secondary: true } } }

    // ---------------- the sheet
    Rectangle { id: sheetBox; x: 18; y: 126; width: (win.fam.name ? parent.width * 0.52 : parent.width - 36); height: parent.height - y - 18; radius: 18; color: win.paper
        border.width: 1; border.color: win.rule
        Behavior on width { NumberAnimation { duration: 220; easing.type: Easing.OutCubic } }
        ListView { id: list; objectName: "list"; anchors { fill: parent; margins: 6 } clip: true; model: Backend.families; boundsBehavior: Flickable.StopAtBounds; reuseItems: true
            delegate: Pressable { id: row; required property var modelData; readonly property bool on: win.fam.name === modelData.name
                width: list.width; height: Math.max(64, Backend.size * 1.5 + 34); radius: 12; color: on ? (Theme.t.dark ? "#2E2820" : "#F3EBDD") : hovered ? (Theme.t.dark ? "#28231D" : "#F7F1E6") : "transparent"
                onClicked: on ? Backend.close() : Backend.open(modelData.name)
                Row { x: 16; y: 10; spacing: 8
                    Label { text: row.modelData.name.toUpperCase(); font.pixelSize: 10; font.weight: Font.Bold; font.letterSpacing: 1.2; color: row.on ? Theme.t.accent : Theme.t.text_secondary }
                    Label { text: row.modelData.styles + (row.modelData.styles === 1 ? " style" : " styles") + (row.modelData.mine ? " · yours" : "") + (row.modelData.mono ? " · monospace" : ""); font.pixelSize: 10; secondary: true }
                    Label { visible: row.modelData.star; text: "★"; font.pixelSize: 10; color: Theme.t.accent } }
                Text { x: 16; y: 26; width: parent.width - 32; height: parent.height - 30; elide: Text.ElideRight; verticalAlignment: Text.AlignVCenter
                    color: win.ink; font.family: row.modelData.name; font.pixelSize: Backend.size; text: win.words }
                Rectangle { x: 16; width: parent.width - 32; height: 1; anchors.bottom: parent.bottom; color: win.rule } }
            Label { visible: list.count === 0; anchors.centerIn: parent; secondary: true
                text: Backend.view === "mine" ? "Fonts you add show up here" : Backend.view === "starred" ? "Star the fonts you like" : "No font is called that" } } }

    // ---------------- the specimen page
    Rectangle { id: page; objectName: "page"; visible: !!win.fam.name; x: sheetBox.x + sheetBox.width + 12; y: 126; width: parent.width - x - 18; height: parent.height - y - 18; radius: 18
        color: Theme.t.island; border.width: 1; border.color: Theme.t.islandLine; clip: true
        Flickable { anchors.fill: parent; contentHeight: spec.height + 40; boundsBehavior: Flickable.StopAtBounds; clip: true
            Column { id: spec; x: 22; y: 18; width: page.width - 44; spacing: 14
                Item { width: parent.width; height: 120
                    Text { id: aa; text: "Aa"; font.family: win.fam.name || ""; font.pixelSize: 104; color: Theme.t.accent; anchors.verticalCenter: parent.verticalCenter }
                    Column { x: aa.width + 18; width: parent.width - x; anchors.verticalCenter: parent.verticalCenter; spacing: 4
                        Label { width: parent.width; elide: Text.ElideRight; text: win.fam.name || ""; font.pixelSize: 22; font.weight: Font.Bold }
                        Label { width: parent.width; wrapMode: Text.WordWrap; secondary: true; font.pixelSize: 12
                            text: (win.fam.styles ? win.fam.styles.length : 0) + " styles · " + win.fam.format + " · " + win.fam.where } } }
                Row { spacing: 8
                    Btn { text: win.fam.star ? "Unstar" : "Star"; onClicked: Backend.star(win.fam.name) }
                    Btn { text: "Copy Name"; onClicked: Backend.copyName(win.fam.name) }
                    Btn { visible: !!win.fam.mine; danger: true; text: "Remove"; onClicked: { var w = Backend.remove(win.fam.name); if (w !== "") toast.say(w, true) } }
                    Btn { text: "Close"; onClicked: Backend.close() } }
                Label { text: "STYLES"; font.pixelSize: 10; font.weight: Font.Bold; font.letterSpacing: 1.2; secondary: true; topPadding: 6 }
                Repeater { model: win.fam.styles || []
                    Column { required property var modelData; width: spec.width; spacing: 0
                        Label { text: modelData.name; font.pixelSize: 10; secondary: true }
                        Text { width: parent.width; elide: Text.ElideRight; color: Theme.t.text; font.family: win.fam.name; font.styleName: modelData.name; font.pixelSize: 22; text: win.words } } }
                Label { text: "SIZES"; font.pixelSize: 10; font.weight: Font.Bold; font.letterSpacing: 1.2; secondary: true; topPadding: 6 }
                Repeater { model: [12, 16, 24, 36, 54, 72]
                    Row { required property int modelData; spacing: 10; width: spec.width
                        Label { width: 26; text: modelData; font.pixelSize: 10; secondary: true; anchors.baseline: line.baseline }
                        Text { id: line; width: parent.width - 36; elide: Text.ElideRight; color: Theme.t.text; font.family: win.fam.name || ""; font.pixelSize: modelData; text: win.words } } }
                Label { text: "LETTERS"; font.pixelSize: 10; font.weight: Font.Bold; font.letterSpacing: 1.2; secondary: true; topPadding: 6 }
                Text { width: parent.width; wrapMode: Text.WrapAnywhere; color: Theme.t.text; font.family: win.fam.name || ""; font.pixelSize: 26; lineHeight: 1.25
                    text: "ABCDEFGHIJKLMNOPQRSTUVWXYZ abcdefghijklmnopqrstuvwxyz 0123456789 ÅÄÖÆØÉÑßæøåéñç !?&@#%*()[]{}“”‘’ € £ $ ¥ — –" } } } }

    Label { visible: Backend.busy !== ""; anchors { right: parent.right; rightMargin: 24; bottom: parent.bottom; bottomMargin: 24 } z: 5; secondary: true; font.pixelSize: 12; text: "Busy: " + Backend.busy + "…" }
}
