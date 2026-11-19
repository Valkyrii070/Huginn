import QtQuick

// Welcome, "tour": steps in the colour of the realm you pick; Back, progress and Next share the island.
GlassWindow {
    id: win
    title: "Welcome"; width: 780; height: 620; glow: "bottom"; padTop: 40
    property int step: Math.max(0, Math.min(4, parseInt(startPage) || 0))
    readonly property var steps: [
        ["Welcome to Huginn OS", "A calm desktop built around the Huginn browser. This short tour shows where things are. It takes about a minute, and you can skip it."],
        ["The dock is home base", "The first button opens the launcher with all your apps and a search box. Next to it are your pinned apps; web apps you install from Huginn are round. A dot means an app is running."],
        ["The top bar tells you what's happening", "Time and date on the left, then the app you're using: click its name for its menus. On the right, Wi‑Fi, battery and the control center for quick settings and notifications."],
        ["Make it yours", "A realm sets the accent colour, the window tint and the wallpaper glow everywhere at once. Pick one, and choose light or dark. You can change both later in Settings."],
        ["You're ready", "Find more apps in the App Store. Your files are in Files, and Settings has everything else. Nothing here needs a terminal."]]
    Item { anchors.fill: parent
        Rectangle { id: art; x: 24; y: 24; width: parent.width - 48; height: 250; radius: Theme.t.radiusTile; clip: true
            gradient: Gradient { GradientStop { position: 0; color: Theme.t.tintA } GradientStop { position: 1; color: Theme.t.tintB } }
            Image { visible: win.step === 0 && osLogo !== ""; anchors.centerIn: parent; width: 132; height: 132; source: osLogo; sourceSize: Qt.size(264, 264); smooth: true; mipmap: true }
            Rectangle { visible: (win.step === 0 && osLogo === "") || win.step === 4; width: 110; height: 110; radius: 55; anchors.centerIn: parent
                gradient: Gradient { GradientStop { position: 0; color: Theme.t.glowA } GradientStop { position: 1; color: Theme.t.glowB } }
                Glyph { visible: win.step === 4; anchors.centerIn: parent; name: "star"; size: 48; ink: "#FFFFFF" } }
            Row { visible: win.step === 1; anchors.centerIn: parent; spacing: 10   // a little dock
                Rectangle { width: 330; height: 64; radius: 20; color: Theme.t.popup; border.width: 1; border.color: Theme.t.line
                    Row { anchors.centerIn: parent; spacing: 10
                        Rectangle { width: 44; height: 44; radius: 12; color: Theme.t.text; Glyph { anchors.centerIn: parent; name: "apps"; size: 22; ink: Theme.t.window } }
                        Rectangle { width: 1; height: 34; color: Theme.t.line; anchors.verticalCenter: parent.verticalCenter }
                        Repeater { model: [[Theme.t.glowA, 12, true], ["#2361AE", 12, false], ["#3A4047", 12, true], ["#563AD1", 22, false], ["#AE4518", 22, false]]
                            Rectangle { required property var modelData; width: 44; height: 44; radius: modelData[1]; color: modelData[0]
                                Rectangle { visible: modelData[2]; width: 5; height: 5; radius: 3; color: Theme.t.accent; anchors { horizontalCenter: parent.horizontalCenter; top: parent.bottom; topMargin: 3 } } } } } }
                Rectangle { width: 64; height: 64; radius: 20; color: Theme.t.popup; border.width: 1; border.color: Theme.t.line; Glyph { anchors.centerIn: parent; name: "list"; size: 20 } } }
            Item { visible: win.step === 2; anchors.fill: parent   // a little top bar
                Rectangle { y: 40; x: 30; width: parent.width - 60; height: 38; radius: 10; color: Theme.t.popup; border.width: 1; border.color: Theme.t.line
                    Row { x: 14; anchors.verticalCenter: parent.verticalCenter; spacing: 10
                        Rectangle { width: 16; height: 16; radius: 8; gradient: Gradient { GradientStop { position: 0; color: Theme.t.glowA } GradientStop { position: 1; color: Theme.t.glowB } } }
                        Label { text: "09:41"; font.weight: Font.DemiBold } Label { text: "Wed, Nov 11" } Rectangle { width: 1; height: 12; color: Theme.t.line; anchors.verticalCenter: parent.verticalCenter }
                        Rectangle { width: 66; height: 22; radius: 7; color: Theme.t.hover; Label { anchors.centerIn: parent; text: "Huginn"; font.weight: Font.DemiBold } } }
                    Row { anchors { right: parent.right; rightMargin: 14; verticalCenter: parent.verticalCenter } spacing: 10; Glyph { name: "wifi"; size: 16 } Rectangle { width: 22; height: 11; radius: 3; color: "transparent"; border.width: 1.2; border.color: Theme.t.text; anchors.verticalCenter: parent.verticalCenter } Rectangle { width: 16; height: 11; radius: 3; color: "transparent"; border.width: 1.5; border.color: Theme.t.text; anchors.verticalCenter: parent.verticalCenter } } }
                Rectangle { x: 150; y: 84; width: 170; height: 130; radius: 10; color: Theme.t.popup; border.width: 1; border.color: Theme.t.line
                    Column { x: 8; y: 8; spacing: 2; Repeater { model: ["File", "Edit", "View", "History"]; Rectangle { required property string modelData; required property int index; width: 154; height: 26; radius: 7; color: index === 0 ? Theme.t.hover : "transparent"; Label { x: 10; anchors.verticalCenter: parent.verticalCenter; text: modelData } } } } } }
            Row { visible: win.step === 3; anchors.centerIn: parent; spacing: 14
                Repeater { model: Theme.t.realms
                    Column { required property var modelData; spacing: 8
                        Rectangle { width: 140; height: 110; radius: Theme.t.radiusTile; border.width: Theme.t.realm === modelData.id ? 4 : 1; border.color: Theme.t.realm === modelData.id ? Theme.t.text : Theme.t.line
                            gradient: Gradient { orientation: Gradient.Horizontal; GradientStop { position: 0; color: modelData.a } GradientStop { position: 1; color: modelData.b } }
                            MouseArea { anchors.fill: parent; onClicked: Theme.setRealm(modelData.id) } }
                        Label { text: modelData.label; anchors.horizontalCenter: parent.horizontalCenter; font.weight: Theme.t.realm === modelData.id ? Font.DemiBold : Font.Normal } } } } }
        Label { x: 40; y: 300; width: parent.width - 80; text: win.steps[win.step][0]; font.pixelSize: 28; font.weight: Font.Light }
        Label { x: 40; y: 346; width: Math.min(parent.width - 80, 620); text: win.steps[win.step][1]; wrapMode: Text.WordWrap; lineHeight: 1.4; secondary: true; font.pixelSize: 15 }
        Row { visible: win.step === 3; x: 40; y: 424; spacing: 8
            Btn { pill: true; primary: !Theme.t.dark; text: "Light"; onClicked: Theme.setDark(false) } Btn { pill: true; primary: Theme.t.dark; text: "Dark"; onClicked: Theme.setDark(true) } }
    }
    Island {   // the tour's own island: back, how far along, onward
        z: 6; anchors { horizontalCenter: parent.horizontalCenter; bottom: parent.bottom; bottomMargin: 14 }
        Seg { visible: win.step < win.steps.length - 1; text: "Skip Tour"; onClicked: win.close() }
        Seg { visible: win.step > 0; text: "Back"; onClicked: win.step-- }
        Row { spacing: 6; leftPadding: 10; rightPadding: 10; anchors.verticalCenter: parent.verticalCenter
            Repeater { model: win.steps.length; Rectangle { required property int index; width: index === win.step ? 20 : 8; height: 8; radius: 4; color: index === win.step ? Theme.t.accent : Theme.t.hover; Behavior on width { NumberAnimation { duration: 150 } } } } }
        Seg { on: true; text: win.step === win.steps.length - 1 ? "Done" : "Next"; onClicked: win.step === win.steps.length - 1 ? win.close() : win.step++ }
    }
}
