import QtQuick

// Battery & Power: a big battery gauge with its health, the power mode, and when the screen and computer rest.
Column {
    id: pg
    width: parent ? parent.width : 600; spacing: 18
    readonly property var p: Backend.power
    readonly property var bat: p.battery || null
    readonly property var steps: [[60, "1 minute"], [120, "2 minutes"], [300, "5 minutes"], [600, "10 minutes"], [900, "15 minutes"], [1800, "30 minutes"], [3600, "1 hour"], [0, "Never"]]
    function words(sec) { for (var i = 0; i < steps.length; i++) if (steps[i][0] === sec) return steps[i][1]; return sec > 0 ? Math.round(sec / 60) + " minutes" : "Never" }
    function choose(title, current, done) { win.pick(title, steps.map(function (s) { return { id: s[0], label: s[1] } }), current, function (v) { done(Number(v)) }) }
    Rectangle { visible: pg.bat !== null; width: parent.width; height: 132; radius: Theme.t.radiusCard; color: Theme.t.group; border.width: 1; border.color: Theme.t.separator
        Ring { id: ring; x: 18; width: 100; height: 100; anchors.verticalCenter: parent.verticalCenter; thickness: 10
            value: pg.bat ? pg.bat.percent / 100 : 0; ink: pg.bat && pg.bat.percent <= 15 && !pg.bat.charging ? Theme.t.danger : "#27C281"
            Column { anchors.centerIn: parent
                Label { anchors.horizontalCenter: parent.horizontalCenter; text: pg.bat ? pg.bat.percent + "%" : ""; font.pixelSize: 24; font.weight: Font.Light }
                Glyph { visible: pg.bat && pg.bat.charging; anchors.horizontalCenter: parent.horizontalCenter; name: "bolt"; size: 14; ink: "#27C281" } } }
        Column { x: 140; anchors.verticalCenter: parent.verticalCenter; spacing: 6; width: parent.width - 160
            Label { text: !pg.bat ? "" : pg.bat.state === "fully-charged" ? "Fully charged" : pg.bat.charging ? "Charging" + (pg.bat.timeLeft ? " · full in " + pg.bat.timeLeft : "") : "On battery" + (pg.bat.timeLeft ? " · about " + pg.bat.timeLeft + " left" : "")
                font.pixelSize: 17; font.weight: Font.DemiBold }
            Label { visible: pg.bat && pg.bat.health > 0; text: pg.bat ? "Battery health " + pg.bat.health + "%" + (pg.bat.health < 80 ? " · it holds noticeably less than when new" : " · good") : ""; secondary: true }
            Label { visible: pg.bat && pg.bat.cycles > 0; text: pg.bat ? pg.bat.cycles + " charge cycles" + (pg.bat.rate > 0 && !pg.bat.charging ? " · using " + pg.bat.rate.toFixed(1) + " W now" : "") : ""; secondary: true } } }
    SetCard { visible: (pg.p.profiles || []).length > 0; title: "Power mode"; note: "Power saver also dims the screen a little and slows background work."
        Row { width: parent.width; height: 86; spacing: 10; leftPadding: 12; topPadding: 12
            Repeater { model: [["power-saver", "Power saver", "Longest battery", "leaf"], ["balanced", "Balanced", "The usual", "gear"], ["performance", "Performance", "Fastest, warmer", "bolt"]]
                Pressable { required property var modelData; visible: (pg.p.profiles || []).indexOf(modelData[0]) >= 0
                    width: (parent.width - 44) / 3; height: 62; radius: 14
                    color: pg.p.profile === modelData[0] ? Qt.rgba(0.15, 0.76, 0.5, 0.22) : (hovered ? Theme.t.hover : (Theme.t.dark ? "#14FFFFFF" : "#0C141E28"))
                    border.width: pg.p.profile === modelData[0] ? 2 : 0; border.color: "#27C281"
                    onClicked: Backend.setProfile(modelData[0])
                    Column { anchors.centerIn: parent; spacing: 2
                        Label { anchors.horizontalCenter: parent.horizontalCenter; text: modelData[1]; font.weight: Font.DemiBold }
                        Label { anchors.horizontalCenter: parent.horizontalCenter; text: modelData[2]; secondary: true; font.pixelSize: 11 } } } } } }
    SetCard { title: "When it's not being used"
        SetRow { title: "Turn the screen off"; sub: pg.bat ? "Plugged in" : ""
            SetPick { text: pg.words(pg.p.idle ? pg.p.idle.ac.screenOff : 600); onClicked: pg.choose("Turn the screen off after", pg.p.idle.ac.screenOff, function (v) { Backend.setIdle("ac", "screenOff", v) }) } }
        SetRow { title: "Sleep"; sub: pg.bat ? "Plugged in" : ""
            SetPick { text: pg.words(pg.p.idle ? pg.p.idle.ac.sleep : 900); onClicked: pg.choose("Sleep after", pg.p.idle.ac.sleep, function (v) { Backend.setIdle("ac", "sleep", v) }) } }
        SetRow { visible: pg.bat !== null; title: "Turn the screen off"; sub: "On battery"
            SetPick { text: pg.words(pg.p.idle ? pg.p.idle.battery.screenOff : 300); onClicked: pg.choose("On battery, turn the screen off after", pg.p.idle.battery.screenOff, function (v) { Backend.setIdle("battery", "screenOff", v) }) } }
        SetRow { visible: pg.bat !== null; title: "Sleep"; sub: "On battery"
            SetPick { text: pg.words(pg.p.idle ? pg.p.idle.battery.sleep : 600); onClicked: pg.choose("On battery, sleep after", pg.p.idle.battery.sleep, function (v) { Backend.setIdle("battery", "sleep", v) }) } } }
    SetCard { title: "Buttons"
        SetRow { visible: pg.bat !== null; title: "Closing the lid"
            SetChoice { each: 92; options: [["1", "Sleep"], ["32", "Lock"], ["64", "Screen off"], ["0", "Nothing"]]; value: pg.p.lid || "1"; onPicked: function (v) { Backend.setPowerAction("lid", v) } } }
        SetRow { title: "The power button"
            SetChoice { each: 92; options: [["16", "Ask"], ["1", "Sleep"], ["8", "Shut down"], ["32", "Lock"]]; value: pg.p.button || "16"; onPicked: function (v) { Backend.setPowerAction("button", v) } } }
        SetRow { title: "Show the percentage in the top bar"; Toggle { on: Settings.batteryPercent; onToggled: function (v) { Settings.set("batteryPercent", v ? "true" : "false") } } } }
}
