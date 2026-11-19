import QtQuick

// A little equaliser while something plays; still (and dimmer) while it's paused.
Row {
    id: eq
    property bool playing: false
    property color tone: Theme.t.accent
    spacing: 3; height: 22
    Repeater { model: [10, 18, 13, 20, 8]
        Rectangle { required property int modelData; required property int index
            width: 3; height: modelData; radius: 2; color: eq.tone; anchors.verticalCenter: parent.verticalCenter
            opacity: eq.playing ? 1 : 0.45
            SequentialAnimation on scale { running: eq.playing && Theme.t.moveMs > 0; loops: Animation.Infinite
                PauseAnimation { duration: index * 90 }
                NumberAnimation { from: 0.45; to: 1; duration: 420; easing.type: Easing.InOutSine }
                NumberAnimation { from: 1; to: 0.45; duration: 420; easing.type: Easing.InOutSine } } } }
}
