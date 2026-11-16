import QtQuick

// An app's windows, above its dock tile: pointing at an open app for a moment (or clicking one with several
// windows) shows them. Its name and how many, New window, then a card for each: click one to bring it forward,
// the × closes it; hidden ones are dimmed and say so.
Glass {
    id: isle
    property var app: null
    signal hoverChanged(bool inside)
    signal picked()
    signal newWindow()
    readonly property var wins: app ? Status.windows.filter(function (w) { return w.name === app.name }) : []
    readonly property color tone: app && app.colours && app.colours.length ? (Theme.t.dark ? app.colours[0] : app.colours[1]) : Theme.t.accent
    readonly property int cardW: wins.length > 3 ? 150 : 180
    readonly property int cardH: Math.round(cardW * 0.62)
    popup: true; dense: true; radius: 22
    width: Math.max(320, cards.width + 28); height: column.height + 28
    HoverHandler { onHoveredChanged: isle.hoverChanged(hovered) }
    // the cards' pictures, kept fresh while they're shown
    Timer {
        running: isle.visible && isle.wins.length > 0; repeat: true; interval: 1500; triggeredOnStart: true
        onTriggered: Status.refreshPictures(isle.wins.filter(function (w) { return !w.minimised }).map(function (w) { return String(w.id) }))
    }
    Column {
        id: column
        x: 14; y: 14; spacing: 12
        Item {
            width: isle.width - 28; height: 32
            Row {
                spacing: 9; anchors.verticalCenter: parent.verticalCenter
                AppIcon { size: 24; anchors.verticalCenter: parent.verticalCenter; name: isle.app ? isle.app.name : ""; glyph: isle.app ? isle.app.glyph : ""; image: isle.app ? isle.app.image : ""; own: isle.app ? isle.app.own || "" : ""; web: isle.app ? isle.app.web : false }
                Label { text: isle.app ? isle.app.name : ""; font.pixelSize: 15; font.weight: Font.DemiBold; anchors.verticalCenter: parent.verticalCenter }
                Label { text: isle.wins.length === 1 ? "1 window" : isle.wins.length + " windows"; secondary: true; font.pixelSize: 13; anchors.verticalCenter: parent.verticalCenter }
            }
            Rectangle {
                anchors { right: parent.right; verticalCenter: parent.verticalCenter }
                width: nw.width + 30; height: 30; radius: 10; color: newHit.containsMouse ? Theme.t.hover : Qt.rgba(1, 1, 1, Theme.t.dark ? 0.08 : 0.5)
                scale: newHit.pressed ? Theme.t.pressScale : 1
                Behavior on scale { NumberAnimation { duration: 90 } }
                Label { id: nw; anchors.centerIn: parent; text: "+  New window"; font.pixelSize: 13; font.weight: Font.DemiBold }
                MouseArea { id: newHit; anchors.fill: parent; hoverEnabled: true; onClicked: isle.newWindow() }
            }
        }
        Row {
            id: cards
            spacing: 12
            Repeater {
                model: isle.wins
                Column {
                    id: card
                    required property var modelData
                    spacing: 7
                    Item {
                        width: isle.cardW; height: isle.cardH
                        scale: cardHit.pressed ? Theme.t.pressScale : 1
                        Behavior on scale { NumberAnimation { duration: 90 } }
                        Rectangle {   // the window: its app's colour and icon, under a live picture of it on Huginn's own compositor
                            anchors.fill: parent; radius: 10; clip: true
                            color: Theme.t.dark ? "#1C2026" : "#F2F4F7"
                            opacity: card.modelData.minimised ? 0.45 : 1
                            border.width: cardHit.containsMouse || card.modelData.active ? 2 : 1
                            border.color: cardHit.containsMouse ? Theme.t.accent : card.modelData.active ? Qt.rgba(isle.tone.r, isle.tone.g, isle.tone.b, 0.8) : Theme.t.line
                            Rectangle { x: 1; y: 1; width: parent.width - 2; height: 18; radius: 9; color: Qt.rgba(isle.tone.r, isle.tone.g, isle.tone.b, 0.22)
                                Label { x: 8; anchors.verticalCenter: parent.verticalCenter; width: parent.width - 16; text: card.modelData.title; elide: Text.ElideRight; font.pixelSize: 10; secondary: true } }
                            AppIcon { anchors.centerIn: parent; anchors.verticalCenterOffset: 8; size: 34; opacity: 0.85; name: isle.app ? isle.app.name : ""; glyph: isle.app ? isle.app.glyph : ""; image: isle.app ? isle.app.image : ""; own: isle.app ? isle.app.own || "" : ""; web: isle.app ? isle.app.web : false }
                            // the window itself, live, on Huginn's own compositor (Status.refreshPictures)
                            Image {
                                anchors.fill: parent; anchors.margins: 3
                                source: Status.windowPictures[String(card.modelData.id)] || ""
                                visible: status === Image.Ready && !card.modelData.minimised
                                fillMode: Image.PreserveAspectFit; smooth: true; mipmap: true; cache: false; asynchronous: true
                            }
                        }
                        Rectangle {
                            visible: card.modelData.minimised; anchors.centerIn: parent; anchors.verticalCenterOffset: 8
                            width: hid.width + 18; height: 22; radius: 11; color: Qt.rgba(0.05, 0.06, 0.08, 0.82)
                            Label { id: hid; anchors.centerIn: parent; text: "Hidden"; color: "#F5F7FA"; font.pixelSize: 12; font.weight: Font.DemiBold }
                        }
                        MouseArea { id: cardHit; anchors.fill: parent; hoverEnabled: true; onClicked: { Status.windowDo(card.modelData.id, "activate"); isle.picked() } }
                        Rectangle {   // the ×
                            visible: cardHit.containsMouse || closeHit.containsMouse
                            width: 22; height: 22; radius: 11; x: parent.width - 14; y: -8
                            color: closeHit.containsMouse ? "#E5484D" : Qt.rgba(0.12, 0.13, 0.16, 0.95); border.width: 1; border.color: Qt.rgba(1, 1, 1, 0.18)
                            Label { anchors.centerIn: parent; text: "×"; color: "white"; font.pixelSize: 15 }
                            MouseArea { id: closeHit; anchors.fill: parent; hoverEnabled: true; onClicked: Status.windowDo(card.modelData.id, "close") }
                        }
                    }
                    Label { width: isle.cardW; horizontalAlignment: Text.AlignHCenter; text: card.modelData.title || (isle.app ? isle.app.name : ""); elide: Text.ElideRight; font.pixelSize: 12; secondary: card.modelData.minimised }
                }
            }
        }
    }
    // Grows out of the tile: in from a little lower and smaller, quick
    transformOrigin: Item.Bottom
    scale: visible ? 1 : 0.92
    Behavior on scale { NumberAnimation { duration: Theme.t.openMs ? 160 : 0; easing.type: Easing.OutCubic } }
}
