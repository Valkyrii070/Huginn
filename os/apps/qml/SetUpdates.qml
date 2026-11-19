import QtQuick

// Software Update: the state in one big card (up to date, or what's waiting and the button that does it all),
// then what's waiting grouped by where it comes from, then automatic updates and Huginn's own version.
Column {
    id: pg
    width: parent ? parent.width : 600; spacing: 18
    readonly property bool have: typeof Updates !== "undefined"
    readonly property var items: have ? Updates.items : []
    readonly property var visibleItems: items.filter(function (i) { return !i.runtime })
    readonly property int security: items.filter(function (i) { return i.security }).length
    readonly property bool working: have && Updates.phase === "installing"
    readonly property bool checking: have && Updates.phase === "checking"
    property bool allSystem: false
    readonly property var groups: [
        { kind: "system", title: "System", sub: "Ubuntu's packages: the kernel, drivers, the browser engine and every library", glyph: "cpu", tile: "#1E40AF" },
        { kind: "app", title: "Apps", sub: "From Flathub", glyph: "apps", tile: "#0A8071" },
        { kind: "huginn", title: "Huginn", sub: "The browser, from its own repository", glyph: "globe", tile: "#5A3FE0" },
        { kind: "firmware", title: "Firmware", sub: "This computer's own firmware and devices (needs a restart)", glyph: "bolt", tile: "#C46A00" } ]
    Rectangle { width: parent.width; height: 150; radius: Theme.t.radiusCard; color: Theme.t.group; border.width: 1; border.color: Theme.t.separator; clip: true
        Rectangle { x: parent.width - 220; y: -60; width: 300; height: 300; radius: 150; opacity: 0.22
            gradient: Gradient { GradientStop { position: 0; color: pg.visibleItems.length ? "#4C8DFF" : "#27C281" } GradientStop { position: 1; color: "transparent" } } }
        Rectangle { x: 24; width: 72; height: 72; radius: 36; anchors.verticalCenter: parent.verticalCenter
            color: pg.visibleItems.length || pg.working || pg.checking ? Qt.rgba(0.3, 0.55, 1, 0.18) : Qt.rgba(0.15, 0.76, 0.5, 0.18)
            Glyph { anchors.centerIn: parent; name: pg.visibleItems.length || pg.working || pg.checking ? "refresh" : "check"; size: 38; ink: pg.visibleItems.length || pg.working || pg.checking ? "#4C8DFF" : "#27C281"
                // turns the way its arrow points (anticlockwise), and comes to rest upright when the work is done
                RotationAnimation on rotation { id: turning; running: pg.working || pg.checking; loops: Animation.Infinite; from: 360; to: 0; duration: 1400
                    onRunningChanged: if (!running) parent.rotation = 0 } } }
        Column { x: 116; anchors.verticalCenter: parent.verticalCenter; width: parent.width - 116 - 200; spacing: 4
            Label { font.pixelSize: 21; font.weight: Font.Light
                text: !pg.have ? "Software Update isn't available" : pg.checking ? "Looking for updates…" : pg.working ? "Updating…" : pg.visibleItems.length ? pg.visibleItems.length + (pg.visibleItems.length === 1 ? " update is ready" : " updates are ready") : "Everything is up to date" }
            Label { width: parent.width; wrapMode: Text.WordWrap; secondary: true
                text: !pg.have ? "" : pg.working ? Updates.line : pg.visibleItems.length ? (pg.security ? pg.security + " fix" + (pg.security === 1 ? "es a" : "") + " security problem" + (pg.security === 1 ? "" : "s") + ". " : "") + "Last looked " + Updates.checked.toLowerCase() + "." : "Last looked " + Updates.checked.toLowerCase() + "." }
            Meter { visible: pg.working; width: parent.width; value: pg.have ? Updates.progress : 0; fill: "#4C8DFF" } }
        Column { anchors { right: parent.right; rightMargin: 22; verticalCenter: parent.verticalCenter } spacing: 8
            Btn { visible: pg.have && pg.visibleItems.length > 0 && !pg.working; primary: true; text: "Update All"; onClicked: Updates.install("all") }
            Btn { visible: pg.have && !pg.working; text: pg.checking ? "Looking…" : "Check Now"; enabled: !pg.checking; onClicked: Updates.look(true) }
            Btn { visible: pg.working; text: "Stop"; onClicked: Updates.stop() } } }
    Rectangle { visible: pg.have && Updates.restart; width: parent.width; height: 58; radius: Theme.t.radiusCard; color: Qt.rgba(0.96, 0.62, 0.04, 0.16); border.width: 1; border.color: Qt.rgba(0.96, 0.62, 0.04, 0.5)
        Glyph { x: 18; anchors.verticalCenter: parent.verticalCenter; name: "refresh"; size: 20; ink: "#E8A10C" }
        Label { x: 50; anchors.verticalCenter: parent.verticalCenter; text: "Restart to finish updating: the new system parts start being used then." }
        Btn { anchors { right: parent.right; rightMargin: 14; verticalCenter: parent.verticalCenter } text: "Restart"; onClicked: win.confirm("Restart now?", "Save your work first: open apps close.", "Restart", function () { Updates.restartNow() }, false) } }
    Repeater { model: pg.groups
        SetCard { required property var modelData
            readonly property var mine: pg.visibleItems.filter(function (i) { return i.kind === modelData.kind })
            visible: mine.length > 0; title: modelData.title
            SetRow { title: modelData.title + " · " + mine.length + (mine.length === 1 ? " update" : " updates"); sub: modelData.sub; glyph: modelData.glyph; tile: modelData.tile
                Btn { text: "Update"; enabled: !pg.working; onClicked: Updates.install(modelData.kind) } }
            Repeater { model: modelData.kind === "system" && !pg.allSystem ? mine.slice(0, 5) : mine
                SetRow { required property var modelData; title: modelData.name
                    sub: (modelData.from ? modelData.from + " → " : "") + modelData.version + (modelData.note ? " · " + modelData.note : "")
                    Row { spacing: 8
                        Rectangle { visible: !!modelData.security; height: 20; width: sec.width + 14; radius: 6; color: Qt.rgba(0.85, 0.2, 0.25, 0.16); anchors.verticalCenter: parent.verticalCenter
                            Label { id: sec; anchors.centerIn: parent; text: "Security"; color: Theme.t.danger; font.pixelSize: 10; font.weight: Font.DemiBold } }
                        Btn { visible: modelData.kind === "app"; text: "Update"; enabled: !pg.working; onClicked: Updates.install(modelData.id) } } } }
            SetRow { visible: modelData.kind === "system" && mine.length > 5; title: pg.allSystem ? "Show fewer" : "Show all " + mine.length; chevron: true; onClicked: pg.allSystem = !pg.allSystem } } }
    SetCard { title: "Automatic updates"; note: "Apps and Huginn update by themselves. System updates are downloaded and go in the next time you restart, so nothing changes under a program you're using."
        SetRow { title: "Keep this computer up to date by itself"; glyph: "refresh"; tile: "#1E40AF"; Toggle { on: Settings.autoUpdate; onToggled: function (v) { Settings.set("autoUpdate", v ? "true" : "false") } } } }
    SetCard { visible: pg.have; title: "Huginn"
        SetRow { title: "Version"; sub: pg.have ? (Updates.huginn.yours ? "Updated by Software Update" : "The version that came with the system") : ""
            Label { text: pg.have ? Updates.huginn.date + " · " + Updates.huginn.commit : ""; secondary: true; font.family: Theme.t.fontMono } }
        SetRow { visible: pg.have && Updates.huginn.canGoBack; title: "Go back to the version before"; sub: "If the newest one gives you trouble"
            Btn { text: "Go Back"; onClicked: Updates.goBack() } } }
}
