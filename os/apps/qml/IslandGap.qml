import QtQuick

// A hairline between groups inside an island.
Item { width: 9; height: 30; anchors.verticalCenter: parent ? parent.verticalCenter : undefined
    Rectangle { anchors.centerIn: parent; width: 1; height: 16; color: Theme.t.islandLine } }
