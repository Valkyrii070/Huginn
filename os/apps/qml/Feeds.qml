import QtQuick

// Feeds, "the magazine": every story is a card, laid out in a grid like a magazine's contents pages. Each site keeps
// its own colour on the top of its cards, so you can tell them apart at a glance without loading a single picture
// (pictures in stories are never fetched). The newest unread story is the big card at the start. Type is plain and
// large, on solid cards, for reading; a story opens as one wide, calm column whose letter size you choose.
GlassWindow {
    id: win
    title: "Feeds"; width: 1120; height: 780; minimumWidth: 760; minimumHeight: 540; glow: "top"
    readonly property bool reading: !!Backend.article.id
    readonly property int cols: Math.max(1, Math.min(4, Math.floor((width - 64 + 16) / (300 + 16))))
    readonly property real cardW: (grid.width - (cols - 1) * 16) / cols
    readonly property color cardBg: Theme.t.dark ? "#1D2027" : "#FFFFFF"
    readonly property color cardLine: Theme.t.dark ? "#2B2F38" : "#E5E7EB"
    readonly property color ink: Theme.t.dark ? "#F3F4F6" : "#14171C"
    readonly property color softInk: Theme.t.dark ? "#B9BEC8" : "#4B5361"
    readonly property string viewTitle: Backend.view === "front" ? "Today" : Backend.view === "starred" ? "Starred" : Backend.view === "all" ? "Everything"
                                       : ((Backend.sources.filter(function (s) { return s.id === Backend.view })[0] || {}).title || "")
    property var sheet: null                   // { kind: "follow" | "sources" | "import", why }
    function follow() { sheet = { kind: "follow", why: "" } }
    function sources() { sheet = { kind: "sources" } }
    function refresh() { Backend.refresh() }
    function allRead() { Backend.allRead() }
    function hue(s) { var h = 7; for (var i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) % 3600; return h / 3600 }
    function siteColour(s, light) { return Qt.hsla(hue(s || "?"), 0.55, light ? 0.52 : 0.40, 1) }
    Connections { target: Backend; function onSaid(msg, wrong) { toast.say(msg, wrong); if (!wrong && win.sheet && win.sheet.kind === "follow") win.sheet = null } }
    Shortcut { sequence: "Escape"; enabled: win.reading && win.sheet === null; onActivated: Backend.close() }

    component Rule: Rectangle { height: 1; color: win.cardLine }

    islands: [
        Island { anchors { right: parent.right; rightMargin: 12 } y: 12
            IslandField { visible: !win.reading; width: 190; placeholder: "Search stories"; onTextChanged: Backend.search(text) }
            Seg { visible: !win.reading; icon: "plus"; text: "Follow"; onClicked: { win.sheet = { kind: "follow", why: "" }; followBox.focusIn() } }
            Seg { visible: !win.reading; icon: "history"; tip: Backend.busy ? "Checking…" : "Check for new stories"; on: Backend.busy; onClicked: Backend.refresh() }
            Seg { visible: !win.reading; icon: "list"; tip: "Your sources"; onClicked: win.sheet = { kind: "sources" } }
            Seg { visible: win.reading; text: "A−"; tip: "Smaller letters"; onClicked: Backend.setSize(Backend.size - 1) }
            Seg { visible: win.reading; text: "A+"; tip: "Bigger letters"; onClicked: Backend.setSize(Backend.size + 1) }
            Seg { visible: win.reading; icon: "star"; on: !!Backend.article.star; tip: Backend.article.star ? "Starred" : "Star it"; onClicked: Backend.star(Backend.article.id) }
            Seg { visible: win.reading; icon: "eye"; tip: "Mark as not read"; onClicked: { Backend.setRead(Backend.article.id, false); Backend.close() } }
            Seg { visible: win.reading && !!Backend.article.link; icon: "share"; text: "Open in Huginn"; onClicked: Backend.openLink(Backend.article.link) } },
        Island { visible: win.reading; x: 132; y: 12
            Seg { icon: "back"; text: "All Stories"; onClicked: Backend.close() } },
        Toast { id: toast; anchors { horizontalCenter: parent.horizontalCenter; bottom: parent.bottom; bottomMargin: 22 } },

        Item { anchors.fill: parent; z: 20; visible: win.sheet !== null
            Rectangle { anchors.fill: parent; radius: win.r; color: "#66000000"; MouseArea { anchors.fill: parent; acceptedButtons: Qt.AllButtons; onClicked: win.sheet = null } }
            Rectangle { id: card; anchors.centerIn: parent; width: 500; radius: 18; color: Theme.t.menu_bg; border.width: 1; border.color: Theme.t.menu_border
                readonly property string kind: win.sheet ? win.sheet.kind : ""
                height: kind === "follow" ? 214 : Math.min(win.height - 80, 150 + Math.max(1, list.count) * 52)
                MouseArea { anchors.fill: parent }
                Label { x: 24; y: 20; font.pixelSize: 17; font.weight: Font.DemiBold; text: card.kind === "follow" ? "Follow a site" : card.kind === "import" ? "Bring in a list of feeds" : "Your sources" }
                Column { visible: card.kind === "follow"; x: 24; y: 54; width: parent.width - 48; spacing: 10
                    Label { width: parent.width; wrapMode: Text.WordWrap; secondary: true; text: "Type the site's address. Its feed is found for you." }
                    TextBox { id: followBox; objectName: "followBox"; width: parent.width; placeholder: "example.com"; onAccepted: Backend.follow(text) } }
                ListView { id: list; visible: card.kind !== "follow"; x: 16; y: 56; width: parent.width - 32; height: parent.height - 120; clip: true; boundsBehavior: Flickable.StopAtBounds
                    model: card.kind === "sources" ? Backend.sources : card.kind === "import" ? win.sheet.files : []
                    delegate: Item { required property var modelData; width: list.width; height: 52
                        Label { x: 8; y: 8; width: parent.width - 130; elide: Text.ElideRight; text: modelData.title || modelData.name; font.weight: Font.DemiBold }
                        Label { x: 8; y: 27; width: parent.width - 130; elide: Text.ElideRight; font.pixelSize: 11; color: modelData.error ? Theme.t.danger : Theme.t.text_secondary
                            text: card.kind === "import" ? "in " + modelData.where : modelData.error ? modelData.error : modelData.unread + " unread" + (modelData.checked ? " · checked " + modelData.checked : "") }
                        Btn { visible: card.kind === "sources"; anchors { right: parent.right; verticalCenter: parent.verticalCenter } text: "Unfollow"; onClicked: Backend.unfollow(modelData.id) }
                        Btn { visible: card.kind === "import"; anchors { right: parent.right; verticalCenter: parent.verticalCenter } primary: true; text: "Bring In"; onClicked: { var p = modelData.path; win.sheet = null; Backend.importOpml(p) } }
                        Rule { anchors.bottom: parent.bottom; width: parent.width } } }
                Label { visible: card.kind !== "follow" && list.count === 0; x: 24; y: 62; width: parent.width - 48; wrapMode: Text.WordWrap; secondary: true
                    text: card.kind === "import" ? "Export your feeds from your old reader as an .opml file into Documents or Downloads, then come back." : "You don't follow anything yet." }
                Row { anchors { left: parent.left; leftMargin: 22; bottom: parent.bottom; bottomMargin: 18 } spacing: 8; visible: card.kind === "sources"
                    Btn { text: "Bring In…"; onClicked: win.sheet = { kind: "import", files: Backend.opmlChoices() } }
                    Btn { text: "Save a Copy"; onClicked: Backend.exportOpml() } }
                Row { anchors { right: parent.right; rightMargin: 22; bottom: parent.bottom; bottomMargin: 18 } spacing: 8
                    Btn { text: card.kind === "follow" ? "Cancel" : "Done"; onClicked: win.sheet = null }
                    Btn { visible: card.kind === "follow"; primary: true; text: Backend.busy ? "Looking…" : "Follow"; onClicked: Backend.follow(followBox.text) } } } }
    ]


    // ---------------- the heading and the sites
    Item { id: head; visible: !win.reading; x: 32; y: 66; width: parent.width - 64; height: 58
        Label { id: big; text: win.viewTitle; font.pixelSize: 30; font.weight: Font.Bold; color: win.ink; width: Math.min(implicitWidth, parent.width * 0.6); elide: Text.ElideRight }
        Label { anchors { left: big.right; leftMargin: 14; baseline: big.baseline } font.pixelSize: 14; color: win.softInk
            text: Backend.today + "  ·  " + (Backend.unread ? Backend.unread + " unread" : "all caught up") }
        Btn { anchors { right: parent.right; verticalCenter: big.verticalCenter } visible: Backend.unread > 0 && Backend.articles.length > 0; text: "Mark All as Read"; onClicked: Backend.allRead() } }
    ListView { id: sections; objectName: "sections"; visible: !win.reading; x: 32; y: 120; width: parent.width - 64; height: 40; orientation: ListView.Horizontal; spacing: 8; clip: true
        boundsBehavior: Flickable.StopAtBounds
        model: [{ id: "front", title: "Today", unread: 0 }, { id: "all", title: "Everything", unread: 0 }, { id: "starred", title: "Starred", unread: Backend.starred }].concat(Backend.sources)
        delegate: Pressable { id: chip; required property var modelData; required property int index; readonly property bool on: Backend.view === modelData.id
            readonly property bool site: index > 2
            width: chipRow.width + 28; height: 36; radius: 18; onClicked: Backend.setView(modelData.id)
            color: on ? (site ? win.siteColour(modelData.title, !Theme.t.dark) : Theme.t.accent) : hovered ? Theme.t.hover : win.cardBg
            border.width: on ? 0 : 1; border.color: win.cardLine
            Row { id: chipRow; anchors.centerIn: parent; spacing: 8
                Rectangle { visible: chip.site; width: 10; height: 10; radius: 5; anchors.verticalCenter: parent.verticalCenter; color: chip.on ? "#FFFFFF" : win.siteColour(chip.modelData.title, !Theme.t.dark) }
                Label { text: chip.modelData.title; font.pixelSize: 13; font.weight: Font.DemiBold; color: chip.on ? (chip.site ? "#FFFFFF" : Theme.t.onAccent) : win.ink }
                Label { visible: chip.modelData.unread > 0; text: chip.modelData.unread; font.pixelSize: 12; font.weight: Font.Bold; color: chip.on ? (chip.site ? "#FFFFFF" : Theme.t.onAccent) : Theme.t.accent }
                Rectangle { visible: !!chip.modelData.error; width: 7; height: 7; radius: 4; color: Theme.t.danger; anchors.verticalCenter: parent.verticalCenter } } } }

    // ---------------- nothing to read
    Column { visible: !win.reading && Backend.articles.length === 0; anchors.horizontalCenter: parent.horizontalCenter; y: 280; spacing: 12; width: 460
        Label { width: parent.width; horizontalAlignment: Text.AlignHCenter; font.pixelSize: 22; font.weight: Font.Bold; color: win.ink
            text: Backend.sources.length === 0 ? "Nothing to read yet" : Backend.view === "starred" ? "Nothing starred" : "Nothing here" }
        Label { width: parent.width; wrapMode: Text.WordWrap; horizontalAlignment: Text.AlignHCenter; color: win.softInk; font.pixelSize: 14; lineHeight: 1.3
            text: Backend.sources.length === 0 ? "Follow the news sites and blogs you like and their new stories land here. Each site is asked directly; nobody else learns what you read."
                                             : Backend.view === "starred" ? "Star a story while reading it to keep it here." : "No stories match." }
        Row { visible: Backend.sources.length === 0; anchors.horizontalCenter: parent.horizontalCenter; spacing: 8
            Btn { primary: true; text: "Follow a Site"; onClicked: { win.sheet = { kind: "follow", why: "" }; followBox.focusIn() } }
            Btn { text: "Bring In a List"; onClicked: win.sheet = { kind: "import", files: Backend.opmlChoices() } } } }

    // ---------------- the cards
    Flickable { id: shelf; objectName: "paper"; visible: !win.reading && Backend.articles.length > 0; x: 32; y: 172; width: parent.width - 64; height: parent.height - 172 - 14
        contentHeight: grid.height + 30; clip: true; boundsBehavior: Flickable.StopAtBounds
        Flow { id: grid; width: shelf.width; spacing: 16
            Repeater { model: Backend.articles
                Pressable { id: card; objectName: index === 0 ? "lead" : ""; required property var modelData; required property int index
                    readonly property bool big: index === 0 && win.cols > 1 && Backend.view === "front"
                    readonly property color site: win.siteColour(modelData.source, !Theme.t.dark)
                    width: big ? win.cardW * 2 + 16 : win.cardW; height: 276; radius: 18; color: win.cardBg; border.width: 1; border.color: hovered ? card.site : win.cardLine
                    clip: true; onClicked: Backend.read(modelData.id)
                    opacity: modelData.read ? 0.62 : 1
                    // the site's band: its colour, its name, and its first letter large
                    Rectangle { id: band; width: parent.width; height: card.big ? 120 : 84; radius: 18
                        gradient: Gradient { orientation: Gradient.Horizontal
                            GradientStop { position: 0; color: card.site }
                            GradientStop { position: 1; color: Qt.darker(card.site, 1.35) } }
                        Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 18     // square bottom corners
                            gradient: Gradient { orientation: Gradient.Horizontal
                                GradientStop { position: 0; color: card.site }
                                GradientStop { position: 1; color: Qt.darker(card.site, 1.35) } } }
                        Text { z: 2; anchors { right: parent.right; rightMargin: 14; verticalCenter: parent.verticalCenter } text: (card.modelData.source || "?").charAt(0).toUpperCase()
                            font.pixelSize: card.big ? 130 : 90; font.weight: Font.Black; color: "#FFFFFF"; opacity: 0.16 }
                        Row { x: 18; y: 16; spacing: 8
                            Rectangle { visible: !card.modelData.read; width: 9; height: 9; radius: 5; color: "#FFFFFF"; anchors.verticalCenter: parent.verticalCenter }
                            Label { text: card.modelData.source; font.pixelSize: 13; font.weight: Font.Bold; color: "#FFFFFF" } }
                        Label { z: 2; x: 18; anchors { bottom: parent.bottom; bottomMargin: 14 } font.pixelSize: 12; color: "#E6FFFFFF"
                            text: card.modelData.when + "  ·  " + card.modelData.mins + " min read" + (card.modelData.star ? "  ·  ★" : "") } }
                    Column { x: 20; y: band.height + 16; width: parent.width - 40; spacing: 10
                        Label { width: parent.width; wrapMode: Text.WordWrap; maximumLineCount: card.big ? 2 : 3; elide: Text.ElideRight; text: card.modelData.title
                            font.pixelSize: card.big ? 28 : 19; font.weight: Font.Bold; lineHeight: 1.18; color: win.ink }
                        Label { width: parent.width; wrapMode: Text.WordWrap; maximumLineCount: card.big ? 3 : (card.modelData.title.length > 70 ? 2 : 3); elide: Text.ElideRight
                            text: card.modelData.summary; font.pixelSize: card.big ? 16 : 14; lineHeight: 1.4; color: win.softInk } } } } } }

    // ---------------- one story
    Rectangle { id: sheetOfPaper; visible: win.reading; anchors { fill: parent; topMargin: 62; leftMargin: 18; rightMargin: 18; bottomMargin: 18 } radius: 20; color: win.cardBg
        border.width: 1; border.color: win.cardLine
        Rectangle { width: parent.width; height: 8; radius: 20; color: win.siteColour(Backend.article.source || "", !Theme.t.dark) }
        Rectangle { y: 4; width: parent.width; height: 4; color: win.siteColour(Backend.article.source || "", !Theme.t.dark) }
        Flickable { id: reader; objectName: "reader"; anchors { fill: parent; topMargin: 8 } contentHeight: story1.height + 80; clip: true; boundsBehavior: Flickable.StopAtBounds
            onVisibleChanged: contentY = 0
            Column { id: story1; width: Math.min(Backend.size * 40, reader.width - 80); x: (reader.width - width) / 2; y: 34; spacing: 14
                Row { spacing: 8
                    Rectangle { width: 10; height: 10; radius: 5; anchors.verticalCenter: parent.verticalCenter; color: win.siteColour(Backend.article.source || "", !Theme.t.dark) }
                    Label { text: (Backend.article.source || "") + (Backend.article.author ? "  ·  " + Backend.article.author : ""); font.pixelSize: 14; font.weight: Font.DemiBold; color: win.ink } }
                Label { width: parent.width; wrapMode: Text.WordWrap; text: Backend.article.title || ""; font.pixelSize: Math.round(Backend.size * 1.75); font.weight: Font.Bold; lineHeight: 1.15; color: win.ink }
                Label { text: (Backend.article.date || "") + (Backend.article.mins ? "  ·  " + Backend.article.mins + " min read" : ""); font.pixelSize: 13; color: win.softInk }
                Rule { width: parent.width }
                Text { objectName: "body"; width: parent.width; wrapMode: Text.WordWrap; textFormat: Text.RichText; text: Backend.article.content || ""
                    font.family: Theme.t.font; font.pixelSize: Backend.size; lineHeight: 1.6; color: win.ink; linkColor: Theme.t.accent
                    onLinkActivated: function (link) { Backend.openLink(link) }
                    MouseArea { anchors.fill: parent; acceptedButtons: Qt.NoButton; cursorShape: parent.hoveredLink ? Qt.PointingHandCursor : Qt.ArrowCursor } }
                Rule { width: parent.width }
                Row { spacing: 8
                    Btn { visible: !!Backend.article.link; primary: true; text: "Read It All in Huginn"; onClicked: Backend.openLink(Backend.article.link) }
                    Btn { text: "Back to All Stories"; onClicked: Backend.close() } } } } }
}
