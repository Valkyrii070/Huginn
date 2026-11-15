import QtQuick

// Archives, "unpack bar": what is inside as a sheet of glass; one wide island does the unpacking.
GlassWindow {
    id: win
    title: "Archives"; heading: Backend.isOpen ? Backend.name : ""; glow: "bottom"; sidebarWidth: 240; padTop: 60; padBottom: 66
    property string picked: ""
    property string notice: ""
    Connections { target: Backend; function onFailed(msg) { win.notice = msg; hide.restart() } function onChanged() { win.picked = "" } }
    Timer { id: hide; interval: 7000; onTriggered: win.notice = "" }
    sidebar: [
        SideTitle { text: "IN DOWNLOADS AND DOCUMENTS" },
        Repeater { model: Backend.nearby; SideItem { required property var modelData; icon: "file"; text: modelData.name; selected: Backend.name === modelData.name; onClicked: Backend.open(modelData.path) } },
        Label { visible: Backend.nearby.length === 0; leftPadding: 10; width: parent.width; wrapMode: Text.WordWrap; secondary: true; font.pixelSize: 12; text: "Zip and tar files you download appear here." }
    ]
    islands: [
        Island {   // the unpack bar: the main island
            visible: Backend.isOpen; x: 276 + (win.width - 276 - width) / 2; anchors { bottom: parent.bottom; bottomMargin: 14 }
            Label { leftPadding: 10; rightPadding: 6; width: Math.min(implicitWidth, win.width - 276 - 420); elide: Text.ElideRight; font.pixelSize: 12; anchors.verticalCenter: parent.verticalCenter
                color: win.notice ? Theme.t.danger : Theme.t.text_secondary; text: win.notice || Backend.note || Backend.summary }
            Seg { visible: Backend.lastFolder !== "" && Backend.note !== ""; icon: "folder"; text: "Show Folder"; onClicked: Backend.showFolder() }
            Seg { visible: win.picked !== ""; icon: "download"; text: "Unpack Selected"; onClicked: Backend.extract(win.picked) }
            Seg { icon: "download"; text: "Unpack All"; on: true; onClicked: Backend.extract("") }
        }
    ]
    Column { visible: !Backend.isOpen; anchors.centerIn: parent; spacing: 8; width: 380
        Item { width: 190; height: 160; anchors.horizontalCenter: parent.horizontalCenter      // a box, zipped shut down the middle
            Rectangle { x: 15; y: 40; width: 160; height: 112; radius: 12; color: Qt.rgba(tintColor.r, tintColor.g, tintColor.b, 0.16); border.width: 1.5; border.color: Theme.t.accent }
            Rectangle { x: 5; y: 18; width: 180; height: 34; radius: 9; color: Theme.t.island; border.width: 1.5; border.color: Theme.t.accent }
            Repeater { model: 9; Rectangle { required property int index; x: index % 2 ? 96 : 86; y: 22 + index * 14; width: 8; height: 6; radius: 2; color: Theme.t.accent } }
            Rectangle { x: 85; y: 146; width: 20; height: 14; radius: 5; color: Theme.t.accent; Rectangle { anchors.centerIn: parent; width: 8; height: 4; radius: 2; color: Theme.t.onAccent } } }
        Label { text: "No archive open"; font.pixelSize: 17; font.weight: Font.DemiBold; anchors.horizontalCenter: parent.horizontalCenter }
        Label { width: parent.width; horizontalAlignment: Text.AlignHCenter; wrapMode: Text.WordWrap; color: win.notice ? Theme.t.danger : Theme.t.text_secondary; text: win.notice || "Double-click a zip or tar file in Files, or choose one on the left." } }
    Item { visible: Backend.isOpen; anchors.fill: parent
        Row { x: 4; y: 0; spacing: 6; height: 30
            Repeater { model: Backend.crumbs
                Row { required property var modelData; required property int index; spacing: 6; anchors.verticalCenter: parent.verticalCenter
                    Label { visible: index > 0; text: "›"; secondary: true; anchors.verticalCenter: parent.verticalCenter }
                    Pressable { width: c.width + 14; height: 26; radius: Theme.t.radiusControl; onClicked: Backend.enter(modelData.full); Label { id: c; anchors.centerIn: parent; text: modelData.name; font.weight: index === Backend.crumbs.length - 1 ? Font.DemiBold : Font.Normal } } } } }
        Rectangle { x: 0; y: 38; width: parent.width - 14; height: parent.height - 38; radius: 12; color: Theme.t.group; border.width: 1; border.color: Theme.t.islandLine }
        Row { x: 6; y: 42; height: 26; Label { width: list.width - 300; leftPadding: 44; text: "Name"; secondary: true; font.pixelSize: 11 } Label { width: 160; text: "Changed"; secondary: true; font.pixelSize: 11 } Label { width: 120; text: "Size"; secondary: true; font.pixelSize: 11 } }
        Flickable { id: list; x: 6; y: 68; width: parent.width - 26; height: parent.height - 68 - 6; contentHeight: rows.height; clip: true
            Column { id: rows; width: parent.width
                Repeater { model: Backend.entries
                    Pressable { required property var modelData; width: rows.width; height: 34; radius: 9; color: win.picked === modelData.full ? Theme.t.hover : (hovered ? Qt.rgba(0.5, 0.5, 0.5, 0.08) : "transparent")
                        Glyph { x: 12; anchors.verticalCenter: parent.verticalCenter; name: modelData.kind; ink: modelData.dir ? Theme.t.accent : Theme.t.icon }
                        Label { x: 44; width: parent.width - 350; anchors.verticalCenter: parent.verticalCenter; text: modelData.name; elide: Text.ElideMiddle }
                        Label { x: parent.width - 300; anchors.verticalCenter: parent.verticalCenter; text: modelData.when; secondary: true; font.pixelSize: 12 }
                        Label { x: parent.width - 140; anchors.verticalCenter: parent.verticalCenter; text: modelData.dir ? "Folder" : modelData.size; secondary: true; font.pixelSize: 12 }
                        MouseArea { anchors.fill: parent; onClicked: win.picked = modelData.full; onDoubleClicked: if (modelData.dir) Backend.enter(modelData.full) } } } } }
    }
}
