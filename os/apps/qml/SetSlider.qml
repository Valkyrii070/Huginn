import QtQuick

// A slider that reports while you drag (at most every 120 ms) and once more when you let go.
Item {
    id: s
    property real value: 0              // 0..1
    property string lowText: ""
    property string highText: ""
    property string glyphLeft: ""
    property string glyphRight: ""
    property color fill: Theme.t.accent
    property real live: value
    signal moved(real v)
    width: 240; height: 26
    onValueChanged: if (!hold.running) live = value
    Glyph { id: gl; visible: s.glyphLeft !== ""; name: s.glyphLeft; size: 14; ink: Theme.t.text_secondary; anchors.verticalCenter: parent.verticalCenter }
    Label { id: ll; visible: s.lowText !== ""; text: s.lowText; secondary: true; font.pixelSize: 11; anchors.verticalCenter: parent.verticalCenter; x: gl.visible ? 20 : 0 }
    Meter { id: m; interactive: true; fill: s.fill; value: s.live
        x: (gl.visible ? 22 : 0) + (ll.visible ? ll.width + 8 : 0); width: s.width - x - (gr.visible ? 22 : 0) - (lr.visible ? lr.width + 8 : 0); anchors.verticalCenter: parent.verticalCenter
        onMoved: function (v) { s.live = v; if (!tick.running) { s.moved(v); tick.start() } else tick.pending = true; hold.restart() } }
    Label { id: lr; visible: s.highText !== ""; text: s.highText; secondary: true; font.pixelSize: 11; anchors { right: gr.visible ? gr.left : parent.right; rightMargin: gr.visible ? 6 : 0; verticalCenter: parent.verticalCenter } }
    Glyph { id: gr; visible: s.glyphRight !== ""; name: s.glyphRight; size: 16; ink: Theme.t.text_secondary; anchors { right: parent.right; verticalCenter: parent.verticalCenter } }
    Timer { id: tick; interval: 120; property bool pending: false; onTriggered: if (pending) { pending = false; s.moved(s.live) } }
    Timer { id: hold; interval: 900 }
}
