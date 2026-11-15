import QtQuick
import QtQuick.Window
import org.kde.layershell 1.0 as LayerShell

// One of the session daemon's windows as a layer-shell surface (the KWin session): banners at the top right (below
// the bar, which reserves its space), the level at the bottom, a question in the middle with the keyboard.
Window {
    id: w
    property string role: ""
    property Component body
    property bool takesInput: true
    title: "huginn:" + role
    color: "transparent"
    flags: Qt.FramelessWindowHint | (w.takesInput ? 0 : Qt.WindowTransparentForInput)
    LayerShell.Window.scope: "huginn-" + role
    LayerShell.Window.layer: LayerShell.Window.LayerOverlay
    LayerShell.Window.keyboardInteractivity: role === "prompt" ? LayerShell.Window.KeyboardInteractivityExclusive : LayerShell.Window.KeyboardInteractivityNone
    LayerShell.Window.anchors: role === "banners" ? (LayerShell.Window.AnchorTop | LayerShell.Window.AnchorRight)
                             : role === "osd" ? LayerShell.Window.AnchorBottom : 0
    LayerShell.Window.exclusionZone: 0
    Loader { anchors.fill: parent; sourceComponent: w.body }
}
