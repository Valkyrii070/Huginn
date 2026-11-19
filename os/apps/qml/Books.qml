import QtQuick

// Books, "the shelf and the page": covers on a shelf; open one and everything else gets out of the way.
GlassWindow {
    id: win
    title: Backend.reading ? Backend.title : "Books"; width: 980; height: 700; glow: Backend.reading ? "none" : "bottom"
    readonly property bool open: Backend.reading !== ""
    property bool listing: false
    onOpenChanged: listing = false
    readonly property color pageColor: Backend.paper === "sepia" ? "#F4ECD8" : Backend.paper === "white" ? "#FFFFFF" : Backend.paper === "black" ? "#000000" : "transparent"
    readonly property color inkColor: Backend.paper === "sepia" ? "#3B2F1E" : Backend.paper === "white" ? "#1A1A1A" : Backend.paper === "black" ? "#D0D0D0" : Theme.t.text
    Connections { target: Backend
        function onSaid(msg, wrong) { toast.say(msg, wrong) }
        function onOpened() { place.restart() } }
    Timer { id: place; interval: 80; onTriggered: page.contentY = Math.max(0, Backend.startAt * (page.contentHeight - page.height)) }
    Timer { id: note; interval: 1200; onTriggered: if (win.open && page.contentHeight > page.height) Backend.at(page.contentY / (page.contentHeight - page.height)) }

    islands: [
        Island { visible: win.open; anchors { right: parent.right; rightMargin: 12 } y: 12
            Seg { icon: "grid"; text: "Shelf"; onClicked: Backend.close() }
            Seg { icon: "list"; text: "Contents"; on: win.listing; onClicked: win.listing = !win.listing }
            Seg { text: "A–"; tip: "Smaller letters"; onClicked: Backend.setSize(Backend.size - 2) }
            Seg { text: "A+"; tip: "Larger letters"; onClicked: Backend.setSize(Backend.size + 2) }
            Repeater { model: [["theme", "Glass"], ["sepia", "Sepia"], ["white", "White"], ["black", "Black"]]
                Seg { required property var modelData; text: modelData[1]; on: Backend.paper === modelData[0]; onClicked: Backend.setPaper(modelData[0]) } } },
        Island { visible: !win.open; anchors { right: parent.right; rightMargin: 12 } y: 12
            Seg { icon: "history"; tip: "Look for new books"; onClicked: Backend.rescan() } },
        Island { visible: win.open; anchors { horizontalCenter: parent.horizontalCenter; bottom: parent.bottom; bottomMargin: 12 }
            Seg { icon: "back"; tip: "Previous part (Left)"; opacity: Backend.chapter > 0 ? 1 : 0.4; onClicked: Backend.turn(-1) }
            Seg { text: "Part " + (Backend.chapter + 1) + " of " + Backend.chapters }
            Seg { icon: "forward"; tip: "Next part (Right)"; onClicked: Backend.turn(1) } },
        Toast { id: toast; anchors { horizontalCenter: parent.horizontalCenter; bottom: parent.bottom; bottomMargin: 70 } }
    ]

    // ---------------- the shelf
    Column { visible: !win.open && Backend.books.length === 0; anchors.centerIn: parent; spacing: 10; width: 440
        Glyph { name: "book"; size: 56; ink: Theme.t.accent; anchors.horizontalCenter: parent.horizontalCenter }
        Label { anchors.horizontalCenter: parent.horizontalCenter; font.pixelSize: 20; font.weight: Font.DemiBold; text: "No books yet" }
        Label { width: parent.width; wrapMode: Text.WordWrap; horizontalAlignment: Text.AlignHCenter; secondary: true
            text: "Put ebooks (.epub files) in the Books folder in your home, or just leave them in Downloads; they show up here. Books locked by a shop (DRM) can't be opened." } }
    Flickable { visible: !win.open && Backend.books.length > 0; anchors { fill: parent; topMargin: 70; leftMargin: 26; rightMargin: 26; bottomMargin: 16 } contentHeight: shelf.height; clip: true; boundsBehavior: Flickable.StopAtBounds
        Flow { id: shelf; width: parent.width; spacing: 22
            Repeater { model: Backend.books
                Item { required property var modelData; required property int index; width: 150; height: 268
                    Rectangle { id: cover; width: 150; height: 212; radius: 8; clip: true; color: Qt.hsla((index * 0.17 + 0.05) % 1, 0.32, 0.34, 1); border.width: 1; border.color: Theme.t.islandLine; scale: tap.pressed ? 0.97 : 1
                        Image { anchors.fill: parent; source: modelData.cover; fillMode: Image.PreserveAspectCrop; asynchronous: true; sourceSize.width: 300; visible: modelData.cover !== "" }
                        Column { visible: modelData.cover === ""; x: 14; y: 20; width: parent.width - 28; spacing: 8
                            Label { width: parent.width; wrapMode: Text.WordWrap; text: modelData.title; color: "white"; font.pixelSize: 15; font.weight: Font.Bold; maximumLineCount: 5; elide: Text.ElideRight }
                            Label { width: parent.width; wrapMode: Text.WordWrap; text: modelData.author; color: "#D0FFFFFF"; font.pixelSize: 11 } }
                        Rectangle { visible: modelData.progress > 0; anchors { left: parent.left; right: parent.right; bottom: parent.bottom } height: 4; color: "#55000000"
                            Rectangle { width: parent.width * modelData.progress; height: 4; color: Theme.t.accent } }
                        MouseArea { id: tap; anchors.fill: parent; onClicked: Backend.open(modelData.path) } }
                    Label { y: 220; width: 150; elide: Text.ElideRight; text: modelData.title; font.pixelSize: 12; font.weight: Font.Medium }
                    Label { y: 238; width: 150; elide: Text.ElideRight; secondary: true; font.pixelSize: 11
                        text: modelData.progress >= 1 ? "Finished" : modelData.progress > 0 ? Math.round(modelData.progress * 100) + "% read" : modelData.author } } } } }

    // ---------------- the page
    Rectangle { visible: win.open; anchors { fill: parent; margins: 6 } radius: win.r - 4; color: win.pageColor }
    Flickable { id: page; visible: win.open; anchors { fill: parent; topMargin: 66; bottomMargin: 62 } contentHeight: words.height + 60; clip: true; boundsBehavior: Flickable.StopAtBounds
        onContentYChanged: note.restart()
        Text { id: words; objectName: "words"; x: Math.max(30, (page.width - width) / 2); y: 20; width: Math.min(720, page.width - 60); textFormat: Text.RichText; wrapMode: Text.WordWrap
            text: Backend.text; color: win.inkColor; font.pixelSize: Backend.size; font.family: "Georgia, 'DejaVu Serif', serif"; lineHeight: 1.45 } }
    Rectangle { visible: win.open && win.listing; z: 5; anchors { right: parent.right; rightMargin: 12; top: parent.top; topMargin: 64 } width: 320; height: Math.min(parent.height - 140, toc.contentHeight + 16); radius: 16
        color: Theme.t.menu_bg; border.width: 1; border.color: Theme.t.menu_border
        MouseArea { anchors.fill: parent }
        ListView { id: toc; anchors { fill: parent; margins: 8 } clip: true; model: win.listing ? Backend.contents : []; boundsBehavior: Flickable.StopAtBounds
            delegate: Pressable { required property var modelData; width: toc.width; height: 32; radius: 8; color: Backend.chapter === modelData.index ? Qt.rgba(tintColor.r, tintColor.g, tintColor.b, 0.18) : hovered ? Theme.t.hover : "transparent"
                onClicked: { Backend.goTo(modelData.index); win.listing = false }
                Label { x: 10; width: parent.width - 20; elide: Text.ElideRight; anchors.verticalCenter: parent.verticalCenter; text: modelData.title; font.pixelSize: 12; font.weight: Backend.chapter === modelData.index ? Font.DemiBold : Font.Normal } } } }
    function pageBy(dir) { if (!open) return; var to = page.contentY + dir * (page.height - 60), max = Math.max(0, page.contentHeight - page.height)
        if (dir > 0 && page.contentY >= max - 2) Backend.turn(1); else if (dir < 0 && page.contentY <= 2) Backend.turn(-1); else page.contentY = Math.max(0, Math.min(max, to)) }
    Shortcut { sequences: ["Space", "PgDown", "Down"]; enabled: win.open; onActivated: win.pageBy(1) }
    Shortcut { sequences: ["Shift+Space", "PgUp", "Up"]; enabled: win.open; onActivated: win.pageBy(-1) }
    Shortcut { sequence: "Right"; enabled: win.open; onActivated: Backend.turn(1) }
    Shortcut { sequence: "Left"; enabled: win.open; onActivated: Backend.turn(-1) }
    Shortcut { sequence: "Escape"; enabled: win.open; onActivated: Backend.close() }
}
