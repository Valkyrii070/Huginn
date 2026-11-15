import QtQuick

// Backup, "the dial and the timeline": one gauge says whether your files are safe; the backups you can go back to
// run along the bottom like points on a line.
GlassWindow {
    id: win
    title: "Backup"; width: 940; height: 640; glow: "centre"; glowY: 0.4
    property var sheet: null                   // { kind: "drive", why }
    readonly property var st: Backend.status
    readonly property bool browsing: Backend.snapshot !== ""
    Connections { target: Backend
        function onFailed(msg) { toast.say(msg, true) }
        function onSaid(msg) { toast.say(msg, false) } }

    islands: [
        Island { anchors { right: parent.right; rightMargin: 12 } y: 12
            Seg { icon: "disc"; text: Backend.dest === "" && !demo ? "Choose a drive" : Backend.destName; onClicked: win.sheet = { kind: "drive", why: "" } }
            IslandGap {}
            Label { leftPadding: 6; anchors.verticalCenter: parent.verticalCenter; secondary: true; font.pixelSize: 12; text: "By itself:" }
            Repeater { model: [["off", "Never"], ["daily", "Daily"], ["weekly", "Weekly"]]
                Seg { required property var modelData; text: modelData[1]; on: Backend.schedule === modelData[0]; onClicked: Backend.setSchedule(modelData[0]) } } },
        Rectangle {   // the timeline
            id: line; anchors { horizontalCenter: parent.horizontalCenter; bottom: parent.bottom; bottomMargin: 14 } width: parent.width - 28; height: 86; radius: 16
            color: Theme.t.island; border.width: 1; border.color: Theme.t.islandLine
            Label { visible: Backend.history.length === 0; anchors.centerIn: parent; secondary: true; text: "Every backup will show here, newest first. Click one to bring files back from it." }
            Rectangle { visible: Backend.history.length > 1; x: 40; y: 23; width: Math.min(parent.width - 80, Backend.history.length * 118 - 60); height: 2; color: Theme.t.islandLine }
            ListView { anchors { fill: parent; margins: 6 } orientation: ListView.Horizontal; clip: true; model: Backend.history
                delegate: Pressable { required property var modelData; required property int index; width: 118; height: 74; radius: 12
                    color: Backend.snapshot === modelData.path ? Qt.rgba(win.tintColor.r, win.tintColor.g, win.tintColor.b, 0.2) : (hovered ? Theme.t.hover : "transparent"); onClicked: Backend.openSnapshot(modelData.path)
                    Rectangle { y: 11; anchors.horizontalCenter: parent.horizontalCenter; width: 14; height: 14; radius: 7; color: index === 0 ? Theme.t.accent : Theme.t.menu_bg; border.width: 2; border.color: Theme.t.accent }
                    Label { y: 32; anchors.horizontalCenter: parent.horizontalCenter; text: modelData.day; font.pixelSize: 12; font.weight: Font.Medium }
                    Label { y: 50; anchors.horizontalCenter: parent.horizontalCenter; text: modelData.time + " · " + modelData.new + " new"; font.pixelSize: 10; secondary: true } } } },
        Toast { id: toast; anchors { horizontalCenter: parent.horizontalCenter; bottom: line.top; bottomMargin: 8 } },
        Item { anchors.fill: parent; z: 20; visible: win.sheet !== null
            Rectangle { anchors.fill: parent; radius: win.r; color: "#66000000"; MouseArea { anchors.fill: parent; acceptedButtons: Qt.AllButtons } }
            Rectangle { anchors.centerIn: parent; width: 460; height: 232 + Math.max(1, Backend.drives.length) * 40; radius: 16; color: Theme.t.menu_bg; border.width: 1; border.color: Theme.t.menu_border
                Label { x: 22; y: 20; font.pixelSize: 16; font.weight: Font.DemiBold; text: "Where should backups go?" }
                Column { x: 16; y: 54; width: parent.width - 32
                    Label { visible: Backend.drives.length === 0; x: 6; height: 40; width: parent.width - 12; wrapMode: Text.WordWrap; verticalAlignment: Text.AlignVCenter; secondary: true; font.pixelSize: 12
                        text: "No drive is plugged in. Plug one in, or connect to a server in Files, and it will show here." }
                    Repeater { model: Backend.drives
                        Pressable { required property var modelData; width: parent.width; height: 40; radius: 10; color: modelData.chosen ? Qt.rgba(win.tintColor.r, win.tintColor.g, win.tintColor.b, 0.2) : (hovered ? Theme.t.hover : "transparent")
                            onClicked: { var why = Backend.choose(modelData.path); if (why === "") win.sheet = null; else win.sheet = { kind: "drive", why: why } }
                            Glyph { x: 10; anchors.verticalCenter: parent.verticalCenter; name: "disc"; size: 16; ink: modelData.chosen ? Theme.t.accent : Theme.t.icon }
                            Label { x: 38; anchors.verticalCenter: parent.verticalCenter; text: modelData.name; font.weight: Font.Medium }
                            Label { anchors { right: parent.right; rightMargin: 10; verticalCenter: parent.verticalCenter } text: modelData.free; secondary: true; font.pixelSize: 12 } } } }
                Column { x: 22; anchors { bottom: parent.bottom; bottomMargin: 62 } spacing: 6; width: parent.width - 44
                    Label { secondary: true; font.pixelSize: 12; text: "Or a folder's path:" }
                    TextBox { id: pathBox; width: parent.width; placeholder: "/media/you/Drive/Backups"; onAccepted: { var why = Backend.choose(text); if (why === "") { win.sheet = null; text = "" } else win.sheet = { kind: "drive", why: why } } }
                    Label { width: parent.width; elide: Text.ElideRight; font.pixelSize: 12; color: win.sheet && win.sheet.why ? Theme.t.danger : Theme.t.text_secondary
                        text: win.sheet && win.sheet.why ? win.sheet.why : "Keeps the newest " + Backend.keep + " backups; older ones make room." } }
                Btn { anchors { right: parent.right; rightMargin: 22; bottom: parent.bottom; bottomMargin: 18 } text: "Done"; onClicked: win.sheet = null } } }
    ]

    // ---------------- the dial
    Column { visible: !win.browsing; anchors.horizontalCenter: parent.horizontalCenter; y: 84; spacing: 12
        Item { width: 190; height: 190; anchors.horizontalCenter: parent.horizontalCenter
            Ring { anchors.fill: parent; thickness: 11; value: Backend.busy ? Math.max(0.03, Backend.progress) : (win.st.state === "ok" ? 1 : win.st.state === "old" ? 0.5 : 0)
                ink: win.st.state === "error" || win.st.state === "old" ? Theme.t.danger : Theme.t.accent }
            Glyph { anchors.centerIn: parent; size: 62; name: Backend.busy ? "history" : win.st.state === "ok" ? "shield" : "disc"
                ink: win.st.state === "ok" || Backend.busy ? Theme.t.accent : Theme.t.text_secondary } }
        Label { anchors.horizontalCenter: parent.horizontalCenter; font.pixelSize: 26; font.weight: Font.DemiBold; text: Backend.busy ? Math.round(Backend.progress * 100) + "%" : (win.st.title || "") }
        Label { anchors.horizontalCenter: parent.horizontalCenter; width: Math.min(560, win.width - 80); horizontalAlignment: Text.AlignHCenter; wrapMode: Text.WordWrap; secondary: true
            color: win.st.state === "error" ? Theme.t.danger : Theme.t.text_secondary; text: Backend.busy ? Backend.doing : (win.st.detail || "") }
        Item { width: 1; height: 4 }
        Row { anchors.horizontalCenter: parent.horizontalCenter; spacing: 8
            Btn { visible: !Backend.busy && (Backend.dest !== "" || demo); primary: true; text: "Back Up Now"; opacity: Backend.connected ? 1 : 0.5; onClicked: Backend.backUpNow() }
            Btn { visible: !Backend.busy && Backend.dest === "" && !demo; primary: true; text: "Choose a Drive"; onClicked: win.sheet = { kind: "drive", why: "" } }
            Btn { visible: Backend.busy; text: "Stop"; onClicked: Backend.stop() } }
        Label { anchors.horizontalCenter: parent.horizontalCenter; secondary: true; font.pixelSize: 11; text: "Everything in Home is kept, except caches and the Trash. Only what changed is copied each time." }
    }

    // ---------------- going back: what one backup holds
    Rectangle { visible: win.browsing; x: 14; y: 62; width: parent.width - 28; height: parent.height - 62 - 110; radius: 16; color: Theme.t.island; border.width: 1; border.color: Theme.t.islandLine
        Row { x: 10; y: 8; height: 34; spacing: 2
            Seg { anchors.verticalCenter: undefined; icon: "back"; tip: "Back"; onClicked: Backend.up() }
            Repeater { model: Backend.crumbs
                Row { required property var modelData; required property int index; spacing: 2
                    Label { visible: index > 0; text: "›"; secondary: true; y: 7 }
                    Seg { anchors.verticalCenter: undefined; text: modelData.name; onClicked: Backend.openFolder(modelData.rel) } } } }
        Label { anchors { right: parent.right; rightMargin: 16 } y: 16; secondary: true; font.pixelSize: 12; text: Backend.busy ? Backend.doing : "Bringing something back never replaces what you have now." }
        ListView { x: 6; y: 48; width: parent.width - 12; height: parent.height - 54; clip: true; model: Backend.files
            delegate: Pressable { id: rowItem; required property var modelData; width: ListView.view.width; height: 36; radius: 9; opacity: modelData.hidden ? 0.6 : 1
                onClicked: if (modelData.dir) Backend.openFolder(modelData.rel)
                Glyph { x: 12; anchors.verticalCenter: parent.verticalCenter; name: modelData.dir ? "folder" : "file"; ink: modelData.dir ? Theme.t.accent : Theme.t.icon }
                Label { x: 44; width: parent.width - 260; elide: Text.ElideMiddle; anchors.verticalCenter: parent.verticalCenter; text: modelData.name }
                Label { anchors { right: parent.right; rightMargin: 120; verticalCenter: parent.verticalCenter } text: modelData.size; secondary: true; font.pixelSize: 12 }
                Btn { visible: rowItem.hovered || hovered; anchors { right: parent.right; rightMargin: 8; verticalCenter: parent.verticalCenter } height: 26; text: "Bring Back"; onClicked: Backend.restore(modelData.rel) } }
            Label { visible: Backend.files.length === 0; anchors.centerIn: parent; secondary: true; text: "This folder was empty" } } }
}
