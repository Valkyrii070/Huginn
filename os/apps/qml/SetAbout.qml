import QtQuick

// About: the logo, the version, and this computer.
Column {
    id: pg
    width: parent ? parent.width : 600; spacing: 18
    readonly property var a: Backend.about
    Rectangle { width: parent.width; height: 160; radius: Theme.t.radiusCard; color: Theme.t.group; border.width: 1; border.color: Theme.t.separator; clip: true
        Rectangle { x: -60; y: -80; width: 320; height: 320; radius: 160; opacity: 0.35
            gradient: Gradient { GradientStop { position: 0; color: Theme.t.glowA } GradientStop { position: 1; color: "transparent" } } }
        Image { visible: osLogo !== ""; x: 34; width: 92; height: 92; anchors.verticalCenter: parent.verticalCenter; source: osLogo; sourceSize: Qt.size(184, 184) }
        Rectangle { visible: osLogo === ""; x: 34; width: 92; height: 92; radius: 46; anchors.verticalCenter: parent.verticalCenter
            gradient: Gradient { GradientStop { position: 0; color: Theme.t.glowA } GradientStop { position: 1; color: Theme.t.glowB } } }
        Column { x: 150; anchors.verticalCenter: parent.verticalCenter; spacing: 4
            Label { text: "Huginn OS"; font.pixelSize: 30; font.weight: Font.Light }
            Label { text: "Version 0.1 · built on Ubuntu 26.04 LTS"; secondary: true }
            Btn { text: "Check for Updates"; pill: true; onClicked: win.go("updates") } } }
    SetCard { title: "This computer"
        Repeater { model: pg.a.rows || []
            SetRow { required property var modelData; title: modelData.name; Label { text: modelData.value; secondary: true; width: Math.min(implicitWidth, 420); elide: Text.ElideRight } } } }
    SetCard { visible: (pg.a.used || 0) > 0; title: "Storage"
        SetRow { title: "Your files and apps"; sub: Math.round(pg.a.used * 100) + "% used"; Meter { width: 260; value: pg.a.used; fill: pg.a.used > 0.9 ? Theme.t.danger : Theme.t.accent } } }
}
