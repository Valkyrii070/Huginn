import QtQuick

// Top bar, Googlebook-leaning: no strip, just text and glyphs floating on the wallpaper.
// Time and date on the left, then the active app (its menus open from the name); status on the right.
// When a window is maximised the bar turns to glass (`solid`) so it stays readable over app content.
Item {
    id: bar
    signal controlCentre()
    signal launcher()
    signal windowAction(string action)    // "minimise" or "close": the window in front (the host does it)
    property bool solid: false
    property string appName: "Huginn"
    // The app's menu: real things to do with the app in front. (Apps keep their own commands in their islands.)
    readonly property var menus: appName === "Huginn" || appName === ""
        ? [{ id: "help", label: "Huginn OS Help" }, { id: "settings", label: "Settings" }]
        : [{ id: "help", label: appName + " Help" }, { id: "minimise", label: "Minimise" }, { id: "close", label: "Close Window" }]
    function run(id) {
        bar.menusOpen = false
        if (id === "help") Apps.launch("python3 /usr/share/huginn-apps/huginn_app.py help")
        else if (id === "settings") Status.openSettings("")
        else bar.windowAction(id)
    }
    property bool menusOpen: startMenus
    // How the menus open from the app name: "dropdown" (default, a list) or "inline" (along the bar).
    // A user setting: Control centre > Customize, saved by the host.
    readonly property string menuStyle: Settings.menuStyle
    readonly property bool dropdownOpen: menusOpen && menuStyle === "dropdown"
    readonly property var battery: Status.battery
    readonly property var net: Status.network
    height: 30

    Glass { anchors.fill: parent; radius: 0; border.width: 0; opacity: bar.solid ? 1 : 0; Behavior on opacity { NumberAnimation { duration: 150 } } }

    Row {
        id: leftRow
        anchors { left: parent.left; leftMargin: 16; verticalCenter: parent.verticalCenter }
        spacing: 10
        Rectangle {   // the realm orb: Huginn's mark, and the way into the launcher
            width: 16; height: 16; radius: 8; anchors.verticalCenter: parent.verticalCenter
            gradient: Gradient { GradientStop { position: 0; color: Theme.t.glowA } GradientStop { position: 1; color: Theme.t.glowB } }
            MouseArea { anchors.fill: parent; anchors.margins: -6; onClicked: bar.launcher() }
        }
        Label {
            id: clock; font.weight: Font.DemiBold; font.pixelSize: 12; anchors.verticalCenter: parent.verticalCenter
            Timer { interval: 15000; running: true; repeat: true; triggeredOnStart: true
                onTriggered: { clock.text = Qt.formatTime(new Date(), Settings.clock24 ? "HH:mm" : "h:mm AP"); date.text = Settings.barDate ? Qt.formatDate(new Date(), "ddd, MMM d") : "" } }
        }
        Label { id: date; font.pixelSize: 12; anchors.verticalCenter: parent.verticalCenter }
        Rectangle { width: 1; height: 12; color: Theme.t.line; anchors.verticalCenter: parent.verticalCenter; visible: bar.appName !== "" }
        Pressable {
            id: appButton
            visible: bar.appName !== ""; width: app.width + 16; height: 22; radius: Theme.t.radiusControl
            color: bar.menusOpen || hovered ? Theme.t.hover : "transparent"
            anchors.verticalCenter: parent.verticalCenter; onClicked: bar.menusOpen = !bar.menusOpen
            Label { id: app; anchors.centerIn: parent; text: bar.appName; font.weight: Font.DemiBold; font.pixelSize: 12 }
        }
        Repeater {
            model: bar.menusOpen && bar.menuStyle === "inline" ? bar.menus : []
            Pressable { required property var modelData; width: ml.width + 14; height: 22; radius: Theme.t.radiusControl; anchors.verticalCenter: parent.verticalCenter
                color: hovered ? Theme.t.hover : "transparent"; onClicked: bar.run(modelData.id)
                Label { id: ml; anchors.centerIn: parent; text: modelData.label; font.pixelSize: 12 } }
        }
    }

    // Dropdown style: the menus as a list under the app name.
    // (In the session the bar's surface grows while this is open; see Shell.qml.)
    Glass {
        visible: bar.menusOpen && bar.menuStyle === "dropdown"
        popup: true; radius: Theme.t.radiusCard; width: 190; height: list.height + 12
        x: leftRow.x + appButton.x; y: bar.height + 2
        Column {
            id: list; x: 6; y: 6; width: parent.width - 12
            Repeater {
                model: bar.menus
                Pressable {
                    required property var modelData
                    required property int index
                    width: list.width; height: 28; radius: Theme.t.radiusControl
                    color: hovered ? Theme.t.hover : "transparent"
                    onClicked: bar.run(modelData.id)
                    Label { x: 10; anchors.verticalCenter: parent.verticalCenter; text: modelData.label }
                }
            }
        }
    }

    Pressable {
        anchors { right: parent.right; rightMargin: 10; verticalCenter: parent.verticalCenter }
        width: status.width + 16; height: 22; radius: 11
        onClicked: { Status.refreshPanel(); bar.controlCentre() }
        Row {
            id: status; anchors.centerIn: parent; spacing: 10
            Glyph {   // the network: Wi‑Fi (faint when not connected), or a wired connection
                visible: bar.net.wifiDevice || bar.net.kind === "wired"
                name: bar.net.kind === "wired" ? "globe" : "wifi"; size: 15; anchors.verticalCenter: parent.verticalCenter
                opacity: bar.net.kind === "none" || (bar.net.kind !== "wired" && !bar.net.wifiOn) ? 0.4 : 1
            }
            Row {      // battery (not on computers without one)
                visible: bar.battery.present
                spacing: 1; anchors.verticalCenter: parent.verticalCenter
                Text { visible: Settings.batteryPercent || bar.battery.percent <= 20; text: bar.battery.percent + "%"; color: bar.battery.percent <= 10 && !bar.battery.charging ? Theme.t.danger : Theme.t.text
                    font.pixelSize: 11; font.family: Theme.t.font; rightPadding: 4; anchors.verticalCenter: parent.verticalCenter }
                Rectangle { width: 22; height: 11; radius: 3.5; color: "transparent"; border.width: 1.2; border.color: Theme.t.text
                    Rectangle { x: 2; y: 2; height: 7; radius: 2; width: Math.max(1, 18 * bar.battery.percent / 100)
                        color: bar.battery.charging ? "#3DD68C" : bar.battery.percent <= 10 ? Theme.t.danger : Theme.t.text } }
                Rectangle { width: 2; height: 5; radius: 1; color: Theme.t.text; anchors.verticalCenter: parent.verticalCenter }
                Glyph { visible: bar.battery.charging; name: "bolt"; size: 11; anchors.verticalCenter: parent.verticalCenter }
            }
            Glyph { visible: Status.dnd; name: "moon"; size: 13; anchors.verticalCenter: parent.verticalCenter }
            // The control-centre mark: a rounded outline.
            Rectangle { width: 16; height: 11; radius: 3; color: "transparent"; border.width: 1.5; border.color: Theme.t.text; anchors.verticalCenter: parent.verticalCenter }
        }
    }
}
