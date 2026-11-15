import QtQuick

// Date & Time: a big clock, the time zone, and how the clock is kept right.
Column {
    id: pg
    width: parent ? parent.width : 600; spacing: 18
    readonly property var t: Backend.time
    property date now: new Date()
    Timer { running: true; repeat: true; interval: 1000; onTriggered: pg.now = new Date() }
    Rectangle { width: parent.width; height: 120; radius: Theme.t.radiusCard; color: Theme.t.group; border.width: 1; border.color: Theme.t.separator
        Column { anchors.centerIn: parent; spacing: 2
            Label { anchors.horizontalCenter: parent.horizontalCenter; text: Qt.formatTime(pg.now, Settings.clock24 ? "HH:mm:ss" : "h:mm:ss AP"); font.pixelSize: 44; font.weight: Font.Light; font.family: Theme.t.font }
            Label { anchors.horizontalCenter: parent.horizontalCenter; text: Qt.formatDate(pg.now, "dddd, MMMM d, yyyy") + " · " + (pg.t.zoneLabel || ""); secondary: true } } }
    SetCard {
        SetRow { title: "Time zone"; glyph: "globe"; tile: "#E8590C"
            SetPick { text: pg.t.zoneLabel || pg.t.zone || ""; maxWidth: 300; onClicked: win.pick("Time zone", Backend.zoneChoices.map(function (z) { return { id: z.id, label: z.label } }), pg.t.zone, function (v) { Backend.setZone(v) }) } }
        SetRow { title: "Set the time automatically"; sub: pg.t.ntp ? (pg.t.synced ? "Kept right by time servers on the internet" : "Waiting to reach a time server") : "You set the clock yourself"
            Toggle { on: pg.t.ntp !== false; onToggled: function (v) { Backend.setNtp(v) } } }
        SetRow { visible: pg.t.ntp === false; title: "Set the clock"
            Btn { text: "Set…"; onClicked: win.ask("Set the clock", "", [{ key: "when", label: "Date and time", text: Qt.formatDateTime(new Date(), "yyyy-MM-dd HH:mm") }], "Set", function (v) { Backend.setClock(v.when) }) } } }
    SetCard { title: "Clock"
        SetRow { title: "24-hour clock"; sub: Settings.clock24 ? "Shows 17:30" : "Shows 5:30 PM"; Toggle { on: Settings.clock24; onToggled: function (v) { Settings.set("clock24", v ? "true" : "false") } } }
        SetRow { title: "Show the date in the top bar"; Toggle { on: Settings.barDate; onToggled: function (v) { Settings.set("barDate", v ? "true" : "false") } } } }
}
