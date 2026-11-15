import QtQuick

// Install Huginn OS. A rail of steps down the left (done ones can be gone back to), the step itself on the right with
// a big plain heading, and Back / Continue in an island at the bottom. Nothing is touched until Ready, where
// everything is shown once more. Then the window becomes the installation: a line of the realm's light filling,
// what it's doing, and the apps waiting on the other side; at the end, Restart.
GlassWindow {
    id: win
    title: "Install Huginn OS"; width: 1000; height: 680; minimumWidth: 900; minimumHeight: 620; glow: "left"
    readonly property string stepId: Backend.steps[Backend.step].id
    readonly property bool setup: Backend.state === "setup"
    property string langFilter: ""
    property string layoutFilter: ""
    property string zoneFilter: ""
    property string openWifi: ""
    property bool showLog: false
    property string encOne: ""
    property string encTwo: ""
    Connections { target: Backend; function onSaid(text, bad) { toast.say(text, bad) } }
    function pushEncryption() { Backend.setEncrypt(Backend.encrypt, win.encOne === win.encTwo ? win.encOne : "") }

    Item {
        anchors.fill: parent

        // ============================================================ the rail of steps
        Column {
            id: rail
            visible: win.setup
            x: 30; y: 70; width: 200; spacing: 6
            Row { spacing: 12; bottomPadding: 24
                Image { width: 40; height: 40; source: osLogo; sourceSize: Qt.size(80, 80); visible: osLogo !== ""; smooth: true; mipmap: true }
                Column { anchors.verticalCenter: parent.verticalCenter
                    Label { text: "Huginn OS"; font.pixelSize: 15; font.weight: Font.DemiBold }
                    Label { text: "Installer"; secondary: true; font.pixelSize: 12 } } }
            Repeater { model: Backend.steps
                Rectangle { required property var modelData; required property int index
                    objectName: "rail-" + modelData.id
                    readonly property bool here: index === Backend.step
                    readonly property bool done: index < Backend.step
                    width: 200; height: 36; radius: 12
                    color: here ? Theme.t.hover : (railHit.containsMouse && done ? Theme.t.hover : "transparent")
                    Row { x: 10; anchors.verticalCenter: parent.verticalCenter; spacing: 12
                        Rectangle { width: 22; height: 22; radius: 11; anchors.verticalCenter: parent.verticalCenter
                            color: parent.parent.done ? Theme.t.accent : "transparent"
                            border.width: parent.parent.done ? 0 : 1.5; border.color: parent.parent.here ? Theme.t.accent : Theme.t.separator
                            Glyph { visible: parent.parent.parent.done; anchors.centerIn: parent; name: "check"; size: 13; ink: Theme.t.onAccent }
                            Rectangle { visible: parent.parent.parent.here; anchors.centerIn: parent; width: 8; height: 8; radius: 4; color: Theme.t.accent } }
                        Label { text: modelData.label; anchors.verticalCenter: parent.verticalCenter; secondary: !parent.parent.here && !parent.parent.done
                            font.weight: parent.parent.here ? Font.DemiBold : Font.Normal } }
                    MouseArea { id: railHit; anchors.fill: parent; hoverEnabled: true; enabled: parent.done; cursorShape: parent.done ? Qt.PointingHandCursor : Qt.ArrowCursor
                        onClicked: Backend.goTo(index) } } }
        }
        Rectangle { visible: win.setup; x: 252; y: 30; width: 1; height: parent.height - 60; color: Theme.t.separator }

        // ============================================================ the step
        Item {
            id: page
            visible: win.setup
            x: 286; y: 40; width: parent.width - x - 40; height: parent.height - y - 84
            readonly property var headings: ({
                welcome: ["Welcome to Huginn OS", "Choose your language. Then try Huginn OS first, or install it now."],
                keyboard: ["Keyboard", "Pick the layout printed on your keys, then try it below."],
                network: ["Connect to the internet", "Not needed to install. With it, the clock is set right away."],
                disk: ["Where should Huginn OS go?", "Nothing changes until you press Install."],
                you: ["Who will use this computer?", "You can add more people later in Settings › Users."],
                time: ["Time zone", "The clock and calendar follow it. It changes by itself when you travel, if you like, later."],
                ready: ["Ready to install", "Look this over. Installing takes about ten minutes."] })
            Label { id: heading; objectName: "heading"; text: page.headings[win.stepId][0]; font.pixelSize: 30; font.weight: Font.Light }
            Label { id: subheading; anchors { top: heading.bottom; topMargin: 6 } width: parent.width; text: page.headings[win.stepId][1]; secondary: true; font.pixelSize: 14; wrapMode: Text.WordWrap }
            Item { id: body; anchors { top: subheading.bottom; topMargin: 22; left: parent.left; right: parent.right; bottom: parent.bottom }

                // ---------------------------------------------------- welcome
                Item { visible: win.stepId === "welcome"; anchors.fill: parent
                    TextBox { id: langSearch; width: parent.width; placeholder: "Search languages"; onEdited: win.langFilter = text.toLowerCase() }
                    Rectangle { anchors { top: langSearch.bottom; topMargin: 10; left: parent.left; right: parent.right; bottom: choices.top; bottomMargin: 18 }
                        radius: 14; color: Theme.t.group; border.width: 1; border.color: Theme.t.islandLine; clip: true
                        ListView { id: langList; anchors.fill: parent; anchors.margins: 6; spacing: 2; clip: true
                            Connections { target: Backend; function onChanged() { var i = langList.model.findIndex(function (l) { return l.id === Backend.language }); if (i >= 0) langList.positionViewAtIndex(i, ListView.Contain) } }
                            model: Backend.languages.filter(function (l) { return !win.langFilter || l.label.toLowerCase().indexOf(win.langFilter) >= 0 || l.id.toLowerCase().indexOf(win.langFilter) >= 0 })
                            delegate: Rectangle { required property var modelData; width: langList.width; height: 36; radius: 10
                                objectName: "lang-" + modelData.id
                                color: modelData.id === Backend.language ? Theme.t.accent : (lh.containsMouse ? Theme.t.hover : "transparent")
                                Label { x: 14; anchors.verticalCenter: parent.verticalCenter; text: modelData.label; color: modelData.id === Backend.language ? Theme.t.onAccent : Theme.t.text
                                    font.weight: modelData.id === Backend.language ? Font.DemiBold : Font.Normal }
                                MouseArea { id: lh; anchors.fill: parent; hoverEnabled: true; onClicked: Backend.setLanguage(modelData.id) } } } }
                    Row { id: choices; anchors.bottom: parent.bottom; width: parent.width; spacing: 14
                        Repeater { model: [{ id: "try", glyph: "eye", title: "Try Huginn OS", line: "Nothing on this computer changes. Install any time from the dock." },
                                           { id: "install", glyph: "download", title: "Install Huginn OS", line: "Put it on this computer, beside what's there or instead of it." }]
                            Rectangle { required property var modelData
                                objectName: "choose-" + modelData.id
                                width: (choices.width - 14) / 2; height: 96; radius: 18
                                color: modelData.id === "install" ? Qt.rgba(Theme.t.accent.r, Theme.t.accent.g, Theme.t.accent.b, ch.containsMouse ? 0.26 : 0.18) : (ch.containsMouse ? Theme.t.hover : Theme.t.group)
                                border.width: 1; border.color: modelData.id === "install" ? Theme.t.accent : Theme.t.islandLine
                                Row { x: 18; anchors.verticalCenter: parent.verticalCenter; spacing: 14
                                    Rectangle { width: 44; height: 44; radius: 14; anchors.verticalCenter: parent.verticalCenter
                                        color: modelData.id === "install" ? Theme.t.accent : Theme.t.hover
                                        Glyph { anchors.centerIn: parent; name: modelData.glyph; size: 22; ink: modelData.id === "install" ? Theme.t.onAccent : Theme.t.icon } }
                                    Column { width: parent.parent.width - 100; anchors.verticalCenter: parent.verticalCenter; spacing: 3
                                        Label { text: modelData.title; font.pixelSize: 16; font.weight: Font.DemiBold }
                                        Label { width: parent.width; text: modelData.line; secondary: true; wrapMode: Text.WordWrap; font.pixelSize: 12 } } }
                                MouseArea { id: ch; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor
                                    onClicked: modelData.id === "try" ? Qt.quit() : Backend.next() } } } }
                }

                // ---------------------------------------------------- keyboard
                Item { visible: win.stepId === "keyboard"; anchors.fill: parent
                    TextBox { id: laySearch; width: parent.width; placeholder: "Search layouts"; onEdited: win.layoutFilter = text.toLowerCase() }
                    Rectangle { anchors { top: laySearch.bottom; topMargin: 10; left: parent.left; right: parent.right; bottom: tryIt.top; bottomMargin: 16 }
                        radius: 14; color: Theme.t.group; border.width: 1; border.color: Theme.t.islandLine; clip: true
                        ListView { id: layList; anchors.fill: parent; anchors.margins: 6; spacing: 2; clip: true
                            model: Backend.layouts.filter(function (l) { return !win.layoutFilter || l.label.toLowerCase().indexOf(win.layoutFilter) >= 0 || l.id === win.layoutFilter })
                            Component.onCompleted: positionViewAtIndex(Math.max(0, model.findIndex(function (l) { return l.id === Backend.layout })), ListView.Center)
                            delegate: Rectangle { required property var modelData; width: layList.width; height: 36; radius: 10
                                color: modelData.id === Backend.layout ? Theme.t.accent : (kh.containsMouse ? Theme.t.hover : "transparent")
                                Label { x: 14; anchors.verticalCenter: parent.verticalCenter; text: modelData.label; color: modelData.id === Backend.layout ? Theme.t.onAccent : Theme.t.text
                                    font.weight: modelData.id === Backend.layout ? Font.DemiBold : Font.Normal }
                                Label { anchors { right: parent.right; rightMargin: 14; verticalCenter: parent.verticalCenter } text: modelData.id; font.family: Theme.t.fontMono; font.pixelSize: 11
                                    color: modelData.id === Backend.layout ? Theme.t.onAccent : Theme.t.text_secondary }
                                MouseArea { id: kh; anchors.fill: parent; hoverEnabled: true; onClicked: Backend.setLayout(modelData.id) } } } }
                    Column { id: tryIt; anchors.bottom: parent.bottom; width: parent.width; spacing: 6
                        Label { text: "Try it"; secondary: true; font.pixelSize: 12 }
                        TextBox { objectName: "tryKeys"; width: parent.width; placeholder: "Type here: æøå, äöü, @, € and the rest" } }
                }

                // ---------------------------------------------------- network
                Item { visible: win.stepId === "network"; anchors.fill: parent
                    Column { width: parent.width; spacing: 10
                        Rectangle { visible: !!Backend.wifi.wired; width: parent.width; height: 52; radius: 14; color: Theme.t.group; border.width: 1; border.color: Theme.t.islandLine
                            Row { x: 16; anchors.verticalCenter: parent.verticalCenter; spacing: 12
                                Glyph { name: "check"; size: 18; ink: Theme.t.accent; anchors.verticalCenter: parent.verticalCenter }
                                Label { text: "Connected by cable"; anchors.verticalCenter: parent.verticalCenter; font.weight: Font.DemiBold } } }
                        Rectangle { width: parent.width; height: Math.min(wifiCol.height + 12, body.height - (Backend.wifi.wired ? 62 : 0)); radius: 14; color: Theme.t.group
                            border.width: 1; border.color: Theme.t.islandLine; clip: true
                            Flickable { anchors.fill: parent; anchors.margins: 6; contentHeight: wifiCol.height; clip: true
                                Column { id: wifiCol; width: parent.width; spacing: 2
                                    Label { visible: !(Backend.wifi.networks || []).length; x: 10; topPadding: 12; bottomPadding: 12
                                        text: Backend.wifi.available === false ? "This computer has no Wi‑Fi." : "Looking for Wi‑Fi networks…"; secondary: true }
                                    Repeater { model: Backend.wifi.networks || []
                                        Rectangle { required property var modelData; width: wifiCol.width; radius: 10
                                            objectName: "wifi-" + modelData.ssid
                                            readonly property bool open: win.openWifi === modelData.ssid
                                            height: open ? 92 : 40
                                            color: wh.containsMouse || open ? Theme.t.hover : "transparent"
                                            Behavior on height { NumberAnimation { duration: 140 } }
                                            Row { x: 12; y: 8; spacing: 12
                                                Glyph { name: "wifi"; size: 18; opacity: 0.35 + modelData.signal / 150; anchors.verticalCenter: parent.verticalCenter }
                                                Label { text: modelData.ssid; anchors.verticalCenter: parent.verticalCenter; font.weight: modelData.ssid === Backend.wifi.connected ? Font.DemiBold : Font.Normal }
                                                Glyph { visible: modelData.secure; name: "lock"; size: 13; opacity: 0.6; anchors.verticalCenter: parent.verticalCenter } }
                                            Label { visible: modelData.ssid === Backend.wifi.connected; anchors { right: parent.right; rightMargin: 14; top: parent.top; topMargin: 11 } text: "Connected"; color: Theme.t.accent; font.pixelSize: 12 }
                                            MouseArea { id: wh; width: parent.width; height: 40; hoverEnabled: true; cursorShape: Qt.PointingHandCursor
                                                onClicked: { if (modelData.ssid === Backend.wifi.connected) return
                                                    if (modelData.secure) { win.openWifi = parent.open ? "" : modelData.ssid; if (win.openWifi) Qt.callLater(function () { wifiPass.focusIn() }) }
                                                    else Backend.connectWifi(modelData.ssid, "") } }
                                            Row { visible: parent.open; x: 42; y: 46; spacing: 8
                                                TextBox { id: wifiPass; width: 280; secret: true; placeholder: "Password for " + modelData.ssid; onAccepted: { Backend.connectWifi(modelData.ssid, text); text = ""; win.openWifi = "" } }
                                                Btn { primary: true; text: "Join"; anchors.verticalCenter: parent.verticalCenter; onClicked: { Backend.connectWifi(modelData.ssid, wifiPass.text); wifiPass.text = ""; win.openWifi = "" } } } } } } } }
                        Row { spacing: 8
                            Btn { text: "Look again"; onClicked: Backend.refreshWifi() } } }
                }

                // ---------------------------------------------------- disk
                Flickable { visible: win.stepId === "disk"; anchors.fill: parent; contentHeight: diskCol.height + 10; clip: true
                    Column { id: diskCol; width: parent.width; spacing: 14
                        // the disks, when there's more than one
                        Flow { visible: Backend.disks.length > 1; width: parent.width; spacing: 8
                            Repeater { model: Backend.disks
                                Rectangle { required property var modelData
                                    objectName: "disk-" + modelData.path
                                    width: dRow.width + 26; height: 40; radius: 12
                                    color: modelData.path === Backend.disk ? Qt.rgba(Theme.t.accent.r, Theme.t.accent.g, Theme.t.accent.b, 0.2) : (dh.containsMouse ? Theme.t.hover : Theme.t.group)
                                    border.width: 1; border.color: modelData.path === Backend.disk ? Theme.t.accent : Theme.t.islandLine
                                    Row { id: dRow; anchors.centerIn: parent; spacing: 8
                                        Glyph { name: modelData.removable ? "download" : "disc"; size: 16; anchors.verticalCenter: parent.verticalCenter }
                                        Label { text: modelData.model; font.weight: Font.DemiBold; anchors.verticalCenter: parent.verticalCenter }
                                        Label { text: modelData.sizeText; secondary: true; anchors.verticalCenter: parent.verticalCenter } }
                                    MouseArea { id: dh; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: Backend.setDisk(modelData.path) } } } }
                        Label { visible: Backend.disks.length === 0; text: "No disk was found to put Huginn OS on."; color: Theme.t.danger }
                        // the disk as it will be: a bar of what's on it, with Huginn OS where it would go
                        Column { visible: !!Backend.chosenDisk.path; width: parent.width; spacing: 6
                            Row { spacing: 8
                                Label { text: Backend.chosenDisk.model || ""; font.weight: Font.DemiBold }
                                Label { text: (Backend.chosenDisk.sizeText || "") + " · " + (Backend.chosenDisk.kind || "") + (Backend.chosenDisk.systems && Backend.chosenDisk.systems.length ? " · has " + Backend.chosenDisk.systems.join(" and ") : ""); secondary: true } }
                            Rectangle { objectName: "diskBar"; width: parent.width; height: 34; radius: 10; color: Theme.t.group; border.width: 1; border.color: Theme.t.islandLine; clip: true
                                Row { anchors.fill: parent; anchors.margins: 3; spacing: 2
                                    Repeater { model: Backend.mode === "erase" ? [{ label: "Huginn OS", holds: "Huginn", share: 1, sizeText: Backend.chosenDisk.sizeText }] : (Backend.chosenDisk.bar || [])
                                        Rectangle { required property var modelData
                                            readonly property bool ours: modelData.holds === "Huginn" || (modelData.free && Backend.mode === "free") || (Backend.mode === "manual" && modelData.label === Backend.root)
                                            width: Math.max(6, (parent.width - 2 * ((Backend.chosenDisk.bar || []).length)) * modelData.share); height: parent.height; radius: 7
                                            color: ours ? Theme.t.accent : modelData.free ? "transparent" : ({ Windows: "#2F6FDB", Linux: "#E8833A", EFI: "#6B7280", macOS: "#A3A3A3" }[modelData.holds] || "#4B5563")
                                            border.width: modelData.free && !ours ? 1 : 0; border.color: Theme.t.separator
                                            Label { anchors.centerIn: parent; visible: parent.width > 90; text: (parent.ours ? "Huginn OS" : modelData.label) + "  " + modelData.sizeText; font.pixelSize: 11
                                                color: parent.ours ? Theme.t.onAccent : "#FFFFFF"; font.weight: Font.DemiBold } } } } } }
                        // how to use it
                        Repeater {
                            model: [{ id: "erase", glyph: "trash", title: "Erase the disk and install Huginn OS",
                                      line: "Everything on " + (Backend.chosenDisk.model || "the disk") + " is deleted" + (Backend.chosenDisk.systems && Backend.chosenDisk.systems.length ? ", " + Backend.chosenDisk.systems.join(" and ") + " too." : "."), ok: true },
                                    { id: "free", glyph: "split", title: Backend.chosenDisk.systems && Backend.chosenDisk.systems.length ? "Install beside " + Backend.chosenDisk.systems.join(" and ") : "Use the free space",
                                      line: !Backend.chosenDisk.freeBytes ? "There's no free space on this disk. Make room first (Windows: Disk Management › Shrink Volume)."
                                          : Backend.chosenDisk.systems && Backend.chosenDisk.systems.length ? Backend.chosenDisk.freeText + " of free space. You'll choose which system to start each time the computer starts."
                                          : Backend.chosenDisk.freeText + " of free space. What's already on the disk stays as it is.",
                                      ok: (Backend.chosenDisk.freeBytes || 0) >= 20e9 },
                                    { id: "manual", glyph: "sliders", title: "Choose partitions myself", line: "For people who've already made room: pick the partition for Huginn OS.", ok: true }]
                            Rectangle { required property var modelData
                                objectName: "mode-" + modelData.id
                                readonly property bool on: Backend.mode === modelData.id
                                // an empty disk: "use the free space" would be the same as erasing it
                                visible: !(modelData.id === "free" && !(Backend.chosenDisk.parts && Backend.chosenDisk.parts.length))
                                width: diskCol.width; height: 64; radius: 16; opacity: modelData.ok ? 1 : 0.5
                                color: on ? Qt.rgba(Theme.t.accent.r, Theme.t.accent.g, Theme.t.accent.b, 0.16) : (mh.containsMouse ? Theme.t.hover : Theme.t.group)
                                border.width: 1; border.color: on ? Theme.t.accent : Theme.t.islandLine
                                Row { x: 16; anchors.verticalCenter: parent.verticalCenter; spacing: 14
                                    Rectangle { width: 20; height: 20; radius: 10; anchors.verticalCenter: parent.verticalCenter; color: "transparent"; border.width: parent.parent.on ? 6 : 1.5; border.color: parent.parent.on ? Theme.t.accent : Theme.t.separator }
                                    Glyph { name: modelData.glyph; size: 20; anchors.verticalCenter: parent.verticalCenter }
                                    Column { anchors.verticalCenter: parent.verticalCenter; spacing: 2; width: diskCol.width - 110
                                        Label { text: modelData.title; font.weight: Font.DemiBold }
                                        Label { width: parent.width; text: modelData.line; secondary: true; font.pixelSize: 12; elide: Text.ElideRight } } }
                                MouseArea { id: mh; anchors.fill: parent; hoverEnabled: true; enabled: modelData.ok; cursorShape: Qt.PointingHandCursor; onClicked: Backend.setMode(modelData.id) } } }
                        // choosing partitions
                        Column { visible: Backend.mode === "manual"; width: parent.width; spacing: 4
                            Repeater { model: Backend.chosenDisk.parts || []
                                Rectangle { required property var modelData; width: diskCol.width; height: 44; radius: 12; color: Theme.t.group; border.width: 1; border.color: Theme.t.islandLine
                                    Row { x: 14; anchors.verticalCenter: parent.verticalCenter; spacing: 12
                                        Label { text: modelData.path; font.family: Theme.t.fontMono; width: 150; anchors.verticalCenter: parent.verticalCenter }
                                        Label { text: modelData.holds + (modelData.label ? " · " + modelData.label : ""); width: 220; elide: Text.ElideRight; anchors.verticalCenter: parent.verticalCenter }
                                        Label { text: modelData.sizeText; secondary: true; width: 70; anchors.verticalCenter: parent.verticalCenter } }
                                    Row { anchors { right: parent.right; rightMargin: 8; verticalCenter: parent.verticalCenter } spacing: 6
                                        Btn { pill: true; primary: Backend.root === modelData.path; text: "Huginn OS"; enabled: modelData.size >= 20e9; onClicked: Backend.setRoot(modelData.path) }
                                        Btn { visible: Backend.firmware === "uefi" && modelData.holds === "EFI"; pill: true; primary: Backend.efi === modelData.path; text: "EFI"; onClicked: Backend.setEfi(modelData.path) } } } }
                            Label { text: "The partition for Huginn OS is formatted. The EFI partition is shared, not formatted."; secondary: true; font.pixelSize: 12 } }
                        // encryption
                        Rectangle { visible: Backend.mode !== "manual"; width: parent.width; height: encCol.height + 24; radius: 16; color: Theme.t.group; border.width: 1; border.color: Theme.t.islandLine
                            Column { id: encCol; x: 16; y: 12; width: parent.width - 32; spacing: 10
                                Item { width: parent.width; height: 40
                                    Row { spacing: 12; anchors.verticalCenter: parent.verticalCenter
                                        Glyph { name: "lock"; size: 20; anchors.verticalCenter: parent.verticalCenter }
                                        Column { Label { text: "Encrypt the disk"; font.weight: Font.DemiBold }
                                            Label { text: "Without its password nobody can read it, even with the disk in another computer."; secondary: true; font.pixelSize: 12 } } }
                                    Toggle { objectName: "encryptToggle"; anchors { right: parent.right; verticalCenter: parent.verticalCenter } on: Backend.encrypt
                                        onToggled: function (v) { Backend.setEncrypt(v, win.encOne === win.encTwo ? win.encOne : "") } } }
                                Row { visible: Backend.encrypt; spacing: 10
                                    TextBox { objectName: "encOne"; width: 220; secret: true; placeholder: "Disk password"; onEdited: { win.encOne = text; win.pushEncryption() } }
                                    TextBox { objectName: "encTwo"; width: 220; secret: true; placeholder: "Again"; onEdited: { win.encTwo = text; win.pushEncryption() } } }
                                Label { visible: Backend.encrypt; width: parent.width; wrapMode: Text.WordWrap; font.pixelSize: 12
                                    color: win.encOne && win.encTwo && win.encOne !== win.encTwo ? Theme.t.danger : Theme.t.text_secondary
                                    text: win.encOne && win.encTwo && win.encOne !== win.encTwo ? "The two aren't the same."
                                        : "It's asked for every time the computer starts. Keep it somewhere safe: without it, nothing on the disk can be recovered." } } }
                    }
                }

                // ---------------------------------------------------- you
                Item { visible: win.stepId === "you"; anchors.fill: parent
                    Rectangle { id: face; width: 96; height: 96; radius: 48
                        gradient: Gradient { orientation: Gradient.Horizontal; GradientStop { position: 0; color: Theme.t.glowA } GradientStop { position: 1; color: Theme.t.glowB } }
                        Rectangle { anchors.fill: parent; anchors.margins: 3; radius: width / 2; color: Qt.darker(Theme.t.accent, 2.6)
                            Label { anchors.centerIn: parent; color: "#FFFFFF"; font.pixelSize: 34; font.weight: Font.DemiBold
                                text: { var n = (Backend.you.realName || "").trim().split(/\s+/); return n[0] ? (n[0][0] + (n.length > 1 ? n[n.length - 1][0] : "")).toUpperCase() : "" } }
                            Glyph { visible: !(Backend.you.realName || "").trim(); anchors.centerIn: parent; name: "user"; size: 40; ink: "#FFFFFF" } } }
                    Grid { anchors { left: face.right; leftMargin: 28; right: parent.right } columns: 2; columnSpacing: 12; rowSpacing: 12
                        property int w: (width - 12) / 2
                        Column { spacing: 5; Label { text: "Your name"; secondary: true; font.pixelSize: 12 }
                            TextBox { objectName: "realName"; width: parent.parent.w; placeholder: "Your full name"; onEdited: Backend.setYou("realName", text) } }
                        Column { spacing: 5; Label { text: "User name"; secondary: true; font.pixelSize: 12 }
                            TextBox { objectName: "userName"; width: parent.parent.w; mono: true; text: Backend.you.name || ""; onEdited: Backend.setYou("name", text) } }
                        Column { spacing: 5; Label { text: "Password"; secondary: true; font.pixelSize: 12 }
                            TextBox { objectName: "password"; width: parent.parent.w; secret: true; onEdited: Backend.setYou("password", text) }
                            Row { spacing: 4; Repeater { model: 4; Rectangle { required property int index; width: (parent.parent.parent.parent.w - 12) / 4; height: 4; radius: 2
                                color: index < (Backend.you.strength || 0) ? ["#EF4444", "#F59E0B", "#84CC16", Theme.t.accent][(Backend.you.strength || 1) - 1] : Theme.t.hover } } } }
                        Column { spacing: 5; Label { text: "Password again"; secondary: true; font.pixelSize: 12 }
                            TextBox { objectName: "again"; width: parent.parent.w; secret: true; onEdited: Backend.setYou("again", text) }
                            Label { text: Backend.you.hasPassword && !Backend.you.same ? "Not the same yet" : ""; color: Theme.t.danger; font.pixelSize: 11 } }
                        Column { spacing: 5; Label { text: "Computer name"; secondary: true; font.pixelSize: 12 }
                            TextBox { objectName: "hostname"; width: parent.parent.w; mono: true; text: Backend.you.hostname || ""; onEdited: Backend.setYou("hostname", text) }
                            Label { text: "How it shows to other computers on the network"; secondary: true; font.pixelSize: 11 } }
                    }
                    Rectangle { anchors { bottom: parent.bottom; left: parent.left; right: parent.right } height: 64; radius: 16; color: Theme.t.group; border.width: 1; border.color: Theme.t.islandLine
                        Row { x: 16; anchors.verticalCenter: parent.verticalCenter; spacing: 12
                            Glyph { name: "key"; size: 20; anchors.verticalCenter: parent.verticalCenter }
                            Column { anchors.verticalCenter: parent.verticalCenter; Label { text: "Sign in by myself"; font.weight: Font.DemiBold }
                                Label { text: "Skip the sign-in screen. Anyone at this computer could use it."; secondary: true; font.pixelSize: 12 } } }
                        Toggle { anchors { right: parent.right; rightMargin: 16; verticalCenter: parent.verticalCenter } on: !!Backend.you.autologin
                            onToggled: function (v) { Backend.setYou("autologin", v ? "true" : "false") } } }
                }

                // ---------------------------------------------------- time zone
                Item { visible: win.stepId === "time"; anchors.fill: parent
                    Rectangle { id: zoneNow; width: parent.width; height: 70; radius: 16; color: Qt.rgba(Theme.t.accent.r, Theme.t.accent.g, Theme.t.accent.b, 0.14); border.width: 1; border.color: Theme.t.accent
                        Row { x: 18; anchors.verticalCenter: parent.verticalCenter; spacing: 14
                            Glyph { name: "globe"; size: 26; ink: Theme.t.accent; anchors.verticalCenter: parent.verticalCenter }
                            Column { anchors.verticalCenter: parent.verticalCenter; Label { text: Backend.zoneLabel; font.pixelSize: 17; font.weight: Font.DemiBold }
                                Label { text: Backend.zone; font.family: Theme.t.fontMono; secondary: true; font.pixelSize: 12 } } } }
                    TextBox { id: zoneSearch; anchors { top: zoneNow.bottom; topMargin: 14 } width: parent.width; placeholder: "Search for a city"; onEdited: win.zoneFilter = text.toLowerCase() }
                    Rectangle { anchors { top: zoneSearch.bottom; topMargin: 10; left: parent.left; right: parent.right; bottom: parent.bottom }
                        radius: 14; color: Theme.t.group; border.width: 1; border.color: Theme.t.islandLine; clip: true
                        ListView { id: zoneList; anchors.fill: parent; anchors.margins: 6; spacing: 2; clip: true
                            model: Backend.zones.filter(function (z) { return !win.zoneFilter || z.city.toLowerCase().indexOf(win.zoneFilter) >= 0 || z.region.toLowerCase().indexOf(win.zoneFilter) >= 0 })
                            delegate: Rectangle { required property var modelData; width: zoneList.width; height: 34; radius: 10
                                objectName: "zone-" + modelData.id
                                color: modelData.id === Backend.zone ? Theme.t.accent : (zh.containsMouse ? Theme.t.hover : "transparent")
                                Label { x: 14; anchors.verticalCenter: parent.verticalCenter; text: modelData.city; color: modelData.id === Backend.zone ? Theme.t.onAccent : Theme.t.text }
                                Label { anchors { right: parent.right; rightMargin: 14; verticalCenter: parent.verticalCenter } text: modelData.region; font.pixelSize: 12
                                    color: modelData.id === Backend.zone ? Theme.t.onAccent : Theme.t.text_secondary }
                                MouseArea { id: zh; anchors.fill: parent; hoverEnabled: true; onClicked: Backend.setZone(modelData.id) } } } }
                }

                // ---------------------------------------------------- ready
                Column { visible: win.stepId === "ready"; anchors.fill: parent; spacing: 14
                    Rectangle { width: parent.width; height: sumCol.height + 12; radius: 16; color: Theme.t.group; border.width: 1; border.color: Theme.t.islandLine
                        Column { id: sumCol; y: 6; width: parent.width
                            Repeater { model: Backend.summary
                                Item { required property var modelData; required property int index; width: sumCol.width; height: Math.max(44, val.height + 22)
                                    Rectangle { visible: index > 0; x: 16; width: parent.width - 32; height: 1; color: Theme.t.separator }
                                    Label { x: 18; y: 13; width: 130; text: modelData.label; secondary: true }
                                    Label { id: val; x: 150; y: 13; width: parent.width - 170; text: modelData.value; wrapMode: Text.WordWrap
                                        color: modelData.warn ? Theme.t.danger : Theme.t.text; font.weight: modelData.warn ? Font.DemiBold : Font.Normal } } } } }
                    Label { width: parent.width; wrapMode: Text.WordWrap; secondary: true; font.pixelSize: 12
                        text: Backend.mode === "erase" ? "Pressing Erase and Install deletes everything on the disk. This can't be undone." : "Pressing Install changes the disk as shown. Back up anything important first." }
                }
            }
        }

        // ============================================================ installing, done, or stopped
        Item {
            id: run
            visible: !win.setup
            anchors.fill: parent
            Column {
                anchors.centerIn: parent; width: Math.min(560, parent.width - 120); spacing: 18
                // the state's own mark
                Item { width: 96; height: 96; anchors.horizontalCenter: parent.horizontalCenter
                    Image { anchors.fill: parent; visible: Backend.state === "installing" && osLogo !== ""; source: osLogo; sourceSize: Qt.size(192, 192); smooth: true; mipmap: true }
                    Rectangle { anchors.fill: parent; radius: 48; visible: Backend.state === "done"
                        gradient: Gradient { orientation: Gradient.Horizontal; GradientStop { position: 0; color: Theme.t.glowA } GradientStop { position: 1; color: Theme.t.glowB } }
                        Glyph { anchors.centerIn: parent; name: "check"; size: 44; ink: "#FFFFFF" } }
                    Rectangle { anchors.fill: parent; radius: 48; visible: Backend.state === "error"; color: Qt.rgba(Theme.t.danger.r, Theme.t.danger.g, Theme.t.danger.b, 0.18); border.width: 2; border.color: Theme.t.danger
                        Glyph { anchors.centerIn: parent; name: "x"; size: 40; ink: Theme.t.danger } } }
                Label { objectName: "runTitle"; anchors.horizontalCenter: parent.horizontalCenter; font.pixelSize: 28; font.weight: Font.Light
                    text: Backend.state === "done" ? "Huginn OS is ready" : Backend.state === "error" ? "The installation stopped" : "Installing Huginn OS" }
                Label { anchors.horizontalCenter: parent.horizontalCenter; width: parent.width; horizontalAlignment: Text.AlignHCenter; wrapMode: Text.WordWrap; secondary: Backend.state !== "error"
                    color: Backend.state === "error" ? Theme.t.danger : Theme.t.text_secondary
                    text: Backend.state === "done" ? "Restart the computer, and take out the installation drive when the screen goes dark."
                        : Backend.state === "error" ? Backend.error
                        : (Backend.label || "Starting") }
                // the line of light
                Rectangle { visible: Backend.state === "installing"; objectName: "progressTrack"; width: parent.width; height: 8; radius: 4; color: Theme.t.hover
                    Rectangle { width: Math.max(8, parent.width * Backend.fraction); height: parent.height; radius: 4
                        Behavior on width { NumberAnimation { duration: 400; easing.type: Easing.OutCubic } }
                        gradient: Gradient { orientation: Gradient.Horizontal; GradientStop { position: 0; color: Theme.t.glowA } GradientStop { position: 1; color: Theme.t.glowB } } } }
                Label { visible: Backend.state === "installing"; anchors.horizontalCenter: parent.horizontalCenter; text: Math.round(Backend.fraction * 100) + "%"; secondary: true; font.pixelSize: 12 }
                // what's waiting on the other side
                Rectangle { id: slide; visible: Backend.state === "installing" && !win.showLog; width: parent.width; height: 96; radius: 18; color: Theme.t.group; border.width: 1; border.color: Theme.t.islandLine
                    property int at: 0
                    Timer { running: slide.visible; interval: 6500; repeat: true; onTriggered: { fadeSlide.restart() } }
                    SequentialAnimation { id: fadeSlide
                        NumberAnimation { target: slideRow; property: "opacity"; to: 0; duration: 250 }
                        ScriptAction { script: slide.at = (slide.at + 1) % Math.max(1, Backend.slides.length) }
                        NumberAnimation { target: slideRow; property: "opacity"; to: 1; duration: 350 } }
                    Row { id: slideRow; x: 18; anchors.verticalCenter: parent.verticalCenter; spacing: 16
                        Image { width: 60; height: 60; source: Backend.slides.length ? Backend.slides[slide.at].icon : ""; sourceSize: Qt.size(120, 120); smooth: true; mipmap: true; anchors.verticalCenter: parent.verticalCenter }
                        Column { width: slide.width - 120; anchors.verticalCenter: parent.verticalCenter; spacing: 3
                            Label { text: Backend.slides.length ? Backend.slides[slide.at].name : ""; font.pixelSize: 16; font.weight: Font.DemiBold }
                            Label { width: parent.width; text: Backend.slides.length ? Backend.slides[slide.at].line : ""; secondary: true; wrapMode: Text.WordWrap; font.pixelSize: 13 } } } }
                // the details
                Rectangle { visible: win.showLog || Backend.state === "error"; width: parent.width; height: 150; radius: 14; color: Qt.rgba(0, 0, 0, Theme.t.dark ? 0.3 : 0.06); border.width: 1; border.color: Theme.t.islandLine
                    Flickable { id: logView; anchors.fill: parent; anchors.margins: 10; contentHeight: logText.height; clip: true
                        onContentHeightChanged: contentY = Math.max(0, contentHeight - height)
                        Label { id: logText; width: parent.width; text: Backend.log; font.family: Theme.t.fontMono; font.pixelSize: 11; wrapMode: Text.WrapAnywhere; secondary: true } } }
                Row { anchors.horizontalCenter: parent.horizontalCenter; spacing: 10
                    Btn { visible: Backend.state === "installing"; text: win.showLog ? "Hide Details" : "Show Details"; onClicked: win.showLog = !win.showLog }
                    Btn { visible: Backend.state === "done"; text: "Keep Trying It"; onClicked: Qt.quit() }
                    Btn { visible: Backend.state === "done"; objectName: "restart"; primary: true; text: "Restart Now"; onClicked: Backend.restart() }
                    Btn { visible: Backend.state === "error"; text: "Save the Log"; onClicked: { var f = Backend.saveLog(); toast.say(f ? "Saved to " + f : "Couldn't save it.", !f) } }
                    Btn { visible: Backend.state === "error"; primary: true; text: "Back to the Summary"; onClicked: Backend.retry() } }
            }
        }
    }

    // ============================================================ Back and Continue
    Island {
        visible: win.setup && win.stepId !== "welcome"
        z: 6; anchors { right: parent.right; bottom: parent.bottom; rightMargin: 24; bottomMargin: 18 }
        Seg { objectName: "back"; text: "Back"; icon: "back"; onClicked: Backend.back() }
        Seg { objectName: "continue"; on: true; text: win.stepId === "ready" ? (Backend.mode === "erase" ? "Erase and Install" : "Install") : "Continue"
            danger: false; onClicked: win.stepId === "ready" ? Backend.install() : Backend.next() }
    }
    Label { visible: win.setup && win.stepId !== "welcome" && Backend.problem !== ""; z: 6; objectName: "problem"
        anchors { left: parent.left; leftMargin: 286; bottom: parent.bottom; bottomMargin: 30 } width: parent.width - 286 - 330; elide: Text.ElideRight
        text: Backend.problem; color: Theme.t.text_secondary; font.pixelSize: 12 }
    Toast { id: toast; z: 50; anchors { horizontalCenter: parent.horizontalCenter; bottom: parent.bottom; bottomMargin: 70 } }
}
