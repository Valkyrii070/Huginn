import QtQuick

// The desktop's cards: the weather for your first place in Weather, which apps used the camera, microphone, screen
// or location this week (Privacy Report), and what's next in Calendar and Reminders. All of it comes from those
// apps' own files (Glance in huginn_shell.py); with nothing there yet, each card says how to fill it. A tap opens
// the app.
Column {
    width: 270; spacing: 14
    component Card: Glass { width: parent.width; radius: 16; wallpaperOnly: true }   // never frosts a window
    component Title: Label { secondary: true; font.pixelSize: 11; font.weight: Font.DemiBold }
    component Tap: MouseArea { property string app: ""; anchors.fill: parent; cursorShape: Qt.PointingHandCursor
        onClicked: Apps.launch("python3 /usr/share/huginn-apps/huginn_app.py " + app) }
    readonly property var w: Glance.weather
    readonly property bool hasWeather: w.temp !== undefined && w.temp !== ""

    Card {
        objectName: "weatherCard"
        height: hasWeather ? (w.days && w.days.length ? 150 : 100) : 86
        Tap { app: "weather" }
        Title { x: 16; y: 16; text: w.place ? w.place.toUpperCase() : "WEATHER" }
        Label { visible: !hasWeather; x: 16; y: 38; width: parent.width - 32; wrapMode: Text.WordWrap; secondary: true; font.pixelSize: 12
            text: w.place ? "Open Weather to get the forecast." : "Pick your place in Weather to see its forecast here." }
        Label { visible: hasWeather; x: 16; y: 36; text: w.temp || ""; font.pixelSize: 40; font.weight: Font.Light }
        Label { visible: hasWeather; anchors { right: parent.right; rightMargin: 16 } y: 44; secondary: true; font.pixelSize: 12; horizontalAlignment: Text.AlignRight
            text: (w.words || "") + (w.high ? "\n↑ " + w.high + "  ↓ " + w.low : "") + (w.stale ? "\n" + w.stale : "") }
        Rectangle { visible: hasWeather && w.days && w.days.length > 0; x: 16; y: 98; width: parent.width - 32; height: 1; color: Theme.t.line }
        Row { visible: hasWeather; x: 16; y: 108; width: parent.width - 32
            Repeater { model: hasWeather ? w.days : []
                Column { required property var modelData; width: parent.width / 3
                    Label { text: modelData.day; secondary: true; font.pixelSize: 12; anchors.horizontalCenter: parent.horizontalCenter }
                    Label { text: modelData.temp; font.weight: Font.DemiBold; font.pixelSize: 12; anchors.horizontalCenter: parent.horizontalCenter } } } }
    }
    Card {
        objectName: "privacyCard"
        height: Math.max(82, privacyLine.height + 54)
        Tap { app: "privacy" }
        Title { x: 16; y: 16; text: "PRIVACY REPORT" }
        Rectangle { x: 16; y: 44; width: 26; height: 26; radius: 13; color: "transparent"; border.width: 2; border.color: Theme.t.accent
            Rectangle { anchors.centerIn: parent; width: 10; height: 10; radius: 5; color: Theme.t.accent } }
        Label { id: privacyLine; x: 56; y: 40; width: parent.width - 72; wrapMode: Text.WordWrap; lineHeight: 1.2; font.pixelSize: 12
            text: Glance.privacy.line || "" }
    }
    Card {
        objectName: "nextCard"
        height: 46 + Math.max(1, Glance.upNext.length) * 46
        Title { x: 16; y: 16; text: "UP NEXT" }
        Label { visible: Glance.upNext.length === 0; x: 16; y: 40; width: parent.width - 32; wrapMode: Text.WordWrap; secondary: true; font.pixelSize: 12
            text: "Nothing coming up. Events from Calendar and Reminders with a day show here." }
        Column { x: 16; y: 38; width: parent.width - 32; spacing: 6
            Repeater { model: Glance.upNext
                Rectangle { required property var modelData; width: parent.width; height: 40; radius: Theme.t.radiusCard; color: Theme.t.hover
                    Tap { app: modelData.when.indexOf("Reminders") >= 0 ? "reminders" : "calendar" }
                    Column { x: 10; width: parent.width - 20; anchors.verticalCenter: parent.verticalCenter
                        Label { text: modelData.title; font.pixelSize: 13; width: parent.width; elide: Text.ElideRight }
                        Label { text: modelData.when; secondary: true; font.pixelSize: 11 } } } } }
    }
}
