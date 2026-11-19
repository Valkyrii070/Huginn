import QtQuick

// A stack, opened over its dock tile: one line per file (or a grid, if picked), the newest first and anything still
// arriving on top. Click a file: it opens. Drag it out: to an app, a folder, the desktop. Right-click: Open, Open
// with, Show in Files, Copy, Move to, Rename, Move to Bin. The ⋯ (or right-clicking the tile): sort, list or grid,
// clearing out old downloads, Open in Files.
Glass {
    id: isle
    property string folder: ""
    property bool startWithMenu: false
    signal done()
    readonly property var stack: { var all = Stacks.stacks; for (var i = 0; i < all.length; i++) if (all[i].folder === folder) return all[i]; return null }
    readonly property bool grid: Stacks.options.view === "grid"
    property var menuFor: null              // the file whose menu is open ("stack": the stack's own)
    property string menuLevel: ""           // "", "open", "move"
    property real menuY: 0
    property string renaming: ""
    popup: true; dense: true; radius: 22
    width: grid ? 420 : 400
    height: Math.min(560, body.height + 24)
    onFolderChanged: { menuFor = startWithMenu ? "stack" : null; menuLevel = ""; renaming = ""; menuY = 46 }
    function closeMenu() { menuFor = null; menuLevel = "" }
    function appsFor(file) {
        if (!file || !file.mime) return []
        var top = file.mime.split("/")[0] + "/*"
        return Apps.all.filter(function (a) { return a.mimes && (a.mimes.indexOf(file.mime) >= 0 || a.mimes.indexOf(top) >= 0) }).slice(0, 5)
    }
    Keys.onEscapePressed: { if (renaming !== "") renaming = ""; else if (menuFor !== null) closeMenu(); else done() }

    Column {
        id: body
        x: 12; y: 12; width: isle.width - 24; spacing: 6
        Item {   // the stack's name, how many, Open in Files and its menu
            width: parent.width; height: 34
            Row {
                x: 6; spacing: 8; anchors.verticalCenter: parent.verticalCenter
                Glyph { name: isle.stack && isle.stack.downloads ? "download" : "folder"; size: 16; ink: Theme.t.icon; anchors.verticalCenter: parent.verticalCenter }
                Label { text: isle.stack ? isle.stack.name : ""; font.pixelSize: 14; font.weight: Font.DemiBold; anchors.verticalCenter: parent.verticalCenter }
                Label { text: isle.stack ? (isle.stack.count === 1 ? "1 item" : isle.stack.count + " items") : ""; secondary: true; font.pixelSize: 12; anchors.verticalCenter: parent.verticalCenter }
            }
            Row {
                anchors { right: parent.right; verticalCenter: parent.verticalCenter }
                spacing: 4
                Label {
                    text: "Open in Files"; color: Theme.t.accent; font.pixelSize: 13; font.weight: Font.DemiBold; anchors.verticalCenter: parent.verticalCenter
                    MouseArea { anchors.fill: parent; anchors.margins: -6; onClicked: { Stacks.showInFiles(isle.folder); isle.done() } }
                }
                Rectangle {
                    width: 30; height: 30; radius: 10; color: dots.containsMouse || isle.menuFor === "stack" ? Theme.t.hover : "transparent"
                    Label { anchors.centerIn: parent; text: "⋯"; font.pixelSize: 16 }
                    MouseArea { id: dots; anchors.fill: parent; hoverEnabled: true; onClicked: { isle.menuY = 46; isle.menuFor = isle.menuFor === "stack" ? null : "stack"; isle.menuLevel = "" } }
                }
            }
        }
        Label {
            visible: isle.stack !== null && isle.stack.items.length === 0; x: 6
            text: isle.stack && isle.stack.downloads ? "Nothing downloaded yet. Files you download land here." : "This folder is empty."
            secondary: true; font.pixelSize: 13; height: 40; verticalAlignment: Text.AlignVCenter
        }
        // ---------------------------------------------------------------- one line per file
        ListView {
            id: list
            visible: !isle.grid
            width: parent.width; height: Math.min(contentHeight, 470); clip: true; interactive: contentHeight > height
            model: isle.stack ? isle.stack.items : []
            spacing: 2
            delegate: Item {
                id: row
                required property var modelData
                required property int index
                width: list.width; height: modelData.partial ? 62 : 52
                Rectangle { anchors.fill: parent; radius: 12; color: rowHit.containsMouse || isle.menuFor === row.modelData ? Theme.t.hover : (row.modelData.partial ? Qt.rgba(1, 1, 1, Theme.t.dark ? 0.04 : 0.3) : "transparent") }
                FileArt { id: art; file: row.modelData; size: 36; x: 10; anchors.verticalCenter: parent.verticalCenter }
                Column {
                    anchors { left: art.right; leftMargin: 12; right: when.left; rightMargin: 10; verticalCenter: parent.verticalCenter }
                    spacing: 3
                    Label { visible: isle.renaming !== row.modelData.path; width: parent.width; text: row.modelData.name; elide: Text.ElideMiddle; font.pixelSize: 13; font.weight: Font.DemiBold }
                    Rectangle {   // renaming
                        visible: isle.renaming === row.modelData.path; width: parent.width; height: 24; radius: 7; color: Theme.t.view; border.width: 1.5; border.color: Theme.t.accent
                        TextInput {
                            id: nameField; anchors { fill: parent; leftMargin: 7; rightMargin: 7 } verticalAlignment: Text.AlignVCenter
                            color: Theme.t.text; font.pixelSize: 13; selectByMouse: true; clip: true
                            onVisibleChanged: if (visible) { text = row.modelData.name; forceActiveFocus(); var dot = text.lastIndexOf("."); select(0, dot > 0 ? dot : text.length) }
                            onAccepted: { Stacks.rename(row.modelData.path, text); isle.renaming = "" }
                            Keys.onEscapePressed: isle.renaming = ""
                        }
                    }
                    Rectangle {   // arriving: how far
                        visible: row.modelData.partial; width: parent.width; height: 4; radius: 2; color: Theme.t.line; clip: true
                        Rectangle { visible: row.modelData.progress >= 0; width: parent.width * Math.max(0.02, row.modelData.progress); height: parent.height; radius: 2; color: Theme.t.accent }
                        Rectangle {
                            id: wave; visible: row.modelData.progress < 0 && !row.modelData.stalled; width: parent.width * 0.35; height: parent.height; radius: 2
                            gradient: Gradient { orientation: Gradient.Horizontal; GradientStop { position: 0; color: "transparent" } GradientStop { position: 0.5; color: Theme.t.accent } GradientStop { position: 1; color: "transparent" } }
                            NumberAnimation on x { from: -wave.width; to: list.width; duration: 1200; loops: Animation.Infinite; running: wave.visible }
                        }
                    }
                    Label {
                        width: parent.width; elide: Text.ElideRight; secondary: true; font.pixelSize: 12
                        text: row.modelData.partial ? row.modelData.size + (row.modelData.stalled ? " · stopped " + row.modelData.when : " so far") : row.modelData.size + (row.modelData.from ? " · from " + row.modelData.from : "")
                    }
                }
                Label { id: when; anchors { right: parent.right; rightMargin: 12; verticalCenter: parent.verticalCenter } text: row.modelData.partial ? (row.modelData.stalled ? "didn't finish" : "arriving") : row.modelData.when; secondary: true; font.pixelSize: 12 }
                MouseArea {
                    id: rowHit; anchors.fill: parent; hoverEnabled: true; acceptedButtons: Qt.LeftButton | Qt.RightButton
                    enabled: isle.renaming !== row.modelData.path
                    onClicked: function (m) {
                        if (m.button === Qt.RightButton) { isle.menuFor = row.modelData; isle.menuLevel = ""; isle.menuY = Math.min(isle.height - 300, row.mapToItem(isle, 0, row.height).y); return }
                        if (row.modelData.partial) return
                        Stacks.open(row.modelData.path); isle.done()
                    }
                }
                // drag it out: to an app, a folder, the desktop
                DragHandler { id: drag; target: null; enabled: !row.modelData.partial }
                Drag.active: drag.active
                Drag.dragType: Drag.Automatic
                Drag.supportedActions: Qt.CopyAction | Qt.MoveAction
                Drag.mimeData: ({ "text/uri-list": row.modelData.url })
            }
        }
        // ---------------------------------------------------------------- or a grid
        GridView {
            id: gridView
            visible: isle.grid
            width: parent.width; height: Math.min(Math.ceil(count / 4) * 104, 420); clip: true
            cellWidth: width / 4; cellHeight: 104
            model: isle.stack ? isle.stack.items : []
            delegate: Item {
                id: cell
                required property var modelData
                width: gridView.cellWidth; height: gridView.cellHeight
                Rectangle { anchors.fill: parent; anchors.margins: 3; radius: 12; color: cellHit.containsMouse || isle.menuFor === cell.modelData ? Theme.t.hover : "transparent" }
                FileArt { file: cell.modelData; size: 54; anchors.horizontalCenter: parent.horizontalCenter; y: 10 }
                Label { width: parent.width - 12; x: 6; y: 70; horizontalAlignment: Text.AlignHCenter; text: cell.modelData.name; elide: Text.ElideMiddle; font.pixelSize: 12 }
                MouseArea {
                    id: cellHit; anchors.fill: parent; hoverEnabled: true; acceptedButtons: Qt.LeftButton | Qt.RightButton
                    onClicked: function (m) {
                        if (m.button === Qt.RightButton) { isle.menuFor = cell.modelData; isle.menuLevel = ""; isle.menuY = Math.min(isle.height - 300, cell.mapToItem(isle, 0, cell.height).y); return }
                        if (!cell.modelData.partial) { Stacks.open(cell.modelData.path); isle.done() }
                    }
                }
                DragHandler { id: cdrag; target: null; enabled: !cell.modelData.partial }
                Drag.active: cdrag.active
                Drag.dragType: Drag.Automatic
                Drag.supportedActions: Qt.CopyAction | Qt.MoveAction
                Drag.mimeData: ({ "text/uri-list": cell.modelData.url })
            }
        }
    }

    // ---------------------------------------------------------------- the menus
    component MenuRow: Rectangle {
        id: mi
        property string text: ""
        property string hint: ""
        property bool on: false
        property bool danger: false
        signal picked()
        width: menu.width - 12; height: 30; radius: 8; color: mih.containsMouse ? (danger ? "#E5484D" : Theme.t.accent) : "transparent"
        Label { x: 10; anchors.verticalCenter: parent.verticalCenter; text: (mi.on ? "✓  " : "") + mi.text; font.pixelSize: 13; color: mih.containsMouse ? (Theme.t.dark || mi.danger ? "white" : "#0B1512") : (mi.danger ? "#E5484D" : Theme.t.text) }
        Label { anchors { right: parent.right; rightMargin: 10; verticalCenter: parent.verticalCenter } text: mi.hint; font.pixelSize: 12; secondary: !mih.containsMouse }
        MouseArea { id: mih; anchors.fill: parent; hoverEnabled: true; onClicked: mi.picked() }
    }
    component MenuLine: Rectangle { width: menu.width - 20; x: 4; height: 1; color: Theme.t.line }
    MouseArea { anchors.fill: parent; visible: isle.menuFor !== null; onClicked: isle.closeMenu() }
    Glass {
        id: menu
        visible: isle.menuFor !== null
        popup: true; dense: true; radius: 14; width: 230; height: items.height + 12
        x: isle.width - width - 14; y: Math.max(8, Math.min(isle.height - height - 8, isle.menuY))
        Column {
            id: items
            x: 6; y: 6; spacing: 1
            // the stack's own
            Label { visible: isle.menuFor === "stack"; x: 10; text: "SORT BY"; secondary: true; font.pixelSize: 10; font.weight: Font.DemiBold; height: 22; verticalAlignment: Text.AlignBottom }
            Repeater {
                model: isle.menuFor === "stack" ? [["date", "Date added"], ["name", "Name"], ["kind", "Kind"]] : []
                MenuRow { required property var modelData; text: modelData[1]; on: Stacks.options.sort === modelData[0]; onPicked: Stacks.setOption("sort", modelData[0]) }
            }
            MenuLine { visible: isle.menuFor === "stack" }
            MenuRow { visible: isle.menuFor === "stack"; text: isle.grid ? "Show as a list" : "Show as a grid"; onPicked: { Stacks.setOption("view", isle.grid ? "list" : "grid"); isle.closeMenu() } }
            MenuRow { visible: isle.menuFor === "stack" && isle.stack && isle.stack.downloads; text: "Clear out after 30 days"; on: Stacks.options.clear30; onPicked: Stacks.setOption("clear30", Stacks.options.clear30 ? "false" : "true") }
            MenuRow { visible: isle.menuFor === "stack"; text: "Open in Files"; onPicked: { Stacks.showInFiles(isle.folder); isle.done() } }
            MenuRow { visible: isle.menuFor === "stack" && isle.stack && !isle.stack.downloads; text: "Remove from the dock"; onPicked: { Stacks.removeFolder(isle.folder); isle.done() } }
            // a file's
            readonly property bool file: isle.menuFor !== null && isle.menuFor !== "stack"
            MenuRow { visible: items.file && isle.menuLevel === ""; text: "Open"; onPicked: { Stacks.open(isle.menuFor.path); isle.done() } }
            MenuRow { visible: items.file && isle.menuLevel === "" && isle.appsFor(isle.menuFor).length > 0; text: "Open with"; hint: "›"; onPicked: isle.menuLevel = "open" }
            MenuRow { visible: items.file && isle.menuLevel === ""; text: "Show in Files"; onPicked: { Stacks.showInFiles(isle.menuFor.path); isle.done() } }
            MenuRow { visible: items.file && isle.menuLevel === ""; text: "Copy"; onPicked: { Stacks.copy(isle.menuFor.path); isle.closeMenu() } }
            MenuRow { visible: items.file && isle.menuLevel === ""; text: "Move to"; hint: "›"; onPicked: isle.menuLevel = "move" }
            MenuRow { visible: items.file && isle.menuLevel === ""; text: "Rename"; onPicked: { isle.renaming = isle.menuFor.path; isle.closeMenu() } }
            MenuLine { visible: items.file && isle.menuLevel === "" }
            MenuRow { visible: items.file && isle.menuLevel === ""; text: "Move to Bin"; danger: true; onPicked: { Stacks.trash(isle.menuFor.path); isle.closeMenu() } }
            MenuRow { visible: items.file && isle.menuLevel !== ""; text: "‹  Back"; onPicked: isle.menuLevel = "" }
            Repeater {
                model: items.file && isle.menuLevel === "open" ? isle.appsFor(isle.menuFor) : []
                MenuRow { required property var modelData; text: modelData.name; onPicked: { Apps.openWith(modelData.name, isle.menuFor.path); isle.done() } }
            }
            Repeater {
                model: items.file && isle.menuLevel === "move" ? ["Desktop", "Documents", "Pictures", "Music", "Videos"] : []
                MenuRow { required property var modelData; text: modelData; onPicked: { Stacks.moveTo(isle.menuFor.path, modelData); isle.closeMenu() } }
            }
        }
    }
    transformOrigin: Item.Bottom
    scale: visible ? 1 : 0.92
    Behavior on scale { NumberAnimation { duration: Theme.t.openMs ? 170 : 0; easing.type: Easing.OutCubic } }
}
