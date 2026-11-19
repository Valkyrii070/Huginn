import QtQuick

// System Monitor, "gauges": the gauges are a rail at the left, where the light is; programs are the list.
GlassWindow {
    id: win
    title: "System Monitor"; heading: mine ? "Your Programs" : "All Processes"
    width: 1160; sidebarWidth: 300; glow: "left"; padTop: 58; padRight: 6
    property bool mine: true
    function setMine(v) { mine = String(v) === "true" }
    property string filter: ""
    property string sortKey: "cpu"
    property int picked: -1
    property var menuFor: null
    property var asking: null      // { row, force }
    property var props: null       // { row, list }
    property string notice: ""
    property var shown: {
        var k = sortKey, rows = Backend.rows.filter(function (r) { return (!mine || r.mine) && r.name.toLowerCase().indexOf(filter.toLowerCase()) >= 0 })
        rows.sort(function (a, b) { return k === "name" ? a.name.toLowerCase().localeCompare(b.name.toLowerCase()) : (b[k] - a[k]) || (b.memory - a.memory) })
        return rows
    }
    Connections { target: Backend; function onFailed(msg) { win.notice = msg; hide.restart() } }
    Timer { id: hide; interval: 5000; onTriggered: win.notice = "" }

    component Dot: Rectangle { width: 8; height: 8; radius: 4; anchors.verticalCenter: parent.verticalCenter }
    component Key: Row { property color ink; property string name; property string value; spacing: 7
        Dot { color: parent.ink } Label { text: parent.name; secondary: true; font.pixelSize: 12 } Label { text: parent.value; font.pixelSize: 12; font.family: Theme.t.fontMono } }
    component Title: Row { property string icon; property string text; spacing: 8; topPadding: 6
        Glyph { name: parent.icon; size: 15; anchors.verticalCenter: parent.verticalCenter } Label { text: parent.text; font.weight: Font.DemiBold } }

    sidebar: [
        // ---- Processor: a ring for now, a line for the last two minutes
        Item { width: parent.width; height: 168
            Ring { id: cpuRing; width: 150; height: 150; thickness: 10; anchors.horizontalCenter: parent.horizontalCenter; value: Backend.cpu
                Graph { x: 34; y: 34; width: 82; height: 34; first: Backend.cpuHistory; unit: true; filled: false }
                Label { anchors.horizontalCenter: parent.horizontalCenter; y: 74; text: Math.round(Backend.cpu * 100) + "%"; font.pixelSize: 26; font.weight: Font.Light }
                Row { anchors.horizontalCenter: parent.horizontalCenter; y: 108; spacing: 5; Glyph { name: "cpu"; size: 13; ink: Theme.t.text_secondary } Label { text: "Processor"; secondary: true; font.pixelSize: 11 } } }
            Label { anchors { horizontalCenter: parent.horizontalCenter; bottom: parent.bottom } text: Backend.cores + " cores"; secondary: true; font.pixelSize: 11 } },
        // ---- Memory and swap: two rings in one
        Title { icon: "memory"; text: "Memory" },
        Item { width: parent.width; height: 96
            Column { x: 8; anchors.verticalCenter: parent.verticalCenter; spacing: 6
                Key { ink: Theme.t.accent; name: "Memory"; value: Math.round(Backend.memory * 100) + "%" } Label { leftPadding: 15; text: Backend.memoryLabel; secondary: true; font.pixelSize: 11 }
                Key { ink: Theme.t.glowB; name: "Swap"; value: Math.round(Backend.swap * 100) + "%" } Label { leftPadding: 15; text: Backend.swapLabel; secondary: true; font.pixelSize: 11 } }
            Ring { width: 92; height: 92; thickness: 8; anchors { right: parent.right; rightMargin: 6; verticalCenter: parent.verticalCenter } value: Backend.memory; inner: Backend.swap
                ink: Backend.memory > 0.9 ? Theme.t.danger : Theme.t.accent
                Label { anchors.centerIn: parent; text: Math.round(Backend.memory * 100) + "%"; font.pixelSize: 15; font.weight: Font.DemiBold } } },
        // ---- Network
        Title { icon: "wifi"; text: "Network" },
        Item { width: parent.width; height: 44
            Column { x: 8; spacing: 5; Key { ink: Theme.t.accent; name: "Download"; value: Backend.downLabel } Key { ink: Theme.t.glowB; name: "Upload"; value: Backend.upLabel } }
            Column { anchors.right: parent.right; anchors.rightMargin: 8; spacing: 5
                Label { text: "Total " + Backend.receivedLabel; secondary: true; font.pixelSize: 11; anchors.right: parent.right } Label { text: "Total " + Backend.sentLabel; secondary: true; font.pixelSize: 11; anchors.right: parent.right } } },
        Graph { x: 8; width: parent.width - 16; first: Backend.downHistory; second: Backend.upHistory },
        // ---- Disk
        Title { icon: "disc"; text: "Disk" },
        Row { x: 8; spacing: 18; height: 24; Key { ink: Theme.t.accent; name: "Read"; value: Backend.readLabel } Key { ink: Theme.t.glowB; name: "Write"; value: Backend.writeLabel } },
        Graph { x: 8; width: parent.width - 16; first: Backend.readHistory; second: Backend.writeHistory }
    ]
    toolbar: [
        IslandField { text: win.filter; onTextChanged: win.filter = text; placeholder: "Find a program" },
        Seg { icon: "cpu"; text: "All"; on: !win.mine; onClicked: win.mine = false },
        Seg { icon: "user"; text: "Yours"; on: win.mine; onClicked: win.mine = true }
    ]

    Label { visible: !Backend.supported; anchors.centerIn: parent; secondary: true; text: "System Monitor reads Linux's process list, which this system doesn't have." }
    Item { visible: Backend.supported; anchors.fill: parent
        Label { x: 16; y: 12; text: "Programs running: " + Backend.summary; secondary: true; font.pixelSize: 12 }
        Row { id: header; x: 12; y: 36; height: 30
            component Head: Pressable { property string text; property string key; property bool alignRight: true; height: 30; radius: 6; onClicked: if (key) win.sortKey = key
                Label { x: 10; width: parent.width - 20; anchors.verticalCenter: parent.verticalCenter; horizontalAlignment: parent.alignRight ? Text.AlignRight : Text.AlignLeft
                    text: parent.text + (win.sortKey === parent.key ? "  ↓" : ""); font.pixelSize: 11; font.weight: win.sortKey === parent.key ? Font.DemiBold : Font.Normal; color: win.sortKey === parent.key ? Theme.t.text : Theme.t.text_secondary } }
            Head { width: table.width - 440; text: "Name"; key: "name"; alignRight: false } Head { width: 100; text: "Processor"; key: "cpu" } Head { width: 110; text: "Memory"; key: "memory" }
            Head { width: 120; text: "Disk"; key: "disk" } Head { width: 110; text: "Number"; key: "" } }
        Rectangle { x: 0; y: 66; width: parent.width; height: 1; color: Theme.t.separator }
        Flickable { id: table; x: 12; y: 70; width: parent.width - 24; height: parent.height - 70 - 34; contentHeight: procs.height; clip: true
            Column { id: procs; width: parent.width
                Repeater { model: win.shown.slice(0, 250)
                    Pressable { id: line; required property var modelData; required property int index; width: procs.width; height: 36; radius: 9
                        readonly property bool sel: win.picked === modelData.pid
                        color: sel ? Theme.t.accent : (hovered ? Theme.t.hover : (index % 2 ? (Theme.t.dark ? "#08FFFFFF" : "#07141E28") : "transparent"))
                        readonly property color fg: sel ? Theme.t.onAccent : Theme.t.text
                        readonly property color fg2: sel ? Theme.t.onAccent : Theme.t.text_secondary
                        Rectangle { x: 10; anchors.verticalCenter: parent.verticalCenter; width: 22; height: 22; radius: 6; color: line.sel ? "#33FFFFFF" : Theme.t.hover
                            Label { anchors.centerIn: parent; text: modelData.name.charAt(0).toUpperCase(); font.pixelSize: 11; font.weight: Font.Bold; color: line.fg } }
                        Label { x: 42; width: parent.width - 500; anchors.verticalCenter: parent.verticalCenter; text: modelData.name + (modelData.paused ? "   (paused)" : ""); elide: Text.ElideRight; color: line.fg }
                        // Processor use as a number and a bar, so the heavy ones stand out at a glance.
                        Rectangle { visible: !line.sel && modelData.cpu > 0.5; x: parent.width - 440 + 8; anchors.verticalCenter: parent.verticalCenter; height: 20; radius: 5; width: Math.min(84, modelData.cpu * 0.84)
                            color: Qt.rgba(Qt.color(Theme.t.accent).r, Qt.color(Theme.t.accent).g, Qt.color(Theme.t.accent).b, 0.22) }
                        Label { x: parent.width - 440; width: 90; anchors.verticalCenter: parent.verticalCenter; text: modelData.cpu.toFixed(1) + "%"; horizontalAlignment: Text.AlignRight; font.family: Theme.t.fontMono; font.pixelSize: 12; color: line.fg }
                        Label { x: parent.width - 340; width: 100; anchors.verticalCenter: parent.verticalCenter; text: modelData.memoryLabel; horizontalAlignment: Text.AlignRight; font.family: Theme.t.fontMono; font.pixelSize: 12; color: line.fg }
                        Label { x: parent.width - 230; width: 110; anchors.verticalCenter: parent.verticalCenter; text: modelData.diskLabel || "–"; horizontalAlignment: Text.AlignRight; font.family: Theme.t.fontMono; font.pixelSize: 12; color: line.fg2 }
                        Label { x: parent.width - 110; width: 100; anchors.verticalCenter: parent.verticalCenter; text: modelData.pid; horizontalAlignment: Text.AlignRight; font.family: Theme.t.fontMono; font.pixelSize: 12; color: line.fg2 }
                        MouseArea { anchors.fill: parent; acceptedButtons: Qt.LeftButton | Qt.RightButton
                            onClicked: function (m) { win.picked = modelData.pid; win.menuFor = m.button === Qt.RightButton ? { row: modelData, x: m.x + 12, y: parent.y - table.contentY + m.y + 74 } : null } } } } } }
        Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 34; color: "transparent"
            Rectangle { width: parent.width; height: 1; color: Theme.t.separator }
            Label { x: 16; anchors.verticalCenter: parent.verticalCenter; font.pixelSize: 12; color: win.notice ? Theme.t.danger : Theme.t.text_secondary
                text: win.notice || (win.picked < 0 ? "Click a program to select it. Right-click for more." : "Right-click the selected program for more.") }
            Btn { visible: win.picked >= 0; anchors { right: parent.right; rightMargin: 8; verticalCenter: parent.verticalCenter } height: 24; text: "End Program"
                onClicked: { var r = win.shown.filter(function (x) { return x.pid === win.picked })[0]; if (r) win.asking = { row: r, force: false } } } }
    }
    MouseArea { visible: win.menuFor !== null; anchors.fill: parent; z: 19; acceptedButtons: Qt.LeftButton | Qt.RightButton; onClicked: win.menuFor = null }
    Rectangle {   // right-click menu
        visible: win.menuFor !== null; z: 20; width: 220; height: menu.height + 10; radius: Theme.t.radiusCard; color: Theme.t.menu_bg; border.width: 1; border.color: Theme.t.menu_border
        x: win.menuFor ? Math.min(win.menuFor.x, parent.width - width - 8) : 0; y: win.menuFor ? Math.min(win.menuFor.y, parent.height - height - 8) : 0
        Column { id: menu; x: 5; y: 5; width: parent.width - 10
            Repeater { model: win.menuFor ? [["End program", "x", "end"], [win.menuFor.row.paused ? "Resume" : "Pause", win.menuFor.row.paused ? "play" : "pause", "pause"], ["Show program location", "folder", "where"], ["Properties", "info", "props"], ["", "", ""], ["Force stop", "trash", "force"]] : []
                Item { required property var modelData; width: menu.width; height: modelData[0] ? 30 : 9
                    Rectangle { visible: !modelData[0]; y: 4; width: parent.width; height: 1; color: Theme.t.separator }
                    Pressable { visible: modelData[0] !== ""; anchors.fill: parent; radius: Theme.t.radiusControl
                        onClicked: { var r = win.menuFor.row, a = modelData[2]; win.menuFor = null
                            if (a === "end") win.asking = { row: r, force: false }; else if (a === "force") win.asking = { row: r, force: true }
                            else if (a === "pause") r.paused ? Backend.resume(r.pid) : Backend.pause(r.pid); else if (a === "where") Backend.showLocation(r.pid)
                            else win.props = { row: r, list: Backend.details(r.pid) } }
                        Glyph { x: 8; anchors.verticalCenter: parent.verticalCenter; name: modelData[1]; size: 14; ink: modelData[2] === "force" ? Theme.t.danger : Theme.t.icon }
                        Label { x: 32; anchors.verticalCenter: parent.verticalCenter; text: modelData[0]; color: modelData[2] === "force" ? Theme.t.danger : Theme.t.text } } } } }
    }
    Rectangle { visible: win.asking !== null || win.props !== null; anchors.fill: parent; color: "#66000000"; z: 30; MouseArea { anchors.fill: parent; onClicked: win.props = null } }
    Rectangle { visible: win.asking !== null; z: 31; anchors.centerIn: parent; width: 400; height: 178; radius: Theme.t.radiusTile; color: Theme.t.menu_bg; border.width: 1; border.color: Theme.t.menu_border
        Label { x: 22; y: 20; text: (win.asking && win.asking.force ? "Force “" : "End “") + (win.asking ? win.asking.row.name : "") + (win.asking && win.asking.force ? "” to stop?" : "”?"); font.pixelSize: 16; font.weight: Font.DemiBold }
        Label { x: 22; y: 50; width: parent.width - 44; wrapMode: Text.WordWrap; secondary: true; lineHeight: 1.3
            text: win.asking && win.asking.force ? "It stops at once with no chance to save. Use this only when End Program didn't work." : "The program is asked to close. Anything in it that you haven't saved may be lost." }
        Row { anchors { right: parent.right; rightMargin: 22; bottom: parent.bottom; bottomMargin: 20 } spacing: 8
            Btn { text: "Cancel"; onClicked: win.asking = null }
            Btn { text: win.asking && win.asking.force ? "Force Stop" : "End Program"; danger: true; onClicked: { win.asking.force ? Backend.force(win.asking.row.pid) : Backend.end(win.asking.row.pid); win.asking = null; win.picked = -1 } } } }
    Rectangle { visible: win.props !== null; z: 31; anchors.centerIn: parent; width: 480; height: plist.height + 110; radius: Theme.t.radiusTile; color: Theme.t.menu_bg; border.width: 1; border.color: Theme.t.menu_border
        Label { x: 22; y: 20; text: win.props ? win.props.row.name : ""; font.pixelSize: 16; font.weight: Font.DemiBold }
        Column { id: plist; x: 22; y: 54; width: parent.width - 44
            Repeater { model: win.props ? win.props.list : []
                Item { required property var modelData; width: plist.width; height: Math.max(30, v.height + 12)
                    Label { y: 6; text: modelData.name; secondary: true } Label { id: v; x: 150; y: 6; width: parent.width - 150; text: modelData.value; wrapMode: Text.WrapAnywhere; font.pixelSize: 12 } } } }
        Btn { anchors { right: parent.right; rightMargin: 22; bottom: parent.bottom; bottomMargin: 18 } text: "Done"; primary: true; onClicked: win.props = null } }
}
