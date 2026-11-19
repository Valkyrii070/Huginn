import QtQuick

// Weather, "the sky": the light comes from above; now is large in the middle, the day runs across, the week sits below.
GlassWindow {
    id: win
    title: "Weather"; width: 980; height: 680; glow: "top"
    property bool adding: false
    readonly property var now: Backend.now
    readonly property bool has: now.temp !== undefined
    Connections { target: Backend; function onFailed(msg) { toast.say(msg, true) } }
    function addPlace() { adding = true; finder.text = ""; finder.focusIn() }
    function refresh() { Backend.refresh() }
    function flipUnit() { Backend.flipUnit() }

    islands: [
        Island { anchors.horizontalCenter: parent.horizontalCenter; y: 12
            Repeater { model: Backend.places
                Seg { required property var modelData; required property int index; text: modelData.name; on: index === Backend.current; onClicked: Backend.choose(index) } }
            Seg { icon: "plus"; tip: "Add a place"; onClicked: { win.adding = true; finder.text = ""; finder.focusIn() } } },
        Island { anchors { right: parent.right; rightMargin: 12 } y: 12
            Seg { text: Backend.unit === "f" ? "°F" : "°C"; tip: "Switch units"; onClicked: Backend.flipUnit() }
            Seg { icon: "history"; tip: "Refresh"; opacity: Backend.loading ? 0.4 : 1; onClicked: Backend.refresh() } },
        Toast { id: toast; anchors { horizontalCenter: parent.horizontalCenter; bottom: parent.bottom; bottomMargin: 18 } },
        Item { anchors.fill: parent; z: 20; visible: win.adding
            Rectangle { anchors.fill: parent; radius: win.r; color: "#66000000"; MouseArea { anchors.fill: parent; acceptedButtons: Qt.AllButtons; onClicked: win.adding = false } }
            Rectangle { anchors.centerIn: parent; width: 440; height: 150 + Math.max(1, Backend.matches.length) * 38 + (Backend.places.length ? 36 : 0); radius: 16; color: Theme.t.menu_bg; border.width: 1; border.color: Theme.t.menu_border
                MouseArea { anchors.fill: parent }
                Label { x: 22; y: 20; font.pixelSize: 16; font.weight: Font.DemiBold; text: "Add a place" }
                TextBox { id: finder; x: 22; y: 54; width: parent.width - 44; placeholder: "A town or city"; onEdited: look.restart(); onAccepted: Backend.search(text); Keys.onEscapePressed: win.adding = false }
                Timer { id: look; interval: 450; onTriggered: Backend.search(finder.text) }
                Column { x: 16; y: 100; width: parent.width - 32
                    Label { visible: Backend.matches.length === 0; x: 6; height: 38; verticalAlignment: Text.AlignVCenter; secondary: true; font.pixelSize: 12; width: parent.width - 12; wrapMode: Text.WordWrap
                        text: Backend.searching ? "Looking…" : finder.text.length < 2 ? "Huginn never works out where you are. Only the place you pick is sent, to open-meteo.com." : "No place by that name." }
                    Repeater { model: Backend.matches
                        Pressable { required property var modelData; required property int index; width: parent.width; height: 38; radius: 9; onClicked: { Backend.add(index); win.adding = false }
                            Label { x: 10; anchors.verticalCenter: parent.verticalCenter; text: modelData.name; font.weight: Font.Medium }
                            Label { anchors { right: parent.right; rightMargin: 10; verticalCenter: parent.verticalCenter } width: parent.width - 150; horizontalAlignment: Text.AlignRight; elide: Text.ElideRight; text: modelData.region; secondary: true; font.pixelSize: 12 } } } }
                Btn { visible: Backend.places.length > 0; x: 22; anchors { bottom: parent.bottom; bottomMargin: 18 } text: "Remove " + (Backend.places.length ? Backend.places[Backend.current].name : ""); onClicked: { Backend.forget(Backend.current); win.adding = false } }
                Btn { anchors { right: parent.right; rightMargin: 22; bottom: parent.bottom; bottomMargin: 18 } text: "Done"; onClicked: win.adding = false } } }
    ]

    Column { visible: !win.has; anchors.centerIn: parent; spacing: 12
        Glyph { name: "cloudsun"; size: 64; ink: Theme.t.accent; anchors.horizontalCenter: parent.horizontalCenter }
        Label { anchors.horizontalCenter: parent.horizontalCenter; font.pixelSize: 20; font.weight: Font.DemiBold
            text: Backend.places.length === 0 ? "Where would you like the weather for?" : Backend.loading ? "Getting the forecast…" : "No forecast yet" }
        Label { visible: Backend.error !== ""; anchors.horizontalCenter: parent.horizontalCenter; secondary: true; text: Backend.error }
        Btn { visible: Backend.places.length === 0; anchors.horizontalCenter: parent.horizontalCenter; primary: true; text: "Add a Place"; onClicked: { win.adding = true; finder.focusIn() } }
        Btn { visible: Backend.places.length > 0 && !Backend.loading; anchors.horizontalCenter: parent.horizontalCenter; text: "Try Again"; onClicked: Backend.refresh() } }

    // ---------------- now
    Column { visible: win.has; anchors.horizontalCenter: parent.horizontalCenter; y: 74; spacing: 2
        Label { anchors.horizontalCenter: parent.horizontalCenter; secondary: true; font.pixelSize: 13; text: win.now.region || "" }
        Row { anchors.horizontalCenter: parent.horizontalCenter; spacing: 18
            Glyph { name: win.now.icon || "cloud"; size: 84; ink: Theme.t.accent; anchors.verticalCenter: parent.verticalCenter }
            Label { text: (win.now.temp !== undefined ? win.now.temp : "") + "°"; font.pixelSize: 108; font.weight: Font.Light } }
        Label { anchors.horizontalCenter: parent.horizontalCenter; font.pixelSize: 20; font.weight: Font.Medium; text: win.now.text || "" }
        Label { anchors.horizontalCenter: parent.horizontalCenter; secondary: true; text: "Feels like " + win.now.feels + "°  ·  High " + win.now.high + "°  ·  Low " + win.now.low + "°" }
        Item { width: 1; height: 10 }
        Row { anchors.horizontalCenter: parent.horizontalCenter; spacing: 26
            Repeater { model: [["wind", win.now.wind, "Wind"], ["drop", win.now.humidity, "Humidity"], ["sun", win.now.sunrise, "Sunrise"], ["moon", win.now.sunset, "Sunset"]]
                Row { required property var modelData; spacing: 7
                    Glyph { name: modelData[0]; size: 16; ink: Theme.t.text_secondary; anchors.verticalCenter: parent.verticalCenter }
                    Column { Label { text: modelData[1] || ""; font.pixelSize: 13; font.weight: Font.Medium } Label { text: modelData[2]; secondary: true; font.pixelSize: 10 } } } } }
    }
    // ---------------- the next day, hour by hour
    Rectangle { visible: win.has; x: 14; y: parent.height - 314; width: parent.width - 28; height: 118; radius: 16; color: Theme.t.island; border.width: 1; border.color: Theme.t.islandLine
        ListView { id: hourly; anchors { fill: parent; margins: 6 } orientation: ListView.Horizontal; clip: true; model: Backend.hours
            delegate: Item { required property var modelData; required property int index; width: 62; height: hourly.height
                Rectangle { visible: index === 0; anchors.fill: parent; radius: 12; color: Qt.rgba(win.tintColor.r, win.tintColor.g, win.tintColor.b, 0.16) }
                Column { anchors.centerIn: parent; spacing: 5
                    Label { anchors.horizontalCenter: parent.horizontalCenter; text: modelData.time; font.pixelSize: 11; secondary: index !== 0; font.weight: index === 0 ? Font.DemiBold : Font.Normal }
                    Glyph { anchors.horizontalCenter: parent.horizontalCenter; name: modelData.icon; size: 22; ink: index === 0 ? Theme.t.accent : Theme.t.icon }
                    Label { anchors.horizontalCenter: parent.horizontalCenter; text: modelData.temp + "°"; font.pixelSize: 15; font.weight: Font.Medium }
                    Label { anchors.horizontalCenter: parent.horizontalCenter; text: modelData.rain >= 15 ? modelData.rain + "%" : " "; font.pixelSize: 10; color: Theme.t.accent } } } } }
    // ---------------- the week
    Rectangle { visible: win.has; x: 14; y: parent.height - 186; width: parent.width - 28; height: 150; radius: 16; color: Theme.t.island; border.width: 1; border.color: Theme.t.islandLine
        Row { anchors { fill: parent; margins: 6 }
            Repeater { model: Backend.days
                Item { required property var modelData; required property int index; width: parent.width / 8; height: parent.height
                    Label { y: 6; anchors.horizontalCenter: parent.horizontalCenter; text: modelData.day; font.pixelSize: 12; font.weight: index === 0 ? Font.DemiBold : Font.Normal; secondary: index !== 0 }
                    Glyph { y: 26; anchors.horizontalCenter: parent.horizontalCenter; name: modelData.icon; size: 22; ink: index === 0 ? Theme.t.accent : Theme.t.icon }
                    Label { y: 52; anchors.horizontalCenter: parent.horizontalCenter; text: modelData.rain >= 15 ? modelData.rain + "%" : " "; font.pixelSize: 10; color: Theme.t.accent }
                    Item { id: bar; x: parent.width / 2 - 26; y: 70; width: 52; height: 62   // where this day's low and high sit within the week's range
                        Label { x: 0; anchors.verticalCenter: parent.verticalCenter; width: 22; horizontalAlignment: Text.AlignRight; text: modelData.low + "°"; font.pixelSize: 11; secondary: true; y: 0 }
                        Rectangle { x: 26; width: 5; height: parent.height; radius: 3; color: Theme.t.group
                            Rectangle { width: 5; radius: 3; y: parent.height * (1 - modelData.to); height: Math.max(6, parent.height * (modelData.to - modelData.from)); color: Theme.t.accent } }
                        Label { x: 34; y: Math.max(0, Math.min(parent.height - 14, parent.height * (1 - modelData.to) - 2)); text: modelData.high + "°"; font.pixelSize: 11; font.weight: Font.Medium } } } } } }
    Label { visible: win.has; anchors { horizontalCenter: parent.horizontalCenter; bottom: parent.bottom; bottomMargin: 12 } secondary: true; font.pixelSize: 11
        color: Backend.error !== "" || win.now.old ? Theme.t.danger : Theme.t.text_secondary
        text: (Backend.error !== "" ? Backend.error + " " : "") + (Backend.loading ? "Updating…" : (win.now.updated || "")) + " · Forecast by Open-Meteo" }
}
