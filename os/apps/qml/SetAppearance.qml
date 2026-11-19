import QtQuick

// Appearance: light or dark, and the realm (the colour of everything).
Column {
    id: pg
    width: parent ? parent.width : 600; spacing: 18
    readonly property var look: Backend.look
    function realmLabel(id) { var r = (Theme.t.realms || []).filter(function (x) { return x.id === id }); return r.length ? r[0].label : id }
    Component.onCompleted: Backend.load("look")
    Row { spacing: 14
        Repeater { model: [["false", "Light", "#F4F5F8", "#DDE1E8", "#14171C"], ["true", "Dark", "#1B1E26", "#0E1015", "#F3F4F6"]]
            Column { required property var modelData; spacing: 8
                Rectangle { width: 200; height: 128; radius: 16; border.width: (Theme.t.dark ? "true" : "false") === modelData[0] ? 3 : 1
                    border.color: (Theme.t.dark ? "true" : "false") === modelData[0] ? Theme.t.accent : Theme.t.separator
                    gradient: Gradient { GradientStop { position: 0; color: modelData[2] } GradientStop { position: 1; color: modelData[3] } }
                    Rectangle { x: 18; y: 22; width: 120; height: 76; radius: 10; color: modelData[0] === "true" ? "#2A2E38" : "#FFFFFF"; border.width: 1; border.color: "#22000000"
                        Row { x: 8; y: 8; spacing: 4; Repeater { model: ["#FF5F57", "#FEBC2E", "#28C840"]; Rectangle { required property string modelData; width: 7; height: 7; radius: 4; color: modelData } } }
                        Rectangle { x: 8; y: 26; width: 70; height: 6; radius: 3; color: Theme.t.accent }
                        Rectangle { x: 8; y: 40; width: 96; height: 5; radius: 3; color: modelData[4]; opacity: 0.25 }
                        Rectangle { x: 8; y: 52; width: 80; height: 5; radius: 3; color: modelData[4]; opacity: 0.25 } }
                    MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: Theme.setDark(modelData[0] === "true") } }
                Label { anchors.horizontalCenter: parent.horizontalCenter; text: modelData[1]; font.weight: (Theme.t.dark ? "true" : "false") === modelData[0] ? Font.DemiBold : Font.Normal } } } }
    SetCard { title: "Realm"; note: "A realm sets the accent colour, the window tint and the wallpaper everywhere at once: each has its own living scene. Each app still keeps its own colour."
        Flow { width: parent.width; padding: 14; spacing: 12
            Repeater { model: Theme.t.realms
                Column { required property var modelData; spacing: 6
                    objectName: "realm-" + modelData.id
                    Rectangle { width: 168; height: 105; radius: Theme.t.radiusTile; clip: true
                        border.width: Theme.t.realm === modelData.id ? 3 : 1; border.color: Theme.t.realm === modelData.id ? Theme.t.accent : Theme.t.separator
                        gradient: Gradient { orientation: Gradient.Horizontal; GradientStop { position: 0; color: modelData.a } GradientStop { position: 1; color: modelData.b } }
                        // the realm's own scene (a still of its live wallpaper)
                        Image { anchors.fill: parent; anchors.margins: parent.border.width; visible: status === Image.Ready; fillMode: Image.PreserveAspectCrop
                            source: Theme.t.liveDir ? Theme.t.liveDir + "stills/" + modelData.id + ".jpg" : ""; sourceSize.width: 336; asynchronous: true }
                        Rectangle { visible: pg.look.loginRealm === modelData.id; anchors { left: parent.left; bottom: parent.bottom; margins: 8 }
                            width: signLabel.width + 14; height: 20; radius: 10; color: "#B3101418"
                            Label { id: signLabel; anchors.centerIn: parent; text: "Sign-in screen"; color: "#FFFFFF"; font.pixelSize: 10; font.weight: Font.DemiBold } }
                        MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: Theme.setRealm(modelData.id) } }
                    Label { text: modelData.label; anchors.horizontalCenter: parent.horizontalCenter; font.weight: Theme.t.realm === modelData.id ? Font.DemiBold : Font.Normal } } } } }
    SetCard { title: "Wallpaper"
        SetRow { glyph: "sparkle"; tile: Theme.t.accent; title: "Live wallpaper"; sub: "The realm's scene keeps moving on the desktop too, slowly. It always moves on the sign-in screen, and comes to rest after you sign in. Uses a little more power."
            Toggle { objectName: "liveToggle"; on: Settings.liveWallpaper; enabled: !Settings.reduceMotion; onToggled: function (v) { Settings.set("liveWallpaper", v ? "true" : "false") } } }
        SetRow { visible: Settings.reduceMotion; glyph: "info"; tile: "#64748B"; title: "Reduce motion is on"; sub: "The wallpaper stays still everywhere, as Accessibility asks." }
        SetRow { glyph: "lock"; tile: "#0EA5E9"; title: "Sign-in screen"; sub: pg.look.loginRealm === Theme.t.realm ? "It wears " + pg.realmLabel(Theme.t.realm) + ", like your desktop."
                                                                                   : "It wears " + pg.realmLabel(pg.look.loginRealm || "aurora") + ". Everyone on this computer sees it."
            Btn { objectName: "useOnLogin"; text: "Use " + pg.realmLabel(Theme.t.realm); visible: pg.look.loginRealm !== Theme.t.realm && pg.look.canChange !== false
                onClicked: Backend.setLoginRealm(Theme.t.realm) } } }
}
