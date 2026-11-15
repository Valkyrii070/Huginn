import QtQuick

// The dock: three separate islands. Left, the orb that opens the launcher. Middle, apps: pinned ones,
// then anything else that is running, then web apps installed from Huginn. Right, a live tile that
// appears only while something is happening (see Live in huginn_shell.py).
// An open app shows a bar in the realm's accent colour with a soft glow under its tile.
Row {
    id: dock
    signal launcher()
    signal controlCentre()                 // kept for callers; the control centre opens from the top bar
    signal tabsWanted(bool show)           // pointer rests on / leaves the Huginn tile
    property real tabsX: 0                 // centre of the Huginn tile, in dock coordinates
    // The session shell draws names in a surface of its own (the dock's is only as tall as the dock),
    // so it turns inlineTips off and listens to tipText / tipX.
    property bool inlineTips: true
    property string tipText: ""
    property real tipX: 0
    property string tipFor: ""              // the app the name bubble belongs to
    // Under Huginn's own compositor: brings the app's window forward when it has one (returns true), instead of
    // starting it again. Elsewhere it stays null and a click starts the app.
    property var activate: null
    property bool menuOpen: false          // the start menu is open (it grows out of the orb)
    onMenuOpenChanged: if (menuOpen && Theme.t.openMs > 0) orbPress.restart()
    function hover(item, app, open, inside) {
        var centre = appsIsland.x + main.x + item.x + item.width / 2
        if (app.name === "Huginn" && Tabs.installed) { if (inside) tabsX = centre; tabsWanted(inside); return }
        // Tracked by app, not by position: tiles move when an app opens or closes.
        if (inside) { tipX = centre; tipFor = app.name; tipText = app.name + (open ? " · open" : "") }
        else if (tipFor === app.name) { tipFor = ""; tipText = "" }
    }
    onNativesChanged: { tipFor = ""; tipText = "" }
    readonly property var pinnedNames: Apps.pinned          // "Keep in the dock" in an app's island changes it
    signal islandWanted(var app, real x)   // right-click (or Menu key) on an app: its island, centred on x (dock coordinates)
    readonly property var natives: {
        var all = Apps.all, run = Apps.running, out = [], i
        for (i = 0; i < pinnedNames.length; i++)
            for (var j = 0; j < all.length; j++)
                if (!all[j].web && all[j].name === pinnedNames[i]) { out.push(all[j]); break }
        for (i = 0; i < all.length; i++)
            if (!all[i].web && pinnedNames.indexOf(all[i].name) < 0 && run.indexOf(all[i].name) >= 0) out.push(all[i])
        return out
    }
    readonly property var webApps: Apps.all.filter(function (a) { return a.web }).slice(0, 4)
    spacing: 12

    component Island: Glass { height: 64; radius: 22 }
    component Divider: Rectangle { width: 1; height: 30; color: Theme.t.line; anchors.verticalCenter: parent.verticalCenter }
    component Tile: Item {
        id: slot
        property var app
        readonly property bool open: Apps.running.indexOf(app.name) >= 0
        property alias hovered: hit.containsMouse
        property bool inlineTip: true
        width: 44; height: 44
        scale: hit.pressed ? Theme.t.pressScale : 1
        Behavior on scale { NumberAnimation { duration: 100 } }
        AppIcon { name: slot.app.name; glyph: slot.app.glyph; image: slot.app.image; own: slot.app.own || ""; web: slot.app.web }
        // Open: an accent bar with a wider, fainter copy behind it as the glow.
        Rectangle { visible: slot.open; width: 34; height: 9; radius: 5; color: Theme.t.accent; opacity: 0.22; anchors { horizontalCenter: parent.horizontalCenter; top: parent.bottom; topMargin: 1 } }
        Rectangle { visible: slot.open; width: 22; height: 3; radius: 2; color: Theme.t.accent; anchors { horizontalCenter: parent.horizontalCenter; top: parent.bottom; topMargin: 4 } }
        // A count the app wants seen (Mail: unread).
        Rectangle { readonly property int n: Apps.badges[slot.app.name] || 0; visible: n > 0; z: 3; height: 16; width: Math.max(16, bn.width + 9); radius: 8; color: "#E5484D"; border.width: 1; border.color: "#33000000"
            anchors { right: parent.right; rightMargin: -3; top: parent.top; topMargin: -3 }
            Label { id: bn; anchors.centerIn: parent; text: parent.n > 99 ? "99+" : parent.n; color: "white"; font.pixelSize: 10; font.weight: Font.Bold } }
        MouseArea {
            id: hit; anchors.fill: parent; hoverEnabled: true; acceptedButtons: Qt.LeftButton | Qt.RightButton
            onClicked: function (m) {
                if (m.button === Qt.RightButton) { dock.islandWanted(slot.app, slot.mapToItem(dock, slot.width / 2, 0).x); return }
                if (!(dock.activate && dock.activate(slot.app))) Apps.launch(slot.app.exec)
            }
            onPressAndHold: dock.islandWanted(slot.app, slot.mapToItem(dock, slot.width / 2, 0).x)
        }
        // Name on hover: every dock item says what it is. The Huginn tile shows its tab stack there.
        Glass {
            visible: slot.inlineTip && hit.containsMouse && !(slot.app.name === "Huginn" && Tabs.installed); popup: true; radius: Theme.t.radiusControl
            width: tip.width + 16; height: 26
            anchors { horizontalCenter: parent.horizontalCenter; bottom: parent.top; bottomMargin: 16 }
            Label { id: tip; anchors.centerIn: parent; text: slot.app.name + ((Apps.badges[slot.app.name] || 0) > 0 ? " · " + Apps.badges[slot.app.name] + " unread" : slot.open ? " · open" : ""); font.pixelSize: 12 }
        }
    }

    Island {
        width: 64
        Pressable {
            anchors.centerIn: parent; width: 44; height: 44; radius: 13; onClicked: dock.launcher()
            Rectangle {   // while the start menu is open the orb glows, as the menu's light comes from it
                anchors.centerIn: parent; width: 40; height: 40; radius: 20; color: Theme.t.glowA
                opacity: dock.menuOpen ? 0.35 : 0
                Behavior on opacity { NumberAnimation { duration: 300 } }
            }
            Rectangle {
                id: orbDot
                anchors.centerIn: parent; width: 26; height: 26; radius: 13
                gradient: Gradient { GradientStop { position: 0; color: Theme.t.glowA } GradientStop { position: 0.45; color: Theme.t.glowA } GradientStop { position: 1; color: Theme.t.glowB } }
                border.width: dock.menuOpen ? 2 : 0; border.color: "#E6FFFFFF"
                SequentialAnimation {   // the press: it dips, then lets the menu out
                    id: orbPress
                    NumberAnimation { target: orbDot; property: "scale"; to: 0.8; duration: 70; easing.type: Easing.OutQuad }
                    NumberAnimation { target: orbDot; property: "scale"; to: 1.12; duration: 140; easing.type: Easing.OutQuad }
                    NumberAnimation { target: orbDot; property: "scale"; to: 1; duration: 160; easing.type: Easing.OutBack }
                }
            }
        }
    }
    Island {
        id: appsIsland
        width: main.width + 20
        Row {
            id: main; anchors.centerIn: parent; spacing: 8
            Repeater {
                model: dock.natives
                Tile {
                    required property var modelData
                    app: modelData; inlineTip: dock.inlineTips
                    onHoveredChanged: dock.hover(this, modelData, open, hovered)
                }
            }
            Divider { visible: dock.webApps.length > 0 }
            Repeater { model: dock.webApps; Tile { required property var modelData; app: modelData; inlineTip: dock.inlineTips; onHoveredChanged: dock.hover(this, modelData, open, hovered) } }
        }
    }
    Island {
        visible: Live.active
        width: live.width + 26
        Row {
            id: live; anchors.centerIn: parent; spacing: 10
            Rectangle {
                width: 44; height: 44; radius: 13; color: Theme.t.view; border.width: 1; border.color: Theme.t.line
                Glyph { anchors.centerIn: parent; name: Live.glyph; size: 22; ink: Theme.t.accent }
            }
            Column {
                anchors.verticalCenter: parent.verticalCenter; spacing: 6
                Label { text: Live.text; font.pixelSize: 13; font.weight: Font.Medium }
                // How far along is not known, so the bar sweeps and does not fill.
                Rectangle {
                    width: 132; height: 4; radius: 2; color: Theme.t.line; clip: true
                    Rectangle {
                        width: 44; height: 4; radius: 2; color: Theme.t.accent
                        SequentialAnimation on x { running: Live.active; loops: Animation.Infinite
                            NumberAnimation { from: -44; to: 132; duration: 1400; easing.type: Easing.InOutQuad } }
                    }
                }
            }
        }
    }
}
