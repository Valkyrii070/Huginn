import QtQuick
import QtQuick.Window
import org.kde.layershell 1.0 as LayerShell

// The lock screen under Huginn's own compositor (huginn_locker.py): a full-screen overlay on every screen, the lock
// itself (the same Lock.qml as the KWin session's) on the main one, black on the others. The Python side is "LockHost"
// (not "Locker": inside this file that name is this file's own type).
QtObject {
    id: root

    property Instantiator screens: Instantiator {
        model: LockHost.screens
        delegate: Window {
            id: win
            required property var modelData
            required property int index
            readonly property bool main: index === 0
            visible: true
            color: "black"
            LayerShell.Window.screen: modelData
            LayerShell.Window.wantsToBeOnActiveScreen: false
            LayerShell.Window.scope: "huginn-lock"
            LayerShell.Window.layer: LayerShell.Window.LayerOverlay
            LayerShell.Window.keyboardInteractivity: win.main ? LayerShell.Window.KeyboardInteractivityExclusive
                                                              : LayerShell.Window.KeyboardInteractivityNone
            LayerShell.Window.anchors: LayerShell.Window.AnchorTop | LayerShell.Window.AnchorBottom | LayerShell.Window.AnchorLeft | LayerShell.Window.AnchorRight
            LayerShell.Window.exclusionZone: -1

            Loader {
                id: lock
                anchors.fill: parent
                active: win.main
                source: LockHost.lockUi
                focus: true
                onLoaded: {
                    item.userName = LockHost.me.login
                    item.realName = LockHost.me.name
                    item.picture = LockHost.me.face
                    item.realm = LockHost.realm
                    if (LockHost.liveDir !== "")
                        item.liveDir = LockHost.liveDir
                    item.canSuspend = true
                    item.allowEmpty = LockHost.live
                    item.submit.connect(function (pw) { LockHost.unlock(pw) })
                    item.suspend.connect(function () { LockHost.suspend() })
                    item.done.connect(function () { LockHost.unlocked() })
                    item.forceActiveFocus()
                }
            }
            Connections {
                target: LockHost
                enabled: win.main
                function onUnlockAnswer(ok, message) {
                    if (!lock.item) return
                    if (ok) lock.item.succeed(); else lock.item.fail(message)
                }
            }
        }
    }
}
