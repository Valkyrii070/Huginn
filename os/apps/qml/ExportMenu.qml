import QtQuick

// A toolbar button that opens a short list of export choices and reports where the file went.
Item {
    id: menu
    property var choices: []          // [[key, label, detail], ...]
    property bool open: false
    signal chosen(string key)
    width: button.width; height: 30; anchors.verticalCenter: parent ? parent.verticalCenter : undefined
    ToolBtn { id: button; icon: "share"; label: "Export"; on: menu.open; onClicked: menu.open = !menu.open }
    Rectangle { visible: menu.open; z: 50; anchors { top: button.bottom; topMargin: 12; right: button.right } width: 270; height: list.height + 10; radius: 14
        color: Theme.t.menu_bg; border.width: 1; border.color: Theme.t.menu_border
        Column { id: list; x: 5; y: 5; width: parent.width - 10
            Repeater { model: menu.choices
                Pressable { required property var modelData; width: list.width; height: 44; radius: Theme.t.radiusControl; onClicked: { menu.open = false; menu.chosen(modelData[0]) }
                    Label { x: 10; y: 6; text: modelData[1]; font.weight: Font.DemiBold } Label { x: 10; y: 24; text: modelData[2]; secondary: true; font.pixelSize: 11 } } } } }
}
