import QtQuick

// Sheets, "glass grid": the grid is a sheet of glass, lit from the formula bar at the top.
GlassWindow {
    id: win
    title: "Sheets"; heading: Backend.title || ""; sidebarWidth: 232; width: 1180; height: 760; glow: "top"; padTop: 60; padBottom: 62; padRight: 14
    property int row: 0
    property int col: 0
    property string notice: ""
    property string exported: ""
    property int naming: -1                               // the sheet being renamed, or -1
    readonly property int cw: 112
    readonly property int rh: 28
    function show() { entry.text = Backend.raw(row, col); entry.selectAll(); entry.forceActiveFocus(); table.positionViewAtCell(Qt.point(col, row), TableView.Contain) }
    function commit() { Backend.put(row, col, entry.text) }
    function go(r, c) { commit(); row = Math.max(0, Math.min(199, r)); col = Math.max(0, Math.min(25, c)); show() }
    Connections { target: Backend
        function onFailed(msg) { win.notice = msg; hide.restart() }
        function onChanged() { if (!entry.activeFocus) win.show() } }
    onRowChanged: summary.text = Backend.columnSummary(col); onColChanged: summary.text = Backend.columnSummary(col)
    Timer { id: hide; interval: 7000; onTriggered: { win.notice = ""; win.exported = "" } }
    Component.onCompleted: show()
    onClosing: { commit(); Backend.save() }
    sidebar: [ DocList { newLabel: "New Sheet"; icon: "table"; empty: "Sheets you make appear here, along with CSV and Excel files in your Documents folder." } ]
    toolbar: [ ExportMenu { visible: Backend.current !== ""; choices: [["xlsx", "Excel", "An .xlsx file, formulas included"], ["csv", "CSV", "Plain values, opens anywhere"]]
        onChosen: function (key) { win.commit(); var p = Backend.export(key); if (p) { win.exported = p; hide.restart() } } } ]

    islands: [
        Island {   // the sheets in this file, then saved or not and where an export went
            visible: Backend.current !== ""; x: 268; anchors { bottom: parent.bottom; bottomMargin: 14 }
            Flickable { width: Math.min(tabs.width, Math.max(120, win.width - 268 - 620)); height: 30; contentWidth: tabs.width; clip: true; anchors.verticalCenter: parent.verticalCenter; flickableDirection: Flickable.HorizontalFlick
                Row { id: tabs; height: 30; spacing: 4
                    Repeater { model: Backend.sheetNames
                        Seg { required property string modelData; required property int index; text: modelData; on: Backend.sheetIndex === index; tip: "Click again to rename"
                            onClicked: { if (on) { rename.text = modelData; win.naming = index } else { win.commit(); Backend.selectSheet(index); win.show() } } } } } }
            Seg { visible: !Backend.oneSheetOnly; icon: "plus"; tip: "Add a sheet"; onClicked: { win.commit(); Backend.addSheet(); win.show() } }
            IslandGap {}
            Label { leftPadding: 4; rightPadding: 10; width: Math.min(implicitWidth, 260); elide: Text.ElideMiddle; font.pixelSize: 12; anchors.verticalCenter: parent.verticalCenter
                color: win.notice ? Theme.t.danger : Theme.t.text_secondary; text: win.notice || (win.exported ? "Exported to " + win.exported : (Backend.saved ? "Saved" : "Saving…")) } },
        Island {   // the column you are in, added up
            visible: Backend.current !== "" && summary.text !== ""; anchors { right: parent.right; rightMargin: 14; bottom: parent.bottom; bottomMargin: 14 }
            Label { id: summary; leftPadding: 10; rightPadding: 10; font.pixelSize: 12; anchors.verticalCenter: parent.verticalCenter } }
    ]
    Column { visible: Backend.current === ""; anchors.verticalCenter: parent.verticalCenter; x: win.middleX(width, parent.y + y, height) - parent.x; spacing: 10
        Item { width: 264; height: 150; anchors.horizontalCenter: parent.horizontalCenter      // a corner of a sheet: one cell chosen, a small chart growing out of it
            Rectangle { anchors.fill: parent; radius: 12; color: Theme.t.island; border.width: 1; border.color: Theme.t.islandLine; clip: true
                Repeater { model: 5; Rectangle { required property int index; x: 0; y: 30 * index; width: 264; height: 1; color: Theme.t.islandLine } }
                Repeater { model: 5; Rectangle { required property int index; x: 44 + 55 * index; y: 0; width: 1; height: 150; color: Theme.t.islandLine } }
                Rectangle { width: 264; height: 30; color: Qt.rgba(tintColor.r, tintColor.g, tintColor.b, 0.14) } Rectangle { width: 44; height: 150; color: Qt.rgba(tintColor.r, tintColor.g, tintColor.b, 0.14) }
                Repeater { model: [[1, 1, 30], [1, 2, 22], [1, 3, 36], [2, 1, 18], [2, 2, 40]]; Rectangle { required property var modelData; x: 52 + 55 * (modelData[0] - 1); y: 30 * modelData[1] + 13; width: modelData[2]; height: 4; radius: 2; color: Theme.t.text_secondary; opacity: 0.5 } }
                Rectangle { x: 99; y: 90; width: 56; height: 31; color: "transparent"; border.width: 2; border.color: Theme.t.accent; Rectangle { x: 50; y: 25; width: 8; height: 8; radius: 2; color: Theme.t.accent } } }
            Row { x: 176; y: 62; spacing: 5; Repeater { model: [26, 44, 34, 62]; Rectangle { required property int modelData; width: 13; height: modelData; y: 76 - modelData; radius: 3; color: Theme.t.accent } } } }
        Label { text: "Start a sheet"; font.pixelSize: 17; font.weight: Font.DemiBold; anchors.horizontalCenter: parent.horizontalCenter }
        Btn { text: "New Sheet"; primary: true; anchors.horizontalCenter: parent.horizontalCenter; onClicked: Backend.create() } }
    Item { visible: Backend.current !== ""; anchors.fill: parent
        ImportNote { id: note; x: 0; y: 0; width: parent.width; file: Backend.importedFile; dropped: Backend.importedDropped; onDismissed: Backend.dismissNote() }
        // ---- formula bar: where the selected cell is typed
        Rectangle { id: bar; y: note.visible ? note.height + 16 : 0; width: parent.width; height: 44; color: "transparent"
            Rectangle { x: 0; y: 5; width: 64; height: 30; radius: 11; color: Theme.t.accent; Label { anchors.centerIn: parent; text: Backend.column(win.col) + (win.row + 1); font.weight: Font.DemiBold; font.family: Theme.t.fontMono; color: Theme.t.onAccent } }
            Rectangle { x: 72; y: 5; width: parent.width - 72; height: 30; radius: 11; color: Theme.t.island; border.width: 1; border.color: entry.activeFocus ? Theme.t.accent : Theme.t.islandLine
                TextInput { id: entry; anchors { fill: parent; leftMargin: 10; rightMargin: 10 } verticalAlignment: TextInput.AlignVCenter; clip: true; color: Theme.t.text; font.family: Theme.t.font; font.pixelSize: 13; selectionColor: Theme.t.accent; selectByMouse: true
                    Keys.onPressed: function (e) {
                        if (e.key === Qt.Key_Return || e.key === Qt.Key_Enter) { win.go(win.row + ((e.modifiers & Qt.ShiftModifier) ? -1 : 1), win.col); e.accepted = true }
                        else if (e.key === Qt.Key_Tab) { win.go(win.row, win.col + 1); e.accepted = true } else if (e.key === Qt.Key_Backtab) { win.go(win.row, win.col - 1); e.accepted = true }
                        else if (e.key === Qt.Key_Down) { win.go(win.row + 1, win.col); e.accepted = true } else if (e.key === Qt.Key_Up) { win.go(win.row - 1, win.col); e.accepted = true }
                        else if (e.key === Qt.Key_Escape) { text = Backend.raw(win.row, win.col); selectAll(); e.accepted = true } }
                    Label { visible: !entry.text; anchors.verticalCenter: parent.verticalCenter; color: Theme.t.text_secondary; text: "Type a value, or a formula such as =SUM(B2:B9)" } } }
        }
        // ---- the grid
        Item { id: gridArea; y: bar.y + 44; width: parent.width; height: parent.height - y; clip: true
            Rectangle { anchors.fill: parent; color: Theme.t.group; border.width: 1; border.color: Theme.t.islandLine }
            TableView { id: table; x: 46; y: win.rh; width: parent.width - 46; height: parent.height - win.rh; clip: true; model: Backend.grid; boundsBehavior: Flickable.StopAtBounds
                columnWidthProvider: function () { return win.cw } rowHeightProvider: function () { return win.rh }
                delegate: Rectangle { required property string display; required property bool number; required property bool problem; required property bool formula; required property int row; required property int column
                    readonly property bool picked: row === win.row && column === win.col
                    color: picked ? Qt.rgba(Qt.color(Theme.t.accent).r, Qt.color(Theme.t.accent).g, Qt.color(Theme.t.accent).b, 0.14) : (row === 0 && display !== "" ? (Theme.t.dark ? "#0DFFFFFF" : "#07141E28") : "transparent")
                    Rectangle { anchors.right: parent.right; width: 1; height: parent.height; color: Theme.t.separator } Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: Theme.t.separator }
                    Rectangle { visible: parent.picked; anchors.fill: parent; color: "transparent"; border.width: 2; border.color: Theme.t.accent }
                    Label { x: 8; width: parent.width - 16; anchors.verticalCenter: parent.verticalCenter; text: parent.display; elide: Text.ElideRight; horizontalAlignment: parent.number ? Text.AlignRight : Text.AlignLeft
                        color: parent.problem ? Theme.t.danger : Theme.t.text; font.weight: parent.row === 0 ? Font.DemiBold : Font.Normal; font.family: parent.number ? Theme.t.fontMono : Theme.t.font; font.pixelSize: parent.number ? 12 : 13 }
                    MouseArea { anchors.fill: parent; onClicked: win.go(parent.row, parent.column) } } }
            Rectangle { x: 46; width: parent.width - 46; height: win.rh; color: Theme.t.dark ? "#12FFFFFF" : "#0D141E28"; clip: true
                Row { x: -table.contentX; Repeater { model: 26
                    Rectangle { required property int index; width: win.cw; height: win.rh; color: index === win.col ? Theme.t.hover : "transparent"
                        Rectangle { anchors.right: parent.right; width: 1; height: parent.height; color: Theme.t.separator }
                        Label { anchors.centerIn: parent; text: Backend.column(index); secondary: index !== win.col; font.pixelSize: 12; font.weight: index === win.col ? Font.DemiBold : Font.Normal } } } }
                Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: Theme.t.separator } }
            Rectangle { y: win.rh; width: 46; height: parent.height - win.rh; color: Theme.t.dark ? "#12FFFFFF" : "#0D141E28"; clip: true
                Column { y: -table.contentY; Repeater { model: 200
                    Rectangle { required property int index; width: 46; height: win.rh; color: index === win.row ? Theme.t.hover : "transparent"
                        Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: Theme.t.separator }
                        Label { anchors.centerIn: parent; text: index + 1; secondary: index !== win.row; font.pixelSize: 11 } } } }
                Rectangle { anchors.right: parent.right; width: 1; height: parent.height; color: Theme.t.separator } }
            Rectangle { width: 46; height: win.rh; color: Theme.t.dark ? "#12FFFFFF" : "#0D141E28" } }
    }
    // ---- rename or delete a sheet: opens when you click the tab that is already in front
    MouseArea { visible: win.naming >= 0; anchors { fill: parent; topMargin: -60; bottomMargin: -62 } z: 39; onClicked: win.naming = -1 }
    Rectangle { visible: win.naming >= 0; z: 40; x: 12; anchors { bottom: parent.bottom; bottomMargin: 2 } width: 320; height: 108; radius: 16; color: Theme.t.menu_bg; border.width: 1; border.color: Theme.t.menu_border
        MouseArea { anchors.fill: parent }
        function done() { Backend.renameSheet(win.naming, rename.text); win.naming = -1 }
        Label { x: 16; y: 12; text: "SHEET NAME"; secondary: true; font.pixelSize: 11; font.weight: Font.DemiBold }
        Field { id: rename; x: 14; y: 32; width: parent.width - 28; icon: "edit"; placeholder: "Name"; onAccepted: parent.done() }
        Row { anchors { right: parent.right; rightMargin: 14; bottom: parent.bottom; bottomMargin: 10 } spacing: 8
            Btn { visible: Backend.sheetNames.length > 1; text: "Delete Sheet"; danger: true; onClicked: { Backend.removeSheet(win.naming); win.naming = -1; win.show() } }
            Btn { text: "Rename"; primary: true; onClicked: parent.parent.done() } }
    }
}
