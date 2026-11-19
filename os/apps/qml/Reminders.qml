import QtQuick

// Reminders, "the tally": four big counters across the top say how things stand; under them one plain ruled list,
// like a page of a notebook, with the lists as tabs along its head.
GlassWindow {
    id: win
    title: "Reminders"; width: 760; height: 720; glow: "top"
    readonly property color pick: Qt.rgba(tintColor.r, tintColor.g, tintColor.b, 0.18)
    property var sheet: null                   // { kind: "edit", row } | { kind: "list" }
    property string draftRepeat: ""
    property string draftList: ""
    function edit(row) { sheet = { kind: "edit", row: row }; eTitle.text = row.title; eNote.many = row.note; eDay.text = row.due; eTime.text = row.time; draftRepeat = row.repeat; draftList = row.list; eWhy.text = ""; eTitle.focusIn() }
    function saveEdit() { var why = Backend.save(sheet.row.id, { title: eTitle.text, note: eNote.many, due: eDay.text, time: eTime.text, repeat: draftRepeat, list: draftList }); eWhy.text = why; if (why === "") sheet = null }
    Connections { target: Backend; function onSaid(msg) { toast.say(msg, false) } }
    onSheetChanged: if (sheet === null) adder.focusIn()
    Component.onCompleted: adder.focusIn()

    islands: [
        Island { anchors { right: parent.right; rightMargin: 12 } y: 12
            IslandField { id: seek; objectName: "seek"; width: 170; placeholder: "Search"; onTextChanged: Backend.setQuery(text) }
            Seg { icon: "list"; text: "Done · " + Backend.doneCount; on: Backend.view === "done"; onClicked: Backend.setView(Backend.view === "done" ? "today" : "done") }
            Seg { visible: Backend.view === "done" && Backend.doneCount > 0; icon: "trash"; tip: "Clear everything that's done"; danger: true; onClicked: Backend.clearDone() }
            Seg { visible: Backend.view.indexOf("list:") === 0 && Backend.lists.length > 1; icon: "trash"; tip: "Remove this list (what's on it moves to the first list)"; onClicked: Backend.removeList(Backend.heading) }
        },
        Toast { id: toast; anchors { horizontalCenter: parent.horizontalCenter; bottom: parent.bottom; bottomMargin: 74 } },
        Item { anchors.fill: parent; z: 20; visible: win.sheet !== null
            Rectangle { anchors.fill: parent; radius: win.r; color: "#66000000"; MouseArea { anchors.fill: parent; acceptedButtons: Qt.AllButtons; onClicked: win.sheet = null } }
            Rectangle { id: card; anchors.centerIn: parent; width: 460; radius: 16; color: Theme.t.menu_bg; border.width: 1; border.color: Theme.t.menu_border
                readonly property string kind: win.sheet ? win.sheet.kind : ""
                height: kind === "list" ? 170 : 490
                MouseArea { anchors.fill: parent }
                Label { x: 22; y: 20; font.pixelSize: 16; font.weight: Font.DemiBold; text: card.kind === "list" ? "New list" : "Details" }
                Column { visible: card.kind === "list"; x: 22; y: 54; width: parent.width - 44; spacing: 8
                    TextBox { id: lName; objectName: "lName"; width: parent.width; placeholder: "Its name"; onAccepted: lMake.clicked() }
                    Label { id: lWhy; color: Theme.t.danger; font.pixelSize: 12; visible: text !== "" } }
                Column { visible: card.kind === "edit"; x: 22; y: 54; width: parent.width - 44; spacing: 8
                    TextBox { id: eTitle; objectName: "eTitle"; width: parent.width; placeholder: "What is it?"; onAccepted: win.saveEdit() }
                    TextBox { id: eNote; width: parent.width; lines: 3; placeholder: "Notes" }
                    Row { spacing: 8
                        TextBox { id: eDay; objectName: "eDay"; width: 250; placeholder: "Day: tomorrow, friday, 13 nov…"; onAccepted: win.saveEdit() }
                        TextBox { id: eTime; objectName: "eTime"; width: 158; placeholder: "Time: 14:30, 9am"; onAccepted: win.saveEdit() } }
                    Label { text: "REPEAT"; secondary: true; font.pixelSize: 10; font.weight: Font.DemiBold; topPadding: 4 }
                    Flow { width: parent.width; spacing: 4
                        Repeater { model: [["", "Never"], ["daily", "Daily"], ["weekly", "Weekly"], ["monthly", "Monthly"], ["yearly", "Yearly"]]
                            Pressable { required property var modelData; width: rl.width + 14; height: 24; radius: 8; color: win.draftRepeat === modelData[0] ? win.pick : "transparent"; border.width: 1
                                border.color: win.draftRepeat === modelData[0] ? Theme.t.accent : Theme.t.capsule_border; onClicked: win.draftRepeat = modelData[0]
                                Label { id: rl; anchors.centerIn: parent; text: modelData[1]; font.pixelSize: 11 } } } }
                    Label { text: "LIST"; secondary: true; font.pixelSize: 10; font.weight: Font.DemiBold; topPadding: 4 }
                    Flow { width: parent.width; spacing: 4
                        Repeater { model: card.kind === "edit" ? Backend.lists : []
                            Pressable { required property var modelData; width: ll.width + 14; height: 24; radius: 8; color: win.draftList === modelData.name ? win.pick : "transparent"; border.width: 1
                                border.color: win.draftList === modelData.name ? Theme.t.accent : Theme.t.capsule_border; onClicked: win.draftList = modelData.name
                                Label { id: ll; anchors.centerIn: parent; text: modelData.name; font.pixelSize: 11 } } } }
                    Label { text: "PUT IT OFF"; secondary: true; font.pixelSize: 10; font.weight: Font.DemiBold; topPadding: 4 }
                    Flow { width: parent.width; spacing: 4
                        Repeater { model: [["hour", "An hour"], ["evening", "This evening"], ["tomorrow", "Tomorrow"], ["week", "Next week"]]
                            Pressable { required property var modelData; width: sl.width + 14; height: 24; radius: 8; color: hovered ? Theme.t.hover : "transparent"; border.width: 1; border.color: Theme.t.capsule_border
                                onClicked: { Backend.snooze(win.sheet.row.id, modelData[0]); win.sheet = null }
                                Label { id: sl; anchors.centerIn: parent; text: modelData[1]; font.pixelSize: 11 } } } }
                    Label { id: eWhy; width: parent.width; wrapMode: Text.WordWrap; color: Theme.t.danger; font.pixelSize: 12; visible: text !== "" } }
                Btn { visible: card.kind === "edit"; x: 22; anchors { bottom: parent.bottom; bottomMargin: 18 } danger: true; text: "Delete"; onClicked: { Backend.remove(win.sheet.row.id); win.sheet = null } }
                Row { anchors { right: parent.right; rightMargin: 22; bottom: parent.bottom; bottomMargin: 18 } spacing: 8
                    Btn { text: "Cancel"; onClicked: win.sheet = null }
                    Btn { id: lMake; visible: card.kind === "list"; primary: true; text: "Create"; onClicked: { lWhy.text = Backend.addList(lName.text); if (lWhy.text === "") { lName.text = ""; win.sheet = null } } }
                    Btn { visible: card.kind === "edit"; primary: true; text: "Save"; onClicked: win.saveEdit() } } } }
    ]

    // ---------------- how things stand
    Row { id: tally; x: 18; y: 64; width: parent.width - 36; spacing: 10
        Repeater { model: Backend.views
            Pressable { id: tile; required property var modelData; readonly property bool on: Backend.view === modelData.id && Backend.query === ""; width: (tally.width - 30) / 4; height: 84; radius: 18
                color: on ? Theme.t.accent : hovered ? Theme.t.hover : Theme.t.island; border.width: 1; border.color: on ? Theme.t.accent : Theme.t.islandLine; onClicked: Backend.setView(modelData.id)
                Rectangle { x: 12; y: 12; width: 30; height: 30; radius: 15; color: tile.on ? Qt.rgba(1, 1, 1, 0.25) : win.pick
                    Glyph { anchors.centerIn: parent; name: tile.modelData.icon; size: 15; ink: tile.on ? Theme.t.onAccent : Theme.t.accent } }
                Label { anchors { right: parent.right; rightMargin: 14 } y: 8; text: tile.modelData.count; font.pixelSize: 30; font.weight: Font.Bold; color: tile.on ? Theme.t.onAccent : Theme.t.text }
                Label { x: 14; y: 56; text: tile.modelData.name; font.weight: Font.DemiBold; color: tile.on ? Theme.t.onAccent : Theme.t.text_secondary } } } }

    // ---------------- the page
    Rectangle { id: sheetPage; anchors { left: parent.left; right: parent.right; top: tally.bottom; bottom: addBar.top; leftMargin: 18; rightMargin: 18; topMargin: 44; bottomMargin: 10 } radius: 18; color: Theme.t.island; border.width: 1; border.color: Theme.t.islandLine
        // the lists, as tabs standing on the page's top edge
        Flickable { x: 14; y: -32; width: parent.width - 28; height: 34; contentWidth: tabs.width; clip: true; boundsBehavior: Flickable.StopAtBounds
            Row { id: tabs; spacing: 4
                Repeater { model: Backend.lists
                    Pressable { required property var modelData; readonly property bool on: Backend.view === modelData.id && Backend.query === ""; width: tb.width + (modelData.count ? 44 : 26); height: on ? 34 : 30; y: on ? 0 : 4; radius: 10
                        color: on ? Theme.t.island : hovered ? Theme.t.hover : "transparent"; border.width: 1; border.color: on ? Theme.t.islandLine : "transparent"; onClicked: Backend.setView(modelData.id)
                        Rectangle { visible: parent.on; anchors { left: parent.left; right: parent.right; bottom: parent.bottom; leftMargin: 1; rightMargin: 1 } height: 10; color: Theme.t.island }
                        Label { id: tb; x: 13; y: 7; text: modelData.name; font.pixelSize: 12; font.weight: parent.on ? Font.DemiBold : Font.Normal; color: parent.on ? Theme.t.accent : Theme.t.text }
                        Label { visible: modelData.count > 0; anchors { right: parent.right; rightMargin: 11 } y: 8; text: modelData.count; secondary: true; font.pixelSize: 11 } } }
                Pressable { width: 30; height: 30; y: 4; radius: 10; color: hovered ? Theme.t.hover : "transparent"; onClicked: { win.sheet = { kind: "list" }; lWhy.text = ""; lName.focusIn() }
                    Glyph { anchors.centerIn: parent; name: "plus"; size: 13; ink: Theme.t.text_secondary } } } }
        Label { id: head; x: 22; y: 16; text: Backend.heading; font.pixelSize: 24; font.weight: Font.Bold; color: Theme.t.accent }
        Label { anchors { left: head.right; leftMargin: 10; baseline: head.baseline } text: Backend.rows.length ? Backend.rows.length : ""; secondary: true; font.pixelSize: 15 }
        Column { visible: Backend.rows.length === 0; anchors.centerIn: parent; spacing: 8
            Glyph { name: "bell"; size: 44; ink: Theme.t.text_secondary; opacity: 0.6; anchors.horizontalCenter: parent.horizontalCenter }
            Label { anchors.horizontalCenter: parent.horizontalCenter; secondary: true; text: Backend.query !== "" ? "Nothing found" : Backend.view === "today" ? "Nothing due today" : Backend.view === "done" ? "Nothing ticked off yet" : "Nothing here" } }
        ListView { id: list; anchors { fill: parent; topMargin: 56; bottomMargin: 8 } clip: true; model: Backend.rows; boundsBehavior: Flickable.StopAtBounds
            delegate: Item { id: row; required property var modelData; width: list.width; height: Math.max(46, texts.height + 18)
                Rectangle { anchors.fill: parent; color: hit.containsMouse ? Theme.t.hover : "transparent" }
                Rectangle { x: 54; width: parent.width - 54; height: 1; anchors.bottom: parent.bottom; color: Theme.t.islandLine }      // the ruled line
                MouseArea { id: hit; anchors.fill: parent; hoverEnabled: true; onClicked: win.edit(row.modelData) }
                Rectangle { id: tick; x: 20; y: 12; width: 22; height: 22; radius: 11; color: row.modelData.done ? Theme.t.accent : "transparent"; border.width: 1.6; border.color: row.modelData.done ? Theme.t.accent : row.modelData.late ? Theme.t.danger : Theme.t.text_secondary
                    Glyph { visible: row.modelData.done; anchors.centerIn: parent; name: "check"; size: 12; ink: Theme.t.onAccent }
                    MouseArea { anchors { fill: parent; margins: -8 } onClicked: Backend.toggle(row.modelData.id) } }
                Column { id: texts; x: 54; y: 9; width: parent.width - 54 - 84; spacing: 2
                    Label { width: parent.width; wrapMode: Text.WordWrap; text: row.modelData.title; opacity: row.modelData.done ? 0.5 : 1; font.strikeout: row.modelData.done; font.pixelSize: 14 }
                    Label { width: parent.width; elide: Text.ElideRight; visible: text !== ""; font.pixelSize: 11; color: row.modelData.late ? Theme.t.danger : Theme.t.text_secondary
                        text: [row.modelData.when, row.modelData.repeats, Backend.view.indexOf("list:") === 0 ? "" : row.modelData.list, row.modelData.note.split("\n")[0]].filter(function (x) { return x }).join("  ·  ") } }
                Row { anchors { right: parent.right; rightMargin: 10; verticalCenter: parent.verticalCenter }
                    Pressable { width: 30; height: 30; radius: 8; opacity: row.modelData.flag || hit.containsMouse || hovered ? 1 : 0; onClicked: Backend.flag(row.modelData.id)
                        Glyph { anchors.centerIn: parent; name: "star"; size: 15; ink: row.modelData.flag ? Theme.t.accent : Theme.t.text_secondary } }
                    Pressable { width: 30; height: 30; radius: 8; opacity: hit.containsMouse || hovered ? 1 : 0; onClicked: Backend.remove(row.modelData.id)
                        Glyph { anchors.centerIn: parent; name: "trash"; size: 14; ink: Theme.t.text_secondary } } } } } }

    // ---------------- a new one, as you'd say it
    Rectangle { id: addBar; anchors { left: parent.left; leftMargin: 18; right: parent.right; rightMargin: 18; bottom: parent.bottom; bottomMargin: 14 } height: 50; radius: 25; color: Theme.t.island; border.width: 1; border.color: Theme.t.islandLine
        visible: Backend.view !== "done"
        Glyph { x: 14; anchors.verticalCenter: parent.verticalCenter; name: "plus"; size: 16; ink: Theme.t.accent }
        TextBox { id: adder; objectName: "adder"; anchors { left: parent.left; leftMargin: 38; right: parent.right; rightMargin: 8; verticalCenter: parent.verticalCenter }
            placeholder: "New reminder, as you'd say it: “Call Sam tomorrow 9am”"; onAccepted: { if (text.trim() !== "") { Backend.add(text); text = "" } } } }
    Shortcut { sequence: "Escape"; enabled: win.sheet !== null; onActivated: win.sheet = null }
    Shortcut { sequence: "Ctrl+N"; onActivated: adder.focusIn() }
}
