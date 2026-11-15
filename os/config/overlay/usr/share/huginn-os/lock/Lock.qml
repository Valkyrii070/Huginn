import QtQuick

// Huginn OS's lock screen: the sign-in screen's twin. The realm's live wallpaper moves behind a quiet clock; one
// frosted island holds your picture in its ring of light, your name and the password. Sleep and switching to
// someone else sit in a capsule at the bottom right. Left alone, all but the clock fades and the wallpaper has the
// screen; a key or a movement brings it back, and a key goes into the password. A wrong password shakes the island.
// Unlocking turns the password into a line of light, and the lock fades away.
//
// It knows nothing about how a password is checked. The host does that (KDE's screen locker in the KWin session,
// Huginn's compositor in its own session): it listens for submit(password) and answers with fail(message) or
// succeed(); `done` fires once the lock has faded and can go.
FocusScope {
    id: lock
    width: 1600; height: 1000

    // ---- from the host
    property string userName: ""
    property string realName: ""
    property string picture: ""
    property string realm: "aurora"
    property string liveDir: Qt.resolvedUrl("../live/")      // the live wallpapers sit beside this folder when installed
    property string face: "Inter"
    property bool canSuspend: false
    property bool canSwitchUser: false
    property bool ready: true                                 // false while the host can't take a password yet
    property int idleAfter: 20
    signal submit(string password)
    signal suspend()
    signal switchUser()
    signal done()

    // ---- its own state
    property bool busy: false
    property bool unlocking: false
    property string note: ""
    property bool noteBad: false
    property int tries: 0
    property bool idle: false
    readonly property var realms: ({
        aurora:     { tintA: "#0F2624", tintB: "#17192C", glowA: "#3DD6B5", glowB: "#7B61FF", accent: "#43D9B8" },
        bifrost:    { tintA: "#1D1932", tintB: "#2A1727", glowA: "#8E7BFF", glowB: "#FF7AB8", accent: "#A995FF" },
        muspelheim: { tintA: "#2C1912", tintB: "#1F1718", glowA: "#FF8A4C", glowB: "#FFC857", accent: "#FF8C50" },
        niflheim:   { tintA: "#12212F", tintB: "#171A20", glowA: "#7CC4FF", glowB: "#CFEAFF", accent: "#7CC4FF" } })
    readonly property var own: realms[realm] || realms.aurora
    readonly property color accent: own.accent
    readonly property color glowA: own.glowA
    readonly property color glowB: own.glowB
    readonly property real k: Math.max(0.75, Math.min(1.8, height / 1000))
    readonly property color ink: "#F5F7FA"
    readonly property color soft: Qt.rgba(1, 1, 1, 0.62)
    property bool capsLock: false                             // the host may tell; otherwise unknown

    // ---- what the host calls
    function fail(message) {
        lock.busy = false
        lock.tries += 1
        lock.noteBad = true
        lock.note = message || (lock.tries >= 3 ? "Still not right. Check Caps Lock and the keyboard layout." : "Wrong password. Try again.")
        pass.text = ""
        pass.forceActiveFocus()
        shake.restart()
    }
    function succeed() {
        lock.busy = false
        lock.unlocking = true
        lock.note = ""
        if (wall.item) wall.item.moving = false
        leave.start()
        leaveGuard.restart()
    }
    // Done once the fade is over, or after a moment anyway: an animation only moves while frames are drawn, and the
    // locker must never be left up after a right password because the screen stopped drawing.
    property bool finished: false
    function finish() { if (!lock.finished) { lock.finished = true; lock.done() } }
    Timer { id: leaveGuard; interval: 1500; onTriggered: lock.finish() }
    function say(message) { lock.note = message; lock.noteBad = false }
    function reset() {                                        // ready to lock again
        leave.stop(); leaveGuard.stop(); lock.finished = false
        lock.opacity = 1; lock.unlocking = false; lock.busy = false; lock.tries = 0; lock.note = ""; lock.noteBad = false
        pass.text = ""; lock.idle = false; idleTimer.restart()
        if (wall.item) wall.item.moving = true
        pass.forceActiveFocus()
    }
    function send() {
        if (lock.busy || lock.unlocking || !lock.ready || pass.text === "")
            return
        lock.wake()
        lock.busy = true
        lock.note = ""; lock.noteBad = false
        lock.submit(pass.text)
    }
    function wake() { lock.idle = false; idleTimer.restart() }

    SequentialAnimation { id: leave
        NumberAnimation { target: lock; property: "opacity"; to: 0; duration: 450; easing.type: Easing.InOutQuad }
        ScriptAction { script: lock.finish() } }
    Timer { id: idleTimer; interval: Math.max(5, lock.idleAfter) * 1000; running: !lock.busy && !lock.unlocking; onTriggered: lock.idle = true }

    // ================================================================ the wallpaper
    Rectangle { anchors.fill: parent; color: "black" }
    Item {
        id: sky
        anchors.fill: parent
        Loader { id: wall; anchors.fill: parent; source: lock.liveDir ? lock.liveDir + "LiveWallpaper.qml" : ""
            onLoaded: item.realm = Qt.binding(function () { return lock.realm }) }
        Canvas { anchors.fill: parent; visible: wall.status !== Loader.Ready
            onPaint: { var c = getContext("2d"); c.reset()
                var g = c.createLinearGradient(0, 0, 0, height); g.addColorStop(0, lock.own.tintA); g.addColorStop(0.6, "#0C1014"); g.addColorStop(1, lock.own.tintB)
                c.fillStyle = g; c.fillRect(0, 0, width, height) } }
    }
    Rectangle { anchors { left: parent.left; right: parent.right; top: parent.top } height: parent.height * 0.34
        gradient: Gradient { GradientStop { position: 0; color: Qt.rgba(0, 0, 0, 0.34) } GradientStop { position: 1; color: "transparent" } } }
    Rectangle { anchors { left: parent.left; right: parent.right; bottom: parent.bottom } height: parent.height * 0.55
        opacity: lock.idle ? 0.35 : 1
        Behavior on opacity { NumberAnimation { duration: 900; easing.type: Easing.InOutQuad } }
        gradient: Gradient { GradientStop { position: 0; color: "transparent" } GradientStop { position: 1; color: Qt.rgba(0, 0, 0, 0.5) } } }
    MouseArea { anchors.fill: parent; hoverEnabled: true; onPositionChanged: lock.wake(); onPressed: { lock.wake(); pass.forceActiveFocus() } }

    component Glass: Rectangle {
        id: glass
        color: Qt.rgba(0.07, 0.08, 0.10, frost.status === Loader.Ready ? 0.34 : 0.62)
        border.width: 1; border.color: Qt.rgba(1, 1, 1, 0.13)
        Loader { id: frost; z: -1; anchors.fill: parent; active: wall.status === Loader.Ready && wall.item !== null && !wall.item.still
            source: "Frost.qml"
            onLoaded: { item.behind = sky; item.radius = Qt.binding(function () { return glass.radius })
                item.area = Qt.binding(function () { return Qt.rect(glass.x, glass.y, glass.width, glass.height) }) } }
        Rectangle { anchors { left: parent.left; right: parent.right; top: parent.top; leftMargin: glass.radius * 0.8; rightMargin: glass.radius * 0.8 } height: 1
            gradient: Gradient { orientation: Gradient.Horizontal
                GradientStop { position: 0; color: "transparent" } GradientStop { position: 0.5; color: Qt.rgba(1, 1, 1, 0.28) } GradientStop { position: 1; color: "transparent" } } }
    }
    component Round: Rectangle {
        id: rb
        property string icon: ""
        property string label: ""
        property real size: 34 * lock.k
        signal clicked()
        width: size; height: size; radius: size / 2
        color: hit.pressed ? Qt.rgba(1, 1, 1, 0.24) : hit.containsMouse ? Qt.rgba(1, 1, 1, 0.15) : "transparent"
        Behavior on color { ColorAnimation { duration: 140 } }
        Icon { anchors.centerIn: parent; width: rb.size * 0.5; height: width; name: rb.icon; ink: lock.ink }
        Rectangle { anchors { bottom: parent.top; bottomMargin: 14 * lock.k; horizontalCenter: parent.horizontalCenter }
            width: tip.width + 18 * lock.k; height: 24 * lock.k; radius: height / 2; color: Qt.rgba(0.07, 0.08, 0.10, 0.82)
            border.width: 1; border.color: Qt.rgba(1, 1, 1, 0.12); opacity: hit.containsMouse ? 1 : 0
            Behavior on opacity { NumberAnimation { duration: 160 } }
            Text { id: tip; anchors.centerIn: parent; text: rb.label; color: lock.ink; font.family: lock.face; font.pixelSize: 11.5 * lock.k; font.weight: Font.Medium } }
        MouseArea { id: hit; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: { lock.wake(); rb.clicked() } }
    }

    // ================================================================ the clock
    Column {
        id: clock
        objectName: "lockClock"
        anchors.horizontalCenter: parent.horizontalCenter
        y: parent.height * 0.085
        opacity: lock.unlocking ? 0 : 1
        Behavior on opacity { NumberAnimation { duration: 300 } }
        property date now: new Date()
        Timer { interval: 1000; running: true; repeat: true; triggeredOnStart: true; onTriggered: clock.now = new Date() }
        readonly property bool h24: { var f = Qt.locale().timeFormat(Locale.ShortFormat); return f.indexOf("AP") < 0 && f.indexOf("ap") < 0 }
        Text { anchors.horizontalCenter: parent.horizontalCenter; color: Qt.rgba(1, 1, 1, 0.78); font.family: lock.face; font.pixelSize: 15 * lock.k
            font.weight: Font.DemiBold; font.letterSpacing: 2.2 * lock.k; font.capitalization: Font.AllUppercase; text: Qt.formatDate(clock.now, "dddd d MMMM") }
        Text { objectName: "lockTime"; anchors.horizontalCenter: parent.horizontalCenter; color: lock.ink; font.family: lock.face; font.pixelSize: 132 * lock.k
            font.weight: Font.ExtraLight; font.letterSpacing: -2 * lock.k; text: Qt.formatTime(clock.now, clock.h24 ? "HH:mm" : "h:mm") }
    }

    // ================================================================ you
    Glass {
        id: island
        objectName: "lockIsland"
        width: 360 * lock.k; height: inside.height + 52 * lock.k; radius: 32 * lock.k
        x: (parent.width - width) / 2; y: parent.height * 0.67 - height / 2
        opacity: lock.idle && !lock.busy ? 0 : 1
        Behavior on opacity { NumberAnimation { duration: 700; easing.type: Easing.InOutQuad } }
        transform: Translate { id: nudge }
        SequentialAnimation { id: shake
            NumberAnimation { target: nudge; property: "x"; to: 16; duration: 55; easing.type: Easing.OutQuad }
            NumberAnimation { target: nudge; property: "x"; to: -13; duration: 70; easing.type: Easing.InOutQuad }
            NumberAnimation { target: nudge; property: "x"; to: 9; duration: 70; easing.type: Easing.InOutQuad }
            NumberAnimation { target: nudge; property: "x"; to: -5; duration: 70; easing.type: Easing.InOutQuad }
            NumberAnimation { target: nudge; property: "x"; to: 0; duration: 90; easing.type: Easing.OutQuad } }
        Column {
            id: inside
            y: 26 * lock.k; x: 24 * lock.k; width: parent.width - 48 * lock.k; spacing: 12 * lock.k
            Item { width: 96 * lock.k; height: width; anchors.horizontalCenter: parent.horizontalCenter
                Rectangle { anchors.fill: parent; radius: width / 2
                    gradient: Gradient { orientation: Gradient.Horizontal; GradientStop { position: 0; color: lock.glowA } GradientStop { position: 1; color: lock.glowB } }
                    RotationAnimator on rotation { from: 0; to: 360; duration: 1600; loops: Animation.Infinite; running: lock.busy || lock.unlocking } }
                Rectangle { anchors.fill: parent; anchors.margins: Math.max(2, parent.width * 0.035); radius: width / 2
                    gradient: Gradient { GradientStop { position: 0; color: Qt.lighter(lock.own.tintA, 2.6) } GradientStop { position: 1; color: Qt.lighter(lock.own.tintB, 2.2) } }
                    Text { anchors.centerIn: parent; visible: pic.status !== Image.Ready; color: "white"; font.family: lock.face; font.pixelSize: parent.width * 0.36; font.weight: Font.DemiBold
                        text: { var n = (lock.realName || lock.userName || "?").trim().split(/\s+/); return (n[0][0] + (n.length > 1 ? n[n.length - 1][0] : "")).toUpperCase() } }
                    Image { id: pic; anchors.fill: parent; source: lock.picture; fillMode: Image.PreserveAspectCrop; visible: false; asynchronous: true }
                    Canvas { anchors.fill: parent; visible: pic.status === Image.Ready
                        property string src: pic.status === Image.Ready ? lock.picture : ""
                        onSrcChanged: { if (src) loadImage(src); requestPaint() }
                        onImageLoaded: requestPaint()
                        onPaint: { var c = getContext("2d"); c.reset(); if (!src || !isImageLoaded(src)) return
                            c.beginPath(); c.arc(width / 2, height / 2, width / 2, 0, Math.PI * 2); c.clip(); c.drawImage(src, 0, 0, width, height) } } } }
            Text { objectName: "lockWho"; anchors.horizontalCenter: parent.horizontalCenter; width: parent.width; horizontalAlignment: Text.AlignHCenter; elide: Text.ElideRight
                color: lock.ink; font.family: lock.face; font.pixelSize: 21 * lock.k; font.weight: Font.DemiBold; text: lock.realName || lock.userName }
            Item { width: 1; height: 2 * lock.k }
            Rectangle {
                width: parent.width; height: 44 * lock.k; radius: height / 2
                color: Qt.rgba(1, 1, 1, pass.activeFocus ? 0.14 : 0.09)
                border.width: 1
                border.color: lock.noteBad ? Qt.rgba(1, 0.45, 0.4, 0.9) : pass.activeFocus ? Qt.rgba(lock.accent.r, lock.accent.g, lock.accent.b, 0.85) : Qt.rgba(1, 1, 1, 0.16)
                Behavior on border.color { ColorAnimation { duration: 180 } }
                TextInput {
                    id: pass
                    objectName: "lockPassword"
                    x: 18 * lock.k; width: parent.width - 18 * lock.k - (go.width + 14 * lock.k) - (caps.visible ? caps.width + 6 * lock.k : 0)
                    anchors.verticalCenter: parent.verticalCenter
                    opacity: lock.busy || lock.unlocking ? 0 : 1
                    Behavior on opacity { NumberAnimation { duration: 180 } }
                    color: lock.ink; font.family: lock.face; font.pixelSize: 15 * lock.k; font.letterSpacing: 2 * lock.k
                    clip: true; focus: true; enabled: !lock.busy && !lock.unlocking
                    echoMode: TextInput.Password; passwordCharacter: "●"; passwordMaskDelay: 0
                    onAccepted: lock.send()
                    onTextChanged: if (text) lock.noteBad = false
                    Keys.onEscapePressed: text = ""
                    Keys.onPressed: function (e) { lock.wake(); e.accepted = false }
                    Text { visible: !parent.text; text: "Password"; color: Qt.rgba(1, 1, 1, 0.5); font.family: lock.face; font.pixelSize: 15 * lock.k; anchors.verticalCenter: parent.verticalCenter }
                }
                Icon { id: caps; visible: lock.capsLock && !lock.busy; width: 18 * lock.k; height: width; name: "caps"; ink: lock.soft
                    anchors { right: go.left; rightMargin: 8 * lock.k; verticalCenter: parent.verticalCenter } }
                Rectangle {
                    id: go
                    objectName: "lockGo"
                    readonly property bool ready: pass.text !== "" && !lock.busy && !lock.unlocking && lock.ready
                    width: 32 * lock.k; height: width; radius: width / 2
                    anchors { right: parent.right; rightMargin: 6 * lock.k; verticalCenter: parent.verticalCenter }
                    color: ready ? lock.accent : Qt.rgba(1, 1, 1, 0.10)
                    opacity: lock.busy || lock.unlocking ? 0 : 1
                    scale: goHit.pressed ? 0.9 : ready ? 1 : 0.86
                    Behavior on color { ColorAnimation { duration: 180 } }
                    Behavior on scale { NumberAnimation { duration: 180; easing.type: Easing.OutBack } }
                    Icon { anchors.centerIn: parent; width: 18 * lock.k; height: width; name: "arrow"; stroke: 2.2; ink: go.ready ? "#0B1512" : Qt.rgba(1, 1, 1, 0.55) }
                    MouseArea { id: goHit; anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: lock.send() }
                }
                Item {
                    objectName: "lockProgress"
                    visible: lock.busy || lock.unlocking
                    anchors { fill: parent; leftMargin: 22 * lock.k; rightMargin: 22 * lock.k }
                    clip: true
                    Rectangle { anchors.verticalCenter: parent.verticalCenter; width: parent.width; height: 3 * lock.k; radius: height / 2; color: Qt.rgba(1, 1, 1, 0.14) }
                    Rectangle { id: runner; anchors.verticalCenter: parent.verticalCenter; width: parent.width * 0.45; height: 3 * lock.k; radius: height / 2
                        gradient: Gradient { orientation: Gradient.Horizontal
                            GradientStop { position: 0; color: "transparent" } GradientStop { position: 0.5; color: lock.glowA } GradientStop { position: 1; color: lock.glowB } }
                        NumberAnimation on x { from: -runner.width; to: runner.parent.width; duration: 1100; loops: Animation.Infinite; easing.type: Easing.InOutSine; running: lock.busy || lock.unlocking } }
                }
            }
            Text {
                objectName: "lockNote"
                width: parent.width; horizontalAlignment: Text.AlignHCenter; wrapMode: Text.WordWrap
                font.family: lock.face; font.pixelSize: 12.5 * lock.k
                color: lock.noteBad ? "#FFA197" : lock.soft
                text: lock.note !== "" ? lock.note : lock.unlocking ? "Unlocking" : lock.busy ? "Checking…" : lock.capsLock ? "Caps Lock is on" : "Locked"
            }
        }
    }

    // ================================================================ bottom: what's locked, and what you can do
    Row {
        x: 26 * lock.k; y: parent.height - height - 28 * lock.k; spacing: 9 * lock.k
        opacity: 0.85 * (lock.idle || lock.unlocking ? 0 : 1)
        Behavior on opacity { NumberAnimation { duration: 700 } }
        Icon { width: 18 * lock.k; height: width; name: "lock"; ink: lock.ink; anchors.verticalCenter: parent.verticalCenter }
        Text { text: "Locked"; color: lock.ink; font.family: lock.face; font.pixelSize: 13 * lock.k; font.weight: Font.DemiBold; anchors.verticalCenter: parent.verticalCenter }
    }
    Glass {
        objectName: "lockActions"
        visible: lock.canSuspend || lock.canSwitchUser
        x: parent.width - width - 22 * lock.k; y: parent.height - height - 20 * lock.k
        height: 44 * lock.k; width: actRow.width + 10 * lock.k; radius: height / 2
        opacity: lock.idle || lock.unlocking ? 0 : 1
        Behavior on opacity { NumberAnimation { duration: 700 } }
        Row { id: actRow; anchors.centerIn: parent; spacing: 4 * lock.k
            Round { objectName: "lockSleep"; visible: lock.canSuspend; icon: "moon"; label: "Sleep"; onClicked: lock.suspend() }
            Round { objectName: "lockSwitch"; visible: lock.canSwitchUser; icon: "switch"; label: "Switch User"; onClicked: lock.switchUser() } }
    }

    Component.onCompleted: pass.forceActiveFocus()
}
