import QtQuick

// A switch. Switched on, the knob slides and the light comes on with a glow that fades (Huginn's motion).
Rectangle {
    id: t
    property bool on: false
    signal toggled(bool value)
    width: 40; height: 24; radius: 12; color: on ? Theme.t.accent : (Theme.t.dark ? "#2EFFFFFF" : "#40141E28")
    Behavior on color { ColorAnimation { duration: Theme.t.openMs ? 160 : 0 } }
    onOnChanged: if (on && Theme.t.openMs > 0) glow.restart()
    Rectangle {   // the glow as it comes on
        id: halo
        anchors.centerIn: parent; width: parent.width; height: parent.height; radius: height / 2
        color: "transparent"; border.width: 6; border.color: Theme.t.accent; opacity: 0; z: -1
        ParallelAnimation {
            id: glow
            NumberAnimation { target: halo; property: "opacity"; from: 0.55; to: 0; duration: 520; easing.type: Easing.OutCubic }
            NumberAnimation { target: halo; property: "scale"; from: 1; to: 1.35; duration: 520; easing.type: Easing.OutCubic }
        }
    }
    Rectangle { width: 20; height: 20; radius: 10; y: 2; x: t.on ? 18 : 2; color: "#FFFFFF"
        Behavior on x { NumberAnimation { duration: Theme.t.openMs ? 170 : 0; easing.type: Easing.OutBack; easing.overshoot: 1.4 } } }
    MouseArea { anchors.fill: parent; onClicked: t.toggled(!t.on) }
}
