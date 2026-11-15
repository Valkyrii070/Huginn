import QtQuick

// An island that runs down the side: a list of places, pages or notes. Scrolls when it is taller than its room.
Rectangle {
    id: rail
    default property alias items: col.data
    property int maxHeight: 400
    width: 220; height: Math.min(col.height + 10, maxHeight); radius: 16
    color: Theme.t.island; border.width: 1; border.color: Theme.t.islandLine
    MouseArea { anchors.fill: parent }
    Flickable { anchors { fill: parent; margins: 5 } contentHeight: col.height; clip: true; interactive: col.height > height
        Column { id: col; width: parent.width; spacing: 2 } }
}
