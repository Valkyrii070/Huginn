import QtQuick
import QtQuick.Effects
import QtQuick.Window

// A translucent surface with a hairline edge. Under KWin, KWin's blur effect supplies the blur behind it. In Huginn's
// own compositor the surface frosts what's behind it itself: the scene's `backdrop` (the wallpaper and the windows),
// or for cards on the desktop just the wallpaper — when a GPU draws the scene (Comp.frost) and transparency is on.
Rectangle {
    id: glass
    property bool popup: false
    property bool wallpaperOnly: false
    readonly property var host: Window.window
    readonly property Item behind: host && host.frostOn === true ? ((wallpaperOnly ? host.wallpaperLayer : host.backdrop) || null) : null
    color: popup ? Theme.t.popup : Theme.t.glass
    radius: Theme.t.radiusTile + 2
    border.width: 1
    border.color: Theme.t.line

    // Where the glass sits over what's behind it. Mapped when it moves or shows; for a moment after (it often slides
    // in, or its parent does), every frame; and every half second while shown, for a parent that moved quietly.
    function follow() {
        if (!behind || !visible) return
        var p = glass.mapToItem(behind, 0, 0)
        var r = Qt.rect(Math.round(p.x), Math.round(p.y), Math.max(1, Math.round(width)), Math.max(1, Math.round(height)))
        frostSrc.sourceRect = r                  // the same rect again changes nothing
    }
    function chase() { if (behind) { follow(); chaser.restart() } }
    onXChanged: chase(); onYChanged: chase(); onWidthChanged: chase(); onHeightChanged: chase()
    onVisibleChanged: chase(); onBehindChanged: chase()
    Component.onCompleted: chase()
    FrameAnimation { id: chaser; running: false; property real spent: 0
        onTriggered: { glass.follow(); spent += frameTime; if (spent > 0.9) { stop(); spent = 0 } } }
    Timer { interval: 500; repeat: true; running: glass.behind !== null && glass.visible; onTriggered: glass.follow() }

    Item {
        z: -1                                     // under the tint and the edge
        anchors.fill: parent
        visible: glass.behind !== null
        ShaderEffectSource {
            id: frostSrc
            anchors.fill: parent; visible: false
            sourceItem: glass.behind; live: true; hideSource: false
            textureSize: Qt.size(Math.max(1, glass.width / 2), Math.max(1, glass.height / 2))   // half size: blurred anyway
        }
        MultiEffect {
            anchors.fill: parent
            source: frostSrc
            autoPaddingEnabled: false
            blurEnabled: true; blur: 1.0; blurMax: 32; blurMultiplier: 0.5
            saturation: 0.3
            maskEnabled: true; maskSource: frostMask
        }
        Item { id: frostMask; anchors.fill: parent; layer.enabled: true; visible: false
            Rectangle { anchors.fill: parent; radius: glass.radius; color: "white" } }
    }
}
