import QtQuick
import QtQuick.Effects

// Frosted glass: the wallpaper behind an island, blurred, in the island's rounded shape. Kept in its own file so the
// sign-in screen still works (with plain tinted glass) where QtQuick.Effects isn't installed or there's no graphics card.
Item {
    id: frost
    property Item behind                     // what's behind the glass (the wallpaper)
    property real radius: 24
    property rect area: Qt.rect(0, 0, width, height)    // where the island is, in the wallpaper's coordinates
    ShaderEffectSource {
        id: src
        anchors.fill: parent
        sourceItem: frost.behind
        sourceRect: frost.area
        live: true
        visible: false
    }
    Rectangle { id: mask; anchors.fill: parent; radius: frost.radius; visible: false; layer.enabled: true }
    MultiEffect {
        anchors.fill: parent
        source: src
        autoPaddingEnabled: false
        blurEnabled: true; blur: 1.0; blurMax: 48; blurMultiplier: 0.6
        saturation: 0.2
        maskEnabled: true; maskSource: mask
    }
}
