import QtQuick
import QtQuick.Window

// One of the session daemon's windows (banners, the level, a question) as an ordinary window: under Huginn's
// compositor, which places it by its title, and in tests. SessionLayer.qml is the same as a layer-shell surface.
Window {
    id: w
    property string role: ""
    property Component body
    property bool takesInput: true
    title: "huginn:" + role
    color: "transparent"
    flags: Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | (w.role === "prompt" ? Qt.Dialog : Qt.Tool) | (w.takesInput ? 0 : Qt.WindowTransparentForInput) | Qt.WindowDoesNotAcceptFocus * (w.role === "prompt" ? 0 : 1)
    Loader { anchors.fill: parent; sourceComponent: w.body }
}
