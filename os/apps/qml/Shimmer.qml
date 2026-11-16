import QtQuick
import QtQuick.Shapes

// Loading: the shape of what's coming, with the realm's light passing through it. Past `ringAfter` ms the Ring
// joins it (a light running round the edge), for longer waits. Reduce Motion: a still placeholder.
Item {
    id: sh
    property int radius: 10
    property int ringAfter: 2500
    property bool loading: true
    readonly property bool motion: Theme.t.openMs > 0
    Rectangle { anchors.fill: parent; radius: sh.radius; color: Theme.t.dark ? Qt.rgba(1, 1, 1, 0.06) : Qt.rgba(0, 0, 0, 0.05); clip: true
        Rectangle {
            id: light
            visible: sh.motion && sh.loading
            width: parent.width * 0.45; height: parent.height * 2; y: -parent.height / 2; rotation: 18
            gradient: Gradient { orientation: Gradient.Horizontal
                GradientStop { position: 0; color: "transparent" }
                GradientStop { position: 0.5; color: Qt.rgba(Theme.t.glowA.r, Theme.t.glowA.g, Theme.t.glowA.b, 0.22) }
                GradientStop { position: 1; color: "transparent" } }
            NumberAnimation on x { from: -light.width; to: sh.width + light.width; duration: 1400; loops: Animation.Infinite; running: light.visible }
        }
    }
    Timer { id: long; interval: sh.ringAfter; running: sh.loading; onTriggered: ring.visible = sh.motion }
    onLoadingChanged: if (!loading) ring.visible = false
    Shape {
        id: ring
        visible: false; anchors.fill: parent
        readonly property real perimeter: 2 * (width + height)
        property real run: 0
        ShapePath {
            strokeColor: Theme.t.glowA; strokeWidth: 2; fillColor: "transparent"; capStyle: ShapePath.RoundCap
            strokeStyle: ShapePath.DashLine; dashPattern: [ring.perimeter * 0.25 / 2, ring.perimeter * 0.75 / 2]; dashOffset: ring.run
            PathRectangle { x: 1; y: 1; width: ring.width - 2; height: ring.height - 2; radius: sh.radius }
        }
        NumberAnimation on run { from: 0; to: -ring.perimeter / 2; duration: 1100; loops: Animation.Infinite; running: ring.visible }
    }
}
