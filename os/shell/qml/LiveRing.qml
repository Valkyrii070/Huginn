import QtQuick

// A ring that empties as a timer runs down (or fills as something arrives); the time or a glyph in the middle.
Item {
    id: ring
    property real value: 0
    property color tone: Theme.t.accent
    property string text: ""
    property string glyph: ""
    property real thick: Math.max(3, width / 11)
    property real textSize: Math.max(9, width * 0.24)
    onValueChanged: canvas.requestPaint()
    onToneChanged: canvas.requestPaint()
    onWidthChanged: canvas.requestPaint()
    Canvas {
        id: canvas; anchors.fill: parent
        onPaint: {
            var c = getContext("2d"), r = width / 2 - ring.thick / 2 - 1
            if (r <= 0) return
            c.reset(); c.lineWidth = ring.thick; c.lineCap = "round"
            c.strokeStyle = Theme.t.line; c.beginPath(); c.arc(width / 2, height / 2, r, 0, Math.PI * 2); c.stroke()
            if (ring.value > 0) { c.strokeStyle = ring.tone; c.beginPath(); c.arc(width / 2, height / 2, r, -Math.PI / 2, -Math.PI / 2 + Math.PI * 2 * Math.min(1, ring.value)); c.stroke() }
        }
    }
    Label { visible: ring.text !== "" && ring.glyph === ""; anchors.centerIn: parent; text: ring.text; font.pixelSize: ring.textSize; font.weight: Font.Bold }
    Glyph { visible: ring.glyph !== ""; anchors.centerIn: parent; name: ring.glyph; size: ring.width * 0.36; ink: ring.tone }
}
