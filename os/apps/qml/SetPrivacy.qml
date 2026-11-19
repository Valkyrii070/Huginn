import QtQuick

// Privacy & Security: what can reach this computer, what apps may use, when the screen locks, and what's remembered.
Column {
    id: pg
    width: parent ? parent.width : 600; spacing: 18
    readonly property var p: Backend.privacy
    readonly property var groups: { var out = {}; (p.permissions || []).forEach(function (x) { (out[x.what] = out[x.what] || []).push(x) }); return out }
    Rectangle { width: parent.width; height: 84; radius: Theme.t.radiusCard; color: Qt.rgba(0.15, 0.64, 0.35, Theme.t.dark ? 0.16 : 0.10); border.width: 1; border.color: Qt.rgba(0.15, 0.64, 0.35, 0.4)
        Glyph { x: 20; anchors.verticalCenter: parent.verticalCenter; name: "shield"; size: 34; ink: "#27A35A" }
        Column { x: 72; anchors.verticalCenter: parent.verticalCenter; width: parent.width - 200; spacing: 2
            Label { text: "Huginn OS sends nothing about you anywhere"; font.weight: Font.DemiBold }
            Label { width: parent.width; text: "No usage data, no crash reports, no advertising ID. Apps from Flathub run in their own sandbox."; secondary: true; font.pixelSize: 12; wrapMode: Text.WordWrap } }
        Btn { anchors { right: parent.right; rightMargin: 16; verticalCenter: parent.verticalCenter } text: "Privacy Report"; onClicked: Backend.openApp("privacy") } }
    SetCard { title: "Network"
        SetRow { title: "Firewall"; glyph: "shield"; tile: pg.p.firewall ? "#27A35A" : "#7D8CA3"
            sub: !pg.p.hasFirewall ? "ufw isn't installed" : pg.p.firewall ? "On · nothing from outside can connect unless you allow it" : "Off · anything on the network can try to connect"
            Toggle { visible: !!pg.p.hasFirewall; on: !!pg.p.firewall; onToggled: function (v) { Backend.setFirewall(v) } } } }
    SetCard { title: "What apps may use"; note: (pg.p.permissions || []).length ? "Apps from Flathub ask before using these. Reset makes the app ask again." : "No app has asked to use the camera, microphone, location or anything else yet."
        Repeater { model: Object.keys(pg.groups)
            Column { required property string modelData; width: parent.width
                Repeater { model: pg.groups[modelData]
                    SetRow { required property var modelData; required property int index; title: modelData.appName; sub: modelData.what + " · " + modelData.app
                        glyph: ({ "Camera": "camera", "Microphone": "mic", "Location": "pin", "Screenshots": "image", "Running in the background": "apps", "Notifications": "bell" })[modelData.what] || "shield"
                        tile: modelData.allow ? "#334155" : "#9AA4B2"
                        Row { spacing: 8
                            Btn { text: "Reset"; onClicked: Backend.forgetPermission(modelData.table, modelData.object, modelData.app) }
                            Toggle { on: modelData.allow; anchors.verticalCenter: parent.verticalCenter; onToggled: function (v) { Backend.setPermission(modelData.table, modelData.object, modelData.app, v) } } } } } } } }
    SetCard { title: "Screen lock"
        SetRow { title: "Lock the screen by itself"; Toggle { on: pg.p.lockOn !== false; onToggled: function (v) { Backend.setPrivacy("lockOn", v) } } }
        SetRow { visible: pg.p.lockOn !== false; title: "Lock after"
            SetChoice { each: 64; options: [["1", "1 min"], ["5", "5 min"], ["10", "10 min"], ["30", "30 min"]]; value: String(pg.p.lockAfter || 5); onPicked: function (v) { Backend.setPrivacy("lockAfter", Number(v)) } } }
        SetRow { title: "Lock when waking from sleep"; Toggle { on: pg.p.lockOnWake !== false; onToggled: function (v) { Backend.setPrivacy("lockOnWake", v) } } } }
    SetCard { title: "History"
        SetRow { title: "Remember recent files"; sub: (pg.p.recent || 0) + " files are remembered for Recent in Files and other apps"
            Toggle { on: pg.p.remember !== false; onToggled: function (v) { Backend.setPrivacy("remember", v) } } }
        SetRow { title: "Forget recent files"; sub: "Clears the list; the files themselves stay"; Btn { text: "Forget"; onClicked: win.confirm("Forget recent files?", "The list of recently opened files is cleared everywhere.", "Forget", function () { Backend.clearHistory() }) } }
        SetRow { title: "Empty the Trash by itself"; sub: "Things in the Trash longer than this are deleted"
            SetChoice { each: 70; options: [["0", "Never"], ["7", "7 days"], ["30", "30 days"], ["90", "90 days"]]; value: String(pg.p.trashDays || 0); onPicked: function (v) { Backend.setPrivacy("trashDays", Number(v)) } } } }
}
