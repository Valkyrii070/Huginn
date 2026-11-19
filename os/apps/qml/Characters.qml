import QtQuick

// Characters, "the type case": the drawers down the left (smileys, people, nature… arrows, maths, money), the
// drawer's contents as a tray of little squares, and above the tray a magnifying lens showing the one under your
// pointer, big, with its name. Click any square to copy it.
GlassWindow {
    id: win
    title: "Characters"; width: 980; height: 700; minimumWidth: 720; minimumHeight: 500; glow: "left"
    property string hover: ""
    readonly property var lens: Backend.picked
    readonly property var swatches: ["#FFC93C", "#F7D7C4", "#E7B48F", "#C68B5E", "#8D5A3B", "#5A3825"]
    Connections { target: Backend; function onSaid(msg, wrong) { toast.say(msg, wrong) } }

    islands: [
        Island { anchors { right: parent.right; rightMargin: 12 } y: 12
            IslandField { id: find; objectName: "find"; width: 240; placeholder: "Search " + Backend.count.toLocaleString(Qt.locale(), "f", 0) + " characters"; onTextChanged: Backend.search(text) } },
        Toast { id: toast; anchors { horizontalCenter: parent.horizontalCenter; bottom: parent.bottom; bottomMargin: 22 } },
        Rail { x: 12; y: 64; width: 168; maxHeight: win.height - 64 - 14
            Repeater { model: Backend.groups
                Pressable { required property var modelData; readonly property bool on: Backend.group === modelData.id && find.text === ""; width: parent.width; height: 34; radius: 11
                    color: on ? Theme.t.accent : hovered ? Theme.t.hover : "transparent"; onClicked: { var g = modelData.id; find.text = ""; Backend.setGroup(g) }
                    Label { x: 10; width: 22; height: parent.height; verticalAlignment: Text.AlignVCenter; horizontalAlignment: Text.AlignHCenter; text: modelData.mark; font.pixelSize: 16; color: parent.on ? Theme.t.onAccent : Theme.t.text }
                    Label { x: 40; height: parent.height; verticalAlignment: Text.AlignVCenter; text: modelData.name; font.pixelSize: 12; font.weight: parent.on ? Font.DemiBold : Font.Normal; color: parent.on ? Theme.t.onAccent : Theme.t.text } } } }
    ]

    // ---------------- the lens
    Rectangle { id: lensBox; objectName: "lens"; x: 194; y: 64; width: parent.width - 194 - 14; height: 156; radius: 22; color: Theme.t.island; border.width: 1; border.color: Theme.t.islandLine
        Rectangle { x: 16; y: 16; width: 124; height: 124; radius: 20; color: Theme.t.group
            Label { anchors.centerIn: parent; text: win.lens.c || ""; font.pixelSize: 76; font.family: "Noto Color Emoji, " + Theme.t.font } }
        Column { x: 158; y: 20; width: parent.width - 158 - 16; spacing: 6
            Label { width: parent.width; elide: Text.ElideRight; text: win.lens.name ? win.lens.name.charAt(0).toUpperCase() + win.lens.name.slice(1) : "Point at a character"; font.pixelSize: 20; font.weight: Font.Bold }
            Label { text: win.lens.code ? win.lens.code + "   ·   " + win.lens.html : "Click one to copy it, then paste it anywhere."; font.pixelSize: 12; font.family: win.lens.code ? Theme.t.fontMono : Theme.t.font; secondary: true }
            Row { spacing: 6; visible: !!win.lens.c
                Btn { primary: true; text: "Copy"; onClicked: Backend.copy(win.lens.c) }
                Btn { text: win.lens.star ? "Unstar" : "Star"; onClicked: Backend.star(win.lens.c) }
                Item { width: 10; height: 1 }
                Repeater { model: win.lens.tones ? 6 : 0
                    Pressable { required property int index; width: 26; height: 26; radius: 13; y: 3; color: win.swatches[index]; border.width: Backend.tone === index ? 3 : 0; border.color: Theme.t.text
                        onClicked: { Backend.setTone(index); Backend.pick(win.lens.variants[index] || win.lens.c) } } } }
            Row { spacing: 2; visible: Backend.recent.length > 0 && !win.lens.tones
                Label { text: "Recent  "; font.pixelSize: 11; secondary: true; anchors.verticalCenter: parent.verticalCenter }
                Repeater { model: Backend.recent
                    Pressable { required property string modelData; width: 28; height: 28; radius: 8; onClicked: Backend.copy(modelData)
                        Label { anchors.centerIn: parent; text: modelData; font.pixelSize: 17 } } } } } }

    // ---------------- the tray
    GridView { id: tray; objectName: "tray"; x: 194; y: lensBox.y + lensBox.height + 12; width: parent.width - 194 - 14; height: parent.height - y - 14; clip: true
        cellWidth: Math.floor(width / Math.max(1, Math.floor(width / 58))); cellHeight: 58; model: Backend.items; boundsBehavior: Flickable.StopAtBounds
        delegate: Pressable { required property var modelData; width: tray.cellWidth - 4; height: 54; radius: 12; color: hovered ? Theme.t.hover : "transparent"
            onClicked: Backend.copy(modelData.c)
            onHoveredChanged: if (hovered) Backend.pick(modelData.c)
            Label { anchors.centerIn: parent; text: modelData.c; font.pixelSize: 28; font.family: "Noto Color Emoji, " + Theme.t.font }
            Label { visible: modelData.star; anchors { right: parent.right; top: parent.top; margins: 4 } text: "★"; font.pixelSize: 9; color: Theme.t.accent } }
        Label { visible: tray.count === 0; anchors.centerIn: parent; secondary: true
            text: find.text !== "" ? "No character is called that" : Backend.group === "starred" ? "Star the ones you use most" : Backend.group === "recent" ? "Characters you copy show up here" : "" } }
}
