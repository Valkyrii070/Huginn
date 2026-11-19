import QtQuick

// One line about what just happened, or what went wrong. Call say(); it leaves by itself.
Rectangle {
    id: toast
    property bool bad: false
    property string text: ""
    function say(msg, wrong) { text = msg; bad = !!wrong; gone.interval = Math.max(4000, Math.min(11000, msg.length * 70)); gone.restart() }
    visible: text !== ""; z: 15; height: Math.max(32, line.implicitHeight + 14); radius: 12
    width: Math.min(line.implicitWidth + 28, parent ? parent.width - 60 : 400, 620)
    color: Theme.t.menu_bg; border.width: 1; border.color: bad ? Theme.t.danger : Theme.t.menu_border
    Label { id: line; anchors { fill: parent; leftMargin: 14; rightMargin: 14 } verticalAlignment: Text.AlignVCenter; wrapMode: Text.WordWrap; text: toast.text; font.pixelSize: 12
        color: toast.bad ? Theme.t.danger : Theme.t.text }
    Timer { id: gone; onTriggered: toast.text = "" }
    MouseArea { anchors.fill: parent; onClicked: toast.text = "" }
}
