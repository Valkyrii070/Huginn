import QtQuick

// The stack above Huginn's dock tile: its open tabs as cards, newest at the bottom, and a New Tab button.
// Clicking a card opens that page in Huginn.
Column {
    id: stack
    signal hoverChanged(bool inside)
    signal picked()
    readonly property bool inside: zone.hovered
    width: 268; spacing: 8
    HoverHandler { id: zone; onHoveredChanged: stack.hoverChanged(hovered) }
    Label { text: Tabs.list.length > 0 ? "OPEN IN HUGINN" : "HUGINN"; secondary: true; font.pixelSize: 11; font.weight: Font.DemiBold; font.letterSpacing: 0.6; leftPadding: 4 }
    Repeater {
        model: Tabs.list
        Glass {
            id: card
            required property var modelData
            popup: true; width: stack.width; height: 56; radius: Theme.t.radiusTile
            scale: press.pressed ? Theme.t.pressScale : 1
            Rectangle { anchors.fill: parent; radius: parent.radius; color: Theme.t.hover; visible: press.containsMouse }
            Column {
                anchors { left: parent.left; right: parent.right; verticalCenter: parent.verticalCenter; margins: 14 }
                spacing: 3
                Label { width: parent.width; text: card.modelData.title; elide: Text.ElideRight; font.pixelSize: 13; font.weight: Font.DemiBold }
                Label { width: parent.width; text: card.modelData.site; elide: Text.ElideRight; secondary: true; font.pixelSize: 12 }
            }
            MouseArea { id: press; anchors.fill: parent; hoverEnabled: true; onClicked: { Tabs.open(card.modelData.url); stack.picked() } }
        }
    }
    Row {
        spacing: 8
        Glass {
            popup: true; width: newTab.width + 32; height: 44; radius: 12
            Rectangle { anchors.fill: parent; radius: parent.radius; color: Theme.t.hover; visible: add.containsMouse }
            Label { id: newTab; anchors.centerIn: parent; text: "New Tab"; color: Theme.t.accent; font.pixelSize: 13; font.weight: Font.DemiBold }
            MouseArea { id: add; anchors.fill: parent; hoverEnabled: true; onClicked: { Tabs.open(""); stack.picked() } }
        }
        Glass {
            popup: true; width: newPrivate.width + 32; height: 44; radius: 12
            Rectangle { anchors.fill: parent; radius: parent.radius; color: Theme.t.hover; visible: priv.containsMouse }
            Label { id: newPrivate; anchors.centerIn: parent; text: "New Private Window"; font.pixelSize: 13; font.weight: Font.DemiBold }
            MouseArea { id: priv; anchors.fill: parent; hoverEnabled: true; onClicked: { Tabs.openPrivate(); stack.picked() } }
        }
    }
}
