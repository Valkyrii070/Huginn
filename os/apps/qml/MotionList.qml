import QtQuick

// A ListView with Huginn's motion: a new item slides in with a wash of the app's colour that fades; one removed
// slides away and the others close the gap. Reduce Motion: they simply appear and go.
ListView {
    id: list
    readonly property bool motion: Theme.t.openMs > 0
    add: Transition {
        enabled: list.motion
        NumberAnimation { property: "opacity"; from: 0; to: 1; duration: 200 }
        NumberAnimation { property: "x"; from: -24; duration: 220; easing.type: Easing.OutCubic }
    }
    remove: Transition {
        enabled: list.motion
        NumberAnimation { property: "opacity"; to: 0; duration: 160 }
        NumberAnimation { property: "x"; to: list.width * 0.4; duration: 180; easing.type: Easing.InCubic }
    }
    displaced: Transition {
        enabled: list.motion
        NumberAnimation { properties: "x,y"; duration: 200; easing.type: Easing.OutCubic }
    }
}
