import QtQuick

// Huginn OS's sign-in screen (an SDDM greeter theme). The realm's live wallpaper moves behind everything: Aurora's
// northern lights, Bifröst's bridge, Muspelheim's fire or Niflheim's ice. A quiet clock sits at the top. Lower down,
// one frosted glass island holds you: your picture in a ring of the realm's light, your name and your password. The
// other people on this computer wait as small orbs beneath it. Sleep, restart and shut down sit at the bottom edge,
// and the keyboard layout and session at the top right.
//
// Left alone, everything but the clock fades away and the wallpaper has the screen; any key or movement brings it
// back (a key also goes into the password). A wrong password shakes the island. Signing in turns the password into
// a line of light, and the wallpaper slows to a stop as the desktop takes over, showing the same scene.
//
// Everything SDDM gives a theme is used through its own objects: sddm, userModel, sessionModel, keyboard and config.
// The wallpaper and the frosted glass come from separate files, so if either can't load, the screen still works.
Rectangle {
    id: root
    width: 1600; height: 1000
    color: "black"

    // ---- settings (theme.conf)
    function conf(key, fallback) { var v = (typeof config !== "undefined" && config) ? config[key] : undefined; return (v === undefined || v === null || v === "") ? fallback : v }
    readonly property string realm: conf("realm", "aurora")
    readonly property string liveDir: { var d = conf("live", "/usr/share/huginn-os/live/"); return (d.indexOf("://") < 0 ? "file://" : "") + (d.charAt(d.length - 1) === "/" ? d : d + "/") }
    readonly property string face: conf("font", "Inter")
    readonly property int idleAfter: Number(conf("idleSeconds", 30))
    readonly property var realms: ({
        aurora:     { tintA: "#0F2624", tintB: "#17192C", glowA: "#3DD6B5", glowB: "#7B61FF", accent: "#43D9B8" },
        bifrost:    { tintA: "#1D1932", tintB: "#2A1727", glowA: "#8E7BFF", glowB: "#FF7AB8", accent: "#A995FF" },
        muspelheim: { tintA: "#2C1912", tintB: "#1F1718", glowA: "#FF8A4C", glowB: "#FFC857", accent: "#FF8C50" },
        niflheim:   { tintA: "#12212F", tintB: "#171A20", glowA: "#7CC4FF", glowB: "#CFEAFF", accent: "#7CC4FF" } })
    readonly property var own: realms[realm] || realms.aurora
    readonly property color accent: conf("accent", own.accent)
    readonly property color glowA: own.glowA
    readonly property color glowB: own.glowB
    readonly property real k: Math.max(0.75, Math.min(1.8, height / 1000))      // everything scales with the screen
    readonly property color ink: "#F5F7FA"
    readonly property color soft: Qt.rgba(1, 1, 1, 0.62)

    // ---- who's signing in
    property int userIdx: userModel.lastIndex >= 0 ? userModel.lastIndex : 0
    property int sessionIdx: sessionModel.lastIndex >= 0 ? sessionModel.lastIndex : 0
    property string userName: ""
    property string realName: ""
    property string userIcon: ""
    property bool needsPassword: true
    property bool typingName: userModel.count === 0          // no list of people: type a user name
    property bool busy: false
    property bool done: false                                 // signed in: the desktop is on its way
    property string note: ""
    property bool noteBad: false
    property int tries: 0
    property string sessionName: ""
    property bool idle: false
    property string menu: ""                                  // "", "session" or "layout"

    function signIn() {
        var who = root.typingName ? nameBox.text.trim() : root.userName
        if (!who || root.busy)
            return
        root.wake()
        root.busy = true
        root.note = ""
        root.noteBad = false
        sddm.login(who, pass.text, root.sessionIdx)
    }
    function wake() {
        root.idle = false
        idleTimer.restart()
    }
    function choose(i) {
        root.typingName = false
        root.userIdx = i
        root.note = ""; root.noteBad = false; root.tries = 0
        pass.text = ""
        swap.restart()
        pass.forceActiveFocus()
    }
    function pick(i) {                                        // from the session or layout list (which closes as it's picked)
        if (root.menu === "session")
            root.sessionIdx = i
        else
            keyboard.currentLayout = i
        var field = root.typingName && !nameBox.text ? nameBox : pass
        field.forceActiveFocus()
        root.menu = ""
    }
    function someoneElse() {
        root.typingName = true
        root.note = ""; root.noteBad = false; root.tries = 0
        pass.text = ""; nameBox.text = ""
        swap.restart()
        nameBox.forceActiveFocus()
    }

    Connections {
        target: sddm
        function onLoginFailed() {
            root.busy = false
            root.tries += 1
            root.noteBad = true
            root.note = root.tries >= 3 ? "Still not right. Check Caps Lock and the keyboard layout." : "Wrong password. Try again."
            pass.text = ""
            pass.forceActiveFocus()
            shake.restart()
        }
        function onLoginSucceeded() {
            root.note = ""; root.noteBad = false
            root.done = true
            if (wall.item) wall.item.moving = false       // the wallpaper comes to rest as the desktop arrives
        }
        function onInformationMessage(message) { root.note = message; root.noteBad = false }
    }

    // the chosen person's and session's details, read through invisible delegates (the models give them per row)
    Repeater { model: userModel
        Item { required property int index; required property string name; required property string realName; required property string icon
            required property bool needsPassword
            readonly property bool chosen: index === root.userIdx && !root.typingName
            onChosenChanged: if (chosen) take()
            Component.onCompleted: if (chosen) take()
            function take() { root.userName = name; root.realName = realName; root.userIcon = icon; root.needsPassword = needsPassword } } }
    Repeater { id: sessionNames; model: sessionModel
        Item { required property int index; required property string name
            property string label: name
            readonly property bool chosen: index === root.sessionIdx
            onChosenChanged: if (chosen) root.sessionName = name
            Component.onCompleted: if (chosen) root.sessionName = name } }

    Timer { id: idleTimer; interval: Math.max(5, root.idleAfter) * 1000; running: !root.busy && !root.done; onTriggered: { root.idle = true; root.menu = "" } }

    // ================================================================ the wallpaper
    Item {
        id: sky
        anchors.fill: parent
        Loader {
            id: wall
            anchors.fill: parent
            source: root.liveDir + "LiveWallpaper.qml"
            onLoaded: item.realm = root.realm
        }
        // without the live wallpaper (not installed, or it couldn't load): the realm's sky, painted once
        Canvas {
            anchors.fill: parent
            visible: wall.status === Loader.Error || wall.status === Loader.Null
            onPaint: {
                var c = getContext("2d"), w = width, h = height
                c.reset()
                var g = c.createLinearGradient(0, 0, 0, h)
                g.addColorStop(0, root.own.tintA); g.addColorStop(0.6, "#0C1014"); g.addColorStop(1, root.own.tintB)
                c.fillStyle = g; c.fillRect(0, 0, w, h)
                var r = c.createRadialGradient(w * 0.25, h * 0.2, 0, w * 0.25, h * 0.2, w * 0.5)
                r.addColorStop(0, Qt.rgba(root.glowA.r, root.glowA.g, root.glowA.b, 0.28)); r.addColorStop(1, "transparent")
                c.fillStyle = r; c.fillRect(0, 0, w, h)
            }
        }
    }
    // shade at the top and bottom, so the clock and the islands always read
    Rectangle { anchors { left: parent.left; right: parent.right; top: parent.top } height: parent.height * 0.34
        gradient: Gradient { GradientStop { position: 0; color: Qt.rgba(0, 0, 0, 0.34) } GradientStop { position: 1; color: "transparent" } } }
    Rectangle { anchors { left: parent.left; right: parent.right; bottom: parent.bottom } height: parent.height * 0.55
        opacity: root.idle ? 0.35 : 1
        Behavior on opacity { NumberAnimation { duration: 900; easing.type: Easing.InOutQuad } }
        gradient: Gradient { GradientStop { position: 0; color: "transparent" } GradientStop { position: 1; color: Qt.rgba(0, 0, 0, 0.5) } } }

    // anything that moves wakes the screen
    MouseArea { anchors.fill: parent; hoverEnabled: true; acceptedButtons: Qt.LeftButton
        onPositionChanged: root.wake()
        onPressed: { root.wake(); root.menu = "" } }

    component Glass: Rectangle {
        id: glass
        property bool frosted: true
        color: Qt.rgba(0.07, 0.08, 0.10, frost.status === Loader.Ready ? 0.34 : 0.62)
        border.width: 1; border.color: Qt.rgba(1, 1, 1, 0.13)
        Loader { id: frost; z: -1; anchors.fill: parent; active: glass.frosted && wall.status === Loader.Ready && wall.item !== null && !wall.item.still
            source: "Frost.qml"
            onLoaded: { item.behind = sky; item.radius = Qt.binding(function () { return glass.radius })
                item.area = Qt.binding(function () { return Qt.rect(glass.x, glass.y, glass.width, glass.height) }) } }   // islands sit on the root, like the wallpaper
        // a hairline of light along the top edge
        Rectangle { anchors { left: parent.left; right: parent.right; top: parent.top; leftMargin: glass.radius * 0.8; rightMargin: glass.radius * 0.8 } height: 1
            gradient: Gradient { orientation: Gradient.Horizontal
                GradientStop { position: 0; color: "transparent" } GradientStop { position: 0.5; color: Qt.rgba(1, 1, 1, 0.28) } GradientStop { position: 1; color: "transparent" } } }
    }
    component Round: Rectangle {
        id: rb
        property string icon: ""
        property string label: ""
        property real size: 34 * root.k
        signal clicked()
        width: size; height: size; radius: size / 2
        color: hit.pressed ? Qt.rgba(1, 1, 1, 0.24) : hit.containsMouse ? Qt.rgba(1, 1, 1, 0.15) : "transparent"
        scale: hit.pressed ? 0.92 : 1
        Behavior on scale { NumberAnimation { duration: 120; easing.type: Easing.OutQuad } }
        Behavior on color { ColorAnimation { duration: 140 } }
        Icon { anchors.centerIn: parent; width: rb.size * 0.5; height: width; name: rb.icon; ink: root.ink }
        // its name, floating above it while the pointer is on it
        Rectangle { anchors { bottom: parent.top; bottomMargin: 14 * root.k; horizontalCenter: parent.horizontalCenter }
            width: tip.width + 18 * root.k; height: 24 * root.k; radius: height / 2; color: Qt.rgba(0.07, 0.08, 0.10, 0.82)
            border.width: 1; border.color: Qt.rgba(1, 1, 1, 0.12)
            opacity: hit.containsMouse ? 1 : 0
            Behavior on opacity { NumberAnimation { duration: 160 } }
            Text { id: tip; anchors.centerIn: parent; text: rb.label; color: root.ink; font.family: root.face; font.pixelSize: 11.5 * root.k; font.weight: Font.Medium } }
        MouseArea { id: hit; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: { root.wake(); rb.clicked() } }
    }
    // someone's picture: theirs if they have one, else their initials on the realm's colours; `ring` circles it in light
    component Face: Item {
        id: fc
        property string who: ""
        property string picture: ""
        property bool ring: false
        property bool spinning: false
        property bool other: false
        Rectangle { anchors.fill: parent; radius: width / 2; visible: fc.ring
            gradient: Gradient { orientation: Gradient.Horizontal; GradientStop { position: 0; color: root.glowA } GradientStop { position: 1; color: root.glowB } }
            RotationAnimator on rotation { from: 0; to: 360; duration: 1600; loops: Animation.Infinite; running: fc.spinning } }
        Rectangle { anchors.fill: parent; anchors.margins: fc.ring ? Math.max(2, parent.width * 0.035) : 0; radius: width / 2
            gradient: Gradient { orientation: Gradient.Vertical
                GradientStop { position: 0; color: fc.other ? "#3A4048" : Qt.lighter(root.own.tintA, 2.6) }
                GradientStop { position: 1; color: fc.other ? "#262A31" : Qt.lighter(root.own.tintB, 2.2) } }
            Text { anchors.centerIn: parent; visible: !fc.other && pic.status !== Image.Ready; color: "white"; font.family: root.face
                font.pixelSize: parent.width * 0.36; font.weight: Font.DemiBold
                text: { var n = (fc.who || "?").trim().split(/\s+/); return (n[0][0] + (n.length > 1 ? n[n.length - 1][0] : "")).toUpperCase() } }
            Icon { anchors.centerIn: parent; visible: fc.other; width: parent.width * 0.5; height: width; name: "person"; ink: Qt.rgba(1, 1, 1, 0.8) }
            Image { id: pic; anchors.fill: parent; source: fc.picture; fillMode: Image.PreserveAspectCrop; asynchronous: true; visible: false; smooth: true }
            // a round crop without extra modules: the picture painted through a circle
            Canvas { anchors.fill: parent; visible: pic.status === Image.Ready
                property string src: pic.status === Image.Ready ? fc.picture : ""
                onSrcChanged: { if (src) loadImage(src); requestPaint() }
                onImageLoaded: requestPaint()
                onPaint: { var c = getContext("2d"); c.reset(); if (!src || !isImageLoaded(src)) return
                    c.beginPath(); c.arc(width / 2, height / 2, width / 2, 0, Math.PI * 2); c.closePath(); c.clip(); c.drawImage(src, 0, 0, width, height) } } }
    }

    // ================================================================ top right: keyboard layout and session
    Glass {
        id: status
        objectName: "statusIsland"
        x: parent.width - width - 22 * root.k; y: 20 * root.k + intro.drop * 0.5
        height: 38 * root.k; width: statusRow.width + 10 * root.k; radius: height / 2
        visible: statusRow.width > 0
        opacity: (root.idle || root.done ? 0 : 1) * intro.ui
        Behavior on opacity { NumberAnimation { duration: 600; easing.type: Easing.InOutQuad } }
        Row { id: statusRow; anchors.centerIn: parent; spacing: 2 * root.k
            Repeater { model: [{ key: "layout", icon: "keyboard" }, { key: "session", icon: "session" }]
                Rectangle { required property var modelData
                    objectName: modelData.key
                    property string text: modelData.key === "layout" ? (has ? String(keyboard.layouts[keyboard.currentLayout].shortName).toUpperCase() : "") : root.sessionName
                    readonly property bool has: modelData.key === "layout" ? (keyboard && keyboard.layouts && keyboard.layouts.length > 1) : sessionModel.count > 1
                    visible: has
                    height: 30 * root.k; width: srow.width + 22 * root.k; radius: height / 2
                    color: sh.containsMouse || root.menu === modelData.key ? Qt.rgba(1, 1, 1, 0.14) : "transparent"
                    Row { id: srow; anchors.centerIn: parent; spacing: 7 * root.k
                        Icon { width: 16 * root.k; height: width; name: modelData.icon; ink: root.ink; anchors.verticalCenter: parent.verticalCenter }
                        Text { text: parent.parent.text; color: root.ink; font.family: root.face; font.pixelSize: 12.5 * root.k; font.weight: Font.Medium; anchors.verticalCenter: parent.verticalCenter }
                        Icon { width: 12 * root.k; height: width; name: "chevron"; ink: root.soft; anchors.verticalCenter: parent.verticalCenter } }
                    MouseArea { id: sh; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor
                        onClicked: { root.wake(); root.menu = root.menu === modelData.key ? "" : modelData.key } } } } }
    }
    // the list that drops from it
    Glass {
        id: dropList
        objectName: "menu"
        visible: opacity > 0
        opacity: root.menu !== "" && !root.idle ? 1 : 0
        Behavior on opacity { NumberAnimation { duration: 140 } }
        radius: 16 * root.k
        width: 240 * root.k; height: menuCol.height + 12 * root.k
        x: parent.width - width - 22 * root.k; y: status.y + status.height + 8 * root.k
        Column { id: menuCol; x: 6 * root.k; y: 6 * root.k; width: parent.width - 12 * root.k
            Repeater {
                model: root.menu === "session" ? sessionModel.count : root.menu === "layout" && keyboard && keyboard.layouts ? keyboard.layouts.length : 0
                Rectangle { required property int index
                    property string label: root.menu === "session" ? (sessionNames.itemAt(index) ? sessionNames.itemAt(index).label : "")
                                                                   : (keyboard.layouts[index] ? keyboard.layouts[index].longName : "")
                    readonly property bool on: root.menu === "session" ? index === root.sessionIdx : index === keyboard.currentLayout
                    objectName: "menuItem" + index
                    width: parent.width; height: 34 * root.k; radius: 10 * root.k
                    color: mh.containsMouse ? Qt.rgba(1, 1, 1, 0.14) : "transparent"
                    Text { x: 12 * root.k; anchors.verticalCenter: parent.verticalCenter; width: parent.width - 40 * root.k; elide: Text.ElideRight
                        text: parent.label; color: root.ink; font.family: root.face; font.pixelSize: 13 * root.k; font.weight: parent.on ? Font.DemiBold : Font.Normal }
                    Rectangle { visible: parent.on; width: 7 * root.k; height: width; radius: width / 2; color: root.accent
                        anchors { right: parent.right; rightMargin: 14 * root.k; verticalCenter: parent.verticalCenter } }
                    MouseArea { id: mh; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor
                        onClicked: root.pick(index) } } } }
    }

    // ================================================================ the clock
    Column {
        id: clock
        objectName: "clock"
        anchors.horizontalCenter: parent.horizontalCenter
        y: parent.height * 0.085 + intro.drop
        opacity: intro.clock * (root.done ? 0 : 1)
        Behavior on opacity { NumberAnimation { duration: 500 } }
        spacing: 0
        property date now: new Date()
        Timer { interval: 1000; running: true; repeat: true; triggeredOnStart: true; onTriggered: clock.now = new Date() }
        readonly property bool h24: { var c = root.conf("clock24", ""); var f = Qt.locale().timeFormat(Locale.ShortFormat); return c === "" ? f.indexOf("AP") < 0 && f.indexOf("ap") < 0 : String(c) === "true" }
        Text { objectName: "date"; anchors.horizontalCenter: parent.horizontalCenter; color: Qt.rgba(1, 1, 1, 0.78)
            font.family: root.face; font.pixelSize: 15 * root.k; font.weight: Font.DemiBold; font.letterSpacing: 2.2 * root.k; font.capitalization: Font.AllUppercase
            text: Qt.formatDate(clock.now, "dddd d MMMM") }
        Text { objectName: "time"; anchors.horizontalCenter: parent.horizontalCenter; color: root.ink
            font.family: root.face; font.pixelSize: 132 * root.k; font.weight: Font.ExtraLight; font.letterSpacing: -2 * root.k
            text: Qt.formatTime(clock.now, clock.h24 ? "HH:mm" : "h:mm") }
    }

    // ================================================================ you
    // a soft pool of the realm's light under the island
    Canvas {
        id: pool
        width: island.width * 1.9; height: island.height * 1.3
        x: island.x + island.width / 2 - width / 2; y: island.y + island.height * 0.05
        opacity: island.opacity * 0.9
        onPaint: { var c = getContext("2d"); c.reset(); c.save(); c.scale(1, height / width)
            var g = c.createRadialGradient(width / 2, width / 2, 0, width / 2, width / 2, width / 2)
            g.addColorStop(0, Qt.rgba(root.glowA.r, root.glowA.g, root.glowA.b, 0.20)); g.addColorStop(0.5, Qt.rgba(root.glowB.r, root.glowB.g, root.glowB.b, 0.06)); g.addColorStop(1, "transparent")
            c.fillStyle = g; c.fillRect(0, 0, width, width); c.restore() }
        onWidthChanged: requestPaint()
        onHeightChanged: requestPaint()
    }
    Glass {
        id: island
        objectName: "island"
        width: 360 * root.k; height: inside.height + 52 * root.k; radius: 32 * root.k
        x: (parent.width - width) / 2
        y: parent.height * 0.67 - height / 2 + intro.rise + (root.done ? -10 * root.k : 0)
        opacity: intro.ui * (root.idle ? 0 : 1)
        Behavior on opacity { NumberAnimation { duration: 700; easing.type: Easing.InOutQuad } }
        transform: Translate { id: nudge }
        SequentialAnimation { id: shake
            NumberAnimation { target: nudge; property: "x"; to: 16; duration: 55; easing.type: Easing.OutQuad }
            NumberAnimation { target: nudge; property: "x"; to: -13; duration: 70; easing.type: Easing.InOutQuad }
            NumberAnimation { target: nudge; property: "x"; to: 9; duration: 70; easing.type: Easing.InOutQuad }
            NumberAnimation { target: nudge; property: "x"; to: -5; duration: 70; easing.type: Easing.InOutQuad }
            NumberAnimation { target: nudge; property: "x"; to: 0; duration: 90; easing.type: Easing.OutQuad } }
        SequentialAnimation { id: swap
            NumberAnimation { target: inside; property: "opacity"; to: 0.0; duration: 90 }
            NumberAnimation { target: inside; property: "opacity"; to: 1.0; duration: 220; easing.type: Easing.OutQuad } }

        Column {
            id: inside
            y: 26 * root.k; width: parent.width - 48 * root.k; x: 24 * root.k
            spacing: 12 * root.k
            Face { objectName: "face"; width: 96 * root.k; height: width; anchors.horizontalCenter: parent.horizontalCenter
                who: root.realName || root.userName; picture: root.typingName ? "" : root.userIcon; other: root.typingName; ring: true; spinning: root.busy || root.done }
            Text { objectName: "who"; anchors.horizontalCenter: parent.horizontalCenter; width: parent.width; horizontalAlignment: Text.AlignHCenter; elide: Text.ElideRight
                color: root.ink; font.family: root.face; font.pixelSize: 21 * root.k; font.weight: Font.DemiBold
                text: root.typingName ? "Someone else" : (root.realName || root.userName) }
            Item { width: 1; height: 2 * root.k }
            // the user name (only when there's no list of people, or for someone else)
            Rectangle {
                id: nameField
                visible: root.typingName
                width: parent.width; height: 44 * root.k; radius: height / 2
                color: Qt.rgba(1, 1, 1, nameBox.activeFocus ? 0.14 : 0.09)
                border.width: 1; border.color: nameBox.activeFocus ? Qt.rgba(root.accent.r, root.accent.g, root.accent.b, 0.85) : Qt.rgba(1, 1, 1, 0.16)
                TextInput { id: nameBox; objectName: "nameBox"; x: 18 * root.k; width: parent.width - 36 * root.k; anchors.verticalCenter: parent.verticalCenter
                    color: root.ink; font.family: root.face; font.pixelSize: 15 * root.k; selectByMouse: true; clip: true
                    KeyNavigation.tab: pass; onAccepted: pass.forceActiveFocus()
                    Keys.onPressed: function (e) { root.wake(); e.accepted = false }
                    Text { visible: !parent.text; text: "User name"; color: Qt.rgba(1, 1, 1, 0.5); font: parent.font } }
            }
            // the password, with its own arrow
            Rectangle {
                id: passField
                objectName: "passField"
                width: parent.width; height: 44 * root.k; radius: height / 2
                color: Qt.rgba(1, 1, 1, pass.activeFocus ? 0.14 : 0.09)
                border.width: 1
                border.color: root.noteBad ? Qt.rgba(1, 0.45, 0.4, 0.9) : pass.activeFocus ? Qt.rgba(root.accent.r, root.accent.g, root.accent.b, 0.85) : Qt.rgba(1, 1, 1, 0.16)
                Behavior on border.color { ColorAnimation { duration: 180 } }
                TextInput {
                    id: pass
                    objectName: "password"
                    x: 18 * root.k; width: parent.width - 18 * root.k - (go.width + 14 * root.k) - (caps.visible ? caps.width + 6 * root.k : 0)
                    anchors.verticalCenter: parent.verticalCenter
                    opacity: root.busy || root.done ? 0 : 1
                    Behavior on opacity { NumberAnimation { duration: 180 } }
                    color: root.ink; font.family: root.face; font.pixelSize: 15 * root.k; font.letterSpacing: 2 * root.k
                    clip: true; focus: true; enabled: !root.busy && !root.done
                    echoMode: TextInput.Password; passwordCharacter: "●"; passwordMaskDelay: 0
                    onAccepted: root.signIn()
                    onTextChanged: if (text) root.noteBad = false
                    Keys.onEscapePressed: text = ""
                    Keys.onPressed: function (e) { root.wake(); e.accepted = false }
                    Text { visible: !parent.text; text: root.needsPassword || root.typingName ? "Password" : "Press Enter to sign in"; color: Qt.rgba(1, 1, 1, 0.5)
                        font.family: root.face; font.pixelSize: 15 * root.k; anchors.verticalCenter: parent.verticalCenter }
                }
                Icon { id: caps; objectName: "caps"; visible: keyboard && keyboard.capsLock && !root.busy; width: 18 * root.k; height: width; name: "caps"; ink: root.soft
                    anchors { right: go.left; rightMargin: 8 * root.k; verticalCenter: parent.verticalCenter } }
                // the arrow: sign in. It wakes when there's something to send.
                Rectangle {
                    id: go
                    objectName: "go"
                    readonly property bool ready: (pass.text !== "" || (!root.needsPassword && !root.typingName)) && !root.busy && !root.done
                    width: 32 * root.k; height: width; radius: width / 2
                    anchors { right: parent.right; rightMargin: 6 * root.k; verticalCenter: parent.verticalCenter }
                    color: ready ? root.accent : Qt.rgba(1, 1, 1, 0.10)
                    opacity: root.busy || root.done ? 0 : 1
                    scale: goHit.pressed ? 0.9 : ready ? 1 : 0.86
                    Behavior on color { ColorAnimation { duration: 180 } }
                    Behavior on scale { NumberAnimation { duration: 180; easing.type: Easing.OutBack } }
                    Icon { anchors.centerIn: parent; width: 18 * root.k; height: width; name: "arrow"; stroke: 2.2; ink: go.ready ? "#0B1512" : Qt.rgba(1, 1, 1, 0.55) }
                    MouseArea { id: goHit; anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: root.signIn() }
                }
                // signing in: a line of the realm's light running inside the field
                Item {
                    objectName: "progress"
                    visible: root.busy || root.done
                    anchors { fill: parent; leftMargin: 22 * root.k; rightMargin: 22 * root.k }
                    clip: true
                    Rectangle { anchors.verticalCenter: parent.verticalCenter; width: parent.width; height: 3 * root.k; radius: height / 2; color: Qt.rgba(1, 1, 1, 0.14) }
                    Rectangle { id: runner; anchors.verticalCenter: parent.verticalCenter; width: parent.width * 0.45; height: 3 * root.k; radius: height / 2
                        gradient: Gradient { orientation: Gradient.Horizontal
                            GradientStop { position: 0; color: "transparent" } GradientStop { position: 0.5; color: root.glowA } GradientStop { position: 1; color: root.glowB } }
                        NumberAnimation on x { from: -runner.width; to: runner.parent.width; duration: 1100; loops: Animation.Infinite; easing.type: Easing.InOutSine; running: root.busy || root.done } }
                }
            }
            // what happened: a wrong password, a message from the system, or what to do
            Text {
                objectName: "note"
                width: parent.width; horizontalAlignment: Text.AlignHCenter; wrapMode: Text.WordWrap
                font.family: root.face; font.pixelSize: 12.5 * root.k
                color: root.noteBad ? "#FFA197" : root.soft
                text: root.note !== "" ? root.note
                    : root.done ? "Welcome back"
                    : root.busy ? "Signing in…"
                    : (keyboard && keyboard.capsLock) ? "Caps Lock is on"
                    : root.typingName ? "Type a user name and password" : "Enter your password"
            }
        }
    }

    // ================================================================ the others on this computer
    Row {
        id: people
        objectName: "people"
        visible: userModel.count > 1 || (root.typingName && userModel.count > 0)
        anchors.horizontalCenter: parent.horizontalCenter
        y: island.y + island.height + 26 * root.k
        spacing: 22 * root.k
        opacity: intro.ui * (root.idle || root.done ? 0 : 1)
        Behavior on opacity { NumberAnimation { duration: 700; easing.type: Easing.InOutQuad } }
        Repeater { model: userModel
            Item { required property int index; required property string name; required property string realName; required property string icon
                objectName: "person" + index
                visible: index !== root.userIdx || root.typingName
                width: 48 * root.k; height: width
                scale: ph.pressed ? 0.92 : ph.containsMouse ? 1.08 : 1
                Behavior on scale { NumberAnimation { duration: 160; easing.type: Easing.OutQuad } }
                Face { anchors.fill: parent; who: realName || name; picture: icon; opacity: ph.containsMouse ? 1 : 0.8 }
                Rectangle { anchors.fill: parent; radius: width / 2; color: "transparent"; border.width: 1; border.color: Qt.rgba(1, 1, 1, 0.3) }
                Text { anchors { top: parent.bottom; topMargin: 7 * root.k; horizontalCenter: parent.horizontalCenter } text: realName || name; color: root.ink
                    font.family: root.face; font.pixelSize: 12 * root.k; font.weight: Font.Medium; opacity: ph.containsMouse ? 0.95 : 0
                    Behavior on opacity { NumberAnimation { duration: 150 } } }
                MouseArea { id: ph; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: { root.wake(); root.choose(index) } } } }
        Item { objectName: "otherPerson"; visible: !root.typingName; width: 48 * root.k; height: width
            scale: oh.pressed ? 0.92 : oh.containsMouse ? 1.08 : 1
            Behavior on scale { NumberAnimation { duration: 160; easing.type: Easing.OutQuad } }
            Face { anchors.fill: parent; other: true; opacity: oh.containsMouse ? 1 : 0.8 }
            Rectangle { anchors.fill: parent; radius: width / 2; color: "transparent"; border.width: 1; border.color: Qt.rgba(1, 1, 1, 0.3) }
            Text { anchors { top: parent.bottom; topMargin: 7 * root.k; horizontalCenter: parent.horizontalCenter } text: "Someone else"; color: root.ink
                font.family: root.face; font.pixelSize: 12 * root.k; font.weight: Font.Medium; opacity: oh.containsMouse ? 0.95 : 0
                Behavior on opacity { NumberAnimation { duration: 150 } } }
            MouseArea { id: oh; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: { root.wake(); root.someoneElse() } } }
    }

    // ================================================================ bottom left: this computer
    Row {
        objectName: "machine"
        x: 26 * root.k; y: parent.height - height - 28 * root.k
        spacing: 9 * root.k
        opacity: 0.85 * intro.ui * (root.idle || root.done ? 0 : 1)
        Behavior on opacity { NumberAnimation { duration: 700; easing.type: Easing.InOutQuad } }
        Image { source: "logo.svg"; width: 22 * root.k; height: width; sourceSize.width: 64; sourceSize.height: 64; anchors.verticalCenter: parent.verticalCenter }
        Text { text: "Huginn OS"; color: root.ink; font.family: root.face; font.pixelSize: 13 * root.k; font.weight: Font.DemiBold; anchors.verticalCenter: parent.verticalCenter }
        Text { text: sddm.hostName || ""; visible: text !== ""; color: root.soft; font.family: root.face; font.pixelSize: 13 * root.k; anchors.verticalCenter: parent.verticalCenter }
    }

    // ================================================================ bottom right: sleep, restart, shut down
    Glass {
        id: power
        objectName: "power"
        x: parent.width - width - 22 * root.k; y: parent.height - height - 20 * root.k - intro.rise * 0.3
        height: 44 * root.k; width: powRow.width + 10 * root.k; radius: height / 2
        opacity: intro.ui * (root.idle || root.done ? 0 : 1)
        Behavior on opacity { NumberAnimation { duration: 700; easing.type: Easing.InOutQuad } }
        Row { id: powRow; anchors.centerIn: parent; spacing: 4 * root.k
            Round { objectName: "sleep"; visible: sddm.canSuspend; icon: "moon"; label: "Sleep"; onClicked: sddm.suspend() }
            Round { objectName: "restart"; visible: sddm.canReboot; icon: "restart"; label: "Restart"; onClicked: sddm.reboot() }
            Round { objectName: "shutdown"; visible: sddm.canPowerOff; icon: "power"; label: "Shut Down"; onClicked: sddm.powerOff() } }
    }

    // ================================================================ arriving: out of the boot screen's darkness
    Rectangle { id: veil; anchors.fill: parent; color: "black"; opacity: 1; z: 10 }
    QtObject {
        id: intro
        objectName: "intro"
        property real clock: 0
        property real ui: 0
        property real drop: -14 * root.k
        property real rise: 26 * root.k
    }
    SequentialAnimation {
        id: arrive
        running: true
        NumberAnimation { target: veil; property: "opacity"; to: 0; duration: 900; easing.type: Easing.InOutQuad }
        ParallelAnimation {
            NumberAnimation { target: intro; property: "clock"; to: 1; duration: 700; easing.type: Easing.OutCubic }
            NumberAnimation { target: intro; property: "drop"; to: 0; duration: 800; easing.type: Easing.OutCubic }
            SequentialAnimation { PauseAnimation { duration: 140 }
                ParallelAnimation {
                    NumberAnimation { target: intro; property: "ui"; to: 1; duration: 650; easing.type: Easing.OutCubic }
                    NumberAnimation { target: intro; property: "rise"; to: 0; duration: 750; easing.type: Easing.OutCubic } } } }
    }

    Component.onCompleted: { if (root.typingName) nameBox.forceActiveFocus(); else pass.forceActiveFocus() }
}
