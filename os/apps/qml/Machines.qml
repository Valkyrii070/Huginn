import QtQuick
import Huginn.Machines

// Machines, "the hangar": your virtual machines stand side by side as screens in a dark bay, lit from below in
// steel blue. Open one and its screen fills the window inside a bezel; the controls ride above it, and snapshots
// and settings slide in from the right like a service panel.
GlassWindow {
    id: win
    title: "Machines"; heading: Backend.openId !== "" ? (Backend.current.name || "") : ""; glow: "bottom"; width: 1280; height: 820; minimumWidth: 960; minimumHeight: 620
    property string sheet: ""                  // new
    property string panel: ""                  // snapshots | settings
    property var made: ({ iso: "", name: "", memory: 4096, cpus: 2, disk: 40, tpm: false, share: "", kind: "" })
    readonly property var m: Backend.current
    readonly property bool inside: Backend.openId !== ""
    readonly property bool on: m.state === "running" || m.state === "paused" || m.state === "starting" || m.state === "stopping"
    readonly property color steel: Theme.t.accent
    function gb(mb) { return (mb / 1024).toFixed(mb % 1024 ? 1 : 0) + " GB" }
    function osColour(kind, system) {
        var s = (system || "").toLowerCase()
        var named = [["ubuntu", ["#F0702E", "#A8301A"]], ["huginn", ["#43D9B8", "#0E6B5C"]], ["fedora", ["#4C7FD1", "#1F3F80"]], ["debian", ["#E2355E", "#8A0B2E"]],
                     ["mint", ["#7BC74D", "#2F7A2A"]], ["arch", ["#3BA6E0", "#165E88"]], ["pop", ["#48B9C7", "#1B6E7A"]], ["windows", ["#3B9BFF", "#1747C2"]], ["bsd", ["#E0334B", "#8E0E22"]]]
        for (var i = 0; i < named.length; i++) if (s.indexOf(named[i][0]) >= 0) return named[i][1]
        return ({ linux: ["#F28C28", "#B5470F"], windows: ["#3B9BFF", "#1747C2"] })[kind] || ["#8C9AB0", "#3F4B5E"] }
    Connections { target: Backend; function onSaid(msg, bad) { toast.say(msg, bad) } }
    Shortcut { sequence: "Ctrl+N"; onActivated: win.newMachine() }
    function newMachine() { var list = Backend.installers(); isoList.model = list; if (list.length) pickIso(list[0]); win.sheet = "new" }
    function pickIso(i) { var s = Backend.suggest(i.path); made = { iso: i.path, name: i.system, memory: s.memory, cpus: s.cpus, disk: s.disk, tpm: s.tpm, kind: s.kind, share: "" } }

    toolbar: [
        Seg { visible: !win.inside; icon: "plus"; text: "New Machine"; onClicked: win.newMachine() },
        Seg { visible: win.inside; icon: "gear"; tip: "Settings"; on: win.panel === "settings"; onClicked: win.panel = win.panel === "settings" ? "" : "settings" },
        Seg { visible: win.inside; icon: "history"; text: "Snapshots"; on: win.panel === "snapshots"; onClicked: win.panel = win.panel === "snapshots" ? "" : "snapshots" },
        Seg { visible: win.inside && win.on; icon: "keyboard"; tip: "Send Ctrl+Alt+Delete"; onClicked: screen.press("ctrl+alt+delete") },
        Seg { visible: win.inside && win.on; icon: "stop"; text: "Shut Down"; onClicked: Backend.shutDown(Backend.openId) },
        Seg { visible: win.inside && win.on; icon: win.m.state === "paused" ? "play" : "pause"; tip: win.m.state === "paused" ? "Carry on" : "Pause"; onClicked: Backend.pause(Backend.openId) },
        Seg { visible: win.inside; icon: "grid"; tip: "All machines"; onClicked: { win.panel = ""; Backend.close() } }
    ]

    // ================================================================ the bay: every machine
    Flickable { id: bay; objectName: "bay"; visible: !win.inside; x: 12; y: 64; width: parent.width - 24; height: parent.height - 76; contentHeight: bayCol.height + 20; clip: true
        boundsBehavior: Flickable.StopAtBounds
        Column { id: bayCol; width: parent.width; spacing: 16
            Row { spacing: 10; leftPadding: 6
                Rectangle { width: 10; height: 10; radius: 5; anchors.verticalCenter: parent.verticalCenter; color: Backend.limits.kvm ? "#3DDC84" : "#F5B83D" }
                Label { anchors.verticalCenter: parent.verticalCenter; secondary: true; font.pixelSize: 12
                    text: !Backend.limits.qemu ? "QEMU isn't installed: machines can't run." : Backend.limits.kvm ? "Hardware virtualisation is on: machines run at nearly full speed."
                        : "Hardware virtualisation (KVM) isn't available: machines run emulated, which is slow. Turn on VT-x or AMD-V in the computer's firmware." } }
            Flow { id: grid; width: parent.width; spacing: 18
                readonly property real cw: Math.floor((width - spacing * (cols - 1)) / cols)
                readonly property int cols: Math.max(2, Math.floor((width + spacing) / 360))
                Repeater { model: Backend.machines
                    Item { id: card; required property var modelData; width: grid.cw; height: grid.cw * 0.62 + 92
                        readonly property bool live: modelData.state !== "off"
                        // the bezel and the screen
                        Rectangle { id: bezel; width: parent.width; height: parent.width * 0.62; radius: 18; color: "#0B0D11"; border.width: 1; border.color: card.live ? win.steel : "#2A2F38"
                            Rectangle { anchors { fill: parent; margins: 9 } radius: 10; clip: true
                                gradient: Gradient { GradientStop { position: 0; color: win.osColour(card.modelData.kind, card.modelData.system)[0] } GradientStop { position: 1; color: win.osColour(card.modelData.kind, card.modelData.system)[1] } }
                                Image { anchors.fill: parent; source: card.modelData.picture; fillMode: Image.PreserveAspectCrop; asynchronous: true; cache: false; visible: source != "" }
                                Text { visible: card.modelData.picture === ""; anchors.centerIn: parent; text: (card.modelData.system || card.modelData.name).split(" ")[0]; color: "#FFFFFF"; opacity: 0.92
                                    font.pixelSize: Math.max(18, parent.width * 0.09); font.weight: Font.Bold }
                                Rectangle { visible: card.modelData.state === "paused"; anchors.fill: parent; color: "#88000000"
                                    Glyph { anchors.centerIn: parent; name: "pause"; size: 34; ink: "#FFFFFF" } } }
                            Rectangle { anchors { right: parent.right; top: parent.top; margins: 16 } height: 22; width: stateL.width + 18; radius: 11; color: "#CC0B0D11"
                                Row { anchors.centerIn: parent; spacing: 5
                                    Rectangle { width: 7; height: 7; radius: 3.5; anchors.verticalCenter: parent.verticalCenter
                                        color: card.modelData.state === "running" ? "#3DDC84" : card.modelData.state === "paused" ? "#F5B83D" : "#6B7280" }
                                    Text { id: stateL; text: ({ running: "On", paused: "Paused", starting: "Starting", stopping: "Shutting down" })[card.modelData.state] || "Off"; color: "#FFFFFF"; font.pixelSize: 10; font.weight: Font.DemiBold } } }
                            MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: Backend.open(card.modelData.id); onDoubleClicked: Backend.start(card.modelData.id) } }
                        // the stand under it: name and what it is
                        Label { x: 6; y: bezel.height + 12; width: parent.width - 120; elide: Text.ElideRight; text: card.modelData.name; font.pixelSize: 15; font.weight: Font.DemiBold }
                        Label { x: 6; y: bezel.height + 34; width: parent.width - 120; elide: Text.ElideRight; secondary: true; font.pixelSize: 11
                            text: card.modelData.system + "  ·  " + win.gb(card.modelData.memory) + " memory  ·  " + card.modelData.cpus + (card.modelData.cpus === 1 ? " processor" : " processors") }
                        Label { x: 6; y: bezel.height + 52; secondary: true; font.pixelSize: 11; text: card.modelData.when + "  ·  " + card.modelData.diskUsed + " on disk" }
                        Btn { anchors { right: parent.right; rightMargin: 4 } y: bezel.height + 14; primary: !card.live; text: card.live ? "Open" : "Start"
                            onClicked: card.live ? Backend.open(card.modelData.id) : Backend.start(card.modelData.id) } } }
                // a new one
                Pressable { width: grid.cw; height: grid.cw * 0.62; radius: 18; color: hovered ? Theme.t.hover : "transparent"; border.width: 2; border.color: Theme.t.islandLine
                    onClicked: win.newMachine()
                    Column { anchors.centerIn: parent; spacing: 8
                        Rectangle { anchors.horizontalCenter: parent.horizontalCenter; width: 52; height: 52; radius: 26; color: win.steel; Glyph { anchors.centerIn: parent; name: "plus"; size: 22; ink: Theme.t.onAccent } }
                        Label { anchors.horizontalCenter: parent.horizontalCenter; text: "New Machine"; font.weight: Font.DemiBold }
                        Label { anchors.horizontalCenter: parent.horizontalCenter; text: "From an installer (.iso) in Downloads"; secondary: true; font.pixelSize: 11 } } } } } }

    // ================================================================ inside one machine
    Rectangle { id: monitor; objectName: "monitor"; visible: win.inside; x: 12; y: 64; width: parent.width - 24 - (win.panel !== "" ? 312 : 0); height: parent.height - 76
        radius: 20; color: "#07080B"; border.width: 1; border.color: win.on ? Qt.rgba(win.steel.r, win.steel.g, win.steel.b, 0.6) : "#262B33"
        Behavior on width { NumberAnimation { duration: Theme.t.still ? 0 : 160; easing.type: Easing.OutCubic } }
        Image { visible: win.on && !Backend.screen; anchors { fill: parent; margins: 10 } source: visible ? (win.m.picture || "") : ""; fillMode: Image.PreserveAspectFit; cache: false }
        MachineScreen { id: screen; objectName: "screen"; visible: win.on; anchors { fill: parent; margins: 10 } client: Backend.screen; focus: win.on }
        // off: the last picture, dimmed, with a big start button and what the machine is
        Item { visible: !win.on; anchors { fill: parent; margins: 10 }
            Image { anchors.fill: parent; source: win.m.picture || ""; fillMode: Image.PreserveAspectFit; opacity: 0.25; asynchronous: true; cache: false }
            Column { anchors.centerIn: parent; spacing: 16
                Pressable { objectName: "startBtn"; anchors.horizontalCenter: parent.horizontalCenter; width: 112; height: 112; radius: 56; color: win.steel; onClicked: Backend.start(Backend.openId)
                    Glyph { anchors.centerIn: parent; name: "play"; size: 40; ink: Theme.t.onAccent } }
                Label { anchors.horizontalCenter: parent.horizontalCenter; text: win.m.name || ""; font.pixelSize: 20; font.weight: Font.DemiBold; color: "#FFFFFF" }
                Label { anchors.horizontalCenter: parent.horizontalCenter; color: "#9CA3AF"; font.pixelSize: 12
                    text: (win.m.system || "") + "  ·  " + win.gb(win.m.memory || 0) + "  ·  " + (win.m.cpus || 0) + " processors  ·  " + (win.m.disk || 0) + " GB disk" }
                Label { visible: !!win.m.resume; anchors.horizontalCenter: parent.horizontalCenter; color: "#9CA3AF"; font.pixelSize: 12; text: "It'll carry on where it was." } } }
        Label { visible: win.on && !!Backend.screen && !Backend.screen.connected; anchors.centerIn: parent; color: "#9CA3AF"; text: win.m.state === "starting" ? "Starting…" : "Connecting to its screen…" } }

    // ---- snapshots and settings
    Rectangle { id: drawer; objectName: "drawer"; visible: win.inside && win.panel !== ""; x: parent.width - width - 12; y: 64; width: 300; height: parent.height - 76; radius: 18
        color: Theme.t.island; border.width: 1; border.color: Theme.t.islandLine; clip: true
        Flickable { anchors { fill: parent; margins: 16 } contentHeight: dcol.height; clip: true; boundsBehavior: Flickable.StopAtBounds
            Column { id: dcol; width: parent.width; spacing: 10
                // snapshots
                Column { visible: win.panel === "snapshots"; width: parent.width; spacing: 10
                    Label { text: "Snapshots"; font.pixelSize: 16; font.weight: Font.DemiBold }
                    Label { width: parent.width; wrapMode: Text.WordWrap; secondary: true; font.pixelSize: 11
                        text: "A snapshot keeps the machine exactly as it is now" + (win.on ? ", even what's open" : "") + ". Go back to it whenever something goes wrong." }
                    TextBox { id: snapName; width: parent.width; placeholder: "Name, such as “Before the update”"; onAccepted: { Backend.takeSnapshot(Backend.openId, text); text = "" } }
                    Btn { primary: true; width: parent.width; text: "Take a Snapshot"; onClicked: { Backend.takeSnapshot(Backend.openId, snapName.text); snapName.text = "" } }
                    Repeater { model: (win.m.snapshots || []).slice().reverse()
                        Rectangle { required property var modelData; width: dcol.width; height: 64; radius: 12; color: Theme.t.dark ? "#14FFFFFF" : "#0A000000"
                            Glyph { x: 12; anchors.verticalCenter: parent.verticalCenter; name: "history"; size: 16 }
                            Column { x: 38; y: 10; width: parent.width - 48; spacing: 2
                                Label { width: parent.width; elide: Text.ElideRight; text: modelData.name; font.pixelSize: 12; font.weight: Font.DemiBold }
                                Label { text: new Date(modelData.when * 1000).toLocaleString(Qt.locale(), "d MMM, HH:mm"); font.pixelSize: 10; secondary: true } }
                            Row { anchors { right: parent.right; rightMargin: 8; bottom: parent.bottom; bottomMargin: 6 } spacing: 2
                                Seg { text: "Go Back"; onClicked: Backend.restoreSnapshot(Backend.openId, modelData.tag || modelData.name) }
                                Seg { icon: "trash"; danger: true; onClicked: Backend.deleteSnapshot(Backend.openId, modelData.tag || modelData.name) } } } } }
                // settings
                Column { visible: win.panel === "settings"; width: parent.width; spacing: 10
                    Label { text: "Settings"; font.pixelSize: 16; font.weight: Font.DemiBold }
                    Label { visible: win.on; width: parent.width; wrapMode: Text.WordWrap; secondary: true; font.pixelSize: 11; text: "Memory and processors change the next time it starts." }
                    Label { text: "MEMORY  ·  " + win.gb(win.m.memory || 0); font.pixelSize: 10; font.weight: Font.Bold; font.letterSpacing: 1.2; secondary: true }
                    Flow { width: parent.width; spacing: 4
                        Repeater { model: [1024, 2048, 4096, 8192, 16384].filter(function (v) { return v <= Backend.limits.memory * 0.75 })
                            Seg { required property int modelData; anchors.verticalCenter: undefined; text: win.gb(modelData); on: win.m.memory === modelData; onClicked: Backend.setting(Backend.openId, "memory", modelData) } } }
                    Label { text: "PROCESSORS"; font.pixelSize: 10; font.weight: Font.Bold; font.letterSpacing: 1.2; secondary: true }
                    Flow { width: parent.width; spacing: 4
                        Repeater { model: [1, 2, 4, 6, 8, 12, 16].filter(function (v) { return v <= Backend.limits.cpus })
                            Seg { required property int modelData; anchors.verticalCenter: undefined; text: String(modelData); on: win.m.cpus === modelData; onClicked: Backend.setting(Backend.openId, "cpus", modelData) } } }
                    Label { text: "INSTALLER DISC"; font.pixelSize: 10; font.weight: Font.Bold; font.letterSpacing: 1.2; secondary: true }
                    Label { width: parent.width; elide: Text.ElideMiddle; font.pixelSize: 11; text: win.m.iso ? win.m.iso.split("/").pop() : "None"; secondary: !win.m.iso }
                    Row { spacing: 4
                        Seg { anchors.verticalCenter: undefined; visible: !!win.m.iso; text: "Take It Out"; onClicked: Backend.setting(Backend.openId, "iso", "") }
                        Seg { anchors.verticalCenter: undefined; visible: !win.m.installed; text: "It's Installed"; onClicked: Backend.installed(Backend.openId) } }
                    Label { text: "SHARED FOLDER"; font.pixelSize: 10; font.weight: Font.Bold; font.letterSpacing: 1.2; secondary: true; visible: win.m.kind !== "windows" }
                    Label { visible: win.m.kind !== "windows"; width: parent.width; wrapMode: Text.WordWrap; font.pixelSize: 11; secondary: true
                        text: win.m.share ? win.m.share.replace(Backend.limits.home || "", "~") + ". Inside, mount it with: sudo mount -t 9p -o trans=virtio hostshare /mnt" : "None. Share your Public folder to pass files in and out." }
                    Seg { anchors.verticalCenter: undefined; visible: win.m.kind !== "windows"; text: win.m.share ? "Stop Sharing" : "Share Public"
                        onClicked: Backend.setting(Backend.openId, "share", win.m.share ? "" : "public") }
                    Row { spacing: 10; height: 34
                        Toggle { anchors.verticalCenter: parent.verticalCenter; on: win.m.network !== "none"; onToggled: function (v) { Backend.setting(Backend.openId, "network", v ? "nat" : "none") } }
                        Label { anchors.verticalCenter: parent.verticalCenter; text: "Internet"; font.pixelSize: 12 } }
                    Row { spacing: 10; height: 34
                        Toggle { anchors.verticalCenter: parent.verticalCenter; on: win.m.sound !== false; onToggled: function (v) { Backend.setting(Backend.openId, "sound", v) } }
                        Label { anchors.verticalCenter: parent.verticalCenter; text: "Sound"; font.pixelSize: 12 } }
                    Item { width: 1; height: 8 }
                    Btn { visible: win.on; danger: true; width: parent.width; text: "Turn Off Without Asking"; onClicked: Backend.forceOff(Backend.openId) }
                    Btn { visible: !win.on; danger: true; width: parent.width; text: "Delete This Machine"
                        onClicked: { var why = Backend.remove(Backend.openId); if (why) toast.say(why, true); else win.panel = "" } } } } } }

    Toast { id: toast; z: 50; anchors { horizontalCenter: parent.horizontalCenter; bottom: parent.bottom; bottomMargin: 30 } }

    // ================================================================ a new machine
    Item { anchors.fill: parent; z: 40; visible: win.sheet === "new"
        Rectangle { anchors.fill: parent; radius: win.r; color: "#77000000"; MouseArea { anchors.fill: parent; onClicked: win.sheet = "" } }
        Rectangle { anchors.centerIn: parent; width: 720; height: Math.min(win.height - 80, 600); radius: 18; color: Theme.t.menu_bg; border.width: 1; border.color: Theme.t.menu_border
            MouseArea { anchors.fill: parent }
            Label { x: 24; y: 20; text: "A new machine"; font.pixelSize: 18; font.weight: Font.DemiBold }
            Label { x: 24; y: 48; width: 300; wrapMode: Text.WordWrap; secondary: true; font.pixelSize: 12
                text: isoList.count ? "Pick the system to install. Its installer (.iso) goes in the machine like a disc." : "No installers (.iso files) in Downloads. Download one (Ubuntu, Fedora, Windows…) and come back." }
            ListView { id: isoList; x: 16; y: 92; width: 330; height: parent.height - 92 - 70; clip: true; spacing: 4
                delegate: Pressable { required property var modelData; width: isoList.width; height: 56; radius: 12
                    readonly property bool picked: win.made.iso === modelData.path
                    color: picked ? Qt.rgba(win.steel.r, win.steel.g, win.steel.b, 0.2) : hovered ? Theme.t.hover : "transparent"; border.width: picked ? 1 : 0; border.color: win.steel
                    onClicked: win.pickIso(modelData)
                    Rectangle { x: 10; anchors.verticalCenter: parent.verticalCenter; width: 34; height: 34; radius: 9
                        gradient: Gradient { GradientStop { position: 0; color: win.osColour(modelData.kind, modelData.system)[0] } GradientStop { position: 1; color: win.osColour(modelData.kind, modelData.system)[1] } }
                        Text { anchors.centerIn: parent; text: modelData.system.charAt(0); color: "#FFFFFF"; font.pixelSize: 16; font.weight: Font.Bold } }
                    Column { x: 54; anchors.verticalCenter: parent.verticalCenter; width: parent.width - 64
                        Label { width: parent.width; elide: Text.ElideRight; text: modelData.system; font.weight: Font.DemiBold; font.pixelSize: 13 }
                        Label { width: parent.width; elide: Text.ElideMiddle; text: modelData.file + "  ·  " + modelData.size; secondary: true; font.pixelSize: 10 } } } }
            Column { x: 370; y: 92; width: parent.width - 370 - 24; spacing: 10; visible: win.made.iso !== ""
                Label { text: "NAME"; font.pixelSize: 10; font.weight: Font.Bold; font.letterSpacing: 1.2; secondary: true }
                TextBox { id: madeName; width: parent.width; text: win.made.name }
                Label { text: "MEMORY"; font.pixelSize: 10; font.weight: Font.Bold; font.letterSpacing: 1.2; secondary: true }
                Flow { width: parent.width; spacing: 4
                    Repeater { model: [2048, 4096, 8192, 16384].filter(function (v) { return v <= Backend.limits.memory * 0.75 })
                        Seg { required property int modelData; anchors.verticalCenter: undefined; text: win.gb(modelData); on: win.made.memory === modelData
                            onClicked: win.made = Object.assign({}, win.made, { memory: modelData }) } } }
                Label { text: "PROCESSORS"; font.pixelSize: 10; font.weight: Font.Bold; font.letterSpacing: 1.2; secondary: true }
                Flow { width: parent.width; spacing: 4
                    Repeater { model: [1, 2, 4, 8].filter(function (v) { return v <= Backend.limits.cpus })
                        Seg { required property int modelData; anchors.verticalCenter: undefined; text: String(modelData); on: win.made.cpus === modelData
                            onClicked: win.made = Object.assign({}, win.made, { cpus: modelData }) } } }
                Label { text: "DISK"; font.pixelSize: 10; font.weight: Font.Bold; font.letterSpacing: 1.2; secondary: true }
                Flow { width: parent.width; spacing: 4
                    Repeater { model: [20, 40, 64, 80, 128, 256]
                        Seg { required property int modelData; anchors.verticalCenter: undefined; text: modelData + " GB"; on: win.made.disk === modelData
                            onClicked: win.made = Object.assign({}, win.made, { disk: modelData }) } } }
                Label { width: parent.width; wrapMode: Text.WordWrap; secondary: true; font.pixelSize: 11
                    text: "The disk only takes the space it fills." + (win.made.kind === "windows" ? (Backend.limits.tpm ? " Windows 11 gets the secure start-up and TPM it asks for." : " Windows 11 asks for a TPM: install swtpm first.") : "") } }
            Row { anchors { right: parent.right; rightMargin: 20; bottom: parent.bottom; bottomMargin: 18 } spacing: 8
                Btn { text: "Cancel"; onClicked: win.sheet = "" }
                Btn { objectName: "createBtn"; primary: true; text: "Make It and Start"; enabled: win.made.iso !== ""
                    onClicked: { var id = Backend.create(Object.assign({}, win.made, { name: madeName.text })); if (id) { win.sheet = ""; Backend.start(id) } } } } } }
}
