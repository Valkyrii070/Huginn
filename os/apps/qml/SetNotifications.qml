import QtQuick

// Notifications: quiet hours at the top, then a row per app with its three switches.
Column {
    id: pg
    width: parent ? parent.width : 600; spacing: 18
    readonly property var n: Backend.notifications
    function hours() { var out = []; for (var h = 0; h < 24; h++) { var t = (h < 10 ? "0" : "") + h + ":00"; out.push({ id: t, label: t }); out.push({ id: t.replace(":00", ":30"), label: t.replace(":00", ":30") }) } return out }
    SetCard {
        SetRow { title: "Do Not Disturb"; sub: "Nothing makes a sound or shows a banner; it all waits in the notification list"; glyph: "moon"; tile: "#6D28D9"
            Toggle { on: !!pg.n.dnd; onToggled: function (v) { Backend.setNotify("dnd", v) } } }
        SetRow { title: "Quiet hours"; sub: pg.n.focus ? "Every day from " + pg.n.from + " to " + pg.n.to : "Do Not Disturb by itself at night"
            Toggle { on: !!pg.n.focus; onToggled: function (v) { Backend.setNotify("focus", v) } } }
        SetRow { visible: !!pg.n.focus; title: "From"
            Row { spacing: 8
                SetPick { text: pg.n.from || ""; onClicked: win.pick("Quiet from", pg.hours(), pg.n.from, function (v) { Backend.setNotify("from", v) }) }
                Label { text: "to"; secondary: true; anchors.verticalCenter: parent.verticalCenter }
                SetPick { text: pg.n.to || ""; onClicked: win.pick("Quiet until", pg.hours(), pg.n.to, function (v) { Backend.setNotify("to", v) }) } } }
        SetRow { title: "Show what a notification says"
            SetChoice { each: 104; options: [["always", "Always"], ["unlocked", "When unlocked"], ["never", "Never"]]; value: pg.n.previews || "always"; onPicked: function (v) { Backend.setNotify("previews", v) } } }
        SetRow { title: "Notification sounds"; Toggle { on: pg.n.sounds !== false; onToggled: function (v) { Backend.setNotify("sounds", v) } } } }
    SetCard { title: "Apps"
        Item { width: parent.width; height: 30
            Label { anchors { right: parent.right; rightMargin: 16 + 2 * 58 + 6; verticalCenter: parent.verticalCenter } text: "Allow"; secondary: true; font.pixelSize: 11; width: 46; horizontalAlignment: Text.AlignHCenter }
            Label { anchors { right: parent.right; rightMargin: 16 + 58 + 6; verticalCenter: parent.verticalCenter } text: "Banner"; secondary: true; font.pixelSize: 11; width: 46; horizontalAlignment: Text.AlignHCenter }
            Label { anchors { right: parent.right; rightMargin: 16 + 6; verticalCenter: parent.verticalCenter } text: "Sound"; secondary: true; font.pixelSize: 11; width: 46; horizontalAlignment: Text.AlignHCenter } }
        Repeater { model: pg.n.apps || []
            SetRow { required property var modelData; title: modelData.name; picture: modelData.icon; glyph: "bell"; tile: "#D6336C"
                Row { spacing: 18
                    Toggle { on: modelData.allow; onToggled: function (v) { Backend.setAppNotify(modelData.id, "allow", v) } }
                    Toggle { on: modelData.banner; enabled: modelData.allow; opacity: modelData.allow ? 1 : 0.4; onToggled: function (v) { Backend.setAppNotify(modelData.id, "banner", v) } }
                    Toggle { on: modelData.sound; enabled: modelData.allow; opacity: modelData.allow ? 1 : 0.4; onToggled: function (v) { Backend.setAppNotify(modelData.id, "sound", v) } } } } } }
}
