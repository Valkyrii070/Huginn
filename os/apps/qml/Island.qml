import QtQuick

// A floating group of controls, like one island of the dock. Lay Seg, IslandField and labels inside it.
Rectangle {
    id: isl
    default property alias items: row.data
    property bool drags: false                 // true: pressing its background moves the window (the name island)
    property int pad: 5
    property bool rtl: false                   // lay the items out from the right
    height: 40; width: row.width + pad * 2; radius: 16
    color: Theme.t.island; border.width: 1; border.color: Theme.t.islandLine
    MouseArea { anchors.fill: parent; onPressed: if (isl.drags) isl.Window.window.startSystemMove() }
    Row { id: row; x: isl.pad; height: parent.height; spacing: 4; layoutDirection: isl.rtl ? Qt.RightToLeft : Qt.LeftToRight }
}
