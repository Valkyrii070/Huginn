import QtQuick

// Default Apps: a grid of tiles, one per kind of thing, showing the app that opens it; then what starts at sign-in.
Column {
    id: pg
    width: parent ? parent.width : 600; spacing: 18
    readonly property var d: Backend.defaults
    Flow { width: parent.width; spacing: 12
        Repeater { model: pg.d.categories || []
            Pressable { required property var modelData; width: (pg.width - 24) / 3; height: 96; radius: Theme.t.radiusCard
                color: hovered ? Theme.t.hover : Theme.t.group; border.width: 1; border.color: Theme.t.separator
                onClicked: win.pick(modelData.label, modelData.choices.map(function (c) { return { id: c.id, label: c.name, icon: c.icon } }), modelData.current, function (v) { Backend.setDefault(modelData.id, v) })
                Rectangle { x: 14; y: 14; width: 26; height: 26; radius: 8; color: "#D97706"; Glyph { anchors.centerIn: parent; name: modelData.glyph; size: 15; ink: "#FFFFFF" } }
                Label { x: 50; y: 18; text: modelData.label; secondary: true; font.pixelSize: 12 }
                Row { x: 14; y: 54; spacing: 8; width: parent.width - 28
                    Image { visible: modelData.currentIcon !== ""; source: modelData.currentIcon; width: 26; height: 26; sourceSize: Qt.size(52, 52); anchors.verticalCenter: parent.verticalCenter }
                    Label { text: modelData.currentName; font.pixelSize: 15; font.weight: Font.DemiBold; elide: Text.ElideRight; width: parent.width - 40; anchors.verticalCenter: parent.verticalCenter } }
                Label { anchors { right: parent.right; rightMargin: 14; top: parent.top; topMargin: 18 } visible: modelData.choices.length > 1; text: modelData.choices.length + " apps"; secondary: true; font.pixelSize: 11 } } } }
    SetCard { title: "Open when you sign in"; note: "Apps here start by themselves. Fewer means a quicker start."
        Repeater { model: pg.d.startup || []
            SetRow { required property var modelData; title: modelData.name; picture: modelData.icon; glyph: "apps"
                Row { spacing: 8
                    Seg { icon: "trash"; tip: "Remove"; onClicked: Backend.removeStartup(modelData.file) }
                    Toggle { on: modelData.on; anchors.verticalCenter: parent.verticalCenter; onToggled: function (v) { Backend.setStartup(modelData.file, v) } } } } }
        SetRow { title: "Add an app…"; chevron: true; onClicked: win.pick("Open when you sign in", (pg.d.addable || []).map(function (a) { return { id: a.id, label: a.name, icon: a.icon } }), "", function (v) { Backend.addStartup(v) }) } }
}
