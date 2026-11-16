import QtQuick
import QtQuick.Shapes

// Top bar, Googlebook-leaning: no strip, just text and glyphs floating on the wallpaper.
// Time and date on the left, then the active app (its menus open from the name); status on the right.
// When a window is maximised the bar turns to glass (`solid`) so it stays readable over app content.
Item {
    id: bar
    signal controlCentre()
    signal launcher()
    signal search()                       // the magnifier: Search everything (Super+Space)
    signal windowAction(string action)    // "minimise" or "close": the window in front (the host does it)
    signal today()                        // the date: Today (the month, the weather, what's coming)
    property bool todayOpen: false
    onTodayOpenChanged: if (todayOpen && Theme.t.openMs > 0) dateRing.run()
    readonly property real dateLeft: leftRow.x + dateButton.x
    readonly property real dateWidth: dateButton.width
    property bool solid: false
    property string appName: "Huginn"
    // The app's name opens its one menu (AppMenuIsland.qml, in a surface of its own); "A row of menus" (Settings ›
    // Desktop & Dock) puts the app's groups along the bar instead, each opening its own list.
    signal appMenu(string group)
    property bool menuOpen: false
    property string menuGroup: ""
    readonly property bool rowMenus: Settings.menuStyle === "row" || Settings.menuStyle === "inline"
    readonly property real nameLeft: leftRow.x + appButton.x
    readonly property real nameWidth: appButton.width
    function groupLeft(name) { for (var i = 0; i < groupRep.count; i++) { var g = groupRep.itemAt(i); if (g && g.modelData.name === name) return leftRow.x + g.x } return nameLeft }
    readonly property var front: { var a = Apps.all; for (var i = 0; i < a.length; i++) if (a[i].name === appName) return a[i]; return null }
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
        Pressable {   // the time and date: Today opens from here
            id: dateButton
            width: dateRow.width + 14; height: 22; radius: Theme.t.radiusControl
            color: bar.todayOpen || hovered ? Theme.t.hover : "transparent"
            anchors.verticalCenter: parent.verticalCenter
            onClicked: bar.today()
            Row {
                id: dateRow; anchors.centerIn: parent; spacing: 8
                Label {
                    id: clock; font.weight: Font.DemiBold; font.pixelSize: 12; anchors.verticalCenter: parent.verticalCenter
                    Timer { interval: 15000; running: true; repeat: true; triggeredOnStart: true
                        onTriggered: { clock.text = Qt.formatTime(new Date(), Settings.clock24 ? "HH:mm" : "h:mm AP"); date.text = Settings.barDate ? Qt.formatDate(new Date(), "ddd, MMM d") : "" } }
                }
                Label { id: date; font.pixelSize: 12; anchors.verticalCenter: parent.verticalCenter; visible: text !== "" }
            }
            // the Ring: as Today opens, a light in the realm's colours runs once round the date
            Shape {
                id: dateRing
                anchors.centerIn: parent; width: parent.width + 4; height: parent.height + 4; opacity: 0
                preferredRendererType: Shape.CurveRenderer
                readonly property real perimeter: 2 * (width + height)
                property real drawn: 0
                function run() { ringAnim.restart() }
                ShapePath {
                    strokeColor: Theme.t.glowA; strokeWidth: 2; fillColor: "transparent"; capStyle: ShapePath.RoundCap
                    strokeStyle: ShapePath.DashLine; dashPattern: [dateRing.drawn / 2, dateRing.perimeter / 2]
                    PathRectangle { x: 1; y: 1; width: dateRing.width - 2; height: dateRing.height - 2; radius: 9 }
                }
                SequentialAnimation {
                    id: ringAnim
                    ScriptAction { script: { dateRing.opacity = 1; dateRing.drawn = 0 } }
                    NumberAnimation { target: dateRing; property: "drawn"; to: dateRing.perimeter; duration: 300; easing.type: Easing.OutCubic }
                    NumberAnimation { target: dateRing; property: "opacity"; to: 0; duration: 260 }
                }
            }
        }
        Rectangle { width: 1; height: 12; color: Theme.t.line; anchors.verticalCenter: parent.verticalCenter; visible: bar.appName !== "" }
        Pressable {   // the app in front: its icon, its name; its menu opens from here
            id: appButton
            visible: bar.appName !== ""; width: appRow.width + 16; height: 22; radius: Theme.t.radiusControl
            color: (bar.menuOpen && bar.menuGroup === "") || hovered ? Theme.t.hover : "transparent"
            anchors.verticalCenter: parent.verticalCenter; onClicked: bar.appMenu("")
            Row {
                id: appRow; anchors.centerIn: parent; spacing: 5
                AppIcon { visible: bar.front !== null; size: 14; anchors.verticalCenter: parent.verticalCenter; name: bar.front ? bar.front.name : ""; glyph: bar.front ? bar.front.glyph : ""; image: bar.front ? bar.front.image : ""; own: bar.front ? bar.front.own || "" : ""; web: bar.front ? bar.front.web : false }
                Label { id: app; text: bar.appName; font.weight: Font.DemiBold; font.pixelSize: 12; anchors.verticalCenter: parent.verticalCenter }
                Glyph { visible: !bar.rowMenus; name: "down"; size: 10; ink: Theme.t.text; opacity: 0.7; anchors.verticalCenter: parent.verticalCenter }
            }
        }
        Repeater {   // a row of menus: the app's groups along the bar
            id: groupRep
            model: bar.rowMenus ? (Status.menus.groups || []) : []
            Pressable { required property var modelData; width: ml.width + 14; height: 22; radius: Theme.t.radiusControl; anchors.verticalCenter: parent.verticalCenter
                color: (bar.menuOpen && bar.menuGroup === modelData.name) || hovered ? Theme.t.hover : "transparent"; onClicked: bar.appMenu(modelData.name)
                Label { id: ml; anchors.centerIn: parent; text: modelData.name; font.pixelSize: 12 } }
        }
    }

    Row {   // the screen, the camera, the microphone: a dot for each while it's in use (it can't be turned off)
        anchors { right: searchButton.left; rightMargin: 6; verticalCenter: parent.verticalCenter }
        spacing: 5
        Repeater {
            model: [["screen", "#FF5A5F", "Your screen is being shared"], ["camera", "#3DD6B5", "The camera is on"], ["mic", "#FFB340", "The microphone is on"]]
            Rectangle {
                required property var modelData
                visible: !!Live.privacy[modelData[0]]
                width: 8; height: 8; radius: 4; color: modelData[1]
                anchors.verticalCenter: parent.verticalCenter
                Rectangle { anchors.centerIn: parent; width: 16; height: 16; radius: 8; color: parent.color; opacity: 0.25; z: -1 }
                Accessible.name: modelData[2]
            }
        }
    }
    Pressable {   // Search everything
        id: searchButton
        anchors { right: statusPill.left; rightMargin: 4; verticalCenter: parent.verticalCenter }
        width: 28; height: 22; radius: 11
        onClicked: bar.search()
        Glyph { anchors.centerIn: parent; name: "search"; size: 14 }
    }
    Pressable {
        id: statusPill
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
            Rectangle {   // notifications are waiting in the Control Centre
                visible: Status.waiting; width: 7; height: 7; radius: 4; color: Theme.t.accent; anchors.verticalCenter: parent.verticalCenter
                Rectangle { anchors.centerIn: parent; width: 15; height: 15; radius: 8; color: Theme.t.accent; opacity: 0.25; z: -1 }
            }
            // The control-centre mark: a rounded outline.
            Rectangle { width: 16; height: 11; radius: 3; color: "transparent"; border.width: 1.5; border.color: Theme.t.text; anchors.verticalCenter: parent.verticalCenter }
        }
    }
}
