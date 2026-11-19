import QtQuick

// Today: four islands under the date — the month, the weather now and over the next hours, the agenda (today,
// tomorrow, later this week, with reminders) and clocks. Opening, they bloom out of the date a beat apart, nearest
// first (240 ms each); closing, they go back into it together (160 ms). Reduce Motion: a fade.
// Pick a day: its events. Click an event: it opens in place. Type to add one ("Lunch with Astrid Friday 12").
Item {
    id: today
    property bool shown: false
    property point origin: Qt.point(60, -14)             // the date, in this item's coordinates
    signal done()
    readonly property bool motion: Theme.t.openMs > 0
    property string openEvent: ""                        // the event shown in place
    property string typed: ""
    readonly property var isl: Today.islands
    onShownChanged: {
        if (shown) { Today.reset(); openEvent = ""; addField.text = ""; bloom.restart(); addField.forceActiveFocus() }
        else { bloom.stop(); fold.restart() }
    }
    visible: shown || fold.running
    function toneOf(c) { return c }

    component Isle: Glass {
        id: g
        property real p: 0
        popup: true; dense: true; radius: 22
        MouseArea { anchors.fill: parent; z: -1 }          // a click on the island itself doesn't close Today
        opacity: today.motion ? Math.min(1, p * 1.6) : p
        transform: [
            Scale { origin.x: today.origin.x - g.x; origin.y: today.origin.y - g.y; xScale: today.motion ? 0.55 + 0.45 * g.p : 1; yScale: xScale }
        ]
    }
    SequentialAnimation {
        id: bloom
        ScriptAction { script: { month.p = 0; weather.p = 0; agenda.p = 0; clocks.p = 0 } }
        ParallelAnimation {
            NumberAnimation { target: month; property: "p"; to: 1; duration: today.motion ? 240 : 120; easing.type: Easing.OutBack; easing.overshoot: 1.1 }
            SequentialAnimation { PauseAnimation { duration: today.motion ? 55 : 0 } NumberAnimation { target: weather; property: "p"; to: 1; duration: today.motion ? 240 : 120; easing.type: Easing.OutBack; easing.overshoot: 1.1 } }
            SequentialAnimation { PauseAnimation { duration: today.motion ? 110 : 0 } NumberAnimation { target: agenda; property: "p"; to: 1; duration: today.motion ? 240 : 120; easing.type: Easing.OutBack; easing.overshoot: 1.1 } }
            SequentialAnimation { PauseAnimation { duration: today.motion ? 165 : 0 } NumberAnimation { target: clocks; property: "p"; to: 1; duration: today.motion ? 240 : 120; easing.type: Easing.OutBack; easing.overshoot: 1.1 } }
        }
    }
    ParallelAnimation {
        id: fold
        NumberAnimation { targets: [month, weather, agenda, clocks]; property: "p"; to: 0; duration: today.motion ? 160 : 100; easing.type: Easing.InCubic }
    }
    Keys.onEscapePressed: { if (today.openEvent !== "") today.openEvent = ""; else today.done() }

    // ---------------------------------------------------------------- the month
    Isle {
        id: month
        visible: today.isl.month !== false
        x: 0; y: 0; width: 330; height: monthCol.height + 28
        Column {
            id: monthCol
            x: 14; y: 14; width: parent.width - 28; spacing: 8
            Item {
                width: parent.width; height: 28
                Label { anchors.verticalCenter: parent.verticalCenter; x: 4; text: Today.title; font.pixelSize: 15; font.weight: Font.DemiBold }
                Row {
                    anchors { right: parent.right; verticalCenter: parent.verticalCenter }
                    spacing: 4
                    Repeater {
                        model: [["‹", -1], ["›", 1]]
                        Rectangle {
                            required property var modelData
                            width: 26; height: 26; radius: 13; color: stepHit.containsMouse ? Theme.t.hover : Qt.rgba(1, 1, 1, Theme.t.dark ? 0.06 : 0.4)
                            Label { anchors.centerIn: parent; text: parent.modelData[0]; font.pixelSize: 15 }
                            MouseArea { id: stepHit; anchors.fill: parent; hoverEnabled: true; onClicked: Today.step(parent.modelData[1]) }
                        }
                    }
                }
            }
            Grid {
                columns: 7; columnSpacing: 0; rowSpacing: 2
                Repeater { model: Today.weekdays; Label { required property var modelData; width: monthCol.width / 7; horizontalAlignment: Text.AlignHCenter; text: modelData; secondary: true; font.pixelSize: 11; font.weight: Font.DemiBold } }
                Repeater {
                    model: Today.days
                    Item {
                        id: dayCell
                        required property var modelData
                        width: monthCol.width / 7; height: 36
                        Rectangle {
                            anchors.horizontalCenter: parent.horizontalCenter; y: 2; width: 28; height: 28; radius: 14
                            color: dayCell.modelData.today ? Theme.t.accent : dayHit.containsMouse ? Theme.t.hover : "transparent"
                            border.width: dayCell.modelData.picked ? 1.5 : 0; border.color: Theme.t.accent
                            Label { anchors.centerIn: parent; text: dayCell.modelData.day; font.pixelSize: 13; font.weight: dayCell.modelData.today ? Font.Bold : Font.Normal
                                color: dayCell.modelData.today ? (Theme.t.dark ? "#0B1512" : "white") : Theme.t.text; opacity: dayCell.modelData.inMonth ? 1 : 0.35 }
                        }
                        Row {   // a dot for each thing that day (up to three)
                            anchors.horizontalCenter: parent.horizontalCenter; y: 31; spacing: 2
                            Repeater { model: dayCell.modelData.dots; Rectangle { required property var modelData; width: 4; height: 4; radius: 2; color: modelData } }
                        }
                        MouseArea { id: dayHit; anchors.fill: parent; hoverEnabled: true; enabled: dayCell.modelData.inMonth; onClicked: { var d = dayCell.modelData.date; today.openEvent = ""; Today.pick(d) } }
                    }
                }
            }
        }
    }

    // ---------------------------------------------------------------- the clocks, under the month
    Isle {
        id: clocks
        visible: today.isl.clocks !== false && Today.clocks.length > 0
        x: 0; y: (month.visible ? month.height + 12 : 0); width: 330; height: 86
        Label { x: 18; y: 14; text: "CLOCKS"; secondary: true; font.pixelSize: 11; font.weight: Font.DemiBold; font.letterSpacing: 0.6 }
        Row {
            x: 18; y: 36; spacing: 0
            Repeater {
                model: Today.clocks
                Column {
                    required property var modelData
                    width: (clocks.width - 36) / Math.max(1, Today.clocks.length); spacing: 2
                    Row { spacing: 3
                        Label { text: modelData.time; font.pixelSize: 16; font.weight: Font.DemiBold }
                        Label { text: modelData.plus; secondary: true; font.pixelSize: 10 } }
                    Label { text: modelData.city; secondary: true; font.pixelSize: 12 }
                }
            }
        }
    }

    // ---------------------------------------------------------------- the weather
    Isle {
        id: weather
        visible: today.isl.weather !== false
        readonly property var w: Today.weather
        readonly property bool have: !!w.temp
        x: (month.visible ? month.width + 12 : 0); y: 0; width: 310; height: have ? 128 : 74
        Row {
            visible: weather.have
            x: 16; y: 14; spacing: 12
            Rectangle {
                width: 44; height: 44; radius: 12; color: Qt.rgba(1, 1, 1, Theme.t.dark ? 0.08 : 0.5)
                Glyph {
                    anchors.centerIn: parent; size: 24; ink: Theme.t.text
                    readonly property int c: weather.w.code === undefined ? -1 : weather.w.code
                    name: c < 0 ? "cloud" : c === 0 ? (weather.w.day ? "sun" : "moon") : c <= 2 ? (weather.w.day ? "cloudsun" : "cloudmoon") : c === 3 ? "cloud" : c <= 48 ? "fog" : c <= 67 || (c >= 80 && c <= 82) ? "rain" : c <= 77 || c === 85 || c === 86 ? "snow" : "storm"
                }
            }
            Column {
                spacing: 1
                Label { text: weather.w.temp || ""; font.pixelSize: 26; font.weight: Font.Light }
                Label { text: (weather.w.words ? weather.w.words + " · " : "") + (weather.w.high ? "high " + weather.w.high + ", low " + weather.w.low + " · " : "") + (weather.w.place || ""); secondary: true; font.pixelSize: 12; width: weather.width - 90; elide: Text.ElideRight }
            }
        }
        Row {
            visible: weather.have
            x: 16; y: 74; spacing: 0
            Repeater {
                model: weather.w.hours || []
                Column {
                    required property var modelData
                    width: (weather.width - 32) / 5; spacing: 2
                    Label { anchors.horizontalCenter: parent.horizontalCenter; text: modelData.hour; secondary: true; font.pixelSize: 11 }
                    Label { anchors.horizontalCenter: parent.horizontalCenter; text: modelData.temp; font.pixelSize: 14; font.weight: Font.DemiBold }
                }
            }
        }
        Column {
            visible: !weather.have; x: 16; y: 14; spacing: 4
            Label { text: "No weather yet"; font.pixelSize: 14; font.weight: Font.DemiBold }
            Label { text: "Add a place in Weather and it shows here."; secondary: true; font.pixelSize: 12 }
        }
        MouseArea { anchors.fill: parent; z: -1; onClicked: { Apps.launch("python3 /usr/share/huginn-apps/huginn_app.py weather"); today.done() } }
    }

    // ---------------------------------------------------------------- the agenda, with adding by typing
    Isle {
        id: agenda
        visible: today.isl.agenda !== false
        x: weather.x; y: weather.visible ? weather.height + 12 : 0; width: 310
        height: Math.min(560, agendaCol.height + 28)
        Column {
            id: agendaCol
            x: 14; y: 14; width: parent.width - 28; spacing: 4
            Repeater {
                model: Today.agenda
                Column {
                    id: section
                    required property var modelData
                    width: agendaCol.width; spacing: 2
                    Label { text: section.modelData.label; secondary: true; font.pixelSize: 11; font.weight: Font.DemiBold; font.letterSpacing: 0.5; topPadding: 4; bottomPadding: 2 }
                    Label { visible: section.modelData.items.length === 0; text: Today.picked !== "" ? "Nothing that day." : "Nothing planned."; secondary: true; font.pixelSize: 12; bottomPadding: 4 }
                    Repeater {
                        model: section.modelData.items
                        Column {
                            id: ev
                            required property var modelData
                            readonly property bool opened: today.openEvent === modelData.id + modelData.date
                            width: agendaCol.width; spacing: 6
                            Item {
                                width: parent.width; height: 40
                                Rectangle { anchors.fill: parent; anchors.margins: -3; radius: 10; color: evHit.containsMouse || ev.opened ? Theme.t.hover : "transparent" }
                                Rectangle {   // a reminder's ring, or the event's colour bar
                                    x: 2; anchors.verticalCenter: parent.verticalCenter
                                    width: ev.modelData.reminder ? 14 : 3; height: ev.modelData.reminder ? 14 : 34; radius: ev.modelData.reminder ? 4 : 2
                                    color: ev.modelData.reminder ? "transparent" : ev.modelData.tone; border.width: ev.modelData.reminder ? 1.5 : 0; border.color: "#FFB340"
                                }
                                Column {
                                    x: 26; anchors.verticalCenter: parent.verticalCenter; width: parent.width - 30; spacing: 1
                                    Label { width: parent.width; text: ev.modelData.title; elide: Text.ElideRight; font.pixelSize: 13; font.weight: Font.DemiBold }
                                    Label { width: parent.width; text: ev.modelData.when + (ev.modelData.reminder ? " · Reminders" : ""); elide: Text.ElideRight; secondary: true; font.pixelSize: 12 }
                                }
                                MouseArea { id: evHit; anchors.fill: parent; hoverEnabled: true; onClicked: today.openEvent = ev.opened ? "" : ev.modelData.id + ev.modelData.date }
                            }
                            // the event, opened in place: where, its reminder, notes; join, or open it in Calendar
                            Column {
                                visible: ev.opened; x: 26; width: parent.width - 30; spacing: 5
                                opacity: ev.opened ? 1 : 0
                                Behavior on opacity { NumberAnimation { duration: today.motion ? 180 : 0 } }
                                Row { visible: ev.modelData.where !== ""; spacing: 7; Glyph { name: "pin"; size: 13; ink: Theme.t.icon } Label { text: ev.modelData.where; font.pixelSize: 12 } }
                                Row { visible: ev.modelData.remind !== ""; spacing: 7; Glyph { name: "bell"; size: 13; ink: Theme.t.icon } Label { text: ev.modelData.remind; font.pixelSize: 12 } }
                                Row { visible: ev.modelData.notes !== ""; spacing: 7; Glyph { name: "note"; size: 13; ink: Theme.t.icon } Label { width: agendaCol.width - 60; text: ev.modelData.notes; wrapMode: Text.WordWrap; maximumLineCount: 3; elide: Text.ElideRight; font.pixelSize: 12 } }
                                Label { visible: ev.modelData.repeats !== "" && !ev.modelData.reminder; text: "Repeats " + ev.modelData.repeats; secondary: true; font.pixelSize: 12 }
                                Row {
                                    spacing: 6; topPadding: 2; bottomPadding: 4
                                    Rectangle {
                                        visible: ev.modelData.call !== ""; width: jl.width + 22; height: 28; radius: 9; color: Theme.t.accent
                                        Label { id: jl; anchors.centerIn: parent; text: "Join call"; color: Theme.t.dark ? "#0B1512" : "white"; font.pixelSize: 12; font.weight: Font.DemiBold }
                                        MouseArea { anchors.fill: parent; onClicked: { Today.join(ev.modelData.call); today.done() } }
                                    }
                                    Rectangle {
                                        width: ol.width + 22; height: 28; radius: 9; color: Qt.rgba(1, 1, 1, Theme.t.dark ? 0.1 : 0.5)
                                        Label { id: ol; anchors.centerIn: parent; text: ev.modelData.reminder ? "Open in Reminders" : "Open in Calendar"; font.pixelSize: 12; font.weight: Font.DemiBold }
                                        MouseArea { anchors.fill: parent; onClicked: { if (ev.modelData.reminder) Apps.launch("python3 /usr/share/huginn-apps/huginn_app.py reminders"); else Today.openInCalendar(ev.modelData.date); today.done() } }
                                    }
                                }
                            }
                        }
                    }
                }
            }
            Label {
                visible: Today.picked !== ""; text: "Back to today"; color: Theme.t.accent; font.pixelSize: 12; font.weight: Font.DemiBold; topPadding: 2
                MouseArea { anchors.fill: parent; anchors.margins: -4; onClicked: Today.pick("") }
            }
            Item { width: 1; height: 6 }
            Rectangle {   // add by typing
                width: agendaCol.width; height: 36; radius: 11
                color: Qt.rgba(1, 1, 1, Theme.t.dark ? 0.06 : 0.5); border.width: addField.activeFocus && addField.text ? 1.5 : 1; border.color: addField.activeFocus && addField.text ? Theme.t.accent : Theme.t.line
                Label { x: 12; anchors.verticalCenter: parent.verticalCenter; text: "+"; color: Theme.t.accent; font.pixelSize: 16 }
                TextInput {
                    id: addField
                    anchors { left: parent.left; leftMargin: 30; right: parent.right; rightMargin: 10; verticalCenter: parent.verticalCenter }
                    color: Theme.t.text; font.pixelSize: 13; font.family: Theme.t.font; clip: true; selectByMouse: true
                    onTextChanged: today.typed = text
                    onAccepted: if (Today.add(text)) text = ""
                    Keys.onEscapePressed: { if (text) text = ""; else today.done() }
                    Label { visible: !addField.text; anchors.verticalCenter: parent.verticalCenter; text: "Add an event or a reminder…"; secondary: true; font.pixelSize: 13 }
                }
            }
            Rectangle {   // what Enter will add
                readonly property var p: today.typed ? Today.preview(today.typed) : ({ ok: false })
                visible: p.ok; width: agendaCol.width; height: 46; radius: 11; color: Qt.rgba(1, 1, 1, Theme.t.dark ? 0.05 : 0.4)
                Rectangle { x: 10; anchors.verticalCenter: parent.verticalCenter; width: parent.p.reminder ? 14 : 3; height: parent.p.reminder ? 14 : 30; radius: parent.p.reminder ? 4 : 2
                    color: parent.p.reminder ? "transparent" : Theme.t.accent; border.width: parent.p.reminder ? 1.5 : 0; border.color: "#FFB340" }
                Column {
                    x: 32; anchors.verticalCenter: parent.verticalCenter; width: parent.width - 120
                    Label { width: parent.width; text: parent.parent.p.title || ""; elide: Text.ElideRight; font.pixelSize: 13; font.weight: Font.DemiBold }
                    Label { width: parent.width; text: parent.parent.p.when || ""; elide: Text.ElideRight; secondary: true; font.pixelSize: 12 }
                }
                Label { anchors { right: parent.right; rightMargin: 10; verticalCenter: parent.verticalCenter } text: "Enter to add"; secondary: true; font.pixelSize: 11 }
            }
        }
    }
}
