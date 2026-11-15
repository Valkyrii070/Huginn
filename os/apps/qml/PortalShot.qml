import QtQuick
import QtQuick.Window

// The screen held still, for an app that asked for a picture of it or for a colour on it.
//   Screenshot  drag over the part to share, or take the whole screen; Enter shares, Escape says no.
//   Colour      a magnifier follows the pointer with the colour under it; click to give it to the app.
Window {
    id: win
    visibility: Shot.showing ? Window.FullScreen : Window.Hidden
    flags: Qt.Window | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
    color: "black"
    title: Shot.kind === "colour" ? "Pick a Colour" : "Share a Screenshot"
    readonly property bool colour: Shot.kind === "colour"
    // the part dragged over, in window coordinates (w = 0: nothing yet)
    property real sx: 0; property real sy: 0; property real sw: 0; property real sh: 0
    property bool dragging: false
    property string under: ""
    onVisibleChanged: if (visible) { sw = 0; sh = 0; under = ""; Qt.callLater(function () { win.requestActivate(); keys.forceActiveFocus() }) }
    onClosing: function (close) { Shot.cancel() }

    function share() {
        if (sw > 4 && sh > 4) Shot.share(sx / width, sy / height, sw / width, sh / height)
        else Shot.share(0, 0, 0, 0)
    }

    Image { id: frozen; anchors.fill: parent; source: Shot.image; fillMode: Image.Stretch; smooth: false; cache: false }
    // dim everything but the part chosen
    Item {
        anchors.fill: parent; visible: !win.colour
        readonly property bool any: win.sw > 4 && win.sh > 4
        Rectangle { visible: !parent.any; anchors.fill: parent; color: "#59000000" }
        Rectangle { visible: parent.any; x: 0; y: 0; width: parent.width; height: win.sy; color: "#73000000" }
        Rectangle { visible: parent.any; x: 0; y: win.sy + win.sh; width: parent.width; height: parent.height - win.sy - win.sh; color: "#73000000" }
        Rectangle { visible: parent.any; x: 0; y: win.sy; width: win.sx; height: win.sh; color: "#73000000" }
        Rectangle { visible: parent.any; x: win.sx + win.sw; y: win.sy; width: parent.width - win.sx - win.sw; height: win.sh; color: "#73000000" }
        Rectangle { objectName: "area"; visible: parent.any; x: win.sx - 1; y: win.sy - 1; width: win.sw + 2; height: win.sh + 2; color: "transparent"
            border.width: 2; border.color: Theme.t.accent
            Rectangle { anchors { top: parent.bottom; topMargin: 8; horizontalCenter: parent.horizontalCenter } width: sizeText.width + 16; height: 24; radius: 12
                color: "#CC0C1013"; visible: parent.height > 0
                Text { id: sizeText; anchors.centerIn: parent; color: "white"; font.pixelSize: 11; font.family: Theme.t.font
                    text: Math.round(win.sw / win.width * Shot.imageWidth) + " × " + Math.round(win.sh / win.height * Shot.imageHeight) } } }
    }
    MouseArea {
        id: area
        anchors.fill: parent; hoverEnabled: true
        cursorShape: Qt.CrossCursor
        property real ox: 0; property real oy: 0
        onPressed: function (m) { if (win.colour) return; ox = m.x; oy = m.y; win.dragging = true; win.sx = m.x; win.sy = m.y; win.sw = 0; win.sh = 0 }
        onPositionChanged: function (m) {
            if (win.colour) { win.under = Shot.colourAt(m.x / win.width, m.y / win.height); return }
            if (!win.dragging) return
            win.sx = Math.min(ox, m.x); win.sy = Math.min(oy, m.y); win.sw = Math.abs(m.x - ox); win.sh = Math.abs(m.y - oy)
        }
        onReleased: function (m) { win.dragging = false }
        onClicked: function (m) { if (win.colour) Shot.pick(m.x / win.width, m.y / win.height) }
        onDoubleClicked: function (m) { if (!win.colour) win.share() }
    }
    // the magnifier (colour)
    Item {
        id: loupe
        visible: win.colour && area.containsMouse
        readonly property int zoom: 10
        readonly property real px: frozen.paintedWidth > 0 ? Shot.imageWidth / win.width : 1
        x: Math.min(win.width - width - 8, area.mouseX + 24); y: Math.min(win.height - height - 8, area.mouseY + 24)
        width: 132; height: 164
        Rectangle { anchors.fill: parent; radius: 18; color: "#E60C1013"; border.width: 1; border.color: "#33FFFFFF" }
        Item {
            x: 8; y: 8; width: 116; height: 116; clip: true
            Image { source: Shot.image; smooth: false; cache: true
                width: win.width * loupe.zoom; height: win.height * loupe.zoom
                x: -area.mouseX * loupe.zoom + 58; y: -area.mouseY * loupe.zoom + 58 }
            Rectangle { x: 58 - loupe.zoom / 2; y: 58 - loupe.zoom / 2; width: loupe.zoom; height: loupe.zoom; color: "transparent"; border.width: 1.5; border.color: "white" }
        }
        Row { x: 12; y: 132; spacing: 8
            Rectangle { width: 20; height: 20; radius: 6; color: win.under || "transparent"; border.width: 1; border.color: "#55FFFFFF" }
            Text { text: win.under.toUpperCase(); color: "white"; font.family: Theme.t.fontMono; font.pixelSize: 13; anchors.verticalCenter: parent.verticalCenter } }
    }
    // what to do: an island at the top
    Rectangle {
        objectName: "bar"
        anchors { top: parent.top; topMargin: 24; horizontalCenter: parent.horizontalCenter }
        height: 48; width: bar.width + 28; radius: 24
        color: Theme.t.dark ? Qt.rgba(0.08, 0.10, 0.12, 0.92) : Qt.rgba(0.98, 0.98, 0.99, 0.95)
        border.width: 1; border.color: Theme.t.islandLine
        Row { id: bar; anchors.centerIn: parent; spacing: 10
            Glyph { name: win.colour ? "picker" : "crop"; size: 18; ink: Theme.t.accent; anchors.verticalCenter: parent.verticalCenter }
            Label { anchors.verticalCenter: parent.verticalCenter; font.pixelSize: 13
                text: win.colour ? "Click a colour to give to " + (Shot.app || "the app")
                    : win.sw > 4 && win.sh > 4 ? "Share this part with " + (Shot.app || "the app") + "?"
                    : "Drag over the part to share with " + (Shot.app || "the app") + ", or" }
            Btn { objectName: "whole"; visible: !win.colour && !(win.sw > 4 && win.sh > 4); text: "Whole Screen"; onClicked: { win.sw = 0; win.share() } }
            Btn { objectName: "again"; visible: !win.colour && win.sw > 4 && win.sh > 4; text: "Choose Again"; onClicked: { win.sw = 0; win.sh = 0 } }
            Btn { objectName: "share"; visible: !win.colour && win.sw > 4 && win.sh > 4; primary: true; text: "Share"; onClicked: win.share() }
            Btn { objectName: "cancel"; text: "Cancel"; onClicked: Shot.cancel() }
        }
    }
    Item { id: keys; focus: true
        Keys.onEscapePressed: Shot.cancel()
        Keys.onReturnPressed: if (!win.colour) win.share()
        Keys.onEnterPressed: if (!win.colour) win.share() }
}
