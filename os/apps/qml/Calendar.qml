import QtQuick

// Calendar, "glass month": each day is a pane of glass; what is coming up sits in the island the light comes from.
GlassWindow {
    id: win
    title: "Calendar"; glow: "bottom"; padTop: 60; padBottom: 62
    readonly property int side: 286
    property string view: startPage === "week" ? "week" : "month"
    // the top bar's menu (and Ctrl+N)
    function newEvent() { what.focusIn() }
    function importFile() { Picker.open("Import events", [["Calendar files", "*.ics *.ical *.ifb *.vcs"]], function (paths) { if (paths.length) Backend.importFile(paths[0]) }) }
    function setView(v) { view = v === "week" ? "week" : "month" }
    property string repeat: ""
    readonly property color wash: Qt.rgba(tintColor.r, tintColor.g, tintColor.b, 0.2)
    islands: [
        Island {   // which month
            anchors.horizontalCenter: parent.horizontalCenter; y: 12
            Seg { icon: "back"; tip: win.view === "week" ? "Previous week" : "Previous month"; onClicked: win.view === "week" ? Backend.stepWeek(-1) : Backend.step(-1) }
            Label { text: win.view === "week" ? Backend.weekTitle : Backend.title; font.pixelSize: 13; font.weight: Font.DemiBold; leftPadding: 8; rightPadding: 8; anchors.verticalCenter: parent.verticalCenter }
            Seg { icon: "forward"; tip: win.view === "week" ? "Next week" : "Next month"; onClicked: win.view === "week" ? Backend.stepWeek(1) : Backend.step(1) }
        },
        Island { anchors { right: parent.right; rightMargin: 12 } y: 12
            Seg { text: "Week"; on: win.view === "week"; onClicked: win.view = "week" }
            Seg { text: "Month"; on: win.view === "month"; onClicked: win.view = "month" }
            IslandGap {}
            Seg { icon: "calendar"; text: "Today"; onClicked: Backend.today() } },
        Island {   // coming up: the main island
            anchors { horizontalCenter: parent.horizontalCenter; bottom: parent.bottom; bottomMargin: 14 }
            Label { text: Backend.upcoming.length ? "Coming up" : "Nothing planned"; secondary: true; font.pixelSize: 12; leftPadding: 10; rightPadding: 4; anchors.verticalCenter: parent.verticalCenter }
            Repeater { model: Backend.upcoming.slice(0, Math.max(1, Math.floor((win.width - 180) / 230)))
                Seg { required property var modelData; required property int index; on: index === 0
                    text: modelData.title + "  ·  " + modelData.when + (modelData.time ? " " + modelData.time : ""); onClicked: Backend.select(modelData.date) } }
        }
    ]
    // ---------------- Week: seven lanes of glass, events placed by their time
    Item { id: weekView; visible: win.view === "week"; x: 14; y: 0; width: parent.width - win.side - 28; height: parent.height
        readonly property int gutter: 44
        readonly property real lane: (width - gutter) / 7
        readonly property int laneTop: 58
        Repeater { model: Backend.week
            Item { required property var modelData; required property int index
                x: weekView.gutter + index * weekView.lane; width: weekView.lane; height: weekView.height
                Label { x: 8; y: 2; text: modelData.label.toUpperCase(); font.pixelSize: 10; font.weight: Font.DemiBold; color: modelData.today ? Theme.t.accent : Theme.t.text_secondary }
                Rectangle { anchors { right: parent.right; rightMargin: 8 } y: 0; width: 22; height: 22; radius: 11; color: modelData.today ? Theme.t.accent : "transparent"
                    Label { anchors.centerIn: parent; text: modelData.day; font.pixelSize: 12; font.weight: modelData.today ? Font.Bold : Font.Normal; color: modelData.today ? Theme.t.onAccent : Theme.t.text } }
                Column { x: 4; y: 26; width: parent.width - 8; spacing: 2   // all-day events sit above the lane
                    Repeater { model: modelData.allDay.slice(0, 1)
                        Rectangle { required property var modelData; width: parent.width; height: 20; radius: 6; color: win.wash; border.width: 1; border.color: Theme.t.accent
                            Label { x: 6; width: parent.width - 10; anchors.verticalCenter: parent.verticalCenter; text: modelData.title; elide: Text.ElideRight; font.pixelSize: 11 } } } }
                Rectangle { id: lane; x: 3; y: weekView.laneTop; width: parent.width - 6; height: parent.height - weekView.laneTop - 3; radius: 10; clip: true
                    color: modelData.selected ? win.wash : Theme.t.group; border.width: 1; border.color: modelData.selected ? Theme.t.accent : Theme.t.islandLine
                    MouseArea { anchors.fill: parent; onClicked: Backend.select(modelData.date) }
                    Repeater { model: Backend.weekHours.length - 1; Rectangle { required property int index; x: 1; width: parent.width - 2; height: 1; y: (index + 1) * lane.height / Backend.weekHours.length; color: Theme.t.separator; opacity: 0.6 } }
                    Repeater { model: modelData.timed
                        Rectangle { required property var modelData
                            x: 3 + modelData.col * (lane.width - 6) / modelData.cols; width: (lane.width - 6) / modelData.cols - 2
                            y: modelData.at * lane.height + 1; height: Math.max(22, modelData.length * lane.height - 2); radius: 7
                            color: Qt.rgba(win.tintColor.r, win.tintColor.g, win.tintColor.b, 0.34); border.width: 1; border.color: Theme.t.accent
                            Label { x: 6; y: 3; width: parent.width - 10; text: modelData.title; elide: Text.ElideRight; font.pixelSize: 11; font.weight: Font.DemiBold }
                            Label { visible: parent.height > 34; x: 6; y: 18; text: modelData.time; secondary: true; font.pixelSize: 10 }
                            MouseArea { anchors.fill: parent; onClicked: Backend.select(modelData.date) } } } }
            } }
        Repeater { model: Backend.weekHours   // the hours down the side
            Label { required property string modelData; required property int index; x: 0; width: weekView.gutter - 8; horizontalAlignment: Text.AlignRight
                y: weekView.laneTop + index * (weekView.height - weekView.laneTop - 3) / Backend.weekHours.length - (index ? 6 : 0); text: modelData; secondary: true; font.pixelSize: 10 } }
    }
    // ---------------- Month
    Row { id: head; visible: win.view === "month"; x: 14; y: 0; width: parent.width - win.side - 28; height: 26
        Repeater { model: Backend.weekdays; Label { required property string modelData; width: head.width / 7; height: 26; text: modelData; secondary: true; font.pixelSize: 11; font.weight: Font.DemiBold; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter } } }
    Grid {
        id: month; visible: win.view === "month"; x: 14; y: 28; columns: 7; width: parent.width - win.side - 28; height: parent.height - 28
        readonly property int rows: Math.ceil(Backend.days.length / 7)
        Repeater { model: Backend.days
            Item {
                required property var modelData
                width: month.width / 7; height: month.height / month.rows
                Rectangle { anchors { fill: parent; margins: 3 } radius: 10; color: modelData.selected ? win.wash : Theme.t.group; opacity: modelData.inMonth ? 1 : 0.45
                    border.width: 1; border.color: modelData.selected ? Theme.t.accent : Theme.t.islandLine }
                Rectangle { x: 10; y: 10; width: 24; height: 24; radius: 12; color: modelData.today ? Theme.t.accent : "transparent"
                    Label { anchors.centerIn: parent; text: modelData.day; font.pixelSize: 12; font.weight: modelData.today ? Font.Bold : Font.Normal
                        color: modelData.today ? Theme.t.onAccent : modelData.inMonth ? Theme.t.text : Theme.t.text_secondary } }
                Column { x: 9; y: 40; width: parent.width - 18; spacing: 3
                    Repeater { model: modelData.events.slice(0, 2)
                        Rectangle { required property var modelData; width: parent.width; height: 18; radius: 6; color: win.wash
                            Label { x: 6; width: parent.width - 10; anchors.verticalCenter: parent.verticalCenter; text: modelData.title; elide: Text.ElideRight; font.pixelSize: 11 } } }
                    Label { visible: modelData.events.length > 2; leftPadding: 6; text: "+" + (modelData.events.length - 2) + " more"; secondary: true; font.pixelSize: 10 } }
                MouseArea { anchors.fill: parent; onClicked: Backend.select(modelData.date) }
            } }
    }
    Rectangle {   // the selected day
        x: parent.width - win.side; y: 3; width: win.side - 14; height: parent.height - 6; radius: 12; color: Theme.t.group; border.width: 1; border.color: Theme.t.islandLine
        MouseArea { anchors.fill: parent }
        Column { x: 16; y: 16; width: parent.width - 32; spacing: 8
            Label { text: Backend.selectedLabel; font.pixelSize: 17; font.weight: Font.DemiBold }
            Label { visible: Backend.agenda.length === 0; text: "No events. Add one below."; secondary: true }
            Repeater { model: Backend.agenda
                Rectangle { required property var modelData; width: parent.width; height: 48; radius: 10; color: win.wash
                    Rectangle { x: 10; y: 10; width: 3; height: 28; radius: 2; color: Theme.t.accent }
                    Label { x: 22; y: 8; width: parent.width - 110; text: modelData.title; elide: Text.ElideRight }
                    Label { x: 22; y: 26; width: parent.width - 110; elide: Text.ElideRight; text: (modelData.time || "All day") + (modelData.repeats ? "  ·  " + modelData.repeats : ""); secondary: true; font.pixelSize: 11 }
                    Row { anchors { right: parent.right; rightMargin: 6; verticalCenter: parent.verticalCenter }
                        Pressable { visible: modelData.id.indexOf("ics-") !== 0 && !modelData.reminder; width: 28; height: 28; onClicked: Backend.invite(modelData.id); Glyph { anchors.centerIn: parent; name: "mail"; size: 14; ink: Theme.t.text_secondary }
                            Rectangle { visible: parent.hovered; anchors { right: parent.left; verticalCenter: parent.verticalCenter } width: it.width + 12; height: 20; radius: 6; color: Theme.t.menu_bg; Label { id: it; anchors.centerIn: parent; text: "Invite people"; font.pixelSize: 10 } } }
                        Pressable { visible: !!modelData.repeats && !modelData.reminder; width: 28; height: 28; onClicked: Backend.skip(modelData.id, modelData.date); Glyph { anchors.centerIn: parent; name: "x"; size: 13; ink: Theme.t.text_secondary }
                            Rectangle { visible: parent.hovered; anchors { right: parent.left; verticalCenter: parent.verticalCenter } width: st.width + 12; height: 20; radius: 6; color: Theme.t.menu_bg; Label { id: st; anchors.centerIn: parent; text: "Skip just this day"; font.pixelSize: 10 } } }
                        Pressable { visible: !modelData.reminder; width: 28; height: 28; onClicked: Backend.remove(modelData.id); Glyph { anchors.centerIn: parent; name: "trash"; size: 14; ink: Theme.t.text_secondary } }
                        Glyph { visible: !!modelData.reminder; name: "bell"; size: 14; ink: Theme.t.text_secondary; width: 28; height: 28 } } } }
            Item { width: 1; height: 6 }
            Rectangle { visible: Backend.notice !== ""; width: parent.width; height: nt.height + 16; radius: 10; color: win.wash; border.width: 1; border.color: Theme.t.accent
                Label { id: nt; x: 10; y: 8; width: parent.width - 20; wrapMode: Text.WordWrap; text: Backend.notice; font.pixelSize: 12 }
                MouseArea { anchors.fill: parent; onClicked: Backend.clearNotice() } }
            Label { text: "NEW EVENT"; secondary: true; font.pixelSize: 11; font.weight: Font.DemiBold }
            Field { id: what; width: parent.width; icon: "edit"; placeholder: "What is it?"; onAccepted: add.clicked() }
            Field { id: when; width: parent.width; icon: "clock"; placeholder: "Time, like 14:30 (optional)"; onAccepted: add.clicked() }
            Flow { spacing: 4; width: parent.width
                Repeater { model: [["", "Once"], ["daily", "Daily"], ["weekdays", "Weekdays"], ["weekly", "Weekly"], ["monthly", "Monthly"], ["yearly", "Yearly"]]
                    Pressable { required property var modelData; width: rl.width + 10; height: 24; radius: 8; color: win.repeat === modelData[0] ? win.wash : "transparent"; border.width: 1; border.color: win.repeat === modelData[0] ? Theme.t.accent : Theme.t.capsule_border
                        onClicked: win.repeat = modelData[0]; Label { id: rl; anchors.centerIn: parent; text: modelData[1]; font.pixelSize: 11 } } } }
            Btn { id: add; text: "Add Event"; primary: true; onClicked: { Backend.addRepeating(what.text, when.text, win.repeat); what.text = ""; when.text = ""; win.repeat = "" } }
        }
    }
}
