import QtQuick

// Users: you (picture, name, password), then everyone else who signs in here.
Column {
    id: pg
    width: parent ? parent.width : 600; spacing: 18
    readonly property var u: Backend.users
    readonly property var me: u.me || ({})
    property bool choosing: false
    function initials(n) { var p = String(n || "?").trim().split(/\s+/); return ((p[0] || "?")[0] + (p.length > 1 ? p[1][0] : "")).toUpperCase() }
    Rectangle { width: parent.width; height: 132; radius: Theme.t.radiusCard; color: Theme.t.group; border.width: 1; border.color: Theme.t.separator
        Rectangle { id: face; x: 20; width: 92; height: 92; radius: 46; anchors.verticalCenter: parent.verticalCenter; clip: true
            gradient: Gradient { GradientStop { position: 0; color: "#B39BFF" } GradientStop { position: 1; color: "#6D28D9" } }
            Label { visible: !pg.me.picture; anchors.centerIn: parent; text: pg.initials(pg.me.full || pg.me.name); color: "#FFFFFF"; font.pixelSize: 34; font.weight: Font.DemiBold }
            Image { visible: !!pg.me.picture; anchors.fill: parent; source: pg.me.picture || ""; sourceSize: Qt.size(184, 184); fillMode: Image.PreserveAspectCrop; cache: false }
            MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: pg.choosing = !pg.choosing } }
        Column { x: 132; anchors.verticalCenter: parent.verticalCenter; spacing: 4
            Label { text: pg.me.full || pg.me.name || ""; font.pixelSize: 22; font.weight: Font.Light }
            Label { text: (pg.me.name || "") + (pg.me.admin ? " · administrator" : ""); secondary: true }
            Row { spacing: 8; topPadding: 6
                Btn { text: "Change Picture"; onClicked: pg.choosing = !pg.choosing }
                Btn { text: "Change Name"; onClicked: win.ask("Your name", "How it shows on the sign-in screen and in apps.", [{ key: "n", label: "Full name", text: pg.me.full || "" }], "Save", function (v) { Backend.setFullName(v.n) }) } } } }
    SetCard { visible: pg.choosing; title: "Choose a picture"; note: "Or pick a photo from your Pictures folder; it's cropped to a square."
        Flow { width: parent.width; padding: 14; spacing: 10
            Repeater { model: pg.choosing ? Backend.pictureChoices() : []
                Rectangle { required property var modelData; width: 64; height: 64; radius: 32; clip: true; color: "transparent"; border.width: 2; border.color: hov.containsMouse ? Theme.t.accent : "transparent"
                    Image { anchors.fill: parent; anchors.margins: 2; source: modelData.url; sourceSize: Qt.size(128, 128); fillMode: Image.PreserveAspectCrop; asynchronous: true }
                    MouseArea { id: hov; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: { Backend.setPicture(modelData.path); pg.choosing = false } } } } } }
    SetCard { title: "Sign-in"
        SetRow { title: "Password"; sub: "Used to sign in, unlock the screen and make system changes"; glyph: "key"; tile: "#6D28D9"
            Btn { text: "Change…"; onClicked: win.ask("Change your password", "Use something long that you don't use anywhere else. A short sentence works well.",
                                                     [{ key: "old", label: "Current password", secret: true }, { key: "new", label: "New password", secret: true }, { key: "again", label: "New password again", secret: true }],
                                                     "Change Password", function (v) { Backend.changePassword(v.old, v.new, v.again) }) } } }
    SetCard { title: "Other people"; note: pg.me.admin ? "New people choose their own password the first time they sign in. The system asks for your password before adding or removing anyone." : "Only an administrator can add or remove people."
        Repeater { model: pg.u.others || []
            SetRow { required property var modelData; title: modelData.full; sub: modelData.name + (modelData.admin ? " · administrator" : " · standard"); picture: modelData.picture; round: true; glyph: "user"; tile: "#8B7BD8"
                Row { visible: !!pg.me.admin; spacing: 8
                    Btn { text: modelData.admin ? "Make Standard" : "Make Administrator"; onClicked: Backend.setAdmin(modelData.uid, !modelData.admin) }
                    Seg { icon: "trash"; tip: "Remove"; onClicked: { var who = modelData; win.ask("Remove " + who.full + "?", "They won't be able to sign in any more.", [{ key: "files", label: "Delete their files too", toggle: true, on: false }], "Remove",
                                                                                         function (v) { Backend.removeUser(who.uid, v.files) }, true) } } } } }
        SetRow { visible: !!pg.me.admin; title: "Add someone…"; chevron: true
            onClicked: win.ask("Add someone", "", [{ key: "full", label: "Their name" }, { key: "login", label: "Sign-in name (lower-case, no spaces)" }, { key: "admin", label: "Administrator (can change the system)", toggle: true, on: false }],
                               "Add", function (v) { Backend.addUser(v.full, v.login || v.full.toLowerCase().replace(/[^a-z0-9]/g, ""), v.admin) }) } }
}
