import QtQuick

Rectangle {
    property bool on: false
    signal toggled(bool value)
    width: 40; height: 24; radius: 12; color: on ? Theme.t.accent : (Theme.t.dark ? "#2EFFFFFF" : "#40141E28")
    Behavior on color { ColorAnimation { duration: 150 } }
    Rectangle { width: 20; height: 20; radius: 10; y: 2; x: parent.on ? 18 : 2; color: "#FFFFFF"; Behavior on x { NumberAnimation { duration: 150 } } }
    MouseArea { anchors.fill: parent; onClicked: parent.toggled(!parent.on) }
}
