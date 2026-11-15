import QtQuick
import QtCore

// Huginn OS's lock screen inside KDE's screen locker (the KWin session), which takes its lock screen from the Plasma
// shell package plasmashellrc names. The lock itself is /usr/share/huginn-os/lock/Lock.qml, which Huginn's own
// compositor uses too; this file only connects it to the screen locker: the password goes to its authenticator (PAM,
// as the user), and when that says yes the locker is told to quit.
//
// The realm comes from ~/.local/share/huginn/Look.qml, which the shell keeps up to date. If the lock can't load at all,
// a plain password field stands in: nobody gets locked out of their own computer by a missing file.
Item {
    id: root
    // what KDE's screen locker looks for on its lock screen
    property bool locked: false
    property bool viewVisible: false
    property bool debug: false
    property string notification: ""
    property bool suspendToRamSupported: false
    property bool suspendToDiskSupported: false
    signal suspendToRam()
    signal suspendToDisk()
    signal clearPassword()
    signal notificationRepeated()

    readonly property bool hasAuth: typeof authenticator !== "undefined" && authenticator !== null
    readonly property bool modern: hasAuth && typeof authenticator.respond === "function"   // Plasma 6; Plasma 5 had tryUnlock(password)
    property bool asking: false             // the conversation is waiting for a password
    property string waiting: ""             // one typed before it asked
    readonly property string lockUi: typeof huginnLockUi !== "undefined" ? huginnLockUi : "file:///usr/share/huginn-os/lock/Lock.qml"

    function start() {
        if (root.modern && typeof authenticator.startAuthenticating === "function")
            authenticator.startAuthenticating()
    }
    function submit(password) {
        if (!root.hasAuth)
            return
        if (!root.modern) {
            authenticator.tryUnlock(password)
        } else if (root.asking) {
            root.asking = false
            authenticator.respond(password)
        } else {
            root.waiting = password
            root.start()
            stuck.restart()
        }
    }
    // Right password: the locker goes at once (its fade would only hold it up: animations and QML timers wait on frames
    // being drawn, which a busy or sleeping screen may not be doing).
    function unlocked() { if (ui.item) ui.item.succeed(); Qt.quit() }
    function refused(message) {
        if (ui.item) ui.item.fail(message || "")
        else { plain.text = ""; plainNote.text = message || "Wrong password" }
        again.restart()
    }

    Connections {
        target: root.hasAuth ? authenticator : null
        ignoreUnknownSignals: true
        function onSucceeded() { stuck.stop(); root.unlocked() }
        function onFailed(kind) { stuck.stop(); if (kind === undefined || kind === 0) root.refused("") }
        function onPromptForSecretChanged() {
            root.asking = true
            if (root.waiting !== "") {
                stuck.stop()
                var p = root.waiting
                root.waiting = ""; root.asking = false
                authenticator.respond(p)
            }
        }
        function onInfoMessageChanged() { if (authenticator.infoMessage && ui.item) ui.item.say(authenticator.infoMessage) }
        function onErrorMessageChanged() { if (authenticator.errorMessage) root.refused(authenticator.errorMessage) }
    }
    Timer { id: again; interval: 700; onTriggered: root.start() }   // a fresh conversation for the next try
    // A password typed while the conversation was already waiting on an earlier prompt (missed, or asked before
    // this screen was ready) would wait for ever: after a moment, end that conversation and start one that asks.
    Timer { id: stuck; interval: 2500
        onTriggered: if (root.waiting !== "" && root.modern && typeof authenticator.stopAuthenticating === "function") {
            authenticator.stopAuthenticating(); root.asking = false; root.start() } }
    Connections { target: root; function onClearPassword() { if (ui.item) ui.item.reset() } }

    Loader { id: look; source: StandardPaths.writableLocation(StandardPaths.GenericDataLocation) + "/huginn/Look.qml" }
    Loader {
        id: ui
        anchors.fill: parent
        source: root.lockUi
        onLoaded: {
            item.realName = typeof kscreenlocker_userName !== "undefined" ? kscreenlocker_userName : ""
            item.picture = typeof kscreenlocker_userImage !== "undefined" ? kscreenlocker_userImage : ""
            item.realm = Qt.binding(function () { return look.item && look.item.realm ? look.item.realm : "aurora" })
            item.canSuspend = Qt.binding(function () { return root.suspendToRamSupported })
            item.submit.connect(root.submit)
            item.suspend.connect(root.suspendToRam)
            item.done.connect(function () { Qt.quit() })
        }
    }
    Rectangle {
        anchors.fill: parent
        visible: ui.status === Loader.Error || ui.status === Loader.Null
        color: "#0B1012"
        Column {
            anchors.centerIn: parent; spacing: 12; width: 320
            Text { text: "Locked"; color: "white"; font.pixelSize: 26; anchors.horizontalCenter: parent.horizontalCenter }
            Rectangle { width: parent.width; height: 42; radius: 21; color: "#22FFFFFF"; border.color: "#55FFFFFF"
                TextInput { id: plain; objectName: "plainPassword"; anchors.fill: parent; anchors.leftMargin: 16; anchors.rightMargin: 16; verticalAlignment: TextInput.AlignVCenter
                    color: "white"; echoMode: TextInput.Password; focus: true; font.pixelSize: 15; onAccepted: root.submit(text) } }
            Text { id: plainNote; color: "#FFA197"; anchors.horizontalCenter: parent.horizontalCenter }
        }
    }
    Component.onCompleted: root.start()
}
