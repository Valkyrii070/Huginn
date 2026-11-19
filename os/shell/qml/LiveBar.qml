import QtQuick

// How far along something is; a sweep when that isn't known (value < 0).
Item {
    id: bar
    property real value: -1
    property color tone: Theme.t.accent
    height: 4
    Rectangle { anchors.fill: parent; radius: height / 2; color: Theme.t.line; clip: true
        Rectangle { visible: bar.value >= 0; width: parent.width * Math.min(1, Math.max(0, bar.value)); height: parent.height; radius: height / 2; color: bar.tone
            Behavior on width { NumberAnimation { duration: 300 } } }
        Rectangle { id: sweep; visible: bar.value < 0; width: parent.width * 0.33; height: parent.height; radius: height / 2; color: bar.tone
            SequentialAnimation on x { running: sweep.visible && Theme.t.moveMs > 0; loops: Animation.Infinite
                NumberAnimation { from: -sweep.width; to: bar.width; duration: 1400; easing.type: Easing.InOutQuad } } } }
}
