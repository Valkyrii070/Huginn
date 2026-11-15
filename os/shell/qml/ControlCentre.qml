import QtQuick

// The control centre: slides out on the right. Everything in it is the computer's real state (Status, from
// huginn_system.py): Wi‑Fi and Bluetooth with their switches, Do Not Disturb, night light, dark, the screen's
// brightness and the sound, the realm, how the app menus open, and the notifications that came. Anything with more to
// it opens that page of Settings.
Glass {
    id: cc
    popup: true; radius: 18; width: 344
    component Block: Rectangle { color: Theme.t.hover; radius: Theme.t.radiusTile }
    component Dot: Rectangle { property bool on: true; property string glyph: ""; width: 28; height: 28; radius: 14
        color: on ? Theme.t.accent : (Theme.t.dark ? "#55FFFFFF" : "#40141E28")
        Glyph { anchors.centerIn: parent; visible: parent.glyph !== ""; name: parent.glyph; size: 15; ink: parent.on ? Theme.t.onAccent : Theme.t.text } }
    // A connection: its switch (the dot) and what it's connected to; the words open its page of Settings.
    component Conn: Item {
        id: conn
        property string title; property string sub; property bool on: true; property string glyph: ""; property string page: ""
        signal toggled(bool on)
        width: parent ? parent.width : 140; height: 30
        Dot { id: dot; on: conn.on; glyph: conn.glyph; anchors.verticalCenter: parent.verticalCenter
            MouseArea { anchors.fill: parent; anchors.margins: -4; cursorShape: Qt.PointingHandCursor; onClicked: conn.toggled(!conn.on) } }
        Column { x: 38; width: parent.width - 38; anchors.verticalCenter: parent.verticalCenter
            Label { text: conn.title; font.weight: Font.DemiBold; font.pixelSize: 13 }
            Label { text: conn.sub; secondary: true; font.pixelSize: 11; width: parent.width; elide: Text.ElideRight } }
        MouseArea { x: 38; width: parent.width - 38; height: parent.height; cursorShape: Qt.PointingHandCursor; onClicked: Status.openSettings(conn.page) }
    }
    component Tile: Block {
        id: tile
        property string label; property bool on: false; property string glyph: ""
        signal clicked()
        width: 71.5; height: 76
        Dot { on: tile.on; glyph: tile.glyph; anchors.horizontalCenter: parent.horizontalCenter; y: 12 }
        Label { text: tile.label; secondary: true; font.pixelSize: 11; anchors.horizontalCenter: parent.horizontalCenter; y: 50; width: parent.width - 8
            horizontalAlignment: Text.AlignHCenter; elide: Text.ElideRight }
        MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: tile.clicked() }
    }
    component Slider: Block {
        id: sl
        property string title; property real value; property string glyph: ""
        signal moved(real v)
        signal glyphClicked()
        height: 68
        Label { x: 12; y: 10; text: sl.title }
        Rectangle {
            id: track; x: 12; y: 34; width: parent.width - 24; height: 22; radius: 11; color: Theme.t.dark ? "#40FFFFFF" : "#30141E28"
            Rectangle { width: Math.max(22, parent.width * sl.value); height: 22; radius: 11; color: Theme.t.text; opacity: 0.88 }
            Glyph { x: 5; anchors.verticalCenter: parent.verticalCenter; visible: sl.glyph !== ""; name: sl.glyph; size: 13; ink: Theme.t.dark ? "#1A1E23" : "#FFFFFF"
                MouseArea { anchors.fill: parent; anchors.margins: -4; onClicked: sl.glyphClicked() } }
            MouseArea { anchors.fill: parent; anchors.leftMargin: 22
                function to(m) { sl.moved(Math.max(0, Math.min(1, (m.x + 22) / track.width))) }
                onPositionChanged: function (m) { if (pressed) to(m) } onPressed: function (m) { to(m) } }
        }
    }
    readonly property var net: Status.network
    readonly property var levels: Status.levels
    Flickable {
        anchors { fill: parent; margins: 14 }
        contentHeight: col.height; clip: true; boundsBehavior: Flickable.StopAtBounds
        Column {
            id: col
            width: parent.width; spacing: 10
            Row {
                spacing: 10
                Block {
                    width: 153; height: conns.height + 24
                    Column { id: conns; x: 12; y: 12; width: parent.width - 24; spacing: 11
                        Conn { visible: cc.net.wifiDevice; title: "Wi‑Fi"; glyph: "wifi"; page: "network"; on: cc.net.wifiOn
                            sub: !cc.net.wifiOn ? "Off" : cc.net.wifiName ? cc.net.wifiName + (cc.net.kind === "wired" ? " \u00b7 connected (wired is used)" : "") : "Not connected"
                            onToggled: function (on) { Status.setWifi(on) } }
                        Conn { visible: !cc.net.wifiDevice || cc.net.wired; title: cc.net.wired ? "Wired" : "Network"; glyph: "globe"; page: "network"
                            on: cc.net.wired || cc.net.kind !== "none"; sub: cc.net.wired ? (cc.net.wiredName || "Connected") : cc.net.kind === "none" ? "Not connected" : cc.net.name }
                        Conn { visible: Status.bluetooth.present; title: "Bluetooth"; glyph: "bluetooth"; page: "bluetooth"; on: Status.bluetooth.on
                            sub: Status.bluetooth.on ? "On" : "Off"; onToggled: function (on) { Status.setBluetooth(on) } } }
                }
                Column {
                    spacing: 10
                    Block { width: 153; height: 52
                        Row { x: 12; anchors.verticalCenter: parent.verticalCenter; spacing: 10
                            Dot { on: Status.dnd; glyph: "moon" }
                            Label { text: "Do Not Disturb"; font.weight: Font.DemiBold; anchors.verticalCenter: parent.verticalCenter; font.pixelSize: 12 } }
                        MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: Status.setDnd(!Status.dnd) } }
                    Row {
                        spacing: 10
                        Tile { visible: Status.nightLight.available; label: "Night light"; glyph: "sun"; on: Status.nightLight.on; onClicked: Status.setNightLight(!on) }
                        Tile { label: "Dark"; glyph: "moon"; on: Theme.t.dark; onClicked: Theme.setDark(!Theme.t.dark) }
                    }
                }
            }
            Slider { visible: cc.levels.brightness >= 0; width: parent.width; title: "Display"; glyph: "sun"; value: Math.max(0, cc.levels.brightness)
                onMoved: function (v) { Status.setBrightness(Math.max(0.02, v)) } }
            Slider { width: parent.width; title: cc.levels.muted ? "Sound (muted)" : "Sound"; glyph: cc.levels.muted ? "x" : "volume"
                value: cc.levels.muted ? 0 : cc.levels.volume
                onMoved: function (v) { Status.setVolume(v) } onGlyphClicked: Status.setMuted(!cc.levels.muted) }
            Label { text: "REALM"; secondary: true; font.pixelSize: 11; font.weight: Font.DemiBold }
            Row {
                spacing: 10
                Repeater {
                    model: Theme.t.realms
                    Rectangle {
                        required property var modelData
                        width: 71.5; height: 40; radius: Theme.t.radiusCard
                        border.width: Theme.t.realm === modelData.id ? 2 : 0; border.color: Theme.t.text
                        gradient: Gradient { orientation: Gradient.Horizontal; GradientStop { position: 0; color: modelData.a } GradientStop { position: 1; color: modelData.b } }
                        MouseArea { anchors.fill: parent; onClicked: Theme.setRealm(modelData.id) }
                    }
                }
            }
            Label { text: "CUSTOMIZE"; secondary: true; font.pixelSize: 11; font.weight: Font.DemiBold }
            Block {
                width: parent.width; height: 74
                Label { x: 12; y: 10; text: "App menus open" }
                Rectangle {   // segmented choice
                    x: 12; y: 34; width: parent.width - 24; height: 28; radius: Theme.t.radiusControl + 2; color: Theme.t.dark ? "#30000000" : "#1F141E28"
                    Row {
                        anchors { fill: parent; margins: 2 }
                        Repeater {
                            model: [["dropdown", "As a list"], ["inline", "Along the bar"]]
                            Rectangle {
                                required property var modelData
                                readonly property bool on: Settings.menuStyle === modelData[0]
                                width: parent.width / 2; height: parent.height; radius: Theme.t.radiusControl
                                color: on ? (Theme.t.dark ? "#38FFFFFF" : "#FFFFFF") : "transparent"
                                Label { anchors.centerIn: parent; text: modelData[1]; font.pixelSize: 12; font.weight: parent.on ? Font.DemiBold : Font.Normal }
                                MouseArea { anchors.fill: parent; onClicked: Settings.set("menuStyle", modelData[0]) }
                            }
                        }
                    }
                }
            }
            Item { width: parent.width; height: 18
                Label { text: "NOTIFICATIONS"; secondary: true; font.pixelSize: 11; font.weight: Font.DemiBold; anchors.verticalCenter: parent.verticalCenter }
                Label { visible: Status.notifications.length > 0; text: "Clear"; font.pixelSize: 11; color: Theme.t.accent; anchors { right: parent.right; verticalCenter: parent.verticalCenter }
                    MouseArea { anchors.fill: parent; anchors.margins: -6; cursorShape: Qt.PointingHandCursor; onClicked: Status.clearNotifications() } } }
            Label { visible: Status.notifications.length === 0; text: Status.dnd ? "Do Not Disturb is on: they wait here quietly." : "Nothing new."
                secondary: true; font.pixelSize: 12 }
            Repeater {
                model: Status.notifications
                Block { required property var modelData; width: col.width; height: nc.height + 20
                    Column { id: nc; x: 12; y: 10; width: parent.width - 24; spacing: 2
                        Row { width: parent.width; spacing: 6
                            Label { text: modelData.app; secondary: true; font.pixelSize: 11 }
                            Label { text: modelData.ago; secondary: true; font.pixelSize: 11 } }
                        Label { text: modelData.summary; font.weight: Font.DemiBold; font.pixelSize: 12; width: parent.width; elide: Text.ElideRight }
                        Label { visible: modelData.body !== ""; text: modelData.body; secondary: true; font.pixelSize: 12; width: parent.width; wrapMode: Text.WordWrap; maximumLineCount: 2; elide: Text.ElideRight } } }
            }
            Rectangle { width: parent.width; height: 34; radius: Theme.t.radiusControl; color: Theme.t.hover
                Row { anchors.centerIn: parent; spacing: 8
                    Glyph { name: "gear"; size: 14; anchors.verticalCenter: parent.verticalCenter }
                    Label { text: "All Settings"; font.pixelSize: 12; font.weight: Font.DemiBold; anchors.verticalCenter: parent.verticalCenter } }
                MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: Status.openSettings("") } }
        }
    }
}
