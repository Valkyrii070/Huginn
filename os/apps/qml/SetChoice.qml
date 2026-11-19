import QtQuick

// A segmented choice: options are [[id, label], ...].
Rectangle {
    id: seg
    property var options: []
    property string value: ""
    property int each: 96
    signal picked(string v)
    width: options.length * each; height: 30; radius: Theme.t.radiusControl + 2; color: Theme.t.dark ? "#30000000" : "#1A141E28"
    Row { anchors { fill: parent; margins: 2 }
        Repeater { model: seg.options
            Rectangle { required property var modelData; readonly property bool on: seg.value === String(modelData[0]); width: parent.width / seg.options.length; height: parent.height; radius: Theme.t.radiusControl
                color: on ? (Theme.t.dark ? "#38FFFFFF" : "#FFFFFF") : "transparent"
                Label { anchors.centerIn: parent; text: modelData[1]; font.pixelSize: 12; font.weight: parent.on ? Font.DemiBold : Font.Normal; width: Math.min(implicitWidth, parent.width - 8); elide: Text.ElideRight }
                MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: seg.picked(String(modelData[0])) } } } }
}
