import QtQuick

// A file as the dock's stacks draw it: a picture shows itself; anything else is a page with the badge of the app
// that opens it (a disc for disc images, a folder for folders). `filling` (0…1, or -1 when unknown): it's still
// arriving, and fills up from the bottom.
Item {
    id: art
    property var file: ({})
    property int size: 40
    property real filling: file && file.partial ? (file.progress === undefined ? -1 : file.progress) : 1
    width: size; height: size
    readonly property string kind: file && file.kind ? file.kind : "other"
    Rectangle {   // the page (or the picture's frame)
        id: page
        anchors.centerIn: parent
        width: art.kind === "image" ? art.size : Math.round(art.size * 0.78); height: art.kind === "image" ? Math.round(art.size * 0.78) : art.size
        radius: Math.max(3, art.size * 0.12); clip: true
        color: art.kind === "disc" ? "#2A2F37" : art.kind === "folder" ? "#3AA0F0" : "#F5F6F8"
        border.width: 1; border.color: Qt.rgba(0, 0, 0, 0.18)
        Image { visible: art.kind === "image" && !!art.file.thumb; anchors.fill: parent; source: art.kind === "image" ? (art.file.thumb || "") : ""; fillMode: Image.PreserveAspectCrop; sourceSize: Qt.size(128, 128); asynchronous: true }
        Rectangle { visible: art.kind === "image" && !art.file.thumb; anchors.fill: parent; gradient: Gradient { GradientStop { position: 0; color: "#3DD6B5" } GradientStop { position: 1; color: "#7B61FF" } } }
        Column {   // a page's lines
            visible: art.kind !== "image" && art.kind !== "disc" && art.kind !== "folder"
            x: page.width * 0.16; y: page.height * 0.16; spacing: Math.max(1.5, art.size * 0.06)
            Rectangle { width: page.width * 0.5; height: Math.max(1.5, art.size * 0.05); radius: 1; color: "#7B8CFF" }
            Repeater { model: 4; Rectangle { width: page.width * (index % 2 ? 0.55 : 0.68); height: Math.max(1, art.size * 0.035); radius: 1; color: "#C9CED6" } }
        }
        Rectangle {   // a disc
            visible: art.kind === "disc"; anchors.centerIn: parent; width: page.width * 0.7; height: width; radius: width / 2
            gradient: Gradient { GradientStop { position: 0; color: "#D7DCE4" } GradientStop { position: 1; color: "#8E98A8" } }
            Rectangle { anchors.centerIn: parent; width: parent.width * 0.26; height: width; radius: width / 2; color: "#2A2F37" }
        }
        Rectangle {   // still arriving: the part not yet here is dimmed; unknown: a light passes through
            visible: art.filling < 1
            anchors { left: parent.left; right: parent.right; top: parent.top }
            height: art.filling >= 0 ? parent.height * (1 - art.filling) : parent.height
            color: Qt.rgba(0.05, 0.06, 0.08, art.filling >= 0 ? 0.55 : 0.35)
        }
        Rectangle {
            id: sweep
            visible: art.filling < 0 && !(art.file && art.file.stalled); width: page.width * 0.5; height: page.height * 1.6; rotation: 20; y: -page.height * 0.3
            gradient: Gradient { orientation: Gradient.Horizontal; GradientStop { position: 0; color: "transparent" } GradientStop { position: 0.5; color: Qt.alpha(Theme.t.glowA, 0.55) } GradientStop { position: 1; color: "transparent" } }
            NumberAnimation on x { from: -page.width * 0.6; to: page.width * 1.1; duration: 1300; loops: Animation.Infinite; running: sweep.visible }
        }
    }
    Image {   // the app that opens it
        visible: art.kind !== "image" && art.kind !== "folder" && !!art.file.badgeUrl && art.size >= 24
        width: Math.round(art.size * 0.46); height: width
        anchors { right: parent.right; bottom: parent.bottom; rightMargin: -art.size * 0.02; bottomMargin: -art.size * 0.02 }
        source: art.file && art.file.badgeUrl ? art.file.badgeUrl : ""; sourceSize: Qt.size(64, 64); smooth: true; mipmap: true
    }
}
