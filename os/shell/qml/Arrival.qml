import QtQuick

// Arriving on the desktop: the sign-in screen's island carries on for a moment where it was (your picture in its ring
// of light, your name, the line of light) while the desktop's pieces come in, then it fades away. The wallpaper behind
// is the same scene, coming to rest. Nothing here takes clicks.
Item {
    id: arrival
    property bool playing: true
    readonly property real k: Math.max(0.75, Math.min(1.8, height / 1000))
    signal finished()
    signal leaving()                       // the island starts to fade: time for the desktop's pieces to come in
    visible: opacity > 0
    opacity: 1
    Timer { running: arrival.playing; interval: 1500; onTriggered: { arrival.leaving(); leave.start() } }
    ParallelAnimation { id: leave
        NumberAnimation { target: arrival; property: "opacity"; to: 0; duration: 700; easing.type: Easing.InOutQuad }
        NumberAnimation { target: card; property: "scale"; to: 0.94; duration: 700; easing.type: Easing.InCubic }
        onFinished: arrival.finished() }

    Rectangle {
        id: card
        objectName: "arrivalCard"
        width: 360 * arrival.k; height: col.height + 52 * arrival.k; radius: 32 * arrival.k
        x: (parent.width - width) / 2; y: parent.height * 0.67 - height / 2 - 10 * arrival.k
        color: Qt.rgba(0.07, 0.08, 0.10, 0.72); border.width: 1; border.color: Qt.rgba(1, 1, 1, 0.13)
        Column {
            id: col
            y: 26 * arrival.k; x: 24 * arrival.k; width: parent.width - 48 * arrival.k; spacing: 12 * arrival.k
            Item { width: 96 * arrival.k; height: width; anchors.horizontalCenter: parent.horizontalCenter
                Rectangle { anchors.fill: parent; radius: width / 2
                    gradient: Gradient { orientation: Gradient.Horizontal; GradientStop { position: 0; color: Theme.t.glowA } GradientStop { position: 1; color: Theme.t.glowB } }
                    RotationAnimator on rotation { from: 0; to: 360; duration: 1600; loops: Animation.Infinite; running: arrival.visible } }
                Rectangle { id: disc; anchors.fill: parent; anchors.margins: Math.max(2, parent.width * 0.035); radius: width / 2; clip: true
                    gradient: Gradient { GradientStop { position: 0; color: Qt.lighter(Theme.t.dark ? Theme.t.tintA : "#24343A", 2.6) } GradientStop { position: 1; color: Qt.lighter(Theme.t.dark ? Theme.t.tintB : "#262838", 2.2) } }
                    Text { anchors.centerIn: parent; visible: Me.face === ""; color: "white"; font.pixelSize: parent.width * 0.36; font.weight: Font.DemiBold
                        text: { var n = (Me.name || "?").trim().split(/\s+/); return (n[0][0] + (n.length > 1 ? n[n.length - 1][0] : "")).toUpperCase() } }
                    Canvas { anchors.fill: parent; visible: Me.face !== ""
                        Component.onCompleted: if (Me.face) loadImage(Me.face)
                        onImageLoaded: requestPaint()
                        onPaint: { var c = getContext("2d"); c.reset(); if (!Me.face || !isImageLoaded(Me.face)) return
                            c.beginPath(); c.arc(width / 2, height / 2, width / 2, 0, Math.PI * 2); c.clip(); c.drawImage(Me.face, 0, 0, width, height) } } } }
            Text { anchors.horizontalCenter: parent.horizontalCenter; text: Me.name; color: "#F5F7FA"; font.pixelSize: 21 * arrival.k; font.weight: Font.DemiBold }
            Item { width: 1; height: 2 * arrival.k }
            Rectangle { width: parent.width; height: 44 * arrival.k; radius: height / 2; color: Qt.rgba(1, 1, 1, 0.09); border.width: 1; border.color: Qt.rgba(1, 1, 1, 0.16)
                Item { anchors { fill: parent; leftMargin: 22 * arrival.k; rightMargin: 22 * arrival.k } clip: true
                    Rectangle { anchors.verticalCenter: parent.verticalCenter; width: parent.width; height: 3 * arrival.k; radius: height / 2; color: Qt.rgba(1, 1, 1, 0.14) }
                    Rectangle { id: runner; anchors.verticalCenter: parent.verticalCenter; width: parent.width * 0.45; height: 3 * arrival.k; radius: height / 2
                        gradient: Gradient { orientation: Gradient.Horizontal
                            GradientStop { position: 0; color: "transparent" } GradientStop { position: 0.5; color: Theme.t.glowA } GradientStop { position: 1; color: Theme.t.glowB } }
                        NumberAnimation on x { from: -runner.width; to: runner.parent.width; duration: 1100; loops: Animation.Infinite; easing.type: Easing.InOutSine; running: arrival.visible } } } }
            Text { width: parent.width; horizontalAlignment: Text.AlignHCenter; text: Me.first ? "Welcome" : "Welcome back"; color: Qt.rgba(1, 1, 1, 0.62); font.pixelSize: 12.5 * arrival.k }
        }
    }
}
