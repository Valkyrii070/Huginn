import QtQuick

// Disks, "the shelf": each drive is a slab of glass with a bar showing how it is divided and how full it is.
GlassWindow {
    id: win
    title: "Disks"; width: 900; height: 640; glow: "right"
    property var sheet: null                   // { kind: "rename" | "erase", dev, name, fs }
    property string eraseFs: "exfat"
    property bool sure: false
    Connections { target: Backend
        function onFailed(msg) { toast.say(msg, true) }
        function onSaid(msg) { toast.say(msg, false) } }
    Timer { interval: 3000; running: !Backend.busy && win.sheet === null; repeat: true; onTriggered: Backend.refresh() }

    islands: [
        Island { visible: Backend.busy; anchors { horizontalCenter: parent.horizontalCenter; bottom: parent.bottom; bottomMargin: 14 }
            Label { leftPadding: 12; rightPadding: 12; anchors.verticalCenter: parent.verticalCenter; text: Backend.doing + "  Leave the drive plugged in."; font.pixelSize: 12 } },
        Toast { id: toast; anchors { horizontalCenter: parent.horizontalCenter; bottom: parent.bottom; bottomMargin: 18 } },
        Item { anchors.fill: parent; z: 20; visible: win.sheet !== null
            Rectangle { anchors.fill: parent; radius: win.r; color: "#66000000"; MouseArea { anchors.fill: parent; acceptedButtons: Qt.AllButtons } }
            Rectangle { id: card; anchors.centerIn: parent; width: 470; radius: 16; color: Theme.t.menu_bg; border.width: 1; border.color: Theme.t.menu_border
                readonly property string kind: win.sheet ? win.sheet.kind : ""
                readonly property string why: kind === "" ? "" : Backend.labelProblem(kind === "erase" ? win.eraseFs : win.sheet.fs, nameBox.text)
                height: kind === "erase" ? 420 : 180
                Label { x: 22; y: 20; width: parent.width - 44; elide: Text.ElideRight; font.pixelSize: 16; font.weight: Font.DemiBold
                    text: card.kind === "erase" ? "Erase “" + win.sheet.name + "”" : card.kind === "rename" ? "Rename “" + win.sheet.name + "”" : "" }
                Column { visible: card.kind === "erase"; x: 16; y: 52; width: parent.width - 32; spacing: 4
                    Label { x: 6; width: parent.width - 12; wrapMode: Text.WordWrap; color: Theme.t.danger; text: "Everything on it will be gone for good. Copy off anything you want to keep first." }
                    Item { width: 1; height: 4 }
                    Repeater { model: Backend.formats
                        Pressable { required property var modelData; width: parent.width; height: 54; radius: 10; onClicked: win.eraseFs = modelData.id
                            color: win.eraseFs === modelData.id ? Qt.rgba(win.tintColor.r, win.tintColor.g, win.tintColor.b, 0.22) : (hovered ? Theme.t.hover : "transparent")
                            border.width: win.eraseFs === modelData.id ? 1 : 0; border.color: Theme.t.accent
                            Label { x: 12; y: 8; text: modelData.name; font.weight: Font.DemiBold }
                            Label { x: 12; y: 28; width: parent.width - 24; elide: Text.ElideRight; text: modelData.detail; secondary: true; font.pixelSize: 11 } } } }
                TextBox { id: nameBox; x: 22; y: card.kind === "erase" ? 252 : 56; width: parent.width - 44; placeholder: "The drive's new name" }
                Label { x: 22; y: nameBox.y + 42; width: parent.width - 44; elide: Text.ElideRight; font.pixelSize: 12; color: Theme.t.danger; text: card.why }
                Pressable { visible: card.kind === "erase"; x: 16; y: 318; width: parent.width - 32; height: 32; radius: 9; color: "transparent"; onClicked: win.sure = !win.sure
                    Rectangle { x: 6; width: 16; height: 16; radius: 5; anchors.verticalCenter: parent.verticalCenter; color: win.sure ? Theme.t.danger : "transparent"; border.width: 1; border.color: win.sure ? Theme.t.danger : Theme.t.text_secondary
                        Label { visible: win.sure; anchors.centerIn: parent; text: "✓"; font.pixelSize: 11; font.weight: Font.Bold; color: "#FFFFFF" } }
                    Label { x: 32; anchors.verticalCenter: parent.verticalCenter; text: "I understand everything on this drive will be erased"; font.pixelSize: 12 } }
                Row { anchors { right: parent.right; rightMargin: 22; bottom: parent.bottom; bottomMargin: 20 } spacing: 8
                    Btn { text: "Cancel"; onClicked: { win.sheet = null; win.sure = false } }
                    Btn { visible: card.kind === "rename"; primary: true; text: "Rename"; opacity: card.why === "" ? 1 : 0.5; onClicked: if (card.why === "") { var s = win.sheet; win.sheet = null; Backend.rename(s.dev, nameBox.text) } }
                    Btn { visible: card.kind === "erase"; danger: true; text: "Erase"; opacity: win.sure && card.why === "" ? 1 : 0.4
                        onClicked: if (win.sure && card.why === "") { var s = win.sheet; win.sheet = null; win.sure = false; Backend.erase(s.dev, win.eraseFs, nameBox.text, true) } } } } }
    ]
    onSheetChanged: if (sheet) { nameBox.text = sheet.kind === "rename" ? sheet.name : ""; nameBox.focusIn(); if (sheet.kind === "erase") { eraseFs = "exfat"; sure = false } }

    Flickable { x: 14; y: 62; width: parent.width - 28; height: parent.height - 76; clip: true; contentHeight: shelf.height + 20
        Column { id: shelf; width: parent.width; spacing: 12
            Repeater { model: Backend.drives
                Rectangle { id: slab; required property var modelData; width: shelf.width; height: 96 + modelData.parts.length * 44; radius: 16; color: Theme.t.island; border.width: 1; border.color: Theme.t.islandLine
                    Rectangle { x: 16; y: 14; width: 42; height: 42; radius: 12; color: Theme.t.group; Glyph { anchors.centerIn: parent; name: slab.modelData.removable ? "disc" : "memory"; size: 22; ink: Theme.t.accent } }
                    Label { x: 70; y: 14; text: slab.modelData.name; font.pixelSize: 16; font.weight: Font.DemiBold }
                    Label { x: 70; y: 36; text: slab.modelData.detail + (slab.modelData.system ? "  ·  Huginn runs from this drive" : ""); secondary: true; font.pixelSize: 12 }
                    Btn { visible: slab.modelData.canEject; anchors { right: parent.right; rightMargin: 14 } y: 18; text: "Eject"; opacity: Backend.busy ? 0.5 : 1; onClicked: Backend.eject(slab.modelData.dev) }
                    Row { x: 16; y: 68; width: parent.width - 32; height: 12; spacing: 3     // how the drive is divided, and how full each part is
                        Repeater { model: slab.modelData.parts
                            Rectangle { required property var modelData; height: 12; radius: 6; color: Theme.t.group
                                width: Math.max(14, (slab.width - 32 - (slab.modelData.parts.length - 1) * 3) * modelData.share)
                                Rectangle { height: 12; radius: 6; width: Math.max(modelData.usedFrac > 0 ? 12 : 0, parent.width * modelData.usedFrac); color: modelData.usedFrac > 0.9 ? Theme.t.danger : Theme.t.accent } } } }
                    Column { x: 8; y: 90; width: parent.width - 16
                        Repeater { model: slab.modelData.parts
                            Item { id: part; required property var modelData; width: parent.width; height: 44
                                Label { x: 10; y: 5; width: 230; elide: Text.ElideRight; text: modelData.name; font.weight: Font.Medium }
                                Label { x: 10; y: 23; text: modelData.kind + " · " + modelData.sizeText; secondary: true; font.pixelSize: 11 }
                                Label { x: 250; anchors.verticalCenter: parent.verticalCenter; text: modelData.locked ? "Locked: open it in Files with its password" : modelData.usedText; secondary: true; font.pixelSize: 12 }
                                Row { anchors { right: parent.right; rightMargin: 6; verticalCenter: parent.verticalCenter } spacing: 2; visible: modelData.canChange; opacity: Backend.busy ? 0.5 : 1
                                    Seg { anchors.verticalCenter: undefined; text: modelData.mount ? "Close" : "Open"; onClicked: modelData.mount ? Backend.close(modelData.dev) : Backend.open(modelData.dev) }
                                    Seg { anchors.verticalCenter: undefined; text: "Rename"; onClicked: win.sheet = { kind: "rename", dev: modelData.dev, name: modelData.name, fs: modelData.fs } }
                                    Seg { anchors.verticalCenter: undefined; text: "Erase"; danger: true; onClicked: win.sheet = { kind: "erase", dev: modelData.dev, name: modelData.name, fs: modelData.fs } } } } } } } }
            Label { visible: Backend.drives.length === 0; width: parent.width; height: 200; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter; secondary: true; text: "No drives found" } } }
}
