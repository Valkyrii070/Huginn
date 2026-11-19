import QtQuick

// A slim bar: progress, usage, or (with `interactive`) a slider.
Rectangle {
    id: m
    property real value: 0
    property bool interactive: false
    property color fill: Theme.t.accent
    signal moved(real v)
    height: 6; radius: 3; color: Theme.t.dark ? "#26FFFFFF" : "#26141E28"
    Rectangle { width: Math.max(0, Math.min(1, m.value)) * parent.width; height: parent.height; radius: 3; color: m.fill }
    Rectangle { visible: m.interactive; width: 14; height: 14; radius: 7; y: -4; x: Math.max(0, Math.min(1, m.value)) * (parent.width - 14); color: "#FFFFFF"; border.width: 1; border.color: Theme.t.capsule_border }
    MouseArea { enabled: m.interactive; anchors.fill: parent; anchors.margins: -8
        function at(mx) { m.moved(Math.max(0, Math.min(1, (mx - 8) / m.width))) }
        onPressed: function (e) { at(e.x) } onPositionChanged: function (e) { at(e.x) } }
}
