import QtQuick

// The app's one menu, out of its name in the top bar: search on top, About and Settings, then the app's groups down
// the side with the one you point at beside them (Open recent opens beside the menu), and Minimise, Close and Quit
// at the bottom. The app's own colour lights the item you're on. Typing searches every command and says where it
// lives. Keys: arrows, Enter, Esc. Opens with a quick grow from the name (120 ms, no light).
// `only`: one group by itself (the bar's "row of menus" way, Settings › Desktop & Dock).
Item {
    id: om
    property bool shown: false
    property string only: ""
    signal done()
    readonly property var m: Status.menus
    readonly property var groups: m.groups || []
    readonly property var front: { var a = Apps.all; for (var i = 0; i < a.length; i++) if (a[i].name === m.app) return a[i]; return null }
    readonly property color tone: front && front.colours && front.colours.length ? (Theme.t.dark ? front.colours[0] : front.colours[1]) : Theme.t.accent
    property int group: 0
    property int cursor: -1
    property var cascade: null
    property real cascadeY: 0
    property string query: ""
    readonly property var shownGroup: {
        if (only !== "") { for (var i = 0; i < groups.length; i++) if (groups[i].name === only) return groups[i]; return null }
        return groups.length ? groups[Math.min(group, groups.length - 1)] : null
    }
    readonly property var found: {
        if (query.trim() === "") return []
        var q = query.trim().toLowerCase(), out = []
        function look(list, where) {
            for (var i = 0; i < (list || []).length; i++) {
                var it = list[i]
                if (it.sep) continue
                if (it.children && it.children.length) { look(it.children, where + " › " + it.label); continue }
                if (it.enabled !== false && it.label.toLowerCase().indexOf(q) >= 0) out.push({ label: it.label, keys: it.keys, id: it.id, where: where })
            }
        }
        look(m.top, ""); for (var g = 0; g < groups.length; g++) look(groups[g].items, groups[g].name); look(m.middle, ""); look(m.bottom, "")
        return out.slice(0, 10)
    }
    width: card.width; height: card.height
    onShownChanged: if (shown) { group = 0; cursor = -1; cascade = null; query = ""; field.text = ""; field.forceActiveFocus(); grow.restart() }
    function run(it) { if (!it || it.sep || it.enabled === false || (it.children && it.children.length)) return; om.done(); Status.menuTrigger(it.id) }
    function list() { return query !== "" ? found : (shownGroup ? shownGroup.items.filter(function (i) { return !i.sep }) : []) }
    function posOf(index) {   // where item `index` of the group pointed at is among its items that aren't lines
        var items = shownGroup ? shownGroup.items : [], n = -1
        for (var i = 0; i <= index && i < items.length; i++) if (!items[i].sep) n++
        return n
    }

    ParallelAnimation {
        id: grow
        NumberAnimation { target: card; property: "scale"; from: Theme.t.openMs ? 0.9 : 1; to: 1; duration: Theme.t.openMs ? 120 : 0; easing.type: Easing.OutCubic }
        NumberAnimation { target: card; property: "opacity"; from: 0; to: 1; duration: Theme.t.openMs ? 120 : 80 }
    }
    Keys.onPressed: function (e) {
        var rows = list()
        if (e.key === Qt.Key_Escape) { if (query !== "") field.text = ""; else om.done(); e.accepted = true }
        else if (e.key === Qt.Key_Down) { cursor = Math.min(rows.length - 1, cursor + 1); e.accepted = true }
        else if (e.key === Qt.Key_Up) { cursor = Math.max(0, cursor - 1); e.accepted = true }
        else if (e.key === Qt.Key_Right && query === "" && only === "") { group = Math.min(groups.length - 1, group + 1); cursor = 0; e.accepted = true }
        else if (e.key === Qt.Key_Left && query === "" && only === "") { group = Math.max(0, group - 1); cursor = 0; e.accepted = true }
        else if (e.key === Qt.Key_Return || e.key === Qt.Key_Enter) { run(rows[Math.max(0, cursor)]); e.accepted = true }
    }

    component MenuItemRow: Rectangle {
        id: r
        property var it: ({})
        property string where: ""
        property bool lit: false
        width: parent ? parent.width : 200; height: it.sep ? 9 : (where !== "" ? 40 : 28); radius: 8
        readonly property bool hot: !it.sep && it.enabled !== false && (hit.containsMouse || lit)
        color: hot ? om.tone : "transparent"
        Rectangle { visible: r.it.sep === true; anchors.centerIn: parent; width: parent.width - 16; height: 1; color: Theme.t.line }
        Column {
            visible: !r.it.sep; x: 11; anchors.verticalCenter: parent.verticalCenter; width: parent.width - 90
            Label { width: parent.width; text: r.it.label || ""; elide: Text.ElideRight; font.pixelSize: 13; opacity: r.it.enabled === false ? 0.4 : 1; color: r.hot ? "white" : Theme.t.text }
            Label { visible: r.where !== ""; text: r.where; font.pixelSize: 11; color: r.hot ? Qt.rgba(1, 1, 1, 0.8) : Theme.t.text_secondary }
        }
        Label {
            visible: !r.it.sep; anchors { right: parent.right; rightMargin: 11; verticalCenter: parent.verticalCenter }
            text: r.it.children && r.it.children.length ? "›" : (r.it.keys || ""); font.pixelSize: 12
            color: r.hot ? Qt.rgba(1, 1, 1, 0.85) : Theme.t.text_secondary; opacity: r.it.enabled === false ? 0.4 : 1
        }
        MouseArea {
            id: hit; anchors.fill: parent; hoverEnabled: true; enabled: !r.it.sep
            onContainsMouseChanged: if (containsMouse) {
                if (r.it.children && r.it.children.length) { om.cascade = r.it; om.cascadeY = r.mapToItem(om, 0, 0).y - 6 }
                else if (!r.where) om.cascade = null
            }
            onClicked: om.run(r.it)
        }
    }

    Glass {
        id: card
        popup: true; dense: true; radius: 16
        transformOrigin: Item.TopLeft
        width: om.groups.length && om.only === "" ? 372 : 270
        height: col.height + 16
        MouseArea { anchors.fill: parent; z: -1 }
        Column {
            id: col
            x: 8; y: 8; width: card.width - 16; spacing: 6
            Rectangle {   // search: every command, typed for
                width: parent.width; height: 34; radius: 10; color: Qt.rgba(1, 1, 1, Theme.t.dark ? 0.07 : 0.5)
                border.width: field.text ? 1.5 : 0; border.color: om.tone
                Glyph { x: 10; anchors.verticalCenter: parent.verticalCenter; name: "search"; size: 14; ink: Theme.t.text_secondary }
                TextInput {
                    id: field
                    anchors { left: parent.left; leftMargin: 32; right: parent.right; rightMargin: 10; verticalCenter: parent.verticalCenter }
                    color: Theme.t.text; font.pixelSize: 13; font.family: Theme.t.font; clip: true
                    onTextChanged: { om.query = text; om.cursor = text ? 0 : -1; om.cascade = null }
                    Keys.forwardTo: [om]
                    Label { visible: !field.text; anchors.verticalCenter: parent.verticalCenter; text: "Search " + (om.m.app || "") + "'s commands"; secondary: true; font.pixelSize: 13 }
                }
            }
            // what typing found, and where each lives
            Column {
                visible: om.query !== ""; width: parent.width
                Repeater { model: om.found; MenuItemRow { required property var modelData; required property int index; it: modelData; where: modelData.where; lit: index === om.cursor } }
                Label { visible: om.found.length === 0; x: 11; height: 30; verticalAlignment: Text.AlignVCenter; text: "Nothing called that"; secondary: true; font.pixelSize: 13 }
                Label { x: 11; height: 22; verticalAlignment: Text.AlignVCenter; text: "↑↓ to choose · Enter to do it · Esc to close"; secondary: true; font.pixelSize: 11 }
            }
            Column {
                visible: om.query === ""; width: parent.width; spacing: 4
                Column { width: parent.width; visible: om.only === ""; Repeater { model: om.m.top || []; MenuItemRow { required property var modelData; it: modelData } } }
                Rectangle { visible: om.only === "" && (om.m.top || []).length > 0; width: parent.width - 16; x: 8; height: 1; color: Theme.t.line }
                Row {
                    visible: om.groups.length > 0
                    spacing: 6; width: parent.width
                    Column {   // the groups
                        visible: om.only === ""
                        width: 104; spacing: 1
                        Repeater {
                            model: om.groups
                            Rectangle {
                                required property var modelData
                                required property int index
                                width: 104; height: 28; radius: 8
                                color: index === om.group ? Qt.rgba(1, 1, 1, Theme.t.dark ? 0.12 : 0.6) : gh.containsMouse ? Theme.t.hover : "transparent"
                                Label { x: 10; anchors.verticalCenter: parent.verticalCenter; text: modelData.name; font.pixelSize: 13; font.weight: index === om.group ? Font.DemiBold : Font.Normal; secondary: index !== om.group }
                                Label { visible: index === om.group; anchors { right: parent.right; rightMargin: 9; verticalCenter: parent.verticalCenter } text: "›"; font.pixelSize: 13; opacity: 0.6 }
                                MouseArea { id: gh; anchors.fill: parent; hoverEnabled: true; onContainsMouseChanged: if (containsMouse) { om.group = index; om.cursor = -1; om.cascade = null } onClicked: om.group = index }
                            }
                        }
                    }
                    Rectangle { visible: om.only === ""; width: 1; height: items.height; color: Theme.t.line }
                    Column {   // the group pointed at
                        id: items
                        width: om.only === "" ? parent.width - 104 - 13 : parent.width
                        Repeater {
                            model: om.shownGroup ? om.shownGroup.items : []
                            MenuItemRow { required property var modelData; required property int index; it: modelData; lit: om.cursor >= 0 && !modelData.sep && om.posOf(index) === om.cursor }
                        }
                    }
                }
                Column { width: parent.width; visible: om.only === "" && (om.m.middle || []).length > 0; Repeater { model: om.m.middle || []; MenuItemRow { required property var modelData; it: modelData } } }
                Rectangle { visible: om.only === "" && (om.m.bottom || []).length > 0; width: parent.width - 16; x: 8; height: 1; color: Theme.t.line }
                Column { width: parent.width; visible: om.only === ""; Repeater { model: om.m.bottom || []; MenuItemRow { required property var modelData; it: modelData } } }
            }
        }
    }
    // Open recent (and anything else with more inside) opens beside the menu
    Glass {
        id: side
        visible: om.cascade !== null && om.query === ""
        popup: true; dense: true; radius: 14
        x: card.width - 6; y: om.cascadeY
        width: 240; height: sideCol.height + 12
        MouseArea { anchors.fill: parent; z: -1 }
        Column {
            id: sideCol
            x: 6; y: 6; width: parent.width - 12
            Repeater {
                model: om.cascade ? om.cascade.children : []
                Rectangle {
                    id: rf
                    required property var modelData
                    width: sideCol.width; height: 44; radius: 8; color: rh.containsMouse ? om.tone : "transparent"
                    Rectangle {   // a document's page, with the app's badge
                        x: 8; anchors.verticalCenter: parent.verticalCenter; width: 22; height: 28; radius: 4; color: "#F5F6F8"; border.width: 1; border.color: Qt.rgba(0, 0, 0, 0.15)
                        Column { x: 4; y: 5; spacing: 2; Repeater { model: 4; Rectangle { width: index === 0 ? 10 : 13; height: 2; radius: 1; color: index === 0 ? om.tone : "#C9CED6" } } }
                    }
                    Column {
                        x: 40; anchors.verticalCenter: parent.verticalCenter; width: parent.width - 48
                        Label { width: parent.width; text: rf.modelData.label; elide: Text.ElideMiddle; font.pixelSize: 13; color: rh.containsMouse ? "white" : Theme.t.text }
                        Label { visible: !!rf.modelData.sub; text: rf.modelData.sub || ""; font.pixelSize: 11; color: rh.containsMouse ? Qt.rgba(1, 1, 1, 0.8) : Theme.t.text_secondary }
                    }
                    MouseArea { id: rh; anchors.fill: parent; hoverEnabled: true; onClicked: om.run(rf.modelData) }
                }
            }
        }
    }
}
